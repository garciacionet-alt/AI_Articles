#!/usr/bin/env python3
"""tiiny_ctl.py — the device controller for the Tiiny model-routing skill.

The routing plugin chooses a model per subtask. This script owns everything
around that choice: the plan, the cross-agent lock, the load, the restore, and
the catalogue refresh.

Why the split
-------------
The delegation plugin has exactly one hook, ``route_task``, and it is called
once per subtask *before* any child runs. There is no "batch finished" hook,
so a plugin cannot know when it is safe to evict a model, and it cannot know
whether a sibling agent is already using the device. Loading therefore has to
live outside the plugin, in a step the manager agent drives explicitly and can
see:

    plan  ->  reserve  ->  load  ->  delegate  ->  release

Between ``plan`` and ``load`` the plan file (``~/.hermes/tiiny-plan.json``) is
what the two halves share: it records which model was assigned to which goal,
so the plugin routes the child to the model this script just loaded.

The lock
--------
Tiiny is one shared box. Two agents delegating at the same time will fight
over the same resident models and the same NPU pool. The lock makes that
visible instead of silent:

  * ``~/.hermes/tiiny-lock.json`` is the mutex. It is taken with
    ``flock`` over a file created with ``O_EXCL`` semantics, so two agents
    cannot both believe they hold it. It expires, so a crashed agent does not
    lock the device forever.
  * The vault's ``hot.md`` carries the announcement — the AMC's own board of
    what is in flight — so agents that are not Hermes profiles can see that
    the device is spoken for.

The sandbox this often runs in cannot unlink or rename files. That is why the
lock is *released by writing a released state into it* rather than by deleting
it, and why the hold file is truncated rather than removed.

Commands
--------
    status                      device, resident set, lock, hold, plan
    plan --goal G [--goal G]    pick models, check the NPU fit, write the plan
    reserve --owner NAME        take the lock and announce it
    load [--model M] [--wave N] load what the batch needs, verify residency
    release [--force]           restore the device, clear the lock and the plan
    catalog [--refresh]         diff the live Model Store against the snapshot
    image "a job description"   pick the right image model for the job

Exit codes: 0 success, 1 the operation failed, 2 the usage was wrong.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- paths ------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _shared_home() -> Path:
    """The BASE Hermes home, even when HERMES_HOME points at a profile.

    Four files are shared state across every profile: the plan, the
    cross-agent lock, the hold file, and the catalogue snapshot.

    Two readers live in the base home and will not look anywhere else:

    - the delegation plugin reads the plan from ``~/.hermes/tiiny-plan.json``
      on purpose — "every profile's manager agent must see the same plan";
    - the watchdog reads the hold from ``~/.hermes/tiiny-hold``.

    When HERMES_HOME is a profile directory (``.../hermes/profiles/<name>``)
    a naive ``HERMES_HOME / "tiiny-hold"`` writes the hold somewhere the
    watchdog never reads. The hold then does not hold: the watchdog reloads
    its required set mid-swap and evicts whatever was deliberately loaded.
    This is the failure the hold file exists to prevent, so the shared
    files have to be resolved against the base home, not the profile.
    """
    home = HERMES_HOME
    if home.name != "profiles" and home.parent.name == "profiles":
        return home.parent.parent
    return home


def _dotenv_value(name: str) -> str:
    """Read one value out of ``~/.hermes/.env`` without printing anything else."""
    try:
        for line in (HERMES_HOME / ".env").read_text().splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return ""


def _caller_owner() -> str:
    """Who is calling.

    The lock is between AGENTS, not between processes: two Hermes profiles on
    one machine are two agents sharing one appliance. TIINY_OWNER wins;
    otherwise the active profile's name, because that is what identifies the
    agent. Falls back to the OS user.

    An empty string means "unknown", and unknown callers are treated as
    NOT the owner of anything — an unidentified agent must not be able to
    take a device another agent is holding.
    """
    env = os.environ.get("TIINY_OWNER", "").strip()
    if env:
        return env
    home = HERMES_HOME
    if home.name != "profiles" and home.parent.name == "profiles":
        return home.name
    return os.environ.get("USER", "").strip()


def _lock_holder() -> dict | None:
    """The lock payload while it is held by someone, or None.

    "Held" means: state is held AND it has not expired. An expired lock is
    free for the taking — that is how a crashed agent does not hold the
    device forever.
    """
    current = lock_read() or {}
    if current.get("state") != "held":
        return None
    try:
        expires = float(current.get("expires") or 0)
    except (TypeError, ValueError):
        expires = 0
    if expires <= time.time():
        return None
    return current


def _held_by_other(owner: str, holder: dict | None) -> bool:
    """True when the device is held by an agent that is not ``owner``.

    An empty ``owner`` is "unknown caller" and never matches the holder, so
    an agent that cannot identify itself cannot disturb another agent's
    device.
    """
    if not holder:
        return False
    held_by = holder.get("owner") or ""
    return held_by != owner



def _find_vault() -> Path | None:
    """Find the vault root — the directory that holds ``hot.md``.

    The controller runs from two places: the vault's skill directory (the
    master copy) and an installed copy under ``~/.hermes/scripts``. In the
    first case the vault is two levels up; in the second it is nowhere near.
    So look for the marker instead of assuming a depth: the vault root is the
    directory that has both ``hot.md`` and ``skills/`` in it.

    Three ways to find it, in order: the ``TIINY_VAULT`` environment
    variable, the same name in ``~/.hermes/.env``, and a walk up from this
    file. The walk is what finds it for the master copy; the other two are
    what an installed copy uses.

    No machine path is hard-coded here. This file is published, and a
    published file must not carry the path of the machine it was written on.
    """
    override = os.environ.get("TIINY_VAULT") or _dotenv_value("TIINY_VAULT")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.exists() else None
    for base in (SKILL_ROOT, HERE):
        for parent in (base, *base.parents):
            try:
                if (parent / "hot.md").exists() and (parent / "skills").exists():
                    return parent
            except OSError:
                continue
    return None


VAULT = _find_vault()

#: Shared state. These live in the BASE Hermes home, not the profile — see
#: `_shared_home` for why, and for the failure that follows if they do not.
SHARED_HOME = _shared_home()
LOCK_FILE = SHARED_HOME / "tiiny-lock.json"
PLAN_FILE = Path(os.environ.get("TIINY_PLAN_FILE", str(SHARED_HOME / "tiiny-plan.json")))
HOLD_FILE = SHARED_HOME / "tiiny-hold"
SNAPSHOT_FILE = SHARED_HOME / "tiiny-catalogue.json"

TIINY_BIN = Path(os.environ.get("TIINY_BIN", "~/.local/tiiny/bin/tiiny")).expanduser()
INFERENCE_BASE = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny/v1").rstrip("/")
MANAGEMENT_BASE = os.environ.get("TIINY_HOST", "http://tiinyhost.local").rstrip("/")

#: The models the watchdog keeps resident. The controller restores exactly
#: this set on release, so the two lists must stay identical — a list that
#: drifts is how a device ends up missing a model that the delegation config
#: expects, which shows up as a 404 and a silent fallback to the paid
#: provider.
REQUIRED_MODELS = (
    "Qwen/Qwen3.6-35B-A3B",
    "Qwen/Qwen3-ASR-1.7B",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Supertone/supertonic-3",
    "openai/gpt-oss-20b",
)

#: The lock's announcement block in hot.md.
LOCK_MARK_START = "<!-- tiiny-device-lock:start -->"
LOCK_MARK_END = "<!-- tiiny-device-lock:end -->"

#: Default lock lifetime, in seconds. Long enough for a long research batch,
#: short enough that a crashed agent does not lock the device overnight.
DEFAULT_TTL = 1800


def _load_tiers():
    """Load the shared tier table by path (see tiers.py for why).

    The table lives next to the plugin in the vault's skill directory, and
    beside the installed plugin under the Hermes tree. Both are searched, so
    the controller works from either copy of itself.
    """
    import importlib.util

    candidates = [
        SKILL_ROOT / "plugin" / "tiers.py",
        HERE / "tiers.py",
        Path(os.path.expanduser(
            "~/.hermes/hermes-agent/plugins/delegation/tiiny-router/tiers.py")),
    ]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        raise SystemExit(
            "could not find the tier table. Looked in: "
            + ", ".join(str(c) for c in candidates)
        )
    spec = importlib.util.spec_from_file_location("tiiny_tiers", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load the tier table from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tiers = _load_tiers()


# --- device access ----------------------------------------------------------

def device_key() -> str:
    """Return the device bearer, or an empty string.

    Tried in order: the environment, ``~/.hermes/.env`` (where Hermes keeps
    it — it is NOT in the process environment for plugin code), and the vault's
    ``pocketlab/CREDENTIALS.md``. The value is never printed.
    """
    value = os.environ.get("TIINY_API_KEY", "").strip()
    if value:
        return value

    dotenv = HERMES_HOME / ".env"
    try:
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line.startswith("TIINY_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    except Exception:
        pass

    credentials = (VAULT / "pocketlab" / "CREDENTIALS.md") if VAULT else None
    try:
        match = re.search(
            r"TIINY_API_KEY=\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            credentials.read_text(),
        )
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def _request(url: str, key: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} from {url}: {exc.read().decode('utf8', 'replace')[:200]}")
    except Exception as exc:
        raise SystemExit(f"could not reach {url}: {exc}")


def resident_ids() -> list[str]:
    """The model ids the inference endpoint can serve right now."""
    key = device_key()
    if not key:
        return []
    payload = _request(INFERENCE_BASE + "/models", key, timeout=10)
    ids = []
    for entry in payload.get("data") or []:
        value = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(value, str) and "/" in value:
            ids.append(value)
    return sorted(ids)


def catalogue() -> list[dict]:
    """The live Model Store, normalised to the fields the skill cares about."""
    key = device_key()
    if not key:
        raise SystemExit("no device key found (TIINY_API_KEY, ~/.hermes/.env, or the vault)")
    payload = _request(MANAGEMENT_BASE + "/api/v1/models/online_models", key, timeout=30)
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "id": item.get("fullname"),
            "name": item.get("name"),
            "type": item.get("type"),
            "npu": item.get("npu_usage"),
            "context": item.get("context_window"),
            "status": item.get("status"),
            "desc": (item.get("desc") or "").strip(),
        })
    rows.sort(key=lambda r: (str(r.get("type")), -(r.get("npu") or 0), str(r.get("id"))))
    return rows


def catalogue_index() -> dict[str, dict]:
    """The live catalogue keyed by model id."""
    return {row["id"]: row for row in catalogue() if row.get("id")}


def npu_of(model: str, index: dict[str, dict] | None = None) -> int:
    """A model's NPU share, from the device when possible, else the table."""
    if index and model in index and index[model].get("npu") is not None:
        return int(index[model]["npu"])
    value = tiers.model_npu(model)
    return int(value) if value is not None else 0


# --- device state -----------------------------------------------------------

def cli_load(model: str) -> bool:
    """Load a model onto the device.

    ``tiiny load`` opens ``/dev/tty`` and fails from a script with "could not
    open a new TTY", so it runs under ``script -q /dev/null`` to get a
    pseudo-terminal. Loads are sequential: the NPU is one shared pool, and
    concurrent loads evict each other mid-load.
    """
    if not TIINY_BIN.exists():
        print(f"tiiny_ctl: the tiiny CLI is missing at {TIINY_BIN}", file=sys.stderr)
        return False
    try:
        result = subprocess.run(
            ["script", "-q", "/dev/null", str(TIINY_BIN), "load", model, "-y"],
            capture_output=True, text=True, timeout=900,
        )
    except Exception as exc:
        print(f"tiiny_ctl: load of {model} failed: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        print(f"tiiny_ctl: load of {model} failed: {' '.join(tail)}", file=sys.stderr)
        return False
    return True


def cli_unload(model: str) -> bool:
    """Unload a model from the device, freeing its NPU share.

    Same pseudo-terminal trick as the load: the CLI opens ``/dev/tty``.
    """
    if not TIINY_BIN.exists():
        print(f"tiiny_ctl: the tiiny CLI is missing at {TIINY_BIN}", file=sys.stderr)
        return False
    try:
        result = subprocess.run(
            ["script", "-q", "/dev/null", str(TIINY_BIN), "unload", model, "-y"],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        print(f"tiiny_ctl: unload of {model} failed: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        print(f"tiiny_ctl: unload of {model} failed: {' '.join(tail)}", file=sys.stderr)
        return False
    return True


def ensure_room(wave: list[str], index: dict[str, dict] | None = None) -> tuple[list[str], list[str]]:
    """Decide what must be evicted so a wave's models can all be resident.

    Returns ``(to evict, kept)``.

    **Why the controller decides this and not the device.** When a load does
    not fit, the device picks what to evict, and it does not know what the
    batch needs. Left to itself it kept the 47% generalist and evicted the
    27% model the wave had just asked for — so the wave's own model was
    missing and its child would have answered ``404 "is not loaded"``.

    So the controller works out what stays before it loads anything: the
    wave's models are sacred, and of everything else the cheapest are kept
    while they fit in what is left. A 5% TTS model is worth keeping; a 47%
    generalist is not, when a wave needs the pool. Everything dropped here
    is restored by ``release``.
    """
    resident = resident_ids()
    wave_set = set(wave)
    wave_share = sum(npu_of(m, index) for m in wave)
    budget = 100 - wave_share

    kept: list[str] = []
    kept_share = 0
    evict: list[str] = []
    others = [m for m in resident if m not in wave_set]
    for model in sorted(others, key=lambda m: npu_of(m, index)):
        share = npu_of(model, index)
        if kept_share + share <= budget:
            kept.append(model)
            kept_share += share
        else:
            evict.append(model)
    return evict, kept


def hold_write(models: list[str]) -> None:
    """Hold the device: the watchdog reloads nothing while this file exists.

    The FIRST line is the model the watchdog checks for staleness, so it must
    be a model that is resident for the whole batch. A multi-wave batch
    rewrites the hold as each wave starts.
    """
    HOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLD_FILE.write_text("".join(f"{m}\n" for m in models))


def hold_clear() -> None:
    """Release the hold.

    Truncate first — a write always works, even where deletion is blocked —
    then try to remove the file, then VERIFY. An empty hold file is a released
    hold, and a script that prints "cleared" without checking is exactly how a
    stale hold disables the watchdog forever.
    """
    try:
        HOLD_FILE.write_text("")
    except Exception:
        pass
    try:
        HOLD_FILE.unlink()
    except Exception:
        pass
    try:
        if HOLD_FILE.exists() and HOLD_FILE.stat().st_size > 0:
            raise SystemExit(
                f"tiiny_ctl: could not release the hold at {HOLD_FILE} — the watchdog "
                "will keep treating the device as held. Truncate it by hand."
            )
    except FileNotFoundError:
        pass


def hold_state() -> list[str]:
    """The models the hold file names."""
    try:
        return [line.strip() for line in HOLD_FILE.read_text().splitlines() if line.strip()]
    except Exception:
        return []


# --- the lock ---------------------------------------------------------------

def lock_read() -> dict | None:
    """The lock's current contents, or None if there is no lock file."""
    try:
        return json.loads(LOCK_FILE.read_text())
    except Exception:
        return None


def _lock_fd():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    return os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)


def _lock_write(fd: int, payload: dict) -> None:
    data = json.dumps(payload, indent=1).encode()
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, data)
    os.fsync(fd)


def lock_acquire(owner: str, task: str, ttl: int, models: list[str] | None = None) -> tuple[dict | None, str]:
    """Take the lock. Returns ``(payload, error)`` — payload is None on failure.

    The critical section is an ``flock`` on the lock file, so two agents
    racing for it are serialised by the kernel rather than by hope. The lock
    itself outlives the process: it is the file's contents, and it expires.
    """
    fd = _lock_fd()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None, "another process is holding the lock right now"

        now = time.time()
        current = lock_read()
        if current and current.get("state") == "held":
            expires = float(current.get("expires") or 0)
            if expires > now:
                if current.get("owner") == owner:
                    # RENEW. The holder extends its own lock. Without this a
                    # long build has to either release the device mid-build
                    # or lose the device to an agent that takes over when the
                    # TTL runs out.
                    payload = dict(current)
                    payload["expires"] = now + ttl
                    payload["models"] = models or current.get("models") or []
                    payload["task"] = task or current.get("task", "")
                    payload["pid"] = os.getpid()
                    _lock_write(fd, payload)
                    return payload, ""
                return None, (
                    f"the device is held by {current.get('owner')} "
                    f"({current.get('task') or 'no task recorded'}) "
                    f"until {time.strftime('%H:%M:%S', time.localtime(expires))}"
                )
            print(
                f"tiiny_ctl: taking over an expired lock from {current.get('owner')} "
                f"(expired {time.strftime('%H:%M:%S', time.localtime(expires))})."
            )

        payload = {
            "state": "held",
            "owner": owner,
            "task": task,
            "models": models or [],
            "created": now,
            "expires": now + ttl,
            "pid": os.getpid(),
        }
        _lock_write(fd, payload)
        return payload, ""
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def lock_release(owner: str, force: bool = False) -> tuple[bool, str]:
    """Release the lock. The file stays; its contents record the release."""
    fd = _lock_fd()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False, "another process is holding the lock right now"
        current = lock_read() or {}
        if current.get("state") == "held":
            # Strict: the owner must match exactly. An empty owner is not a
            # wildcard — it is "unknown caller", and an unknown caller must
            # not be able to release somebody else's lock.
            if not force and current.get("owner") != owner:
                return False, (
                    f"the lock is held by {current.get('owner')}, not {owner}. "
                    "Use --force if that is wrong."
                )
        _lock_write(fd, {
            "state": "released",
            "owner": current.get("owner", owner),
            "task": current.get("task", ""),
            "released": time.time(),
            "pid": os.getpid(),
        })
        return True, ""
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# --- the announcement -------------------------------------------------------

def _hot_md() -> Path | None:
    if VAULT is None:
        return None
    hot = VAULT / "hot.md"
    return hot if hot.exists() else None


def announce_set(text: str) -> bool:
    """Write the announcement block into hot.md. Returns True if it landed."""
    hot = _hot_md()
    if hot is None:
        return False
    body = hot.read_text()
    block = f"{LOCK_MARK_START}\n{text}\n{LOCK_MARK_END}"
    if LOCK_MARK_START in body and LOCK_MARK_END in body:
        head = body[: body.index(LOCK_MARK_START)]
        tail = body[body.index(LOCK_MARK_END) + len(LOCK_MARK_END):]
        updated = head + block + tail
    else:
        updated = body.rstrip() + "\n\n" + block + "\n"
    updated = re.sub(r"(?m)^updated:.*$", f"updated: {time.strftime('%Y-%m-%d')}", updated, count=1)
    hot.write_text(updated)
    return True


def announce_clear() -> bool:
    """Remove the announcement block from hot.md."""
    hot = _hot_md()
    if hot is None:
        return False
    body = hot.read_text()
    if LOCK_MARK_START not in body or LOCK_MARK_END not in body:
        return False
    head = body[: body.index(LOCK_MARK_START)]
    tail = body[body.index(LOCK_MARK_END) + len(LOCK_MARK_END):]
    hot.write_text((head.rstrip() + "\n\n" + tail.lstrip()).rstrip() + "\n")
    return True


# --- the plan ---------------------------------------------------------------

def plan_write(entries: list[dict], waves: list[list[str]], owner: str, task: str) -> dict:
    payload = {
        "batch": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{os.getpid():x}",
        "created": time.time(),
        "owner": owner,
        "task": task,
        "entries": entries,
        "waves": waves,
    }
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps(payload, indent=1))
    return payload


def plan_read() -> dict | None:
    try:
        return json.loads(PLAN_FILE.read_text())
    except Exception:
        return None


def plan_clear() -> None:
    try:
        PLAN_FILE.write_text("")
    except Exception:
        pass
    try:
        PLAN_FILE.unlink()
    except Exception:
        pass


# --- commands ---------------------------------------------------------------

def cmd_status(args) -> int:
    print("TIINY DEVICE STATUS\n")

    key = device_key()
    print(f"  key        : {'found' if key else 'NOT FOUND'}")
    print(f"  inference  : {INFERENCE_BASE}")
    print(f"  management : {MANAGEMENT_BASE}")

    try:
        resident = resident_ids()
    except SystemExit as exc:
        print(f"  device     : UNREACHABLE — {exc}")
        resident = []
    else:
        print(f"  device     : reachable")

    index = {}
    try:
        index = catalogue_index()
    except SystemExit:
        pass

    if resident:
        print(f"\n  RESIDENT ({len(resident)} models, "
              f"{sum(npu_of(m, index) for m in resident)}% NPU):")
        for model in resident:
            print(f"    {npu_of(model, index):>3}%  {model}")
    else:
        print("\n  RESIDENT: none known")

    lock = lock_read() or {}
    state = lock.get("state", "none")
    if state == "held":
        expires = float(lock.get("expires") or 0)
        remaining = int(expires - time.time())
        print(f"\n  LOCK: HELD by {lock.get('owner')} — {lock.get('task') or 'no task'} "
              f"({remaining}s left)")
        print(f"        models: {', '.join(lock.get('models') or []) or '(none recorded)'}")
    else:
        print(f"\n  LOCK: {state}")

    held = hold_state()
    print(f"  HOLD: {', '.join(held) if held else '(none — the watchdog is live)'}")

    plan = plan_read()
    if plan and plan.get("entries"):
        print(f"\n  PLAN {plan.get('batch')}: {len(plan['entries'])} task(s), "
              f"{len(plan.get('waves') or [])} wave(s), owner {plan.get('owner')}")
    else:
        print("\n  PLAN: none")

    return 0


def cmd_plan(args) -> int:
    goals = list(args.goal or [])
    if not goals:
        print("tiiny_ctl: plan needs at least one --goal", file=sys.stderr)
        return 2

    index = catalogue_index()
    resident = set(resident_ids())

    # Which candidate can this device actually run? A model that is not
    # downloaded cannot be loaded, so choosing it would produce a plan that
    # fails at the load step.
    def candidates(tier: str) -> list[str]:
        return [name for name, _npu, _ctx in tiers.TIER_CHOICES[tier]]

    entries = []
    for goal in goals:
        tier = args.tier or tiers.detect_tier(goal)
        if tier not in tiers.TIER_MODEL:
            print(f"tiiny_ctl: unknown tier {tier!r}. Valid: {', '.join(tiers.VALID_TIERS)}",
                  file=sys.stderr)
            return 2
        forced_model = None
        if args.model:
            forced_model = args.model
        chosen = None
        reason = ""
        for name in candidates(tier):
            if forced_model and name != forced_model:
                continue
            status = (index.get(name) or {}).get("status")
            if name in resident:
                chosen, reason = name, "resident"
                break
            if status in ("downloaded", "running"):
                chosen, reason = name, "downloaded"
                break
        if chosen is None:
            chosen = tiers.GENERALIST
            reason = "no downloadable candidate — the generalist"
        entries.append({
            "goal": goal,
            "tier": tier,
            "model": chosen,
            "npu": npu_of(chosen, index),
            "reason": reason,
        })

    # Waves: the device serves one generation-heavy stream at a time, and the
    # models of a wave must fit inside one shared NPU pool. A batch whose
    # models do not fit is split into waves, and each wave is a separate
    # delegation call.
    distinct: list[str] = []
    for entry in entries:
        if entry["model"] not in distinct:
            distinct.append(entry["model"])

    # First-fit decreasing, with the models that are already resident placed
    # first. Resident-first matters: a wave that loads a new specialist
    # evicts whatever does not fit, so keeping the already-loaded model in
    # the first wave saves a load and a reload. Ties break on the larger
    # model, because a large model is the one that constrains the packing.
    ordered = sorted(distinct, key=lambda m: (0 if m in resident else 1, -npu_of(m, index)))
    waves: list[list[str]] = []
    for model in ordered:
        share = npu_of(model, index)
        placed = False
        for wave in waves:
            if sum(npu_of(m, index) for m in wave) + share <= 100:
                wave.append(model)
                placed = True
                break
        if not placed:
            waves.append([model])

    for entry in entries:
        for number, wave in enumerate(waves, start=1):
            if entry["model"] in wave:
                entry["wave"] = number
                break

    payload = plan_write(entries, waves, args.owner or "unassigned", args.task or "")

    print(f"BATCH PLAN  {payload['batch']}")
    print(f"  owner: {payload['owner']}    task: {payload['task'] or '(none recorded)'}\n")
    print(f"  {'#':<3}{'tier':<10}{'model':<42}{'NPU':>5}  {'wave':<5}{'state'}")
    print(f"  {'-'*78}")
    for number, entry in enumerate(entries, start=1):
        print(f"  {number:<3}{entry['tier']:<10}{entry['model']:<42}"
              f"{entry['npu']:>4}%  {entry.get('wave', 1):<5}{entry['reason']}")

    print()
    for number, wave in enumerate(waves, start=1):
        share = sum(npu_of(m, index) for m in wave)
        fits = "fits" if share <= 100 else "DOES NOT FIT"
        evict, kept = ensure_room(wave, index)
        print(f"  WAVE {number}: {share}% NPU — {fits}")
        for model in wave:
            print(f"      {model}")
        if evict:
            print(f"      evicts to make room: {', '.join(evict)}")
        if kept:
            print(f"      stays alongside: {', '.join(kept)}")
        print("      (displacement is computed from the residency now; the")
        print("       controller re-decides it when it actually loads)")

    resident_share = sum(npu_of(m, index) for m in resident)
    batch_share = sum(npu_of(m, index) for m in distinct)
    displaced = [m for m in resident if m not in distinct]
    print(f"\n  batch models total : {batch_share}% NPU")
    print(f"  resident now       : {resident_share}% NPU across {len(resident)} models")
    if displaced:
        print(f"  may be displaced   : {', '.join(displaced)}")
        print("      (the watchdog restores the required set on release)")
    print("\n  The device serves one generation-heavy stream at a time: run one")
    print("  heavy child per wave, not every wave's children at once.")
    return 0


def cmd_reserve(args) -> int:
    payload, error = lock_acquire(args.owner, args.task or "", args.ttl, args.model or [])
    if payload is None:
        print(f"tiiny_ctl: cannot take the lock — {error}", file=sys.stderr)
        return 1

    held = ", ".join(args.model or []) or "(not decided yet)"
    text = (
        "**Tiiny is BUSY — do not schedule device work.**\n"
        f"Held by `{payload['owner']}` for {payload['task'] or 'an unnamed task'} "
        f"since {time.strftime('%H:%M:%S')}. Models: {held}. "
        f"Lock expires {time.strftime('%H:%M:%S', time.localtime(payload['expires']))}. "
        "This notice disappears when the device is released."
    )
    announced = announce_set(text)

    print(f"lock held by {payload['owner']} until "
          f"{time.strftime('%H:%M:%S', time.localtime(payload['expires']))}")
    print(f"  announcement: {'hot.md updated' if announced else 'hot.md not reachable — skipped'}")
    return 0


def cmd_load(args) -> int:
    # GUARD FIRST. A load is a swap on a device with one shared NPU pool, so
    # loading while another agent holds the device silently evicts whatever
    # that agent deliberately loaded. Check before touching anything.
    owner = args.owner or _caller_owner()
    holder = _lock_holder()
    if holder and _held_by_other(owner, holder) and not args.force:
        expires = float(holder.get("expires") or 0)
        print(f"tiiny_ctl: the device is held by {holder.get('owner')} "
              f"({holder.get('task') or 'no task recorded'}) until "
              f"{time.strftime('%H:%M:%S', time.localtime(expires))} — "
              f"refusing to load. Use --force if that is wrong.",
              file=sys.stderr)
        return 1

    models = list(args.model or [])
    if not models:
        plan = plan_read()
        if not plan:
            print("tiiny_ctl: no --model and no plan. Run 'plan' first.", file=sys.stderr)
            return 2
        waves = plan.get("waves") or []
        if args.wave:
            if args.wave < 1 or args.wave > len(waves):
                print(f"tiiny_ctl: wave {args.wave} is outside this plan "
                      f"(1..{len(waves)})", file=sys.stderr)
                return 2
            models = list(waves[args.wave - 1])
        else:
            models = [model for wave in waves for model in wave]

    if not models:
        print("tiiny_ctl: nothing to load", file=sys.stderr)
        return 2

    before = set(resident_ids())

    # Write the hold BEFORE loading. The watchdog can fire at any moment; if
    # it fires between the load and the hold, it evicts the model just loaded.
    hold_write(models)

    # Make room explicitly. When a load does not fit, the device picks what to
    # evict and it does not know what the batch needs — left to itself it
    # kept the 47% generalist and evicted the 27% model the wave had just
    # asked for. The controller decides what stays.
    index = {}
    try:
        index = catalogue_index()
    except SystemExit:
        pass
    evict, kept = ensure_room(models, index)
    for model in evict:
        print(f"  evicting {model} to make room for the wave", flush=True)
        cli_unload(model)
    if evict or kept:
        print(f"  staying alongside: {', '.join(kept) if kept else '(nothing)'}")

    for model in models:
        if model in resident_ids():
            print(f"  already resident: {model}")
            continue
        print(f"  loading {model} ...", flush=True)
        cli_load(model)

    after = set(resident_ids())
    missing = [m for m in models if m not in after]
    evicted = sorted(before - after)

    print(f"\n  loaded      : {', '.join(models)}")
    if missing:
        print(f"  NOT RESIDENT: {', '.join(missing)}")
    if evicted:
        print(f"  displaced   : {', '.join(evicted)}")
    print(f"  hold        : {', '.join(hold_state())}")

    if missing:
        print("\n  A model that did not land cannot answer: the device will return")
        print("  404 \"is not loaded\" and the child will fall back to the paid")
        print("  provider. Check that it is downloaded, and that its NPU share")
        print("  leaves room for what else the wave needs.", file=sys.stderr)
        return 1
    return 0


def cmd_release(args) -> int:
    # GUARD FIRST, and this used to be the whole bug.
    #
    # The old order was: clear the hold, restore the required set, THEN
    # check the lock. So another agent running `release` cleared the hold and
    # evicted the held model before it discovered the lock was not its own.
    # Worse, the old code defaulted the owner to the lock's current owner, so
    # a bare `release` adopted somebody else's lock and released it happily.
    #
    # Ownership is now checked before ANY mutation, and the owner is never
    # inherited from the lock.
    owner = args.owner or _caller_owner()
    holder = _lock_holder()
    if holder and _held_by_other(owner, holder) and not args.force:
        expires = float(holder.get("expires") or 0)
        print(f"tiiny_ctl: the device is held by {holder.get('owner')} "
              f"({holder.get('task') or 'no task recorded'}) until "
              f"{time.strftime('%H:%M:%S', time.localtime(expires))} — "
              f"refusing to release. Use --force if that is wrong.",
              file=sys.stderr)
        return 1

    # Restore the required set FIRST is wrong: the hold is what stops the
    # watchdog from fighting the restore. Clear it, then restore.
    hold_clear()
    print("hold cleared")

    resident = set(resident_ids())
    missing = [m for m in REQUIRED_MODELS if m not in resident]
    for model in missing:
        print(f"  restoring {model} ...", flush=True)
        cli_load(model)

    restored = set(resident_ids())
    still_missing = [m for m in REQUIRED_MODELS if m not in restored]
    if still_missing:
        print(f"  WARNING: still missing {', '.join(still_missing)}", file=sys.stderr)

    plan_clear()
    print("plan cleared")

    ok, error = lock_release(owner, force=args.force)
    print(f"lock released" if ok else f"lock NOT released — {error}")

    cleared = announce_clear()
    print(f"announcement: {'removed from hot.md' if cleared else 'nothing to remove'}")

    print(f"\nresident now: {', '.join(sorted(restored)) or '(none)'}")
    return 0 if ok and not still_missing else 1


def cmd_catalog(args) -> int:
    rows = catalogue()
    index = {row["id"]: row for row in rows if row.get("id")}
    current = {rid: row for rid, row in index.items()}

    previous = {}
    try:
        previous = json.loads(SNAPSHOT_FILE.read_text()).get("models", {})
    except Exception:
        previous = {}

    print(f"MODEL STORE: {len(current)} models\n")

    if not previous:
        print("  No snapshot to compare against. Run with --update to record one.")
        for row in rows:
            print(f"    {str(row.get('npu')):>4}%  {row.get('status'):<16} {row['id']}")
        return 0

    new = sorted(set(current) - set(previous))
    gone = sorted(set(previous) - set(current))
    changed = []
    for rid in sorted(set(current) & set(previous)):
        before, after = previous[rid], current[rid]
        for field in ("npu", "context", "status"):
            if before.get(field) != after.get(field):
                changed.append((rid, field, before.get(field), after.get(field)))
                break

    print(f"  snapshot had {len(previous)} models; the store has {len(current)}")
    if new:
        print(f"\n  NEW ({len(new)}):")
        for rid in new:
            row = current[rid]
            print(f"    + {rid}  [{row.get('type')}] {row.get('npu')}% NPU, "
                  f"status {row.get('status')}")
    if gone:
        print(f"\n  GONE ({len(gone)}):")
        for rid in gone:
            print(f"    - {rid}")
    if changed:
        print(f"\n  CHANGED ({len(changed)}):")
        for rid, field, before, after in changed:
            print(f"    ~ {rid}: {field} {before} -> {after}")
    if not (new or gone or changed):
        print("\n  Nothing changed.")

    tier_models = {name for choices in tiers.TIER_CHOICES.values() for name, _n, _c in choices}
    tier_drift = [rid for rid, *_ in changed if rid in tier_models]
    if tier_drift:
        print(f"\n  The tier table quotes figures for these models, which just changed:")
        for rid in tier_drift:
            print(f"    - {rid}")

    if args.update:
        SNAPSHOT_FILE.write_text(json.dumps({
            "source": MANAGEMENT_BASE + "/api/v1/models/online_models",
            "read": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model_count": len(current),
            "models": current,
        }, indent=1))
        print(f"\n  snapshot written to {SNAPSHOT_FILE}")

    return 0


def cmd_image(args) -> int:
    kind = args.kind
    model, reason = tiers.pick_special_model(args.description, kind)
    index = catalogue_index()
    row = index.get(model) or {}

    print(f"IMAGE MODEL for: {args.description}\n")
    print(f"  pick    : {model}")
    print(f"  reason  : {reason}")
    print(f"  role    : {tiers.SPECIAL_MODELS.get(model, (0, '', 'n/a', ''))[2]}")
    print(f"  NPU     : {row.get('npu', tiers.model_npu(model))}%")
    print(f"  state   : {row.get('status', 'unknown')}"
          f"{' — RESIDENT' if model in resident_ids() else ''}")
    if model in tiers.KNOWN_GOOD_SIZES:
        print(f"  sizes   : {', '.join(tiers.KNOWN_GOOD_SIZES[model])}")

    alternatives = [
        rid for rid, entry in tiers.SPECIAL_MODELS.items()
        if entry[1] == kind and rid != model
    ]
    if alternatives:
        print("\n  other candidates for this kind:")
        for rid in alternatives:
            status = (index.get(rid) or {}).get("status", "?")
            npu = (index.get(rid) or {}).get("npu", tiers.model_npu(rid))
            note = "" if status in ("downloaded", "running") else "  (not downloaded — download it first)"
            print(f"    {rid}  {npu}% NPU, {status}{note}")

    if args.load:
        print()
        hold_write([model])
        if model not in resident_ids():
            print(f"  loading {model} ...", flush=True)
            cli_load(model)
        if model in resident_ids():
            print(f"  loaded and resident. Release with 'tiiny_ctl.py release'.")
            return 0
        print("  the model did not land", file=sys.stderr)
        return 1
    return 0


# --- entry point ------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Control the Tiiny device: plan, lock, load, release, refresh.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="device, resident set, lock, hold, plan")

    plan = sub.add_parser("plan", help="pick models, check the NPU fit, write the plan")
    plan.add_argument("--goal", action="append", help="a task goal; repeat for a batch")
    plan.add_argument("--tier", choices=tiers.VALID_TIERS, help="force one tier for every goal")
    plan.add_argument("--model", help="force one model for every goal")
    plan.add_argument("--owner", default=os.environ.get("TIINY_OWNER", ""), help="who is planning")
    plan.add_argument("--task", default="", help="what the batch is for")

    reserve = sub.add_parser("reserve", help="take the cross-agent lock")
    reserve.add_argument("--owner", required=True, help="who is taking the device")
    reserve.add_argument("--task", default="", help="what it is for")
    reserve.add_argument("--model", action="append", help="a model the batch needs")
    reserve.add_argument("--ttl", type=int, default=DEFAULT_TTL, help="lock lifetime in seconds")

    load = sub.add_parser("load", help="load what the batch needs")
    load.add_argument("--model", action="append", help="a model to load")
    load.add_argument("--wave", type=int, help="load only this wave of the plan")
    load.add_argument("--owner", default=os.environ.get("TIINY_OWNER", ""),
                      help="who is loading; defaults to the active profile")
    load.add_argument("--force", action="store_true",
                      help="load even if another agent holds the device")

    release = sub.add_parser("release", help="restore the device and clear the lock")
    release.add_argument("--owner", default=os.environ.get("TIINY_OWNER", ""),
                         help="who is releasing; defaults to the active profile")
    release.add_argument("--force", action="store_true", help="release a lock held by someone else")

    catalog = sub.add_parser("catalog", help="diff the live Model Store against the snapshot")
    catalog.add_argument("--update", action="store_true", help="record the snapshot")
    catalog.add_argument("--refresh", action="store_true", help="refresh and record in one step")

    image = sub.add_parser("image", help="pick the right image model for a job")
    image.add_argument("description", help="what the image is for")
    image.add_argument("--kind", default="image", choices=sorted(tiers.SPECIAL_DEFAULTS))
    image.add_argument("--load", action="store_true", help="load the chosen model")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 2

    if args.command == "status":
        return cmd_status(args)
    if args.command == "plan":
        return cmd_plan(args)
    if args.command == "reserve":
        return cmd_reserve(args)
    if args.command == "load":
        return cmd_load(args)
    if args.command == "release":
        return cmd_release(args)
    if args.command == "catalog":
        if args.refresh:
            args.update = True
        return cmd_catalog(args)
    if args.command == "image":
        return cmd_image(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
