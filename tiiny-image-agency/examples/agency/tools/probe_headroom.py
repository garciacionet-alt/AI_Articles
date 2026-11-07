#!/usr/bin/env python3
"""
probe_headroom.py — where is the generation headroom limit?

Observed so far:
  62% alone (flagship)            -> generation WORKS   (197s, 202s)
  85% (enhancer 23% + flagship)   -> generation FAILS   (500 / 150004)
  89% (chat 27% + flagship)       -> generation FAILS   (500 / 150004)
  81% (planner 55% + Z-Image 26%) -> UNTESTED  <- the hot path

Also captures the PE-T2I 400 body with full detail.

Usage:
  TIINY_API_KEY=<bearer> python3 probe_headroom.py
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


def npu():
    out = subprocess.run([TIINY, "status"], capture_output=True, text=True, timeout=25).stdout
    m = RAMPAT.search(out)
    return (float(m.group(2)), float(m.group(3))) if m else (None, None)


def top_pct():
    out = subprocess.run([TIINY, "top"], capture_output=True, text=True, timeout=25).stdout
    m = re.search(r"NPU Used:\s*([\d.]+)%", out)
    return float(m.group(1)) if m else None


def load(model):
    t0 = time.time()
    subprocess.run(["script", "-q", "/dev/null", TIINY, "load", model, "-y"],
                   capture_output=True, timeout=300)
    return round(time.time() - t0, 1)


def chat_raw(model, payload):
    """POST chat/completions and return (status, body) without raising."""
    req = urllib.request.Request(
        INFER + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:800]


def generate(model, prompt, size, out_path):
    body = json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode()
    req = urllib.request.Request(
        INFER + "/images/generations", data=body,
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code,
                "body": e.read().decode("utf-8", "replace")[:300],
                "elapsed_sec": round(time.time() - t0, 2)}
    item = (out.get("data") or [{}])[0]
    raw = base64.b64decode(item.get("b64_json") or "")
    if raw:
        out_path.write_bytes(raw)
    return {"ok": bool(raw), "bytes": len(raw),
            "elapsed_sec": round(time.time() - t0, 2)}


def alpha(path):
    from PIL import Image
    im = Image.open(path)
    a = im.convert("RGBA").getchannel("A")
    h = a.histogram()
    t = sum(h)
    return {"fully_transparent_pct": round(100 * h[0] / t, 2),
            "partial_px": t - h[0] - h[255]}


def main():
    results = {}

    # ── TEST A: the hot path — planner 55% + Z-Image 26% = 81% ──────────
    print("TEST A — hot path: planner (55%) + Z-Image-Turbo (26%) = 81%")
    print(f"  load planner : {load('Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo')}s")
    print(f"  load Z-Image  : {load('Tongyi-MAI/Z-Image-Turbo')}s")
    used, total = npu()
    print(f"  NPU {top_pct()}%   NPU-RAM {used}/{total} GiB")
    a = generate("Tongyi-MAI/Z-Image-Turbo",
                 "A flat vector icon of a fox head, front-facing, single solid "
                 "orange fill, clean geometric shapes, transparent background, no text",
                 "1024x1024", SCRATCH / "fox-zimage.png")
    print(f"  generation: {a}")
    if a.get("ok"):
        print(f"  alpha: {alpha(SCRATCH / 'fox-zimage.png')}")
    results["A_planner55_plus_zimage26"] = {"npu_pct": top_pct(), "generation": a}

    # ── TEST B: flagship + 23% enhancer = 85%, then PE chat detail ──────
    print("\nTEST B — flagship (62%) + PE-T2I (23%) = 85%")
    print(f"  load PE-T2I   : {load('Qwen/Qwen-Image-2.1-PE-T2I')}s")
    print(f"  load flagship : {load('Qwen/Qwen-Image-2.1')}s")
    used, total = npu()
    print(f"  NPU {top_pct()}%   NPU-RAM {used}/{total} GiB")

    print("\n  PE-T2I chat probes:")
    variants = [
        ("plain", {"model": "Qwen/Qwen-Image-2.1-PE-T2I",
                   "messages": [{"role": "user", "content": "an app icon of a fox head"}],
                   "max_tokens": 800}),
        ("with thinking", {"model": "Qwen/Qwen-Image-2.1-PE-T2I",
                           "messages": [{"role": "user", "content": "an app icon of a fox head"}],
                           "max_tokens": 800,
                           "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}),
        ("system+user", {"model": "Qwen/Qwen-Image-2.1-PE-T2I",
                         "messages": [
                             {"role": "system", "content": "Expand the request into a detailed image description."},
                             {"role": "user", "content": "an app icon of a fox head"}],
                         "max_tokens": 800}),
    ]
    pe_detail = {}
    for label, payload in variants:
        status, body = chat_raw("Qwen/Qwen-Image-2.1-PE-T2I", payload)
        text = ""
        if isinstance(body, dict):
            text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        print(f"    [{label}] HTTP {status}  "
              f"{'-> ' + repr(text[:180]) if text else str(body)[:220]}")
        pe_detail[label] = {"status": status,
                            "text": text[:1200],
                            "body": body if not isinstance(body, dict) else None}
    results["B_pe_chat"] = {"npu_pct": top_pct(), "variants": pe_detail}

    print("\n  generation at 85% with the flagship:")
    b = generate("Qwen/Qwen-Image-2.1",
                 "A flat vector icon of a fox head, front-facing, single solid "
                 "orange fill, clean geometric shapes, transparent background, no text",
                 "1024x1024", SCRATCH / "fox-85pct.png")
    print(f"    {b}")
    results["B_generation_85pct"] = b

    path = SCRATCH / "headroom-probe.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
