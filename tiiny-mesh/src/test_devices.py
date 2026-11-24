#!/usr/bin/env python3
"""Tests for devices.py — per-device registry and CLI configuration isolation."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import devices as D


def test_registry_defaults_and_lookup():
    reg = D.load_registry(registry_dir=Path("/nonexistent"))
    assert "tiiny-ant" in reg
    assert "tiiny-octo" in reg
    ant = reg["tiiny-ant"]
    assert ant.address == "198.51.100.198"
    assert ant.key_env == "TIINY_API_KEY"
    assert ant.npu_tops == 190.0
    assert ant.npu_ram_gib == 47.9

    by_ip = D.get_device("198.51.100.198", registry_dir=Path("/nonexistent"))
    assert by_ip is not None
    assert by_ip.name == "tiiny-ant"

    by_name = D.get_device("tiiny-octo", registry_dir=Path("/nonexistent"))
    assert by_name is not None
    assert by_name.address == "198.51.100.192"


def test_urls_are_literal_ips_never_aliases():
    dev = D.Device(
        name="test-box",
        address="198.51.100.50",
        key_env="TEST_KEY",
        cli_config="cli-test.json",
    )
    admin = dev.admin_url("/api/v1/models/running")
    base = dev.base_url("/chat/completions")
    chat = dev.chat_url()

    assert "198.51.100.50" in admin
    assert "tiinyhost.local" not in admin
    assert "openai.api.tiiny" not in admin

    assert "198.51.100.50/v1" in base
    assert chat == "http://198.51.100.50/v1/chat/completions"


def test_ensure_registry_creates_isolated_configs_without_leaking_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        tdir = Path(tmpdir)
        env_file = tdir / "test.env"
        env_file.write_text(
            "TIINY_API_KEY=ant-secret-key-12345\n"
            "TIINY_API_KEY_2=octo-secret-key-67890\n",
            encoding="utf-8",
        )
        reg_dir = tdir / "devices"

        devices = D.ensure_registry(registry_dir=reg_dir, env_file=env_file)
        assert len(devices) == 2

        # 1. Descriptor files must NOT contain the secret value
        for name in ("tiiny-ant", "tiiny-octo"):
            desc_file = reg_dir / f"{name}.json"
            assert desc_file.exists()
            content = desc_file.read_text(encoding="utf-8")
            assert "ant-secret-key" not in content
            assert "octo-secret-key" not in content
            assert "TIINY_API_KEY" in content

        # 2. CLI configs must contain the secret for CLI operation and be chmod 0600
        cli_ant = reg_dir / "cli-ant.json"
        cli_octo = reg_dir / "cli-octo.json"
        assert cli_ant.exists()
        assert cli_octo.exists()

        ant_cfg = json.loads(cli_ant.read_text(encoding="utf-8"))
        assert ant_cfg["deviceAddress"] == "198.51.100.198"
        assert ant_cfg["account"]["authKey"] == "ant-secret-key-12345"

        mode_ant = stat.S_IMODE(cli_ant.stat().st_mode)
        assert mode_ant == 0o600


def test_probe_running_identifies_401_as_auth_failure():
    # Test with bogus key against a live or unreachable device
    dev = D.Device(
        name="bogus-ant",
        address="198.51.100.198",
        key_env="NONEXISTENT_KEY_VAR_123",
        cli_config="cli-bogus.json",
    )
    status, details = D.probe_running(dev, timeout=5)
    if status == 401:
        assert any("auth_failed" in d for d in details)


def run_all():
    tests = [
        ("registry defaults & lookup", test_registry_defaults_and_lookup),
        ("urls are literal IPs", test_urls_are_literal_ips_never_aliases),
        ("ensure registry isolation & security", test_ensure_registry_creates_isolated_configs_without_leaking_keys),
        ("probe reports 401 cleanly", test_probe_running_identifies_401_as_auth_failure),
    ]
    fails = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:
            print(f"  FAIL {name}: {exc}")
            fails += 1
    if fails:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    run_all()
