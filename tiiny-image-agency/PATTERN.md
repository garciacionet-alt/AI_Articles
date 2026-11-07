# The Pattern

This is the portable design. Nothing here is specific to one appliance or one
repository — it is what to build if you have a pool of models on shared
hardware and want to hand them to an agent without the agent having to know
anything about them.

## The shape of the problem

You have several models. They are all local. They cannot all be resident at
once. A caller asks for a result in words.

Three failures are available, and all three are common:

1. The caller picks a model and gets the wrong thing. It never learns why.
2. The caller picks a model that cannot be loaded right now, and either
   fails or quietly evicts something that was working.
3. Two callers race for the pool and corrupt each other's residency.

The design below removes each failure by moving a decision to a place that
can see the whole picture.

## 1. Words become a requirement vector

A free-text request is ambiguous in ways that are expensive. "a logo for my
coffee shop" does not say whether it needs transparency, whether it has text
in it, or whether it needs to be 1024 pixels square.

**The planner** turns the request into a structured vector. Every field has a
closed vocabulary — the set of artifacts a generator can actually produce, the
set of styles, the alpha requirement, the text requirement, the size.

```python
class RequirementVector(BaseModel):
    artifact: str          # icon | logo | photo | poster | comic | infographic | illustration
    style: str             # flat | realistic | painterly | ...
    alpha: str             # required | no
    text_in_image: str     # yes | no
    size: str              # 1024x1024
    edit_op: str           # none | background_remove | object_remove | outpaint | detail_regen
    speed: str             # normal | fast
    hard: list[str]
```

Two rules make this trustworthy:

**The vocabulary is closed, and it is the vocabulary the resolvers can
satisfy.** An early version included `prompt_expansion` in the artifact list,
which no image model produces. The planner, given a request it could not map,
offered it — and the request then failed at the last possible moment. A
planner that can name something no generator does is a planner that will
eventually be asked for it.

**There is a deterministic fallback.** If the planner model is not resident,
or times out, or returns something unparseable, a keyword matcher produces a
vector instead. The result is worse and it says so — the plan carries
`planner_source: "fallback"` — but the request still happens.

## 2. The resolver chooses, and explains

**The resolver is deterministic.** No model call, no sampling. The same
request against the same registry and the same resident set always produces
the same choice. That is what makes it reviewable: you can write a table of
thirty-six cases and assert the winner for each one.

It scores candidates against the requirement vector, and it has **hard
filters** that are not preferences:

| filter | meaning |
|---|---|
| capability | the model can do what the request demands |
| availability | it is downloaded, so it can actually be loaded |
| residency | it fits the pool with what must stay |

The availability filter is not obvious and it is not optional. A catalogue
built from the store lists models that are *listed* and models that are
*on disk*, and they are different sets. A resolver that picks from the first
set produces a plan that cannot execute.

**Hard filters do not fall back.** If nothing satisfies a hard requirement,
the answer is "no loadable model", not "the nearest thing that is close
enough". A request that needs a transparent background must not be answered
by an opaque model with a note.

**The choice comes with prose.** Not "chose X" — the reasoning, the cost, and
the alternatives that would also have worked:

> *Tongyi-MAI/Z-Image-Turbo was selected for this request. It occupies 78%
> of the NPU pool together with the planner. It co-resides with the planner,
> so the conversation stays alive during generation. black-forest-labs/FLUX.2
> would also satisfy the request, but it is not downloaded on this appliance,
> so it cannot be loaded.*

That paragraph is a product feature. It is the difference between an agent
that trusts the system and an agent that has to check.

## 3. Residency is one transaction

A model load is not a load. It is a **transition**: it evicts whatever does
not fit, and what it evicts may be another agent's work.

So the transaction is:

```
1. acquire the watchdog lock
2. acquire the cross-agent lock
3. write the hold file          <- before the load, not after
4. load the planned wave
5. generate
6. judge
7. restore the required set
8. clear the hold, and verify it is clear
```

**The hold is written before the load.** If the process dies between the load
and the hold, the appliance is in a state nobody owns. The hold first, then
the load, means a crash leaves a stale hold that the next agent can see and
clear — a recoverable mess rather than an invisible one.

**Restoring is part of the transaction, not a cleanup.** The planner was
resident before the request and must be resident after it. A system that
leaves the planner evicted has broken the next request too.

**"The hold is cleared" is a claim that must be checked.** Reading the file
back is the difference between reporting and hoping.

### The ceiling, and why admission is not proof

This is the part that is specific to shared accelerator hardware, and it is
the part that is most often gotten wrong.

A composition can be **accepted** by the device and then **fail to execute**.
Measured on one appliance:

| composition | admitted | executed |
|---|---|---|
| planner (55%) + fast image (23%) = 78% | yes | yes, ~55 s |
| planner (55%) + medium image (26%) = 81% | yes | yes, ~55 s |
| planner (55%) + slow image (30%) = 85% | yes | **no** — HTTP 500, `150004` |
| flagship image (62%) alone | yes | yes, ~200 s |

A client sees "accepted" for the 85% row and then waits for a picture that
never comes. The acceptance is not a promise about execution.

The fix is a **ceiling** the planner respects before it builds the wave, and
an eviction plan that accounts for it. The manager does not ask "does this
model fit?" It asks "does this model plus everything that must stay plus
the judge fit?" — and when it does not, it says which model had to go.

**The judge is part of the wave, not an afterthought.** The critic needs its
own model resident. If the critic does not fit alongside the generator, the
image is still delivered and the record says the critique was skipped and
why. Delivering an image without a critique is a degraded result; refusing
to deliver because the critic would not fit is a broken one.

## 4. Events are scoped to a job

The event stream is how a caller learns what is happening. Two properties
make it usable:

**A late subscriber catches up.** The bus replays recent session events to a
subscriber that connects after the work was queued. Without this, a client
that opens the stream late misses the whole job.

**And that replay is a trap.** It carries the terminal events of *earlier*
jobs in the same session. A consumer that does not filter by job id will
render the previous job's asset — quickly, confidently, and without
generating anything.

So two rules, and they are not optional:

1. **Open the stream with the job id**, and ignore any event whose job id is
   not yours.
2. **Events that carry no job id at all** — the swap events — cannot be
   scoped that way. Treat them as display-only: they may be shown, and they
   must never decide anything.

The second rule is the one that gets missed. Three of the fourteen event
types have no job id, and a consumer that acts on them unconditionally will
print a line about a job that finished an hour ago.

### The event vocabulary

| event | carries | job id |
|---|---|---|
| `job.queued` | kind | yes |
| `job.started` | — | yes |
| `plan.ready` | model, justification, planner_source | yes |
| `swap.started` | model, also_resident | **no** |
| `swap.finished` | model | **no** |
| `download.started` | model, size_bytes | yes |
| `download.progress` | model, progress | yes |
| `download.finished` | model, size_bytes | yes |
| `generate.started` | model, prompt, size | **no** |
| `generate.finished` | model, size | **no** |
| `critique.ready` | model, prompt | **no** |
| `asset.ready` | asset_id | yes |
| `job.finished` | asset_id | yes |
| `job.failed` | error | yes |

Five of the fourteen have no job id. That is the whole shape of the trap.

## 5. The bytes are bytes

If the output is a PNG with an alpha channel, then every path that carries it
must treat it as opaque bytes.

- **Never decode and re-encode.** The CLI writes the bytes it received. The
  browser puts them in an `<img>` over a CSS checkerboard.
- **Never round-trip through an image library.** Not to resize, not to
  measure, not to "normalize" it. A decode/encode cycle is exactly where a
  transparent background quietly becomes an opaque one.
- **Measure the alpha by reading the structure.** The PNG's own header
  carries the dimensions, the bit depth and the colour type; the pixel data
  carries the transparency. Both can be read without a decoder, and reading
  them does not touch the file.

The last point matters for a product reason: if the tool can *measure* the
alpha, then a claim like "this model renders transparency" can be checked
instead of believed. One flagship model was measured at 44.86% transparency
on one prompt, then at **0%** on a different prompt for the same image, and
then at **40.76%** after the prompt was rewritten to ask for a cut-out in
those words. The alpha is prompt-dependent. A model property stated as a
percentage is a measurement pretending to be a law.

## 6. A judge's suggestion is an instruction, not a note

If a critic's suggested changes are appended to the prompt and sent to the
generator — which is the natural design, and the one that lets a critic
actually improve anything — then **every change is a command to the image
model**, and the model will obey it literally.

The failure is specific and worth remembering. A critic asked for the
size to be added to the prompt. The size was already an *argument* to the
model, not prompt text, so there was nothing to fix — but the prompt was
built from the requirement vector, which mentions the size, and the
critic correctly noticed that the prompt did not. The delivered image had
the size **drawn across it as a caption**, because the model read
"1024x1024" as something to render rather than something to obey.

Three rules fall out of it.

**The critic must not be asked to fix what is already an argument.** If the
size is passed as a parameter, then a requirement vector listing the size
invites the critic to ask for it in the prompt. Say so explicitly in the
critic's instructions, and mark the parameter as a parameter.

**Filter the suggestions anyway.** Guidance is not a guarantee — a critic
is a model, and models do what they are asked. A suggestion asking for the
output's dimensions should be dropped, in every way one is written:
`1024x1024`, `1024 x 1024`, `at 1024 by 1024`, "the image size", "the
output dimensions".

**Make the filter narrow.** Bare words like "resolution" and "size" appear
in legitimate art direction — "a grainy low-resolution photograph", "the
size of the subject in frame is too small" — and a filter that drops those
throws away real advice. Match the *request for the output's dimensions*,
not the vocabulary of dimension.

And one more: **a suggestion set that is entirely unusable is a broken
verdict, not a failure.** If every change was dropped, there is nothing to
act on, and regenerating against a change you cannot send burns a
generation to produce the same picture. That verdict is inconclusive.

## What to take from this

The transferable parts, in order of how much they matter:

1. **Make the choice explainable, and show the explanation.** It is the
   difference between a system you trust and one you audit.
2. **Make the residency a transaction, and hold the lock across all of it.**
   Half a transaction is a race with extra steps.
3. **Scope events to the job, and treat unscopable events as display-only.**
4. **Treat acceptance as not-execution**, and enforce a ceiling yourself.
5. **Measure the thing, and publish the measurement.** A catalogue built from
   a vendor's own description is a catalogue of beliefs.
6. **Remember that a machine reading your instructions is not reading your
   notes.** Whatever a critic says becomes a command to a generator.
