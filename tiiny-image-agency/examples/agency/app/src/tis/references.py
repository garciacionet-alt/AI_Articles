"""The reference store: a saved result, kept so the next one matches it.

WHAT A REFERENCE IS
-------------------
Two things. The PNG, byte for byte, and the RECIPE that made it — the
requirements, the model that was chosen, the dialect the prompt was
written in, the size, the prompt itself, the modifiers, and what the
judge said.

The recipe is the part that makes a repeated job repeatable. "The same
fox head, but this week's" is a request whose answer is a set of
requirements and a model and a dialect, not a picture — and all of that
is already in the lineage the service writes.

WHY IT IS A SEPARATE STORE AND NOT AN ASSET
--------------------------------------------
An asset is a DELIVERED image: the product, with its lineage. A
reference is a REFERENCE to a delivered image: the same bytes, but
saved because the user liked them and wants more like them. A reference
also carries the recipe, which an asset's lineage does not — the lineage
records what happened, and a reference records what to DO AGAIN.

THE PNG IS WRITTEN AS IT ARRIVES
--------------------------------
The bytes go to disk exactly as they were produced. Nothing here
decodes, re-encodes or inspects an image. A round trip through an image
library is exactly where a transparent background quietly becomes an
opaque one, and a reference whose transparency is a lie is worse than no
reference at all.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The prefix on every reference id, so an id in a URL says what it is.
REFERENCE_ID_PREFIX = "ref_"

#: What a reference id must look like. An id becomes a file name, and a
#: file name may not walk out of the references directory — so an id
#: that is not safe is answered with "no such reference" rather than
#: being read from somewhere it should not be.
SAFE_ID = re.compile(r"^ref_[A-Za-z0-9._-]{1,64}$")

#: The eight bytes every PNG starts with.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Reference:
    """One saved result and the recipe that made it."""

    id: str
    png: bytes
    name: str
    requirements: dict
    model_id: str
    dialect: str
    size: str
    prompt: str
    modifiers: tuple[str, ...]
    critique: dict | None
    created_at: float

    def to_dict(self) -> dict:
        """The reference without its bytes — for a listing."""
        return {
            "id": self.id,
            "name": self.name,
            "requirements": self.requirements,
            "model_id": self.model_id,
            "dialect": self.dialect,
            "size": self.size,
            "prompt": self.prompt,
            "modifiers": list(self.modifiers),
            "critique": self.critique,
            "created_at": self.created_at,
        }


class ReferenceStore:
    """A directory of PNGs and their recipe files.

    The files are the store. There is no index: the directory listing is
    the index, and a reference that is on disk is a reference that
    exists — which is the property that matters when a recipe is asked
    for three weeks later.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- writing ----------------------------------------------------------

    def save(self, png: bytes, recipe: dict, name: str = "",
             reference_id: str | None = None) -> Reference:
        """Write the image and its recipe, and return the reference.

        The image bytes are written exactly as given — the PNG is not
        decoded, re-encoded or inspected.

        The reference id is minted from a uuid4 unless the caller pins
        one. Pinning is how a retry lands on the same reference instead
        of creating a second one.

        Saving over an id that is already taken raises ``ValueError``. A
        reference id is a permanent public name for a saved result, and
        silently replacing what is behind it would make the name a lie.
        """
        if not png:
            raise ValueError("a reference needs an image")
        if not png.startswith(PNG_MAGIC):
            raise ValueError(
                "a reference needs a PNG; the bytes are not one")

        reference_id = (new_reference_id() if reference_id is None
                        else reference_id)
        if not SAFE_ID.match(reference_id):
            raise ValueError(f"unusable reference id: {reference_id!r}")

        png_path = self.root / f"{reference_id}.png"
        recipe_path = self.root / f"{reference_id}.json"
        if png_path.exists() or recipe_path.exists():
            raise ValueError(f"reference {reference_id} already exists")

        # Opened exclusively: the filesystem, not a check-then-write, is
        # what makes "never twice" true when two requests race.
        try:
            with png_path.open("xb") as handle:
                handle.write(png)
        except FileExistsError:
            raise ValueError(
                f"reference {reference_id} already exists") from None

        record = {
            "name": name or reference_id,
            "requirements": recipe.get("requirements") or {},
            "model_id": recipe.get("model_id") or "",
            "dialect": recipe.get("dialect") or "",
            "size": recipe.get("size") or "",
            "prompt": recipe.get("prompt") or "",
            "modifiers": list(recipe.get("modifiers") or ()),
            "critique": recipe.get("critique"),
            "created_at": float(recipe.get("created_at") or time.time()),
        }
        try:
            with recipe_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(record, indent=2, sort_keys=True))
        except FileExistsError:
            # The recipe lost the race; do not leave half a reference
            # behind.
            png_path.unlink(missing_ok=True)
            raise ValueError(
                f"reference {reference_id} already exists") from None

        return Reference(
            id=reference_id,
            png=png,
            name=record["name"],
            requirements=record["requirements"],
            model_id=record["model_id"],
            dialect=record["dialect"],
            size=record["size"],
            prompt=record["prompt"],
            modifiers=tuple(record["modifiers"]),
            critique=record["critique"],
            created_at=record["created_at"],
        )

    # -- reading ----------------------------------------------------------

    def get(self, reference_id: str) -> Reference | None:
        """The reference, or None if there is no such reference.

        The reference is the pair: the image and the recipe. A PNG
        without its recipe is a write that did not finish, and it is not
        a reference.
        """
        png = self.get_png(reference_id)
        recipe = self.get_recipe(reference_id)
        if png is None or recipe is None:
            return None
        return Reference(
            id=reference_id,
            png=png,
            name=recipe.get("name") or reference_id,
            requirements=recipe.get("requirements") or {},
            model_id=recipe.get("model_id") or "",
            dialect=recipe.get("dialect") or "",
            size=recipe.get("size") or "",
            prompt=recipe.get("prompt") or "",
            modifiers=tuple(recipe.get("modifiers") or ()),
            critique=recipe.get("critique"),
            created_at=float(recipe.get("created_at") or 0.0),
        )

    def get_png(self, reference_id: str) -> bytes | None:
        """The image bytes, exactly as they were written."""
        if not SAFE_ID.match(reference_id):
            return None
        path = self.root / f"{reference_id}.png"
        if not path.is_file():
            return None
        return path.read_bytes()

    def get_recipe(self, reference_id: str) -> dict | None:
        """The recipe, or None if this reference has none."""
        if not SAFE_ID.match(reference_id):
            return None
        path = self.root / f"{reference_id}.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def list(self, limit: int = 50) -> list[str]:
        """The reference ids, newest first.

        Newest first by the time the file was written, because that is
        how a person reads a list of work: the thing they saved a
        moment ago is at the top.

        Only complete references are listed. An image whose recipe never
        arrived is a write that did not finish, and offering it would be
        offering an id that resolves to nothing.
        """
        limit = max(0, int(limit))
        entries: list[tuple[int, str]] = []
        for png_path in self.root.glob("*.png"):
            reference_id = png_path.stem
            if not (self.root / f"{reference_id}.json").is_file():
                continue
            try:
                modified = png_path.stat().st_mtime_ns
            except OSError:
                continue
            entries.append((modified, reference_id))
        entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [reference_id for _, reference_id in entries[:limit]]

    # -- forgetting --------------------------------------------------------

    def delete(self, reference_id: str) -> bool:
        """Forget a reference. True if there was one."""
        if not SAFE_ID.match(reference_id):
            return False
        png_path = self.root / f"{reference_id}.png"
        recipe_path = self.root / f"{reference_id}.json"
        if not png_path.exists() and not recipe_path.exists():
            return False
        png_path.unlink(missing_ok=True)
        recipe_path.unlink(missing_ok=True)
        return True


def new_reference_id() -> str:
    """A reference id: the prefix and sixteen hex characters of a uuid4."""
    return f"{REFERENCE_ID_PREFIX}{uuid.uuid4().hex[:16]}"
