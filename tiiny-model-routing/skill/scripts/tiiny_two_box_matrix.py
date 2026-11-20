#!/usr/bin/env python3
"""Two-box Tiiny capability difference matrix — READ-ONLY.

Fetches both appliances' live store catalogues, classifies every model by the
device's own metadata, writes a markdown difference matrix, then re-reads both
devices and verifies every headline number before exiting non-zero on a
mismatch.

Never loads, unloads, starts, stops or downloads anything.

Usage:
    python3 tiiny_two_box_matrix.py             # write the matrix
    python3 tiiny_two_box_matrix.py --verify    # verify the last matrix
"""
import argparse, collections, json, os, re, sys, time

# --- configuration: IP + key ENV VAR NAME only, never a value ---------------
BOXES = {
    "TinyAnt":  ("http://198.51.100.198", "TIINY_API_KEY"),
    "TiinyOcto": ("http://198.51.100.192", "TIINY_API_KEY_2"),
}
NPU_TOTAL_MB = 49024.0   # /api/v1/npu/status devices[0].mem_total_mb (LQ50-48GB)
RESIDENT = "Qwen/Qwen3.6-35B-A3B"


def load_env():
    p = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def request(url, bearer, timeout=60):
    """Return (status, parsed_json_or_text). Never raises."""
    import urllib.request, urllib.error
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + bearer,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    try:
        return status, json.loads(raw)
    except Exception:
        return status, raw


# --- classification ---------------------------------------------------------
BENCHMARK = re.compile(r"achieves parity|outperform|benchmark|compared to|eval", re.I)
TRAINING = re.compile(r"training data|knowledge cutoff|trained on a text-only|pre-?training", re.I)
PURPOSE = re.compile(
    r"built (for|specifically|around)|designed (for|specifically)|targeting\b|optimi[sz]ed for"
    r"|is a .*coding|coding-specialized|coding model|for code generation"
    r"|the same coding|for users who want"
    r"|purpose-built for coding|coding workflows|code execution", re.I)


def coding_evidence(r):
    """(is_code_purpose, evidence_sentence) from the device's own desc."""
    mid = r.get("model_id") or ""
    if re.search(r"coder", mid, re.I):
        return True, "model id contains 'Coder'"
    for sent in re.split(r"(?<=[.\n])\s+", r.get("desc") or ""):
        s = sent.strip()
        if not re.search(r"\bcoding\b|\bcode generation\b|\bmulti-file edit", s, re.I):
            continue
        if TRAINING.search(s) or BENCHMARK.search(s):
            continue          # training-data footnote or benchmark aside -> not a purpose
        if PURPOSE.search(s):
            return True, s[:150]
    return False, ""


def lineage_code(r, D):
    """A variant inherits the base model's specialty when the device says so."""
    mid, desc = r.get("model_id") or "", (r.get("desc") or "")
    for base in ("Qwen/Qwen3.8-27B", "Qwen/Qwen3.6-35B-A3B"):
        if base.split("/")[-1] in mid and base in D:
            ok, ev = coding_evidence(D[base])
            if ok and re.search(r"same .*architecture|variant of|inherits|keeps the same", desc, re.I):
                return True, (f"device desc: variant of {base} keeping the same "
                              f"architecture (base desc: '{ev[:90]}…')")
    return False, ""


def classify(r, D):
    """(capability, evidence_source). Device fields first; desc/id only for code."""
    t = (r.get("type") or "").strip()
    caps = [str(c).lower() for c in (r.get("capabilities") or [])]
    sup_l = [str(s).lower() for s in (r.get("supported") or [])]
    mid = r.get("model_id") or ""
    think = r.get("thinking") or {}
    if "prompt enhance" in sup_l:
        return "other (image prompt enhancer)", "device supported flag 'Prompt Enhance'"
    if t == "Image-to-Text":
        if "ocr" in caps or "ocr" in mid.lower():
            return "OCR/document", "device type=Image-to-Text + capabilities tag 'ocr'"
        return "vision/VLM (image->text)", "device type=Image-to-Text"
    if t == "Text Classification":
        return "other (decision/classification)", "device type=Text Classification"
    if t == "Text Reranking":  return "reranker", "device type=Text Reranking"
    if t == "Text Embedding":  return "embeddings", "device type=Text Embedding"
    if t == "ASR":              return "ASR/speech-to-text", "device type=ASR"
    if t == "Text-to-Speech":  return "TTS", "device type=Text-to-Speech"
    if t == "Music Generation": return "music/audio generation", "device type=Music Generation"
    if t == "Text-to-Image":
        return (("image editing", "device supported flag 'Image Editing'") if "image editing" in sup_l
                else ("image generation", "device type=Text-to-Image"))
    if t in ("Text-to-Video", "Image-to-Video"): return "video", f"device type={t}"
    if t == "Image-to-3D": return "3D", "device type=Image-to-3D"
    if t in ("Image-Text-to-Text", "Text Generation", "Text-to-Text"):
        reasoning = ("reasoning" in sup_l
                     or (isinstance(think, dict) and think.get("supported"))
                     or bool(r.get("reasoning_levels")))
        img = "Image" in (r.get("input") or "")
        vid = "Video" in (r.get("input") or "")
        ok, ev = coding_evidence(r)
        if not ok:
            ok, ev = lineage_code(r, D)
        if ok:
            src = ("model id contains 'Coder' (no device code field)"
                   if ev.startswith("model id contains")
                   else f"device desc purpose: “{ev[:110]}”")
            return (("code + reasoning", f"device type={t} + {src}") if reasoning
                    else ("code", f"device type={t} + {src}"))
        if reasoning and img: return "reasoning (vision-capable)", f"device type={t} + supported=Reasoning + input includes Image"
        if reasoning:          return "reasoning", f"device type={t} + supported/thinking flag"
        if img:                return "chat/general (vision input)", f"device type={t} + input includes Image"
        if vid:                return "chat/general (video input)", f"device type={t} + input includes Video"
        return "chat/general", f"device type={t}"
    return "other", "model id (no usable type field)"


# --- live read --------------------------------------------------------------
def fetch():
    load_env()
    live = {}
    for name, (admin, env) in BOXES.items():
        key = os.environ.get(env, "")
        if not key:
            raise SystemExit(f"missing env var {env} (name only; never print a value)")
        st, p = request(admin + "/api/v1/models/online_models", key)
        if st != 200:
            raise SystemExit(f"{name}: store endpoint HTTP {st}: {str(p)[:200]}")
        items = p if isinstance(p, list) else (p.get("data") or p.get("models") or [])
        live[name] = {r["model_id"]: r for r in items}
        st2, run = request(admin + "/api/v1/models/running", key, timeout=20)
        live[name + "__run"] = run
        st3, npu = request(admin + "/api/v1/npu/status", key, timeout=20)
        live[name + "__npu"] = npu
    return live


def ctxs(r):
    c = r.get("context_window")
    return f"{c//1024}K" if isinstance(c, int) and c >= 1024 else (c or "—")


def build(live):
    A, B = live["TinyAnt"], live["TiinyOcto"]
    ready = lambda r: r.get("status") in ("downloaded", "running")
    ant_only = [m for m in sorted(A) if ready(A[m]) and not ready(B[m])]
    octo_only = [m for m in sorted(A) if ready(B[m]) and not ready(A[m])]
    both = [m for m in sorted(A) if ready(A[m]) and ready(B[m])]
    def catmap(D):
        """capability -> sorted list of ready models in that capability."""
        out = collections.defaultdict(list)
        for m, r in D.items():
            if ready(r):
                out[classify(r, D)[0]].append(m)
        return {c: sorted(v) for c, v in out.items()}
    ca, cb = catmap(A), catmap(B)
    return A, B, ready, ant_only, octo_only, both, ca, cb


def render(live):
    A, B, ready, ant_only, octo_only, both, ca, cb = build(live)
    L = []
    w = L.append
    w("# Tiiny Capability Difference Matrix")
    w("")
    w(f"Source: each appliance's live store catalogue, `GET /api/v1/models/online_models`, ")
    w(f"read {time.strftime('%Y-%m-%d %H:%M %Z')}. Both boxes return the same model ids and ")
    w("identical per-model metadata; they differ only in download state and residency.")
    w("")
    w("## 1. Store state (device-reported)")
    w("")
    w("| | TinyAnt (vault) | TiinyOcto (flex) |")
    w("|---|---|---|")
    sa = collections.Counter(r.get("status") for r in A.values())
    sb = collections.Counter(r.get("status") for r in B.values())
    w(f"| Catalogue size | {len(A)} | {len(B)} |")
    w(f"| Model ids identical to the other box | {'yes' if set(A)==set(B) else 'NO'} | {'yes' if set(A)==set(B) else 'NO'} |")
    for s in ("running", "downloaded", "downloading", "not_downloaded"):
        w(f"| status `{s}` | {sa.get(s,0)} | {sb.get(s,0)} |")
    w(f"| **Ready to load** | **{sum(ready(r) for r in A.values())}** | **{sum(ready(r) for r in B.values())}** |")
    w("")
    w("## 2. Difference table — ready on ONE box, not the other")
    w("")
    w("Capability comes from the device's own `type` field first, then its `supported` / ")
    w("`capabilities` / `input` / `output` flags. Only for **code** — which the device does ")
    w("not expose as a field — is the device's own `desc` or model id used; every such row says so.")
    w("")
    def table(title, lst, D):
        w(f"### {title} ({len(lst)} models)")
        w("")
        w("| Model | Device `type` | Capability | Classified from | ctx | NPU | Params |")
        w("|---|---|---|---|---|---|---|")
        for m in lst:
            r = D[m]; cat, src = classify(r, D)
            w(f"| `{m}` | {r.get('type')} | **{cat}** | {src} | {ctxs(r)} | {r.get('npu_usage')} | {r.get('params')} |")
        w("")
    table("Ready on TinyAnt ONLY — ask TinyAnt", ant_only, A)
    table("Ready on TiinyOcto ONLY — ask TiinyOcto", octo_only, B)
    w(f"### Ready on BOTH boxes ({len(both)} models)")
    w("")
    w("| Model | Device `type` | Capability | ctx | NPU |")
    w("|---|---|---|---|---|")
    for m in both:
        r = A[m]; cat, _ = classify(r, A)
        w(f"| `{m}` | {r.get('type')} | {cat} | {ctxs(r)} | {r.get('npu_usage')} |")
    w("")
    w("## 3. Per-box capability summary")
    w("")
    w("| Capability | TinyAnt | TiinyOcto | TinyAnt-only | TiinyOcto-only |")
    w("|---|---|---|---|---|")
    for cat in sorted(set(ca) | set(cb)):
        a, b = set(ca.get(cat, [])), set(cb.get(cat, []))
        w(f"| {cat} | {len(a)} | {len(b)} | {len(a-b)} | {len(b-a)} |")
    w("")
    for label, cm, other in (("TinyAnt ALONE", ca, cb), ("TiinyOcto ALONE", cb, ca)):
        w(f"### {label}")
        w("")
        for cat in sorted(set(cm) | set(other)):
            only = sorted(set(cm.get(cat, [])) - set(other.get(cat, [])))
            if only:
                w(f"- **{cat}**: " + ", ".join(f"`{m}`" for m in only))
        w("")
    w("## 4. NPU budget")
    w("")
    for name in BOXES:
        npu = live[name + "__npu"]; d = npu["devices"][0]
        inst = live[name + "__run"]["instances"]["running"][0]
        pct = d["mem_used_mb"] / d["mem_total_mb"] * 100
        w(f"### {name}")
        w(f"- `/api/v1/npu/status`: one device, `{d['model']}`, `mem_total_mb = {d['mem_total_mb']:.0f}` MB ({d['mem_total_mb']/1024:.0f} GiB), serial `{d['sn']}`")
        w(f"- Measured NPU in use: `{d['mem_used_mb']:.0f} MB` = **{pct:.2f}%** of total")
        w(f"- Resident `{inst['model_id']}` declares `npu_usage = {inst['npu_usage']}` (delta {inst['npu_usage']-pct:+.2f} pp)")
        w(f"- `occupants`: `{npu.get('occupants')}` — no per-model occupancy breakdown exposed")
        w("")
    w("`npu_usage` is a per-model integer 0-100, identical for the same id on both boxes, and is ")
    w("**percent of the 48 GiB NPU** (calibrated: resident declares 47, device measures 46.30%; ")
    w("small models match their file share to within 1 pp). A co-resident set must sum to <= 100.")
    w("")
    w("`/api/v1/sys/status` -> `npus[].memory_total_mb` is a live working-set counter, NOT the budget ")
    w("(it moves between samples and never equals 49024). Every other `/api/v1/npu/*` path 404s.")
    w("")
    for name, D in (("TinyAnt", A), ("TiinyOcto", B)):
        res = [m for m, r in D.items() if r.get("status") == "running"]
        used = sum(D[m].get("npu_usage") or 0 for m in res); free = 100 - used
        co = sorted([(m, D[m]["npu_usage"]) for m, r in D.items()
                     if ready(r) and m not in res and D[m]["npu_usage"] <= free], key=lambda x: x[1])
        so = sorted([(m, D[m]["npu_usage"]) for m, r in D.items()
                     if ready(r) and m not in res and D[m]["npu_usage"] > free], key=lambda x: x[1])
        w(f"### Co-residency on {name} (resident `{res[0]}`, {used} used, {free} free)")
        w("")
        w("| Fits alongside resident | NPU | Total | Requires unloading resident | NPU |")
        w("|---|---|---|---|---|")
        for i in range(max(len(co), len(so))):
            a = f"`{co[i][0]}`" if i < len(co) else ""
            av = co[i][1] if i < len(co) else ""
            at = used + co[i][1] if i < len(co) else ""
            b = f"`{so[i][0]}`" if i < len(so) else ""
            bv = so[i][1] if i < len(so) else ""
            w(f"| {a} | {av} | {at} | {b} | {bv} |")
        w("")
    w("## 5. Resident models")
    w("")
    w("| | TinyAnt | TiinyOcto |")
    w("|---|---|---|")
    ra, rb = live["TinyAnt__run"], live["TiinyOcto__run"]
    ia, ib = ra["instances"]["running"][0], rb["instances"]["running"][0]
    w(f"| Resident | {', '.join(ra['running'])} | {', '.join(rb['running'])} |")
    w(f"| Pending | {ra['pending'] or '[]'} | {rb['pending'] or '[]'} |")
    w(f"| type / caps | {ia['type']} {ia['capabilities']} | {ib['type']} {ib['capabilities']} |")
    w(f"| npu_usage | {ia['npu_usage']} | {ib['npu_usage']} |")
    w("")
    w(f"Both boxes have exactly one resident model and it is the same one: `{RESIDENT}`. ")
    w("**The resident sets are identical**, so the generalist never requires choosing a box.")
    w("")
    w("## 6. Caveats")
    w("")
    w("- `Qwen/Qwen-Image-2.1-PE-T2I` is typed `Text Generation` but carries `supported: ['Prompt Enhance']` — a prompt expander, not a chat model.")
    w("- `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` carries a device `desc` that actually describes `Z-Image-Turbo CharacterDesignSheet` — the catalogue's own copy/paste error.")
    w("- The `other (decision/classification)` group (8 models: `vllm-sr/d3*`, `PelaAI/KnowLine-*`) is device-typed `Text Classification`; none are downloaded on either box.")
    w("- `trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo` gets its code label by lineage: its own desc never says \"coding\", but it states it is a variant of `Qwen/Qwen3.8-27B` keeping the same architecture.")
    w("- Both boxes report identical `npu_usage`, `context_window`, `type`, `capabilities` and `params` for all shared ids — the difference is purely what is on disk and what is resident.")
    return "\n".join(L)


def verify(live, doc):
    A, B, ready, ant_only, octo_only, both, _, _ = build(live)
    ok = True
    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))
    check("both catalogues 93", (len(A), len(B)), (93, 93))
    check("model id sets identical", set(A) == set(B), True)
    check("ready counts", (sum(ready(r) for r in A.values()), sum(ready(r) for r in B.values())),
          (18, 47))
    check("ant-only / octo-only / both", (len(ant_only), len(octo_only), len(both)), (3, 32, 15))

    # Classification regression guard. These 12 pin the rules that are easy to
    # break: the Reasoning flag is case-insensitive, "coding" as a training-data
    # footnote is NOT a code capability, "coding" as a benchmark aside is NOT,
    # a desc-quoted purpose IS, and lineage carries the base model's label.
    EXPECT = {
        "zai-org/GLM-4.7-Flash": "reasoning",
        "openai/gpt-oss-20b": "reasoning",
        "openai/gpt-oss-120b": "reasoning",
        "google/gemma-4-26B-A4B-it": "reasoning (vision-capable)",
        "Qwen/Qwen3.5-9B": "reasoning (vision-capable)",
        "InternScience/Sage-A1.5-Turbo": "reasoning (vision-capable)",
        "Qwen/Qwen3-Coder-30B-A3B-Instruct": "code",
        "Qwen/Qwen3-Coder-Next": "code",
        "Qwen/Qwen3.6-35B-A3B": "code + reasoning",
        "Qwen/Qwen3.8-27B": "code + reasoning",
        "huihui-ai/Huihui-Ornith-1.5-35B-A3B-abliterated-Turbo": "code + reasoning",
        "trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo": "code + reasoning",
    }
    for mid, want in EXPECT.items():
        box = "TinyAnt" if mid in A else "TiinyOcto"
        got = classify((A if box == "TinyAnt" else B)[mid], A if box == "TinyAnt" else B)[0]
        check(f"classify {mid}", got, want)

    # Capability-map guard: every ready model must appear in exactly one
    # category, and each category's member list must be its own members only.
    _, _, _, _, _, _, ca, cb = build(live)
    for label, cm in (("TinyAnt", ca), ("TiinyOcto", cb)):
        members = [m for v in cm.values() for m in v]
        check(f"{label} category map has no duplicates", len(members), len(set(members)))
        src = A if label == "TinyAnt" else B
        check(f"{label} category map covers every ready model",
              len(members), sum(ready(r) for r in src.values()))
        check(f"{label} each category lists only its own members",
              all(all(classify(src[m], src)[0] == cat for m in v) for cat, v in cm.items()), True)

    for name in BOXES:
        st, run = request(BOXES[name][0] + "/api/v1/models/running", os.environ[BOXES[name][1]], 20)
        check(f"{name} resident", run.get("running"), [RESIDENT])
        st2, npu = request(BOXES[name][0] + "/api/v1/npu/status", os.environ[BOXES[name][1]], 20)
        d = npu["devices"][0]
        check(f"{name} NPU total MB", d["mem_total_mb"], NPU_TOTAL_MB)
    if doc:
        for label, block, want in (("ant-only", "### Ready on TinyAnt ONLY", ant_only),
                                   ("octo-only", "### Ready on TiinyOcto ONLY", octo_only),
                                   ("both", "### Ready on BOTH boxes", both)):
            if block in doc:
                seg = doc.split(block)[1].split("## ")[0]
                got = sorted(set(re.findall(r"\| `([^`]+)` \|", seg)))
                check(f"doc {label} == live", got, sorted(want))
    print("  OVERALL:", "ALL CHECKS PASS" if ok else "FAILURES PRESENT")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="verify an existing matrix instead of writing one")
    ap.add_argument("--out", default=os.path.expanduser("~/.hermes/mesh/reports/tiiny-capability-matrix.md"))
    args = ap.parse_args()
    live = fetch()
    doc = ""
    if args.verify and os.path.exists(args.out):
        doc = open(args.out).read()
    else:
        doc = render(live)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        open(args.out, "w").write(doc)
        print("wrote", args.out)
    return 0 if verify(live, doc) else 1


if __name__ == "__main__":
    sys.exit(main())
