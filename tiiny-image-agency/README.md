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
```

And the same port serves a browser surface that shows the conversation, the
canvas, which model made the picture and why, the NPU meter, and a banner
whenever the appliance is swapping models or downloading one.

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

## What is in this folder

- **[PATTERN.md](PATTERN.md)** — the portable design: the requirement vector,
  the resolver contract, the residency transaction, the job-scoped event
  stream. What to copy if you build something like this.
- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** — the concrete build: the
  project layout, the API contract, the registry, how to run it.
- `scripts/` — the registry builder and the research loop, standalone.
- `examples/` — the application itself: the package, the tests, the screen.
- `skill/` — the Hermes skill, the procedure an agent follows.

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
