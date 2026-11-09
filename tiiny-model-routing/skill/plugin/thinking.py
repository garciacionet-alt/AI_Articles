"""Reasoning-mode control for the Tiiny routing backend.

The device publishes what each model can do with reasoning. It is read from
the device **at route time** rather than kept in the tier table, because the
Model Store changes with every TiinyOS update and a hand-maintained table
goes stale quietly — a table that says a model reasons when it no longer does
is worse than no table, because it is believed.

Two endpoints carry the capability:

``GET /v1/models``
    Every model that is resident, with a ``thinking`` block. Small, and it is
    the same read the router already makes for residency.

``GET /api/v1/models/online_models``
    Every model in the store, with the same ``thinking`` block. Large — the
    entries carry full descriptions — so it is only read when a model that is
    not resident has to be resolved.

The block looks like this::

    "thinking": {
        "supported": true,            # the model can reason at all
        "toggleable": true,           # a boolean on/off switch exists
        "levels": [],                 # named reasoning levels, when it has any
        "enabled_by_default": true,
        "default_level": null,
    }

Two controls reach the device, and they are not interchangeable
------------------------------------------------------------
``extra_body.chat_template_kwargs.enable_thinking``
    A boolean, passed through the chat template. This is the decisive
    control where the model honours it: the reasoning trace disappears and
    the answer comes straight back.

``reasoning_effort`` at the top level of the request
    A named level, read by the inference server itself rather than by the
    model's chat template. This is the control for a model whose chat
    template has no boolean switch — and it is the *only* control for that
    model, because the boolean is ignored outright.

The same level name inside ``chat_template_kwargs`` is a **different** knob
that only some chat templates read. Putting the level there works on one
model family and is silently ignored by another, which is worse than not
sending it: the route looks configured and the model does not change.

The device's own ``toggleable`` flag is a **hint, not ground truth**. One
model on this device is flagged non-toggleable and honours
``enable_thinking: false`` perfectly well. So the boolean is sent whenever it
can be sent, and the level is sent alongside it when the device says the
boolean will not move this model. Which control actually took effect is
reported in the route's label, so the operator sees the achieved state and
not the requested one.

What "off" means when the model cannot be turned off
----------------------------------------------------
Some models have no working switch. For those, "off" is not a refusal and
not a pretence: it means **the cheapest state the model offers**. That is the
lowest reasoning level it declares. The model still reasons — it just
reasons less — and the label says so (``off→low``) rather than claiming a
switch that does not exist.

What this module will not do is guess. If the device does not report a
model's capability, nothing is applied and the label says ``unknown``: the
model's native behaviour is a known quantity, an invented one is not.

Nothing here mutates the device. It reads, and it computes.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Mapping

#: The device's OpenAI-compatible endpoint. Local, on the LAN.
TIINY_BASE_URL = os.environ.get("TIINY_BASE_URL", "http://openai.api.tiiny/v1").rstrip("/")

#: The device's management host. Serves the full Model Store catalogue.
TIINY_HOST = os.environ.get("TIINY_HOST", "http://tiinyhost.local").rstrip("/")

#: Reasoning levels, cheapest first. Used only to pick the cheapest and the
#: most expensive level out of the ones a model declares. A level the device
#: does not name here still sorts — it just sorts after the named ones.
LEVEL_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh")

#: The smallest output budget a reasoning model can finish inside.
#:
#: A reasoning model spends its budget on the trace first. With a small
#: budget the request comes back HTTP 200 with an **empty** answer and the
#: budget gone — a silent failure that looks like the model produced nothing.
#: The floor is the budget children run with by default.
THINKING_MAX_TOKENS = 4096

#: How long a reasoning-capability lookup is reused, in seconds. The Model
#: Store changes on a TiinyOS update, not on a heartbeat, so a long cache is
#: safe and keeps the routing path cheap.
CAPABILITY_TTL = 900

#: Cached capability lookup for resident models: (timestamp, {id: capability}).
_capability_cache: tuple[float, dict[str, dict[str, Any]]] | None = None

#: Cached capability lookup for the whole store: (timestamp, {id: capability}).
_catalogue_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


def device_key() -> str:
    """Return the device API key, or an empty string if it cannot be found.

    Hermes keeps its secrets in ``~/.hermes/.env`` and resolves them through
    its own accessor — they are **not** in the process environment. Reading
    ``os.environ`` alone therefore finds nothing, and the router would
    silently fail open on every call. Read it the way Hermes reads it, fall
    back to the environment, and fall back to the dotenv file itself so the
    standalone checker works outside Hermes.
    """
    value = ""
    try:
        from hermes_cli.config import get_env_value_prefer_dotenv

        value = get_env_value_prefer_dotenv("TIINY_API_KEY") or ""
    except Exception:
        value = ""
    value = (value or os.environ.get("TIINY_API_KEY", "") or "").strip()
    if value:
        return value
    try:
        path = os.path.expanduser("~/.hermes/.env")
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("TIINY_API_KEY"):
                    _, _, raw = line.partition("=")
                    return raw.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _read_json(url: str, key: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _entries(payload: Any) -> list[dict[str, Any]]:
    """Return the list of model entries in a catalogue response."""
    items = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(items, dict):
        items = items.get("models") or items.get("data") or []
    if not isinstance(items, list):
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _capability_of(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise one catalogue entry into a capability record."""
    thinking = entry.get("thinking")
    thinking = thinking if isinstance(thinking, Mapping) else {}
    levels = thinking.get("levels") or entry.get("reasoning_levels") or []
    if not isinstance(levels, list):
        levels = []
    return {
        "supported": bool(thinking.get("supported")),
        "toggleable": bool(thinking.get("toggleable")),
        "levels": [str(level) for level in levels if isinstance(level, str)],
        "enabled_by_default": bool(thinking.get("enabled_by_default")),
        "default_level": thinking.get("default_level"),
    }


def _model_id(entry: Mapping[str, Any]) -> str:
    for key in ("model_id", "id", "fullname", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _resident_capabilities(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return the capability of every resident model."""
    global _capability_cache
    now = time.monotonic()
    if not refresh and _capability_cache is not None:
        if now - _capability_cache[0] < CAPABILITY_TTL:
            return _capability_cache[1]

    key = device_key()
    caps: dict[str, dict[str, Any]] = {}
    if key:
        try:
            payload = _read_json(TIINY_BASE_URL + "/models", key, 3.0)
            for entry in _entries(payload):
                model_id = entry.get("id") or _model_id(entry)
                if isinstance(model_id, str) and model_id:
                    caps[model_id] = _capability_of(entry)
        except Exception:
            caps = {}

    _capability_cache = (now, caps)
    return caps


def _catalogue_capabilities(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return the capability of every model in the store.

    The catalogue entries carry full descriptions, so this is a heavy read.
    It is only made when a model that is not resident has to be resolved, and
    the answer is cached for ``CAPABILITY_TTL``.
    """
    global _catalogue_cache
    now = time.monotonic()
    if not refresh and _catalogue_cache is not None:
        if now - _catalogue_cache[0] < CAPABILITY_TTL:
            return _catalogue_cache[1]

    key = device_key()
    caps: dict[str, dict[str, Any]] = {}
    if key:
        try:
            payload = _read_json(TIINY_HOST + "/api/v1/models/online_models", key, 20.0)
            for entry in _entries(payload):
                model_id = _model_id(entry)
                if model_id:
                    caps.setdefault(model_id, _capability_of(entry))
        except Exception:
            caps = {}

    _catalogue_cache = (now, caps)
    return caps


def thinking_capability(model: str) -> dict[str, Any] | None:
    """Return what the device says about a model's reasoning, or ``None``.

    ``None`` means the device did not say — it was unreachable, or it does not
    publish this model. The caller then applies nothing.
    """
    if not model:
        return None
    capability = _resident_capabilities().get(model)
    if capability is not None:
        return capability
    return _catalogue_capabilities().get(model)


def _pick_level(levels: list[str], *, cheapest: bool) -> str | None:
    """Return the cheapest or the most expensive of a model's levels."""
    if not levels:
        return None
    ranked = sorted(
        levels,
        key=lambda level: (
            LEVEL_ORDER.index(level) if level in LEVEL_ORDER else len(LEVEL_ORDER),
            levels.index(level),
        ),
    )
    return ranked[0] if cheapest else ranked[-1]


def resolve_thinking(
    model: str,
    requested: str,
    *,
    max_tokens_floor: int = THINKING_MAX_TOKENS,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a requested thinking mode against what the model can do.

    Returns ``(request_overrides or None, achieved state)``.

    The achieved state is what the route reports, and it is deliberately not
    the requested one:

    ``auto``
        Nothing was applied. The model keeps its native behaviour.
    ``on`` / ``off``
        The boolean switch was applied and is the control.
    ``on→high`` / ``off→low``
        The model has no working boolean switch, so the named level was
        applied instead — the most expensive one for ``on``, the cheapest for
        ``off``. The model still reasons; it just reasons less.
    ``unsupported``
        The model does not reason at all, so ``on`` is not a thing that can
        happen.
    ``unknown``
        The device did not report this model, so nothing was applied.
    """
    requested = (requested or "auto").strip().lower()
    if requested not in ("auto", "on", "off"):
        raise ValueError(
            f"Unknown thinking mode {requested!r}. Valid modes are: auto, on, off."
        )

    if requested == "auto":
        return None, "auto"

    capability = thinking_capability(model)
    if capability is None:
        return None, "unknown"

    if not capability["supported"]:
        # The model does not reason at all. "on" cannot happen; "off" is
        # already the truth.
        return None, ("unsupported" if requested == "on" else "off")

    levels = capability["levels"]
    template_kwargs: dict[str, Any] = {"enable_thinking": requested == "on"}

    overrides: dict[str, Any] = {
        "extra_body": {"chat_template_kwargs": template_kwargs},
    }

    level: str | None = None
    if levels and not capability["toggleable"]:
        # The device says the boolean cannot move this model, so the level is
        # the control that works. It goes at the top level of the request,
        # where the inference server reads it — inside
        # ``chat_template_kwargs`` it would be ignored.
        level = _pick_level(levels, cheapest=(requested == "off"))
        if level:
            overrides["reasoning_effort"] = level

    # The floor is needed whenever the model reasons at all — including in the
    # "off" state, because a model whose boolean switch does not work still
    # produces a trace.
    if isinstance(max_tokens_floor, int) and max_tokens_floor > 0:
        overrides["max_tokens"] = max_tokens_floor

    if level:
        # The level is the effective control, so the label reports it.
        achieved = f"{requested}→{level}"
    else:
        achieved = requested

    return overrides, achieved


def describe_capability(model: str) -> str:
    """Return a one-line description of a model's reasoning capability."""
    capability = thinking_capability(model)
    if capability is None:
        return "unknown (the device did not report this model)"
    if not capability["supported"]:
        return "no reasoning"
    levels = capability["levels"]
    if levels and not capability["toggleable"]:
        return f"levels only ({', '.join(levels)}) — the on/off switch is ignored"
    if levels:
        return f"on/off switch, levels {', '.join(levels)}"
    return "on/off switch"
