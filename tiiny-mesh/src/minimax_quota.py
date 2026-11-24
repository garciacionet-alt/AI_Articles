#!/usr/bin/env python3
"""MiniMax quota client for TiinyMesh.

Standard library only. Reads the MINIMAX_API_KEY, polls
`GET /v1/token_plan/remains`, parses model_remains for "general", and
returns a quota status dict with 300-second cache at
~/.hermes/mesh/.minimax_quota.json.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE = Path.home() / ".hermes" / "mesh" / ".minimax_quota.json"
CACHE_TTL = 300  # seconds


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ssl_context():
    """Reuse mesh._ssl_context() when mesh.py is importable, fall back."""
    try:
        import mesh as M
        return M._ssl_context()
    except Exception:
        import ssl
        return ssl.create_default_context()


def _http_get(url: str, bearer: str, timeout: int = 15) -> tuple[int, dict | None, str | None]:
    """Internal HTTP GET helper. Returns (status_code, json_dict, error_msg)."""
    headers = {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": "TiinyMesh/1.0",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        ctx = _ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = resp.status
            raw = resp.read()
            data = json.loads(raw.decode("utf-8", "replace"))
            return status, data, None
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read()
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            data = None
        return status, data, f"HTTP {status}"
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def _read_cache(cache_file: Path) -> dict | None:
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at < CACHE_TTL:
            out = dict(data)
            out.pop("_cached_at", None)
            out["cached"] = True
            return out
    except Exception:
        pass
    return None


def _write_cache(cache_file: Path, payload: dict) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        to_store = dict(payload)
        to_store["_cached_at"] = time.time()
        to_store["cached"] = False

        # Atomic replace via temp file
        with tempfile.NamedTemporaryFile("w", dir=str(cache_file.parent),
                                         delete=False, encoding="utf-8") as tf:
            json.dump(to_store, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, str(cache_file))
    except Exception:
        pass


def _load_api_key() -> str:
    """Return the API key from os.environ or ~/.hermes/.env."""
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        return key
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "MINIMAX_API_KEY" and not key:
                    key = v
        except OSError:
            pass
    return key.strip('"').strip("'")


def quota(cache_path=None, force=False, _fetcher=None) -> dict:
    """Poll MiniMax token plan remains and return quota status.

    Returns dict:
        {"ok": bool, "is_exhausted": bool,
         "interval_remaining_percent": float|None,
         "interval_status": int|None,
         "weekly_remaining_percent": float|None,
         "weekly_status": int|None,
         "weekly_remains_time_s": int|None,
         "fetched_at": str, "cached": bool, "error": str|None}
    """
    cache_file = Path(cache_path) if cache_path else DEFAULT_CACHE

    if not force:
        cached = _read_cache(cache_file)
        if cached is not None:
            return cached

    api_key = _load_api_key()
    if not api_key:
        result = {
            "ok": False,
            "is_exhausted": False,
            "interval_remaining_percent": None,
            "interval_status": None,
            "weekly_remaining_percent": None,
            "weekly_status": None,
            "weekly_remains_time_s": None,
            "fetched_at": _iso_now(),
            "cached": False,
            "error": "MINIMAX_API_KEY not found in environment or ~/.hermes/.env",
        }
        return result

    fetch = _fetcher or _http_get
    status, data, err = fetch(
        "https://api.minimax.io/v1/token_plan/remains",
        api_key,
    )
    if status != 200 or not isinstance(data, dict):
        result = {
            "ok": False,
            "is_exhausted": False,
            "interval_remaining_percent": None,
            "interval_status": None,
            "weekly_remaining_percent": None,
            "weekly_status": None,
            "weekly_remains_time_s": None,
            "fetched_at": _iso_now(),
            "cached": False,
            "error": err or f"HTTP {status}",
        }
        return result

    # Find model_remains for model_name == "general"
    model_remains = data.get("model_remains")
    if not isinstance(model_remains, list):
        result = {
            "ok": False,
            "is_exhausted": False,
            "interval_remaining_percent": None,
            "interval_status": None,
            "weekly_remaining_percent": None,
            "weekly_status": None,
            "weekly_remains_time_s": None,
            "fetched_at": _iso_now(),
            "cached": False,
            "error": "No model_remains list in response",
        }
        return result

    item = None
    for m in model_remains:
        if isinstance(m, dict) and m.get("model_name") == "general":
            item = m
            break

    if item is None:
        result = {
            "ok": False,
            "is_exhausted": False,
            "interval_remaining_percent": None,
            "interval_status": None,
            "weekly_remaining_percent": None,
            "weekly_status": None,
            "weekly_remains_time_s": None,
            "fetched_at": _iso_now(),
            "cached": False,
            "error": "No general model found in model_remains",
        }
        return result

    # Parse fields per the contract
    interval_remaining_percent = item.get("current_interval_remaining_percent")
    if isinstance(interval_remaining_percent, (int, float)):
        interval_remaining_percent = float(interval_remaining_percent)
    else:
        interval_remaining_percent = None

    interval_status = item.get("current_interval_status")
    if isinstance(interval_status, int):
        interval_status = int(interval_status)
    else:
        interval_status = None

    weekly_remaining_percent = item.get("current_weekly_remaining_percent")
    if isinstance(weekly_remaining_percent, (int, float)):
        weekly_remaining_percent = float(weekly_remaining_percent)
    else:
        weekly_remaining_percent = None

    weekly_status = item.get("current_weekly_status")
    if isinstance(weekly_status, int):
        weekly_status = int(weekly_status)
    else:
        weekly_status = None

    weekly_remains_time_s = item.get("weekly_remains_time")
    if weekly_remains_time_s is not None:
        try:
            weekly_remains_time_s = round(float(weekly_remains_time_s) / 1000.0)
        except (ValueError, TypeError):
            weekly_remains_time_s = 0
    else:
        weekly_remains_time_s = None

    is_exhausted = (
        (weekly_status == 2)
        or (weekly_remaining_percent is not None and weekly_remaining_percent <= 5)
        or (interval_status == 2)
    )

    result = {
        "ok": True,
        "is_exhausted": is_exhausted,
        "interval_remaining_percent": interval_remaining_percent,
        "interval_status": interval_status,
        "weekly_remaining_percent": weekly_remaining_percent,
        "weekly_status": weekly_status,
        "weekly_remains_time_s": weekly_remains_time_s,
        "fetched_at": _iso_now(),
        "cached": False,
        "error": None,
    }
    _write_cache(cache_file, result)
    return result
