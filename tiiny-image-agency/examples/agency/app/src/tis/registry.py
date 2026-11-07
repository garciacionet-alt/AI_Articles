"""The registry: the device's model catalogue, merged with curated judgement.

registry/image-models.json is the single source of truth for what the
appliance can do. It has three layers:

  device facts    what the device reports (name, NPU cost, description)
  curated overlay hand-maintained judgement (app/data/overlay.yaml)
  merged output   the two combined, written by tools/build_registry.py

The resolver sits on top of this file and must not read raw dictionary keys,
so every capability is exposed as a named property here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# Community-run builds. Never auto-selected; the resolver returns them as
# alternatives with their caveat.
#
# The community quant of Qwen-Image-2.1 is the only other model declaring icon
# capability and it reports 0% NPU, so it is a tempting win. Two reasons not
# to auto-select it: we MEASURED the vendor flagship's alpha (44.86% fully
# transparent pixels) and never measured the community build's; and a
# professional demonstration should not silently default to an unsupported
# community quant.
COMMUNITY_MODEL_IDS: frozenset[str] = frozenset({
    "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
})


class RegistryError(Exception):
    """Raised for every registry failure: missing file, bad JSON, wrong shape."""


@dataclass(frozen=True)
class PlannerSpec:
    """The planning model.

    The registry records the planner separately from the image models: it is
    not a generator, and it carries only its id and its NPU cost.
    """

    id: str
    npu_usage: int


@dataclass(frozen=True)
class ModelSpec:
    """One model in the catalogue, read through named properties."""

    raw: dict

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def kind(self) -> str:
        return self.raw["kind"]

    @property
    def role(self) -> str:
        return self.raw["role"]

    @property
    def npu_usage(self) -> int:
        return self.raw["device"]["npu_usage"]

    @property
    def size_bytes(self) -> int:
        """How much disk this model takes on the appliance.

        Zero means the device did not say, and the capacity check then
        cannot promise the model will fit.
        """
        return int(self.raw.get("device", {}).get("size_bytes") or 0)

    @property
    def co_resident_with_planner(self) -> bool:
        return self.raw["residency"]["co_resident_with_planner"]

    @property
    def artifact(self) -> list[str]:
        # A copy: a caller that mutated the list would corrupt the registry
        # for every other caller.
        return list(self.raw["specialty"].get("artifact") or [])

    @property
    def alpha(self) -> bool:
        return bool(self.raw["specialty"]["alpha"])

    @property
    def text_rendering(self) -> str:
        return self.raw["specialty"]["text_rendering"]

    @property
    def style(self) -> list[str]:
        return list(self.raw["specialty"].get("style") or [])

    @property
    def edit_ops(self) -> list[str]:
        return list(self.raw["specialty"].get("edit_ops") or [])

    @property
    def quality(self) -> str:
        return self.raw["specialty"]["quality"]

    @property
    def speed(self) -> str:
        return self.raw["specialty"]["speed"]

    @property
    def dialect(self) -> str:
        return self.raw["prompting"]["dialect"]

    @property
    def sizes_verified(self) -> list[str]:
        return list(self.raw["prompting"].get("sizes_verified") or [])

    @property
    def sizes_rejected(self) -> list[str]:
        """The sizes this model refuses, with the reason.

        A rejected size is not the same as an unverified one. An
        unverified size is one nobody has checked, and the translator
        nudges it to the nearest verified size. A REJECTED size is one
        the device has said it will not produce, and the translator has
        to say so by name rather than quietly moving the request.
        """
        return list(self.raw["prompting"].get("sizes_rejected") or [])

    @property
    def rejected_reason(self) -> str:
        """Why the rejected sizes are rejected, in the registry's words.

        The registry stores an ABSENT reason as JSON null, not as an
        omitted key, so the default alone would hand back None and every
        caller would have to check for it. The reason is always a string.
        """
        return self.raw["prompting"].get("rejected_reason") or ""

    @property
    def size_rule(self) -> str:
        return self.raw["prompting"].get("size_rule") or ""

    @property
    def notes(self) -> str:
        return self.raw.get("notes", "")

    @property
    def provenance(self) -> str:
        return self.raw.get("provenance", "")

    @property
    def vendor_supported(self) -> bool:
        return self.id not in COMMUNITY_MODEL_IDS

    @property
    def downloaded(self) -> bool:
        """Is this model on the appliance's disk right now?

        The device's store catalogue lists every model Tiiny SELLS, and
        only some of them are downloaded. The distinction is not
        cosmetic: a model that is not downloaded cannot be loaded, so
        choosing it produces a plan that fails at the load step with
        "Model not found".

        This bit the product for real. The registry is built from
        GET /api/v1/models/online_models, which is the STORE, and 9 of
        the 16 curated models were `not_downloaded` on the appliance.
        The resolver duly chose one and the load failed.

        An unknown status is treated as downloadable, so a hand-made
        registry that does not record the field still works.
        """
        status = str(self.raw.get("device", {}).get("status") or "").lower()
        if not status:
            return True
        return status in ("downloaded", "running")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ModelSpec({self.id!r}, kind={self.kind!r})"


@dataclass(frozen=True)
class Registry:
    """The loaded catalogue."""

    models: tuple[ModelSpec, ...]
    planner: PlannerSpec
    path: Path

    @classmethod
    def load(cls, path: Path | str) -> "Registry":
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise RegistryError(f"registry file not found: {path}") from None
        except OSError as exc:
            raise RegistryError(f"could not read registry {path}: {exc}") from None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Invalid JSON in registry {path}: {exc}") from None

        if not isinstance(data, dict):
            raise RegistryError(f"registry {path} must contain a JSON object")
        if "models" not in data:
            raise RegistryError(f"registry {path} is missing the 'models' key")
        if "planner" not in data:
            raise RegistryError(f"registry {path} is missing the 'planner' key")

        raw_models = data["models"]
        if not isinstance(raw_models, list):
            raise RegistryError(f"registry {path} 'models' must be a list")

        models: list[ModelSpec] = []
        for entry in raw_models:
            if not isinstance(entry, dict):
                raise RegistryError(f"registry {path} has a non-object model entry")
            if "id" not in entry:
                raise RegistryError(
                    f"registry {path} has a model entry missing 'id': {entry!r}")
            if "kind" not in entry:
                raise RegistryError(
                    f"registry {path} has a model entry missing 'kind': {entry!r}")
            models.append(ModelSpec(entry))

        raw_planner = data["planner"]
        if not isinstance(raw_planner, dict) or "id" not in raw_planner:
            raise RegistryError(
                f"registry {path} 'planner' must be an object with an 'id'")
        planner = PlannerSpec(
            id=raw_planner["id"],
            npu_usage=int(raw_planner.get("npu_usage", 0)),
        )

        return cls(models=tuple(models), planner=planner, path=path)

    def by_id(self, model_id: str) -> ModelSpec:
        for model in self.models:
            if model.id == model_id:
                return model
        raise RegistryError(f"model not found in registry: {model_id}")

    def find(self, model_id: str) -> ModelSpec | None:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def refresh_status(self, catalogue: list[dict]) -> int:
        """Update the downloaded flags from a LIVE catalogue.

        The registry's ``status`` is a snapshot — the device's store at
        the moment the registry was generated. A model downloaded since
        then is still recorded as not downloaded, and the resolver would
        refuse a job it could actually do.

        So the status is refreshed from the appliance before a job runs.
        Only the status moves: the curated data — the artifacts, the
        styles, the NPU cost — comes from the overlay and the device and
        does not change.

        Returns the number of models whose status changed.
        """
        statuses = {
            str(row.get("fullname") or ""): str(row.get("status") or "")
            for row in catalogue
        }
        changed = 0
        for model in self.models:
            status = statuses.get(model.id)
            if not status:
                continue
            device = model.raw.get("device")
            if not isinstance(device, dict):
                continue
            if device.get("status") != status:
                device["status"] = status
                changed += 1
        return changed

    @property
    def generators(self) -> tuple[ModelSpec, ...]:
        return tuple(m for m in self.models if m.kind == "image_generator")

    @property
    def enhancers(self) -> tuple[ModelSpec, ...]:
        return tuple(m for m in self.models if m.kind == "prompt_enhancer")

    @property
    def ids(self) -> list[str]:
        return [m.id for m in self.models]

    def __len__(self) -> int:
        return len(self.models)

    def __iter__(self) -> Iterator[ModelSpec]:
        return iter(self.models)

    def __contains__(self, model_id: object) -> bool:
        return any(m.id == model_id for m in self.models)


def load_default(settings: Any | None = None) -> Registry:
    """Load the registry the application ships with."""
    if settings is None:
        from .config import Settings

        settings = Settings()
    return Registry.load(settings.registry_path)
