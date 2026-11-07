"""Tests for the six things the agency gained.

THE JUDGE MUST SEE.
THE SURFACE TAKES A DROPPED IMAGE.
THERE IS A CARD FOR EVERY MODEL.
THE SURFACE SHOWS WHERE THE FILE IS.
AN AGENT MAY SAY WHERE TO WRITE IT.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

VISION_JUDGE = "Qwen/Qwen3.6-35B-A3B"
TEXT_MODEL = "openai/gpt-oss-20b"

# A PNG header. The upload checks it, and the asset store writes the
# bytes exactly as given.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def _agency(tmp_path, registry: Registry):
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=ROLES_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
        planner_model=TEXT_MODEL,
    )
    return Agency(settings, device=FakeDevice(registry),
                  registry=registry)


def _client(agency):
    from fastapi.testclient import TestClient

    from tis.api import create_app

    return TestClient(create_app(agency=agency))


# -- the judge must see ---------------------------------------------------


def test_the_judge_is_a_vision_model_by_default(tmp_path, registry: Registry):
    """The default critic can see. A critic that cannot see the image
    judges the prompt instead, and a prompt judge invents a defect."""
    agency = _agency(tmp_path, registry)
    assert agency.critic.vision is True
    assert agency.critic.model_id == VISION_JUDGE


def test_a_text_only_judge_is_refused_over_the_api(tmp_path,
                                                   registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/roles",
                                    json={"critic": TEXT_MODEL})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "cannot see an image" in detail
    assert "invent a defect" in detail, (
        "the refusal has to say WHY, or the user cannot choose another")


def test_the_guide_lists_only_models_that_can_be_the_judge(
        tmp_path, registry: Registry):
    """The critic's picker must not offer a model that would be refused."""
    agency = _agency(tmp_path, registry)
    options = agency.role_options()
    for model in options["vision_models"]:
        assert model["vision"] is True


def test_the_judge_can_be_any_model_that_can_see(tmp_path,
                                                 registry: Registry):
    """The rule is SEEING, not one named model."""
    agency = _agency(tmp_path, registry)
    options = agency.role_options()
    if len(options["vision_models"]) < 2:
        pytest.skip("only one vision model on this store")
    other = options["vision_models"][1]
    agency.set_roles(critic=other["id"])
    assert agency.critic.model_id == other["id"]
    assert agency.critic.vision is True


# -- the drop zone --------------------------------------------------------


def test_an_uploaded_image_becomes_an_asset(tmp_path, registry: Registry):
    """A dropped file is stored, byte for byte, as an asset."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=PNG,
        headers={"Content-Type": "image/png"})

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"].startswith("ast_")
    assert body["bytes"] == len(PNG)

    stored = agency.assets.get_png(body["asset_id"])
    assert stored == PNG, "the bytes were changed on the way in"


def test_the_uploaded_image_is_written_where_the_answer_says(tmp_path,
                                                             registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=PNG,
        headers={"Content-Type": "image/png"})
    path = Path(response.json()["path"])
    assert path.exists()
    assert path.read_bytes() == PNG


def test_a_file_that_is_not_a_png_is_refused(tmp_path, registry: Registry):
    """Every model on the appliance reads PNG. A JPEG would arrive as
    pixels the agency never saw."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=b"\xff\xd8\xff\xe0 not a png",
        headers={"Content-Type": "image/jpeg"})

    assert response.status_code == 400
    assert "PNG" in response.json()["detail"]


def test_an_empty_upload_is_refused(tmp_path, registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/assets", content=b"")
    assert response.status_code == 400


def test_the_upload_route_is_in_the_openapi_schema(tmp_path,
                                                   registry: Registry):
    agency = _agency(tmp_path, registry)
    schema = _client(agency).get("/openapi.json").json()
    assert "/v1/assets" in schema["paths"]


# -- the model cards ------------------------------------------------------


def test_every_model_in_the_catalogue_has_a_card(tmp_path, registry: Registry):
    """A model with no card is a model the user cannot judge."""
    agency = _agency(tmp_path, registry)
    client = _client(agency)
    for model in registry.models:
        if model.kind != "image_generator":
            continue
        response = client.get("/v1/models/card",
                              params={"model_id": model.id})
        assert response.status_code == 200, f"{model.id} has no card"
        body = response.json()
        assert body["model_id"] == model.id
        assert "advertised" in body
        assert "notes" in body
        assert "measured" in body


def test_a_card_says_what_the_device_advertises(tmp_path, registry: Registry):
    """The vendor's own claim, kept apart from what we measured."""
    agency = _agency(tmp_path, registry)
    body = _client(agency).get(
        "/v1/models/card",
        params={"model_id": "Tongyi-MAI/Z-Image-Turbo"}).json()

    assert body["advertised"], (
        "the card does not say what the device claims the model is for")


def test_a_card_for_a_model_nobody_has_measured_still_exists(
        tmp_path, registry: Registry):
    """Not measured is a fact the card reports - not a 404."""
    agency = _agency(tmp_path, registry)
    body = _client(agency).get(
        "/v1/models/card",
        params={"model_id": "Tongyi-MAI/Z-Image-Turbo"}).json()

    assert body["researched"] is True, (
        "this model HAS been measured - the card must say so")
    assert body["measured"] is not None


def test_a_card_for_a_model_that_does_not_exist_is_a_404(tmp_path,
                                                          registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).get("/v1/models/card",
                                    params={"model_id": "nobody/this"})
    assert response.status_code == 404


def test_the_model_list_carries_the_advertisement(tmp_path,
                                                  registry: Registry):
    """A list the user cannot read the claims on is a list they have to
    take on faith."""
    agency = _agency(tmp_path, registry)
    body = _client(agency).get("/v1/models").json()
    for model in body["models"]:
        assert "advertised" in model
        assert "notes" in model


# -- where the file is ----------------------------------------------------


def test_the_api_takes_a_write_path_for_the_finished_image(tmp_path,
                                                            registry: Registry):
    """An agent may say where the PNG should land."""
    agency = _agency(tmp_path, registry)
    schema = _client(agency).get("/openapi.json").json()
    body = schema["components"]["schemas"]["GenerateRequest"]["properties"]
    assert "output_path" in body, (
        "the API does not accept a write path for the finished image")


def test_a_finished_image_is_written_where_the_caller_asked(tmp_path,
                                                             registry: Registry):
    """The bytes are COPIED, never re-encoded. A round trip through an
    image library is where a transparent background quietly becomes an
    opaque one."""
    agency = _agency(tmp_path, registry)
    target = tmp_path / "elsewhere" / "final.png"
    written = agency._write_to(PNG, str(target))

    assert written == str(target)
    assert target.read_bytes() == PNG


def test_a_path_that_cannot_be_written_is_not_fatal(tmp_path,
                                                    registry: Registry):
    """The agency's own copy is still on disk, so this is not an error."""
    agency = _agency(tmp_path, registry)
    written = agency._write_to(PNG, "/proc/definitely/not/writable.png")
    assert written == ""


def test_the_asset_event_carries_the_path(tmp_path, registry: Registry):
    agency = _agency(tmp_path, registry)
    queue = agency.events.subscribe("default")

    target = tmp_path / "out" / "image.png"
    agency._deliver(
        _work(agency, output_path=str(target)),
        _result(PNG),
        _requirements(),
        "llm",
        "a fox",
    )

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    ready = [e for e in events
             if getattr(e, "type", None) == "asset.ready"]
    assert ready, "no asset.ready event"
    data = ready[0].data
    assert isinstance(data, dict)
    assert data["path"] == str(target)


# -- the surface ----------------------------------------------------------


def test_the_surface_has_a_drop_zone(index_html: str, app_js: str):
    assert 'id="dropzone"' in index_html, (
        "there is nowhere to drop an image")
    assert "dragover" in app_js, "the drop zone does not accept a drag"
    assert "uploadSource" in app_js, (
        "the dropped image is never uploaded")
    assert "/v1/assets" in app_js, (
        "the dropped image does not go to the upload route")


def test_a_dropped_image_makes_the_next_request_an_edit(app_js: str):
    """The difference between "make this better" and "make me
    something else"."""
    assert "sourceAssetId" in app_js
    assert "startEdit" in app_js, (
        "a request with a dropped image does not become an edit")


def test_the_surface_shows_where_the_file_is(index_html: str, app_js: str):
    assert 'id="file-path"' in index_html, (
        "the surface does not show the path of the file it made")
    assert "filePath" in app_js


def test_the_surface_has_a_model_card_browser(index_html: str, app_js: str):
    assert 'id="card-model"' in index_html, (
        "there is no browser for the model cards")
    assert "loadModelCard" in app_js
    assert "loadCardModels" in app_js


def test_the_card_shows_the_advertisement_and_what_we_noticed(
        app_js: str):
    """The third part is the point: the difference between the
    advertisement and the model."""
    assert "What the device says" in app_js
    assert "What we measured" in app_js
    assert "What we have noticed" in app_js


# -- helpers --------------------------------------------------------------


def _work(agency, output_path: str = ""):
    from tis.service import _Work

    return _Work(job_id="job_test", session_id="default", kind="generate",
                 request="a fox", width=1024, height=1024,
                 model_id="", output_path=output_path)


def _result(image: bytes):
    from tis.orchestrator import GenerationResult

    return GenerationResult(image=image, model_id="Tongyi-MAI/Z-Image-Turbo",
                            prompt="a fox", size="1024x1024", attempts=1,
                            critique=None, critique_skipped_reason=None)


def _requirements():
    from tis.models import RequirementVector

    return RequirementVector()
