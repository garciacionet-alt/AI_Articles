#!/usr/bin/env python3
"""AMC health witnessing tests — offline, temp-dir based."""

import os
import sys
import tempfile
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mesh_amc

def t(name, fn):
    try:
        fn()
        print("  ok   ", name)
        return 0
    except AssertionError as e:
        print("  FAIL ", name, "-", e)
        return 1

fails = 0

def test_engraphis_probe():
    with tempfile.TemporaryDirectory() as td:
        db_file = os.path.join(td, "engraphis.db")
        # Missing DB -> down
        res = mesh_amc.probe_engraphis(db_file)
        assert res["state"] == "down", res

        # Fresh DB -> up
        with open(db_file, "w") as f:
            f.write("sqlite format 3\0")
        res = mesh_amc.probe_engraphis(db_file)
        assert res["state"] == "up", res
        assert res["detail"]["size_mb"] >= 0

        # Old DB (>24h) -> degraded
        old_time = time.time() - 100000
        os.utime(db_file, (old_time, old_time))
        res = mesh_amc.probe_engraphis(db_file)
        assert res["state"] == "degraded", res

def test_obsidian_probe():
    with tempfile.TemporaryDirectory() as td:
        # Non-existent vault -> down
        res = mesh_amc.probe_obsidian(os.path.join(td, "missing_vault"))
        assert res["state"] == "down", res

        # Vault with fresh md file
        vault = os.path.join(td, "vault")
        os.makedirs(vault)
        md = os.path.join(vault, "note.md")
        with open(md, "w") as f:
            f.write("# Hello\n")

        res = mesh_amc.probe_obsidian(vault)
        # State will be up if Obsidian process is running, or degraded if not running but note is fresh
        assert res["state"] in ("up", "degraded"), res
        assert res["detail"]["files_scanned"] >= 1
        assert res["detail"]["latest_note"] == "note.md"

def test_idrive_probe():
    # Empty paths -> not-configured
    res = mesh_amc.probe_idrive([])
    assert res["state"] == "not-configured", res
    assert res["error"] is None

    # Bogus path -> down
    res = mesh_amc.probe_idrive(["/nonexistent/path/for/idrive/test"])
    assert res["state"] == "down", res
    assert res["error"] is not None

def test_collect():
    res = mesh_amc.collect({"force": True})
    assert res["object"] == "list"
    assert len(res["subsystems"]) == 3
    ids = [s["id"] for s in res["subsystems"]]
    assert ids == ["engraphis", "obsidian", "idrive"]

fails += t("engraphis probe states", test_engraphis_probe)
fails += t("obsidian probe states", test_obsidian_probe)
fails += t("idrive probe states", test_idrive_probe)
fails += t("collect aggregation", test_collect)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
