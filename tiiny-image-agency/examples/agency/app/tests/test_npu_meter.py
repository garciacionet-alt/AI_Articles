"""Tests for the NPU meter.

THE METER WAS LYING
--------------------
When the appliance does not answer - because it is busy with a
generation, because it is off, because the call timed out - the
agency's ``npu()`` returns an empty resident set and
``reachable: false``. The meter read that as "0% used, nothing
resident", which is a FALSE STATEMENT: five models were resident and
the meter said none were.

The difference matters because the meter is the one number somebody
glances at to decide whether the appliance can take a job right now.
A wrong answer there sends them to the wrong conclusion.

So: when the appliance did not answer, the meter says so. It does not
guess, and it does not claim the pool is empty.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def test_the_meter_looks_at_whether_the_appliance_answered(app_js: str):
    """The agency already says so; the meter has to read it."""
    assert "reachable" in app_js


def test_the_meter_says_the_appliance_did_not_answer(app_js: str):
    """Instead of "0% used, nothing resident" - which is a false
    statement about a pool that may well be full."""
    assert "did not answer" in app_js


def test_the_meter_does_not_say_nothing_is_resident_when_unreachable(
        app_js: str):
    """The unreachable path must RETURN before the meter reaches the
    "nothing resident" line - otherwise the false statement is still
    one branch away."""
    body = app_js.split("async function updateNpu()", 1)[1]
    body = body.split("\n}", 1)[0]
    # The invariant is about the CODE. A comment may name the old
    # wording - in fact it should, to explain why it is gone - without
    # that being a path that can still reach it.
    body = re.sub(r"//[^\n]*", "", body)

    guard = body.index("reachable")
    claim = body.index("nothing resident")
    assert guard < claim, (
        "the meter reaches the 'nothing resident' fallback before it "
        "checks whether the appliance answered")

    between = body[guard:claim]
    assert "return;" in between, (
        "the unreachable path does not return, so the meter falls "
        "through to claiming nothing is resident")


def test_a_slow_answer_cannot_overwrite_a_fresh_one(app_js: str):
    """The appliance is serial and its answers can take seconds. The
    poll is every three. Without a guard, an older answer can land
    after a newer one and put the wrong number on screen."""
    assert "npuPoll" in app_js


def test_no_function_is_defined_twice(app_js: str):
    """THE BUG THAT CAUSED ALL OF THIS.

    A second `apiGet` was defined further down the file, and because
    function declarations are hoisted the LATER one won. It returned
    the raw Response instead of the parsed JSON, so every caller in
    the page - the meter, the cards, the references, the roles, the
    lineage - silently got a Response object and read `undefined` off
    it.

    Nothing failed. The API tab kept working because it happened to
    use its own fetch. Everything else quietly showed nothing.

    So: no name may be defined twice. A duplicate is a silent
    whole-page failure waiting to happen.
    """
    names = re.findall(
        r"^(?:async )?function ([A-Za-z_$][\w$]*)\(", app_js, re.M)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, (
        "these functions are defined more than once, and the later "
        "definition silently wins: " + ", ".join(duplicates))


def test_the_api_helper_returns_the_parsed_json(app_js: str):
    """The one helper every caller shares. It resolves to the data."""
    body = app_js.split("async function apiGet(", 1)[1].split("\n}", 1)[0]
    assert "response.json()" in body, (
        "the shared helper does not return the parsed JSON")
