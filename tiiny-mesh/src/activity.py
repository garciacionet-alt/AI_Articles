"""activity.py — is a Tiiny working right now, and who is using it.

The dashboard already shows an NPU meter, but that meter answers a
different question: how much of the NPU *memory pool* is allocated to
resident models. A box with a 47% model loaded and nothing running reads
47% on that meter and is, in fact, idle.

What an operator actually wants to know before dispatching work is:
"is this box busy right now?" - and if it is, "who has it?"

Two answers, from two places:

  * the appliance itself, over `/api/v1/npu/status`. That endpoint
    carries the live compute utilisation (`devices[].util_percent`) and
    an `occupants` array naming the running instances, their
    `active_request_count`, and the individual `active_tasks`. Measured
    on 2026-11-23: 0.0% while idle, 75-97% during a generation, with
    `active_request_count` of 1 and the task's model and modality named.

  * the reservation. `mesh_watchdog` holds record who *claimed* a box.
    A hold says "agent-a owns this"; the device says "agent-a is
    actually running something on it". Both together answer "busy, and
    by whom" without trusting a poll that may have stopped.

This module samples the appliances on a timer and keeps a short rolling
history, so the panel can draw a sparkline of the last few minutes
rather than a single number that jumped.

It is deliberately dependency-free and never raises: a telemetry
failure must degrade to "unknown", never take the gateway with it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Compute utilisation at or above this counts as "working". The device
# reports 0.0 when idle and 75-97% under a generation, so the threshold
# sits in the wide empty middle rather than near either end.
BUSY_UTIL_THRESHOLD = 10.0

# How many samples to keep per device. At the default 2 s interval that
# is five minutes of history - long enough to see whether a box was busy
# a minute ago, short enough that a restarted gateway starts empty
# rather than replaying stale numbers.
DEFAULT_HISTORY = 150

# The default sampling interval. Fast enough to catch a generation
# starting, slow enough that two boxes cost about one request a second.
DEFAULT_INTERVAL = 2.0

# The NPU pool size every Tiiny reports. Used only as a fallback when
# the device does not send mem_total_mb.
FALLBACK_TOTAL_MB = 49024.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _tasks_from_occupants(occupants: Any) -> tuple[int, list[dict]]:
    """(active request count, task list) from the device's occupants.

    The shape is nested three deep and every level is optional:

        occupants[] -> activate_model[] -> active_tasks[]

    `active_request_count` sits on the model instance; `active_tasks`
    hangs off it with the task type, the modality, and when it started.
    A missing or empty occupants array means nothing is running.
    """
    count = 0
    tasks: list[dict] = []
    if not isinstance(occupants, list):
        return 0, tasks

    for occupant in occupants:
        if not isinstance(occupant, dict):
            continue
        app_id = occupant.get("app_id") or ""
        models = occupant.get("activate_model")
        if not isinstance(models, list):
            continue
        for instance in models:
            if not isinstance(instance, dict):
                continue
            count += int(_num(instance.get("active_request_count")))
            model_name = instance.get("model_name") or ""
            instance_id = instance.get("instance_id") or ""
            started = instance.get("started_at")
            for task in instance.get("active_tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_started = task.get("started_at") or started
                tasks.append({
                    "model": model_name,
                    "instance_id": instance_id,
                    "app_id": app_id,
                    "task_type": task.get("task_type") or app_id or "",
                    "modality": task.get("modality") or "",
                    "started_at": task_started,
                    "age_s": round(max(0.0, time.time() - _num(task_started)), 1)
                    if task_started else None,
                })
    return count, tasks


class ActivityMonitor:
    """Samples every appliance on a timer and keeps a rolling history."""

    def __init__(self, mesh_loader, interval: float = DEFAULT_INTERVAL,
                 history: int = DEFAULT_HISTORY):
        self._mesh_loader = mesh_loader
        self.interval = interval
        self.history = history
        self._lock = threading.Lock()
        # target id -> list of sample dicts, oldest first
        self._series: dict[str, list[dict]] = {}
        # target id -> the most recent sample
        self._latest: dict[str, dict] = {}
        self._started = time.time()

    # -- sampling --------------------------------------------------------
    def _sample(self, target) -> dict:
        """One reading from one appliance. Never raises."""
        now = time.time()
        base = {
            "t": now,
            "ok": False,
            "util_percent": None,
            "mem_used_mb": None,
            "mem_total_mb": None,
            "cpu_percent": None,
            "memory_percent": None,
            "active_requests": 0,
            "tasks": [],
            "error": None,
        }
        if getattr(target, "kind", "") != "tiiny":
            return base

        import mesh as M  # the sibling module, imported by bare name

        try:
            status, payload, _ = M._request(
                target.admin("/api/v1/npu/status"), target.key(), timeout=8)
        except Exception as e:
            base["error"] = f"{type(e).__name__}: {e}"
            return base

        if status != 200 or not isinstance(payload, dict):
            base["error"] = f"HTTP {status}"
            return base

        base["ok"] = True

        devices = payload.get("devices") or []
        dev = devices[0] if devices and isinstance(devices[0], dict) else {}
        base["util_percent"] = _num(dev.get("util_percent"))
        base["mem_used_mb"] = _num(dev.get("mem_used_mb"))
        base["mem_total_mb"] = _num(dev.get("mem_total_mb")) or FALLBACK_TOTAL_MB

        cpu = payload.get("cpu")
        if isinstance(cpu, dict):
            base["cpu_percent"] = _num(cpu.get("total_percent"))
        memory = payload.get("memory")
        if isinstance(memory, dict):
            base["memory_percent"] = _num(memory.get("usage_percent"))

        count, tasks = _tasks_from_occupants(payload.get("occupants"))
        base["active_requests"] = count
        base["tasks"] = tasks

        npu = payload.get("npu")
        if isinstance(npu, dict):
            base["npu_status"] = npu.get("status") or ""
        return base

    def tick(self) -> dict:
        """Sample every Tiiny target once. Never raises."""
        try:
            mesh = self._mesh_loader()
        except Exception:
            return {}
        out = {}
        for target in getattr(mesh, "targets", []):
            if getattr(target, "kind", "") != "tiiny":
                continue
            try:
                sample = self._sample(target)
            except Exception as e:
                sample = {"t": time.time(), "ok": False, "util_percent": None,
                          "mem_used_mb": None, "mem_total_mb": None,
                          "cpu_percent": None, "memory_percent": None,
                          "active_requests": 0, "tasks": [],
                          "error": f"{type(e).__name__}: {e}"}
            out[target.id] = sample
            with self._lock:
                series = self._series.setdefault(target.id, [])
                series.append(sample)
                if len(series) > self.history:
                    del series[: len(series) - self.history]
                self._latest[target.id] = sample
        return out

    def run_forever(self) -> None:
        """The sampler loop. Runs in the gateway's own thread."""
        while True:
            started = time.time()
            try:
                self.tick()
            except Exception:
                pass
            # sleep the remainder, so the cadence does not drift
            time.sleep(max(0.5, self.interval - (time.time() - started)))

    # -- state -----------------------------------------------------------
    @staticmethod
    def _state(sample: dict | None) -> str:
        """idle | busy | offline | unknown

        `busy` means the box is working *now*: it has an in-flight
        request, or its compute utilisation is above the threshold.
        Anything else that answers is idle, however much NPU memory it
        has allocated.
        """
        if not sample:
            return "unknown"
        if not sample.get("ok"):
            return "offline"
        if sample.get("active_requests", 0) > 0:
            return "busy"
        util = sample.get("util_percent")
        if util is not None and util >= BUSY_UTIL_THRESHOLD:
            return "busy"
        return "idle"

    def _busy_since(self, target_id: str, latest: dict) -> float | None:
        """When the current busy streak started, from the history.

        Walk BACK from the newest sample while the samples are still
        busy, and keep the oldest one. Walking forward would find the
        first busy sample ever - including a burst that ended an hour
        ago - so "busy for" would be wrong.
        """
        if self._state(latest) != "busy":
            return None
        with self._lock:
            series = list(self._series.get(target_id) or [])
        started = None
        for sample in reversed(series):
            if self._state(sample) != "busy":
                break
            started = sample.get("t")
        return started if started is not None else latest.get("t")

    # -- holds -----------------------------------------------------------
    @staticmethod
    def _holds() -> dict[str, dict]:
        """Every active hold, by device. Empty if the watchdog is absent."""
        try:
            import mesh_watchdog
            return mesh_watchdog.list_holds()
        except Exception:
            return {}

    # -- the payload -----------------------------------------------------
    def snapshot(self, include_history: bool = True) -> dict:
        """The activity report: one entry per appliance."""
        holds = self._holds()
        with self._lock:
            latest = dict(self._latest)
            series = {k: list(v) for k, v in self._series.items()}

        entries = []
        for target_id in sorted(latest):
            sample = latest[target_id]
            state = self._state(sample)
            hold = holds.get(target_id) or {}
            entry = {
                "target": target_id,
                "state": state,
                "busy": state == "busy",
                "util_percent": sample.get("util_percent"),
                "mem_used_mb": sample.get("mem_used_mb"),
                "mem_total_mb": sample.get("mem_total_mb"),
                "cpu_percent": sample.get("cpu_percent"),
                "memory_percent": sample.get("memory_percent"),
                "active_requests": sample.get("active_requests", 0),
                "tasks": sample.get("tasks") or [],
                "npu_status": sample.get("npu_status", ""),
                "error": sample.get("error"),
                "sampled_at": sample.get("t"),
                "busy_since": self._busy_since(target_id, sample),
                # the reservation: who claimed the box, if anybody
                "held_by": hold.get("owner"),
                "held_models": hold.get("models") or [],
                "hold_expires": hold.get("expires"),
            }
            if include_history:
                hist = series.get(target_id) or []
                entry["history"] = [
                    {
                        "t": s.get("t"),
                        "u": s.get("util_percent"),
                        "r": s.get("active_requests", 0),
                        "ok": bool(s.get("ok")),
                    }
                    for s in hist
                ]
            entries.append(entry)

        return {
            "generated": time.time(),
            "uptime_s": round(time.time() - self._started, 1),
            "interval_s": self.interval,
            "threshold": BUSY_UTIL_THRESHOLD,
            "targets": entries,
        }
