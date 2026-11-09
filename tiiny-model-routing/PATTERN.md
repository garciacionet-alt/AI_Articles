## The pattern

A **routing layer that answers one question per delegated subtask: which
model does this one get?** It sits above the delegation mechanism, inspects
each task, and returns a model for that task alone. Nothing about it is
Tiiny-specific except the numbers in the table below — the mechanism is a
standard per-task routing hook, and the same shape works against any
provider with a model library.

The pattern has one non-obvious property: **the cheapest correct decision is
usually not the best model, it is the smallest model that fits the task.**
That sounds obvious and is routinely violated, because the best model is the
one with the most impressive description and the routing decision defaults to
it.

### Route by shape, not by keyword

Task shape is what predicts which model does well. A goal that says "index
the vault" is an indexing job regardless of what else it mentions. A research
task *about* code is still a research task — keyword matching gets that one
wrong, because it finds "code" in the goal and routes to the coder.

Shape is not a keyword list either. It is the *operation* the task performs:
gathering evidence, enumerating and labelling, editing files, driving a
browser, producing prose. Those five operations are what the catalogue's
specialisations line up with.

### The budget constraint comes first

On a device with one shared NPU pool, the first question is not "which model
is best" but **"what else needs to be loaded?"** Two specialists that are
each individually reasonable can be jointly impossible: a 47% model plus a
54% model is 101%, and 101% does not fit.

This inverts the usual intuition. The most capable model is often the worst
choice, because its share is large and it evicts everything else. The routing
table has to carry NPU share as a first-class column, not as an afterthought,
because it determines which combinations are reachable at all.

### The generalist fallback is a decision

A task whose shape is not confidently recognised goes to a generalist model.
That is a choice, not an absence of one.

The reasoning: being wrong about a specialist is more expensive than being
mediocre at a general task. A generalist that handles everything adequately
loses a little on every task. A specialist chosen for a task it does not fit
can fail badly and fail silently. Where the router is unsure, the floor is
the safer surface.

### Routing never manages residency

**The router chooses; it does not mutate the device.** It never calls
`tiiny load` or `tiiny unload`.

This separation is load-bearing. A load is a swap: it evicts whatever was
resident. If a routing decision could trigger a load, then a batch that
spawned several children could evict the model out from under a sibling
child that was already running — and the failing sibling would report a 404,
which reads as a bad model id and sends the operator hunting in the wrong
place.

Residency is an operator decision, made deliberately, with the eviction
consequences understood. The router's job is to name the model the task
wants. Whether that model is currently resident is a separate question, with
a separate answer.

### The caller needs an override that fails loudly

Inferring shape from a goal is a heuristic, and heuristics need an escape
hatch. The caller can force a tier.

The override must **fail loudly**. An unrecognised tier is refused outright,
not silently mapped to the generalist. A typo in a routing parameter that
quietly degrades every task to the fallback is worse than a typo that stops
the batch — the first is invisible in the output and expensive in the
tokens; the second is a failed run.

The case where this matters is the goal that understates the work. "Read
these logs and tell me what went wrong" is shaped like reading and is
actually a drafting task. Inference cannot recover that; an explicit
override can.

### Verify before you spend

A routing decision is cheap to check and expensive to get wrong. Before a
batch runs, four things should be confirmed:

1. **The model is resident.** `tiiny top` is the ground truth. `tiiny ls`
   lists the whole store, and its NPU column shows a model's *size*, not
   its load state — a model can be listed there and not loaded.
2. **The models the batch needs fit.** Their NPU shares must sum to 100% or
   less.
3. **The route is the one intended.** The checker prints the tier, the
   model, and the budget for any goal, so the decision can be reviewed
   before tokens are spent on it.
4. **The task fits the context window.** A child that silently truncates is
   usually routed to a model whose window is too small, not a broken task.

---

## Failure modes

### The pinned-model default

Every subtask gets one model, because `delegation.model` pins one model for
the whole delegation. It is correct when every subtask is the same kind of
work, and wrong the moment a batch mixes research, indexing, coding, and
drafting.

In practice it shows up as an expensive batch: a 94%-NPU coding model
holding most of the pool to produce a five-bullet summary, while the
research subtask that would have benefited from a research specialist ran on
the coder anyway.

### The swap that evicts a sibling

A load is a swap. Loading a model evicts whatever was resident — verified on
a device where loading `Qwen/Qwen3.8-27B` evicted the resident
`Qwen/Qwen3.6-35B-A3B`.

When this happens mid-batch, the sibling child fails with a 404 and the
batch reports a model error. The operator's first instinct is to suspect the
model id, the provider config, or the endpoint. The cause is a residency
change that the batch itself caused.

The preventive measure is the separation above: the router chooses, and a
separate controller loads — under a lock, with the batch's fit checked before
anything moves. The reactive measure is to restore the required set when the
batch finishes, so the next batch does not inherit a device nobody
configured.

The separation is the load-bearing part, and it is not about caution. A load
needs three things a delegation plugin cannot have: a **batch-level view** of
which models the whole batch needs, a **lock** against other agents, and a
**"we are done"** moment. The delegation plugin's only hook is
`route_task`, called once per subtask before any child runs, so it has
neither. Give the plugin a load and it will evict a model out from under a
sibling task, in the middle of the batch, with nothing to say so.

Two failure modes follow from getting this wrong, and both are silent:

- **The device evicts the wrong model.** When a load does not fit, the device
  picks what to evict, and it does not know what the batch needs. Observed on
  a real device: it kept the 47% generalist and evicted the 27% model the
  batch had just asked for, so the wave's own model was missing.
- **The watchdog evicts it back.** A device that reloads its required models
  every few minutes will undo a deliberate swap mid-task.

So the controller decides what stays *before* it loads: the batch's models
are sacred, and of everything else resident the cheapest are kept while they
fit.

### The 404 mistaken for a bad model id

A `404 Not Found` from the inference endpoint means **the model is not
resident**. It does not mean the model id is wrong, and it does not mean the
model is missing from the store.

The diagnostic that separates them: `/v1/models` lists only *resident*
models, while `tiiny ls` lists the whole store. A model present in `tiiny
ls` and absent from `/v1/models` is in the store and not loaded.

Guessing at ids instead of checking residency is how a working setup gets
"fixed" by changing a model name that was never wrong.

### The watchdog evicting a deliberate swap

A device that reloads its required models on a timer will evict a model that
was loaded deliberately for a long task — a research sweep running for twenty
minutes, evicted at the four-minute mark by a reload that had no idea what
was happening.

Both behaviours are correct. The watchdog does not know about deliberate
swaps, and the swap does not know about the watchdog. The reconciliation is a
**hold file**: while it exists, the watchdog reloads nothing and reports the
device as held rather than cold.

The ordering detail is the whole bug. The hold check must run *before* the
cold-check. Placed after it, a held device still reports as cold, the reload
fires, and the deliberate swap is evicted — with the hold file sitting right
there saying otherwise.

### The goal that understates the work

Shape inference reads the goal, and goals are written for humans. A task
whose goal describes the input rather than the operation gets the wrong tier.
"Read these logs and tell me what went wrong" describes reading; the work is
summarising.

There is no signal in the text that fixes this — which is exactly why the
override exists. The cost of the mistake is asymmetric: a drafting task sent
to the generalist wastes some quality; a research task sent to the coder
wastes the whole run.

### The task that outgrows its context window

Every model has a context ceiling, and the specialist chosen for a task's
shape is not automatically the one with the largest window. Routing a task
that needs a very large context to a model with a smaller window produces a
truncated result rather than an error — the child returns something plausible
that is missing the beginning or the end.

This is the failure that looks like a model that suddenly got worse. The
context window belongs in the routing table next to the model, not in a
separate document nobody reads at decision time.

---

## The routing table

| Task shape | Model | NPU share | Context |
|---|---|---|---|
| Long-running research | `InternScience/Sage-A1.5-Turbo` | 48% | 262144 |
| Long-running research (alternate) | `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 |
| Bulk indexing and classification | `openai/gpt-oss-20b` | 27% | 131072 |
| Terminal coding, repository navigation | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 |
| Repository-scale coding | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |
| Computer use, browser automation | `Qwen/Qwen3.8-27B` | 52% | 262144 |
| Drafting, summarising | `Qwen/Qwen3.5-9B` | 29% | 131072 |
| Generalist fallback | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |
| Hard refactoring, recovery from failed runs | `Qwen/Qwen3-Coder-Next` | 94% | 131072 |

Read on 2026-11-09, when the store held 92 models. The shares have already
moved once — a model that took 55% of the pool took 47% on this read — so
re-read them before trusting this table.

Combinations that cannot be resident together, from the same read:

| Combination | NPU | Verdict |
|---|---|---|
| `Qwen/Qwen3.6-35B-A3B` + `endless-frontier/BigBang-v1-Turbo` | 101% | Impossible |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` + `Qwen/Qwen3.6-35B-A3B` | 102% | Impossible |
| `Qwen/Qwen3.8-27B` + `endless-frontier/BigBang-v1-Turbo` | 105% | Impossible |
| `Qwen/Qwen3.6-35B-A3B` + `openai/gpt-oss-20b` | 74% | Fits |
| `openai/gpt-oss-20b` + `Qwen/Qwen3.5-9B` | 56% | Fits comfortably |

---

## Reasoning mode is part of the route

Which model gets the task is only half the decision. The other half is
whether that model reasons before it answers — and the answer is not the same
for every model in the table, which is why it cannot be a boolean in the
config.

Three things make it a routing decision rather than a setting:

**The control differs per model.** Some models have a switch that stops the
trace dead; some have only named reasoning levels, and their switch is
ignored; some do not reason at all. A single boolean is right for one family
and silently wrong for the next.

**The switch is not always a switch.** A device that flags a model as having
no on/off control may be wrong about that, and a level that works for one
model family is discarded by the next because it is read from a different
place in the request.

**"Off" cannot always mean "off".** For a model with no working switch, the
honest answer is the cheapest state it offers, not a refusal and not a claim
that reasoning stopped.

The pattern that follows: read the capability from the provider at route
time, apply the control that model honours, and **report the achieved state,
not the requested one**. A route that asked for `off` and landed on the
cheapest level did not turn reasoning off, and a label that says otherwise
is a lie the operator pays for.

---

## Reference checklist

Before trusting a routing setup:

- [ ] The tier table carries the NPU share and context window for every
      model, read from the device — not from memory, and not from a
      previous read of the same table.
- [ ] Every model in the table exists in the device's store.
- [ ] The NPU shares of the models a batch needs sum to 100% or less, and a
      batch that does not fit is split into waves.
- [ ] The router chooses; a separate controller loads. The plugin never loads
      or unloads a model.
- [ ] The controller decides what to evict before it loads — the device's own
      eviction choice is not batch-aware.
- [ ] The device is locked for the duration, and the lock expires.
- [ ] An unrecognised tier is refused, not silently mapped to the fallback.
- [ ] The generalist fallback is a deliberate choice, not an accident.
- [ ] Reasoning mode is a per-task parameter — 'off' for mechanical work,
      'on' for novel reasoning, 'auto' for the model's native behaviour.
- [ ] The control that is applied matches what the model honours, and the
      route reports the state the model actually reached.
- [ ] A model with no working switch gets its cheapest reasoning level
      rather than a refusal or a false claim.
- [ ] An output floor is set whenever reasoning is in play: a small budget
      spends itself on the trace and returns an empty answer with a 200.
- [ ] Residency is checked with `tiiny top`, not `tiiny ls`.
- [ ] A hold file prevents the watchdog from evicting a deliberate swap.
- [ ] The hold check runs before the cold-check.
- [ ] The required model set is restored after a deliberate swap.
- [ ] A routing checker can show the tier, model, budget and reasoning state
      for a goal before a batch spends tokens on it.
- [ ] Every task's route can be read back from the child's result.
