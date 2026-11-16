#!/usr/bin/env python3
"""
muse-trust: Trust scoring system for standing objectives and patterns.

Each pattern/objective has a score (0.0 to 1.0) that goes up on success
and down on ignore. Patterns only fire when score >= threshold.

File: ~/.hermes/muse-trust.json
Format: {"<pattern_id>": {"score": 0.6, "successes": 3, "ignores": 1, "last_updated": "2026-11-15T10:00:00"}}
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TRUST_FILE = Path(
    os.environ.get(
        "MUSE_TRUST_FILE",
        str(Path.home() / ".hermes/muse-trust.json"),
    )
)
DEFAULT_THRESHOLD = 0.6
DEFAULT_SCORE = 0.5
SCORE_UP = 0.1
SCORE_DOWN = 0.2
SCORE_MIN = 0.0
SCORE_MAX = 1.0


def load_trust_data() -> dict:
    """Load the trust scoring file, creating it if missing."""
    if TRUST_FILE.exists():
        with open(TRUST_FILE, "r") as f:
            return json.load(f)
    return {}


def save_trust_data(data: dict) -> None:
    """Save the trust scoring file atomically."""
    tmp = TRUST_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(TRUST_FILE)


def get_score(pattern_id: str, default: Optional[float] = None) -> float:
    """Get current trust score for a pattern.

    ``default`` is the *granted* score: what this pattern starts at when
    nobody has vouched for it yet. A pattern that has never fired has no
    record, so its score comes from the grant — the detector's confidence,
    or the ``initial_score`` its author declared. Without a grant it falls
    back to DEFAULT_SCORE, which is below the threshold, so an unvouched
    pattern stays silent.

    Once a pattern has a record, the record wins: the grant applies once,
    and everything after it is earned.
    """
    data = load_trust_data()
    entry = data.get(pattern_id, {})
    if "score" in entry:
        return entry["score"]
    if default is not None:
        try:
            return max(SCORE_MIN, min(SCORE_MAX, float(default)))
        except (TypeError, ValueError):
            return DEFAULT_SCORE
    return DEFAULT_SCORE


def grant_score(pattern_id: str, score: float) -> float:
    """Record the starting score for a pattern that has no history yet.

    Write-if-absent: a grant is a starting position, not a decision. Once
    the pattern has fired, its own outcomes own the score and this does
    nothing.
    """
    data = load_trust_data()
    if pattern_id in data:
        return data[pattern_id].get("score", DEFAULT_SCORE)
    try:
        value = max(SCORE_MIN, min(SCORE_MAX, float(score)))
    except (TypeError, ValueError):
        value = DEFAULT_SCORE
    data[pattern_id] = {
        "score": value,
        "successes": 0,
        "ignores": 0,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    save_trust_data(data)
    return value


def update_score(pattern_id: str, success: bool) -> float:
    """Update trust score: success += SCORE_UP, ignore -= SCORE_DOWN. Clamped to [0, 1].
    
    Returns: new score value
    """
    data = load_trust_data()
    
    if pattern_id not in data:
        data[pattern_id] = {
            "score": DEFAULT_SCORE,
            "successes": 0,
            "ignores": 0,
            "last_updated": ""
        }
    
    entry = data[pattern_id]
    current = entry.get("score", DEFAULT_SCORE)
    
    if success:
        entry["successes"] = entry.get("successes", 0) + 1
        current = min(SCORE_MAX, current + SCORE_UP)
    else:
        entry["ignores"] = entry.get("ignores", 0) + 1
        current = max(SCORE_MIN, current - SCORE_DOWN)
    
    entry["score"] = round(current, 2)
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    data[pattern_id] = entry
    save_trust_data(data)
    
    return entry["score"]


def should_fire(pattern_id: str, threshold: Optional[float] = None,
                default: Optional[float] = None) -> bool:
    """Check if a pattern should fire based on trust score and threshold.

    ``default`` is the granted score, for a pattern that has no history
    yet — see :func:`get_score`.
    """
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    
    score = get_score(pattern_id, default=default)
    return score >= threshold


def get_all_scores() -> dict:
    """Get all trust scores for debugging/reporting."""
    data = load_trust_data()
    result = {}
    for pid, entry in data.items():
        result[pid] = {
            "score": entry.get("score", DEFAULT_SCORE),
            "successes": entry.get("successes", 0),
            "ignores": entry.get("ignores", 0),
            "should_fire": entry.get("score", DEFAULT_SCORE) >= DEFAULT_THRESHOLD
        }
    return result


def reset_pattern(pattern_id: str) -> None:
    """Reset a pattern's trust score to default."""
    data = load_trust_data()
    if pattern_id in data:
        data[pattern_id]["score"] = DEFAULT_SCORE
        data[pattern_id]["successes"] = 0
        data[pattern_id]["ignores"] = 0
        data[pattern_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_trust_data(data)
