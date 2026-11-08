"""Tests for the developer tab.

WHAT THIS TAB IS FOR
--------------------
Somebody integrating with the Agency needs to know what the API is, and
they need to know it NOW, not after reading a document that was true
when it was written.

So the tab renders the LIVE SCHEMA — the one the running server
publishes at ``/openapi.json`` — rather than a copy of it. A copy
would drift: a route added on Tuesday would not appear in a page
written on Monday. The live schema cannot drift, because it IS the
server.

AND A CONSOLE
--------------
Reading a schema tells you what a request looks like. TRYING one tells
you what it does. The console sends a request from the page and shows
what came back, so the first call an integrator makes is on their own
screen rather than in a terminal they have to hand-roll.

The credential never appears: the browser is already talking to the
agency, and the agency's bearer stays where it is.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def test_there_is_a_developer_tab(index_html: str):
    """Somebody has to be able to GET to it."""
    assert 'data-tab="api"' in index_html
    assert 'id="panel-api"' in index_html
    assert "API" in index_html


def test_the_tab_reads_the_live_schema(app_js: str):
    """The live schema, not a copy of it.

    A copy would drift: a route added on Tuesday would not appear in a
    page written on Monday. The live schema cannot drift, because it
    IS the server.
    """
    assert "/openapi.json" in app_js
    assert "loadOpenApi" in app_js


def test_the_tab_is_fetched_when_it_is_opened(app_js: str):
    """Not at page load. The Make tab does not need it."""
    assert "TAB_LOADERS.api" in app_js


def test_the_endpoints_are_listed(index_html: str, app_js: str):
    """A list, with a place to put them."""
    assert 'id="api-endpoints"' in index_html
    assert "renderEndpoints" in app_js


def test_the_endpoints_can_be_searched(index_html: str, app_js: str):
    """Seventeen routes is browsable. Sixty would not be."""
    assert 'id="api-search"' in index_html
    assert "api-search" in app_js


def test_there_is_a_console(index_html: str, app_js: str):
    """Reading a schema tells you what a request looks like. TRYING one
    tells you what it does."""
    assert 'id="api-body"' in index_html
    assert 'id="api-send"' in index_html
    assert 'id="api-response"' in index_html
    assert "api-send" in app_js


def test_the_console_sends_to_the_chosen_endpoint(app_js: str):
    """The method and the path come from the endpoint that was
    clicked, not from something typed in."""
    assert "sendApiRequest" in app_js
    assert "apiMethod" in app_js
    assert "apiPath" in app_js


def test_the_response_is_shown(app_js: str):
    """Status and body. An integrator's first question is 'what came
    back', and the answer should be on the screen."""
    assert "api-response" in app_js
    assert "response.ok" in app_js or "response.status" in app_js


def test_the_tab_points_at_the_automated_docs(index_html: str):
    """FastAPI serves a full Swagger UI at /docs. The tab should say so
    rather than pretending to be the only way in."""
    assert "/docs" in index_html


def test_the_tab_explains_the_credential(index_html: str):
    """The bearer is never in the page and never in a request the
    browser makes. Saying so is part of the documentation."""
    text = index_html.lower()
    assert "bearer" in text or "credential" in text
    assert "tiiny_api_key" not in text
