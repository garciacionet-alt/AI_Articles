#!/usr/bin/env python3
"""Tests for Mesh.pools() — dual-pool reporting, no unified sum.

Each Tiiny target is its own pool. We mock _request to avoid hitting real
devices, and verify the pool structure, memory numbers and the absence of
a summed pool.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Put the mesh source on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh


class MockTarget:
    """A Target stand-in for testing without real appliances."""

    def __init__(self, target_id, admin_url, kind="tiiny"):
        self.id = target_id
        self.kind = kind
        self.admin_url = admin_url

    def admin(self, path):
        return self.admin_url.rstrip("/") + path

    def key(self):
        return "mock-key"


# ------------------------------------------------------------------
# Helper: build the npu/status payload the way a real Tiiny returns it
# ------------------------------------------------------------------

def _npu_payload(mem_used_mb, mem_total_mb=49024.0, status="available"):
    return {
        "npu": {"status": status},
        "devices": [{
            "mem_used_mb": mem_used_mb,
            "mem_total_mb": mem_total_mb,
        }],
    }


def _running_payload(models_list=None):
    return {"running": models_list or ["Qwen/Qwen3.6-35B-A3B"], "models": models_list or ["Qwen/Qwen3.6-35B-A3B"]}


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestPools(unittest.TestCase):
    """Each Tiiny is its own pool; non-Tiiny targets are skipped."""

    def _make_mesh(self, targets, mocks=None):
        """Build a Mesh and apply _request mocks in one go."""
        m = mesh.Mesh(targets)
        if mocks:
            # mocks: list of tuples (call_args, return_value)
            # call_args is a callable that receives the _request call
            def side_effect(url, bearer="", method="GET", body=None, timeout=20):
                for call_fn, ret in mocks:
                    if call_fn(url):
                        return ret
                return (200, {}, {})
            return m, side_effect
        return m, None

    def test_two_tiiny_give_two_pools(self):
        """Two Tiiny targets -> two separate pool entries."""
        targets = [
            MockTarget("tiiny-ant", "http://198.51.100.10"),
            MockTarget("tiiny-octo", "http://198.51.100.11"),
        ]

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "/npu/status" in url:
                if "1.10" in url:
                    return (200, _npu_payload(12000.0), {})
                return (200, _npu_payload(20000.0), {})
            if "/models/running" in url:
                if "1.10" in url:
                    return (200, _running_payload(["model-a"]), {})
                return (200, _running_payload(["model-b"]), {})
            return (200, {}, {})

        m, _ = self._make_mesh(targets)
        # Patch _request at the module level
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        self.assertTrue(result.get("ok"))
        pools = result["pools"]
        self.assertEqual(len(pools), 2)
        ids = {p["target"] for p in pools}
        self.assertEqual(ids, {"tiiny-ant", "tiiny-octo"})

    def test_mem_total_around_49024(self):
        """Each pool's mem_total_mb should be ~49024 MB (default)."""
        targets = [MockTarget("tiiny-x", "http://192.0.2.1")]

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "/npu/status" in url:
                return (200, _npu_payload(5000.0), {})
            return (200, _running_payload(), {})

        m, _ = self._make_mesh(targets)
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        pool = result["pools"][0]
        self.assertAlmostEqual(pool["mem_total_mb"], 49024.0, delta=1.0)

    def test_no_unified_sum(self):
        """The result must never contain a summed/aggregate pool."""
        targets = [
            MockTarget("tiiny-ant", "http://198.51.100.10"),
            MockTarget("tiiny-octo", "http://198.51.100.11"),
            MockTarget("openai-proxy", "http://127.0.0.1:1234", kind="openai"),
        ]

        npu_ant = (200, _npu_payload(12000.0), {})
        npu_octo = (200, _npu_payload(20000.0), {})
        models_ant = (200, _running_payload(["a"]), {})
        models_octo = (200, _running_payload(["b"]), {})
        models_ao = (200, _npu_payload(0, mem_total_mb=0), {})

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "1.10" in url:
                if "/npu/status" in url:
                    return npu_ant
                return models_ant
            if "1.11" in url:
                if "/npu/status" in url:
                    return npu_octo
                return models_octo
            # openai target
            return (200, {"data": []}, {})

        m, _ = self._make_mesh(targets)
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        pools = result["pools"]
        # Only Tiiny targets should be in the pool list
        self.assertEqual(len(pools), 2)
        pool_ids = {p["target"] for p in pools}
        self.assertNotIn("openai-proxy", pool_ids)
        # No "summed" or "total" or "aggregate" entry
        for p in pools:
            self.assertNotIn("sum", p.get("name", "").lower())

    def test_util_percent_calculation(self):
        """util_percent should be (used/total)*100 rounded to 1 decimal."""
        targets = [MockTarget("tiiny-u", "http://192.0.2.5")]

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "/npu/status" in url:
                return (200, _npu_payload(24512.0, 49024.0), {})
            return (200, _running_payload(), {})

        m, _ = self._make_mesh(targets)
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        pool = result["pools"][0]
        expected = round((24512.0 / 49024.0) * 100.0, 1)
        self.assertAlmostEqual(pool["util_percent"], expected, places=1)

    def test_mem_free_non_negative(self):
        """mem_free_mb must never be negative (used could exceed total in edge cases)."""
        targets = [MockTarget("tiiny-o", "http://192.0.2.9")]

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "/npu/status" in url:
                # Simulate used > total (should clamp to 0)
                return (200, _npu_payload(60000.0, 49024.0), {})
            return (200, _running_payload(), {})

        m, _ = self._make_mesh(targets)
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        pool = result["pools"][0]
        self.assertGreaterEqual(pool["mem_free_mb"], 0.0)

    def test_address_parsing(self):
        """The address field should extract the host from admin_url."""
        targets = [MockTarget("tiiny-t", "http://198.51.100.42:8080")]

        def side_effect(url, bearer="", method="GET", body=None, timeout=20):
            if "/npu/status" in url:
                return (200, _npu_payload(0), {})
            return (200, _running_payload(), {})

        m, _ = self._make_mesh(targets)
        with patch.object(mesh, '_request', side_effect=side_effect):
            result = m.pools()

        pool = result["pools"][0]
        self.assertEqual(pool["address"], "198.51.100.42")


if __name__ == "__main__":
    unittest.main()
