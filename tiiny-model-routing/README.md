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

Real combinations, measured on a device with 92 models in its store:

| Combination | NPU | Verdict |
|---|---|---|
| `openai/gpt-oss-20b` (27%) + `Qwen/Qwen3.5-9B` (29%) | 56% | Fits comfortably |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `openai/gpt-oss-20b` (27%) | 74% | Fits |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `InternScience/Sage-A1.5-Turbo` (48%) | 95% | Fits, tight |
| `Qwen/Qwen3.6-35B-A3B` (47%) + `endless-frontier/BigBang-v1-Turbo` (54%) | 101% | **Impossible** |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` (55%) + `Qwen/Qwen3.6-35B-A3B` (47%) | 102% | **Impossible** |
| `Qwen/Qwen3.8-27B` (52%) + `endless-frontier/BigBang-v1-Turbo` (54%) | 105% | **Impossible** |

Two specialists that are each individually reasonable can be jointly
impossible. The router has to know that before it picks.

That last pair is the one to notice: the two coding models in the table below
cannot be resident at the same time. A batch that wants both is two waves, not
one.

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
| Computer use, browser automation | `Qwen/Qwen3.8-27B` | Its agentic tool use is strong enough to drive computer-use, browser automation, and mobile interaction across multi-step workflows | 52% | 262144 |
| Drafting, summarising | `Qwen/Qwen3.5-9B` | A 9B multimodal model covering chat, analysis, and vision-language tasks in one model | 29% | 131072 |
| Hard refactoring, recovery from failed runs | `Qwen/Qwen3-Coder-Next` | Built specifically for agentic coding tasks: multi-file edits, long-horizon debugging, tool use, and recovery from execution failures | 94% | 131072 |

Note the shape of the table. The specialist for the hardest coding job costs
**94%** of the pool. The specialist for bulk indexing costs **27%**. Routing
the mechanical work to the wrong end of that range is what makes a local
appliance feel slow.

A tier can also list a second and third choice, tried in order when the first
is not resident. The coding tier's own first choice is
`Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` at 55% — and at 55% it cannot share
the pool with the 47% model, which is exactly why the fallback list exists.

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
    "code":     (("Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo", 55, 65536),
                 ("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
                 ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
                 ("Qwen/Qwen3-Coder-Next", 94, 131072)),
    "browser":  (("Qwen/Qwen3.8-27B", 52, 262144),),
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

**The router chooses; a separate controller loads.** The backend picks the
model for a subtask and never touches the device. A load is a swap that
evicts whatever was resident, so a routing decision made inside a delegation
batch must not be able to yank a model out from under a sibling task — and
the delegation plugin has no hook that says "the batch is finished".

So the loading half is a separate command that the manager agent drives
explicitly, under a lock: plan the batch, reserve the device, load what the
batch needs, delegate, then release. The two halves agree through a **plan
file** that records which model was assigned to which goal, so the specialist
the controller just loaded is the specialist the child actually runs on.

The division is not tidiness. A load needs three things a plugin cannot
have: a batch-level view (which models the whole batch needs), a lock
against other agents, and a "we are done" moment. The controller has all
three.

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

## Reasoning mode is a routing decision too

A reasoning model answers in two parts: the trace, and the answer. The trace
is not free, and on mechanical work it is not wanted — indexing a folder does
not need a chain of thought, it needs the folder.

So the backend takes a second per-task parameter, `thinking`, with three
values. `auto` (the default) changes nothing and leaves the model's native
behaviour alone. `off` turns reasoning off where the model can be turned off.
`on` turns it on where the model can be turned on.

The obvious implementation is a boolean. It is also the wrong one, because
the models in a catalogue do not agree on how reasoning is controlled:

- Some models have a **switch** — `enable_thinking: false` in the chat
  template's keyword arguments stops the trace dead.
- Some models have only **levels** — `low`, `medium`, `high` — and their
  switch is ignored outright. The level is read at the **top level of the
  request**, not inside the chat template; put it in the wrong place and it
  is silently discarded.
- Some models **do not reason at all**, and a request to turn reasoning on is
  not a thing that can happen.
- One model on the device is flagged as having no switch and honours it
  perfectly well. **The device's own flag is a hint, not ground truth.**

A boolean-only implementation therefore does one of two wrong things: it
claims to have turned reasoning off on a model it cannot, or it refuses a
task because the model happens not to have a switch. Both are worse than
doing the work at the model's cheapest setting.

So the router reads the device's own capability for the model it picked, at
route time:

```json
{"thinking": {"supported": true, "toggleable": false, "levels": ["low", "medium", "high"]}}
```

It comes from `GET /v1/models` for a resident model and
`GET /api/v1/models/online_models` for the whole store. A hand-maintained
capability table would be simpler and would be wrong within one TiinyOS
update — the Model Store changes, and a stale row is believed.

### "Off" means the cheapest available state

For a model with no working switch, `thinking: "off"` is **not a refusal and
not a pretence**. It means the cheapest state the model offers: the lowest
reasoning level it declares. The model still reasons — it just reasons less.
The routing table's own indexing model is one of these, so this is the case
that matters in practice.

### The label reports what happened

The route carries a label, and the label carries the achieved state — never
the requested one:

| Label | Meaning |
|---|---|
| `[think:off]` | The switch worked. |
| `[think:off→low]` | The switch was ignored; the model is at its cheapest level. |
| `[think:on]` | The switch worked. |
| `[think:on→high]` | The switch was ignored; the model is at its most expensive level. |
| `[think:unsupported]` | The model does not reason at all. |
| `[think:unknown]` | The device would not say, so nothing was applied. |

A route that asked for `off` and got `off→low` did not turn reasoning off.
Saying otherwise is how a token bill becomes a surprise.

### The empty response that looks like success

A reasoning model spends its budget on the trace first. With a small
`max_tokens`, the trace eats the whole budget and the request comes back
**HTTP 200 with an empty answer** — the same status code as a successful
call, with nothing in it. The router therefore applies an output floor
whenever a model's reasoning is in play, including in the "off" state, where
a model whose switch does not work still produces a trace.

## Making the load survivable

Choosing a model is half the problem. The other half is residency, and this
is where most routing implementations break.

**A load is a swap.** Loading a model evicts the resident one. The evicted
model's inference endpoint then returns `404` — which means *not resident*,
not a bad model id. Read `/v1/models` to see what is actually loaded; it
lists resident models, not the whole store.

**The device decides what to evict — unless you decide first.** When a load
does not fit, the device makes room by evicting something, and it does not
know what the batch needs. Left to itself it kept the 47% generalist and
evicted the 27% model the batch had just asked for, so the wave's own model
was missing and the child answered `404 "is not loaded"` and fell back to
the paid provider. The controller therefore decides what stays *before* it
loads: the batch's models are sacred, and of everything else resident the
cheapest are kept while they fit.

**A batch that does not fit is split into waves.** One shared NPU pool means
a batch needing 154% cannot hold its models at once. The plan packs the
batch into waves that each fit inside 100%, and each wave is a separate
delegation call.

**The device serves one generation-heavy stream at a time.** Two heavy
children starve each other, and the failure mode is a *hang*, not an error:
the device keeps reporting healthy while it answers nothing. Run one heavy
child per wave. A heavy device child and the parent's own cloud stream are
two providers, so they genuinely run in parallel.

**The watchdog fights you.** A device that reloads its required models every
few minutes will evict the research model you just loaded for a long task,
mid-task. The fix is a hold file: while it exists, the watchdog reloads
nothing. The hold check has to run *before* the cold-check — put it after,
and a hold reads as "cold" and the reload evicts your model anyway.

**Restore what you displaced.** A delegated batch that swapped in a
specialist should put the required set back when it finishes, or the next
batch inherits a device nobody configured.

All of that is handled by a controller:

```bash
tiiny_ctl.py plan --owner "$AGENT" --task "what this batch is for" \
  --goal "index every file under the vault and classify each"   # pick, fit, wave
tiiny_ctl.py reserve --owner "$AGENT" --task "what this batch is for"  # lock it
tiiny_ctl.py load --wave 1                                       # load, evict, verify
tiiny_ctl.py release                                             # restore, unlock
```

The plan writes the hold *before* the load, which closes the window where
the watchdog fires between the load and the hold, and the release verifies
the restore instead of assuming it.

### Two agents, one device

The controller also holds the device against other agents, because two
delegations at once will fight over the same models and the same silicon.
The lock is a file taken under `flock`, so two agents cannot both believe
they hold it, and it **expires**, so a crashed agent does not lock the
device overnight. Alongside it, a marked notice in the team's shared status
board tells agents that are not running this code that the device is spoken
for.

### The image bonus

The same device runs the image models, and the same controller picks the
right one for the job — a text-accurate default for a logo, a
high-fidelity model for detail that IS the subject, a character sheet for a
turnaround, an adapter for cutting a subject out of an existing photo. It
is the kind of thing that looks like a bonus and turns out to be the reason
the image pipeline works at all.

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
reasoning: levels only (low, medium, high) — the on/off switch is ignored
thinking: auto (the model's native behaviour)
residency: loaded
```

And with a reasoning mode asked for:

```bash
python3 scripts/route_check.py --thinking off "index every file under the vault"
```

```
thinking: off -> off→low
sent:    enable_thinking=false, reasoning_effort=low, max_tokens=4096
```

The checker reads the device's resident set — one read-only call to the local
CLI — and the device's own capability for the model it picked. It changes
nothing on the device. It exists so a routing decision can be checked
*before* a batch spends tokens on it.

## The limits

**The routing table is device-specific.** The tier choices, NPU shares, and
context windows here were read from one device's catalogue endpoint on
2026-11-09, when the store held 92 models. The store changes with every
TiinyOS update, and the NPU shares have already moved once — a model that
took 55% of the pool took 47% on the read behind this article. **Re-read the
numbers before trusting them.**

**The reasoning capability is read at route time, so it is never stale in
the route.** The same is not true of this article's prose: the model's
capability table moves with the Model Store, and the route reads the
device's own copy rather than any table shipped with it.

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
