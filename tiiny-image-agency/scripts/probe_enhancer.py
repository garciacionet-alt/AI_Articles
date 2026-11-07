#!/usr/bin/env python3
"""
probe_enhancer.py — the full two-model pipeline the device ships.

Qwen-Image-2.1-PE-T2I expands a one-line request into a ~20-sentence English
scene description plus an aspect ratio, and its output is designed to be
passed straight to Qwen-Image-2.1. If that works, the dialect translator in
SPEC.md is not something to build — it is a model on the device.

Also tests the residency claim: PE-T2I (23%) + Qwen-Image-2.1 (62%) = 85%.

Usage:
  TIINY_API_KEY=<bearer> python3 probe_enhancer.py "<request>"
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny").rstrip("/")
INFER = BASE + "/v1"
TIINY = os.path.expanduser("~/.local/tiiny/bin/tiiny")
SCRATCH = Path(os.environ.get(
    "TIS_SCRATCH", str(Path.home() / ".hermes" / "cache" / "scratch")))
RAMPAT = re.compile(r"NPU-RAM\s+\[.*?\]\s+([\d.]+)%\s+([\d.]+)\s*/\s*([\d.]+)\s*GiB")

ENHANCER = "Qwen/Qwen-Image-2.1-PE-T2I"
GENERATOR = "Qwen/Qwen-Image-2.1"


def npu_ram():
    out = subprocess.run([TIINY, "status"], capture_output=True, text=True, timeout=25).stdout
    m = RAMPAT.search(out)
    return (float(m.group(2)), float(m.group(3))) if m else (None, None)


def top():
    out = subprocess.run([TIINY, "top"], capture_output=True, text=True, timeout=25).stdout
    return out


def load(model):
    t0 = time.time()
    subprocess.run(["script", "-q", "/dev/null", TIINY, "load", model, "-y"],
                   capture_output=True, timeout=300)
    return round(time.time() - t0, 1)


def chat(model, prompt, max_tokens=1200, thinking=None):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0}
    if thinking is not None:
        body["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}
    req = urllib.request.Request(
        INFER + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read().decode())
    ch = (out.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return {
        "text": (msg.get("content") or "").strip(),
        "reasoning": (msg.get("reasoning_content") or "")[:600],
        "elapsed_sec": round(time.time() - t0, 2),
        "usage": out.get("usage"),
        "finish_reason": ch.get("finish_reason"),
    }


def generate(model, prompt, size, out_path):
    body = json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode()
    req = urllib.request.Request(
        INFER + "/images/generations", data=body,
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read().decode())
    item = (out.get("data") or [{}])[0]
    raw = base64.b64decode(item["b64_json"]) if item.get("b64_json") else b""
    if raw:
        out_path.write_bytes(raw)
    return {"elapsed_sec": round(time.time() - t0, 2), "bytes": len(raw)}


def alpha(path):
    from PIL import Image
    im = Image.open(path)
    a = im.convert("RGBA").getchannel("A")
    h = a.histogram()
    t = sum(h)
    return {"size": list(im.size), "mode": im.mode,
            "fully_transparent_pct": round(100 * h[0] / t, 2),
            "partial_px": t - h[0] - h[255], "opaque_px": h[255]}


def main():
    request = sys.argv[1] if len(sys.argv) > 1 else \
        "an app icon of a fox head, flat, transparent background"
    print(f"request: {request}\n")

    print("STEP 1 — load the enhancer")
    print(f"  load {ENHANCER}: {load(ENHANCER)}s")
    used, total = npu_ram()
    print(f"  NPU-RAM {used}/{total} GiB")

    print("\nSTEP 2 — load the generator on top (23% + 62% = 85%)")
    print(f"  load {GENERATOR}: {load(GENERATOR)}s")
    used, total = npu_ram()
    print(f"  NPU-RAM {used}/{total} GiB")
    print(top())

    print("STEP 3 — expand the request with PE-T2I")
    for thinking in (None, False):
        try:
            r = chat(ENHANCER, request, thinking=thinking)
        except Exception as e:
            print(f"  thinking={thinking}: ERROR {e}")
            continue
        label = "default" if thinking is None else f"thinking={thinking}"
        print(f"  [{label}] {r['elapsed_sec']}s  finish={r['finish_reason']}  "
              f"usage={r.get('usage')}")
        if r["text"]:
            print(f"    -> {r['text'][:500]}")
            if len(r["text"]) > 200:
                expanded = r["text"]
                break
    else:
        expanded = request

    print("\nSTEP 4 — generate with the expanded prompt")
    size = "1024x1024"
    try:
        g = generate(GENERATOR, expanded, size,
                     SCRATCH / "fox-enhanced.png")
        print(f"  {g['elapsed_sec']}s  {g['bytes']} bytes")
        a = alpha(SCRATCH / "fox-enhanced.png")
        print(f"  alpha: {a}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}")
        g, a = {"error": e.code}, None

    out = {"request": request, "expanded": expanded, "generation": g, "alpha": a}
    with open(SCRATCH / "enhancer-probe.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n-> {SCRATCH/'enhancer-probe.json'}")


if __name__ == "__main__":
    main()
