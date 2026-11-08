"""Tests for the edit operations — the source image actually arriving.

THE GAP THIS CLOSES
-------------------
An edit adapter is CHOSEN for an edit request, but the Agency did not
send the source image with the request. ``Device.generate`` took a
model, a prompt and a size, and nothing else — so "remove the
background" resolved to the right model and then made a new picture
instead of editing the one that was uploaded.

The four adapters now say so on their cards. These tests are the other
half: they say the Agency does the thing the card claims.

WHAT THE MEASUREMENT ALLOWS
----------------------------
Of the fifteen models, only THREE honour a source image — and only one
of those three is an edit adapter: ``FLUX.2-klein-4B-Object-Remove``.

So the rules are:

- an edit request may only go to a model that HONOURS an image, because
  the whole point of an edit is the image;
- ``object_remove`` has such a model, and it is chosen;
- ``background_remove`` has NONE, and the Agency says so rather than
  sending the image to a model that ignores it and pretending.

THE IMAGE GOES OUT AS IT IS
---------------------------
Base64 in the appliance's ``image`` field, which is what the appliance
was measured taking. The bytes are not re-encoded on the way — a JPEG
that has been through a codec once cannot be through it twice without
losing more.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.models import Artifact, EditOp, RequirementVector
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"

#: The one adapter that honours a source image.
OBJECT_REMOVE = "fal/FLUX.2-klein-4B-Object-Remove"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


# -- the device sends the image -----------------------------------------


def test_the_device_sends_the_source_image(monkeypatch):
    """Base64 in the `image` field, which is what the appliance reads."""
    from tis.config import Settings
    from tis.device import TiinyDevice

    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    captured = {}

    def fake_request(method, path, body=None, **kwargs):
        captured.update(body or {})
        return 200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}

    monkeypatch.setattr(device, "_request", fake_request)

    device.generate("some/model", "remove the background", "1024x1024",
                    image=PNG)

    assert captured["image"] == base64.b64encode(PNG).decode()
    assert captured["model"] == "some/model"
    assert captured["prompt"] == "remove the background"


def test_the_device_sends_no_image_field_when_there_is_no_image(monkeypatch):
    """A generation without a source is a generation, and the field is
    absent rather than empty."""
    from tis.config import Settings
    from tis.device import TiinyDevice

    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    captured = {}

    def fake_request(method, path, body=None, **kwargs):
        captured.update(body or {})
        return 200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}

    monkeypatch.setattr(device, "_request", fake_request)

    device.generate("some/model", "a fox", "1024x1024")

    assert "image" not in captured


def test_a_jpeg_source_is_sent_as_the_bytes_it_is(monkeypatch):
    """No re-encoding on the way out. A JPEG that has been through a
    codec once cannot go through it twice without losing more."""
    from tis.config import Settings
    from tis.device import TiinyDevice

    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    captured = {}

    def fake_request(method, path, body=None, **kwargs):
        captured.update(body or {})
        return 200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}

    monkeypatch.setattr(device, "_request", fake_request)

    device.generate("some/model", "edit it", "1024x1024", image=JPEG)

    assert base64.b64decode(captured["image"]) == JPEG


# -- the resolver refuses the models that would ignore the image --------


def test_an_edit_request_only_goes_to_a_model_that_honours_an_image(
        registry: Registry):
    """The whole point of an edit is the image. A model that ignores it
    would make a new picture and call it an edit."""
    from tis.resolver import Resolver

    resolver = Resolver(registry)
    requirements = RequirementVector(
        artifact=Artifact.EDIT, edit_op=EditOp.OBJECT_REMOVE)

    resolution = resolver.resolve(requirements)

    assert resolution.chosen.id == OBJECT_REMOVE


def test_an_edit_with_no_model_that_honours_an_image_is_refused(
        registry: Registry):
    """Background-Remove does the operation and ignores the image.
    Nothing on this appliance can do it, and the Agency says so."""
    from tis.resolver import Resolver, ResolverError

    resolver = Resolver(registry)
    requirements = RequirementVector(
        artifact=Artifact.EDIT, edit_op=EditOp.BACKGROUND_REMOVE)

    with pytest.raises(ResolverError) as caught:
        resolver.resolve(requirements)

    message = str(caught.value).lower()
    assert "image" in message, "the refusal must say what the problem is"


def test_the_refusal_names_the_models_that_take_an_image(registry: Registry):
    """A refusal that names no alternative is a dead end."""
    from tis.resolver import Resolver, ResolverError

    resolver = Resolver(registry)
    requirements = RequirementVector(
        artifact=Artifact.EDIT, edit_op=EditOp.BACKGROUND_REMOVE)

    with pytest.raises(ResolverError) as caught:
        resolver.resolve(requirements)

    assert OBJECT_REMOVE in str(caught.value)


def test_a_plain_generation_is_not_affected(registry: Registry):
    """The rule is about EDITS. A generation has no source image and
    must not be filtered by whether the model takes one."""
    from tis.resolver import Resolver

    resolver = Resolver(registry)
    requirements = RequirementVector(artifact=Artifact.ILLUSTRATION)

    resolution = resolver.resolve(requirements)

    assert resolution.chosen.id


# -- the service carries the source asset -------------------------------


def _agency(tmp_path, registry):
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=ROLES_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
    )
    return Agency(settings, device=FakeDevice(registry), registry=registry)


@pytest.fixture
def agency(tmp_path, registry):
    """An agency that is CLOSED afterwards.

    The worker is a thread, and a thread outlives the test that made it
    unless somebody stops it — so every agency here is closed, or it
    goes on to break a test elsewhere that counts the threads.
    """
    built = _agency(tmp_path, registry)
    try:
        yield built
    finally:
        built.close()


def test_a_generation_with_a_source_asset_sends_that_asset(agency):
    """The bytes that were uploaded are the bytes that go to the
    appliance."""
    asset = agency.assets.save(PNG, {"origin": "test"})

    job_id = agency.generate("remove the object",
                              source_asset_id=asset.id)

    job = agency.get_job(job_id)
    while job.status not in ("done", "failed", "succeeded"):
        job = agency.get_job(job_id)
    assert job.status in ("done", "succeeded"), job.error

    sent = [call for call in agency.device.calls if call[0] == "generate"]
    assert sent
    assert getattr(agency.device, "last_image", None) == PNG


def test_the_lineage_records_the_source_asset(agency):
    """Where the picture came from is part of the provenance."""
    asset = agency.assets.save(PNG, {"origin": "test"})

    job_id = agency.generate("remove the object",
                              source_asset_id=asset.id)

    job = agency.get_job(job_id)
    while job.status not in ("done", "failed", "succeeded"):
        job = agency.get_job(job_id)

    result = agency.get_asset(job.payload["asset_id"])
    assert result.lineage.get("source_asset_id") == asset.id


def test_a_source_asset_that_does_not_exist_is_refused(agency):
    """The message says which one, so a typo in a list is findable."""
    job_id = agency.generate("remove the object",
                              source_asset_id="ast_0000000000000000")

    job = agency.get_job(job_id)
    while job.status not in ("done", "failed", "succeeded"):
        job = agency.get_job(job_id)

    assert job.status == "failed"
    assert "ast_0000000000000000" in (job.error or "")


def test_the_api_accepts_a_source_asset(agency):
    """The door for "edit this picture"."""
    from fastapi.testclient import TestClient

    from tis.api import create_app

    asset = agency.assets.save(PNG, {"origin": "test"})
    client = TestClient(create_app(agency))

    response = client.post("/v1/generate", json={
        "request": "remove the object",
        "source_asset_id": asset.id,
    })

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
