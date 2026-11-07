"""The planner: English in, a requirement vector out.

This is the ONE piece of the product the LLM is allowed to touch, and the
only thing it is allowed to do is READ ENGLISH. The model does not pick an
image model — it says what the sentence wants, and the resolver then picks
the model, deterministically, from the registry, where every explainable
decision in the product lives.

There are exactly two ways to produce a vector, and the second one is not a
degraded mode:

  the model      a 30B model on the appliance reads the request and answers
                 with one JSON object.
  the fallback   a deterministic keyword pass over the request text.

The fallback exists because the appliance is ONE inference stream: the
planner can be evicted, be busy, or not be loaded at all, and a request
that cannot be planned is a request that cannot be served. The fallback is
deliberately CONSERVATIVE — it names a signal only when the request states
it, and leaves the requirement vector's default alone otherwise. A missing
signal costs a slightly worse model; a wrong one costs the request.

The registry is the vocabulary. The prompt lists the artifacts and the
styles the catalogue declares, and the fallback may only name a style the
catalogue declares: the resolver treats a style it cannot match as a filter
that removes every candidate, so inventing one would leave the request with
no model to generate with.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .models import Artifact, EditOp, RequirementVector
from .registry import Registry

if TYPE_CHECKING:
    from .device import Device


class PlannerError(RuntimeError):
    """The request could not be turned into a requirement vector."""


@dataclass(frozen=True)
class Plan:
    """One extracted requirement vector, and where it came from."""

    requirements: RequirementVector
    #: "llm" when the model produced the vector, "fallback" when the
    #: keyword planner did.
    source: str
    #: The model's reply, verbatim. It is kept even when the reply is
    #: unusable, because the lineage should show what the model actually
    #: said — the prose, the stray fence, the invalid alpha — rather than
    #: hiding it behind a silent default.
    raw: str


#: The style the registry uses to mean "this model has no style". It is a
#: PLACEHOLDER, not a choice: the edit adapters and the prompt enhancers
#: carry it, because a background-removal pass has no style of its own.
#: Offering it in the prompt would let the model ask for a style that only
#: those models declare - which would select an adapter that transforms an
#: existing image and cannot generate one.
NO_STYLE = "n/a"

#: The alpha values, and what each one asks of the appliance.
ALPHA_VALUES: tuple[str, ...] = ("required", "preferred", "no")

#: The text-in-image values. The same three answers as alpha: the feature
#: is required, it is welcome, or it is unwanted.
TEXT_VALUES: tuple[str, ...] = ("required", "preferred", "no")

#: The speed values. They are a preference, not a promise: the resolver
#: weighs them, and the occupancy it reports is what actually happens.
SPEED_VALUES: tuple[str, ...] = ("fastest", "normal", "quality_first")

#: The edit operations. "none" is the usual answer and means the request
#: is for a new image.
EDIT_OP_VALUES: tuple[str, ...] = (
    "none",
    "background_remove",
    "object_remove",
    "outpaint",
    "detail_regen",
)

#: A one-word description of each artifact, for the prompt. The registry
#: declares the vocabulary but does not describe it, and a model asked to
#: choose between bare nouns guesses.
ARTIFACT_DESCRIPTIONS: dict[str, str] = {
    "icon": "symbol",
    "logo": "brandmark",
    "sticker": "diecut",
    "infographic": "chart",
    "poster": "print",
    "comic": "panels",
    "character_sheet": "turnaround",
    "texture": "surface",
    "cutout": "isolated",
    "photo": "photograph",
    "illustration": "drawing",
    "edit": "transformation",
}

#: The fallback's artifact words, in the order they are tried. The order is
#: the priority: a request that says "icon" and "picture" wants the icon.
ARTIFACT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("icon", ("icon",)),
    ("logo", ("logo",)),
    ("sticker", ("sticker",)),
    ("infographic", ("infographic",)),
    ("poster", ("poster",)),
    ("comic", ("comic",)),
    ("character_sheet", ("character sheet",)),
    ("texture", ("texture",)),
    ("cutout", ("cutout", "cut out")),
    ("photo", ("photo", "photograph", "photorealistic")),
    ("illustration", ("illustration", "drawing", "picture")),
)

#: The words that ask for a transparent background outright.
ALPHA_REQUIRED_WORDS: tuple[str, ...] = (
    "transparent",
    "transparency",
    "no background",
    "background removed",
)

#: The words that ask for an alpha channel without insisting on it.
ALPHA_PREFERRED_WORDS: tuple[str, ...] = ("with alpha",)

#: The words that ask for words in the image.
TEXT_REQUIRED_WORDS: tuple[str, ...] = (
    "with text",
    "lettering",
    "words",
    "typography",
    "a label",
)

#: The fallback's style words. A style the catalogue does not declare is
#: never used: the resolver filters out every model that does not declare
#: the requested style, so an invented one leaves nothing to generate with.
STYLE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flat", ("flat",)),
    ("crayon", ("crayon",)),
    ("photoreal", ("photoreal", "photorealistic", "realistic")),
    ("illustrated", ("cartoon", "illustrated")),
    ("layout", ("layout",)),
)

#: The fallback's speed words.
SPEED_WORDS: tuple[
    tuple[Literal["fastest", "normal", "quality_first"], tuple[str, ...]], ...,
] = (
    ("fastest", ("fastest", "as fast as possible", "quick")),
    ("quality_first", ("best quality", "highest quality", "quality first")),
)

#: The edit operations the appliance has models for, and the words that
#: name them.
#:
#: The order matters: the first match wins, so the specific operations
#: come before the general one. Without it, "remove the background"
#: would read as an object removal — which is not the same job, and is
#: served by a different model.
#:
#: These words made the edit adapters reachable. Until the planner could
#: name an edit operation, the resolver's edit handling existed but
#: nothing could ever enter it: the requirement vector's edit_op was
#: always "none", every edit adapter was excluded as a candidate, and a
#: request to remove a background was answered by a general image model.
EDIT_OP_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("background_remove", (
        "remove the background",
        "remove background",
        "cut out the background",
        "isolate the subject",
    )),
    ("outpaint", (
        "outpaint",
        "out paint",
        "extend the image",
        "extend the canvas",
        "extend the picture",
    )),
    ("detail_regen", (
        "detail regeneration",
        "regenerate the detail",
        "add more detail",
        "add detail",
    )),
    ("object_remove", (
        "remove the object",
        "remove the ",
        "erase the ",
        "take out the ",
    )),
)

#: A markdown fence, with or without the language tag. A 30B model wraps
#: its JSON in one often enough that the fence has to be looked for.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _numeric(value: object) -> bool:
    """Whether a value is a number, or a string that spells one."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return False
        return True
    return False


def _positive_int(value: object, default: int) -> int:
    """A size the requirement vector can hold."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


class Planner:
    """Turns a request into a requirement vector.

    The device and the model id are injected, and the registry is the
    vocabulary: the prompt lists what the catalogue declares, and the
    fallback may only name a style the catalogue declares.
    """

    def __init__(self, device: Device, model_id: str, registry: Registry):
        self.device = device
        self.model_id = model_id
        self.registry = registry

    # -- the public entry point -------------------------------------------

    def plan(self, request: str, width: int = 1024, height: int = 1024) -> Plan:
        """Plan one request.

        The only failure that reaches the caller is an empty request: a
        request with no words in it is a caller's mistake, and no amount of
        planning can repair it. Everything else — the planner not being
        resident, the call raising, a reply that is prose, a reply whose
        alpha is not a value the vector accepts — falls back to the keyword
        planner, because a request that cannot be planned is a request
        that cannot be served.
        """
        if not request or not request.strip():
            raise PlannerError("the request is empty")

        width = _positive_int(width, 1024)
        height = _positive_int(height, 1024)

        try:
            reply = self._ask(request, width, height)
        except Exception:
            # The appliance could not be asked at all: the planner is not
            # resident, the call failed, the reply was not the shape a
            # chat answer has. There is no reply to keep, so the lineage
            # shows nothing rather than something invented.
            reply = ""

        if reply:
            try:
                requirements = self._vector(reply, width, height)
            except Exception:
                requirements = None
            if requirements is not None:
                return Plan(requirements=requirements, source="llm", raw=reply)

        return Plan(
            requirements=self._fallback(request, width, height),
            source="fallback",
            raw=reply,
        )

    # -- the model ---------------------------------------------------------

    def _ask(self, request: str, width: int, height: int) -> str:
        """Ask the model and take its reply, verbatim."""
        response = self.device.chat(
            self.model_id, self._prompt(request, width, height)
        )
        content = response["choices"][0]["message"]["content"]
        # A reply that is not text is not a reply; the caller is answered
        # by the keyword planner rather than by a stringified None.
        return content if isinstance(content, str) else ""

    def _vector(self, reply: str, width: int, height: int) -> RequirementVector:
        """Turn the reply into a requirement vector, or raise.

        The reply is parsed defensively and then validated through the
        real RequirementVector, so the defaults and the deliberate
        tolerance for an unknown artifact apply exactly as they do
        everywhere else.
        """
        data = _json_object(reply)
        if not isinstance(data, dict):
            raise ValueError("the reply holds no JSON object")

        fields = dict(data)
        for key in ("width", "height"):
            if key in fields and not _numeric(fields[key]):
                # A size that is not a number at all is the model saying
                # something incoherent, and a reply that incoherent is not
                # one to half-trust.
                raise ValueError(f"the model's {key} is not a number")

        # The caller owns the size. The model is told what size to use, and
        # its answer is kept as evidence rather than obeyed.
        fields["width"] = width
        fields["height"] = height
        return RequirementVector.model_validate(fields)

    # -- the keyword planner ------------------------------------------------

    def _fallback(self, request: str, width: int, height: int) -> RequirementVector:
        """Extract the intent from the words alone.

        Conservative on purpose: a signal the request does not state is
        left at the vector's default, because a wrong signal is worse than
        a missing one. An invented alpha requirement, for instance, filters
        out every model that cannot render one and leaves the request with
        nothing to generate with.
        """
        text = request.lower()
        edit_op = self._edit_op(text)
        artifact = self._artifact(text)
        if edit_op is not EditOp.NONE:
            # An edit is not a new image. The artifact follows the
            # operation: a background removal yields a cutout, every other
            # edit yields an edit.
            artifact = (Artifact.CUTOUT if edit_op is EditOp.BACKGROUND_REMOVE
                        else Artifact.EDIT)
        return RequirementVector(
            artifact=artifact,
            alpha=self._alpha(text),
            text_in_image=self._text(text),
            style=self._style(text),
            speed=self._speed(text),
            edit_op=edit_op,
            width=width,
            height=height,
        )

    def _artifact(self, text: str) -> Artifact:
        for artifact, words in ARTIFACT_WORDS:
            if any(word in text for word in words):
                return Artifact(artifact)
        return Artifact.ILLUSTRATION

    def _alpha(self, text: str) -> Literal["required", "preferred", "no"]:
        # Transparency asked for outright wins over an alpha channel asked
        # for as a preference: the first is a requirement, the second is a
        # nicety.
        if any(word in text for word in ALPHA_REQUIRED_WORDS):
            return "required"
        if any(word in text for word in ALPHA_PREFERRED_WORDS):
            return "preferred"
        return "no"

    def _text(self, text: str) -> Literal["required", "preferred", "no"]:
        if any(word in text for word in TEXT_REQUIRED_WORDS):
            return "required"
        return "no"

    def _style(self, text: str) -> str:
        vocabulary = self.style_vocabulary()
        for style, words in STYLE_WORDS:
            if style not in vocabulary:
                # The catalogue does not declare this style, so naming it
                # would filter out every model in the catalogue.
                continue
            if any(word in text for word in words):
                return style
        return "general"

    def _speed(self, text: str) -> Literal["fastest", "normal", "quality_first"]:
        for speed, words in SPEED_WORDS:
            if any(word in text for word in words):
                return speed
        return "normal"

    def _edit_op(self, text: str) -> EditOp:
        """The edit operation the request asks for, if any."""
        for op, words in EDIT_OP_WORDS:
            if any(word in text for word in words):
                return EditOp(op)
        return EditOp.NONE

    # -- the vocabulary -----------------------------------------------------

    def artifact_vocabulary(self) -> list[str]:
        """Every artifact the IMAGE GENERATORS declare, sorted.

        The generators only, and not the whole registry. The catalogue
        also holds the prompt enhancers, whose declared speciality is
        "prompt_expansion" — an operation on a prompt, not a thing a user
        asks an image to BE. Offering it would let the model answer
        "I need a better prompt for my fox image" with the artefact of a
        prompt expansion, and the resolver would then quietly discard the
        choice and generate an illustration instead, leaving the caller
        with a result that does not match what was planned.
        """
        return sorted({
            artifact
            for model in self.registry.generators
            for artifact in model.artifact
        })

    def style_vocabulary(self) -> list[str]:
        """Every style the IMAGE GENERATORS declare, sorted.

        For the same reason as the artifacts. The enhancers declare a
        style of "n/a", and a model offered "n/a" as a style would be
        offering a placeholder as if it were a choice.
        """
        return sorted({
            style
            for model in self.registry.generators
            for style in model.style
            if style != NO_STYLE
        })

    # -- the prompt ---------------------------------------------------------

    def _prompt(self, request: str, width: int, height: int) -> str:
        """The prompt that asks for one JSON object and nothing else."""
        artifacts = self.artifact_vocabulary()
        styles = self.style_vocabulary()

        lines = [
            "You are the planner for an image agency. Read the request and "
            "reply with ONE JSON object and nothing else: no prose before "
            "it, no prose after it, no explanation, no markdown fence.",
            "",
            "THE REQUEST",
            request,
            "",
            "THE ARTIFACTS",
        ]
        for artifact in artifacts:
            description = ARTIFACT_DESCRIPTIONS.get(artifact, "image")
            lines.append(f"{artifact}: {description}")
        lines += [
            "Choose exactly one artifact from the list above, the one the "
            "request is really about.",
            "",
            "THE STYLES",
        ]
        lines += styles
        lines += [
            "Choose exactly one style from the list above, or \"general\" "
            "when none of them fits.",
            "",
            "THE VALUES",
            "alpha: " + " | ".join(ALPHA_VALUES),
            "  required - the image must have a transparent background",
            "  preferred - a transparent background is wanted but not "
            "essential",
            "  no - an opaque background is fine",
            "text_in_image: " + " | ".join(TEXT_VALUES),
            "  required - words must appear in the image",
            "  preferred - words are welcome but not required",
            "  no - no text in the image",
            "speed: " + " | ".join(SPEED_VALUES),
            "  fastest - the quickest generation that will do",
            "  normal - the balanced default",
            "  quality_first - the highest fidelity available",
            "edit_op: " + " | ".join(EDIT_OP_VALUES),
            "  none - the request is for a NEW image, which is the usual case",
            "  background_remove - take the background out of an existing image",
            "  object_remove - take one thing out of an existing image",
            "  outpaint - extend the canvas of an existing image",
            "  detail_regen - redo a part of an existing image in more detail",
            "When the request asks for an existing image to be CHANGED, name "
            "the operation in edit_op and set the artifact to \"cutout\" for a "
            "background removal or \"edit\" for anything else. When the "
            "request is to make a new image, edit_op is \"none\".",
            "hard: a list of short constraint strings, for example "
            "[\"native_alpha\"], or an empty list. Only name a constraint "
            "the request insists on.",
            "",
            "THE SIZE",
            f"width: {width}",
            f"height: {height}",
            "The size is given to you and must be used: report these exact "
            "numbers.",
            "",
            "REPLY WITH ONE JSON OBJECT AND NOTHING ELSE, with these keys:",
            '{"artifact": "<one artifact>", "alpha": "<required|preferred|no>",'
            ' "text_in_image": "<required|preferred|no>",'
            ' "style": "<one style>", "speed": "<fastest|normal|quality_first>",'
            ' "edit_op": "<none|background_remove|object_remove|outpaint|detail_regen>",'
            f' "hard": [], "width": {width}, "height": {height}}}',
        ]
        return "\n".join(lines)


def _json_object(reply: str) -> Any:
    """Pull the JSON object out of a reply.

    A 30B model writes JSON, but it also writes prose and markdown, so the
    reply is searched in the order a model tends to break it: a fenced
    block first, and the outermost braces otherwise.
    """
    match = _FENCE.search(reply)
    if match:
        text = match.group(1)
    else:
        start = reply.find("{")
        end = reply.rfind("}")
        if start < 0 or end < start:
            raise ValueError("the reply contains no JSON object")
        text = reply[start:end + 1]
    return json.loads(text)
