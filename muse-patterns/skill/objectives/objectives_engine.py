#!/usr/bin/env python3
"""
muse-objectives: Standing objectives (persistent if/then rules).

Each objective has:
- id: unique identifier
- name: human-readable
- trigger: condition to evaluate (e.g., "day_of_week=Tue", "has_new_job_alerts")
- action: what to do when trigger fires (e.g., "draft_job_summary")
- priority: 1 (low) to 5 (high)
- enabled: whether this objective is active
- objective_type: "calendar", "tasks", "cron", "custom"

File: ~/.hermes/muse-objectives.yaml
"""

import yaml
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List

# The objectives file is the reader's own state. It is overridable so a test
# (or a second install) does not touch the live file.
OBJECTIVES_FILE = Path(
    os.environ.get(
        "MUSE_OBJECTIVES_FILE",
        str(Path.home() / ".hermes/muse-objectives.yaml"),
    )
)

# Trigger keys this engine can evaluate with the data it actually has.
#
# Everything else needs context the engine does not have — a calendar, the
# user's mail, a tracker. A trigger type that is NOT in this set must never
# fire: returning True for an unevaluated trigger fires every objective on
# every cycle, which is worse than not firing at all.
EVALUATABLE_TRIGGERS = {"day_of_week", "hour_range"}

# Trigger keys the engine knows how to evaluate once the daemon injects
# context for them. Without context they do not fire.
CONTEXT_TRIGGERS = {
    "meeting_in_minutes",
    "task_due_in_days",
    "has_new_job_alerts",
    "has_unread_email",
}
SAMPLE_OBJECTIVES = """
# Muse Standing Objectives
# Each objective is an if/then rule that fires when conditions are met.
# Only objectives with enabled: true will be evaluated.
#
# Trigger conditions:
#   - day_of_week: Mon,Tue,Wed,Thu,Fri,Sat,Sun (single or comma-separated)
#   - hour_range: "09-17" (9am to 5pm local time)
#   - has_new_job_alerts: true/false (checks kanban for new alerts)
#   - has_unread_email: true/false (checks inbox)
#   - meeting_in_minutes: <N> (fires N minutes before a meeting)
#   - task_due_in_days: <N> (fires N days before a task is due)
#
# Actions (what to do when trigger fires):
#   - notify: "message to send to user"
#   - create_kanban_task: "title of task to create"
#   - draft_email: "email draft subject"
#   - review_alerts: "review and summarize"
#
# The grant — initial_score:
#   - initial_score: 0.0-1.0 — the score this objective STARTS at.
#   - It is the one thing that can start an objective. Without it, an
#     objective sits at DEFAULT_SCORE (0.5), below the threshold, and never
#     fires — the threshold is load-bearing, so nothing starts by accident.
#   - A detected pattern gets its grant from the model's confidence. A
#     hand-written objective declares its own. After the first firing, the
#     grant is spent and the score is earned from outcomes.
#
objectives:
  - id: "obj_job_alert_review"
    name: "Weekly Job Alert Review"
    trigger:
      day_of_week: "Tue"
      hour_range: "09-17"
    action:
      type: "create_kanban_task"
      title: "Review and summarize job alerts from LinkedIn/Greenhouse"
      body: "Review job alerts every Tuesday. Check new alerts and produce a summary."
    priority: 3
    enabled: true
    objective_type: "cron"
    initial_score: 0.6

  - id: "obj_meeting_prep"
    name: "Meeting Preparation"
    trigger:
      meeting_in_minutes: 30
    action:
      type: "notify"
      message: "You have a meeting in 30 minutes. Would you like me to prepare notes?"
    priority: 4
    enabled: true
    objective_type: "calendar"
    initial_score: 0.6

  - id: "obj_task_deadline"
    name: "Task Deadline Reminder"
    trigger:
      task_due_in_days: 2
    action:
      type: "notify"
      message: "A task is due in 2 days. Would you like me to check progress?"
    priority: 3
    enabled: true
    objective_type: "tasks"
    initial_score: 0.6

  - id: "obj_morning_brief"
    name: "Morning Briefing"
    trigger:
      day_of_week: "Mon,Fri"
      hour_range: "07-09"
    action:
      type: "draft_email"
      subject: "Weekly Briefing - {date}"
      body: "Summary of week ahead/week past, key tasks, and calendar events."
    priority: 2
    enabled: true
    objective_type: "cron"
    initial_score: 0.6
"""


def load_objectives() -> List[dict]:
    """Load standing objectives from YAML file, creating with sample if missing."""
    if not OBJECTIVES_FILE.exists():
        # Create with sample objectives
        with open(OBJECTIVES_FILE, "w") as f:
            f.write(SAMPLE_OBJECTIVES)
    
    with open(OBJECTIVES_FILE, "r") as f:
        data = yaml.safe_load(f)
    
    return data.get("objectives", [])


def save_objectives(objectives: List[dict]) -> None:
    """Save objectives back to YAML file."""
    data = {"objectives": objectives}
    tmp = OBJECTIVES_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    tmp.replace(OBJECTIVES_FILE)


def get_enabled_objectives() -> List[dict]:
    """Get all enabled objectives, sorted by priority (highest first)."""
    objectives = load_objectives()
    enabled = [o for o in objectives if o.get("enabled", True)]
    return sorted(enabled, key=lambda x: x.get("priority", 3), reverse=True)


def add_objective(objective: dict) -> None:
    """Add a new standing objective, replacing any with the same id.

    The detector runs once a day and re-derives the same patterns. Appending
    unconditionally meant the objectives file grew a duplicate every day,
    and the daemon then evaluated each copy.
    """
    objectives = load_objectives()
    obj_id = objective.get("id")
    for i, existing in enumerate(objectives):
        if existing.get("id") == obj_id:
            objectives[i] = objective
            save_objectives(objectives)
            return
    objectives.append(objective)
    save_objectives(objectives)


def update_objective(obj_id: str, updates: dict) -> None:
    """Update an existing objective by id."""
    objectives = load_objectives()
    for i, obj in enumerate(objectives):
        if obj.get("id") == obj_id:
            objectives[i].update(updates)
            save_objectives(objectives)
            return
    raise ValueError(f"Objective {obj_id} not found")


def disable_objective(obj_id: str) -> None:
    """Disable an objective (set enabled=false)."""
    update_objective(obj_id, {"enabled": False})


def enable_objective(obj_id: str) -> None:
    """Enable an objective."""
    update_objective(obj_id, {"enabled": True})


DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_ALL_DAYS = [str(d) for d in DAY_NAMES]


def _parse_days(days_str) -> List[str]:
    """Parse a day-of-week specification into a list of day names.

    Three forms appear in practice:
      "Tue"          — a single day
      "Mon,Fri"      — a comma-separated list
      "Mon-Sun"      — a range, which is what the detector's model emits
                       when it means "every day"

    The old parser split on commas only, so "Mon-Sun" produced the single
    token "Mon-Sun", which matched no day — and the objective silently
    never fired.
    """
    text = str(days_str).strip()
    if not text:
        return []

    # A range: Mon-Sun, Mon-Fri
    if "-" in text:
        parts = [p.strip() for p in text.split("-")]
        if len(parts) == 2 and parts[0] in DAY_NAMES and parts[1] in DAY_NAMES:
            start = DAY_NAMES.index(parts[0])
            end = DAY_NAMES.index(parts[1])
            if start <= end:
                return _ALL_DAYS[start:end + 1]
            # A wrapped range such as Fri-Mon.
            return _ALL_DAYS[start:] + _ALL_DAYS[:end + 1]

    return [d.strip() for d in text.split(",") if d.strip()]


def evaluate_trigger(objective: dict, current_time: Optional[datetime] = None,
                     context: Optional[Dict] = None) -> bool:
    """Evaluate whether an objective's trigger conditions are met.

    ``context`` is an optional dict of facts the daemon has gathered —
    ``meeting_in_minutes``, ``task_due_in_days``, ``has_new_job_alerts``,
    ``has_unread_email``. A context trigger fires only when the context
    supplies that fact.

    A trigger this engine cannot evaluate does NOT fire. The previous
    behaviour — returning True for any trigger it did not recognise — made
    every context-triggered objective fire on every single cycle.
    """
    if current_time is None:
        current_time = datetime.now()

    trigger = objective.get("trigger", {})
    if not trigger:
        # An objective with no trigger has no condition to be met.
        return False

    context = context or {}

    # Check day of week
    if "day_of_week" in trigger:
        days_str = trigger["day_of_week"]
        days = _parse_days(days_str)
        day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        current_day = day_map.get(current_time.strftime("%a"))
        if current_day is None or current_day not in [day_map.get(d) for d in days]:
            return False

    # Check hour range
    if "hour_range" in trigger:
        hour_str = str(trigger["hour_range"])
        parts = hour_str.split("-")
        if len(parts) == 2:
            try:
                start_hour = int(parts[0])
                end_hour = int(parts[1])
            except ValueError:
                return False
            current_hour = current_time.hour
            if not (start_hour <= current_hour <= end_hour):
                return False

    # Context triggers: fire only when the context supplies the fact.
    if "meeting_in_minutes" in trigger:
        minutes = context.get("meeting_in_minutes")
        if minutes is None:
            return False
        try:
            if int(minutes) > int(trigger["meeting_in_minutes"]):
                return False
        except (TypeError, ValueError):
            return False

    if "task_due_in_days" in trigger:
        days = context.get("task_due_in_days")
        if days is None:
            return False
        try:
            if int(days) > int(trigger["task_due_in_days"]):
                return False
        except (TypeError, ValueError):
            return False

    for flag in ("has_new_job_alerts", "has_unread_email"):
        if flag in trigger:
            if flag not in context:
                return False
            if bool(context[flag]) != bool(trigger[flag]):
                return False

    # Any trigger key this engine does not know how to evaluate is a reason
    # NOT to fire. Failing open here is what made every objective fire on
    # every cycle.
    unknown = set(trigger) - EVALUATABLE_TRIGGERS - CONTEXT_TRIGGERS
    if unknown:
        return False

    return True


def get_objective_actions(objective: dict) -> List[dict]:
    """Get the actions to take when an objective fires."""
    return objective.get("action", [])
