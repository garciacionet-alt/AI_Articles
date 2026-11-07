#!/usr/bin/env python3
"""
build_registry.py — build the image-model registry for Tiiny Image Studio.

The registry is two layers:

  1. DEVICE FACTS   — read live from GET /api/v1/models/online_models.
                      Objective, changes whenever the device updates.
  2. SPECIALTY OVERLAY — hand-curated: what each model is actually good at,
                      which prompts it wants, which sizes it accepts.

Layer 1 alone is not enough. The device's own `desc` field is wrong in at
least one confirmed case (TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic
carries the CharacterDesignSheet description verbatim — a copy-paste bug in
TiinyOS's catalogue). The overlay is what makes routing defensible.

Output: registry/image-models.json

Usage:
  TIINY_API_KEY=<bearer> python3 build_registry.py [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

DEVICE_BASE = "http://openai.api.tiiny"
STORE_PATH = "/api/v1/models/online_models"

# Planner model assumed by the residency planner.
PLANNER = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"


def _strip_trailing(value: Any) -> Any:
    """Remove trailing whitespace from every string in the overlay.

    YAML's block scalars (`>` and `|`) append a final newline to the value.
    The curated strings never had one, so without this the generated registry
    differs from the original by a trailing newline on every dialect and notes
    string. Stripping here — rather than relying on a particular YAML block
    style — makes the conversion exact regardless of how the file is edited.
    """
    if isinstance(value, str):
        return value.rstrip()
    if isinstance(value, dict):
        return {k: _strip_trailing(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_trailing(v) for v in value]
    return value


def load_overlay() -> dict[str, dict]:
    try:
        with open(Path(__file__).parent.parent / "app" / "data" / "overlay.yaml", "r") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError("overlay.yaml root must be a mapping")
            models = data.get("models", {})
            if not isinstance(models, dict):
                raise ValueError("overlay.yaml must have a 'models' mapping")
            return _strip_trailing(models)
    except Exception as e:
        raise SystemExit(f"ERROR: Failed to load overlay.yaml: {e}")


def _size_bytes(m: dict) -> int:
    """The model's download size, in bytes.

    The store buries it in the tags list:
    ``[{"tag_name": "v1", "manifest": "ernie_image_turbo",
    "size": 11429631451}, ...]``. It is the only place the device says
    how much disk a model will take, and the capacity check needs it
    before it can promise a download will fit.
    """
    for tag in m.get("tags") or []:
        size = tag.get("size")
        if isinstance(size, int) and size > 0:
            return size
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="registry/image-models.json")
    ap.add_argument("--base", default=DEVICE_BASE)
    args = ap.parse_args()

    token = os.environ.get("TIINY_API_KEY", "")
    if not token:
        print("ERROR: TIINY_API_KEY not set", file=sys.stderr)
        return 1

    store = fetch_store(args.base, token)
    planner_npu = 0
    for m in store:
        if m.get("fullname") == PLANNER:
            planner_npu = m.get("npu_usage") or 0

    overlay = load_overlay()
    
    # Verify all overlay entries match device models
    device_ids = {m.get("fullname") for m in store if m.get("type") == "Text-to-Image" or "Prompt Enhance" in m.get("supported", [])}
    overlay_ids = set(overlay.keys())
    extra_ids = overlay_ids - device_ids
    if extra_ids:
        raise SystemExit(f"ERROR: overlay.yaml contains models not in device store: {extra_ids}")
    
    models = []
    enhancers = []
    uncharacterised: list[str] = []
    for m in store:
        mid = str(m.get("fullname") or "")
        supported = m.get("supported") or []
        is_enhancer = "Prompt Enhance" in supported
        if m.get("type") != "Text-to-Image" and not is_enhancer:
            continue
        ov = overlay.get(mid, {})
        if not ov:
            # No curated entry. The model is in the store, but nobody has
            # characterised it, and the overlay is what makes routing
            # defensible - an uncharacterised model would be chosen on a
            # guess, with a dialect nobody has measured. So it stays out
            # of the registry, and a curator is told it is waiting.
            uncharacterised.append(mid)
            continue
        npu = m.get("npu_usage") or 0
        kind = "prompt_enhancer" if is_enhancer else "image_generator"
        entry = {
            "id": mid,
            "name": m.get("name"),
            "kind": kind,
            "role": ov.get("role", "unclassified"),
            "device": {
                "npu_usage": npu,
                "size_bytes": _size_bytes(m),
                "steps": m.get("steps"),
                "guidance_scale": m.get("guidance_scale"),
                "input": m.get("input"),
                "output": m.get("output"),
                "supported": supported,
                "context_window": m.get("context_window"),
                "image_size": m.get("image_size"),
                "status": m.get("status"),
                "version_label": m.get("version_label"),
                "load_time": m.get("load_time"),
            },
            "specialty": {
                "artifact": ov.get("artifact", []),
                "alpha": ov.get("alpha", False),
                "alpha_kind": ov.get("alpha_kind"),
                "text_rendering": ov.get("text_rendering", "unknown"),
                "style": ov.get("style", []),
                "edit_ops": ov.get("edit_ops", []),
                "max_refs": ov.get("max_refs"),
                "quality": ov.get("quality", "unknown"),
                "speed": ov.get("speed", "unknown"),
            },
            "prompting": {
                "dialect": ov.get("dialect", "Not yet characterised."),
                "sizes_verified": ov.get("sizes_verified", []),
                "sizes_rejected": ov.get("sizes_rejected", []),
                "rejected_reason": ov.get("rejected_reason"),
                "size_rule": ov.get("size_rule"),
            },
            "residency": {
                "co_resident_with_planner": bool(planner_npu + npu <= 100),
                "combined_npu_pct": planner_npu + npu,
                "note": "Derived from the device's reported npu_usage field. "
                        "Approximate — validate against observed NPU MB.",
            },
            "notes": ov.get("notes", ""),
            "provenance": ov.get("provenance", "d"),
        }
        models.append(entry)

    models.sort(key=lambda x: (x["kind"], x["residency"]["combined_npu_pct"], x["id"]))
    enhancers = [m for m in models if m["kind"] == "prompt_enhancer"]

    out = {
        "schema": "tiiny-image-agency/registry/v1",
        "generated_from": {
            "device_store": args.base + STORE_PATH,
            "device_model_count": len(store),
            "image_model_count": sum(1 for m in models if m["kind"] == "image_generator"),
            "prompt_enhancer_count": len(enhancers),
        },
        "planner": {"id": PLANNER, "npu_usage": planner_npu},
        "prompt_enhancers": [
            {
                "id": e["id"],
                "npu_usage": e["device"]["npu_usage"],
                "context_window": e["device"]["context_window"],
                "status": e["device"]["status"],
                "role": e["role"],
                "dialect": e["prompting"]["dialect"],
                "notes": e["notes"],
            }
            for e in enhancers
        ],
        "models": models,
    }

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    co = sum(1 for m in models if m["residency"]["co_resident_with_planner"])
    print(f"Wrote {path} — {len(models)} image models, {co} co-resident with planner")
    if uncharacterised:
        print(f"  {len(uncharacterised)} model(s) in the store are not in the "
              f"overlay, so they are not in the registry:")
        for mid in uncharacterised:
            print(f"    {mid}")
    for m in models:
        flag = "co-resident" if m["residency"]["co_resident_with_planner"] else "SWAP REQUIRED"
        print(f"  {m['id']:<58} {m['device']['npu_usage']:>3}%  {flag}")
    return 0


def fetch_store(base: str, token: str) -> list[dict]:
    req = urllib.request.Request(
        base + STORE_PATH, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
