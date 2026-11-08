---
title: Tiiny Image Agency — Technical Specification
type: design
status: draft
project: tiiny-image-agency
updated: 2026-11-05
---

# Tiiny Image Agency — Technical Specification

**One line.** A local image-generation work surface where a conversational model
plans what you want, a resolver picks the right Tiiny image model, and a
residency manager loads it — without the user ever learning a model name.

**Who reads this.** Whoever builds it. It is written against facts measured on
the device on 2026-11-05, not against a wish list.

---

## 1. The problem, stated precisely

A developer with a Tiiny appliance and 14 image models has three problems, and
only the first is obvious.

1. **Selection.** Fourteen models, each good at something different. Only one
   emits native transparency. The knowledge of which to use lives in a
   catalogue document, not in anyone's head.
2. **Residency.** The NPU is one shared pool of 15,559 MB. Loading an image
   model evicts the chat model. The user wants to *talk about* an image and
   *have* an image at the same time; the device can rarely do both.
3. **Dialect.** Image models respond differently to prompt phrasing. The user's
   words are not the model's words. Somebody has to translate.

Problem 2 is the one that makes this a real product. A model picker is a lookup
table. An NPU-budget-aware model picker is architecture.

## 2. The insight the product is built on

**The capability the user cares most about is the one model that cannot coexist
with the conversation model.**

`Qwen/Qwen-Image-2.1` is the only model that outputs native RGBA — the reason
the user can cut an icon instead of running a separate background-removal pass.
It costs 62% of the NPU. The planner model costs 55%. 62 + 55 = 117 > 100.

So the flagship capability is exactly the one that forces a swap, and the swap
eats the conversation model the user was just talking through.

The resolution is not "avoid it." It is:

> **Swap the generator, not the conversation — and when the requirement is a
> hard constraint, swap deliberately, visibly, and restore automatically.**

Two escape hatches, in preference order:

1. **Co-residency first.** 12 of 14 image models fit alongside a 55% planner.
   The resolver prefers a co-resident model whenever it satisfies the request.
2. **A co-resident flagship.** `abenzerps/Qwen-Image-2.1-Uncensored-Quantized`
   reports **0% NPU**, same weights family, same native RGBA. It coexists with
   anything. Offered with its caveat (community quant build, not
   vendor-supported).
3. **Deliberate swap.** For `Qwen/Qwen-Image-2.1` and `SenseNova-U1.5-8B-MoT`,
   the app performs a held swap: hold the watchdog, evict, load, generate,
   restore the planner. The user sees a progress event, not a hang.

The product rule that follows: **the resolver must be able to justify every
choice in one sentence a user can check.** "Chose Z-Image-Turbo (26% NPU,
co-resident) because you asked for a photo and it fits beside the planner"
is a good answer. "Chose Qwen-Image-2.1 (62% NPU, swap required) because you
need native transparency and no co-resident model provides it" is a better one.

## 3. System architecture

```
                    ┌────────────────────────────────────────────┐
                    │            Tiiny Image Agency             │
                    │                                            │
   User ──────────► │  ┌──────────┐    ┌─────────────────────┐  │
   (chat + canvas)  │  │ Work     │    │  Orchestrator       │  │
                    │  │ Surface  │◄──►│  (planner /         │  │
   Hermes ────────► │  │ (web)    │    │   resolver /         │  │
   (skill + API)    │  └──────────┘    │   critic)            │  │
                    │                 └──────────┬──────────┘  │
                    │                            │             │
                    │                 ┌──────────▼──────────┐  │
                    │                 │  Model Registry      │  │
                    │                 │  (device facts +     │  │
                    │                 │   specialty overlay) │  │
                    │                 └──────────┬──────────┘  │
                    │                            │             │
                    │                 ┌──────────▼──────────┐  │
                    │                 │  Residency Manager  │  │
                    │                 │  (NPU budget, swap) │  │
                    │                 └──────────┬──────────┘  │
                    │                            │             │
                    │                 ┌──────────▼──────────┐  │
                    │                 │  Device Adapter     │  │
                    │                 └──────────┬──────────┘  │
                    └────────────────────────────┼─────────────┘
                                                 │  LAN
                              ┌──────────────────▼──────────────────┐
                              │  Tiiny Pocket Lab                  │
                              │  ┌──────────────────────────────┐  │
                              │  │  NPU pool — 15,559 MB        │  │
                              │  │  shared, finite, evicting    │  │
                              │  └──────────────────────────────┘  │
                              │  /v1/chat/completions               │
                              │  /v1/images/generations             │
                              │  /v1/models   (resident only)       │
                              │  /api/v1/models/online_models       │
                              │  /api/v1/sys/status                 │
                              └─────────────────────────────────────┘
```

**The app runs on the Mac, not the device.** The Tiiny is the compute engine,
not the application host. It has no general runtime we should be installing
onto, and the app needs a web server, a file store, and SSE streaming.

### 3.1 Components

| # | Component | Responsibility | Holds the secret? |
|---|-----------|----------------|-------------------|
| 1 | **Work Surface** | Chat pane, image canvas, model badge, NPU meter, iteration history | No |
| 2 | **Orchestrator** | Drives the plan → resolve → generate → critique loop | No |
| 3 | **Model Registry** | Device facts + curated specialty overlay + residency classes | No |
| 4 | **Residency Manager** | Decides load/unload, performs held swaps, restores | No |
| 5 | **Device Adapter** | Typed client for the Tiiny's OpenAI-compatible + management APIs | **Yes** |
| 6 | **Asset Store** | Generated images, prompt lineage, plan provenance | No |
| 7 | **Public API** | Stable HTTP surface for Hermes and other agents | No |
| 8 | **Skill** | Hermes-facing procedure that calls the Public API | No |

**One rule:** the device bearer is loaded by the Device Adapter only, from the
environment. It never reaches the browser, never reaches the asset store, and
never appears in an API response or a log line. It is a device-admin-grade
secret — it grants read/write to the profile and `/api/v1/sys/setting`.

## 4. The Orchestrator

### 4.1 Intent → requirement vector

The LLM does **not** pick the model. It produces a structured requirement
vector. The resolver picks the model, deterministically, from the registry.

```
RequirementVector {
  artifact:   icon | illustration | photo | logo | poster | infographic
             | comic | character_sheet | texture | cutout | edit
  alpha:      required | preferred | no
  text_in_image: required | preferred | no
  style:      photoreal | flat | illustrated | crayon | layout | realistic_people
             | character_reference | general
  edit_op:    none | background_remove | object_remove | outpaint | detail_regen
  size:       {w, h}
  speed:      fastest | normal | quality_first
  hard:       [constraint, ...]   # non-negotiable; resolver may not violate
}
```

**Why the LLM does not pick the model.** Four reasons, all practical:

1. **The LLM does not know NPU costs.** It will pick the RGBA model every time
   and blow the budget on every call.
2. **The registry changes when the device updates.** 82 models today; the
   catalogue doc is already dated. A resolver that reads live metadata does not
   need retraining.
3. **Determinism is testable.** A routing decision has a traceable input and a
   checkable output. "The model picked this" is not debuggable.
4. **The LLM proposes; the resolver disposes.** The LLM may override with a
   justification — the resolver validates feasibility and either accepts it or
   explains why it cannot.

The LLM's actual job is the part humans are bad at: turning *"I need something
that looks like an app icon, but transparent, and not too cartoonish"* into
`artifact=icon, alpha=required, style=flat, size=1024x1024, speed=normal`.

### 4.2 Requirement vector → model

Deterministic scoring over the registry. For each candidate:

1. **Filter** — drop models that cannot satisfy a hard constraint (missing
   native alpha when alpha is required; missing edit op; unsupported input
   mode).
2. **Score** — weighted sum over specialty fit, quality, speed, and
   residency class.
3. **Rank** — highest score wins. Ties break toward lower NPU, then more
   steps (quality).

Residency enters the score as a **preference, not a veto**, except when the
model is the *only* one satisfying a hard constraint — then the resolver
returns a swap plan instead of a co-resident model.

### 4.3 Prompt dialect translation

A named module, not a side effect. When the target model changes — on the
first generation, or on a user request to *"make it more realistic"* — the
user's intent is **re-written into the target model's dialect**, using the
registry's `prompting.dialect` field for that model.

- Z-Image (8 steps): plain descriptive English, subject first. No quality
  booster tokens, no comma salad.
- ERNIE (typography): give the text verbatim and say where it goes.
- FLUX.2 (4 steps): short and literal — brevity over elaboration.
- HiDream (28 steps): dense and specific; name materials, light source, lens.
- Qwen-Image-2.1: shape language and negative space over adjectives.

This is where the quality of the product actually lives. The model matters;
the translation matters more.

**Measured 2026-11-05 — the dialect is the difference between a flat PNG and
a usable asset.** Two prompts, same model, same size, same 200 s:

| Prompt | Fully transparent px | Result |
|---|---|---|
| *"…transparent background, no text"* | **0%** | Good fox on a **soft white radial fade**. Usable only on white. |
| *"…alpha cutout on empty canvas, PNG with alpha channel, no gradient, no shadow"* | **44.86%** | Genuine cut-out. Shows through a dark surface. |

The second prompt also changed the *style* — hard-edged and angular rather
than soft and rounded, with narrower eyes. **The dialect buys transparency at
some cost to character fidelity.** A translator that maximises transparency
will produce icon-quality cut-outs that do not look like what the user asked
for; one that maximises fidelity will produce a pretty picture on an opaque
background. The translator has to know which the user wants, and the
requirement vector is where that preference belongs.

The second image also carries a **faint white halo** along the fox's edge —
the classic alpha-matte fringe. Real, and worth a post-processing step
(threshold or de-fringe) rather than pretending it is not there.

**A note on the device's claim.** The catalogue says this model "can output
images with a real transparent background, so stickers, logos, and product
cutouts come out ready to place on any design without a separate
background-removal step." The channel is real and the cut-out is achievable.
It is **not automatic** — it took a deliberate prompt. The device's claim is
about capability, not about default behaviour, and the difference is exactly
the product's job.

### 4.4 The critique loop

```
user request
   │
   ├─► planner (LLM, vision+text)      → requirement vector
   ├─► resolver (deterministic)        → model + plan + residency class
   ├─► residency manager                → load / hold / swap
   ├─► generate                         → POST /v1/images/generations
   ├─► critic (LLM, vision)            → image vs requirement vector
   │       ├─ pass  → deliver
   │       └─ fail  → dialect rewrite → regenerate (bounded retries)
   └─► asset store                      → PNG + prompt lineage + plan
```

The critic reads the generated image and judges it against the **requirement
vector**, not against the user's original words. That distinction matters: the
user said *"a fox"*, the requirement vector said `artifact=icon, alpha=required`,
and the critic judges the icon.

#### 4.4.1 The judge is a model that can SEE

The critic is a **model the user chooses** — and every model it can be is a
vision model. There is no blind option, and the reason is a measurement:

| | `device.chat()` | `device.vision()` |
|---|---|---|
| What it sees | the prompt and the requirement vector | the prompt, the vector, **and the pixels** |
| What it can catch | a prompt that does not ask for what was requested | a generation that simply came out wrong |
| What it cannot catch | a wrong image | — |
| Cost | the conversation model's | a vision model's, which is usually larger |

A blind judge is not a broken judge — it is the right judge for *is this the
brief?* — but it is the wrong judge for *is this picture right?*, and it has a
specific failure mode: asked to judge something it cannot see, it will
invent a defect rather than admit the limit, and every invented defect
becomes an instruction to regenerate. The first live run of the Agency
burned three generations chasing a defect the prompt judge invented.

**So the Agency refuses a text-only judge**, and says why:

> `openai/gpt-oss-20b` cannot see an image, so it cannot be the judge. A judge
> that reads text only judges the PROMPT, and it will invent a defect rather
> than admit the limit. Choose a model marked as seeing one — `tis roles`
> lists them.

The refusal carries the reason because a refusal that explains itself can be
acted on and one that does not cannot. The default judge is
`Qwen/Qwen3.6-35B-A3B` at 47%, which sees.

**The conversation agent is a separate setting and is not affected.** It
writes the plan and never looks at a pixel, so a small text model is the
right model for it — and a 27% one costs no swap at all, because the watchdog
already holds it.

**The fit is the judge plus a generator, against the 81% execution
ceiling.** The talker is not in that sum: it has already written the scene
description by the time the image is made, so its weights are swapped out
and the judge and the generator have the pool to themselves. A 47% vision
judge and the 23% default generator is 70%, and that runs.

**The second catalogue.** The image registry holds the generators; the
roles catalogue (`registry/roles.json`, curated in `app/data/roles.yaml`)
holds the models that talk and judge. They are separate because no text
model is in the image registry and no image model can hold either role.
`vision` is derived from the device's own record — `type ==
"Image-Text-to-Text"` or an `input` that accepts an image — and every
entry says whether it was measured here (`m`) or is the device's own claim
(`d`).

A model that is listed is not a model that is downloaded. The guide marks
the difference, and the residency manager prices a judge from the roles
catalogue, because a judge priced at zero would leave the pool above the
ceiling and the generation would fail.

Retry bound: 3 generations per user turn. Each is a real image on the NPU —
HiDream at 1024² is ~34s, so an unbounded loop is a foot-gun.

## 5. Residency Manager

### 5.1 The budget

**Measured 2026-11-05.** The pool is **47.9 GiB** of NPU-RAM (`tiiny status`),
not the 15,559 MB the management API reports — that field is unstable across
reads and is not a pool-size figure. See `MEASUREMENTS.md` §M1.1.

The budgeting unit is the **percentage**, and it is not derivable from model
size: three models of ~14 GiB carry 55%, 30% and 62%. Read it, don't compute it.

| Model | NPU % | Model size | With 55% planner | Class |
|---|---|---|---|---|
| `abenzerps/Qwen-Image-2.1-Uncensored-Quantized` | 0 | 14.5 GiB | 55% | co-resident *(unverified)* |
| `Tongyi-MAI/Z-Image-Turbo` | 26 | 9.5 GiB | 81% | **co-resident — measured** |
| `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `Tongyi-MAI/Z-Image-Turbo-Children-Drawing` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `black-forest-labs/FLUX.2-klein-4B` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `fal/FLUX.2-klein-4B-Background-Remove` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `fal/FLUX.2-klein-4B-Object-Remove` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `fal/FLUX.2-klein-4B-Outpaint` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `fal/FLUX.2-klein-4B-Zoom` | 26 | 9.5 GiB | 81% | co-resident *(unverified)* |
| `baidu/ERNIE-Image-Turbo` | 27 | 9.5 GiB | 82% | co-resident *(unverified)* |
| `HiDream-ai/HiDream-O1-Image-Dev` | 30 | 14.2 GiB | 85% | co-resident *(unverified)* |
| `SenseTime/SenseNova-U1.5-8B-MoT` | 48 | — | **103%** | **swap** |
| `Qwen/Qwen-Image-2.1` | 62 | 14.5 GiB | **117%** | **swap — measured** |

**Measured:** the 55% planner and a 26% image model coexist at NPU 81%. The
load evicted `gpt-oss-20b` (27%) — 55 + 27 + 26 = 108% — so the device keeps
the heavy models and sheds the rest to fit. The co-residency claim is
confirmed for the Z-Image case and **still unverified for the other eleven.**
The `abenzerps` 0% case is the sharpest unknown: 14.5 GiB of model reported
at 0% NPU is either free to coexist or it will evict something.

12 of 14 *should* fit beside the planner. One case is now measured. The other
eleven are arithmetic on a device-assigned weight, and the arithmetic has
already been wrong once — the management API's pool figure.

### 5.2 Swap choreography

**Measured 2026-11-05 — the eviction is total, not partial.** Loading an image
model does not just evict the chat model; it evicts the **whole resident set**
except models reporting 0%.

| Action | NPU before | NPU after | What was evicted | Load time |
|---|---|---|---|---|
| Load `Qwen3-Coder-30B-A3B-Instruct-Turbo` (55%) | 86% | 94% | `Qwen3.6-35B-A3B` (47%) | **54.5 s** |
| Load `Qwen-Image-2.1` (62%) on top | 94% | 62% | planner, `gpt-oss-20b`, ASR, both TTS | **12.5 s** |
| Load `Z-Image-Turbo` (26%) on top of the 55% planner | 82% | 81% | `gpt-oss-20b` (27%) | **30.7 s** |

Earlier vault evidence: after `tiiny load HiDream-ai/HiDream-O1-Image-Dev`,
`Qwen/Qwen3.6-35B-A3B` began returning 404 "is not loaded".

**Two consequences the design has to absorb.**

1. **During a flagship generation there is no conversation model on the
   device at all.** Not "a smaller one" — none. Any fallback has to be
   *loaded after* the generation, or the generation has to be run without a
   conversation in flight. See §5.3.
2. **Load times are tens of seconds, not seconds.** 54.5 s for the planner
   into an occupied pool; 12.5 s into a nearly empty one; 30.7 s for a 26%
   image model. The product's honest number is **the worst case, about a
   minute**, and it must be shown as a progress event. A silent stall is the
   failure mode this product exists to avoid.

Two existing traps the manager must handle:

| Trap | Handling |
|---|---|
| `tiiny load` needs a TTY | Run under a pseudo-terminal (`script -q /dev/null`) |
| The watchdog re-loads its required set every 5 min and will evict a deliberate swap | Use the **hold file** `~/.hermes/tiiny-hold`, or `~/.hermes/scripts/tiiny-swap.sh` |
| Models unload on reboot | The same watchdog restores them; the app should detect and report rather than silently 404 |

**The swap sequence:**

```
1. write ~/.hermes/tiiny-hold          (before the load — closes the race)
2. unload the planner                   (free its 55%)
3. load the target image model          (under a pty)
4. generate
5. unload the target
6. reload the planner
7. remove ~/.hermes/tiiny-hold
```

Every step emits an event to the work surface. The user sees *"releasing the
planner to load Qwen-Image-2.1 (62% NPU) — this takes about 20 seconds"* and
then a progress bar. A silent 30-second hang during which the chat appears
broken is the failure mode this product exists to avoid.

### 5.3 Why the planner and the generator are separable

This is the architectural move that makes the swap cheap.

The conversation model and the generation model do not have to be the same
model, and they do not have to be the *big* model. During image generation the
planner is mostly idle — it is not reasoning hard, it is waiting on the
diffusion pass. So:

**Measured 2026-11-05 — and the fallback *loads* but does not *run*.** With
`Qwen-Image-2.1` (62%) resident, loading `openai/gpt-oss-20b` (27%) succeeded
and both stayed resident at **NPU 89%**. 62 + 27 = 89 ≤ 100.

But a generation attempted at that occupancy **failed**:

```
HTTP 500 {"error":{"message":"The operation failed to complete.",
                   "type":"server_error","code":150004}}
```

The identical prompt, with the flagship alone (69% NPU), generated fine in
197 s. So the 500 was caused by the co-residency, not the prompt.

> **Admission and execution are different constraints.** A model set can be
> *admitted* (fits the NPU budget) and still not be *executable* (no headroom
> for the diffusion pass). The residency manager must therefore budget for
> **two** things: what fits, and what can run.

| Path | Composition | NPU | Admission | Generation |
|---|---|---|---|---|
| **Hot path** — planner + 26% image model | 55 + 26 | 81% | fits | not yet tested |
| **Occupied path** — flagship + small chat | 62 + 27 | 89% | fits | **fails — 500** |
| **Dead path** — flagship + 55% planner | 62 + 55 | 117% | evicted | impossible |
| **Clean path** — flagship alone | 62 | 62% | fits | **works — 197 s** |

The design consequence, and it is a design change from the original spec:

> **The conversation model is loaded *after* the generation, never beside it.**
> When the resolver picks the flagship, the sequence is:
> load flagship → generate → load `gpt-oss-20b` as the conversation → restore
> the planner when the turn ends.

The user is not silenced for the whole turn — only for the generation, which
is a single blocking call with a progress bar. The alternative (keep a chat
model resident beside the generator) is now known to **break generation**, and
the device proved it.

This is the single most important thing Phase 0 established, and it was not
the design that was written before the measurements.

### 5.4 The budget has two constraints, not one — and the boundary is measured

**Measured 2026-11-05.** The device enforces **two** separate limits, and the
gap between them is the whole product:

| Occupancy | Composition | Generation |
|---|---|---|
| **62%** | flagship alone | ✅ **works** — 197 s, 202 s |
| **81%** | planner (55%) + `Z-Image-Turbo` (26%) | ✅ **works** — **54.5 s**, 1.19 MB |
| **85%** | `PE-T2I` (23%) + flagship (62%) | ❌ **500 / 150004** |
| **89%** | `gpt-oss-20b` (27%) + flagship (62%) | ❌ **500 / 150004** |

> **Admission and execution are different constraints.** 85% and 89% are
> *admitted* — the models load and stay resident — and then the diffusion pass
> fails. The threshold sits **between 81% and 85%**. A residency manager that
> budgets only for admission will build a product that loads successfully and
> then fails at generation time.

This produces the two operating modes the product actually has:

**Hot path — 81%.** The 55% planner and a 26% image model coexist, and
generation runs **in 54.5 s while the conversation model stays live.** This
covers the Z-Image family (5), the FLUX.2 family (5), ERNIE, and HiDream —
ten of the fourteen. The conversation never stops. **This is the default path
and it should be the default.**

**Flagship path — 62%.** `Qwen-Image-2.1` must have the device to itself. The
planner is evicted, the generation runs (~200 s), and the planner is restored
afterwards. This is the only path to native RGBA, so it costs a swap and a
~200 s generation with no conversation in flight.

**The cost of the flagship is now quantified, not asserted:** ~55 s of load
plus ~200 s of generation, with the conversation interrupted for the duration.
Against the hot path's 54.5 s with no interruption. That comparison is the
honest answer to "which model should the resolver pick?"

### 5.6 The appliance takes a source image, and the Agency was not sending one

`POST /v1/images/generations` accepts a source image. The field is
`image` (a base64 **string**) or `images` (an **array** of them). Both
were confirmed by the appliance's own type errors — it reports the
expected type without naming the field, so the field has to be found by
the status code, not by reading the message:

| field | answer | meaning |
|---|---|---|
| `image` | 400 `type must be string` | recognised — a string |
| `images` | 400 `type must be array` | recognised — an array |
| `image_url`, `init_image`, `input_image`, `source_image`, `image_base64`, `reference_image` | 200 | ignored |

**That the field is recognised is not the same as the image being
honoured,** and the distinction matters enough to be measured rather than
assumed. The proof used a control: a half-red, half-blue rectangle, the
prompt *"reproduce this image as a pencil sketch"*, and a second request
with **no image at all**.

| variant | time | what came back |
|---|---|---|
| **control (no image)** | **16.3 s** | **a random bald man's face** |
| `image` = raw base64 | 33.9 s | **the input** — a rectangle split vertically, dense hatching left, light right |
| `image` = data URL | 34.4 s | the input's rectangle, faint vertical division |
| `images` = [raw base64] | 34.0 s | the input, split inverted |

Two independent signals agree. The control drew a completely different
*subject*; every image-bearing variant drew the input's *structure*. And
the timing splits cleanly — 16.3 s without an image, ~34 s with one.

**This changes the product.** The catalogue already advertised
`input: Text,Image` and `supported: ['Image Editing']` for
`Qwen/Qwen-Image-2.1` and the FLUX adapters, and the curated overlay
already carried `max_refs: 10` and `identity_preservation` for exactly
the two models that take an image. But `device.generate()` sent only
`model`, `prompt`, `size` and `n`, so **every drag-and-drop edit had
been a text-only regeneration wearing an edit's name.** The appliance
was always capable; the Agency was simply not asking.

The bare-base64 form is the one to use: it is what the appliance accepts
as a string, and it preserved the input's structure more faithfully
than the data-URL form. Which *models* honour it is a separate
measurement, and the resolver must not offer an image-conditioned edit
to a model that cannot take one.

### 5.7 The catalogue has no "new model" signal

The catalogue holds 92 rows: 50 `not_downloaded`, 37 `downloaded`, 5
`running`. `need_update` is `False` on all 92 — it cannot signal
anything. The only usable signals are `created_time` and `udpate_time`.

There is no vendor "what's new" endpoint. **So the Agency keeps its own
watermark** — the catalogue ids seen at the last check — and diffs
against it. A notice is an *offer*, never an action: ten GiB must not
move because a row appeared in a catalogue the user did not ask about.

### 5.8 The prompt-enhancer models are admitted but not callable
The device ships `Qwen/Qwen-Image-2.1-PE-T2I` (23%, 262,144 ctx, downloaded)
and `Qwen/Qwen-Image-2.1-PE-I2I` (24%, **not downloaded**). Their descriptions
say the output is "meant to be passed straight to Qwen-Image-2.1" — they are
the dialect translator, purpose-built and shipped.

**They do not answer on the chat endpoint.** Every request variant returned:

```json
{"error":{"message":"Model 'Qwen/Qwen-Image-2.1-PE-T2I' does not support chat.",
           "type":"invalid_request_error","param":"model","code":400}}
```

Plain, explicit `enable_thinking`, and system+user were all identical. The
model loads and occupies 23% of the NPU but refuses `/v1/chat/completions`.

**Consequence: the dialect translator still has to be built.** It cannot be
delegated to PE-T2I through the documented API. It must run on a
chat-capable model — and the planner is the obvious one, since the planner is
already resident on the hot path.

**This is worth raising with the device vendor.** A shipped model that cannot
be called is either an app-internal component, a packaging omission, or a
feature flag. Until it is callable, it is dead weight in the registry — and
the registry should say so rather than list it as an option.

## 6. Public API

Stable, documented, and the only path an external agent should take. One rule
underlies it:

> **Agents do not get to bypass the orchestrator.** An agent that calls
> `/v1/images/generations` on the device directly will blow away the chat
> model and every other resident model, and will not know which model it just
> evicted. The API exists so that never happens.

### 6.1 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/models` | The registry — every image model with specialty, NPU cost, residency class, dialect |
| `GET` | `/v1/models/cards` | **Every** card in one request — for a browser listing, which would otherwise make one request per model |
| `GET` | `/v1/models/card?model_id=` | The **card** for a model: what the device advertises, what we measured, what we have noticed |
| `GET` | `/v1/roles` | The **guide** — every conversational model, whether it can see an image, its NPU cost, whether it is on the device, and whether the current pair fits the pool |
| `POST` | `/v1/roles` | The **choice** — `{"critic": "..."}` and/or `{"conversation": "..."}`. Applies to the next job. A critic that cannot see an image is refused |
| `GET` | `/v1/npu` | Live residency: resident models, NPU MB used/free, loaded set |
| `POST` | `/v1/plan` | Request → requirement vector + resolved model + justification + swap plan |
| `POST` | `/v1/generate` | Request or plan → asset. Handles load/swap/generate/restore. Takes `output_path` and `reference_id` |
| `POST` | `/v1/iterate` | Asset + feedback → revised prompt (dialect-translated) → new asset. Takes `output_path` |
| `POST` | `/v1/assets` | **Upload** an image — the image bytes are the body (PNG or JPEG) → asset id. The door for "update this image" |
| `GET` | `/v1/assets/{asset_id}` | The image, in the format it was stored in (PNG, alpha preserved) |
| `POST` | `/v1/documents` | **Make a PDF** of some assets, one page each. The images go in untouched — a JPEG as JPEG, an RGB PNG's scanlines as they are, and an RGBA PNG's alpha as its own transparency channel |
| | | The document's title is **metadata only** — it is not drawn on the page, because a drawn title needs a font and a font is a dependency this project has so far refused |
| `GET` | `/v1/assets/{asset_id}/lineage` | Full provenance: plan, prompts, model, sizes, timings, and the file's path |
| `POST` | `/v1/references` | **Save an asset as a named reference** — the PNG byte-for-byte plus its recipe: model, dialect, size, requirements, modifiers, critique |
| `GET` | `/v1/references` | The saved references, newest first |
| `GET` | `/v1/references/{ref_id}` | One reference, with its recipe |
| `DELETE` | `/v1/references/{ref_id}` | Forget it |
| `GET` | `/v1/session/{session_id}/events` | SSE stream — plan, load, generate, critique, swap progress, and `catalogue.new_model` |
| `GET` | `/v1/health` | Device reachable? Registry fresh? App alive? |

### 6.2 Request and response shapes

```jsonc
// POST /v1/plan
{
  "request": "I need an app icon of a fox head, flat, transparent background",
  "size": {"w": 1024, "h": 1024},
  "session_id": "optional"
}

// 200
{
  "plan_id": "plan_01H...",
  "requirements": {
    "artifact": "icon", "alpha": "required", "text_in_image": "no",
    "style": "flat", "size": {"w": 1024, "h": 1024},
    "speed": "normal", "hard": ["native_alpha"]
  },
  "model": {
    "id": "Qwen/Qwen-Image-2.1",
    "role": "flagship",
    "npu_usage": 62,
    "co_resident_with_planner": false
  },
  "justification": "Native transparency is a hard requirement and no "
                   "co-resident model provides it. This model costs 62% NPU, "
                   "so the planner is released for the generation and restored "
                   "afterwards. Expected cost: ~20s load, ~35s generate.",
  "alternatives": [
    {"id": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
     "note": "Same native RGBA, 0% NPU, no swap — community quant build, "
             "not vendor-supported. Offer to the user."}
  ],
  "swap_required": true,
  "swap_plan": {
    "evict": ["Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"],
    "load": "Qwen/Qwen-Image-2.1",
    "restore": ["Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"],
    "conversation_fallback": "openai/gpt-oss-20b"
  }
}
```

```jsonc
// POST /v1/generate
{
  "plan_id": "plan_01H...",       // or "request": "..." to plan and generate
  "prompt": "user's own words",   // optional; the orchestrator will
                                  // dialect-translate if absent
  "model_id": "optional model",   // the model the caller wants; honoured
                                  // when it can do the job, and the
                                  // agency says so when it cannot
  "output_path": "/tmp/final.png" // optional; the finished PNG is ALSO
                                  // written here, byte for byte. The
                                  // agency's own copy is written either
                                  // way.
}

// 202 ACCEPTED — the work is QUEUED, not done
{
  "job_id": "job_01H...",
  "session_id": "default",
  "status": "queued"
}
```

The `output_path` copy is the same bytes, never a re-encode. A round trip
through an image library is exactly where a transparent background quietly
becomes an opaque one, so the agency copies and never decodes.

```jsonc
// POST /v1/assets — the door for "update this image"
// The body IS the PNG. No multipart: the bytes are the image.
{
  // ...raw PNG bytes, Content-Type: image/png
}

// 200
{
  "asset_id": "ast_01H...",
  "path": "/Users/you/.hermes/tia/assets/ast_01H....png",
  "bytes": 1030281
}
```

The uploaded bytes are stored **exactly as given**. PNG and JPEG are
accepted, and the format is taken from the **bytes** rather than from
what the caller says — so a JPEG is stored with a `.jpg` name and
served as `image/jpeg`. Anything else is refused.

A JPEG was **measured**, not assumed: the appliance takes one in its
`image` field (HTTP 200, 34.1 s). It is not converted to PNG at
upload, because the appliance decodes it to pixels itself, so a
conversion would produce exactly the same picture and would cost a
re-encode that could only lose what the JPEG already lost. What a JPEG
*did* lose is its alpha channel, and that happened before the agency
ever saw the file — so the lineage says `"alpha": "none"` and names the
loss in words rather than leaving the caller to discover it later.

```jsonc
// POST /v1/assets — the door for "update this image"
// The body IS the image. No multipart: the bytes are the image.
// Content-Type: image/png or image/jpeg
{
  // ...raw image bytes
}
{
  "asset_id": "ast_5f3c...",
  "path": ".../assets/ast_5f3c....png",
  "bytes": 1030281,
  "format": "png"
}
```

```jsonc
// GET /v1/models/card?model_id=Tongyi-MAI%2FZ-Image-Turbo
{
  "model_id": "Tongyi-MAI/Z-Image-Turbo",
  "advertised": "what the DEVICE says the model is for...",
  "notes": "what WE have noticed that the device does not say...",
  "measured": { ...the research card... },
  "researched": true,
  "downloaded": true,
  "npu_usage": 23
}
```

A card exists for every model in the catalogue, researched or not — "not
measured yet" is a fact the card reports, not a 404. The three parts are
kept apart on purpose: the whole point of the card is the distance between
the vendor's claim and what the model actually does.

```jsonc
// GET /v1/assets/{asset_id}/lineage — the provenance, including where
// the file is
{
  "model_id": "Tongyi-MAI/Z-Image-Turbo",
  "prompt": "the prompt that was actually sent",
  "requirements": { ... },
  "critique": { ... },
  "path": "/Users/you/.hermes/tia/assets/ast_01H....png",
  "output_path": "/tmp/final.png"
}
```

### 6.3 The Skill

Hermes should reach the device through this app, not around it. The skill is a
procedure, not a wrapper:

```
name: tiiny-image-agency
description: "Plan and generate images on the local Tiiny appliance."
```

Skill rules, in order of priority:

1. **Never call the Tiiny's `/v1/images/generations` directly.** Go through
   the Image Studio API so residency is managed. A direct call evicts the
   resident chat model and the agent will not know what it displaced.
2. **Describe the request in terms of the artifact**, not the aesthetic —
   "app icon, transparent background" routes better than "nice modern fox".
3. **Iterate with `/v1/iterate`**, not by re-calling generate with a new
   prompt. The iterate endpoint does the dialect translation; a hand-rolled
   prompt loses it.
4. **Read the critique.** The orchestrator returns why an image missed. A
   second attempt with the critique applied is better than a third blind
   attempt.
5. **Report the model.** Say which model produced the asset and why. The model
   choice is the interesting part.

## 7. Work Surface

**The surface has three tabs: Make, Models, References.**

**Make** is the generation flow: the conversation, the canvas, the drop
zone, the iteration strip, the roles, the resolver's alternatives, the
confirmation dialog and the lineage.

**Models** is the card browser. The cards were a dropdown at the bottom
of a long page, which meant a person who wanted to learn what the
models were had to go looking for them. It is a grid instead: every
model at a glance, with what it costs and what it was measured to do,
and a pane beside it to read one in full.

**References** is where the saved results live, so a repeated job comes
out consistent. It is empty until a reference is saved.

The three parts of a card stay visually separate: what the device
advertises, what we measured, and what we have noticed that the device
does not say. The distance between the first two is the whole reason a
card exists.

**The tab is fetched when it is opened, not at page load.** The Make tab
does not need seventeen cards, and a request the user did not ask for is
a request the user waits for. The filters — by kind of picture, by
measured or not, and a text search — run against what is already in the
browser, so a keystroke is not a round trip.

Three panes, one screen.

```
┌─────────────────────────────┬──────────────────────────┐
│  CONVERSATION               │  CANVAS                  │
│                             │                          │
│  "icon of a fox,            │  ┌────────────────────┐  │
│   transparent"              │  │                    │  │
│                             │  │   [ generated ]    │  │
│  → Plan: Qwen-Image-2.1     │  │                    │  │
│    native RGBA, swap req.   │  └────────────────────┘  │
│    alt: 0% NPU build ✓      │                          │
│                             │  ▢ checkerboard = alpha  │
│  → Generating…              │                          │
│    releasing planner 20s    │  ┌──┐ ┌──┐ ┌──┐         │
│                             │  └──┘ └──┘ └──┘  history │
├─────────────────────────────┴──────────────────────────┤
│  NPU ████████░░░░  8,834 / 15,559 MB free              │
│  Resident: planner · Z-Image-Turbo                     │
└────────────────────────────────────────────────────────┘
```

Required elements:

- **Tab strip** — *Make*, *Models*, *References*. The strip is flat and
  quiet so the content is what draws the eye, and each tab reports its
  state with `aria-selected` rather than only by colour.
- **Model badge** — which model produced the current asset, and why it was
  chosen. One line, always visible.
- **NPU meter** — used/free MB, and the resident set. This is the app's
  honesty about the constraint that shapes it.
- **Alpha checkerboard** — transparency is invisible on white. If the product
  is going to sell native RGBA, it has to *show* it.
- **Swap banner** — during a swap, a clear banner with elapsed time and what
  is being released. Never a silent stall.
- **Iteration strip** — thumbnails of every attempt in the current turn, so
  the conversation has a visual history.
- **Roles panel** — two pickers, *Talks* and *Judges*, fed by the agency's
  own guide (`GET /v1/roles`) rather than a hard-coded list. Each option says
  whether the model can **see** an image, what it costs, and whether it is
  on the device. The *Judges* picker lists **only** models that can see —
  the agency refuses a blind judge, and a picker that offered one would be
  offering something it will later reject. Below them, one line that says
  whether the current pair **fits** the pool, measured against the 81%
  ceiling — because a choice that does not fit is a choice that will fail in
  the middle of a generation.
- **The dialog** — before anything is generated, the surface says which model
  was chosen and why, offers the alternatives with their NPU cost and
  whether they are on the device, says what a download would cost when one
  is needed, and **waits**. A generation costs a minute and sometimes three;
  a model the user did not need is worse than a slow one.
- **The drop zone** — drag a PNG onto the surface and it becomes the source
  of the next request. The file is stored byte for byte, and the next
  request is an **edit** of that image rather than a new picture — the
  difference between "make this better" and "make me something else".
- **The file's path** — under the image, the path of the finished PNG. A
  user who wants the file should not have to ask where it went.
- **The model-card browser** — on the *Models* tab, a grid of every model
  in the catalogue with what it costs and what it was measured to do, and
  beside it a pane to read one in full: what the device **advertises** it
  does, what we **measured** it to do, and what we have **noticed** that
  the device does not say. The third part is the point. The card exists
  for every model — "not measured yet" is a fact it reports, not a
  missing page.
- **The card filters** — by kind of picture, by measured or not, and a
  text search. They run against what is already in the browser, so a
  keystroke is not a round trip.

## 8. Build phases and verification

### Phase 0 — Ground truth (do this before writing the app)

| Task | Why it blocks |
|---|---|
| **Validate the NPU arithmetic.** Load each image model and record actual NPU MB before/after. The percentages are the device's claim, not an observation. | The entire residency manager depends on the number being real |
| **Confirm Qwen-Image-2.1 actually emits an alpha channel.** Load it, generate, inspect the PNG for an alpha channel with real transparency. | It is the flagship claim; the catalogue says so, the device metadata says so, but nobody has looked at the pixels |
| **Measure `openai/gpt-oss-20b` as the conversation fallback.** Can it hold a multi-turn planning conversation while a 62% model is resident? | It is the answer to "how do we not silence the user during a swap" |
| **Measure generation latency per model** at each verified size | The swap UX needs honest timing, not catalogue prose |

### Phase 1 — Registry and resolver (no UI)

CLI tool. Input a request, print the requirement vector, the resolved model,
the justification, and the alternatives. **Run it over 30 hand-written
requests** covering every artifact type, both alpha cases, every edit op, and
at least one deliberately impossible request. The resolver's output is
reviewable by eye — a human should agree with most of them.

Exit criterion: a human agrees with the resolver on ≥ 85% of the 30 requests.

### Phase 2 — Generation and the swap

Wire the device adapter. Implement the residency manager with the hold file.
Prove the swap path end to end, including the restore, including a crash
mid-swap.

Exit criterion: 20 consecutive generate operations with no orphaned models left
resident and no watchdog fight.

### Phase 3 — Work surface

Chat, canvas, NPU meter, model badge, swap banner, iteration strip. SSE for
the event stream.

### Phase 4 — Iteration loop

Dialect translation module + vision critique + bounded retries.

### Phase 5 — Public API and Skill

The six endpoints, the OpenAPI document, the Hermes skill, and a test that
proves an agent cannot accidentally bypass the orchestrator.

### Phase 6 — Demo packaging

Scripted demo, README, a 90-second video.

## 9. Risks and open questions

| Risk | Evidence | Mitigation |
|---|---|---|
| The device's `desc` metadata is unreliable | Confirmed — one model carries another's description verbatim | The specialty overlay is hand-curated and versioned; device metadata is facts only |
| NPU percentages are claims, not observations | Derived from `npu_usage` field | Phase 0 task 1; the resolver degrades to "prefer lower NPU" if the numbers prove wrong |
| The planner cannot hold a conversation while a big model is resident | Untested | Phase 0 task 3; the fallback chain is `gpt-oss-20b` → cloud → tell the user |
| The RGBA capability cannot coexist with the planner | 62 + 55 > 100, confirmed from device metadata | Co-resident 0% NPU sibling, plus a deliberate swap path |
| Model quality varies wildly and unpredictably | The catalogue's whole premise | The critic loop is the quality lever; the model is the floor |
| The bearer is device-admin grade | Confirmed | Adapter-only access; never in a response, a log, or the browser |
| The watchdog fights deliberate swaps | Confirmed in the vault | Hold file, written before the load |
| The app is single-user, single-device | By construction | Stated explicitly. Not a multi-tenant product |

**Open questions for the device vendor:**

1. Why does `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` carry the
   CharacterDesignSheet description? The catalogue cannot be trusted at face
   value until this is fixed.
2. Can `npu_usage` be read as a fraction of the 15,559 MB pool, or is it
   weighted differently? The answer changes whether 55% + 62% is really
   impossible or merely discouraged.
3. Is there a documented way to reserve NPU for a model rather than evicting?
   The whole swap dance would be unnecessary if the API supported pinning.

## 10. Explicit non-goals

- **Not a general-purpose image editor.** It generates and iterates. It does
  not become a full editor.
- **Not multi-tenant.** One user, one device, one Mac.
- **Not a hosted service.** It runs on your hardware, against your appliance.
- **Not a model marketplace.** The registry is a local view of the device's
  store, plus curated notes.
- **Not cloud fallback by default.** Tiiny is free and private; that is the
  point. A cloud fallback exists for resilience, and it is always explicit and
  always disclosed.

## 11. Provenance

Every number in this document was read from the device on 2026-11-05.

| Fact | Source | Tier |
|---|---|---|
| 82 models in the store, 14 Text-to-Image | `GET /api/v1/models/online_models` | d |
| NPU pool 15,559 MB, 8,834 MB free, 81.4% utilization | `GET /api/v1/sys/status` | d |
| Resident set: Qwen3.6-35B-A3B (47%), gpt-oss-20b (27%), ASR (7%), TTS (5%), TTS (0%) | `GET /v1/models` + store | d |
| `npu_usage` per model | store metadata | d |
| Qwen-Image-2.1 is the only native-RGBA model | store `desc` + catalogue | d |
| `abenzerps` variant reports 0% NPU, same family | store metadata | d |
| Image API shape: `POST /v1/images/generations`, body `{model, prompt, size, n}`, response `data[0].b64_json` | working client `tiiny_image.py` | d |
| Loading an image model evicts the chat model | verified in the vault, 2026-10-25 | m |
| Z-Image rejects 1536×1024, 1024×1536, 1792×1024 | vault, measured | m |
| Hermes's `image_generate` tool sends the two rejected sizes | vault | m |
| Specialties and dialects | `tiiny-discovery/tiiny-model-catalogue.md`, curated 2026-11-01 | d,i |

**Not claimed:** that the residency arithmetic is empirically confirmed — it is
derived from metadata and is Phase 0 task 1. That Qwen-Image-2.1's PNG has a
working alpha channel — nobody has inspected the pixels yet. That the registry
will stay accurate — the device's catalogue moves faster than any document.

---

**Related**

- `PRODUCT-PLAN.md` — why this exists and who it is for
- `registry/image-models.json` — the generated registry
- `tools/build_registry.py` — the generator, and the overlay as code
- `PLAN-THREE-FEATURES.md` — the next three features, and the measurements that shaped them
- `MEASUREMENTS.md` — every number this spec quotes, and where it came from

**In the vault only**, three sibling documents carry the device's
context: the compute-tier design note, the full model catalogue, and
the endpoint inventory. They live outside this project's folder and so
are not published here.
