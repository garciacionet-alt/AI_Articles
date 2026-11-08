"""The resolver: a RequirementVector in, a chosen model and its reasons out.

This is the product's core. The LLM extracts intent; the resolver matches that
intent against the registry's declared taxonomy and explains itself.

Three properties matter and are enforced by app/tests/test_resolver.py:

  deterministic — the same vector always yields the same resolution. No
                  clock, no randomness, no I/O.

  explainable   — every choice carries the factors that produced it, the
                  NPU it will occupy, and what it costs to run.

  honest        — the resolver never pretends an untested configuration is
                  safe. If the occupancy sits above the last combination
                  measured working, it says so.

The scoring model lives in app/tests/resolver_acceptance.py. That file is the
specification, and this module is its implementation.
"""
from __future__ import annotations

from typing import Collection

from .models import ModelChoice, RequirementVector, Resolution
from .registry import ModelSpec, Registry
from .residency import MAX_EXECUTABLE_OCCUPANCY_PCT

#: How much each role contributes to a model's score. These are a judgement
#: about the catalogue, not about any one request: a flagship is the safest
#: general answer, a specialist is better when its speciality matches, and an
#: edit adapter is a tool rather than a generator.
ROLE_POINTS = {
    "flagship": 24,
    "default": 20,
    "specialist": 18,
    "unified": 16,
    "quality-leader": 14,
    "style": 12,
    "fast-base": 10,
    "edit-adapter": 8,
}

#: Text rendering is graded, not binary: "best" is for the typography
#: specialist, "strong" is for models that can be trusted with a label, and
#: "weak" means the request should never have reached them.
_TEXT_POINTS = {
    "required": {"best": 30, "strong": 22},
    "preferred": {"best": 18, "strong": 14},
    "no": {"best": 10, "strong": 8},
}

#: Speed and fidelity are separate axes. "fastest" and "quality_first" are
#: explicit requests and dominate; "normal" prefers the cheap fast models.
_SPEED_POINTS_FASTEST = {"fastest": 45, "fast": 10}
_SPEED_POINTS_NORMAL = {"fast": 20, "fastest": 15}
_QUALITY_POINTS = {"highest": 45, "high": 15}


def _article(word: str) -> str:
    """"a" or "an", for prose that a human reads."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def _text_points(model: ModelSpec, want: str) -> float:
    return _TEXT_POINTS.get(want, {}).get(model.text_rendering, 0)


def _speed_points(model: ModelSpec, want: str) -> float:
    if want == "fastest":
        return _SPEED_POINTS_FASTEST.get(model.speed, 0)
    if want == "normal":
        return _SPEED_POINTS_NORMAL.get(model.speed, 0)
    return _QUALITY_POINTS.get(model.quality, 0)


class Resolver:
    """Chooses an image model for a requirement vector.

    ``planner_pct`` is the NPU cost of the planning model and ``ceiling_pct``
    is the highest occupancy measured to work on the device. Both are
    arguments because they are device facts, not policy.
    """

    def __init__(self, registry: Registry, planner_pct: int = 55,
                 ceiling_pct: int = MAX_EXECUTABLE_OCCUPANCY_PCT):
        self.registry = registry
        self.planner_pct = planner_pct
        self.ceiling_pct = ceiling_pct

    # -- public ---------------------------------------------------------

    def resolve(self, requirements: RequirementVector,
                resident: Collection[str] | None = None,
                preferred: str | None = None) -> Resolution:
        """Choose a model for ``requirements``.

        ``resident`` is the set of model ids currently loaded on the device.
        When it is None the resolver assumes the hot-path baseline — the
        planner plus the default model — so the swap plan it produces is the
        one the residency manager would act on.

        ``preferred`` is a model the USER chose. It wins, if it can do the
        job — the capability filter still applies, because a user asking
        for a transparent background cannot be given a model that cannot
        render one. If it cannot do the job, the resolver says so in the
        justification rather than quietly ignoring the request.
        """
        ranked = self._rank(requirements)
        preferred_note = None
        if preferred:
            spec = next((m for m in ranked if m.id == preferred), None)
            if spec is None:
                # Not in the registry at all, or filtered out because it
                # cannot do this job. Either way the user asked for
                # something impossible, and saying so is the whole
                # point of saying it.
                preferred_note = (
                    f"You asked for {preferred}, and it cannot make this "
                    f"image, so a model that can was chosen instead."
                )
            else:
                ranked = [spec] + [m for m in ranked if m.id != spec.id]
                preferred_note = (
                    f"You chose {preferred}, and it can make this image."
                )
        chosen = self._winner(ranked)
        alternatives = [self._choice(m) for m in ranked if m.id != chosen.id][:3]
        unavailable = [self._choice(m) for m in self._unavailable(requirements)][:3]

        planner_resident = chosen.co_resident_with_planner
        occupancy = self._occupancy(chosen, planner_resident)
        swap_plan = self._swap_plan(chosen, resident, planner_resident)
        reasons = self._reasons(chosen, requirements)
        if preferred_note:
            # The user's own choice, or the reason it could not be
            # honoured, belongs with the reasons the model was picked.
            reasons = [preferred_note] + list(reasons)

        return Resolution(
            chosen=self._choice(chosen),
            requirements=requirements,
            justification=self._justification(
                chosen, requirements, planner_resident, occupancy,
                reasons, alternatives, ranked, unavailable),
            alternatives=alternatives,
            unavailable=unavailable,
            swap_required=bool(swap_plan["load"] or swap_plan["evict"]),
            swap_plan=swap_plan,
            generation_occupancy_pct=occupancy,
            planner_resident=planner_resident,
            exceeds_measured_ceiling=occupancy > self.ceiling_pct,
            reasons=reasons,
        )

    # -- selection ------------------------------------------------------

    def _passes_capability(self, requirements: RequirementVector,
                            model: ModelSpec) -> bool:
        """What the model must be ABLE to do. There is no fallback past
        these.

        A model without alpha cannot satisfy an alpha requirement, and an
        edit adapter transforms an existing asset rather than generating
        one. Falling back past a capability filter would produce an image
        that silently fails the request — which is worse than an error,
        because the error is visible.

        Whether the model is DOWNLOADED is NOT checked here. That is a
        separate question, and the two are asked separately: a model that
        is not downloaded is not a candidate, but it may still be the
        model that WOULD do the job, and naming it is the whole point of
        the refusal message.
        """
        if model.role == "edit-adapter" and requirements.edit_op.value == "none":
            return False
        if requirements.alpha == "required" and not model.alpha:
            return False
        if (requirements.text_in_image == "required"
                and model.text_rendering in ("weak", "n/a", "unknown")):
            return False
        if (requirements.edit_op.value != "none"
                and requirements.edit_op.value not in model.edit_ops):
            return False
        if (requirements.edit_op.value != "none"
                and model.image_input == "no"):
            # AN EDIT IS THE IMAGE. An adapter that does the operation
            # but IGNORES a source image would make a new picture and
            # call it an edit — which is exactly the gap the adapter
            # cards used to describe.
            #
            # "no" is the refusal. "unknown" is not: it is a verdict
            # the judge could not make consistently, and an unknown
            # model that does the operation is still worth trying —
            # the judge will say whether it worked.
            return False
        return True

    def _passes_style(self, requirements: RequirementVector,
                      model: ModelSpec) -> bool:
        """A style is a preference, not a capability.

        A model that does not advertise "crayon" can still draw one, so a
        mismatch narrows the pool only when something does match. This is
        what separates "the layout specialist" from "no model on this
        appliance has been told it is a layout specialist".
        """
        return (requirements.style == "general"
                or requirements.style in model.style)

    def _candidates(self, requirements: RequirementVector) -> list[ModelSpec]:
        """The models that can do this, narrowed to the artifact and the
        style where something matches.

        The narrowing is a preference and never empties the pool: the
        registry's artifact list is a model's declared speciality, so if
        something declares the requested artifact, honour that; if nothing
        does, the request is unusual rather than impossible.
        """
        generators = list(self.registry.generators)
        available = [m for m in generators if m.downloaded]

        capable = [m for m in available
                   if self._passes_capability(requirements, m)]
        if not capable:
            # Nothing on the appliance can do this. Say what is missing
            # rather than picking a model that cannot do the job.
            missing = [m for m in generators
                       if not m.downloaded
                       and self._passes_capability(requirements, m)]
            if missing:
                raise ResolverError(
                    "no downloaded model can do this; "
                    + ", ".join(m.id for m in missing)
                    + " can, but must be downloaded first")
            if requirements.edit_op.value != "none":
                # AN EDIT IS THE IMAGE. Say which models do the
                # operation, say that they ignore the image, and say
                # which models take one — so the refusal is a road
                # rather than a wall.
                doers = [m.id for m in generators
                         if requirements.edit_op.value in m.edit_ops]
                takers = [m.id for m in generators if m.image_input == "yes"]
                raise ResolverError(
                    "no downloaded model can %s an image: %s %s the "
                    "operation, but %s ignore%s the image %s given. "
                    "Only %s take one, and none of them does this "
                    "operation, so downloading one would not help"
                    % (requirements.edit_op.value.replace("_", " "),
                       ", ".join(doers) if doers else "no model",
                       "does" if len(doers) == 1 else "do",
                       "it" if len(doers) == 1 else "they",
                       "s" if len(doers) == 1 else "",
                       "it" if len(doers) == 1 else "they",
                       ", ".join(takers) if takers
                       else "no model on the appliance"))
            raise ResolverError(
                "no downloaded model satisfies this request")

        styled = [m for m in capable if self._passes_style(requirements, m)]
        if styled:
            capable = styled

        decliners = [m for m in capable
                     if requirements.artifact.value in m.artifact]
        if decliners:
            capable = decliners
        return capable

    def _unavailable(self, requirements: RequirementVector) -> list[ModelSpec]:
        """The models that would do this if they were downloaded.

        They are not candidates, but they are worth naming: "download this
        and the request becomes possible" is more useful than a bare
        refusal.
        """
        return [m for m in self.registry.generators
                if not m.downloaded
                and self._passes_capability(requirements, m)]

    def best_unavailable(self, requirements: RequirementVector) -> ModelSpec | None:
        """The best model that WOULD do the job if it were downloaded.

        Ranked the same way as the real candidates, so this is the model
        the resolver would have chosen had it been on the appliance. It
        is what the Agency downloads when nothing downloaded can do the
        job.
        """
        candidates = [m for m in self.registry.generators
                      if not m.downloaded
                      and self._passes_capability(requirements, m)]
        if not candidates:
            return None
        scored = [(self._score(m, requirements), m) for m in candidates]
        scored.sort(key=lambda t: (-t[0], t[1].npu_usage, t[1].id))
        return scored[0][1]

    def _score(self, model: ModelSpec, requirements: RequirementVector) -> float:
        """How well a model fits the request.

        The weights encode the product's central bet: co-residency is worth
        45 points, because a swap costs a model load, interrupts the
        conversation, and turns a 54.5 s generation into roughly 200 s. That
        is worth more than a marginal speciality advantage — but not more than
        a hard constraint, which is why the filters run first.
        """
        score = 0.0
        if requirements.artifact.value in model.artifact:
            score += 40
        score += {"required": 70, "preferred": 35, "no": 0}[requirements.alpha]
        score += _text_points(model, requirements.text_in_image)
        score += _speed_points(model, requirements.speed)
        if requirements.style != "general" and requirements.style in model.style:
            score += 40
        if model.co_resident_with_planner:
            score += 45
        if model.vendor_supported:
            score += 10
        score += ROLE_POINTS.get(model.role, 0)
        return score

    def _rank(self, requirements: RequirementVector) -> list[ModelSpec]:
        pool = self._candidates(requirements)
        scored = [(self._score(m, requirements), m) for m in pool]
        scored.sort(key=lambda t: (-t[0], t[1].npu_usage, t[1].id))
        return [m for _score, m in scored]

    def _winner(self, ranked: list[ModelSpec]) -> ModelSpec:
        """The first vendor-supported model in the ranking.

        A community build may outscore every vendor model — the community
        quant of Qwen-Image-2.1 declares icon capability and reports 0% NPU,
        so it beats the vendor flagship for an alpha-required icon — and it
        must still never be selected. We measured the vendor flagship's alpha
        and never measured the community build's, and a professional
        demonstration should not silently default to an unsupported quant. It
        surfaces as an alternative with its caveat instead.
        """
        for model in ranked:
            if model.vendor_supported:
                return model
        raise ResolverError("no vendor-supported model satisfies this request")

    # -- the answer -----------------------------------------------------

    def _choice(self, model: ModelSpec) -> ModelChoice:
        combined = (self.planner_pct + model.npu_usage
                    if model.co_resident_with_planner else model.npu_usage)
        return ModelChoice(
            id=model.id,
            role=model.role,
            npu_usage=model.npu_usage,
            co_resident_with_planner=model.co_resident_with_planner,
            combined_npu_pct=combined,
            downloaded=model.downloaded,
        )

    def _occupancy(self, model: ModelSpec, planner_resident: bool) -> int:
        if planner_resident:
            return self.planner_pct + model.npu_usage
        return model.npu_usage

    def _baseline_residency(self) -> set[str]:
        """The hot path: the planner plus the default model."""
        baseline = {self.registry.planner.id}
        for model in self.registry.generators:
            if model.role == "default":
                baseline.add(model.id)
                break
        return baseline

    def _swap_plan(self, chosen: ModelSpec, resident: Collection[str] | None,
                   planner_resident: bool) -> dict[str, list[str]]:
        """What the residency manager would have to do to reach this model."""
        target = {chosen.id}
        if planner_resident:
            target.add(self.registry.planner.id)

        current = set(resident) if resident is not None else self._baseline_residency()

        return {
            "load": sorted(target - current),
            "evict": sorted(current - target),
            "keep": sorted(current & target),
        }

    # -- explanation ----------------------------------------------------

    def _reasons(self, model: ModelSpec, requirements: RequirementVector) -> list[str]:
        reasons: list[str] = []
        if requirements.alpha == "required":
            reasons.append("a transparent background is required")
        elif requirements.alpha == "preferred":
            reasons.append("a transparent background is preferred")
        if requirements.text_in_image == "required":
            reasons.append(f"text in the image is required ({model.text_rendering} rendering)")
        if requirements.style != "general" and requirements.style in model.style:
            reasons.append(f"it is the {requirements.style} specialist")
        if requirements.speed == "fastest":
            reasons.append(f"it is the fastest option ({model.speed})")
        elif requirements.speed == "quality_first":
            reasons.append(f"it has the highest fidelity in the catalogue ({model.quality})")
        if requirements.artifact.value in model.artifact:
            reasons.append(f"it is built for {requirements.artifact.value}")
        if model.co_resident_with_planner:
            reasons.append("it co-resides with the planner, so the conversation is not interrupted")
        else:
            reasons.append("it cannot share the NPU with the planner")
        reasons.append(f"it is {_article(model.role)} {model.role} model")
        return reasons

    def _justification(self, chosen: ModelSpec, requirements: RequirementVector,
                       planner_resident: bool, occupancy: int, reasons: list[str],
                       alternatives: list[ModelChoice],
                       ranked: list[ModelSpec],
                       unavailable: list[ModelChoice] | None = None) -> str:
        sentences: list[str] = []

        sentences.append(
            f"{chosen.id} was selected for this request. "
            f"It occupies {occupancy}% of the NPU pool"
            + (f" together with the planner."
               if planner_resident else " on its own.")
        )

        if requirements.alpha == "required":
            sentences.append(
                f"A transparent background is required, and {chosen.id} is a "
                f"vendor model that renders one natively."
            )
        elif requirements.text_in_image == "required":
            sentences.append(
                f"Text has to appear in the image, and {chosen.id} has "
                f"{chosen.text_rendering} text rendering."
            )
        elif requirements.style != "general" and requirements.style in chosen.style:
            sentences.append(
                f"The request asked for {_article(requirements.style)} "
                f"{requirements.style} style, which is this model's declared "
                f"speciality."
            )
        elif requirements.style != "general":
            # The style narrowed the pool to nothing, which means no
            # downloaded model declares it. Say so rather than implying
            # the request was honoured.
            sentences.append(
                f"The request asked for {_article(requirements.style)} "
                f"{requirements.style} style. No model downloaded on this "
                f"appliance declares that speciality, so the request was "
                f"answered by the strongest general fit instead."
            )
        else:
            sentences.append(
                f"It is the strongest fit for {_article(requirements.artifact.value)} "
                f"{requirements.artifact.value} at {chosen.npu_usage}% NPU."
            )

        if planner_resident:
            sentences.append(
                "It co-resides with the planner, so the conversation stays "
                "alive during generation."
            )
        else:
            sentences.append(
                "It cannot share the NPU pool with the planner, so the planner "
                "is evicted for the duration of the generation and the "
                "conversation pauses. On this device that path takes roughly "
                "200 seconds against 54.5 seconds on the hot path."
            )

        if occupancy > self.ceiling_pct:
            sentences.append(
                f"That combination sits at {occupancy}%, above the "
                f"{self.ceiling_pct}% ceiling that was last measured to work, "
                f"so this particular pairing is untested."
            )

        displaced = [a for a in alternatives
                     if not self.registry.by_id(a.id).vendor_supported]
        for alt in displaced:
            sentences.append(
                f"{alt.id} also satisfies the request and reports "
                f"{alt.npu_usage}% NPU, but it is a community-run build rather "
                f"than a vendor one, and its output has not been measured — so "
                f"it is offered as an alternative rather than chosen."
            )

        for alt in (unavailable or []):
            spec = self.registry.by_id(alt.id)
            caveat = (" and it is a community-run build rather than a vendor one"
                      if not spec.vendor_supported else "")
            sentences.append(
                f"{alt.id} would also satisfy the request{caveat}, but it is "
                f"not downloaded on this appliance, so it cannot be loaded."
            )

        sentences.append("Contributing factors: " + "; ".join(reasons) + ".")
        return " ".join(sentences)


class ResolverError(Exception):
    """Raised when no model can satisfy a request at all."""
