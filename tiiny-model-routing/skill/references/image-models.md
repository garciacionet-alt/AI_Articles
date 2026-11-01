# Image models on the device

The appliance runs the image models as well as the chat ones, and picking the
right one is the difference between an image that works and an afternoon.

The controller picks from what is actually on the device:

```bash
python3 scripts/tiiny_ctl.py image "a realistic portrait of an engineer"
python3 scripts/tiiny_ctl.py image "a logo with the word ARC in it"
python3 scripts/tiiny_ctl.py image "a character turnaround, three views"
python3 scripts/tiiny_ctl.py image "..." --load      # load it as well
```

It prints the model, the reason it was chosen, the NPU share, and whether the
model is on the device and currently resident.

## The models, and what each is for

Figures read from the device on 2026-11-01.

| Model | NPU | Role | On the device? |
|---|---|---|---|
| `Tongyi-MAI/Z-Image-Turbo` | 26% | **The default.** Photorealism, fast iteration, and the one that renders text accurately | downloaded |
| `HiDream-ai/HiDream-O1-Image-Dev` | 30% | Maximum fidelity — fur, foliage, reflections, complex light | downloaded |
| `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` | 26% | A realistic person — skin, hair, fabric | downloaded |
| `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` | 26% | A character turnaround in ONE image | downloaded |
| `fal/FLUX.2-klein-4B-Background-Remove` | 26% | Background removal — **an adapter, not a generator** | downloaded |
| `Qwen/Qwen-Image-2.1` | 58% | Native transparency (RGBA) and up to 10 reference images | not downloaded |
| `Tongyi-MAI/Z-Image-Turbo-Children-Drawing` | 26% | Crayon and marker style | not downloaded |
| `black-forest-labs/FLUX.2-klein-4B` | 26% | The base FLUX.2 klein generator | not downloaded |
| `baidu/ERNIE-Image-Turbo` | 27% | A second photoreal generator | not downloaded |
| `SenseTime/SenseNova-U1.5-8B-MoT` | 48% | A larger unified creation model | not downloaded |

**This skill never downloads a model.** A model that is not on the device
cannot be loaded, so `tiiny_ctl.py image` says which models are missing and
lets you download them yourself with `tiiny download <model>`.

## Name the job, not the picture

The question is not "what should it look like" but **what is the image for**.
The same subject needs a different model depending on what it is for, and
the cues the controller matches on are the job, not the subject.

| The need | The model | Why |
|---|---|---|
| A logo, a title card, anything with **legible text** | `Tongyi-MAI/Z-Image-Turbo` | It is the one that renders text accurately |
| Photorealism and speed | `Tongyi-MAI/Z-Image-Turbo` | ~9s at 512x512, ~55s at 1024x1024 |
| Maximum fidelity — fur, foliage, reflections, complex light | `HiDream-ai/HiDream-O1-Image-Dev` | ~34s at 1024x1024, up to 2048x2048 |
| A character turnaround — perspectives, expressions, palette in one image | `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` | A LoRA built for exactly that |
| A realistic person — skin, hair, fabric | `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` | A LoRA for realism |
| Cutting a subject out of an EXISTING photo | `fal/FLUX.2-klein-4B-Background-Remove` | Isolates the subject without masking |
| Transparency — a sticker, a logo on nothing | `Qwen/Qwen-Image-2.1` | The only one that outputs native RGBA |

## The trade

Z-Image-Turbo is the default for good reason. HiDream is noticeably better
on fine detail and about 3x slower, so it earns its keep only when detail
*is* the subject. Z-Image's 8-step distillation is what makes iterating
cheap.

**An image model evicts the chat models.** The NPU is one shared pool: the
chat, ASR, TTS and embedding models all get displaced. So image work belongs
inside a reserved batch — reserve, load the image model, generate, release —
and the release puts everything back.

## Sizes are strict

The transformer-token ceiling bites before the pixel limit does.

| Size | Z-Image-Turbo |
|---|---|
| 1024x1024, 1280x768, 1152x768, 1024x768, 512x512 | OK |
| 1536x1024, 1024x1536 | 400 — exceeds max transformer tokens 5760 |
| 1792x1024 | 400 — exceeds max_width 1536 |

HiDream goes to 2048x2048, and accepts 1536x1024 and 1024x1536.

**Hermes's `image_generate` tool sends 1536x1024 for "landscape" and
1024x1536 for "portrait" — both fail here.** Use "square", or call the
generator with an explicit size, for example:

```bash
python3 tiiny_image.py --prompt "a red fox in snow" --size 1024x1024 --out fox.png
```

That helper talks to the same `/v1/images/generations` endpoint Hermes's
tool uses, so the output is interchangeable with it.

## Look at the result

A prompt for "a blue circle on white" comes back on a light-grey ground.
Read the image back before claiming success.

## Other kinds of work the device does

The same controller reaches the document and audio models, which are chosen
by job in the same way.

| The need | The model | NPU | On the device? |
|---|---|---|---|
| Read text out of a scan, a screenshot or a photo | `PaddlePaddle/PP-OCRv6-Medium` | 1% | downloaded |
| Where the blocks are on a page — tables, columns, figures | `PaddlePaddle/PP-DocLayoutV3` | 20% | downloaded |
| A song from a description | `tencent/SongGeneration-v2-large` | 28% | downloaded |
| A quick instrumental bed | `RoyalCities/Foundation-1` | 5% | downloaded |
| 3D from an image | `microsoft/TRELLIS.2-4B` | 6% | not downloaded |
| 3D from an image | `Tencent/Hunyuan3d-2.1` | 22% | not downloaded |
