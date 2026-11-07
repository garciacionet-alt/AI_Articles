"""Tests for the residency of a runtime-chosen critic.

THE TWO THINGS THAT WENT WRONG
------------------------------
1. The residency manager costed a model by looking in the IMAGE
   registry, then in a table of five appliance models, and otherwise
   said "zero". A judge chosen at runtime is usually in neither - so a
   29% judge was costed at zero, the eviction planner left the pool
   above the execution ceiling, and the generation failed.

2. The orchestrator was handed the critic when it was built. Choosing
   a different critic replaced the agency's copy and the guide, and
   left the orchestrator judging with the old one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.registry import Registry
from tis.residency import HoldFile, ResidencyManager
from tis.roles import Roles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

JUDGE = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"
VISION_JUDGE = "Qwen/Qwen3.6-35B-A3B"
CHEAP_VISION = "Qwen/Qwen3.5-9B"


@pytest.fixture(scope="module")
def roles() -> Roles:
    return Roles.load(ROLES_PATH)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _manager(registry: Registry, roles: Roles, tmp_path: Path, **kw):
    device = FakeDevice(registry, resident=[JUDGE, VISION_JUDGE])
    manager = ResidencyManager(
        device, registry,
        HoldFile(tmp_path / "hold"),
        tmp_path / "watch.lock",
        roles=roles, **kw)
    return manager, device


def test_a_judge_outside_the_image_registry_is_costed(registry, roles,
                                                       tmp_path):
    """Not zero. Zero is how the pool got over the ceiling."""
    manager, _ = _manager(registry, roles, tmp_path)
    assert manager._cost(CHEAP_VISION) == 29


def test_the_image_registry_still_costs_what_it_costs(registry, roles,
                                                       tmp_path):
    manager, _ = _manager(registry, roles, tmp_path)
    assert manager._cost("Tongyi-MAI/Z-Image-Turbo") == 23


def test_the_planner_still_costs_what_it_costs(registry, roles, tmp_path):
    manager, _ = _manager(registry, roles, tmp_path)
    assert manager._cost(JUDGE) == 55


def test_the_appliance_models_still_cost_what_they_cost(registry, roles,
                                                         tmp_path):
    manager, _ = _manager(registry, roles, tmp_path)
    assert manager._cost("Qwen/Qwen3-ASR-1.7B") == 7


def test_a_model_nobody_knows_is_still_free(registry, roles, tmp_path):
    """The safe assumption: do not evict somebody else for a model
    whose cost is unknown."""
    manager, _ = _manager(registry, roles, tmp_path)
    assert manager._cost("nobody/imagines-this-model") == 0


def test_the_eviction_plan_makes_room_for_a_judge_that_costs(registry, roles,
                                                              tmp_path):
    """The whole point: the judge is priced, so the plan is right.

    Without the price the 29% judge was free, the plan kept everything
    resident, and the generation would have run above the ceiling.
    """
    manager, device = _manager(registry, roles, tmp_path)
    target = manager._target_set("Tongyi-MAI/Z-Image-Turbo", (CHEAP_VISION,))

    assert CHEAP_VISION in target
    evictions = manager._plan_evictions(target)
    total = sum(manager._cost(m) for m in device.resident()) \
        + sum(manager._cost(m) for m in target if m not in device.resident()) \
        - sum(manager._cost(m) for m in evictions)
    assert total <= 81, (
        f"the plan leaves {total}% of the pool, over the 81% ceiling")


def test_a_judge_that_cannot_share_the_pool_is_left_out(registry, roles,
                                                         tmp_path):
    """The flagship path: a pair that does not fit is not a slow load."""
    manager, _ = _manager(registry, roles, tmp_path)
    target = manager._target_set("Qwen/Qwen-Image-2.1", (JUDGE,))
    assert JUDGE not in target


def test_the_agency_gives_the_orchestrator_the_new_critic(tmp_path,
                                                           registry):
    """Choosing a critic has to change the JUDGING, not just the guide."""
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=ROLES_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
        planner_model=JUDGE,
    )
    agency = Agency(settings,
                    device=FakeDevice(registry,
                                      resident=[JUDGE, VISION_JUDGE]),
                    registry=registry)

    assert agency.orchestrator.critic.model_id == VISION_JUDGE
    agency.set_roles(critic=VISION_JUDGE)
    assert agency.orchestrator.critic.model_id == VISION_JUDGE
    assert agency.orchestrator.critic.vision is True
