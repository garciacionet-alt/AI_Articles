"""Tiiny routing delegation backend (``delegation.backend: tiiny-router``).

Routes each ``delegate_task`` subtask to the Tiiny model that suits its shape,
instead of sending every subtask to one pinned model.

Why a backend rather than a config value
----------------------------------------
``delegation.model`` pins ONE model for every child. That is the right default
when every subtask is the same kind of work. It is the wrong default when a
single delegation batch mixes a web-research sweep, a filesystem index, a
terminal code edit, and a browser-automation run: the cheap subtasks pay for
the expensive model's context, and the expensive subtask gets a model that is
not specialised for it.

A backend solves that at the routing layer. ``route_task`` is called once per
task with that task's goal and context, and returns the model, provider, and
request overrides for that subtask alone.

Routing is by task shape, not by keyword
-----------------------------------------
The route is chosen from the task's *shape* — what kind of work it is — because
shape is what predicts which model does well. A goal that mentions "index the
vault" is an indexing job; a goal that says "refactor these three modules" is
a coding job. Matching on keywords in the prompt is brittle in a different way:
a research task about code will match code keywords and get the coder.

The shape is read from the goal text, with the explicit ``tier`` parameter as
an override. When neither gives a confident answer, the task goes to the
generalist, which is the right default: it is the model that is good at
everything in the catalogue and mediocre at each, and being wrong about a
specialist is more expensive than being mediocre at a general task.

The router chooses; the lifecycle loads
---------------------------------------
**This plugin never loads, unloads, or otherwise mutates the device.** That is
not caution, it is a division of labour: the device's resident set is a
*shared, finite* resource, and a load is a swap that evicts whatever was
resident.

The loading half lives in ``scripts/tiiny_ctl.py``, which the manager agent
drives explicitly: plan the batch, take the cross-agent lock, load what the
batch needs, delegate, then release. Between those two calls the router and
the controller agree on one file — the **plan** (``~/.hermes/tiiny-plan.json``).

The plan is what makes the two halves agree. When the controller has loaded a
specialist for a batch, the plan records which model it assigned to which
goal, and this plugin routes that goal to that model. Without the plan the
router falls back to the residency-only rule below, which is safe but cannot
use a specialist that is not loaded yet.

The two halves therefore compose like this:

    controller: plan -> reserve -> load      |  plugin: route_task
    controller: release                      |  child runs on the plan's model

Residency is read, never changed
--------------------------------
The plugin does read the device's resident set, and it uses it. A model that
is not resident cannot answer — the device replies ``404 "is not loaded"``,
which Hermes classifies as terminal and falls back to the paid provider. On a
device whose shared NPU pool holds only a few models at a time, that turns a
routing decision into a silent move off the local device.

So the router picks a model that is actually resident when it can: the plan's
assignment if there is one, then the tier's own first choice, then another
candidate from the same tier, then the generalist the watchdog keeps resident.
The label on the route records any substitution (``code→generalist``), so the
operator can see that the specialist was not available. When residency cannot
be determined at all the router behaves exactly as it did before: the tier's
first choice.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider, DelegationRouteError

#: The shared tier table. Loaded by path — see the note in ``tiers.py`` for
#: why a relative import would break under the Hermes plugin loader.
_TIERS_PATH = Path(__file__).resolve().parent / "tiers.py"
_spec = importlib.util.spec_from_file_location("tiiny_router_tiers", _TIERS_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - packaging error
    raise ImportError(f"could not load the tier table from {_TIERS_PATH}")
tiers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tiers)

TIER_CHOICES = tiers.TIER_CHOICES
TIER_MODEL = tiers.TIER_MODEL
VALID_TIERS = tiers.VALID_TIERS
GENERALIST = tiers.GENERALIST
SHAPE_SIGNALS = tiers.SHAPE_SIGNALS
detect_tier = tiers.detect_tier

#: The device's OpenAI-compatible endpoint. Local, on the LAN.
TIINY_BASE_URL = tiers.TIINY_BASE_URL

#: Provider name as configured in ``providers:`` in config.yaml.
TIINY_PROVIDER = tiers.TIINY_PROVIDER

#: How long a residency lookup is reused, in seconds. The device's resident
#: set changes on a swap, not on a heartbeat, so a short cache is enough and
#: keeps the routing path cheap.
RESIDENCY_TTL = 30

#: Cached residency lookup: (monotonic timestamp, frozenset of model ids).
_residency_cache: tuple[float, frozenset[str]] | None = None

#: The plan the lifecycle controller writes. It lives in the BASE Hermes home
#: on purpose: every profile's manager agent must see the same plan, and the
#: base home is what they share.
PLAN_FILE = Path(
    os.environ.get("TIINY_PLAN_FILE", "~/.hermes/tiiny-plan.json")
).expanduser()


def device_key() -> str:
    """Return the device API key, or an empty string if it cannot be found.

    Hermes keeps its secrets in ``~/.hermes/.env`` and resolves them through
    its own accessor — they are **not** in the process environment. Reading
    ``os.environ`` alone therefore finds nothing, and the router would
    silently fail open on every call, which is exactly the failure this
    lookup exists to prevent. Read it the way Hermes reads it, and fall back
    to the environment for a shell that exported it.
    """
    value = ""
    try:
        from hermes_cli.config import get_env_value_prefer_dotenv

        value = get_env_value_prefer_dotenv("TIINY_API_KEY") or ""
    except Exception:
        value = ""
    return (value or os.environ.get("TIINY_API_KEY", "") or "").strip()


def resident_models() -> frozenset[str] | None:
    """Return the model ids currently resident on the device.

    Returns ``None`` when residency cannot be determined — the device is
    offline, the key is missing, or the lookup timed out. The caller then
    falls back to the tier's default choice, which is exactly the behaviour
    from before residency was considered. This path must never raise: a
    routing decision is not a place to fail.
    """
    global _residency_cache
    now = time.monotonic()
    if _residency_cache is not None and now - _residency_cache[0] < RESIDENCY_TTL:
        return _residency_cache[1]

    key = device_key()
    if not key:
        return None
    try:
        request = urllib.request.Request(
            TIINY_BASE_URL + "/models",
            headers={"Authorization": "Bearer " + key},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
    except Exception:
        return None

    ids: set[str] = set()
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("id")
        if isinstance(value, str) and "/" in value:
            ids.add(value)
    resident = frozenset(ids)
    _residency_cache = (now, resident)
    return resident


def _normalise_goal(goal: str) -> str:
    """Collapse whitespace so a goal survives a copy-paste with different spacing."""
    return " ".join((goal or "").split())


def planned_models() -> dict[str, str]:
    """Return the plan's ``goal -> model`` assignments, or an empty mapping.

    The plan is written by ``scripts/tiiny_ctl.py plan`` and lives at
    ``~/.hermes/tiiny-plan.json``. A missing, unreadable or malformed plan is
    not an error: it simply means the lifecycle did not run, and the router
    falls back to the residency-only rule. Routing must never fail because a
    sidecar file is wrong.
    """
    try:
        payload = json.loads(PLAN_FILE.read_text())
    except Exception:
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {}
    planned: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        goal = entry.get("goal")
        model = entry.get("model")
        if isinstance(goal, str) and isinstance(model, str) and goal and model:
            planned[_normalise_goal(goal)] = model
    return planned


def choose_model(tier: str, goal: str = "") -> tuple[str, str]:
    """Pick the model for a task and say how it was picked.

    Returns ``(model, label)``.

    The order is: the plan's assignment for this goal, if there is one and
    its model is resident; then the tier's own first choice if it is
    resident; then any other candidate in the tier that is resident; then the
    generalist, if it is resident; then the tier's first choice regardless.

    The point of the later steps is that a model which is not resident cannot
    answer — the device answers ``404 "is not loaded"``, which Hermes treats as
    terminal and falls back to the paid provider. On a device whose NPU pool
    holds only a few models at a time, routing to a specialist that is not
    loaded would quietly move the work off the device. Preferring a resident
    model keeps the work local, and the label records the substitution so the
    operator can see it happened.
    """
    choices = TIER_CHOICES[tier]
    default_model = choices[0][0]

    resident = resident_models()
    plan = planned_models()
    planned = plan.get(_normalise_goal(goal)) if goal else None

    # The plan wins, but only if what it names is actually there. A plan is a
    # promise about the device's state, and the device is the authority: if
    # the planned model is gone, something evicted it and the plan is stale.
    if planned and (resident is None or planned in resident):
        if planned == default_model:
            return planned, tier
        return planned, f"{tier}→{planned.split('/')[-1]}"

    if resident is None:
        # Residency unknown — behave exactly as before.
        return default_model, tier

    for model, _npu, _ctx in choices:
        if model in resident:
            if model == default_model:
                return model, tier
            return model, f"{tier}→{model.split('/')[-1]}"

    if GENERALIST in resident:
        return GENERALIST, f"{tier}→generalist"

    return default_model, tier


class TiinyRouterDelegationProvider(DelegationProvider):
    """Route each subtask to the Tiiny model that fits its shape."""

    @property
    def name(self) -> str:
        return "tiiny-router"

    @property
    def display_name(self) -> str:
        return "Tiiny Router"

    @property
    def summary(self) -> str:
        return ("Route each subtask to the Tiiny model that matches its shape: "
                "research, index, code, browser, draft, general.")

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "tier": {
                "type": "string",
                "enum": list(VALID_TIERS),
                "description": (
                    "Force a routing tier for this task instead of inferring it from the goal. "
                    "Use when the goal understates the work: a task that says 'read these logs' "
                    "but means 'summarise what went wrong' is a 'draft' task, not a 'general' one."
                ),
            },
        }

    def description(self, config: Mapping[str, Any]) -> str:
        return (
            "Set 'tier' on a task to force a model: " + ", ".join(VALID_TIERS) + ". "
            "When tier is omitted the model is inferred from the task's shape, so name the "
            "work honestly ('index every file under X') and the cheap specialist gets it."
        )

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        goal = str(task.get("goal") or "")
        forced = task.get("tier")

        if forced:
            tier = str(forced)
            if tier not in TIER_MODEL:
                raise DelegationRouteError(
                    f"Unknown tier {tier!r}. Valid tiers are: {', '.join(VALID_TIERS)}."
                )
        else:
            tier = detect_tier(goal)

        model, label = choose_model(tier, goal)

        # Return the delegation section's own shape and override only the
        # model — the way the default backend returns ``dict(config)``.
        #
        # This is not cosmetic. Hermes resolves a route's credentials from
        # ``base_url`` / ``api_key`` / ``provider``:
        #
        #   * ``base_url`` set, ``api_key`` empty -> a direct endpoint, and
        #     ``api_key`` None means INHERIT THE PARENT'S KEY. The parent runs
        #     on the paid provider, so the device would receive the wrong
        #     bearer and answer ``401 auth_failed`` — and the child would fall
        #     back to the paid provider, invisibly.
        #   * ``base_url`` empty, ``provider`` set -> the runtime provider
        #     system, which resolves the device's ``key_env`` correctly.
        #
        # The default backend lives on the second branch. Returning the
        # section's shape puts this backend on it too, so the device key is
        # the device key.
        route = {k: v for k, v in config.items() if k != "service_tier"}
        route["model"] = model
        route["label"] = label
        return route


def register(ctx) -> None:
    ctx.register_delegation_provider(TiinyRouterDelegationProvider())
