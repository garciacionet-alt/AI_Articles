# Two-box capability difference matrix (read-only, verified 2026-11-13)

Procedure for answering "which box do I ask for this?" across the two Tiiny
appliances. Produces a per-model capability classification and a per-box
summary from **live device metadata only**.

## The two boxes

| | TinyAnt (vault) | TiinyOcto (flex) |
|---|---|---|
| IP | 198.51.100.198 | 198.51.100.192 |
| Device ID | TNYM…redacted | TNYM…redacted |
| Key env var | `TIINY_API_KEY` | `TIINY_API_KEY_2` |

Both carry the **same 93-model store** — identical model ids, and identical
`npu_usage` / `context_window` / `type` / `capabilities` / `params` for every
one of the 93. They differ **only in download state and residency**. Verified
across all 93 ids on 2026-11-13.

## The endpoints that matter

| Endpoint | Returns | Notes |
|---|---|---|
| `GET /api/v1/models/online_models` | full 93-model catalogue | **The store truth.** Carries `status`, `progress`, `npu_usage`, `context_window`, `type`, `capabilities`, `supported`, `input`, `output`, `params`, `desc`, `thinking`, `reasoning_levels` |
| `GET /api/v1/models/running` | running + pending + instances | **The residency truth.** Each running instance carries its own `npu_usage` |
| `GET /api/v1/npu/status` | one device: `model`, `mem_total_mb`, `mem_used_mb` | The **only** endpoint that gives the NPU budget |
| `GET /api/v1/sys/storage` | disk: `total_bytes`, `used_bytes`, `remaining_bytes`, per-category breakdown | The **disk** constraint — model store, agent apps, other containers. Independent of the NPU budget |
| `GET /api/v1/sys/status` -> `npus[]` | live working set | **404 as of 2026-11-23** — the firmware dropped it. Use `/api/v1/npu/status` for the budget |
| `GET /v1/models` | resident models only | Alias `default`; matches the store's `running` entries |

`/v1/models` on the box lists only **resident** models. `/api/v1/models` lists
only what is **on disk**. `/api/v1/models/online_models` lists the **whole
store**. Confusing these two is the classic misread.

### 404s to stop probing

`/api/v1/npu` (bare), `/api/v1/npu/config`, `/devices`, `/occupants`,
`/memory`, `/limit`, `/max`, `/total`, `/budget`, `/api/v1/sys/npu*`,
`/api/v1/sys/info`, `/api/v1/sys`, `/api/v1/sys/status`, `/api/v1/config`,
`/api/v1/settings`, `/api/v1/device/*`, `/api/v1/hardware` — **all 404**.
Only `/api/v1/npu/status` exists, and — for disk — `/api/v1/sys/storage`.

`/api/v1/sys/status` is the one that changed: it answered with `npus[]` on
2026-11-13 and **404s on both boxes as of 2026-11-23**. The firmware dropped
it. Probing a route you read about in an older note is how you discover that.

## The NPU budget (this took the most probing)

- `/api/v1/npu/status` -> `devices[0]`: `model: "LQ50-48GB"`,
  `mem_total_mb: 49024.0` (**48 GiB**), `mem_used_mb: 22697.0` (46.30%).
  `util_percent`, `temp_c`, `power_w` are null. `occupants` is `[]` — the
  device exposes **no per-model NPU occupancy breakdown**.
- The catalogue's `npu_usage` is a per-model integer **0-100** and is
  **percent of that 48 GiB**. Calibration: the resident model declares 47 and
  the device measures 46.30% in use; for small models the declared number
  matches the weight file's share of 48 GiB to within 1 pp
  (MOSS-Transcribe-Diarize 6 vs 5.99, Qwen3-TTS-12Hz-1.7B-Base 5 vs 4.95).
  For large models the declared number runs *above* the raw file share,
  because residency also carries runtime/KV-cache overhead the file size
  does not show. **Co-resident sets must sum to <= 100.**
- `/api/v1/sys/status` -> `npus[].memory_total_mb` was **not** the budget: it
  moved between samples on the same box (TinyAnt: 1456 / 2691 / 5974 MB) and
  never equalled 49024. Treat it as a live working-set counter. *(Observed
  2026-11-13; the route now 404s — see the 404 list above.)*
- `mem_used_mb` from `/api/v1/npu/status` was stable across 20 samples.

## The disk is the other half of the constraint

The NPU budget says how much of the *pool* a model may claim. It says nothing
about whether the weights have anywhere to live, and on these two boxes the
answer is not the one you would guess.

`GET /api/v1/sys/storage` returns the appliance's own breakdown: the total
disk, the bytes used, the bytes remaining, and the disk split into categories
— the model store, the agent apps, other containers, and the system.

Measured on 2026-11-23:

| | TinyAnt | TiinyOcto |
|---|---|---|
| total | 921 GB | 921 GB |
| used | 462 GB | 724 GB |
| **free** | **412 GB** | **151 GB** |
| model store | 405 GB | 658 GB |
| agent apps | 0 GB | 19 GB |

**The box with the most free disk is not the one with the models.** The
specialty models — image generation, 3D, music, OCR — are overwhelmingly
Octo-only, and Octo has 151 GB free against a 658 GB model store. NPU
headroom and disk are independent limits: a model can fit in the NPU budget
and still have nowhere to sit on the disk, and the placement answer has to
carry both.

The per-model disk size is an **estimate** derived from the declared NPU
share — the device publishes no per-model file size. It is close for small
models and an over-estimate for large ones, which is enough to catch "this
will not fit on the Octo" before the download starts.

## Classification: use the device's fields, in this order

1. **`type`** — the primary field. `Image-Text-to-Text`, `Text Generation`,
   `Text-to-Image`, `Image-to-Text`, `Text Embedding`, `Text Reranking`,
   `Text Classification`, `ASR`, `Text-to-Speech`, `Music Generation`,
   `Image-to-3D`, `Text-to-Video`.
2. **`supported`** — disambiguates within a `type`:
   `['Image Editing']` -> image editing; `['Prompt Enhance']` -> image prompt
   enhancer; `['Reasoning','Tool Use']` -> reasoning-capable.
3. **`capabilities`** — `ocr`/`OCR` tag on an `Image-to-Text` model means
   OCR/document, not generic vision.
4. **`input`/`output`** — modality: `Audio`->`Text` is ASR, `Score` is
   rerank/classification, `Vector` is embeddings, `3D` is 3D.
5. **`thinking` / `reasoning_levels`** — reasoning capability, independent of
   `type`.
6. **Only then, the device's own `desc` text or model id** — needed for
   exactly one distinction the device does not expose as a field: **code**.
   The device has no code flag, so a code label must come from the `desc`.

### The code-detection trap

A naive "does the desc contain 'coding'?" produces false positives. The word
appears in three different roles:

- **purpose** — "is a multimodal agentic coding model built for developers" ->
  CODE.
- **training-data footnote** — "Trained on a text-only dataset with a focus on
  STEM, coding, and general knowledge" (gpt-oss-20b/120b) -> **not** code.
- **benchmark aside** — "achieves parity with or improvement over the
  separate Qwen3-VL line on reasoning, coding, agent, and visual understanding
  tasks" (Qwen3.5-9B) -> **not** code.

Rule: a coding sentence counts only if it reads as the model's *purpose*
(`built for`, `designed for`, `targeting`, `is a ... coding model`,
`coding-specialized`) **and** is not a training-data or benchmark aside.

Models that pass: Qwen3.6-35B-A3B (+Turbo), Qwen3.8-27B, BigBang-v1-Turbo,
Ornith-1.5-35B-A3B-Turbo, Huihui-Ornith-1.5-abliterated-Turbo,
Ornith-1.0-35B, the three `Qwen3-Coder-*`.
Models that fail: gemma-4-26B-A4B-it, gpt-oss-20b/120b, GLM-4.7-Flash,
Sage-A1.5-Turbo, Qwen3.5-9B.

**Lineage case:** `trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo` never says
"coding" — its desc only says it is a variant of `Qwen3.8-27B` keeping the
same architecture. Resolve via the base model's desc and say so in the row.

## A worked answer (2026-11-13)

Ready = `downloaded` + `running`.

- **TinyAnt**: 17 downloaded + 1 running = **18 ready**.
- **TiinyOcto**: 46 downloaded + 1 running = **47 ready**.
- Ant-only: **3**. Octo-only: **32**. Both: **15**.

**TinyAnt alone**: `Qwen/Qwen3-Reranker-0.6B` (reranker),
`zai-org/GLM-4.7-Flash` (reasoning),
`huihui-ai/Huihui-Ornith-1.5-35B-A3B-abliterated-Turbo` (code+reasoning).

**TiinyOcto alone**: 3D, 2 extra ASR, 3 extra OCR, 2 TTS, 3 code specialists,
4 extra image editors, 7 extra image generators, 2 music models, the image
prompt enhancer, gpt-oss-120b, 2 extra rerankers, 2 extra vision reasoners.

**Both boxes have the identical resident set: exactly one model,
`Qwen/Qwen3.6-35B-A3B`** (npu_usage 47, 256K ctx, text+image+video in).
So the generalist never requires choosing a box; the choice only matters for
specialists, and TiinyOcto covers every category TinyAnt does.

## Driving both boxes at once

The two boxes are separate hosts with separate NPUs, so **both can be managed
concurrently** — but only over HTTP. The paths differ and the difference costs
an afternoon if it is discovered mid-sprint.

| Path | Both boxes at once? | Why |
|---|---|---|
| `POST /mesh/lifecycle` `{action, model, target}` on the mesh gateway | **yes** | one call per target, gateway key, reaches each box over its own bearer, needs no CLI session |
| `POST /api/v1/models/<id>/start\|stop` on the box, with that box's bearer | **yes** | what the lifecycle route does underneath; no session needed |
| `tiiny_ctl.py load/unload` | **no** | `device_key()` reads only `TIINY_API_KEY`, `MANAGEMENT_BASE` only `TIINY_HOST`, and both shell out to `tiiny load`, whose session is bound to one device |
| `tiiny load` by hand | **no** | signing in for the second box signs the first out |

**Driving the second box with the controller** — per-box env in that shell
only; the four state files matter, or the two controllers contend for one lock:

```bash
TIINY_HOST=http://198.51.100.192 \
TIINY_API_KEY="$TIINY_API_KEY_2" \
TIINY_LOCK_FILE=~/.hermes/tiiny-octo-lock.json \
TIINY_PLAN_FILE=~/.hermes/tiiny-octo-plan.json \
TIINY_HOLD_FILE=~/.hermes/tiiny-octo-hold \
TIINY_SNAPSHOT_FILE=~/.hermes/tiiny-octo-snapshot.json \
  python3 scripts/tiiny_ctl.py status
```

**Concurrent load, verified** — start the same model on both boxes from two
threads, then read residency back from each device:

```python
import json, threading, urllib.request
key = open(os.path.expanduser("~/.hermes/mesh/gateway_key")).read().strip()
def post(target):
    body = json.dumps({"action": "start", "model": MODEL, "target": target}).encode()
    r = urllib.request.Request("http://127.0.0.1:8767/mesh/lifecycle", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    urllib.request.urlopen(r, timeout=120)
```

Both answers are `ok` and both models land; the incumbents survive because the
requested model fit the free share. Undo with the same call and `action: stop`
— always leave the residency you found.

**The two boxes do not agree on error shape, so never judge by the response
code.** Stopping a model that was not resident returned HTTP 500
`Internal Server Error` on one box and `ok: true` with
`stop_reason: "explicit_stop"` on the other, for the same request. Read
`GET /api/v1/models/running` on the box and treat a 500 from a non-resident
stop as "nothing to stop", not a failed unload.

**Two boxes means two waves in flight, not two children per box.** Each box is
still single-stream, so a four-wave plan runs as two concurrent lanes of two
sequential waves.

## Device-side data bugs found

1. `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` carries the
   **CharacterDesignSheet** description verbatim — the catalogue's own
   copy-paste error, and it picks the wrong image model if you trust the desc.
2. `Qwen/Qwen-Image-2.1-PE-T2I` is typed `Text Generation` but is really an
   image prompt expander (`supported: ['Prompt Enhance']`).
3. Two Octo-ready models carry `need_update` with no `update_title`:
   `Qwen/Qwen-Image-2.1-PE-T2I`, `openai/Whisper-large-v3-turbo`.

## Reproducible script

`scripts/tiiny_two_box_matrix.py` (in this skill directory) runs the whole
read-only pass: fetches both catalogues, classifies every model with the
evidence recorded, writes the markdown matrix, and re-reads both devices to
verify every headline number before exiting non-zero on any mismatch.

```bash
python3 scripts/tiiny_two_box_matrix.py            # writes the matrix
python3 scripts/tiiny_two_box_matrix.py --verify   # verify an existing matrix
```

It never loads, unloads, starts, stops or downloads anything. It reads
`~/.hermes/.env` for the two key env vars by name and never prints a value.
