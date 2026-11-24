"""devices.py — Per-device registry for multi-device Tiiny management.

Provides explicit, isolated per-device identity for Tiiny appliances:
- Each device is keyed by a stable name and a literal IP address (never focus-dependent aliases).
- Registry descriptors store the NAME of the environment variable (e.g. TIINY_API_KEY), never secrets.
- Generates dedicated 0600 CLI configs (~/.hermes/tiiny-devices/cli-<name>.json) so `tiiny --config`
  is isolated and never mutates the default CLI configuration.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ENV_FILE = Path(os.environ.get("TIINY_MESH_ENV", str(Path.home() / ".hermes" / ".env")))
DEFAULT_REGISTRY_DIR = Path(os.environ.get("TIINY_DEVICES_DIR", str(Path.home() / ".hermes" / "tiiny-devices")))

# Built-in inventory for the dual-device estate
DEFAULT_DEVICES = {
    "tiiny-ant": {
        "name": "tiiny-ant",
        "address": "198.51.100.198",
        "key_env": "TIINY_API_KEY",
        "device_id": "TNYM…redacted",
        "cli_config": "cli-ant.json",
        "npu_tops": 190.0,
        "npu_ram_gib": 47.9,
    },
    "tiiny-octo": {
        "name": "tiiny-octo",
        "address": "198.51.100.192",
        "key_env": "TIINY_API_KEY_2",
        "device_id": "TNYM…redacted",
        "cli_config": "cli-octo.json",
        "npu_tops": 190.0,
        "npu_ram_gib": 47.9,
    },
}


def _read_env_var(name: str, env_file: Path | None = None) -> str:
    """Read an env var value from os.environ first, then from ~/.hermes/.env."""
    if not name:
        return ""
    val = os.environ.get(name, "").strip()
    if val:
        return val.strip('"').strip("'")
    target_env = env_file or ENV_FILE
    if target_env.exists():
        try:
            for line in target_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


@dataclass
class Device:
    name: str
    address: str
    key_env: str
    cli_config: str
    device_id: str = ""
    npu_tops: float = 190.0
    npu_ram_gib: float = 47.9

    def key(self, env_file: Path | None = None) -> str:
        """Resolve the bearer token without leaking it."""
        return _read_env_var(self.key_env, env_file=env_file)

    def admin_url(self, path: str = "") -> str:
        base = f"http://{self.address}"
        if not path:
            return base
        return base + ("" if path.startswith("/") else "/") + path

    def base_url(self, path: str = "") -> str:
        base = f"http://{self.address}/v1"
        if not path:
            return base
        return base + ("" if path.startswith("/") else "/") + path

    def chat_url(self) -> str:
        return self.base_url("/chat/completions")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def cli_config_path(self, registry_dir: Path | None = None) -> Path:
        rdir = registry_dir or DEFAULT_REGISTRY_DIR
        cfg = Path(self.cli_config)
        if cfg.is_absolute():
            return cfg
        return rdir / cfg


def load_registry(registry_dir: Path | None = None) -> dict[str, Device]:
    """Load devices from ~/.hermes/tiiny-devices/*.json."""
    rdir = registry_dir or DEFAULT_REGISTRY_DIR
    devices: dict[str, Device] = {}
    if rdir.exists():
        for p in sorted(rdir.glob("*.json")):
            if p.name.startswith("cli-"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "name" in data and "address" in data:
                    cli_cfg = data.get("cli_config") or f"cli-{data['name']}.json"
                    dev = Device(
                        name=data["name"],
                        address=data["address"],
                        key_env=data.get("key_env", ""),
                        cli_config=cli_cfg,
                        device_id=data.get("device_id", ""),
                        npu_tops=float(data.get("npu_tops", 190.0)),
                        npu_ram_gib=float(data.get("npu_ram_gib", 47.9)),
                    )
                    devices[dev.name] = dev
            except (OSError, ValueError, TypeError):
                continue

    if not devices:
        for name, spec in DEFAULT_DEVICES.items():
            devices[name] = Device(**spec)

    return devices


def get_device(name_or_ip: str, registry_dir: Path | None = None) -> Device | None:
    """Find a device by name or IP address."""
    reg = load_registry(registry_dir=registry_dir)
    if name_or_ip in reg:
        return reg[name_or_ip]
    for d in reg.values():
        if d.address == name_or_ip:
            return d
    return None


def ensure_registry(registry_dir: Path | None = None, env_file: Path | None = None) -> dict[str, Device]:
    """Ensure the registry directory, descriptor files, and 0600 CLI configs exist."""
    rdir = registry_dir or DEFAULT_REGISTRY_DIR
    rdir.mkdir(parents=True, exist_ok=True)
    os.chmod(rdir, 0o700)

    devices = load_registry(registry_dir=rdir)

    for name, dev in devices.items():
        desc_path = rdir / f"{name}.json"
        desc_data = dev.to_dict()
        desc_path.write_text(json.dumps(desc_data, indent=2), encoding="utf-8")
        os.chmod(desc_path, 0o600)

        # Write CLI config with that device's authKey
        cli_path = dev.cli_config_path(registry_dir=rdir)
        key_val = dev.key(env_file=env_file)
        cli_content = {
            "deviceAddress": dev.address,
            "account": {
                "authKey": key_val,
            },
        }
        cli_path.write_text(json.dumps(cli_content, indent=2), encoding="utf-8")
        os.chmod(cli_path, 0o600)

    return devices


def probe_running(device: Device, timeout: int = 8, env_file: Path | None = None) -> tuple[int, list[str]]:
    """Query /api/v1/models/running for a device."""
    key = device.key(env_file=env_file)
    url = device.admin_url("/api/v1/models/running")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            running = data.get("running") or []
            return resp.status, running
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return 401, [f"auth_failed: wrong bearer for {device.name} via {device.key_env}"]
        return exc.code, [f"http_error_{exc.code}"]
    except Exception as exc:
        return 0, [f"unreachable: {exc}"]
