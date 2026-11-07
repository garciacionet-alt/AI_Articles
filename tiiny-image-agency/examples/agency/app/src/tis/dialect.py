"""Dialect translation: a scene description becomes the prompt a model wants.

The planning LLM produces a SceneDescription. The resolver picks a model.
This module writes the prompt that model actually understands, in the dialect
that model expects, and enforces the output sizes the device will accept.

Two ideas run through the code:

* The registry records a model's dialect as prose. Prose cannot be executed,
  so each generator is mapped to a DialectProfile here: an explicit,
  testable structure that says how to compose, what to strip and how brief to
  be. The mapping is checked against the registry's own wording by the tests,
  so the two cannot drift apart silently.

* The device fails on sizes it does not like. Size enforcement is therefore
  not optional: an unverified request is moved to the nearest verified size,
  a rejected size is never used, and every move is explained in the notes.

The translator is pure. No I/O, no clock, no randomness: the same scene and
model always produce the same PromptPlan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Iterable

from pydantic import BaseModel, Field, field_validator

from .registry import ModelSpec, Registry

# Quality-booster tokens. These exist because the registry's own dialect text
# tells us to reject them: Z-Image-Turbo's prose says "No prompt-engineering
# keywords, no quality booster tokens, no comma salad", and FLUX.2-klein's
# says it "rewards brevity over elaboration". Stripping them is how the
# translator honours that instruction instead of merely restating it.
BOOSTER_TOKENS: tuple[str, ...] = (
    "masterpiece",
    "best quality",
    "highest quality",
    "high quality",
    "4k",
    "8k",
    "uhd",
    "ultra detailed",
    "highly detailed",
    "incredibly detailed",
    "extremely detailed",
    "trending on artstation",
    "award-winning",
    "award winning",
)

# Longest first, so "highest quality" is tried before "high quality" and the
# whole phrase is removed rather than a fragment of it.
_BOOSTER_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(token) for token in sorted(BOOSTER_TOKENS, key=len, reverse=True))
    + r")(?!\w)",
    re.IGNORECASE,
)

# Placeholder that protects the user's verbatim text from the booster pass.
# The text may legitimately contain a word like "masterpiece"; the prompt has
# to carry it unchanged.
_TEXT_SENTINEL = "\ue000tiiny-verbatim-text\ue001"


class SceneDescription(BaseModel):
    """The structured output the planning LLM produces.

    ``text`` holds the exact words to render. It is copied into the prompt
    verbatim, never paraphrased and never re-cased.
    """

    subject: str
    modifiers: tuple[str, ...] = ()
    lighting: str = ""
    mood: str = ""
    text: str | None = None
    text_placement: str | None = None
    extra: str = ""

    @field_validator("subject")
    @classmethod
    def subject_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("subject must not be empty")
        return value


class PromptPlan(BaseModel):
    """The finished prompt and everything the UI needs to explain it."""

    prompt: str
    model_id: str
    dialect: str
    size_requested: str
    size_used: str
    size_adjusted: bool
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class DialectProfile:
    """How one family of models wants to be spoken to."""

    name: str
    compose: Callable[[SceneDescription], str]
    strip_boosters: bool
    max_words: int | None = None


# --------------------------------------------------------------------------
# composition helpers
# --------------------------------------------------------------------------


def _present(parts: Iterable[str]) -> list[str]:
    """The non-empty parts, trimmed."""
    return [part.strip() for part in parts if part and part.strip()]


def _sentence_case(text: str) -> str:
    """Capitalise the opening word of a sentence.

    ``a red fox`` becomes ``A red fox`` and ``snow-covered pines`` becomes
    ``Snow-covered pines``. ``iPhone`` and ``35mm`` are left alone: a word
    that already carries a capital, or a number, is not touched.
    """
    first, separator, rest = text.partition(" ")
    for index, character in enumerate(first):
        if not character.isalpha():
            continue
        if index == 0 or not first[index - 1].isalnum():
            if character.islower() and not any(c.isupper() for c in first):
                first = first[:index] + character.upper() + first[index + 1:]
        break
    return first + separator + rest


def _finish(text: str) -> str:
    """Close the prompt as a sentence."""
    text = text.strip().rstrip(" ,;")
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return _sentence_case(text)


def _with_article(placement: str) -> str:
    """``top banner`` -> ``The top banner``; ``the base`` stays as it is."""
    if placement.lower().startswith("the "):
        return placement
    return f"The {placement}"


def _in_place(placement: str) -> str:
    """``top banner`` -> ``in the top banner``, without doubling articles."""
    lowered = placement.lower()
    if lowered.startswith(("in ", "on ", "at ", "inside ", "within ", "across ")):
        return placement
    if lowered.startswith("the "):
        return f"in {placement}"
    return f"in the {placement}"


def _text_phrase(scene: SceneDescription) -> str:
    """The user's words as a quoted phrase, untouched inside the quotes."""
    if not scene.text:
        return ""
    return f'with the text "{scene.text}"'


# --------------------------------------------------------------------------
# the profiles
# --------------------------------------------------------------------------


def _compose_conversational(scene: SceneDescription) -> str:
    """One flowing sentence. The registry's own example is a single sentence."""
    parts = _present(
        [scene.subject, *scene.modifiers, scene.lighting, scene.mood, scene.extra]
    )
    text_phrase = _text_phrase(scene)
    if text_phrase:
        parts.append(text_phrase)
    return _finish(", ".join(parts))


def _compose_descriptive(scene: SceneDescription) -> str:
    """Subject first, then modifiers, then lighting and mood, as short sentences.

    The dialect takes no free-form extra: the order is the instruction, and
    the model is told to avoid comma salad.
    """
    sentences = []
    for part in _present([scene.subject, *scene.modifiers, scene.lighting, scene.mood]):
        sentences.append(_sentence_case(part.rstrip(" .")) + ".")
    text_phrase = _text_phrase(scene)
    if text_phrase:
        sentences.append(_sentence_case(text_phrase[0].upper() + text_phrase[1:]) + ".")
    return " ".join(sentences)


def _compose_dense(scene: SceneDescription) -> str:
    """Everything the scene knows, in one dense sentence."""
    parts = _present(
        [scene.subject, *scene.modifiers, scene.lighting, scene.mood, scene.extra]
    )
    text_phrase = _text_phrase(scene)
    if text_phrase:
        parts.append(text_phrase)
    return _finish(", ".join(parts))


def _compose_literal_short(scene: SceneDescription) -> str:
    """Subject and at most two modifiers. Nothing else."""
    parts = _present([scene.subject, *list(scene.modifiers)[:2]])
    text_phrase = _text_phrase(scene)
    if text_phrase:
        parts.append(text_phrase)
    return _finish(", ".join(parts))


def _compose_layout(scene: SceneDescription) -> str:
    """Layout and text first, then the visual description."""
    if scene.text:
        if scene.text_placement:
            head = f'{_with_article(scene.text_placement)} reads "{scene.text}"'
        else:
            head = f'Title reads "{scene.text}"'
    else:
        head = ""
    visual = _present(
        [scene.subject, *scene.modifiers, scene.lighting, scene.mood, scene.extra]
    )
    parts = _present([head, ", ".join(visual)])
    return _finish(", ".join(parts))


def _compose_instruction(scene: SceneDescription) -> str:
    """An instruction: what to put, where it goes, how it should read."""
    visual = _present(
        [scene.subject, *scene.modifiers, scene.lighting, scene.mood, scene.extra]
    )
    parts = ["Create an image of " + ", ".join(visual)]
    if scene.text:
        if scene.text_placement:
            placement = _in_place(scene.text_placement)
        else:
            placement = ""
        if placement:
            parts.append(
                f'The text "{scene.text}" should read clearly and sit {placement}.'
            )
        else:
            parts.append(f'The text "{scene.text}" should read clearly.')
    return _finish(" ".join(parts))


def _compose_sheet(scene: SceneDescription) -> str:
    """An explicit request for a character design sheet."""
    subject = scene.subject.strip()
    detail = _present([*scene.modifiers, scene.lighting, scene.mood, scene.extra])
    panels = [
        "multiple views",
        "expression variants",
        "and a palette swatch",
        "one character consistent across all panels",
    ]
    parts = [f"Character design sheet of {subject}"]
    parts.append(", ".join(detail + panels))
    text_phrase = _text_phrase(scene)
    if text_phrase:
        parts.append(text_phrase)
    return _finish(", ".join(parts))


def _compose_edit(scene: SceneDescription) -> str:
    """An instruction about the input image, never a claim to generate one."""
    parts = _present([scene.subject, *scene.modifiers, scene.extra])
    prompt = "Edit the input image: " + ", ".join(parts)
    text_phrase = _text_phrase(scene)
    if text_phrase:
        prompt += ", " + text_phrase
    return _finish(prompt)


_CONVERSATIONAL = DialectProfile(
    name="conversational",
    compose=_compose_conversational,
    strip_boosters=False,
    max_words=None,
)

_DESCRIPTIVE = DialectProfile(
    name="descriptive",
    compose=_compose_descriptive,
    strip_boosters=True,
    max_words=None,
)

_DENSE = DialectProfile(
    name="dense",
    compose=_compose_dense,
    strip_boosters=False,
    max_words=None,
)

_LITERAL_SHORT = DialectProfile(
    name="literal_short",
    compose=_compose_literal_short,
    strip_boosters=True,
    max_words=16,
)

_LAYOUT = DialectProfile(
    name="layout",
    compose=_compose_layout,
    strip_boosters=False,
    max_words=None,
)

_INSTRUCTION = DialectProfile(
    name="instruction",
    compose=_compose_instruction,
    strip_boosters=False,
    max_words=None,
)

_SHEET = DialectProfile(
    name="sheet",
    compose=_compose_sheet,
    strip_boosters=False,
    max_words=None,
)

_EDIT = DialectProfile(
    name="edit",
    compose=_compose_edit,
    strip_boosters=False,
    max_words=None,
)

# Every generator in the registry, and the dialect it speaks. The mapping is
# explicit rather than inferred: the registry's prose is guidance for a
# human, and the tests check that each model's prose still agrees with the
# profile it is given here.
DIALECT_PROFILES: dict[str, DialectProfile] = {
    # conversational
    "Qwen/Qwen-Image-2.1": _CONVERSATIONAL,
    "abenzerps/Qwen-Image-2.1-Uncensored-Quantized": _CONVERSATIONAL,
    # descriptive
    "Tongyi-MAI/Z-Image-Turbo": _DESCRIPTIVE,
    "Tongyi-MAI/Z-Image-Turbo-Children-Drawing": _DESCRIPTIVE,
    # dense
    "TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic": _DENSE,
    "HiDream-ai/HiDream-O1-Image-Dev": _DENSE,
    # literal and short
    "black-forest-labs/FLUX.2-klein-4B": _LITERAL_SHORT,
    # layout and typography
    "baidu/ERNIE-Image-Turbo": _LAYOUT,
    # instruction shaped
    "SenseTime/SenseNova-U1.5-8B-MoT": _INSTRUCTION,
    # character sheet
    "YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet": _SHEET,
    # edit adapters
    "fal/FLUX.2-klein-4B-Background-Remove": _EDIT,
    "fal/FLUX.2-klein-4B-Object-Remove": _EDIT,
    "fal/FLUX.2-klein-4B-Outpaint": _EDIT,
    "fal/FLUX.2-klein-4B-Zoom": _EDIT,
}


# --------------------------------------------------------------------------
# booster stripping
# --------------------------------------------------------------------------


def _tidy(text: str) -> str:
    """Repair the punctuation a removed token leaves behind.

    Removing a whole modifier leaves an empty slot: a dangling comma in a
    comma-joined prompt, or a sentence with nothing in it. Both are put
    back together here.
    """
    text = re.sub(r"\s+", " ", text).strip()
    # empty sentences and doubled full stops
    text = re.sub(r"\.(\s*\.)+", ".", text)
    # a leading orphan full stop
    text = re.sub(r"^\.\s*", "", text)
    # empty comma slots
    text = re.sub(r"(?:\s*,\s*)+,", ",", text)
    # a comma in front of a full stop
    text = re.sub(r"\s*,\s*(?=[.;:!?])", "", text)
    # a comma with nothing before it
    text = re.sub(r"^\s*,\s*", "", text)
    # space in front of punctuation
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    # leading and trailing leftovers
    text = re.sub(r"^[\s,;:]+", "", text)
    text = re.sub(r"[\s,;:]+$", "", text)
    return text.strip()


def _strip_boosters(text: str, protected: str | None) -> tuple[str, list[str]]:
    """Remove booster tokens as whole words, leaving the user's text alone."""
    masked = text
    if protected:
        masked = masked.replace(protected, _TEXT_SENTINEL)
    removed: list[str] = []

    def _drop(match: re.Match[str]) -> str:
        removed.append(match.group(0).lower())
        return ""

    cleaned = _tidy(_BOOSTER_RE.sub(_drop, masked))
    if protected:
        cleaned = cleaned.replace(_TEXT_SENTINEL, protected)
    return cleaned, sorted(set(removed))


# --------------------------------------------------------------------------
# size enforcement
# --------------------------------------------------------------------------


def _parse_size(size: str) -> tuple[int, int]:
    width, height = size.lower().split("x")
    return int(width), int(height)


def _nearest_verified(requested: str, verified: list[str]) -> str:
    """The closest verified size: area first, then aspect ratio, then order."""
    request_width, request_height = _parse_size(requested)
    request_area = request_width * request_height
    request_ratio = Fraction(request_width, request_height)

    best_key: tuple[int, Fraction] | None = None
    best_size = verified[0]
    for size in verified:
        width, height = _parse_size(size)
        key = (
            abs(width * height - request_area),
            abs(Fraction(width, height) - request_ratio),
        )
        # Strictly smaller keeps the earlier entry when two sizes tie.
        if best_key is None or key < best_key:
            best_key = key
            best_size = size
    return best_size


class DialectTranslator:
    """Turns a SceneDescription into a model-specific PromptPlan."""

    def __init__(self, registry: Registry):
        self.registry = registry
        # Generators with no profile would fail at generation time, so they
        # are named here where the mistake can be seen.
        self.uncovered_model_ids: tuple[str, ...] = tuple(
            model.id for model in registry.generators if model.id not in DIALECT_PROFILES
        )

    # -- profile lookup ----------------------------------------------------

    def profile_for(self, model: ModelSpec) -> DialectProfile:
        """The dialect profile for a model."""
        try:
            return DIALECT_PROFILES[model.id]
        except KeyError:
            raise ValueError(f"no dialect profile for model {model.id!r}") from None

    # -- composition -------------------------------------------------------

    def _compose(
        self, scene: SceneDescription, profile: DialectProfile
    ) -> tuple[str, list[str]]:
        """Compose, then strip the boosters this model's dialect rejects."""
        prompt = profile.compose(scene)
        if not profile.strip_boosters:
            return prompt, []
        return _strip_boosters(prompt, scene.text)

    def _fit_budget(
        self, scene: SceneDescription, profile: DialectProfile
    ) -> tuple[str, list[str], list[str]]:
        """Bring the prompt inside a model's brevity target.

        The user's text is never touched: if the text alone does not fit, the
        text wins and the overflow is reported.
        """
        notes: list[str] = []
        prompt, removed = self._compose(scene, profile)
        if profile.max_words is None or len(prompt.split()) <= profile.max_words:
            return prompt, notes, removed

        reduced = scene.model_copy(update={"modifiers": ()})
        shorter, removed = self._compose(reduced, profile)
        if len(shorter.split()) <= profile.max_words:
            notes.append("Dropped the modifiers to fit the model's brevity target.")
            return shorter, notes, removed

        subject_words = scene.subject.split()
        overhead = len(shorter.split()) - len(subject_words)
        keep = max(profile.max_words - overhead, 1)
        trimmed = scene.model_copy(
            update={"subject": " ".join(subject_words[:keep]), "modifiers": ()}
        )
        shortest, removed = self._compose(trimmed, profile)
        if len(shortest.split()) <= profile.max_words:
            notes.append("Shortened the subject to fit the model's brevity target.")
        else:
            notes.append(
                "Shortened the subject to fit the model's brevity target; the "
                "requested text is longer than the target allows and is kept "
                "verbatim."
            )
        return shortest, notes, removed

    # -- sizes -------------------------------------------------------------

    def _resolve_size(
        self, model: ModelSpec, requested: str
    ) -> tuple[str, bool, list[str]]:
        """The size to send, whether it moved, and why."""
        verified = [size for size in model.sizes_verified]
        rejected = list(model.sizes_rejected)
        reason = model.rejected_reason
        rule = model.size_rule or ""

        if not verified:
            return (
                requested,
                False,
                [
                    f"{model.id} declares no verified output sizes, "
                    f"so the requested {requested} is used as-is."
                ],
            )

        if requested in verified and requested not in rejected:
            return requested, False, []

        candidates = [size for size in verified if size not in rejected]
        if not candidates:
            return (
                requested,
                False,
                [
                    f"{model.id} rejects every size it lists as verified; "
                    f"the requested {requested} is passed through unchanged."
                ],
            )

        size_used = _nearest_verified(requested, candidates)
        if requested in rejected:
            note = f"The requested size {requested} is rejected by {model.id}"
            if reason:
                note += f" ({reason})"
            note += f"; using the nearest verified size {size_used} instead."
        else:
            note = (
                f"The requested size {requested} is not verified for {model.id}; "
                f"using the nearest verified size {size_used} instead."
            )
        notes = [note]
        if rule:
            notes.append(f"Size rule for {model.id}: {rule}")
        return size_used, True, notes

    # -- the public entry point --------------------------------------------

    def translate(
        self,
        scene: SceneDescription,
        model: ModelSpec,
        width: int = 1024,
        height: int = 1024,
    ) -> PromptPlan:
        """Write the prompt for this scene, on this model, at this size."""
        profile = self.profile_for(model)
        prompt, notes, removed = self._fit_budget(scene, profile)

        if profile.max_words is not None and len(scene.modifiers) > 2:
            # The profile composes at most two modifiers; say so when it
            # actually had more to work with and at least one survived.
            kept = [m for m in scene.modifiers[:2] if m]
            if kept and any(m in prompt for m in kept):
                notes.append(
                    "Kept only the first two modifiers; this model rewards brevity."
                )
        if removed:
            notes.append(
                "Removed prompt-engineering booster tokens this model's dialect rejects: "
                + ", ".join(removed)
                + "."
            )

        requested = f"{width}x{height}"
        size_used, size_adjusted, size_notes = self._resolve_size(model, requested)
        notes.extend(size_notes)

        return PromptPlan(
            prompt=prompt,
            model_id=model.id,
            dialect=model.dialect,
            size_requested=requested,
            size_used=size_used,
            size_adjusted=size_adjusted,
            notes=notes,
        )
