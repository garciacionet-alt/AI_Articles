# Muse Patterns: Proactive Planning for an Agent

**A reactive agent does what you ask. A proactive one also notices what you
did not.** The gap between those two is where most of the value in an agent
lives — and it is also where most of the noise lives.

Muse Patterns closes the gap with three mechanisms: **standing objectives**
that say when something is worth doing, **trust scoring** that decides which
of them are allowed to speak up, and a **daily pattern scan** that watches
your work history for new ones.

The design premise worth stating up front: **a proactive agent that speaks
up too often is worse than a reactive one.** You mute it, and you lose the
one thing it was for. So every objective here has to earn the right to fire,
and the mechanism for that is a number, not a setting.

---

## The problem

An agent is very good at being asked. It is bad at noticing.

The things worth noticing are rarely dramatic. There is a meeting in
twenty-five minutes and nobody prepared notes. A task goes stale on
Thursday. You check the same feed every Tuesday and then write the same
summary every Tuesday. None of that announces itself — it is just a shape
in your week that nobody named.

You can name it yourself. That is what a standing objective is: a rule, in
YAML, that says when a condition holds and what should happen then.

```yaml
- id: "obj_job_alert_review"
  name: "Weekly Job Alert Review"
  trigger:
    day_of_week: "Tue"
    hour_range: "09-17"
  action:
    type: "create_kanban_task"
    title: "Review and summarize job alerts"
```

That works. The problem is the second one.

## The problem with naming it yourself

Write five of those rules and you have written five things that will fire on
a schedule whether or not they are still relevant. One of them will be
wrong within a month. It will fire every Tuesday at 9am, forever, and it
will be noise — so you will start ignoring the channel, and the four that
were right will go with it.

The failure is not that a rule is wrong. The failure is that **a wrong rule
is indistinguishable from a right one at the moment it fires.** Both produce
a message. Only one of them was worth producing.

So the missing piece is not a way to write more rules. It is a way to tell
the agent which of its rules have earned the right to speak.

## Trust scoring

Each objective carries a score between 0 and 1. It goes **up when the
objective does something useful** and **down when it is ignored**. It fires
only at or above a threshold.

```
New pattern          → 0.5    (below threshold — cannot fire)
Fires and succeeds   → +0.1
Fires and is ignored → -0.2
Threshold            → 0.6
```

A new pattern starts at 0.5, which is **below** the 0.6 threshold. It sits
there silently until it succeeds once, then it crosses to 0.6 and starts
firing. Two ignores take it from 0.9 down to 0.5 and it stops entirely.
Three more successes bring it back.

The behaviour this buys is the thing worth having:

> **A bad pattern announces itself once, quietly, and then goes away.**

It is not that bad rules are prevented. It is that they are cheap, and
self-limiting. The channel stays worth reading because the noise retires
itself.

## The daily scan

Naming every rule by hand does not scale — the value is in the patterns you
did not notice. So a once-daily scan reads your work history and asks a
model what recurring shapes are in it.

```
Every 15 minutes:   evaluate objectives → fire → update trust
Once a day:          read history → ask the model → propose new objectives
```

The scan is the only part that needs a model. Everything else — the
evaluation loop, the trust arithmetic, the trigger matching — is plain
Python, so **the core loop costs nothing and keeps running when the model
is unavailable.** A pattern scan that fails leaves the daemon working; it
just leaves tomorrow's objectives unrefreshed.

Because the scan is optional and runs daily, it can afford to run against a
**local** model. Nothing about pattern detection needs frontier capability —
it is reading a few hundred lines of history and asking for structured JSON.
On a local appliance that is free, and it means the agent's most intimate
data (your work history) never leaves the machine.

## How a trigger is evaluated

A trigger says when an objective applies. Two forms:

```yaml
trigger:
  day_of_week: "Tue"      # single day
  hour_range: "09-17"     # local time window
```

and the ones that need context:

```yaml
trigger:
  meeting_in_minutes: 30
  task_due_in_days: 2
  has_new_job_alerts: true
```

Those three cannot be evaluated by a clock. They need facts the engine does
not have — a calendar, a task tracker, a mail client. The caller gathers
them and passes them in as context.

**Which brings us to the single most important rule in the engine.**

### An unevaluable trigger does not fire

If an objective carries a condition the engine cannot evaluate, and the
caller has not supplied the context for it, the objective **stays quiet**.

The tempting alternative is to treat an unevaluable condition as satisfied —
to return "true" and move on. Do not. Here is what that does:

A `meeting_in_minutes: 30` objective has no `day_of_week` and no
`hour_range`. A parser that checks only the conditions it recognises finds
nothing to check, falls through the end of the function, and returns its
default. If that default is `true`, the objective fires **on every single
cycle** — every fifteen minutes, forever, at two in the morning. If it is
`false`, it never fires, and a rule you wrote correctly does nothing.

Both are silent. Neither raises. The objective just appears in the file and
never does anything, or appears in the file and does something constantly.

The engine therefore fails **closed**, and it fails closed for two reasons:

1. **Unknown condition keys.** A trigger key the engine does not recognise
   is a reason not to fire. The engine cannot know what the author meant,
   and guessing in the direction of "fire anyway" is how you get woken up at
   2am.
2. **Known condition keys with no context.** `meeting_in_minutes` is a
   legitimate trigger. Without a calendar it is not evaluable, and an
   objective that is not evaluable does not fire.

The same reasoning applies to the trigger *shape*. The detector's model emits
a nested trigger:

```json
{"type": "schedule", "schedule": {"day_of_week": "Tue", "hour_range": "09-17"}}
```

while the engine reads a flat one. A saved objective holding the nested
shape has trigger keys the engine does not recognise — so under the rule
above it would never fire, whatever the model's confidence. The fix is a
translation step, not a relaxation of the rule: the nested form is
translated to the flat form at the boundary, and anything still
untranslatable is dropped with a message rather than saved inert.

This is worth stating plainly because it is the defect that made an earlier
version of this code look functional while doing nothing at all.

## What the agent does when an objective fires

Actions are deliberately boring, because the agent is offering, not acting:

| Action | Effect |
|---|---|
| `notify` | A message |
| `create_kanban_task` | A task file in the inbox for review |
| `draft_email` | A draft, not a send |
| `review_alerts` | A task to review and summarise |

Nothing is sent, nothing is published, nothing is deleted. The agent writes
a file and the human decides. That is a deliberate boundary: **the value of
proactivity is that it shortens the gap between noticing and acting, and
shortening it is not the same as removing the human from the loop.**

## The shape of the code

```
┌─────────────────────────────────────────────────────────┐
│  Muse Daemon (every 15 minutes)                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 1. Load standing objectives (YAML)                │  │
│  │ 2. Evaluate triggers (day/hour/context)           │  │
│  │ 3. Check trust scores (≥ 0.6 to fire)             │  │
│  │ 4. Execute actions (task / notify / draft)        │  │
│  │ 5. Update trust scores (+0.1 success, -0.2 ignore)│  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Pattern Detection (once/day)                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 1. Load kanban history, cron output, sessions    │  │
│  │ 2. Send to a local model                          │  │
│  │ 3. Extract patterns → structured rules            │  │
│  │ 4. Save high-confidence patterns as objectives    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

Five modules, about 1,250 lines of Python, no JavaScript:

| Module | Purpose | Needs a model? |
|---|---|---|
| `trust/trust_scoring.py` | The score arithmetic | No |
| `objectives/objectives_engine.py` | Load objectives, evaluate triggers | No |
| `daemon/muse_daemon.py` | The evaluation loop | No |
| `scripts/pattern_detection.py` | Read history, ask the model | Yes |
| `tests/test_muse_system.py` | The harness | No |

Only one module needs a model. That ratio is the design.

## The parts that are easy to get wrong

This code has been through a round of defects that all shared one shape:
**the system looked healthy while doing nothing.** Four of them are worth
naming, because each one has a lesson that generalises.

**A test harness can hide a broken entry point.** The harness set up its
module paths correctly. The daemon did not — it pointed at its own folder
instead of its sibling, and could not import anything. The tests passed
because they exercised a different path than production. The fix was to
assert, in the harness, that the paths the daemon computes are the paths the
daemon needs. A green test suite is evidence about the code the test
touches, not about the code that ships.

**A query can name a column that does not exist.** The kanban reader
selected `updated_at`, which the schema does not have. The query raised,
the exception was swallowed into a warning, and the function returned an
empty list. The detector reported zero tasks, every time, and nothing
looked wrong. The column list is now derived from the live schema.

**The output shape of a producer is the input shape of a consumer.** The
model emits nested triggers; the engine reads flat ones. Both sides were
individually reasonable. Together they meant every detected pattern was
saved in a form that could never fire. When two components meet at a
boundary, the boundary is where the test belongs.

**A hardcoded path works on exactly one machine.** The first version named
one laptop's directory layout and one private LAN address. It would have
worked on that laptop and nowhere else — and would have failed on the
author's next install, which is the failure that costs the most time.
Everything is read from the environment now, with a working default.

There is also a fifth, about a trust score: **a score that only goes up is
not a trust score.** It is a ratchet. The value of the mechanism is entirely
in the downward branch, and it is the branch that is hardest to observe —
which is why the harness asserts both directions rather than just the
happy one.

## Quick start

```bash
# Install
cp -r muse-patterns ~/.hermes/skills/muse-patterns

# Check it
cd ~/.hermes/skills/muse-patterns/tests
python3 test_muse_system.py

# Run one cycle
cd ~/.hermes/skills/muse-patterns/daemon
python3 muse_daemon.py
```

A quiet cycle prints `[SILENT]`. That string matters: a scheduled job that
returns it produces no notification, so **a quiet cycle is genuinely quiet,
not a quiet message.** An agent that says "nothing to report" every fifteen
minutes has taught you to ignore it.

## What is shipped

- `PATTERN.md` — the portable design: the principles, the failure modes, the
  reasoning behind each default
- `IMPLEMENTATION.md` — the concrete setup: environment, commands, the
  checklist
- `skill/` — the installable skill: the five modules, the harness, and the
  skill manifest

## License

MIT.
