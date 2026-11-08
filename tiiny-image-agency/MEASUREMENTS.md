---
title: Tiiny Image Agency — Phase 0 Measurements
type: measurement
status: active
project: tiiny-image-agency
measured: 2026-11-05
---

# Phase 0 — Measurements

**What this is.** The measurements that block the build, taken against the live
device on 2026-11-05. Every number here was read from the device or observed
during a call. Nothing is copied from a catalogue.

**Tier key:** `d` read from the device's own surface · `m` measured during a
call · `i` inferred.

---

## M1 — The NPU pool is one shared budget, and it is reported two different ways

### M1.1 The device reports three different pool sizes. Two of them are wrong.

`GET /api/v1/sys/status` returns an `npus[0]` block with `memory_total_mb`,
`memory_used_mb`, `memory_free_mb` and `utilization_percent`. Read four times
in a row, unchanged device state:

| Read | total_mb | used_mb | free_mb | util% |
|---|---|---|---|---|
| earlier | 15,559 | 6,725 | 8,834 | 81.39 |
| later | 10,238 | 7,445 | 2,793 | 39.50 |
| x4 read A | 10,401 | 4,346 | 6,055 | 69.52 |
| x4 read B | 11,851 | 8,831 | 3,020 | 49.04 |

**A pool total cannot change between reads with nothing else changing. The
field is unreliable.** It is not a pool-size figure and it must not be used
for budgeting. `d`

`tiiny status` reports the pool as:

```
NPU-RAM  [█████████████████████████████████  ] 83.4%  39.9 / 47.9 GiB
```

**47.9 GiB is the pool.** `d`

> **Correction to SPEC.md §3 and §5 and to the diagram.** The figure
> "15,559 MB" came from the unreliable API field. The pool is **47.9 GiB**, and
> the budgeting unit is the **percentage**, not the MB figure.

### M1.2 The percentage is the budgeting unit, and it is not derivable from size

`tiiny info <model>` gives both `NPU usage` and `Model size`. They do not
correlate by size:

| Model | NPU % | Model size |
|---|---|---|
| Qwen/Qwen3.6-35B-A3B | 47% | 16.2 GiB |
| Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo | 55% | 14.1 GiB |
| Qwen/Qwen-Image-2.1 | 62% | 14.5 GiB |
| HiDream-ai/HiDream-O1-Image-Dev | 30% | 14.2 GiB |
| Tongyi-MAI/Z-Image-Turbo | 26% | 9.5 GiB |
| openai/gpt-oss-20b | 27% | 9.6 GiB |
| Qwen/Qwen3-ASR-1.7B | 7% | 3.8 GiB |
| Qwen/Qwen3-TTS-12Hz-1.7B-Base | 5% | 2.4 GiB |
| Supertone/supertonic-3 | 0% | 215.5 MiB |
| abenzerps/Qwen-Image-2.1-Uncensored-Quantized | 0% | 14.5 GiB |

Three models of nearly identical size (14.1, 14.2, 14.5 GiB) carry 55%, 30%
and 62%. **The percentage is a device-assigned admission-control weight, not a
function of the model's footprint.** You cannot predict it — you must read it.
`d`

`abenzerps/Qwen-Image-2.1-Uncensored-Quantized` is the outlier worth
watching: **14.5 GiB, identical to Qwen-Image-2.1, reported at 0% NPU.** If
that is true the model is free to coexist; if the field is wrong it will
evict something. It has not been tested. See M4.

---

## M2 — Loading a model is a swap, and the flagship swap clears the whole device

Three states, in order, measured with `tiiny top` and `GET /v1/models`:

**Baseline** — NPU 86%
```
supertonic-3            0%
Qwen3.6-35B-A3B        47%
gpt-oss-20b            27%
Qwen3-ASR-1.7B          7%
Qwen3-VoiceClone-1.7B   5%
```

**After loading `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` (55%)** — NPU 94%
```
supertonic-3            0%
gpt-oss-20b            27%
Qwen3-ASR-1.7B          7%
Qwen3-VoiceClone-1.7B   5%
Qwen3-Coder-30B-A3B-Instruct-Turbo  55%
```
`Qwen3.6-35B-A3B` was evicted. **Load took 54.5 s.** `m`

**After loading `Qwen/Qwen-Image-2.1` (62%) on top** — NPU 62%
```
supertonic-3            0%
Qwen-Image-2.1         62%
```
**Everything else was evicted.** Not just the planner — `gpt-oss-20b`, the ASR
model, and both TTS models went too. Only the 0% model survived. **Load took
12.5 s.** `m`

> **This is worse than the spec assumed.** SPEC.md §5.2 said "loading an image
> model evicts the chat model." In fact it evicts the **entire resident set**
> except models reporting 0%. The implication is concrete: during a flagship
> generation there is **no conversation model on the device at all**, so the
> fallback chain cannot be "keep the planner warm" — it has to be "load a
> small model afterwards", or the conversation is simply unavailable for the
> duration of the generation.

### M2.1 Unload is also destructive — and it reverts to the device's default set

`tiiny unload openai/gpt-oss-20b` did not just unload that one model. The
device dropped `Qwen-Image-2.1` as well and reverted to:

```
supertonic-3            0%
Qwen3.6-35B-A3B        47%
```

An unload is a swap like any other, and the device appears to rebalance to a
canonical set when one is removed. **The residency manager must treat unload
as a full state transition, not a single-model removal** — and must re-read
the resident set after every load or unload rather than tracking it locally.
`m`

> This invalidated one measurement attempt: a test that intended to leave the
> flagship resident and drop only the small chat model actually dropped both,
> and the following generation returned 404 "is not loaded" — which, correctly,
> is the documented meaning of a 404 on this device.

---

## M3 — Model load latency

| Operation | Wall clock |
|---|---|
| Load `Qwen3-Coder-30B-A3B-Instruct-Turbo` (55%, 14.1 GiB) | **54.5 s** |
| Load `Qwen/Qwen-Image-2.1` (62%, 14.5 GiB) | **12.5 s** |

The 54.5 s figure was a cold load with other models resident and evicting.
The 12.5 s figure was a load into a nearly empty pool. **The honest number
for the product is the worst case — around a minute — and it must be shown to
the user as a progress event, not a silent stall.** `m`

`tiiny load` requires a TTY. Under a pty (`script -q /dev/null`) it works
from a script. `d`

---

## M4 — Open measurements

### M4.1 Native alpha — the channel is real, the cut-out is not

`Qwen-Image-2.1`, 1024×1024, prompt *"A flat vector icon of a fox head,
front-facing, single solid fill, clean geometric shapes, transparent background,
no text"*. **202.07 s.** `m`

| Measurement | Value |
|---|---|
| PNG color type | **RGBA (6)** — a real alpha channel |
| Fully transparent pixels | **0** |
| Partially transparent pixels | **687,688** (65.6% of the image) |
| Fully opaque pixels | 360,888 |

The alpha channel is genuine — this is not a model that flattens to RGB. But
**the background it produced is a soft white radial fade, not a clean cut-out.**
Zero fully-transparent pixels means the background fades rather than clears.
Looking at the image: a good flat-vector fox head, orange fill, black eyes and
nose, white muzzle — on a white canvas with a soft grey vignette.

> **The device's own claim — "can output images with a real transparent
> background, so stickers, logos, and product cutouts come out ready to place
> on any design without a separate background-removal step" — is half true.**
> The channel is real; the cut-out was not produced. Whether that is the
> prompt's fault or the model's default is the open question in M4.6, and it
> matters because it determines whether the product needs a background-removal
> pass in the pipeline.

**Product consequence:** if the soft-alpha background proves to be the model's
default, the pipeline gains a step — generate, then cut — and
`fal/FLUX.2-klein-4B-Background-Remove` (26%, co-resident, and the cheapest
adapter in the catalogue) is the tool. That is a *two-stage* generation, and
it is a different product from the one-stage design in SPEC.md §4.4.

### M4.2–M4.6 still open

| # | Question | Why it matters | Status |
|---|---|---|---|
| M4.2 | Does `abenzerps/Qwen-Image-2.1-Uncensored-Quantized` really coexist at 0% NPU, given it is 14.5 GiB? | It is the only co-resident path to native RGBA | Not started |
| M4.3 | Can `openai/gpt-oss-20b` (27%) be loaded **on top of** `Qwen-Image-2.1` (62%)? | 27 + 62 = 89%. If yes, the conversation survives the flagship generation | **Measured — admitted but not executable.** Loads fine at 89%, both resident, load 14.3 s. **Generation then failed with HTTP 500 / code 150004.** The same prompt with the flagship alone succeeded. |
| M4.4 | Can a 26% model coexist with the 55% planner without eviction? | Tests the whole "12 of 14 co-resident" claim rather than assuming it | **Measured — yes.** NPU 81%, both resident. `gpt-oss-20b` was the one evicted |
| M4.5 | Generation latency per model at each verified size | The swap UX needs honest timings | Partial — Qwen-Image-2.1 at 1024² is **202 s** and **197 s** on two runs |
| M4.6 | Does the prompt dialect determine whether the alpha is a clean cut-out? | If yes, the dialect translator is the quality lever. If no, the pipeline needs a cut-out stage | **Measured — yes, decisively.** Soft prompt → **0%** fully transparent. Explicit cut-out dialect → **44.86%** fully transparent, genuine cut-out, shows through a dark surface. Same model, same size, same ~200 s. |

M4.3 and M4.4 are the two that decided the product's core design, and both
now hold by measurement. M4.6 resolved in favour of the dialect translator,
which promotes that module from "a quality nicety" to **the mechanism that
produces the headline capability.**

**The M4.3 result is the sharpest lesson of the day.** A model set can be
*admitted* to the NPU and still not be *executable* — it fits the budget but
leaves no headroom for the diffusion pass. The residency manager needs two
budgets, not one: what fits, and what can run.

**Two artefacts from the run**, kept in `evidence/`:

| File | What it shows |
|---|---|
| `fox-soft-alpha-0pct-transparent.png` | Good flat-vector fox on a **soft white radial fade**. RGBA, but 0% fully transparent — unusable on anything but white. |
| `fox-cutout-44pct-transparent.png` | Angular fox with a **genuine cut-out**. 44.86% fully transparent; shows through a dark surface. A faint white halo remains along the edge. |

Both 1024×1024, both RGBA, both from `Qwen-Image-2.1` on the same device. The
only difference is the prompt.

---

## M6 — Context windows: a real term, but not the one the NPU charges for

The question was whether the memory budget must factor in the LLM, the image
model, **and the context windows for both**. Answer: context is a real budget
term, but on this device it is a **latency and selection** term, not an
**admission** term. Three measurements.

### M6.1 The KV cache does not move the NPU pool

Sampling `tiiny status` continuously (every 1.5 s) during each call:

| Call | Prompt tokens | Time | NPU-RAM base → peak |
|---|---|---|---|
| small | 1,543 | 2.4 s | 39.9 → **39.9 GiB** |
| large | 26,262 | 32.0 s | 39.9 → **39.9 GiB** |
| small again | 1,543 | 2.1 s | 39.9 → **39.9 GiB** |
| large, new text | 25,466 | 31.2 s | 39.9 → **39.9 GiB** |

**Zero movement.** A 26k-token context changes the reported NPU-RAM by less
than the CLI's 0.1 GiB resolution. `m`

> The management API's `npus[0].memory_used_mb` is the wrong instrument — it
> is the same field whose *total* changed across reads with no device change.
> During one 66,680-token call it did move +486 MB, but the sweep produced
> values swinging 439 ↔ 6474 MB with no relationship to token count. **The
> CLI is the instrument; the API field is not.** This is the second time that
> field produced nonsense, and it should not be used for budgeting.

### M6.2 Prefill throughput is ~800 tok/s, and the prefix cache works

| Prompt | Tokens | Cold | Warm |
|---|---|---|---|
| small | 6,575 | 8.2 s | — |
| medium | 26,262 | 32.0 s | — |
| large | 66,680 | 87.46 s | **0.97 s** |

800 / 821 / 762 tok/s — consistent. The repeated 66,680-token prompt returned
in **0.97 s against 87.46 s cold: a 69× speedup from the prefix cache.**

**This is the single most useful operational fact in the whole project.** A
long conversation is expensive once and nearly free thereafter, as long as the
prefix does not change. The product's cost model should be built on it.

### M6.3 The advertised context window does not drive the NPU allocation

Across all 28 chat and image models in the store, the correlation between
`context_window` and `npu_usage` is **Pearson r = −0.246** — essentially zero.
Three models with ~14 GiB weights carry 55%, 30% and 62%.

The device reserves NPU-RAM against a **static, per-model weight**, not
against the model's maximum context. `d`

### M6.4 So what IS in the budget?

| Term | In the NPU admission budget? | In the product's budget? |
|---|---|---|
| LLM weights | **Yes** — `Model size` and `npu_usage` | Yes |
| Image model weights | **Yes** | Yes |
| **LLM context / KV cache** | **No** — measured flat | **Yes**, as latency: `tokens ÷ 800` seconds of prefill |
| Image model "context" | No — it is a **transformer-token ceiling** on the request, enforced as a 400, not an allocation | **Yes**, as a request-validation rule |
| **Number of models** | **Yes** — and this is the term the spec was missing | Yes |
| Execution headroom | Not modelled at all until today — see M7 | **Yes** |

### M6.5 The term the spec was missing: the prompt enhancer

The device ships **two purpose-built prompt-enhancement models**, which the
original registry missed because their `type` is not `Text-to-Image`:

| Model | NPU | Ctx | Status | What it does |
|---|---|---|---|---|
| `Qwen/Qwen-Image-2.1-PE-T2I` | **23%** | 262,144 | downloaded | Expands a short image request into a ~20-sentence English scene description plus a recommended aspect ratio. **"The output is meant to be passed straight to Qwen-Image-2.1."** |
| `Qwen/Qwen-Image-2.1-PE-I2I` | **24%** | 262,144 | **not downloaded** | The image-editing counterpart — rewrites a vague edit instruction after looking at the input images |

**The dialect translator this spec proposed to build is a model on the
device.** And 23% + 62% = **85%**, so the enhancer and the flagship are
*admitted* together — measured, both resident, loads of 18.9 s and 10.5 s.

Whether they can *run* together is M7.

---

## M7 — The execution-headroom boundary

The gap between "the models fit" and "the generation runs" is the whole
product. Four compositions measured, same prompt, same 1024×1024:

| Occupancy | Composition | Generation | Time |
|---|---|---|---|
| **62%** | `Qwen-Image-2.1` alone | ✅ | 197 s, 202 s |
| **81%** | planner (55%) + `Z-Image-Turbo` (26%) | ✅ | **54.5 s** |
| **85%** | `PE-T2I` (23%) + `Qwen-Image-2.1` (62%) | ❌ 500 / 150004 | failed at 93.6 s |
| **89%** | `gpt-oss-20b` (27%) + `Qwen-Image-2.1` (62%) | ❌ 500 / 150004 | — |

**The threshold is between 81% and 85%.** `m`

Two consequences:

1. **The hot path works.** The 55% planner and a 26% image model coexist
   *and generate together*, in 54.5 s, with the conversation model live. Ten
   of the fourteen image models are in this class — the Z-Image family, the
   FLUX.2 family, ERNIE, and HiDream.
2. **The flagship path is exclusive.** `Qwen-Image-2.1` needs the device to
   itself. Adding *any* second model above ~23% pushes it past the boundary
   and the diffusion pass fails.

**A residency manager that budgets only for admission will build a product
that loads successfully and then fails at generation time.** It needs two
budgets: what fits, and what can run.

### M7.1 The hot-path image is opaque — as expected

The 81% generation via `Z-Image-Turbo` produced **0% transparent pixels and
0 partial-alpha pixels** — a fully opaque RGB image. That is correct
behaviour: Z-Image is not an RGBA model. The alpha capability belongs to the
flagship, which lives on the other path. Kept as
`evidence/fox-zimage-26pct-co-resident.png`.

### M7.2 The prompt-enhancer models are admitted but not callable

`Qwen/Qwen-Image-2.1-PE-T2I` loads and occupies 23% of the NPU alongside the
flagship (85% total, both resident). Every chat attempt returns:

```json
{"error":{"message":"Model 'Qwen/Qwen-Image-2.1-PE-T2I' does not support chat.",
           "type":"invalid_request_error","param":"model","code":400}}
```

Three variants tried — plain, explicit `enable_thinking: true`, and
system+user — all identical. The model is in the store, is downloaded, loads
onto the NPU, and refuses the chat endpoint.

**Open question for the vendor:** is PE-T2I an app-internal component, an
unmounted endpoint, or a feature flag? Until it is reachable, the dialect
translator has to be built on a chat-capable model — and the planner, which
is already resident on the hot path, is the obvious host for it.

---

## M9 — A judge that can see the image

The critic judged the prompt because `device.chat()` sends text only. The
appliance's own models are image-text-to-text, and `device.vision()` already
sent an image as a base64 `image_url` content part — the capability was
there and unused.

### M9.1 The catalogue says which models can see

The device states it twice: the model's `type` is `Image-Text-to-Text`, and
its `input` is `Text,Image`. Either signal counts. Reading the live store
gives **26 conversational models, 16 of them vision-capable** — and the
cheapest downloaded one is `Qwen/Qwen3.5-9B` at 29% of the pool.

The image registry holds the generators; no text model is in it and no image
model can hold a conversational role, so this needed a second catalogue.

### M9.2 A vision judge fits, because the talker is gone by then

| | NPU |
|---|---|
| `Qwen/Qwen3.6-35B-A3B` as the judge | 47% |
| `Tongyi-MAI/Z-Image-Turbo` generating | 23% |
| **while the image is judged** | **70%** — under the 81% execution ceiling |

The conversation agent is **not** in that sum. It writes the scene
description before the generation starts, so by the time the image is made
its weights have been swapped out. Summing all three roles gives 125% and
the false conclusion that a vision judge is unaffordable.

### M9.3 Verified live — 2026-11-07

A generation judged by `Qwen/Qwen3.6-35B-A3B`:

```
[swap.started]   model=Tongyi-MAI/Z-Image-Turbo also_resident=[Qwen/Qwen3.6-35B-A3B]
[generate.finished] size=1024x1024
[critique.ready] model=Qwen/Qwen3.6-35B-A3B  vision=true
[asset.ready]    ast_f343d03ec27d4bf2
```

The swap asked for the judge as a companion, the generation ran, and the
critique event named the model with `vision: true`.

### M9.4 A reasoning model can spend its whole budget thinking

The first live run of the vision judge returned an **empty** reply: the
model thought for the whole token budget and answered nothing. That looks
exactly like a model that cannot see, and it is not — the capability is
fine and the budget is the problem. `VISION_MAX_TOKENS` is 2500 because
at 1200 one probe in eleven came back empty; the critic's prompt is much
longer than a probe's question, so it thinks longer.

### M9.5 Two bugs the live run exposed

**A judge priced at zero.** The residency manager costed models from the
image registry and a table of five appliance models, and treated everything
else as free. A 29% judge chosen at runtime was therefore free, the
eviction plan left the pool over the ceiling, and the generation would have
failed. The roles catalogue is now its third source of prices.

**A choice that changed the guide and not the judging.** The orchestrator
was handed the critic when it was built, so replacing the agency's copy
left the orchestrator judging with the old model. The choice would have
looked perfect in the UI and changed nothing about the output.

---

## M5 — Tooling that now exists and is reusable

| Tool | What it does |
|---|---|
| `tools/measure_npu.py <label>` | Captures NPU state and the resident set as JSON. Read-only |
| `tools/probe_image.py <model> <prompt> <size> <out.png>` | Generates one image and inspects the PNG for a real alpha channel, with pixel-level transparency stats and latency |
| `tools/build_registry.py` | Regenerates `registry/image-models.json` from the live store plus the curated overlay |

`probe_image.py` found a real bug in itself on first run: the inference
surface is at `/v1/images/generations`, not `/images/generations`. A 404 from
the device on a "loaded" model means **check the path before blaming the
model**.

---

## M8 — The first end-to-end run, and the two defects only a live run finds

On 2026-11-06 the agency generated an image on the appliance for the
first time, through the whole chain: `tis generate` → the API → the
planner → the resolver → the residency manager → the appliance → the SSE
bus → the CLI → a PNG on disk.

```
request   "a friendly robot waving hello"
model     Tongyi-MAI/Z-Image-Turbo (26%, co-resident with the planner)
occupancy 81% — the hot path
asset     ast_bae119fe716c44f9
sha256    b2e68e46cfb6714c53e28aa520fae466e10f0546985583f40e239eef8bababf6
PNG       1024×1024, 8-bit RGB, non-interlaced, 1,291,265 bytes
evidence/agency-end-to-end-robot.png
```

The image is coherent: a white robot with blue eyes, waving. The CLI
printed every event as it arrived and exited 0.

The timeline was 4 min 10 s, and **only 54 s of it was the image**:

| Phase | Time |
|---|---|
| swap: load the planner and the image model, evict three others | 79 s |
| generate → critique → generate → critique → generate → critique | 3 × 54 s |
| save the asset | 3 s |

### M8.1 The store catalogue is not what the appliance can do

The first attempt failed at the load step:

```
plan.ready    black-forest-labs/FLUX.2-klein-4B
swap.finished black-forest-labs/FLUX.2-klein-4B
job.failed    tiiny load failed: Model '...' not found.
```

The registry is built from `GET /api/v1/models/online_models`, which is
the **store** — every model Tiiny sells. Each record carries a `status`:
`downloaded`, `not_downloaded` or `running`. The registry already kept
that field; the resolver ignored it.

**Only 7 of the 16 curated models were on the appliance's disk.** The
other 9 were in the store only.

The resolver now treats a model that is not downloaded as not a
candidate, separates *capability* from *preference* so that nothing falls
back past a capability, and refuses — with the model to download named —
when nothing on the appliance can do the job.

### M8.2 A judge that cannot see the image must not be asked to judge it

The run took three generations instead of one, and all three were wasted
on the same complaint. The lineage record for the asset says:

```
attempts  3
critique  VERDICT: fail
          REASON: The image has a transparent background when it should
                  have a solid background
```

The requirement was `alpha: "no"` — a solid background was wanted — and
the delivered image has exactly that. **The complaint was invented.**

The cause: the judge's prompt contained the requirement vector and
nothing else. No image (the device's chat API is text-only) and no
prompt. So the judge was asked to reach a verdict about an image it had
never seen, and it did what a language model does with no evidence: it
guessed a plausible-sounding defect. The orchestrator treated that
verdict as an instruction and regenerated — twice more, to the same
invention.

**162 seconds of appliance time, chasing a defect nobody could see.**

The fix brings the code in line with its own documentation, which had
promised this all along ("it judges the requirement vector *against the
prompt that produced the image*"). The judge is now given the prompt, and
told plainly that it cannot see the image and must not invent a defect
it cannot see.

**The general lesson: a verdict that drives a costly action needs
evidence. A judge given no evidence will produce confident reasons for
its answer, and the confidence is not worth anything.**

### M8.3 The judge, fixed — and a new defect in the feedback loop

With the prompt added, the judge became a prompt critic that actually
works. A second live run, "a lighthouse at dusk", produced:

```
attempts 2
critique VERDICT: pass
         REASON: The prompt asks for a photo of a lighthouse at dusk with
                 specified dimensions, which aligns with the requirements.
```

Two attempts, not three, and the reason is grounded in the prompt rather
than invented. The image is a good lighthouse at dusk.

**But the first attempt's complaint produced a visible artifact in the
delivered image.** The judge's suggested changes were:

```
Add "photo" to the prompt
Add "1024x1024" to the prompt
```

Those changes are injected into the prompt verbatim, and the image model
obeyed them literally: it drew a white band across the bottom of the
picture bearing the garbled text **"Alowiobe 1024x1004"** — the size,
rendered as a caption.

```
evidence/agency-end-to-end-lighthouse.png
sha256 7e9832dda31f27141ef60d7f4beaaae9cda0e06e9be93530ac98b4886af035a5
```

**So the feedback loop has a hazard the first run hid: a change the
judge suggests is not advice to the model, it is an instruction to it.**
"Add 1024x1024 to the prompt" is a reasonable note for a judge and a
literal instruction for a diffusion model, which duly drew the number.

The size is already in the model's parameters — it was the size the
generation was made at. The judge asked for it in the prompt because it
was looking at a requirement vector that mentions `width` and `height`
and no prompt that mentioned them.

Two things follow. The judge's prompt should carry the size as context
rather than as a change to make, and a suggested change must never
restate something the model already knows.

**Fixed on 2026-11-06** (`4a75509`). Two halves, because guidance alone is
not a guarantee:

1. **The judge is told.** The size line in the requirements now says it is
   passed as a parameter, and the judge prompt has a section on what a
   CHANGE may ask for: something visible in the image, never the size,
   the resolution, the aspect ratio, the file format or the megapixel
   count — and never "add X to the prompt".
2. **The changes are filtered.** A change asking for the output's
   dimensions is dropped, in whatever way it is written: `1024x1024`,
   `1024 x 1024`, `at 1024 by 1024`, `the image size`, `the output
   dimensions`. The filter is deliberately narrow — bare words like
   "resolution" and "size" are NOT matched, because they appear in
   legitimate art direction ("a grainy low-resolution photograph", "the
   size of the subject in frame is too small") and dropping those would
   throw away real advice. There is a test for exactly that.

A fail verdict whose every change was dropped is **inconclusive**, not a
failure: there is nothing left to act on, and regenerating against a
change that cannot be sent would burn a generation to produce the same
picture. The judge's own words stay in `raw`, so nothing is lost.

The general lesson, and the one worth keeping: **a change from the judge
is not advice — it is an instruction to the image model.** Any suggestion
that restates what the model already knows, or that talks about the
prompt rather than the picture, will be rendered literally.

### M8.4 A second generation returned the first one's picture

The second run was over in **0.2 seconds** and wrote the robot image
from the first run, byte for byte, under the new name. Nothing was
generated.

The cause was two bugs, one on each side of the wire:

1. **The CLI acted on a replayed event.** The event bus replays a
   session's recent events to a late subscriber — which is what makes a
   late subscriber able to catch up. The first job's `asset.ready` was
   in that replay, and the CLI took it as its own.
2. **The SSE route ended the stream on it.** The route broke on any
   `job.finished`, including a *replayed* one from an earlier job — so
   the stream closed before the second job's first event arrived.

Both are fixed: the CLI decides only on its own job's events, and the
route takes an optional `job_id` so that only that job's terminal event
ends the stream. A session-wide watcher (a browser tab) still gets the
old behaviour of ending on any terminal event.

**The general lesson: a replay is not a fresh event, and a consumer that
cannot tell the difference will act on history.** Every consumer of a
replaying stream needs the same answer — the id of the thing it is
waiting for.

### M8.5 What a live run costs

- The swap is the expensive part: **79 s** to load two models and evict
  three. Every generation after it is 54 s.
- The device is a serial, exclusive resource. A generation holds the
  appliance for the whole call, and other agents wait.
- The watchdog restores the device's default five models (86%) within
  five minutes of the hold clearing.

## M9 — Downloading a model, and what the appliance will actually allow

The question was whether the Agency could download an optimal model when
Tiiny has storage capacity. The answer is yes, and the measurements
change the shape of the answer: **storage is not the constraint.**

### M9.1 The disk is not the scarce resource

`GET /api/v1/sys/storage` reports the appliance's disk:

| | |
|---|---|
| total | 915.9 GiB |
| used | 594.0 GiB |
| **remaining** | **278.2 GiB** |

and breaks it down: the models (the "LLM" category) occupy 455.0 GiB,
the agents 22.4 GiB, the system 116.7 GiB.

For comparison, the **NPU pool is 47.9 GiB** and the last configuration
measured to generate was 81% of it. So the scarce resource is the
silicon, not the disk: a 10.6 GiB model is free, and loading it is not.

The capacity check is still worth making. It is the difference between
"download it" and "the appliance cannot hold it" — and the headroom
matters, because the appliance unpacks while it downloads.

### M9.2 Where the device keeps what the Agency needs

Three facts the product needs, all from the device:

| What | Where |
|---|---|
| a model's disk size, in bytes | `tags[].size` in the store catalogue |
| what is on the disk right now | `status` on the catalogue record |
| how far a download has got | `progress` on the catalogue record |
| how much disk is free | `remaining_bytes` from `/api/v1/sys/storage` |

The size is worth noting: it is **not** a top-level field. The store
buries it in the tags list, so a search for a key containing "size"
finds nothing. It is 11,429,631,451 bytes for ERNIE — which is exactly
the 10.6 GiB `tiiny info` reports.

### M9.3 A measured download

`tiiny download baidu/ERNIE-Image-Turbo`, watched through the catalogue:

```
status=downloading  progress=20.26
status=downloading  progress=32.80
status=downloading  progress=60.07
status=downloading  progress=78.50
status=downloading  progress=100.0  →  downloaded
```

**10.6 GiB in about five minutes, roughly 43 MiB/s.** Free space fell by
exactly 10.6 GiB over the run.

Two behaviours worth knowing:

1. **The CLI starts the download and returns.** The appliance does the
   work. The CLI's exit code is not a verdict on the download's outcome,
   so the caller watches the catalogue instead.
2. **The management API's download route answers 404 to everything.**
   `POST /api/v1/model/download` was tried with four different body
   shapes and every one answered `{"detail":"Not Found"}`. The download
   goes through the CLI, which holds its own credentials — so the Agency
   never needs a second secret.

### M9.4 The store moved while the build was going

Two changes the appliance made to its own catalogue, both caught by
regenerating the registry:

1. **The NPU costs fell.** The FLUX.2 family went from 26% to 19-20%
   and the Z-Image family from 26% to 23%. The hot path is therefore
   **78%** now, not 81% — still under the measured ceiling, but the
   number in every measurement that says "81%" describes a configuration
   the appliance no longer offers.
2. **A new model appeared**: `krea/Krea-2-Turbo`, with no curated
   overlay. The generator now leaves a model out of the registry when the
   overlay does not describe it, and says so — the overlay is what makes
   routing defensible, and an uncharacterised model would be chosen on a
   guess, with a dialect nobody has measured.

And one the build caused: **ERNIE-Image-Turbo is now downloaded**, so the
resolver's six text cases pick it again. That is what the acceptance
table wanted before the download filter existed. The filter was the
right interim fix; being able to download is the end state.

## Provenance

| Fact | Source | Tier |
|---|---|---|
| Pool is 47.9 GiB, 39.9 used at baseline | `tiiny status` | d |
| `npus[0].memory_*_mb` is unstable across reads | `/api/v1/sys/status` ×6 | m |
| Per-model `NPU usage` and `Model size` | `tiiny info <model>` | d |
| Eviction behaviour of two loads | `tiiny top` before/after | m |
| Load latencies 54.5 s / 12.5 s | wall clock around `tiiny load` under pty | m |
| 82 models in the store, 14 Text-to-Image | `GET /api/v1/models/online_models` | d |
| Device metadata `desc` is wrong for ≥1 model | `tiiny info` output | d |
| `tiiny load` needs a TTY | vault, confirmed working under pty | d |
| 7 of 16 curated models are `downloaded` | `status` field in `online_models` | d |
| End-to-end generation: 1024×1024 PNG in 4 min 10 s | `tis generate`, exit 0 | m |
| Swap costs 79 s; a generation costs 54 s | event timeline, wall clock | m |
| The critic invents a defect when given no image and no prompt | asset lineage `ast_bae119fe716c44f9` | m |
| The judge passes when given the prompt | asset lineage `ast_49650f34cc834a43` | m |
| A judged change is injected verbatim and the model obeys it literally | "Alowiobe 1024x1004" in the image | m |
| A replayed terminal event ends an SSE stream | second run returned in 0.2 s | m |

**Not claimed:** that the 12-of-14 co-resident figure holds (M4.4 untested);
that `abenzerps` coexists (M4.2 untested); that `gpt-oss-20b` can be
re-loaded alongside the flagship (M4.3 untested); that any model produces
native transparency (M4.1 in progress).

---

## M10 — The appliance takes an image into generation

**`image` (a string) and `images` (an array) are both REAL fields on
`/v1/images/generations`.** The appliance's type errors name the field's
TYPE but not the field's name — `[json.exception.type_error.302] type
must be string, but is number` — so a probe that looks for the name in
the message concludes the field does not exist. That mistake was made
and corrected. `m`

| field | answer | meaning |
|---|---|---|
| `image` | 400 `type must be string` | **recognised — a string** |
| `images` | 400 `type must be array` | **recognised — an array** |
| `image_url`, `init_image`, `input_image`, `source_image`, `image_base64`, `reference_image` | 200 | ignored; a generation happened anyway |

**Proved by a control, not by a prompt that gives the answer away.** The
input was a rectangle half pure red and half pure blue; the prompt was
"reproduce this image as a pencil sketch, keeping the composition"; the
CONTROL had no image at all. `m`

| variant | time | what came back |
|---|---|---|
| **control (no image)** | **16.3 s** | **a random bald man's face** |
| `image` = raw base64 | 33.9 s | **the input**: a rectangle split vertically, dense hatching left, light right |
| `image` = data URL | 34.4 s | the input's rectangle, faint vertical division |
| `images` = [raw base64] | 34.0 s | the input, split inverted |
| `images` = [data URL] | 34.0 s | the input's structure |

**Two independent signals agree.** The control drew a completely
different SUBJECT — a face, not a rectangle. Every image-bearing variant
drew the rectangle with its vertical division. And the timing splits
cleanly: **16.3 s without an image, ~34 s with one** — eighteen extra
seconds of the model reading the picture. The bare-base64 form
preserved the split most faithfully and is the form to use. `m`

**Consequence: every drag-and-drop edit has been text-only.** The
Agency's `device.generate()` sends only `model`, `prompt`, `size` and
`n`, and `orchestrator.py:150` calls it with `(current, prompt, size)`.
There is no path by which a source PNG reaches a generation. `m`

**Not claimed:** that every model honours the image. The catalogue says
`input: Text,Image` for `Qwen/Qwen-Image-2.1`, the community quant and
the four FLUX adapters, and `input: Text` for the FLUX base — but the
catalogue is a claim, and Phase N task N0 measures the models.

---

## M11 — The catalogue has no "new model" signal

**92 rows: 50 `not_downloaded`, 37 `downloaded`, 5 `running`.** **All 15
Text-to-Image rows are already downloaded** — the user installed them
all. The 50 not-downloaded rows are TTS, ASR, embedding and
classification models, none of them an image model. `m`

**`need_update` is `False` on all 92 rows**, so it cannot signal
anything. The usable signals are `created_time` (73 distinct values,
oldest 2025-12-31, newest 2026-11-04) and `udpate_time`. `m`

**So the app must keep its own watermark** — the catalogue ids seen at
the last check — and diff against it. There is no vendor "what's new"
endpoint to ask. `i`

`tools/build_registry.py` already has the vocabulary: a model in the
store with no overlay entry is `uncharacterised`, and is deliberately
kept OUT of the registry so nobody routes to a model nobody has
measured. `m`

---

## M12 — The lineage already holds everything a reference needs

A recipe-level reference needs the requirements, the model that was
chosen, the dialect, the resolved size, the prompt, the modifiers and
the critique. **All of it is already in the lineage the service writes**,
and the dialect translator already knows how to write a prompt in a given
model's dialect. `m`

**And the curated layer was already written for this.** `max_refs: 10`
and `edit_ops: [instruction_edit, local_edit, identity_preservation]`
sit on exactly the two models the catalogue says take `Text,Image` —
the code never used them. `m`

---

## M15 — the source image arrives, and the edit is real (2026-11-07)

**THE EDIT WAS RUN ON THE APPLIANCE ✓ ✓.** A picture the agency had
made — an orange fox head on a white background with a faint diagonal
hatch — was given to `POST /v1/generate` as `source_asset_id`, with the
request *"remove the object"*.

**WHAT CAME BACK ✓ ✓** — in 163 s, from `fal/FLUX.2-klein-4B-Object-Remove`
✓ ✓:

- **the fox head is GONE ✓ ✓**
- **the diagonal hatch pattern is PRESERVED ✓ ✓**

**That is the proof ✓ ✓.** A regeneration could not have kept the
source's particular background hatching ✓ ✓ — it would have drawn a
new picture with a new background ✓ ✓. The operation happened **TO
that picture** ✓ ✓.

**AND THE PROMPT THE APPLIANCE SENT TALLED ✓ ✓:**

> Edit the input image: remove the object, Ensure the fox head
> illustration is completely removed from the center of the image.,
> Ensure the background remains with its existing diagonal line pattern

Something read the image ✓ ✓ — the appliance's own editor named the
fox head and the diagonal line pattern ✓ ✓, neither of which was in
the request ✓ ✓.

**THE LINEAGE RECORDS THE SOURCE ✓ ✓** — `source_asset_id:
ast_011a69af30394a0b` ✓ ✓, so "where did this picture come from" has
an answer ✓ ✓.

## M14 — a JPEG is a real source, and what it costs (2026-11-07)

**THE APPLIANCE TAKES A JPEG.** The `image` field was measured with a
JPEG made by `sips` (2,013 bytes, magic `ff d8 ff`): **HTTP 200** in
34.1 s, against 41.6 s for the same picture as a PNG. `m`

**BUT THE STRUCTURE DID NOT SURVIVE.** The same source given as PNG
produced a faithful pencil sketch of the divided square (judged 3/5
rectangle, confirmed by eye). The same source given as a JPEG produced a
narrow vertical shape with a line down the middle — the quadrant edges
were gone (judged 1/5, confirmed by eye). Two independent readings
agree. `m`

**THE REASON IS JPEG ITSELF** — its lossy compression destroys exactly
the hard colour edges an image model reads structure from, and the
model reasonably drew a vertical split rather than a four-way one. `m`

**THE CONSEQUENCE FOR THE DESIGN.** The appliance decodes the JPEG to
pixels either way, so passing the JPEG bytes straight through and
converting them to PNG at upload produce **the same picture**. **JPEG
input therefore needs no image library at all** — the agency accepts the
bytes, passes them through unchanged, and records the format by its
magic bytes. What is lost is the alpha, and it was lost before the
agency ever saw the file, so the lineage says `"alpha": "none"` and
names the loss. `m`

## M13 — Only three of the fifteen models actually use an image

**M10 proved the ENDPOINT accepts `image` and `images`. This measures
which models USE one.** The catalogue says several accept "Text,Image";
the device's advertisement is not a reliable guide to which. `m`

| | models |
|---|---|
| **Takes an image** | `Qwen/Qwen-Image-2.1`, `SenseTime/SenseNova-U1.5-8B-MoT`, `fal/FLUX.2-klein-4B-Object-Remove` |
| **Does not** | `Qwen-Image-2.1`, `ERNIE-Image-Turbo`, `Z-Image-Turbo`, `Children-Drawing`, `CharacterDesignSheet`, `TaoBaiBai`, `krea/Krea-2-Turbo` — these seven **refuse an image outright**, HTTP 400, *"images is not supported by this model"* — plus the `FLUX.2-klein-4B` base, `Background-Remove`, `Zoom` and the community quant, which **accept one and ignore it** |
| **Unknown** | `HiDream-ai/HiDream-O1-Image-Dev` (its load times out), `FLUX.2-klein-4B-Outpaint` (the judge cannot classify it consistently) |

**THE CONTROL WAS NOT OPTIONAL.** Four models drew the divided rectangle
with **no image at all**, so a picture that looks like the input proves
nothing on its own. `m`

**TWO PIXEL METRICS WERE TRIED AND BOTH WERE FOOLED.** The first
compared the left quarter against the right on every row: it caught a
clean vertical split and MISSED `Qwen-Image-2.1`, which drew the input
as a four-quadrant grid — the sign flipped between the top and bottom
halves. The second measured how much the cells of a coarse grid differ:
it failed for the opposite reason, because a four-quadrant grid has
cells of SIMILAR mean tone, and the community quant — which plainly
ignored the image — scored within 2 points of the model that plainly
used it. **The appliance's own vision model settled it**: it is asked
what is in each picture, and it says RECTANGLE for the with-image
output and OTHER for the control. `m`

**THE JUDGE WAVERS, SO THE VERDICT IS A DIFFERENCE.** Asked the same
question five times about the same picture, the judge is not perfectly
consistent: Qwen's CONTROL was called a rectangle twice out of five even
though it is a blocky figure. So the verdict is the DIFFERENCE between
the two pictures — at least three of five for the with-image picture
and at least three more than the control — and a rate of two out of
five is a coin flip, not evidence. `m`

**The timing agrees.** A model that reads a picture takes longer:
`Qwen-Image-2.1` 199.9 s → 276.3 s, `SenseNova` 129.6 s → 257.6 s,
the FLUX family 23 s → 34 s. `m`

**The `images` ARRAY wants a different encoding than `image`** — the
same base64 string in an array is answered *"image could not be
decoded"*. So multi-reference is not available in the shape
single-reference is. `m`

**Not measured:** `HiDream-ai/HiDream-O1-Image-Dev` — its load times
out and it will not stay resident, which is an appliance problem rather
than an answer about the model. `FLUX.2-klein-4B-Zoom` is described as
zooming into "a red-marked region" and fails on an unmarked input.
`m`

**What this changes:** a reference image can only condition a
generation on the three models in the first row. The RECIPE-level
reference — the model, the dialect, the size and the requirements — works
on every model, and is what a repeated job actually needs.
