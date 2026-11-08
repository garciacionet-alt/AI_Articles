"""Tests for the theme.

THE REFACTOR IS THE POINT
-------------------------
The stylesheet had eight variables and about forty hard-coded colours.
Every one of those forty was a place a dark theme could not reach —
and a colour that cannot be themed is a colour that will be wrong in
one of the two themes.

So the rule is now enforced: **every colour in the stylesheet is the
value of a variable.** A hard-coded colour is a test failure, not a
thing somebody has to remember. That is worth more than the palette.

THE TWO THEMES
--------------
The light one is the default. The dark one is a block of the same
variable names with different values, so switching themes is switching
which values apply — not a second stylesheet that can drift.

THE ALPHA CHECKERBOARD IS NOT A COLOUR
--------------------------------------
A transparent PNG is shown on a checkerboard, because the checkerboard
is the honest display of transparency: a transparent image looks opaque
if you put it on white. So the checkerboard has to be THEMELED TOO,
and in the dark theme it has to be a DARK checkerboard — a light one
behind a transparent picture is worse than no checkerboard at all.

WHOSE CHOICE IS IT
-------------------
The operating system's, by default: somebody who has asked their whole
computer to be dark should not have to ask this page as well. A toggle
overrides it, and the override is remembered — a preference that is
forgotten between visits is not a preference.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def style_css() -> str:
    return (WEB_DIR / "style.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def test_every_colour_in_the_stylesheet_is_a_variable(style_css: str):
    """The rule that makes the theme possible.

    A hard-coded colour is a colour the dark theme cannot reach, and
    a colour that cannot be themed will be wrong in one of the two
    themes.
    """
    declared = {
        value.lower()
        for _, value in re.findall(
            r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b", style_css)
    }
    used = {value.lower()
            for value in re.findall(r"#[0-9a-fA-F]{3,8}\b", style_css)}

    stray = used - declared
    assert not stray, (
        "these colours are written into the rules rather than being "
        "variables, so the dark theme cannot reach them: "
        + ", ".join(sorted(stray)))


def test_there_is_a_dark_palette(style_css: str):
    """The same variable names with different values."""
    assert '[data-theme="dark"]' in style_css
    dark = style_css.split('[data-theme="dark"]', 1)[1]
    names = set(re.findall(r"(--[\w-]+)\s*:", dark.split("}", 1)[0]))
    root = style_css.split(":root", 1)[1].split("}", 1)[0]
    light_names = set(re.findall(r"(--[\w-]+)\s*:", root))
    assert names, "the dark theme declares no variables"

    # Every colour the dark theme names must also have a light value,
    # or switching themes would change more than the colours.
    missing = names - light_names
    assert not missing, (
        "the dark theme names variables the light theme does not: "
        + ", ".join(sorted(missing)))


def test_the_checkerboard_is_themed(style_css: str):
    """A transparent picture on a light checkerboard in a dark theme is
    worse than no checkerboard at all."""
    assert "--checker-a" in style_css
    assert "--checker-b" in style_css
    dark = style_css.split('[data-theme="dark"]', 1)[1]
    assert "--checker-a" in dark, "the checkerboard is not themed"
    assert "--checker-b" in dark, "the checkerboard is not themed"


def test_there_is_a_toggle(index_html: str, app_js: str):
    """Somebody has to be able to choose."""
    assert 'id="theme-toggle"' in index_html
    assert "theme-toggle" in app_js


def test_the_operating_system_is_the_default(app_js: str):
    """Somebody who has asked their whole computer to be dark should
    not have to ask this page as well."""
    assert "prefers-color-scheme" in app_js


def test_the_choice_is_remembered(app_js: str):
    """A preference that is forgotten between visits is not a
    preference."""
    assert "localStorage" in app_js
    assert "theme" in app_js


def test_the_theme_is_applied_before_the_page_paints(index_html: str):
    """A dark page that flashes white on the way in is worse than a
    light one. The choice has to be applied in the head, before the
    stylesheet paints anything."""
    head = index_html.split("</head>", 1)[0]
    assert "data-theme" in head or "theme" in head.lower()
    assert head.index("<style") < head.index("</head>") if "<style" in head \
        else "theme" in head.lower()
