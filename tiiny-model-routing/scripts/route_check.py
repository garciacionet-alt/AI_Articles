#!/usr/bin/env python3
"""route_check.py — show which Tiiny model a task goal would be routed to.

A read-only companion to the routing backend. It applies the same tier table
and the same shape detection, then prints the tier, the model, and that
model's NPU share and context window — so a routing decision can be checked
without spawning a child agent.

The tier table comes from ``plugin/tiers.py``, the same file the routing
plugin reads, so this script and the backend cannot drift apart.

Usage:
    python3 route_check.py "index every file under the vault and classify each"
    python3 route_check.py --tier code
    python3 route_check.py --all          # every tier, with its budget
    python3 route_check.py --image "a photorealistic portrait"

Exit codes:
    0  a route was found
    1  the tier was not recognised
    2  the usage was wrong

The script makes no network calls and changes nothing on the device.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def _load_tiers():
    """Load the shared tier table by path (see plugin/tiers.py for why)."""
    path = Path(__file__).resolve().parent.parent / "plugin" / "tiers.py"
    spec = importlib.util.spec_from_file_location("tiiny_tiers", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load the tier table from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tiers = _load_tiers()

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

    if args.alternatives:
        print("fallbacks:")
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
