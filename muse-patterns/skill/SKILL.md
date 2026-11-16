---
name: muse-patterns
description: "Add proactive planning to a Hermes agent. Standing objectives are evaluated on a schedule, trust scoring gates them so a pattern must earn the right to fire, and an optional daily scan uses a local model to suggest new objectives."
version: 1.0.0
author: Gary Garcia (garciacionet-alt), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [proactive, objectives, trust-scoring, pattern-detection, cron, local-inference, scheduling]
    related_skills: [tiiny-model-routing]
---

# Muse Patterns — Proactive Planning Engine

Fills the gap between Hermes's reactive cron/delegation system and Muse's proactive planning.

## What it does

- **Pattern Detection**: Reads kanban/cron/session history, uses a local model to extract recurring patterns as standing objectives
- **Trust Scoring**: Each pattern gets a score (0.0–1.0) that increases on success, decreases on ignore; only fires when score >= threshold (default 0.6)
- **Standing Objectives**: Persistent if/then rules that survive across sessions, evaluated by a daemon loop every 15 minutes
- **Pattern Learning**: Once per day, the system scans history for new patterns and suggests them as objectives

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Muse Daemon (every 15 min)                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 1. Evaluate standing objectives                   │  │
│  │ 2. Fire actions (kanban tasks, notifications)     │  │
│  │ 3. Update trust scores                            │  │
│  │ 4. If no actions fired → check for pattern scan   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Pattern Detection (once/day)                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 1. Load kanban history, cron results, sessions    │  │
│  │ 2. Send to Qwen3.6-35B-A3B on the local endpoint │  │
│  │ 3. Extract patterns → JSON                        │  │
│  │ 4. Save high-confidence patterns as objectives     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## File locations

| Component | Path |
|---|---|
| Trust scoring | `muse-patterns/trust/trust_scoring.py` |
| Objectives engine | `muse-patterns/objectives/objectives_engine.py` |
| Pattern detection | `muse-patterns/scripts/pattern_detection.py` |
| Daemon | `muse-patterns/daemon/muse_daemon.py` |
| Test harness | `muse-patterns/tests/test_muse_system.py` |

## Usage

### Install

Copy the `muse-patterns/` folder into your agent's skills directory:

```bash
cp -r /path/to/muse-patterns ~/.hermes/skills/muse-patterns
```

The folder is self-contained. Every path and endpoint it uses is read from
the environment with a working default — see [Configuration](#configuration).


### Run once (for testing)

```bash
cd ~/.hermes/skills/muse-patterns/daemon
python3 muse_daemon.py
```

### Run as a scheduled job

Add it to your agent's scheduler:
```bash
# Run every 15 minutes
python3 ~/.hermes/skills/muse-patterns/daemon/muse_daemon.py
```

### Run pattern detection manually

```bash
cd ~/.hermes/skills/muse-patterns/scripts
python3 pattern_detection.py
```

## Configuration

### Trust scoring

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_SCORE` | 0.5 | Starting score for new patterns |
| `SCORE_UP` | 0.1 | How much to increase on success |
| `SCORE_DOWN` | 0.2 | How much to decrease on ignore |
| `DEFAULT_THRESHOLD` | 0.6 | Minimum score to fire |

Trust data is stored in `~/.hermes/muse-trust.json`.

### Standing objectives

Objectives are stored in `~/.hermes/muse-objectives.yaml`. Edit this file directly to add/remove rules.

### Daemon

| Setting | Default | Description |
|---|---|---|
| `EVALUATION_INTERVAL` | 900s | How often to evaluate objectives |
| `PATTERN_DETECTION_INTERVAL` | 86400s | How often to scan for patterns |
| `TRUST_THRESHOLD` | 0.6 | Minimum trust score to fire |
| `MUSE_TIINY_URL` | `http://127.0.0.1:8767/v1` | The OpenAI-compatible endpoint for pattern detection |
| `MODEL_ID` | `Qwen/Qwen3.6-35B-A3B` | Model for pattern detection |

## Sample Objectives (from `muse-objectives.yaml`)

1. **Weekly Job Alert Review** — every Tuesday 9-17, create kanban task to review alerts
2. **Meeting Preparation** — 30 minutes before a meeting, notify to prepare notes
3. **Task Deadline Reminder** — 2 days before a task is due, notify to check progress
4. **Morning Briefing** — Mon/Fri 7-9am, draft weekly summary email

## How to use it

1. **Install** — copy the `muse-patterns/` folder into your agent's skills directory
2. **Point at a model** — set `MUSE_TIINY_URL` and `TIINY_API_KEY` if you want the daily pattern scan (everything else runs without one)
3. **Schedule it** — `python3 muse_daemon.py` every 15 minutes
4. **Run pattern scan** — `python3 pattern_detection.py` once per day (midnight)
5. **Review kanban** — outputs go to the kanban board for user approval

## Trust Scoring Behavior

```
New pattern → score 0.5
If fires & succeeds → score += 0.1
If fires & ignored → score -= 0.2
Only fires when score >= 0.6 (threshold)

Example:
  0.5 → 0.6 → 0.7 → 0.8 → 0.9 → 1.0 (max)
  0.9 → 0.7 (once ignored) → 0.5 (twice) → stops firing
  0.5 → 0.6 → 0.7 → 0.8 (recovers with 3 successes)
```

## Testing

```bash
cd ~/.hermes/skills/muse-patterns/tests
python3 test_muse_system.py
```

Tests:
- Trust scoring (load, update, threshold)
- Objectives engine (load, evaluate trigger)
- File structure
- Pattern detection module
- Daemon module
