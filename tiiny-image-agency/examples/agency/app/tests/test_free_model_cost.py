"""Tests for the cost of a model the device prices at zero.

The community quant build reports 0% NPU and is 14.5 GiB of weights.
Believing the 0% meant the eviction planner never evicted it, and every
load after it failed to allocate its buffer while every generation
answered HTTP 500. Unloading it and asking again produced a 980 KB PNG.

So: a model the device calls free is only free if it is SMALL.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.registry import Registry
from tis.residency import (
    FREE_MODEL_WEIGHT_LIMIT,
    NPU_POOL_BYTES,
    HoldFile,
    ResidencyManager,
)
from tis.roles import Roles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

COMMUNITY = "abenzerps/Qwen-Image-2.1-Uncensored-Quantized"
VOICE = "Supertone/supertonic-3"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def roles() -> Roles:
    return Roles.load(ROLES_PATH)


def _manager(registry: Registry, roles: Roles, tmp_path: Path,
             resident=None) -> ResidencyManager:
    device = FakeDevice(registry, resident=resident if resident is not None
                        else [COMMUNITY, VOICE])
    return ResidencyManager(device, registry, HoldFile(tmp_path / "hold"),
                             tmp_path / "watch.lock", roles=roles)


def test_the_community_build_is_not_free_despite_the_device_saying_so(
        registry, roles, tmp_path):
    """14.5 GiB of weights is thirty percent of the pool.

    The device prices it at 0%, and believing that is what broke the
    research run.
    """
    manager = _manager(registry, roles, tmp_path)

    cost = manager._cost(COMMUNITY)
    assert cost > 0, (
        "the community build is 14.5 GiB of weights; calling it free "
        "means the eviction planner never evicts it, and then nothing "
        "else can load")
    assert 25 <= cost <= 35, (
        f"expected roughly its share of the 47.9 GiB pool, got {cost}%")


def test_a_tiny_model_the_device_calls_free_is_still_free(
        registry, roles, tmp_path):
    """The voice really is free. It is 0.21 GiB."""
    manager = _manager(registry, roles, tmp_path)
    assert manager._cost(VOICE) == 0


def test_the_free_limit_sits_between_the_two_kinds():
    """The gap is wide, and that is why a threshold works at all."""
    assert FREE_MODEL_WEIGHT_LIMIT == 1024 ** 3
    assert 0.21 * 1024 ** 3 < FREE_MODEL_WEIGHT_LIMIT
    assert 14.52 * 1024 ** 3 > FREE_MODEL_WEIGHT_LIMIT


def test_the_pool_size_is_the_measured_one():
    assert 47 < NPU_POOL_BYTES / 1024 ** 3 < 49


def test_the_community_build_is_evicted_before_a_load(registry, roles,
                                                      tmp_path):
    """The whole point: it has to GO, or the next load cannot allocate.

    The observed failure was the appliance aborting the judge's
    container with "CreateDeviceBuffer: FAILED" while the community
    build sat there costing nothing in the accounting. Its 14.5 GiB of
    weights were in the way of a contiguous buffer.

    The eviction plan brings the pool down to what the job needs, so a
    big model that is not the target is the first thing to go — it is
    the most expensive thing in the room.
    """
    judge = "Qwen/Qwen3.6-35B-A3B"
    manager = _manager(registry, roles, tmp_path,
                       resident=[COMMUNITY, judge, VOICE])

    # The judge is 47%, the community build 30%, the voice free. That is
    # 77% before the generator — and the generator needs 23% more.
    evictions = manager._plan_evictions([judge, "Tongyi-MAI/Z-Image-Turbo"])

    assert COMMUNITY in evictions, (
        "the community build is not free, so it must be evicted before "
        "a load that needs the room")
    assert evictions.index(COMMUNITY) == 0, (
        "it is the most expensive thing in the room, so it goes first")


def test_a_model_with_no_known_size_is_still_free(registry, roles, tmp_path):
    """The safe assumption is unchanged for a model we cannot measure."""
    manager = _manager(registry, roles, tmp_path)
    assert manager._cost("nobody/imagines-this-model") == 0
