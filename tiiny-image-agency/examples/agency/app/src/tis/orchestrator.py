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


class Orchestrator:
    """Runs one requirement vector to an image."""

    def __init__(self, device: Device, registry: Registry,
                 resolver: Resolver, translator, critic: Critic,
                 residency: ResidencyManager, max_attempts: int = 3):
        self.device = device
        self.registry = registry
        self.resolver = resolver
        self.translator = translator
        self.critic = critic
        self.residency = residency
        self.max_attempts = max_attempts

    def generate(self, requirements: RequirementVector,
                 scene: SceneDescription) -> GenerationResult:
        resolution = self.resolver.resolve(requirements)
        chosen = resolution.chosen
        # The resolver works in ModelChoice; the translator needs the model's
        # declared capabilities (verified sizes, dialect) to write a prompt
        # it will actually accept.
        model = self.registry.by_id(chosen.id)

        prompt_plan = self.translator.translate(
            scene, model, requirements.width, requirements.height)

        prompt = prompt_plan.prompt
        size = prompt_plan.size_used
        image = b""
        critique: Critique | None = None
        skipped: str | None = None
        attempts = 0

        with self.residency.swap_to(chosen.id, self.critic.model_id):
            for attempt in range(1, self.max_attempts + 1):
                attempts = attempt
                image = self.device.generate(chosen.id, prompt, size)

                if self.critic.model_id not in self.device.resident():
                    skipped = (
                        f"no judge was resident: {chosen.id} occupies "
                        f"{chosen.npu_usage}% NPU and cannot share the pool "
                        f"with the {self.critic.model_id}, so the image was "
                        f"delivered without a critique"
                    )
                    break

                critique = self.critic.judge(image, requirements, prompt)
                if critique.passed or critique.inconclusive:
                    break

                changes = "; ".join(critique.suggested_changes)
                prompt = f"{prompt}\n\nAdjustments: {changes}"

        return GenerationResult(
            image=image,
            model_id=chosen.id,
            prompt=prompt,
            size=size,
            attempts=attempts,
            critique=critique,
            critique_skipped_reason=skipped,
        )
