#!/usr/bin/env python3
"""route_check.py — show which Tiiny model a task goal would be routed to.

A read-only companion to the routing backend. It applies the same tier table
and the same shape detection, then prints the tier, the model, and that
model's NPU share and context window — so a routing decision can be checked
without spawning a child agent.

Usage:
    python3 route_check.py "index every file under the vault and classify each"
    python3 route_check.py --tier code
    python3 route_check.py --all          # every tier, with its budget

Exit codes:
    0  a route was found
    1  the tier was not recognised
    2  the usage was wrong

The script makes no network calls and changes nothing on the device.
"""

from __future__ import annotations

import argparse
import os
import sys

# tier -> ((model id, NPU share, context window), ...)
TIER_CHOICES = {
    "research": (
        ("InternScience/Sage-A1.5-Turbo", 48, 262144),
        ("endless-frontier/BigBang-v1-Turbo", 54, 131072),
    ),
    "index": (
        ("openai/gpt-oss-20b", 27, 131072),
    ),
    "code": (
        ("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
        ("Qwen/Qwen3-Coder-Next", 94, 131072),
    ),
    "browser": (
        ("Qwen/Qwen3.8-27B", 51, 262144),
    ),
    "draft": (
        ("Qwen/Qwen3.5-9B", 29, 131072),
    ),
    "general": (
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
    ),
}

TIER_MODEL = {tier: choices[0][0] for tier, choices in TIER_CHOICES.items()}
VALID_TIERS = tuple(sorted(TIER_MODEL))

SHAPE_SIGNALS = (
    ("research", (
        "research", "literature", "survey", "investigate", "find sources",
        "web search", "search the web", "literature review", "deep dive",
        "competitive analysis", "market analysis", "sweep the",
    )),
    ("index", (
        "index", "indexing", "inventory", "classify", "classify every",
        "categorize", "catalog", "catalogue", "list every file", "walk the",
        "enumerate", "manifest", "tag every", "bulk", "batch classify",
    )),
    ("browser", (
        "browser", "click through", "web ui", "web page", "fill in the form",
        "navigate the site", "screenshot the", "scrape the page",
        "automate the browser",
    )),
    ("code", (
        "code", "refactor", "implement", "write a function", "bug", "debug",
        "fix the", "compile", "unit test", "patch the", "repository", "repo",
        "module", "script that", "shell script", "migrate the schema",
    )),
    ("draft", (
        "draft", "summar", "rewrite", "rephrase", "bullet", "outline",
        "condense", "shorten", "proofread", "reword", "tl;dr", "summarise",
    )),
)


def detect_tier(goal: str) -> str:
    """Return the task tier for a goal, or 'general' when unrecognised."""
    text = (goal or "").lower()
    for tier, signals in SHAPE_SIGNALS:
        for signal in signals:
            if signal in text:
                return tier
    return "general"


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
        print(f"residency: NOT loaded — `tiiny-swap.sh {model} -- <cmd>` loads it and restores the rest")

    return 0


if __name__ == "__main__":
    sys.exit(main())
