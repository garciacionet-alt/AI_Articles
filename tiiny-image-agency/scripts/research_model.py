#!/usr/bin/env python3
"""research_model.py — characterise one model, and write its card.

The device's own description of a model cannot be trusted: TiinyOS's
catalogue carries the CharacterDesignSheet text verbatim on
TaoBaiBai2025's entry. So the curated layer of the registry is built
from measurements, and this is the tool that makes them.

It runs on the appliance, so it HOLDS the device for as long as the
probes take — a generation is 54 seconds at best and three minutes at
worst. Nothing else may touch the appliance while it runs.

Usage:
  TIINY_API_KEY=<bearer> python3 research_model.py <model_id> [--full]
      [--out DIR] [--judge MODEL]

Writes:
  <out>/<model_id>.card.json     the summary, for the application
  <out>/<model_id>.overlay.yaml  the overlay entry, for the registry
  <out>/<model_id>__*.png        the evidence
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app" / "src"))

import yaml  # noqa: E402

from tis.config import Settings  # noqa: E402
from tis.device import TiinyDevice  # noqa: E402
from tis.registry import Registry  # noqa: E402
from tis.residency import HoldFile, ResidencyManager  # noqa: E402
from tis.research import (  # noqa: E402
    JUDGE_MODEL,
    ModelResearcher,
    Probe,
    default_probes,
    write_card,
)

PROJECT_ROOT = HERE.parent
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"
DEFAULT_OUT = PROJECT_ROOT / "research"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--full", action="store_true",
                        help="also sweep the sizes and the extra styles")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--judge", default=JUDGE_MODEL)
    parser.add_argument("--only", default=None,
                        help="run only the probes whose name contains this")
    args = parser.parse_args()

    key = os.environ.get("TIINY_API_KEY", "")
    if not key:
        print("ERROR: TIINY_API_KEY not set", file=sys.stderr)
        return 1

    registry = Registry.load(REGISTRY_PATH)
    settings = Settings(api_key=key)
    device = TiinyDevice(settings)
    # The research holds the appliance for as long as the probes take, so
    # it takes the hold and the watchdog lock through the residency
    # manager like any other run of work.
    residency = ResidencyManager(device, registry,
                                 HoldFile(settings.hold_file),
                                 settings.watchdog_lock)
    out = Path(args.out)
    researcher = ModelResearcher(device, registry, out,
                                 judge_model=args.judge,
                                 residency=residency)

    probes = default_probes(full=args.full)
    if args.only:
        probes = [p for p in probes if args.only in p.name]
    print(f"Researching {args.model} with {len(probes)} probes "
          f"(about {len(probes) * 60 // 60} minutes of generation)")

    started = time.monotonic()
    card = researcher.characterise(args.model, probes)

    card_path = write_card(card, out / f"{args.model.replace('/', '__')}.card.json")
    entry = researcher.overlay_entry(card)
    overlay_path = out / f"{args.model.replace('/', '__')}.overlay.yaml"
    overlay_path.write_text(
        yaml.safe_dump(entry, sort_keys=False, allow_unicode=True),
        encoding="utf-8")

    print()
    print(f"  card     : {card_path}")
    print(f"  overlay  : {overlay_path}")
    print(f"  elapsed  : {round(time.monotonic() - started)}s")
    print()
    print(f"  {card.summary}")
    if card.strengths:
        for strength in card.strengths:
            print(f"    + {strength}")
    for limitation in card.limitations:
        print(f"    - {limitation}")
    print()
    for result in card.probes:
        state = "ok " if result.ok else "ERR"
        detail = result.answer.replace("\n", " ")[:60] if result.ok else result.error[:60]
        print(f"    [{state}] {result.probe:<22} {result.seconds:>6}s  {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
