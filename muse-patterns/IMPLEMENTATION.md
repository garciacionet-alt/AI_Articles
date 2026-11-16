# Implementation

The concrete setup. Five modules, about 1,250 lines of Python, no
JavaScript, and one optional model endpoint.

---

## Layout

```
muse-patterns/
├── trust/
│   └── trust_scoring.py        # the score arithmetic
├── objectives/
│   └── objectives_engine.py    # load objectives, evaluate triggers
├── daemon/
│   └── muse_daemon.py          # the evaluation loop
├── scripts/
│   └── pattern_detection.py    # read history, ask the model
├── tests/
│   └── test_muse_system.py     # the harness
├── SKILL.md
└── README.md
```

The four code directories are siblings, and each module that needs another
puts that module's directory on `sys.path` before importing it. There is no
package to install and no dependency to resolve — copy the folder and it
runs.

## Requirements

- **Python 3.9+.** Standard library only, apart from one dependency below.
- **PyYAML.** The objectives file is YAML.
- **An OpenAI-compatible endpoint.** Optional. Only the daily pattern scan
  uses it, and every other part of the system runs without one.

```bash
pip install pyyaml
```

## Install

```bash
cp -r muse-patterns ~/.hermes/skills/muse-patterns
```

Or, to install it as a loadable skill, copy it into whatever directory your
agent resolves skills from and make sure `SKILL.md` is at the top.

## Configuration

Everything is read from the environment, with a working default for each.

| Variable | Default | Purpose |
|---|---|---|
| `MUSE_TIINY_URL` | `TIINY_BASE_URL`, else `http://127.0.0.1:8767/v1` | The OpenAI-compatible endpoint for pattern detection |
| `TIINY_API_KEY` | — | Bearer token for that endpoint |
| `MUSE_MODEL_ID` | `Qwen/Qwen3.6-35B-A3B` | Model used for pattern detection |
| `MUSE_OBJECTIVES_FILE` | `~/.hermes/muse-objectives.yaml` | Where the objectives live |
| `MUSE_TRUST_FILE` | `~/.hermes/muse-trust.json` | Where trust scores live |
| `MUSE_OUTPUT_DIR` | `~/.hermes/muse/kanban/inbox` | Where fired actions are written |
| `MUSE_KANBAN_DB` | `~/.hermes/kanban.db` | Kanban database, read for history |
| `MUSE_CRON_DIR` | `~/.hermes/cron/output` | Cron output, read for history |

The `MUSE_` prefix keeps these from colliding with the environment the
agent already has. The defaults point at the conventional locations for a
Hermes install, so on a standard machine **no configuration is needed at
all** for the daemon to work — only for the scan to find a model.

### Pointing at a local model

The scan needs an OpenAI-compatible endpoint. A local appliance or a local
server both work:

```bash
export MUSE_TIINY_URL="http://<your-endpoint>/v1"
export TIINY_API_KEY="your-device-key"
export MUSE_MODEL_ID="Qwen/Qwen3.6-35B-A3B"
```

Two things about the request matter.

**The reasoning switch has a specific shape.** It goes at
`extra_body.chat_template_kwargs.enable_thinking`, not at the top of
`extra_body`:

```python
"extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
```

The wrong shape is not an error — the device ignores it, the model reasons
for the whole token budget, and the response comes back empty with a
success status. If pattern detection returns nothing and reports no error,
check this first.

**`max_tokens` needs a floor.** A reasoning model with a small token
budget returns empty content with HTTP 200. The scan uses 4096.

## Running it

### One cycle

```bash
cd ~/.hermes/skills/muse-patterns/daemon
python3 muse_daemon.py
```

Quiet:

```
[muse-daemon] Evaluation cycle starting...
[muse-daemon] Output: [SILENT]
```

Fired:

```
[muse-daemon] Evaluation cycle starting...
[muse-daemon] Created kanban task: muse_20261115_223330.md
[muse-daemon] Action executed for 'Weekly Job Alert Review': success (trust: 0.7)
[muse-daemon] 1 actions fired:
- Weekly Job Alert Review: create_kanban_task (trust: 0.7)
```

**`[SILENT]` is a contract.** A scheduler that recognises it produces no
notification. Use it, and the agent stays genuinely quiet between events.

### As a scheduled job

```bash
python3 ~/.hermes/skills/muse-patterns/daemon/muse_daemon.py
```

Every fifteen minutes is the default interval. The daemon runs one cycle and
exits — it is not a resident process, so there is nothing to supervise and
nothing to leak if it dies.

Set the interval in `daemon/muse_daemon.py`:

```python
EVALUATION_INTERVAL = 900                    # seconds
PATTERN_DETECTION_INTERVAL = 86400           # seconds
TRUST_THRESHOLD = 0.6
```

### The pattern scan, on its own

```bash
cd ~/.hermes/skills/muse-patterns/scripts
python3 pattern_detection.py
```

```
[muse-patterns] Starting pattern detection...
[muse-patterns] Loading history...
[muse-patterns] Loaded 0 tasks, 40 cron results, 10 summaries
[muse-patterns] Sending to Qwen for pattern detection...
[muse-patterns] Detected 2 patterns
  - Engraphis MCP Watchdog Execution (confidence: 0.95)
  - MiniMax API Connection Failure Monitoring (confidence: 0.85)
[muse-patterns] Saved objective: Engraphis MCP Watchdog Execution
[muse-patterns] Skipped 'MiniMax API Connection Failure Monitoring': trigger
  {'type': 'context', 'context': 'api_request_log_contains_max_retries'} maps to
  no evaluable condition
[muse-patterns] Pattern detection complete.
```

That last line is the system working correctly, not a warning to worry
about: a pattern whose trigger maps to nothing the engine can evaluate is
**skipped rather than saved inert**. An objective that can never fire is
worse than no objective, because it looks like coverage.

## The objectives file

`~/.hermes/muse-objectives.yaml`. Created with four examples the first time
it is read, and yours to edit from there.

```yaml
objectives:
  - id: "obj_job_alert_review"
    name: "Weekly Job Alert Review"
    trigger:
      day_of_week: "Tue"
      hour_range: "09-17"
    action:
      type: "create_kanban_task"
      title: "Review and summarize job alerts"
      body: "Review job alerts every Tuesday. Check new alerts and produce a summary."
    priority: 3
    enabled: true
    objective_type: "cron"
    initial_score: 0.6
```

### The grant — `initial_score`

`initial_score` is the score an objective starts at. It is optional, and
it is the only thing that can start an objective.

An objective without one has no history, so it scores at `DEFAULT_SCORE`
(0.5) — below the 0.6 threshold — and it never fires. It cannot climb out
of that either: it does not fire, so it cannot succeed, so it stays at 0.5.
The threshold is meant to be load-bearing, but a pattern with no way in
never gets a hearing at all.

So there are two ways to grant one:

- **A detected pattern gets it automatically.** The scan already refuses to
  save a pattern it is less than 0.6 confident about; that confidence now
  becomes the objective's `initial_score`, so the model's judgement is the
  vouch rather than a gate that leads nowhere.
- **A hand-written objective grants one itself.** Declare `initial_score`
  in the YAML:

  ```yaml
    initial_score: 0.6    # starts at the threshold, fires
  ```

The grant applies **once**. On the first firing it is written into the
trust file, and from then on the score is earned from outcomes — one
success takes it to 0.7, one ignore takes it to 0.4, and a second ignore
puts it back below the threshold where it stops firing.

### Triggers

| Key | Form | Evaluated by |
|---|---|---|
| `day_of_week` | `Tue`, `Mon,Fri`, `Mon-Fri`, `Mon-Sun` | A clock |
| `hour_range` | `"09-17"` — local time | A clock |
| `meeting_in_minutes` | `<N>` | Context |
| `task_due_in_days` | `<N>` | Context |
| `has_new_job_alerts` | `true` / `false` | Context |
| `has_unread_email` | `true` / `false` | Context |

A day range is written `Mon-Sun`; a comma list is written `Mon,Fri`. Both
parse, and a range that wraps the week (`Fri-Mon`) is handled.

**A trigger the engine cannot evaluate does not fire.** The context
triggers need a context object passed to the daemon:

```python
daemon = MuseDaemon(context={
    "meeting_in_minutes": 25,
    "task_due_in_days": 1,
    "has_new_job_alerts": True,
})
```

Without one, those objectives stay quiet. That is the intended behaviour —
see `PATTERN.md`, principle 3.

### Actions

| Type | Effect |
|---|---|
| `notify` | Writes a notification file to the inbox |
| `create_kanban_task` | Writes a task file with review checkboxes |
| `draft_email` | Writes a draft to `MUSE_OUTPUT_DIR/drafts/` |
| `review_alerts` | Writes a task to review and summarise |

Everything lands in a file. Nothing is sent.

### Priority

`1` to `5`. Higher priority objectives are evaluated first, and the file
sorts by it.

## The trust file

`~/.hermes/muse-trust.json`:

```json
{
  "obj_job_alert_review": {
    "score": 0.7,
    "successes": 2,
    "ignores": 0,
    "last_updated": "2026-11-15T22:33:30.915890"
  }
}
```

To reset one:

```python
import sys
sys.path.insert(0, "trust")
import trust_scoring
trust_scoring.reset_pattern("obj_job_alert_review")   # back to 0.5
```

## The history the scan reads

Three sources, all optional:

- **Kanban tasks** — from `MUSE_KANBAN_DB`, a SQLite database. The query
  derives its column list from the live schema, so it does not break when
  the schema changes.
- **Cron output** — from `MUSE_CRON_DIR`. Both `.txt` files and the `.md`
  files inside per-job subdirectories are read.
- **Session summaries** — from `~/.hermes/cache/compactions` and
  `~/.hermes/sessions`, as `.md` or `.json`.

The scan sends a compiled slice of this to the model: task titles and
statuses, the head of each cron output, and the head of each session file.
**This is your work history going to the endpoint you configured.** If that
endpoint is a local appliance, it never leaves the machine. If it is not,
it does — and that is a decision worth making on purpose rather than by
default.

## Testing

```bash
cd ~/.hermes/skills/muse-patterns/tests
python3 test_muse_system.py
```

The harness covers trust scoring, trigger evaluation, module structure, and
**twelve regression tests** — one for each defect that shipped in an earlier
version of this code. It is worth reading that list: each test names the
bug it prevents, and together they are a description of the failure modes
this design is exposed to.

The last one is worth singling out, because it is the one that would have
caught the worst bug:

```python
# BUG 1: the daemon put <daemon>/trust on sys.path instead of
# <muse>/trust, so it could never import its own modules and could
# never start. The test harness masked this by using parent.parent.
muse_root = Path(muse_daemon.MUSE_DIR)
assert muse_root == MUSE_DIR
assert (muse_root / "trust" / "trust_scoring.py").exists()
```

The harness had been passing all along. It was passing because it set up
its own module paths correctly — and the program it was nominally testing
could not start at all. The assertion above makes the harness check the
program's own wiring rather than its own.

## End-to-end checklist

For a fresh install, this is the order that proves it works:

1. **Install** the folder and confirm the four modules are present.
2. **Run the harness.** Everything passes, including the twelve regression
   tests.
3. **Run one daemon cycle.** It prints `[SILENT]` — nothing fires yet,
   because an objective with no grant starts at 0.5, below the 0.6
   threshold.
4. **Give one objective a grant** — add `initial_score: 0.6` to it, or put
   a score of 0.6 for it in the trust file.
5. **Run the daemon again.** It fires, writes a task file into
   `MUSE_OUTPUT_DIR`, and reports the new trust score.
6. **Point at a model** and run the pattern scan. It reports the number of
   patterns found, the ones it saved, and any it skipped and why.
7. **Schedule it.** Every fifteen minutes.

Step 3 before step 4 is not a formality — it is the behaviour that makes
the system usable. If an objective fires on its first cycle without anyone
having vouched for it, the trust score is not doing anything.

## Troubleshooting

**The daemon will not start.** Check that the four directories are siblings.
Each module puts its sibling's directory on `sys.path`, so
`trust/trust_scoring.py` must be a sibling of `objectives/`, not nested
inside it.

**The daemon fires nothing.** Work down this list: does the objective have
a grant — an `initial_score`, or an entry in the trust file? Is its trust
score at or above 0.6? Does its trigger evaluate with the current
conditions? Does it use a context trigger with no context supplied?

**The scan returns nothing and reports no error.** Almost always the
reasoning switch. It must be at
`extra_body.chat_template_kwargs.enable_thinking`. The wrong shape is
silently ignored, and the model then spends its whole budget reasoning and
returns empty content.

**The scan finds no history.** Check the paths with
`MUSE_KANBAN_DB` and `MUSE_CRON_DIR`. The cron directory in a standard
install is `~/.hermes/cron/output`, not `~/.hermes/cron`.

**A detected pattern is skipped.** The message says which trigger did not
map to an evaluable condition. Either add a context provider for it or
leave it out — it would not have fired anyway.

**A pattern fires every cycle.** Its trigger holds a condition the engine
does not recognise, and the engine is failing open. This should be
impossible in this version; if it happens, the trigger holds a key outside
the known set, and the check for unknown keys is not being reached.

## License

MIT.
