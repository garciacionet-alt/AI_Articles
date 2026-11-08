"""The conversational catalogue: the models that can TALK.

THE SECOND CATALOGUE, AND WHY
-----------------------------
`registry.py` holds the IMAGE catalogue: the models that generate
pictures, which the resolver picks from. It says nothing about the
Agency's two other roles:

  * the CONVERSATION AGENT, which turns a request into a requirement
    vector, and
  * the CRITIC, which judges the result.

Both are held by TEXT models, and no text model is in the image
registry. So there is a second catalogue, `registry/roles.json`, built
from the same live store snapshot and curated in `app/data/roles.yaml`.

THE FLAG THAT MATTERS MOST
--------------------------
`vision`. A model with `vision: true` accepts an IMAGE as well as
text. That is the difference between a critic that judges the prompt
and a critic that judges the picture — and the first live run of the
Agency burned three generations chasing a defect the prompt judge
invented, because it could not look at the image it was judging.

The device states this twice: the model's `type` is
"Image-Text-to-Text", and its `input` is "Text,Image". Both are read.

A NOTE ABOUT WHAT IS TRUSTED
-----------------------------
The appliance's own description of a model is not trusted. It
described one model as producing text correctly; eleven probes found
it mangled text every time. So `notes` here say who measured what, and
`provenance` says whether it was measured HERE ("m") or is the
device's own claim ("d").
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RoleError(Exception):
    """The roles catalogue could not be read, or a role is not in it."""


class RoleSpec:
    """One conversational model, read through named properties."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or self.raw["id"])

    @property
    def role(self) -> str:
        return str(self.raw.get("role") or "conversation")

    @property
    def vision(self) -> bool:
        """Can this model accept an IMAGE as well as text?

        This is the flag that decides whether the critic can look at
        the picture it is judging.
        """
        return bool(self.raw.get("vision"))

    @property
    def npu_usage(self) -> int:
        return int(self.raw.get("device", {}).get("npu_usage") or 0)

    @property
    def size_bytes(self) -> int:
        """How much disk this model's weights take on the appliance.

        Zero means the device did not say. It matters for the models the
        device prices at 0% NPU: the voice is tiny and genuinely free,
        and the community quant build is 14.5 GiB and not free at all.
        """
        return int(self.raw.get("device", {}).get("size_bytes") or 0)

    @property
    def context_window(self) -> int:
        return int(self.raw.get("device", {}).get("context_window") or 0)

    @property
    def status(self) -> str:
        """Is it on the device? "downloaded", "running", or not."""
        return str(self.raw.get("device", {}).get("status") or "")

    @property
    def downloaded(self) -> bool:
        """Can this model be loaded right now?

        A model that is listed is not a model that is on disk. The
        resolver learned that the hard way, and so does this.
        """
        return self.status in ("downloaded", "running")

    @property
    def notes(self) -> str:
        return str(self.raw.get("notes") or "")

    @property
    def provenance(self) -> str:
        """Who measured this. "m" measured here, "d" the device's claim."""
        return str(self.raw.get("provenance") or "")

    def as_dict(self) -> dict[str, Any]:
        """The shape the API serves."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "vision": self.vision,
            "npu_usage": self.npu_usage,
            "context_window": self.context_window,
            "downloaded": self.downloaded,
            "status": self.status,
            "notes": self.notes,
            "provenance": self.provenance,
        }


class Roles:
    """The conversational catalogue."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self._models = [RoleSpec(m) for m in raw.get("models", [])]

    @classmethod
    def load(cls, path: Path | str) -> "Roles":
        path = Path(path)
        try:
            with path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError as exc:
            raise RoleError(
                f"the roles catalogue is not there: {path}. Run "
                f"tools/build_registry.py to build it."
            ) from exc
        except json.JSONDecodeError as exc:
            raise RoleError(f"the roles catalogue is not valid JSON: {exc}") from exc
        return cls(raw)

    def __len__(self) -> int:
        return len(self._models)

    def __iter__(self):
        return iter(self._models)

    def all(self) -> list[RoleSpec]:
        return list(self._models)

    def get(self, model_id: str) -> RoleSpec | None:
        for model in self._models:
            if model.id == model_id:
                return model
        return None

    def require(self, model_id: str) -> RoleSpec:
        model = self.get(model_id)
        if model is None:
            raise RoleError(
                f"{model_id} is not in the conversational catalogue"
            )
        return model

    def vision_models(self) -> list[RoleSpec]:
        """The models that can SEE an image, cheapest first.

        This is the guide: a user who wants a critic that can look at
        the picture wants one of these, and the cheapest one that fits
        the pool beside a generator is the one that will actually run.
        """
        return sorted(
            (m for m in self._models if m.vision),
            key=lambda m: (m.npu_usage, m.id),
        )

    def for_role(self, role: str) -> list[RoleSpec]:
        return sorted(
            (m for m in self._models if m.role == role),
            key=lambda m: (not m.vision, m.npu_usage, m.id),
        )
