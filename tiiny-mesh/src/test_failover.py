#!/usr/bin/env python3
"""Test transparent 429 failover in mesh.py."""

import json
import os
import sys
import tempfile
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mesh as M

def test_429_failover():
    # Setup a mesh with primary target that returns 429 and secondary that returns 200
    doc = {
        "policy": {
            "chat": {
                "primary": "mock-primary/model-a",
                "secondary": "mock-secondary/model-b"
            }
        },
        "targets": {
            "mock-primary": {
                "kind": "openai",
                "base_url": "http://192.0.2.1/v1",
                "models": ["model-a"],
                "priority": 10,
                "capabilities": ["chat"]
            },
            "mock-secondary": {
                "kind": "openai",
                "base_url": "http://192.0.2.2/v1",
                "models": ["model-b"],
                "priority": 20,
                "capabilities": ["chat"]
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(doc, tf)
        path = tf.name

    m = M.Mesh.load(path)
    os.unlink(path)

    # Monkeypatch _request
    def mock_request(url, bearer="", method="GET", body=None, timeout=30):
        if "192.0.2.1" in url:
            return 429, {"error": {"message": "Rate limit exceeded"}}, {}
        if "192.0.2.2" in url:
            return 200, {"choices": [{"message": {"role": "assistant", "content": "Success from secondary"}}]}, {}
        return 404, None, {}

    old_req = M._request
    M._request = mock_request
    try:
        res = m.chat("mock-primary/model-a", {"messages": [{"role": "user", "content": "hi"}]})
        assert res.get("ok") is True, f"Expected ok=True, got {res}"
        assert res["payload"]["choices"][0]["message"]["content"] == "Success from secondary"
        route = res["payload"]["mesh_route"]
        assert route["failover_from"] == "mock-primary", route
        assert route["failover_reason"] == "429 rate limit", route
        print("  ok    429 failover to secondary")
    finally:
        M._request = old_req

if __name__ == "__main__":
    test_429_failover()
    print("FAILURES: 0")
