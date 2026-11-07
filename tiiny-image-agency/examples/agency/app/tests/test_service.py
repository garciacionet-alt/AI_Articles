"""Tests for the service layer: the wiring, the job runner, and the events.

The service is the one place where the whole graph is wired, so most of
what it does is integration: a FakeDevice with the REAL planner, resolver,
residency manager, dialect translator, asset store, job store and event bus
behind it. The only thing faked is the appliance, because the appliance
takes a minute and the suite has to finish.

Two things are faked that the appliance does not do but the test needs:
a generation that WAITS (so "generate() returns before the job is done"
is a fact and not a race), and a generation that FAILS (so the worker's
survival can be seen).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

import pytest

from fake_device import FakeDevice, png_bytes
from tis.assets import AssetStore
from tis.config import Settings
from tis.device import Device, DeviceError
from tis.events import EventBus
from tis.jobs import Job
from tis.registry import Registry
from tis.service import Agency, WORKER_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

#: The bearer the settings carry. It must never reach a response, a
#: lineage, an event or a job payload.
BEARER = "sk-tis-test-bearer-8f21c0"

PASS = "VERDICT: pass\nREASON: it satisfies the requirements"

#: A reply the planner can read as a requirement vector.
PLANNER_JSON = json.dumps({
    "artifact": "illustration",
    "alpha": "no",
    "text_in_image": "no",
    "style": "general",
    "speed": "normal",
    "hard": [],
    "width": 1024,
    "height": 1024,
})


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key=BEARER,
        registry_path=REGISTRY_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
    )


def _agency(tmp_path: Path, registry: Registry, device=None,
            replies=None) -> Agency:
    """An Agency with a fake appliance and a temporary home.

    The job store, the asset store and the event bus are the Agency's own
    defaults, built from the settings — which is how the real paths are
    exercised rather than mocked away.
    """
    if device is None:
        device = FakeDevice(registry, replies=replies or {})
    return Agency(_settings(tmp_path), device=device, registry=registry)


def _wait(agency: Agency, job_id: str, timeout: float = 10.0) -> Job:
    """Wait for a job to reach a final state, and return it."""
    deadline = time.monotonic() + timeout
    while True:
        job = agency.get_job(job_id)
        if job is not None and job.status in ("succeeded", "failed"):
            return job
        if time.monotonic() > deadline:
            status = job.status if job is not None else None
            raise AssertionError(
                f"job {job_id} did not finish; its status is {status!r}")
        time.sleep(0.01)


def _drain(events, timeout: float = 0.5) -> list:
    """Every event waiting on a subscriber's queue."""
    collected = []
    while True:
        try:
            collected.append(events.get(timeout=timeout))
        except queue.Empty:
            return collected


def _types(events) -> list[str]:
    return [event.type for event in events]


class _BlockingDevice(FakeDevice):
    """An appliance that takes as long as the real one does.

    The real appliance needs 54-200 seconds for one image. A fake that
    returns instantly cannot show that ``generate()`` hands back a job id
    before the work is done, because the work would be done.
    """

    def __init__(self, registry, **kwargs):
        super().__init__(registry, **kwargs)
        self.gate = threading.Event()

    def generate(self, model: str, prompt: str, size: str) -> bytes:
        self.gate.wait(timeout=10.0)
        return super().generate(model, prompt, size)


class _FlakyDevice(FakeDevice):
    """An appliance whose generation fails, the way the appliance fails."""

    def __init__(self, registry, failures: int = 1, **kwargs):
        super().__init__(registry, **kwargs)
        self.failures = failures

    def generate(self, model: str, prompt: str, size: str) -> bytes:
        if self.failures > 0:
            self.failures -= 1
            self.calls.append(("generate", model, size))
            raise DeviceError(
                "The operation failed to complete.",
                retryable=True, status=500, code=150004)
        return super().generate(model, prompt, size)


class _DeadDevice(FakeDevice):
    """An appliance that is switched off."""

    def resident(self) -> list[str]:
        raise DeviceError(
            "device call to /models failed: connection refused", retryable=True)


# -- the wiring -------------------------------------------------------------


def test_the_agency_builds_without_touching_the_device(registry, tmp_path):
    device = FakeDevice(registry)
    agency = Agency(_settings(tmp_path), device=device, registry=registry)
    try:
        assert device.calls == []
        assert agency.registry is registry
        assert agency.device is device
        assert agency.jobs.path == tmp_path / "jobs.db"
        assert agency.assets.root == tmp_path / "assets"
        assert agency.events is not None
        assert agency.resolver.registry is registry
        assert agency.translator.registry is registry
        assert agency.planner.device is device
        assert agency.residency.registry is registry
        assert agency.orchestrator.registry is registry
        # The worker sleeps until the first job is accepted.
        assert not any(t.name == WORKER_NAME for t in threading.enumerate())
    finally:
        agency.close()


def test_the_orchestrator_sees_the_device_through_the_decorator(registry, tmp_path):
    agency = _agency(tmp_path, registry)
    try:
        assert isinstance(agency.orchestrator.device, Device)
        # The planner must NOT see it, or its planning call would be
        # published as a critique.
        assert agency.planner.device is agency.device
    finally:
        agency.close()


# -- planning ---------------------------------------------------------------


def _fresh_registry(registry: Registry) -> Registry:
    """A private copy of the registry.

    The Agency refreshes the registry's downloaded flags from the
    appliance, which mutates it. The fixture is module-scoped, so a test
    that downloads a model would leave every later test believing the
    model is already on the disk.
    """
    return Registry.load(registry.path)


def test_a_generation_downloads_the_model_it_needs(tmp_path: Path,
                                                  registry: Registry,
                                                  monkeypatch):
    """A request only an UNDOWNLOADED model can do downloads it first.

    The appliance has no object-removal adapter: the model that does the
    job is in the store but not on the disk. Rather than refusing, the
    Agency fetches it and then uses it — which is the whole point of
    having a store and a disk.
    """
    monkeypatch.setattr("tis.service.DOWNLOAD_POLL_SECONDS", 0.01)
    fresh = _fresh_registry(registry)
    device = FakeDevice(fresh)
    agency = _agency(tmp_path, fresh, device=device)
    try:
        job_id = agency.generate("remove the object from the photo")
        job = _wait(agency, job_id)

        assert job.status == "succeeded", job.error
        assert device.downloads == ["fal/FLUX.2-klein-4B-Object-Remove"]

        # And the model really is on the appliance afterwards.
        statuses = {row["fullname"]: row["status"]
                    for row in device.catalogue()}
        assert statuses["fal/FLUX.2-klein-4B-Object-Remove"] == "downloaded"
    finally:
        agency.close()


def test_a_download_is_published_as_progress(tmp_path: Path, registry: Registry,
                                              monkeypatch):
    """A download takes minutes. The session is told what is happening
    throughout, so a watcher sees progress rather than a silence."""
    monkeypatch.setattr("tis.service.DOWNLOAD_POLL_SECONDS", 0.01)
    fresh = _fresh_registry(registry)
    device = FakeDevice(fresh)
    agency = _agency(tmp_path, fresh, device=device)
    try:
        subscriber = agency.events.subscribe("default")
        agency.generate("remove the object from the photo")
        time.sleep(0.5)

        kinds = []
        while True:
            try:
                event = subscriber.get_nowait()
            except queue.Empty:
                break
            kinds.append(event.type)
    finally:
        agency.close()

    assert "download.started" in kinds
    assert "download.finished" in kinds


def test_a_plan_that_needs_a_download_names_it(tmp_path: Path,
                                                registry: Registry):
    """A plan is a read, so it downloads nothing — but it says what the
    generation would fetch."""
    fresh = _fresh_registry(registry)
    device = FakeDevice(fresh)
    agency = _agency(tmp_path, fresh, device=device)
    try:
        plan = agency.plan("remove the object from the photo")
        assert plan["download"]["model"] == "fal/FLUX.2-klein-4B-Object-Remove"
        assert plan["download"]["size_bytes"] > 0
        assert device.downloads == []
    finally:
        agency.close()


def test_a_download_is_refused_when_the_disk_has_no_room(tmp_path: Path,
                                                          registry: Registry,
                                                          monkeypatch):
    """Storage is not usually the constraint, but when it is, the request
    says so instead of filling the disk."""
    monkeypatch.setattr("tis.service.DOWNLOAD_POLL_SECONDS", 0.01)
    fresh = _fresh_registry(registry)
    device = FakeDevice(fresh)
    device._total_bytes = 1024
    agency = _agency(tmp_path, fresh, device=device)
    try:
        job_id = agency.generate("remove the object from the photo")
        job = _wait(agency, job_id)
        assert job.status == "failed"
        assert "GiB" in (job.error or "")
        assert device.downloads == []
    finally:
        agency.close()


def test_a_generation_uses_the_model_it_just_downloaded(tmp_path: Path,
                                                          registry: Registry,
                                                          monkeypatch):
    """The downloaded model is the one that generates the image."""
    monkeypatch.setattr("tis.service.DOWNLOAD_POLL_SECONDS", 0.01)
    fresh = _fresh_registry(registry)
    device = FakeDevice(fresh)
    agency = _agency(tmp_path, fresh, device=device)
    try:
        job_id = agency.generate("remove the object from the photo")
        job = _wait(agency, job_id)
        assert job.status == "succeeded", job.error

        # The model that generated the image is the one just downloaded.
        generated = [call[1] for call in device.calls if call[0] == "generate"]
        assert "fal/FLUX.2-klein-4B-Object-Remove" in generated
    finally:
        agency.close()


def test_a_plan_returns_the_documented_shape(registry, tmp_path):
    agency = _agency(tmp_path, registry)
    try:
        plan = agency.plan("a friendly robot waving hello")
        assert set(plan) == {
            "plan_id", "requirements", "model", "justification",
            "alternatives", "unavailable", "swap_required", "swap_plan",
            "planner_source", "download",
        }
        # Nothing to download: the model was already on the appliance.
        assert plan["download"] is None
        assert plan["plan_id"].startswith("plan_")
        assert len(plan["plan_id"]) == len("plan_") + 16
        assert plan["planner_source"] == "fallback"
        assert plan["requirements"]["artifact"] == "illustration"
        assert set(plan["model"]) == {
            "id", "role", "npu_usage", "co_resident_with_planner",
            "downloaded",
        }
        assert plan["model"]["id"] == "Tongyi-MAI/Z-Image-Turbo"
        assert isinstance(plan["alternatives"], list)
        for alternative in plan["alternatives"]:
            assert set(alternative) == {
                "id", "role", "npu_usage", "co_resident_with_planner",
                "downloaded",
            }
        assert isinstance(plan["unavailable"], list)
        for model in plan["unavailable"]:
            assert set(model) == {
                "id", "role", "npu_usage", "co_resident_with_planner",
                "downloaded",
            }
            assert model["downloaded"] is False
        assert isinstance(plan["swap_required"], bool)
        assert set(plan["swap_plan"]) == {"load", "evict", "keep"}
        assert plan["justification"]
    finally:
        agency.close()


def test_plan_records_the_llm_planner_source(registry, tmp_path):
    device = FakeDevice(registry, resident=[registry.planner.id],
                         replies={registry.planner.id: PLANNER_JSON})
    agency = _agency(tmp_path, registry, device=device)
    try:
        plan = agency.plan("a friendly robot waving hello")
        assert plan["planner_source"] == "llm"
        assert plan["requirements"]["artifact"] == "illustration"
    finally:
        agency.close()


def test_every_plan_gets_its_own_id(registry, tmp_path):
    agency = _agency(tmp_path, registry)
    try:
        first = agency.plan("a friendly robot waving hello")
        second = agency.plan("a friendly robot waving hello")
        assert first["plan_id"] != second["plan_id"]
    finally:
        agency.close()


# -- the job runner ---------------------------------------------------------


def test_generate_returns_a_job_id_before_the_job_is_finished(registry, tmp_path):
    device = _BlockingDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        job_id = agency.generate("a friendly robot waving hello", session_id="s1")
        assert job_id.startswith("job_")

        job = agency.get_job(job_id)
        assert job is not None
        assert job.status in ("queued", "running")
        assert job.status != "succeeded"

        device.gate.set()
        assert _wait(agency, job_id).status == "succeeded"
    finally:
        device.gate.set()
        agency.close()


def test_a_generation_succeeds_and_writes_an_asset(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        job_id = agency.generate("a friendly robot waving hello", session_id="s1")
        job = _wait(agency, job_id)
        assert job.status == "succeeded"
        assert job.error is None

        asset = agency.get_asset(job.payload["asset_id"])
        assert asset is not None
        lineage = asset.lineage
        assert set(lineage) == {
            "requirements", "model_id", "prompt", "size", "attempts",
            "critique", "critique_skipped_reason", "planner_source",
            "request", "modifiers", "session_id", "job_id", "created_at",
        }
        assert lineage["model_id"] == "Tongyi-MAI/Z-Image-Turbo"
        assert lineage["prompt"]
        assert lineage["requirements"]["artifact"] == "illustration"
        assert lineage["session_id"] == "s1"
        assert lineage["job_id"] == job_id
        assert lineage["planner_source"] == "fallback"
        assert lineage["request"] == "a friendly robot waving hello"
        # A first generation carries no modifiers yet; they accumulate
        # with each iteration.
        assert lineage["modifiers"] == []
        assert lineage["attempts"] == 1
        assert lineage["critique"] is not None
        assert lineage["critique_skipped_reason"] is None
        assert lineage["created_at"] > 0
    finally:
        agency.close()


def test_the_png_is_byte_for_byte_what_the_device_returned(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        job_id = agency.generate("a friendly robot waving hello")
        job = _wait(agency, job_id)
        asset = agency.get_asset(job.payload["asset_id"])
        assert asset.png == png_bytes()
        on_disk = tmp_path / "assets" / f"{asset.id}.png"
        assert on_disk.read_bytes() == png_bytes()
    finally:
        agency.close()


def test_a_failed_generation_fails_the_job_and_the_worker_survives(registry, tmp_path):
    device = _FlakyDevice(registry, failures=1,
                           replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        events = agency.events.subscribe("s1")
        bad = agency.generate("a friendly robot waving hello", session_id="s1")
        job = _wait(agency, bad)
        assert job.status == "failed"
        assert job.error is not None
        assert "failed to complete" in job.error
        assert "job.failed" in _types(_drain(events))

        # The worker is still there, and it takes the next job.
        good = agency.generate("a friendly robot waving hello again",
                               session_id="s1")
        assert _wait(agency, good).status == "succeeded"
    finally:
        agency.close()


# -- the event stream -------------------------------------------------------


def test_the_events_for_a_session_arrive_in_order(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        events = agency.events.subscribe("s1")
        job_id = agency.generate("a friendly robot waving hello", session_id="s1")
        _wait(agency, job_id)

        assert _types(_drain(events)) == [
            "job.queued",
            "job.started",
            "plan.ready",
            "swap.started",
            "generate.started",
            "generate.finished",
            # Exactly one critique: the planner's own chat did not produce
            # one, because the planner talks to the raw device.
            "critique.ready",
            "swap.finished",
            "asset.ready",
            "job.finished",
        ]
    finally:
        agency.close()


def test_an_event_for_one_session_is_not_delivered_to_another(registry, tmp_path):
    agency = _agency(tmp_path, registry, replies={registry.planner.id: PASS})
    try:
        mine = agency.events.subscribe("mine")
        theirs = agency.events.subscribe("theirs")
        job_id = agency.generate("a friendly robot waving hello", session_id="mine")
        _wait(agency, job_id)

        assert "job.queued" in _types(_drain(mine))
        with pytest.raises(queue.Empty):
            theirs.get(timeout=0.2)
    finally:
        agency.close()


def test_the_plan_ready_event_carries_the_model_and_the_reason(registry, tmp_path):
    agency = _agency(tmp_path, registry, replies={registry.planner.id: PASS})
    try:
        events = agency.events.subscribe("s1")
        job_id = agency.generate("a friendly robot waving hello", session_id="s1")
        _wait(agency, job_id)

        ready = [e for e in _drain(events) if e.type == "plan.ready"]
        assert len(ready) == 1
        assert ready[0].data["model"] == "Tongyi-MAI/Z-Image-Turbo"
        assert ready[0].data["justification"]
        assert ready[0].data["planner_source"] == "fallback"
        assert ready[0].session_id == "s1"
    finally:
        agency.close()


# -- iteration --------------------------------------------------------------


def test_iterate_on_an_unknown_asset_fails_the_job(registry, tmp_path):
    agency = _agency(tmp_path, registry, replies={registry.planner.id: PASS})
    try:
        events = agency.events.subscribe("s1")
        job_id = agency.iterate("ast_does_not_exist", "make it blue",
                                session_id="s1")
        job = _wait(agency, job_id)
        assert job.status == "failed"
        assert job.error is not None
        assert "ast_does_not_exist" in job.error
        assert "job.failed" in _types(_drain(events))
    finally:
        agency.close()


def test_iterate_carries_the_feedback_into_the_new_prompt(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        first = agency.generate("a friendly robot waving hello", session_id="s1")
        original = _wait(agency, first)
        asset_id = original.payload["asset_id"]

        second = agency.iterate(asset_id, "make it blue and smaller",
                                session_id="s1")
        revised = _wait(agency, second)
        assert revised.status == "succeeded"

        asset = agency.get_asset(revised.payload["asset_id"])
        assert asset is not None
        assert asset.id != asset_id
        # The feedback travels as a modifier, and the dialect translator
        # capitalises the sentence it becomes — so the words are there,
        # not the exact casing.
        assert "make it blue and smaller" in asset.lineage["prompt"].lower()
        # The requirements carry over from the image being iterated on.
        original_asset = agency.get_asset(asset_id)
        assert original_asset is not None
        assert asset.lineage["requirements"] == original_asset.lineage["requirements"]
        assert asset.lineage["session_id"] == "s1"
    finally:
        agency.close()


# -- the facts about the appliance -----------------------------------------


def test_health_answers_when_the_device_is_unreachable(registry, tmp_path):
    agency = _agency(tmp_path, registry, device=_DeadDevice(registry))
    try:
        health = agency.health()
        assert health["alive"] is True
        assert health["device_reachable"] is False
        assert health["registry_loaded"] is True
    finally:
        agency.close()


def test_npu_reports_the_resident_set_and_its_cost(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        npu = agency.npu()
        assert npu["resident"] == device.resident()
        assert isinstance(npu["used_pct"], int)
        assert npu["used_pct"] > 0
        assert {entry["id"] for entry in npu["models"]} == set(device.resident())
        for entry in npu["models"]:
            assert isinstance(entry["npu_usage"], int)
    finally:
        agency.close()


# ------------------------------------------------------------ the bearer-----


def test_the_bearer_never_reaches_a_response(registry, tmp_path):
    settings = _settings(tmp_path)
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = Agency(settings, device=device, registry=registry)
    try:
        events = agency.events.subscribe("s1")
        job_id = agency.generate("a friendly robot waving hello", session_id="s1")
        job = _wait(agency, job_id)
        assert job.status == "succeeded"
        asset = agency.get_asset(job.payload["asset_id"])

        plan = agency.plan("a friendly robot waving hello")
        health = agency.health()
        npu = agency.npu()
        collected = _drain(events)

        lineage_on_disk = (tmp_path / "assets" / f"{asset.id}.json").read_text()
        assert BEARER not in json.dumps(asset.lineage)
        assert BEARER not in lineage_on_disk
        assert BEARER not in json.dumps(
            [{"type": e.type, "data": e.data} for e in collected])
        assert BEARER not in json.dumps(job.payload)
        assert BEARER not in json.dumps(plan)
        assert BEARER not in json.dumps(health)
        assert BEARER not in json.dumps(npu)
    finally:
        agency.close()


# -- closing ----------------------------------------------------------------


def test_close_stops_the_worker_and_is_safe_to_call_twice(registry, tmp_path):
    agency = _agency(tmp_path, registry, replies={registry.planner.id: PASS})
    job_id = agency.generate("a friendly robot waving hello")
    _wait(agency, job_id)

    agency.close()
    agency.close()

    assert not any(t.name == WORKER_NAME for t in threading.enumerate())


def test_close_is_safe_when_no_job_was_ever_accepted(registry, tmp_path):
    agency = Agency(_settings(tmp_path), device=FakeDevice(registry),
                    registry=registry)
    agency.close()
    agency.close()


def test_iterating_builds_on_the_request_not_on_the_previous_prompt(registry, tmp_path):
    """The dialect is applied once, not to itself.

    The prompt is what the translator produced. Feeding it back in would
    apply the model's dialect rules to an already-dialected prompt, and
    every iteration would compound. The base is the original request; the
    feedback accumulates as modifiers.
    """
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        first = agency.generate("an app icon of a fox head", session_id="s1")
        asset_id = _wait(agency, first).payload["asset_id"]

        second = agency.iterate(asset_id, "make the ears sharper",
                                session_id="s1")
        revised = _wait(agency, second)
        assert revised.status == "succeeded"

        lineage = agency.get_asset(revised.payload["asset_id"]).lineage
        assert lineage["modifiers"] == ["make the ears sharper"]
        # The subject is the original request, not the previous prompt.
        assert lineage["request"] == "an app icon of a fox head"
        assert "fox head" in lineage["prompt"].lower()
        assert "make the ears sharper" in lineage["prompt"].lower()
    finally:
        agency.close()


def test_iterating_twice_accumulates_the_modifiers(registry, tmp_path):
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    agency = _agency(tmp_path, registry, device=device)
    try:
        first = agency.generate("an app icon of a fox head", session_id="s1")
        asset_id = _wait(agency, first).payload["asset_id"]

        second = agency.iterate(asset_id, "sharper ears", session_id="s1")
        asset_id2 = _wait(agency, second).payload["asset_id"]

        third = agency.iterate(asset_id2, "warmer colour", session_id="s1")
        asset_id3 = _wait(agency, third).payload["asset_id"]

        asset = agency.get_asset(asset_id3)
        assert asset is not None
        lineage = asset.lineage
        assert lineage["modifiers"] == ["sharper ears", "warmer colour"]
        # Still built on the original request.
        assert lineage["request"] == "an app icon of a fox head"
    finally:
        agency.close()
