#!/usr/bin/env python3
"""
probe_image.py — generate one image on the device and inspect what came back.

Measures:
  - generation latency (wall clock)
  - whether the PNG carries a real alpha channel
  - how many pixels are actually transparent
  - the model's answer vs the request (field-by-field)

Writes the image and a JSON record. Read-only against the device apart from
the generation call itself.

Usage:
  TIINY_API_KEY=<bearer> python3 probe_image.py <model_id> <prompt> <WxH> <out.png>
"""
import base64
import json
import os
import struct
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny").rstrip("/")
# The inference surface lives under /v1; the management surface is at the root.
INFER_BASE = BASE + "/v1"
SCRATCH = Path(os.environ.get(
    "TIS_SCRATCH", str(Path.home() / ".hermes" / "cache" / "scratch")))


def post_images(model, prompt, size, timeout=420):
    body = json.dumps({
        "model": model, "prompt": prompt, "size": size, "n": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        INFER_BASE + "/images/generations", data=body,
        headers={"Authorization": f"Bearer {os.environ['TIINY_API_KEY']}",
                 "Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8")), time.time() - t0


def inspect_png(data: bytes) -> dict:
    """Parse the PNG header and chunks without any third-party library."""
    info = {}
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return {"is_png": False, "bytes": len(data)}

    info["is_png"] = True
    info["bytes"] = len(data)
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8].decode("ascii", "replace")
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == "IHDR":
            w, h, bitdepth, colortype, comp, filt, interlace = struct.unpack(">IIBBBBB", chunk)
            info.update({
                "width": w, "height": h, "bit_depth": bitdepth,
                "color_type": colortype, "interlace": interlace,
            })
            info["has_alpha_channel"] = colortype in (4, 6)
            info["color_type_name"] = {0: "greyscale", 2: "RGB", 3: "palette",
                                       4: "greyscale+alpha", 6: "RGBA"}.get(colortype, str(colortype))
        elif ctype == "tRNS":
            info["has_trns_chunk"] = True
        pos += 12 + length
    return info


def alpha_stats(path: Path) -> dict:
    """Pixel-level alpha stats, if Pillow is available."""
    try:
        from PIL import Image
    except ImportError:
        return {"pil": "unavailable"}
    im = Image.open(path)
    out = {"pil": Image.__version__, "mode": im.mode, "size": list(im.size)}
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        alpha = im.convert("RGBA").getchannel("A")
        hist = alpha.histogram()
        total = sum(hist)
        out["alpha_min"] = min(i for i, c in enumerate(hist) if c)
        out["alpha_max"] = max(i for i, c in enumerate(hist) if c)
        out["fully_transparent_px"] = hist[0]
        out["fully_opaque_px"] = hist[255]
        out["partial_alpha_px"] = total - hist[0] - hist[255]
        out["transparent_pct"] = round(100.0 * hist[0] / total, 2) if total else 0.0
    else:
        out["alpha_channel"] = False
    return out


def main():
    model = sys.argv[1]
    prompt = sys.argv[2]
    size = sys.argv[3] if len(sys.argv) > 3 else "1024x1024"
    out_path = Path(sys.argv[4]) if len(sys.argv) > 4 else SCRATCH / "probe.png"

    print(f"model={model}  size={size}")
    print(f"prompt={prompt[:110]}")
    try:
        result, elapsed = post_images(model, prompt, size)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        print(f"HTTP {e.code}: {body}")
        return 1
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    data = result.get("data") or []
    if not data:
        print(f"No image returned: {json.dumps(result)[:400]}")
        return 1

    item = data[0]
    if item.get("b64_json"):
        raw = base64.b64decode(item["b64_json"])
        src = "b64_json"
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=180) as r:
            raw = r.read()
        src = "url"
    else:
        print("Neither b64_json nor url in the response.")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)

    record = {
        "model_requested": model,
        "size_requested": size,
        "prompt": prompt,
        "elapsed_sec": round(elapsed, 2),
        "response_source": src,
        "response_model": result.get("model"),
        "response_keys": sorted(result.keys()),
        "png": inspect_png(raw),
        "pixels": alpha_stats(out_path),
        "written_to": str(out_path),
    }
    rec_path = SCRATCH / f"probe-{model.split('/')[-1]}.json"
    rec_path.write_text(json.dumps(record, indent=2))

    print(f"\n--- RESULT ---")
    print(f"elapsed        : {record['elapsed_sec']}s")
    print(f"response model : {record['response_model']}")
    print(f"png            : {record['png'].get('width')}x{record['png'].get('height')} "
          f"color_type={record['png'].get('color_type_name')} "
          f"alpha_channel={record['png'].get('has_alpha_channel')}")
    px = record["pixels"]
    if px.get("pil") != "unavailable":
        print(f"alpha pixels   : transparent={px.get('transparent_pct')}% "
              f"partial={px.get('partial_alpha_px')} opaque={px.get('fully_opaque_px')}")
    else:
        print("alpha pixels   : Pillow unavailable — header check only")
    print(f"image          : {out_path} ({len(raw)} bytes)")
    print(f"record         : {rec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
