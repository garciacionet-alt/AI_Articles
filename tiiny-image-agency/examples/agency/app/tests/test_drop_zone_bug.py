"""Tests for the bug: dropping a JPEG opened it in a new tab.

WHAT HAPPENED
-------------
A JPG was dropped onto the app and the BROWSER opened the file in a
new tab instead. The agency never saw it.

The dropzone's own `drop` handler calls `preventDefault()`, which is
correct - but it only fires when the drop lands ON the dropzone
element. The dropzone is a small box above the canvas that says "Drop
an image to update it"; the canvas below it - where the generated
picture actually appears - is a SEPARATE element with no listener at
all. A user who (reasonably) drops the picture onto the picture area
hits a part of the page nothing is listening to, and the browser's
own default action - navigate to the dropped file - runs instead.

TWO FIXES, BOTH NEEDED
------------------------
1. A page-wide guard. ANY drop anywhere on this page must never
   navigate the tab away, even onto whitespace, even if some future
   element is added without its own handler. This is pure safety net:
   it does not have to do anything useful, it only has to make sure a
   stray drop never leaves the app.
2. The canvas itself - where the picture is shown - must act as a
   second drop target with the SAME upload logic as the dropzone,
   because that is where a person's hand actually goes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def test_a_stray_drop_anywhere_cannot_navigate_the_page(app_js: str):
    """The safety net. A drop that lands outside every known drop
    target must still never trigger the browser's own file-open."""
    assert "window.addEventListener('dragover'" in app_js
    assert "window.addEventListener('drop'" in app_js


def test_the_safety_net_still_lets_the_real_drop_zones_work(app_js: str):
    """The window-level guard must not swallow the event before the
    dropzone's own handler gets to act on it."""
    body = app_js.split("window.addEventListener('drop'", 1)[1]
    body = body.split("\n});", 1)[0]
    assert "preventDefault" in body
    # It must not stop the event from reaching the real targets.
    assert "stopPropagation" not in body
    assert "stopImmediatePropagation" not in body


def test_the_canvas_is_a_second_drop_target(app_js: str):
    """The picture area - where a person's hand actually goes - must
    upload the file too, not just the small labelled box above it."""
    assert "imageContainer" in app_js
    canvas_drops = app_js.count(
        "els.imageContainer.addEventListener('drop'")
    assert canvas_drops == 1


def test_both_drop_targets_call_the_same_upload(app_js: str):
    """One upload path, not two that can drift apart."""
    assert app_js.count("uploadSource(") >= 2
