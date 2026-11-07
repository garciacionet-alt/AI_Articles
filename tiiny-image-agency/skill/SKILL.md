---
name: tiiny-image-agency
description: "Generate images on the local Tiiny Pocket Lab through the Tiiny Image Agency. Plans the request, resolves the model, generates on the appliance, reads the critique, and reports which model made the image and why."
version: 1.1.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
# The Agency's Python runs on Linux. The vendor toolchain it shells out
# to is macOS-built, so a Linux host needs the Linux CLI build - see
# references/portability.md.
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

6. **Check `planner_source` before you trust a plan.** A plan carries
   `"planner_source": "llm"` or `"fallback"`. If it says `fallback`, the
   words in the request were thrown away — the keyword planner only
   knows the catalogue's vocabulary, so a style nobody declares comes
   back as "general" and never reaches the prompt. This looks exactly
   like a routing bug and is not one.

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

## The Judge — It Always Sees

The agency has two conversational roles. The **talker** turns the request
into a requirement vector. The **judge** decides whether the result is
good. They are separate choices, and they have different needs.

**The judge is always a vision model.** A judge that reads text only
judges the PROMPT, and a prompt judge does not fail loudly — it invents a
defect rather than admit the limit. Every invented defect becomes an
instruction to regenerate, so a blind judge costs a generation each time
it guesses wrong. The agency refuses a text-only judge and says why:

```
openai/gpt-oss-20b cannot see an image, so it cannot be the judge. A judge
that reads text only judges the PROMPT, and it will invent a defect rather
than admit the limit. Choose a model marked as seeing one — 'tis roles'
lists them.
```

So `tis roles` lists only models that can see, under **Judges**, and
`tis roles --critic <model>` accepts only those. The default judge is
`Qwen/Qwen3.6-35B-A3B` at 47%.

**The talker does NOT have to see.** It writes the plan and never looks at
a pixel, so a small text model is right for it — the default is
`openai/gpt-oss-20b` at 27%, which the watchdog already holds, so planning
costs no swap at all. A 27% talker with the 47% judge and a 23% generator
is 70%, under the 81% ceiling that a generation needs to actually run.

**Read the fit line before you choose.** The guide says whether the judge
and a generator fit in the NPU pool together, measured against the 81%
ceiling. A judge that does not fit will be swapped in and out, and the
generation may fail outright.

The talker is not part of that sum: it has already written the scene
description by the time the image is made, so its weights are swapped out
while the judge and the generator have the pool to themselves.

## Timing — and Why You Must Not Interrupt It

The appliance takes **54 to 200 seconds** for one image:

| model | NPU | time |
|---|---|---|
| Z-Image-Turbo (the default) | 23% | ~55 s |
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

**The critique judges the PIXELS.** Two roles hold the conversation: the
CONVERSATION AGENT, which turns a request into a requirement vector, and
the CRITIC, which judges the result. They are separate choices, and
`tis roles` shows which model holds each one right now. The critic always
sees the image.

The appliance's chat API is OpenAI-compatible and its own models are
image-text-to-text, so an image is handed to them as a content part — the
device adapter's `vision(model, question, image_bytes)` method does it, and
the research loop already uses that method to characterise models.

Choose the critic with `tis roles --critic <model>`. The catalogue it
prints lists every conversational model on the appliance, marks the ones
that can see, and gives each one's NPU cost. Read it rather than trusting
a list written down anywhere — including here — because the appliance's
catalogue moves.

**The talker, the judge and a generator have to fit in one pool.** The
appliance has a single NPU pool and a model load is a swap, so the three
things a job needs — the model that plans, the model that judges, and the
model that draws — must fit in it together, or one of them is swapped out
and back between stages.

One model holding both roles counts ONCE — a vision model can do both jobs,
and then the pool pays for it once.

The talker is the cheap one and should stay cheap. A 27% talker with the
47% judge and the 23% default generator is 70% during judging, which runs.
The sum that does NOT fit is the one that adds the talker to the judge and
the generator while the image is being judged — 125% — and it is the wrong
question, because the talker's weights are gone by then. `tis roles`
reports the total for the current choice and names the model that would
make it fit.

Those percentages are this appliance's, measured. Run `tis roles` for the
numbers as they are now.

**A suggestion from the critique may repeat something the generator already
knows.** The judge sees the size in the requirements, so it may suggest
"add 1024x1024 to the prompt" — and the image model will render that text
into the picture. When you apply a critique, keep the change to something
the prompt did not already say.

## What Not to Do

- Do not call the appliance's generation endpoint directly.
- Do not try to make a text-only model the judge. It is refused, and the
  refusal is the correct behaviour: a judge that cannot see invents
  defects. `tis roles` lists only the models that can.
- Do not sum the talker, the judge and the generator against the ceiling.
  The talker is swapped out before the image is judged. The sum that
  matters is judge + generator.
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

### What the surface does that a chat box does not

- **It asks before it generates.** The plan opens a dialog naming the
  model and why, lists the alternatives with their NPU cost and whether
  they are on the device, says what a download would cost, and WAITS. A
  generation costs a minute and sometimes three, so a model the user did
  not need is worse than a slow one.
- **You can drop an image into it.** The file becomes the source of the
  next request, so the next request is an EDIT of that image rather than
  a new picture — the difference between "make this better" and "make me
  something else". The upload route is `POST /v1/assets` with the PNG
  bytes as the body; there is no multipart form.
- **It tells you where the file is.** The path is under the image, in the
  lineage, and in the `asset.ready` event.
- **It has a card for every model.** `GET /v1/models/card?model_id=`
  gives three parts kept apart: what the device **advertises** it does,
  what we **measured**, and what we have **noticed** that the device does
  not say. A card exists for every model — "not measured yet" is a fact
  the card reports, not a 404. The third part is the point.

An agent can also say where the finished PNG should land:
`POST /v1/generate` and `POST /v1/iterate` take `output_path`, and the
finished file is written there too, byte for byte. The agency's own copy
is written either way.

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

## Running It Somewhere Else

The Agency is an HTTP client of the appliance, and the appliance is a
network device. The app itself — the API, the CLI, the browser surface —
is pure Python and runs anywhere that can reach the device.

**What does not travel is the vendor toolchain**, because the vendor CLI
is the only way to load a model into NPU memory: the device's management
API has no load, unload or resident-set route. So a second machine needs
the vendor CLI built for its platform, the `script` pty wrapper spelled
its way (`script -q /dev/null cmd` on BSD, `script -q -c "cmd" /dev/null`
on util-linux), and a lock that is not POSIX-only.

**Point the base URL at the device's own address on a second machine.**
The vendor hostname resolves to a loopback address because a local proxy
answers on it — that is a property of the client machine, not of the
device. Both of the device's APIs answer directly on its address.

**The hold, the lock and the plan are per-machine paths.** They
coordinate agents sharing one machine and nothing else. A second machine
driving the same appliance needs coordination the per-machine files
cannot provide.

The findings, the checks that establish them, and the recipe are in
[references/portability.md](references/portability.md).

## Related

- `tiiny-model-routing` — using the appliance to host delegated sub-agents.
  The two skills share one device, and the lock in that skill is what keeps
  them from colliding.
