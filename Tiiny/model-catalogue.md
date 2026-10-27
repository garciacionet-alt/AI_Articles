# Tiiny Model Store — every model and what it is actually good at

**73 models on the device this was read from. Each one has a specialty.** The specialty is not always in the
name, and the name is sometimes misleading — the strongest finding from
reading all 73 device descriptions is that the *device's own metadata* is a
better guide to what a model is for than its filename is.

This document is a research addendum to the factual list Zolon published in
[`thezolon/tiiny-api-notes`](https://github.com/thezolon/tiiny-api-notes)
(`docs/MODELS.md`). His file is the authoritative **inventory** — every model,
its parameters, NPU share, size, and context window, regenerated from the
device. This document adds the **judgement**: what each model is specialised
for, when to reach for it, and where the catalogue is wrong or misleading.

> **Status: maintained.** The model catalogue changes with every TiinyOS
> update. The numbers below were read from the device on 2026-10-27 and match
> Zolon's snapshot exactly (0 discrepancies in NPU, size, and context across
> all 73).

---

## How the specialties actually work

Image models have obvious specialties because a LoRA adapter is a *style
toggle* — you can see it in the output. LLMs are subtler, and the axes are
different. Four patterns show up across this catalogue:

**1. Architecture is the strongest signal.** A model labelled `A3B` or `A4B` is
a mixture-of-experts: it holds 26–35B of weights but activates only 3–4B per
token, so it *thinks* like a large model and *runs* like a small one. A dense
model (`27B`, `31B`) runs every parameter on every token, which is slower but
gives steadier per-token quality. This is the single biggest decision in the
catalogue, and it is invisible if you only read the model name.

**2. Post-training creates the real specialisation.** `Qwen3-Coder-Next` is
Qwen base plus coding RL. `Ornith` is a Qwen/Gemma base plus self-generated
task RL. `BigBang` is Qwen3.6 plus adversarial self-evolving data. `gemma-4-*-it`
is base plus instruction tuning. Same size, same context, completely different
specialty.

**3. Chat models are not interchangeable with agent models.** A model built for
"answer the question" and a model built for "hold a task open across 40 tool
calls" are different animals. The device tells you which is which: 11 models
are advertised for "any agent in Agent Store", and only 4 are advertised for
coding agents specifically.

**4. The `-Turbo` suffix is a distillation trade.** Turbo variants are
distilled for speed and cost accuracy slightly. They are the right default for
interactive work, the wrong default for anything where a wrong answer is
expensive.

**A caution on inference.** The specialties below are read from the device's
own descriptions, which are themselves written from each project's model cards.
They are *the publisher's claims about their own model*, not independent
benchmark results measured on this device. I have not run all 73 and timed
them. Where a claim is mine rather than the device's, it says so.

---

## The constraint that decides everything: NPU is one shared pool

The device has a finite NPU budget. Models that add up to more than 100% of
NPU RAM cannot be loaded together, and loading one can evict another — an
image model evicts the chat model and vice versa. This is why "which model is
best" is usually the wrong question on this device. The right question is
"which model is best **given what else I need loaded**."

| Combination | NPU | Verdict |
|---|---|---|
| `Qwen3.6-35B-A3B` (55%) + `Qwen3-Embedding-0.6B` (2%) + `Qwen3-Reranker-0.6B` (2%) | 59% | Fits. A full local RAG stack with the flagship chat model. |
| `Qwen3.6-35B-A3B` (55%) + `Qwen3-ASR-1.7B` (7%) + `Qwen3-TTS-12Hz-1.7B-VoiceDesign` (5%) | 67% | Fits. Chat plus a full voice round-trip. |
| `Qwen3.6-35B-A3B` (55%) + `Z-Image-Turbo` (26%) | 81% | Fits, tight. |
| `Qwen3.6-35B-A3B` (55%) + `Qwen-Image-2.1` (58%) | 113% | **Impossible.** One of them must go. |
| `gpt-oss-120b` alone | 100% | Fits, but leaves nothing for anything else. |
| `Qwen3-Coder-Next` alone | 94% | Fits, but nearly the whole device. |

Two models dominate the catalogue by footprint: `gpt-oss-120b` (100%) and
`Qwen3-Coder-Next` (94%). Both are powerful and both are effectively
single-occupant. Everything below 60% can be combined.

---

## Chat with vision (15 models)

Multimodal — text and image in, text out. This is the category the device
recommends hardest: `Qwen3.6-35B-A3B` is rank #1, `gemma-4-26B-A4B-it` is
rank #2, `Qwen3.8-27B` is rank #3.

### The four serious general-purpose picks

**`Qwen/Qwen3.6-35B-A3B` — 55% NPU, 128K, rank #1**
The device's own top recommendation and the flagship. MoE: 3B active of 35B.
Built for *repository-level* work — tool calling, multi-step code execution,
and reading screenshots, UI mockups, and diagrams alongside code. Its
distinguishing feature is **thinking preservation**: it retains reasoning
traces across turns instead of re-deriving them, which cuts token burn in
iterative loops and keeps long agent sessions consistent. Thinking mode is
toggleable per request.
*Reach for it when:* you are running an agent over a codebase and want it to
stay coherent for a long session. *Cost:* it is a big resident — 55% of NPU.

**`Qwen/Qwen3.8-27B` — 52% NPU, 256K, rank #3**
The most capable dense model in the catalogue, and the only one with **256K
context in the vision tier**. Dense (64 layers, not MoE) with hybrid attention
mixing gated attention and gated DeltaNet blocks, plus a vision encoder for
image and video. Its specialty is **long-horizon agentic execution** —
autonomous planning, browser automation, computer-use, mobile interaction —
and it scores strongly on those specifically. It is also the only vision model
with tunable reasoning depth: `reasoning_effort` of `low`, `medium`, or
`xhigh`, defaulting to `low`.
*Reach for it when:* the task is long, multi-step, and interactive with a
browser or device, and you need the extra context window. *My read:* the
strongest single model here for agentic work, ahead of the rank-1 model.

**`google/gemma-4-31B-it` — 51% NPU, 128K**
The dense Gemma 4 sibling. 30.7B dense, post-trained for chat formatting,
system-prompt adherence, and native structured tool calling. Configurable
thinking mode with a visible reasoning trace. Pretrained on 140+ languages
with robust instruction-following in 35+.
*Reach for it when:* you want the best general-purpose quality of the dense
Gemma 4 checkpoints and your prompts are not Qwen-shaped.

**`google/gemma-4-26B-A4B-it` — 78% NPU, 128K, rank #2**
MoE: 25.2B total, 3.8B active, routing each token to 8 of 128 experts plus one
always-active shared expert. Per-token compute near a 4B model. The device
ranks it #2 — but at 78% NPU it is a strange recommendation, because it is
nearly half again the footprint of the 31B dense model it is meant to be
cheaper than. See [the note on this below](#the-gemma-4-26b-ranking-anomaly).
*Reach for it when:* you want Gemma 4 quality at 4B-class speed, and you have
the NPU budget to spare.

### The coding specialists

**`deepreinforce-ai/Ornith-1.0-35B` — 50% NPU, 128K**
Post-trained on a Qwen 3.5 MoE base via RL, targeting **terminal-based
agentic coding**: multi-file editing, repository navigation, shell command
execution. Advertised for Kilocode-Tiiny and opencode specifically.
*Reach for it when:* the work is in the terminal, not the chat window.

**`ornith-ai/Ornith-1.5-35B-A3B-Turbo` — 54% NPU, 128K**
Ornith 1.5 is the self-improving generation: RL jointly optimises *task
generation*, *scaffold construction*, and *solution rollouts* — the model
proposes its own curriculum rather than following a human-curated one. Built
on Qwen3.5 and Gemma 4 with continued pretraining, mid-training, and
post-training. Emits OpenAI-compatible function calls, and returns its chain
of thought in `<think>` blocks via a `reasoning_content` field.
*Reach for it when:* you want a coding model that is also its own teacher.

**`trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo` — 56% NPU, 128K**
An **abliterated** community fine-tune of Qwen3.8-27B: the base model's refusal
behaviour is surgically removed rather than new capability being added. It
keeps the same 27B dense architecture, image understanding, and long context,
but its safety guardrails are deliberately stripped.
*Reach for it when:* you specifically need an uncensored model and understand
what that means. *My read:* treat this as a research tool, not a default. It
is also a good argument for the *unmodified* Qwen3.8-27B at the same price.

### The long-horizon research pick

**`endless-frontier/BigBang-v1-Turbo` — 54% NPU, 128K**
Evolved from Qwen3.6-35B-A3B by post-training. Built around a tool-calling
loop combining web search, webpage reading, and sandboxed code execution,
aimed at literature research, coding, and open-ended scientific problem
solving. Its training is unusual and worth knowing about: one model proposes
increasingly difficult frontier-level problems while a second critiques them
for correctness, difficulty, and diversity — producing a small, unusually hard
post-training set with objectively verifiable answers.
*Reach for it when:* the task is research-shaped and benefits from
self-verified hard problems. It is the closest thing in the catalogue to a
"scientist" model.

### The Qwen 3.5 tier — the fast small ones

**`Qwen/Qwen3.5-9B` / `Qwen/Qwen3.5-9B-Turbo` — 29% / 28% NPU, 128K**
Multimodal reasoning in 9B. Chat, analysis, and vision-language in one small
model. 201 languages. Thinking mode on by default. These are the value picks —
at 28–29% NPU you can run one *and* a 55% flagship and still have room.
Advertised specifically for "analyze images, screenshots, and documents
alongside text."

**`Qwen/Qwen3.5-35B-A3B` — 45% NPU, 128K**
The 3.5-generation counterpart to the 3.6 flagship: MoE with 3B active of 35B,
accepting text, images, **and video** as input, 201 languages, thinking by
default. 45% NPU is 10 points cheaper than the 3.6 model.
*Reach for it when:* you need video input or maximum capability per NPU point.

### The dense Qwen 3.6 pair

**`Qwen/Qwen3.6-27B` / `Qwen/Qwen3.6-27B-Turbo` — 48% / 55% NPU, 128K**
Dense 27B with hybrid attention, running all 27B parameters per forward pass.
Deliberately the opposite trade from the MoE siblings: per-token reasoning
depth over throughput. The device frames this as the choice for "workloads
where per-token reasoning depth matters more than throughput."
*My read:* the interesting pair here. The Turbo variant costs 7 points *more*
NPU than the base for a speed benefit, which is the reverse of every other
Turbo in the catalogue — worth checking against `npu_usage` before assuming
Turbo is always the cheaper resident.

### Not a chat model

**`Qwen/Qwen-Image-2.1-PE-I2I` — 24% NPU, 256K**
A **prompt enhancer** for image editing, filed in the vision-chat category
because it takes images in and text out. It looks at your input images and
rewrites a vague edit request into a precise instruction — spelling out what
to change, what to leave alone, and what aspect ratio to use. It does not
generate images.
*Reach for it when:* your image edits are unreliable because the request was
under-specified.

---

## Chat, text only (11 models)

### Reasoning specialists

**`openai/gpt-oss-120b` — 100% NPU, 128K**
OpenAI's open-weight reasoning model: 117B MoE, 5.1B active. Configurable
reasoning effort at three levels (low/medium/high) per request. Full
chain-of-thought access. Trained on the harmony response format and *only*
works correctly with it.
*Reach for it when:* you want the deepest reasoning available and can give the
device to it entirely. *Caveat:* 100% NPU means nothing else loads alongside.

**`openai/gpt-oss-20b` — 27% NPU, 128K, rank #4**
21B MoE, 3.6B active. The low-latency and local-deployment flavour of the
same series, with the same three reasoning-effort levels (default: medium).
The device singles it out for Kilocode-Tiiny, opencode, and other agents.
*Reach for it when:* you want gpt-oss reasoning at a quarter of the footprint.
**At 27% NPU this is the best capability-per-NPU-point in the catalogue**, and
it is the model I would load first if the goal is "good agent on a small
budget."

**`Qwen/Qwen3-30B-A3B-Thinking` — 58% NPU, 128K**
30.5B MoE, 3.3B active, built for hard problems: mathematics, science, coding,
multi-step logic requiring extended deliberation. Thinking is **not
toggleable** here — it is on and permanent.
*Reach for it when:* the question is genuinely hard and you want deliberation
rather than a fast answer. *Note:* permanent thinking means every call burns
reasoning tokens.

**`Qwen/Qwen3.8-27B`** — see the vision section; it is the multimodal sibling
and the denser, stronger one.

### Coding

**`Qwen/Qwen3-Coder-Next` — 94% NPU, 128K**
80B MoE, 3B active. The most serious coding model here: multi-file edits,
long-horizon debugging, tool use, and **recovery from execution failures**
across real codebases. Throughput on par with a small model while the capacity
supports complex reasoning over large codebases. Advertised for Kilocode-Tiiny
and opencode.
*Reach for it when:* you are doing serious refactoring or debugging and can
dedicate the device. *Caveat:* 94% NPU — effectively solo.

**`Qwen/Qwen3-Coder-30B-A3B-Instruct` / `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` — 55% NPU, 64K**
30B MoE, 3.3B active. Code generation, multi-file editing, agentic coding.
Advertised for "any coding agent in Agent Store." The Turbo trades accuracy
for speed at the same footprint. *Note:* both are **64K context**, half the
128K of most peers — a real constraint for repository-scale work.

**`Qwen/Qwen3-30B-A3B-Instruct` — 55% NPU, 128K**
The general-purpose MoE sibling of the Thinking model, updated in July 2025
for stronger instruction following, reasoning, coding, multilingual coverage,
and long-context understanding. 3.3B active of 30.5B.
*Reach for it when:* you want a flexible generalist at MoE speed.

### General and compact

**`Qwen/Qwen3-8B` — 28% NPU, 128K**
The everyday workhorse. Reasoning, instruction-following, creative writing,
agentic tasks across 100+ languages, with a built-in toggle between thinking
and non-thinking modes in the same model. *Reach for it when:* you want a
capable generalist that leaves NPU free for something else.

**`Qwen/Qwen3-4B-Instruct-2507` — 25% NPU, 128K**
AWQ-quantized 4B dense. The smallest serious model. Fast, cheap, and still
handles instruction following, reasoning, coding, and 128K context.
*Reach for it when:* the device must hold something else important.

**`zai-org/GLM-4.7-Flash` — 57% NPU, 64K**
30B-A3B MoE from Zhipu AI, 3B active. Built for agentic tasks: multi-turn
tool use, web browsing, software engineering workflows. Thinking mode can be
enabled or disabled per request, and tool use works in both modes. Primarily
English and Chinese. MIT licence.
*Reach for it when:* the workflow is tool-heavy and mostly English or Chinese.

**`Qwen/Qwen-Image-2.1-PE-T2I` — 23% NPU, 256K**
The text-to-image counterpart of the enhancer above: expands a one-line image
idea into a full English scene description plus a recommended aspect ratio.
A prompt-writing helper, not a generator.

---

## Image generation and editing (13 models)

This is where the "specialty" idea is most literal. Several of these are
**LoRA adapters** on a base model — same base, different specialisation,
loaded separately.

### The Z-Image family — one base, four specialisations

**`Tongyi-MAI/Z-Image-Turbo` — 26% NPU — the base and the default**
6B text-to-image from Alibaba's Tongyi-MAI lab. Photorealistic, strong prompt
adherence, accurate text rendering. **8 diffusion steps**, guidance 0.0, up to
1536×1536. Earlier measurements on a Tiiny call it the default and record
its measured speed: ~9s at 512px, ~55s at 1024px.
*Reach for it when:* you want one image model that handles most things well.
*From testing on a Tiiny:* it accepts 1024×1024, 1280×768, 1152×768,
1024×768, 512×512, and **rejects** 1536×1024, 1024×1536, and 1792×1024. The
Hermes `image_generate` tool's "landscape" and "portrait" presets both fail
on this model — use "square" or pass an explicit size.

**`TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` — 26% NPU — realistic people**
The specialist for photoreal people: skin, hair, fabric. Same 8 steps, same
size, same NPU as the base.
⚠️ **The device's description for this model is wrong.** It carries the
CharacterDesignSheet description verbatim — a copy-paste error in TiinyOS's
catalogue. The two models are different adapters with different jobs. Trust
the name and the community description, not the device's `desc` field here.
This is the clearest evidence in the catalogue that **the device metadata
cannot be taken at face value**, and it is worth reporting to Tiiny.

**`Tongyi-MAI/Z-Image-Turbo-Children-Drawing` — 26% NPU — crayon/marker style**
A LoRA that converts any prompt into a child's crayon or marker drawing. No
trigger word needed — the style applies automatically regardless of prompt
content, so it drops into any existing prompt unmodified.
*Reach for it when:* you want a deliberate, unmistakable stylistic shift. This
is the "anime vs realistic" axis in the catalogue, and it is the only one
where the style is guaranteed to apply.

**`YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` — 26% NPU — character reference**
Multi-view character sheets: several perspectives, facial expression variants,
and a colour palette swatch in a single image. For concept artists, game
character designers, and illustrators who need a structured reference rather
than a standalone illustration.

### The FLUX.2 family — one base, four editing adapters

**`black-forest-labs/FLUX.2-klein-4B` — 26% NPU — the base**
4B rectified flow transformer, Apache 2.0, runs on consumer GPUs with as
little as 13GB VRAM. Unifies text-to-image, image-to-image, and
multi-reference editing in one model. **4 diffusion steps** — the fastest
generating model in the catalogue, sub-second end-to-end on the device's own
terms. Also the only non-Z-Image generator with multi-reference support.
*Reach for it when:* speed matters, or you need multi-reference composition.

**`fal/FLUX.2-klein-4B-Background-Remove` — subject isolation**
Cuts the main subject out of a photo, for product photography and compositing
without manual masking. This is the adapter earlier testing on a Tiiny
already uses for cutting a subject out of an existing photo.

**`fal/FLUX.2-klein-4B-Object-Remove` — unwanted-object removal and inpainting**
Removes marked objects and fills the area with contextually appropriate
content. Product shots, real estate, social media cleanup.

**`fal/FLUX.2-klein-4B-Outpaint` — border extension**
Extends an image past its original borders, matching the scene. Photo
expansion, background generation, aspect-ratio conversion.

**`fal/FLUX.2-klein-4B-Zoom` — detail regeneration**
Zooms into a marked region and regenerates it enlarged *with added detail*,
rather than cropping and stretching. Not an upscaler — it re-imagines the
region.

*Note on the four editing adapters:* each does one job, in the same
sub-second pass, on the same 4B base. Load the adapter you need rather than
the base; the base does not do removal.

### The other generators

**`Qwen/Qwen-Image-2.1` — 58% NPU, 40 steps — unified creation and editing**
The only model in the catalogue that does both with the same weights, and the
only one that outputs **native transparent (RGBA) images** — stickers, logos,
and product cutouts come out ready to place on any design, with no separate
background-removal step. Supports up to 10 reference images, local edits via
circles/painted annotations/masks, and identity preservation for people and
products. Mixed-granularity attention with prefix KV cache reuse.
*Reach for it when:* transparency matters, or you need many reference images.
*Cost:* 58% NPU and 40 steps — the most expensive image model here. It
cannot coexist with the flagship chat model.

**`baidu/ERNIE-Image-Turbo` — 27% NPU, 8 steps — text and layout**
Built for cases where **text legibility and structured layout** matter as much
as visual quality: posters, infographics, comics, multi-panel compositions.
Distilled from full ERNIE-Image via distribution matching and RL. 8 steps,
guidance 0.0, up to 1536×1536.
*Reach for it when:* you need words in the image to be readable and the layout
to be composed. This is the "typography" specialist.

**`HiDream-ai/HiDream-O1-Image-Dev` — 30% NPU, 28 steps — maximum fidelity**
The vault's own testing calls this the fidelity leader: fur, foliage,
reflections, up to 2048×2048 and beyond. 28 steps at guidance 0.0 versus 50
for the full HiDream-O1-Image, and it skips separate VAE and text-encoder
stages entirely. Supports text-to-image, instruction-based editing, and
subject-driven personalization. Resolutions must be multiples of 32 with
(w/32)×(h/32) ≤ 4096.
*Reach for it when:* the image has to survive scrutiny — textures, hair,
reflections. Slower, but the quality ceiling here.

**`SenseTime/SenseNova-U1.5-8B-MoT` — 48% NPU, 30 steps — unified multimodal**
SenseTime's Mixture-of-Transformers design generates directly in pixel space
rather than through a separate VAE decoder, and keeps attention shared across
text and image tokens while splitting feed-forward and normalisation layers
between them — which avoids the gradient conflicts that usually limit a
single unified model. Legible on-image text, high-fidelity visual creation,
and instruction-based editing. 2048×2048 recommended, a long list of
supported ratios, same (w/32)×(h/32) ≤ 4096 rule.
*Reach for it when:* you need both text legibility and fine visual detail in
one model, and can spare 48% NPU.

---

## Reading text in images — OCR (4 models)

**`zai-org/GLM-OCR` — 4% NPU, 64K — the one to reach for**
0.9B, and the only OCR model here that is a language model rather than a
detector-and-recogniser pair. Two distinct jobs: raw content extraction
(text, formulas, tables) and **structured extraction where the output conforms
to a user-defined JSON schema**. Handles real business documents — scanned
pages with seals, code blocks, dense tables. Formula and table recognition are
its edge over the Paddle models.
*Reach for it when:* you need the output as structured data, or you need
formulas and tables, not just words.

**`PaddlePaddle/PP-OCRv6-Small` — 0% NPU — 2.48M parameters**
The mid-tier recognition model. Note the device contradicts itself on its size:
the `params` field says 2.48M, the model's own description says 5.2M
parameters. 50 languages, 16 scenario categories including handwritten,
ancient, Japanese, industrial, and card text. Shares the LCNetV4 backbone and
EncoderWithLightSVTR recognition neck with the medium tier — scaled down, not
architecturally redesigned.
*Reach for it when:* you are OCRing hundreds of images and the NPU cost
matters. **0% NPU means it effectively coexists with anything.**

**`PaddlePaddle/PP-OCRv6-Medium` — 1% NPU — the accuracy tier**
Same architecture, same 50 languages, same 16 categories, with the extra
capacity concentrated on the hardest categories: **handwritten text, Japanese
script, and artistic text**.
*Reach for it when:* the input is handwriting or Japanese and PP-OCRv6-Small
is not reading it. *My read:* Small is the default; Medium only when you have
evidence Small is failing.

**`PaddlePaddle/PP-DocLayoutV3` — 20% NPU — document structure, not text**
Detects and *orders* the structural elements of a page from an image:
non-rectangular multi-point bounding boxes plus logical reading order in a
single forward pass, replacing the detect-then-reorder two-stage approach of
earlier versions. ~33M parameters. Built for messy real input — skewed scans,
curved book photos, screen captures, not just clean flat PDFs.
*Reach for it when:* you are building a document parsing pipeline and need
layout and reading order before you OCR. Note this one is 20% NPU for what is
a small model — the catalogue's NPU figure is not a reliable cost proxy
across architectures.

---

## Speech to text (6 models)

**`Qwen/Qwen3-ASR-1.7B` — 7% NPU, rank #6 — the generalist**
30 languages with automatic language detection. Built on the Qwen3-Omni audio
foundation. Its stated edge is the cases other ASR models struggle with:
**complex acoustic environments, singing voices, and songs with background
music** alongside standard speech. This is the model the device ranks.
*Reach for it when:* the audio is not clean speech.

**`FunAudioLLM/Fun-ASR-Nano` — 7% NPU — depth over breadth**
800M end-to-end, built on a Qwen3-0.6B backbone. English, Chinese, and
Japanese — but Chinese coverage extends to **7 dialect groups** (Wu, Cantonese,
Min, Hakka, Gan, Xiang, Jin) and 26 named regional accents. Explicitly
optimised for education and finance verticals, and trained against two named
failure modes: hallucination generation and language confusion.
*Reach for it when:* Chinese dialects, or domain vocabulary in education or
finance.

**`FunAudioLLM/Fun-ASR-MLT-Nano` — 6% NPU — breadth over depth**
31 languages including Cantonese, Japanese, Korean, Vietnamese, Indonesian,
Thai, Malay, Filipino, Arabic, and Hindi, plus 19 European languages. Trained
on hundreds of thousands of hours (versus tens of millions for the non-MLT
version) — it trades dialect granularity for language breadth. Supports
**free language switching mid-stream** without pre-labelling the input
language, and hotword injection at runtime.
*Reach for it when:* the language is not known in advance, or it changes
mid-recording. Hotword injection is the feature to know about for technical
vocabulary.

**`nvidia/Parakeet-TDT-0.6B-V3` — 5% NPU — European languages and timestamps**
25 European languages with automatic language detection. FastConformer encoder
with a TDT decoder that predicts how many audio frames to skip alongside each
token — faster than a standard transducer with no external language model.
Outputs punctuated, capitalised text directly. Word-level, segment-level,
**and character-level** timestamps. Single-pass long-form.
*Reach for it when:* you need to align captions or search inside a recording,
and the language is European.

**`OpenMOSS-Team/MOSS-Transcribe-Diarize` — 6% NPU — who said what**
The diarization specialist. Converts long multi-speaker recordings into
structured transcripts with timestamps **and speaker labels in a single pass**,
jointly, without a separate diarization pipeline. Whisper-Medium audio encoder
plus a Qwen3-0.6B-style causal decoder, 16kHz in 30-second chunks. Output
format is `[start_time][Sxx]text[end_time]`. Promptable — custom transcription
instructions and hotword injection via prompt prefix. English and Chinese.
*Reach for it when:* meetings, calls, podcasts, interviews. This is the one
that separates voices, and it is required by Tiiny Meeting in Agent Store.

**`openai/Whisper-large-v3-turbo` — 5% NPU — the most languages, and translation**
99 languages, and it can **translate non-English speech directly into English
text**. Whisper large-v3 with the decoder trimmed from 32 layers to 4 —
substantially faster with a minor accuracy drop.
*Reach for it when:* you need English output from non-English audio, or the
language is outside every other model's list. The translation capability is
unique in this catalogue.

---

## Text to speech (4 models)

**`Qwen/Qwen3-TTS-12Hz-1.7B-Base` — 5% NPU — voice cloning**
Clones any voice from a **3-second** audio sample, across 10 languages
(English, Chinese, Japanese, Korean, German, French, Russian, Portuguese,
Spanish, Italian). Dual-track language model architecture, trained on over 5
million hours of multilingual speech.
*The API contract matters:* the raw endpoint requires **both** `ref_audio` and
`ref_text`, and the OpenAI-style `voice: "alloy"` parameter does not work —
you get `"custom_voice is not supported by this model"`. Send a 3+ second
reference clip *and* its transcript.

**`Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` — 5% NPU — describe the voice**
Generates speech from text plus a **natural-language description of the voice
you want** — timbre, emotion, speaking style in plain words. No preset list, no
reference audio. Discrete multi-codebook language model with a 12Hz speech
tokenizer, same 10 languages.
*Reach for it when:* you want a specific character or mood and do not have a
sample to clone.

**`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` — 7% NPU — presets**
9 predefined speaker profiles, each with distinct gender, age, and language
characteristics, and natural-language instructions to adjust emotion and
style *within* those voices. Streaming and batch inference.
*Reach for it when:* you want fast, consistent narration without supplying
audio.

**`Supertone/supertonic-3` — 0% NPU — lightweight and wide**
~99M parameters, **31 languages**, ONNX Runtime, entirely local with no cloud
call. Substantially lighter than comparable open TTS systems.
*Reach for it when:* memory is the constraint, or you need a language none of
the Qwen models cover. **0% NPU** — it coexists with anything.

---

## Music (4 models)

**`tencent/SongGeneration-v2-large` — 28% NPU — full songs with separate stems**
Turns structured lyrics and style prompts into complete songs up to **4
minutes 30 seconds**. English, Chinese, Spanish, Japanese, and more. Hybrid
LLM-Diffusion architecture separates musical structure from audio rendering,
producing **dual-track output where vocals and accompaniment export
independently** — a capability most open models do not have. This is the
model the device wires into Tiiny Music in Agent Store.
*Reach for it when:* you need a full song and want the vocal stem separately.

**`ACE-Step/AceStep-XL-Base` — 40% NPU — the only one that edits audio**
Generates original songs from text, and in its size tier it is the only
variant that also does **source separation, segment stitching, and loop
completion** alongside generation, cover creation, and inpainting. Carries no
SFT or RL on top of pretraining, which preserves higher output diversity than
the SFT and Turbo variants — and makes it the recommended starting point for
LoRA and full fine-tuning.
*Reach for it when:* you want to train on it, or you need the editing tools.

**`ACE-Step/AceStep-XL-Turbo` — 40% NPU — fastest full-song generation**
Distillation-accelerated: full songs in **8 diffusion steps** on a 4B
Diffusion Transformer, trained on legally licensed, royalty-free, and synthetic
MIDI-to-audio data for **commercial use**. Two-stage pipeline — a language
model planner (0.6B–4B) generates lyrics, metadata, and audio codes, then
passes structured conditioning to the DiT synthesizer, giving compositional
control at the planning stage.
*Reach for it when:* you want songs fast and you need commercial licensing
clarity. The planner stage is the interesting part — it is closer to
"writing the song" than "describing a picture of a song."

**`RoyalCities/Foundation-1` — 5% NPU — loops, not songs**
The odd one out, and the most producer-oriented. A **text-to-sample** model
rather than a song generator: tempo-synced, key-locked **loops** with explicit
control over instrument identity, timbral character, FX, and musical phrase
structure. Unlike models that treat sound as a flat descriptor, it separates
these dimensions into **composable prompt layers** — you can specify not just
*what* an instrument is but how it behaves tonally and musically. 5% NPU.
*Reach for it when:* you are making beats and need a loop that locks to tempo
and key, not a finished song. *My read:* the most underrated model in the
catalogue and the one I would be most surprised to see anyone using.

---

## 3D (2 models)

**`microsoft/TRELLIS.2-4B` — 6% NPU — state of the art**
Microsoft Research's large 3D generative model. Single input image →
fully textured 3D mesh with **physically-based rendering materials, including
transparency and translucency**. 6% NPU for a model of this capability.
*Reach for it when:* you need the better mesh.

**`Tencent/Hunyuan3d-2.1` — 22% NPU — production pipeline**
Two-stage image-to-3D for gaming, film, and industrial design. Its defining
addition is a **PBR texture pipeline that simulates light interaction at the
material level** — metallic reflections and subsurface scattering rather than
flat RGB surface colour.
*Reach for it when:* material response matters more than mesh fidelity.

*Community comparison (not verified on this device):* reviewers tend to find
TRELLIS produces fewer polygons and occasional artefacts, while Hunyuan
struggles more with textures — a rough inverse of the device's own framing.
Worth testing both on your own assets before committing.

---

## Embeddings (8 models)

**`Qwen/Qwen3-Embedding-8b` — 18% NPU — the accuracy leader**
Ranks **#1 on the MTEB multilingual leaderboard** (as of the June 2025
leaderboard, score 70.58). 100+ languages, 32K context, embedding dimensions
from 32 to 4096 with user-defined output sizes.
*Reach for it when:* retrieval accuracy is the point.

**`Qwen/Qwen3-Embedding-4b` — 23% NPU — the middle**
The deliberate middle of the series: stronger retrieval than 0.6B, lighter to
run than 8B. *Note:* at 23% NPU it costs **more** than the 8B's 18% while
being smaller. The NPU figures across architectures are not comparable
directly — check the actual byte and dimension costs.

**`Qwen/Qwen3-Embedding-0.6B` — 2% NPU — the default**
The smallest and most hardware-efficient in the series, and the one the
device wires into the Vault for document vectorization. 100+ languages, 32K
input capability. 2% NPU.
*My read:* 1024-dim output at 2% NPU is the right default for a local vault
index. The 8B's benchmark lead does not usually survive the difference in
index size.

**`nvidia/Nemotron-3-Embed-8b-Bf16` — 20% NPU — sliceable dimensions**
Outputs **4096-dimensional embeddings that can be sliced to 2048 or 1024 and
still work well after re-normalization** — so you can trade a little accuracy
for less storage and faster search **without re-encoding anything**. That
property is genuinely useful for an index you have already built.
*Reach for it when:* you have a large existing index and want to shrink it.

**`nvidia/Nemotron-3-Embed-1B-BF16` — 7% NPU — small multilingual**
Distilled from the 8B teacher through two rounds of structured pruning and
knowledge distillation, keeping strong multilingual and cross-lingual
retrieval accuracy at a fraction of the size.

**`Qwen/Qwen3-Vl-Embedding-8b` — 21% NPU — multimodal retrieval**
Text, images, and screenshots into a **single shared space**, so you can
search across mixed media — match a screenshot to a text query, or cluster
text and images together. 16K context. Pairs with the VL reranker.

**`Qwen/Qwen3-Vl-Embedding-2b` — 8% NPU — multimodal on a budget**
The same shared text-image space at 2B, for devices too constrained for the
larger vision-language embedding models. 16K context.

**`tencent/R3-embedding-0.6b` — 4% NPU — agent skill routing, not document search**
The genuinely different one. Built for **agent skill routing** — matching
user queries to the right *combination* of tools or capabilities. Unlike
general embedding models, it was trained on signals about **which skills
should not be retrieved together** for a given query, so it captures skill
compatibility as a *set* rather than scoring each query-skill pair in
isolation.
*Reach for it when:* you are building an agent that selects tools, and
picking two tools that conflict is a real failure mode. *My read:* the most
interesting model in the embeddings category by a wide margin, and nobody
outside the agent-tooling world is going to know it exists.

---

## Rerankers (6 models)

A reranker is the second-stage filter: embeddings retrieve candidates, the
reranker reorders them by true relevance. It is where precision comes from.

**`Qwen/Qwen3-Reranker-8b` — 16% NPU — the text accuracy leader**
Ranks **#1 on the MTEB multilingual leaderboard** in its class. 100+ languages,
custom task instructions so retrieval behaviour can be tuned per scenario
without retraining.

**`Qwen/Qwen3-Reranker-4b` — 10% NPU — the text middle**
The same capability at half the size. The sensible default if 8B is more than
your budget.

**`Qwen/Qwen3-Reranker-0.6B` — 2% NPU — the text floor**
Full Qwen3 reranking quality at 2% NPU. At this size there is little excuse
not to add reranking to a local search stack.

**`Qwen/Qwen3-Vl-Reranker-8b` — 21% NPU — multimodal precision**
Scores query-document pairs across text **and** images. Pairs with
Qwen3-VL-Embedding-8B: the embedding model handles fast initial recall, the
reranker applies precise cross-modal scoring to reorder. 16K context.

**`Qwen/Qwen3-Vl-Reranker-2b` — 8% NPU — multimodal on a budget**
The same two-stage multimodal pipeline at 2B, at a smaller footprint than the
8B reranker.

**`tencent/R3-rerank-0.6b` — 3% NPU — the skill-compatibility second stage**
The reranking half of the R3-Skill two-stage retriever. Scores each
query-skill pair **jointly** rather than independently, which gives more
precise compatibility judgments than the recall stage can — including which
skills should not be combined for a given request. Use it *after*
R3-embedding-0.6B.

---

## What the device recommends, and where it is worth disagreeing

Seven models carry a `recommend_rank`, and 27 of 73 are flagged `is_trend`.

| Rank | Model | NPU |
|---|---|---|
| 1 | `Qwen/Qwen3.6-35B-A3B` | 55% |
| 2 | `google/gemma-4-26B-A4B-it` | 78% |
| 3 | `Qwen/Qwen3.8-27B` | 52% |
| 4 | `openai/gpt-oss-20b` | 27% |
| 5 | `Qwen/Qwen3.6-35B-A3B-Turbo` | 46% |
| 6 | `Qwen/Qwen3-ASR-1.7B` | 7% |
| 6 | `Tongyi-MAI/Z-Image-Turbo` | 26% |

**The gemma-4-26B-A4B ranking anomaly.** Rank #2 costs 78% NPU while the
rank #1 model costs 55%, and the whole point of an A4B MoE is per-token
efficiency. The 26B-A4B is smaller (13.4 GB) than the 31B dense (16.7 GB),
so if the ranking reflects download size or a general "quality per family
member" judgement it is defensible; if it reflects NPU residency it is hard
to explain. Worth raising with Tiiny. It is the single clearest place where
the device's own recommendation does not line up with the device's own
constraint.

**Where I would disagree with the ranking:** `openai/gpt-oss-20b` at 27% NPU
is arguably the best *general* pick in the catalogue on a shared-NPU device
and it is only rank #4. It has three configurable reasoning levels, a
low-latency profile, and fits alongside a 55% flagship with room to spare.

---

## Known problems with the catalogue

Found while reading all 73 records. These are device-side metadata issues, not
model problems.

1. **`TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` carries the wrong
   description** — the CharacterDesignSheet text verbatim. Two different
   adapters, two different jobs, one copy-paste error. Anyone choosing an
   image model from the device's own descriptions will choose wrong here.
2. **`Qwen3.6-27B-Turbo` costs 7 NPU points *more* than the base model** it
   is a speed variant of (55% vs 48%), while every other Turbo in the
   catalogue is equal or cheaper. The `npu_usage` figure may be measuring
   something other than residency.
3. **`PP-OCRv6-Small` reports 2.48M parameters** in the `params` field while
   its own description says 5.2M — the device contradicts itself about the
   same model's size.
4. **`PP-DocLayoutV3` costs 20% NPU** — a third of the flagship chat model —
   for a ~33M-parameter layout detector, while PP-OCRv6-Medium costs 1% for
   22M parameters. NPU cost is not proportional to model size across
   architectures, and the catalogue gives no way to predict it.
5. **The `params` field for `Qwen/Qwen-Image-2.1-PE-T2I` and `-PE-I2I` is
   7B**, but both are 7B *prompt enhancers*, not the 7B image model. Same
   base lineage, different role — worth keeping straight.
6. **Twenty-three models have no app mapping at all** — no "Use it in..."
   text. The catalogue describes them in detail but never says where TiinyOS
   uses them.

---

## How the 73 break down

| Category | Count | The single best pick |
|---|---|---|
| Chat with vision | 15 | `Qwen3.8-27B` — longest horizon, 256K, tunable reasoning |
| Chat, text only | 11 | `gpt-oss-20b` — 27% NPU, three reasoning levels |
| Image creation and editing | 13 | `HiDream-O1-Image-Dev` for fidelity, `Qwen-Image-2.1` for transparency |
| Embeddings | 8 | `Qwen3-Embedding-0.6B` at 2% NPU for most local indexes |
| Rerankers | 6 | `Qwen3-Reranker-0.6B` at 2% NPU — no reason to skip reranking |
| Speech to text | 6 | `Qwen3-ASR-1.7B` for hard audio, `MOSS-Transcribe-Diarize` for speakers |
| Text to speech | 4 | `Qwen3-TTS-12Hz-1.7B-VoiceDesign` — describe the voice, no sample needed |
| Music | 4 | `SongGeneration-v2-large` — 4:30 songs with separate vocal stems |
| OCR | 4 | `GLM-OCR` for formulas, tables, and JSON-schema output |
| 3D | 2 | `TRELLIS.2-4B` at 6% NPU |

---

## Method and provenance

**What I read.** All 73 records from `GET /api/v1/models/online_models` on
2026-10-27 — the device's own catalogue, including the full `desc` field that
Zolon's table does not carry. This is the same endpoint Zolon's
`tools/model_list.py` uses, and his file is byte-identical to the attachment.

**What I verified.** His table against the live catalogue: **0 discrepancies**
in NPU share, download size, and context window across all 73 models.

**What I added.** The device's own one-to-three paragraph description per
model (its `desc` field), the `capabilities`, `steps`, `guidance_scale`,
`image_size`, `thinking`/`reasoning_levels`, `is_trend`, `recommend_rank`,
and `downloads` fields, and the "Use it in..." app mapping — none of which
appear in the inventory table.

**What I researched externally.** Provider model cards and documentation for
Qwen3-Embedding-8B (MTEB #1, score 70.58), gemma-4 (five sizes, 140+
languages, 256K context on medium models, Apache 2.0), Qwen3.8-27B (dense 64
layers, hybrid gated-attention and gated-DeltaNet, `reasoning_effort`,
`preserve_thinking`), Qwen-Image-2.1 (32 single-stream DiT layers, native
RGBA, up to 10 reference images), FLUX.2 klein 4B (Apache 2.0, 13GB VRAM,
sub-second), Z-Image-Turbo (6B, single-stream diffusion transformer), and
gpt-oss (harmony format required, 117B/5.1B and 21B/3.6B).

**What I did not do.** I did not run or benchmark any of the 73 models on this
device. Every performance statement is either the publisher's own claim, the
device catalogue's text, or my reading of them — never an independent
measurement. I did not change any device state; the catalogue endpoint is
read-only.

**Reproducing the facts.** Everything in the "how the specialties work" and
"how the 73 break down" tables comes from one endpoint, and it is read-only:
`GET /api/v1/models/online_models` on your own device, with your own API key.
The community tool `tools/model_list.py` in
[thezolon/tiiny-api-notes](https://github.com/thezolon/tiiny-api-notes) reads
the same endpoint and regenerates the inventory table; the `desc` field it
omits is where the specialisations come from. Nothing in the catalogue
changes device state — no model is loaded, and no file is written.

**Open question worth Zolon's attention.** The `desc` copy-paste on
`Z-Image-Turbo-Creating-Realistic` is a device-catalogue bug, not a model
bug. If Tiiny's catalogue is generated from a static metadata file, the fix is
upstream; if it is hand-authored, someone should report it. Either way it is
the kind of thing his `api_snapshot.py` would catch on the next update.

---

## Related

- [`api-call-logging.md`](./api-call-logging.md) — where API calls
  go and why you cannot see them
- [`README.md`](./README.md) —
  every documentation surface the device ships with

---

Corrections and additions welcome — open an issue on this repository, or post
them in the Discord channel. Either way they will fold into the next
revision.  -@Antattack and Friendlybot
