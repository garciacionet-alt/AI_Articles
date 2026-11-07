#!/usr/bin/env python3
"""
probe_context.py — does context length consume NPU-RAM or system RAM?

The gap in the Phase 0 measurements: NPU-RAM used (39.9 GiB) minus the sum of
resident model sizes (32.21 GiB) = 7.7 GiB unexplained. Hypothesis: that is
preallocated KV cache, which means context length is a THIRD term in the
residency budget, not just a number the chat model happens to advertise.

Method:
  1. capture NPU-RAM + system RAM
  2. chat with a tiny prompt  -> capture again
  3. chat with a large prompt -> capture again
  4. report the deltas

Usage:
  TIINY_API_KEY=<bearer> python3 probe_context.py <model_id> [big_chars]
"""
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny").rstrip("/")
INFER = BASE + "/v1"
SCRATCH = os.environ.get(
    "TIS_SCRATCH", str(Path.home() / ".hermes" / "cache" / "scratch"))


def snap(label):
    req = urllib.request.Request(
        BASE + "/api/v1/sys/status",
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        s = json.loads(r.read().decode())
    npu = (s.get("npus") or [{}])[0]
    mem = s.get("memory") or {}
    out = {
        "label": label,
        "npu_used_mb": npu.get("memory_used_mb"),
        "npu_total_mb": npu.get("memory_total_mb"),
        "npu_util_pct": npu.get("utilization_percent"),
        "ram_used_bytes": mem.get("used_bytes"),
        "ram_total_bytes": mem.get("total_bytes"),
        "ram_usage_pct": mem.get("usage_percent"),
    }
    print(f"  {label:28s} NPU {out['npu_used_mb']:>6}/{out['npu_total_mb']} MB   "
          f"RAM {out['ram_usage_pct']:>6}%")
    return out


def chat(model, prompt, max_tokens=16):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }).encode("utf-8")
    req = urllib.request.Request(
        INFER + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read().decode())
    usage = out.get("usage") or {}
    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": (out.get("choices") or [{}])[0].get("finish_reason"),
    }


def main():
    model = sys.argv[1]
    big_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 300_000

    print(f"model: {model}")
    print(f"big prompt: {big_chars:,} chars\n")

    print("STEP 0 — baseline")
    s0 = snap("before any call")

    print("\nSTEP 1 — tiny prompt")
    t1 = chat(model, "Reply with the single word: ok")
    print(f"  -> {t1}")
    s1 = snap("after tiny call")

    print(f"\nSTEP 2 — large prompt ({big_chars:,} chars)")
    filler = ("The quick brown fox jumps over the lazy dog. " * (big_chars // 45))
    t2 = chat(model, filler + "\n\nReply with the single word: ok")
    print(f"  -> {t2}")
    s2 = snap("after large call")

    print("\nSTEP 3 — large prompt again (cache warm?)")
    t3 = chat(model, filler + "\n\nReply with the single word: ok")
    print(f"  -> {t3}")
    s3 = snap("after second large call")

    def d(a, b, k):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            return round(vb - va, 2)
        return None

    print("\n--- DELTAS ---")
    print(f"tiny call   : NPU {d(s0,s1,'npu_used_mb')} MB   RAM {d(s0,s1,'ram_usage_pct')} pct")
    print(f"large call  : NPU {d(s1,s2,'npu_used_mb')} MB   RAM {d(s1,s2,'ram_usage_pct')} pct")
    print(f"large again : NPU {d(s2,s3,'npu_used_mb')} MB   RAM {d(s2,s3,'ram_usage_pct')} pct")
    print(f"total       : NPU {d(s0,s3,'npu_used_mb')} MB   RAM {d(s0,s3,'ram_usage_pct')} pct")
    print(f"\nprompt tokens charged: tiny={t1['prompt_tokens']}  "
          f"large={t2['prompt_tokens']}  large_again={t3['prompt_tokens']}")

    out = {"model": model, "big_chars": big_chars,
           "snapshots": [s0, s1, s2, s3],
           "calls": [t1, t2, t3]}
    path = f"{SCRATCH}/context-probe.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
