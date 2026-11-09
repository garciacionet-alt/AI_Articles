#!/usr/bin/env python3
"""route_check.py — show which Tiiny model a task goal would be routed to.

A read-only companion to the routing backend. It applies the same tier table
and the same shape detection, then prints the tier, the model, that model's
NPU share and context window, and what the model's reasoning mode would be —
so a routing decision can be checked without spawning a child agent.

The tier table comes from the plugin's ``tiers.py`` and the reasoning control
from its ``thinking.py``: the same files the routing plugin reads, so this
script and the backend cannot drift apart. Both are located relative to this
file, because the plugin and the checker ship side by side in two layouts —
``plugin/`` inside a skill, ``examples/tiiny-router/`` inside an article.

Usage:
    python3 route_check.py "index every file under the vault and classify each"
    python3 route_check.py --tier code
    python3 route_check.py --all          # every tier, with its budget
    python3 route_check.py --image "a photorealistic portrait"
    python3 route_check.py --thinking off "summarise the meeting notes"
    python3 route_check.py --thinking on  "solve this novel reasoning problem"

Exit codes:
    0  a route was found
    1  the tier was not recognised
    2  the usage was wrong

The script changes nothing on the device. It makes read-only calls: one to
the device's resident model list, and — only when a thinking mode is asked
for — one to the device's model catalogue, to read what that model can do
with reasoning.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

#: Where the plugin's shared modules may live, relative to this script.
_PLUGIN_DIRS = (
    Path("plugin"),
    Path("examples") / "tiiny-router",
)


def _load(name: str, filename: str):
    """Load a shared plugin module by path, whichever layout it sits in."""
    here = Path(__file__).resolve().parent.parent
    for candidate in _PLUGIN_DIRS:
        path = here / candidate / filename
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise SystemExit(
        f"could not find {filename}. It ships next to the plugin: look in "
        + ", ".join(str(here / c) for c in _PLUGIN_DIRS)
        + "."
    )


tiers = _load("tiiny_tiers", "tiers.py")
thinking = _load("tiiny_thinking", "thinking.py")

TIER_CHOICES = tiers.TIER_CHOICES
TIER_MODEL = tiers.TIER_MODEL
VALID_TIERS = tiers.VALID_TIERS


def detect_tier(goal: str) -> str:
    """Return the task tier for a goal, or 'general' when unrecognised."""
    return tiers.detect_tier(goal)


def resident_models() -> set[str] | None:
    """Models currently resident, read from the device CLI. None if unavailable."""
    import shutil
    import subprocess

    tiiny = shutil.which("tiiny") or os.path.expanduser("~/.local/tiiny/bin/tiiny")
    if not os.path.exists(tiiny):
        return None
    try:
        out = subprocess.run([tiiny, "top"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    models = set()
    for line in out.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        # The Model ID column holds the full id, e.g. Qwen/Qwen3.6-35B-A3B
        for cell in cells:
            if "/" in cell and " " not in cell and not cell.startswith("Model"):
                models.add(cell)
                break
    return models or None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Show which Tiiny model a task goal routes to.",
    )
    ap.add_argument("goal", nargs="?", help="the task goal, as it would be passed to delegate_task")
    ap.add_argument("--tier", choices=VALID_TIERS, help="force a tier instead of inferring it")
    ap.add_argument("--all", action="store_true", help="show every tier and its budget")
    ap.add_argument("--image", metavar="JOB", help="pick the image model for a job description")
    ap.add_argument("--alternatives", action="store_true", help="also list the fallback models for the tier")
    ap.add_argument("--thinking", choices=["auto", "on", "off"], default="auto",
                    help="thinking mode override for this check (default: auto)")
    args = ap.parse_args()

    if args.all:
        print(f"{'tier':<10} {'model':<44} {'NPU':>5}  context")
        print("-" * 78)
        for tier in VALID_TIERS:
            for model, npu, ctx in TIER_CHOICES[tier]:
                mark = "  " if model == TIER_MODEL[tier] else "* "
                print(f"{mark}{tier:<8} {model:<44} {npu:>4}%  {ctx}")
        print("\n* = fallback for that tier. NPU shares are of one shared pool;")
        print("  two models can only be resident together if their shares sum to 100% or less.")
        return 0

    if args.image:
        model, reason = tiers.pick_special_model(args.image, "image")
        entry = tiers.SPECIAL_MODELS.get(model, (0, "", "", ""))
        print(f"job:    {args.image}")
        print(f"model:  {model}")
        print(f"reason: {reason}")
        print(f"role:   {entry[2]}")
        print(f"budget: {entry[0]}% NPU")
        print(f"note:   {entry[3]}")
        return 0

    if not args.goal:
        ap.error("a task goal is required (or use --all)")

    tier = args.tier or detect_tier(args.goal)
    model, npu, ctx = TIER_CHOICES[tier][0]

    print(f"goal:   {args.goal}")
    print(f"tier:   {tier}" + ("  (forced)" if args.tier else "  (inferred)"))
    print(f"model:  {model}")
    print(f"budget: {npu}% NPU, {ctx} context")

    # What the model can actually do with reasoning, read from the device.
    print(f"reasoning: {thinking.describe_capability(model)}")

    if args.thinking == "auto":
        print("thinking: auto (the model's native behaviour)")
    else:
        try:
            overrides, achieved = thinking.resolve_thinking(model, args.thinking)
        except Exception as exc:
            print(f"thinking: could not be resolved ({exc})")
            overrides, achieved = None, "unknown"
        if overrides:
            print(f"thinking: {args.thinking} -> {achieved}")
            sent = []
            body = (overrides.get("extra_body") or {}).get("chat_template_kwargs") or {}
            if "enable_thinking" in body:
                sent.append(f"enable_thinking={str(body['enable_thinking']).lower()}")
            if "reasoning_effort" in overrides:
                sent.append(f"reasoning_effort={overrides['reasoning_effort']}")
            if "max_tokens" in overrides:
                sent.append(f"max_tokens={overrides['max_tokens']}")
            if sent:
                print(f"sent:    {', '.join(sent)}")
        else:
            print(f"thinking: {args.thinking} -> {achieved} (nothing sent)")

    if args.alternatives:
        print("fallbacks (same model, same thinking setting):")
        for alt, anpu, actx in TIER_CHOICES[tier][1:]:
            print(f"  {alt}  ({anpu}% NPU, {actx} context)")

    resident = resident_models()
    if resident is None:
        print("residency: unknown (tiiny CLI not available)")
    elif model in resident:
        print("residency: loaded")
    else:
        print(f"residency: NOT loaded — `tiiny_ctl.py load --model {model}` loads it")

    return 0


if __name__ == "__main__":
    sys.exit(main())
