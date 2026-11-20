# Choosing a model per project role

The tier table answers "what shape is this sub-task?". A multi-day project
asks a different question: which model holds each **role** — planner, manager,
worker — and which box does each one live on. Role is decided by what the
loop does, not by what its output looks like.

## The three roles

| Role | What the loop does | What it actually needs | Fails when |
|---|---|---|---|
| **Planner / designer** | reads a spec or a codebase once, produces a plan or a design | depth per token, a big window, tunable reasoning | it is a throughput-optimised MoE asked to do its one expensive job |
| **Manager** | holds a task board open across dozens of tool calls, dispatches children, checks their work | state retention across turns, reliable tool calling, cheap enough to stay resident | it re-derives context every turn, or it is too big to coexist with anything |
| **Worker** | one bounded edit, research run or index sweep | the specialisation (code / research / mechanical) | — |

The manager is the role people get wrong. It is not a reasoning role; it is a
**state-retention** role, and the model that wins it is the one whose
architecture is built to keep a task open, not the one that reasons hardest.

## Decision table (93-model store, ~48 GiB NPU pool)

| Role | Pick | Why | Watch out |
|---|---|---|---|
| Planner, standing | `Qwen/Qwen3.8-27B` @ `reasoning_effort: xhigh` | the only dense 27B with a 256K window and tunable depth; per-token depth over throughput is exactly a one-shot design read | 52% NPU, so one small companion fits and little else |
| Planner, escalation | `openai/gpt-oss-120b` @ `high` | deepest reasoning in the store | 100% NPU, 128K — single-occupant, and needs the harmony response format. Load it for the hard decision, unload it after |
| Manager | `Qwen/Qwen3.6-35B-A3B` | thinking preservation across turns + repository-level tool calling + 256K, at 47% so a second model can sit beside it | none material — it is the generalist, and usually already resident |
| Manager, NPU-tight | `openai/gpt-oss-20b` | 27% NPU, three reasoning levels | 128K, and weaker at holding state over a long loop — fallback, not first choice |
| Worker, code | `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo`, `Ornith-1.5-35B-A3B-Turbo` | built for terminal/repo agentic work | the Coder is 64K — repository-scale work needs the Ornith or the 35B-A3B |
| Worker, mechanical | `gpt-oss-20b` thinking off | cheapest capable resident | — |

## The discriminators, in the order they decide

1. **Dense vs MoE, not parameter count.** An `A3B`/`A4B` model activates 3–4B
   per token: it runs like a small model and therefore *reasons* like one per
   token. That is a great trade for throughput and a bad one for a single
   irreversible design read. Pick dense where the output is the deliverable and
   MoE where volume is.
2. **Thinking preservation is the manager feature.** `Qwen3.6-35B-A3B` retains
   its reasoning trace across turns instead of re-deriving it. A manager loop
   is precisely the workload that pays for it: dozens of tool calls in one
   session, each one cheaper when the trace survives.
3. **Tunable reasoning depth is the planner feature.** `Qwen3.8-27B` is the
   only vision-tier model with `low`/`medium`/`xhigh`; without a depth knob you
   cannot ask a planner to think harder for the one call that matters.
4. **A 100% NPU model is a visitor, not a resident.** `gpt-oss-120b` and
   `Qwen3-Coder-Next` (94%) are escalation and one-shot tools — anything you
   keep loaded alongside them does not fit.
5. **A stated orchestration capability can be dormant.** `Sage-A1.5-Turbo`
   advertises parallel subagents and self-verification, but the orchestration
   only activates when the host registers a dedicated subagent tool. On a plain
   chat/completions route it is a well-tuned Qwen3.6 and nothing more. Read the
   capability against the host, not against a wish list.
6. **Check the input size before arguing about context.** A 20 KB
   requirements doc is roughly 6K tokens, so a 128K window is not the binding
   constraint and choosing on window size alone picks the wrong model.
   Context decides only when the repo or transcript actually approaches it.

## Topology on two boxes

Two boxes are two independent generation streams, and each is still
single-stream internally. The shape that uses both:

1. **Plan phase** on the flex box (the one that does not declare
   `keep_resident` for the generalist) — it is expected to be swapped.
2. **Run phase**: the manager stays on the box that already holds the
   generalist, so it needs no swap and survives reboots if restore is enabled;
   workers go to the flex box.

Two consequences worth stating out loud before the run:

- The plan phase and the workers share the flex box, so they are **sequential**.
  Finish planning before loading a worker model, or the worker load evicts the
  planner mid-thought.
- Loading a worker on the flex box evicts that box's resident planner; a
  manager that retries a failed turn onto the flex box evicts it too. See the
  mesh-policy pitfall in SKILL.md.

## Reporting it to the user

Give the pick, the box, the NPU share and the reasoning setting in a table,
then one line each on *why that model* and *what to avoid*. Name the
solo-occupant and the dormant-orchestration cases explicitly — they are the
choices a reader would otherwise make confidently and wrongly.
