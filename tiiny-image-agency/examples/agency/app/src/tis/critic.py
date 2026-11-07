"""The critic: does the image satisfy the requirement vector?

The critic judges against the REQUIREMENT VECTOR, not the user's original
words. The user said "a fox"; the vector says artifact=icon,
alpha=required; the critic judges the ICON — because the icon is what was
asked for, not the fox.

A KNOWN LIMITATION, STATED PLAINLY
----------------------------------
``Device.chat`` sends text. The judge therefore cannot see the PNG. It
judges the requirement vector against the prompt that produced the image,
which catches a great deal — a prompt that forgot the transparency
requirement, a prompt with no text where text was required, the wrong
artifact — but it cannot catch a generation that simply came out wrong.

The appliance's planner model is an image-text-to-text model, and the
device's API is OpenAI-compatible, so the judge's reply can be given the
image as a multimodal content part. That is the next step, and it is a
change to the device protocol rather than to this module. Until then the
critic is a prompt critic, and the orchestrator's retry loop treats its
verdict accordingly: it is worth a second attempt, but a judge that cannot
see the image must not be the last word.

THE PROMPT IS NOT OPTIONAL
---------------------------
The first live run found this. The judge was given the requirement
vector and nothing else — no prompt, no image — and asked for a verdict.
With no evidence to reason from, it invented a defect: it reported "the
image has a transparent background" for a request that asked for a solid
one, the orchestrator regenerated, and the judge invented it again. Three
generations, 162 seconds of appliance time, chasing a complaint about an
image neither of them had seen.

So the judge is given the prompt, and it is told plainly that it cannot
see the image and must not invent a defect it cannot see. A defect it
reports is not a note — it is an instruction to regenerate.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .device import Device
    from .models import RequirementVector


#: A change that asks for the OUTPUT's dimensions is unusable, and
#: sometimes worse than unusable: the size is passed to the model as an
#: argument, not written into the prompt, so a prompt that mentions
#: "1024x1024" makes the model DRAW the numbers as text.
#:
#: It happened. A judge asked for "1024x1024" to be added to the prompt,
#: and the delivered image had "Alowiobe 1024x1004" written across it -
#: one wasted generation and a ruined picture.
#:
#: The pattern is deliberately narrow. Bare words like "resolution" and
#: "size" are NOT matched, because they appear in legitimate art
#: direction ("a grainy low-resolution photograph") and dropping those
#: would throw away real advice. What is matched is a request for the
#: output's dimensions, in any of the ways one is written.
_DIMENSION_CHANGE = re.compile(
    r"\d+\s*[x×]\s*\d+"                          # 1024x1024, 1024 x 1024
    r"|\b(?:image|output|picture|canvas|render)\s+(?:size|dimensions?)\b"
    r"|\bdimensions?\s+(?:of|should|to|must|at)\b"
    r"|\b(?:at|to)\s+\d+\s*(?:by|x)\s*\d+\b"     # at 1024 by 1024
    r"|\b(?:pixel|megapixel)\s+(?:size|count|dimensions?)\b",
    re.IGNORECASE,
)


def _is_usable_change(change: str) -> bool:
    """Can this change be appended to the prompt and sent to the model?

    A change that asks for the output's dimensions cannot: the model
    already has the size as an argument, and the prompt repeating it
    makes the model draw the numbers.
    """
    return not _DIMENSION_CHANGE.search(change)


class Critique(BaseModel):
    """The judge's verdict on one image."""

    passed: bool
    inconclusive: bool
    reasons: list[str]
    suggested_changes: list[str]
    raw: str


class Critic:
    """Judges a generated image against the requirement vector.

    A critic with `vision` can SEE the image. One without, judges the
    prompt that produced it.

    Both are useful, and the difference is the whole story of the
    first live run: a blind judge was given the requirement vector and
    nothing else, invented a defect, and the orchestrator regenerated
    against the invention. Three generations chasing a complaint about
    an image neither of them had seen.

    A judge that can see catches what a judge that can only read
    structurally cannot - a generation that simply came out wrong.
    """

    def __init__(self, device: Device, model_id: str, vision: bool = False):
        self.device = device
        self.model_id = model_id
        #: Whether this judge can accept an IMAGE as well as text.
        self.vision = vision

    def judge(self, image: bytes, requirements: RequirementVector,
              prompt: str = "") -> Critique:
        """Judge the image.

        The judge is asked to answer in exactly one format, and the reply is
        parsed line by line. A reply with no VERDICT line is INCONCLUSIVE -
        that is a broken judge, not a failed image, and it must not make the
        orchestrator burn its retries.

        A DeviceError propagates. If the judge is not resident, that is a
        real fault the caller needs to see; the orchestrator checks residency
        before it judges so it never reaches here in that state.

        ``prompt`` is the prompt that produced this image. For a BLIND
        judge it is the only evidence it has - without it, the judge is asked
        to reach a verdict on nothing at all, and what it does then is invent
        a defect. For a judge that can SEE, the image is the evidence and
        the prompt is the context that says what the image was meant to be.
        """
        judge_prompt = self._judge_prompt(requirements, prompt, self.vision)
        if self.vision:
            # The image goes with the question. The appliance's chat API
            # is OpenAI-compatible and its own models are
            # image-text-to-text, so an image can be handed to them as a
            # content part.
            answer = self.device.vision(self.model_id, judge_prompt, image)
            return self._parse(answer)
        response = self.device.chat(self.model_id, judge_prompt)
        reply = response["choices"][0]["message"]["content"]
        return self._parse(reply)

    def _judge_prompt(self, requirements: RequirementVector,
                      prompt: str = "", vision: bool = False) -> str:
        if vision:
            # A judge that can SEE must not be told it cannot. Telling it
            # so would make it reason about the prompt anyway - and it
            # would be reasoning about a picture it is looking at.
            opening = (
                "You are judging an IMAGE against a requirement "
                "specification.\n"
                "You CAN see the image - it is attached to this message. "
                "Judge what you see: the subject, the composition, the "
                "colour, the lighting, whether the background is "
                "transparent, and whether any text was rendered.\n"
                "The prompt below is the one that produced it, and it "
                "tells you what the image was MEANT to be. Judge the image "
                "against the requirements, not the prompt against the "
                "requirements.\n"
            )
        else:
            opening = (
                "You are judging the PROMPT that produced an image "
                "against a requirement specification.\n"
                "You cannot see the image. You can only see the prompt "
                "and the requirements. So judge ONE thing: does the "
                "prompt ask for what the requirements demand?\n"
                "If the prompt is consistent with the requirements, "
                "answer pass. Never invent a defect you cannot see - a "
                "defect you report becomes an instruction to regenerate "
                "the image, and a made-up one costs a generation and "
                "changes nothing.\n"
            )
        return (
            opening +
            "Answer in EXACTLY this format and nothing else:\n"
            "VERDICT: pass\n"
            "REASON: <one line>\n"
            "CHANGE: <one specific change>\n"
            "CHANGE: <another specific change>\n"
            "\n"
            "Use VERDICT: pass when the prompt satisfies every requirement. "
            "Use VERDICT: fail with two CHANGE lines when it does not.\n"
            "\n"
            "WHAT A CHANGE MAY AND MAY NOT ASK FOR\n"
            "A CHANGE is appended to the prompt and sent to the image "
            "model, so it must describe something VISIBLE in the image.\n"
            "Never ask for the image SIZE or RESOLUTION - that is passed to "
            "the model as a parameter, not written into the prompt, and a "
            "prompt that mentions it makes the model DRAW the numbers as "
            "text. Never ask for the aspect ratio, the file format, or the "
            "number of megapixels for the same reason.\n"
            "Never ask for a requirement to be 'added to the prompt' or "
            "'mentioned in the prompt'. Describe the change you want to "
            "SEE instead: 'the background is transparent' rather than "
            "'add transparent background to the prompt'.\n"
            "Ask only for things you can SEE in an image: subject, "
            "composition, colour, lighting, material, mood, background.\n"
            "\n"
            "THE PROMPT\n"
            f"{prompt or '(the prompt was not recorded)'}\n"
            "\n"
            "THE REQUIREMENTS\n"
            f"artifact: {requirements.artifact.value}\n"
            f"alpha (a transparent background): {requirements.alpha}\n"
            f"text in the image: {requirements.text_in_image}\n"
            f"style: {requirements.style}\n"
            f"size: {requirements.width}x{requirements.height} (passed as a "
            f"parameter; never ask for it in a CHANGE)\n"
            f"hard constraints: {', '.join(requirements.hard) or '(none)'}\n"
        )

    @staticmethod
    def _parse(reply: str) -> Critique:
        verdict: str | None = None
        reasons: list[str] = []
        changes: list[str] = []

        for line in reply.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("VERDICT:"):
                verdict = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("REASON:"):
                reasons.append(stripped.split(":", 1)[1].strip())
            elif stripped.upper().startswith("CHANGE:"):
                changes.append(stripped.split(":", 1)[1].strip())

        if verdict is None:
            # No verdict: the judge did not answer in the format. That is
            # inconclusive, not a failed image.
            reasons = []
            if not reply.strip():
                # An EMPTY reply is a different fault from a reply in the
                # wrong shape, and it needs to say so. A reasoning model
                # that spends its whole token budget thinking returns
                # nothing at all - and "nothing" is what a model that
                # cannot see also returns. Silently recording both as
                # "inconclusive" hides the difference.
                reasons.append(
                    "the judge returned an empty reply: it spent its token "
                    "budget thinking and answered nothing"
                )
            return Critique(passed=False, inconclusive=True, reasons=reasons,
                            suggested_changes=[], raw=reply)

        # A change that asks for the output's dimensions is dropped. The
        # size is an argument to the model, not prompt text, and repeating
        # it in the prompt makes the model draw the numbers. The judge's
        # own words stay in `raw`, so nothing is lost.
        usable = [change for change in changes if _is_usable_change(change)]

        # If every change was dropped, there is nothing left to act on.
        # The judge asked for something unusable, so this is a broken
        # verdict, not a failed image - and the orchestrator must not
        # burn a generation regenerating against a change it cannot send.
        if changes and not usable:
            return Critique(passed=False, inconclusive=True, reasons=reasons,
                            suggested_changes=[], raw=reply)

        return Critique(
            passed=verdict.strip().lower() == "pass",
            inconclusive=False,
            reasons=reasons,
            suggested_changes=usable,
            raw=reply,
        )
