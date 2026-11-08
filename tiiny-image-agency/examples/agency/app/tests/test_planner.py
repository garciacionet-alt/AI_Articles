"""Tests for the planner.

The planner is the only place the LLM is allowed to touch, and the only
thing it is allowed to do is READ ENGLISH. These tests therefore check two
things: that the model's answer is used when it is usable, and that the
product still works when it is not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.planner import (
    ARTIFACT_WORDS,
    NO_STYLE,
    STYLE_WORDS,
    Planner,
    PlannerError,
)
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

PLANNER = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"

GOOD_REPLY = json.dumps({
    "artifact": "icon",
    "alpha": "required",
    "text_in_image": "no",
    "style": "flat",
    "speed": "normal",
    "hard": ["native_alpha"],
    "width": 1024,
    "height": 1024,
})


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _device(registry: Registry, reply: str, *, resident=None) -> FakeDevice:
    return FakeDevice(
        registry,
        resident=resident if resident is not None else [PLANNER],
        replies={PLANNER: reply},
    )


def _planner(registry: Registry, reply: str, *, resident=None) -> Planner:
    return Planner(_device(registry, reply, resident=resident), PLANNER, registry)


def _fallback_plan(registry: Registry, request: str):
    """A plan made by the keyword planner: the model's reply is unusable."""
    return _planner(registry, "I am afraid I cannot help with that.").plan(request)


class _BrokenDevice:
    """A device that answers with something that is not a chat reply."""

    def __init__(self, answer):
        self.answer = answer

    def chat(self, model: str, prompt: str, **kw) -> dict:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def generate(self, model: str, prompt: str, size: str,
                 image: bytes | None = None) -> bytes:
        raise NotImplementedError

    def resident(self) -> list[str]:
        return []

    def load(self, model: str) -> None:
        pass

    def unload(self, model: str) -> None:
        pass


# --- the model's answer ----------------------------------------------------


def test_a_well_formed_reply_becomes_the_plan(registry: Registry):
    plan = _planner(registry, GOOD_REPLY).plan("an app icon of a fox head")
    assert plan.source == "llm"
    assert plan.raw == GOOD_REPLY
    assert plan.requirements.artifact.value == "icon"
    assert plan.requirements.alpha == "required"
    assert plan.requirements.text_in_image == "no"
    assert plan.requirements.style == "flat"
    assert plan.requirements.speed == "normal"
    assert plan.requirements.hard == ["native_alpha"]


def test_a_fenced_reply_is_parsed(registry: Registry):
    device = _device(registry, f"```json\n{GOOD_REPLY}\n```")
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "llm"
    assert plan.requirements.artifact.value == "icon"
    assert plan.requirements.alpha == "required"


def test_a_reply_in_a_bare_fence_is_parsed(registry: Registry):
    device = _device(registry, f"```\n{GOOD_REPLY}\n```")
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "llm"
    assert plan.requirements.artifact.value == "icon"


def test_a_reply_with_prose_around_the_json_is_parsed(registry: Registry):
    reply = (
        "Sure — here is the requirement vector you asked for:\n"
        f"{GOOD_REPLY}\n"
        "Let me know if you want anything else."
    )
    device = _device(registry, reply)
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "llm"
    assert plan.requirements.artifact.value == "icon"
    assert plan.requirements.alpha == "required"


def test_a_missing_key_takes_the_vectors_default(registry: Registry):
    reply = json.dumps({"artifact": "logo"})
    plan = _planner(registry, reply).plan("a logo for a bakery")
    assert plan.source == "llm"
    assert plan.requirements.alpha == "no"
    assert plan.requirements.text_in_image == "no"
    assert plan.requirements.style == "general"
    assert plan.requirements.speed == "normal"
    assert plan.requirements.hard == []


def test_an_artifact_the_registry_does_not_declare_is_still_valid(registry: Registry):
    """The user may ask for anything; the resolver's soft filter copes."""
    reply = json.dumps({"artifact": "hologram", "alpha": "no"})
    plan = _planner(registry, reply).plan("a hologram of a fox")
    assert plan.source == "llm"
    assert plan.requirements.artifact.value == "hologram"


# --- the fallbacks ---------------------------------------------------------


def test_a_reply_that_is_not_json_falls_back(registry: Registry):
    reply = "I think you want an icon, but I am not certain."
    plan = _planner(registry, reply).plan("an app icon of a fox head")
    assert plan.source == "fallback"
    assert plan.raw == reply
    assert plan.requirements.artifact.value == "icon"


def test_a_reply_with_an_invalid_alpha_falls_back(registry: Registry):
    reply = json.dumps({"artifact": "icon", "alpha": "maybe"})
    plan = _planner(registry, reply).plan("an app icon of a fox head")
    assert plan.source == "fallback"
    assert plan.raw == reply
    assert plan.requirements.alpha == "no"


def test_a_reply_with_an_invalid_speed_falls_back(registry: Registry):
    reply = json.dumps({"artifact": "icon", "speed": "quick"})
    plan = _planner(registry, reply).plan("an app icon of a fox head")
    assert plan.source == "fallback"


def test_a_reply_with_a_non_numeric_size_falls_back(registry: Registry):
    reply = json.dumps({"artifact": "icon", "width": "large", "height": 1024})
    plan = _planner(registry, reply).plan("an app icon of a fox head")
    assert plan.source == "fallback"


def test_a_planner_that_is_not_resident_falls_back(registry: Registry):
    """The appliance serves one inference stream; the planner may be gone."""
    plan = _planner(registry, GOOD_REPLY,
                    resident=["Supertone/supertonic-3"]).plan("an app icon of a fox head")
    assert plan.source == "fallback"
    assert plan.raw == ""
    assert plan.requirements.artifact.value == "icon"


def test_an_empty_reply_falls_back(registry: Registry):
    plan = _planner(registry, "").plan("an app icon of a fox head")
    assert plan.source == "fallback"


def test_a_device_that_raises_something_unexpected_falls_back(registry: Registry):
    """The appliance fails in more ways than the protocol documents."""
    device = _BrokenDevice(RuntimeError("the inference engine wedged"))
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "fallback"
    assert plan.raw == ""
    assert plan.requirements.artifact.value == "icon"


def test_a_reply_that_is_not_a_chat_reply_falls_back(registry: Registry):
    device = _BrokenDevice({"unexpected": "shape"})
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "fallback"


def test_a_reply_that_is_not_text_falls_back(registry: Registry):
    device = _BrokenDevice({"choices": [{"message": {"content": None}}]})
    plan = Planner(device, PLANNER, registry).plan("an app icon of a fox head")
    assert plan.source == "fallback"
    assert plan.raw == ""


# --- the caller's mistakes -------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_request_raises_planner_error(registry: Registry, text: str):
    device = _device(registry, GOOD_REPLY)
    with pytest.raises(PlannerError):
        Planner(device, PLANNER, registry).plan(text)
    # A request with no words in it is a caller's mistake, and it is
    # answered before the appliance is troubled.
    assert device.prompts == []


# --- the keyword planner ---------------------------------------------------


def test_the_fallback_reads_transparency(registry: Registry):
    plan = _fallback_plan(registry, "a fox head with a transparent background")
    assert plan.requirements.alpha == "required"


def test_the_fallback_reads_an_icon(registry: Registry):
    plan = _fallback_plan(registry, "I need an app icon of a fox head")
    assert plan.requirements.artifact.value == "icon"


def test_the_fallback_leaves_alpha_alone_when_nothing_is_said(registry: Registry):
    plan = _fallback_plan(registry, "a picture of a fox in a field")
    assert plan.requirements.alpha == "no"


def test_the_fallback_leaves_the_style_alone_when_nothing_is_said(registry: Registry):
    plan = _fallback_plan(registry, "a picture of a fox in a field")
    assert plan.requirements.style == "general"


def test_the_fallback_reads_a_background_removal(registry: Registry):
    """A request to remove a background is an EDIT, not a new image."""
    plan = _fallback_plan(registry, "remove the background from this photo")
    assert plan.requirements.edit_op.value == "background_remove"
    assert plan.requirements.artifact.value == "cutout"


def test_the_fallback_reads_an_object_removal(registry: Registry):
    plan = _fallback_plan(registry, "remove the cat from the photo")
    assert plan.requirements.edit_op.value == "object_remove"
    assert plan.requirements.artifact.value == "edit"


def test_the_fallback_reads_an_outpaint(registry: Registry):
    plan = _fallback_plan(registry, "extend the canvas to the left")
    assert plan.requirements.edit_op.value == "outpaint"


def test_the_fallback_leaves_the_edit_alone_when_nothing_is_asked(registry: Registry):
    plan = _fallback_plan(registry, "a picture of a fox in a field")
    assert plan.requirements.edit_op.value == "none"


def test_the_fallback_does_not_turn_transparency_into_an_edit(registry: Registry):
    """"A transparent background" asks for a new image with alpha, not for
    a background to be taken off an existing one."""
    plan = _fallback_plan(registry, "a fox head with a transparent background")
    assert plan.requirements.edit_op.value == "none"
    assert plan.requirements.alpha == "required"


def test_the_fallback_does_not_invent_a_style(registry: Registry):
    """A style the catalogue does not declare filters out every model."""
    styles = {style for model in registry.models for style in model.style}
    plan = _fallback_plan(registry, "a cartoon of a fox")
    assert plan.requirements.style in styles
    assert plan.requirements.style == "general"


def test_the_fallback_takes_a_style_the_catalogue_declares(registry: Registry):
    styles = {style for model in registry.models for style in model.style}
    assert "flat" in styles
    plan = _fallback_plan(registry, "a flat icon of a fox head")
    assert plan.requirements.style == "flat"


def test_the_fallback_leaves_everything_at_its_default(registry: Registry):
    plan = _fallback_plan(registry, "a fox")
    requirements = plan.requirements
    assert requirements.artifact.value == "illustration"
    assert requirements.alpha == "no"
    assert requirements.text_in_image == "no"
    assert requirements.style == "general"
    assert requirements.speed == "normal"
    assert requirements.hard == []


def test_the_fallback_reads_text(registry: Registry):
    plan = _fallback_plan(registry, "a poster with the words OPEN")
    assert plan.requirements.text_in_image == "required"


def test_the_fallback_reads_the_speed(registry: Registry):
    plan = _fallback_plan(registry, "an icon, as fast as possible")
    assert plan.requirements.speed == "fastest"


def test_the_fallback_invents_no_constraints(registry: Registry):
    plan = _fallback_plan(registry, "an icon, transparent, with text")
    assert plan.requirements.hard == []


def test_the_fallback_keeps_the_callers_size(registry: Registry):
    plan = _planner(registry, "not json at all").plan("an icon", width=512, height=768)
    assert plan.requirements.width == 512
    assert plan.requirements.height == 768


# --- the size --------------------------------------------------------------


def test_the_callers_size_wins_over_the_models(registry: Registry):
    """The caller owns the size; the model does not."""
    reply = json.dumps({"artifact": "icon", "width": 512, "height": 512})
    plan = _planner(registry, reply).plan("an app icon", width=1024, height=2048)
    assert plan.source == "llm"
    assert plan.requirements.width == 1024
    assert plan.requirements.height == 2048


def test_a_size_of_zero_falls_back_to_the_callers(registry: Registry):
    reply = json.dumps({"artifact": "icon", "width": 0, "height": 0})
    plan = _planner(registry, reply).plan("an app icon", width=1024, height=1024)
    assert plan.source == "llm"
    assert plan.requirements.width == 1024
    assert plan.requirements.height == 1024


# --- the prompt ------------------------------------------------------------


def test_the_prompt_names_the_vocabulary_and_asks_for_json(registry: Registry):
    device = _device(registry, GOOD_REPLY)
    Planner(device, PLANNER, registry).plan("an app icon of a fox head")

    prompt = device.prompts[-1]
    assert "JSON" in prompt
    assert "an app icon of a fox head" in prompt
    for artifact in {a for model in registry.generators for a in model.artifact}:
        assert artifact in prompt
    for style in {style for model in registry.generators for style in model.style
                  if style != NO_STYLE}:
        assert style in prompt
    for value in ("required", "preferred", "fastest", "normal", "quality_first"):
        assert value in prompt
    assert "1024" in prompt


def test_the_prompt_offers_only_what_an_image_can_be(registry: Registry):
    """The prompt enhancers are not things a user asks an image to be.

    Their declared speciality is "prompt_expansion" and their style is
    "n/a" — a placeholder and an operation, not a choice. Offering them
    lets the model answer a request about a better PROMPT with the
    artefact of a prompt expansion, and the resolver then discards the
    choice and generates something else entirely.
    """
    device = _device(registry, GOOD_REPLY)
    planner = Planner(device, PLANNER, registry)

    assert "prompt_expansion" not in planner.artifact_vocabulary()
    assert "n/a" not in planner.style_vocabulary()

    planner.plan("an app icon of a fox head")
    prompt = device.prompts[-1]
    assert "prompt_expansion" not in prompt
    assert "n/a" not in prompt

    # And the fallback cannot reach for one either.
    assert all(style != NO_STYLE for style, _words in STYLE_WORDS)
    assert all(artifact != "prompt_expansion" for artifact, _words in ARTIFACT_WORDS)


def test_the_prompt_gives_the_model_the_size(registry: Registry):
    device = _device(registry, GOOD_REPLY)
    Planner(device, PLANNER, registry).plan("an app icon", width=512, height=768)
    prompt = device.prompts[-1]
    assert "512" in prompt
    assert "768" in prompt
