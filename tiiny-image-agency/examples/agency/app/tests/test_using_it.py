"""Tests for the "Using it" panel.

ONE TAB, TWO PANELS
--------------------
The API tab now has two sub-panels: "Using it" and "API". They sit
together because an integrator and a first-time user are both asking
the same underlying question - "how does this thing work" - and a
third tab for it would be a third place to look.

ONE FILE IS THE TRUTH
----------------------
The text explaining the app, the curated README, and the skill all
risk saying three slightly different things about the same feature.
So "Using it" is not hand-typed into the page: it is rendered from
``src/tis/resources/using_it.md``, the same file the API serves at
``/v1/using-it``. There is exactly one place to edit this text.

IT SHIPS WITH THE PACKAGE
---------------------------
A markdown file beside a Python module is not included in a wheel
unless something says so - setuptools only packages ``.py`` files by
default. Forgetting the ``package-data`` entry would make this 404 for
every installed user while working fine from a source checkout, which
is exactly the kind of gap that is invisible until somebody who is not
a developer hits it.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = APP_DIR / "web"
RESOURCE = APP_DIR / "src" / "tis" / "resources" / "using_it.md"


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


def test_the_file_exists_and_is_not_empty():
    assert RESOURCE.is_file()
    assert len(RESOURCE.read_text(encoding="utf-8").strip()) > 200


def test_the_package_ships_it():
    """Without this, the wheel drops the file and every installed user
    gets a 404 that a source checkout would never show."""
    import tomllib as _toml
    pyproject = _toml.loads(
        (APP_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = (pyproject.get("tool", {}).get("setuptools", {})
                     .get("package-data", {}))
    patterns = package_data.get("tis", [])
    assert any("resources" in pattern for pattern in patterns), (
        "resources/*.md is not declared as package-data, so a wheel "
        "build drops this file")


def test_the_endpoint_serves_it(tmp_path: Path):
    from fake_device import FakeDevice
    from tis.api import create_app
    from tis.config import Settings
    from tis.registry import Registry
    from tis.service import Agency

    registry = Registry.load(APP_DIR.parent / "registry" / "image-models.json")
    settings = Settings(assets_dir=tmp_path / "assets",
                        cards_dir=tmp_path / "cards",
                        hold_file=tmp_path / "hold",
                        watchdog_lock=tmp_path / "watch.lock")
    device = FakeDevice(registry)
    agency = Agency(settings, device=device, registry=registry)
    client = TestClient(create_app(agency=agency))
    response = client.get("/v1/using-it")
    assert response.status_code == 200
    body = response.json()
    assert "markdown" in body
    assert len(body["markdown"]) > 200


def test_there_are_two_sub_panels(index_html: str):
    assert 'id="api-subtab-using"' in index_html
    assert 'id="api-subtab-schema"' in index_html
    assert 'id="panel-using-it"' in index_html


def test_using_it_is_shown_first(index_html: str):
    """The question "how does this work" comes before "what is the
    schema" for most people who open this tab."""
    using_pos = index_html.index('id="panel-using-it"')
    api_pos = index_html.index('id="api-columns"')
    assert using_pos < api_pos


def test_the_markdown_is_rendered(app_js: str):
    assert "renderMarkdown" in app_js
    assert "loadUsingIt" in app_js


def test_switching_sub_panels_does_not_refetch(app_js: str):
    """The text does not change while the tab is open, so clicking
    between "Using it" and "API" must not ask the server again."""
    assert "usingItLoaded" in app_js or "usingItMarkdown" in app_js
