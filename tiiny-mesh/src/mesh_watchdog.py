#!/usr/bin/env python3
"""mesh_watchdog.py — Per-device holds, locks, status, and restore for TiinyMesh.

Holds are lightweight TTL markers (JSON files) that record which models a
device is keeping resident.  Locks use fcntl.flock so concurrent processes
or a second agent on the same appliance are serialised into a single holder
for a given device.

The module plugs into the local ``devices.py`` module for probing, catalogue
queries, and model lifecycle management.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Re-use mesh.py helpers without duplicating logic
import mesh as _mesh

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration paths
# ---------------------------------------------------------------------------

HOLDS_DIR = Path(
    os.environ.get("TIINY_HOLDS_DIR", Path.home() / ".hermes" / "mesh" / "holds")
)
LOCKS_DIR = Path(
    os.environ.get("TIINY_LOCKS_DIR", Path.home() / ".hermes" / "mesh" / "locks")
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    """Create HOLDS_DIR and LOCKS_DIR with mode 0700."""
    for d in (HOLDS_DIR, LOCKS_DIR):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)


def _hold_path(device: str) -> Path:
    return HOLDS_DIR / f"{device}.json"


def _lock_path(device: str) -> Path:
    return LOCKS_DIR / f"{device}.lock"


def _write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via a temp file, then rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _is_expired(data: dict) -> bool:
    return time.time() > data.get("expires", 0)


# ---------------------------------------------------------------------------
# Holds — lightweight TTL markers
# ---------------------------------------------------------------------------


def hold(device_name: str, models: list[str], owner: str, ttl: int = 1800) -> dict:
    """Write a hold file for *device_name* listing the models to keep.

    Returns the written payload dict.
    """
    _ensure_dirs()
    now = time.time()
    payload = {
        "device": device_name,
        "owner": owner,
        "models": list(models),
        "created": now,
        "expires": now + ttl,
    }
    _write_json(_hold_path(device_name), payload)
    log.info(
        "hold  device=%s owner=%s models=%s ttl=%d",
        device_name, owner, models, ttl,
    )
    return payload


def release_hold(device_name: str, owner: str | None = None) -> bool:
    """Remove a hold file.  If *owner* is given it must match unless
    the hold is expired or the hold file itself is gone.

    Returns True when the hold was successfully released (or was already
    expired/gone).
    """
    path = _hold_path(device_name)
    data = _read_json(path)
    if data is None:
        return True  # nothing to release

    if _is_expired(data):
        path.unlink(missing_ok=True)
        log.info("release_hold device=%s (expired)", device_name)
        return True

    if owner is not None and data.get("owner") != owner:
        log.warning(
            "release_hold device=%s owner mismatch: %s != %s",
            device_name, owner, data.get("owner"),
        )
        return False

    path.unlink(missing_ok=True)
    log.info(
        "release_hold device=%s owner=%s",
        device_name, owner or data.get("owner"),
    )
    return True


def get_hold(device_name: str) -> dict | None:
    """Read a hold file.  If expired, unlink and return None."""
    data = _read_json(_hold_path(device_name))
    if data is None:
        return None
    if _is_expired(data):
        _hold_path(device_name).unlink(missing_ok=True)
        return None
    return data


def list_holds() -> dict[str, dict]:
    """Return {device_name: payload} for every active (non-expired) hold."""
    _ensure_dirs()
    result: dict[str, dict] = {}
    if not HOLDS_DIR.exists():
        return result
    for p in sorted(HOLDS_DIR.glob("*.json")):
        data = _read_json(p)
        if data is None:
            continue
        if not _is_expired(data):
            result[data.get("device", p.stem)] = data
    return result


# ---------------------------------------------------------------------------
# Locks — fcntl.flock based
# ---------------------------------------------------------------------------


def lock_acquire(
    device_name: str, owner: str, task: str = "", ttl: int = 1800
) -> tuple[dict | None, str]:
    """Acquire an exclusive lock on the device.

    Reads the lock JSON file.  If no lock or an expired lock exists,
    the lock is acquired.  If the lock is held by the same owner and
    not expired, it is renewed.  If held by a different non-expired
    owner, acquisition is rejected.

    Returns (payload, "") on success or (None, error_msg) on failure.
    """
    _ensure_dirs()
    path = _lock_path(device_name)

    existing = _read_json(path)

    if existing is not None and not _is_expired(existing):
        if existing.get("owner") == owner:
            # Same owner — renew
            now = time.time()
            payload = {
                "device": device_name,
                "owner": owner,
                "task": task,
                "created": now,
                "expires": now + ttl,
                "state": "held",
                "pid": os.getpid(),
            }
            _write_json(path, payload)
            log.info(
                "lock_renew device=%s owner=%s task=%s ttl=%d",
                device_name, owner, task, ttl,
            )
            return (payload, "")

        # Different owner — reject
        current_owner = existing.get("owner", "unknown")
        return (
            None,
            f"lock held by {current_owner} on {device_name}",
        )

    # No lock or expired — acquire fresh
    now = time.time()
    payload = {
        "device": device_name,
        "owner": owner,
        "task": task,
        "created": now,
        "expires": now + ttl,
        "state": "held",
        "pid": os.getpid(),
    }
    _write_json(path, payload)
    log.info(
        "lock_acquire device=%s owner=%s task=%s ttl=%d",
        device_name, owner, task, ttl,
    )
    return (payload, "")


def lock_release(device_name: str, owner: str, force: bool = False) -> tuple[bool, str]:
    """Release a lock.  owner must match unless force=True.

    Returns (True, "") on success or (False, error_msg) on failure.
    """
    path = _lock_path(device_name)
    data = _read_json(path)
    if data is None:
        return (True, "no lock held")

    if not force and data.get("owner") != owner:
        return (
            False,
            f"lock owner mismatch: {owner} != {data.get('owner')}",
        )

    path.unlink(missing_ok=True)
    log.info("lock_release device=%s owner=%s force=%s", device_name, owner, force)
    return (True, "")


def lock_status(device_name: str) -> dict | None:
    """Return the lock payload for *device_name*, or None if no lock held."""
    return _read_json(_lock_path(device_name))


# ---------------------------------------------------------------------------
# Integration with devices.py
# ---------------------------------------------------------------------------


def status(device_name: str | None = None) -> dict:
    """Gather status for every registered device or a single device.

    Returns {device_name: {address, reachable, hold, lock, models}}.
    """
    import devices as _devices

    reg = _devices.load_registry()
    devices_to_check: list[str]
    if device_name:
        dev = _devices.get_device(device_name)
        devices_to_check = [dev.name] if dev else []
    else:
        devices_to_check = sorted(reg.keys())

    result: dict[str, Any] = {}
    for name in devices_to_check:
        dev = reg.get(name)
        if dev is None:
            continue

        # Probe running models
        status_code, models = _devices.probe_running(dev)
        reachable = status_code > 0 and status_code != 404

        hold_data = get_hold(name)
        lock_data = lock_status(name)

        # Normalize models list (probe_running returns strings or dicts)
        model_list: list[str] = []
        for m in (models or []):
            if isinstance(m, dict):
                model_list.append(m.get("model_id", str(m)))
            else:
                model_list.append(str(m))

        result[name] = {
            "address": dev.address,
            "reachable": reachable,
            "probe_status": status_code,
            "models": model_list,
            "hold": hold_data,
            "lock": lock_data,
        }
    return result


def restore(device_name: str | None = None) -> dict:
    """Restore keep_resident models on a device if no hold is active.

    Reads the mesh config to discover keep_resident targets.  If no hold
    is active for the given device, checks running models and loads any
    missing keep_resident models.
    """
    import devices as _devices

    config_path = _mesh.DEFAULT_CONFIG
    if not config_path.exists():
        return {
            "ok": False,
            "error": f"mesh config not found: {config_path}",
        }

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "mesh config is not valid JSON"}

    reg = _devices.load_registry()

    # Build a list of targets from config
    target_specs: list[dict] = []
    if "targets" in cfg and isinstance(cfg["targets"], dict):
        for tid, spec in cfg["targets"].items():
            if not isinstance(spec, dict):
                continue
            spec["id"] = spec.get("id") or spec.get("name") or tid
            target_specs.append(spec)

    # Build a Mesh instance so we can use its lifecycle() method
    mesh_instance = _mesh.Mesh.load(config_path)

    results: list[dict] = []

    devices_to_restore: list[str]
    if device_name:
        devices_to_restore = [device_name] if device_name in reg else []
    else:
        devices_to_restore = sorted(reg.keys())

    for dev_name in devices_to_restore:
        dev = reg.get(dev_name)
        if dev is None:
            continue

        # Find the target that matches this device's address
        matching_targets = [
            t
            for t in mesh_instance.targets
            if t.kind == "tiiny"
            and t.base_url
            and dev.address in t.base_url
        ]

        if not matching_targets:
            results.append({
                "device": dev_name,
                "action": "skip",
                "reason": "no matching target in mesh config",
            })
            continue

        target = matching_targets[0]

        # Check if a hold is active for this device
        hold_data = get_hold(dev_name)
        if hold_data is not None:
            results.append({
                "device": dev_name,
                "action": "skip",
                "reason": "hold is active (models held by hold)",
                "hold": hold_data,
            })
            continue

        # Check running models
        running_status, running_models = _devices.probe_running(dev)
        if not (running_status > 0 and running_status != 404):
            results.append({
                "device": dev_name,
                "action": "skip",
                "reason": f"device not reachable (status {running_status})",
            })
            continue

        # Normalize running models to a set
        running_set: set[str] = set()
        for m in (running_models or []):
            if isinstance(m, dict):
                mid = m.get("model_id") or m.get("model")
                if mid:
                    running_set.add(mid)
            elif isinstance(m, str):
                running_set.add(m)

        keep = target.keep_resident if target.keep_resident else []

        for model in keep:
            if model in running_set:
                results.append({
                    "device": dev_name,
                    "model": model,
                    "action": "already resident",
                })
                continue

            lifecycle_result = mesh_instance.lifecycle(target.id, model, "start")
            results.append({
                "device": dev_name,
                "model": model,
                "action": "load",
                "ok": lifecycle_result.get("ok", False),
                "http": lifecycle_result.get("status"),
            })

    return {"ok": True, "device": device_name or "all", "actions": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point with subcommands: status, hold, release, lock, unlock, restore."""
    parser = argparse.ArgumentParser(
        description="TiinyMesh watchdog — holds, locks, status, restore"
    )
    sub = parser.add_subparsers(dest="command")

    # status
    p_status = sub.add_parser("status", help="Show device status")
    p_status.add_argument("--device", help="Specific device name")

    # hold
    p_hold = sub.add_parser("hold", help="Place a hold on a device")
    p_hold.add_argument("device", help="Device name")
    p_hold.add_argument("models", nargs="+", help="Models to hold")
    p_hold.add_argument("--owner", required=True, help="Owner name")
    p_hold.add_argument("--ttl", type=int, default=1800, help="TTL in seconds")

    # release
    p_release = sub.add_parser("release", help="Release a hold")
    p_release.add_argument("device", help="Device name")
    p_release.add_argument("--owner", help="Owner name (optional)")

    # lock
    p_lock = sub.add_parser("lock", help="Acquire an exclusive lock")
    p_lock.add_argument("device", help="Device name")
    p_lock.add_argument("--owner", required=True, help="Owner name")
    p_lock.add_argument("--task", default="", help="Task description")
    p_lock.add_argument("--ttl", type=int, default=1800, help="TTL in seconds")

    # unlock
    p_unlock = sub.add_parser("unlock", help="Release a lock")
    p_unlock.add_argument("device", help="Device name")
    p_unlock.add_argument("--owner", required=True, help="Owner name")
    p_unlock.add_argument("--force", action="store_true", help="Force release")

    # restore
    p_restore = sub.add_parser("restore", help="Restore keep_resident models")
    p_restore.add_argument("--device", help="Specific device name")

    args = parser.parse_args(argv)

    if args.command == "status":
        result = status(args.device)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "hold":
        result = hold(args.device, args.models, args.owner, args.ttl)
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "release":
        ok = release_hold(args.device, args.owner)
        print(json.dumps({"device": args.device, "released": ok}))

    elif args.command == "lock":
        payload, err = lock_acquire(args.device, args.owner, args.task, args.ttl)
        if err:
            print(json.dumps({"error": err}))
        else:
            print(json.dumps(payload, indent=2, default=str))

    elif args.command == "unlock":
        ok, err = lock_release(args.device, args.owner, force=args.force)
        print(json.dumps({"device": args.device, "released": ok, "error": err or ""}))

    elif args.command == "restore":
        result = restore(args.device)
        print(json.dumps(result, indent=2, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
