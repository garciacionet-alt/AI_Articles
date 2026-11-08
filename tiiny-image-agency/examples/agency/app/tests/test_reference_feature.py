"""Tests for the reference feature, at the service and API level.

The store keeps the bytes and the recipe. What has to be proved here is
the part that makes a reference WORTH saving:

  * saving a reference from an asset produces a recipe that would
    actually reproduce that asset — the same model, the same dialect,
    the same size, the same requirements;
  * using a reference pins those, so a repeated job comes out the same
    way;
  * and the pin is a strong preference, not an absolute: if the
    reference's model cannot do the new job, the agency says so rather
    than quietly producing something different.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tis.config import Settings
from tis.references import ReferenceStore
from tis.service import Agency

PNG = b"\x89PNG\r\n\x1a\n" + b"the original bytes, untouched"


@pytest.fixture
def agency(tmp_path: Path):
    """An agency with one asset, ready to be made into a reference."""
    from tests.test_research import FakeDevice
    from tis.registry import Registry

    registry = Registry.load(
        Path(__file__).resolve().parents[2] / "registry" / "image-models.json")
    settings = Settings(
        assets_dir=tmp_path / "assets",
        references_dir=tmp_path / "references",
        cards_dir=tmp_path / "cards",
        hold_file=tmp_path / "hold",
        watchdog_lock=tmp_path / "watch.lock",
    )
    device = FakeDevice(registry)
    instance = Agency(settings, device=device, registry=registry)
    try:
        yield instance
    finally:
        instance.close()


def _save_asset(agency, lineage: dict | None = None) -> str:
    body = lineage or {
        "requirements": {"artifact": "icon", "alpha": "required"},
        "model_id": "Tongyi-MAI/Z-Image-Turbo",
        "dialect": "Plain descriptive English.",
        "size": "1024x1024",
        "prompt": "A flat vector icon of a fox head.",
        "modifiers": ["warmer fill"],
        "critique": {"passed": True, "reasons": []},
    }
    asset = agency.assets.save(PNG, body)
    return asset.id


# -- saving ---------------------------------------------------------------


def test_an_asset_can_be_saved_as_a_reference(agency):
    asset_id = _save_asset(agency)
    reference = agency.save_reference(asset_id, name="newsletter header")
    assert reference.id.startswith("ref_")
    assert reference.name == "newsletter header"
    assert reference.model_id == "Tongyi-MAI/Z-Image-Turbo"
    assert reference.png == PNG


def test_a_saved_reference_carries_the_recipe_that_made_it(agency):
    """This is the whole value: the recipe reproduces the asset."""
    asset_id = _save_asset(agency)
    reference = agency.save_reference(asset_id, name="x")
    assert reference.dialect == "Plain descriptive English."
    assert reference.size == "1024x1024"
    assert reference.prompt == "A flat vector icon of a fox head."
    assert reference.modifiers == ("warmer fill",)
    assert reference.requirements["alpha"] == "required"


def test_saving_a_missing_asset_is_an_error(agency):
    with pytest.raises(LookupError):
        agency.save_reference("ast_nothing", name="x")


def test_the_references_can_be_listed(agency):
    asset_id = _save_asset(agency)
    agency.save_reference(asset_id, name="x")
    listed = agency.list_references()
    assert len(listed) == 1
    assert listed[0]["name"] == "x"


# -- the API --------------------------------------------------------------


def _client(agency) -> TestClient:
    from tis.api import create_app
    return TestClient(create_app(agency=agency))


def test_the_api_saves_a_reference(agency):
    asset_id = _save_asset(agency)
    with _client(agency) as client:
        response = client.post("/v1/references",
                               json={"asset_id": asset_id,
                                     "name": "newsletter header"})
        assert response.status_code in (200, 201)
        body = response.json()
        assert body["id"].startswith("ref_")
        assert body["name"] == "newsletter header"


def test_the_api_saves_a_reference_from_raw_png_bytes(agency):
    """An agent may have a PNG of its own and no asset."""
    with _client(agency) as client:
        response = client.post("/v1/references?filename=fox.png",
                               content=PNG,
                               headers={"Content-Type": "image/png"})
        assert response.status_code in (200, 201)
        assert response.json()["bytes"] == len(PNG)


def test_the_api_refuses_a_non_png(agency):
    with _client(agency) as client:
        response = client.post("/v1/references",
                               content=b"not a png at all")
        assert response.status_code == 400


def test_the_api_lists_the_references(agency):
    asset_id = _save_asset(agency)
    agency.save_reference(asset_id, name="x")
    with _client(agency) as client:
        response = client.get("/v1/references")
        assert response.status_code == 200
        assert len(response.json()["references"]) == 1


def test_the_api_serves_a_reference_image(agency):
    asset_id = _save_asset(agency)
    reference = agency.save_reference(asset_id, name="x")
    with _client(agency) as client:
        response = client.get(f"/v1/references/{reference.id}/image")
        assert response.status_code == 200
        assert response.content == PNG


def test_the_api_forgets_a_reference(agency):
    asset_id = _save_asset(agency)
    reference = agency.save_reference(asset_id, name="x")
    with _client(agency) as client:
        assert client.delete(f"/v1/references/{reference.id}").status_code \
            in (200, 204)
        assert client.get(f"/v1/references/{reference.id}/image").status_code \
            == 404


def test_a_missing_reference_is_a_404(agency):
    with _client(agency) as client:
        assert client.get("/v1/references/ref_nothing/image").status_code \
            == 404


# -- USING a reference -----------------------------------------------------


def test_using_a_reference_pins_the_model_it_was_made_with(agency):
    """The point of a reference: the next one comes out like it.

    The reference's model is a strong preference, and the reference's
    requirements replace the ones the planner would have inferred. A
    weekly newsletter wants THIS look, not a fresh interpretation of the
    same words.
    """
    asset_id = _save_asset(agency, {
        "requirements": {"artifact": "icon", "alpha": "no"},
        "model_id": "Tongyi-MAI/Z-Image-Turbo",
        "dialect": "Plain descriptive English.",
        "size": "1024x1024",
        "prompt": "A flat vector icon of a fox head.",
        "modifiers": ["warmer fill"],
    })
    reference = agency.save_reference(asset_id, name="newsletter header")
    plan = agency.plan_with_reference("this week's fox", reference.id)
    assert plan["model"]["id"] == "Tongyi-MAI/Z-Image-Turbo"
    # The requirements are the REFERENCE's, not the planner's.
    assert plan["requirements"]["artifact"] == "icon"
    assert plan["requirements"]["alpha"] == "no"


def test_using_a_reference_says_so_in_the_justification(agency):
    asset_id = _save_asset(agency, {
        "requirements": {"artifact": "icon", "alpha": "no"},
        "model_id": "Tongyi-MAI/Z-Image-Turbo",
        "dialect": "Plain descriptive English.",
        "size": "1024x1024",
        "prompt": "A flat vector icon of a fox head.",
        "modifiers": [],
    })
    reference = agency.save_reference(asset_id, name="newsletter header")
    plan = agency.plan_with_reference("this week's fox", reference.id)
    assert "newsletter header" in plan["justification"]
    assert reference.id in plan["justification"]


def test_a_reference_whose_model_cannot_do_the_job_is_explained(agency):
    """The pin is a preference, not an absolute.

    Children-Drawing draws illustrations and nothing else, so a
    reference made with it cannot make an icon. The agency must not
    quietly use it anyway — and must not quietly use a different model
    without saying so either.
    """
    asset_id = _save_asset(agency, {
        "requirements": {"artifact": "icon", "alpha": "no"},
        "model_id": "Tongyi-MAI/Z-Image-Turbo-Children-Drawing",
        "dialect": "Plain descriptive English.",
        "size": "1024x1024",
        "prompt": "A crayon drawing of a fox.",
        "modifiers": [],
    })
    reference = agency.save_reference(asset_id, name="crayon")
    plan = agency.plan_with_reference("an icon of a fox", reference.id)
    # It did NOT use the reference's model, because that model cannot
    # make an icon.
    assert plan["model"]["id"] != "Tongyi-MAI/Z-Image-Turbo-Children-Drawing"
    # And it said so.
    assert "crayon" in plan["justification"]


def test_a_missing_reference_is_refused(agency):
    with pytest.raises(LookupError):
        agency.plan_with_reference("a fox", "ref_nothing")
