---
name: tiiny-model-routing
description: "Run delegated sub-agents on the Tiiny device. Chooses the model that fits each subtask, loads it, locks the device against other agents, supervises the child, verifies its work, and releases the device."
version: 2.0.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [tiiny, delegation, model-routing, local-inference, agents, locking, lifecycle]
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
| **The router** (`plugin/`) | A delegation backend. Hermes calls it once per subtask. | Choosing the model for each subtask. |
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

| Tier | Model | NPU | Context | On the device? |
|---|---|---|---|---|
| `research` | `InternScience/Sage-A1.5-Turbo` | 48% | 262144 | downloaded |
| `research` (alt) | `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 | downloaded |
| `index` | `openai/gpt-oss-20b` | 27% | 131072 | **resident** |
| `code` | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 | downloaded |
| `code` (alt) | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | **resident** |
| `code` (heavy) | `Qwen/Qwen3-Coder-Next` | 94% | 131072 | not downloaded |
| `browser` | `Qwen/Qwen3.8-27B` | 52% | 262144 | downloaded |
| `draft` | `Qwen/Qwen3.5-9B` | 29% | 131072 | downloaded |
| `general` | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | **resident** |

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
- **Thinking mode costs tokens without adding value on mechanical work.**
  The route disables it per request (`enable_thinking: false`). A small
  `max_tokens` budget against a thinking model can return an empty response
  with the budget spent in reasoning.
- **A stale hold is worse than no hold.** It silently stops the watchdog from
  ever restoring the device. `release` clears it and verifies.
- **This skill never downloads a model.** It chooses and loads from what is
  already on the device.

## Verification

```bash
python3 scripts/tiiny_ctl.py status                  # device, residency, lock, hold, plan
python3 scripts/tiiny_ctl.py plan --goal "your goal" # tier, model, NPU fit, waves
python3 scripts/route_check.py --all                 # every tier and its budget
python3 scripts/tiiny_ctl.py catalog --refresh       # what moved in the Model Store
```

A batch is correct when the plan's model matches the shape of the work, every
wave fits inside 100% NPU, every wave's models were resident when the child
ran, the child's route label says what you expected, the child's artifact
survives its own claim, and the device was released at the end.
