"""The service layer: the one place where the whole graph is wired, and the
one place where the appliance's single inference stream is modelled
honestly.

WHY THIS MODULE EXISTS
-----------------------
Two callers need the same product: the CLI and the HTTP API. If each of
them wired the planner, the resolver, the residency manager and the
orchestrator for itself, they would disagree about which model an image
would be made with, and a fix to one would not reach the other. So the
wiring lives here, once, and both callers drive it through the same eight
methods.

THE APPLIANCE IS ONE STREAM
----------------------------
The Tiiny Pocket Lab serves ONE inference at a time. Its NPU pool is
shared, and the hold file that keeps the watchdog from restoring the
appliance mid-job is global to the device. Two workers generating at once
would fight over the pool and over the hold file, and each would believe
it had the device to itself. So there is ONE worker thread for the whole
application and ONE queue of jobs across every session — not one worker
per session, which is the mistake this module exists to prevent.

A generation takes 54-200 seconds. A caller that waited on it would be
stuck, not waiting, and could not tell a slow generation from a dead one.
So a request is ACCEPTED: a job id comes back immediately, and the work
happens on the worker, which publishes progress to the event bus. The
caller watches the SSE stream for its own session and learns what is
happening instead of staring at a socket.

THE PHASES ARE DECORATED, NOT INSTRUMENTED
-------------------------------------------
The orchestrator resolves, translates, swaps, generates and critiques in
ONE call, because those phases are not separable — the residency check for
the critic has to happen inside the swap. The service still has to tell a
client what is happening, so it wraps the device and the residency manager
in two small decorators that publish events around the calls. The
orchestrator itself is not changed: it has the right shape, and a phase
boundary that existed only to emit an event would be a lie about the work.

THE SCENE IS THE REQUEST, AND NOTHING MORE
------------------------------------------
The scene's subject is the request text itself. That is honest and it is
enough: the dialect translator rewrites the prompt into the target model's
dialect, and the requirement vector carries what the request was really
asking for. A richer scene — a subject separated from its modifiers, a
lighting note, a mood — would come from the planner's LLM call reading the
request more richly, and this module does not invent one it does not have.
The remaining fields are left empty rather than filled with a guess.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, cast

from .assets import Asset, AssetStore
from .config import Settings
from .critic import Critic
from .device import Device, DeviceError, TiinyDevice
from .dialect import DialectTranslator, SceneDescription
from .events import EventBus
from .jobs import Job, JobStore
from .models import ModelChoice, RequirementVector, Resolution
from .orchestrator import GenerationResult, Orchestrator
from .planner import Planner
from .registry import ModelSpec, Registry
from .residency import MAX_EXECUTABLE_OCCUPANCY_PCT
from .roles import Roles
from .residency import APPLIANCE_MODEL_NPU_PCT, HoldFile, ResidencyManager
from .resolver import Resolver, ResolverError

#: How long close() waits for the worker to notice the sentinel and stop.
#: Short on purpose: a generation can take three minutes, and a shutdown
#: that waits for one is a shutdown the user cannot interrupt.
CLOSE_TIMEOUT = 5.0

#: The name of the one worker thread, so it can be found in a stack dump
#: and recognised in a test.
WORKER_NAME = "tis-worker"

#: How often a download is polled, and how long it may take. The
#: measured download of a 10.6 GiB model took about five minutes.
DOWNLOAD_POLL_SECONDS = 2.0
DOWNLOAD_TIMEOUT_SECONDS = 3600.0

#: The headroom a download needs beyond the model's own size. The
#: appliance unpacks while it downloads, and a download that fills the
#: disk to the last byte takes the appliance down with it.
DOWNLOAD_HEADROOM = 1.25


class InsufficientStorageError(RuntimeError):
    """Raised when the appliance cannot hold the model a request needs."""


class UnknownAssetError(LookupError):
    """The asset id does not name an asset."""


class _Session:
    """The session the worker is serving right now.

    The device and residency decorators publish to a session, but the
    orchestrator does not know which one — it is not its business. The
    worker sets the session before each job, and there is only one worker,
    so a plain attribute is enough.
    """

    def __init__(self) -> None:
        self._session_id = "default"

    def get(self) -> str:
        return self._session_id

    def set(self, session_id: str) -> None:
        self._session_id = session_id


class _ObservedDevice:
    """The device, with the phases of a generation made visible.

    The orchestrator works in one call, so the only place the service can
    see a generation begin is around the device call itself. Everything the
    protocol asks for is forwarded; everything the protocol does not yet
    ask for is forwarded too, by ``__getattr__``, so the wrapper does not
    become the place where the protocol has to be taught about a new call.
    """

    def __init__(self, device: Device, events: EventBus,
                 session: Callable[[], str]):
        self._device = device
        self._events = events
        self._session = session

    def chat(self, model: str, prompt: str, **kw) -> dict:
        response = self._device.chat(model, prompt, **kw)
        # After the call, not before: a chat that raised produced no
        # critique, and an event claiming otherwise would be a lie. Only
        # the judge talks through this wrapper — the planner talks to the
        # raw device — so a "judge.called" event really is a judge.
        #
        # This event says the judge was CALLED and carries the prompt it
        # was given. It does not carry the verdict, because at this level
        # there is no verdict yet — only a reply to be parsed. The
        # orchestrator publishes "critique.ready" with the parsed
        # verdict, which is the event a client should act on.
        self._events.publish("judge.called", self._session(),
                             {"model": model, "prompt": prompt})
        return response

    def vision(self, model: str, question: str, image: bytes) -> str:
        """Ask a model about an image, and say so when it has answered.

        The same event as chat(), for the same reason: a judge that can
        SEE the image is still a judge, and the fact that it was called
        is worth an event.
        """
        answer = self._device.vision(model, question, image)
        self._events.publish("judge.called", self._session(),
                             {"model": model, "prompt": question,
                              "vision": True})
        return answer

    def generate(self, model: str, prompt: str, size: str) -> bytes:
        session = self._session()
        self._events.publish("generate.started", session,
                             {"model": model, "prompt": prompt, "size": size})
        try:
            return self._device.generate(model, prompt, size)
        finally:
            # Published even when the generation failed: the attempt
            # finished either way, and a client waiting on the stream
            # must not be left believing the appliance is still working.
            self._events.publish("generate.finished", session,
                                 {"model": model, "size": size})

    def resident(self) -> list[str]:
        return self._device.resident()

    def load(self, model: str) -> None:
        self._device.load(model)

    def unload(self, model: str) -> None:
        self._device.unload(model)

    def __getattr__(self, name: str) -> Any:
        # __dict__ rather than self._device, so a lookup that happens
        # before __init__ finished raises AttributeError rather than
        # recursing into itself.
        device = self.__dict__.get("_device")
        if device is None:
            raise AttributeError(name)
        return getattr(device, name)


class _ObservedResidency:
    """The residency manager, with the swap made visible.

    A swap is the part of a generation a client waits longest for and
    understands least, so it gets its own pair of events. The swap itself
    is not touched: the manager's ordering — hold first, lock second,
    load third, restore in a finally — is what keeps the watchdog from
    evicting a model in the middle of a generation.
    """

    def __init__(self, residency: ResidencyManager, events: EventBus,
                 session: Callable[[], str]):
        self._residency = residency
        self._events = events
        self._session = session

    @contextmanager
    def swap_to(self, model_id: str, *also_resident: str) -> Iterator[None]:
        session = self._session()
        self._events.publish("swap.started", session,
                             {"model": model_id,
                              "also_resident": list(also_resident)})
        try:
            with self._residency.swap_to(model_id, *also_resident):
                yield
        finally:
            self._events.publish("swap.finished", session, {"model": model_id})

    def __getattr__(self, name: str) -> Any:
        residency = self.__dict__.get("_residency")
        if residency is None:
            raise AttributeError(name)
        return getattr(residency, name)


@dataclass
class _Work:
    """One unit of work on the one queue."""

    job_id: str
    session_id: str
    kind: str
    request: str
    width: int
    height: int
    asset_id: str = ""
    feedback: str = ""
    #: The model the user asked for, if any. Empty means "the resolver
    #: chooses". A model the user chose is honoured when it can do the
    #: job, and the resolver says so when it cannot.
    model_id: str = ""


class Agency:
    """The wired application: plan, generate, iterate, and the answers.

    Everything is injected, so a test can hand it a FakeDevice and a
    temporary directory and exercise the whole graph without an appliance
    and without touching the network. Building the Agency is cheap and
    offline; the worker thread does not exist until the first job is
    accepted.
    """

    def __init__(self, settings: Settings,
                 device: Device | None = None,
                 registry: Registry | None = None,
                 jobs: JobStore | None = None,
                 assets: AssetStore | None = None,
                 events: EventBus | None = None):
        self.settings = settings
        self.registry = (registry if registry is not None
                         else Registry.load(settings.registry_path))
        self.device = device if device is not None else TiinyDevice(settings)
        # The job store lives beside the hold file: both are the app's
        # state about the appliance, and they are read and written
        # together.
        self.jobs = (jobs if jobs is not None
                     else JobStore(settings.hold_file.parent / "jobs.db"))
        self.assets = assets if assets is not None else AssetStore(settings.assets_dir)
        self.events = events if events is not None else EventBus()

        self.resolver = Resolver(self.registry)
        self.translator = DialectTranslator(self.registry)
        # The conversational catalogue: the models that can hold either
        # role. It is what lets a user CHOOSE a critic that can see the
        # image, and it is what tells them which ones can.
        self.roles = Roles.load(settings.roles_path)
        # The planner talks to the RAW device. Its chat() is a planning
        # call, not a critique, and publishing "critique.ready" for it
        # would tell a client a judge had spoken when none had.
        self.planner = Planner(self.device, settings.planner_model, self.registry)

        self._session = _Session()
        observed = _ObservedDevice(self.device, self.events, self._session.get)
        # The critic judges THROUGH the observed device, because its
        # chat() is the critique, and the client has to be told about it.
        self._observed = observed
        self.critic = self._build_critic(self._judge_model_id(settings))
        self.residency = ResidencyManager(
            self.device, self.registry, HoldFile(settings.hold_file),
            settings.watchdog_lock, roles=self.roles)
        self.orchestrator = Orchestrator(
            observed, self.registry, self.resolver, self.translator,
            self.critic,
            # The orchestrator asks a residency manager for one thing: a
            # swap_to context manager. The decorator provides it, and the
            # cast says so in the type the orchestrator was written
            # against without pretending the wrapper IS the manager.
            cast(ResidencyManager,
                 _ObservedResidency(self.residency, self.events,
                                    self._session.get)),
            # The orchestrator publishes the judge's VERDICT. Without this
            # the event stream carries the prompt the judge was given and
            # nothing about what it concluded, and a surface can only say
            # "the judge compared the image against the requirements" -
            # which is true whether the judge passed, failed, or was
            # never called.
            events=self.events, session=self._session.get)

        self._queue: queue.Queue[_Work | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._closed = False

    # -- the public surface ------------------------------------------------

    # -- the roles: who talks, and who judges ------------------------------

    def _judge_model_id(self, settings) -> str:
        """Which model judges.

        The judge is the conversation agent unless the user has chosen
        otherwise. The two roles were one model because a blind judge
        and the model that wrote the prompt had nothing to tell each
        other; a judge that can SEE the image is a different model, and
        a different one may be wanted.
        """
        return settings.judge_model or settings.planner_model

    def _build_critic(self, model_id: str) -> Critic:
        """A critic for a model, with its vision capability resolved.

        The catalogue says whether the model can accept an image as
        well as text. A model that is not in the catalogue is treated
        as blind, because the safe assumption about an unknown model is
        the one that cannot fail by claiming to see something.
        """
        spec = self.roles.get(model_id)
        vision = bool(spec and spec.vision)
        # The wrapper forwards everything the protocol asks for, and
        # everything it does not, through __getattr__ - so it satisfies
        # the protocol at runtime. The cast says so in the type the
        # critic was written against, without pretending the wrapper IS
        # the device.
        return Critic(cast(Device, self._observed), model_id, vision=vision)

    def role_options(self) -> dict:
        """The guide: every model that can hold either role.

        Each entry says whether the model can SEE an image, what it
        costs in NPU, how much context it has, and whether it is on the
        device right now. The `vision` flag is the one that decides
        whether a critic can judge the picture or only the prompt.

        The `fit` section is the part that makes the guide GUIDE rather
        than list. A judge that can see costs more of the pool, and the
        pool is finite: the talker, the judge and a generator have to
        fit in it at once, or one of them has to be swapped out and
        back between stages. So the guide says whether the CURRENT
        choice fits, and what to change if it does not.
        """
        models = [m.as_dict() for m in self.roles.all()]
        return {
            "conversation": {
                "model": self.planner.model_id,
                "npu_usage": self._npu_of(self.planner.model_id),
            },
            "critic": {
                "model": self.critic.model_id,
                "vision": self.critic.vision,
                "npu_usage": self._npu_of(self.critic.model_id),
            },
            "models": models,
            "vision_models": [m.as_dict() for m in self.roles.vision_models()],
            "fit": self._fit(),
        }

    def _fit(self) -> dict:
        """Can the judge and a generator be resident at the same time?

        Measured on this appliance: the pool is 47.9 GiB and the
        percentages are the device's own. The generator is the one the
        resolver would pick for an ordinary request, because that is
        the one the fit has to hold for.

        THE TALKER IS NOT IN THIS SUM, AND THAT IS THE POINT.
        The conversation agent writes the scene description BEFORE the
        generation starts. By the time the image is being made, its
        weights have been swapped out and the judge and the generator
        have the pool to themselves. So a judge that can SEE the image
        is affordable even when it is much bigger than the talker -
        47% judge + 23% generator is 70%, and the measured ceiling for
        a generation that actually runs is 81%.

        The ceiling is the EXECUTION ceiling, not the admission one.
        The appliance accepted 85% and failed the diffusion pass with
        HTTP 500. So "it fits in the pool" is not the question either;
        "can it RUN" is.

        The talker still has to be DOWNLOADED, because it is swapped
        back in afterwards.
        """
        from .models import RequirementVector

        resolution = self.resolver.resolve(RequirementVector())
        generator = resolution.chosen
        talker_model = self.planner.model_id
        judge_model = self.critic.model_id
        talker = self._npu_of(talker_model)
        judge = self._npu_of(judge_model)

        # What has to be resident WHILE the image is being judged.
        during = judge + generator.npu_usage
        fits = during <= MAX_EXECUTABLE_OCCUPANCY_PCT
        talker_ready = bool(self.roles.get(talker_model) and
                            self.roles.require(talker_model).downloaded)

        if fits:
            advice = (
                f"It fits: {judge_model} judges at {judge}% while "
                f"{generator.id} generates at {generator.npu_usage}% - "
                f"{during}% of the pool, under the {MAX_EXECUTABLE_OCCUPANCY_PCT}% "
                f"ceiling a generation needs to actually run."
            )
            if talker_model != judge_model:
                advice += (
                    f" {talker_model} is swapped out while the image is made "
                    f"and swapped back in to judge it, so its {talker}% does "
                    f"not compete for the pool."
                )
        else:
            options = []
            for model in sorted(self.roles.all(), key=lambda m: m.npu_usage):
                if not model.downloaded or model.id == judge_model:
                    continue
                new_total = model.npu_usage + generator.npu_usage
                if new_total <= MAX_EXECUTABLE_OCCUPANCY_PCT:
                    options.append((model, new_total))
            if options:
                pick, new_total = options[0]
                advice = (
                    f"It does not fit: {judge_model} judges at {judge}% and "
                    f"{generator.id} generates at {generator.npu_usage}% - "
                    f"{during}%, over the {MAX_EXECUTABLE_OCCUPANCY_PCT}% "
                    f"ceiling. The device accepts a set like that and then "
                    f"fails the generation. A smaller judge would work: "
                    f"{pick.id} would give {new_total}%."
                )
            else:
                advice = (
                    f"It does not fit: {judge_model} judges at {judge}% and "
                    f"{generator.id} generates at {generator.npu_usage}% - "
                    f"{during}%, over the {MAX_EXECUTABLE_OCCUPANCY_PCT}% "
                    f"ceiling, and no model on the device makes room beside "
                    f"the generator."
                )
        return {
            "generator": generator.id,
            "generator_npu": generator.npu_usage,
            "conversation_npu": talker,
            "critic_npu": judge,
            "shared_model": talker_model == judge_model,
            "during_judging": during,
            "ceiling": MAX_EXECUTABLE_OCCUPANCY_PCT,
            "total": during,
            "fits": fits,
            "talker_downloaded": talker_ready,
            "advice": advice,
        }

    def _npu_of(self, model_id: str) -> int:
        spec = self.roles.get(model_id)
        return spec.npu_usage if spec else 0

    def set_roles(self, conversation: str | None = None,
                  critic: str | None = None) -> dict:
        """Choose who talks and who judges.

        This is the ENABLING half: the guide tells a user which models
        can see an image, and this is how they choose one.

        The conversation agent is the planner; the critic is the judge.
        A model that is not in the conversational catalogue is refused:
        the guide would not have shown it, and a role held by a model
        nobody knows anything about is how the first live run went
        wrong.

        A judge that cannot see the image is allowed, and the answer
        says so plainly - some users want a prompt critic, which is
        cheaper and never invents a visual defect.
        """
        if conversation:
            self.roles.require(conversation)
            self.planner = Planner(self.device, conversation, self.registry)
        if critic:
            self.roles.require(critic)
            self.critic = self._build_critic(critic)
            # The orchestrator was handed the critic when it was built,
            # so replacing the agency's copy is not enough - the
            # orchestrator has to be given the new one too, or the
            # choice would change the guide and not the judging.
            self.orchestrator.critic = self.critic

        result = self.role_options()
        result["changed"] = {
            "conversation": conversation or self.planner.model_id,
            "critic": self.critic.model_id,
        }
        # The residency warning is the honest part. A judge that cannot
        # be loaded beside the generator will never run, and a user who
        # has just chosen it deserves to know that before they wait for
        # a picture.
        fit = self._fit()
        judge = self.roles.get(self.critic.model_id)
        if judge and judge.vision:
            result["note"] = (
                f"{judge.id} can SEE the image. {fit['advice']}"
            )
        elif critic:
            result["note"] = (
                f"{self.critic.model_id} reads text only, so the critic "
                f"judges the PROMPT and cannot see the image. "
                f"{fit['advice']}"
            )
        result["fit"] = fit
        return result

    def plan(self, request: str, width: int = 1024, height: int = 1024,
             session_id: str = "default", model_id: str = "") -> dict:
        """Plan a request without generating anything.

        A plan is a read: it does not touch the appliance beyond the
        planner's own call, and it publishes no events — the event stream
        is the story of a generation, and this is not one. The session is
        accepted so that every entry point looks the same to a caller.

        ``model_id`` is a model the user chose. It is honoured when it can
        do the job, and the plan says so when it cannot.
        """
        plan = self.planner.plan(request, width, height)
        self._refresh_status()
        try:
            resolution = self.resolver.resolve(plan.requirements,
                                               preferred=model_id or None)
        except ResolverError as exc:
            model = self.resolver.best_unavailable(plan.requirements)
            if model is None:
                raise exc
            return self._plan_needing_a_download(plan, model)
        return {
            "plan_id": _new_plan_id(),
            "requirements": plan.requirements.model_dump(mode="json"),
            "model": _choice(resolution.chosen),
            "justification": resolution.justification,
            "alternatives": [_choice(a) for a in resolution.alternatives],
            "unavailable": [_choice(m) for m in resolution.unavailable],
            "swap_required": resolution.swap_required,
            "swap_plan": dict(resolution.swap_plan),
            "planner_source": plan.source,
            "download": None,
        }

    def _plan_needing_a_download(self, plan: Any, model: ModelSpec) -> dict:
        """The plan for a request that needs a model the appliance does
        not have.

        A PLAN downloads nothing — a plan is a read, and downloading is
        a write to a shared appliance. But the answer is not a refusal
        either: it is the model that would do the job, how much disk it
        needs, and the fact that the generation will fetch it first.
        """
        size = model.size_bytes
        return {
            "plan_id": _new_plan_id(),
            "requirements": plan.requirements.model_dump(mode="json"),
            "model": {
                "id": model.id,
                "role": model.role,
                "npu_usage": model.npu_usage,
                "co_resident_with_planner": model.co_resident_with_planner,
                "downloaded": False,
            },
            "justification": (
                f"{model.id} would satisfy this request, but it is not "
                f"downloaded on this appliance. The generation will download "
                f"it first — {size / 1024 ** 3:.1f} GiB — and then use it."
            ),
            "alternatives": [],
            "unavailable": [],
            "swap_required": True,
            "swap_plan": {"load": [model.id], "evict": [], "keep": []},
            "planner_source": plan.source,
            "download": {"model": model.id, "size_bytes": size},
        }

    def generate(self, request: str, session_id: str = "default",
                 width: int = 1024, height: int = 1024,
                 model_id: str = "") -> str:
        """Accept a generation and return its job id, immediately.

        The appliance needs a minute and sometimes three. A caller that
        waited on it would be stuck, not waiting, so the work is handed to
        the one worker and the id comes back now.

        ``model_id`` is a model the user chose, or empty to let the
        resolver decide.
        """
        job = self.jobs.create(session_id, "generate", request)
        self.events.publish("job.queued", session_id,
                            {"job_id": job.id, "kind": "generate"})
        self._enqueue(_Work(job_id=job.id, session_id=session_id,
                            kind="generate", request=request,
                            width=width, height=height, model_id=model_id))
        return job.id

    def iterate(self, asset_id: str, feedback: str,
                session_id: str = "default") -> str:
        """Accept an iteration of an existing asset and return its job id.

        The asset is looked up by the WORKER, not here: this call must
        not block, and whether the asset exists is the worker's finding
        to report — as a failed job that names the id, not as an
        exception thrown at a caller that has already been given a job.
        """
        job = self.jobs.create(session_id, "iterate", feedback,
                               payload={"asset_id": asset_id,
                                        "feedback": feedback})
        self.events.publish("job.queued", session_id,
                            {"job_id": job.id, "kind": "iterate"})
        self._enqueue(_Work(job_id=job.id, session_id=session_id,
                            kind="iterate", request=feedback,
                            width=1024, height=1024,
                            asset_id=asset_id, feedback=feedback))
        return job.id

    def get_job(self, job_id: str) -> Job | None:
        """The job with this id, or None if there is no such job."""
        return self.jobs.get(job_id)

    def get_asset(self, asset_id: str) -> Asset | None:
        """The asset with this id, or None if there is no such asset."""
        return self.assets.get(asset_id)

    def model_card(self, model_id: str) -> dict | None:
        """The research card for a model, if it has one.

        The card is written by the research loop, which MEASURES the
        model on the appliance — because the device's own description of
        a model cannot be trusted. It is the summary the user is shown,
        and every field in it has an evidence entry behind it.
        """
        # The model id contains slashes, so it cannot be used as a path
        # as it stands.
        name = model_id.replace("/", "__")
        path = self.settings.cards_dir / f"{name}.card.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def npu(self) -> dict:
        """What the NPU pool is doing right now.

        The device reports which models are resident; the costs come from
        the registry and from the measured table the appliance's own
        models live in, because the device does not price them itself.
        """
        try:
            resident = list(self.device.resident())
        except Exception:
            # A device that is off is an answer, not an exception: this
            # is asked on every page load.
            return {"resident": [], "used_pct": 0, "models": [],
                    "reachable": False}
        models = [{"id": model_id, "npu_usage": self._cost(model_id)}
                  for model_id in resident]
        return {
            "resident": resident,
            "used_pct": sum(entry["npu_usage"] for entry in models),
            "models": models,
            "reachable": True,
        }

    def health(self) -> dict:
        """Whether the app is alive, the device is reachable, the registry
        is loaded.

        The device check must not raise: a health endpoint that throws
        when the appliance is off reports the outage by crashing, which
        is the one thing a health endpoint must not do.
        """
        try:
            self.device.resident()
            reachable = True
        except Exception:
            reachable = False
        return {
            "alive": True,
            "device_reachable": reachable,
            "registry_loaded": bool(self.registry.models),
            "model_count": len(self.registry.models),
        }

    def close(self) -> None:
        """Stop the worker and close the job store.

        Safe to call twice, and safe to call when no job was ever
        accepted: there is no worker to stop, and the store closes
        cleanly.
        """
        with self._worker_lock:
            worker = self._worker
            if not self._closed:
                self._closed = True
                if worker is not None:
                    self._queue.put(None)
        if worker is not None:
            worker.join(timeout=CLOSE_TIMEOUT)
        self.jobs.close()

    # -- the one worker ----------------------------------------------------

    def _enqueue(self, work: _Work) -> None:
        """Put a job on the one queue, waking the worker if it is asleep."""
        self._ensure_worker()
        self._queue.put(work)

    def _ensure_worker(self) -> None:
        """Start the one worker, if it is not already running."""
        with self._worker_lock:
            if self._closed:
                raise RuntimeError("the agency is closed")
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run_worker, name=WORKER_NAME, daemon=True)
            self._worker.start()

    def _run_worker(self) -> None:
        """The one worker: one queue, every session, in acceptance order."""
        while True:
            work = self._queue.get()
            try:
                if work is None:
                    return
                self._run_job(work)
            except Exception:
                # The worker is the only thing that can serve the next
                # caller, so it must never die because one job did.
                pass
            finally:
                self._queue.task_done()

    def _run_job(self, work: _Work) -> None:
        """Run one job, and record how it ended."""
        self._session.set(work.session_id)
        self._update_job(work.job_id, status="running")
        self.events.publish("job.started", work.session_id,
                            {"job_id": work.job_id})
        try:
            if work.kind == "iterate":
                self._iterate(work)
            else:
                self._generate(work)
        except Exception as exc:
            self._fail(work, exc)

    def _fail(self, work: _Work, exc: BaseException) -> None:
        """Record a failed job and tell the session."""
        message = str(exc) or exc.__class__.__name__
        self._update_job(work.job_id, status="failed", error=message)
        self.events.publish("job.failed", work.session_id,
                            {"job_id": work.job_id, "error": message})

    def _update_job(self, job_id: str, **changes) -> None:
        """Change a job, tolerating a store that has been closed.

        close() may close the store while a long generation is still
        running; the worker's own failure must not become a crash.
        """
        try:
            self.jobs.update(job_id, **changes)
        except Exception:
            pass

    # -- the two kinds of job ----------------------------------------------

    def _generate(self, work: _Work) -> None:
        """Plan, resolve, generate, deliver."""
        plan = self.planner.plan(work.request, work.width, work.height)
        self._resolve(work, plan.requirements, plan.source)
        scene = SceneDescription(subject=work.request)
        result = self.orchestrator.generate(plan.requirements, scene,
                                             preferred=work.model_id or None)
        self._deliver(work, result, plan.requirements, plan.source,
                      work.request, scene.modifiers)

    def _iterate(self, work: _Work) -> None:
        """Take the old image's requirements, add the feedback, generate.

        The subject is the ORIGINAL REQUEST, never the previous prompt.
        The prompt is what the dialect translator produced, and the
        translator's job is to rewrite an intent into a model's dialect -
        feeding it an already-dialected prompt would apply the dialect to
        itself, and every iteration would compound. The feedback
        accumulates as modifiers instead, so the second revision is the
        first request plus both pieces of advice, and not the first
        prompt plus the second.
        """
        asset = self.assets.get(work.asset_id)
        if asset is None:
            raise UnknownAssetError(
                f"there is no asset {work.asset_id!r} to iterate on")
        lineage = asset.lineage or {}
        requirements = RequirementVector.model_validate(
            lineage.get("requirements") or {})
        source = str(lineage.get("planner_source") or "fallback")
        request = str(lineage.get("request") or work.feedback)
        subject = request
        previous = tuple(str(m) for m in (lineage.get("modifiers") or ()))
        # The feedback goes in as a MODIFIER, so it reaches the prompt the
        # dialect translator writes rather than sitting beside it.
        scene = SceneDescription(subject=subject,
                                 modifiers=previous + (work.feedback,))
        self._resolve(work, requirements, source)
        result = self.orchestrator.generate(requirements, scene)
        self._deliver(work, result, requirements, source, request,
                      scene.modifiers)

    # --- getting the model onto the appliance ------------------------------

    def _refresh_status(self) -> None:
        """Refresh the registry's downloaded flags from the appliance.

        The registry records the device's store as it was when the
        registry was generated. A model downloaded since then would still
        look unavailable, and the resolver would refuse a job it could
        do. The catalogue is 270 KB, which is nothing beside a
        generation.
        """
        try:
            catalogue = self.device.catalogue()
        except Exception:
            # A device that will not answer is a device that cannot be
            # downloaded from. The registry's snapshot still stands.
            return
        self.registry.refresh_status(catalogue)

    def _ensure_available(self, work: _Work | None,
                          requirements: RequirementVector) -> Resolution:
        """Resolve, downloading a model first if that is what the request
        needs.

        The resolver only ever chooses models that are ON the appliance.
        When nothing downloaded can do the job, the answer is not "no" —
        it is "download the model that can, if the disk has room".
        """
        self._refresh_status()
        try:
            return self.resolver.resolve(requirements)
        except ResolverError:
            model = self.resolver.best_unavailable(requirements)
            if model is None:
                raise
            if work is None:
                raise
        self._download(work, model)
        self._refresh_status()
        return self.resolver.resolve(requirements)

    def _download(self, work: _Work, model: ModelSpec) -> None:
        """Put the model on the appliance's disk, and say so as it goes.

        The download takes minutes, so the session is told what is
        happening throughout. A caller watching the stream sees the
        progress rather than a silence.
        """
        size = model.size_bytes
        free = int(self.device.storage().get("remaining_bytes") or 0)
        needed = int(size * DOWNLOAD_HEADROOM)
        if size and free < needed:
            raise InsufficientStorageError(
                f"{model.id} needs {size / 1024 ** 3:.1f} GiB and the "
                f"appliance has {free / 1024 ** 3:.1f} GiB free")

        self.events.publish("download.started", work.session_id, {
            "job_id": work.job_id,
            "model": model.id,
            "size_bytes": size,
        })
        self.device.download(model.id)

        deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
        while True:
            status, progress = self._download_status(model.id)
            if status == "downloaded":
                break
            if status not in ("downloading", "running"):
                raise DeviceError(
                    f"the download of {model.id} stopped with status "
                    f"'{status or 'unknown'}'")
            self.events.publish("download.progress", work.session_id, {
                "job_id": work.job_id,
                "model": model.id,
                "progress": progress,
            })
            if time.monotonic() > deadline:
                raise DeviceError(
                    f"the download of {model.id} did not finish in time")
            time.sleep(DOWNLOAD_POLL_SECONDS)

        self.events.publish("download.finished", work.session_id, {
            "job_id": work.job_id,
            "model": model.id,
            "size_bytes": size,
        })

    def _download_status(self, model_id: str) -> tuple[str, float]:
        """The model's live status and progress, from the catalogue."""
        for row in self.device.catalogue():
            if str(row.get("fullname") or "") == model_id:
                return (str(row.get("status") or ""),
                        float(row.get("progress") or 0.0))
        return ("", 0.0)

    def _resolve(self, work: _Work, requirements: RequirementVector,
                 source: str) -> None:
        """Resolve the requirements and publish the plan.

        The orchestrator resolves again internally. That is safe because
        the resolver is PURE and deterministic, and because there is
        exactly one worker, so nothing can change the resident set
        between the two resolves — they must agree. Neither call is given
        a live resident set for the same reason.

        This is also where a model the appliance does not have yet gets
        downloaded: the resolver only chooses what is on the disk, so
        without this a request that needs something new would be refused.
        """
        resolution = self._ensure_available(work, requirements)
        self.events.publish("plan.ready", work.session_id, {
            "job_id": work.job_id,
            "model": resolution.chosen.id,
            "justification": resolution.justification,
            "planner_source": source,
        })

    def _deliver(self, work: _Work, result: GenerationResult,
                 requirements: RequirementVector, source: str,
                 request: str, modifiers: tuple[str, ...] = ()) -> None:
        """Write the asset, record the job, and tell the session.

        The modifiers are kept in the lineage so that a second iteration
        can add to them. The prompt is NOT the base for the next
        iteration - it is the dialect applied once, and applying it twice
        would compound.
        """
        lineage = {
            "requirements": requirements.model_dump(mode="json"),
            "model_id": result.model_id,
            "prompt": result.prompt,
            "size": result.size,
            "attempts": result.attempts,
            "critique": (result.critique.model_dump(mode="json")
                         if result.critique is not None else None),
            "critique_skipped_reason": result.critique_skipped_reason,
            "planner_source": source,
            "request": request,
            "modifiers": list(modifiers),
            "session_id": work.session_id,
            "job_id": work.job_id,
            "created_at": time.time(),
        }
        asset = self.assets.save(result.image, lineage)
        self._update_job(work.job_id, status="succeeded",
                         payload={"asset_id": asset.id})
        self.events.publish("asset.ready", work.session_id,
                            {"job_id": work.job_id, "asset_id": asset.id})
        self.events.publish("job.finished", work.session_id,
                            {"job_id": work.job_id, "asset_id": asset.id})

    # -- the facts about the pool ------------------------------------------

    def _cost(self, model_id: str) -> int:
        """What a resident model costs the NPU pool, in percent."""
        if self.registry.planner.id == model_id:
            return self.registry.planner.npu_usage
        model = self.registry.find(model_id)
        if model is not None:
            return model.npu_usage
        # The appliance's own models — the generalist, the ASR and TTS
        # models, the voice — are not in the registry, because the
        # registry is the IMAGE catalogue. Their measured cost is a fact
        # about the device, and it lives with the other device facts.
        return APPLIANCE_MODEL_NPU_PCT.get(model_id, 0)


def _new_plan_id() -> str:
    """A plan id: the prefix and sixteen hex characters of a uuid4."""
    return f"plan_{uuid.uuid4().hex[:16]}"


def _choice(choice: ModelChoice) -> dict:
    """A model choice in the shape the plan document uses."""
    return {
        "id": choice.id,
        "role": choice.role,
        "npu_usage": choice.npu_usage,
        "co_resident_with_planner": choice.co_resident_with_planner,
        # Whether the appliance can actually load it. A model that is not
        # downloaded can be named, but never chosen.
        "downloaded": choice.downloaded,
    }
