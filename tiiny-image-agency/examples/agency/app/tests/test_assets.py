"""Tests for the asset store: the image on disk, byte for byte, and the
provenance beside it.

The PNG is the product, and the alpha channel is the part everybody
accidentally destroys. So the central test here is not "a PNG comes back"
but "the same bytes come back", compared with ==, on a hand-built RGBA
image with transparent pixels.
"""
import json
import os
import re
import struct
import time
import uuid
import zlib
from pathlib import Path

import pytest

import tis.assets
from tis.assets import Asset, AssetStore

ASSET_ID = re.compile(r"^ast_[0-9a-f]{16}$")

LINEAGE = {
    "requirements": {
        "artifact": "icon",
        "alpha": "required",
        "width": 1024,
        "height": 1024,
    },
    "model_id": "Qwen/Qwen-Image-2.1",
    "prompt": "A flat vector icon of a fox head, transparent background.",
    "size": "1024x1024",
    "attempts": 2,
    "critique": {"passed": False, "reasons": ["the ears are too rounded"]},
    "created_at": 1762000000.0,
    "updated_at": 1762000048.2,
    "job_id": "job_0123456789abcdef",
}


def _rgba_png(width: int = 2, height: int = 2, alpha: int = 0) -> bytes:
    """A real PNG with an alpha channel and fully transparent pixels.

    Built by hand rather than with an imaging library, because a library
    round trip is exactly the thing that can quietly re-encode the image
    and drop the alpha channel. The bytes here are the bytes the appliance
    produced.
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    # 8 bits per channel, colour type 6 = RGBA.
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b""
    for _ in range(height):
        # One filter byte (0 = none) then the pixels, red with the alpha.
        raw += b"\x00" + bytes([255, 0, 0, alpha] * width)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


@pytest.fixture
def store(tmp_path: Path) -> AssetStore:
    return AssetStore(tmp_path / "assets")


def test_save_writes_a_png_and_a_lineage_file(store: AssetStore):
    asset = store.save(_rgba_png(), LINEAGE)

    assert isinstance(asset, Asset)
    assert (store.root / f"{asset.id}.png").exists()
    assert (store.root / f"{asset.id}.json").exists()


def test_the_asset_id_has_the_expected_shape(store: AssetStore):
    asset = store.save(_rgba_png(), LINEAGE)

    assert ASSET_ID.match(asset.id), asset.id
    assert asset.id.startswith("ast_")
    assert len(asset.id) == len("ast_") + 16


def test_the_png_bytes_survive_byte_for_byte(store: AssetStore):
    image = _rgba_png()
    asset = store.save(image, LINEAGE)

    stored = store.get_png(asset.id)

    assert stored == image
    assert stored[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(stored) == len(image)


def _chunks(png: bytes) -> dict[bytes, bytes]:
    """The chunks of a PNG, by tag."""
    found: dict[bytes, bytes] = {}
    offset = 8  # past the signature
    while offset < len(png):
        length = struct.unpack(">I", png[offset:offset + 4])[0]
        tag = png[offset + 4:offset + 8]
        found[tag] = png[offset + 8:offset + 8 + length]
        offset += 12 + length
    return found


def test_the_alpha_channel_is_not_stripped(store: AssetStore):
    image = _rgba_png(alpha=0)
    asset = store.save(image, LINEAGE)

    stored = store.get_png(asset.id)

    assert stored == image
    chunks = _chunks(stored)
    # Colour type 6 is RGBA; a stripped alpha would make it 2 (RGB).
    assert chunks[b"IHDR"][9] == 6
    # The transparent pixel survives in the decompressed scanlines.
    raw = zlib.decompress(chunks[b"IDAT"])
    assert raw[-4:] == bytes([255, 0, 0, 0])


def test_the_asset_round_trips_with_its_png_and_lineage(store: AssetStore):
    image = _rgba_png()
    asset = store.save(image, LINEAGE)

    fetched = store.get(asset.id)

    assert fetched is not None
    assert fetched.id == asset.id
    assert fetched.image == image
    assert fetched.format == "png"
    assert fetched.lineage == LINEAGE


def test_the_lineage_round_trips_as_a_dict(store: AssetStore):
    asset = store.save(_rgba_png(), LINEAGE)

    lineage = store.get_lineage(asset.id)

    assert isinstance(lineage, dict)
    assert lineage == LINEAGE
    assert lineage["requirements"]["alpha"] == "required"
    assert lineage["attempts"] == 2
    assert lineage["job_id"] == "job_0123456789abcdef"


def test_the_lineage_json_is_indented_and_sorted(store: AssetStore):
    asset = store.save(_rgba_png(), LINEAGE)

    raw = (store.root / f"{asset.id}.json").read_text(encoding="utf-8")

    assert json.loads(raw) == LINEAGE
    assert "\n  " in raw
    assert raw.index('"attempts"') < raw.index('"model_id"')


def test_get_returns_none_for_an_unknown_id(store: AssetStore):
    assert store.get("ast_0000000000000000") is None


def test_get_png_returns_none_for_an_unknown_id(store: AssetStore):
    assert store.get_png("ast_0000000000000000") is None


def test_get_lineage_returns_none_for_an_unknown_id(store: AssetStore):
    assert store.get_lineage("ast_0000000000000000") is None


def test_saving_the_same_asset_id_twice_raises_value_error(store: AssetStore):
    """An asset id is a permanent public name; it is never reused."""
    store.save(_rgba_png(), LINEAGE, asset_id="ast_0123456789abcdef")

    with pytest.raises(ValueError):
        store.save(_rgba_png(), LINEAGE, asset_id="ast_0123456789abcdef")


def test_a_collision_in_the_generated_id_is_refused(store: AssetStore,
                                                     monkeypatch):
    """The store mints the id, so a collision is only reachable by pinning
    the generator — and it must still be refused rather than overwrite."""
    monkeypatch.setattr(tis.assets.uuid, "uuid4", lambda: uuid.UUID(int=0))

    store.save(_rgba_png(), LINEAGE)
    with pytest.raises(ValueError):
        store.save(_rgba_png(), LINEAGE)


def test_saving_over_an_existing_id_does_not_overwrite_the_image(
        store: AssetStore):
    image = _rgba_png()
    asset = store.save(image, LINEAGE)

    with pytest.raises(ValueError):
        store.save(b"not a png at all", LINEAGE, asset_id=asset.id)

    assert store.get_png(asset.id) == image


def test_list_returns_the_asset_ids_newest_first(store: AssetStore):
    first = store.save(_rgba_png(), LINEAGE)
    time.sleep(0.01)
    second = store.save(_rgba_png(), LINEAGE)
    time.sleep(0.01)
    third = store.save(_rgba_png(), LINEAGE)

    assert store.list() == [third.id, second.id, first.id]


def test_list_honours_the_limit(store: AssetStore):
    for _ in range(5):
        store.save(_rgba_png(), LINEAGE)
        time.sleep(0.01)

    assert len(store.list(limit=2)) == 2
    assert len(store.list()) == 5


def test_list_is_empty_for_an_empty_store(store: AssetStore):
    assert store.list() == []


def test_a_known_asset_can_be_read_back_after_the_store_is_reopened(
        tmp_path: Path):
    root = tmp_path / "assets"
    asset = AssetStore(root).save(_rgba_png(), LINEAGE)

    reopened = AssetStore(root)

    assert reopened.get(asset.id).image == _rgba_png()
    assert reopened.get_lineage(asset.id) == LINEAGE
    assert reopened.list() == [asset.id]


def test_an_id_that_could_walk_out_of_the_directory_is_refused(
        store: AssetStore):
    """The id becomes a file name, so it must not be able to escape."""
    for bad in ("../escape", "ast_../../escape", "ast_a/b", ""):
        with pytest.raises(ValueError):
            store.save(_rgba_png(), LINEAGE, asset_id=bad)

    assert store.get_png("../escape") is None
    assert store.get_lineage("../escape") is None

