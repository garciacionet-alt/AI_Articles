"""Tests for the residency layer.

Every test uses the FakeDevice and real files under tmp_path. Nothing here
touches the appliance.
"""
import os
import time
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.device import DeviceError
from tis.registry import Registry
from tis.residency import (
    DEFAULT_RESIDENT_SET,
    HOLD_GRACE_SECONDS,
    MAX_EXECUTABLE_OCCUPANCY_PCT,
    HoldFile,
    ResidencyError,
    ResidencyManager,
    can_co_reside,
    can_execute,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

FLAGSHIP = "Qwen/Qwen-Image-2.1"
ZIMAGE = "Tongyi-MAI/Z-Image-Turbo"
CODER = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


@pytest.fixture
def device(registry: Registry) -> FakeDevice:
    return FakeDevice(registry)


@pytest.fixture
def hold(tmp_path: Path) -> HoldFile:
    return HoldFile(tmp_path / "tiiny-hold")


@pytest.fixture
def manager(device: FakeDevice, registry: Registry, hold: HoldFile,
            tmp_path: Path) -> ResidencyManager:
    return ResidencyManager(device, registry, hold, tmp_path / "tiiny-watch.lock")


# -- the two budgets ---------------------------------------------------

def test_the_measured_ceiling_is_81():
    assert MAX_EXECUTABLE_OCCUPANCY_PCT == 81


def test_can_co_reside_is_the_admission_budget():
    assert can_co_reside(100) is True
    assert can_co_reside(101) is False


def test_can_execute_is_the_execution_budget():
    assert can_execute(81) is True
    assert can_execute(82) is False


def test_the_two_budgets_differ():
    """A set can fit and still not be able to generate."""
    assert can_co_reside(85) is True
    assert can_execute(85) is False


# -- the hold file -----------------------------------------------------

def test_hold_round_trips_model_ids(hold: HoldFile):
    hold.write(["model1", "model2"])
    assert hold.read() == ["model1", "model2"]


def test_hold_clear_removes_it_and_verifies(hold: HoldFile):
    hold.write(["model1"])
    assert hold.clear() is True
    assert hold.read() == []
    assert not hold.path.exists()


def test_clearing_a_hold_that_is_not_there_succeeds(hold: HoldFile):
    assert hold.clear() is True
    assert hold.read() == []


def test_an_emptied_hold_is_no_hold(hold: HoldFile):
    """An emptied file is a RELEASE, not a hold of nothing."""
    hold.write(["model1"])
    hold.path.write_text("", encoding="utf-8")
    assert hold.read() == []


def test_a_fresh_hold_is_fresh(hold: HoldFile):
    hold.write(["model1"])
    assert hold.is_fresh() is True


def test_a_hold_past_the_grace_window_is_not_fresh(hold: HoldFile):
    hold.write(["model1"])
    old = time.time() - (HOLD_GRACE_SECONDS + 100)
    os.utime(hold.path, (old, old))
    assert hold.is_fresh() is False


def test_a_missing_hold_is_not_fresh(hold: HoldFile):
    assert hold.is_fresh() is False
    assert hold.age_seconds() is None


# -- the swap ----------------------------------------------------------

def test_swap_to_holds_the_model_while_it_runs(manager: ResidencyManager,
                                               hold: HoldFile):
    with manager.swap_to(FLAGSHIP):
        assert hold.read() == [FLAGSHIP]
        assert FLAGSHIP in manager.device.resident()


def test_swap_to_clears_the_hold_and_restores_the_resident_set(
        manager: ResidencyManager, hold: HoldFile, device: FakeDevice):
    before = list(device.resident())
    with manager.swap_to(FLAGSHIP):
        pass
    assert hold.read() == []
    assert device.resident() == before


def test_a_crash_mid_swap_still_restores(manager: ResidencyManager,
                                          hold: HoldFile, device: FakeDevice):
    """A crash must not leave the device in a state nobody cleans up."""
    before = list(device.resident())
    with pytest.raises(RuntimeError, match="boom"):
        with manager.swap_to(FLAGSHIP):
            raise RuntimeError("boom")
    assert hold.read() == []
    assert device.resident() == before


def test_a_generation_inside_the_swap_at_high_occupancy_fails(
        manager: ResidencyManager, device: FakeDevice):
    """The measured failure: above 81% the device answers 500 / 150004."""
    with manager.swap_to(FLAGSHIP):
        # The flagship alone is 62% and generates fine.
        assert device.generate(FLAGSHIP, "a fox", "1024x1024").startswith(
            b"\x89PNG\r\n\x1a\n")
        # Add the planner and the pair no longer fits the execution budget.
        device.set_resident([CODER, FLAGSHIP])
        with pytest.raises(DeviceError) as excinfo:
            device.generate(FLAGSHIP, "a fox", "1024x1024")
        assert excinfo.value.status == 500
        assert excinfo.value.code == 150004


def test_the_swap_refuses_when_the_watchdog_lock_is_taken(
        manager: ResidencyManager, tmp_path: Path, device: FakeDevice):
    """A tick that holds the lock must not be raced.

    The swap waits for the lock rather than failing instantly, so this
    uses a short timeout — a real tick lasts seconds, not minutes.
    """
    import fcntl
    manager.lock_timeout = 0.3
    manager.watchdog_lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(manager.watchdog_lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResidencyError):
            with manager.swap_to(FLAGSHIP):
                pass
    finally:
        os.close(fd)


# -- recovery ----------------------------------------------------------

def test_recover_clears_a_stale_hold_and_restores_the_default_set(
        manager: ResidencyManager, hold: HoldFile, device: FakeDevice):
    hold.write([FLAGSHIP])
    old = time.time() - (HOLD_GRACE_SECONDS + 100)
    os.utime(hold.path, (old, old))
    # The held model is not resident, so the hold protects nothing.
    device.set_resident(["Supertone/supertonic-3"])

    restored = manager.recover()

    assert restored == list(DEFAULT_RESIDENT_SET)
    assert hold.read() == []
    assert set(device.resident()) == set(DEFAULT_RESIDENT_SET)


def test_recover_leaves_a_fresh_hold_alone(
        manager: ResidencyManager, hold: HoldFile, device: FakeDevice):
    hold.write([FLAGSHIP])
    assert manager.recover() == []
    assert hold.read() == [FLAGSHIP]


def test_recover_leaves_a_hold_whose_model_is_resident_alone(
        manager: ResidencyManager, hold: HoldFile, device: FakeDevice):
    """An old hold whose model is still resident still protects it."""
    hold.write([FLAGSHIP])
    old = time.time() - (HOLD_GRACE_SECONDS + 100)
    os.utime(hold.path, (old, old))
    device.set_resident([FLAGSHIP, "Supertone/supertonic-3"])

    assert manager.recover() == []
    assert hold.read() == [FLAGSHIP]


def test_recover_with_no_hold_does_nothing(
        manager: ResidencyManager, hold: HoldFile):
    assert manager.recover() == []
    assert hold.read() == []


def test_the_swap_waits_for_a_watchdog_tick_rather_than_failing(registry, tmp_path):
    """The watchdog holds the lock only for the length of a reload. A job
    waits for it; it does not lose a 200-second generation to a tick."""
    import fcntl
    import os
    import threading
    import time

    device = FakeDevice(registry)
    manager = ResidencyManager(device, registry,
                               HoldFile(tmp_path / "tiiny-hold"),
                               tmp_path / "tiiny-watch.lock")

    holder_fd = os.open(tmp_path / "tiiny-watch.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    released = threading.Event()

    def release_soon():
        time.sleep(0.5)
        released.set()
        fcntl.flock(holder_fd, fcntl.LOCK_UN)

    threading.Thread(target=release_soon, daemon=True).start()
    try:
        with manager.swap_to("Tongyi-MAI/Z-Image-Turbo"):
            assert released.is_set()
    finally:
        os.close(holder_fd)


def test_the_swap_fails_loudly_if_the_lock_is_never_released(registry, tmp_path):
    import fcntl
    import os

    device = FakeDevice(registry)
    manager = ResidencyManager(device, registry,
                               HoldFile(tmp_path / "tiiny-hold"),
                               tmp_path / "tiiny-watch.lock")

    holder_fd = os.open(tmp_path / "tiiny-watch.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(ResidencyError):
            with manager._watchdog_lock(timeout=0.3):
                pass
    finally:
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        os.close(holder_fd)
