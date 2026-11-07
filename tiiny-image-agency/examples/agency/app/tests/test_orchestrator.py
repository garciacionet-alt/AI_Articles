"""Tests for the orchestrator: the loop from a requirement vector to an image.

Everything here runs against the FakeDevice with REAL collaborators — the
real resolver, the real dialect translator, the real residency manager. The
only thing faked is the appliance. That matters: the interesting failures in
this loop are integration failures (a model that will not fit beside the
judge, a swap that evicts what the job needs), and mocks hide all of them.
"""
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.critic import Critic
from tis.dialect import DialectTranslator, SceneDescription
from tis.models import Artifact, RequirementVector
from tis.orchestrator import Orchestrator
from tis.registry import Registry
from tis.residency import HoldFile, ResidencyManager
from tis.resolver import Resolver

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

PASS = "VERDICT: pass\nREASON: it satisfies the requirements"
FAIL = ("VERDICT: fail\nREASON: the background is not transparent\n"
        "CHANGE: remove the background\nCHANGE: use a single solid fill")


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _build(registry: Registry, tmp_path: Path, replies=None
           ) -> tuple[Orchestrator, FakeDevice]:
    device = FakeDevice(registry, replies=replies or {})
    resolver = Resolver(registry)
    translator = DialectTranslator(registry)
    critic = Critic(device, registry.planner.id)
    residency = ResidencyManager(
        device, registry, HoldFile(tmp_path / "tiiny-hold"),
        tmp_path / "tiiny-watch.lock")
    orchestrator = Orchestrator(device, registry, resolver, translator,
                                critic, residency)
    return orchestrator, device


def _scene() -> SceneDescription:
    return SceneDescription(subject="a fox icon",
                            modifiers=("front-facing", "single solid fill"),
                            lighting="even studio light",
                            mood="playful")


def test_one_generation_with_the_right_model_and_prompt(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.model_id == "Tongyi-MAI/Z-Image-Turbo"
    assert result.image.startswith(b"\x89PNG\r\n\x1a\n")
    assert result.attempts == 1
    assert result.prompt
    assert result.size


def test_a_passing_critic_ends_the_loop_after_one_attempt(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.attempts == 1
    assert result.critique is not None
    assert result.critique.passed is True
    assert result.critique_skipped_reason is None
    assert len([c for c in device.calls if c[0] == "generate"]) == 1


def test_a_failing_critic_causes_a_second_generation_with_adjustments(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: [FAIL, PASS]})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.attempts == 2
    assert "Adjustments:" in result.prompt
    assert "remove the background" in result.prompt
    assert result.critique is not None
    assert result.critique.passed is True


def test_the_loop_stops_at_three_attempts(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: [FAIL]})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.attempts == 3
    assert len([c for c in device.calls if c[0] == "generate"]) == 3
    assert result.critique is not None
    assert result.critique.passed is False


def test_an_inconclusive_critic_stops_the_loop_immediately(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: "I cannot say"})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.attempts == 1
    assert result.critique is not None
    assert result.critique.inconclusive is True


def test_the_image_is_still_delivered_when_no_judge_can_run(registry, tmp_path):
    """The 62% flagship evicts the 55% planner, so there is no judge — but
    the image is still the user's answer."""
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    requirements = RequirementVector(artifact=Artifact.ICON, alpha="required")
    result = orchestrator.generate(requirements, _scene())

    assert result.model_id == "Qwen/Qwen-Image-2.1"
    assert result.image.startswith(b"\x89PNG\r\n\x1a\n")
    assert result.attempts == 1
    assert result.critique is None
    assert result.critique_skipped_reason
    assert "Qwen/Qwen-Image-2.1" in result.critique_skipped_reason


def test_the_resident_set_is_restored_after_the_generation(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    before = list(device.resident())
    orchestrator.generate(RequirementVector(), _scene())
    assert device.resident() == before


def test_the_critic_judges_against_the_requirement_vector(registry, tmp_path):
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    orchestrator.generate(
        RequirementVector(artifact=Artifact.ILLUSTRATION,
                          alpha="no"), _scene())

    prompt = device.prompts[-1]
    assert "illustration" in prompt
    assert "alpha" in prompt
    assert "no" in prompt


def test_the_hot_path_keeps_the_judge_resident(registry, tmp_path):
    """The 55% planner and a 26% image model fit together at 81% — the last
    combination measured to generate — so the judge survives the swap and
    the critique actually runs."""
    orchestrator, device = _build(registry, tmp_path,
                                   {registry.planner.id: PASS})
    result = orchestrator.generate(RequirementVector(), _scene())

    assert result.critique is not None
    assert result.critique_skipped_reason is None
    assert any(call[0] == "chat" for call in device.calls)
