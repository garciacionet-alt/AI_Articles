#!/usr/bin/env python3
"""
probe_context_mem.py — does the KV cache consume NPU-RAM, and does it free?

The management API's `npus[0].memory_used_mb` is unreliable (its "total"
changes between reads with no device-state change), so it is not the
instrument. `tiiny status` reports NPU-RAM in GiB and has been stable across
many reads — use that, and sample it CONTINUOUSLY during the call so a
transient allocation is not missed after the fact.

Method:
  - start a chat in a background thread
  - poll `tiiny status` every 1.5 s while it runs
  - report baseline / peak / settled NPU-RAM
  - repeat at two context sizes, and with a third call to see if the
    allocation is released

Usage:
  TIINY_API_KEY=<bearer> python3 probe_context_mem.py [model_id]
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.request

BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny").rstrip("/")
INFER = BASE + "/v1"
TIINY = os.path.expanduser("~/.local/tiiny/bin/tiiny")
SCRATCH = os.environ.get(
    "TIS_SCRATCH", str(Path.home() / ".hermes" / "cache" / "scratch"))

RAMPAT = re.compile(r"NPU-RAM\s+\[.*?\]\s+([\d.]+)%\s+([\d.]+)\s*/\s*([\d.]+)\s*GiB")


def npu_ram():
    """NPU-RAM used / total in GiB, from the CLI."""
    try:
        out = subprocess.run([TIINY, "status"], capture_output=True, text=True, timeout=25).stdout
        m = RAMPAT.search(out)
        if m:
            return float(m.group(2)), float(m.group(3))
    except Exception:
        pass
    return None, None


def chat(model, prompt):
    body = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
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


def filler(n_chars, word):
    unit = f"The {word} fox jumps over the lazy dog near the quiet riverbank. "
    return (unit * (n_chars // len(unit) + 1))[:n_chars]


def run_sampled(model, label, nchars, word):
    samples = []
    stop = threading.Event()
    result = {}

    def sampler():
        while not stop.is_set():
            used, total = npu_ram()
            if used is not None:
                samples.append((round(time.time(), 2), used, total))
            stop.wait(1.5)

    t = threading.Thread(target=sampler, daemon=True)
    t.start()
    time.sleep(2)
    toks, secs = chat(model, filler(nchars, word) if nchars else "Reply: ok")
    time.sleep(2)
    stop.set()
    t.join(timeout=5)

    vals = [s[1] for s in samples]
    base = vals[0] if vals else 0
    peak = max(vals) if vals else 0
    settled = vals[-1] if vals else 0
    print(f"{label:32s} tok={str(toks or '?'):>7}  {secs:>6.1f}s  "
          f"NPU-RAM base={base:.1f} peak={peak:.1f} settled={settled:.1f} GiB  "
          f"(peak-base={peak-base:+.1f})")
    return {"label": label, "tokens": toks, "elapsed_sec": secs,
            "base_gib": base, "peak_gib": peak, "settled_gib": settled,
            "samples": samples}


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.6-35B-A3B"
    print(f"model: {model}")
    used, total = npu_ram()
    print(f"initial NPU-RAM: {used} / {total} GiB\n")

    runs = [
        run_sampled(model, "A  small (~2k tok)",     7_000,  "alpha"),
        run_sampled(model, "B  large (~30k tok)",  120_000, "gamma"),
        run_sampled(model, "C  small again (~2k)",   7_000,  "delta"),
        run_sampled(model, "D  large, new text",  120_000, "epsilon"),
    ]

    print("\n--- READING ---")
    for r in runs:
        if r["tokens"] and r["peak_gib"] is not None:
            delta = r["peak_gib"] - r["base_gib"]
            per_k = delta * 1024 * 1024 / r["tokens"] / 1024
            print(f"  {r['label']:32s} peak-base {delta:+.1f} GiB  ~{per_k:.2f} KiB/token")
    print("\n  C returning to baseline  -> the cache IS released after the call")
    print("  D re-allocating           -> the cache is not a permanent reservation")
    print("  flat NPU-RAM across all   -> context does NOT consume the NPU pool")

    path = f"{SCRATCH}/context-mem.json"
    with open(path, "w") as f:
        json.dump({"model": model, "runs": runs}, f, indent=2)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
