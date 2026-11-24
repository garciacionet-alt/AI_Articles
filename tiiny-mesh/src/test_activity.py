#!/usr/bin/env python3
"""Tests for the activity monitor — "is this Tiiny working right now?".

The monitor's job is to turn the appliance's `/api/v1/npu/status` into
an honest answer about load, and to attribute a reservation when one
exists. These tests mock the device so nothing here touches a real box.

The device's payload, measured on 2026-11-23:

    {
      "devices": [{"util_percent": 78.05, "mem_used_mb": 22697.0,
                   "mem_total_mb": 49024.0}],
      "cpu": {"total_percent": 42.1},
      "memory": {"usage_percent": 68.8},
      "occupants": [{"app_id": "API",
                     "activate_model": [{"model_name": "Qwen/Qwen3.6-35B-A3B",
                                         "active_request_count": 1,
                                         "active_tasks": [{"modality": "chat",
                                                           "started_at": 123.0}]}]}],
      "npu": {"status": "ready"}
    }
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import activity


class MockTarget:
    def __init__(self, target_id="tiiny-ant", kind="tiiny"):
        self.id = target_id
        self.kind = kind
        self.admin_url = "http://192.0.2.10"

    def admin(self, path):
        return self.admin_url.rstrip("/") + path

    def key(self):
        return "mock-key"


class MockMesh:
    def __init__(self, targets):
        self.targets = targets


def _payload(util=0.0, mem_used=22697.0, mem_total=49024.0, requests=0,
             occupants=None, npu_status="ready"):
    if occupants is None:
        occupants = []
    return {
        "devices": [{
            "device_id": 0,
            "util_percent": util,
            "mem_used_mb": mem_used,
            "mem_total_mb": mem_total,
        }],
        "cpu": {"total_percent": 10.5},
        "memory": {"usage_percent": 68.8},
        "occupants": occupants,
        "npu": {"status": npu_status},
    }


def _occupants(model="Qwen/Qwen3.6-35B-A3B", requests=1, modality="chat",
                started_at=None):
    if started_at is None:
        started_at = time.time() - 30
    return [{
        "app_id": "API",
        "activate_model": [{
            "model_name": model,
            "instance_id": "runtime_abc",
            "pid": None,
            "port": 9090,
            "started_at": started_at - 600,
            "active_request_count": requests,
            "active_tasks": [{
                "task_type": "API",
                "app_id": "API",
                "session_id": None,
                "modality": modality,
                "started_at": started_at,
                "display_type": "API",
            }],
        }],
    }]


# ------------------------------------------------------------------


class TestStateDerivation(unittest.TestCase):
    """idle / busy / offline - and the distinction that matters."""

    def test_zero_util_and_no_requests_is_idle(self):
        sample = {"ok": True, "util_percent": 0.0, "active_requests": 0}
        self.assertEqual(activity.ActivityMonitor._state(sample), "idle")

    def test_high_util_is_busy(self):
        sample = {"ok": True, "util_percent": 78.05, "active_requests": 0}
        self.assertEqual(activity.ActivityMonitor._state(sample), "busy")

    def test_any_request_in_flight_is_busy_even_at_zero_util(self):
        # the device can report a request that has not started computing
        sample = {"ok": True, "util_percent": 0.0, "active_requests": 1}
        self.assertEqual(activity.ActivityMonitor._state(sample), "busy")

    def test_memory_allocated_but_idle_is_still_idle(self):
        # the whole point: a resident model fills the pool but the box
        # is not working. Util, not memory, decides.
        sample = {"ok": True, "util_percent": 0.0, "active_requests": 0,
                  "mem_used_mb": 38148.0}
        self.assertEqual(activity.ActivityMonitor._state(sample), "idle")

    def test_unreachable_is_offline(self):
        sample = {"ok": False, "util_percent": None, "active_requests": 0}
        self.assertEqual(activity.ActivityMonitor._state(sample), "offline")

    def test_no_sample_is_unknown(self):
        self.assertEqual(activity.ActivityMonitor._state(None), "unknown")


class TestOccupants(unittest.TestCase):
    """The nested occupants array, which is the device's own answer."""

    def test_empty_occupants_means_nothing_running(self):
        count, tasks = activity._tasks_from_occupants([])
        self.assertEqual(count, 0)
        self.assertEqual(tasks, [])

    def test_missing_occupants_is_safe(self):
        count, tasks = activity._tasks_from_occupants(None)
        self.assertEqual(count, 0)
        self.assertEqual(tasks, [])

    def test_request_count_and_task_detail(self):
        count, tasks = activity._tasks_from_occupants(
            _occupants(requests=2, modality="chat"))
        self.assertEqual(count, 2)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["model"], "Qwen/Qwen3.6-35B-A3B")
        self.assertEqual(tasks[0]["modality"], "chat")
        self.assertIsNotNone(tasks[0]["age_s"])
        self.assertGreaterEqual(tasks[0]["age_s"], 25)

    def test_two_instances_are_counted_together(self):
        occupants = _occupants(requests=1) + _occupants(requests=3)
        count, tasks = activity._tasks_from_occupants(occupants)
        self.assertEqual(count, 4)
        self.assertEqual(len(tasks), 2)

    def test_malformed_occupants_do_not_raise(self):
        count, tasks = activity._tasks_from_occupants(
            ["nonsense", {"activate_model": "not a list"}, {"activate_model": [None]}])
        self.assertEqual(count, 0)
        self.assertEqual(tasks, [])


class TestSnapshot(unittest.TestCase):
    """The payload the panel reads."""

    def _monitor(self, payload, holds=None):
        mon = activity.ActivityMonitor(lambda: MockMesh([MockTarget()]))
        with patch("mesh._request", return_value=(200, payload, {})):
            mon.tick()
        # the holds patch has to be live when snapshot() runs, not when
        # tick() does
        if holds is not None:
            with patch.object(activity.ActivityMonitor, "_holds",
                              staticmethod(lambda: holds)):
                return mon.snapshot()
        return mon.snapshot()

    def test_snapshot_shape(self):
        snap = self._monitor(_payload(util=78.05, requests=1,
                                       occupants=_occupants()))
        self.assertEqual(len(snap["targets"]), 1)
        entry = snap["targets"][0]
        self.assertEqual(entry["target"], "tiiny-ant")
        self.assertEqual(entry["state"], "busy")
        self.assertTrue(entry["busy"])
        self.assertEqual(entry["util_percent"], 78.05)
        self.assertEqual(entry["active_requests"], 1)
        self.assertEqual(entry["mem_total_mb"], 49024.0)
        self.assertEqual(len(entry["tasks"]), 1)

    def test_history_grows_and_is_capped(self):
        mon = activity.ActivityMonitor(lambda: MockMesh([MockTarget()]),
                                       history=5)
        with patch("mesh._request", return_value=(200, _payload(), {})):
            for _ in range(12):
                mon.tick()
        snap = mon.snapshot()
        self.assertEqual(len(snap["targets"][0]["history"]), 5)

    def test_history_can_be_omitted(self):
        mon = activity.ActivityMonitor(lambda: MockMesh([MockTarget()]))
        with patch("mesh._request", return_value=(200, _payload(), {})):
            mon.tick()
        snap = mon.snapshot(include_history=False)
        self.assertNotIn("history", snap["targets"][0])

    def test_reservation_is_attributed(self):
        holds = {"tiiny-ant": {"device": "tiiny-ant", "owner": "agent-a",
                                "models": ["Qwen/Qwen3.6-35B-A3B"]}}
        entry = self._monitor(_payload(util=80.0, requests=1,
                                       occupants=_occupants()),
                              holds=holds)["targets"][0]
        self.assertEqual(entry["held_by"], "agent-a")
        self.assertEqual(entry["held_models"], ["Qwen/Qwen3.6-35B-A3B"])

    def test_no_reservation_reads_as_nobody(self):
        entry = self._monitor(_payload(), holds={})["targets"][0]
        self.assertIsNone(entry["held_by"])

    def test_busy_since_is_set_on_a_busy_streak(self):
        entry = self._monitor(_payload(util=80.0, requests=1,
                                       occupants=_occupants()))["targets"][0]
        self.assertIsNotNone(entry["busy_since"])

    def test_busy_since_is_the_start_of_the_current_streak(self):
        # The bug this catches: walking forward through the history
        # returns the FIRST busy sample ever, so "busy for" reads as the
        # age of the last burst instead of the current one.
        mon = activity.ActivityMonitor(lambda: MockMesh([MockTarget()]))
        base = 1000.0

        def sample(t, util, requests):
            return {"t": t, "ok": True, "util_percent": util,
                    "active_requests": requests, "mem_used_mb": 22697.0,
                    "mem_total_mb": 49024.0, "cpu_percent": 1.0,
                    "memory_percent": 1.0, "tasks": [], "error": None}

        series = [
            sample(base + 0, 80.0, 1),    # an old burst
            sample(base + 1, 0.0, 0),     # idle
            sample(base + 2, 0.0, 0),     # idle
            sample(base + 3, 75.0, 1),    # the current burst starts
            sample(base + 4, 80.0, 1),
            sample(base + 5, 82.0, 1),
        ]
        with mon._lock:
            mon._series["tiiny-ant"] = list(series)
            mon._latest["tiiny-ant"] = series[-1]

        entry = mon.snapshot()["targets"][0]
        self.assertEqual(entry["busy_since"], base + 3)

    def test_busy_since_is_none_when_idle(self):
        entry = self._monitor(_payload())["targets"][0]
        self.assertIsNone(entry["busy_since"])

    def test_offline_target_reports_the_error(self):
        mon = activity.ActivityMonitor(lambda: MockMesh([MockTarget()]))
        with patch("mesh._request", return_value=(None, "connection refused", {})):
            mon.tick()
        entry = mon.snapshot()["targets"][0]
        self.assertEqual(entry["state"], "offline")
        self.assertIsNotNone(entry["error"])


class TestResilience(unittest.TestCase):
    """Telemetry must never take the gateway down."""

    def test_non_tiiny_target_is_skipped(self):
        mon = activity.ActivityMonitor(
            lambda: MockMesh([MockTarget(kind="openai")]))
        self.assertEqual(mon.tick(), {})

    def test_broken_mesh_loader_does_not_raise(self):
        def boom():
            raise RuntimeError("no config")
        mon = activity.ActivityMonitor(boom)
        self.assertEqual(mon.tick(), {})

    def test_snapshot_with_no_samples(self):
        mon = activity.ActivityMonitor(lambda: MockMesh([]))
        snap = mon.snapshot()
        self.assertEqual(snap["targets"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
