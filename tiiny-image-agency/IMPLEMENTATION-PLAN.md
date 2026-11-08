---
title: Tiiny Image Agency — Implementation Plan
type: plan
status: active
project: tiiny-image-agency
updated: 2026-11-05
---

# Tiiny Image Agency — Implementation Plan

> **For Hermes:** execute with `subagent-driven-development`. Every task is
> dispatched to a fresh subagent running on the Tiiny Coder model, then
> reviewed twice — spec compliance first, code quality second.

**Goal:** Build an application that plans, generates, and iterates images on a
local Tiiny Pocket Lab, exposing that capability through an API that agents
like Hermes can use, and managing the device's NPU residency so it never
silently breaks.

**Architecture:** A pure-function core (resolver, dialect translator) that
decides *what* to do, wrapped by an impure shell (device adapter, residency
manager, orchestrator) that does it. The device adapter is the only place
the bearer token exists. Every long operation is a job with an event stream,
because a generation takes 54–202 seconds and the device serves one stream at
a time.

**Tech stack:** Python 3.11, FastAPI, uvicorn, pydantic v2, pytest, httpx.
Frontend: one HTML file, vanilla JS, SSE. No build step.

---

## The facts this build is built on

Every number below was measured on the device on 2026-11-05. Full detail in
`MEASUREMENTS.md`.

| Fact | Value |
|---|---|
| NPU pool | 47.9 GiB, one shared budget. A model load is a **swap** |
| Admission vs execution | 81% → generation works. 85% → generation **fails** with 500 / 150004 |
| Co-resident with the 55% planner | 26% image models — **generation confirmed working, 54.5 s** |
| Flagship `Qwen-Image-2.1` (62%) | must run **alone** — ~200 s, the only native-RGBA model |
| Model load time | 10–56 s |
| Prefill | ~800 tok/s; prefix cache gives a 69× speedup on a repeated prompt |
| `npu_usage` | a device-assigned weight, **not** derivable from model size (r = −0.246) |

**Design consequences that are not optional:**

1. **Two budgets, not one.** The resolver must know what *fits* and what can
   *run*. A model set can be admitted and still fail the diffusion pass.
2. **The conversation model loads *after* the generation**, never beside the
   flagship. 62% + 27% = 89% is admitted and then fails.
3. **The hold file is written before the load**, and the watchdog's `flock` is
   held for the whole swap. The watchdog is a separate cron job that will
   otherwise evict a deliberate load mid-generation.
4. **The bearer is device-admin grade.** It lives in one adapter, never in a
   response, a log, a browser payload, or a document.

---

## Phase A — Foundation: the pure core

Everything in this phase is a pure function. It has no I/O, no device, no
network — which is what makes it testable in milliseconds instead of hours.

### Task A1 — Package skeleton and config

**Files:**
- Create: `app/pyproject.toml`
- Create: `app/src/tis/__init__.py`
- Create: `app/src/tis/config.py`
- Test: `app/tests/test_config.py`

```python
# app/src/tis/config.py
"""Paths and runtime settings. The bearer is read here and nowhere else."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "http://openai.api.tiiny"
INFERENCE_SUFFIX = "/v1"


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    planner_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"
    planner_npu_pct: int = 55
    registry_path: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "registry" / "image-models.json")
    assets_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "assets")
    hold_file: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.hermes/tiiny-hold")))
    watchdog_lock: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.hermes/tiiny-watch.lock")))
    tiiny_bin: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.local/tiiny/bin/tiiny")))

    @property
    def inference_base(self) -> str:
        return self.base_url.rstrip("/") + INFERENCE_SUFFIX


def load_settings() -> Settings:
    """Build settings from the environment. Never raises on a missing key —
    the adapter reports the auth failure at call time, not at import time."""
    key = os.environ.get("TIINY_API_KEY", "")
    return Settings(api_key=key)
```

**Step 1 — Write failing test** in `app/tests/test_config.py`:

```python
from tis.config import Settings, load_settings


def test_inference_base_appends_v1():
    assert Settings(base_url="http://openai.api.tiiny").inference_base == \
        "http://openai.api.tiiny/v1"


def test_inference_base_does_not_double_v1():
    assert Settings(base_url="http://openai.api.tiiny/v1").inference_base == \
        "http://openai.api.tiiny/v1"


def test_load_settings_reads_key(monkeypatch):
    monkeypatch.setenv("TIINY_API_KEY", "secret")
    assert load_settings().api_key == "secret"


def test_load_settings_without_key_is_empty(monkeypatch):
    monkeypatch.delenv("TIINY_API_KEY", raising=False)
    assert load_settings().api_key == ""
```

**Step 2 — Run, verify FAIL.** `cd app && python3 -m pytest tests/test_config.py -v`
**Step 3 — Implement** as above.
**Step 4 — Run, verify PASS** (4 passed).
**Step 5 — Commit** `feat(config): package skeleton and settings`.

### Task A2 — The data model

**Files:**
- Create: `app/src/tis/models.py`
- Test: `app/tests/test_models.py`

```python
# app/src/tis/models.py
"""The contracts. A requirement vector is what the LLM produces; a resolution
is what the deterministic resolver produces from it."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Artifact(str, Enum):
    ICON = "icon"
    ILLUSTRATION = "illustration"
    PHOTO = "photo"
    LOGO = "logo"
    POSTER = "poster"
    INFOGRAPHIC = "infographic"
    COMIC = "comic"
    CHARACTER_SHEET = "character_sheet"
    TEXTURE = "texture"
    CUTOUT = "cutout"
    EDIT = "edit"


class EditOp(str, Enum):
    NONE = "none"
    BACKGROUND_REMOVE = "background_remove"
    OBJECT_REMOVE = "object_remove"
    OUTPAINT = "outpaint"
    DETAIL_REGEN = "detail_regen"


class RequirementVector(BaseModel):
    """What the user actually needs, extracted from their words."""

    artifact: Artifact = Artifact.ILLUSTRATION
    alpha: Literal["required", "preferred", "no"] = "no"
    text_in_image: Literal["required", "preferred", "no"] = "no"
    style: str = "general"
    edit_op: EditOp = EditOp.NONE
    width: int = 1024
    height: int = 1024
    speed: Literal["fastest", "normal", "quality_first"] = "normal"
    hard: list[str] = Field(default_factory=list)


class ModelChoice(BaseModel):
    id: str
    role: str
    npu_usage: int
    co_resident_with_planner: bool
    combined_npu_pct: int


class Resolution(BaseModel):
    """The resolver's answer, with the reasoning attached."""

    chosen: ModelChoice
    requirements: RequirementVector
    justification: str
    alternatives: list[ModelChoice] = Field(default_factory=list)
    swap_required: bool = False
    swap_plan: dict[str, list[str]] = Field(default_factory=dict)
    generation_occupancy_pct: int = 0
```

**Step 1 — failing test** (the vector round-trips; the resolution carries a
justification).
**Step 2** — run, FAIL. **Step 3** — implement. **Step 4** — run, PASS.
**Step 5** — commit.

### Task A3 — Move the curated overlay into data

The overlay currently lives inside `tools/build_registry.py`. The runtime
needs it, so it becomes data and both the generator and the app read it.

**Files:**
- Create: `app/data/overlay.yaml`
- Modify: `tools/build_registry.py` — load the overlay from YAML, drop the inline dict
- Test: `app/tests/test_registry.py`

```yaml
# app/data/overlay.yaml — the curated judgement layer.
# Device facts come from the live store; this file is what a human knows.
# Provenance: d = from the device, m = measured, i = inferred.
models:
  Tongyi-MAI/Z-Image-Turbo:
    role: default
    artifact: [illustration, photo, logo, poster, texture]
    alpha: false
    text_rendering: strong
    style: [photoreal, general]
    edit_ops: []
    quality: high
    speed: fast
    dialect: >-
      Plain descriptive English. Subject first, then modifiers, then lighting
      and mood. No prompt-engineering keywords, no quality booster tokens, no
      comma salad.
    sizes_verified: ["512x512", "1024x1024", "1280x768", "1152x768", "1024x768"]
    sizes_rejected: ["1536x1024", "1024x1536", "1792x1024"]
    rejected_reason: exceeds max transformer tokens 5760 / max_width 1536
    notes: 8 steps, guidance 0.0. ~9s at 512px, ~55s at 1024px.
    provenance: d,m
```

**Acceptance:** `tools/build_registry.py` produces a byte-identical
`registry/image-models.json` to the one committed before the change, except
for the `kind` and `context_window` fields added in the earlier fix.

### Task A4 — The registry loader

**Files:**
- Create: `app/src/tis/registry.py`
- Test: `app/tests/test_registry.py`

```python
# app/src/tis/registry.py
"""Loads the generated registry. Read-only; knows nothing about the device."""
from __future__ import annotations

import json
from pathlib import Path

from .models import ModelChoice


class Registry:
    def __init__(self, payload: dict):
        self._payload = payload
        self._models = payload.get("models", [])
        self._by_id = {m["id"]: m for m in self._models}

    @classmethod
    def load(cls, path: str | Path) -> "Registry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def planner(self) -> dict:
        return self._payload.get("planner", {})

    @property
    def planner_npu(self) -> int:
        return int(self.planner.get("npu_usage", 0))

    def generators(self) -> list[dict]:
        return [m for m in self._models if m.get("kind") == "image_generator"]

    def enhancers(self) -> list[dict]:
        return [m for m in self._models if m.get("kind") == "prompt_enhancer"]

    def get(self, model_id: str) -> dict | None:
        return self._by_id.get(model_id)

    def choice(self, model_id: str) -> ModelChoice:
        m = self._by_id[model_id]
        return ModelChoice(
            id=m["id"], role=m["role"],
            npu_usage=m["device"]["npu_usage"],
            co_resident_with_planner=m["residency"]["co_resident_with_planner"],
            combined_npu_pct=m["residency"]["combined_npu_pct"],
        )
```

### Task A5 — **The resolver** — the product

**Files:**
- Create: `app/src/tis/resolver.py`
- Test: `app/tests/test_resolver.py` — **at least 30 cases**

```python
# app/src/tis/resolver.py
"""Deterministic model selection. Pure: no I/O, no device, no network.

The LLM proposes a RequirementVector. This module disposes of it. The split
matters: the model does not know the NPU costs, the registry changes without
retraining, and a deterministic decision is testable.
"""
from __future__ import annotations

from .models import EditOp, RequirementVector, Resolution
from .registry import Registry

#: Residency above this percentage is admitted but cannot run a diffusion
#: pass. Measured 2026-11-05: 81% works, 85% fails with 500 / 150004.
MAX_EXECUTABLE_OCCUPANCY_PCT = 81

#: Below this, the flagship and everything else would have to share a pool.
#: The flagship is the only native-RGBA model, so it is worth a swap.
FLAGSHIP_ALPHA_PCT = 62


def _satisfies(model: dict, req: RequirementVector) -> bool:
    """Hard filter. A model that cannot meet a hard constraint is out."""
    spec = model.get("specialty", {})
    if req.alpha == "required" and not spec.get("alpha"):
        return False
    if req.text_in_image == "required" and spec.get("text_rendering") in ("weak", "n/a", "unknown"):
        return False
    if req.edit_op != EditOp.NONE and req.edit_op.value not in (spec.get("edit_ops") or []):
        return False
    if req.artifact.value in (spec.get("artifact") or []):
        return True
    # An edit adapter has no artifact list; it matches only its own op.
    return bool(spec.get("edit_ops"))


def _score(model: dict, req: RequirementVector) -> float:
    spec = model.get("specialty", {})
    score = 0.0
    if req.artifact.value in (spec.get("artifact") or []):
        score += 40.0
    if req.alpha in ("required", "preferred") and spec.get("alpha"):
        score += 30.0
    if req.text_in_image in ("required", "preferred") and spec.get("text_rendering") == "best":
        score += 20.0
    if req.speed == "fastest" and spec.get("speed") == "fastest":
        score += 15.0
    if req.speed == "quality_first" and spec.get("quality") in ("highest", "high"):
        score += 15.0
    # Prefer a model that can run beside the planner.
    if model["residency"]["co_resident_with_planner"]:
        score += 12.0
    # Then prefer the cheaper one.
    score -= model["device"]["npu_usage"] * 0.05
    return score


def resolve(req: RequirementVector, registry: Registry) -> Resolution:
    """Pick a model for a requirement vector, and say why."""
    candidates = [m for m in registry.generators() if _satisfies(m, req)]
    if not candidates:
        candidates = list(registry.generators())

    ranked = sorted(candidates, key=lambda m: (-_score(m, req), m["device"]["npu_usage"], m["id"]))
    chosen = ranked[0]
    planner_npu = registry.planner_npu

    occupancy = planner_npu + chosen["device"]["npu_usage"]
    swap_required = occupancy > MAX_EXECUTABLE_OCCUPANCY_PCT
    # With a swap, the generator runs alone, so its occupancy is just itself.
    generation_occupancy = chosen["device"]["npu_usage"] if swap_required else occupancy

    if req.alpha == "required" and chosen["specialty"].get("alpha"):
        why = (f"{chosen['id']} is the only co-resident model with native RGBA output, "
               f"and alpha was a hard requirement.")
    else:
        why = (f"{chosen['id']} best matches a {req.artifact.value} request "
               f"(style={req.style}, npu={chosen['device']['npu_usage']}%).")

    if swap_required:
        why += (f" It needs {occupancy}% of the NPU with the planner, above the "
                f"{MAX_EXECUTABLE_OCCUPANCY_PCT}% that can actually run a diffusion "
                f"pass, so the planner is released for the generation.")

    return Resolution(
        chosen=registry.choice(chosen["id"]),
        requirements=req,
        justification=why,
        alternatives=[registry.choice(m["id"]) for m in ranked[1:4]],
        swap_required=swap_required,
        swap_plan={
            "evict": [registry.planner["id"]] if swap_required else [],
            "load": [chosen["id"]],
            "restore": [registry.planner["id"]] if swap_required else [],
        },
        generation_occupancy_pct=generation_occupancy,
    )
```

**Acceptance:** the test file holds **30+ cases**, each a
`(RequirementVector, expected_model_id)` pair, covering every artifact type,
both alpha cases, every edit op, every speed preference, and at least one
request no model can satisfy. A human reviews the table and agrees with ≥85%
of the picks.

**This is the task to get right.** It is the product.

### Task A6 — The dialect translator

**Files:**
- Create: `app/src/tis/dialect.py`
- Test: `app/tests/test_dialect.py`

```python
# app/src/tis/dialect.py
"""Rewrites a user's intent into the target model's dialect.

Measured 2026-11-05: the same model, same size, same 200s, produced 0%
fully-transparent pixels with a soft prompt and 44.86% with an explicit
cut-out dialect. The prompt is not the same thing as the model's prompt.
"""
from __future__ import annotations

from .models import RequirementVector
from .registry import Registry

CUTOUT_DIALECT = (
    "Isolated asset, hard clean edges, transparent background, no background "
    "layer, no gradient, no shadow, alpha cutout on empty canvas."
)


def translate(user_words: str, req: RequirementVector, model: dict) -> str:
    """Return the prompt to send the image model."""
    dialect = (model.get("prompting") or {}).get("dialect") or ""
    parts = [user_words.strip().rstrip(".") + "."]

    if req.alpha in ("required", "preferred"):
        parts.append(CUTOUT_DIALECT)
    if req.text_in_image == "required":
        parts.append("Any text in the image must be exactly as specified, correctly spelled.")
    if req.style and req.style != "general":
        parts.append(f"Style: {req.style}.")
    parts.append(dialect.strip())
    return " ".join(p for p in parts if p)
```

---

## Phase B — The device layer

### Task B1 — The adapter protocol and the fake

**Files:**
- Create: `app/src/tis/device.py`
- Create: `app/tests/fake_device.py`

```python
# app/src/tis/device.py
"""The only place the bearer token exists.

Everything above this module talks to a Device, never to HTTP.
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.request
from typing import Protocol

from .config import Settings


class DeviceError(RuntimeError):
    """A device call failed. `retryable` says whether the same call might
    work after a residency change."""


class Device(Protocol):
    def chat(self, model: str, prompt: str, **kw) -> dict: ...
    def generate(self, model: str, prompt: str, size: str) -> bytes: ...
    def resident(self) -> list[str]: ...
    def load(self, model: str) -> None: ...
    def unload(self, model: str) -> None: ...


class TiinyDevice:
    """The real appliance."""

    def __init__(self, settings: Settings):
        self._s = settings

    def _get(self, path: str, timeout: int = 15) -> dict:
        req = urllib.request.Request(
            self._s.base_url + path,
            headers={"Authorization": f"Bearer {self._s.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            raise DeviceError(f"GET {path} failed: {exc}") from exc
```

**Acceptance for the fake:** `FakeDevice` implements the same protocol with
scripted responses, including the **measured** failures — a 500 at 85%
occupancy, a 404 for a model that is not resident, and a load that evicts
every model except the 0% ones.

### Task B2 — Chat and image generation

**Files:** Modify `app/src/tis/device.py`, `app/tests/fake_device.py`
- Test: `app/tests/test_device.py`

---

## Phase C — Residency

### Task C1 — The budget

**Files:**
- Create: `app/src/tis/residency.py`
- Test: `app/tests/test_residency.py`

```python
# app/src/tis/residency.py
"""Two budgets: what fits, and what can run.

A model set can be admitted to the NPU and still fail the diffusion pass.
Measured 2026-11-05: 81% runs, 85% returns 500 / 150004.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

MAX_EXECUTABLE_OCCUPANCY_PCT = 81


def can_co_reside(combined_pct: int) -> bool:
    """Whether the two models may both be resident."""
    return combined_pct <= 100


def can_execute(combined_pct: int) -> bool:
    """Whether a generation can actually run at that occupancy."""
    return combined_pct <= MAX_EXECUTABLE_OCCUPANCY_PCT
```

### Task C2 — The hold file and the watchdog lock

**Files:** Modify `app/src/tis/residency.py`
- Test: `app/tests/test_residency.py`

Three rules, each learned the hard way:

1. **Write the hold BEFORE the load.** The watchdog fires on a 5-minute cron
   and can land between the load and the hold.
2. **Take the watchdog's `flock`.** The watchdog holds
   `~/.hermes/tiiny-watch.lock`; without taking it, a tick that already
   passed its hold-check will evict the model mid-generation.
3. **Never report "hold cleared" without checking.** A stale hold disables
   the watchdog forever, silently.

```python
class HoldFile:
    """`~/.hermes/tiiny-hold` — the contract with the watchdog."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, model_ids: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(model_ids) + "\n", encoding="utf-8")

    def clear(self) -> bool:
        """Release the hold and VERIFY it is gone. Returns False if the hold
        is still there — a stale hold stops the watchdog restoring the
        device, forever."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return not self.path.exists()
```

### Task C3 — The swap

**Files:** Modify `app/src/tis/residency.py`
- Test: `app/tests/test_residency.py`

```python
    async def swap_to(self, model_id: str):
        """Load a model, hold it against the watchdog, and restore after.

        The ordering is not stylistic. Write the hold first, take the
        watchdog's lock, and restore in a finally — a crash mid-swap must
        not leave the device in a state nobody cleans up.
        """
```

**Acceptance:** the test suite covers — a load that evicts the resident set,
an unload that reverts to the device's default set, a generation that fails
at high occupancy, a crash mid-swap, and a stale hold found at startup.

---

## Phase D — Orchestration

### Task D1 — The orchestrator

**Files:**
- Create: `app/src/tis/orchestrator.py`
- Test: `app/tests/test_orchestrator.py`

The loop: plan → resolve → swap → generate → critique → deliver. Retry bound
**3 generations per user turn** — HiDream at 1024² is ~34 s and the flagship
~200 s, so an unbounded loop is a foot-gun.

### Task D2 — The critic

The critic judges the image against the **requirement vector**, not the user's
original words. The user said *"a fox"*; the vector says
`artifact=icon, alpha=required`; the critic judges the icon.

---

## Phase E — State, assets, events

### Task E1 — SQLite job store
### Task E2 — The asset store (PNG + lineage JSON on disk)
### Task E3 — The SSE event bus

---

## Phase F — The API

### Task F1 — The planner: natural language to a requirement vector

The one piece of the product the SPEC assigns to the LLM. The LLM does
**not** pick the model — it extracts intent into the `RequirementVector`,
and the resolver picks the model deterministically.

`app/src/tis/planner.py`:

- `Planner(device, model_id).plan(request: str, width: int = 1024,
  height: int = 1024) -> RequirementVector`
- The prompt states the artifact vocabulary, the style vocabulary and the
  enum values, and asks for **JSON only**. The registry is the vocabulary
  source — do not invent an artifact or a style that is not in it.
- The reply is parsed defensively: strip a markdown fence if present, take
  the first JSON object in the reply, and validate it against
  `RequirementVector`. A reply that will not parse is a `PlannerError`,
  never a silent default.
- **The fallback matters.** A deterministic keyword planner extracts intent
  from the request text alone (artifact words, "transparent" → alpha
  required, "logo"/"text" → text_in_image, "photoreal"/"flat" → style).
  When the LLM fails, the product still works. The fallback is deliberately
  conservative and says so in the lineage.
- The planner records which path produced the vector — `llm` or `fallback`
  — so the lineage shows it.

### Task F2 — The service layer: wiring and the job runner

`app/src/tis/service.py`:

- `Agency` — builds the whole graph from `Settings`: registry, resolver,
  translator, planner, critic, device, residency manager, job store, asset
  store, event bus, orchestrator. One place where the wiring lives, so the
  CLI and the API share it.
- **The appliance is serial and takes 54–200 s for one image.** A request
  that waits synchronously for that is a request that times out. So
  `/v1/generate` returns a **job id immediately** and the work runs on a
  background thread, publishing progress to the event bus.
- The job runner is a single worker thread per session, not one thread per
  job: the appliance serves one inference at a time, and a queue is the
  only honest model of it.
- The runner publishes `job.started`, `generate.started`,
  `generate.finished`, `critique.ready`, `asset.ready`, `job.finished` or
  `job.failed`.
- **The device bearer never reaches a response, a log line or the asset
  store.** The `Agency` holds it; nothing else sees it.

### Task F3 — FastAPI routes

`app/src/tis/api.py`, mounting exactly the SPEC's surface:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/models` | the registry, with specialty, NPU cost, dialect |
| `GET` | `/v1/npu` | live residency: resident models, NPU used and free |
| `POST` | `/v1/plan` | request → requirements + resolved model + justification + swap plan |
| `POST` | `/v1/generate` | request or plan → job id, then the asset |
| `POST` | `/v1/iterate` | asset + feedback → revised prompt → new job |
| `GET` | `/v1/assets/{asset_id}` | the PNG, alpha preserved |
| `GET` | `/v1/assets/{asset_id}/lineage` | the full provenance |
| `GET` | `/v1/session/{session_id}/events` | the SSE stream |
| `GET` | `/v1/health` | device reachable, registry fresh, app alive |

- `create_app(settings)` returns the FastAPI app. Nothing at import time
  touches the device or the filesystem — the app is constructed with
  dependencies so a test can hand it a fake.
- The SSE route subscribes to the event bus for the session and streams
  `data: {json}\n\n` until the client disconnects or the job finishes.
- The PNG route returns `image/png` with the bytes **exactly as stored**.
  The alpha channel is the product; re-encoding it would destroy it.

### Task F4 — The API tests

`app/tests/test_api.py`, with FastAPI's `TestClient`:

- every endpoint answers, and the shapes match the SPEC's examples
- `/v1/plan` returns the model, the justification and the swap plan
- `/v1/generate` returns a job id **immediately** and the job completes in
  the background
- the SSE stream delivers the events for a session, and only that session's
- `/v1/assets/{id}` returns the PNG byte-for-byte
- a failed job publishes `job.failed` and carries the reason
- the bearer never appears in any response body

---

## Phase G — CLI and skill

### Task G1 — The CLI (`tis`): `plan`, `generate`, `iterate`, `models`, `npu`
### Task G2 — The Hermes skill

---

## Phase H — The work surface

### Task H1 — `web/index.html` + `app.js` + `style.css`

---

## Phase I — Publish

### Task I1 — `publish/README.md`, `PATTERN.md`, `IMPLEMENTATION.md`
### Task I2 — The `publish.py` mapping to `AI_Articles/tiiny-image-agency/`

---

## Phase J — The two roles, and the judge that can see

The original spec drew the critic as `LLM, vision`, and the implementation
did not deliver it: the critic called `device.chat()` with a plain string,
so it judged the prompt and never the pixels. The first live run burned
three generations chasing a defect it had invented, because it could not
look at the image it was judging.

### Task J1 — The conversational catalogue
- [x] `registry/roles.json`, built from the live store, curated in
      `app/data/roles.yaml` — 26 conversational models, 16 that can see
- [x] `vision` derived from the device's own record: `type ==
      "Image-Text-to-Text"`, or an `input` that accepts an image
- [x] Prompt enhancers excluded — an enhancer cannot hold either role
- [x] `app/src/tis/roles.py` — typed, with `downloaded` (listed ≠ on disk)
      and provenance (`m` measured here, `d` the device's claim)

### Task J2 — A critic that can see
- [x] `Critic(device, model_id, vision=True)` dispatches to `device.vision()`
- [x] The judge prompt branches: a vision judge is told it CAN see and to
      judge what it sees; a blind judge is told it cannot and to never invent
      a defect
- [x] `_ObservedDevice.vision()` publishes `critique.ready` like `chat()`
      does — a critique the client was never told about is a critique the
      client cannot show

### Task J3 — The choice
- [x] `settings.judge_model`, separate from `settings.planner_model`
- [x] `GET /v1/roles` — the guide: every model, its vision flag, its NPU
      cost, whether it is on the device, and whether the choice **fits**
- [x] `POST /v1/roles` — the choice; applies to the next job
- [x] `tis roles [--critic] [--conversation]`
- [x] The work surface's two pickers, fed by the guide, not a hard-coded list

### Task J4 — Making the choice work
- [x] The fit is **judge + generator against the 81% execution ceiling**.
      The talker is not in that sum — it has already written the scene
      description by the time the image is made, so its weights are swapped
      out and a 47% judge with a 23% generator is 70%, which runs
- [x] The residency manager prices a judge from the roles catalogue. A judge
      priced at zero would leave the pool above the ceiling and the
      generation would fail
- [x] The orchestrator is given the new critic when one is chosen. It was
      handed the critic when it was built, so replacing the agency's copy
      would have changed the guide and not the judging

### Task J5 — Verified on the device
- [x] A live generation judged by `Qwen/Qwen3.6-35B-A3B` — the swap
      requested it as a companion, the generation ran at 70%, and the
      critique event named the model with `vision: true`

---

## Definition of done

- [x] `pytest` green with no live-device tests in the default run
- [x] The resolver table of 30+ cases reviewed and agreed
- [x] A real generation on the device, end to end, through the API
- [x] A real generation through the skill, with no device contact outside the API
- [x] The work surface shows the model badge, the NPU meter, and the swap banner
- [x] No bearer token in any response, log, or file in the repo
- [x] Published to `AI_Articles/tiiny-image-agency/`

---

## Phase K — The tab strip (2026-11-07)

The prerequisite for Phase L and Phase N. Three tabs: **Make**, **Models**,
**References**. The card block leaves the canvas column and becomes the
Models tab.

- [x] K1 — the tab strip in `app/web/index.html`
- [ ] K2 — the switching behaviour in `app/web/app.js` + `app/web/style.css`
- [ ] K3 — the tests, then the commit

## Phase L — Feature 1: the model card browser (2026-11-07)

A grid of every model's card, with the three parts kept distinct: what
the device advertises, what we measured, and what we have noticed.

- [ ] L1 — `GET /v1/models/cards`, one request for all of them
- [ ] L2 — the grid and the detail pane
- [ ] L3 — the filters (artifact, measured, can see, text search)
- [ ] L4 — the tests, then the commit

## Phase M — Feature 2: notice a new model, ask, download, benchmark (2026-11-07)

**M11 measured: there is no vendor signal.** `need_update` is false on
all 92 rows, so the app keeps its own watermark of seen catalogue ids and
diffs against it. **All 15 image models are already installed today**,
so this feature has nothing to announce until the vendor adds one.

- [ ] M1 — `app/src/tis/catalogue.py`, the diff
- [ ] M2 — the seen-models watermark
- [ ] M3 — the watcher, publishing `catalogue.new_model`
- [ ] M4 — the banner in the surface (a banner, not a modal)
- [ ] M5 — the download-and-benchmark job, including the registry reload
- [ ] M6 — the tests, then the commit

## Phase N — Feature 3: a saved reference (2026-11-07)

**M10 measured: the appliance DOES take an image**, in `image` (string)
or `images` (array) — proved against a no-image control, with the
timing split at 16.3 s versus ~34 s. **Every drag-and-drop edit has
been text-only until now**, because the Agency never sent the bytes.

- [ ] N0 — **the gate:** measure which models honour an image
- [ ] N1 — `device.generate()` sends the source
- [ ] N2 — the orchestrator passes it through
- [ ] N3 — `app/src/tis/references.py`, the store
- [ ] N4 — the API routes and `reference_id` on generate
- [ ] N5 — the surface: save a reference, the References tab, use it
- [ ] N6 — the CLI and the three skill copies
- [ ] N7 — the tests, then the commit

**The full task detail, with the code, is in `PLAN-THREE-FEATURES.md`.**
