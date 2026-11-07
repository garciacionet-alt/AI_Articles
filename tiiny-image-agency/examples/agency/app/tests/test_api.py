"""Tests for the HTTP API of the Tiiny Image Agency.

Every test runs against a FakeDevice and a temporary directory. A test
that builds a real Agency would reach for the real appliance, the real
job store under ~/.hermes and the real assets directory — a unit test
that writes to the user's state is a unit test that will one day find
the user's state.

The TestClient is used bare rather than as a context manager, because
the context manager runs the app's LIFESPAN, and the lifespan closes the
Agency. A bare client leaves the Agency open, so a test can still read
the job it just started. The Agency is closed by the fixture instead.
One test covers the lifespan itself.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fake_device import FakeDevice, png_bytes
from tis.api import create_app
from tis.device import DeviceError
from tis.registry import Registry
from tis.service import Agency, WORKER_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

#: A bearer that is obviously a placeholder, so a test that finds it in a
#: response is unambiguous.
BEARER = "sk-tis-test-bearer-not-a-real-key"
PASS = "VERDICT: pass\nREASON: it satisfies the requirements"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


@pytest.fixture
def agency(tmp_path: Path, registry: Registry):
    """An Agency on a fake appliance and a temporary home."""
    device = FakeDevice(registry, replies={registry.planner.id: PASS})
    built = Agency(
        _settings(tmp_path),
        device=device,
        registry=registry,
    )
    try:
        yield built
    finally:
        built.close()


def _settings(tmp_path: Path):
    from tis.config import Settings

    return Settings(
        api_key=BEARER,
        registry_path=REGISTRY_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
    )


def _client(agency: Agency) -> TestClient:
    return TestClient(create_app(agency=agency))


def _events_endpoint(app):
    """The SSE route's own function, so a test can drive its generator."""
    return next(route.endpoint for route in app.routes
                if route.path.endswith("/events"))


# -- the app itself -----------------------------------------------------


def test_the_app_carries_the_agency_and_every_route(agency: Agency):
    app = create_app(agency=agency)
    assert app.state.agency is agency
    expected = {
        "/v1/models",
        "/v1/npu",
        "/v1/plan",
        "/v1/generate",
        "/v1/iterate",
        "/v1/assets/{asset_id}",
        "/v1/assets/{asset_id}/lineage",
        "/v1/session/{session_id}/events",
        "/v1/health",
    }
    assert expected.issubset({getattr(route, "path", "") for route in app.routes})


def test_the_lifespan_closes_the_agency(agency: Agency):
    """The app owns the worker thread, so the app's shutdown must stop it.

    A worker left running would keep the appliance held after the server
    that asked for it is gone.
    """
    app = create_app(agency=agency)
    with TestClient(app):
        pass
    assert not any(t.name == WORKER_NAME for t in threading.enumerate())


# -- the read routes ----------------------------------------------------


def test_models_lists_the_registry(agency: Agency):
    response = _client(agency).get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert isinstance(data["models"], list)
    model = data["models"][0]
    for field in ("id", "role", "npu_usage", "kind", "alpha",
                  "text_rendering", "quality", "speed",
                  "artifacts", "styles", "dialect", "sizes_verified"):
        assert field in model


def test_npu_reports_the_resident_set(agency: Agency):
    response = _client(agency).get("/v1/npu")
    assert response.status_code == 200
    data = response.json()
    assert "resident" in data
    assert "used_pct" in data
    assert "models" in data


def test_health_answers(agency: Agency):
    response = _client(agency).get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["alive"] is True
    assert "device_reachable" in data
    assert "registry_loaded" in data


def test_health_answers_even_when_the_device_is_unreachable(tmp_path, registry):
    """A health endpoint that throws when the appliance is off reports the
    outage by crashing, which is the one thing it must not do."""

    class Unreachable:
        """A device that is switched off."""

        def resident(self):
            raise DeviceError("the appliance is off", status=503)

        def chat(self, model, prompt, **kw):
            raise DeviceError("the appliance is off", status=503)

        def generate(self, model, prompt, size):
            raise DeviceError("the appliance is off", status=503)

        def load(self, model):
            raise DeviceError("the appliance is off", status=503)

        def unload(self, model):
            raise DeviceError("the appliance is off", status=503)

    unreachable = Agency(_settings(tmp_path), device=Unreachable(),
                         registry=registry)
    try:
        response = _client(unreachable).get("/v1/health")
        assert response.status_code == 200
        assert response.json()["device_reachable"] is False
    finally:
        unreachable.close()


# -- the plan -----------------------------------------------------------


def test_plan_returns_the_model_and_the_reason(agency: Agency):
    response = _client(agency).post(
        "/v1/plan", json={"request": "a friendly robot waving hello"})
    assert response.status_code == 200
    data = response.json()
    for key in ("plan_id", "requirements", "model", "justification",
                "alternatives", "unavailable", "swap_required", "swap_plan",
                "planner_source"):
        assert key in data
    assert data["plan_id"].startswith("plan_")
    # "plan_" is five characters and the id carries sixteen more.
    assert len(data["plan_id"]) == 21
    assert data["model"]["id"]
    assert data["justification"]
    assert data["planner_source"] in ("llm", "fallback")


def test_plan_rejects_an_empty_request(agency: Agency):
    client = _client(agency)
    assert client.post("/v1/plan", json={"request": ""}).status_code == 400
    assert client.post("/v1/plan", json={"request": "   "}).status_code == 400


def test_a_plan_that_needs_a_download_says_so(tmp_path: Path,
                                               registry: Registry):
    """A request only an UNDOWNLOADED model can do gets a plan, not a
    refusal.

    The appliance has no adapter for object removal — the model that
    does it is in the store but not on the disk. Falling back to a model
    that cannot remove objects would return an image that silently fails
    the request. So the plan names the model that would work, says how
    much disk it needs, and the generation downloads it first.
    """
    reply = json.dumps({"artifact": "edit", "edit_op": "object_remove"})
    device = FakeDevice(registry, replies={registry.planner.id: reply})
    built = Agency(_settings(tmp_path), device=device, registry=registry)
    try:
        response = _client(built).post(
            "/v1/plan", json={"request": "remove the object from the photo"})
        assert response.status_code == 200
        data = response.json()
        assert data["download"]["model"] == "fal/FLUX.2-klein-4B-Object-Remove"
        assert data["download"]["size_bytes"] > 0
        assert data["model"]["downloaded"] is False
        assert "download" in data["justification"].lower()
    finally:
        built.close()


def test_a_plan_names_the_models_that_are_not_downloaded(agency: Agency):
    """The plan document says which models could do the job if they were
    downloaded, so a caller is not left guessing."""
    data = _client(agency).post(
        "/v1/plan", json={"request": "an icon of a fox head"}).json()

    for model in data["model"], *(data["alternatives"] + data["unavailable"]):
        assert "downloaded" in model
    # The chosen model is always loadable.
    assert data["model"]["downloaded"] is True


# -- the job routes -----------------------------------------------------


def test_generate_is_accepted_and_returns_a_job_id(agency: Agency):
    response = _client(agency).post(
        "/v1/generate",
        json={"request": "a friendly robot waving hello",
              "session_id": "test-session"})
    # 202, not 200: the work is QUEUED. A client that read 200 would
    # reasonably believe the image was ready.
    assert response.status_code == 202
    data = response.json()
    assert data["job_id"].startswith("job_")
    assert data["session_id"] == "test-session"
    assert data["status"] == "queued"

    # And the job really is running in the background.
    job = agency.get_job(data["job_id"])
    assert job is not None
    assert job.status in ("queued", "running", "succeeded")


def test_generate_rejects_an_empty_request(agency: Agency):
    client = _client(agency)
    assert client.post("/v1/generate", json={"request": ""}).status_code == 400
    assert client.post("/v1/generate", json={"request": "  "}).status_code == 400


def test_iterate_is_accepted_and_returns_a_job_id(agency: Agency):
    response = _client(agency).post(
        "/v1/iterate",
        json={"asset_id": "ast_0123456789abcdef", "feedback": "make it blue"})
    assert response.status_code == 202
    data = response.json()
    assert data["job_id"].startswith("job_")
    assert data["status"] == "queued"


def test_iterate_rejects_empty_feedback(agency: Agency):
    client = _client(agency)
    assert client.post("/v1/iterate", json={
        "asset_id": "ast_0123456789abcdef", "feedback": ""}).status_code == 400
    assert client.post("/v1/iterate", json={
        "asset_id": "ast_0123456789abcdef", "feedback": "  "}).status_code == 400


# -- the assets ---------------------------------------------------------


def test_the_png_route_returns_the_bytes_exactly(agency: Agency):
    """The alpha channel is the product. A round trip through an image
    library is exactly where a transparent background quietly becomes an
    opaque one, so the bytes come back as they went in."""
    image = png_bytes()
    saved = agency.assets.save(image, {"model_id": "test", "size": "1024x1024"})
    response = _client(agency).get(f"/v1/assets/{saved.id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == image


def test_the_lineage_route_returns_the_provenance(agency: Agency):
    lineage = {"model_id": "Tongyi-MAI/Z-Image-Turbo", "size": "1024x1024",
               "attempts": 1, "requirements": {"artifact": "icon"}}
    saved = agency.assets.save(png_bytes(), lineage)
    response = _client(agency).get(f"/v1/assets/{saved.id}/lineage")
    assert response.status_code == 200
    assert response.json() == lineage


def test_an_unknown_asset_is_a_404(agency: Agency):
    client = _client(agency)
    assert client.get("/v1/assets/ast_does_not_exist").status_code == 404
    assert client.get("/v1/assets/ast_does_not_exist/lineage").status_code == 404


# -- the event stream ---------------------------------------------------


def test_the_events_route_is_an_event_stream(agency: Agency):
    app = create_app(agency=agency)
    response = asyncio.run(_events_endpoint(app)(session_id="s1"))
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"


def test_the_stream_carries_the_events_and_ends_with_job_finished(agency: Agency):
    async def scenario():
        app = create_app(agency=agency)
        response = await _events_endpoint(app)(session_id="s1")
        stream = response.body_iterator

        agency.events.publish("job.finished", "s1", {"job_id": "job_1"})
        chunk = await stream.__anext__()

        assert chunk.startswith("data: ")
        payload = json.loads(chunk[len("data: "):].strip())
        assert payload["type"] == "job.finished"
        assert payload["session_id"] == "s1"
        assert payload["data"]["job_id"] == "job_1"
        assert payload["id"]

        # The stream ends on job.finished, so the next pull raises.
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    # ONE event loop for the whole scenario: an async generator belongs
    # to the loop it was created in, and running it in another loop is
    # how a test hangs instead of failing.
    asyncio.run(scenario())


def test_the_stream_does_not_end_on_another_jobs_terminal_event(agency: Agency):
    """The bus REPLAYS a session's recent events, so a subscriber sees the
    terminal events of EARLIER jobs.

    Ending the stream on one of those cut it off before the caller's own
    job had started. This was found the hard way: a second generation in
    the same session returned in 0.2 seconds without generating anything.
    """
    async def scenario():
        app = create_app(agency=agency)
        response = await _events_endpoint(app)(session_id="s1", job_id="job_2")
        stream = response.body_iterator

        # An EARLIER job's terminal event, replayed from the history.
        agency.events.publish("job.finished", "s1", {"job_id": "job_1"})
        chunk = await stream.__anext__()
        payload = json.loads(chunk[len("data: "):].strip())
        assert payload["data"]["job_id"] == "job_1"

        # The stream is STILL OPEN: the caller's own job has not finished.
        agency.events.publish("job.finished", "s1", {"job_id": "job_2"})
        chunk = await stream.__anext__()
        payload = json.loads(chunk[len("data: "):].strip())
        assert payload["data"]["job_id"] == "job_2"

        # And now it ends, on the caller's own terminal event.
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    asyncio.run(scenario())


def test_the_stream_of_one_session_does_not_carry_another_sessions_events(
        agency: Agency):
    async def scenario():
        app = create_app(agency=agency)
        mine = (await _events_endpoint(app)(session_id="s1")).body_iterator
        theirs = (await _events_endpoint(app)(session_id="s2")).body_iterator

        agency.events.publish("job.finished", "s2", {"job_id": "job_2"})

        # s2's stream gets it.
        chunk = await theirs.__anext__()
        assert "job.finished" in chunk
        # s1's stream does not - it is still waiting.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(mine.__anext__(), timeout=0.3)

    asyncio.run(scenario())


def test_two_clients_on_one_session_both_get_the_events(agency: Agency):
    """A browser tab and a script can watch the same session."""
    async def scenario():
        app = create_app(agency=agency)
        first = (await _events_endpoint(app)(session_id="s1")).body_iterator
        second = (await _events_endpoint(app)(session_id="s1")).body_iterator

        agency.events.publish("job.finished", "s1", {"job_id": "job_1"})

        assert "job.finished" in await first.__anext__()
        assert "job.finished" in await second.__anext__()

    asyncio.run(scenario())


def test_one_client_leaving_does_not_silence_the_other(agency: Agency):
    """Dropping the whole session on the first disconnect would kill the
    second watcher too, which is the opposite of what a session is for."""
    async def scenario():
        app = create_app(agency=agency)
        first = (await _events_endpoint(app)(session_id="s1")).body_iterator
        second = (await _events_endpoint(app)(session_id="s1")).body_iterator

        # The first client goes away: its generator is closed.
        await first.aclose()

        agency.events.publish("job.finished", "s1", {"job_id": "job_1"})
        assert "job.finished" in await second.__anext__()

    asyncio.run(scenario())


# --------------------------------------------------------- the bearer


def test_the_bearer_never_reaches_a_response(agency: Agency):
    client = _client(agency)
    bodies = [
        client.get("/v1/models").text,
        client.get("/v1/npu").text,
        client.get("/v1/health").text,
        client.post("/v1/plan", json={"request": "a friendly robot"}).text,
        client.post("/v1/generate", json={"request": "a friendly robot"}).text,
    ]
    for body in bodies:
        assert BEARER not in body
