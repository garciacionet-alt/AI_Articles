"""Tests for the registry loader."""
import json
from pathlib import Path

import pytest

from tis.registry import (
    COMMUNITY_MODEL_IDS,
    ModelSpec,
    PlannerSpec,
    Registry,
    RegistryError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"


@pytest.fixture
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def test_registry_loads_real_registry(registry: Registry):
    assert len(registry.generators) == 15
    assert len(registry.enhancers) == 2
    assert len(registry) == 17
    assert registry.planner.id == "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"
    assert registry.planner.npu_usage == 55
    assert isinstance(registry.planner, PlannerSpec)


def test_registry_by_id_round_trip(registry: Registry):
    model = registry.by_id("Qwen/Qwen-Image-2.1")
    assert model.id == "Qwen/Qwen-Image-2.1"
    assert isinstance(model, ModelSpec)

    with pytest.raises(RegistryError) as excinfo:
        registry.by_id("nonexistent")
    assert "nonexistent" in str(excinfo.value)


def test_registry_find_returns_none_for_unknown_id(registry: Registry):
    assert registry.find("nonexistent") is None
    assert registry.find("Qwen/Qwen-Image-2.1") is not None


def test_modelspec_properties(registry: Registry):
    flagship = registry.by_id("Qwen/Qwen-Image-2.1")
    assert flagship.npu_usage == 62
    assert flagship.alpha is True
    assert flagship.co_resident_with_planner is False
    assert flagship.role == "flagship"
    assert flagship.kind == "image_generator"
    assert flagship.text_rendering == "strong"
    assert flagship.quality == "highest"
    assert flagship.speed == "slow"
    assert flagship.dialect

    default = registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    assert default.npu_usage == 23
    assert default.co_resident_with_planner is True
    assert default.role == "default"
    # The size is what the capacity check compares against.
    assert default.size_bytes > 0


def test_modelspec_exposes_the_rejected_sizes(registry: Registry):
    """A rejected size is a capability, so it belongs on the typed view.

    The dialect translator needs to say WHY a size was refused, and until
    this property existed it had to reach into the raw registry record to
    find out — which is the thing the typed view exists to prevent.
    """
    model = registry.by_id("Tongyi-MAI/Z-Image-Turbo")
    assert model.sizes_rejected == ["1536x1024", "1024x1536", "1792x1024"]
    assert "transformer tokens" in model.rejected_reason

    # A model that rejects nothing says so plainly rather than raising.
    flagship = registry.by_id("Qwen/Qwen-Image-2.1")
    assert flagship.sizes_rejected == []
    assert flagship.rejected_reason == ""


def test_modelspec_lists_are_copies(registry: Registry):
    """Mutating a returned list must not corrupt the registry."""
    model = registry.by_id("Qwen/Qwen-Image-2.1")

    artifact = model.artifact
    artifact.append("new_artifact")
    assert "new_artifact" not in model.artifact

    style = model.style
    style.append("new_style")
    assert "new_style" not in model.style

    edit_ops = model.edit_ops
    edit_ops.append("new_op")
    assert "new_op" not in model.edit_ops

    assert "new_artifact" not in model.raw["specialty"]["artifact"]
    assert "new_style" not in model.raw["specialty"]["style"]
    assert "new_op" not in model.raw["specialty"]["edit_ops"]


def test_modelspec_image_input_is_measured_not_advertised(registry: Registry):
    """The device says several models accept an image. Some refuse one.

    The field records what was MEASURED, and "unknown" is a real value:
    a model nobody measured is not a model that cannot take an image.
    """
    for model in registry.models:
        value = model.image_input
        assert value in ("yes", "no", "unknown"), (
            f"{model.id} has an image_input of {value!r}, which is not "
            "one of the three states a measurement can be in")
        # The convenience property agrees with the field, and says yes
        # ONLY when it was measured yes.
        assert model.takes_an_image == (value == "yes")


def test_modelspec_vendor_supported(registry: Registry):
    assert registry.by_id("Qwen/Qwen-Image-2.1").vendor_supported is True
    assert registry.by_id(
        "abenzerps/Qwen-Image-2.1-Uncensored-Quantized").vendor_supported is False
    assert "abenzerps/Qwen-Image-2.1-Uncensored-Quantized" in COMMUNITY_MODEL_IDS


def test_registry_missing_file(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(missing)
    assert "not found" in str(excinfo.value)
    assert str(missing) in str(excinfo.value)


def test_registry_invalid_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(bad)
    assert "Invalid JSON" in str(excinfo.value)


def test_registry_missing_models_key(tmp_path: Path):
    path = tmp_path / "no_models.json"
    path.write_text(json.dumps({"planner": {"id": "x", "npu_usage": 1}}), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(path)
    assert "missing the 'models' key" in str(excinfo.value)


def test_registry_missing_planner(tmp_path: Path):
    path = tmp_path / "no_planner.json"
    path.write_text(json.dumps({"models": []}), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(path)
    assert "missing the 'planner' key" in str(excinfo.value)


def test_registry_model_missing_id(tmp_path: Path):
    path = tmp_path / "no_id.json"
    path.write_text(json.dumps({
        "models": [{"kind": "image_generator"}],
        "planner": {"id": "x", "npu_usage": 1},
    }), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(path)
    assert "missing 'id'" in str(excinfo.value)


def test_registry_model_missing_kind(tmp_path: Path):
    path = tmp_path / "no_kind.json"
    path.write_text(json.dumps({
        "models": [{"id": "some/model"}],
        "planner": {"id": "x", "npu_usage": 1},
    }), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(path)
    assert "missing 'kind'" in str(excinfo.value)


def test_registry_planner_must_be_an_object(tmp_path: Path):
    path = tmp_path / "bad_planner.json"
    path.write_text(json.dumps({
        "models": [],
        "planner": "just-a-string",
    }), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        Registry.load(path)
    assert "'planner' must be an object" in str(excinfo.value)


def test_registry_supports_len_and_iter(registry: Registry):
    assert len(registry) == 17
    assert list(registry) == list(registry.models)
    assert "Qwen/Qwen-Image-2.1" in registry
    assert "nonexistent" not in registry
