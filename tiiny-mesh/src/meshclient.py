#!/usr/bin/env python3
"""Shared helpers for the TiinyMesh test scripts.

Every test script points at the gateway through these, so a test can be
pointed at a copy instead of the live one:

    TIINY_MESH_PORT=8799 TIINY_MESH_CONFIG=/path/to/config.json python3 e2e.py

Without the env vars the live gateway on 8767 is used, which is what you
want when you are testing the thing that is actually running.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

PORT = os.environ.get("TIINY_MESH_PORT", "8767")
GW = f"http://127.0.0.1:{PORT}"


def key() -> str:
    """The gateway's key: the env var, else the key file."""
    k = os.environ.get("TIINY_MESH_KEY", "").strip()
    if k:
        return k
    path = os.environ.get(
        "TIINY_MESH_KEY_FILE",
        str(Path.home() / ".hermes" / "mesh" / "gateway_key"))
    return Path(path).read_text().strip()


def call(method, path, body=None, timeout=240, raw=None, ctype=None):
    """One HTTP call against the gateway. Returns (status, bytes, content_type)."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Authorization": f"Bearer {key()}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(GW + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}".encode(), ""


def js(path, timeout=240):
    """One GET against the gateway, parsed as JSON."""
    status, raw, _ = call("GET", path, timeout=timeout)
    try:
        return status, json.loads(raw)
    except Exception:
        return status, {"raw": raw[:200].decode("utf-8", "replace")}
