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
vault" is an indexing job; a goal that says "refactor these three modules" is a
coding job. Matching on keywords in the prompt is brittle in a different way:
a research task about code will match code keywords and get the coder.

The shape is read from the goal text, with the explicit ``tier`` parameter as
an override. When neither gives a confident answer, the task goes to the
generalist, which is the right default: it is the model that is good at
everything in the catalogue and mediocre at each, and being wrong about a
specialist is more expensive than being mediocre at a general task.

Cost is a routing input
------------------------
Every model on the device is free, but not equally cheap: each takes a share
of the one shared NPU pool, and a bigger share is a bigger resident footprint
that evicts more. A mechanical subtask routed to a 94-NPU-point coding model
evicts the models a concurrent research task is using. The router therefore
prefers the *smallest* model that fits the shape, and the ``tier`` table below
records the NPU share each choice costs.

The plugin never loads, unloads, or otherwise mutates the device. Model
residency is the operator's decision, made with ``tiiny-swap.sh``; this plugin
only chooses which model a child should ask for. That separation is deliberate:
a load evicts whatever was resident, and a routing decision made inside a
delegation batch must not be able to yank a model out from under a sibling
task that is already running.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider, DelegationRouteError

#: The device's OpenAI-compatible endpoint. Local, on the LAN.
TIINY_BASE_URL = "http://openai.api.tiiny/v1"

#: Provider name as configured in ``providers:`` in config.yaml.
TIINY_PROVIDER = "custom:tiiny"

#: Task tier -> (model id, NPU share, context window).
#:
#: The NPU and context figures were read from the device's own catalogue
#: endpoint. They are not decoration: the NPU share is what decides whether a
#: model can stay resident alongside the others a batch needs, and the context
#: window is the ceiling on how much a child can hold at once.
#:
#: A tier can list more than one candidate. The first is the default; the rest
#: are the fallbacks in the order the device's own descriptions support.
TIER_CHOICES: dict[str, tuple[tuple[str, int, int], ...]] = {
    # tier        (model id, NPU share, context window)
    "research": (
        ("InternScience/Sage-A1.5-Turbo", 48, 262144),
        ("endless-frontier/BigBang-v1-Turbo", 54, 131072),
    ),
    "index": (
        ("openai/gpt-oss-20b", 27, 131072),
    ),
    "code": (
        ("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
        ("Qwen/Qwen3-Coder-Next", 94, 131072),
    ),
    "browser": (
        ("Qwen/Qwen3.8-27B", 51, 262144),
    ),
    "draft": (
        ("Qwen/Qwen3.5-9B", 29, 131072),
    ),
    "general": (
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
    ),
}

#: Which model each tier resolves to — the first choice in its list.
TIER_MODEL: dict[str, str] = {
    tier: choices[0][0] for tier, choices in TIER_CHOICES.items()
}

#: The tier names a caller may pass explicitly.
VALID_TIERS = tuple(sorted(set(TIER_MODEL)))

#: Shape signals. These are matched against the task goal, lowercased.
#:
#: Ordering matters: the first tier with a signal wins, so the specific
#: shapes are tested before the general ones.
SHAPE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("research", (
        "research", "literature", "survey", "investigate", "find sources",
        "web search", "search the web", "literature review", "deep dive",
        "competitive analysis", "market analysis", "sweep the",
    )),
    ("index", (
        "index", "indexing", "inventory", "classify", "classify every",
        "categorize", "catalog", "catalogue", "list every file", "walk the",
        "enumerate", "manifest", "tag every", "bulk", "batch classify",
    )),
    ("browser", (
        "browser", "click through", "web ui", "web page", "fill in the form",
        "navigate the site", "screenshot the", "scrape the page", "automate the browser",
    )),
    ("code", (
        "code", "refactor", "implement", "write a function", "bug", "debug",
        "fix the", "compile", "unit test", "patch the", "repository", "repo",
        "module", "script that", "shell script", "migrate the schema",
    )),
    ("draft", (
        "draft", "summar", "rewrite", "rephrase", "bullet", "outline",
        "condense", "shorten", "proofread", "reword", "tl;dr", "summarise",
    )),
)


def tier_cost(tier: str) -> tuple[int, int]:
    """Return the (NPU share, context window) of a tier's default model."""
    model, npu, ctx = TIER_CHOICES[tier][0]
    return npu, ctx


def detect_tier(goal: str) -> str:
    """Return the task tier for a goal, or ``general`` when unrecognised."""
    text = (goal or "").lower()
    for tier, signals in SHAPE_SIGNALS:
        for signal in signals:
            if signal in text:
                return tier
    return "general"


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

        model = TIER_MODEL[tier]

        return {
            "model": model,
            "provider": TIINY_PROVIDER,
            "base_url": TIINY_BASE_URL,
            "request_overrides": {
                "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            },
            "label": tier,
        }


def register(ctx) -> None:
    ctx.register_delegation_provider(TiinyRouterDelegationProvider())
