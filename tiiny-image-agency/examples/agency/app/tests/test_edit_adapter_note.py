"""Tests for what the model cards say about the edit adapters.

THE GAP, STATED ON THE CARD
----------------------------
An edit adapter is CHOSEN for an edit request — the resolver knows it
is the model for "remove the background" — but the Agency does not yet
send the source image with the request. ``Device.generate`` takes a
model, a prompt and a size, and nothing else.

So an edit request today resolves to the right model and then makes a
new picture rather than editing the one that was uploaded.

THE NOTE EXISTS SO THAT IS NOT A SURPRISE
------------------------------------------
The card is where a person goes to find out what a model actually does.
If the card says an adapter is the one for removing a background and
says nothing about the image never arriving, the card is telling a
half-truth — and the half it withholds is the half that matters.

The note is therefore not decoration. It is the difference between a
card that can be trusted and one that cannot.

AND IT IS AN INVARIANT, NOT A ONE-OFF
-------------------------------------
A fifth adapter added later must carry the note too, so the rule is
enforced over the registry rather than written into four places.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

#: What the note has to say, in enough words that nobody can mistake
#: it for a complaint about the model.
THE_FACT = "source image"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def test_the_registry_has_edit_adapters(registry: Registry):
    """If this fails, the rule below has nothing to say."""
    adapters = [m for m in registry.models if m.role == "edit-adapter"]
    assert adapters, "no edit adapters in the registry"


def test_every_edit_adapter_says_the_source_image_is_not_sent(
        registry: Registry):
    """Each adapter's notes name the gap.

    Read from the REGISTRY rather than from the overlay, because the
    registry is what the card is built from — and the registry is
    rebuilt from the overlay. A note that lives only in the overlay
    would be lost the next time somebody rebuilt it by hand.
    """
    for model in registry.models:
        if model.role != "edit-adapter":
            continue
        notes = (model.notes or "").lower()
        assert THE_FACT in notes, (
            f"{model.id} is an edit adapter but its notes do not mention "
            f"the {THE_FACT}")
        assert "not" in notes or "yet" in notes, (
            f"{model.id} mentions the {THE_FACT} but does not say what is "
            "not happening")


def test_a_generator_is_not_given_the_edit_adapter_note(registry: Registry):
    """The note belongs to the adapters and to nothing else."""
    for model in registry.models:
        if model.role == "edit-adapter":
            continue
        notes = (model.notes or "").lower()
        assert "does not send" not in notes, (
            f"{model.id} is not an edit adapter but carries the "
            "edit-adapter note")


def test_the_card_shows_the_note(registry: Registry, tmp_path: Path):
    """The note is on the CARD, which is where a person looks."""
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=PROJECT_ROOT / "registry" / "roles.json",
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
    )
    from fake_device import FakeDevice

    agency = Agency(settings, device=FakeDevice(registry), registry=registry)
    try:
        cards = {card["model_id"]: card
                 for card in agency.all_model_cards()}
        adapter = next(m for m in registry.models if m.role == "edit-adapter")
        assert THE_FACT in cards[adapter.id]["notes"].lower()
    finally:
        agency.close()
