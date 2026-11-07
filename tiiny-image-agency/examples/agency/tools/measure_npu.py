#!/usr/bin/env python3
"""
measure_npu.py — capture the Tiiny's live NPU state as JSON.

Read-only. Never loads, unloads, or generates anything.

Usage:
  TIINY_API_KEY=<bearer> python3 measure_npu.py <label>
"""
import json
import os
from pathlib import Path
import sys
import urllib.request

BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny").rstrip("/")


def get(path):
    req = urllib.request.Request(
        BASE + path, headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    status = get("/api/v1/sys/status")
    resident = get("/v1/models")

    npu = (status.get("npus") or [{}])[0]
    mem = status.get("memory") or {}

    out = {
        "label": label,
        "npu": {
            "name": npu.get("name"),
            "utilization_pct": npu.get("utilization_percent"),
            "memory_used_mb": npu.get("memory_used_mb"),
            "memory_total_mb": npu.get("memory_total_mb"),
            "memory_free_mb": npu.get("memory_free_mb"),
        },
        "system": {
            "ram_used_bytes": mem.get("used_bytes"),
            "ram_total_bytes": mem.get("total_bytes"),
            "ram_usage_pct": mem.get("usage_percent"),
        },
        "resident": [
            {
                "id": m.get("id"),
                "type": m.get("type"),
                "supports_chat": m.get("supports_chat"),
                "supports_vision": m.get("supports_vision"),
                "context_window": m.get("context_window"),
            }
            for m in resident.get("data", [])
        ],
    }

    path = str(Path.home() / ".hermes" / "cache" / "scratch"
                    / f"npu-{label}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    n = out["npu"]
    print(f"[{label}] NPU {n['utilization_pct']}%  "
          f"{n['memory_used_mb']}/{n['memory_total_mb']} MB  "
          f"free {n['memory_free_mb']} MB")
    print(f"[{label}] resident ({len(out['resident'])}): "
          + ", ".join(m["id"] for m in out["resident"]))
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
