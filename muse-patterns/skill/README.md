# Muse Patterns — Proactive Planning for an Agent

Adds proactive planning to an agent: standing objectives evaluated on a
schedule, trust scoring that gates them, and an optional daily scan that
uses a local model to suggest new objectives.

The idea is simple. A reactive agent does what it is asked. A proactive one
also notices things worth doing: the meeting coming up in half an hour, the
task about to go stale, the inbox that has been filling since Tuesday.

The hard part is not noticing — it is **noticing at the wrong time**. An
agent that speaks up on every cycle gets muted, and a muted agent is worse
than a reactive one. So every objective here has to earn the right to fire,
and the mechanism for that is a number, not a setting.

## The three pieces

| Component | Purpose | Needs an LLM? |
|---|---|---|
| `trust/trust_scoring.py` | Score per objective, 0.0–1.0. Rises on success, falls on being ignored. Fires only at or above threshold. | No |
| `objectives/objectives_engine.py` | The objectives themselves, in YAML. Trigger evaluation. | No |
| `daemon/muse_daemon.py` | The loop. Evaluates objectives, fires actions, updates trust. | No |
| `scripts/pattern_detection.py` | Reads work history, asks a local model for new patterns, saves them as objectives. | Yes |

Only the pattern scan needs a model, and it runs once a day. Everything else
is plain Python — so the core loop costs nothing and keeps running when the
model is unavailable.

## How trust gating works

```
New pattern          → 0.5   (below threshold — does not fire yet)
Fires and succeeds   → +0.1
Fires and is ignored → -0.2
Threshold            → 0.6
```

A pattern starts at 0.5, which is **below** the threshold. It cannot fire
until it has succeeded once. Each success adds 0.1, so the second success
takes it to 0.7 and it starts firing. Two ignores take it from 0.9 to 0.5 and
it stops entirely — three more successes bring it back.

The practical effect: **a bad pattern announces itself once, quietly, and
then goes away.** You never get a stream of noise from something the agent
invented.

## Triggers

An objective's trigger says when it applies.

| Trigger | Meaning |
|---|---|
| `day_of_week` | `Tue`, `Mon,Fri`, or a range like `Mon-Fri` / `Mon-Sun` |
| `hour_range` | `"09-17"` — 9am to 5pm local |
| `meeting_in_minutes` | Fires N minutes before a meeting |
| `task_due_in_days` | Fires N days before a task is due |
| `has_new_job_alerts` | Fires when the context says so |

**A trigger the engine cannot evaluate does not fire.** If a condition needs
a calendar and the caller has not supplied one, the objective stays quiet
rather than firing on every cycle. This is the single most important rule in
the engine.

## Install

```bash
cp -r /path/to/muse-patterns ~/.hermes/skills/muse-patterns
```

The folder is self-contained. Every path and endpoint it uses is read from
the environment with a working default — see [Configuration](#configuration).

## Verify

```bash
ls ~/.hermes/skills/muse-patterns/trust/trust_scoring.py
ls ~/.hermes/skills/muse-patterns/objectives/objectives_engine.py
ls ~/.hermes/skills/muse-patterns/scripts/pattern_detection.py
ls ~/.hermes/skills/muse-patterns/daemon/muse_daemon.py

cd ~/.hermes/skills/muse-patterns/tests
python3 test_muse_system.py
```

The harness covers trust scoring, trigger evaluation, the module structure,
and a regression test per defect that shipped in an earlier version of this
code.

## Run once (for testing)

```bash
cd ~/.hermes/skills/muse-patterns/daemon
python3 muse_daemon.py
```

Expected output when nothing fires:

```
[muse-daemon] Evaluation cycle starting...
[muse-daemon] Output: [SILENT]
```

Expected output when something fires:

```
[muse-daemon] Evaluation cycle starting...
[muse-daemon] Created kanban task: muse_20261115_223330.md
[muse-daemon] 1 actions fired:
- Weekly Job Alert Review: create_kanban_task (trust: 0.7)
```

`[SILENT]` is the important one. A scheduled job that returns it produces no
notification — so a quiet cycle is genuinely quiet, not a quiet message.

## Run as a scheduled job

```bash
# Every 15 minutes
python3 ~/.hermes/skills/muse-patterns/daemon/muse_daemon.py
```

The daemon runs one cycle and exits. It is a scheduled job, not a resident
process — there is nothing to supervise and nothing to leak if it dies.

## Run pattern detection manually

```bash
cd ~/.hermes/skills/muse-patterns/scripts
python3 pattern_detection.py
```

## Configuration

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `MUSE_TIINY_URL` | `TIINY_BASE_URL`, else `http://127.0.0.1:8767/v1` | The OpenAI-compatible endpoint used for pattern detection |
| `TIINY_API_KEY` | — | Bearer for that endpoint |
| `MUSE_MODEL_ID` | `Qwen/Qwen3.6-35B-A3B` | Model used for pattern detection |
| `MUSE_OBJECTIVES_FILE` | `~/.hermes/muse-objectives.yaml` | Where objectives live |
| `MUSE_TRUST_FILE` | `~/.hermes/muse-trust.json` | Where trust scores live |
| `MUSE_OUTPUT_DIR` | `~/.hermes/muse/kanban/inbox` | Where fired actions are written |
| `MUSE_KANBAN_DB` | `~/.hermes/kanban.db` | Kanban database, read for history |
| `MUSE_CRON_DIR` | `~/.hermes/cron/output` | Cron output, read for history |

### Trust scoring

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_SCORE` | 0.5 | Starting score for a new pattern |
| `SCORE_UP` | 0.1 | Increase on success |
| `SCORE_DOWN` | 0.2 | Decrease on ignore |
| `DEFAULT_THRESHOLD` | 0.6 | Minimum score to fire |

### Daemon

| Setting | Default | Description |
|---|---|---|
| `EVALUATION_INTERVAL` | 900s | How often to evaluate objectives |
| `PATTERN_DETECTION_INTERVAL` | 86400s | How often to scan for patterns |
| `TRUST_THRESHOLD` | 0.6 | Minimum trust score to fire |

### Objectives file

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
```

Action types: `notify`, `create_kanban_task`, `draft_email`, `review_alerts`.

## Testing

```bash
cd ~/.hermes/skills/muse-patterns/tests
python3 test_muse_system.py
```

## Dependencies

- Python 3.9+ (standard library)
- PyYAML
- An OpenAI-compatible endpoint for the pattern scan (optional — everything
  else runs without one)

## License

MIT. See the `LICENSE` file in the repository root.
