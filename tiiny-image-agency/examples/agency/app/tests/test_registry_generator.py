"""Tests for the curated overlay and the registry generator that consumes it.

These are pure file tests — no device, no network.
"""
import json
import sys
from pathlib import Path

# The project root is two levels up from this file: app/tests -> app -> root.
# tools/ has no __init__.py; Python 3 namespace packages make
# `from tools.build_registry import ...` work once the root is on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from tools.build_registry import load_overlay

OVERLAY_PATH = PROJECT_ROOT / "app" / "data" / "overlay.yaml"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

REQUIRED_KEYS = [
    "role",
    "artifact",
    "alpha",
    "text_rendering",
    "style",
    "edit_ops",
    "quality",
    "speed",
    "dialect",
    "provenance",
]

# d = documented by the vendor, m = measured on the device,
# i = inferred, a = aggregated. Combinations are written "d,m".
ALLOWED_PROVENANCE = {"d", "m", "i", "a"}


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_overlay_file_exists_and_parses():
    """The overlay exists and parses into the expected shape."""
    assert OVERLAY_PATH.exists(), f"overlay.yaml should exist at {OVERLAY_PATH}"
    assert OVERLAY_PATH.is_file()

    data = yaml.safe_load(OVERLAY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "overlay.yaml should parse to a dict"
    assert "models" in data, "overlay.yaml should have a 'models' key"
    assert isinstance(data["models"], dict), "overlay.yaml 'models' should be a mapping"


def test_overlay_covers_every_registry_model():
    """Every model in the registry has an overlay entry, and both enhancers are present.

    The expected set is computed from the registry rather than hardcoded, so
    this test fails when the device catalogue gains a model and the curated
    layer has not caught up.
    """
    registry = _registry()
    overlay = load_overlay()

    generators = {m["id"] for m in registry["models"] if m["kind"] == "image_generator"}
    enhancers = {m["id"] for m in registry["models"] if m["kind"] == "prompt_enhancer"}

    assert generators, "the registry should contain image generators"
    assert len(enhancers) == 2, f"expected 2 prompt enhancers, found {len(enhancers)}"

    missing = generators - set(overlay)
    assert not missing, f"overlay is missing image generators: {sorted(missing)}"

    missing_enhancers = enhancers - set(overlay)
    assert not missing_enhancers, f"overlay is missing prompt enhancers: {sorted(missing_enhancers)}"


def test_overlay_entries_have_required_keys():
    """Every overlay entry carries the fields the resolver relies on."""
    overlay = load_overlay()
    assert overlay, "the overlay should not be empty"

    for model_id, entry in overlay.items():
        for key in REQUIRED_KEYS:
            assert key in entry, f"model {model_id} is missing required key {key}"


def test_overlay_provenance_values():
    """Provenance is one of the allowed tiers, or a combination of them."""
    overlay = load_overlay()

    for model_id, entry in overlay.items():
        provenance = entry.get("provenance", "")
        assert provenance, f"model {model_id} has no provenance"
        for part in provenance.split(","):
            assert part.strip() in ALLOWED_PROVENANCE, (
                f"invalid provenance {part.strip()!r} in model {model_id}"
            )


def test_overlay_artifacts_match_the_registry():
    """The curated layer must reproduce the registry's merged output exactly.

    This is the regression test for the overlay move. YAML's block scalars
    append a trailing newline to every string, which silently changed all 36
    dialect and notes values when the overlay moved from Python to YAML. The
    generator now strips trailing whitespace on load, so every curated field
    must match the registry exactly.
    """
    registry = _registry()
    overlay = load_overlay()

    # Which part of the merged registry each overlay field lands in.
    SPECIALTY_FIELDS = {
        "artifact", "alpha", "text_rendering", "style", "edit_ops",
        "quality", "speed",
    }
    PROMPTING_FIELDS = {"dialect", "sizes_verified", "sizes_rejected", "rejected_reason"}
    TOP_LEVEL_FIELDS = {"role", "notes", "provenance"}

    checked = 0
    for model in registry["models"]:
        entry = overlay.get(model["id"])
        if entry is None:
            continue
        for field, value in entry.items():
            if field in SPECIALTY_FIELDS:
                actual = model["specialty"].get(field)
            elif field in PROMPTING_FIELDS:
                actual = model["prompting"].get(field)
            elif field in TOP_LEVEL_FIELDS:
                actual = model.get(field)
            else:
                continue
            assert actual == value, (
                f"overlay drift for {model['id']}.{field}:\n"
                f"  overlay : {value!r}\n"
                f"  registry: {actual!r}"
            )
            checked += 1

    assert checked > 100, f"expected to check many fields, only checked {checked}"


def test_registry_strings_have_no_trailing_whitespace():
    """No curated string in the registry ends in whitespace.

    A trailing newline is invisible in review and changes the file's bytes.
    """
    registry = _registry()
    offenders = []
    for model in registry["models"]:
        for section in ("specialty", "prompting"):
            for field, value in (model.get(section) or {}).items():
                if isinstance(value, str) and value != value.rstrip():
                    offenders.append(f"{model['id']}.{section}.{field}")
        notes = model.get("notes")
        if isinstance(notes, str) and notes != notes.rstrip():
            offenders.append(f"{model['id']}.notes")
    assert not offenders, f"trailing whitespace in: {offenders}"
