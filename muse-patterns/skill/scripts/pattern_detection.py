#!/usr/bin/env python3
"""
muse-patterns: Pattern detection engine.

Uses an LLM (Qwen3.6-35B-A3B on Tiiny) to analyze kanban/cron/task history
and extract recurring patterns that can become standing objectives.

LLM Prompt: "Read this work history, find patterns, and output structured rules."
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

# Paths
KANBAN_DB = Path(
    os.environ.get(
        "MUSE_KANBAN_DB",
        str(Path.home() / ".hermes/kanban.db"),
    )
)

# Where to look for cron output and session history. Each is optional: a
# missing directory is skipped, not an error.
#
# The previous values pointed inside a hardcoded project directory, which
# resolved to nothing on any other machine and leaked a private layout.
CRON_DIRS = [
    Path(os.environ.get("MUSE_CRON_DIR", str(Path.home() / ".hermes/cron/output"))),
    Path.home() / ".hermes/cron",
]
SESSION_DIRS = [
    Path.home() / ".hermes/cache/compactions",
    Path.home() / ".hermes/sessions",
]

# Cron output is written as .txt files and as .md files inside a per-job
# subdirectory. The old loader only globbed *.log, which matches neither.
CRON_SUFFIXES = (".txt", ".log", ".md")

# Tiiny configuration.
#
# The endpoint is read from the environment so the reader points it at their
# own appliance. The previous value was a specific private LAN address.
TIINY_API_URL = os.environ.get(
    "MUSE_TIINY_URL",
    os.environ.get("TIINY_BASE_URL", "http://127.0.0.1:8767/v1"),
)
TIINY_API_KEY = os.environ.get("TIINY_API_KEY", "")
MODEL_ID = os.environ.get("MUSE_MODEL_ID", "Qwen/Qwen3.6-35B-A3B")


def load_kanban_tasks(limit: int = 50) -> List[dict]:
    """Load recent kanban tasks from the database (if accessible).
    
    Returns a list of task dicts with id, title, body, status, created_at, etc.
    If the DB is not accessible, returns empty list.
    """
    tasks = []
    if KANBAN_DB.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(KANBAN_DB))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Query recent tasks.
            #
            # The column list is derived from the table itself. The previous
            # hardcoded list named ``updated_at``, which the schema does not
            # have — so this query raised on every run and the function
            # returned an empty list, silently. The detector never saw a
            # single task.
            available = {row[1] for row in cursor.execute("PRAGMA table_info(tasks)")}
            wanted = ["id", "title", "body", "status", "assignee",
                      "created_at", "priority"]
            columns = [c for c in wanted if c in available]
            if not columns:
                print("[muse-patterns] Kanban tasks table has no expected columns")
                return []

            cursor.execute(
                f"SELECT {', '.join(columns)} FROM tasks "
                "ORDER BY created_at DESC LIMIT ?", (limit,))

            for row in cursor.fetchall():
                tasks.append(dict(row))

            conn.close()
        except Exception as e:
            print(f"[muse-patterns] Warning: Could not read kanban DB: {e}")
    else:
        print(f"[muse-patterns] Kanban DB not found at {KANBAN_DB}")

    return tasks


def load_cron_results(limit: int = 20) -> List[dict]:
    """Load recent cron job results from the agent's cron output directory.
    
    Looks for cron log files or kanban task results.
    Returns a list of result dicts.
    """
    results = []
    seen = set()
    # Check the configured locations for cron output
    for cron_dir in CRON_DIRS:
        if not cron_dir.exists():
            continue
        candidates = []
        for suffix in CRON_SUFFIXES:
            candidates.extend(cron_dir.glob(f"*{suffix}"))
        # Per-job subdirectories hold the same output as the flat .txt files.
        for sub in cron_dir.iterdir() if cron_dir.is_dir() else []:
            if sub.is_dir():
                for suffix in CRON_SUFFIXES:
                    candidates.extend(sub.glob(f"*{suffix}"))

        candidates = sorted(
            (p for p in candidates if p.is_file() and p not in seen),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )[:limit]

        for log_file in candidates:
            seen.add(log_file)
            try:
                with open(log_file, "r") as f:
                    content = f.read()
                if not content.strip():
                    continue
                results.append({
                    "source": log_file.name,
                    "content": content[:2000],  # Limit to first 2000 chars
                    "timestamp": datetime.fromtimestamp(
                        os.path.getmtime(log_file)
                    ).isoformat()
                })
            except Exception:
                pass

    return results


def load_session_summaries(limit: int = 10) -> List[dict]:
    """Load recent session summaries from the agent's session store.

    Session artifacts come in two shapes: markdown summaries and JSON
    request dumps. The old loader globbed only ``*.md``, so on an install
    that keeps JSON sessions it found nothing at all.
    """
    summaries = []
    seen = set()

    for session_dir in SESSION_DIRS:
        if not session_dir.exists():
            continue
        candidates = []
        for pattern in ("*.md", "*.json"):
            candidates.extend(session_dir.glob(pattern))
        candidates = sorted(
            (p for p in candidates if p.is_file() and p not in seen),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )[:limit]

        for file in candidates:
            seen.add(file)
            try:
                content = file.read_text(errors="ignore")
                if len(content) > 100:  # Skip tiny files
                    summaries.append({
                        "source": file.name,
                        "content": content[:3000],  # Limit to first 3000 chars
                        "timestamp": datetime.fromtimestamp(
                            os.path.getmtime(file)
                        ).isoformat()
                    })
            except Exception:
                pass

    return summaries


def compile_history_context(tasks: List[dict], cron_results: List[dict], 
                          session_summaries: List[dict]) -> str:
    """Compile all history into a single context string for the LLM."""
    context_parts = []
    
    # Tasks section
    if tasks:
        context_parts.append("=== KANBAN TASK HISTORY (most recent first) ===")
        for i, task in enumerate(tasks[:20]):  # Limit to 20 tasks
            context_parts.append(
                f"[Task {i+1}] ID: {task.get('id', 'N/A')} | "
                f"Title: {task.get('title', 'N/A')} | "
                f"Status: {task.get('status', 'N/A')} | "
                f"Priority: {task.get('priority', 'N/A')} | "
                f"Created: {task.get('created_at', 'N/A')}"
            )
            if task.get('body'):
                context_parts.append(f"Body: {task['body'][:500]}")
            if i >= 5:
                context_parts.append("... (truncated)")
                break
    else:
        context_parts.append("No kanban task history available.")
    
    # Cron results section
    if cron_results:
        context_parts.append("\n=== CRON RESULTS ===")
        for i, result in enumerate(cron_results[:5]):
            context_parts.append(
                f"[Cron {i+1}] Source: {result.get('source', 'N/A')} | "
                f"Time: {result.get('timestamp', 'N/A')}"
            )
            if result.get('content'):
                context_parts.append(f"Content: {result['content'][:500]}")
    
    # Session summaries section
    if session_summaries:
        context_parts.append("\n=== SESSION SUMMARIES ===")
        for i, summary in enumerate(session_summaries[:3]):
            context_parts.append(
                f"[Session {i+1}] Source: {summary.get('source', 'N/A')} | "
                f"Time: {summary.get('timestamp', 'N/A')}"
            )
            if summary.get('content'):
                context_parts.append(f"Summary: {summary['content'][:500]}")
    
    return "\n".join(context_parts)


def build_llm_prompt(history_context: str) -> str:
    """Build the prompt to send to the LLM for pattern detection."""
    return f"""You are a pattern detection assistant for a personal AI agent. Your job is to analyze work history and find recurring patterns that can become standing objectives (automated rules).

## Analysis Instructions

Read the work history below and identify:
1. **Recurring tasks** — things the user does regularly (e.g., "checks job alerts every Tuesday")
2. **Predictable workflows** — sequences of actions that follow a pattern (e.g., "after reviewing alerts, drafts a summary email")
3. **Contextual triggers** — events that predict when work is needed (e.g., "before meetings, prepares notes")
4. **Patterns to avoid** — things that happened only once or sporadically (don't create rules for these)

For each pattern you find, output a structured rule in this exact JSON format:
```json
{{
  "pattern_id": "unique_id_lowercase",
  "name": "Human-readable name",
  "trigger": {{
    "type": "schedule|event|context",
    "schedule": {{
      "day_of_week": "Tue,Fri",
      "hour_range": "09-17"
    }},
    "event": "meeting_start",
    "context": "has_new_job_alerts"
  }},
  "action": {{
    "type": "notify|create_kanban_task|draft_email|review_alerts",
    "title": "Task title (if applicable)",
    "message": "Notification message",
    "body": "Detailed instructions"
  }},
  "confidence": 0.85,
  "evidence": "Why you think this is a pattern (cite specific history items)",
  "priority": 3,
  "objective_type": "cron|calendar|tasks|custom"
}}
```

If no clear patterns emerge, output: `[{{"pattern_id": "no_clear_patterns", "confidence": 0.0, "evidence": "Insufficient history to detect patterns."}}]`

## Work History

{history_context}

## Output

Return ONLY the JSON array. No explanations, no markdown, no other text.
"""


def call_qwen_for_patterns(history_context: str) -> str:
    """Call Qwen3.6-35B-A3B on Tiiny to detect patterns."""
    import urllib.request
    
    prompt = build_llm_prompt(history_context)
    
    payload = json.dumps({
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": "You are a pattern detection assistant. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        # The reasoning switch lives at extra_body.chat_template_kwargs.
        # The previous shape put enable_thinking at the top of extra_body and
        # reasoning_effort inside it, where the device ignores both — so the
        # model reasoned for the whole budget and returned empty content.
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }).encode()
    
    req = urllib.request.Request(
        TIINY_API_URL + "/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {TIINY_API_KEY}",
            "Content-Type": "application/json"
        }
    )
    
    try:
        resp = urllib.request.urlopen(req)
        resp_data = json.loads(resp.read())
        
        # Extract the response (Qwen puts content in reasoning_content)
        choice = resp_data["choices"][0]
        reasoning_content = choice["message"].get("reasoning_content", "")
        content = choice["message"].get("content", "")
        
        # Try content first, fall back to reasoning_content
        response_text = content or reasoning_content
        
        return response_text
    except Exception as e:
        return f"ERROR: Could not call Qwen: {e}"


def extract_patterns_from_response(response_text: str) -> List[dict]:
    """Extract JSON patterns from the LLM response (handles markdown wrapping)."""
    # Remove markdown code blocks if present
    clean = response_text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[1] if len(lines) > 1 else lines[0]
        clean = clean.replace("```json", "").replace("json", "").strip()
    
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        print(f"[muse-patterns] WARNING: Could not parse LLM response as JSON: {clean[:200]}")
        return []


def run_pattern_detection() -> List[dict]:
    """Run the full pattern detection pipeline.
    
    Returns:
        List of detected patterns as dicts
    """
    print("[muse-patterns] Loading history...")
    
    # 1. Load history
    tasks = load_kanban_tasks(limit=30)
    cron_results = load_cron_results(limit=20)
    session_summaries = load_session_summaries(limit=10)
    
    print(f"[muse-patterns] Loaded {len(tasks)} tasks, {len(cron_results)} cron results, {len(session_summaries)} summaries")
    
    # 2. Compile context
    context = compile_history_context(tasks, cron_results, session_summaries)
    
    # 3. Call LLM
    print("[muse-patterns] Sending to Qwen for pattern detection...")
    response = call_qwen_for_patterns(context)
    
    # 4. Extract patterns
    patterns = extract_patterns_from_response(response)
    
    print(f"[muse-patterns] Detected {len(patterns)} patterns")
    for p in patterns:
        print(f"  - {p.get('name', 'Unknown')} (confidence: {p.get('confidence', 0)})")
    
    return patterns


def normalize_trigger(trigger: Dict) -> Dict:
    """Flatten a detected pattern's trigger into the engine's shape.

    The detector's prompt asks the model for a nested trigger::

        {"type": "schedule",
         "schedule": {"day_of_week": "Tue", "hour_range": "09-17"}}

    but the objectives engine reads a FLAT trigger::

        {"day_of_week": "Tue", "hour_range": "09-17"}

    Saving the model's shape verbatim produced an objective whose trigger
    held only keys the engine does not know — so it could never fire, no
    matter how confident the model was. This translates between the two.

    A schedule trigger is flattened to its fields. An event or context
    trigger is mapped onto the engine's context keys. Anything the engine
    cannot evaluate is dropped, because an unknown key means the objective
    must not fire.
    """
    if not isinstance(trigger, dict):
        return {}

    flat: Dict = {}

    # Nested schedule: {"type": "schedule", "schedule": {...}}
    schedule = trigger.get("schedule")
    if isinstance(schedule, dict):
        for key in ("day_of_week", "hour_range"):
            if key in schedule:
                flat[key] = schedule[key]

    # Already-flat schedule fields.
    for key in ("day_of_week", "hour_range"):
        if key in trigger and key not in flat:
            flat[key] = trigger[key]

    # Event triggers: map onto the engine's context keys.
    event = trigger.get("event")
    if isinstance(event, str):
        if "meeting" in event.lower():
            flat["meeting_in_minutes"] = 30
        elif "due" in event.lower() or "deadline" in event.lower():
            flat["task_due_in_days"] = 2

    # Context triggers: {"context": "has_new_job_alerts"}
    context = trigger.get("context")
    if isinstance(context, str):
        for flag in ("has_new_job_alerts", "has_unread_email"):
            if flag in context:
                flat[flag] = True

    return flat


def save_patterns_to_objectives(patterns: List[dict]) -> None:
    """Save detected patterns as standing objectives."""
    # The objectives engine lives in a sibling directory. Import it the same
    # way the daemon does — by putting that directory on the path and
    # importing the module directly. The previous import used a package path
    # (objectives.objectives_engine) that does not exist, so every detected
    # pattern raised on the way to being saved.
    import sys
    engine_dir = Path(__file__).resolve().parent.parent / "objectives"
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
    from objectives_engine import load_objectives, save_objectives, add_objective

    for pattern in patterns:
        if pattern.get("confidence", 0) >= 0.6:  # Only save patterns with sufficient confidence
            trigger = normalize_trigger(pattern.get("trigger", {}))
            if not trigger:
                # A trigger the engine cannot evaluate would save an
                # objective that can never fire. Skip it and say so.
                print(f"[muse-patterns] Skipped '{pattern.get('name', 'Unknown')}': "
                      f"trigger {pattern.get('trigger')} maps to no evaluable condition")
                continue
            objective = {
                "id": f"pattern_{pattern['pattern_id']}",
                "name": pattern["name"],
                "trigger": trigger,
                "action": {
                    "type": pattern["action"]["type"],
                    "title": pattern["action"].get("title", ""),
                    "message": pattern["action"].get("message", ""),
                    "body": pattern["action"].get("body", pattern.get("evidence", ""))
                },
                "priority": pattern.get("priority", 3),
                "enabled": True,
                "objective_type": pattern.get("objective_type", "custom")
            }
            add_objective(objective)
            print(f"[muse-patterns] Saved objective: {objective['name']}")


def main():
    """Main entry point — call from daemon or cron."""
    print("[muse-patterns] Starting pattern detection...")
    
    patterns = run_pattern_detection()
    save_patterns_to_objectives(patterns)
    
    print("[muse-patterns] Pattern detection complete.")


if __name__ == "__main__":
    main()
