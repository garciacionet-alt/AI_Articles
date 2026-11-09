---
name: tiiny-model-routing
description: "Run delegated sub-agents on the Tiiny device. Chooses the model that fits each subtask, loads it, locks the device against other agents, supervises the child, verifies its work, and releases the device."
version: 2.1.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [tiiny, delegation, model-routing, local-inference, agents, locking, lifecycle, thinking]
---

# Tiiny Model Routing

Let a manager agent use the Tiiny appliance as the host for its sub-agents:
choose the model that fits each subtask, load it, keep other agents off the
device while it works, supervise the child, check what it produced, and hand
the device back.

The shape of it: **a frontier model on a paid plan supervises, and the device
does the work.** MiniMax-M3 stays in the main loop — that is where judgement
and conversation belong — and everything token-heavy goes down to the box on
the LAN. The paid subscription stops paying for volume, and the diversity of
the Model Store becomes available to every batch.

## When to Use

- A delegation batch mixes different kinds of work — a research sweep, a
  filesystem index, a code edit, a browser run, a summary.
- The subtasks are big enough that the paid provider's cost and rate limits
  matter.
- Another agent in the AMC might want the device at the same time, and the
  two need to be able to see that it is spoken for.
- You need an image and want the right image model rather than the default.

Don't use for: a single-model deployment where every subtask is the same kind
of work (set `delegation.model` and stop), or non-Tiiny providers (the
mechanism is provider-agnostic, but the tier table is Tiiny-specific).

## Prerequisites

- A Tiiny device reachable on the LAN, with its bearer available as
  `TIINY_API_KEY` (Hermes keeps it in `~/.hermes/.env`; the controller finds
  it there, in the environment, or in the vault's credentials file).
- The `tiiny` CLI at `~/.local/tiiny/bin/tiiny` for the load and unload
  commands.
- The routing backend plugin installed (see [references/backend.md](references/backend.md)), and
  `delegation.backend: tiiny-router` set in the active profile's config.
- **Models already downloaded.** The skill never downloads anything. It
  chooses and loads from what is already on the device, and a model that is
  not downloaded cannot be loaded — the plan will say so and pick something
  else. Download models yourself with `tiiny download <model>`.

## The two halves

| | What it is | What it owns |
|---|---|---|
| **The router** (`plugin/`) | A delegation backend. Hermes calls it once per subtask. | Choosing the model for each subtask, and its reasoning mode. |
| **The controller** (`scripts/tiiny_ctl.py`) | A command-line tool the manager agent drives. | The plan, the lock, the load, the restore, the catalogue refresh. |

The split is not tidiness. The delegation plugin has exactly one hook —
`route_task`, called once per subtask *before* any child runs — and there is
no "batch finished" hook. A plugin therefore cannot know when it is safe to
evict a model, and cannot know whether a sibling agent is already using the
device. Loading has to be a step the manager agent takes and can see.

The two halves meet at one file, the **plan** (`~/.hermes/tiiny-plan.json`).
The controller writes it when it plans the batch; the router reads it when it
routes each subtask. That is how a specialist the controller just loaded
becomes the specialist the child actually runs on.

## The lifecycle

```
  1  evaluate     what kind of work is this?
  2  pick         which model fits it?
  3  fit          do the models for the whole batch fit in one NPU pool?
  4  reserve      is the device free, and is it ours for the duration?
  5  load         put the batch's models on the device
  6  plan         one wave at a time — the device serves one stream
  7  supervise    watch the child, do not lose the thread
  8  verify       check the artifact, not the summary
  9  release      put the device back and let other agents in
 10  refresh      check the Model Store for models worth adding
```

Each step has a checkable completion criterion. Do not skip ahead — a skipped
step here fails quietly, and a quiet failure on this device looks exactly
like success.

## Quick Reference

### The tiers

| Tier | Model | NPU | Context | Reasoning | On the device? |
|---|---|---|---|---|---|
| `research` | `InternScience/Sage-A1.5-Turbo` | 48% | 262144 | switch | downloaded |
| `research` (alt) | `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 | switch | downloaded |
| `index` | `openai/gpt-oss-20b` | 27% | 131072 | **levels only** | **resident** |
| `code` | `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` | 55% | 65536 | none | downloaded |
| `code` (alt) | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 | switch | downloaded |
| `code` (alt) | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | switch | **resident** |
| `code` (heavy) | `Qwen/Qwen3-Coder-Next` | 94% | 131072 | none | not downloaded |
| `browser` | `Qwen/Qwen3.8-27B` | 52% | 262144 | switch | downloaded |
| `draft` | `Qwen/Qwen3.5-9B` | 29% | 131072 | switch | downloaded |
| `general` | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | switch | **resident** |

The Reasoning column is a snapshot of what the device reported on 2026-11-09.
**The device is the authority** — the router reads the capability at route
time, so this table can go stale without breaking anything. See
[Thinking mode](#thinking-mode).

### The commands

| Command | What it does |
|---|---|
| `tiiny_ctl.py status` | Device, resident set with NPU shares, the lock, the hold, the plan |
| `tiiny_ctl.py plan --goal "..."` | Pick the models, check the NPU fit, write the plan |
| `tiiny_ctl.py reserve --owner NAME` | Take the cross-agent lock and announce it |
| `tiiny_ctl.py load [--wave N]` | Load the batch's models, evict what does not fit, verify |
| `tiiny_ctl.py release` | Restore the required set, clear the lock, the plan and the notice |
| `tiiny_ctl.py catalog --refresh` | Diff the live Model Store against the last snapshot |
| `tiiny_ctl.py image "a job"` | Pick the right image model for a job |
| `route_check.py "a goal"` | Read-only: which model would this goal route to, and why |
| `route_check.py --thinking off "a goal"` | The same, plus the reasoning state it would achieve |

## Procedure

### 1 — Evaluate the job

Name the shape honestly. "Index every file under X and classify each" is an
indexing task; "read these logs and tell me what broke" is a drafting task. A
goal that understates the work gets the generalist, which is the wrong model
for it.

The router infers the shape from the goal text, and the `tier` parameter
overrides it. Use the override where inference would guess wrong — an
unknown tier is refused loudly rather than silently mapped.

*Done when:* each goal states the operation, not just the subject.

### 2 — Pick the model, and check it can run

```bash
python3 scripts/tiiny_ctl.py plan --owner "$AGENT" --task "what this batch is for" \
  --goal "index every file under the vault and classify each" \
  --goal "research the latest on agent memory systems"
```

The plan prints, per goal: the tier, the model, its NPU share, the wave it
belongs to, and whether the model is resident or merely downloaded. A model
that is **not downloaded** cannot be loaded — the plan falls back to a
candidate that can, and says so.

*Done when:* every goal has a model that is on the device.

### 3 — Ensure the combination fits

One shared NPU pool, and a load is a **swap**: it evicts whatever was
resident. Models over 100% cannot be resident together — a 47% model plus a
54% model is 101%.

The plan packs the batch into **waves**: each wave's models fit inside 100%,
and a wave that does not fit with the rest is a second delegation call. The
plan also prints what the wave will displace and what stays alongside it.

*Done when:* every wave's NPU sum is 100% or less.

### 4 — Reserve the device

```bash
python3 scripts/tiiny_ctl.py reserve --owner "$AGENT" --task "what this batch is for"
```

This takes the lock and writes a notice into the vault's `hot.md` so other
agents in the AMC can see that Tiiny is spoken for. If the device is already
held, the reserve **refuses** and tells you who holds it and until when.

*Done when:* the lock is held and the notice is in `hot.md`.

### 5 — Load the batch's models

```bash
python3 scripts/tiiny_ctl.py load --wave 1     # then --wave 2, and so on
```

The controller writes the hold first (so the watchdog does not evict what it
just loaded), then decides what to evict, then loads, then **verifies that
every model in the wave is resident**. A model that did not land cannot
answer — the device returns `404 "is not loaded"` and the child falls back
to the paid provider, invisibly.

*Done when:* the load reports no model missing.

### 6 — Plan the work: the device is single-threaded

**Tiiny serves one generation-heavy stream at a time.** Two heavy children
starve each other, and the failure mode is a *hang*, not an error — the
device keeps reporting healthy while it answers nothing.

So: run **one heavy child per wave**, not every wave's children at once. The
parent's own cloud route is a separate stream, so parent work and one device
child genuinely run in parallel. If a batch needs a second workstream, give
it a named non-device provider.

*Done when:* no wave runs more than one generation-heavy child at a time.

### 7 — Supervise the child

The child is running on a small local model, so give it a job it can finish:
state the operation, the output, and where to write it. Ask it to save raw
findings to a file early and keep its summary short — that is what keeps a
local model competitive with a frontier one.

Watch for the two failure modes that look like progress: a child that is
stalled behind the device's queue, and a child that fell back to the paid
provider. The child's route carries the backend and the label
(`code→generalist` means the specialist was not available).

*Done when:* the child has written its findings at least once, and its route
label says what you expected.

### 8 — Check the child's work

A child's report is a self-report. Recompute the numbers it claims from the
primary record with a script, and render what it built — a delivered HTML
file is not done when it parses.

*Done when:* a script recomputes every claimed count from the source and
exits zero.

### 9 — Release the device

```bash
python3 scripts/tiiny_ctl.py release
```

This restores the required models, clears the hold, clears the plan, releases
the lock, and removes the notice from `hot.md`. **Restoring is part of the
run, not a follow-up**: a swap that is not restored breaks every later
delegated child, and the failure looks like a model problem rather than a
leftover state.

*Done when:* the required models are resident, the hold is gone, the lock is
free, and `hot.md` no longer carries the notice.

### 10 — Keep the catalogue honest

```bash
python3 scripts/tiiny_ctl.py catalog --refresh
```

This diffs the live Model Store against the last snapshot and reports what is
new, what is gone, and whose NPU share or context window moved. If a tier
model's figures changed, the tier table in `plugin/tiers.py` is now wrong —
update it, and update
[`tiiny-discovery/tiiny-model-catalogue.md`](../../Tiiny/model-catalogue.md)
to match.

The snapshot records **facts**; the analysis around them is written by hand.
New models are worth adding to the tier table when they are genuinely better
at a shape the tiers do not cover — not because they are new.

*Done when:* the diff is empty, or the differences are reflected in the tier
table and the catalogue.

## Thinking mode

A reasoning model answers in two parts: the trace, and the answer. The trace
is not free, and on mechanical work it is not wanted. Indexing a folder does
not need a chain of thought; it needs the folder.

So each task carries a `thinking` parameter:

| Value | What happens |
|---|---|
| `auto` (default) | Nothing is applied. The model keeps its native behaviour. |
| `off` | Reasoning is turned off where the model can be turned off, and down to the model's cheapest reasoning level where it cannot. |
| `on` | Reasoning is turned on where the model can be turned on, and up to its most expensive level where it cannot. |

```bash
python3 scripts/route_check.py --thinking off "index every file under the vault"
```

### The device knows more than a table does

Models differ in *how* reasoning is controlled, and the differences are not
guessable:

- Some models have a **switch** — `enable_thinking: false` stops the trace
  dead.
- Some models have only **levels** — `low`, `medium`, `high` — and their
  switch is ignored outright.
- Some models **do not reason at all**, and a request to turn reasoning on is
  not a thing that can happen.
- One model is flagged by the device as having no switch and honours it
  perfectly well. **The flag is a hint, not ground truth.**

So the router does not keep a table of this. It reads the device's own
capability for the model it picked, at route time, and applies the control
that model actually honours:

```json
{"thinking": {"supported": true, "toggleable": false, "levels": ["low", "medium", "high"]}}
```

That comes from `GET /v1/models` for a resident model and
`GET /api/v1/models/online_models` for the whole store. The Model Store
changes with every TiinyOS update, and a hand-maintained capability table
goes stale quietly — which is worse than having none, because it is
believed.

### "Off" means the cheapest available state

For a model with no working switch, `thinking: "off"` is **not a refusal and
not a pretence**. It means the cheapest state the model offers: the lowest
reasoning level it declares. The model still reasons — it just reasons less —
and the label says so rather than claiming a switch that does not exist.

### The label reports what happened, not what was asked

Every route carries a label. The thinking state is part of it:

| Label | Meaning |
|---|---|
| `[think:off]` | The switch worked. |
| `[think:off→low]` | The switch was ignored; the model is at its cheapest level. |
| `[think:on]` | The switch worked. |
| `[think:on→high]` | The switch was ignored; the model is at its most expensive level. |
| `[think:unsupported]` | The model does not reason at all. |
| `[think:unknown]` | The device would not say, so nothing was applied. |
| `[think:auto]` | Nothing was applied; native behaviour. |

A route that asked for `off` and got `off→low` did not turn reasoning off.
Saying otherwise is how a token bill becomes a surprise.

### Thinking on needs a token floor

A reasoning model spends its budget on the trace first. With a small
`max_tokens`, the trace eats the budget and the request comes back **HTTP 200
with an empty answer** — a silent failure that looks like the model produced
nothing.

So the router applies an output floor (4096, the budget children already run
with) whenever a model's reasoning is in play. If you raise your own budget
above that, raise the floor with it, or a reasoning child is quietly clamped
back down:

```yaml
delegation:
  backends:
    tiiny-router:
      thinking_max_tokens: 8192
```

## The image benefit

The same device runs the image models, and picking the right one is the
difference between an image that works and an afternoon. The controller picks
from what is on the device:

```bash
python3 scripts/tiiny_ctl.py image "a realistic portrait of an engineer"
python3 scripts/tiiny_ctl.py image "a logo with the word ARC in it"
python3 scripts/tiiny_ctl.py image "a character turnaround, three views"
```

| The job | The model | NPU |
|---|---|---|
| Photorealism, legible text, fast iteration | `Tongyi-MAI/Z-Image-Turbo` | 26% |
| Maximum fidelity — fur, foliage, reflections | `HiDream-ai/HiDream-O1-Image-Dev` | 30% |
| A realistic person — skin, hair, fabric | `TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic` | 26% |
| A character turnaround in one image | `YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet` | 26% |
| Cut a subject out of an existing photo | `fal/FLUX.2-klein-4B-Background-Remove` | 26% |

An image model evicts the chat models — the NPU is one pool — so image work
belongs inside a reserved batch, and the release puts everything back. See
[references/image-models.md](references/image-models.md) for the sizes that
work and the ones that do not.

## The lock

Two agents delegating at once will fight over the same models and the same
silicon. The lock makes that visible instead of silent.

| | |
|---|---|
| **The mutex** | `~/.hermes/tiiny-lock.json`. Taken under `flock`, so two agents cannot both believe they hold it. It **expires**, so a crashed agent does not lock the device overnight. |
| **The announcement** | A marked block in the vault's `hot.md` — the AMC's own board of what is in flight — so agents that are not Hermes profiles can see the device is spoken for. |

`status` shows both. `release` clears both.

## Pitfalls

- **A load is a swap.** Loading a model evicts the resident one; the evicted
  model's endpoint then returns `404`, which means *not resident*, not a bad
  model id. Restore the required set when the work is done.
- **The device decides what to evict — unless you decide first.** Left alone
  it kept the 47% generalist and evicted the 27% model the batch had just
  asked for. The controller evicts explicitly, keeping the cheapest models
  that fit. Never let a bare `tiiny load` be the only thing that touches the
  device during a batch.
- **The watchdog fights deliberate swaps.** It reloads the required models
  every five minutes and will evict a research model you loaded for a long
  task. The hold file is what prevents this — the hold check must run before
  the cold-check, or the hold reads as cold.
- **Two heavy children deadlock.** Not an error — a hang, with the device
  still reporting healthy. One heavy child at a time.
- **`tiiny ls` shows size, not residency.** Its NPU column is how much NPU a
  model takes, not whether it is loaded. `tiiny_ctl.py status` is the
  residency truth.
- **A 404 is not a typo.** Before concluding a model id is wrong, check
  residency. A model can be in the Store and not loaded.
- **Context window is a ceiling, not a suggestion.** A child that silently
  truncates its context is usually routed to a model whose window is too
  small for the task, not to a broken task.
- **A level inside `chat_template_kwargs` is not the same knob as a level at
  the top level of the request.** The chat-template one is read by some model
  families and silently ignored by others — a model whose chat template has
  no boolean switch reads the level only at the top level of the request.
  Putting it in the wrong place looks configured and changes nothing.
- **`enable_thinking: false` is mandatory on every Tiiny route.** It is the
  provider's `extra_body` and it survives the route's own overrides only
  where the route does not set its own thinking state. Without it, every
  child reasons by default, on every task, including the mechanical ones.
- **A reasoning model with a small `max_tokens` returns an empty response**
  with the budget spent in the trace, and the status code is 200. The router
  applies an output floor for this reason; if you set `max_tokens` yourself,
  keep it above the floor.
- **The device's `toggleable` flag has been wrong.** A model flagged as
  having no on/off switch honours it anyway. Send the boolean whenever it can
  be sent, and let the label report what actually took effect.
- **A stale hold is worse than no hold.** It silently stops the watchdog from
  ever restoring the device. `release` clears it and verifies.
- **This skill never downloads a model.** It chooses and loads from what is
  already on the device.

## Verification

```bash
python3 scripts/tiiny_ctl.py status                  # device, residency, lock, hold, plan
python3 scripts/tiiny_ctl.py plan --goal "your goal" # tier, model, NPU fit, waves
python3 scripts/route_check.py --all                 # every tier and its budget
python3 scripts/route_check.py --thinking off "goal" # tier, model, and the reasoning state
python3 scripts/tiiny_ctl.py catalog --refresh       # what moved in the Model Store
```

A batch is correct when the plan's model matches the shape of the work, every
wave fits inside 100% NPU, every wave's models were resident when the child
ran, the child's route label says what you expected, the child's artifact
survives its own claim, and the device was released at the end.
