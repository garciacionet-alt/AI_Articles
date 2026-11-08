"""Tests for JPEG input.

WHAT THIS FEATURE IS, PRECISELY
--------------------------------
A JPEG may be uploaded and is stored BYTE FOR BYTE, with the format
recorded in the lineage and the right content type served.

WHAT IT IS NOT
--------------
It is not "the agency can edit a JPEG". The agency does not send a
source image to the appliance at all — ``Device.generate`` takes a
model, a prompt and a size, and nothing else. The edit adapters are
CHOSEN for an edit request, but no image goes with the request, so
that gap is a separate piece of work and is not pretended away here.

WHY THE BYTES ARE NOT CONVERTED
--------------------------------
The appliance decodes the JPEG to pixels itself. Converting the file
to PNG at upload would produce exactly the same picture and would cost
a re-encode that can only lose what the JPEG already lost. So the
bytes go to disk as they arrived.

THE ONE LOSS, NAMED
--------------------
A JPEG has no alpha channel. That loss happened before the agency ever
saw the file, and the lineage says so, in words, rather than leaving
the caller to discover it later.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

# A JPEG's first three bytes. The agency identifies a JPEG by its
# magic and does not decode it — the appliance decodes it, and the
# Agency has no image library on purpose.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

# A GIF. Not a PNG, not a JPEG: refused.
GIF = b"GIF89a" + b"\x00" * 32

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


def _agency(tmp_path, registry: Registry):
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


def _client(agency):
    from tis.api import create_app

    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        create_app(agency))


# -- the upload ----------------------------------------------------------


def test_a_jpeg_upload_is_accepted(tmp_path, registry: Registry):
    """A JPEG is a real image and the appliance reads one."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=JPEG,
        headers={"Content-Type": "image/jpeg"})

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"].startswith("ast_")
    assert body["bytes"] == len(JPEG)


def test_the_jpeg_is_stored_byte_for_byte(tmp_path, registry: Registry):
    """No re-encode. The bytes are the bytes that arrived."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=JPEG,
        headers={"Content-Type": "image/jpeg"})

    stored = agency.assets.get_image(response.json()["asset_id"])
    assert stored == JPEG, "the bytes were changed on the way in"


def test_the_jpeg_is_written_with_a_jpeg_extension(tmp_path, registry: Registry):
    """A JPEG called .png is a lie about its own format."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=JPEG,
        headers={"Content-Type": "image/jpeg"})

    path = Path(response.json()["path"])
    assert path.suffix == ".jpg"
    assert path.read_bytes() == JPEG


def test_the_lineage_records_the_format_and_the_lost_alpha(
        tmp_path, registry: Registry):
    """One honest, named loss rather than a silent one."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=JPEG,
        headers={"Content-Type": "image/jpeg"})

    lineage = agency.assets.get_lineage(response.json()["asset_id"])
    assert lineage["format"] == "jpeg"
    assert lineage["alpha"] == "none"
    assert "alpha" in lineage["notes"].lower()


def test_the_asset_is_served_as_a_jpeg(tmp_path, registry: Registry):
    """The content type follows the file, not the other way round."""
    agency = _agency(tmp_path, registry)
    client = _client(agency)
    uploaded = client.post("/v1/assets", content=JPEG,
                           headers={"Content-Type": "image/jpeg"})
    asset_id = uploaded.json()["asset_id"]

    served = client.get(f"/v1/assets/{asset_id}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/jpeg")
    assert served.content == JPEG


def test_a_png_is_still_a_png(tmp_path, registry: Registry):
    """The change adds a format; it does not move the existing one."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=PNG,
        headers={"Content-Type": "image/png"})

    path = Path(response.json()["path"])
    assert path.suffix == ".png"
    lineage = agency.assets.get_lineage(response.json()["asset_id"])
    assert lineage["format"] == "png"


def test_a_gif_is_refused(tmp_path, registry: Registry):
    """A GIF is neither a PNG nor a JPEG, and it is not an animation
    this agency can pretend to support."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=GIF,
        headers={"Content-Type": "image/gif"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "PNG" in detail and "JPEG" in detail


def test_an_empty_upload_is_refused(tmp_path, registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/assets", content=b"")

    assert response.status_code == 400


def test_a_jpeg_asset_is_listed(tmp_path, registry: Registry):
    """The list is the directory listing, so it must find both formats."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post(
        "/v1/assets", content=JPEG,
        headers={"Content-Type": "image/jpeg"})

    assert response.json()["asset_id"] in agency.assets.list()
