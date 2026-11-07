---
name: tiiny-image-agency
description: "Generate images on the local Tiiny Pocket Lab through the Tiiny Image Agency. Plans the request, resolves the model, generates on the appliance, reads the critique, and reports which model made the image and why."
version: 1.0.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [tiiny, images, generation, local-inference, agency, alpha, transparent]
---

# Tiiny Image Agency

Make an image on the local Tiiny appliance, through the app that manages
the appliance for you.

The appliance is a single shared inference stream with one NPU pool. A
model load is a **swap**: loading one evicts whatever was there. The agency
exists so that a request does not have to know any of that — it holds the
device, loads what the job needs, restores what was there, and tells you
which model it chose and why.

## When to Use

- Someone asks for an image, an icon, a logo, a cut-out, a poster, a photo.
- A job needs a transparent background, a specific artefact, or a revision.
- Someone asks *which* model would make this, before spending a generation.

## The Rules, in Priority Order

1. **Never call the Tiiny's `/v1/images/generations` directly.** Go through
   the agency. A direct call evicts the resident chat model, and you will
   not know which model you just displaced — and neither will the next
   agent that wants the device.

2. **Describe the request in terms of the artefact, not the aesthetic.**
   "app icon, transparent background" routes; "nice modern fox" does not.
   The artefact vocabulary is the registry's, and the resolver filters on
   it.

3. **Iterate with `tis iterate`, never by re-running generate with a new
   prompt.** The iteration path takes the asset's own requirements and
   applies the dialect translation again. A hand-rolled prompt loses the
   translation — and the dialect is the difference between a flat PNG and a
   usable asset.

4. **Read the critique.** The orchestrator judges the image against the
   requirement vector and says what missed. A second attempt with the
   critique applied beats a third blind attempt.

5. **Report the model.** Say which model produced the asset and why. The
   model choice is the interesting part of the answer.

## Before You Start

Check the agency is up:

```bash
tis health
```

If it answers, carry on. If it says the agency is not running, tell the
user — it has to be started with `tis serve` — rather than reaching for
the device yourself.

## The Commands

```bash
tis plan "I need an app icon of a fox head, flat, transparent background"
tis generate "I need an app icon of a fox head, flat, transparent background"
tis iterate ast_0123456789abcdef "make the ears sharper and the fill warmer"
tis models          # the catalogue: artefact, NPU cost, alpha, text rendering
tis npu             # what is resident right now, and the NPU used
tis health          # is the app alive, is the appliance reachable
tis alpha file.png  # how much of this PNG is actually transparent
```

If `tis` is not found, it is installed at `~/.hermes/venvs/tis311/bin/tis`
and linked into `~/.local/bin`.

`tis plan` costs nothing but a planner call and tells you the model, the
NPU cost, whether a swap is required, and the resolver's justification.
**When a request is ambiguous, plan first.** It is much cheaper than a
generation, and the justification often tells you the request was
under-specified.

`tis generate` writes the PNG into the current directory and prints the
path. `tis iterate` takes the asset id from that path.

## Timing — and Why You Must Not Interrupt It

The appliance takes **54 to 200 seconds** for one image:

| model | NPU | time |
|---|---|---|
| Z-Image-Turbo (the default) | 26% | ~55 s |
| Qwen-Image-2.1 (the flagship, native alpha) | 62% | ~200 s |

`tis generate` prints each progress event as it arrives. **Let it run.** A
generation that is interrupted leaves the appliance in a state somebody
else has to clean up, and the work is lost.

If the command is going to take a while, say so before you start it. A user
who has been told "about a minute" is patient; a user who has been told
nothing and sees a hanging terminal is not.

## What to Report Back

- **The asset** — the path to the PNG, and what it shows.
- **The model** — which one, and its NPU cost.
- **The justification** — why that model. `tis plan` prints it in full and
  it is worth passing on: it is the resolver explaining itself.
- **The critique** — if there was one. What missed, and what to change.

## Two Things Worth Knowing

**Transparency is the expensive thing — and it has to be asked for
plainly.** Only the flagship `Qwen-Image-2.1` renders a genuine alpha
cut-out; everything else is opaque whatever the prompt says.

But the flagship's alpha is **prompt-dependent**, and a measurement of
one image is not a property of the model. Measured on the appliance,
same model, same icon:

| request | fully transparent |
|---|---|
| "app icon of a fox head, flat, transparent background" | **0%** — a white background, not a cut-out |
| the same icon, iterated with "make the background fully transparent so it is a clean cut-out" | **40.76%** |

So if the request needs a cut-out, **say "transparent background" in
those words**, and then CHECK the result rather than trusting the plan:

```bash
tis alpha the-file.png     # fully transparent / partly / opaque, measured
```

A cut-out is measurable and the measurement is the truth. A model that
answers "transparent background" in the prompt is not the same thing as
a transparent background in the file.

If the request needs a transparent background, the plan will say so and
it will cost a swap: the planner is released for the generation and
restored afterwards.

**The model that made the image is in the lineage.** The asset's lineage
holds the requirements, the model, the prompt that was actually sent, the
attempts, and the critique. It is the record of what happened, and it is
worth reading when a request comes back asking for a change.

## What Not to Do

- Do not call the appliance's generation endpoint directly.
- Do not re-encode, resize or re-save a PNG that came out of the agency.
  The alpha channel is the product; a round trip through an image library
  is exactly where a transparent background quietly becomes an opaque one.
- Do not hand-roll a prompt to iterate when `tis iterate` exists.
- Do not start a second generation while one is running. The appliance
  serves one inference at a time, and the agency serialises them — but a
  second agent with the device is a different story, and the cross-agent
  lock is what stops it.

## The Work Surface

While the agency is running, a person can watch it work:

    http://127.0.0.1:8080

That is the same port as the API. The screen shows the conversation, the
canvas, which model made the picture and why, the NPU meter, and a banner
whenever the appliance is swapping models or downloading one. The user
can iterate from the screen as well as from the CLI.

If someone asks "what is it doing?" or "can I see it?", that URL is the
answer. It is also the fastest way for a person to see the appliance's
state — the NPU meter reads the real resident set, live.

## Related

- `tiiny-model-routing` — using the appliance to host delegated sub-agents.
  The two skills share one device, and the lock in that skill is what keeps
  them from colliding.
