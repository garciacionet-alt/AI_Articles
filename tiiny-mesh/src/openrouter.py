#!/usr/bin/env python3
"""OpenRouter target support and account credits client for TiinyMesh.

Standard library only.
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

DEFAULT_CACHE = Path.home() / ".hermes" / "mesh" / ".openrouter_credits.json"
CACHE_TTL = 86400  # 24 hours


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_env_keys() -> tuple[str, list[str]]:
    """Return (management_key, list_of_api_keys) from env, ~/.hermes/.env, or ~/.hermes/auth.json."""
    mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY", "").strip()
    api_candidates: list[str] = []

    env_api = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("OPENROUTER_KEY", "").strip()
    if env_api:
        api_candidates.append(env_api)

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
                if k == "OPENROUTER_MANAGEMENT_KEY" and not mgmt:
                    mgmt = v
                elif k in ("OPENROUTER_API_KEY", "OPENROUTER_KEY"):
                    if v and v not in api_candidates:
                        api_candidates.append(v)
        except OSError:
            pass

    auth_file = Path.home() / ".hermes" / "auth.json"
    if auth_file.exists():
        try:
            auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
            for item in auth_data.get("credential_pool", {}).get("openrouter", []):
                tok = (item.get("access_token") or item.get("api_key") or "").strip()
                if tok and tok not in api_candidates:
                    api_candidates.append(tok)
        except Exception:
            pass

    return mgmt, api_candidates


def _ssl_context():
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
        with tempfile.NamedTemporaryFile("w", dir=str(cache_file.parent), delete=False, encoding="utf-8") as tf:
            json.dump(to_store, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, str(cache_file))
    except Exception:
        pass


def credits(cache_path: str | Path | None = None, force: bool = False,
            _fetcher=None) -> dict:
    """Fetch OpenRouter account credit balance or per-key usage.

    Returns dict matching the contract specified in sprint-plan-2026-11-14.md.
    """
    cache_file = Path(cache_path) if cache_path else Path(os.environ.get("OPENROUTER_CREDITS_CACHE", str(DEFAULT_CACHE)))

    if not force:
        cached = _read_cache(cache_file)
        if cached is not None:
            return cached

    fetch = _fetcher or _http_get
    mgmt_key, api_keys = _read_env_keys()

    # Step 1: If management key is available, try GET /api/v1/credits
    if mgmt_key:
        status, data, err = fetch("https://openrouter.ai/api/v1/credits", mgmt_key)
        if status == 200 and isinstance(data, dict) and "data" in data:
            d = data["data"]
            tot_credits = float(d.get("total_credits", 0.0))
            tot_usage = float(d.get("total_usage", 0.0))
            balance = round(tot_credits - tot_usage, 4)
            result = {
                "ok": True,
                "scope": "account",
                "balance": balance,
                "total_credits": tot_credits,
                "total_usage": tot_usage,
                "key_usage": None,
                "limit_remaining": None,
                "fetched_at": _iso_now(),
                "cached": False,
                "error": None,
                "needs": None,
            }
            _write_cache(cache_file, result)
            return result

    # Step 2: Fall back to GET /api/v1/key with candidate API keys
    for api_key in api_keys:
        status, data, err = fetch("https://openrouter.ai/api/v1/key", api_key)
        if status == 200 and isinstance(data, dict) and "data" in data:
            kd = data["data"]
            key_usage = float(kd.get("usage", 0.0)) if kd.get("usage") is not None else None
            lim_rem = float(kd.get("limit_remaining")) if kd.get("limit_remaining") is not None else None
            result = {
                "ok": True,
                "scope": "key",
                "balance": lim_rem,
                "total_credits": None,
                "total_usage": None,
                "key_usage": key_usage,
                "limit_remaining": lim_rem,
                "fetched_at": _iso_now(),
                "cached": False,
                "error": None,
                "needs": "management_key",
            }
            _write_cache(cache_file, result)
            return result

    # Step 3: Neither succeeded or no keys configured
    error_msg = "No OpenRouter keys configured"
    needs = "management_key"
    if mgmt_key or api_keys:
        error_msg = "OpenRouter authentication failed or API unreachable"

    result = {
        "ok": False,
        "scope": None,
        "balance": None,
        "total_credits": None,
        "total_usage": None,
        "key_usage": None,
        "limit_remaining": None,
        "fetched_at": _iso_now(),
        "cached": False,
        "error": error_msg,
        "needs": needs,
    }
    return result
