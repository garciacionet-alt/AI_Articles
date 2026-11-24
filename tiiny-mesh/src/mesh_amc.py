#!/usr/bin/env python3
"""AMC (Agent Memory Commons) health witnessing for TiinyMesh.

Witnesses host-side status for:
1. Engraphis (semantic memory layer)
2. Obsidian (indexed memory tree)
3. iDrive (replicated sandbox filesystem)

Standard library only.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ENGRAPHIS_DB = Path.home() / ".engraphis" / "engraphis.db"
DEFAULT_VAULT_PATH = Path.home() / "Library" / "Mobile Documents" / "CloudDocs" / "OpenHuman" / "projects"

_CACHE: dict = {}
_CACHE_TIME = 0.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _is_process_running(pattern: str) -> bool:
    """Check if process matching pattern is running via pgrep."""
    try:
        res = subprocess.run(["pgrep", "-f", pattern],
                             capture_output=True, text=True, timeout=3)
        return res.returncode == 0
    except Exception:
        return False


def probe_engraphis(db_path: str | Path) -> dict:
    """Probe Engraphis semantic memory layer."""
    p = Path(db_path).expanduser()
    if not p.exists():
        return {
            "id": "engraphis",
            "label": "Engraphis",
            "role": "semantic memory layer",
            "state": "down",
            "summary": "database not found",
            "detail": {"path": str(p)},
            "error": "engraphis.db missing",
        }

    try:
        size_bytes = p.stat().st_size
        mtime = p.stat().st_mtime
        wal = p.parent / (p.name + "-wal")
        if wal.exists():
            mtime = max(mtime, wal.stat().st_mtime)

        age_s = max(0.0, time.time() - mtime)
        proc_running = _is_process_running("engraphis")

        state = "up" if age_s < 86400 else "degraded"
        summary = f"last write {_format_age(age_s)} ({size_bytes // (1024*1024)} MB)"

        return {
            "id": "engraphis",
            "label": "Engraphis",
            "role": "semantic memory layer",
            "state": state,
            "summary": summary,
            "detail": {
                "path": str(p),
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "last_write_age_s": round(age_s, 1),
                "last_write": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                "process_running": proc_running,
            },
            "error": None,
        }
    except Exception as e:
        return {
            "id": "engraphis",
            "label": "Engraphis",
            "role": "semantic memory layer",
            "state": "degraded",
            "summary": "error reading db",
            "detail": {"path": str(p)},
            "error": str(e),
        }


def probe_obsidian(vault_path: str | Path) -> dict:
    """Probe Obsidian indexed memory tree."""
    vp = Path(vault_path).expanduser()
    if not vp.exists() or not vp.is_dir():
        return {
            "id": "obsidian",
            "label": "Obsidian",
            "role": "indexed memory tree",
            "state": "down",
            "summary": "vault directory missing",
            "detail": {"vault_path": str(vp)},
            "error": "vault path not found",
        }

    proc_running = _is_process_running("Obsidian")

    # Bounded scan for newest markdown file mtime
    newest_mtime = 0.0
    newest_file = ""
    file_count = 0
    start_t = time.time()

    skip_dirs = {".git", ".obsidian", ".cache", "node_modules", ".trash"}
    try:
        for root, dirs, files in os.walk(str(vp)):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for f in files:
                if f.endswith(".md"):
                    file_count += 1
                    fp = os.path.join(root, f)
                    try:
                        mt = os.path.getmtime(fp)
                        if mt > newest_mtime:
                            newest_mtime = mt
                            newest_file = f
                    except OSError:
                        pass
                if file_count >= 20000 or (time.time() - start_t) > 3.0:
                    break
            if file_count >= 20000 or (time.time() - start_t) > 3.0:
                break
    except Exception:
        pass

    age_s = max(0.0, time.time() - newest_mtime) if newest_mtime > 0 else None

    # Determine state
    if proc_running and age_s is not None and age_s < 86400:
        state = "up"
    elif proc_running or (age_s is not None and age_s < 86400):
        state = "degraded"
    else:
        state = "down"

    summary = f"indexed {_format_age(age_s)}" if age_s is not None else "no notes found"
    if not proc_running:
        summary += " (app not running)"

    return {
        "id": "obsidian",
        "label": "Obsidian",
        "role": "indexed memory tree",
        "state": state,
        "summary": summary,
        "detail": {
            "vault_path": str(vp),
            "process_running": proc_running,
            "last_index_age_s": round(age_s, 1) if age_s is not None else None,
            "last_index_event": datetime.fromtimestamp(newest_mtime, timezone.utc).isoformat() if newest_mtime > 0 else None,
            "latest_note": newest_file,
            "files_scanned": file_count,
        },
        "error": None,
    }


def probe_idrive(paths: list[str | Path]) -> dict:
    """Probe iDrive replicated sandbox filesystem."""
    if not paths:
        return {
            "id": "idrive",
            "label": "iDrive",
            "role": "shared & replicated sandbox filesystem",
            "state": "not-configured",
            "summary": "not configured on this host",
            "detail": {"paths": []},
            "error": None,
        }

    mounted = []
    missing = []
    for p in paths:
        sp = str(Path(p).expanduser())
        if os.path.exists(sp):
            is_mnt = os.path.ismount(sp)
            try:
                st = os.statvfs(sp)
                free_gb = round((st.f_bavail * st.f_frsize) / (1024**3), 1)
                total_gb = round((st.f_blocks * st.f_frsize) / (1024**3), 1)
                mounted.append({"path": sp, "mounted": is_mnt, "free_gb": free_gb, "total_gb": total_gb})
            except Exception:
                mounted.append({"path": sp, "mounted": is_mnt})
        else:
            missing.append(sp)

    if missing and not mounted:
        state = "down"
        summary = f"mount missing ({missing[0]})"
    elif missing:
        state = "degraded"
        summary = f"{len(mounted)} mounted, {len(missing)} missing"
    else:
        state = "up"
        summary = f"{len(mounted)} mount(s) active"

    return {
        "id": "idrive",
        "label": "iDrive",
        "role": "shared & replicated sandbox filesystem",
        "state": state,
        "summary": summary,
        "detail": {"mounted": mounted, "missing": missing},
        "error": f"missing paths: {missing}" if missing else None,
    }


def collect(config: dict | None = None) -> dict:
    """Collect AMC status across subsystems."""
    global _CACHE, _CACHE_TIME
    cfg = config or {}
    amc_cfg = cfg.get("amc") or {}

    poll_s = int(amc_cfg.get("poll_seconds") or 300)
    now = time.time()
    if _CACHE and (now - _CACHE_TIME) < poll_s and not config.get("force"):
        return _CACHE

    db_path = amc_cfg.get("engraphis_db") or str(DEFAULT_ENGRAPHIS_DB)
    vault_path = amc_cfg.get("vault_path") or str(DEFAULT_VAULT_PATH)
    idrive_paths = amc_cfg.get("idrive_paths") or []

    res = {
        "object": "list",
        "fetched_at": _iso_now(),
        "subsystems": [
            probe_engraphis(db_path),
            probe_obsidian(vault_path),
            probe_idrive(idrive_paths),
        ],
    }
    _CACHE = res
    _CACHE_TIME = now
    return res
