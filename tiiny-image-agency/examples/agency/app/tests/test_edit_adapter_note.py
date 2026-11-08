"""Tests for what the model cards say about the source image.

THE GAP, NOW CLOSED
-------------------
An edit adapter is CHOSEN for an edit request, and the Agency now
sends the source image with the request — the bytes go to the
appliance in the ``image`` field, which is the field the appliance was
measured to read.

But sending it is only half of it. What the appliance DOES with the
image is a separate fact, and it was measured: of the fifteen models,
only three honour a source image, and only one of those three is an
edit adapter.

So the cards have to say both things: that the image is sent, and
whether the adapter uses it. A card that says the image is sent and
does not say whether it is used is telling half the story.

AND THE CARD HAS TO AGREE WITH THE MEASUREMENT
----------------------------------------------
The card's claim about the source image is checked against the
measured ``image_input`` value, so a card cannot drift away from what
the appliance actually does. An adapter that honours the image says so;
an adapter that ignores it says so; an adapter the judge could not
classify says that too.

AND IT IS AN INVARIANT, NOT A ONE-OFF
--------------------------------------
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

#: What each measured answer has to sound like.
CLAIM = {
    "yes": ("honours",),
    "no": ("ignores",),
    "unknown": ("too close to call",),
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def test_the_registry_has_edit_adapters(registry: Registry):
    """If this fails, the rule below has nothing to say."""
    adapters = [m for m in registry.models if m.role == "edit-adapter"]
    assert adapters, "no edit adapters in the registry"


def test_every_edit_adapter_says_what_happens_to_the_source_image(
        registry: Registry):
    """Each adapter's notes name the source image and say what becomes
    of it.

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


def test_the_card_agrees_with_the_measurement(registry: Registry):
    """A card that claims the adapter honours the image when the
    measurement says it does not is worse than no card."""
    for model in registry.models:
        if model.role != "edit-adapter":
            continue
        notes = (model.notes or "").lower()
        measured = model.image_input
        assert measured in CLAIM, (
            f"{model.id} has an image_input this test does not know: "
            f"{measured!r}")
        for phrase in CLAIM[measured]:
            assert phrase in notes, (
                f"{model.id} measured image_input={measured!r} but its "
                f"notes do not say {phrase!r}")


def test_a_generator_is_not_given_the_edit_adapter_note(registry: Registry):
    """The note belongs to the adapters and to nothing else."""
    for model in registry.models:
        if model.role == "edit-adapter":
            continue
        notes = (model.notes or "").lower()
        assert "the source image is wired" not in notes, (
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
