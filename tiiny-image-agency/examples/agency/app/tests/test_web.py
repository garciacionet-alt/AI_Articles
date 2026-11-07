"""Tests for the work surface.

The surface is three static files with no build step, so there is no
Python to import. What can be tested is the contract between the
surface and the API, and that contract is where the real bugs were.

Two of them, both shipped at least once:

  * The event bus REPLAYS a session's recent events to a late
    subscriber. A surface that does not filter by job id will show the
    PREVIOUS job's asset. The CLI shipped that bug; the first
    delegation for this surface shipped it again.
  * The surface once polled the events route as if it returned JSON.
    It returns an SSE stream.

So these tests read the JavaScript and assert on what it does. That is
not ideal, but it is the only way to test a build-step-free surface
without inventing a browser harness, and the assertions are on the
exact behaviours that broke.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def index_html() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_css() -> str:
    return (WEB_DIR / "style.css").read_text(encoding="utf-8")


# -- the files exist -----------------------------------------------------


def test_the_three_files_exist() -> None:
    for name in ("index.html", "app.js", "style.css"):
        path = WEB_DIR / name
        assert path.is_file(), f"{name} is missing from the work surface"
        assert path.stat().st_size > 200, f"{name} is suspiciously small"


def test_no_build_step_is_required() -> None:
    """The surface must work without npm, a bundler or a framework."""
    surface = "\n".join(
        (WEB_DIR / name).read_text(encoding="utf-8")
        for name in ("index.html", "app.js", "style.css")
    )
    for forbidden in ("import ", "require(", "from '", 'from "', "node_modules",
                      "webpack", "vite", "react", "vue", "svelte"):
        assert forbidden not in surface.lower(), (
            f"the surface mentions {forbidden!r}; it must have no build step"
        )


# -- the job id filter ----------------------------------------------------


def test_the_event_stream_is_opened_with_the_job_id(app_js: str) -> None:
    """The stream MUST carry ?job_id=, or a replayed asset can be shown."""
    assert "job_id=" in app_js, (
        "the event stream is opened without ?job_id=; the bus replays the "
        "session's recent events and a previous job's asset would be shown"
    )
    assert re.search(r"events\?job_id=", app_js), (
        "the ?job_id= query parameter is not on the events route"
    )


def test_events_are_filtered_by_job_id(app_js: str) -> None:
    """An event belonging to another job must be ignored."""
    assert re.search(r"job_id\s*!==\s*currentJobId", app_js), (
        "the surface does not compare an event's job id with its own"
    )
    assert re.search(r"data\.job_id\s*&&\s*\n?\s*data\.job_id\s*!==", app_js), (
        "the surface does not drop an event whose job id is not its own"
    )


def test_the_job_id_comes_from_the_api_not_from_the_clock(app_js: str) -> None:
    """The job id is the API's. Inventing one shows nothing real."""
    assert "queued.job_id" in app_js, (
        "the surface does not take the job id from the API's response"
    )
    assert "Math.random" not in app_js, (
        "the surface invents a job id; the id must come from the API"
    )


def test_a_replayed_job_finished_does_not_end_the_wrong_job(app_js: str) -> None:
    """The job.finished event carries a job id and must be filtered."""
    assert "'job.finished'" in app_js
    # The filter runs before the switch, so job.finished is filtered too.
    filter_at = app_js.index("data.job_id !== currentJobId")
    switch_at = app_js.index("switch (kind)")
    assert filter_at < switch_at, (
        "the job id filter must run BEFORE the events are dispatched"
    )


# -- the stream is an SSE stream -----------------------------------------


def test_the_events_route_is_read_as_a_stream_not_as_json(app_js: str) -> None:
    """It is text/event-stream. response.json() on it never works."""
    assert "EventSource" in app_js, (
        "the surface does not use EventSource for the SSE stream"
    )
    assert re.search(r"response\.json\(\)", app_js) is not None, (
        "the surface should still parse JSON for the non-stream routes"
    )
    # The events route must never be parsed as a whole-document JSON.
    events_block = app_js[app_js.index("new EventSource"):]
    assert "response.json()" not in events_block, (
        "the events route is parsed as JSON; it is an SSE stream"
    )


def test_sse_messages_are_parsed_from_the_data_field(app_js: str) -> None:
    assert "JSON.parse(message.data)" in app_js, (
        "the surface does not parse the SSE payload out of message.data"
    )


def test_the_event_field_is_type_not_event(app_js: str) -> None:
    """The wire shape is {"type": ..., "data": ...}."""
    assert "event.type" in app_js, "the surface reads the wrong field name"
    assert "event.event" not in app_js, (
        "the surface reads event.event; the field is event.type"
    )


# -- the event names are the API's ---------------------------------------


def test_the_event_names_are_the_ones_the_agency_publishes(app_js: str) -> None:
    """A typo in an event name is a silent no-op in the surface."""
    published = {
        "job.queued", "job.started", "job.finished", "job.failed",
        "plan.ready", "swap.started", "swap.finished",
        "download.started", "download.progress", "download.finished",
        "generate.started", "generate.finished", "critique.ready",
        "asset.ready",
    }
    handled = set(re.findall(r"case '([a-z]+\.[a-z]+)'", app_js))
    missing = published - handled
    assert not missing, f"the surface ignores these events: {sorted(missing)}"


def test_the_surface_does_not_invent_event_names(app_js: str) -> None:
    """Names that the agency never publishes are bugs."""
    invented = {"generation.completed", "swap.completed", "job.complete",
                "image.ready", "generation.done"}
    for name in invented:
        assert f"case '{name}'" not in app_js, (
            f"the surface handles {name!r}, which the agency never publishes"
        )


# -- the alpha must survive ------------------------------------------------


def test_the_png_is_not_round_tripped_through_a_canvas(app_js: str) -> None:
    """Re-encoding through a canvas is where alpha quietly becomes opaque."""
    for forbidden in ("toDataURL", "toBlob", "getImageData", "createImageBitmap",
                      "OffscreenCanvas"):
        assert forbidden not in app_js, (
            f"the surface uses {forbidden}; the PNG must be shown as it is"
        )
    assert "v1/assets/" in app_js, "the surface does not fetch the asset bytes"


def test_the_checkerboard_is_on_the_canvas(style_css: str) -> None:
    assert "background-image" in style_css, (
        "the canvas has no checkerboard; the alpha would be invisible"
    )


def test_the_image_is_not_hidden_by_its_own_rule(style_css: str) -> None:
    """The image rule must not set display:none.

    The image element is hidden with a .hidden class and shown by
    removing it. If the #generated-image rule itself sets display:none,
    the image is laid out at zero size and NEVER appears — the class
    comes off, the DOM says it is visible, and the screen stays empty.
    That is a bug that no DOM assertion catches.
    """
    match = re.search(r"#generated-image\s*\{[^}]*\}", style_css)
    assert match, "there is no rule for #generated-image"
    rule = match.group(0)
    assert "display: none" not in rule, (
        "#generated-image sets display:none; the image can never be shown"
    )
    assert "display: block" in rule or "display: flex" in rule, (
        "#generated-image does not set a display mode that shows it"
    )


def test_the_hidden_class_wins(style_css: str) -> None:
    """The .hidden class is what hides the image before it loads."""
    assert re.search(r"\.hidden\s*\{[^}]*display:\s*none\s*!important", style_css), (
        ".hidden must win with !important, or the loaded image stays hidden"
    )


# -- no credentials in the browser ----------------------------------------


def test_the_surface_holds_no_credential(app_js: str, index_html: str) -> None:
    """The bearer lives on the server. The browser talks only to the agency."""
    surface = app_js + index_html
    for forbidden in ("TIINY_API_KEY", "Authorization", "Bearer", "api_key",
                      "apiKey", "x-api-key"):
        assert forbidden not in surface, (
            f"the surface mentions {forbidden!r}; it must hold no credential"
        )


def test_the_surface_never_names_the_appliance(app_js: str) -> None:
    """It is an HTTP client of the agency, not of the appliance."""
    for forbidden in ("openai.api.tiiny", "tiiny.dev", "tiiny_ctl", "tiiny top"):
        assert forbidden not in app_js, (
            f"the surface references {forbidden!r}; it must only talk to "
            f"the agency"
        )


# -- the three persistent elements ---------------------------------------


def test_the_three_persistent_elements_are_present(index_html: str) -> None:
    for element in ("model-badge", "npu-meter", "swap-banner"):
        assert element in index_html, f"{element} is missing from the page"


def test_the_three_elements_are_addressed_by_the_script(app_js: str) -> None:
    """An element in the markup that nothing drives is not a feature."""
    for element in ("model-id", "npu-fill", "swap-banner"):
        assert f"'{element}'" in app_js, f"the script never touches {element}"


def test_the_model_badge_carries_the_justification(app_js: str) -> None:
    assert "justification" in app_js, (
        "the badge does not show why the model was chosen; that is the point"
    )


def test_the_research_card_is_used(app_js: str) -> None:
    assert "models/card" in app_js, "the surface ignores the research cards"
    # The model id is a query parameter: every id contains slashes.
    assert "encodeURIComponent(modelId)" in app_js, (
        "the model id is not encoded; every id contains a slash"
    )


def test_the_npu_meter_shows_the_used_percentage_and_the_resident_set(
        app_js: str) -> None:
    assert "v1/npu" in app_js
    assert "used_pct" in app_js
    assert "resident" in app_js


# -- the banner ------------------------------------------------------------


def test_the_banner_shows_a_running_elapsed_time(app_js: str) -> None:
    assert "setInterval" in app_js and "tick" in app_js, (
        "the banner has no running clock; a five-minute wait must not be "
        "a silence"
    )


def test_the_download_banner_is_covered(app_js: str) -> None:
    """A download is about five minutes. It needs its own banner."""
    for event in ("download.started", "download.progress", "download.finished"):
        assert f"case '{event}'" in app_js, f"{event} is not handled"
    assert "size_bytes" in app_js, (
        "the download banner does not say how big the download is"
    )


# -- iteration -------------------------------------------------------------


def test_iteration_is_wired(app_js: str) -> None:
    assert "v1/iterate" in app_js, "the surface cannot iterate"
    assert "asset_id" in app_js and "feedback" in app_js


def test_the_iteration_strip_exists(index_html: str) -> None:
    assert "thumbs" in index_html, "there is no iteration strip"
    assert "feedback" in index_html, "there is no way to give feedback"


# -- the lineage -----------------------------------------------------------


def test_the_lineage_is_shown(app_js: str) -> None:
    assert "lineage" in app_js, "the surface does not show the lineage"
    assert "model_id" in app_js and "requirements" in app_js


# -- the input -------------------------------------------------------------


def test_there_is_a_way_to_make_an_image(index_html: str, app_js: str):
    assert 'id="request"' in index_html, "there is no request box"
    assert "v1/generate" in app_js, "the surface cannot generate"
    assert "v1/plan" in app_js, (
        "the surface does not plan first; the plan says what will happen "
        "before it happens"
    )


# -- who talks, and who judges --------------------------------------------


def test_the_surface_offers_the_role_choices(index_html: str):
    """A user can choose a critic that can SEE the image."""
    assert 'id="role-critic"' in index_html, "there is no judge picker"
    assert 'id="role-conversation"' in index_html, "there is no talker picker"
    assert 'id="role-note"' in index_html, "the roles say nothing"


def test_the_surface_reads_the_guides_own_catalogue(app_js: str):
    """Not a hard-coded list: the agency knows which models can see."""
    assert "v1/roles" in app_js, "the surface does not read the roles guide"
    assert "v1/roles" in app_js and "model.vision" in app_js, (
        "the picker does not know which models can see an image"
    )


def test_the_surface_can_change_a_role(app_js: str):
    assert "'/v1/roles'" in app_js, "the surface cannot set a role"
    assert "setRole" in app_js, "the surface has no way to set a role"


def test_the_surface_says_when_the_judge_is_blind(app_js: str):
    """A user who picks a text model must be told what that means."""
    assert "judges the" in app_js and "PROMPT" in app_js, (
        "the surface does not say that a blind judge judges the prompt only"
    )
