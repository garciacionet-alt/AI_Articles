#!/usr/bin/env python3
"""
resolver_acceptance.py — the resolver's expected behaviour, as data.

THIS IS THE SPEC for the resolver. It is written from the registry's specialty
taxonomy and the measured device behaviour, NOT from an implementation. The
resolver in app/src/tis/resolver.py must satisfy every row.

The scoring below is the reference model. The implementation must be a pure
function of (RequirementVector, Registry) -> Resolution.

THE DIVISION OF LABOUR
----------------------
The LLM's job is to extract INTENT: what artifact, does it need alpha, does it
need text in the image, what style, what edit, how fast. The resolver's job is
to match that intent against the registry's declared taxonomy. The resolver
invents no taxonomy of its own — artifact, style, text_rendering, speed and
quality all come from the registry.

HARD FILTERS (a model that violates one is not a candidate)
  1. alpha == "required"          -> specialty.alpha must be true
  2. text_in_image == "required"  -> text_rendering must not be weak/n/a
  3. edit_op != none              -> edit_op must be in specialty.edit_ops
  4. role == "edit-adapter"       -> edit_op must not be none
     (an edit adapter transforms an existing asset; it cannot generate one)
  5. community builds             -> never SELECTED, but still ranked, so
     they can surface as alternatives with their caveat
  6. a style is requested         -> style must be in specialty.style
  7. artifact                     -> SOFT filter: if any model declares the
     artifact, only those models remain; if none does, fall back to all

SCORE (higher wins)
  artifact in specialty.artifact                     +40
  alpha            required +70 / preferred +35 / no +0
  text  required   best +30 / strong +22 / other +0
        preferred  best +18 / strong +14 / other +0
        no         best +10 / strong +8  / other +0
  speed  fastest        -> speed == fastest +45 / fast +10
          normal         -> speed == fast +20 / fastest +15
          quality_first  -> quality == highest +45 / high +15
  style in specialty.style                           +40
  co_resident_with_planner                           +45
  vendor_supported                                   +10
  role  flagship +24 / default +20 / specialist +18 / unified +16
        quality-leader +14 / style +12 / fast-base +10 / edit-adapter +8
  Tie-break: lower npu_usage, then model id.

WHY co-residency IS WORTH 45
-----------------------------
A swap costs a model load (10-56 s), interrupts the conversation, and the
flagship generation is ~200 s against 54.5 s on the hot path. That is the
product's central bet, so co-residency outranks a marginal specialty
advantage — but not a hard constraint, which is why the filters run first.

WHY COMMUNITY BUILDS ARE EXCLUDED
----------------------------------
The community quant of Qwen-Image-2.1 is the only other model that declares
icon capability, and it reports 0% NPU so it would be a tempting win. Two
reasons not to auto-select it: we MEASURED the vendor flagship's alpha
(44.86% fully transparent pixels) and never measured the community build's;
and a professional demonstration should not silently default to an
unsupported community quant. It is surfaced as an alternative with its
caveat, and the resolver's justification says so.
"""
from __future__ import annotations

import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / "registry" / "image-models.json"

# Community-run builds. Never auto-selected; returned as alternatives only.
NON_VENDOR = {
    "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
}

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

REQ_DEFAULTS = {
    "artifact": "illustration",
    "alpha": "no",
    "text_in_image": "no",
    "style": "general",
    "edit_op": "none",
    "speed": "normal",
}


def normalize(req: dict) -> dict:
    """A case may state only the fields it cares about; fill the rest."""
    return {**REQ_DEFAULTS, **req}


def vendor_supported(model: dict) -> bool:
    return model["id"] not in NON_VENDOR


def _text_points(spec: dict, want: str) -> float:
    t = spec["text_rendering"]
    if want == "required":
        return {"best": 30, "strong": 22}.get(t, 0)
    if want == "preferred":
        return {"best": 18, "strong": 14}.get(t, 0)
    return {"best": 10, "strong": 8}.get(t, 0)


def _speed_points(spec: dict, want: str) -> float:
    if want == "fastest":
        return {"fastest": 45, "fast": 10}.get(spec["speed"], 0)
    if want == "normal":
        return {"fast": 20, "fastest": 15}.get(spec["speed"], 0)
    return {"highest": 45, "high": 15}.get(spec["quality"], 0)


def downloadable(model: dict) -> bool:
    """Is the model on the appliance's disk?

    The registry carries the device's own status: "downloaded",
    "not_downloaded", or "running". The store catalogue lists every
    model Tiiny SELLS, and only some of them are actually on the box. A
    model that is not there cannot be loaded, so it cannot be chosen.
    """
    status = str(model.get("device", {}).get("status") or "").lower()
    return status in ("downloaded", "running")


def passes_capability(model: dict, req: dict) -> bool:
    """What the model must be ABLE to do. No fallback past these.

    Community builds are ranked alongside everything else so they can
    surface with their caveat, but they are never selected. That
    distinction lives in winner(), not here.
    """
    spec = model["specialty"]
    if not downloadable(model):
        return False
    if model["role"] == "edit-adapter" and req["edit_op"] == "none":
        return False
    if req["alpha"] == "required" and not spec["alpha"]:
        return False
    if req["text_in_image"] == "required" and spec["text_rendering"] in ("weak", "n/a", "unknown"):
        return False
    if req["edit_op"] != "none" and req["edit_op"] not in (spec["edit_ops"] or []):
        return False
    return True


def passes_style(model: dict, req: dict) -> bool:
    """A style is a preference, not a capability.

    A model that does not advertise a style can still draw one, so a
    mismatch narrows the pool only when something does match.
    """
    return req["style"] == "general" or req["style"] in (model["specialty"]["style"] or [])


def score(model: dict, req: dict) -> float:
    spec = model["specialty"]
    s = 0.0
    if req["artifact"] in (spec["artifact"] or []):
        s += 40
    s += {"required": 70, "preferred": 35, "no": 0}[req["alpha"]]
    s += _text_points(spec, req["text_in_image"])
    s += _speed_points(spec, req["speed"])
    if req["style"] != "general" and req["style"] in (spec["style"] or []):
        s += 40
    if model["residency"]["co_resident_with_planner"]:
        s += 45
    s += 10  # vendor_supported
    s += ROLE_POINTS.get(model["role"], 0)
    return s


def candidates(registry: dict, req: dict) -> list[dict]:
    """The models that can do this, narrowed by style and artifact.

    The narrowing is a preference and never empties the pool. The
    capability filter is different: if nothing downloaded can do the
    job, the pool is empty and the request is refused rather than
    silently handed to a model that cannot do it.
    """
    gens = [m for m in registry["models"] if m["kind"] == "image_generator"]
    available = [m for m in gens if downloadable(m)]
    pool = [m for m in available if passes_capability(m, req)]
    if not pool:
        return []
    # Soft style filter: narrow when something matches.
    styled = [m for m in pool if passes_style(m, req)]
    if styled:
        pool = styled
    # Soft artifact filter: if anything declares this artifact, honour that.
    decliners = [m for m in pool if req["artifact"] in (m["specialty"]["artifact"] or [])]
    if decliners:
        pool = decliners
    return pool


def rank(registry: dict, req: dict) -> list[tuple[str, float]]:
    """The full ranking, community builds included."""
    pool = candidates(registry, req)
    scored = [(m["id"], score(m, req)) for m in pool]
    scored.sort(key=lambda t: (-t[1], next(m["device"]["npu_usage"]
                                            for m in pool if m["id"] == t[0]), t[0]))
    return scored


def winner(registry: dict, req: dict) -> str | None:
    """The first VENDOR-SUPPORTED model in the ranking.

    A community build may outscore every vendor model — the community quant of
    Qwen-Image-2.1 declares icon capability and reports 0% NPU — but it is
    never selected. It surfaces as an alternative with its caveat instead.
    """
    for model_id, _score in rank(registry, req):
        if model_id not in NON_VENDOR:
            return model_id
    return None


# ── THE CASES ────────────────────────────────────────────────────────
# (case name, requirement vector, expected winner)
#
# THE WINNER MUST BE DOWNLOADED ON THE APPLIANCE.
#
# The registry is built from the device's store catalogue, which lists
# every model Tiiny sells. Only 7 of the 16 curated models were on the
# appliance's disk when this table was last reconciled, and a model that
# is not there cannot be loaded — the resolver's first live generation
# chose one and the load failed with "Model not found".
#
# So a case whose specialist is not downloaded now expects the strongest
# general fit, and a case that REQUIRES an undownloaded model has moved
# to REFUSAL_CASES below. The expectations below are grounded in what
# the appliance can actually do.
CASES: list[tuple[str, dict, str]] = [
    # --- alpha: the hard case -----------------------------------------
    ("icon with required alpha",
     dict(artifact="icon", alpha="required"), "Qwen/Qwen-Image-2.1"),
    ("logo with required alpha",
     dict(artifact="logo", alpha="required"), "Qwen/Qwen-Image-2.1"),
    ("sticker with required alpha",
     dict(artifact="sticker", alpha="required"), "Qwen/Qwen-Image-2.1"),
    ("cutout with required alpha",
     dict(artifact="cutout", alpha="required"), "Qwen/Qwen-Image-2.1"),
    ("photo with preferred alpha stays on the hot path",
     dict(artifact="photo", alpha="preferred"), "Tongyi-MAI/Z-Image-Turbo"),
    ("illustration with preferred alpha stays on the hot path",
     dict(artifact="illustration", alpha="preferred"), "Tongyi-MAI/Z-Image-Turbo"),
    ("an icon without an alpha requirement still uses the icon model",
     dict(artifact="icon"), "Qwen/Qwen-Image-2.1"),

    # --- text in image -------------------------------------------------
    ("poster with required text",
     dict(artifact="poster", text_in_image="required"), "baidu/ERNIE-Image-Turbo"),
    ("infographic with required text",
     dict(artifact="infographic", text_in_image="required"), "baidu/ERNIE-Image-Turbo"),
    ("comic with required text",
     dict(artifact="comic", text_in_image="required"), "baidu/ERNIE-Image-Turbo"),
    ("logo with required text",
     dict(artifact="logo", text_in_image="required"), "baidu/ERNIE-Image-Turbo"),
    ("illustration with required text falls back to the strong-text default",
     dict(artifact="illustration", text_in_image="required"), "Tongyi-MAI/Z-Image-Turbo"),

    # --- artifact fit --------------------------------------------------
    ("character sheet",
     dict(artifact="character_sheet"), "YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet"),
    ("texture",
     dict(artifact="texture"), "Tongyi-MAI/Z-Image-Turbo"),
    ("generic illustration defaults to the default model",
     dict(artifact="illustration"), "Tongyi-MAI/Z-Image-Turbo"),
    ("generic photo defaults to the default model",
     dict(artifact="photo"), "Tongyi-MAI/Z-Image-Turbo"),
    ("generic logo defaults to the default model",
     dict(artifact="logo"), "Tongyi-MAI/Z-Image-Turbo"),
    ("comic without a text requirement",
     dict(artifact="comic"), "baidu/ERNIE-Image-Turbo"),
    ("infographic without a text requirement",
     dict(artifact="infographic"), "baidu/ERNIE-Image-Turbo"),
    ("poster without a text requirement stays on the hot path",
     dict(artifact="poster"), "Tongyi-MAI/Z-Image-Turbo"),
    ("an artifact nobody declares falls back to the default model",
     dict(artifact="blueprint"), "Tongyi-MAI/Z-Image-Turbo"),

    # --- style: the registry's own specialist signal ----------------------
    # The expectation is a PAIR: the specialist IF it is on the device,
    # otherwise the fallback. The resolver has an availability filter -
    # a model that is listed but not downloaded cannot be loaded - so a
    # single hard winner here would change whenever the store moved.
    # The store moved on 6 Nov, and the table said nothing about why the
    # answer had changed. This says why.
    ("realistic people",
     dict(artifact="photo", style="realistic-people"),
     ("TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic",
      "Tongyi-MAI/Z-Image-Turbo")),
    ("crayon style falls back when the crayon model is not downloaded",
     dict(artifact="illustration", style="crayon"), "Tongyi-MAI/Z-Image-Turbo"),
    ("layout style takes the layout specialist",
     dict(artifact="poster", style="layout"), "baidu/ERNIE-Image-Turbo"),
    ("a plain photoreal request stays on the hot path",
     dict(artifact="photo", style="photoreal"), "Tongyi-MAI/Z-Image-Turbo"),

    # --- speed ---------------------------------------------------------
    ("fastest stays on the hot path when the 4-step model is not downloaded",
     dict(artifact="illustration", speed="fastest"), "Tongyi-MAI/Z-Image-Turbo"),
    ("quality first wins the fidelity leader",
     dict(artifact="photo", speed="quality_first"), "HiDream-ai/HiDream-O1-Image-Dev"),
    ("quality first on a poster stays on the hot path",
     dict(artifact="poster", speed="quality_first"), "Tongyi-MAI/Z-Image-Turbo"),

    # --- edit operations (hard filter) ---------------------------------
    ("background removal",
     dict(artifact="cutout", edit_op="background_remove"), "fal/FLUX.2-klein-4B-Background-Remove"),

    # --- the default vector --------------------------------------------
    ("a bare request gets the default model",
     dict(), "Tongyi-MAI/Z-Image-Turbo"),

    # --- alpha + other constraints together ----------------------------
    ("alpha required beats the text specialist",
     dict(artifact="poster", alpha="required", text_in_image="required"), "Qwen/Qwen-Image-2.1"),
    ("alpha required with quality first still takes the flagship",
     dict(artifact="icon", alpha="required", speed="quality_first"), "Qwen/Qwen-Image-2.1"),
    ("alpha required with a style request still takes the flagship",
     dict(artifact="icon", alpha="required", style="flat"), "Qwen/Qwen-Image-2.1"),
]


# ── THE REFUSALS ─────────────────────────────────────────────────────
# A request that only an UNDOWNLOADED model can do is refused, not
# quietly handed to a model that cannot do it. The message names the
# model to download.
#
# (case name, requirement vector, the model that would do it)
REFUSAL_CASES: list[tuple[str, dict, str]] = [
    ("object removal has no downloaded adapter",
     dict(artifact="edit", edit_op="object_remove"),
     "fal/FLUX.2-klein-4B-Object-Remove"),
    ("outpaint has no downloaded adapter",
     dict(artifact="edit", edit_op="outpaint"),
     "fal/FLUX.2-klein-4B-Outpaint"),
    ("detail regeneration has no downloaded adapter",
     dict(artifact="edit", edit_op="detail_regen"),
     "fal/FLUX.2-klein-4B-Zoom"),
]


# ── OCCUPANCY ────────────────────────────────────────────────────────
# The resolver must report the NPU the generation will occupy, and flag when
# that combination sits above the last configuration we MEASURED as working.
#
# Measured on the device:
#   55% planner + 26% image model = 81%  -> generation SUCCEEDED in 54.5 s
#   23% enhancer + 62% flagship  = 85%  -> generation FAILED (HTTP 500, 150004)
#   27% planner + 62% flagship  = 89%  -> generation FAILED (HTTP 500, 150004)
#   62% flagship alone          = 62%  -> generation SUCCEEDED in ~200 s
#
# So 81 is the last proven-safe total, and the flagship is only proven ALONE.
MEASURED_CEILING_PCT = 81
PLANNER_PCT = 55

# (case name, requirement vector, expected model, expected occupancy,
#  expected planner resident, expected exceeds-ceiling)
OCCUPANCY_CASES: list[tuple[str, dict, str, int, bool, bool]] = [
    ("a hot-path model keeps the planner resident",
     dict(artifact="illustration"), "Tongyi-MAI/Z-Image-Turbo", 78, True, False),
    ("the quality leader plus the planner is above the proven ceiling",
     dict(artifact="photo", speed="quality_first"),
     "HiDream-ai/HiDream-O1-Image-Dev", 85, True, True),
    ("the text specialist plus the planner is above the proven ceiling",
     dict(artifact="poster", text_in_image="required"),
     "baidu/ERNIE-Image-Turbo", 82, True, True),
    ("the flagship runs alone and evicts the planner",
     dict(artifact="icon", alpha="required"),
     "Qwen/Qwen-Image-2.1", 62, False, False),
    ("the background remover stays on the hot path",
     dict(artifact="cutout", edit_op="background_remove"),
     "fal/FLUX.2-klein-4B-Background-Remove", 74, True, False),
]


def occupancy(model_id: str, registry: dict) -> tuple[int, bool, bool]:
    """(occupancy_pct, planner_resident, exceeds_measured_ceiling)."""
    m = next(x for x in registry["models"] if x["id"] == model_id)
    npu = m["device"]["npu_usage"]
    co = m["residency"]["co_resident_with_planner"]
    total = (PLANNER_PCT + npu) if co else npu
    return total, co, total > MEASURED_CEILING_PCT


def main() -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    failures = []
    print(f"{'CASE':60s} {'GOT':44s} RESULT")
    print("-" * 118)
    for name, req, expected in CASES:
        got = winner(reg, normalize(req)) or "<none>"
        ok = got == expected
        if not ok:
            failures.append((name, expected, got, rank(reg, normalize(req))[:3]))
        print(f"{name:60s} {got.split('/')[-1][:43]:44s} {'ok' if ok else 'MISMATCH'}")
    print()
    print(f"{len(CASES) - len(failures)}/{len(CASES)} match the reference scoring")
    if failures:
        print("\nMISMATCHES (the table and the scoring disagree):")
        for name, exp, got, top in failures:
            print(f"  {name}\n     expected {exp}\n     got      {got}")
            for mid, sc in top:
                print(f"       {sc:8.2f}  {mid}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
