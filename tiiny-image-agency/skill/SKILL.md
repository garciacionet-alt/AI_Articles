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
tis roles           # the TALKER and the JUDGE: which models, which can SEE an image
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

`tis alpha` reads a PNG and reports what fraction of it is fully
transparent, partly transparent, and opaque. It only READS the file — never
re-encodes, never resizes — because a round trip through an image library
is exactly where a transparent background quietly becomes an opaque one. Use
it to check a cut-out instead of trusting the prompt.

## The Judge — and Whether It Can See

The agency has two conversational roles. The **talker** turns the request
into a requirement vector. The **judge** decides whether the result is
good. By default they are the same model, and the judge sees only the
prompt.

That is enough to catch a prompt that does not ask for what was requested.
It is **not** enough to catch a generation that simply came out wrong — and
a blind judge will invent a defect rather than admit it cannot see, and
every invented defect costs another generation.

Some models on the appliance can see an image. `tis roles` lists them all:

```bash
tis roles                                  # the guide
tis roles --critic Qwen/Qwen3.6-35B-A3B    # a judge that SEES
```

**When to switch the judge:** if the request is about how the image looks
and the first result is close but wrong — a transparent background that is
not transparent, text that is mangled, a subject that is not there — a
judge that can see will find it, and a judge that reads the prompt will not.

**Read the fit line before you choose.** The guide says whether the judge
and a generator fit in the NPU pool together, measured against the 81%
ceiling that a generation needs to actually run. A judge that does not fit
will be swapped in and out, and the generation may fail outright.

The talker is not part of that sum: it has already written the scene
description by the time the image is made, so its weights are swapped out
while the judge and the generator have the pool to themselves.

A judge that sees is slower and costs more. It is also the only kind that
can answer "what is actually wrong with this image".

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

## Things Worth Knowing

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

**The critique judges the PROMPT or the PIXELS — depending on the judge.**
Two roles hold the conversation: the CONVERSATION AGENT, which turns a
request into a requirement vector, and the CRITIC, which judges the
result. They are separate choices, and `tis roles` shows which model holds
each one right now.

A judge that cannot see an image judges the PROMPT. It catches a prompt
that does not ask for what the requirements demand, and nothing else. It
can also be wrong about a defect it cannot see, so when it reports a
failure, check the failure against the requirement vector before acting on
it — a complaint about a transparent background on an image that has one
costs a generation and changes nothing.

A judge that CAN see an image judges the PICTURE. The appliance's chat
API is OpenAI-compatible and its own models are image-text-to-text, so an
image is handed to them as a content part — the device adapter's
`vision(model, question, image_bytes)` method does it, and the research
loop already uses that method to characterise models.

Choose one with `tis roles --critic <model>`. The catalogue it prints
lists every conversational model on the appliance, marks the ones that can
see, and gives each one's NPU cost. Read it rather than trusting a list
written down anywhere — including here — because the appliance's catalogue
moves.

**The talker, the judge and a generator have to fit in one pool.** The
appliance has a single NPU pool and a model load is a swap, so the three
things a job needs — the model that plans, the model that judges, and the
model that draws — must fit in it together, or one of them is swapped out
and back between stages.

One model holding both roles counts ONCE. The default has the same Coder
planning and judging, so it needs 55% + 23% = 78% of the pool, not 133%.

A judge that can see costs more, and the default talker is too big to
leave room for it: 55% + 47% + 23% = 125%. The fix is not to give up on
seeing — it is to move the talker to a smaller model. A 29% talker with
the same judge and generator is 99%, which fits. `tis roles` reports the
total for the current choice and names the model that would make it fit.

Those percentages are this appliance's, measured. Run `tis roles` for the
numbers as they are now.

**A suggestion from the critique may repeat something the generator already
knows.** The judge sees the size in the requirements, so it may suggest
"add 1024x1024 to the prompt" — and the image model will render that text
into the picture. When you apply a critique, keep the change to something
the prompt did not already say.

## What Not to Do

- Do not call the appliance's generation endpoint directly.
- Do not assume the judge can see the image. Run `tis roles` and read the
  JUDGE line: "text only" means the critique is a claim about the prompt,
  and a claim about the pixels needs a judge that was told it could look.
- Do not pick a judge that does not fit the pool. The guide reports the
  fit; if the total is over 100%, the judge gets swapped in and out, or
  never runs at all.
- Do not re-encode, resize or re-save a PNG that came out of the agency.
  The alpha channel is the product; a round trip through an image library
  is exactly where a transparent background quietly becomes an opaque one.
- Do not hand-roll a prompt to iterate when `tis iterate` exists.
- Do not start a second generation while one is running. The appliance
  serves one inference at a time, and the agency serialises them — but a
  second agent with the device is a different story, and the cross-agent
  lock is what stops it.
- Do not treat the plan's model choice as a promise about the alpha. The
  plan says a transparent background is required; only `tis alpha` on the
  finished file says whether it is.
- Do not apply a critique's suggestion verbatim when it restates the size,
  the format, or anything else the generator already received.

## The Work Surface

While the agency is running, a person can watch it work:

    http://127.0.0.1:8080

That is the same port as the API. The screen shows the conversation, the
canvas, which model made the picture and why, the NPU meter, and a banner
whenever the appliance is swapping models or downloading one. The user can
iterate from the screen as well as from the CLI.

If someone asks "what is it doing?" or "can I see it?", that URL is the
answer. It is also the fastest way for a person to see the appliance's
state — the NPU meter reads the real resident set, live.

The surface is an HTTP client of the API, exactly like the CLI. It holds no
credential and never touches the appliance. If you are checking that a
change went through the API rather than around it, look for the credential
and the appliance URL in the CLI and in the surface: neither may have one.

## The Appliance Is Shared — Read the Board Before You Take It

The device holds one NPU pool and every agent on the machine shares it. A
generation is a swap: it evicts whatever was resident, including another
agent's conversation model. The agency takes the cross-agent lock and
restores what was there, but only for the duration of the job.

**Before you touch the device, read the board.** The AMC keeps one file,
`hot.md`, that records what is in flight across every agent, and it carries
a `tiiny-device-lock` block naming whoever holds the appliance. That block
is the ONLY thing that tells another agent the device is taken.

Do not work it out from your own processes. Your own processes are
evidence about *your* footprint, and the question is usually about
someone else's. Read the board, then read the appliance's own resident set.

**A lock that announces nothing is a lock nobody respects.** If you hold
the device, the notice must be on the board; if the notice is stale, it
misleads in both directions — the board said "busy" an hour after the lock
expired, and said "free" while the lock was held.

**Shared state resolves against the BASE Hermes home, not the profile.**
`HERMES_HOME` points at a profile directory when a profile runs, and a
profile's own `.env` does not carry the shared settings. Anything shared
across agents — the lock, the hold file, the plan, the appliance bearer,
the vault path — must be read and written against `~/.hermes`, not against
`HERMES_HOME`. A shared file resolved against the profile is a file
another agent never sees, and the symptom is silence: a lock taken, and
nothing announced.

### Releasing the device means four things, not two

When you are done, "released" is a claim about four artefacts, and only
one of them is your process:

| artefact | where |
|---|---|
| the hold file | `~/.hermes/tiiny-hold` — emptied or removed |
| the lock | `~/.hermes/tiiny-lock.json` — released, not expired |
| the plan | `~/.hermes/tiiny-plan.json` — cleared |
| the notice | the `tiiny-device-lock` block in `hot.md` — removed |

Leave a stale one and the next agent inherits your intent. The hold and
the notice are the two that mislead: a stale hold keeps a model resident
that nothing wants, and a stale notice keeps every other agent out of a
free device.

The commands, the board's format, the keepalive, and the quiescence
check are in
[references/appliance-sharing.md](references/appliance-sharing.md).

Two things follow:

- **A generation evicts the chat model.** The conversation model comes back
  afterwards, but the other agent pays for it. If someone is mid-task on the
  same appliance, say that your generation will briefly displace it.
- **When a delegation needs the appliance's coder model, load it first and
  hold it.** A warm model that is not held gets evicted by the watchdog
  within minutes, and the next request falls back to a paid provider with no
  error. Reserve the device, load the model, write the hold, and start the
  keepalive — then dispatch. Check the delegation manifest afterwards to
  confirm which model actually served the task.

## Related

- `tiiny-model-routing` — using the appliance to host delegated sub-agents.
  The two skills share one device, and the lock in that skill is what keeps
  them from colliding.
