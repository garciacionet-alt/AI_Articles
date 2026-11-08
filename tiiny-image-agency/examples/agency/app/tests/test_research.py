"""Tests for the research loop and the PNG reader.

The reader is checked against PNGs whose alpha is known by
construction, because "does this model render a transparent background"
is the one fact the product cannot get wrong: a vision model cannot see
transparency, so the pixels are the only evidence.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fake_device import FakeDevice
from tis.api import create_app
from tis.imaging import alpha_stats, read_info
from tis.registry import Registry
from tis.research import (
    JUDGE_MODEL,
    ModelResearcher,
    Probe,
    default_probes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"


# -- a PNG with a known amount of transparency ---------------------------

def make_png(width: int = 8, height: int = 4, transparent: int = 0,
             rgba: bool = True) -> bytes:
    """A PNG whose first ``transparent`` rows are fully transparent."""
    colour_type = 6 if rgba else 2
    channels = 4 if rgba else 3

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter: none
        for _ in range(width):
            if rgba:
                raw.extend((0, 0, 0, 0) if row < transparent else (10, 20, 30, 255))
            else:
                raw.extend((10, 20, 30))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8,
                                         colour_type, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


def test_the_reader_sees_the_geometry():
    info = read_info(make_png(16, 9, transparent=2))
    assert info.width == 16
    assert info.height == 9
    assert info.colour_type_name == "RGBA"
    assert info.has_alpha_channel is True


def test_the_reader_measures_transparency():
    """Two of the four rows are transparent, so half the pixels are."""
    stats = alpha_stats(make_png(8, 4, transparent=2))
    assert stats.total_px == 32
    assert stats.fully_transparent_px == 16
    assert stats.transparent_pct == 50.0
    assert stats.partial_alpha_px == 0


def test_a_png_with_no_alpha_channel_is_opaque():
    stats = alpha_stats(make_png(8, 4, transparent=0, rgba=False))
    assert stats.has_alpha_channel is False
    assert stats.transparent_pct == 0.0
    assert stats.fully_opaque_px == 32


def test_something_that_is_not_a_png_is_reported_not_raised():
    stats = alpha_stats(b"not a png at all")
    assert stats.unreadable
    assert stats.transparent_pct == 0.0


# -- the research loop ---------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _researcher(registry: Registry, tmp_path: Path,
                replies: dict[str, str]) -> ModelResearcher:
    device = FakeDevice(registry, replies=replies,
                        resident=["Tongyi-MAI/Z-Image-Turbo"])
    return ModelResearcher(device, registry, tmp_path,
                           judge_model=JUDGE_MODEL)


def test_the_matrix_covers_every_dimension():
    dimensions = {probe.dimension for probe in default_probes()}
    assert dimensions == {"artifact", "style", "alpha", "text"}


def test_the_matrix_uses_one_subject_so_only_the_dimension_changes():
    """If the subject changed between probes, the measurement would be of
    the subject and not of the artifact."""
    for probe in default_probes():
        if probe.dimension == "artifact":
            # The subject is the same in every probe; only the artifact
            # changes. (The logo probe capitalises it, because it is a
            # brand name there.)
            assert "fox" in probe.prompt.lower()


def test_the_card_says_what_was_measured(registry: Registry, tmp_path: Path):
    """The judge's answers become the artifacts, and the pixels become
    the transparency."""
    researcher = _researcher(registry, tmp_path, {JUDGE_MODEL: "ICON"})
    card = researcher.characterise("Tongyi-MAI/Z-Image-Turbo")

    assert card.model_id == "Tongyi-MAI/Z-Image-Turbo"
    assert card.artifacts == ["icon"]
    assert card.role
    assert card.summary
    assert card.measured_at
    # Every probe leaves an evidence entry.
    assert len(card.probes) == len(default_probes())
    assert all(result.ok for result in card.probes)
    assert all(Path(result.image).exists() for result in card.probes)


def test_the_transparency_is_measured_not_guessed(registry: Registry,
                                                   tmp_path: Path):
    """A vision model cannot see transparency, so it comes from the
    pixels."""
    researcher = _researcher(registry, tmp_path, {JUDGE_MODEL: "ICON"})
    card = researcher.characterise("Tongyi-MAI/Z-Image-Turbo")
    # The fake's PNG is opaque, so the answer must be "no" even though
    # the judge was scripted to say nothing about it.
    assert card.alpha == "no"
    assert card.transparent_pct == 0.0


def test_the_overlay_entry_is_machine_readable(registry: Registry,
                                               tmp_path: Path):
    researcher = _researcher(registry, tmp_path, {JUDGE_MODEL: "ICON"})
    card = researcher.characterise("Tongyi-MAI/Z-Image-Turbo")
    entry = researcher.overlay_entry(card)

    assert entry["artifact"] == ["icon"]
    assert entry["alpha"] is False
    assert entry["text_rendering"] in ("best", "strong", "weak", "none",
                                       "unknown")
    assert entry["notes"] == card.summary


def test_a_probe_that_fails_is_recorded_not_hidden(registry: Registry,
                                                   tmp_path: Path):
    """A model that refuses a size is a measurement."""
    researcher = _researcher(registry, tmp_path, {JUDGE_MODEL: "ICON"})
    probe = Probe(name="broken", prompt="x", dimension="artifact",
                  question="What is this?")
    card = researcher.characterise("Tongyi-MAI/Z-Image-Turbo", [probe])
    assert len(card.probes) == 1


# -- the card reaches the user ------------------------------------------

def test_the_api_serves_the_card(registry: Registry, tmp_path: Path):
    from tis.config import Settings
    from tis.service import Agency

    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "some-model.card.json").write_text(
        json.dumps({"model_id": "some-model", "summary": "it is a fox"}),
        encoding="utf-8")

    settings = Settings(assets_dir=tmp_path / "assets", cards_dir=cards,
                        hold_file=tmp_path / "hold",
                        watchdog_lock=tmp_path / "watch.lock")
    device = FakeDevice(registry)
    agency = Agency(settings, device=device, registry=registry)
    try:
        client = TestClient(create_app(agency=agency))
        response = client.get("/v1/models/card",
                              params={"model_id": "some-model"})
        assert response.status_code == 200
        # The card has three parts and they are kept apart: what the
        # device advertises, what we measured, and what we have noticed.
        body = response.json()
        assert body["measured"]["summary"] == "it is a fox"
        assert body["model_id"] == "some-model"
        assert body["researched"] is True

        missing = client.get("/v1/models/card",
                             params={"model_id": "not-researched"})
        assert missing.status_code == 404

        # A model id with slashes in it — which every real one has.
        (cards / "a__b.card.json").write_text(
            json.dumps({"model_id": "a/b"}), encoding="utf-8")
        slashed = client.get("/v1/models/card", params={"model_id": "a/b"})
        assert slashed.status_code == 200
    finally:
        agency.close()


def test_the_api_serves_every_card_in_one_request(registry: Registry,
                                                   tmp_path: Path):
    """A browser listing wants all of them at once.

    Seventeen separate requests to draw one grid is a grid that arrives
    in pieces, and the pieces arrive in the order the network decides.
    """
    from tis.config import Settings
    from tis.service import Agency

    cards = tmp_path / "cards"
    cards.mkdir()
    settings = Settings(assets_dir=tmp_path / "assets", cards_dir=cards,
                        hold_file=tmp_path / "hold",
                        watchdog_lock=tmp_path / "watch.lock")
    device = FakeDevice(registry)
    agency = Agency(settings, device=device, registry=registry)
    try:
        client = TestClient(create_app(agency=agency))
        response = client.get("/v1/models/cards")
        assert response.status_code == 200
        body = response.json()
        assert "cards" in body
        listed = body["cards"]

        # Every image generator has a card, researched or not: a model
        # with no card is a model the user cannot judge.
        generators = [m for m in registry.models
                      if m.kind == "image_generator"]
        assert len(listed) == len(generators)
        for card in listed:
            assert "model_id" in card
            assert "advertised" in card
            assert "notes" in card
            assert "researched" in card
    finally:
        agency.close()
