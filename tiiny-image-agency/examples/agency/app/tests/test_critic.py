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


# -- the judge's changes must be usable -----------------------------------
#
# A change is not a note. It is appended to the prompt and sent to the
# image model. So a change that asks for the output's dimensions makes
# the model DRAW the numbers, and the picture is ruined.
#
# It happened: a judge asked for "1024x1024" to be added to the prompt,
# and the delivered image had "Alowiobe 1024x1004" written across it.


def test_a_change_asking_for_the_size_is_dropped(registry: Registry):
    """The size is an argument to the model, not prompt text."""
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: the prompt does not state the size\n"
        "CHANGE: Add 1024x1024 to the prompt",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.suggested_changes == []
    # The judge's own words are not lost.
    assert "1024x1024" in critique.raw


def test_a_dimension_change_in_any_spelling_is_dropped(registry: Registry):
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: wrong\n"
        "CHANGE: set the image size to 2048x2048\n"
        "CHANGE: make the output dimensions 512 by 512\n"
        "CHANGE: the image should be 1024 x 1024",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.suggested_changes == []


def test_a_usable_change_survives_alongside_a_dropped_one(registry: Registry):
    """The filter drops the dimension, not the advice."""
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: the lighting is flat\n"
        "CHANGE: Add 1024x1024 to the prompt\n"
        "CHANGE: use warm rim lighting from the left",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.suggested_changes == [
        "use warm rim lighting from the left"]


def test_a_judge_whose_every_change_is_unusable_is_inconclusive(
        registry: Registry):
    """There is nothing left to act on, so it must not trigger a retry.

    A fail verdict with an unusable change is a broken verdict. The
    orchestrator would otherwise regenerate against a change it cannot
    send, burn a generation, and get the same image.
    """
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: the prompt does not state the size\n"
        "CHANGE: Add 1024x1024 to the prompt",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.inconclusive is True
    assert critique.passed is False


def test_art_direction_about_resolution_is_not_dropped(registry: Registry):
    """The filter must be narrow.

    "resolution" and "size" appear in legitimate art direction. Dropping
    those would throw away real advice about the picture.
    """
    device = _device(
        registry,
        "VERDICT: fail\n"
        "REASON: it looks too clean\n"
        "CHANGE: make it a grainy low-resolution photograph\n"
        "CHANGE: the size of the subject in frame is too small",
    )
    critique = Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())
    assert critique.suggested_changes == [
        "make it a grainy low-resolution photograph",
        "the size of the subject in frame is too small",
    ]


def test_the_judge_is_told_not_to_ask_for_the_size(registry: Registry):
    """Guidance as well as the filter: the judge should not ask at all."""
    device = _device(registry, "VERDICT: pass")
    Critic(device, JUDGE).judge(b"\x89PNG", RequirementVector())

    prompt = device.prompts[-1]
    assert "Never ask for the image SIZE or RESOLUTION" in prompt
    assert "passed as a parameter" in prompt
