"""Tests for the dialect translator.

The translator turns a SceneDescription into the prompt a specific model
actually wants, and enforces the output sizes the device will accept.

These tests are deliberately data-driven: the set of models and the set of
dialect prose both come from the registry at runtime, so a new model in the
catalogue cannot slip past the mapping unnoticed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tis.dialect import (
    DIALECT_PROFILES,
    DialectProfile,
    DialectTranslator,
    PromptPlan,
    SceneDescription,
)
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

# The phrase that distinguishes each dialect profile in the registry's own
# prose. A model assigned to the wrong profile will not match its markers,
# which is the point: the mapping may not drift away from the data.
#
# Some families have more than one wording in the registry (the community
# Qwen quant points at its flagship, the Z-Image dense model spells the
# advice out differently from HiDream), so each profile lists the markers
# its models are allowed to match.
PROFILE_MARKERS: dict[str, tuple[str, ...]] = {
    "conversational": ("conversational", "same dialect guidance"),
    "descriptive": ("subject first", "style applies automatically"),
    "dense": ("dense and specific", "name the person concretely"),
    "literal_short": ("brevity", "short and literal"),
    "layout": ("verbatim",),
    "instruction": ("instruction-shaped",),
    "sheet": ("ask for the sheet",),
    "edit": ("not a generator",),
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def translator(registry: Registry) -> DialectTranslator:
    return DialectTranslator(registry)


@pytest.fixture
def scene() -> SceneDescription:
    return SceneDescription(
        subject="a red fox sitting in deep snow",
        modifiers=("soft winter fur", "snow-covered pines"),
        lighting="cold blue dawn light",
        mood="calm and watchful",
        extra="wide shot, shallow depth of field",
    )


def test_every_generator_has_a_dialect_profile(registry: Registry):
    """The mapping must cover every generator the registry declares."""
    generator_ids = {model.id for model in registry.generators}
    assert generator_ids, "the registry declares no generators"
    assert generator_ids <= set(DIALECT_PROFILES), (
        "generators without a dialect profile: "
        f"{sorted(generator_ids - set(DIALECT_PROFILES))}"
    )
    # No profile may point at a model the registry does not know.
    assert set(DIALECT_PROFILES) <= set(registry.ids)


def test_profile_names_match_the_registry_dialect_text(registry: Registry):
    """Each model's profile must agree with the prose the registry records."""
    for model in registry.generators:
        profile = DIALECT_PROFILES[model.id]
        markers = PROFILE_MARKERS[profile.name]
        prose = model.dialect.lower()
        assert any(marker in prose for marker in markers), (
            f"{model.id} is mapped to the {profile.name} profile but its "
            f"dialect prose {model.dialect!r} matches none of {markers}"
        )


def test_verified_size_is_used_unchanged(translator: DialectTranslator, registry: Registry):
    model = registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    plan = translator.translate(
        SceneDescription(subject="a red fox in snow"), model, width=1024, height=1024
    )
    assert plan.size_requested == "1024x1024"
    assert plan.size_used == "1024x1024"
    assert plan.size_adjusted is False
    assert plan.notes == []


def test_unverified_size_is_adjusted_to_the_nearest_verified(
    translator: DialectTranslator, registry: Registry
):
    model = registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    plan = translator.translate(
        SceneDescription(subject="a red fox in snow"), model, width=800, height=800
    )
    assert plan.size_requested == "800x800"
    assert plan.size_adjusted is True
    assert plan.size_used in model.sizes_verified
    assert plan.size_used != "800x800"
    assert plan.notes, "an adjusted size must be explained"
    assert any("800x800" in note for note in plan.notes)


def test_rejected_size_is_never_used_and_is_named_in_the_notes(
    translator: DialectTranslator, registry: Registry
):
    model = registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    plan = translator.translate(
        SceneDescription(subject="a red fox in snow"), model, width=1536, height=1024
    )
    assert plan.size_used != "1536x1024"
    assert plan.size_used in model.sizes_verified
    assert plan.size_adjusted is True
    assert any("reject" in note.lower() for note in plan.notes), plan.notes


def test_nearest_size_rule(translator: DialectTranslator, registry: Registry):
    """A verified size stays; a verified-but-unrequested one moves to the nearest."""
    model = registry.by_id("Tongyi-MAI/Z-Image-Turbo")

    stay = translator.translate(
        SceneDescription(subject="a red fox in snow"), model, width=1024, height=1024
    )
    assert stay.size_used == "1024x1024"
    assert stay.size_adjusted is False

    move = translator.translate(
        SceneDescription(subject="a red fox in snow"), model, width=2048, height=2048
    )
    assert move.size_adjusted is True
    assert move.size_used in model.sizes_verified
    # Area difference first: 1024x1024 is the closest verified area to 2048x2048.
    assert move.size_used == "1024x1024"


def test_layout_text_is_verbatim_and_placement_is_stated(
    translator: DialectTranslator, registry: Registry
):
    model = registry.by_id("baidu/ERNIE-Image-Turbo")
    text = "SUMMER SALE — 50% OFF"
    plan = translator.translate(
        SceneDescription(
            subject="a retro travel poster of a coastal lighthouse",
            modifiers=("flat vector shapes",),
            text=text,
            text_placement="top banner",
        ),
        model,
    )
    assert text in plan.prompt
    assert f'"{text}"' in plan.prompt, "the text must appear inside a quoted string"
    assert "top banner" in plan.prompt


def test_booster_tokens_are_stripped_for_descriptive_and_survive_for_conversational(
    translator: DialectTranslator, registry: Registry
):
    booster_scene = SceneDescription(
        subject="a red fox in snow",
        modifiers=("masterpiece", "best quality", "highly detailed"),
    )

    descriptive = translator.translate(
        booster_scene, registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    )
    lowered = descriptive.prompt.lower()
    assert "masterpiece" not in lowered
    assert "best quality" not in lowered
    assert "highly detailed" not in lowered
    # The removed modifiers must not leave empty slots or doubled stops behind.
    assert ",," not in descriptive.prompt
    assert ".." not in descriptive.prompt
    assert descriptive.prompt.endswith(".")

    conversational = translator.translate(
        booster_scene, registry.by_id("Qwen/Qwen-Image-2.1")
    )
    lowered = conversational.prompt.lower()
    assert "masterpiece" in lowered
    assert "best quality" in lowered


def test_booster_tokens_inside_the_users_text_are_left_alone(
    translator: DialectTranslator, registry: Registry
):
    """The user's words are verbatim, even when they look like a booster."""
    text = "MASTERPIECE — best quality"
    plan = translator.translate(
        SceneDescription(subject="a gallery wall", text=text),
        registry.by_id("Tongyi-MAI/Z-Image-Turbo"),
    )
    assert text in plan.prompt


def test_literal_short_prompt_stays_within_max_words(
    translator: DialectTranslator, registry: Registry
):
    model = registry.by_id("black-forest-labs/FLUX.2-klein-4B")
    profile = DIALECT_PROFILES[model.id]
    assert profile.max_words is not None
    plan = translator.translate(
        SceneDescription(
            subject="a lone red fox in deep snow",
            modifiers=("soft winter fur", "snow-covered pines", "distant ridge"),
            lighting="cold blue dawn light",
            mood="calm",
            text="NORTH",
        ),
        model,
    )
    assert len(plan.prompt.split()) <= profile.max_words


def test_edit_prompt_does_not_claim_to_generate_and_mentions_the_input_image(
    translator: DialectTranslator, registry: Registry
):
    model = registry.by_id("fal/FLUX.2-klein-4B-Background-Remove")
    plan = translator.translate(
        SceneDescription(
            subject="remove the background behind the product photo",
            modifiers=("keeping the edges crisp",),
        ),
        model,
    )
    assert "input image" in plan.prompt.lower()
    for forbidden in ("generate", "generating", "generation", "create a new"):
        assert forbidden not in plan.prompt.lower()


def test_translator_is_deterministic(translator: DialectTranslator, registry: Registry):
    model = registry.by_id("Qwen/Qwen-Image-2.1")
    description = SceneDescription(
        subject="a red fox sitting in deep snow",
        modifiers=("soft winter fur",),
        lighting="cold blue dawn light",
        mood="calm and watchful",
        text="NORTH",
        text_placement="top left",
    )
    first = translator.translate(description, model, width=1024, height=1024)
    second = translator.translate(description, model, width=1024, height=1024)
    assert isinstance(first, PromptPlan)
    assert first == second
    assert first.prompt == second.prompt


def test_empty_subject_is_rejected():
    with pytest.raises(ValidationError):
        SceneDescription(subject="")
    with pytest.raises(ValidationError):
        SceneDescription(subject="   ")


def test_every_profile_composes_a_non_empty_prompt(registry: Registry):
    populated = SceneDescription(
        subject="a red fox sitting in deep snow",
        modifiers=("soft winter fur",),
        lighting="cold blue dawn light",
        mood="calm and watchful",
        text="NORTH",
        text_placement="top left",
        extra="wide shot",
    )
    seen: set[str] = set()
    for model_id, profile in DIALECT_PROFILES.items():
        assert isinstance(profile, DialectProfile)
        prompt = profile.compose(populated)
        assert prompt and prompt.strip(), f"{model_id} composed an empty prompt"
        seen.add(profile.name)
    # Every profile family in the catalogue is exercised by the loop above.
    assert seen == set(PROFILE_MARKERS)
