#!/usr/bin/env python3
"""
probe_context_sweep.py — is the KV cache linear in context, and does it free?

Three questions the residency budget needs answered:
  1. Is the per-token cost constant, or does it scale with length?
  2. Does a DIFFERENT prompt of the same size re-use the buffer, or add to it?
  3. Does a smaller prompt after a large one release the memory?

Usage:
  TIINY_API_KEY=<bearer> python3 probe_context_sweep.py [model_id]
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


def npu_used():
    req = urllib.request.Request(
        BASE + "/api/v1/sys/status",
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        s = json.loads(r.read().decode())
    n = (s.get("npus") or [{}])[0]
    return n.get("memory_used_mb")


def chat(model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4, "temperature": 0,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }).encode("utf-8")
    req = urllib.request.Request(
        INFER + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read().decode())
    u = out.get("usage") or {}
    return u.get("prompt_tokens"), round(time.time() - t0, 2)


def filler(n_chars, seed_word):
    unit = f"The {seed_word} fox jumps over the lazy dog near the quiet riverbank. "
    return (unit * (n_chars // len(unit) + 1))[:n_chars]


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.6-35B-A3B"
    print(f"model: {model}\n")

    steps = [
        ("A  baseline (no call)", None, None),
        ("B  ~8k tokens",          30_000,  "alpha"),
        ("C  ~8k tokens, DIFFERENT text", 30_000, "beta"),
        ("D  ~30k tokens",         120_000, "gamma"),
        ("E  ~8k tokens again",     30_000, "delta"),
    ]

    rows = []
    prev = None
    for label, nchars, word in steps:
        if nchars is None:
            used = npu_used()
            print(f"{label:36s} NPU {used:>6} MB")
            rows.append({"label": label, "npu_used_mb": used})
            prev = used
            continue
        toks, secs = chat(model, filler(nchars, word))
        used = npu_used()
        delta = (used - prev) if prev is not None else None
        print(f"{label:36s} NPU {used:>6} MB  (delta {delta:+} MB)  "
              f"{toks:>7,} tok  {secs:>6.1f}s")
        rows.append({"label": label, "npu_used_mb": used, "delta_mb": delta,
                     "prompt_tokens": toks, "elapsed_sec": secs,
                     "kb_per_token": round(delta * 1024 / toks, 3) if delta and delta > 0 else None})
        prev = used

    print("\n--- SUMMARY ---")
    for r in rows:
        if r.get("delta_mb") is not None:
            print(f"  {r['label']:36s} {r['delta_mb']:+6} MB  "
                  f"{r.get('kb_per_token') or '-':>7} KB/token")
    print("\nReading: negative delta at step E means the cache FREED.")
    print("         positive delta at step C means it GROWS with distinct content.")

    path = f"{SCRATCH}/context-sweep.json"
    with open(path, "w") as f:
        json.dump({"model": model, "steps": rows}, f, indent=2)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
