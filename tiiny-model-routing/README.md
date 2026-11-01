# Routing Work to the Right Model

**A management agency's agents do not all do the same job. Pinning them to one
model wastes the cheap tasks and starves the expensive ones.**

An agency running agent fleets has a routing problem before it has a cost
problem. The research sweep, the document index, the code fix, the browser
run, and the summary all end up on the same model — because that is what a
single pin does. Every subtask pays for one model's context window, whether
or not it needs that window, and the specialist that would have done one of
them better never gets a turn.

This article is about fixing that with a local appliance that holds a whole
library of models, and about the one hard constraint that decides every
choice you make.

## The problem with one model

Take a batch of five delegated subtasks:

| # | Subtask | What it actually is |
|---|---|---|
| 1 | Survey the vendor landscape, find sources | Long-horizon research |
| 2 | Index every file in the client folder, classify each | Mechanical bulk work |
| 3 | Fix the failing test in the integration module | Terminal coding |
| 4 | Click through the signup flow, screenshot each step | Browser automation |
| 5 | Summarise the meeting notes into five bullets | Drafting |

Pinned to one model, all five run on it. The consequences are not abstract:

- **The cheap tasks get expensive.** A 94%-NPU coding model running a
  five-bullet summary is holding a large share of one shared pool to produce
  a paragraph.
- **The hard tasks get mediocre.** The research sweep wants a model built for
  long multi-step investigation, not one built for multi-file edits.
- **They fight over the device.** Each model takes a share of one NPU pool.
  Loading a second one evicts the first, so a batch that needs two
  specialists may not be able to hold both.

On a paid API this is a money problem. On a local appliance it is a
correctness problem: the model that cannot be resident is the model that
cannot answer.

## The constraint that decides everything

**NPU is one shared pool.** Every model carries an NPU share, and models whose
shares sum above 100% cannot be resident at the same time. A load is a
**swap**, not an add — it evicts whatever was resident.

This is the number to check before anything else, and it is why "which model
is best" is the wrong first question. The right first question is **"what
else needs to be loaded?"**

Real combinations, measured on a device with 82 models in its store:

| Combination | NPU | Verdict |
|---|---|---|
| `openai/gpt-oss-20b` (27%) + `Qwen/Qwen3.5-9B` (29%) | 56% | Fits comfortably |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `openai/gpt-oss-20b` (27%) | 74% | Fits |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `InternScience/Sage-A1.5-Turbo` (48%) | 95% | Fits, tight |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `endless-frontier/BigBang-v1-Turbo` (54%) | 101% | **Impossible** |
| `Qwen/Qwen3.8-27B` (51%) + `endless-frontier/BigBang-v1-Turbo` (54%) | 105% | **Impossible** |

Two specialists that are each individually reasonable can be jointly
impossible. The router has to know that before it picks.

## Routing by task shape

The fix is to route each subtask to the model that matches its shape. Shape,
not keyword — because shape is what predicts which model does well. A goal
that mentions "index the vault" is an indexing job. A research task *about*
code is still a research task, and keyword matching gets it wrong.

Here is the routing table, with each model's NPU share and context window read
from the device's own catalogue endpoint. The "why" column is drawn from the
publisher's own description of each model.

| Task shape | Model | Why this one | NPU | Context |
|---|---|---|---|---|
| Long-running research | `InternScience/Sage-A1.5-Turbo` | Built for long, multi-step scientific and analytical tasks — literature investigation, evidence gathering — and it splits a task across parallel subagents and checks its own progress mid-task | 48% | 262144 |
| Bulk indexing, classification | `openai/gpt-oss-20b` | A mixture-of-experts model with only 3.6B parameters active per token out of 21B total, which keeps it fast and resource-light on-device | 27% | 131072 |
| Terminal coding, repo navigation | `deepreinforce-ai/Ornith-1.0-35B` | Post-trained on Qwen 3.5 MoE for terminal-based agentic coding: multi-file editing, repository navigation, shell command execution | 50% | 131072 |
| Repository-scale coding | `Qwen/Qwen3.6-35B-A3B` | A multimodal agentic coding model for repository-level reasoning, tool calling, and multi-step code execution; a sparse MoE activating only 3B of 35B parameters per token | 47% | 262144 |
| Computer use, browser automation | `Qwen/Qwen3.8-27B` | Its agentic tool use is strong enough to drive computer-use, browser automation, and mobile interaction across multi-step workflows | 51% | 262144 |
| Drafting, summarising | `Qwen/Qwen3.5-9B` | A 9B multimodal model covering chat, analysis, and vision-language tasks in one model | 29% | 131072 |
| Hard refactoring, recovery from failed runs | `Qwen/Qwen3-Coder-Next` | Built specifically for agentic coding tasks: multi-file edits, long-horizon debugging, tool use, and recovery from execution failures | 94% | 131072 |

Note the shape of the table. The specialist for the hardest coding job costs
**94%** of the pool. The specialist for bulk indexing costs **27%**. Routing
the mechanical work to the wrong end of that range is what makes a local
appliance feel slow.

## Implementing the router

A routing layer needs to answer one question per subtask: *which model does
this one get?* In Hermes, that question is answered by a **delegation
backend** — a plugin that implements `route_task`, called once per task with
that task's goal and context.

```python
TIER_CHOICES = {
    "research": (("InternScience/Sage-A1.5-Turbo", 48, 262144),
                 ("endless-frontier/BigBang-v1-Turbo", 54, 131072)),
    "index":    (("openai/gpt-oss-20b", 27, 131072),),
    "code":     (("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
                 ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
                 ("Qwen/Qwen3-Coder-Next", 94, 131072)),
    "browser":  (("Qwen/Qwen3.8-27B", 51, 262144),),
    "draft":    (("Qwen/Qwen3.5-9B", 29, 131072),),
    "general":  (("Qwen/Qwen3.6-35B-A3B", 47, 262144),),
}

def detect_tier(goal: str) -> str:
    text = (goal or "").lower()
    for tier, signals in SHAPE_SIGNALS:
        if any(signal in text for signal in signals):
            return tier
    return "general"
```

The route it returns is ordinary configuration:

```python
{
    "model": model,
    "provider": "custom:tiiny",
    "base_url": "http://openai.api.tiiny/v1",
    "request_overrides": {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "label": tier,
}
```

Three details in that response are worth calling out, because each one is a
decision rather than a default.

**The `general` fallback is deliberate.** A task whose shape is not
recognised goes to `Qwen/Qwen3.6-35B-A3B` — the model that is good at
everything in the catalogue and mediocre at each. Being wrong about a
specialist costs more than being mediocre at a general task.

**Thinking is disabled per request.** Several models in the catalogue run in
thinking mode by default. On mechanical work that spends the token budget
producing a reasoning trace before an answer nobody asked for — and on a
small `max_tokens` budget it can return an empty response with the budget
spent. The `chat_template_kwargs` override turns it off per request.

**The router never loads a model.** It chooses; it does not mutate the
device. That separation matters: a load evicts whatever was resident, and a
routing decision made inside a delegation batch must not be able to yank a
model out from under a sibling task that is already running.

**But it does read the device, and that changes what it picks.** A model that
is not resident cannot answer: the device replies `404 "is not loaded"`,
Hermes treats that as terminal, and the child falls back to the paid
provider. On a device whose shared NPU pool holds a handful of models at a
time, routing to a specialist that is not loaded silently moves the work off
the local device — and the work still completes, so nothing looks wrong.

So the router asks the device what is resident and picks something that is
actually there: the tier's own first choice, then another candidate from the
same tier, then the generalist. The label on the route records the
substitution (`code->generalist`), so it is visible rather than invisible in
a fallback. If the device cannot be reached at all, the router behaves
exactly as it did before — the tier's first choice.

This is what makes the fallback list in `TIER_CHOICES` worth having. Without
it, the tier table is a lookup table; with it, the router is the thing that
keeps work on the device when the device is half-loaded.

### Letting the caller override

Inference from the goal is a heuristic, and heuristics need an escape hatch.
The backend exposes a `tier` parameter per task, validated against the tier
list and **refused** if it is not one of them — a typo must fail loudly
rather than silently falling back to the generalist.

The case where this matters: a task that reads "read these logs and tell me
what went wrong" is shaped like reading, but is actually a drafting task.
The goal understates the work. A forced `tier` fixes it; an inferred one
cannot.

## Making the swap survivable

Choosing a model is half the problem. The other half is residency, and this
is where most routing implementations break.

**A load is a swap.** Loading a model evicts the resident one. The evicted
model's inference endpoint then returns `404` — which means *not resident*,
not a bad model id. Read `/v1/models` to see what is actually loaded; it
lists resident models, not the whole store.

**The watchdog fights you.** A device that reloads its required models every
few minutes will evict the research model you just loaded for a long task,
mid-task. The fix is a hold file: while it exists, the watchdog reloads
nothing. The hold check has to run *before* the cold-check — put it after,
and a hold reads as "cold" and the reload evicts your model anyway.

**Restore what you displaced.** A delegated batch that swapped in a
specialist should put the required set back when it finishes, or the next
batch inherits a device nobody configured.

All three are handled by a swap script:

```bash
tiiny-swap.sh <model_id> -- <command>   # hold, load, run, restore
tiiny-swap.sh <model_id>                 # hold and load, restore later
tiiny-swap.sh --restore                   # drop the hold, reload the required set
```

The script writes the hold *before* the load, which closes the window where
the watchdog fires between the load and the hold.

## What the reader gets

The routing table, the backend, the swap script, and a checker that shows
what any given goal would be routed to:

```bash
python3 scripts/route_check.py "index every file under the vault and classify each"
```

```
goal:   index every file under the vault and classify each
tier:   index  (inferred)
model:  openai/gpt-oss-20b
budget: 27% NPU, 131072 context
residency: NOT loaded — `tiiny-swap.sh openai/gpt-oss-20b -- <cmd>` loads it and restores the rest
```

The checker makes no network calls and changes nothing on the device. It
exists so a routing decision can be checked *before* a batch spends tokens
on it.

## The limits

**The routing table is device-specific.** The tier choices, NPU shares, and
context windows here were read from one device's catalogue endpoint on
2026-10-31, when the store held 82 models. The store changes with every
TiinyOS update, and the NPU shares have already moved once — a model that
took 55% of the pool took 47% on the read behind this article. **Re-read the
numbers before trusting them.**

**Reading the catalogue's description fields is not the same as reading the
model's card.** The device's `desc` is the publisher's own summary and is
reliable about specialisation. It is not a benchmark. Where this article
names a trait, that trait is quoted from the device's description, not
inferred from a benchmark table.

**Routing by shape is a heuristic.** It works because the models genuinely
specialise, and it fails when a task's real shape is not in its goal text.
The `tier` override exists for that.

**This does not make the models interchangeable.** A better model on the
right task is better; a worse model on the wrong task is not rescued by
routing. The table is a floor, not a ceiling.

## Where to go next

- [model-catalogue.md](../Tiiny/model-catalogue.md) — every model in the store and
  what the device's own descriptions say it is good at.
- [PATTERN.md](./PATTERN.md) — the routing pattern in full: the failure
  modes, the tier design, and the reference checklist.
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) — the backend plugin, the swap
  script, and an end-to-end setup checklist.
- [scripts/route_check.py](./scripts/route_check.py) — the routing checker.
