#!/usr/bin/env python3
"""test_mesh_watchdog.py — Unit tests for mesh_watchdog module.

Exercise per-device isolation for holds and locks, expiration logic,
owner-based lock renewal/rejection, and CLI subcommand parsing.

Uses a temp directory for HOLDS_DIR / LOCKS_DIR so tests don't touch
real state and can be run in parallel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# We must point sys.path so ``devices`` and ``mesh`` resolve.
PROJECT_DIR = Path(__file__).resolve().parent  # TiinyMesh/

sys.path.insert(0, str(PROJECT_DIR))

import mesh_watchdog as W


# ---------------------------------------------------------------------------
# Helpers — use an isolated temp dir for holds/locks
# ---------------------------------------------------------------------------


class TempDirs:
    """Context manager that points W.HOLDS_DIR and W.LOCKS_DIR at temp dirs."""

    def __init__(self) -> None:
        self.holds_dir: Path | None = None
        self.locks_dir: Path | None = None

    def __enter__(self) -> "TempDirs":
        self.holds_dir = tempfile.mkdtemp(prefix="tw_holds_")
        self.locks_dir = tempfile.mkdtemp(prefix="tw_locks_")
        self._orig_holds = W.HOLDS_DIR
        self._orig_locks = W.LOCKS_DIR
        W.HOLDS_DIR = Path(self.holds_dir)
        W.LOCKS_DIR = Path(self.locks_dir)
        return self

    def __exit__(self, *exc: object) -> None:
        W.HOLDS_DIR = self._orig_holds
        W.LOCKS_DIR = self._orig_locks


# ---------------------------------------------------------------------------
# Tests — Holds
# ---------------------------------------------------------------------------


def test_holds_are_per_device_and_do_not_collide() -> None:
    """Hold on tiiny-ant does not affect tiiny-octo."""
    with TempDirs():
        # Place holds on both devices
        hold_ant = W.hold(
            "tiiny-ant",
            ["meta-llama/Llama-3.3-70B-Instruct-TIINY-Q8_0"],
            "the author",
            ttl=300,
        )
        hold_octo = W.hold(
            "tiiny-octo",
            ["meta-llama/Llama-3.3-70B-Instruct-TIINY-Q4_K_M"],
            "the author",
            ttl=300,
        )

        # Verify devices are different
        assert hold_ant["device"] == "tiiny-ant"
        assert hold_octo["device"] == "tiiny-octo"
        assert hold_ant["models"] != hold_octo["models"]

        # Verify files are separate
        assert (W.HOLDS_DIR / "tiiny-ant.json").exists()
        assert (W.HOLDS_DIR / "tiiny-octo.json").exists()

        # Verify get_hold returns correct, independent data
        held_ant = W.get_hold("tiiny-ant")
        held_octo = W.get_hold("tiiny-octo")
        assert held_ant is not None
        assert held_octo is not None
        assert held_ant["device"] == "tiiny-ant"
        assert held_octo["device"] == "tiiny-octo"
        assert held_ant["models"] != held_octo["models"]

        # Verify list_holds returns both
        all_holds = W.list_holds()
        assert len(all_holds) == 2
        assert "tiiny-ant" in all_holds
        assert "tiiny-octo" in all_holds

        # Release tiiny-ant only
        assert W.release_hold("tiiny-ant", owner="the author") is True

        # tiiny-octo still active
        assert W.get_hold("tiiny-octo") is not None
        # tiiny-ant gone
        assert W.get_hold("tiiny-ant") is None
        all_holds = W.list_holds()
        assert len(all_holds) == 1
        assert "tiiny-octo" in all_holds
        assert "tiiny-ant" not in all_holds

        print("  ok    test_holds_are_per_device_and_do_not_collide")


def test_hold_expiration() -> None:
    """Expired holds are transparently removed on read."""
    with TempDirs():
        now = time.time()
        hold_path = W._hold_path("tiiny-ant")
        payload = {
            "device": "tiiny-ant",
            "owner": "the author",
            "models": ["model-a"],
            "created": now - 3600,
            "expires": now - 1,  # already expired
        }
        hold_path.write_text(json.dumps(payload), encoding="utf-8")

        # get_hold should return None (and unlink)
        result = W.get_hold("tiiny-ant")
        assert result is None
        assert not hold_path.exists()

        # list_holds should not include it
        all_holds = W.list_holds()
        assert "tiiny-ant" not in all_holds

        print("  ok    test_hold_expiration")


# ---------------------------------------------------------------------------
# Tests — Locks
# ---------------------------------------------------------------------------


def test_locks_are_per_device_and_isolated() -> None:
    """Lock on tiiny-ant does not affect tiiny-octo."""
    with TempDirs():
        payload_a, err_a = W.lock_acquire(
            "tiiny-ant", "alice", task="test", ttl=300
        )
        assert err_a == ""
        assert payload_a is not None
        assert payload_a["device"] == "tiiny-ant"
        assert payload_a["owner"] == "alice"
        assert payload_a["state"] == "held"

        payload_o, err_o = W.lock_acquire(
            "tiiny-octo", "bob", task="test", ttl=300
        )
        assert err_o == ""
        assert payload_o is not None
        assert payload_o["device"] == "tiiny-octo"
        assert payload_o["owner"] == "bob"

        # Verify lock files exist independently
        assert (W.LOCKS_DIR / "tiiny-ant.lock").exists()
        assert (W.LOCKS_DIR / "tiiny-octo.lock").exists()

        # Status returns correct data
        status_a = W.lock_status("tiiny-ant")
        status_o = W.lock_status("tiiny-octo")
        assert status_a is not None
        assert status_o is not None
        assert status_a["owner"] == "alice"
        assert status_o["owner"] == "bob"

        # Release only tiiny-octo
        ok_o, err_o = W.lock_release("tiiny-octo", "bob")
        assert ok_o is True

        # tiiny-ant still locked by alice
        assert W.lock_status("tiiny-ant") is not None

        # Clean up
        W.lock_release("tiiny-ant", "alice")
        print("  ok    test_locks_are_per_device_and_isolated")


def test_lock_renew_by_owner() -> None:
    """Same owner can renew lock by re-acquiring."""
    with TempDirs():
        payload1, err1 = W.lock_acquire(
            "tiiny-ant", "alice", task="first", ttl=300
        )
        assert err1 == ""
        assert payload1 is not None

        # Wait a tick to ensure timestamps differ
        time.sleep(0.05)

        # Re-acquire with same owner — should succeed and renew
        payload2, err2 = W.lock_acquire(
            "tiiny-ant", "alice", task="second", ttl=300
        )
        assert err2 == ""
        assert payload2 is not None
        assert payload2["task"] == "second"
        assert payload2["owner"] == "alice"
        assert payload2["state"] == "held"
        assert payload2["pid"] == os.getpid()

        W.lock_release("tiiny-ant", "alice")
        print("  ok    test_lock_renew_by_owner")


def test_lock_rejection_by_other_owner() -> None:
    """Different owner cannot acquire when a valid lock is held."""
    with TempDirs():
        # Alice acquires
        payload_a, err_a = W.lock_acquire(
            "tiiny-ant", "alice", task="alice-task", ttl=300
        )
        assert err_a == ""

        # Bob tries — should be rejected
        payload_b, err_b = W.lock_acquire(
            "tiiny-ant", "bob", task="bob-task", ttl=300
        )
        assert err_b != ""
        assert payload_b is None
        assert "bob" not in err_b  # error mentions the holder (alice), not bob
        assert "alice" in err_b.lower() or "lock" in err_b.lower()

        # Alice can still release normally
        ok, err = W.lock_release("tiiny-ant", "alice")
        assert ok is True
        assert err == ""

        # Now Bob can acquire
        payload_b2, err_b2 = W.lock_acquire(
            "tiiny-ant", "bob", task="bob-task", ttl=300
        )
        assert err_b2 == ""
        assert payload_b2 is not None
        assert payload_b2["owner"] == "bob"

        W.lock_release("tiiny-ant", "bob")
        print("  ok    test_lock_rejection_by_other_owner")


# ---------------------------------------------------------------------------
# Tests — CLI
# ---------------------------------------------------------------------------


def test_cli_parsing() -> None:
    """CLI subcommands parse correctly and produce JSON output."""
    with TempDirs():
        W.HOLDS_DIR.mkdir(parents=True, exist_ok=True)
        W.LOCKS_DIR.mkdir(parents=True, exist_ok=True)

        # --- status (no device) ---
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mesh_watchdog; mesh_watchdog.main(['status'])"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        status_data = json.loads(proc.stdout)
        assert isinstance(status_data, dict)

        # --- hold ---
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mesh_watchdog; mesh_watchdog.main(["
             "  'hold', 'test-device', 'model-a', 'model-b', "
             "  '--owner', 'tester', '--ttl', '600'])"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        hold_data = json.loads(proc.stdout)
        assert hold_data["device"] == "test-device"
        assert hold_data["owner"] == "tester"
        assert "model-a" in hold_data["models"]

        # --- release ---
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mesh_watchdog; mesh_watchdog.main(["
             "  'release', 'test-device', '--owner', 'tester'])"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        release_data = json.loads(proc.stdout)
        assert release_data["released"] is True

        # --- lock ---
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mesh_watchdog; mesh_watchdog.main(["
             "  'lock', 'test-device', '--owner', 'tester', "
             "  '--task', 'cli-test', '--ttl', '600'])"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        lock_data = json.loads(proc.stdout)
        assert lock_data["device"] == "test-device"
        assert lock_data["task"] == "cli-test"

        # --- unlock ---
        proc = subprocess.run(
            [sys.executable, "-c",
             "import mesh_watchdog; mesh_watchdog.main(["
             "  'unlock', 'test-device', '--owner', 'tester'])"],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        unlock_data = json.loads(proc.stdout)
        assert unlock_data["released"] is True

        print("  ok    test_cli_parsing")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_holds_are_per_device_and_do_not_collide()
    test_hold_expiration()
    test_locks_are_per_device_and_isolated()
    test_lock_renew_by_owner()
    test_lock_rejection_by_other_owner()
    test_cli_parsing()
    print("FAILURES: 0")
