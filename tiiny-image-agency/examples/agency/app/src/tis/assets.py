"""The asset store: the delivered image and the record of how it was made.

An asset is two files: the PNG and its lineage. Splitting them is
deliberate. The PNG is the product — an icon with a transparent
background is worth nothing if the background comes back white — and the
lineage is the provenance: what was asked for, which model was chosen and
why, which prompts were sent, what the critic said. One is served to a
browser, the other is served to whoever asks "why is this icon shaped
like that?" three weeks later.

THE IMAGE IS WRITTEN AS IT ARRIVES
----------------------------------
The bytes go to disk exactly as the device produced them, and exactly
as an uploader sent them. Nothing here decodes, re-encodes or re-saves
an image. A round trip through an image library is exactly where a
transparent background quietly becomes an opaque one, and the alpha
channel is the reason the flagship model is worth its 62% of the NPU.

TWO FORMATS, AND THE FORMAT IS DERIVED NOT DECLARED
----------------------------------------------------
The agency stores PNG and JPEG. It knows which is which from the
magic bytes, not from what the caller says — a caller cannot make a
JPEG into a PNG by calling it one, and the file extension follows the
bytes rather than the other way round.

A JPEG is accepted, not converted. The appliance decodes it to pixels
itself, so converting it at upload would produce exactly the same
picture and would cost a re-encode that can only lose what the JPEG
already lost. What the JPEG DID lose is its alpha channel, and that
loss happened before the agency ever saw the file — so the lineage
names it rather than leaving the caller to discover it later.

THE LINEAGE IS THE CALLER'S TO WRITE
------------------------------------
The store does not know what a requirement vector or a critique is — and
must not, because the resolver and the orchestrator are not its business.
The caller hands over a lineage dict and the store writes it down
faithfully, sorted and indented so that two lineages for the same request
diff cleanly. The SHAPE is the caller's too, and there is exactly one
writer of a lineage - the service - so there is exactly one shape. A
builder in this module would be a second one, and the two would drift.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The prefix on every asset id, so an id in a URL says what it is.
ASSET_ID_PREFIX = "ast_"

#: What an asset id must look like. An id becomes a file name, and a file
#: name may not walk out of the assets directory — so an id that is not
#: safe is answered with "no such asset" rather than being read from
#: somewhere it should not be.
SAFE_ID = re.compile(r"^ast_[A-Za-z0-9._-]{1,64}$")

#: The eight bytes every PNG starts with.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: The first three bytes of every JPEG.
JPEG_MAGIC = b"\xff\xd8\xff"

#: The file extension for each format the agency accepts, and the
#: content type it is served as. The extension follows the BYTES.
FORMATS: dict[str, tuple[str, str]] = {
    "png": (".png", "image/png"),
    "jpeg": (".jpg", "image/jpeg"),
}


def image_format(data: bytes) -> str:
    """The format of these bytes: 'png', 'jpeg', or 'unknown'.

    Identified by its magic, not by decoding it. The agency does not
    decode images — the appliance does — and a JPEG made by something
    other than `sips` is still a JPEG.
    """
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    return "unknown"


@dataclass(frozen=True)
class Asset:
    """One delivered image and the lineage that explains it."""

    id: str
    image: bytes
    lineage: dict
    format: str


class AssetStore:
    """A directory of PNGs and their lineage files.

    The files are the store. There is no index: the directory listing is
    the index, and an asset that is on disk is an asset that exists —
    which is the property that matters when the API is asked for an
    image that was generated an hour ago.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- writing ----------------------------------------------------------

    def save(self, image: bytes, lineage: dict,
             asset_id: str | None = None) -> Asset:
        """Write an image and its lineage, and return the asset.

        The image bytes are written exactly as given — the PNG is not
        decoded, re-encoded or inspected. The format is DERIVED from
        those bytes, and the file extension follows it, so a JPEG is
        never stored under a name that claims to be a PNG.

        The asset id is minted from a uuid4 unless the caller pins one.
        Pinning is how the API can hand out an id before the generation
        has finished, and how a retry lands on the same asset instead of
        creating a second one.

        Saving over an id that is already taken raises ``ValueError``. An
        asset id is a permanent public name for a delivered file, and
        silently replacing what is behind it would make the name a lie.
        """
        asset_id = _new_asset_id() if asset_id is None else asset_id
        if not SAFE_ID.match(asset_id):
            raise ValueError(f"unusable asset id: {asset_id!r}")

        image_format_name = image_format(image)
        if image_format_name not in FORMATS:
            raise ValueError(
                f"cannot store a {image_format_name} image; the agency "
                "stores PNG and JPEG")
        extension, _ = FORMATS[image_format_name]

        image_path = self.root / f"{asset_id}{extension}"
        lineage_path = self.root / f"{asset_id}.json"
        if image_path.exists() or lineage_path.exists():
            raise ValueError(f"asset {asset_id} already exists")

        # Opened exclusively: the filesystem, not a check-then-write, is
        # what makes "never twice" true when two requests race.
        try:
            with image_path.open("xb") as handle:
                handle.write(image)
        except FileExistsError:
            raise ValueError(f"asset {asset_id} already exists") from None
        try:
            with lineage_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(lineage, indent=2, sort_keys=True))
        except FileExistsError:
            # The lineage lost the race; do not leave half an asset behind.
            image_path.unlink(missing_ok=True)
            raise ValueError(f"asset {asset_id} already exists") from None
        return Asset(id=asset_id, image=image, lineage=lineage,
                     format=image_format_name)

    # -- reading ----------------------------------------------------------

    def get(self, asset_id: str) -> Asset | None:
        """The asset, or None if there is no such asset.

        An asset is the pair: the image and its lineage. An image without
        its lineage is a write that did not finish, and it is not an
        asset.
        """
        image = self.get_image(asset_id)
        lineage = self.get_lineage(asset_id)
        if image is None or lineage is None:
            return None
        return Asset(id=asset_id, image=image, lineage=lineage,
                     format=image_format(image))

    def get_image(self, asset_id: str) -> bytes | None:
        """The image bytes, exactly as they were written."""
        path = self._image_path(asset_id)
        if path is None:
            return None
        return path.read_bytes()

    def get_png(self, asset_id: str) -> bytes | None:
        """The PNG of this asset, or None if it is not a PNG.

        Kept because "is this a PNG?" is a real question, and None is
        an honest answer to it. A JPEG asset has no PNG, and saying so
        is better than handing back the JPEG under a PNG's name.
        """
        path = self._image_path(asset_id)
        if path is None or path.suffix != ".png":
            return None
        return path.read_bytes()

    def _image_path(self, asset_id: str) -> Path | None:
        """Where this asset's image lives, or None if it has none.

        The extension is part of the format, so the file is found by
        asking for each extension the agency stores. An id that is not
        safe is never turned into a path at all.
        """
        if not SAFE_ID.match(asset_id):
            return None
        for extension, _ in FORMATS.values():
            path = self.root / f"{asset_id}{extension}"
            if path.is_file():
                return path
        return None

    def get_lineage(self, asset_id: str) -> dict | None:
        """The lineage, or None if this asset has none."""
        if not SAFE_ID.match(asset_id):
            return None
        path = self.root / f"{asset_id}.json"
        if not path.is_file():
            return None
        lineage = json.loads(path.read_text(encoding="utf-8"))
        return lineage if isinstance(lineage, dict) else None

    def list(self, limit: int = 50) -> list[str]:
        """The asset ids, newest first.

        Newest first by the time the file was written, because that is
        how a person reads a list of work: the thing they asked for a
        moment ago is at the top.

        Only complete assets are listed. An image whose lineage never
        arrived is a write that did not finish, and offering it would be
        offering an id that resolves to nothing.
        """
        limit = max(0, int(limit))
        entries: list[tuple[int, str]] = []
        for extension, _ in FORMATS.values():
            for image_path in self.root.glob(f"*{extension}"):
                asset_id = image_path.stem
                if not (self.root / f"{asset_id}.json").is_file():
                    continue
                try:
                    modified = image_path.stat().st_mtime_ns
                except OSError:
                    continue
                entries.append((modified, asset_id))
        entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [asset_id for _, asset_id in entries[:limit]]


def _new_asset_id() -> str:
    """An asset id: the prefix and sixteen hex characters of a uuid4."""
    return f"{ASSET_ID_PREFIX}{uuid.uuid4().hex[:16]}"
