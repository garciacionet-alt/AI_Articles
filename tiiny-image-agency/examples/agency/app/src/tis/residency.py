"""Residency: the app's contract with the appliance's one shared NPU pool.

Two things make this harder than it looks.

THE TWO BUDGETS ARE DIFFERENT
------------------------------
A model set can be ADMITTED to the NPU and still fail the diffusion pass.
Measured on the appliance 2026-11-05:

    55% planner + 26% image model = 81%  -> generation SUCCEEDED (54.5 s)
    23% enhancer + 62% flagship  = 85%  -> HTTP 500, code 150004
    27% planner + 62% flagship  = 89%  -> HTTP 500, code 150004
    62% flagship alone          = 62%  -> generation SUCCEEDED (~200 s)

So a set can fit (100%) and still not be able to generate. ``can_co_reside``
is about fitting; ``can_execute`` is about running. Conflating them is how
you get a device that accepts a request and then fails it.

THE WATCHDOG
-------------
A watchdog on a five-minute cron restores the appliance's required set
unless something holds it. The hold file — ``~/.hermes/tiiny-hold`` — is
that contract: the model ids deliberately resident right now. The watchdog
honours a hold only while the file is FRESH or the held model is still
resident, so a hold left behind by a crashed run protects nothing and must
be cleaned up.

The watchdog also takes a lock while it reloads. Without taking that lock
ourselves, a tick that has already passed its hold-check can evict the model
we deliberately loaded, in the middle of a generation.
"""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .device import Device
from .registry import Registry

#: The highest NPU occupancy measured to actually run a generation.
#: 81% worked; 85% did not. This is a measured fact about the appliance, not
#: a policy knob, and it is why the resolver imports it rather than
#: repeating the number.
MAX_EXECUTABLE_OCCUPANCY_PCT = 81

#: How long a hold stays fresh. The watchdog treats a hold as protective
#: while it is within this window, or while the held model is resident.
HOLD_GRACE_SECONDS = 600

#: The NPU cost of the appliance's own resident models, which the registry
#: does not carry because they are not image generators. Measured on the
#: device 2026-11-05.
APPLIANCE_MODEL_NPU_PCT: dict[str, int] = {
    "Qwen/Qwen3.6-35B-A3B": 47,
    "openai/gpt-oss-20b": 27,
    "Qwen/Qwen3-ASR-1.7B": 7,
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": 5,
    "Supertone/supertonic-3": 0,
}

#: The appliance's required set — what the watchdog puts back.
DEFAULT_RESIDENT_SET: tuple[str, ...] = (
    "Qwen/Qwen3.6-35B-A3B",
    "openai/gpt-oss-20b",
    "Qwen/Qwen3-ASR-1.7B",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Supertone/supertonic-3",
)


class ResidencyError(RuntimeError):
    """The device could not be moved to the residency we need."""


def can_co_reside(combined_pct: int) -> bool:
    """Whether the two models may both be resident.

    This is the ADMISSION budget: the pool is 100% and the device will
    decide what to evict. It says nothing about whether the pair can
    actually generate.
    """
    return combined_pct <= 100


def can_execute(combined_pct: int) -> bool:
    """Whether a generation can actually run at that occupancy.

    This is the EXECUTION budget, and it is much lower than admission.
    """
    return combined_pct <= MAX_EXECUTABLE_OCCUPANCY_PCT


class HoldFile:
    """``~/.hermes/tiiny-hold`` — the contract with the watchdog.

    The file holds the model ids that are deliberately resident. The
    watchdog reads it on every tick; if the file names a model that is still
    resident, the watchdog leaves the device alone.

    An emptied file is a RELEASED hold, not a hold of nothing — which is
    why ``clear`` truncates as well as unlinks, and why ``read`` treats an
    empty file as no hold at all.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def write(self, model_ids: list[str]) -> None:
        """Claim the device for these models."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(model_ids) + "\n", encoding="utf-8")

    def read(self) -> list[str]:
        """The model ids being held, or an empty list if there is no hold."""
        try:
            content = self.path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return []
        if not content:
            return []
        return [line for line in content.splitlines() if line.strip()]

    def clear(self) -> bool:
        """Release the hold and VERIFY it is gone.

        Returns False if the hold is still there. A stale hold stops the
        watchdog restoring the device, forever, and it fails silently — so
        the answer is checked, never assumed.
        """
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        # An emptied file is also a release, so a file we could not delete
        # is truncated instead.
        try:
            if self.path.exists():
                self.path.write_text("", encoding="utf-8")
        except OSError:
            pass
        return not self.read()

    def age_seconds(self) -> Optional[float]:
        """How old the hold is, or None if there is no hold."""
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return None

    def is_fresh(self) -> bool:
        """Whether the hold is within its grace window."""
        age = self.age_seconds()
        if age is None:
            return False
        return age <= HOLD_GRACE_SECONDS


class ResidencyManager:
    """Moves the device between resident sets, safely.

    Collaborators are injected so a test can pass a FakeDevice and a
    tmp_path hold. Nothing here touches the device except through the
    Device protocol.
    """

    def __init__(self, device: Device, registry: Registry,
                 hold: HoldFile, watchdog_lock: Path,
                 default_set: Optional[list[str]] = None,
                 lock_timeout: float = 30.0,
                 roles=None):
        self.device = device
        self.registry = registry
        self.hold = hold
        self.watchdog_lock = Path(watchdog_lock)
        self.default_set = list(default_set) if default_set else list(DEFAULT_RESIDENT_SET)
        #: The conversational catalogue, when there is one. The CRITIC's
        #: model is chosen at runtime and is usually not an image model,
        #: so without this the cost of a judge would be unknown - and an
        #: unknown cost is cost zero, which would let the eviction
        #: planner leave the pool above the execution ceiling and the
        #: generation would fail.
        self.roles = roles
        #: How long to wait for the watchdog's lock. The watchdog holds it
        #: only for the length of a reload, so this is generous; it is a
        #: parameter so a test can exercise the refusal without waiting.
        self.lock_timeout = lock_timeout

    # -- the swap -------------------------------------------------------

    @contextmanager
    def swap_to(self, model_id: str, *also_resident: str) -> Iterator[None]:
        """Load a model, hold it against the watchdog, and put it back.

        ``also_resident`` names companions that should stay resident too —
        the critic's judging model, for instance, which the product's hot
        path keeps alongside the image model (55% planner + 26% image model
        = 81%, the last combination measured to generate). A companion is
        only included if it fits ALONGSIDE ``model_id``; if it does not, it
        is left out and the caller finds out by looking at the resident
        set afterwards. That is the flagship path: the 62% flagship and the
        55% planner are 117% together and cannot coexist.

        The ordering is not stylistic:

        1. work out the target set and write the hold FIRST — the watchdog
           fires on a five-minute cron and can land between the load and
           the hold;
        2. take the watchdog's lock — a tick that already passed its
           hold-check would otherwise evict the model mid-generation;
        3. load — a load is a swap, and the eviction it causes is expected;
        4. restore in a ``finally`` — a crash mid-swap must not leave the
           device in a state nobody cleans up.
        """
        target = self._target_set(model_id, also_resident)
        previous = list(self.device.resident())
        self.hold.write(target)
        try:
            with self._watchdog_lock():
                # Make room FIRST. The device evicts only what it must to fit
                # the next load, which is not enough: a generation fails above
                # the execution ceiling, so the whole resident set has to come
                # down to the budget, not just fit the incoming model.
                for victim in self._plan_evictions(target):
                    self.device.unload(victim)
                for model in target:
                    self.device.load(model)
                yield
        finally:
            self.hold.clear()
            self._restore(previous)

    def _plan_evictions(self, target: list[str]) -> list[str]:
        """Which resident models must go so the job can run.

        The generation budget is the EXECUTION ceiling, not the admission
        one: a set can fit in the pool and still fail the diffusion pass
        above 81%. So the resident set is brought down to what the job
        needs — the target models, plus any zero-cost models, which cost
        nothing and always ride along — by evicting the most expensive
        models first.
        """
        keep = set(target)
        candidates = [m for m in self.device.resident()
                      if m not in keep and self._cost(m) > 0]
        total = sum(self._cost(m) for m in self.device.resident())
        total += sum(self._cost(m) for m in target if m not in self.device.resident())

        evictions: list[str] = []
        for model in sorted(candidates, key=self._cost, reverse=True):
            if can_execute(total):
                break
            evictions.append(model)
            total -= self._cost(model)
        return evictions

    def _target_set(self, model_id: str, also_resident: tuple[str, ...]) -> list[str]:
        """The models that should be resident for this job.

        A companion joins only if it fits alongside the primary model. The
        appliance has one shared pool, and a pair that does not fit is not
        a slow load — it is a swap that evicts the very model the job is
        for.
        """
        target = [model_id]
        used = self._cost(model_id)
        for companion in also_resident:
            cost = self._cost(companion)
            if can_co_reside(used + cost):
                target.append(companion)
                used += cost
        return target

    def _cost(self, model_id: str) -> int:
        """The NPU cost of a model.

        The registry keeps the PLANNER separately from the image models, so
        it is not findable by id — but the planner is the most expensive
        thing on the appliance and the one whose cost decides whether a
        judge can sit alongside an image model. Look for it explicitly.

        The registry knows the image models; the conversational catalogue
        knows the models that talk and judge; the appliance's own resident
        models — the generalist, the ASR and TTS models, the voice — are in
        the table above. A model in none of them is treated as free, which
        is the safe assumption: a model we cannot cost is not one we should
        evict someone else for.
        """
        if self.registry.planner.id == model_id:
            return self.registry.planner.npu_usage
        try:
            return self.registry.by_id(model_id).npu_usage
        except Exception:
            pass
        if self.roles is not None:
            spec = self.roles.get(model_id)
            if spec is not None:
                return spec.npu_usage
        return APPLIANCE_MODEL_NPU_PCT.get(model_id, 0)

    @contextmanager
    def _watchdog_lock(self, timeout: Optional[float] = None) -> Iterator[None]:
        """Take the lock the watchdog uses while it reloads.

        The watchdog holds this lock only for the length of a reload — a
        few seconds — so a job WAITS for it rather than failing. But it
        does not wait forever: a lock nobody releases is a different fault,
        and it should surface as one rather than as a hang.
        """
        if timeout is None:
            timeout = self.lock_timeout
        self.watchdog_lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.watchdog_lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ResidencyError(
                            f"could not take the watchdog lock "
                            f"{self.watchdog_lock} within {timeout:.0f}s: {exc}"
                        ) from exc
                    time.sleep(0.2)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _restore(self, previous: list[str]) -> None:
        """Put the device back the way we found it.

        A device that can set its resident set directly — the fake — does so
        exactly. The real appliance has no such call, and cannot have one:
        a load is a swap, so a set of models cannot be rebuilt by loading
        them one at a time. There, clearing the hold IS the restore — the
        watchdog owns putting the required set back, and it does so as soon
        as the hold disappears.
        """
        restore = getattr(self.device, "set_resident", None)
        if restore is not None:
            restore(previous)

    # -- recovery -------------------------------------------------------

    def recover(self) -> list[str]:
        """Clean up after a run that crashed, and say what it changed.

        A hold is stale when it is not fresh AND the model it names is no
        longer resident — at that point it protects nothing, and the
        watchdog will restore the device over the top of it. A fresh hold,
        or one whose model is still resident, is left alone: it may belong
        to a run that is still going.
        """
        held = self.hold.read()
        if not held:
            return []
        if self.hold.is_fresh():
            return []
        resident = self.device.resident()
        if any(model in resident for model in held):
            return []

        self.hold.clear()
        restore = getattr(self.device, "set_resident", None)
        if restore is not None:
            restore(self.default_set)
        return list(self.default_set)
