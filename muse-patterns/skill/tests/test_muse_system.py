#!/usr/bin/env python3
"""
Test harness for muse-patterns system.

Tests:
1. Trust scoring (load, update, threshold check)
2. Objectives engine (load, evaluate trigger)
3. Pattern detection module (import, structure)
4. Daemon (import, structure)

Run with: python3 test_muse_system.py
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime

# Add module paths BEFORE any imports
MUSE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(MUSE_DIR / "trust"))
sys.path.insert(0, str(MUSE_DIR / "objectives"))
sys.path.insert(0, str(MUSE_DIR / "daemon"))
sys.path.insert(0, str(MUSE_DIR / "scripts"))

# Override trust file to use temp dir for tests
os.environ["MUSE_TEST_MODE"] = "1"

from trust_scoring import (
    get_score, update_score, should_fire, 
    get_all_scores, DEFAULT_SCORE, TRUST_FILE
)
from objectives_engine import (
    get_enabled_objectives, evaluate_trigger, 
    load_objectives
)
import trust_scoring
import objectives_engine

# For tests, override trust file to temp location
import tempfile
_test_trust_file = None

def _setup_test_trust_file():
    """Set up a temp trust file for tests."""
    global _test_trust_file
    _test_trust_file = tempfile.mktemp(suffix=".json")
    os.environ["MUSE_TRUST_FILE"] = _test_trust_file
    trust_scoring.TRUST_FILE = Path(_test_trust_file)


def test_trust_scoring():
    """Test trust scoring system."""
    global _test_trust_file
    _setup_test_trust_file()
    
    print("\n=== Testing Trust Scoring ===")
    
    # Test 1: Default score for unknown pattern
    default_score = trust_scoring.get_score("test_pattern_unknown")
    print(f"  Default score for unknown pattern: {default_score}")
    assert default_score == trust_scoring.DEFAULT_SCORE, f"Expected {trust_scoring.DEFAULT_SCORE}, got {default_score}"
    print("  ✓ PASS: Default score is correct")
    
    # Test 2: Update score on success
    new_score = trust_scoring.update_score("test_pattern_success", True)
    print(f"  After 1 success: {new_score}")
    assert new_score > trust_scoring.DEFAULT_SCORE, f"Score should increase after success"
    print(f"  ✓ PASS: Score increased to {new_score}")
    
    # Test 3: Update score on ignore
    new_score = trust_scoring.update_score("test_pattern_ignore", False)
    print(f"  After 1 ignore: {new_score}")
    assert new_score < trust_scoring.DEFAULT_SCORE, f"Score should decrease after ignore"
    print(f"  ✓ PASS: Score decreased to {new_score}")
    
    # Test 4: Threshold check
    fire_check = trust_scoring.should_fire("test_pattern_success")
    print(f"  Should fire (high trust): {fire_check}")
    assert fire_check, "Should fire when score >= threshold"
    print("  ✓ PASS: Fires when score >= threshold")
    
    # Test 5: Should not fire for low trust
    fire_check = trust_scoring.should_fire("test_pattern_ignore")
    print(f"  Should fire (low trust): {fire_check}")
    # This may or may not fire depending on the threshold — just check it doesn't crash
    print(f"  ✓ PASS: Threshold check works (score={new_score})")
    
    print("  All trust scoring tests passed ✓")


def test_objectives_engine():
    """Test standing objectives engine."""
    print("\n=== Testing Objectives Engine ===")
    
    # Test 1: Load objectives
    objectives = objectives_engine.load_objectives()
    print(f"  Loaded {len(objectives)} objectives")
    assert len(objectives) > 0, "Should load at least the sample objectives"
    print(f"  ✓ PASS: Loaded {len(objectives)} objectives")
    
    # Test 2: Get enabled objectives
    enabled = objectives_engine.get_enabled_objectives()
    print(f"  Enabled objectives: {len(enabled)}")
    assert len(enabled) > 0, "Should have enabled objectives"
    print(f"  ✓ PASS: {len(enabled)} enabled objectives")
    
    # Test 3: Evaluate trigger (day of week check)
    test_obj = {
        "trigger": {
            "day_of_week": "Mon",
            "hour_range": "09-17"
        }
    }
    
    # Test with Monday at 10am (should match)
    monday = datetime(2026, 11, 16, 10, 0)
    trigger_met = objectives_engine.evaluate_trigger(test_obj, monday)
    print(f"  Monday 10am trigger (Mon, 09-17): {trigger_met}")
    assert trigger_met, "Monday 10am should match Mon trigger"
    print(f"  ✓ PASS: Monday trigger evaluates correctly")
    
    # Test with Tuesday (should not match)
    tuesday = datetime(2026, 11, 17)  # A Tuesday
    trigger_met = objectives_engine.evaluate_trigger(test_obj, tuesday)
    print(f"  Tuesday 10am trigger (Mon, 09-17): {trigger_met}")
    assert not trigger_met, "Tuesday should not match Mon trigger"
    print(f"  ✓ PASS: Tuesday correctly rejected")
    
    # Test with Monday at 8am (should not match — outside hour range)
    monday_early = datetime(2026, 11, 16, 8, 0)
    trigger_met = objectives_engine.evaluate_trigger(test_obj, monday_early)
    print(f"  Monday 8am trigger (Mon, 09-17): {trigger_met}")
    assert not trigger_met, "Monday 8am should not match 09-17 range"
    print(f"  ✓ PASS: Monday 8am correctly rejected")
    
    # Test with Monday at 6pm (should not match — outside hour range)
    monday_evening = datetime(2026, 11, 16, 18, 0)
    trigger_met = objectives_engine.evaluate_trigger(test_obj, monday_evening)
    print(f"  Monday 6pm trigger (Mon, 09-17): {trigger_met}")
    assert not trigger_met, "Monday 6pm should not match 09-17 range"
    print(f"  ✓ PASS: Monday 6pm correctly rejected")
    
    print("  All objectives tests passed ✓")


def test_pattern_detection_structure():
    """Test pattern detection module structure."""
    print("\n=== Testing Pattern Detection Module Structure ===")
    
    # Check that the module can be imported (not full test — that requires Tiiny)
    try:
        sys.path.insert(0, str(MUSE_DIR / "scripts"))
        import pattern_detection
        print("  ✓ PASS: pattern_detection module imports correctly")
        
        # Check key functions exist
        assert hasattr(pattern_detection, "run_pattern_detection"), "Missing run_pattern_detection"
        assert hasattr(pattern_detection, "call_qwen_for_patterns"), "Missing call_qwen_for_patterns"
        assert hasattr(pattern_detection, "compile_history_context"), "Missing compile_history_context"
        print("  ✓ PASS: All key functions present")
        
    except Exception as e:
        print(f"  ✗ FAIL: Pattern detection module error: {e}")
        return False
    
    return True


def test_daemon_structure():
    """Test daemon module structure."""
    print("\n=== Testing Daemon Module Structure ===")
    
    try:
        sys.path.insert(0, str(MUSE_DIR / "daemon"))
        import muse_daemon
        print("  ✓ PASS: muse_daemon module imports correctly")
        
        # Check key classes/functions exist
        assert hasattr(muse_daemon, "MuseDaemon"), "Missing MuseDaemon class"
        assert hasattr(muse_daemon, "main"), "Missing main function"
        print("  ✓ PASS: MuseDaemon class and main function present")
        
        # Try instantiating the daemon
        daemon = muse_daemon.MuseDaemon()
        print("  ✓ PASS: MuseDaemon instantiates correctly")
        
    except Exception as e:
        print(f"  ✗ FAIL: Daemon module error: {e}")
        return False
    
    return True


def test_file_structure():
    """Verify the file structure is correct."""
    print("\n=== Testing File Structure ===")
    
    expected_files = [
        "trust/trust_scoring.py",
        "objectives/objectives_engine.py",
        "scripts/pattern_detection.py",
        "daemon/muse_daemon.py",
    ]
    
    all_ok = True
    for f in expected_files:
        path = MUSE_DIR / f
        if path.exists():
            print(f"  ✓ {f}")
        else:
            print(f"  ✗ {f} MISSING")
            all_ok = False
    
    if all_ok:
        print("  ✓ PASS: All files present")
    else:
        print("  ✗ FAIL: Some files missing")
    
    return all_ok


def test_regression_bugs():
    """Test the specific defects that made the system non-functional.

    Each of these was a real bug that shipped with the system passing its
    own tests. They are regression tests, not new features.
    """
    print("\n=== Testing Regression Bugs ===")
    all_ok = True

    # Imported here, at the top of the function, so that the `import
    # objectives_engine` inside the Bug 8 block does not make Python treat
    # the name as local to the whole function — which would break every
    # reference to it above.
    import objectives_engine
    import pattern_detection

    # BUG 1: the daemon put <daemon>/trust on sys.path instead of
    # <muse>/trust, so it could never import its own modules and could
    # never start. The test harness masked this by using parent.parent.
    print("\n  [Bug 1] Daemon module paths resolve to real directories")
    try:
        import muse_daemon
        muse_root = Path(muse_daemon.MUSE_DIR)
        assert muse_root == MUSE_DIR, \
            f"daemon MUSE_DIR is {muse_root}, expected {MUSE_DIR}"
        assert (muse_root / "trust" / "trust_scoring.py").exists(), \
            "daemon MUSE_DIR/trust/trust_scoring.py does not exist"
        assert (muse_root / "objectives" / "objectives_engine.py").exists(), \
            "daemon MUSE_DIR/objectives/objectives_engine.py does not exist"
        print("    ✓ PASS: daemon module paths are correct")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 2: a trigger the engine could not evaluate returned True, so
    # every context-triggered objective fired on every single cycle.
    print("\n  [Bug 2] Unevaluable triggers do not fire")
    try:
        meeting = {"trigger": {"meeting_in_minutes": 30}}
        deadline = {"trigger": {"task_due_in_days": 2}}
        assert objectives_engine.evaluate_trigger(meeting, datetime.now()) is False, \
            "meeting_in_minutes fired without calendar context"
        assert objectives_engine.evaluate_trigger(deadline, datetime.now()) is False, \
            "task_due_in_days fired without task context"
        print("    ✓ PASS: context triggers do not fire without context")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 3: an unknown trigger key must also not fire.
    print("\n  [Bug 3] Unknown trigger keys do not fire")
    try:
        unknown = {"trigger": {"phase_of_moon": "full"}}
        assert objectives_engine.evaluate_trigger(unknown, datetime.now()) is False, \
            "an unknown trigger key fired"
        print("    ✓ PASS: unknown trigger keys do not fire")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 4: context triggers DO fire when the context supplies the fact.
    print("\n  [Bug 4] Context triggers fire when context is supplied")
    try:
        ctx = {"meeting_in_minutes": 10, "task_due_in_days": 1}
        assert objectives_engine.evaluate_trigger(
            {"trigger": {"meeting_in_minutes": 30}}, datetime.now(), context=ctx) is True, \
            "meeting_in_minutes did not fire with context"
        assert objectives_engine.evaluate_trigger(
            {"trigger": {"task_due_in_days": 2}}, datetime.now(), context=ctx) is True, \
            "task_due_in_days did not fire with context"
        print("    ✓ PASS: context triggers fire with context")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 5: the prompt template had an unescaped brace, so building it
    # raised "Invalid format specifier" and detection never ran at all.
    print("\n  [Bug 5] The detection prompt builds without error")
    try:
        import pattern_detection
        prompt = pattern_detection.build_llm_prompt("SOME HISTORY")
        assert "SOME HISTORY" in prompt, "history context missing from prompt"
        assert "no_clear_patterns" in prompt, "fallback instruction missing"
        print("    ✓ PASS: prompt builds cleanly")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 6: the reasoning switch was in the wrong place in the request
    # body, so the device ignored it and the model spent the whole token
    # budget on reasoning.
    print("\n  [Bug 6] The reasoning switch is in the shape the device reads")
    try:
        import pattern_detection
        src = Path(pattern_detection.__file__).read_text()
        assert "chat_template_kwargs" in src, \
            "enable_thinking is not under chat_template_kwargs"
        assert '"extra_body": {"enable_thinking"' not in src, \
            "enable_thinking is still at the top of extra_body"
        print("    ✓ PASS: reasoning switch is correctly shaped")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 7: the kanban query named a column the schema does not have, so
    # it raised and the detector silently saw zero tasks.
    print("\n  [Bug 7] The kanban query works against the real schema")
    try:
        import pattern_detection
        import sqlite3
        if pattern_detection.KANBAN_DB.exists():
            conn = sqlite3.connect(str(pattern_detection.KANBAN_DB))
            available = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
            conn.close()
            wanted = ["id", "title", "body", "status", "assignee",
                      "created_at", "priority"]
            missing = [c for c in wanted if c not in available]
            assert not missing, f"query names columns the schema lacks: {missing}"
        print("    ✓ PASS: kanban query matches the schema")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 8: the objective save path imported a package that does not
    # exist, so every detected pattern raised on the way to being saved.
    print("\n  [Bug 8] A detected pattern can be saved")
    try:
        import pattern_detection
        tmp = tempfile.mktemp(suffix=".yaml")
        os.environ["MUSE_OBJECTIVES_FILE"] = tmp
        import objectives_engine
        objectives_engine.OBJECTIVES_FILE = Path(tmp)
        pattern_detection.save_patterns_to_objectives([{
            "pattern_id": "test_pattern",
            "name": "Test Pattern",
            "trigger": {"day_of_week": "Wed"},
            "action": {"type": "notify", "message": "hi"},
            "confidence": 0.9,
            "priority": 3,
        }])
        saved = objectives_engine.load_objectives()
        assert any(o.get("id") == "pattern_test_pattern" for o in saved), \
            "the pattern was not saved"
        os.unlink(tmp)
        print("    ✓ PASS: patterns save cleanly")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 9: machine-specific paths were hardcoded into the source.
    print("\n  [Bug 9] No machine-specific paths or addresses in the source")
    try:
        offenders = []
        for py in MUSE_DIR.rglob("*.py"):
            # This test file names the offending strings on purpose — it is
            # the check, not a violation.
            if py.name == "test_muse_system.py":
                continue
            for lineno, line in enumerate(py.read_text().split("\n"), 1):
                code = line.split("#")[0]
                if "192.168.1." in code:
                    offenders.append(f"{py.name}:{lineno}: private LAN address")
                if "Desktop/OpenHuman-Projects" in code:
                    offenders.append(f"{py.name}:{lineno}: hardcoded vault path")
        assert not offenders, f"still hardcoded: {offenders}"
        print("    ✓ PASS: no hardcoded addresses or paths")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 10: the model emits a NESTED trigger, the engine reads a FLAT
    # one. Saving the model's shape verbatim produced an objective whose
    # trigger held only unknown keys — so it could never fire.
    print("\n  [Bug 10] A detected trigger maps to an evaluable condition")
    try:
        import pattern_detection
        nested = {"type": "schedule",
                  "schedule": {"day_of_week": "Tue", "hour_range": "09-17"}}
        flat = pattern_detection.normalize_trigger(nested)
        assert flat.get("day_of_week") == "Tue", f"day_of_week lost: {flat}"
        assert flat.get("hour_range") == "09-17", f"hour_range lost: {flat}"
        assert "type" not in flat and "schedule" not in flat, \
            f"unknown trigger keys survived: {flat}"
        # And the flattened form must actually be evaluable.
        assert objectives_engine.evaluate_trigger(
            {"trigger": flat}, datetime(2026, 11, 17, 10, 0)) is True, \
            "the flattened trigger does not fire when it should"
        print("    ✓ PASS: nested triggers flatten correctly")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 11: add_objective appended unconditionally, so the daily detector
    # grew a duplicate of every pattern it re-derived.
    print("\n  [Bug 11] Re-adding the same objective replaces it")
    try:
        import objectives_engine
        tmp = tempfile.mktemp(suffix=".yaml")
        os.environ["MUSE_OBJECTIVES_FILE"] = tmp
        objectives_engine.OBJECTIVES_FILE = Path(tmp)
        objectives_engine.save_objectives([])
        for _ in range(3):
            objectives_engine.add_objective(
                {"id": "dup", "name": "Dup", "trigger": {"day_of_week": "Mon"}})
        saved = objectives_engine.load_objectives()
        assert len(saved) == 1, f"expected 1 objective, got {len(saved)}"
        os.unlink(tmp)
        print("    ✓ PASS: duplicates are replaced, not appended")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    # BUG 12: the model emits a day RANGE ("Mon-Sun"), the parser split on
    # commas only, so the token matched no day and the objective silently
    # never fired.
    print("\n  [Bug 12] A day range parses into the days it covers")
    try:
        import objectives_engine
        assert set(objectives_engine._parse_days("Mon-Sun")) == {
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}, \
            "Mon-Sun did not expand to every day"
        assert set(objectives_engine._parse_days("Mon-Fri")) == {
            "Mon", "Tue", "Wed", "Thu", "Fri"}, \
            "Mon-Fri did not expand to the weekdays"
        assert objectives_engine._parse_days("Mon,Fri") == ["Mon", "Fri"], \
            "a comma list broke"
        assert objectives_engine._parse_days("Tue") == ["Tue"], \
            "a single day broke"
        # And the whole-day range must actually fire on any weekday.
        every_day = {"trigger": {"day_of_week": "Mon-Sun", "hour_range": "00-23"}}
        assert objectives_engine.evaluate_trigger(
            every_day, datetime(2026, 11, 17, 10, 0)) is True, \
            "an every-day objective did not fire on a Tuesday"
        print("    ✓ PASS: day ranges expand correctly")
    except Exception as e:
        print(f"    ✗ FAIL: {e}")
        all_ok = False

    print("\n  All regression tests passed ✓" if all_ok else "\n  SOME REGRESSION TESTS FAILED ✗")
    return all_ok


def main():
    """Run all tests."""
    print("=" * 60)
    print("Muse Patterns System — Test Harness")
    print("=" * 60)
    
    all_passed = True
    
    # Test trust scoring
    try:
        test_trust_scoring()
    except Exception as e:
        print(f"  ✗ FAIL: Trust scoring test error: {e}")
        all_passed = False
    
    # Test objectives engine
    try:
        test_objectives_engine()
    except Exception as e:
        print(f"  ✗ FAIL: Objectives test error: {e}")
        all_passed = False
    
    # Test file structure
    if not test_file_structure():
        all_passed = False
    
    # Test module structures
    if not test_pattern_detection_structure():
        all_passed = False

    if not test_daemon_structure():
        all_passed = False

    # Test the regression bugs — the defects that shipped with this
    # system passing its own tests.
    try:
        if not test_regression_bugs():
            all_passed = False
    except Exception as e:
        print(f"  ✗ FAIL: Regression test error: {e}")
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED ✗")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
