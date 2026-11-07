---
title: Tiiny Image Agency
type: folder-readme
status: active
project: tiiny-image-agency
created: 2026-11-06
updated: 2026-11-06
---

# Tiiny Image Agency

**A demonstration of what is possible using the Tiiny Pocket Lab as an engine
for developers.**

You describe an image in words. A local model works out what you actually
meant, the system picks the right one of the image models already sitting on
your own hardware, loads it, generates, and helps you iterate — while telling
you, legibly, what it is doing and why.

## The problem this solves

An image API is easy to call and hard to trust. The request you send is
interpreted by a model you cannot see, against a catalogue of models you do
not control, on hardware whose limits you cannot observe. When it goes wrong
you get a picture and no explanation.

The appliance makes that worse in one specific way, and better in all the
others. It is worse because the models are **already downloaded** — a
catalogue of fourteen image generators on a laptop, each one costing a slice
of a shared NPU pool. Only a few fit at once. Choosing the wrong one means
evicting the one that was working, and the eviction is not free.

It is better because everything that would be opaque is locally observable.
The catalogue is a file. The pool has a number. The residency is a set. And a
model that is resident can be asked what it is good at.

## The three things it does

**It turns words into a requirement vector.** "A flat app icon of a fox head
with a transparent background" becomes: artifact `icon`, style `flat`, alpha
`required`. The planner is a local model, and it has a deterministic fallback
for when it is unavailable — because a request that silently changes meaning
when the planner is down is worse than one that fails.

**It chooses the model and explains itself.** The resolver is deterministic:
the same request and the same resident set always produce the same choice,
and the answer comes with prose that says what the trade-off was. Not "chose
X" — *why* X, what it cost, and what else would have done.

**It manages the residency as one transaction.** Acquire the lock, write the
hold, load the wave, generate, judge, restore, clear the hold. Every one of
those steps, or none of them.

## What it looks like

There is a CLI for an agent, an API for a script, and a screen for a person:

```bash
tis plan "an app icon of a fox head, flat, transparent background"
tis generate "an app icon of a fox head, flat, transparent background"
tis iterate ast_0123456789abcdef "make the ears sharper"
tis alpha the-icon.png          # how much of this PNG is actually transparent
```

```
POST /v1/generate                 -> 202 {"job_id": "..."}
GET  /v1/session/default/events   -> an SSE stream of what the appliance is doing
GET  /v1/assets/ast_0123456789abcdef   -> the PNG, byte for byte
POST /v1/assets                   -> upload a PNG you already have, as the
                                     source of an edit
GET  /v1/models/card?model_id=... -> what a model claims, what we measured,
                                     what we have noticed
```

An agent can also say **where the finished PNG should land**:

```
POST /v1/generate  {"request": "...", "output_path": "/tmp/final.png"}
```

The agency's own copy is written either way; the copy at that path is the
same bytes, never a re-encode.

And the same port serves a browser surface that shows the conversation, the
canvas, which model made the picture and why, the NPU meter, and a banner
whenever the appliance is swapping models or downloading one.

Four things it does that a chat box does not:

- **It asks before it generates.** The dialog says which model was chosen
  and why, lists the alternatives with their cost, and waits. A generation
  costs a minute and sometimes three.
- **You can drop an image into it.** The file becomes the source of the next
  request, so the next request is an *edit* of that image rather than a new
  picture.
- **It tells you where the file is.** The path is under the image, in the
  lineage, and in the events.
- **It has a card for every model.** What the device advertises, what we
  measured, and what we have noticed that the device does not say.

## The hard constraint

Every design decision in this project comes down to one measurement.

**The appliance has one NPU pool and it is finite.** The planner occupies 55%
of it. A fast image model occupies 23%. Together that is 78%. The flagship
model that can actually render a transparent background occupies 62% *on its
own*, so it cannot run beside the planner at all — the request has to
interrupt the conversation to happen.

Measurements on the appliance, not estimates:

| composition | outcome |
|---|---|
| planner + fast image model (78%) | works, ~55 s |
| planner + medium image model (81%) | works, ~55 s |
| planner + slow image model (85%) | **fails**, HTTP 500 / `150004` |
| flagship alone (62%) | works, ~200 s, planner evicted |

The failure at 85% is the important row. The appliance **accepts** that
composition and then **fails** to execute it, and the difference between
accepting and executing is not something a client can see from the outside.
Admission is not proof.

So the residency manager plans the whole wave, including what to evict, and
enforces a ceiling. And when the flagship runs, the planner is released for
the duration and restored afterwards.

## Two things that are easy to get wrong

**The alpha channel is the product, and a round trip destroys it.** A
transparent background survives being written to disk and read back. It does
not survive being decoded to pixels and re-encoded. Every path in this
project that touches a generated PNG treats the bytes as bytes: no decode,
no resize, no re-save. The CLI measures the alpha by reading the PNG's own
structure.

**A late subscriber sees the previous job's events.** The event bus replays a
session's recent events to a subscriber that connects after the work was
queued — a real feature, because otherwise a client that opens the stream
late misses everything. The sharp edge is that the replay carries the
terminal events of *earlier* jobs too. A consumer that does not filter by
job id will show the wrong picture: an earlier asset, returned in under a
second, without generating anything at all.

That bug shipped in the CLI once, and again in the first version of the
browser surface. The filter is now the first thing in both files, and there
is a test that fails if it is removed.

## The judge, and whether it can see

The critic decides whether the result is good. It is a **model the user
chooses** — and every model it can be is one that can **see** an image.

A **blind** judge sees the prompt and the requirement vector. It can catch a
prompt that does not ask for what was requested. It cannot catch a
generation that simply came out wrong — and asked to judge something it
cannot see, it will invent a defect rather than admit the limit. Every
invented defect becomes an instruction to regenerate. The first live run of
this project burned three generations chasing a defect the blind judge had
invented, because it could not look at the image it was judging.

So the project **refuses** a blind judge, and says why:

```
openai/gpt-oss-20b cannot see an image, so it cannot be the judge. A judge
that reads text only judges the PROMPT, and it will invent a defect rather
than admit the limit. Choose a model marked as seeing one — 'tis roles'
lists them.
```

The refusal carries the reason because a refusal that explains itself can be
acted on and one that does not cannot. The default judge is
`Qwen/Qwen3.6-35B-A3B` at 47%, which sees.

**The conversation agent is a separate setting and is unaffected.** It writes
the plan and never looks at a pixel, so a small text model is the right model
for it — and a 27% one costs no swap at all, because the watchdog already
holds it.

The appliance already knew which models could see: it labels them
`Image-Text-to-Text` and gives them an input of `Text,Image`. The project
needed a second catalogue to hold that — the image registry holds the
*generators*, and no text model is in it. The conversational catalogue holds
26 models, 16 of which can see.

**The fit is the judge plus a generator, against the 81% ceiling** — not all
three roles. The conversation agent writes the scene description *before*
the generation starts, so by the time the image is made its weights have
been swapped out and the judge and the generator have the pool to
themselves. A 47% seeing judge and the 23% default generator is 70%, and
that runs. Summing all three roles gives 125% and the false conclusion
that a seeing judge is unaffordable.

A verified live run, judged by `Qwen/Qwen3.6-35B-A3B`:

```
VERDICT: pass
REASON: The image is an illustration of a lighthouse, has a solid
        background (not transparent), contains no text, and the style
        aligns with the general prompt.
```

"A solid background" and "no text" are observations of the image. The judge
could not have inferred them from the prompt.

**One trap worth naming.** The appliance's generalist is a *reasoning*
model: it thinks before it answers, and the thinking is not part of the
reply. With the critic's long prompt it spent the entire token budget
thinking and returned nothing — which looks exactly like a model that
cannot see. The judge now asks for no thinking at all, because a judge
needs a verdict, not a deliberation.

## Running it on Linux and Windows — a contribution wanted

**This project was built and tested on macOS, and it will not run on Linux
or Windows as it stands. A contributor with either machine would be doing
the most useful thing anyone could do with it.**

The reason is worth stating precisely, because it is not the usual reason.
The application itself is portable: pure Python, four dependencies
(`pydantic`, `httpx`, `fastapi`, `uvicorn`), no compiled extensions, no
macOS APIs anywhere in the resolver, the planner, the registry, the
orchestrator or the asset store. **The appliance is network-reachable and
platform-neutral** — it answers both its inference API and its management
API directly on the LAN, at an ordinary IP address.

Three things stop it, and all three are small.

**1. The `tiiny` CLI is a macOS binary.** Loading and unloading a model
is not an HTTP call — it goes through the vendor's CLI, and the
management API has no load or unload route. The build used here is
`tiiny-cli-darwin-arm64`. The CLI itself takes a `--device-address` flag
and works against the appliance's IP from any machine, so a Linux or
Windows build of the same CLI is most of what is needed. The vendor's
own local proxy carries a `WindowsCompatListener` setting, which
suggests they build for more than one platform.

**2. `script -q /dev/null` for the pty.** The CLI dies with *"could not
open a new TTY"* unless it is given a pseudo-terminal, so every load,
unload and download is wrapped in `script`. macOS ships the BSD
version; Linux ships util-linux `script`, which takes the same idea with
different flags. A platform check, or dropping `script` for a Python
pty, fixes it.

**3. `fcntl.flock` for the watchdog lock.** The application takes a lock
so the appliance's own watchdog cannot evict a model in the middle of a
generation. `fcntl` is POSIX, so Linux is fine and Windows needs
`msvcrt.locking` or a `filelock` dependency.

There is also a configuration detail that matters more than it looks: the
default base URL is a hostname that resolves to `127.0.0.1` **on the
machine where this was built**, because a local macOS proxy answers on
it. On another machine that name will not resolve, and the appliance has
to be addressed by its IP instead. The base URL needs to come from the
environment.

**A rough estimate of the work:** on Linux, a day. The three changes
above are around thirty lines in total, and none of them touch the
resolver, the planner or the orchestrator — the parts that carry the
ideas. On Windows, longer, and gated on a Windows build of the vendor's
CLI existing.

### One design constraint a porter must decide about

The hold file and the watchdog lock live in a per-machine home directory.
That is fine while everything runs on one machine, and it is what makes
the coordination work — the application and the appliance's watchdog
exclude each other correctly. But it means that **running the Agency on
one machine while the watchdog runs on another silently loses that
coordination**: neither would see the other's lock, and two agents could
drive the appliance at once.

So there are two honest answers, and the choice belongs to whoever ports
it:

- **Run everything on the same machine.** The current design is already
  correct, and the port is the work.
- **Move the lock somewhere both machines can see** — a shared
  filesystem, or a lock served by the appliance itself. This is a better
  design and a much bigger piece of work, and it is worth doing
  deliberately rather than by accident.

### How to contribute

The application is under `examples/agency/`, and the parts that carry
the design are documented in **[PATTERN.md](PATTERN.md)** and
**[IMPLEMENTATION.md](IMPLEMENTATION.md)**. A port is mostly a matter of
making the three changes above and confirming that the suite still
passes — `cd examples/agency/app && python -m pytest`.

Two things a port must preserve, because they are the parts that took
the work to get right:

- **The bytes are never re-encoded.** An image goes to the appliance and
  comes back as the same bytes. A round trip through an image library is
  exactly where a transparent background quietly becomes an opaque one.
- **The judge has to see.** A critic that cannot see the image judges the
  prompt instead, and a prompt judge invents a defect rather than admit
  the limit. Every invented defect costs a generation.

If you port it, open a pull request with what you found. The appliance
is the hard part of this project and it does not change; the port is
three known edits and a machine you already own.

## What is in this folder

- **[PATTERN.md](PATTERN.md)** — the portable design: the requirement vector,
  the resolver contract, the residency transaction, the job-scoped event
  stream. What to copy if you build something like this.
- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** — the concrete build: the
  project layout, the API contract, the registry, how to run it.
- **[architecture.html](architecture.html)** — the architecture diagram. Open it
  in a browser; it is one self-contained file, no build step and no
  dependencies.
- `scripts/` — the registry builder and the research loop, standalone.
- `examples/` — the application itself: the package, the tests, the screen.
- `skill/` — the Hermes skill, the procedure an agent follows.

### Running the screen

The work surface is three static files with no build step. To see it without
the API running, serve the folder and open the page:

```bash
cd examples/agency/app/web
python3 -m http.server 8081
# then open http://127.0.0.1:8081/index.html
```

With the API running, it is served on the same port as the API itself —
<http://127.0.0.1:8080>. Either way the page finds the API on its own
origin, and `?api=` points it somewhere else.

## Measured, not assumed

Every number in this article came from the appliance. The catalogue, the NPU
costs, the execution boundary, the alpha percentages, the generation times,
the context behaviour, the download throughput — all measured, with the
command that measured it recorded alongside it.

That matters more here than it would in a normal project, because the
manufacturer's own description of a model cannot be trusted: the device
describes one of its models as producing text correctly, and a probe of
eleven generated images found it mangled text every time. The catalogue says
what the vendor believes; only a probe says what the model does.
