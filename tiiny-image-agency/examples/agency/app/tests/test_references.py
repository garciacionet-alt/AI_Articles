"""Tests for the reference store.

A reference is a saved result, kept so the NEXT one comes out like it.
It is two things: the PNG, byte for byte, and the recipe that made it —
the model, the dialect, the size, the requirements, the modifiers, and
what the judge said.

The PNG is stored exactly as it arrived, for the same reason assets are:
a round trip through an image library is precisely where a transparent
background quietly becomes an opaque one. A reference whose transparency
is a lie is worse than no reference.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tis.references import ReferenceStore

#: A real PNG header — the store checks the magic bytes so a JPEG
#: cannot masquerade as an image the models never saw.
PNG = b"\x89PNG\r\n\x1a\n" + b"the original bytes, untouched"

RECIPE = {
    "requirements": {"artifact": "icon", "alpha": "required"},
    "model_id": "Tongyi-MAI/Z-Image-Turbo",
    "dialect": "Plain descriptive English.",
    "size": "1024x1024",
    "prompt": "A flat vector icon of a fox head.",
    "modifiers": ["warmer fill"],
    "critique": {"passed": True, "reasons": []},
}


@pytest.fixture
def store(tmp_path: Path) -> ReferenceStore:
    return ReferenceStore(tmp_path / "references")


def test_a_reference_keeps_the_bytes_it_was_given(store: ReferenceStore):
    """The whole point of a transparent model is the alpha channel."""
    reference = store.save(PNG, RECIPE, name="newsletter header")
    assert store.get(reference.id).png == PNG


def test_a_reference_keeps_the_recipe(store: ReferenceStore):
    reference = store.save(PNG, RECIPE, name="newsletter header")
    fetched = store.get(reference.id)
    assert fetched.model_id == "Tongyi-MAI/Z-Image-Turbo"
    assert fetched.dialect == "Plain descriptive English."
    assert fetched.size == "1024x1024"
    assert fetched.prompt == "A flat vector icon of a fox head."
    assert fetched.modifiers == ("warmer fill",)
    assert fetched.requirements["alpha"] == "required"
    assert fetched.name == "newsletter header"


def test_a_reference_id_looks_like_a_reference(store: ReferenceStore):
    reference = store.save(PNG, RECIPE, name="x")
    assert reference.id.startswith("ref_")


def test_a_reference_is_not_png_is_refused(store: ReferenceStore):
    with pytest.raises(ValueError):
        store.save(b"\xff\xd8\xff\xe0 not a png", RECIPE, name="x")


def test_an_empty_reference_is_refused(store: ReferenceStore):
    with pytest.raises(ValueError):
        store.save(b"", RECIPE, name="x")


def test_saving_the_same_id_twice_is_refused(store: ReferenceStore):
    reference = store.save(PNG, RECIPE, name="x")
    with pytest.raises(ValueError):
        store.save(PNG, RECIPE, name="x", reference_id=reference.id)


def test_an_unusable_id_is_refused(store: ReferenceStore):
    with pytest.raises(ValueError):
        store.save(PNG, RECIPE, name="x", reference_id="../escape")


def test_a_missing_reference_is_none(store: ReferenceStore):
    assert store.get("ref_nothing") is None
    assert store.get_png("ref_nothing") is None
    assert store.get_recipe("ref_nothing") is None


def test_the_list_is_newest_first(store: ReferenceStore):
    first = store.save(PNG, RECIPE, name="one")
    second = store.save(PNG, RECIPE, name="two")
    listed = store.list()
    assert listed[0] == second.id
    assert listed[1] == first.id


def test_a_reference_can_be_forgotten(store: ReferenceStore):
    reference = store.save(PNG, RECIPE, name="x")
    assert store.delete(reference.id) is True
    assert store.get(reference.id) is None
    assert store.delete(reference.id) is False


def test_the_recipe_is_readable_without_the_png(store: ReferenceStore):
    """The list of references is a list of recipes, not a gallery."""
    reference = store.save(PNG, RECIPE, name="newsletter header")
    recipe = store.get_recipe(reference.id)
    assert recipe["model_id"] == "Tongyi-MAI/Z-Image-Turbo"
    assert recipe["name"] == "newsletter header"


def test_the_recipe_is_written_as_sorted_json(store: ReferenceStore):
    """Two lineages for the same job must diff cleanly."""
    reference = store.save(PNG, RECIPE, name="x")
    path = Path(store.root) / f"{reference.id}.json"
    text = path.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True)


def test_a_reference_with_no_critique_is_fine(store: ReferenceStore):
    """A reference can be saved from a generation the judge skipped."""
    recipe = dict(RECIPE)
    recipe.pop("critique")
    reference = store.save(PNG, recipe, name="x")
    assert store.get(reference.id).critique is None
