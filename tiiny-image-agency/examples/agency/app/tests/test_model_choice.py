"""Choosing the model, instead of only being told which one was chosen.

The resolver picks a model and explains why. That is right for a
request the system understood. It is not enough for a user who knows
the appliance better than the resolver does — and the surface showed the
alternatives without offering them, so "the app always uses
Z-Image-Turbo" was the only thing a user could observe.

Two rules:

  A model the user chose is honoured WHEN IT CAN DO THE JOB. The
  capability filter is not a preference; a request for a transparent
  background cannot be given to a model that cannot render one.

  When the choice cannot be honoured, the answer says so. Silently
  using a different model would be a lie about what the user asked for.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tis.models import RequirementVector
from tis.registry import Registry
from tis.resolver import Resolver

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

DEFAULT_MODEL = "Tongyi-MAI/Z-Image-Turbo"
FLAGSHIP = "Qwen/Qwen-Image-2.1"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def test_the_resolver_chooses_the_same_model_when_nothing_is_preferred(
        registry: Registry):
    resolver = Resolver(registry)
    assert resolver.resolve(RequirementVector()).chosen.id == DEFAULT_MODEL


def test_a_model_the_user_chose_is_used(registry: Registry):
    resolver = Resolver(registry)
    resolution = resolver.resolve(RequirementVector(), preferred=FLAGSHIP)

    assert resolution.chosen.id == FLAGSHIP
    assert any("You chose" in reason for reason in resolution.reasons)


def test_a_model_that_cannot_do_the_job_is_refused_with_a_reason(
        registry: Registry):
    """Alpha is a hard constraint, not a preference.

    Asking for a transparent background and being given a model that
    cannot render one would produce an opaque image and a claim that the
    request was met.
    """
    resolver = Resolver(registry)
    requirements = RequirementVector(alpha="required")
    resolution = resolver.resolve(requirements, preferred=DEFAULT_MODEL)

    assert resolution.chosen.id != DEFAULT_MODEL, (
        "the default model cannot render a transparent background")
    assert any("cannot make this image" in reason
               for reason in resolution.reasons), (
        "the reason the choice was not honoured must be in the answer")


def test_a_model_that_is_not_in_the_registry_is_refused_with_a_reason(
        registry: Registry):
    resolver = Resolver(registry)
    resolution = resolver.resolve(RequirementVector(),
                                  preferred="nobody/imagines-this-model")

    assert resolution.chosen.id == DEFAULT_MODEL
    assert any("cannot make this image" in reason
               for reason in resolution.reasons)


def test_the_api_accepts_a_chosen_model(tmp_path, registry: Registry):
    from fastapi.testclient import TestClient

    from tis.api import create_app
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=PROJECT_ROOT / "registry" / "roles.json",
        assets_dir=tmp_path / "assets",
        planner_model=registry.planner.id,
    )
    agency = Agency(settings, registry=registry)
    try:
        client = TestClient(create_app(agency=agency))
        response = client.post("/v1/plan", json={
            "request": "a fox icon, flat, transparent background",
            "model_id": FLAGSHIP,
        })

        assert response.status_code == 200
        body = response.json()
        assert body["model"]["id"] == FLAGSHIP, (
            "the plan does not honour the model the user chose")
    finally:
        agency.close()


def test_the_api_says_so_when_the_choice_cannot_be_honoured(tmp_path,
                                                             registry: Registry):
    from fastapi.testclient import TestClient

    from tis.api import create_app
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=PROJECT_ROOT / "registry" / "roles.json",
        assets_dir=tmp_path / "assets",
        planner_model=registry.planner.id,
    )
    agency = Agency(settings, registry=registry)
    try:
        client = TestClient(create_app(agency=agency))
        response = client.post("/v1/plan", json={
            "request": "a fox icon, flat, transparent background",
            "model_id": DEFAULT_MODEL,
        })

        assert response.status_code == 200
        assert "cannot make this image" in response.json()["justification"]
    finally:
        agency.close()
