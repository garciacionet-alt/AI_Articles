---
name: tiiny-model-routing
description: "Route delegated subtasks to the right Tiiny model."
version: 1.0.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [tiiny, delegation, model-routing, local-inference, agents]
---

# Tiiny Model Routing

Pick the right model for each delegated subtask, instead of sending every
subtask to one pinned model.

## When to Use

- A delegation batch mixes different kinds of work — a research sweep, a
  filesystem index, a code edit, a browser run, a summary.
- A delegation is burning tokens on a model that is not specialised for the
  work, or evicting another model that a concurrent task needs.
- You are setting up or debugging a delegation backend that routes per task.

Don't use for: a single-model deployment where every subtask is the same kind
of work (set `delegation.model` and stop), or non-Tiiny providers (the
mechanism is provider-agnostic, but the tier table is Tiiny-specific).

## Prerequisites

- A Tiiny device reachable on the LAN, with its bearer in the environment as
  `TIINY_API_KEY`.
- The `tiiny` CLI on `PATH` for the residency commands.
- The routing backend plugin installed (see [references/backend.md](references/backend.md)), and
  `delegation.backend: tiiny-router` set in the active profile's config.

## How to Run

Route a task through the backend and read back what it chose:

```bash
python3 scripts/route_check.py "index every file under the vault and classify each"
```

The script prints the tier, the model, and that model's NPU share and context
window — the same numbers the backend uses, so a routing decision can be
checked without spawning a child.

## Quick Reference

| Tier | Model | NPU | Context |
|---|---|---|---|
| `research` | `InternScience/Sage-A1.5-Turbo` | 48% | 262144 |
| `research` (alt) | `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 |
| `index` | `openai/gpt-oss-20b` | 27% | 131072 |
| `code` | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 |
| `code` (alt) | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |
| `code` (heavy) | `Qwen/Qwen3-Coder-Next` | 94% | 131072 |
| `browser` | `Qwen/Qwen3.8-27B` | 51% | 262144 |
| `draft` | `Qwen/Qwen3.5-9B` | 29% | 131072 |
| `general` | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |

| Command | What it does |
|---|---|
| `tiiny top` | What is resident right now, and each model's NPU share |
| `tiiny ls` | The whole Model Store — note the NPU column is *size*, not load state |
| `tiiny-swap.sh <model> -- <cmd>` | Load a model, run something, restore the required set |
| `tiiny-swap.sh --restore` | Drop a hold and reload the required models |

## Procedure

1. **Name the shape honestly.** The router reads the task's shape from its
   goal. "Index every file under X and classify each" is an indexing task;
   "read these logs and tell me what broke" is a drafting task. A goal that
   understates the work gets the generalist.
   *Done when:* each goal states the operation, not just the subject.

2. **Override when the goal lies.** Pass `tier` on the task to force the
   route. The tiers are `research`, `index`, `code`, `browser`, `draft`,
   `general`. An unknown tier is refused rather than silently falling back.
   *Done when:* the override is used only where inference would guess wrong.

3. **Check the budget before the batch.** Every model takes a share of one
   shared NPU pool, and models over 100% cannot be resident together. Two
   specialists often cannot coexist — a 47% model plus a 54% model is 101%.
   Read `tiiny top` and confirm the models the batch needs will fit.
   *Done when:* the models the batch needs sum to 100% NPU or less.

4. **Load what the batch needs, and restore afterwards.** A load is a swap,
   not an add: it evicts whatever was resident. Use the swap script, which
   writes a hold first so the watchdog does not evict the model mid-task, and
   restores the required set when the command exits.
   *Done when:* the required models are resident again and no hold file is
   left behind.

5. **Verify the route ran on the model you expected.** The child's result
   carries a `route` with the backend and label. A child that fell back to a
   paid provider says so in the run notice.
   *Done when:* the route label on each child matches the tier you intended.

## Pitfalls

- **A load is a swap.** Loading a model evicts the resident one; the evicted
  model's endpoint then returns `404`, which means *not resident*, not a bad
  model id. Restore the required set when the work is done.
- **The watchdog fights deliberate swaps.** It reloads the required models
  every five minutes and will evict a research model you loaded for a long
  task. The hold file in the swap script is what prevents this — the hold
  check must run before the cold-check, or the hold reads as cold.
- **`tiiny ls` shows size, not residency.** Its NPU column is how much NPU a
  model takes, not whether it is loaded. `tiiny top` is the residency truth.
- **A 404 is not a typo.** Before concluding a model id is wrong, check
  residency. A model can be in the Store and not loaded.
- **Context window is a ceiling, not a suggestion.** A child that silently
  truncates its context is usually routed to a model whose window is too
  small for the task, not to a broken task.
- **Thinking mode costs tokens without adding value on mechanical work.**
  The backend disables it per request (`enable_thinking: false`). A small
  `max_tokens` budget against a thinking model can return an empty response
  with the budget spent in reasoning.
- **Routing does not manage residency.** The backend chooses a model; it
  never loads one. A routing decision inside a batch must not be able to
  evict a model a sibling task is already using.

## Verification

```bash
python3 scripts/route_check.py "your task goal here"    # tier + model + budget
python3 scripts/route_check.py --all                      # every tier, with NPU
tiiny top                                                # what is resident
```

A route is correct when the tier matches the shape of the work, the chosen
model is resident (`tiiny top` lists it), and the models the batch needs fit
inside 100% NPU.
