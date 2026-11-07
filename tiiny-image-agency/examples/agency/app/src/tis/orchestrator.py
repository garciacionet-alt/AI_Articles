"""The orchestrator: plan -> resolve -> swap -> generate -> critique -> deliver.

This is the loop that turns a requirement vector into an image on a shared,
single-stream appliance.

THE ORDER MATTERS
-----------------
  resolve     pick the model, with reasons
  translate   write the prompt in that model's dialect, at a size it accepts
  swap        hold the model against the watchdog, take the watchdog's lock,
              load it
  generate    one image
  critique    judge it against the requirement vector
  deliver     the image, with the critique attached

The swap wraps the generate-and-critique loop, because both need the model
resident — and the residency check for the CRITIC has to happen INSIDE the
swap. The swap changes what is resident, so a check made before it answers
a different question than a check made after it.

THE JUDGE HAS TO BE VISIBLE
---------------------------
A judge that fails in silence is a judge the user cannot act on. The
first version published "critique.ready" carrying the PROMPT the judge
was given, and the surface said "the judge compared the image against the
requirements" — which is true of every judge that has ever run, including
one that failed, one that passed, and one that was never called at all.

So the verdict is published here, where the verdict exists: the verdict,
the reasons, and the changes the judge wants. And a change is what the
next attempt acts on.

WHEN A JUDGE KEEPS FAILING, CHANGE THE MODEL
---------------------------------------------
The first attempt fixes the PROMPT, because the most common complaint is
that the prompt does not ask for what was requested. The second attempt
asks a DIFFERENT MODEL — because if the prompt now says the right thing
and the image is still wrong, the prompt is not the problem.

When the model changes, the prompt is re-translated for it: a different
model wants a different dialect, and a size that one accepts is not
necessarily a size the other one does. Carrying the old prompt across
would carry the old dialect with it.

THE CRITIC MAY NOT BE ABLE TO RUN
----------------------------------
The critic needs its own model resident. The hot path (55% planner + 26%
image model = 81%) has the planner resident and the critic can use it. The
flagship path (the 62% Qwen-Image-2.1 alone) evicts the planner, and there
is no judge. When that happens the image is still generated and still
delivered — the result says the critique was skipped and why. An image with
no critique is worth more than no image.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

# Critique is imported at RUNTIME, not under TYPE_CHECKING: pydantic has to
# resolve the annotation on GenerationResult, and with `from __future__ import
# annotations` a type-checking-only import leaves it as an unresolvable
# string. critic.py does not import orchestrator.py, so this is not a cycle.
from .critic import Critique

if TYPE_CHECKING:
    from .critic import Critic
    from .device import Device
    from .dialect import SceneDescription
    from .models import RequirementVector
    from .registry import Registry
    from .residency import ResidencyManager
    from .resolver import Resolver


class GenerationResult(BaseModel):
    """What one user turn produced."""
    image: bytes
    model_id: str
    prompt: str
    size: str
    attempts: int
    critique: Critique | None = None
    critique_skipped_reason: str | None = None
    #: Every model that was tried, in order. A user who sees two models
    #: in this list knows the judge changed the course of the job.
    models_used: list[str] = []


class Orchestrator:
    """Runs one requirement vector to an image."""

    def __init__(self, device: Device, registry: Registry,
                 resolver: Resolver, translator, critic: Critic,
                 residency: ResidencyManager, max_attempts: int = 3,
                 events=None, session=None):
        self.device = device
        self.registry = registry
        self.resolver = resolver
        self.translator = translator
        self.critic = critic
        self.residency = residency
        self.max_attempts = max_attempts
        #: The event bus, so the verdict can be published. Optional: a
        #: caller that does not want events gets none.
        self.events = events
        self.session = session or (lambda: "default")

    # -- the loop ---------------------------------------------------------

    def generate(self, requirements: RequirementVector,
                 scene: SceneDescription,
                 preferred: str | None = None) -> GenerationResult:
        resolution = self.resolver.resolve(requirements, preferred=preferred)
        chosen = resolution.chosen

        # The models this job may use: the winner first, then the
        # alternatives the resolver ranked, and only the ones that are
        # on the device. A model that is not on disk cannot be loaded.
        #
        # An alternative must also be able to RUN beside the judge. A
        # model that is too big would produce an image with no verdict
        # at all, which is worse than the image the user already has.
        candidates = [chosen.id]
        for alternative in resolution.alternatives:
            if alternative.id in candidates:
                continue
            if not alternative.downloaded:
                continue
            if not self.residency.fits_with_judge(alternative.id,
                                                   self.critic.model_id):
                continue
            candidates.append(alternative.id)

        current = chosen.id
        modifiers = tuple(scene.modifiers)
        prompt, size = self._prompt_for(current, requirements, scene, modifiers)

        image = b""
        critique: Critique | None = None
        skipped: str | None = None
        attempts = 0
        models_used: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            model = self.registry.by_id(current)
            with self.residency.swap_to(current, self.critic.model_id):
                attempts = attempt
                models_used.append(current)
                image = self.device.generate(current, prompt, size)

                if self.critic.model_id not in self.device.resident():
                    skipped = (
                        f"no judge was resident: {current} occupies "
                        f"{model.npu_usage}% NPU and cannot share the pool "
                        f"with the {self.critic.model_id}, so the image was "
                        f"delivered without a critique"
                    )
                    break

                critique = self.critic.judge(image, requirements, prompt)

                # The verdict, published where the verdict exists and
                # while the judge is still resident. A judge that fails
                # in silence is a judge the user cannot act on.
                self._publish_critique(critique, current, attempt)

            if critique.passed or critique.inconclusive:
                break

            changes = critique.suggested_changes
            if not changes:
                # Nothing to act on. Retrying would produce the same
                # picture and cost another generation.
                break

            # The judge's changes become modifiers, so the prompt can be
            # rebuilt for whichever model runs next — and rebuilt in that
            # model's dialect rather than carried across in the old one.
            modifiers = modifiers + tuple(changes)

            if attempt == 1 and len(candidates) > 1:
                # The prompt was wrong and has now been fixed. If the
                # image is STILL wrong, the prompt is not the problem.
                current = candidates[1]
                self._publish("model.changed", {
                    "from": models_used[-1],
                    "to": current,
                    "reason": "; ".join(changes),
                })

            prompt, size = self._prompt_for(current, requirements, scene,
                                            modifiers)

        return GenerationResult(
            image=image,
            model_id=current,
            prompt=prompt,
            size=size,
            attempts=attempts,
            critique=critique,
            critique_skipped_reason=skipped,
            models_used=models_used,
        )

    # -- helpers ----------------------------------------------------------

    def _prompt_for(self, model_id: str, requirements: RequirementVector,
                    scene: SceneDescription,
                    modifiers: tuple[str, ...]) -> tuple[str, str]:
        """The prompt for one model, with the accumulated changes in it.

        The size comes from the model's own rule, so a model that does
        not accept 1024x1024 gets the size it does accept — and a change
        of model changes the size.
        """
        model = self.registry.by_id(model_id)
        working = scene
        if modifiers != tuple(scene.modifiers):
            working = scene.model_copy(update={"modifiers": modifiers})
        plan = self.translator.translate(
            working, model, requirements.width, requirements.height)
        return plan.prompt, plan.size_used

    def _publish_critique(self, critique: Critique, model_id: str,
                          attempt: int) -> None:
        if self.events is None:
            return
        self.events.publish("critique.ready", self.session(), {
            "model": model_id,
            "vision": getattr(self.critic, "vision", False),
            "passed": critique.passed,
            "inconclusive": critique.inconclusive,
            "reasons": list(critique.reasons),
            "suggested_changes": list(critique.suggested_changes),
            "attempt": attempt,
        })

    def _publish(self, kind: str, data: dict) -> None:
        if self.events is None:
            return
        self.events.publish(kind, self.session(), data)
