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

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .device import Device
    from .models import RequirementVector


class Critique(BaseModel):
    """The judge's verdict on one image."""

    passed: bool
    inconclusive: bool
    reasons: list[str]
    suggested_changes: list[str]
    raw: str


class Critic:
    """Judges a generated image against the requirement vector."""

    def __init__(self, device: Device, model_id: str):
        self.device = device
        self.model_id = model_id

    def judge(self, image: bytes, requirements: RequirementVector,
              prompt: str = "") -> Critique:
        """Judge the image.

        The judge is asked to answer in exactly one format, and the reply is
        parsed line by line. A reply with no VERDICT line is INCONCLUSIVE —
        that is a broken judge, not a failed image, and it must not make the
        orchestrator burn its retries.

        A DeviceError propagates. If the judge is not resident, that is a
        real fault the caller needs to see; the orchestrator checks residency
        before it judges so it never reaches here in that state.

        ``prompt`` is the prompt that produced this image. The judge cannot
        see the pixels, so the prompt is the only evidence it has — without
        it, the judge is asked to reach a verdict on nothing at all, and
        what it does then is invent a defect.
        """
        judge_prompt = self._judge_prompt(requirements, prompt)
        response = self.device.chat(self.model_id, judge_prompt)
        reply = response["choices"][0]["message"]["content"]
        return self._parse(reply)

    def _judge_prompt(self, requirements: RequirementVector,
                      prompt: str = "") -> str:
        return (
            "You are judging the PROMPT that produced an image against a "
            "requirement specification.\n"
            "You cannot see the image. You can only see the prompt and the "
            "requirements. So judge ONE thing: does the prompt ask for what "
            "the requirements demand?\n"
            "If the prompt is consistent with the requirements, answer "
            "pass. Never invent a defect you cannot see - a defect you "
            "report becomes an instruction to regenerate the image, and a "
            "made-up one costs a generation and changes nothing.\n"
            "Answer in EXACTLY this format and nothing else:\n"
            "VERDICT: pass\n"
            "REASON: <one line>\n"
            "CHANGE: <one specific change>\n"
            "CHANGE: <another specific change>\n"
            "\n"
            "Use VERDICT: pass when the prompt satisfies every requirement. "
            "Use VERDICT: fail with two CHANGE lines when it does not.\n"
            "\n"
            "THE PROMPT\n"
            f"{prompt or '(the prompt was not recorded)'}\n"
            "\n"
            "THE REQUIREMENTS\n"
            f"artifact: {requirements.artifact.value}\n"
            f"alpha (a transparent background): {requirements.alpha}\n"
            f"text in the image: {requirements.text_in_image}\n"
            f"style: {requirements.style}\n"
            f"size: {requirements.width}x{requirements.height}\n"
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
            return Critique(passed=False, inconclusive=True, reasons=[],
                            suggested_changes=[], raw=reply)

        return Critique(
            passed=verdict.strip().lower() == "pass",
            inconclusive=False,
            reasons=reasons,
            suggested_changes=changes,
            raw=reply,
        )
