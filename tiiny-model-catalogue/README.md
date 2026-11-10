---
title: Tiiny Model Store — Complete Catalogue with Measured Capabilities
type: reference
status: draft — for review before GitHub publication
updated: 2026-11-10
source: GET /api/v1/models/online_models on live Tiiny (92 models) + app/data/overlay.yaml measurements 2026-11-07
audience: Gary Garcia (reviewer), then public via AI_Articles/tiiny-image-agency
---

# Tiiny Model Store — Complete Catalogue with Measured Capabilities

> **Snapshot, not a live feed.** This document was built from your own device on **2026-11-10** — 92 models via `GET /api/v1/models/online_models` (NPU, context, `thinking`, `desc`, all live columns) plus the agency's measured overlay for the 15 image generators + 2 prompt enhancers (image-input, alpha, text-rendering, specialty — all `provenance: d,m` from `app/data/overlay.yaml`).
> Between this read and the moment you publish, TiinyOS can add, drop, or move a model. **Your device is the authority; this doc is dated evidence.** Re-run `curl -H "Authorization: Bearer $TIINY_API_KEY" http://tiinyhost.local/api/v1/models/online_models | python3 -m json.tool` to re-verify.

## What this document adds to the device's own descriptions

- **Every one of the 92 models is here with its full `desc` verbatim** — not just the chat and image models, but TTS, ASR, OCR, embeddings, rerankers, music, 3D, video. The description is what the publisher claims; the columns beside it are what the device reports and what we measured.
- **NPU share, context window, params, `is_trend`, `recommend_rank` — live values from 2026-11-10**, with notes where they have moved between reads (e.g. `Qwen3.6-35B-A3B` was 55% on 2026-10-27, 47% now; `gemma-4-26B-A4B-it` 78% → 37%).
- **Thinking capability as the device reports it today** (`thinking.supported`, `toggleable`, `levels`, `enabled_by_default`, `default_level`) — not inferred from the prose. Highlighted where the prose hides it.
- **Measured image capabilities** (`image_input: yes/no/unknown`, `alpha`, `text_rendering`, `artifact/style/speed/quality`) from the 2026-11-07 research probes (control vs. image, 5× judge, pixel transparency). Those are `d,m` provenance — device + measurement — and they override any assumption in the prose.

## Key finding: thinking that wasn't advertised (and thinking that was mis-advertised)

22 of 92 models report `thinking.supported: true` on the live device. 21 of those advertise it in their `desc` ("Thinking Mode", "reasoning", "chain-of-thought", "reasoning_levels"). One does not — and the device's own flags are unreliable in three deeper ways we learned building the Tiiny Model Router.

### 1 — One model reasons silently

| Model | Device says | Desc says | Why it matters |
|---|---|---|---|
| **`trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo`** — 56% NPU, 131K, dense 27B, `levels: [low, medium, xhigh]` | `supported: true, toggleable: true, enabled_by_default: true` | **No mention of "thinking" or "reasoning" anywhere in `desc`** — the desc only says the refusal behaviour is "surgically removed" | The model *is* the thinking-capable Qwen3.8-27B base (same 52% base now reads 56% here), so with no prose cue you would route it as a plain chat model and burn thinking tokens silently. **Marked 🔴 HIDDEN THINKING in the tables and cards below.** |

This is the only `supported:true` model whose `desc` omits the word. Every other thinking model advertises it — which is how this one was missed until the router read `thinking` at route time instead of reading the prose.

### 2 — The toggle flag is a hint, not ground truth

> From `tiiny-model-routing/SKILL.md#Thinking mode` and `projects/MrPeabody/memory.md#The reasoning-model trap`: *"One model is flagged by the device as having no switch and honours it perfectly well. The flag is a hint, not ground truth."*

The router therefore **always sends `enable_thinking: false` when it can**, and lets the label report what actually took effect (`[think:off]` vs `[think:off→low]`). Do not maintain a hand table of this — read `thinking` at route time.

### 3 — Switch vs. levels vs. neither

| Device reports | What `thinking: off` / `on` actually does | Examples |
|---|---|---|
| `toggleable: true, levels: []` — pure switch | Sends `enable_thinking: false/true`. Trace stops dead. | `Qwen/Qwen3.6-35B-A3B`, `Qwen3.5-9B`, `gemma-4-26B-A4B-it` |
| `toggleable: true, levels: [low/medium/xhigh]` — switch + levels | Switch wins; levels are the depth when on. | `Qwen/Qwen3.8-27B` (low/medium/xhigh), `Qwen3.6-35B-A3B-Turbo` (low) |
| `toggleable: false, levels: [low/medium/high]` — **levels only** | No off switch exists. `off` → cheapest level (`low`), `on` → most expensive (`high`). Label says `[think:off→low]` so you know. | `openai/gpt-oss-20b`, `openai/gpt-oss-120b` |
| `toggleable: false, levels: []` — reasoning without a knob | `supported:true` but neither switch nor levels. Trace is always on. `off` is best-effort. | `Qwen/Qwen3-30B-A3B-Thinking`, `Ornith-1.0-35B`, `Ornith-1.5-35B-Turbo`, `Sage-A1.5-Turbo` and its abliterated twin |

### 4 — Thinking without budget = empty 200 (the meter bug's cousin)

A reasoning model spends its `max_tokens` on the trace first. With a small budget the trace eats it all and the device returns **HTTP 200 with an empty answer** — which the old critic read as "no critique" and the old meter read as "nothing resident." Router floor is **4096 tokens** (`thinking_max_tokens`, raise it if you raise `max_tokens`) and it sends `chat_template_kwargs: {"enable_thinking": False}` for the judge so the verdict actually arrives (memory.md measured: `thinking ON, 2500` → sometimes nothing, `thinking ON, 8000` → 502, `thinking OFF, 8000` → 200 with verdict).

---

## How to read the tables

- **🔴 HIDDEN** — `thinking.supported:true` but `desc` never says "thinking" / "reasoning". Route it as a reasoning model or you will pay for a trace you didn't ask for.
- **🟡 LEVELS ONLY** — `toggleable:false` with `levels: [...]`. `thinking: off` cannot turn it off; it goes to `low`.
- **🟡 ALWAYS ON** — `supported:true` with no switch and no levels. Reasoning is permanent.
- **NPU / Ctx / Status** — live from the device at read time. "running" = resident now, "downloaded" = on disk, "not_downloaded" = needs `tiiny download`.
- **Image notes** — for the 15 generators + 2 enhancers, the `overlay.yaml` specialty (measured `image_input`, `alpha`, `text_rendering`, etc.). "MEASURED 2026-11-07: …" is literal probe output.

## Chat with vision — 17 models — `type: Image-Text-to-Text`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 | downloaded | always-on default=off | 🟡 ALWAYS ON | Ornith-1.0-35B is a coding-specialized reasoning model … |
| `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 | downloaded | switch default=on | — | BigBang-v1-Turbo is an agentic model built for long-hor… |
| `google/gemma-4-26B-A4B-it` | 37% | 131072 | downloaded | switch default=on | — | rank #2 |
| `google/gemma-4-31B-it` | 53% | 131072 | not_downloaded | switch default=on | — | Gemma 4 31B-IT is Google DeepMind's instruction-tuned v… |
| `huihui-ai/Huihui-Ornith-1.5-35B-A3B-abliterated-Turbo` | 48% | 262144 | not_downloaded | always-on default=off | 🟡 ALWAYS ON | Huihui-Ornith-1.5-35B-A3B-abliterated is an uncensored … |
| `InternScience/Sage-A1.5-Turbo` | 48% | 262144 | downloaded | always-on default=off | 🟡 ALWAYS ON | Sage-A1.5 is an agentic research model from Shanghai AI… |
| `ornith-ai/Ornith-1.5-35B-A3B-Turbo` | 54% | 262144 | downloaded | always-on default=off | 🟡 ALWAYS ON | Ornith-1.5-35B-A3B-Turbo is a mixture-of-experts model … |
| `Qwen/Qwen-Image-2.1-PE-I2I` | 24% | 262144 | not_downloaded | — | — | `image_input:` · alpha:False · text:n/a · fast/n/a |
| `Qwen/Qwen3.5-35B-A3B` | 45% | 131072 | not_downloaded | switch default=on | — | Qwen3.5-35B-A3B is a multimodal MoE model that accepts … |
| `Qwen/Qwen3.5-9B` | 29% | 131072 | downloaded | switch default=on | — | Qwen3.5-9B is a multimodal reasoning model that accepts… |
| `Qwen/Qwen3.5-9B-Turbo` | 28% | 131072 | not_downloaded | switch default=on | — | Qwen3.5-9B-Turbo is a multimodal reasoning model that a… |
| `Qwen/Qwen3.6-27B` | 48% | 131072 | not_downloaded | switch default=on | — | Qwen3.6-27B is a 27B dense multimodal model that handle… |
| `Qwen/Qwen3.6-27B-Turbo` | 55% | 131072 | not_downloaded | switch default=on | — | Qwen3.6-27B-Turbo is a 27B dense multimodal model that … |
| `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | running | switch default=on | — | rank #1 |
| `Qwen/Qwen3.6-35B-A3B-Turbo` | 46% | 262144 | downloaded | switch+low default=low | — | rank #5 |
| `Qwen/Qwen3.8-27B` | 52% | 262144 | downloaded | switch+low,medium,xhigh default=low | — | rank #3 |
| `trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo` | 56% | 131072 | downloaded | switch+low,medium,xhigh default=low | 🔴 HIDDEN | Qwen3.8-27B-heretic-ara is an abliterated variant of Qw… |

## Image generation & editing — 15 models — `type: Text-to-Image`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `abenzerps/Qwen-Image-2.1-Uncensored-Quantized` | 0% | — | downloaded | — | — | `image_input:no` · alpha:True · text:strong · slow/highest |
| `baidu/ERNIE-Image-Turbo` | 27% | — | downloaded | — | — | `image_input:no` · alpha:False · text:best · fast/high |
| `black-forest-labs/FLUX.2-klein-4B` | 19% | — | downloaded | — | — | `image_input:no` · alpha:False · text:weak · fastest/medium |
| `fal/FLUX.2-klein-4B-Background-Remove` | 19% | — | downloaded | — | — | `image_input:no` · alpha:False · text:n/a · fastest/n/a |
| `fal/FLUX.2-klein-4B-Object-Remove` | 19% | — | downloaded | — | — | `image_input:yes` · alpha:False · text:n/a · fastest/n/a |
| `fal/FLUX.2-klein-4B-Outpaint` | 20% | — | downloaded | — | — | `image_input:unknown` · alpha:False · text:n/a · fastest/n/a |
| `fal/FLUX.2-klein-4B-Zoom` | 20% | — | downloaded | — | — | `image_input:no` · alpha:False · text:n/a · fastest/n/a |
| `HiDream-ai/HiDream-O1-Image-Dev` | 30% | — | downloaded | — | — | `image_input:unknown` · alpha:False · text:weak · fast/highest |
| `krea/Krea-2-Turbo` | 36% | — | downloaded | — | — | `image_input:no` · alpha:False · text:unknown · fast/unknown |
| `Qwen/Qwen-Image-2.1` | 62% | — | downloaded | — | — | `image_input:yes` · alpha:True · text:strong · slow/highest |
| `SenseTime/SenseNova-U1.5-8B-MoT` | 48% | — | downloaded | — | — | `image_input:yes` · alpha:False · text:strong · slow/high |
| `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` | 23% | — | downloaded | — | — | `image_input:no` · alpha:False · text:weak · fast/high · ⚠️ desc copy-paste bug |
| `Tongyi-MAI/Z-Image-Turbo` | 23% | — | downloaded | — | — | `image_input:no` · alpha:False · text:strong · fast/high |
| `Tongyi-MAI/Z-Image-Turbo-Children-Drawing` | 23% | — | downloaded | — | — | `image_input:no` · alpha:False · text:weak · fast/medium |
| `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` | 23% | — | downloaded | — | — | `image_input:no` · alpha:False · text:weak · fast/high |

## Text to speech — 10 models — `type: Text-to-Speech`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `hexgrad/Kokoro-82M` | 0% | — | not_downloaded | — | — | Kokoro-82M is a compact open-weight text-to-speech mode… |
| `k2-fsa/OmniVoice` | 2% | — | not_downloaded | — | — | OmniVoice is a massively multilingual zero-shot text-to… |
| `microsoft/VibeVoice-1.5B` | 8% | — | not_downloaded | — | — | VibeVoice-1.5B is Microsoft's open text-to-speech model… |
| `microsoft/VibeVoice-Realtime-0.5B` | 2% | — | not_downloaded | — | — | VibeVoice-Realtime-0.5B is Microsoft's lightweight real… |
| `openbmb/VoxCPM2` | 7% | — | not_downloaded | — | — | VoxCPM2 is a tokenizer-free, diffusion-autoregressive t… |
| `OpenMOSS-Team/MOSS-TTS-Nano-100M` | 0% | — | not_downloaded | — | — | MOSS-TTS-Nano-100M is a tiny multilingual speech genera… |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | 5% | — | running | — | — | Qwen3-VoiceClone-1.7B is a text-to-speech model that cl… |
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | 7% | — | not_downloaded | — | — | Qwen3-CustomVoice-1.7B is a text-to-speech model that s… |
| `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 5% | — | not_downloaded | — | — | Qwen3-VoiceDesign-1.7B is a text-to-speech model that g… |
| `Supertone/supertonic-3` | 0% | — | running | — | — | Supertonic 3 is a compact on-device text-to-speech mode… |

## 3D — 2 models — `type: Image-to-3D`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `microsoft/TRELLIS.2-4B` | 6% | — | not_downloaded | — | — | TRELLIS.2 is a state-of-the-art large 3D generative mod… |
| `Tencent/Hunyuan3d-2.1` | 22% | — | not_downloaded | — | — | Hunyuan3D-2.1 is a two-stage image-to-3D generation sys… |

## Video — 1 models — `type: Text-to-Video`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `lightx2v/MiniMax-H3-Turbo` | 49% | — | downloaded | — | — | Minimax-h3-Turbo turns a text prompt or a single starti… |

## ASR — 6 models — `type: ASR`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `FunAudioLLM/Fun-ASR-MLT-Nano` | 6% | — | not_downloaded | — | — | Fun-ASR-MLT-Nano is a speech recognition model from Ton… |
| `FunAudioLLM/Fun-ASR-Nano` | 7% | — | not_downloaded | — | — | Fun-ASR-Nano is an end-to-end speech recognition model … |
| `nvidia/Parakeet-TDT-0.6B-V3` | 5% | — | not_downloaded | — | — | Parakeet-TDT-0.6B-V3 is a speech recognition model from… |
| `openai/Whisper-large-v3-turbo` | 5% | — | downloaded | — | — | Whisper large-v3-turbo is a speech recognition model fr… |
| `OpenMOSS-Team/MOSS-Transcribe-Diarize` | 6% | — | downloaded | — | — | MOSS-Transcribe-Diarize is an end-to-end model for conv… |
| `Qwen/Qwen3-ASR-1.7B` | 7% | — | running | — | — | rank #6 |

## Image-to-Text — 4 models — `type: Image-to-Text`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `PaddlePaddle/PP-DocLayoutV3` | 20% | — | downloaded | — | — | PP-DocLayoutV3 detects and orders the structural elemen… |
| `PaddlePaddle/PP-OCRv6-Medium` | 1% | — | downloaded | — | — | PP-OCRv6 Medium Rec is the top-tier recognition model i… |
| `PaddlePaddle/PP-OCRv6-Small` | 0% | — | not_downloaded | — | — | PP-OCRv6 Small Rec is the mid-tier text recognition mod… |
| `zai-org/GLM-OCR` | 4% | 65536 | not_downloaded | — | — | GLM-OCR is a document OCR model from Zhipu AI that extr… |

## Music Generation — 5 models — `type: Music Generation`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `ACE-Step/AceStep-XL-Base` | 40% | — | not_downloaded | — | — | AceStep-XL-Base is a music generation model from ACE St… |
| `ACE-Step/AceStep-XL-Turbo` | 40% | — | not_downloaded | — | — | AceStep-XL-Turbo is a distillation-accelerated music ge… |
| `m-a-p/YuE2-3B` | 14% | — | not_downloaded | — | — | YuE2-3B is a music generation model from Multimodal Art… |
| `RoyalCities/Foundation-1` | 5% | — | downloaded | — | — | Foundation-1 is a text-to-sample model built for music … |
| `tencent/SongGeneration-v2-large` | 28% | — | downloaded | — | — | SongGeneration-v2-large is an open-weight, full-song ge… |

## Text Classification — 7 models — `type: Text Classification`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `PelaAI/KnowLine-35B-A3B-Gen1.5` | 48% | 262144 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `PelaAI/KnowLine-4B-Gen5.5` | 17% | 262144 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `vllm-sr/d3-edge` | 21% | 16384 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `vllm-sr/d3-flash` | 34% | 16384 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `vllm-sr/d3-lite` | 7% | 16384 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `vllm-sr/d3-mini` | 26% | 16384 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |
| `vllm-sr/d3-nano` | 25% | 16384 | not_downloaded | — | — | Please update the service to version 0.1.39 before usin… |

## Text Embedding — 8 models — `type: Text Embedding`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `nvidia/Nemotron-3-Embed-1B-BF16` | 7% | 4096 | not_downloaded | — | — | Nemotron-3-Embed-1B turns text into dense vector embedd… |
| `nvidia/Nemotron-3-Embed-8b-Bf16` | 20% | 4096 | not_downloaded | — | — | Nemotron-3-Embed-8B turns text into dense vector embedd… |
| `Qwen/Qwen3-Embedding-0.6B` | 2% | 8192 | downloaded | — | — | Qwen3-Embedding-0.6B converts text into numerical repre… |
| `Qwen/Qwen3-Embedding-4b` | 23% | 8192 | not_downloaded | — | — | Qwen3-Embedding-4B converts text into numerical represe… |
| `Qwen/Qwen3-Embedding-8b` | 18% | 8192 | not_downloaded | — | — | Qwen3-Embedding-8B converts text into numerical represe… |
| `Qwen/Qwen3-Vl-Embedding-2b` | 8% | 16384 | not_downloaded | — | — | Qwen3-VL-Embedding-2B converts text, images, and screen… |
| `Qwen/Qwen3-Vl-Embedding-8b` | 21% | 16384 | not_downloaded | — | — | Qwen3-VL-Embedding-8B converts text, images, and screen… |
| `tencent/R3-embedding-0.6b` | 4% | 8192 | not_downloaded | — | — | R3-Embedding-0.6B is a retrieval model built specifical… |

## Text Generation — 11 models — `type: Text Generation`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 100% | 131072 | downloaded | levels:low,medium,high default=medium | 🟡 LEVELS ONLY | gpt-oss-120b is OpenAI's open-weight reasoning model, a… |
| `openai/gpt-oss-20b` | 27% | 131072 | running | levels:low,medium,high default=medium | 🟡 LEVELS ONLY | rank #4 |
| `Qwen/Qwen-Image-2.1-PE-T2I` | 23% | 262144 | downloaded | — | — | `image_input:` · alpha:False · text:n/a · fast/n/a |
| `Qwen/Qwen3-30B-A3B-Instruct` | 55% | 131072 | not_downloaded | — | — | A general-purpose MoE language model from Alibaba's Qwe… |
| `Qwen/Qwen3-30B-A3B-Thinking` | 58% | 131072 | not_downloaded | always-on default=on | 🟡 ALWAYS ON | Qwen3-30B-A3B-Thinking-2507 is a mixture-of-experts rea… |
| `Qwen/Qwen3-4B-Instruct-2507` | 25% | 131072 | not_downloaded | — | — | Qwen3-4B-Instruct-2507 is a compact 4B dense language m… |
| `Qwen/Qwen3-8B` | 28% | 131072 | not_downloaded | switch default=on | — | Qwen3-8B is a general-purpose open-weight language mode… |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct` | 55% | 65536 | downloaded | — | — | A coding-specialized model built for developers who nee… |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` | 55% | 65536 | downloaded | — | — | Qwen3-Coder-30B-A3B-Instruct-Turbo is an optimized vari… |
| `Qwen/Qwen3-Coder-Next` | 94% | 131072 | downloaded | — | — | Qwen3-Coder-Next is an 80B MoE model built specifically… |
| `zai-org/GLM-4.7-Flash` | 57% | 65536 | not_downloaded | — | — | GLM-4.7-Flash is a 30B-A3B MoE text generation model fr… |

## Text Reranking — 6 models — `type: Text Reranking`

| Model | NPU | Ctx | Status | Thinking (device) | Flag | Measured / Note |
|---|---|---|---|---|---|---|
| `Qwen/Qwen3-Reranker-0.6B` | 2% | 8192 | not_downloaded | — | — | Qwen3-Reranker-0.6B is a text reranking model that scor… |
| `Qwen/Qwen3-Reranker-4b` | 10% | 8192 | not_downloaded | — | — | Qwen3-Reranker-4B is a text reranking model that scores… |
| `Qwen/Qwen3-Reranker-8b` | 16% | 8192 | not_downloaded | — | — | Qwen3-Reranker-8B is a text reranking model that scores… |
| `Qwen/Qwen3-Vl-Reranker-2b` | 8% | 16384 | downloaded | — | — | Qwen3-VL-Reranker-2B is a multimodal reranking model th… |
| `Qwen/Qwen3-Vl-Reranker-8b` | 21% | 16384 | not_downloaded | — | — | Qwen3-VL-Reranker-8B is a multimodal reranking model th… |
| `tencent/R3-rerank-0.6b` | 3% | 8192 | not_downloaded | — | — |  |

---

## Detailed cards — every model, full `desc` + device columns + measured notes

> Each card is one model. The `desc` block is verbatim from the device — line breaks preserved. "Device columns" are the live fields at read time. "Measured" is only for the 15 generators + 2 enhancers where we ran probes; everything else is `d` (device) provenance only.

### `abenzerps/Qwen-Image-2.1-Uncensored-Quantized`

- **Type:** `Text-to-Image` · **NPU:** 0% · **Context:** None · **Params:** 7B · **Status:** downloaded · **Version:** 20261029 · **Load time:** 0s · **Trending:** False · **Rank:** — · **Downloads:** 443
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 2048x2048 (recommended) · **Steps:** 40 · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen-Image-2.1-Uncensored is an uncensored variant of Qwen-Image-2.1, a 7B diffusion transformer for text-to-image generation and image editing. It keeps the same weights for both creating and revising images, and runs on the intranet with its own packaged runtime.

**Supported image sizes**

* 2048x2048 is the recommended resolution.
* These sizes are also verified to work well: 512x512, 640x480, 480x640, 768x480, 480x768, 736x416, 416x736, 1024x1024, 1280x960, 960x1280, 1536x960, 960x1536, 1536x864, 864x1536, 2400x1792, 1792x2400, 2560x1600, 1600x2560, 2752x1536, 1536x2752.
* Other sizes may also work if width and height are each divisible by 32 and satisfy the formula below:

```text
width % 16 == 0
height % 16 == 0
ceil_to_32((width / 16) * (height / 16)) <= 16896
```

**Transparent Images**

- Generate standard or transparent (RGBA) images from a text prompt
- Edit existing transparent layers while keeping the alpha channel intact
- Extract a subject from a photograph onto a transparent background

For transparent output, state in the prompt that the image has an alpha channel and a transparent background.

**Editing**

- Combine up to 10 reference images in a single request
- Mark the area to change with a drawn circle, painted annotation, or separate mask for local edits
- Keeps the identity of people and products consistent across edits

**Visual Quality**

Improvements over earlier Qwen-Image releases focus on typography, portrait lighting, realistic textures, and fine detail. 

**Architecture**

A 7B diffusion transformer with 32 single-stream layers, paired with a Qwen3-VL text encoder that reads both the prompt and any reference images. Mixed-granularity attention and prefix KV cache reuse reduce the compute cost of each generation.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** flagship-co-resident · **Artifact:** ['icon', 'logo', 'sticker', 'cutout', 'illustration', 'photo', 'comic'] · **Alpha:** True (native-rgba) · **Text rendering:** strong · **Style:** ['general', 'flat', 'illustration'] · **Speed:** slow · **Quality:** highest · **Image input:** `no`
- **Dialect:** Same family as Qwen-Image-2.1. Same dialect guidance applies.
- **Sizes verified:** ['512x512', '1024x1024', '2048x2048', '2560x1600', '2752x1536']
- **Notes:** Community uncensored quant build of Qwen-Image-2.1 with its own packaged runtime. Reports 0% NPU, so it coexists with a resident planner. Treat as a research build: the quantization is community-run, not vendor-supported.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at logo, photo, comic, illustration; handled flat and realistic style; rendered 25.52% transparent pixels; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the judge called the picture with the image a rectangle 0 times out of five and the control 0 times — so the image was not used.

---

### `ACE-Step/AceStep-XL-Base`

- **Type:** `Music Generation` · **NPU:** 40% · **Context:** None · **Params:** 5B · **Status:** not_downloaded · **Version:** 20261021 · **Load time:** 65s · **Trending:** False · **Rank:** — · **Downloads:** 154
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

AceStep-XL-Base is a music generation model from ACE Studio and StepFun that creates original songs from text descriptions, and the only variant in its size tier that also supports audio editing tasks: source separation, segment stitching, and loop completion alongside standard generation, cover creation, and inpainting. It carries no supervised fine-tuning or reinforcement learning on top of pretraining, which preserves higher output diversity than the SFT and Turbo variants and makes it the recommended starting point for LoRA and full fine-tuning workflows.


**Task Coverage**

The Base checkpoint supports all tasks in the v1.5 pipeline: Text2Music, Cover, Repaint, Reference Audio conditioning, Extract, Lego, and Complete. The SFT and Turbo variants drop Extract, Lego, and Complete in exchange for higher audio quality and prompt adherence.

**Architecture**

Two-stage pipeline. An LM planner (Qwen3-based, available in 0.6B, 1.7B, or 4B) converts text prompts into song blueprints via Chain-of-Thought, generating metadata, lyrics, and 5Hz audio codes. The Base DiT (2B parameters, BF16) then synthesizes audio from those codes at 50 steps with CFG enabled. Output is stereo 48kHz audio.

**Quality and Diversity Position**

Rated Medium quality and High diversity in the official model zoo, compared to High quality / Medium diversity for SFT and Very High quality / Medium diversity for Turbo. The diversity advantage comes from the absence of fine-tuning alignment, which narrows the output distribution in exchange for polish.

**Fine-Tuning**

Rated as the easiest checkpoint in the lineup to fine-tune. The absence of SFT and RL layers means downstream fine-tuning does not need to contend with prior alignment objectives.

**License**

MIT.

---

### `ACE-Step/AceStep-XL-Turbo`

- **Type:** `Music Generation` · **NPU:** 40% · **Context:** None · **Params:** 5B · **Status:** not_downloaded · **Version:** 20261021 · **Load time:** 69s · **Trending:** False · **Rank:** — · **Downloads:** 233
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

AceStep-XL-Turbo is a distillation-accelerated music generation model from ACE Studio and StepFun that produces full songs from text prompts in 8 diffusion steps, built on a 4B-parameter Diffusion Transformer architecture trained on legally licensed, royalty-free, and synthetic MIDI-to-audio data for commercial use. Its two-stage pipeline routes a text prompt through a language model planner (0.6B to 4B) that generates lyrics, metadata, and audio codes before passing structured conditioning to the DiT synthesizer, giving it compositional control at the planning stage rather than through classifier-free guidance at inference.


**Architecture**

Two-component pipeline: an LM stage (Qwen3-based, available in 0.6B, 1.7B, or 4B) handles caption-to-composition planning, outputting metadata, lyrics, and 5Hz audio codes. The DiT stage (4B, this model) synthesizes audio from those codes via a Finite Scalar Quantization detokenizer and VAE decoder, producing stereo 48kHz output.

**Inference**

8 steps, no classifier-free guidance (CFG disabled), distilled. This is the fastest variant in the XL lineup. The standard (non-turbo) XL variants run 32 to 50 steps with CFG.

**Editing Capabilities**

Beyond text-to-song generation, the system supports cover generation, inpainting (repainting segments of an existing track), vocal-to-BGM conversion, and loop-to-full-song extension. These are available in the base and SFT variants; the turbo distillation preserves standard generation tasks.

**Language Support**

Prompt adherence across 50+ languages. Lyrics generation and style control are not restricted to English.

**Training Data and Commercial Use**

Trained on professionally licensed tracks, royalty-free and public domain music, and synthetic MIDI-to-audio data. The model card explicitly states generated output is cleared for commercial use.

**Family Position**

XL Turbo is the speed-optimized checkpoint in the 4B DiT tier. The XL Base and XL SFT variants use 50-step CFG inference and offer higher diversity and quality respectively, at the cost of generation time. All three share the same underlying 4B DiT weights before distillation.

**License**

MIT.

---

### `baidu/ERNIE-Image-Turbo`

- **Type:** `Text-to-Image` · **NPU:** 27% · **Context:** None · **Params:** 8B · **Status:** downloaded · **Version:** 20261013 · **Load time:** 28s · **Trending:** False · **Rank:** — · **Downloads:** 324
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 0.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

A text-to-image model developed by Baidu, built for content creation tasks where text legibility and structured layout matter as much as visual quality, including posters, infographics, comics, and multi-panel compositions. It completes generation in 8 inference steps, distilled from the full ERNIE-Image model using distribution matching and reinforcement learning.

Use it in Chat to generate images directly in conversation.


**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```


**Text Rendering**

ERNIE-Image-Turbo handles dense, multi-line, and layout-sensitive text embedded directly within generated images. This includes bilingual content in both English and Chinese, making it well suited for scenarios where legible in-image text is a requirement rather than an afterthought.

**Structured Image Generation**

The model is trained for layout-aware composition tasks. This includes multi-panel comic strips, storyboards, poster grids, and UI-like designs where the spatial arrangement of elements needs to follow prompt instructions reliably.

**Prompt Enhancer**

ERNIE-Image ships with an optional lightweight Prompt Enhancer that rewrites brief user inputs into richer, more structured descriptions before they reach the image generator. This can improve output alignment on complex or underspecified prompts, at some trade-off in attribute-binding precision.

**Style Coverage**

Supports a range of visual styles: clean graphic design and typography-focused outputs, realistic photography, and more cinematic or stylized aesthetics.

**Language Support**

Bilingual prompt input in English and Chinese.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** specialist · **Artifact:** ['poster', 'infographic', 'comic', 'logo', 'photo', 'illustration'] · **Alpha:** False (None) · **Text rendering:** best · **Style:** ['layout', 'structured'] · **Speed:** fast · **Quality:** high · **Image input:** `no`
- **Dialect:** Give the exact text verbatim, and say where it goes: 'title reads X, top banner reads Y'. Layout instructions matter more than visual adjectives for this model.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** The typography specialist. 8 steps, guidance 0.0.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at logo, photo, poster, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `black-forest-labs/FLUX.2-klein-4B`

- **Type:** `Text-to-Image` · **NPU:** 19% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 5s · **Trending:** False · **Rank:** — · **Downloads:** 461
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 4 · **Guidance:** 1.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

FLUX.2 klein 4B is a compact text-to-image and image editing model for users who want fast, high-quality local image generation and multi-reference editing in a single model. The distilled 4B architecture completes generation in as low as under a second while supporting text-to-image, image-to-image editing, and multi-reference composition at quality above what its size typically delivers.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```


**Architecture and Speed**

FLUX.2 klein 4B is a rectified flow transformer step-distilled to 4 inference steps, enabling sub-second end-to-end generation. It uses a Qwen3 text embedder for prompt understanding. The distilled checkpoint trades some output diversity relative to the Base variants in exchange for significantly lower latency.

**Unified Capabilities**

All three task types run from a single model checkpoint, no switching between separate models:

- Text-to-image generation

- Image-to-image single-reference editing

- Multi-reference generation (combining elements from multiple input images)

**Distilled vs. Base**

The standard `FLUX.2-klein-4B` checkpoint is the distilled version, optimized for low-latency production use. A separate `FLUX.2-klein-base-4B` checkpoint is also available for fine-tuning, LoRA training, and research use where output diversity matters more than inference speed.

**Content Provenance**

Inference code includes pixel-layer watermarking. C2PA metadata support is included in the repository for deployments that require content provenance labeling.

**License** Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** fast-base · **Artifact:** ['illustration', 'photo', 'texture', 'logo', 'comic', 'infographic'] · **Alpha:** False (None) · **Text rendering:** weak · **Style:** ['general', 'flat'] · **Speed:** fastest · **Quality:** medium · **Image input:** `no`
- **Dialect:** Short and literal. 4 diffusion steps, rectified flow — it rewards brevity over elaboration.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Fastest generating model in the catalogue — sub-second on the device's own terms. Apache 2.0. The only non-Z-Image generator with multi-reference support.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at logo, photo, illustration, comic, infographic; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the judge called the picture with the image a rectangle 0 times out of five and the control 0 times — so the image was not used.

---

### `deepreinforce-ai/Ornith-1.0-35B`

- **Type:** `Image-Text-to-Text` · **NPU:** 50% · **Context:** 131072 · **Params:** 35B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 27s · **Trending:** True · **Rank:** — · **Downloads:** 226
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:False levels:[] default:None`
- **Flag:** 🟡 **ALWAYS ON** — reasoning is permanent; every call burns trace tokens. Budget 4096+ or you get empty 200.

**Device `desc` (verbatim):**

Ornith-1.0-35B is a coding-specialized reasoning model from DeepReinforce, post-trained on Qwen 3.5 MoE architecture via reinforcement learning, targeting terminal-based agentic coding workflows such as multi-file editing, repository navigation, and shell command execution. It activates 35B parameters in a mixture-of-experts configuration, reaching performance comparable to much larger dense models on coding agent benchmarks while fitting on a single GPU node.

Use it in Chat, or load it for Kilocode-Tiiny and opencode in Agent Store.

**Reasoning Mode**

Every response begins with a `<think>...</think>` chain-of-thought block before the final answer. The reasoning trace and the final answer are returned in separate fields when served via vLLM or SGLang with the Qwen3 reasoning parser enabled. This is on by default and cannot be disabled at the model level.

**Architecture**

Built on the Qwen 3.5 MoE architecture (qwen3_5_moe). The model is also multimodal at the architecture level (image-text-to-text pipeline tag), meaning it can accept image inputs alongside text, though the model card frames its primary use case as agentic coding.

**Self-Improving Training**

The distinguishing training method is joint RL optimization of both the solution and the search scaffold that produces it. Rather than training on solution rollouts alone, the model learns to generate the scaffolding strategy alongside the answer, allowing it to discover more effective reasoning trajectories during training.

**Tool Calling**

Emits structured `<tool_call>` blocks parsed into OpenAI-compatible `tool_calls` by the server. Works out of the box with OpenHands, opencode, Hermes Agent, and OpenClaw via the OpenAI-compatible endpoint.


**License**

MIT. No regional restrictions.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `endless-frontier/BigBang-v1-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 54% · **Context:** 131072 · **Params:** 36B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 18s · **Trending:** False · **Rank:** — · **Downloads:** 133
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

BigBang-v1-Turbo is an agentic model built for long-horizon scientific research, coding, and tool-driven reasoning, letting researchers and developers run extended search-then-verify workflows rather than single-turn question answering. It is trained through an adversarial, self-evolving synthetic data process, where one model proposes increasingly difficult frontier-level problems and a second model critiques them for correctness, difficulty, and diversity, producing a small but unusually hard post-training set of problems with objectively verifiable answers.
Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Architecture**

A mixture-of-experts model evolved from Qwen3.6-35B-A3B through post-training, with 36B total parameters and roughly 3B activated per token. It accepts both image and text input.

**Agentic Tool Use**

Built and evaluated around a tool-calling loop that combines web search, webpage reading, and sandboxed code execution, aimed at long-horizon tasks such as literature research, coding, and open-ended scientific problem solving rather than single-turn chat.

**Reasoning Mode**

Supports extended reasoning, served with a Qwen3-compatible reasoning parser that separates the thinking trace from the final answer.


**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `fal/FLUX.2-klein-4B-Background-Remove`

- **Type:** `Text-to-Image` · **NPU:** 19% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 157
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 4 · **Guidance:** 1.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

This LoRA adapter removes the background from a photo and isolates the main subject, for product photography, subject cutouts, and creative compositing without manual masking. It builds on the 4B-parameter FLUX.2 [klein] base model, so background removal happens in the same sub-second, on-device generation pass the base model is optimized for.

Use it in Chat to isolate the subject of an uploaded image.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**How It Works**

The user supplies an image with a fixed instruction prompt ("Remove the background from the image"). The model isolates the main subject and removes the surrounding background.

**Training**

Fine-tuned via LoRA on 100 image pairs spanning people, products, animals, and objects. Trained for 4,000 steps at a learning rate of 0.00005 on the fal.ai platform.

**Recommended Settings**

LoRA scale of 1.1 is recommended for best results. Supports common aspect ratios (1:1, 16:9, 9:16, 4:3, 3:4, and others).

**Limitations**

Requires a reasonably clear separation between subject and background. Fine details like hair or fur can show artifacts at the edges, and semi-transparent objects may not isolate cleanly.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** edit-adapter · **Artifact:** ['cutout', 'icon', 'logo', 'photo', 'illustration', 'comic', 'infographic'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fastest · **Quality:** n/a · **Image input:** `no`
- **Dialect:** Not a generator. Operates on an input image.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Cuts the main subject out of a photo. Product photography and compositing without manual masking.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, illustration, comic, infographic; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the judge called the picture with the image a rectangle 0 times out of five and the control 0 times — so the image was not used.

THE SOURCE IMAGE IS WIRED, AND THIS ADAPTER IGNORES IT. The bytes of the picture go to the appliance with the request — that part works. But this adapter was MEASURED ignoring the image it is given: the judge called the picture with the image a rectangle 0 times out of five and the control 0 times. So a request to remove a background is REFUSED rather than answered with a new picture that looks like an edit.

---

### `fal/FLUX.2-klein-4B-Object-Remove`

- **Type:** `Text-to-Image` · **NPU:** 19% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 117
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 4 · **Guidance:** 1.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

This LoRA adapter removes unwanted objects from photos and fills the area back in with contextually appropriate content, for anyone cleaning up product shots, real estate photos, or social media images without a full photo editor. It builds on the 4B-parameter FLUX.2 [klein] base model, so removal happens in the same sub-second, on-device generation pass the base model is optimized for.

Use it in Chat to remove marked objects from an uploaded image.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**How It Works**

The user highlights or masks the object to remove and pairs it with a fixed instruction prompt ("Remove the highlighted object from the scene"). The model erases the object and reconstructs the background naturally, matching lighting, texture, and surrounding context.

**Training**

Fine-tuned via LoRA on 100 image pairs spanning people, furniture, vehicles, electronics, animals, text and watermarks, and natural elements, across multiple aspect ratios. Trained for 4,000 steps at a learning rate of 0.00005 on the fal.ai platform.

**Recommended Settings**

LoRA scale of 1.1 is recommended for best results. Supports common aspect ratios (1:1, 16:9, 9:16, 4:3, 3:4, and others).

**Limitations**

Performance drops on very large objects and complex backgrounds, which may need multiple passes. Shadows or reflections belonging to the removed object can remain visible after removal.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** edit-adapter · **Artifact:** ['edit', 'icon', 'logo', 'photo', 'poster', 'comic', 'illustration'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fastest · **Quality:** n/a · **Image input:** `yes`
- **Dialect:** Not a generator. Operates on an input image.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Removes marked objects and fills the area contextually.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: YES — the judge called the picture with the image a rectangle 3 times out of five, and the control 0 times — so the image was used.

THE SOURCE IMAGE IS WIRED. This adapter does the operation ON a picture, and the bytes of that picture go to the appliance with the request — base64 in the image field, which is the field the appliance was measured to read. What the appliance does with them is a separate question, and it was MEASURED: this adapter honours the image, so an edit request comes out as an edit of the picture that was given.

---

### `fal/FLUX.2-klein-4B-Outpaint`

- **Type:** `Text-to-Image` · **NPU:** 20% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 135
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 4 · **Guidance:** 1.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

This LoRA adapter extends an image beyond its original borders, filling the new area with content that matches the scene, for photo expansion, background generation, and converting an image to a different aspect ratio. It builds on the 4B-parameter FLUX.2 [klein] base model, so the extended region is generated in the same sub-second, on-device pass the base model is optimized for.

Use it in Chat to extend the borders of an uploaded image.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**How It Works**

The user adds a pure green border (#00FF00) around the image marking the area to fill, paired with a fixed instruction prompt ("Fill the green spaces according to the image"). The model contextually completes the marked area to match the rest of the scene.

**Training**

Fine-tuned via LoRA on 1,000 image pairs spanning landscapes, portraits, animals, food, architecture, and various art styles, with green borders applied at 5% to 25% of image dimensions across multiple aspect ratios. Trained on the fal.ai platform.

**Recommended Settings**

Green border must be pure RGB(0, 255, 0), sized 5% to 25% of the image dimensions. LoRA scale of 1.1 is recommended for best results.

**Limitations**

Complex scenes may need multiple passes to fill coherently. Very large border areas relative to the image produce less coherent results.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** edit-adapter · **Artifact:** ['edit', 'logo', 'photo', 'poster', 'comic', 'illustration'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fastest · **Quality:** n/a · **Image input:** `unknown`
- **Dialect:** Not a generator. Operates on an input image.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Extends past the original borders, matching the scene.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at logo, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: UNKNOWN — the judge called the picture with the image a rectangle 2 times out of five, and the control 0 times — which is too close to call.

THE SOURCE IMAGE IS WIRED, AND THIS ADAPTER IGNORES IT. The bytes of the picture go to the appliance with the request — that part works. But this adapter was MEASURED ignoring the image it is given: the judge called the picture with the image a rectangle 2 times out of five and the control 0 times, which is too close to call. So an outpaint is TRIED rather than refused, and the judge says whether it worked.

---

### `fal/FLUX.2-klein-4B-Zoom`

- **Type:** `Text-to-Image` · **NPU:** 20% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 147
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 4 · **Guidance:** 1.0
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

This LoRA adapter zooms into a red-marked region of an image and generates an enlarged, detailed view of it, for anyone who needs to inspect or showcase a specific detail without a separate upscaling tool. It builds on the 4B-parameter FLUX.2 [klein] base model, so the zoomed region is regenerated with added detail rather than simply cropped and stretched.

Use it in Chat to zoom into a marked region of an uploaded image.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**How It Works**

The user marks the area of interest with a red highlight and pairs it with a fixed instruction prompt ("Zoom into the red highlighted area"). The model generates an enlarged, detailed reconstruction of that region.

**Training**

Fine-tuned via LoRA on 86 image pairs spanning landscapes, objects, people, and art, all marked with consistent red highlight regions. Trained for 4,000 steps at a learning rate of 0.00005 on the fal.ai platform.

**Recommended Settings**

Supports common aspect ratios (1:1, 16:9, 9:16, 4:3, 3:4, and others). Works best with clearly defined red highlight regions.

**Limitations**

Small highlighted regions can lose detail after zooming. Images that already contain red objects can be mistaken for highlight markers, leading to unintended zoom targets.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** edit-adapter · **Artifact:** ['edit', 'logo', 'photo', 'poster', 'comic', 'illustration'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fastest · **Quality:** n/a · **Image input:** `no`
- **Dialect:** Not a generator. Operates on an input image.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Regenerates a marked region enlarged WITH added detail. Not an upscaler — it re-imagines the region.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at logo, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the judge called the picture with the image a rectangle 1 times out of five, and the control 2 times — so the image was not used.

THE SOURCE IMAGE IS WIRED, AND THIS ADAPTER IGNORES IT. The bytes of the picture go to the appliance with the request — that part works. But this adapter was MEASURED ignoring the image it is given: the judge called the picture with the image a rectangle 1 times out of five and the control 2 times. So a request to regenerate a region in more detail is REFUSED rather than answered with a new picture that looks like an edit.

---

### `FunAudioLLM/Fun-ASR-MLT-Nano`

- **Type:** `ASR` · **NPU:** 6% · **Context:** None · **Params:** 1B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 10s · **Trending:** True · **Rank:** — · **Downloads:** 161
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Fun-ASR-MLT-Nano is a speech recognition model from Tongyi Lab built for multilingual transcription across 31 languages, with optimization for East and Southeast Asian languages, free language switching within a single audio stream, and low-latency real-time output. At 800M parameters, it covers broad language scope without the weight of larger ASR models, and handles difficult acoustic conditions including far-field pickup, noisy environments, and music-backed speech.
Use in Tiiny Meeting in Agent Store for real-time transcription.
Details

**Language support**

Supports 31 languages: Chinese, English, Cantonese, Japanese, Korean, Vietnamese, Indonesian, Thai, Malay, Filipino, Arabic, Hindi, and 19 European languages including Bulgarian, Croatian, Czech, Danish, Dutch, Estonian, Finnish, Greek, Hungarian, Irish, Latvian, Lithuanian, Maltese, Polish, Portuguese, Romanian, Slovak, Slovenian, and Swedish. Language switching mid-stream is supported without requiring pre-labeling of input language.

**Acoustic conditions**

Specifically tuned for far-field and high-noise environments such as conference rooms, in-vehicle use, and industrial sites. Also handles music background interference, enabling lyric and rap recognition.

**Relation to Fun-ASR-Nano**

Fun-ASR-MLT-Nano is the multilingual variant in the Fun-ASR-Nano family. The non-MLT version (Fun-ASR-Nano) covers Chinese (with 7 dialect families and 26 regional accents), English, and Japanese at higher depth; MLT-Nano trades dialect granularity for cross-language breadth across 31 languages, trained on hundreds of thousands of hours rather than tens of millions.

**Hotword injection**

Supports runtime hotword injection for domain-specific terminology, useful for technical, medical, or financial content where standard vocabulary coverage is insufficient.

**VAD integration**

Can be paired with an FSMN-VAD model for long-form audio segmentation, enabling processing of recordings without pre-chunked input.

**License**

Apache 2.0.

---

### `FunAudioLLM/Fun-ASR-Nano`

- **Type:** `ASR` · **NPU:** 7% · **Context:** None · **Params:** 1B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 10s · **Trending:** True · **Rank:** — · **Downloads:** 219
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Fun-ASR-Nano is an end-to-end speech recognition model from Tongyi Lab, trained on tens of millions of hours of real speech data, designed for English, Chinese and Japanese transcription with particular depth in Chinese dialect and regional accent coverage. Its 800M parameter size delivers low-latency real-time transcription with strong performance in noisy environments, including far-field pickup, music backgrounds, and rap, at a fraction of the size of competing models in the 1.5B to 8B range.

Use it in Tiiny Meeting for real-time transcription.

**Language Support**

The Nano variant supports English, Chinese and Japanese. Chinese coverage extends to 7 major dialect groups (Wu, Cantonese, Min, Hakka, Gan, Xiang, Jin) and 26 named regional accents. English and Japanese include multiple regional accent variants.

**Domain Strengths**

The model is explicitly optimized for vertical industry use cases including education and finance, with training targeting accurate recognition of professional terminology and industry-specific expressions. It addresses two named failure modes in ASR systems: hallucination generation and language confusion.

**Acoustic Conditions**

Far-field and high-noise scenarios are a core training focus, covering conference rooms, in-vehicle environments, and industrial sites. The model also handles music background interference for lyric recognition and rap speech recognition.

**Real-Time Transcription**

Supports low-latency streaming inference. VAD (voice activity detection) integration is available via the FSMN-VAD model for long-form audio segmentation. Hotword boosting is supported at inference time.

**Architecture**

End-to-end design built on a Qwen3-0.6B language model backbone with an encoder adaptor layer. The tokenizer is Qwen3-based.

**License**

Apache 2.0.

---

### `google/gemma-4-26B-A4B-it`

- **Type:** `Image-Text-to-Text` · **NPU:** 37% · **Context:** 131072 · **Params:** 26B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 11s · **Trending:** False · **Rank:** 2 · **Downloads:** 2423
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

gemma-4-26B-A4B-it is Google DeepMind's instruction-tuned mixture-of-experts model for general-purpose chat, reasoning, and agentic tasks, aimed at developers and teams who want strong language understanding without the compute cost of a full dense model. It holds 25.2B total parameters but routes only 3.8B per token through 8 of 128 experts plus one always-active shared expert, giving it inference speed close to a 4B model while approaching the quality of Gemma 4's dense 31B sibling.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Architecture**

A Mixture-of-Experts transformer, instruction-tuned on top of the base 26B-A4B checkpoint for chat formatting, instruction-following, and structured tool-call output. Each token is routed to 8 of 128 experts plus 1 shared expert that is always active, which is what keeps per-token compute down near 4B despite the larger total weight count.


**Thinking Mode**

Configurable reasoning. It can be switched on to produce a visible reasoning trace ahead of the final answer, or off for faster, direct responses.

**Tool Use**

Native function-calling is built into the instruction tuning, intended to drive autonomous, multi-step agent workflows.

**Language Support**

Pretrained across 140+ languages, with robust instruction-following quality in 35+.

**License**

Apache 2.0 (Gemma license terms apply, commercial use permitted under the Gemma Terms of Use).

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `google/gemma-4-31B-it`

- **Type:** `Image-Text-to-Text` · **NPU:** 53% · **Context:** 131072 · **Params:** 31B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 14s · **Trending:** False · **Rank:** — · **Downloads:** 342
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Gemma 4 31B-IT is Google DeepMind's instruction-tuned version of the dense 31B model in the Gemma 4 family, built for multimodal chat, reasoning, and agentic tool use, suited for developers who want the strongest general-purpose quality among Gemma 4's dense checkpoints. It carries the same 30.7B-parameter dense architecture as the base model but is post-trained for chat formatting, system-prompt adherence, and native structured tool calling, and it supports a configurable thinking mode that produces a visible reasoning trace before the final answer.
Use it in Chat to analyze images, screenshots, and documents alongside text, or load it in Agent Store for any agent that needs a general-purpose text generation model.


**Architecture**

A 60-layer dense transformer with a hybrid attention mechanism that alternates local sliding-window attention (1024-token window) with full global attention. Global layers use unified Key-Value caching and Proportional RoPE (p-RoPE) to control memory growth at long context lengths. It ships with a dedicated Multi-Token Prediction drafter model for speculative decoding, which speeds up inference without changing output quality.


**Thinking Mode**

Toggled with an `enable_thinking` parameter or a `<|think|>` control token in the system prompt. When enabled, the model writes an internal reasoning trace, wrapped in dedicated channel markers, before producing its final answer. The reasoning trace is not carried into later turns, only the final response is kept in history.

**Multimodal Capabilities**

- Accepts interleaved text and image input in any order

- Handles images at variable aspect ratios and resolutions through a configurable visual token budget (70 to 1120 tokens per image)

- Image understanding spans object detection, document and PDF parsing, screen and UI reading, chart comprehension, multilingual OCR, and handwriting recognition

- Processes video as a sequence of frames, up to 60 seconds at 1 fps


**Language Support**

Pretrained on data spanning 140+ languages, with out-of-the-box instruction-following output in 35+ languages.

**Function Calling**

Native structured tool use, covering both text-only and multimodal function calling, is trained into this instruction-tuned checkpoint specifically, enabling agentic pipelines without external scaffolding.

**Training Data Cutoff**

January 2025.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `hexgrad/Kokoro-82M`

- **Type:** `Text-to-Speech` · **NPU:** 0% · **Context:** None · **Params:** 82M · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 99
- **Input:** `Text` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Kokoro-82M is a compact open-weight text-to-speech model from hexgrad with 82 million parameters. Despite its lightweight architecture, it delivers quality comparable to larger models while being significantly faster and more cost-efficient.


**Core Capability**

Kokoro reads text aloud in one of its preset voices; it takes no reference audio. Version 1.0 ships 54 voices across its supported languages.

**Input and Output**

- Input: text, plus the name of a preset voice
- Output: speech audio at 24 kHz

**Language Support**

American English, British English, Japanese, Mandarin Chinese, Spanish, French, Hindi, Italian and Brazilian Portuguese.

**Architecture**

Kokoro is built on StyleTTS 2 with an ISTFTNet vocoder. It is decoder-only: no diffusion and no audio encoder. This build is the 8-bit (UINT8) ONNX export of the v1.0 weights.

**Training Data**

Kokoro was trained only on permissive and non-copyrighted audio: public-domain recordings, audio under licenses such as Apache and MIT, and synthetic audio from closed TTS models.

**License**

Apache 2.0.

- **Supported tags (device):** ['Custom Voice'] · **Reasoning levels (device):** []

---

### `HiDream-ai/HiDream-O1-Image-Dev`

- **Type:** `Text-to-Image` · **NPU:** 30% · **Context:** None · **Params:** 9B · **Status:** downloaded · **Version:** 20261013 · **Load time:** 18s · **Trending:** False · **Rank:** — · **Downloads:** 236
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 2048x2048 (recommended), up to 3104 per side; width and height multiples of 32 with (w/32)*(h/32) <= 4096 · **Steps:** 28 · **Guidance:** 0.0
- **Thinking (device):** `supported:None toggleable:None enabled_by_default:None levels:None default:None`

**Device `desc` (verbatim):**

HiDream-O1-Image-Dev is a distilled, speed-optimized variant of HiDream's unified image generation model, built for text-to-image generation, instruction-based image editing, and subject-driven personalization at up to 2,048 x 2,048 resolution. It completes generation in 28 inference steps at zero guidance scale, versus 50 steps for the full HiDream-O1-Image model, cutting inference time substantially while keeping the same pixel-level transformer that skips separate VAE and text-encoder stages.
Use it in Chat to generate images directly in conversation.


**Supported image sizes**

- 2048x2048 is the recommended, native resolution.
- These sizes are also verified to work well: 2304x1728, 1728x2304, 2560x1440, 1440x2560, 2496x1664, 1664x2496, 3104x1312, 1312x3104, 2304x1792, 1792x2304
- Other sizes may also work if width and height are each divisible by 32. See the formula below:

```
  width % 32 == 0
  height % 32 == 0
  width <= 3104
  height <= 3104
  (width / 32) * (height / 32) <= 4096
```

**Architecture**

A Pixel-level Unified Transformer (UiT) that processes raw pixels, text, and task-specific conditions in a single shared token space, without external VAEs or separate text encoders. This end-to-end design is what lets one checkpoint handle text-to-image generation, editing, and personalization without switching models.

**Distilled for Speed**

The Dev checkpoint is step-distilled from the full HiDream-O1-Image model: 28 inference steps instead of 50, a default guidance scale of 0.0 instead of 5.0, and a flash scheduler on predefined timesteps for generation (editing tasks default to a flow-match scheduler instead). This trades some of the full model's editing fidelity for lower latency; for editing where quality matters more than speed, HiDream recommends the full model.

**Reasoning-Driven Prompt Agent**

A built-in agent reasons through layout, subject attributes, physical logic, and text-rendering details before rewriting a raw user instruction into a self-contained English prompt, reducing the prompt-engineering burden on the user.

**Conditioning and Personalization**

Supports skeleton guidance, layout bounding boxes, and multi-reference image inputs, enabling subject-driven personalization that preserves identity across different scenes.

**Language Support**

Multilingual prompt understanding, with accurate text rendering inside generated images in both English and Chinese.

**License**

MIT.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** quality-leader · **Artifact:** ['photo', 'illustration', 'icon', 'logo'] · **Alpha:** False (None) · **Text rendering:** weak · **Style:** ['photoreal', 'high-detail'] · **Speed:** fast · **Quality:** highest · **Image input:** `unknown`
- **Dialect:** Dense and specific. Name materials, textures, the light source, and the lens. 28 steps — it rewards a fuller prompt than the 8-step models do.
- **Sizes verified:** ['1024x1024', '2048x2048']
- **Notes:** The fidelity ceiling in the catalogue — fur, foliage, reflections. ~34s at 1024x1024. Earns its keep only when detail IS the subject.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: UNKNOWN — no picture was made to judge.

---

### `huihui-ai/Huihui-Ornith-1.5-35B-A3B-abliterated-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 48% · **Context:** 262144 · **Params:** 35B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 20s · **Trending:** False · **Rank:** — · **Downloads:** 202
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:False levels:[] default:None`
- **Flag:** 🟡 **ALWAYS ON** — reasoning is permanent; every call burns trace tokens. Budget 4096+ or you get empty 200.

**Device `desc` (verbatim):**

Huihui-Ornith-1.5-35B-A3B-abliterated is an uncensored edition of Ornith-1.5-35B-A3B, built by huihui-ai for users who want the same coding, reasoning, and tool-driven agent behavior without the base model's refusal alignment. It keeps the mixture-of-experts shape of the original, activating about 3B of its 35B total parameters per token, and this Turbo release serves it with a 256K token context window.\
Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Abliteration**

The refusal behavior was removed with abliteration rather than retraining, which the author describes as a proof-of-concept implementation. Safety filtering is significantly reduced compared with the base model, so treat it as a research and testing model and review outputs before relying on them.

**Context Window**

256K tokens.

**License**

MIT, inherited from the base model.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `InternScience/Sage-A1.5-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 48% · **Context:** 262144 · **Params:** 35B · **Status:** downloaded · **Version:** 20261029 · **Load time:** 19s · **Trending:** False · **Rank:** — · **Downloads:** 69
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:False levels:[] default:None`
- **Flag:** 🟡 **ALWAYS ON** — reasoning is permanent; every call burns trace tokens. Budget 4096+ or you get empty 200.

**Device `desc` (verbatim):**

Sage-A1.5 is an agentic research model from Shanghai AI Laboratory, built for long, multi-step scientific and analytical tasks such as literature investigation, evidence gathering, and tool-driven problem solving. Built on Qwen3.6-35B-A3B, it adds the ability to split a task across parallel subagents and to check its own progress mid-task, so it changes course when a line of inquiry stops paying off instead of following one path to the end.
Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Agentic Orchestration**

The model can break a problem into sub-tasks and hand them to subagents that run at the same time, each with its own separate context. Keeping contexts apart stops one line of work from contaminating another. The main agent then compares the results, challenges weak conclusions against the evidence, and merges the findings.

This behavior is turned on when the host application registers a dedicated subagent tool. Without it, the model works as a single agent.

**Verification Mode**

An opt-in mode in which the model reviews its own reasoning as it goes: it checks evidence, spots dead-end search paths, and revises its strategy. The review happens inside its own chain of thought, with no separate critic model involved.

**Open Scientific Discovery**

Beyond answering defined questions, the model is trained to support exploratory research, combining open-ended inquiry with interactive analysis and producing research outputs that can be inspected and checked.

**Other Strengths**

- Task decomposition, forward planning, and adjusting the plan based on intermediate results
- Native function calling for working with external tools
- Scientific reasoning with tools and professional-domain knowledge questions
- Following detailed instructions with multiple constraints at once

**Thinking Mode**

Reasons before answering, with its reasoning returned separately from the final response.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `k2-fsa/OmniVoice`

- **Type:** `Text-to-Speech` · **NPU:** 2% · **Context:** None · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 6s · **Trending:** False · **Rank:** — · **Downloads:** 91
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

OmniVoice is a massively multilingual zero-shot text-to-speech model from the k2-fsa team, supporting over 600 languages, the broadest coverage among zero-shot TTS models. It is built on a diffusion-language-model-style architecture for high quality at high inference speed.


**Core Capability**

- Voice cloning: reproduce a voice from a short reference recording.
- Voice design: describe the voice through speaker attributes such as gender, age, pitch, dialect or accent, and whispering.
- Fine-grained control: non-verbal symbols such as [laughter], and pronunciation correction through pinyin or phonemes.

**Input and Output**

- Input: text, plus a reference audio clip and its transcript for cloning, or speaker attributes for voice design
- Output: speech audio at 24 kHz

**Language Support**

More than 600 languages.

**Architecture**

A diffusion-language-model-style design on a Qwen3-0.6B backbone that predicts 8 audio codebooks, paired with an audio codec whose encoder reads the reference voice and whose decoder turns the generated tokens into a 24 kHz waveform.

**License**

The code is Apache 2.0. The pre-trained model is licensed CC-BY-NC.

- **Supported tags (device):** ['Voice Clone', 'Voice Design'] · **Reasoning levels (device):** []

---

### `krea/Krea-2-Turbo`

- **Type:** `Text-to-Image` · **NPU:** 36% · **Context:** None · **Params:** 13B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 115
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 1
- **Thinking (device):** `supported:None toggleable:None enabled_by_default:None levels:None default:None`

**Device `desc` (verbatim):**

Krea-2-Turbo is a text-to-image model for creative, commercial, and design workflows, turning natural-language prompts into finished images for concepting, visual production, and rapid iteration. It is a distilled version of the base Krea 2 model, tuned to produce a full image in as few as 8 inference steps with no guidance-scale tuning needed, making it far faster than typical diffusion models that require 20 to 50 steps.
Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**Architecture**

A diffusion transformer with 12 billion parameters. Krea 2 Turbo is a post-trained checkpoint built on the Krea 2 Raw base model, with additional fine-tuning and distillation applied specifically to cut the number of steps needed at generation time.


**Training Data**

Trained on a combination of publicly available data, data licensed from third-party providers, and synthetic data generated through proprietary methods.

**License**

Krea 2 Community License (gated access). Krea does not claim copyright or other intellectual property rights over content generated by users.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** general · **Artifact:** ['photo', 'illustration', 'icon', 'logo', 'poster', 'comic'] · **Alpha:** False (None) · **Text rendering:** unknown · **Style:** ['general', 'photoreal'] · **Speed:** fast · **Quality:** unknown · **Image input:** `no`
- **Dialect:** Provisionally the DESCRIPTIVE dialect: SUBJECT FIRST, then the modifiers. That is the safest guess for a photoreal generator and it is only a guess - NOT YET CHARACTERISED. The appliance offers this model, it was downloaded on 7 Nov, and a model nobody has run is a model nobody can route to. The research loop measures it and replaces this entry with what it found. Until then the resolver will not pick it for a request it has not been shown to satisfy.
- **Notes:** The device's description claims photoreal rendering from a 12B
rectified-flow transformer at 36% NPU. NONE of that is measured
here yet — the research run is what will say whether it is true.
Kept out of the acceptance table until it has a card.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `lightx2v/MiniMax-H3-Turbo`

- **Type:** `Text-to-Video` · **NPU:** 49% · **Context:** None · **Params:** 33B · **Status:** downloaded · **Version:** 20261029 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 662
- **Input:** `Text,Image` → **Output:** `Video` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:None toggleable:None enabled_by_default:None levels:None default:None`

**Device `desc` (verbatim):**

Minimax-h3-Turbo turns a text prompt or a single starting image into a short video clip with matching audio, for anyone who wants fast AI video generation without waiting on a full diffusion pipeline. It distills MiniMax's H3 video model down to as few as 4 to 8 sampling steps, so clips render in a fraction of the passes a standard video diffusion model needs while still producing synchronized video and audio in one generation.

**Origin**

Built by the LightX2V/ModelTC team as a distilled acceleration LoRA for MiniMaxAI/MiniMax-H3, the video generation model MiniMax open-sourced. It is a community distillation released under the lightx2v organization on Hugging Face, not an official MiniMax checkpoint.

**Generation Modes**

Combines text-to-video, image-to-video, and reference-to-video in one model. Write a prompt to generate a clip from scratch, supply a starting image (or a first/last frame pair) to animate it, or provide a reference to guide the result.

**Audio**

Generates synchronized audio alongside the video in the same pass, carrying over the base MiniMax H3 model's native audio generation rather than requiring a separate audio step.

**Speed and Resolution**

Ships as separate 4-step and 8-step distilled checkpoints at 544p and 768p. The 8-step 768p checkpoint is the current default, which its maintainers describe as improving video and audio quality over the earlier 4-step version.

**License**

Apache 2.0.

---

### `m-a-p/YuE2-3B`

- **Type:** `Music Generation` · **NPU:** 14% · **Context:** None · **Params:** 3B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 11s · **Trending:** False · **Rank:** — · **Downloads:** 113
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

YuE2-3B is a music generation model from Multimodal Art Projection (M-A-P) that generates complete songs, vocals and instrumental accompaniment together, from a lyric and style prompt. It writes an editable score and semantic plan before rendering audio, so a song's melody, chords, and lyrics can be revised through iterative feedback rather than only regenerated from scratch.
Required by Tiiny Music in Agent Store.

**Architecture**

YuE2-3B combines an autoregressive/non-autoregressive Mixture-of-Transformers backbone with a flow-matching renderer. The AR-NAR stage writes the song's score and semantic tokens; flow matching then converts those into acoustic latents, which a VAE decodes into final audio. This two-stage design separates musical planning from audio synthesis, which is what allows the score to be edited independently of the rendered sound.

**Symbolic Planning and Editing**

The model supports three chain-of-thought planning modes: full (melody and chords), melody-only, or off (direct generation with no symbolic planning stage). With planning enabled, melody and chords are expressed in ABC notation before audio is generated, so a user can adjust the underlying composition and only re-render the parts that changed. The model also accepts musical feedback for agentic, multi-turn revision of an existing song's score, style, or lyrics.

**Song Creation Modes**

Beyond generating a new song from a text and lyric prompt, YuE2-3B can take an existing song and reinterpret it in a different style as a cover.

**Language Support**

English and Mandarin Chinese lyrics and prompts.

**Output**

48 kHz stereo audio, exported as FLAC or MP3. Example generations run multiple minutes in length.

**License**

CC BY-NC 4.0, non-commercial use only.

---

### `microsoft/TRELLIS.2-4B`

- **Type:** `Image-to-3D` · **NPU:** 6% · **Context:** None · **Params:** 4B · **Status:** not_downloaded · **Version:** 20261021 · **Load time:** 12s · **Trending:** False · **Rank:** — · **Downloads:** 212
- **Input:** `Image` → **Output:** `3D` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

TRELLIS.2 is a state-of-the-art large 3D generative model from Microsoft Research for high-fidelity image-to-3D generation: given a single input image, it produces a fully textured 3D mesh with physically-based rendering (PBR) materials, including transparency and translucency.

**Architecture**

A 4B-parameter flow-matching transformer built on a field-free sparse voxel representation called O-Voxel, which encodes geometry and appearance together. Unlike iso-surface approaches (SDF, Flexicubes) it handles arbitrary topology - open surfaces, non-manifold geometry and fully-enclosed structures - with sharp features, and converts between meshes and O-Voxels near-instantly without lossy optimization.

**Generation Quality**

Generates fully textured assets at voxel-grid resolutions from 512^3 up to 1536^3.

**License**

MIT.

---

### `microsoft/VibeVoice-1.5B`

- **Type:** `Text-to-Speech` · **NPU:** 8% · **Context:** None · **Params:** 1.5B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 11s · **Trending:** False · **Rank:** — · **Downloads:** 112
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

VibeVoice-1.5B is Microsoft's open text-to-speech model for expressive, long-form, multi-speaker conversational audio such as podcasts. It addresses the main limits of traditional TTS for this kind of content: scalability, speaker consistency and natural turn-taking.


**Core Capability**

The model generates a whole multi-speaker dialogue in one pass: up to 4 distinct speakers and up to about 90 minutes of speech, with the language model following the dialogue flow so the turns sound natural. Overlapping speech is not modeled.

**Input and Output**

- Input: a dialogue script, plus a voice sample for each speaker
- Output: speech audio at 24 kHz

**Language Support**

English and Chinese only. Scripts in other languages may produce unexpected output.

**Architecture**

A Qwen2.5-1.5B language model works with continuous acoustic and semantic speech tokenizers that run at an ultra-low 7.5 Hz frame rate, and a lightweight diffusion head (4 layers, about 123M parameters) that generates the acoustic detail token by token. Context length: 64K tokens.

**Intended Use**

Microsoft releases VibeVoice for research and development, and does not recommend commercial or real-world use without further testing.

**License**

MIT.

- **Supported tags (device):** ['Voice Clone', 'Multi-Speaker Dialogue'] · **Reasoning levels (device):** []

---

### `microsoft/VibeVoice-Realtime-0.5B`

- **Type:** `Text-to-Speech` · **NPU:** 2% · **Context:** None · **Params:** 0.5B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 16s · **Trending:** False · **Rank:** — · **Downloads:** 135
- **Input:** `Text` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

VibeVoice-Realtime-0.5B is Microsoft's lightweight real-time text-to-speech model, built for live narration and for letting an assistant start speaking before its full answer is written. It is designed for streaming text input and robust long-form speech generation.


**Core Capability**

The model speaks text in a single voice chosen from its preset voices; this build ships 61 voice presets. It supports one speaker per output. For multi-speaker conversations use VibeVoice-1.5B.

**Input and Output**

- Input: text, plus the name of a preset voice
- Output: speech audio at 24 kHz, up to about 10 minutes per generation

**Language Support**

Primarily English. Microsoft also provides experimental voices in nine more languages (German, French, Italian, Japanese, Korean, Dutch, Polish, Portuguese and Spanish); output in languages other than English may be unpredictable.

**Architecture**

A Qwen2.5-0.5B language model drives a lightweight diffusion head (about 40M parameters) that predicts acoustic latents, decoded by a sigma-VAE acoustic tokenizer running at an ultra-low 7.5 Hz frame rate. An interleaved, windowed design encodes incoming text chunks while generation continues from earlier context. Context length: 8K tokens.

**Intended Use**

Microsoft releases the model for research purposes.

**License**

MIT.

- **Supported tags (device):** ['Custom Voice'] · **Reasoning levels (device):** []

---

### `nvidia/Nemotron-3-Embed-1B-BF16`

- **Type:** `Text Embedding` · **NPU:** 7% · **Context:** 4096 · **Params:** 1B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 17s · **Trending:** False · **Rank:** — · **Downloads:** 81
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Nemotron-3-Embed-1B turns text into dense vector embeddings for retrieval, semantic search, and RAG pipelines, built for teams working across many languages. It was distilled from NVIDIA's larger Nemotron-3-Embed-8B teacher through two rounds of structured pruning and knowledge distillation, keeping strong multilingual and cross-lingual retrieval accuracy at a fraction of the size.

Required by Vault for document retrieval.



**Training Lineage**

Derived from an 8B parent model via NVIDIA ModelOpt Neural Architecture Search, which pruned hidden width, FFN size, attention heads, and depth, followed by distillation using combined cosine and MSE loss against the larger teacher's representations. The full pruning-and-distillation cycle was run twice to reach the final size.

**Language Support**

Evaluated across 34 languages, including English, Chinese, Japanese, Korean, Arabic, Hindi, Russian, and Vietnamese, with cross-lingual retrieval as a core design target.

**Context Window**

Accepts input sequences up to 32,768 tokens. Longer documents should be chunked before encoding.

**Usage Convention**

Queries and passages are encoded differently: prefix search queries with "query: " and indexed documents with "passage: ". Output vectors are L2-normalized, so dot product and cosine similarity produce equivalent rankings.

**Training Data**

Trained on 8.5M+ question-passage pairs, blending public datasets (MIRACL, HotpotQA, SQuAD, PubMedQA, and others) with synthetic data generated using Qwen3, Gemma, GPT-OSS, and NVIDIA's own Nemotron-3 Super and Ultra models.

**License**

Released under the OpenMDW License Agreement v1.1. Built on Ministral-3-3B-Instruct-2512, which is Apache 2.0. Cleared for commercial use.

---

### `nvidia/Nemotron-3-Embed-8b-Bf16`

- **Type:** `Text Embedding` · **NPU:** 20% · **Context:** 4096 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 37s · **Trending:** False · **Rank:** — · **Downloads:** 161
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Nemotron-3-Embed-8B turns text into dense vector embeddings for retrieval, semantic search, and RAG pipelines, aimed at teams building multilingual question-answering systems over large text corpora. It outputs 4096-dimensional embeddings that can be sliced down to smaller sizes like 2048 or 1024 dimensions and still work well after re-normalization, so retrieval systems can trade a little accuracy for less storage and faster search without re-encoding anything.

Required by Vault for document retrieval.



**Architecture**

Built directly on Ministral-3-8B-Instruct-2512 as a bidirectional transformer encoder, using average pooling over token representations to produce each embedding. Unlike the smaller 1B version in this family, the 8B is not a pruned or distilled derivative, it is the full-size base for that lineage.

**Flexible Embedding Size**

Embeddings can be truncated from the front of the 4096-dimension vector (for example to 2048 or 1024 dimensions) to save storage and speed up similarity search. Truncated vectors need to be re-normalized (L2) after slicing to stay accurate.

**Context Window**

Supports sequences up to 32,768 tokens. The model uses YaRN-scaled RoPE to maintain long-context behavior; a benign Transformers config warning about `apply_yarn_scaling` is expected and should not be removed from `config.json`.

**Language Support**

Evaluated across 34 languages, including English, Chinese, Japanese, Arabic, Hindi, and Russian, with cross-lingual retrieval as a core target.

**Usage Convention**

Prefix search queries with "query: " and indexed documents with "passage: ". Output embeddings are L2-normalized, so dot product and cosine similarity rank results identically.

**Training Data**

Trained on 50M+ question-passage pairs combining public datasets (MIRACL, HotpotQA, SQuAD, PubMedQA, Wikipedia, Reddit, and others) with synthetic data generated using Qwen3, Gemma, GPT-OSS, and NVIDIA's own Nemotron-3 Super and Ultra models.

**License**

Released under the OpenMDW License Agreement v1.1. Built on Ministral-3-8B-Instruct-2512, which is Apache 2.0. Cleared for commercial use.

---

### `nvidia/Parakeet-TDT-0.6B-V3`

- **Type:** `ASR` · **NPU:** 5% · **Context:** None · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20260928 · **Load time:** 5s · **Trending:** False · **Rank:** — · **Downloads:** 167
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Parakeet-TDT-0.6B-V3 is a speech recognition model from NVIDIA that transcribes audio to text across 25 European languages, automatically detecting the spoken language without needing a manual language setting. It outputs punctuated, capitalized text directly, and handles long recordings in a single pass, from meetings and lectures up to full-length calls.
Required by Tiiny Meeting in Agent Store for real-time transcription.

**Language Support**

25 languages: Bulgarian, Croatian, Czech, Danish, Dutch, English, Estonian, Finnish, French, German, Greek, Hungarian, Italian, Latvian, Lithuanian, Maltese, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Spanish, Swedish, and Ukrainian.

**Architecture**

FastConformer encoder paired with a TDT (Token-and-Duration Transducer) decoder. The TDT decoder predicts how many audio frames to skip alongside each token, which lets the model decode faster than a standard transducer without a separate external language model.

**Timestamps**

Word-level, segment-level, and character-level timestamps are available alongside the transcript, useful for aligning captions or searching within long recordings.

**Long-Form Audio**

The model processes long audio in a single pass rather than requiring manual chunking, handling multi-hour recordings.

**Training Data**

Trained on a mix of roughly 10,000 hours of human-transcribed speech and about 660,000 hours of pseudo-labeled speech spanning the 25 supported languages.

**License**

CC-BY-4.0, permitting commercial use with attribution.

---

### `openai/gpt-oss-120b`

- **Type:** `Text Generation` · **NPU:** 100% · **Context:** 131072 · **Params:** 120B · **Status:** downloaded · **Version:** 20260930 · **Load time:** 120s · **Trending:** False · **Rank:** — · **Downloads:** 1264
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:True levels:['low', 'medium', 'high'] default:medium`
- **Flag:** 🟡 **LEVELS ONLY** — no off switch. `thinking: off` → `low`, `thinking: on` → `high`. Label reports `[think:off→low]` so you know.

**Device `desc` (verbatim):**

gpt-oss-120b is OpenAI's open-weight reasoning model, a 117B MoE model that activates 5.1B parameters per token, designed for production workloads requiring strong chain-of-thought reasoning, tool use, and agentic task execution. Reasoning effort is configurable at three levels per request, letting you trade off response depth against latency depending on the task.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.


**Reasoning Levels**

The model accepts a reasoning effort setting in the system prompt: low for fast general dialogue, medium for balanced responses, and high for deep analysis. The full chain-of-thought output is accessible to developers but is intended for debugging rather than end-user display.

**Agentic Capabilities**

Natively supports function calling with defined schemas, web browsing via built-in browsing tools, and Python code execution. These are first-class capabilities trained into the model rather than added via system prompt scaffolding.

**Training Data and Knowledge Cutoff**

Trained on a text-only dataset with a focus on STEM, coding, and general knowledge. Knowledge cutoff is June 2024.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** ['low', 'medium', 'high']

---

### `openai/gpt-oss-20b`

- **Type:** `Text Generation` · **NPU:** 27% · **Context:** 131072 · **Params:** 20B · **Status:** running · **Version:** 20260910 · **Load time:** 30s · **Trending:** True · **Rank:** 4 · **Downloads:** 787
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:True levels:['low', 'medium', 'high'] default:medium`
- **Flag:** 🟡 **LEVELS ONLY** — no off switch. `thinking: off` → `low`, `thinking: on` → `high`. Label reports `[think:off→low]` so you know.

**Device `desc` (verbatim):**

A compact open-weight reasoning model from OpenAI, built for local deployment, low-latency inference, and agentic workflows. It uses a Mixture-of-Experts architecture with only 3.6B parameters active per token out of 21B total, which keeps it fast and resource-light on-device.

Use it in Chat, or load it for Kilocode-Tiiny, opencode, and other agents in Agent Store.



**Reasoning Effort**

Reasoning depth is configurable at three levels: low for fast general dialogue, medium for balanced speed and detail, and high for deep analysis. The level is set via a single line in the system prompt. Full chain-of-thought output is exposed to developers but is not intended to be surfaced to end users.

**Agentic Capabilities**

The model has native support for function calling, web browsing, Python code execution, and structured outputs. It was designed specifically for use inside agentic workflows, not just conversational use.

**Training and Format**

Trained on OpenAI's Harmony response format, which must be used for correct behavior. Training data is primarily English, with a focus on STEM, coding, and general knowledge. The tokenizer is o200k\_harmony, a superset of the tokenizer used for o4-mini and GPT-4o.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** ['Low', 'Medium', 'High']

---

### `openai/Whisper-large-v3-turbo`

- **Type:** `ASR` · **NPU:** 5% · **Context:** None · **Params:** 0.8B · **Status:** downloaded · **Version:** 20260929 · **Load time:** 7s · **Trending:** False · **Rank:** — · **Downloads:** 278
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Whisper large-v3-turbo is a speech recognition model from OpenAI that transcribes spoken audio to text across 99 languages, and can also translate non-English speech directly into English text. It is a distilled version of Whisper large-v3, with its decoder trimmed from 32 layers to 4, giving substantially faster transcription with only a minor drop in accuracy.
Required by Tiiny Meeting in Agent Store for real-time transcription.

**Translation**

Setting the task to translate has the model output an English transcript of non-English speech directly, without a separate translation step.

**Timestamps**

Both sentence-level and word-level timestamps are supported, useful for captioning or navigating within a recording.

**Audio Chunking**

The model processes audio in 30-second windows. Longer recordings are handled by either sequential buffered decoding or a chunked algorithm, both supported out of the box, and batched inference is available for processing multiple files at once.

**Training Data**

Trained on more than 5 million hours of labeled audio using weak supervision, which is what gives it broad generalization across accents, background noise, and domain-specific language without per-language fine-tuning.

**License**

MIT.

---

### `openbmb/VoxCPM2`

- **Type:** `Text-to-Speech` · **NPU:** 7% · **Context:** None · **Params:** 2B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 10s · **Trending:** False · **Rank:** — · **Downloads:** 68
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

VoxCPM2 is a tokenizer-free, diffusion-autoregressive text-to-speech model from OpenBMB. With 2B parameters, it covers 30 languages and produces 48 kHz studio-quality audio, trained on over 2 million hours of multilingual speech.


**Core Capability**

- Voice design: create a new voice from a natural-language description alone (gender, age, tone, emotion, pace), with no reference audio.
- Controllable cloning: clone a voice from a short clip, with optional style guidance to steer emotion, pace and expression while keeping the timbre.
- Ultimate cloning: give the reference audio together with its transcript for the most faithful reproduction of the voice.
- Context-aware synthesis: the model infers suitable prosody and expressiveness from the text.

**Input and Output**

- Input: text, optionally with a voice description or a reference audio clip (16 kHz reference audio is accepted)
- Output: speech audio at 48 kHz

**Language Support**

30 languages, with no language tag needed: Arabic, Burmese, Chinese, Danish, Dutch, English, Finnish, French, German, Greek, Hebrew, Hindi, Indonesian, Italian, Japanese, Khmer, Korean, Lao, Malay, Norwegian, Polish, Portuguese, Russian, Spanish, Swahili, Swedish, Tagalog, Thai, Turkish and Vietnamese. Chinese dialects include Sichuanese, Cantonese, Wu, Dongbei, Henan, Shaanxi, Shandong, Tianjin and Minnan.

**Architecture**

A diffusion-autoregressive pipeline (local encoder, text-semantic LM, residual acoustic LM, local diffusion transformer) built on a MiniCPM-4 backbone. AudioVAE V2 takes 16 kHz audio in and puts 48 kHz audio out with built-in super-resolution, so no external upsampler is needed.

**License**

Apache 2.0.

- **Supported tags (device):** ['Voice Clone', 'Voice Design'] · **Reasoning levels (device):** []

---

### `OpenMOSS-Team/MOSS-Transcribe-Diarize`

- **Type:** `ASR` · **NPU:** 6% · **Context:** None · **Params:** 0.9B · **Status:** downloaded · **Version:** 20261008 · **Load time:** 14s · **Trending:** False · **Rank:** — · **Downloads:** 176
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

MOSS-Transcribe-Diarize is an end-to-end model for converting long, multi-speaker audio recordings into structured transcripts with timestamps and speaker labels, in a single pass. It handles speech transcription and speaker diarization jointly, without requiring separate pipeline components, making it effective for meetings, calls, podcasts, and interviews.\
Required by Tiiny Meeting in Agent Store for transcription.


MOSS-Transcribe-Diarize is built by OpenMOSS.

**Architecture**

The model combines a Whisper-Medium audio encoder with a Qwen3-0.6B-style causal decoder, connected by a 4x temporal merge and MLP adaptor. Audio is processed at 16 kHz in 30-second chunks. The output follows a compact format: `[start_time][Sxx]transcribed text[end_time]`, where speaker labels such as `[S01]` and `[S02]` are relative identifiers assigned within the audio file.

**Capabilities**

- Long-form transcription with per-segment timestamps
- Speaker diarization without a separate diarization pipeline
- Promptable generation: supports custom transcription instructions and hotword injection via prompt prefix
- Acoustic event annotation support

**Language Support**

Trained on English and Chinese audio; the model card lists both as supported languages.

**Serving**

Supports vLLM and SGLang Omni serving via an OpenAI-compatible `/v1/audio/transcriptions` endpoint. Use `response_format=verbose_json` to receive parsed speaker segments; `json` returns the raw transcript string only. For long multi-speaker recordings, `max_new_tokens` should be raised from the default 5120 (the model card recommends up to 65536 for extended audio).

**License**

Apache 2.0.

---

### `OpenMOSS-Team/MOSS-TTS-Nano-100M`

- **Type:** `Text-to-Speech` · **NPU:** 0% · **Context:** None · **Params:** 0.1B · **Status:** not_downloaded · **Version:** 20261029 · **Load time:** 5s · **Trending:** False · **Rank:** — · **Downloads:** 104
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

MOSS-TTS-Nano-100M is a tiny multilingual speech generation model from MOSI.AI and the OpenMOSS team. With only 0.1B parameters it is designed for real-time speech generation directly on the CPU, without a GPU or NPU. This build is a self-contained CPU package.


**Core Capability**

Voice cloning is the model's main workflow: give it a short reference recording and it speaks new text in that voice. Long text is supported, with the input split into chunks and cloned automatically.

**Input and Output**

- Input: text, plus a reference audio clip of the target voice
- Output: 48 kHz, two-channel (stereo) speech audio

**Language Support**

20 languages: Chinese, English, German, Spanish, French, Japanese, Italian, Hebrew, Hungarian, Korean, Russian, Persian (Farsi), Arabic, Polish, Portuguese, Czech, Danish, Swedish, Greek and Turkish.

**Architecture**

A pure autoregressive Audio Tokenizer + LLM pipeline. The audio side uses MOSS-Audio-Tokenizer-Nano, a roughly 20M-parameter causal-Transformer codec that compresses 48 kHz stereo audio into a 12.5 Hz token stream with 16 RVQ codebooks. This build is a Q8_0 GGUF package: the language model and codec projections are 8-bit, the remaining matrices FP16.

**License**

Apache 2.0.

- **Supported tags (device):** ['Voice Clone'] · **Reasoning levels (device):** []

---

### `ornith-ai/Ornith-1.5-35B-A3B-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 54% · **Context:** 262144 · **Params:** 35B · **Status:** downloaded · **Version:** 20261029 · **Load time:** 18s · **Trending:** False · **Rank:** — · **Downloads:** 304
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:False levels:[] default:None`
- **Flag:** 🟡 **ALWAYS ON** — reasoning is permanent; every call burns trace tokens. Budget 4096+ or you get empty 200.

**Device `desc` (verbatim):**

Ornith-1.5-35B-A3B-Turbo is a mixture-of-experts model built for coding, reasoning, and agentic workflows, letting developers handle repository-scale coding and multi-step tool-driven tasks without flagship-scale hardware. It activates only about 3B of its 35B total parameters per token, and is trained with a self-improving reinforcement learning loop that has the model generate its own tasks, scaffolds, and solution rollouts rather than relying on fixed, human-curated data.
Use it in Chat, or load it in any agent in Agent Store that requires a text generation model.

**Reasoning Mode**

Generates a chain-of-thought inside `<think>...</think>` blocks, returned separately from the final answer via a `reasoning_content` field when served with a compatible reasoning parser.

**Self-Improving Training**

The distinguishing method jointly optimizes three components with reinforcement learning: task generation (what problems to train on), scaffold construction (the harness used to attempt them), and solution rollouts (the attempted answers). Instead of a fixed, human-curated curriculum, the model continuously proposes new tasks and improves its own policy against them, letting the training curriculum evolve alongside the model's capability.


**Architecture**

A mixture-of-experts model built on Qwen3.5 and Gemma4 with additional continued pretraining, mid-training, and post-training. It accepts both image and text input alongside text output.

**Tool Calling**

Emits OpenAI-compatible function calls, parsed from structured tool-call blocks in the model's output. Optimized for terminal-based coding agents, and works with agent frameworks such as OpenCode, Hermes Agent, and OpenClaw.

**Family**

Ornith-1.5 spans three sizes: a 9B dense model (with a quantized variant for on-device mobile use), this 35B mixture-of-experts model at roughly 3B active parameters, and a 397B mixture-of-experts flagship.

**License**

MIT.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `PaddlePaddle/PP-DocLayoutV3`

- **Type:** `Image-to-Text` · **NPU:** 20% · **Context:** None · **Params:** 1B · **Status:** downloaded · **Version:** 20260911 · **Load time:** Nones · **Trending:** False · **Rank:** — · **Downloads:** 103
- **Input:** `Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:None toggleable:None enabled_by_default:None levels:None default:None`

**Device `desc` (verbatim):**

PP-DocLayoutV3 detects and orders the structural elements of a document page directly from an image, letting developers build document parsing pipelines that hold up on messy real-world input such as skewed scans, curved book photos, and screen captures, not just clean flat PDFs. It predicts non-rectangular, multi-point bounding boxes and the logical reading order in a single forward pass, replacing the separate detect-then-reorder two-stage approach used by earlier PP-DocLayout versions, at roughly 33M parameters.

**Role in Document Parsing**

This model performs layout analysis only: it locates and labels regions such as titles, paragraphs, tables, images, and formulas, and determines the order they should be read in. It does not transcribe text itself, so a full OCR pipeline pairs it with a separate text recognition model. It serves as the layout analysis stage inside PaddleOCR-VL, and document parsing pipelines from other model families (including GLM-OCR's official SDK) also use it as their layout stage.

**Architecture**

An object detection model with roughly 33.3M parameters. Earlier PP-DocLayout versions combined a separate detector with a cascaded pointer network to determine reading order; PP-DocLayoutV3 predicts region locations and reading order together in one pass, and its multi-point box format lets it fit skewed or curved page regions more accurately than a standard axis-aligned box.

**Robustness**

Built specifically to handle non-planar document images, including uneven lighting, skewed pages, screen-photographed content, and curved surfaces such as photographed book pages.

**License**

Apache 2.0.

---

### `PaddlePaddle/PP-OCRv6-Medium`

- **Type:** `Image-to-Text` · **NPU:** 1% · **Context:** None · **Params:** 22M · **Status:** downloaded · **Version:** 20260910 · **Load time:** 11s · **Trending:** False · **Rank:** — · **Downloads:** 157
- **Input:** `Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

PP-OCRv6 Medium Rec is the top-tier recognition model in PaddlePaddle's PP-OCRv6 system, a 19M-parameter model covering 50 languages and 16 text categories including handwritten, ancient, Japanese, industrial, and card text. It shares the same LCNetV4 backbone, EncoderWithLightSVTR recognition neck, and CTC+NRTR multi-head decoder as the small and tiny tiers, where the additional capacity concentrates most visibly on the hardest recognition categories: handwritten text, Japanese script, and artistic text.

**Role in Pipeline**

PP-OCRv6 separates OCR into detection and recognition. This model handles recognition only: it receives a cropped text-region image from a detection model and returns transcribed text with a confidence score. Full OCR pipeline usage requires pairing it with `PP-OCRv6_medium_det`.

**Architecture**

Three components, identical in design to the small and tiny tiers, scaled to 19M total parameters:

- **LCNetV4**: MetaFormer-style lightweight backbone with structural reparameterization. Multi-branch convolutions are fused into a single branch at inference, reducing latency without accuracy loss.

- **EncoderWithLightSVTR**: Recognition neck combining local convolution with global sparse vision transformer attention, with additive skip connections.

- **CTC+NRTR decoder**: Multi-head decoder combining Connectionist Temporal Classification and Non-Recurrent Transformer, providing complementary decoding paths for more robust recognition.

**Language and Scenario Support**

50 languages. 16 scenario categories: handwritten Chinese and English, printed Chinese and English, traditional Chinese, ancient text, Japanese, confusable characters, special symbols, general text, pinyin, artistic text, industrial labels (digital displays, dot-matrix characters, tire prints), screen text, and card text.

**License**

Apache 2.0.

---

### `PaddlePaddle/PP-OCRv6-Small`

- **Type:** `Image-to-Text` · **NPU:** 0% · **Context:** None · **Params:** 2.48M · **Status:** not_downloaded · **Version:** 20260910 · **Load time:** 11s · **Trending:** False · **Rank:** — · **Downloads:** 264
- **Input:** `Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

PP-OCRv6 Small Rec is the mid-tier text recognition model in PaddlePaddle's PP-OCRv6 OCR system, a 5.2M-parameter model that reads text from localized image regions across 50 languages and 16 scenario categories including handwritten, ancient, Japanese, industrial, and card text. All three tiers in the PP-OCRv6 family share the same MetaFormer-style block primitives with structural reparameterization, so the small model inherits the same backbone (LCNetV4) and recognition neck (EncoderWithLightSVTR) as the medium tier, scaled down rather than architecturally redesigned.

**Role in Pipeline**

PP-OCRv6 splits OCR into detection and recognition. This model handles recognition only: it receives a cropped text-region image from a separate detection model and returns the transcribed text with a confidence score. Full OCR pipeline usage requires pairing it with `PP-OCRv6_small_det`.

**Architecture**

Three architectural components:

- **LCNetV4**: MetaFormer-style lightweight backbone with structural reparameterization. Reparameterization fuses multi-branch convolutions into a single branch at inference, reducing latency without accuracy loss.

- **EncoderWithLightSVTR**: Recognition neck combining local convolution with global sparse vision transformer attention, with additive skip connections.

- **CTC+NRTR decoder**: Multi-head decoder combining Connectionist Temporal Classification and Non-Recurrent Transformer, providing complementary decoding paths for more robust recognition.

**Language and Scenario Support**

50 languages. Scenario coverage spans 16 categories: handwritten Chinese and English, printed Chinese and English, traditional Chinese, ancient text, Japanese, confusable characters, special symbols, general text, pinyin, artistic text, industrial labels (including digital displays, dot-matrix characters, tire prints), screen text, and card text.

**License**

Apache 2.0.

---

### `PelaAI/KnowLine-35B-A3B-Gen1.5`

- **Type:** `Text Classification` · **NPU:** 48% · **Context:** 262144 · **Params:** 35B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 21s · **Trending:** False · **Rank:** — · **Downloads:** 86
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

KnowLine-35B-A3B-Gen1.5 answers with probabilities rather than prose: you send a state, text or a chat, sometimes with images, and up to 64 typed yes/no, multiple choice or rubric questions, and it returns the likelihood of each option. It keeps the weights of Gen1 unchanged and adds a front end that reads every short request twice before answering, improving reasoning over longer inputs at about 1.56 times the prompt tokens.

**Answering Format**

Each question is a single forward pass and the answer is read from the probability of the label tokens, so no text is generated and existing clients only need to change the base URL or the model name.

**Read Twice**

Text-only requests of up to 3,000 tokens are sent a second time before the model answers, so every token can also attend to the earlier copy that already contains the question. Longer requests and requests with images are handled exactly as in Gen1. No retraining was involved, and the gains are concentrated in reasoning and inference over long inputs while short-text tasks are flat or slightly lower.

**Languages and License**

English, Simplified Chinese and Traditional Chinese. The weights are Apache-2.0 and the serving code is MIT.

---

### `PelaAI/KnowLine-4B-Gen5.5`

- **Type:** `Text Classification` · **NPU:** 17% · **Context:** 262144 · **Params:** 4B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 24s · **Trending:** False · **Rank:** — · **Downloads:** 81
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

KnowLine-4B-Gen5.5 answers typed questions about a piece of text or a chat, such as yes/no checks, pick-one-of-k choices and rubric scores, and returns a probability for each option rather than writing an answer. It reads the same short text-only request twice before answering, which improves accuracy on long inputs at about 1.56 times the prompt tokens, with the weights unchanged from the previous release.

**Requests**: 

One request carries a state and up to 64 typed questions, each answered in a single forward pass with no text generation, so clients of earlier releases only need to point at the new model name.

**Read twice**: 

The second pass applies to text-only requests of up to 3,000 tokens; longer requests and requests with images are served exactly as in the previous release.

**Languages**: 

English, Simplified Chinese and Traditional Chinese.

**License**: 

The weights are Apache-2.0, and the companion server scripts are MIT.

---

### `Qwen/Qwen-Image-2.1`

- **Type:** `Text-to-Image` · **NPU:** 62% · **Context:** None · **Params:** 7B · **Status:** downloaded · **Version:** 20261102 · **Load time:** 5s · **Trending:** False · **Rank:** 6 · **Downloads:** 636
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 2048x2048 · **Steps:** 40 · **Guidance:** 1
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen-Image-2.1 is a unified image model from the Qwen team that generates images from text and edits existing images with the same weights, for users who want one model for both creation and revision. It can output images with a real transparent background, so stickers, logos, and product cutouts come out ready to place on any design without a separate background-removal step.
Use it in Chat to generate images directly in conversation.

**Supported image sizes**

* 2048x2048 is the recommended resolution.
* These sizes are also verified to work well: 512x512, 640x480, 480x640, 768x480, 480x768, 736x416, 416x736, 1024x1024, 1280x960, 960x1280, 1536x960, 960x1536, 1536x864, 864x1536, 2400x1792, 1792x2400, 2560x1600, 1600x2560, 2752x1536, 1536x2752.
* Other sizes may also work if width and height are each divisible by 32 and satisfy the formula below:

```text
width % 16 == 0
height % 16 == 0
ceil_to_32((width / 16) * (height / 16)) <= 16896
```

**Transparent Images**

- Generate standard or transparent (RGBA) images from a text prompt
- Edit existing transparent layers while keeping the alpha channel intact
- Extract a subject from a photograph onto a transparent background

For transparent output, state in the prompt that the image has an alpha channel and a transparent background.

**Editing**

- Combine up to 10 reference images in a single request
- Mark the area to change with a drawn circle, painted annotation, or separate mask for local edits
- Keeps the identity of people and products consistent across edits

**Visual Quality**

Improvements over earlier Qwen-Image releases focus on typography, portrait lighting, realistic textures, and fine detail. 

**Architecture**

A 7B diffusion transformer with 32 single-stream layers, paired with a Qwen3-VL text encoder that reads both the prompt and any reference images. Mixed-granularity attention and prefix KV cache reuse reduce the compute cost of each generation.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** flagship · **Artifact:** ['icon', 'logo', 'sticker', 'cutout', 'illustration', 'photo', 'comic'] · **Alpha:** True (native-rgba) · **Text rendering:** strong · **Style:** ['general', 'flat', 'illustration'] · **Speed:** slow · **Quality:** highest · **Image input:** `yes`
- **Dialect:** Conversational and specific. 'A flat vector icon of a fox head, front-facing, single solid fill, transparent background.' Negative space and shape language beat adjectives.
- **Sizes verified:** ['512x512', '1024x1024', '2048x2048', '2400x1792', '1536x960']
- **Notes:** THE transparency model. Native RGBA output — stickers, logos and cutouts come out ready to place, no background-removal step. 40 steps, 62% NPU: the most expensive image model here, and it cannot coexist with a 55% planner. Planning consequence, not a reason to avoid it.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, illustration, comic; handled flat and realistic style; rendered 16.07% transparent pixels; got text right.

MEASURED 2026-11-07: IMAGE INPUT: YES — the judge called the picture with the image a rectangle 5 times out of five, and the control 2 times — so the image was used.

---

### `Qwen/Qwen-Image-2.1-PE-I2I`

- **Type:** `Image-Text-to-Text` · **NPU:** 24% · **Context:** 262144 · **Params:** 7B · **Status:** not_downloaded · **Version:** 20261021 · **Load time:** 9s · **Trending:** False · **Rank:** — · **Downloads:** 95
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen-Image-2.1-PE-I2I turns a short or vague image-editing request into a detailed, precise instruction for Qwen-Image-2.1, for users who want reliable edits without writing long prompts. It looks at the input images before rewriting, so the expanded instruction spells out exactly what to change, what to leave untouched, and what aspect ratio the result should use.

**How It Works**

The model takes one or more images plus an editing instruction, reasons through the request in a thinking step, then returns a structured result: the rewritten instruction and an aspect ratio decision. The ratio is either a new value for a fresh composition or a pointer to the input image whose proportions the edit should keep.

The output is meant to be passed straight to Qwen-Image-2.1, not read as a conversational reply.

**Editing Behavior**

- Local edits (objects, attributes, backgrounds, text, style, image quality, viewpoint, canvas) are scoped tightly: the named change is applied with full strength and everything else stays as in the original
- Requests that place a subject in a new picture, such as a new scene, a composite, a product shoot, a poster, or an infographic, get an actively designed scene, lighting, composition, and layout
- Faces, recognizable accessories, product designs, and the original art medium are preserved unless the request targets them

**Multiple Images**

With two or more input images, the rewritten instruction refers to each image by position and states its role, including which one serves as the base canvas. This keeps compositing and face or object swaps unambiguous for the editor.

**Aspect Ratio**

- A ratio or format named in the request (for example "square" or "poster") is followed
- In-place edits keep the proportions of the input image
- Outpainting picks a new ratio from the direction of extension, and panoramas default to 2:1
- "2K", "4K", and "8K" are treated as quality cues, not as size or ratio

**Language Support**

Chinese instructions produce a Chinese rewritten instruction, and instructions in other languages produce English. Text to be rendered inside the image follows the language the user names, otherwise the language already present in the image, otherwise the language of the instruction.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** prompt-enhancer · **Artifact:** ['prompt_expansion'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fast · **Quality:** n/a · **Image input:** `None`
- **Dialect:** Takes one or more images plus a vague editing instruction and returns a precise rewrite that spells out what to change, what to leave untouched, and the aspect ratio.
- **Notes:** 7B, 262144 ctx, 24% NPU. The image-to-image counterpart of PE-T2I. NOT downloaded on this device as of 2026-11-05.

---

### `Qwen/Qwen-Image-2.1-PE-T2I`

- **Type:** `Text Generation` · **NPU:** 23% · **Context:** 262144 · **Params:** 7B · **Status:** downloaded · **Version:** 20261021 · **Load time:** 8s · **Trending:** False · **Rank:** — · **Downloads:** 123
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen-Image-2.1-PE-T2I expands a short image idea into a full, detailed scene description for Qwen-Image-2.1, for users who want rich, well-composed images without learning how to write long prompts. A one-line request in any language comes back as a complete English description of the finished picture, along with a recommended aspect ratio.

**How It Works**

The model reads the request, reasons through it in a thinking step, then returns a structured result: the expanded description and an aspect ratio. The output is meant to be passed straight to Qwen-Image-2.1, not read as a conversational reply.

**Prompt Expansion**

- Every request is expanded to a similar depth, roughly 20 sentences, so a short idea gets as much detail as a long one
- Details the user leaves open, such as setting, props, and colors, are filled in, while details the user specifies are kept as given
- The description walks through framing, every element in the scene, lighting, and overall composition
- Written as a plain description of the final image, without filler quality words like "masterpiece" or "8K"
- Practical requests such as "no noise" are applied to the description rather than repeated in it

**Text in Images**

Any text meant to appear in the image is quoted exactly, with its position, style, and relative size. Text keeps its original script, so Chinese, Japanese, Korean, Russian, or Arabic signage stays in that language even though the surrounding description is in English. Charts and infographics get their axes, labels, and values written out.

**Aspect Ratio**

- A ratio named in the request is followed
- Otherwise, horizontal subjects default to 3:2 and vertical subjects to 2:3
- Square 1:1 is chosen for badges, icons, and emblems, 16:9 for cinematic scenes, and tall ratios for phone screens or banners

**Base Model**

Fine-tuned from Qwen3.5-VL as the official prompt enhancer for Qwen-Image-2.1 text-to-image generation. A separate companion model, Qwen-Image-2.1-PE-I2I, handles image-editing requests.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** prompt-enhancer · **Artifact:** ['prompt_expansion'] · **Alpha:** False (None) · **Text rendering:** n/a · **Style:** ['n/a'] · **Speed:** fast · **Quality:** n/a · **Image input:** `None`
- **Dialect:** Takes a short image request and returns a full English scene description of roughly 20 sentences, plus a recommended aspect ratio. The output is designed to be passed straight to Qwen-Image-2.1 — it IS the dialect.
- **Notes:** 7B, 262144 ctx, 23% NPU. Coexists with Qwen-Image-2.1 (62%) at 85%. This is the device's own answer to prompt translation — use it instead of hand-writing a dialect.

---

### `Qwen/Qwen3-30B-A3B-Instruct`

- **Type:** `Text Generation` · **NPU:** 55% · **Context:** 131072 · **Params:** 30B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 30s · **Trending:** True · **Rank:** — · **Downloads:** 136
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

A general-purpose MoE language model from Alibaba's Qwen team, updated in July 2025 to deliver stronger instruction following, reasoning, coding, multilingual coverage, and long-context understanding than the original Qwen3-30B-A3B. It activates only 3.3B of 30.5B total parameters per token, keeping inference fast while operating at a much larger effective knowledge capacity.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.



**Non-Thinking Only**

This model runs exclusively in non-thinking mode. It does not produce chain-of-thought output. No configuration is needed to disable thinking; it is simply absent. Users who want thinking mode should use the base Qwen3-30B-A3B instead.

**Agentic Capabilities**

Supports tool calling natively. The Qwen team recommends pairing it with Qwen-Agent for agentic workflows, which handles tool-calling templates and MCP configuration internally.


**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-30B-A3B-Thinking`

- **Type:** `Text Generation` · **NPU:** 58% · **Context:** 131072 · **Params:** 30B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 30s · **Trending:** True · **Rank:** — · **Downloads:** 193
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:False enabled_by_default:True levels:[] default:None`
- **Flag:** 🟡 **ALWAYS ON** — reasoning is permanent; every call burns trace tokens. Budget 4096+ or you get empty 200.

**Device `desc` (verbatim):**

Qwen3-30B-A3B-Thinking-2507 is a mixture-of-experts reasoning model built for hard problems: mathematics, science, coding, and multi-step logic tasks that require extended deliberation. It runs 30.5B total parameters while activating only 3.3B per token, keeping inference efficient relative to its reasoning depth.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.



**Architecture**

MoE with 128 experts, 8 activated per forward pass. 48 layers, GQA with 32 query heads and 4 KV heads.

**Thinking Mode**

This model operates in thinking-only mode. There is no non-thinking toggle. Every response goes through an internal chain-of-thought before producing a final answer. The thinking trace is visible to the application layer but excluded from multi-turn history by default via the built-in chat template. Qwen recommends reserving at least 32,768 output tokens for typical queries, and up to 81,920 for competition-level math or coding problems.

**Agentic Capability**

Tool calling is a first-class feature. The model supports MCP server configuration natively and integrates with Qwen-Agent for structured tool use. Function calling works in thinking mode.

**Language Support**

100+ languages and dialects, with multilingual instruction following included in post-training.

**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-4B-Instruct-2507`

- **Type:** `Text Generation` · **NPU:** 25% · **Context:** 131072 · **Params:** 4B · **Status:** not_downloaded · **Version:** 20260911 · **Load time:** 12s · **Trending:** False · **Rank:** — · **Downloads:** 221
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-4B-Instruct-2507 is a compact 4B dense language model from Alibaba's Qwen team, updated in July 2025 to deliver stronger instruction following, reasoning, coding, multilingual coverage, and long-context understanding than the original Qwen3-4B. Its small footprint makes it a fast, low-cost choice for everyday chat, writing, and lightweight agent tasks. This deployment serves an AWQ-quantized build with a 128K-token context window.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Non-Thinking Only**

This model runs exclusively in non-thinking mode. It does not produce chain-of-thought output. No configuration is needed to disable thinking; it is simply absent. Users who want thinking mode should use a Qwen3 thinking variant instead.

**Agentic Capabilities**

Supports tool calling natively. The Qwen team recommends pairing it with Qwen-Agent for agentic workflows, which handles tool-calling templates and MCP configuration internally.

**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-8B`

- **Type:** `Text Generation` · **NPU:** 28% · **Context:** 131072 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 8s · **Trending:** True · **Rank:** — · **Downloads:** 270
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-8B is a general-purpose open-weight language model from Alibaba's Qwen team, suited for reasoning, instruction-following, creative writing, and agentic tasks across 100+ languages. Its defining feature is a built-in toggle between thinking mode for step-by-step reasoning and non-thinking mode for faster general dialogue, both available within the same model.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.



**Thinking Mode**

Thinking mode is enabled by default. In this mode the model works through a reasoning chain before producing its final response, which improves quality on math, coding, and logic tasks. Non-thinking mode disables that chain entirely, behaving like a standard instruction-following model and trading depth for speed. The mode can be set at the API level or toggled per-turn during conversation using `/think` and `/no_think` tags.

**Agentic Capabilities**

The model supports tool calling in both thinking and non-thinking modes. The Qwen team recommends using it with Qwen-Agent for tool integration, including MCP-based tool configuration.

**Language Support**

Covers 100+ languages and dialects with explicit training for multilingual instruction following and translation.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-ASR-1.7B`

- **Type:** `ASR` · **NPU:** 7% · **Context:** None · **Params:** 1.7B · **Status:** running · **Version:** 20261013 · **Load time:** 10s · **Trending:** False · **Rank:** 6 · **Downloads:** 535
- **Input:** `Audio` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-ASR-1.7B is a speech recognition model that transcribes audio to text across 30 languages, with automatic language detection built in. Built on the Qwen3-Omni audio foundation, it handles difficult inputs other ASR models struggle with: complex acoustic environments, singing voices, and songs with background music alongside standard speech.

Required by Tiiny Meeting in Agent Store for real-time transcription.


**Language Support**

30 languages including English, Chinese, Japanese, Korean, Arabic, German, French, Spanish, Portuguese, Russian, Vietnamese, Thai, Hindi, Indonesian, and more. English accents from multiple countries and regions are also supported. Language can be forced or left unset for automatic detection.

**Audio Input Types**

The model accepts speech, singing voices, and songs with background music. Both offline batch transcription and streaming inference are supported within a single model, without switching variants. Long audio transcription is supported by setting a higher token generation limit.

**Timestamp Output**

Word-level timestamps are available via the companion Qwen3-ForcedAligner-0.6B model. The forced aligner supports 11 languages and handles up to 5 minutes of audio per call.

**Architecture**

Built on Qwen3-Omni as the audio understanding foundation. The 1.7B and 0.6B variants share the same architecture and inference toolkit; the 0.6B trades some accuracy for substantially higher throughput at high concurrency.

**License**

Apache 2.0.

---

### `Qwen/Qwen3-Coder-30B-A3B-Instruct`

- **Type:** `Text Generation` · **NPU:** 55% · **Context:** 65536 · **Params:** 30B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 30s · **Trending:** True · **Rank:** — · **Downloads:** 406
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

A coding-specialized model built for developers who need strong performance on code generation, multi-file editing, and agentic coding workflows. Its MoE architecture activates only 3.3B of 30B parameters per token, keeping inference fast without sacrificing capability.

Use it in Chat, or load it for any coding agent in Agent Store.


**Agentic Coding**

Qwen3-Coder-30B-A3B-Instruct is designed specifically for agentic coding scenarios, including multi-step code editing, browser-based automation tasks, and tool-calling workflows. It uses a function call format purpose-built for coding agents.

**Fill-in-the-Middle (FIM)**

The model supports fill-in-the-middle code completion, which inserts code into existing context rather than appending to it. This is useful for completing partial functions, filling gaps within existing files, or editing specific sections without rewriting surrounding code.

**Thinking Mode**

This model runs in non-thinking mode only. It does not generate reasoning traces before answers, making responses direct and faster, suited to the latency expectations of interactive coding workflows.

**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo`

- **Type:** `Text Generation` · **NPU:** 55% · **Context:** 65536 · **Params:** 31B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 30s · **Trending:** True · **Rank:** — · **Downloads:** 349
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Coder-30B-A3B-Instruct-Turbo is an optimized variant of Qwen3-Coder-30B-A3B-Instruct, tuned for faster inference speed at a slight reduction in output accuracy. It shares the same architecture and capability profile as the base model — a coding-specialized model built for developers who need strong performance on code generation, multi-file editing, and agentic coding workflows. Its MoE architecture activates only 3.3B of 30B parameters per token, keeping inference fast without sacrificing capability.

Use it in Chat, or load it for any coding agent in Agent Store.

**Agentic Coding**

Qwen3-Coder-30B-A3B-Instruct-turbo is designed specifically for agentic coding scenarios, including multi-step code editing, browser-based automation tasks, and tool-calling workflows. It uses a function call format purpose-built for coding agents.

**Fill-in-the-Middle (FIM)**

The model supports fill-in-the-middle code completion, which inserts code into existing context rather than appending to it. This is useful for completing partial functions, filling gaps within existing files, or editing specific sections without rewriting surrounding code.

**Thinking Mode**

This model runs in non-thinking mode only. It does not generate reasoning traces before answers, making responses direct and faster, suited to the latency expectations of interactive coding workflows.

**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-Coder-Next`

- **Type:** `Text Generation` · **NPU:** 94% · **Context:** 131072 · **Params:** 80B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 45s · **Trending:** False · **Rank:** — · **Downloads:** 504
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Coder-Next is an 80B MoE model built specifically for agentic coding tasks: multi-file edits, long-horizon debugging, tool use, and recovery from execution failures across real codebases. It activates only 3B parameters per token, which puts throughput on par with a small model while the overall capacity supports complex reasoning over large codebases.

Use it in Chat, or load it for Kilocode-Tiiny and opencode in Agent Store.



**Architecture**

Built on the Qwen3-Next base, which departs from standard Transformer attention. The hybrid attention layer combines Gated DeltaNet and Gated Attention to handle ultra-long contexts without the quadratic memory cost of full self-attention. The MoE layer uses an extreme sparsity ratio: 80B total parameters, 3B activated per forward pass.

**Training Approach**

The defining design choice is agentic training rather than static code-text pretraining. Qwen synthesized 800,000 verifiable coding tasks drawn from real GitHub pull requests and paired them with executable environments. The model was trained using supervised fine-tuning on agent trajectories followed by reinforcement learning with environment feedback. This means the model learned from actual execution outcomes, not text prediction alone.

**Thinking Mode**

This model operates in non-thinking mode only. There are no chain-of-thought traces in output. Responses are immediate. The model's reasoning capability comes from training, not from an explicit thinking step at inference time.

**Agentic Integration**

The model card explicitly names scaffold compatibility with Kilo Code, Cline, Claude Code, Qwen Code, and Trae. Tool calling is a first-class capability.

**License**

Apache 2.0.

- **Supported tags (device):** ['Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-Embedding-0.6B`

- **Type:** `Text Embedding` · **NPU:** 2% · **Context:** 8192 · **Params:** 0.6B · **Status:** downloaded · **Version:** 20251231 · **Load time:** 7s · **Trending:** True · **Rank:** — · **Downloads:** 49
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Embedding-0.6B converts text into numerical representations that let applications measure semantic similarity, search documents by meaning, and classify or cluster content across more than 100 languages. At 0.6B parameters it is the smallest and most hardware-efficient model in the Qwen3 Embedding series, designed for deployments where memory and compute are constrained without sacrificing multilingual coverage or the ability to handle 32k-token inputs.

Required by Vault for document vectorization.


**Embedding Dimension**

Up to 1024. Supports Matryoshka Representation Learning (MRL), meaning output dimensions can be set anywhere between 32 and 1024. Smaller dimensions reduce storage and compute costs with a controllable accuracy tradeoff.

**Language Support**

100+ languages, including programming languages. Supports multilingual, cross-lingual, and code retrieval within the same model.

**Instruction Awareness**

The model accepts task-specific instructions prepended to queries. Omitting instructions typically reduces retrieval performance by 1 to 5%, so providing a short task description on the query side is recommended. Instructions should be written in English even for multilingual tasks, consistent with the model's training distribution.

**Architectural Basis**

Built on the same dense transformer architecture as Qwen3-0.6B (28 layers, 0.6B parameters). The embedding capability comes from fine-tuning the base language model on embedding and ranking tasks rather than a separately designed architecture.

**Task Coverage**

Text retrieval, code retrieval, text classification, text clustering, bitext mining, and semantic similarity scoring.

**License:** Apache 2.0

---

### `Qwen/Qwen3-Embedding-4b`

- **Type:** `Text Embedding` · **NPU:** 23% · **Context:** 8192 · **Params:** 4B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 12s · **Trending:** True · **Rank:** — · **Downloads:** 173
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Embedding-4B converts text into numerical representations that let applications measure semantic similarity, search documents by meaning, and classify or cluster content across more than 100 languages. At 4B parameters it sits between the lightweight 0.6B and the top-ranked 8B models in the Qwen3 Embedding series, offering stronger retrieval quality than the 0.6B model while staying lighter to run than the 8B.

Required by Vault for document vectorization.

**Embedding Dimension**

Up to 2,560. Supports Matryoshka Representation Learning (MRL), meaning output dimensions can be set anywhere between 32 and 2,560. Smaller dimensions reduce storage and compute costs with a controllable accuracy tradeoff.

**Language Support**

100+ languages, including programming languages. Supports multilingual, cross-lingual, and code retrieval within the same model.

**Instruction Awareness**

The model accepts task-specific instructions prepended to queries. Omitting instructions typically reduces retrieval performance by 1 to 5%, so providing a short task description on the query side is recommended.

**Architectural Basis**

Built on the Qwen3 dense transformer architecture (36 layers, 4B parameters). The embedding capability comes from fine-tuning the base language model on embedding and ranking tasks rather than a separately designed architecture.

**Task Coverage**

Text retrieval, code retrieval, text classification, text clustering, bitext mining, and semantic similarity scoring.

**License:**

Apache 2.0

---

### `Qwen/Qwen3-Embedding-8b`

- **Type:** `Text Embedding` · **NPU:** 18% · **Context:** 8192 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 12s · **Trending:** True · **Rank:** — · **Downloads:** 174
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Embedding-8B converts text into numerical representations that let applications measure semantic similarity, search documents by meaning, and classify or cluster content across more than 100 languages. It is the largest and highest-quality model in the Qwen3 Embedding series, ranking first on the MTEB multilingual leaderboard among models of its class, for use cases where retrieval accuracy matters more than model size.

Required by Vault for document vectorization.

**Embedding Dimension**

Up to 4,096. Supports Matryoshka Representation Learning (MRL), meaning output dimensions can be set anywhere between 32 and 4,096. Smaller dimensions reduce storage and compute costs with a controllable accuracy tradeoff.

**Language Support**

100+ languages, including programming languages. Supports multilingual, cross-lingual, and code retrieval within the same model.

**Instruction Awareness**

The model accepts task-specific instructions prepended to queries. Omitting instructions typically reduces retrieval performance by 1 to 5%, so providing a short task description on the query side is recommended.

**Architectural Basis**

Built on the Qwen3-8B-Base dense transformer architecture (36 layers, 8B parameters). The embedding capability comes from fine-tuning the base language model on embedding and ranking tasks rather than a separately designed architecture.

**Task Coverage**

Text retrieval, code retrieval, text classification, text clustering, bitext mining, and semantic similarity scoring.

**License:**

Apache 2.0

---

### `Qwen/Qwen3-Reranker-0.6B`

- **Type:** `Text Reranking` · **NPU:** 2% · **Context:** 8192 · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 14s · **Trending:** True · **Rank:** — · **Downloads:** 278
- **Input:** `Text` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Reranker-0.6B is a text reranking model that scores query-document pairs by relevance, used as a second-stage filter after an embedding model retrieves initial candidates to improve final search precision. It supports over 100 languages and accepts custom task instructions, allowing retrieval behavior to be tuned per scenario without retraining.


**How Reranking Works in a Retrieval Pipeline**

A reranker operates after a first-stage retrieval step, typically an embedding model. The embedding model retrieves a broad set of candidates quickly; the reranker then scores each candidate against the query more precisely and reorders them. Qwen3-Reranker-0.6B is designed to pair with Qwen3-Embedding-0.6B, and the two can run together on the same device.

**Instruction-Aware Scoring**

The model accepts a natural language instruction alongside each query, letting the caller define what "relevant" means for a specific task. The model card notes that adding task-specific instructions typically improves scores by 1 to 5 percentage points over instruction-free usage. Instructions should be written in English for best results, regardless of the document language.

**Language Support**

Covers 100+ languages including multiple programming languages, supporting cross-lingual retrieval where the query and document may be in different languages.

**Architecture**

Built on the Qwen3-0.6B dense foundation model. Uses a generative scoring approach: the model outputs logits over "yes" and "no" tokens for a query-document pair, and the score is derived from the difference between those two logit values.

**License**

Apache 2.0.

---

### `Qwen/Qwen3-Reranker-4b`

- **Type:** `Text Reranking` · **NPU:** 10% · **Context:** 8192 · **Params:** 4B · **Status:** not_downloaded · **Version:** 20260923 · **Load time:** 13s · **Trending:** True · **Rank:** — · **Downloads:** 71
- **Input:** `Text` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Reranker-4B is a text reranking model that scores query-document pairs by relevance, used as a second-stage filter after an embedding model retrieves initial candidates to improve final search precision. It supports over 100 languages and accepts custom task instructions, allowing retrieval behavior to be tuned per scenario without retraining.

**How Reranking Works in a Retrieval Pipeline**

A reranker operates after a first-stage retrieval step, typically an embedding model. The embedding model retrieves a broad set of candidates quickly; the reranker then scores each candidate against the query more precisely and reorders them. Qwen3-Reranker-4B is designed to pair with same-size or larger Qwen3-Embedding models for a stronger accuracy-focused retrieval pipeline.

**Instruction-Aware Scoring**

The model accepts a natural language instruction alongside each query, letting the caller define what "relevant" means for a specific task. The model card notes that adding task-specific instructions typically improves scores by 1 to 5 percentage points over instruction-free usage. Instructions should be written in English for best results, regardless of the document language.

**Language Support**

Covers 100+ languages including multiple programming languages, supporting cross-lingual retrieval where the query and document may be in different languages.

**Architecture**

Built on the Qwen3-4B-Base dense foundation model (36 layers, 4B parameters). Uses a generative scoring approach: the model outputs logits over "yes" and "no" tokens for a query-document pair, and the score is derived from the difference between those two logit values.

**License**

Apache 2.0.

---

### `Qwen/Qwen3-Reranker-8b`

- **Type:** `Text Reranking` · **NPU:** 16% · **Context:** 8192 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20260923 · **Load time:** 11s · **Trending:** True · **Rank:** — · **Downloads:** 72
- **Input:** `Text` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-Reranker-8B is a text reranking model that scores query-document pairs by relevance, used as a second-stage filter after an embedding model retrieves initial candidates to improve final search precision. It is the largest and highest-quality model in the Qwen3 Reranker series, ranking first on the MTEB multilingual leaderboard among models of its class, for use cases where retrieval accuracy matters more than model size.

**How Reranking Works in a Retrieval Pipeline**

A reranker operates after a first-stage retrieval step, typically an embedding model. The embedding model retrieves a broad set of candidates quickly; the reranker then scores each candidate against the query more precisely and reorders them. Qwen3-Reranker-8B is designed to pair with same-size or larger Qwen3-Embedding models for a stronger accuracy-focused retrieval pipeline.

**Instruction-Aware Scoring**

The model accepts a natural language instruction alongside each query, letting the caller define what "relevant" means for a specific task. The model card notes that adding task-specific instructions typically improves scores by 1 to 5 percentage points over instruction-free usage. Instructions should be written in English for best results, regardless of the document language.

**Language Support**

Covers 100+ languages including multiple programming languages, supporting cross-lingual retrieval where the query and document may be in different languages.

**Architecture**

Built on the Qwen3-8B-Base dense foundation model (36 layers, 8B parameters). Uses a generative scoring approach: the model outputs logits over "yes" and "no" tokens for a query-document pair, and the score is derived from the difference between those two logit values.

**License**

Apache 2.0.

---

### `Qwen/Qwen3-TTS-12Hz-1.7B-Base`

- **Type:** `Text-to-Speech` · **NPU:** 5% · **Context:** None · **Params:** 1.7B · **Status:** running · **Version:** 20260821 · **Load time:** 10s · **Trending:** True · **Rank:** — · **Downloads:** 358
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VoiceClone-1.7B is a text-to-speech model that clones any voice from a 3-second audio sample and synthesizes speech across 10 languages, including English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, and Italian. At 1.7B parameters, it runs efficiently on-device while delivering high-fidelity voice reproduction through a dual-track language model architecture trained on over 5 million hours of multilingual speech data.


**Core Capability**

The model accepts a short audio clip as a reference and generates speech in the cloned voice for any input text. No fine-tuning is required. The cloning operation is zero-shot: pass in 3 or more seconds of clean reference audio and the model reproduces the speaker's vocal characteristics across arbitrary content and target languages.

**Architecture**

Qwen3-VoiceClone-1.7B uses a discrete multi-codebook language model architecture paired with the Qwen3-TTS-Tokenizer-12Hz, a self-developed acoustic tokenizer that compresses and encodes speech signals while preserving paralinguistic features such as prosody, rhythm, and ambient acoustic context. Speech decoding uses a lightweight non-DiT vocoder for fast reconstruction.

**Language Support**

10 languages: English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian. The cloned voice transfers across all supported languages from a single reference sample.

**Streaming**

The dual-track architecture supports streaming generation with a first-audio-packet latency of 97ms, suitable for real-time applications.

**Relationship to Qwen3-TTS Family**

This is the Base model in the Qwen3-TTS series. It handles voice cloning specifically. Two other 1.7B variants exist for different tasks: VoiceDesign (create a new voice from a text description) and CustomVoice (9 preset high-quality voices with instruction-based emotion and tone control). The Base model does not support style instruction control; emotion and prosody reflect the reference audio, not text prompts.

**License**

Apache 2.0.

- **Supported tags (device):** ['Voice Clone'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`

- **Type:** `Text-to-Speech` · **NPU:** 7% · **Context:** None · **Params:** 1.7B · **Status:** not_downloaded · **Version:** 20260821 · **Load time:** 10s · **Trending:** False · **Rank:** — · **Downloads:** 251
- **Input:** `Text` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-CustomVoice-1.7B is a text-to-speech model that synthesizes speech from 9 predefined speaker profiles, each with distinct gender, age, and language characteristics, and accepts natural language instructions to adjust emotion and speaking style within those voices. It covers 10 languages and supports both streaming and batch inference.


**Speaker Profiles**

The model ships with 9 named speakers: 

- ryan (dynamic male with rhythmic drive, English)

- aiden (sunny clear midrange American male, English)

- vivian (bright, slightly edgy young female, Chinese)

- serena (warm, gentle young female, Chinese)

- uncle_fu (low, mellow seasoned male, Chinese)

- eric (lively slightly husky male with Sichuan dialect)

- dylan (clear natural male voice with Beijing dialect)

- ono_anna (playful light Japanese female, Japanese)

- sohee (warm emotionally rich Korean female, Korean)

Each speaker can output any of the 10 supported languages, not only their native one.

**Instruction Control**

An optional `instruct` parameter accepts a natural language description of how to deliver the speech, for example specifying anger, excitement, or a slow measured pace. This modifies prosody and emotional expression while keeping the selected speaker's timbre.

**Language Support**

10 languages: English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, and Italian. Language can be set explicitly per request or left on auto-detect.

**Architecture**

Shares the same discrete multi-codebook LM architecture and 12Hz speech tokenizer as the rest of the Qwen3-TTS family, with end-to-end synthesis latency as low as 97ms in streaming mode.

**License**

Apache 2.0.

- **Supported tags (device):** ['Custom Voice'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`

- **Type:** `Text-to-Speech` · **NPU:** 5% · **Context:** None · **Params:** 1.7B · **Status:** not_downloaded · **Version:** 20260821 · **Load time:** 10s · **Trending:** False · **Rank:** — · **Downloads:** 210
- **Input:** `Text` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VoiceDesign-1.7B is a text-to-speech model that generates speech from a text input and a natural language description of the desired voice, letting you define timbre, emotion, and speaking style in plain words rather than selecting from preset voices or providing a reference audio clip. It uses a discrete multi-codebook language model architecture with a 12Hz speech tokenizer, supporting 10 languages: English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, and Italian.



**Voice Control Method**

This is the Voice Design variant of Qwen3-TTS. Instead of cloning an existing voice from a reference audio clip (Base) or picking from a predefined speaker list (CustomVoice), you write a free-form description of the voice you want. The model interprets natural language instructions to control timbre, pitch, emotional tone, and prosody. This makes it suited for generating novel voices without any reference material.

**Architecture**

The model uses a proprietary 12Hz speech tokenizer (Qwen3-TTS-Tokenizer-12Hz) for acoustic compression, combined with a discrete multi-codebook language model as the generation backbone. This architecture supports end-to-end streaming synthesis with latency as low as 97ms.

**Language Support**

10 languages: English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian. 

**License**

Apache 2.0.

- **Supported tags (device):** ['Voice Design'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3-Vl-Embedding-2b`

- **Type:** `Text Embedding` · **NPU:** 8% · **Context:** 16384 · **Params:** 2B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 12s · **Trending:** True · **Rank:** — · **Downloads:** 122
- **Input:** `Text,Image,Video` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VL-Embedding-2B converts text, images, and screenshots into numerical representations in a single shared space, letting applications search and compare across mixed media rather than text alone. At 2B parameters it brings multimodal retrieval, matching a screenshot to a text query or clustering mixed text-and-image content, to devices too constrained for larger vision-language embedding models.

Required by Vault for document vectorization.

**Embedding Dimension**

Up to 2,048. Supports Matryoshka Representation Learning (MRL), meaning output dimensions can be set anywhere between 64 and 2,048. Smaller dimensions reduce storage and compute costs with a controllable accuracy tradeoff.

**Modality Support**

Accepts text, images, and screenshots, including inputs that mix these modalities in a single query. All inputs are embedded into the same vector space, so a text query can retrieve a matching image without a separate cross-modal pipeline.

**Language Support**

30+ languages.

**Instruction Awareness**

The model accepts task-specific instructions prepended to the input, with a default of "Represent the user's input." Adding a task-specific instruction typically improves retrieval performance by 1 to 5%.

**Architectural Basis**

Built on Qwen3-VL-2B-Instruct (28 layers, 2B parameters). The embedding capability comes from fine-tuning the vision-language base model on embedding and retrieval tasks.

**License:**

Apache 2.0

---

### `Qwen/Qwen3-Vl-Embedding-8b`

- **Type:** `Text Embedding` · **NPU:** 21% · **Context:** 16384 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20260923 · **Load time:** 28s · **Trending:** True · **Rank:** — · **Downloads:** 124
- **Input:** `Text,Image` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VL-Embedding-8B converts text, images, and screenshots into numerical representations in a single shared space, letting applications search and compare across mixed media rather than text alone. It is the largest model in the Qwen3 VL Embedding series, offering stronger cross-modal retrieval quality than the 2B model for use cases where matching accuracy matters more than model size.

Required by Vault for document vectorization.

**Embedding Dimension**

Up to 4,096. Supports Matryoshka Representation Learning (MRL), meaning output dimensions can be set anywhere between 64 and 4,096. Smaller dimensions reduce storage and compute costs with a controllable accuracy tradeoff.

**Modality Support**

Accepts text, images, and screenshots, including inputs that mix these modalities in a single query. All inputs are embedded into the same vector space, so a text query can retrieve a matching image without a separate cross-modal pipeline.

**Language Support**

30+ languages.

**Instruction Awareness**

The model accepts task-specific instructions prepended to the input. Adding a task-specific instruction typically improves retrieval performance by 1 to 5%.

**Architectural Basis**

Built on Qwen3-VL-8B-Instruct (36 layers, 8B parameters). The embedding capability comes from fine-tuning the vision-language base model on embedding and retrieval tasks.

**License:**

Apache 2.0

---

### `Qwen/Qwen3-Vl-Reranker-2b`

- **Type:** `Text Reranking` · **NPU:** 8% · **Context:** 16384 · **Params:** 2B · **Status:** downloaded · **Version:** 20260923 · **Load time:** 20s · **Trending:** True · **Rank:** — · **Downloads:** 78
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VL-Reranker-2B is a multimodal reranking model that scores query-document pairs across text and images, used as a second-stage filter after a multimodal embedding model retrieves initial candidates to improve final search precision. It pairs with Qwen3-VL-Embedding-2B in a two-stage pipeline, where the embedding model handles fast initial recall and the reranker applies more precise cross-modal scoring to reorder the results, at a smaller footprint than the 8B reranker.

**How Reranking Works in a Retrieval Pipeline**

A reranker operates after a first-stage retrieval step, typically an embedding model. The embedding model retrieves a broad set of candidates quickly; the reranker then scores each candidate against the query more precisely and reorders them. Unlike a text-only reranker, this model can score relevance across mixed text-and-image query-document pairs.

**Modality Support**

Accepts text, images, and screenshots, including combinations such as text plus image, on both the query and document side.

**Instruction-Aware Scoring**

The model accepts a natural language instruction alongside each query, letting the caller define what "relevant" means for a specific task. The model card notes that adding task-specific instructions typically improves scores by 1 to 5 percentage points over instruction-free usage.

**Language Support**

30+ languages, inherited from its foundation model.

**Architecture**

Built on the Qwen3-VL-2B-Instruct vision-language foundation model (28 layers, 2B parameters). Takes query-document pairs as input and outputs a relevance score for reranking.

**License**

Apache 2.0.

---

### `Qwen/Qwen3-Vl-Reranker-8b`

- **Type:** `Text Reranking` · **NPU:** 21% · **Context:** 16384 · **Params:** 8B · **Status:** not_downloaded · **Version:** 20260923 · **Load time:** 28s · **Trending:** True · **Rank:** — · **Downloads:** 106
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3-VL-Reranker-8B is a multimodal reranking model that scores query-document pairs across text and images, used as a second-stage filter after a multimodal embedding model retrieves initial candidates to improve final search precision. It pairs with Qwen3-VL-Embedding-8B in a two-stage pipeline, where the embedding model handles fast initial recall and the reranker applies more precise cross-modal scoring to reorder the results.

**How Reranking Works in a Retrieval Pipeline**

A reranker operates after a first-stage retrieval step, typically an embedding model. The embedding model retrieves a broad set of candidates quickly; the reranker then scores each candidate against the query more precisely and reorders them. Unlike a text-only reranker, this model can score relevance across mixed text-and-image query-document pairs.

**Modality Support**

Accepts text, images, and screenshots, including combinations such as text plus image, on both the query and document side.

**Instruction-Aware Scoring**

The model accepts a natural language instruction alongside each query, letting the caller define what "relevant" means for a specific task. The model card notes that adding task-specific instructions typically improves scores by 1 to 5 percentage points over instruction-free usage.

**Language Support**

30+ languages, inherited from its foundation model.

**Architecture**

Built on the Qwen3-VL-8B-Instruct vision-language foundation model (36 layers, 8B parameters). Takes query-document pairs as input and outputs a relevance score for reranking.

**License**

Apache 2.0.

---

### `Qwen/Qwen3.5-35B-A3B`

- **Type:** `Image-Text-to-Text` · **NPU:** 45% · **Context:** 131072 · **Params:** 35B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 27s · **Trending:** False · **Rank:** — · **Downloads:** 114
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.5-35B-A3B is a multimodal MoE model that accepts text, images, and video as input, activating only 3B of its 35B parameters per token, which keeps inference cost comparable to a 3B dense model while carrying the knowledge and capability of a much larger one. It runs in thinking mode by default, supports tool calling, and covers 201 languages.

Use it in Chat to analyze images, screenshots, and documents alongside text.


**Thinking Mode**

Enabled by default. The model generates a reasoning trace inside `<think>` tags before producing its final answer. Thinking can be disabled per request for tasks where direct responses are preferred. Both modes support tool calling.

**Multimodal Input**

Accepts text, and images through early-fusion multimodal training. The model card notes parity with or improvement over the separate Qwen3-VL line across reasoning, coding, and visual understanding tasks.

**Language Support**

201 languages and dialects.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.5-9B`

- **Type:** `Image-Text-to-Text` · **NPU:** 29% · **Context:** 131072 · **Params:** 9B · **Status:** downloaded · **Version:** 20260907 · **Load time:** 13s · **Trending:** False · **Rank:** — · **Downloads:** 349
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.5-9B is a multimodal reasoning model that accepts text and images as input, covering chat, analysis, and vision-language tasks within a single 9B-parameter model. It runs in thinking mode by default and supports over 201 languages.

Use it in Chat to analyze images, screenshots, and documents alongside text.


**Thinking Mode**

The model generates a reasoning trace before producing its final response. Thinking can be disabled per request to get direct answers for tasks that do not require deep reasoning. Both modes use the same model weights with no variant switching required.

**Multimodal Training**

The model was trained with early fusion across text and image tokens from pretraining. The model card notes this achieves parity with or improvement over the separate Qwen3-VL line on reasoning, coding, agent, and visual understanding tasks, all within a unified model.

**Language Support**

201 languages and dialects, including strong multilingual instruction following and translation capability.

**Tool Use**

Supports tool calling natively. Both thinking and non-thinking modes can call tools.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.5-9B-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 28% · **Context:** 131072 · **Params:** 9B · **Status:** not_downloaded · **Version:** 20260915 · **Load time:** 16s · **Trending:** False · **Rank:** — · **Downloads:** 140
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.5-9B-Turbo is a multimodal reasoning model that accepts text and images as input, covering chat, analysis, and vision-language tasks within a single 9B-parameter model. It runs in thinking mode by default and supports over 201 languages.

Use it in Chat to analyze images, screenshots, and documents alongside text.


**Thinking Mode**

The model generates a reasoning trace before producing its final response. Thinking can be disabled per request to get direct answers for tasks that do not require deep reasoning. Both modes use the same model weights with no variant switching required.

**Multimodal Training**

The model was trained with early fusion across text and image tokens from pretraining. The model card notes this achieves parity with or improvement over the separate Qwen3-VL line on reasoning, coding, agent, and visual understanding tasks, all within a unified model.

**Language Support**

201 languages and dialects, including strong multilingual instruction following and translation capability.

**Tool Use**

Supports tool calling natively. Both thinking and non-thinking modes can call tools.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.6-27B`

- **Type:** `Image-Text-to-Text` · **NPU:** 48% · **Context:** 131072 · **Params:** 27B · **Status:** not_downloaded · **Version:** 20260918 · **Load time:** 35s · **Trending:** False · **Rank:** — · **Downloads:** 154
- **Input:** `Image,Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.6-27B is a 27B dense multimodal model that handles text and image input, with a hybrid attention architecture that supports agentic coding, visual reasoning, and long-context tasks. It runs all 27B parameters on every forward pass, which distinguishes it from MoE siblings in the Qwen3.6 family and makes it suited for workloads where per-token reasoning depth matters more than throughput.

Use it in Chat to analyze images, screenshots, and documents alongside text.


**Architecture**

Dense 27B. Not a mixture-of-experts model. The hidden layout uses a hybrid attention pattern: each block is structured as three Gated DeltaNet layers followed by a single Gated Attention layer, with FFN after each. This replaces the quadratic standard attention that would otherwise become prohibitive at long context. A vision encoder is attached for multimodal input handling.

**Thinking Mode**

Thinking mode is on by default. The model generates a reasoning trace before producing its final response. Non-thinking mode is available via API parameters but does not use the `/think` and `/no_think` soft-switch syntax from Qwen3. A new `preserve_thinking` option allows the model to carry reasoning traces from earlier turns forward, which reduces redundant re-reasoning in multi-turn agent sessions.

**Agentic Coding Focus**

The Qwen3.6 release specifically targets agentic coding improvements over Qwen3.5: frontend workflows, repository-level reasoning, and thinking preservation across agent turns. MTP (multi-token prediction) is supported for lower-latency decoding.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.6-27B-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 55% · **Context:** 131072 · **Params:** 27B · **Status:** not_downloaded · **Version:** 20260916 · **Load time:** 125s · **Trending:** False · **Rank:** — · **Downloads:** 120
- **Input:** `Image,Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.6-27B-Turbo is a 27B dense multimodal model that handles text and image input, with a hybrid attention architecture that supports agentic coding, visual reasoning, and long-context tasks. It runs all 27B parameters on every forward pass, which distinguishes it from MoE siblings in the Qwen3.6 family and makes it suited for workloads where per-token reasoning depth matters more than throughput.

Use it in Chat to analyze images, screenshots, and documents alongside text.


**Architecture**

Dense 27B. Not a mixture-of-experts model. The hidden layout uses a hybrid attention pattern: each block is structured as three Gated DeltaNet layers followed by a single Gated Attention layer, with FFN after each. This replaces the quadratic standard attention that would otherwise become prohibitive at long context. A vision encoder is attached for multimodal input handling.

**Thinking Mode**

Thinking mode is on by default. The model generates a reasoning trace before producing its final response. Non-thinking mode is available via API parameters but does not use the `/think` and `/no_think` soft-switch syntax from Qwen3. A new `preserve_thinking` option allows the model to carry reasoning traces from earlier turns forward, which reduces redundant re-reasoning in multi-turn agent sessions.

**Agentic Coding Focus**

The Qwen3.6 release specifically targets agentic coding improvements over Qwen3.5: frontend workflows, repository-level reasoning, and thinking preservation across agent turns. MTP (multi-token prediction) is supported for lower-latency decoding.

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.6-35B-A3B`

- **Type:** `Image-Text-to-Text` · **NPU:** 47% · **Context:** 262144 · **Params:** 35B · **Status:** running · **Version:** 20261029 · **Load time:** 13s · **Trending:** True · **Rank:** 1 · **Downloads:** 1008
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:[] default:None`

**Device `desc` (verbatim):**

Qwen3.6-35B-A3B is a multimodal agentic coding model built for developers who need repository-level reasoning, tool calling, and multi-step code execution running locally. It activates only 3B of its 35B parameters per token — a sparse MoE design that delivers frontier-tier coding performance at a fraction of the inference compute, making it practical to run on consumer hardware.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.


**Multimodal Input**

The model includes a vision encoder and accepts text, and image as input. This allows it to handle screenshots, UI mockups, diagrams, and documents alongside code during agentic workflows — not just static prompt-response pairs.

**Thinking Preservation**

A new capability introduced in this release: the model can retain reasoning traces from prior turns in a multi-turn conversation rather than reasoning from scratch on each step. This reduces redundant token generation during iterative development loops and improves consistency in long agentic sessions.

**Thinking Mode**

Supports both thinking (extended chain-of-thought reasoning) and non-thinking (direct response) modes within a single model. The mode can be toggled per-request without separate model weights.

**Language Support**

Covers 100+ languages and dialects, with strong multilingual instruction following inherited from the Qwen3 training corpus (36 trillion tokens across 119 languages at the Qwen3 base level, carried forward into Qwen3.6).

**License**

Apache 2.0. Cleared for commercial self-hosting and Agent Store deployment without usage restrictions.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `Qwen/Qwen3.6-35B-A3B-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 46% · **Context:** 262144 · **Params:** 35B · **Status:** downloaded · **Version:** 20261008 · **Load time:** 18s · **Trending:** False · **Rank:** 5 · **Downloads:** 868
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:['low'] default:low`

**Device `desc` (verbatim):**

Qwen3.6-35B-A3B-Turbo is a multimodal agentic coding model built for developers who need repository-level reasoning, tool calling, and multi-step code execution running locally. It activates only 3B of its 35B parameters per token — a sparse MoE design that delivers frontier-tier coding performance at a fraction of the inference compute, making it practical to run on consumer hardware.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.


**Multimodal Input**

The model includes a vision encoder and accepts text, and image as input. This allows it to handle screenshots, UI mockups, diagrams, and documents alongside code during agentic workflows — not just static prompt-response pairs.

**Thinking Preservation**

A new capability introduced in this release: the model can retain reasoning traces from prior turns in a multi-turn conversation rather than reasoning from scratch on each step. This reduces redundant token generation during iterative development loops and improves consistency in long agentic sessions.

**Thinking Mode**

Supports both thinking (extended chain-of-thought reasoning) and non-thinking (direct response) modes within a single model. The mode can be toggled per-request without separate model weights.

**Language Support**

Covers 100+ languages and dialects, with strong multilingual instruction following inherited from the Qwen3 training corpus (36 trillion tokens across 119 languages at the Qwen3 base level, carried forward into Qwen3.6).

**License**

Apache 2.0.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** ['low']

---

### `Qwen/Qwen3.8-27B`

- **Type:** `Image-Text-to-Text` · **NPU:** 52% · **Context:** 262144 · **Params:** 27B · **Status:** downloaded · **Version:** 20261101 · **Load time:** 26s · **Trending:** False · **Rank:** 3 · **Downloads:** 1653
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:['low', 'medium', 'xhigh'] default:low`

**Device `desc` (verbatim):**

Qwen3.8-27B is a dense model built for developers and knowledge workers who need strong coding, research, and long-horizon agentic task performance without a mixture-of-experts footprint. It understands images alongside text, and its agentic tool use is strong enough to drive computer-use, browser automation, and mobile interaction tasks with high reliability across multi-step workflows.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.

**Thinking Mode**

Thinking is enabled by default, generating reasoning before the final response. It can be disabled per request, and reasoning depth can be tuned with a `reasoning_effort` parameter (low, medium, or xhigh) to balance response quality against inference cost. Reasoning traces from earlier turns are preserved by default across a conversation for consistency.

**Agentic and Tool Use**

Built for autonomous planning and multi-step execution with environment feedback, scoring strongly on computer-use, browser automation, and mobile-interaction benchmarks. Designed specifically to hold up on long-horizon software engineering and workflow-completion tasks rather than single-turn responses.

**Architecture**

A 27B-parameter dense causal language model (64 layers, not MoE) with a hybrid attention design mixing gated attention and gated DeltaNet blocks, paired with a vision encoder for image understanding.

**License:**

Apache 2.0

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** ['low', 'medium', 'xhigh']

---

### `RoyalCities/Foundation-1`

- **Type:** `Music Generation` · **NPU:** 5% · **Context:** None · **Params:** 2B · **Status:** downloaded · **Version:** 20260821 · **Load time:** 10s · **Trending:** False · **Rank:** — · **Downloads:** 232
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Foundation-1 is a text-to-sample model built for music production workflows, generating tempo-synced, key-locked loops with explicit control over instrument identity, timbral character, FX, and musical phrase structure. Unlike models that treat sound as a single flat descriptor, it separates these dimensions into composable prompt layers, allowing producers to specify not just what an instrument is but how it behaves tonally and musically.



**What it generates**

Structured musical loops designed to slot into production workflows: bar-aligned, BPM-locked, with phrase coherence driven by notation-aware prompt terms (chord progression, melody, arp, rising, complex). Not full tracks or generic textures.

**Prompt architecture**

Five independently composable conditioning layers:

**Instrument coverage**

Ten families: synths, keys, bass, bowed strings, mallets, winds, guitars, brass, vocals, plucked strings. Over 35 sub-roles including Wavetable Synth, Vibraphone, Church Organ, Choir, and Ocarina.

**Loop timing**

- Supported bar lengths: 4 and 8 bars

- Supported BPM values: 100, 110, 120, 128, 130, 140, 150

- Prompts outside these denominations produce less coherent output

**Scope**

Percussion and drums are out of scope for this release. Open-ended natural language prompts produce weaker results than structured tag prompts. Genre tagging is minimal by design, covering only Dubstep and Chiptune waveform behaviors.

**Base model**

Fine-tuned from Stability AI's Stable Audio Open 1.0. Weights: 2.43 GB at 16-bit precision.

**License**

Stability AI Community License.

---

### `SenseTime/SenseNova-U1.5-8B-MoT`

- **Type:** `Text-to-Image` · **NPU:** 48% · **Context:** None · **Params:** 8B · **Status:** downloaded · **Version:** 20260920 · **Load time:** 37s · **Trending:** False · **Rank:** — · **Downloads:** 196
- **Input:** `Text,Image` → **Output:** `Image` · **Image size:** 2048x2048 (recommended); also 2304x1728, 1728x2304, 2560x1440, 1440x2560, 2496x1664, 1664x2496, 3104x1312, 1312x3104, 2304x1792, 1792x2304; width and height multiples of 32 with (w/32)*(h/32) <= 4096 · **Steps:** 30 · **Guidance:** 0.0
- **Thinking (device):** `supported:None toggleable:None enabled_by_default:None levels:None default:None`

**Device `desc` (verbatim):**

SenseNova-U1.5-8B-MoT is SenseTime's unified multimodal model for text-to-image generation and instruction-based image editing, built for anyone who needs high-fidelity visual creation with legible on-image text. It generates directly in pixel space rather than through a separate VAE decoder, and its Mixture of Transformers design keeps attention shared across text and image tokens while splitting the feed-forward and normalization layers between them, which avoids the gradient conflicts that usually limit a single network trying to handle both understanding and generation.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 2048x2048 is the recommended, native resolution.
- These sizes are also verified to work well: 2304x1728, 1728x2304, 2560x1440, 1440x2560, 2496x1664, 1664x2496, 3104x1312, 1312x3104, 2304x1792, 1792x2304
- Other sizes may also work if width and height are each divisible by 32. See the formula below:

```
  width % 32 == 0
  height % 32 == 0
  (width / 32) * (height / 32) <= 4096
```


**Architecture**

Built on SenseTime's NEO-unify architecture, which folds understanding, generation, editing, and visual reasoning into one transformer instead of stitching together separate encoders and diffusion pipelines. Image patches are fed straight into the transformer and predicted back out in pixel space, skipping the VAE compression step that latent diffusion models rely on. This is the dense 8B checkpoint in the U1.5 family; a separate 30B MoE variant (A3B-MoT) activates only 3B parameters per token, while this one runs its full 8B on every token.

**Resolution and Generation**

Supports native high-resolution output up to 2048x2048 with coherent global structure at that scale, plus flexible aspect ratios rather than a single fixed canvas size.

**Image Editing**

Edits preserve subject identity and untouched regions of the source image. Region and object-level control is available through masks, bounding boxes, visual markers, and multi-image references, and the model follows compound instructions involving object counts, spatial relationships, and multiple constraints at once.

**Text Rendering**

Produces legible Chinese and English text inside generated images, aimed at posters and information-dense layouts rather than short captions alone.

**Checkpoints**

This repository is the RL-stage checkpoint, SenseTime's primary recommended release. A separate SFT-stage checkpoint (SenseNova-U1.5-8B-MoT-SFT) is also published for users who want the supervised fine-tuning stage instead.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** unified · **Artifact:** ['poster', 'illustration', 'photo', 'logo'] · **Alpha:** False (None) · **Text rendering:** strong · **Style:** ['general', 'high-detail'] · **Speed:** slow · **Quality:** high · **Image input:** `yes`
- **Dialect:** Instruction-shaped: what to put, where, and how it should read.
- **Sizes verified:** ['1024x1024', '2048x2048']
- **Notes:** Generates in pixel space, no separate VAE decoder. 48% NPU — needs a swap alongside a 55% planner.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at illustration, logo, poster; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: YES — the judge called the picture with the image a rectangle 5 times out of five and the control 0 times — so the image was used.

---

### `Supertone/supertonic-3`

- **Type:** `Text-to-Speech` · **NPU:** 0% · **Context:** None · **Params:** 0.1B · **Status:** running · **Version:** 20261029 · **Load time:** 6s · **Trending:** False · **Rank:** — · **Downloads:** 245
- **Input:** `Text` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Supertonic 3 is a compact on-device text-to-speech model covering 31 languages, built by Supertone for local inference with low memory overhead and fast generation. At roughly 99M parameters, it runs substantially lighter than comparable open TTS systems while maintaining competitive output quality across its supported language set.


**Architecture and Format**

The model is distributed as a set of ONNX assets comprising four components: a text encoder, duration predictor, vector estimator (diffusion denoiser), and vocoder. This pipeline design allows each stage to be optimized or replaced independently. Runtime does not require a GPU.

**Language Support**

31 languages, expanded from 5 in Supertonic 2. The model card does not enumerate all 31 languages explicitly, but the supported set includes English, Japanese, and Korean, with evaluation reported across the full language list using WER (word error rate) for alphabetic languages and CER (character error rate) for character-based scripts.

**Voice Styles**

The open-weight release includes fixed preset voice styles bundled as JSON files for immediate local inference. Zero-shot custom voice cloning from reference audio is available separately via Supertone's Voice Builder tool, which produces downloadable voice embedding files.

**Improvements Over Supertonic 2**

Repeat and skip failures — where the model loops or skips words mid-utterance — are reduced. Speaker similarity is higher across the shared 5-language set. Context handling on short and long utterances is more stable.

**License**

Model weights: OpenRAIL-M. Sample code: MIT.

- **Supported tags (device):** ['Custom Voice'] · **Reasoning levels (device):** []

---

### `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic`

- **Type:** `Text-to-Image` · **NPU:** 23% · **Context:** None · **Params:** 10B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** True · **Rank:** — · **Downloads:** 543
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 1
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Z-Image-Turbo CharacterDesignSheet is a LoRA adapter for Z-Image-Turbo that generates multi-view character design sheets in a single image, targeting concept artists, game designers, and illustrators who need structured character references rather than standalone illustrations. It combines three simultaneous perspectives, a color palette swatch, and optional facial expression variations into one coherent output.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```

**What it is**

A LoRA fine-tune of Z-Image-Turbo by Civitai creator YeiYeiArt, published December 13, 2025. File format is SafeTensor, 162 MB. License: Apache 2.0. This is the Z-Image Turbo variant of a long-running multi-model series by the same author that also covers Illustrious XL, FLUX, Pony XL, and SD 1.5.

**Core output format**

The LoRA conditions the model to produce a structured character sheet layout on a white background. A single generation can include:

* Three simultaneous views: full-body, headshot/front-face close-up, and side profile
* A color palette swatch block placed within the image, showing the character's main colors
* Multiple facial expressions per view, including exaggerated emotions such as happy, angry, and serious

**Prompting approach**

Unlike keyword-tag-based LoRAs, this model is designed around descriptive natural language prompting. The trigger word is `CharacterDesignIZT`. The author provides a structured prompt template:

1. Trigger word plus scene framing sentence: subject, art style, white background, and color palette
2. Full physical and clothing description in detail
3. Explicit instruction for the three-view layout
4. Optional facial expression instructions per view

The author notes the model understands context rather than relying on discrete tags and recommends describing poses, actions, and character traits in sentence form.

**Style coverage**

The Z-Image Turbo version is described by the author as fast and flexible across anime, semi-realistic, and cartoon styles. Style is controlled through the art style specification in the prompt rather than baked into the LoRA itself.

**Community reception**

1,258 reviews rated Overwhelmingly Positive. More than 97,700 downloads and 359,600 bookmarks at the time of retrieval. It is one of YeiYeiArt's most downloaded models across their catalog.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** specialist · **Artifact:** ['photo', 'illustration', 'icon', 'logo', 'comic'] · **Alpha:** False (None) · **Text rendering:** weak · **Style:** ['photoreal', 'realistic-people'] · **Speed:** fast · **Quality:** high · **Image input:** `no`
- **Dialect:** Name the person concretely — age range, hair, skin, fabric, expression. Describing the person as an object produces a mannequin.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** Same adapter family and NPU cost as the base. The device's own description for this model is wrong (it carries the CharacterDesignSheet text) — trust the name, not `desc`.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, illustration, comic; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `Tencent/Hunyuan3d-2.1`

- **Type:** `Image-to-3D` · **NPU:** 22% · **Context:** None · **Params:** 5.3B · **Status:** not_downloaded · **Version:** 20260920 · **Load time:** 36s · **Trending:** False · **Rank:** — · **Downloads:** 1520
- **Input:** `Image` → **Output:** `3D` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Hunyuan3D-2.1 is a two-stage image-to-3D generation system from Tencent that produces textured 3D meshes from a single input image, designed for production use in gaming, film, and industrial design. Its defining addition over the prior version is a physically-based rendering (PBR) texture pipeline that simulates light interaction at the material level, producing metallic reflections and subsurface scattering rather than flat RGB surface color.

**Pipeline Architecture**

The system consists of two separate models that run in sequence.

- **Hunyuan3D-Shape-v2-1** (3.3B parameters): a flow-matching DiT that takes a single image and generates an untextured 3D mesh.

- **Hunyuan3D-Paint-v2-1** (2B parameters): a PBR texture synthesis model that applies physically-grounded material properties to the mesh.

Both models are included in the same repository (14.9 GB total) and can be run as a combined pipeline or independently.

**PBR Texture Generation**

The texture model outputs PBR-compatible material maps rather than baked RGB color. This means the resulting asset responds correctly to different lighting environments and can be dropped directly into engines and renderers that support PBR workflows (e.g., Unity, Unreal, Blender Cycles) without re-texturing.

**License**

[Tencent Hunyuan Community License.](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE)

---

### `tencent/R3-embedding-0.6b`

- **Type:** `Text Embedding` · **NPU:** 4% · **Context:** 8192 · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20261013 · **Load time:** 7s · **Trending:** True · **Rank:** — · **Downloads:** 150
- **Input:** `Text` → **Output:** `Vector` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

R3-Embedding-0.6B is a retrieval model built specifically for agent skill routing, designed to match user queries to the right combination of tools or capabilities in an LLM agent system. Unlike general embedding models, it was trained on signals about which skills should not be retrieved together for a given query, so it captures skill compatibility as a set rather than scoring each query-skill pair in isolation.



**Two-Stage Pipeline**

This model is the bi-encoder (recall) stage of the R3-Skill retriever. It embeds a query and each skill independently, then ranks candidates by cosine similarity. It is paired with R3-Rerank-0.6B, which acts as the reranking stage using a cross-encoder to apply the compatibility signal more precisely.

**The Compatibility Problem**

Standard embedding models treat retrieval as a per-pair relevance problem. Agent skill retrieval is different: the top-K result needs to contain skills that work together for the given query. R3-Embedding was trained on a bilingual (Chinese-English) benchmark of 10,246 skills across 8 thematic domains, incorporating over 32,000 LLM rejection annotations that specify which skill combinations fail for a given query. Those rejection signals are used as compatibility supervision rather than discarded.

**Skill Input Format**

Documents are encoded as structured strings in the format "name | description | skill_md". Queries are encoded separately using the model's `encode_query` method.

**Language Support**

Trained and evaluated across four language directions within a Chinese-English bilingual setting.

**License**

Apache 2.0.

---

### `tencent/R3-rerank-0.6b`

- **Type:** `Text Reranking` · **NPU:** 3% · **Context:** 8192 · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20260923 · **Load time:** 4s · **Trending:** True · **Rank:** — · **Downloads:** 105
- **Input:** `Text` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

R3-Rerank-0.6B is the reranking stage of the R3-Skill two-stage retriever, built to refine a shortlist of agent skills by scoring each query-skill pair jointly rather than independently. Because it evaluates the full query and skill text together at once, it applies more precise compatibility judgments than the recall stage can, including which skills should not be combined for a given request.



**Two-Stage Pipeline Role**

This model operates after R3-Embedding-0.6B narrows the candidate pool via fast cosine similarity. R3-Rerank-0.6B then takes those candidates and re-scores each (query, skill) pair jointly as a cross-encoder, producing the final ranking. The two models are designed to be used together.

**Why Cross-Encoder for Compatibility**

The paper behind R3-Skill notes that the LLM rejection signal (which skills conflict for a given query) is difficult to inject into a bi-encoder objective. A cross-encoder processes the query and skill together in a single forward pass, which allows the model to use that rejection signal as graded ranking supervision. The result is more accurate detection of skill combinations that fail to serve a query correctly.

**Skill Input Format**

Skills are passed as strings formatted "name | description | skill_md", paired with the user query. The model outputs a relevance score per pair.

**Language Support**

Trained on a bilingual Chinese-English benchmark covering four language directions.

**License**

Apache 2.0.

---

### `tencent/SongGeneration-v2-large`

- **Type:** `Music Generation` · **NPU:** 28% · **Context:** None · **Params:** 4B · **Status:** downloaded · **Version:** 20260911 · **Load time:** 18s · **Trending:** False · **Rank:** — · **Downloads:** 1848
- **Input:** `Text,Audio` → **Output:** `Audio` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

SongGeneration-v2-large is an open-weight, full-song generation model from Tencent AI Lab that turns structured lyrics and style prompts into complete songs up to 4 minutes 30 seconds long, with support for English, Chinese, Spanish, Japanese, and additional languages. Its hybrid LLM-Diffusion architecture separates the tasks of musical structure and high-fidelity audio rendering, producing dual-track outputs where vocals and accompaniment can be exported independently, a capability absent in most competing open-source models.

Required by Tiiny Music in Agent Store.


**Architecture**

The model uses a two-component pipeline internally called LeLM ("composer brain") and a diffusion renderer. The language model component handles global song structure, melodic coherence, and lyric-to-beat alignment. The diffusion component then synthesizes the final audio, handling timbre, room acoustics, and instrument texture. Two token streams run in parallel: mixed tokens (combined vocal-instrument audio) and dual-track tokens (vocals and accompaniment separately encoded), which enables clean stem separation at output.

**Lyric Accuracy**

The v2-large checkpoint was trained through a three-stage pipeline: supervised fine-tuning on high-quality songs, large-scale offline Direct Preference Optimization (DPO) on approximately 200,000 positive/negative lyric pairs, and semi-online DPO with automated aesthetic scoring. This pipeline targets lyrical hallucination, the failure mode where the model generates garbled or incorrect words. Output quality is sensitive to input formatting: lyrics must follow structured section tags (verse, chorus, bridge, intro, outro) or generation quality degrades.

**Inputs and Controllability**

- **Lyrics input:** Formatted text with section labels

- **Style prompt:** Comma-separated keywords specifying genre, vocal gender, instruments, mood, BPM

- **Audio prompt:** Optional 10-second reference clip for style transfer; significantly affects output and can introduce metric variance

**Output modes:** Full song (vocals + accompaniment), instrumental only (`--bgm`), vocals only (`--vocal`), or separated dual-track stems (`--separate`)

**Context / Song Length**

Maximum generated song length: 4 minutes 30 seconds.

**License**

Custom Tencent terms (NOASSERTION on the GitHub repository). Review the LICENSE file in the official repository before any commercial deployment.

---

### `Tongyi-MAI/Z-Image-Turbo`

- **Type:** `Text-to-Image` · **NPU:** 23% · **Context:** None · **Params:** 10B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** True · **Rank:** 6 · **Downloads:** 824
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 1
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Z-Image-Turbo is a 10B-parameter text-to-image model from Alibaba's Tongyi-MAI lab, built for photorealistic generation with strong prompt adherence and accurate text rendering. It reaches full generation quality in just 8 diffusion steps, making it one of the fastest open-source image models at this quality tier.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```


**Architecture**

Z-Image-Turbo is built on a Scalable Single-Stream Diffusion Transformer (S3-DiT), which concatenates text, visual semantic tokens, and image VAE tokens into a single unified input sequence. This single-stream design maximizes parameter utilization compared to dual-stream architectures like those used in FLUX.

**Training approach**

The Turbo variant combines two post-training techniques stacked on top of the base Z-Image model. Decoupled-DMD (Distribution Matching Distillation) compresses 50-step generation into 8 steps by treating CFG augmentation as the primary distillation driver and distribution matching as a regularizer. DMDR then fuses reinforcement learning with DMD to further improve semantic alignment, aesthetic quality, and structural coherence. The result is a distilled model that has gone through both SFT and RL stages, unlike the base Z-Image which stops at SFT.

**Key capabilities**

- Photorealistic image generation with high aesthetic quality

- Accurate rendering of complex English and Chinese text within images, including mixed-language layouts

- Prompt Enhancer mode: an optional reasoning layer that expands sparse prompts using world knowledge before generation

- Guidance-free inference (guidance scale = 0), which contributes to the speed reduction

**Generation characteristics**

Because Z-Image-Turbo is a distilled model, it trades diversity for speed and visual quality. Output diversity is rated lower than the base Z-Image. It is not designed for fine-tuning; the base Z-Image or Z-Image-Omni-Base are the appropriate starting points for LoRA training or downstream adaptation.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** default · **Artifact:** ['illustration', 'photo', 'logo', 'poster', 'texture', 'icon', 'comic'] · **Alpha:** False (None) · **Text rendering:** strong · **Style:** ['photoreal', 'general'] · **Speed:** fast · **Quality:** high · **Image input:** `no`
- **Dialect:** Plain descriptive English. Subject first, then modifiers, then lighting and mood. No prompt-engineering keywords, no quality booster tokens, no comma salad.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Sizes rejected:** ['1536x1024', '1024x1536', '1792x1024'] — exceeds max transformer tokens 5760 / max_width 1536
- **Notes:** 8 steps, guidance 0.0. ~9s at 512px, ~55s at 1024px. The default for good reason — cheapest iteration loop in the catalogue.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `Tongyi-MAI/Z-Image-Turbo-Children-Drawing`

- **Type:** `Text-to-Image` · **NPU:** 23% · **Context:** None · **Params:** 10B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 5s · **Trending:** False · **Rank:** — · **Downloads:** 145
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 1
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

A LoRA fine-tune on Z-Image Turbo that converts any text prompt into output styled as a child's crayon or marker drawing. It requires no trigger word and applies the style automatically regardless of prompt content, making it usable directly with any existing prompt without modification.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```


**What it does**

Applies a children's hand-drawn art style to the generated image. The style renders subjects in the loosely proportioned, roughly colored, flat aesthetic characteristic of a young child's drawing. Content from the prompt remains legible but is fully reinterpreted through that visual register.

**Prompt behavior**

No trigger word required. Any prompt works. Style strength is controlled by the LoRA scale, with a recommended value of 1.0 and a usable range of 0.1 to 2.0. Lower values blend more of the base model's realism into the output; higher values push further into the stylized drawing look.

**Base model**

Fine-tuned adapter for Tongyi-MAI/Z-Image-Turbo. Published by ostris, trained as a demonstration for an AI Toolkit tutorial on LoRA training workflow for Z-Image-Turbo.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** style · **Artifact:** ['illustration'] · **Alpha:** False (None) · **Text rendering:** weak · **Style:** ['crayon', 'marker', 'childrens-drawing'] · **Speed:** fast · **Quality:** medium · **Image input:** `no`
- **Dialect:** None needed. The style applies automatically regardless of prompt content — the only model in the catalogue where style is guaranteed to apply.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** A LoRA that drops into any existing prompt unmodified.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at illustration; handled flat style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `trohrbaugh/Qwen3.8-27B-heretic-ara-Turbo`

- **Type:** `Image-Text-to-Text` · **NPU:** 56% · **Context:** 131072 · **Params:** 27B · **Status:** downloaded · **Version:** 20260922 · **Load time:** 32s · **Trending:** False · **Rank:** — · **Downloads:** 401
- **Input:** `Text,Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:True toggleable:True enabled_by_default:True levels:['low', 'medium', 'xhigh'] default:low`
- **Flag:** 🔴 **HIDDEN THINKING** — device says this model reasons, but its `desc` never mentions "thinking" or "reasoning". Treat it as a reasoning model when you route and budget.

**Device `desc` (verbatim):**

Qwen3.8-27B-heretic-ara is an abliterated variant of Qwen3.8-27B, a community fine-tune that surgically removes the base model's built-in refusal behavior rather than adding new capability. It keeps the same 27B dense architecture, image understanding, and long-context support as the original, but its safety guardrails have been deliberately stripped, so it will comply with requests the base model would refuse.

**What "Abliterated" Means Here**

The model was produced with Heretic (a custom fork, v1.2.0+) using a technique called Arbitrary-Rank Ablation (ARA), which targets specific weight directions across layers 26 to 56 that are responsible for refusal behavior. This is a post-training weight modification, not additional fine-tuning on new data or capabilities.

**Safety Behavior Change**

The model card reports a drop from 99 out of 100 refusals on a standard test set (base model) to 0 out of 100 refusals (this variant). In practice this means the model has no reliable built-in resistance to harmful, unsafe, or policy-violating requests, and any safety behavior would need to be enforced entirely outside the model, for example through a system prompt, input filtering, or output moderation.

**Architecture**

Inherits the base Qwen3.8-27B architecture unchanged: 27B dense parameters, 64 layers with hybrid gated attention and gated DeltaNet blocks and image understanding via a vision encoder.

**License:**

Apache 2.0

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** ['low', 'medium', 'xhigh']

---

### `vllm-sr/d3-edge`

- **Type:** `Text Classification` · **NPU:** 21% · **Context:** 16384 · **Params:** 0.6B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** False · **Rank:** — · **Downloads:** 52
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

D3 Edge (0.6B) is a member of the d3 series, a decision model built on the Qwen3.5 architecture. It reads a state (text and optionally images) together with a question and a list of options, and replies with the code of the best option, for classification and routing decisions. Call it through `POST /v1/systemone` (llama.cpp's TypeSafe-compatible System One API).

**Input and Output**

- Input: text and images (multimodal input)
- Output: the code of the chosen option, as text

**Context**

- 16K context window

**License**

Apache 2.0.

---

### `vllm-sr/d3-flash`

- **Type:** `Text Classification` · **NPU:** 34% · **Context:** 16384 · **Params:** 9B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 12s · **Trending:** False · **Rank:** — · **Downloads:** 80
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

D3 Flash (9B) is a member of the d3 series, a decision model built on the Qwen3.5 architecture. It reads a state (text and optionally images) together with a question and a list of options, and replies with the code of the best option, for classification and routing decisions. Call it through `POST /v1/systemone` (llama.cpp's TypeSafe-compatible System One API).

**Input and Output**

- Input: text and images (multimodal input)
- Output: the code of the chosen option, as text

**Context**

- 16K context window (16384 tokens); 

**License**

Apache 2.0.

---

### `vllm-sr/d3-lite`

- **Type:** `Text Classification` · **NPU:** 7% · **Context:** 16384 · **Params:** 0.8B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 8s · **Trending:** False · **Rank:** — · **Downloads:** 58
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

D3 Lite (0.8B) is a member of the d3 series, a decision model built on the Qwen3.5 architecture. It reads a state (text and optionally images) together with a question and a list of options, and replies with the code of the best option, for classification and routing decisions. Call it through `POST /v1/systemone` (llama.cpp's TypeSafe-compatible System One API).

**Input and Output**

- Input: text and images (multimodal input)
- Output: the code of the chosen option, as text

**Context**

- 16K context window (16384 tokens)

**License**

Apache 2.0.

---

### `vllm-sr/d3-mini`

- **Type:** `Text Classification` · **NPU:** 26% · **Context:** 16384 · **Params:** 4B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 6s · **Trending:** False · **Rank:** — · **Downloads:** 58
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

D3 Mini (4B) is a member of the d3 series, a decision model built on the Qwen3.5 architecture. It reads a state (text and optionally images) together with a question and a list of options, and replies with the code of the best option, for classification and routing decisions. Call it through POST /v1/systemone (llama.cpp TypeSafe-compatible System One API).

**Input and Output**

- Input: text and images (multimodal input)
- Output: the code of the chosen option, as text

**Context**

- 16K context window (16384 tokens)

**License**

Apache 2.0.

---

### `vllm-sr/d3-nano`

- **Type:** `Text Classification` · **NPU:** 25% · **Context:** 16384 · **Params:** 2B · **Status:** not_downloaded · **Version:** 20261106 · **Load time:** 6s · **Trending:** False · **Rank:** — · **Downloads:** 37
- **Input:** `Text,Image` → **Output:** `Score` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

Please update the service to version 0.1.39 before using this model.

D3 Nano (2B) is a member of the d3 series, a decision model built on the Qwen3.5 architecture. It reads a state (text and optionally images) together with a question and a list of options, and replies with the code of the best option, for classification and routing decisions. Call it through `POST /v1/systemone` (llama.cpp's TypeSafe-compatible System One API).

**Input and Output**

- Input: text and images (multimodal input)
- Output: the code of the chosen option, as text

**Context**

- 16K context window (16384 tokens); 

**License**

Apache 2.0.

---

### `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet`

- **Type:** `Text-to-Image` · **NPU:** 23% · **Context:** None · **Params:** 10B · **Status:** downloaded · **Version:** 20261106 · **Load time:** 4s · **Trending:** True · **Rank:** — · **Downloads:** 1135
- **Input:** `Text` → **Output:** `Image` · **Image size:** 512x512 (fastest), up to 1536x1536 · **Steps:** 8 · **Guidance:** 1
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

A LoRA fine-tune built on Z-Image Turbo, designed to generate character design sheets with multiple perspectives, facial expressions, and a color palette swatch in a single image output. It targets concept artists, game character designers, and illustrators who need a structured multi-view reference from a single natural-language prompt.

Use it in Chat to generate images directly in conversation.

**Supported image sizes**

- 512x512 is the fastest, native resolution. 
- These sizes are also verified to work well: 432x768, 768x432, 768x480, 480x768, 640x480, 480x640, 864x1536, 1536x864, 1536x960, 960x1536, 1024x1024, 1280x960, 960x1280
- Other sizes may also work if width and height are each divisible by 16. See the formula below:

```
  width % 16 == 0
  height % 16 == 0
  ceil_to_32((width / 16) * (height / 16)) <= 9216
```


**What it outputs**

Each generation produces a single image containing three character views (full body, headshot, facial close-up), a set of facial expressions, and a color palette swatch on a white background. The layout is structured for use as a production reference sheet.

**Prompt approach**

This LoRA does not use tag-based prompting. It responds to natural language descriptions of the character's appearance, clothing, pose behavior, and art style. A structured four-block prompt format is recommended:

1. Trigger word + subject description + art style + background context
2. Physical characteristics and clothing in prose detail
3. Pose and perspective instructions (three views)
4. Facial expression variants per view

**Base model and variants**

Fine-tuned on Z-Image Turbo. The same LoRA concept exists in versions for Illustrious XL, FLUX, PONY XL, and SD 1.5, each published as separate Civitai model variants. The Z-Image Turbo version uses the trigger word `CharacterDesignIZT`.

**Style coverage**

Handles anime, semi-realistic, and cartoon styles. Style is controlled via the art style descriptor in the prompt rather than separate trigger words.

**Output resolution**

Square outputs (`1024x1024`) are the default recommendation for this version.

**License**

Apache 2.0.

**Measured overlay (`app/data/overlay.yaml`, provenance: `d,m` — device + probe 2026-11-07):**

- **Role:** specialist · **Artifact:** ['character_sheet', 'icon', 'logo', 'photo', 'poster', 'comic', 'illustration'] · **Alpha:** False (None) · **Text rendering:** weak · **Style:** ['character-reference'] · **Speed:** fast · **Quality:** high · **Image input:** `no`
- **Dialect:** Ask for the sheet explicitly: multiple views, expression variants, a palette swatch. One character, consistent across panels.
- **Sizes verified:** ['512x512', '1024x1024', '1280x768', '1152x768', '1024x768']
- **Notes:** For concept artists and game character designers.

MEASURED ON THE APPLIANCE 2026-11-07: measured good at icon, logo, photo, poster, comic, illustration; handled flat and realistic style; rendered an opaque background; got text right.

MEASURED 2026-11-07: IMAGE INPUT: NO — the appliance refuses an image for this model.

---

### `zai-org/GLM-4.7-Flash`

- **Type:** `Text Generation` · **NPU:** 57% · **Context:** 65536 · **Params:** 31B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 35s · **Trending:** True · **Rank:** — · **Downloads:** 443
- **Input:** `Text` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

GLM-4.7-Flash is a 30B-A3B MoE text generation model from Zhipu AI, designed for agentic tasks including multi-turn tool use, web browsing, and software engineering workflows, with only 3B parameters activated per token for efficient on-device inference. Thinking mode can be enabled or disabled per request.

Use it in Chat, or load it for any agent in Agent Store that requires a text generation model.


**Thinking Mode**

Thinking is enabled by default. The model generates a reasoning trace before producing its final response. Thinking can be disabled per request for tasks where direct answers are preferred. Tool use is available in both modes.

**Tool Use**

Natively supports function calling with a dedicated tool-call parser. Tool use is available in both thinking-enabled and thinking-disabled modes.

**Context and Language**

Primarily covers English and Chinese.

**License**

MIT.

- **Supported tags (device):** ['Reasoning', 'Tool Use'] · **Reasoning levels (device):** []

---

### `zai-org/GLM-OCR`

- **Type:** `Image-to-Text` · **NPU:** 4% · **Context:** 65536 · **Params:** 0.9B · **Status:** not_downloaded · **Version:** 20260922 · **Load time:** 7s · **Trending:** False · **Rank:** — · **Downloads:** 245
- **Input:** `Image` → **Output:** `Text` · **Image size:** — · **Steps:** — · **Guidance:** —
- **Thinking (device):** `supported:False toggleable:False enabled_by_default:False levels:[] default:None`

**Device `desc` (verbatim):**

GLM-OCR is a document OCR model from Zhipu AI that extracts text, formulas, and tables from images, covering complex layouts found in real business documents including scanned files with seals, code blocks, and dense tables. At 0.9B parameters, it handles two distinct tasks: raw content extraction (text, formula, and table recognition) and structured information extraction where the output conforms to a user-defined JSON schema.


**Two Operating Modes**

The model accepts two prompt types that produce fundamentally different outputs. Document Parsing mode extracts raw content as text or Markdown, with separate prompt variants for plain text, mathematical formulas, and tables. Information Extraction mode accepts a JSON schema as the prompt and returns structured data fields populated from the document image, suitable for processing forms, IDs, invoices, and similar records.

**Architecture**

Built on the GLM-V encoder-decoder architecture with three components: the CogViT visual encoder trained on large-scale image-text data, a lightweight cross-modal connector with token downsampling, and a GLM-0.5B language decoder. The full document parsing pipeline adds a two-stage layout analysis layer using PP-DocLayout-V3 before recognition, which is available via the official SDK. Model-only inference (via Transformers, vLLM, SGLang, or Ollama) skips the layout layer and is suited for single-image recognition and information extraction tasks.

**Training Approach**

The model uses Multi-Token Prediction loss combined with full-task reinforcement learning, which the model card identifies as improving recognition accuracy and generalization across diverse document types.

**License**

MIT (model weights). The full pipeline SDK integrates PP-DocLayoutV3, which is Apache 2.0. Both licenses apply when using the SDK.

---

## Provenance & how to re-verify

- **Live catalogue:** `GET /api/v1/models/online_models` on your own Tiiny — 92 records on 2026-11-10, every `fullname`, `npu_usage`, `context_window`, `thinking`, `desc` above. This doc was built from one `curl` with `Authorization: Bearer $TIINY_API_KEY` to `http://tiinyhost.local` (raw JSON ships alongside this document as `data/catalogue.json`).
- **Image measurements:** `tiiny-image-agency/app/data/overlay.yaml` — 17 entries (`15 generators + 2 prompt enhancers`), each `notes` carries "MEASURED ON THE APPLIANCE 2026-11-07" with `image_input` verdict (yes/no/unknown, 5× judge) and pixel transparency. The research probes are in `app/src/tis/research.py` + `imaging.py`.
- **Thinking flags:** read at route time via `GET /v1/models` (resident) and `GET /api/v1/models/online_models` (store). The router does not keep a hand table because the flag has been wrong before — see "The toggle flag is a hint" above.
- **What has moved since 2026-11-01:** `gemma-4-26B-A4B-it` NPU 78% → 37%, `Qwen/Qwen-Image-2.1-Uncensored-Quantized` stays 0% NPU, `InternScience/Sage-A1.5-Turbo` stays 48%/262K, etc. Where this doc and your device disagree, your device is right.

## For publication (after your review)

- This file lives for review in your `SatanDocuments` folder and a copy in the vault at `tiiny-discovery/` — both are local review copies.
- **Do not hand-edit the per-model tables** to fix a drifted NPU/context — re-run the `curl` above and rebuild via the build script (kept alongside the raw JSON) so the rebuild is reproducible.
- When you are ready, the publish step is the standard vault publisher targeting `AI_Articles/tiiny-model-catalogue/` or your chosen prefix — after your edits, run the publish scan to catch any bearer/path that slipped into a `desc` block.
