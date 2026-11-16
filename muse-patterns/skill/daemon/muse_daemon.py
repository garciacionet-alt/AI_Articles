#!/usr/bin/env python3
"""
muse-daemon: Standing objectives daemon for Muse proactive planning.

This daemon runs periodically (every 15 minutes by default) and:
1. Evaluates all standing objectives against current state
2. Fires objectives whose triggers are met
3. Updates trust scores based on outcomes
4. Optionally runs pattern detection (once per day)

Configuration:
- Evaluation interval: 900 seconds (15 minutes)
- Pattern detection: once per day (midnight local)
- Kanban output: creates tasks for user review
- Silent mode: returns [SILENT] if nothing to report
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# Add module paths.
#
# The modules live one level up from this file, in sibling directories. The
# previous code used ``Path(__file__).parent`` — the daemon's OWN folder —
# so it put <daemon>/trust and <daemon>/objectives on the path, neither of
# which exists, and the import failed. The daemon could never start.
MUSE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MUSE_DIR / "trust"))
sys.path.insert(0, str(MUSE_DIR / "objectives"))

from trust_scoring import get_score, should_fire, update_score, get_all_scores
from objectives_engine import get_enabled_objectives, evaluate_trigger, load_objectives

# Configuration
EVALUATION_INTERVAL = 900  # seconds (15 minutes)
PATTERN_DETECTION_INTERVAL = 86400  # seconds (24 hours)
TRUST_THRESHOLD = 0.6

# Where fired actions are written.
#
# The default is a directory under the reader's own home, not a path inside a
# particular vault: this tool is not tied to one layout. The previous value
# was a hardcoded path into one machine's project directory, which is wrong on every
# machine that is not the one it was written on.
MUSE_OUTPUT_DIR = Path(
    os.environ.get(
        "MUSE_OUTPUT_DIR",
        str(Path.home() / ".hermes/muse/kanban/inbox"),
    )
)

# Output format
SILENT = "[SILENT]"


class MuseDaemon:
    """Main daemon class that evaluates objectives and fires actions."""

    def __init__(self, context=None):
        self.last_pattern_detection = None
        # Facts the objectives engine needs but cannot gather itself — a
        # calendar, the user's mail. Passed in by the caller; without them,
        # context-triggered objectives simply do not fire.
        self.context = context or {}
        self.load_last_pattern_time()

    def load_last_pattern_time(self) -> None:
        """Load the last pattern detection time from file."""
        time_file = Path.home() / ".hermes/muse-last-pattern-time"
        if time_file.exists():
            try:
                with open(time_file, "r") as f:
                    self.last_pattern_detection = float(f.read().strip())
            except Exception:
                self.last_pattern_detection = None
        else:
            self.last_pattern_detection = None
    
    def save_last_pattern_time(self) -> None:
        """Save the last pattern detection time."""
        time_file = Path.home() / ".hermes/muse-last-pattern-time"
        with open(time_file, "w") as f:
            f.write(str(datetime.now().timestamp()))
    
    def evaluate_objectives(self) -> List[Dict]:
        """Evaluate all standing objectives and return fired actions."""
        objectives = get_enabled_objectives()
        fired = []
        now = datetime.now()
        
        for obj in objectives:
            obj_id = obj.get("id", "unknown")
            
            # Check trust score
            trust_score = get_score(obj_id)
            if trust_score < TRUST_THRESHOLD:
                continue  # Not trusted enough to fire
            
            # Evaluate trigger
            try:
                if evaluate_trigger(obj, now, context=self.context):
                    # Trigger is met — fire the action
                    action = obj.get("action", {})
                    fired.append({
                        "objective_id": obj_id,
                        "objective_name": obj.get("name", "Unknown"),
                        "action_type": action.get("type", "unknown"),
                        "action_data": action,
                        "trust_score": trust_score,
                        "fired_at": now.isoformat()
                    })
            except Exception as e:
                print(f"[muse-daemon] Error evaluating {obj_id}: {e}")
        
        return fired
    
    def execute_action(self, fired_action: Dict) -> bool:
        """Execute a fired action and return success status."""
        action_type = fired_action["action_type"]
        action_data = fired_action["action_data"]
        obj_id = fired_action["objective_id"]
        
        try:
            if action_type == "notify":
                # Create a kanban task for user review
                self.create_kanban_task(fired_action)
                return True
            
            elif action_type == "create_kanban_task":
                # Create a kanban task
                self.create_kanban_task(fired_action)
                return True
            
            elif action_type == "draft_email":
                # Draft an email in kanban
                self.draft_email(fired_action)
                return True
            
            elif action_type == "review_alerts":
                # Review job alerts (calls pattern detection or external script)
                self.review_job_alerts(fired_action)
                return True
            
            elif action_type == "check_calendar":
                # Check calendar for upcoming events
                self.check_calendar(fired_action)
                return True
            
            else:
                print(f"[muse-daemon] Unknown action type: {action_type}")
                return False
        
        except Exception as e:
            print(f"[muse-daemon] Error executing action: {e}")
            return False
    
    def create_kanban_task(self, fired_action: Dict) -> None:
        """Create a kanban task in the output inbox."""
        title = fired_action["action_data"].get("title", 
                    fired_action["action_data"].get("message", 
                    fired_action["objective_name"]))
        body = fired_action["action_data"].get("body", 
                  fired_action["action_data"].get("message", ""))
        
        # Create a markdown file in the inbox
        kanban_dir = MUSE_OUTPUT_DIR
        kanban_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_file = kanban_dir / f"muse_{timestamp}.md"
        
        with open(task_file, "w") as f:
            f.write(f"# Muse Task: {title}\n\n")
            f.write(f"## Source\n")
            f.write(f"- Objective: {fired_action['objective_name']}\n")
            f.write(f"- Fired at: {fired_action['fired_at']}\n")
            f.write(f"- Trust score: {fired_action['trust_score']}\n\n")
            f.write(f"## Details\n")
            f.write(f"{body}\n\n")
            f.write(f"## Action Required\n")
            f.write(f"- [ ] Review and approve\n")
            f.write(f"- [ ] Mark as complete\n")
        
        print(f"[muse-daemon] Created kanban task: {task_file.name}")
    
    def draft_email(self, fired_action: Dict) -> None:
        """Draft an email in the kanban inbox."""
        subject = fired_action["action_data"].get("subject", 
                   fired_action["objective_name"])
        body = fired_action["action_data"].get("body", "")
        
        # Create a markdown file in the drafts folder
        drafts_dir = MUSE_OUTPUT_DIR / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_file = drafts_dir / f"muse_{timestamp}.md"
        
        with open(draft_file, "w") as f:
            f.write(f"# Email Draft: {subject}\n\n")
            f.write(f"## Source\n")
            f.write(f"- Objective: {fired_action['objective_name']}\n")
            f.write(f"- Fired at: {fired_action['fired_at']}\n\n")
            f.write(f"## Subject\n")
            f.write(f"{subject}\n\n")
            f.write(f"## Body\n")
            f.write(f"{body}\n\n")
            f.write(f"## Action Required\n")
            f.write(f"- [ ] Review and send\n")
        
        print(f"[muse-daemon] Created email draft: {draft_file.name}")
    
    def review_job_alerts(self, fired_action: Dict) -> None:
        """Review job alerts (placeholder — can be extended with external script)."""
        # Create a kanban task for the user to review alerts
        self.create_kanban_task({
            **fired_action,
            "action_data": {
                "title": "Review and summarize job alerts",
                "body": "Check new job alerts from LinkedIn/Greenhouse and produce a summary.",
                "type": "review_alerts"
            }
        })
    
    def check_calendar(self, fired_action: Dict) -> None:
        """Check calendar for upcoming events (placeholder — can be extended)."""
        self.create_kanban_task({
            **fired_action,
            "action_data": {
                "title": "Check upcoming calendar events",
                "body": "Review upcoming meetings and events in the next 24 hours.",
                "type": "check_calendar"
            }
        })
    
    def run_pattern_detection(self) -> None:
        """Run pattern detection to find new standing objectives."""
        print("[muse-daemon] Running pattern detection...")
        
        try:
            # Import and run pattern detection
            sys.path.insert(0, str(MUSE_DIR / "scripts"))
            import pattern_detection
            
            patterns = pattern_detection.run_pattern_detection()
            pattern_detection.save_patterns_to_objectives(patterns)
            
            if patterns:
                self.save_last_pattern_time()
                print(f"[muse-daemon] Pattern detection found {len(patterns)} patterns")
            else:
                self.save_last_pattern_time()
                print("[muse-daemon] No patterns detected")
        
        except Exception as e:
            print(f"[muse-daemon] Pattern detection failed: {e}")
            # Don't update the last detection time on failure
            # Will retry next run
    
    def run(self) -> str:
        """Run one evaluation cycle. Returns output string.
        
        Returns:
            SILENT if nothing to report, or a summary of fired actions
        """
        print("[muse-daemon] Evaluation cycle starting...")
        
        # 1. Evaluate standing objectives
        fired = self.evaluate_objectives()
        
        if not fired:
            # 2. Check if it's time for pattern detection
            now = datetime.now()
            if (self.last_pattern_detection is None or 
                (now - datetime.fromtimestamp(self.last_pattern_detection)).total_seconds() > PATTERN_DETECTION_INTERVAL):
                
                print("[muse-daemon] Running scheduled pattern detection...")
                self.run_pattern_detection()
            
            return SILENT
        
        # 3. Execute fired actions and update trust scores
        results = []
        for action in fired:
            obj_id = action["objective_id"]
            success = self.execute_action(action)
            
            # Update trust score based on outcome
            new_score = update_score(obj_id, success)
            action["new_trust_score"] = new_score
            action["trust_updated"] = True
            
            results.append(action)
            
            print(f"[muse-daemon] Action executed for '{action['objective_name']}': {'success' if success else 'fail'} (trust: {new_score})")
        
        # 4. Generate output
        if results:
            output_lines = [f"[muse-daemon] {len(results)} actions fired:"]
            for r in results:
                output_lines.append(
                    f"- {r['objective_name']}: {r['action_type']} "
                    f"(trust: {r['new_trust_score']})"
                )
            return "\n".join(output_lines)
        
        return SILENT
    
    def run_loop(self) -> None:
        """Run the daemon in a loop (for background processes)."""
        print("[muse-daemon] Starting daemon loop (every 15 minutes)...")
        
        while True:
            try:
                output = self.run()
                print(f"[muse-daemon] Output: {output[:200]}")
            except Exception as e:
                print(f"[muse-daemon] Error in loop: {e}")
            
            # Sleep for the evaluation interval
            import time
            time.sleep(EVALUATION_INTERVAL)


def main():
    """Main entry point — called from cron or as a one-shot daemon."""
    daemon = MuseDaemon()
    output = daemon.run()
    print(output)
    
    # Return appropriate exit code
    if output == SILENT:
        sys.exit(0)  # No output is not an error
    else:
        sys.exit(0)  # Success


if __name__ == "__main__":
    main()
