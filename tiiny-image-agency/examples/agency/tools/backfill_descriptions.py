"""Backfill the device's own description into the registry.

The registry is built from the live store, and the builder now keeps
the device's `desc` field so that a model card can show the vendor's
claim beside what we measured. This applies that same field to a
registry that was built before the builder learned to keep it.

It reads the catalogue snapshot rather than the live device on purpose:
the appliance is serial and exclusive, and a live fetch during a
generation run would be a collision. The snapshot is the same data the
builder would have used.

Only the `description` field is touched. Everything else in the
registry - the download states, the co-residency, the pinned planner -
is left exactly as it is, because those are facts about the device's
current state and the published acceptance table depends on them.
"""
from __future__ import annotations

import json
from pathlib import Path

# The project root is the parent of tools/. Nothing here is written for
# one machine: a hard-coded home path is both a leak and wrong the
# moment anyone else runs it.
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path("/tmp/cat.json")
REGISTRY = ROOT / "registry" / "image-models.json"


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"FAIL: no catalogue snapshot at {SNAPSHOT}")
        return 1

    store = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    descriptions = {
        str(row.get("fullname") or ""): str(row.get("desc") or "")
        for row in store
        if row.get("fullname")
    }

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changed = 0
    for model in registry.get("models", []):
        description = descriptions.get(model["id"], "")
        device = model.setdefault("device", {})
        if description and device.get("description") != description:
            device["description"] = description
            changed += 1

    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n",
                        encoding="utf-8")
    print(f"Backfilled the device description into {changed} model(s)")
    for model in registry.get("models", []):
        device = model.get("device", {})
        print(f"  {model['id']:<58} {len(device.get('description') or ''):>5} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
