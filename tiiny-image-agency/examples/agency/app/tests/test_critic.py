"""Tests for the critic."""
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.critic import Critic
from tis.device import DeviceError
from tis.models import Artifact, RequirementVector
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

JUDGE = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _device(registry: Registry, reply: str, *, resident=None) -> FakeDevice:
    return FakeDevice(
        registry,
        resident=resident if resident is not None else [JUDGE],
        replies={JUDGE: reply},
    )


def test_a_pass_verdict_passes(registry: Registry):
    device = _device(registry, "VERDICT: pass\nREASON: it is right")
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.passed is True
    assert critique.inconclusive is False
    assert critique.reasons == ["it is right"]
    assert critique.suggested_changes == []
    assert "VERDICT: pass" in critique.raw


def test_a_fail_verdict_fails_with_reasons_and_changes(registry: Registry):
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: the background is not transparent\n"
        "CHANGE: remove the background\n"
        "CHANGE: use a single solid fill",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.passed is False
    assert critique.inconclusive is False
    assert critique.reasons == ["the background is not transparent"]
    assert critique.suggested_changes == [
        "remove the background", "use a single solid fill"]


def test_a_reply_with_no_verdict_is_inconclusive(registry: Registry):
    """A broken judge is not a failed image."""
    device = _device(registry, "I think it looks quite good actually")
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.inconclusive is True
    assert critique.passed is False
    assert critique.suggested_changes == []


def test_a_multi_line_reply_is_parsed_line_by_line(registry: Registry):
    """The reply is split on newlines, not on a literal backslash-n."""
    device = _device(
        registry,
        "Here is my judgement.\nVERDICT: fail\nREASON: wrong shape\nCHANGE: square it",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.passed is False
    assert critique.reasons == ["wrong shape"]
    assert critique.suggested_changes == ["square it"]


def test_the_judge_prompt_states_the_requirement_vector(registry: Registry):
    device = _device(registry, "VERDICT: pass")
    requirements = RequirementVector(artifact=Artifact.ICON, alpha="required",
                                     text_in_image="required")
    Critic(device, JUDGE).judge(b"\x89PNG", requirements)

    prompt = device.prompts[-1]
    assert "icon" in prompt
    assert "alpha" in prompt
    assert "required" in prompt


def test_a_non_resident_judge_raises(registry: Registry):
    """The 404 propagates — the orchestrator checks residency first, so this
    is a real fault and must not be laundered into 'inconclusive'."""
    device = _device(registry, "VERDICT: pass",
                     resident=["Supertone/supertonic-3"])
    with pytest.raises(DeviceError) as excinfo:
        Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert excinfo.value.status == 404
    assert excinfo.value.retryable is True


def test_the_judge_prompt_carries_the_prompt_that_produced_the_image(
        registry: Registry):
    """The judge cannot see the image, so the prompt is its only evidence.

    Without it the judge reasons from nothing and invents a defect — which
    is not a note but an instruction to regenerate. The first live run
    burned three generations that way.
    """
    device = _device(registry, "VERDICT: pass")
    Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector(),
                                "A friendly robot waving hello.")

    prompt = device.prompts[-1]
    assert "A friendly robot waving hello." in prompt


def test_the_judge_is_told_it_cannot_see_the_image(registry: Registry):
    """A judge that does not know it is blind will invent a defect."""
    device = _device(registry, "VERDICT: pass")
    Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector(),
                                "A friendly robot waving hello.")

    prompt = device.prompts[-1]
    assert "cannot see the image" in prompt
    assert "Never invent a defect" in prompt


def test_a_judge_with_no_prompt_still_asks_for_one(registry: Registry):
    """It must not silently pretend it has evidence it does not have."""
    device = _device(registry, "VERDICT: pass")
    Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())

    prompt = device.prompts[-1]
    assert "the prompt was not recorded" in prompt
