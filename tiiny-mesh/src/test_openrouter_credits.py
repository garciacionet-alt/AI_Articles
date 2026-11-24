#!/usr/bin/env python3
"""OpenRouter credits client tests — offline, fixture-driven."""

import os
import sys
import tempfile
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import openrouter

def t(name, fn):
    try:
        fn()
        print("  ok   ", name)
        return 0
    except AssertionError as e:
        print("  FAIL ", name, "-", e)
        return 1

fails = 0

def test_account_response():
    def mock_fetch(url, bearer, timeout=15):
        assert url == "https://openrouter.ai/api/v1/credits"
        return 200, {"data": {"total_credits": 100.5, "total_usage": 25.75}}, None

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        cache_path = tf.name
    try:
        old_mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        os.environ["OPENROUTER_MANAGEMENT_KEY"] = "mock_mgmt_key"
        res = openrouter.credits(cache_path=cache_path, force=True, _fetcher=mock_fetch)
        assert res["ok"] is True, res
        assert res["scope"] == "account", res["scope"]
        assert res["balance"] == 74.75, res["balance"]
        assert res["total_credits"] == 100.5, res["total_credits"]
        assert res["total_usage"] == 25.75, res["total_usage"]
        assert res["cached"] is False
    finally:
        if old_mgmt is not None:
            os.environ["OPENROUTER_MANAGEMENT_KEY"] = old_mgmt
        else:
            os.environ.pop("OPENROUTER_MANAGEMENT_KEY", None)
        if os.path.exists(cache_path):
            os.unlink(cache_path)

def test_key_fallback_response():
    def mock_fetch(url, bearer, timeout=15):
        if "credits" in url:
            return 403, {"error": {"message": "Only management keys allowed"}}, "HTTP 403"
        if "key" in url:
            return 200, {"data": {"usage": 12.34, "limit_remaining": 87.66}}, None
        return 404, None, "not found"

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        cache_path = tf.name
    try:
        old_mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        old_api = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_MANAGEMENT_KEY"] = "bad_mgmt_key"
        os.environ["OPENROUTER_API_KEY"] = "mock_api_key"

        res = openrouter.credits(cache_path=cache_path, force=True, _fetcher=mock_fetch)
        assert res["ok"] is True, res
        assert res["scope"] == "key", res["scope"]
        assert res["needs"] == "management_key", res["needs"]
        assert res["key_usage"] == 12.34, res["key_usage"]
        assert res["limit_remaining"] == 87.66, res["limit_remaining"]
    finally:
        if old_mgmt is not None:
            os.environ["OPENROUTER_MANAGEMENT_KEY"] = old_mgmt
        else:
            os.environ.pop("OPENROUTER_MANAGEMENT_KEY", None)
        if old_api is not None:
            os.environ["OPENROUTER_API_KEY"] = old_api
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)
        if os.path.exists(cache_path):
            os.unlink(cache_path)

def test_both_fail():
    def mock_fetch(url, bearer, timeout=15):
        return 401, {"error": {"message": "Unauthorized"}}, "HTTP 401"

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        cache_path = tf.name
    try:
        old_mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        old_api = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_MANAGEMENT_KEY"] = "bad_mgmt"
        os.environ["OPENROUTER_API_KEY"] = "bad_api"

        res = openrouter.credits(cache_path=cache_path, force=True, _fetcher=mock_fetch)
        assert res["ok"] is False, res
        assert res["error"] is not None and isinstance(res["error"], str), res["error"]
        assert "traceback" not in res["error"].lower(), res["error"]
    finally:
        if old_mgmt is not None:
            os.environ["OPENROUTER_MANAGEMENT_KEY"] = old_mgmt
        else:
            os.environ.pop("OPENROUTER_MANAGEMENT_KEY", None)
        if old_api is not None:
            os.environ["OPENROUTER_API_KEY"] = old_api
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)
        if os.path.exists(cache_path):
            os.unlink(cache_path)

def test_cache_ttl():
    calls = []
    def mock_fetch(url, bearer, timeout=15):
        calls.append(url)
        return 200, {"data": {"total_credits": 100.5, "total_usage": 25.75}}, None

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        cache_path = tf.name
    try:
        old_mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        os.environ["OPENROUTER_MANAGEMENT_KEY"] = "mock_mgmt_key"

        r1 = openrouter.credits(cache_path=cache_path, force=True, _fetcher=mock_fetch)
        assert r1["cached"] is False
        assert len(calls) == 1

        r2 = openrouter.credits(cache_path=cache_path, force=False, _fetcher=mock_fetch)
        assert r2["cached"] is True
        assert len(calls) == 1, f"Expected 1 fetch, got {len(calls)}"
    finally:
        if old_mgmt is not None:
            os.environ["OPENROUTER_MANAGEMENT_KEY"] = old_mgmt
        else:
            os.environ.pop("OPENROUTER_MANAGEMENT_KEY", None)
        if os.path.exists(cache_path):
            os.unlink(cache_path)

def test_no_keys_in_cache():
    def mock_fetch(url, bearer, timeout=15):
        return 200, {"data": {"total_credits": 100.5, "total_usage": 25.75}}, None

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        cache_path = tf.name
    try:
        secret_key = "sk-or-v1-secret-test-key-should-never-be-saved"
        old_mgmt = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        os.environ["OPENROUTER_MANAGEMENT_KEY"] = secret_key

        openrouter.credits(cache_path=cache_path, force=True, _fetcher=mock_fetch)
        content = pathlib.Path(cache_path).read_text(encoding="utf-8")
        assert secret_key not in content, "Secret key was leaked into cache file!"
        assert "sk-or" not in content, "sk-or prefix found in cache file!"
    finally:
        if old_mgmt is not None:
            os.environ["OPENROUTER_MANAGEMENT_KEY"] = old_mgmt
        else:
            os.environ.pop("OPENROUTER_MANAGEMENT_KEY", None)
        if os.path.exists(cache_path):
            os.unlink(cache_path)

fails += t("account response balance calculation", test_account_response)
fails += t("key fallback response", test_key_fallback_response)
fails += t("both fail error handling", test_both_fail)
fails += t("cache TTL second call cached", test_cache_ttl)
fails += t("no keys in cache file", test_no_keys_in_cache)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
