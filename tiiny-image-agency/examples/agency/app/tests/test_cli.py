"""Tests for the `tis` command line interface.

The HTTP layer is faked, never called. A test that needs a running
agency is not a unit test.

The fakes answer with the shapes the API ACTUALLY returns - read
app/src/tis/api.py for them. A mock that agrees with the test rather
than with the API is how a CLI ends up disagreeing with the server it
talks to.
"""
from __future__ import annotations

import json

import httpx
import pytest

from tis.cli import DEFAULT_BASE_URL, NOT_RUNNING, main

PLANNER = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"

MODELS = {
    "models": [
        {
            "id": "Tongyi-MAI/Z-Image-Turbo",
            "role": "default",
            "npu_usage": 26,
            "kind": "image_generator",
            "alpha": False,
            "text_rendering": "weak",
            "quality": "good",
            "speed": "fast",
            "artifacts": ["illustration", "photo", "logo"],
            "styles": ["flat", "general"],
            "dialect": "Plain descriptive English.",
            "sizes_verified": ["1024x1024"],
        }
    ]
}

NPU = {
    "resident": [PLANNER, "Supertone/supertonic-3"],
    "used_pct": 55,
    "models": [{"id": PLANNER, "npu_usage": 55}],
    "reachable": True,
}

HEALTH = {
    "alive": True,
    "device_reachable": True,
    "registry_loaded": True,
    "model_count": 16,
}

PLAN = {
    "plan_id": "plan_0123456789abcdef",
    "requirements": {"artifact": "icon", "alpha": "required"},
    "model": {"id": "Qwen/Qwen-Image-2.1", "role": "flagship",
              "npu_usage": 62, "co_resident_with_planner": False},
    "justification": "Native transparency is a hard requirement.",
    "alternatives": [{"id": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
                      "role": "community", "npu_usage": 0,
                      "co_resident_with_planner": True}],
    "swap_required": True,
    "swap_plan": {"evict": [PLANNER], "load": "Qwen/Qwen-Image-2.1"},
    "planner_source": "llm",
}

QUEUED = {"job_id": "job_0123456789abcdef", "session_id": "s1",
          "status": "queued"}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _response(status: int, url: str = "http://agency.test", **kwargs):
    """A response with the request attached.

    httpx's `raise_for_status` needs one: a response with no request
    raises "the request instance has not been set on this response".
    """
    return httpx.Response(status, request=httpx.Request("GET", url), **kwargs)


def _events(*payloads: dict) -> list[str]:
    """The SSE lines a stream would deliver."""
    return ["data: " + json.dumps(payload) for payload in payloads]


class FakeStream:
    """What httpx.stream() hands back."""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        return iter(self._lines)


# -- the parser ----------------------------------------------------------


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "Tiiny Image Agency" in capsys.readouterr().out


def test_the_json_flag_is_accepted_before_or_after_the_command():
    """`tis models --json` and `tis --json models` are both natural to
    type, and argparse will not do both on its own."""
    from tis.cli import build_parser

    built = build_parser()
    assert built.parse_args(["--json", "models"]).json is True
    assert built.parse_args(["models", "--json"]).json is True
    assert built.parse_args(["models"]).json is False


def test_the_base_url_comes_from_the_flag_then_the_environment(monkeypatch):
    from tis.cli import build_parser

    monkeypatch.delenv("TIS_URL", raising=False)
    # The environment is read when the parser is BUILT, so it is read
    # after the variable is set.
    assert build_parser().parse_args(["models"]).url == DEFAULT_BASE_URL
    monkeypatch.setenv("TIS_URL", "http://elsewhere:9000")
    assert build_parser().parse_args(["models"]).url == "http://elsewhere:9000"
    assert build_parser().parse_args(
        ["--url", "http://flag:1", "models"]).url == "http://flag:1"


# -- the read commands ---------------------------------------------------


def test_models_prints_a_row_per_model(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        assert url.endswith("/v1/models")
        return _response(200, json=MODELS)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "Z-Image-Turbo" in out
    assert "26" in out


def test_npu_prints_the_resident_set(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        assert url.endswith("/v1/npu")
        return _response(200, json=NPU)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["npu"]) == 0
    out = capsys.readouterr().out
    assert "55" in out
    assert PLANNER in out


def test_health_reports_the_appliance(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        assert url.endswith("/v1/health")
        return _response(200, json=HEALTH)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["health"]) == 0
    assert "reachable" in capsys.readouterr().out


def test_health_exits_non_zero_when_the_appliance_is_off(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        return _response(200, json={**HEALTH, "device_reachable": False})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["health"]) == 1
    assert "NOT reachable" in capsys.readouterr().out


def test_json_output_is_one_parseable_object(monkeypatch, capsys):
    def fake_get(url, **kwargs):
        return _response(200, json=NPU)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["--json", "npu"]) == 0
    assert json.loads(capsys.readouterr().out) == NPU


# -- the plan ------------------------------------------------------------


def test_plan_posts_the_request_and_prints_the_justification(monkeypatch,
                                                              capsys):
    seen = {}

    def fake_post(url, json=None, **kwargs):
        seen["url"] = url
        seen["json"] = json
        return _response(200, json=PLAN)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert main(["plan", "an icon of a fox head"]) == 0
    # The API's request field is "request", not "prompt".
    assert seen["json"] == {"request": "an icon of a fox head"}
    out = capsys.readouterr().out
    assert "Qwen-Image-2.1" in out
    assert "Native transparency" in out


# -- the generation ------------------------------------------------------


def test_generate_posts_follows_the_stream_and_saves_the_asset(monkeypatch,
                                                               capsys, tmp_path):
    posted = {}

    def fake_post(url, json=None, **kwargs):
        posted["url"] = url
        posted["json"] = json
        return _response(202, json=QUEUED)

    def fake_stream(method, url, **kwargs):
        assert "/v1/session/s1/events" in url
        return FakeStream(_events(
            {"type": "plan.ready", "ts": 1762000000.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "model": "Z-Image-Turbo"}},
            {"type": "asset.ready", "ts": 1762000048.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_0123456789abcdef"}},
            {"type": "job.finished", "ts": 1762000049.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_0123456789abcdef"}},
        ))

    def fake_get(url, **kwargs):
        assert url.endswith("/v1/assets/ast_0123456789abcdef")
        return _response(200, content=PNG,
                              headers={"content-type": "image/png"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "get", fake_get)

    out_path = tmp_path / "fox.png"
    assert main(["generate", "an icon of a fox head", "--out", str(out_path)]) == 0

    # The request field is "request".
    assert posted["json"] == {"request": "an icon of a fox head"}
    printed = capsys.readouterr().out
    assert "plan.ready" in printed
    assert "asset.ready" in printed
    # And the PNG is on disk, byte for byte.
    assert out_path.read_bytes() == PNG


def test_generate_exits_non_zero_when_the_agency_is_not_running(monkeypatch,
                                                                 capsys):
    def fake_post(url, json=None, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    assert main(["generate", "an icon of a fox head"]) == 1
    assert NOT_RUNNING in capsys.readouterr().err


def test_a_failed_job_prints_the_error_and_exits_non_zero(monkeypatch, capsys):
    def fake_post(url, json=None, **kwargs):
        return _response(202, json=QUEUED)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream(_events(
        {"type": "job.failed", "ts": 1762000049.0,
         "data": {"job_id": "job_0123456789abcdef",
                  "error": "the NPU was exhausted"}},
    )))
    assert main(["generate", "an icon of a fox head"]) == 1
    assert "the NPU was exhausted" in capsys.readouterr().err


def test_iterate_posts_the_feedback_not_a_prompt(monkeypatch, capsys, tmp_path):
    posted = {}

    def fake_post(url, json=None, **kwargs):
        posted["url"] = url
        posted["json"] = json
        return _response(202, json=QUEUED)

    def fake_get(url, **kwargs):
        return _response(200, content=PNG)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: FakeStream(_events(
        {"type": "job.finished", "ts": 1762000049.0,
         "data": {"job_id": "job_0123456789abcdef",
                  "asset_id": "ast_0123456789abcdef"}},
    )))
    monkeypatch.setattr(httpx, "get", fake_get)

    out_path = tmp_path / "revised.png"
    assert main(["iterate", "ast_0123456789abcdef", "make it blue",
                 "--out", str(out_path)]) == 0
    # The API's field is "feedback".
    assert posted["json"] == {"asset_id": "ast_0123456789abcdef",
                              "feedback": "make it blue"}
    assert out_path.read_bytes() == PNG


# -- serve ---------------------------------------------------------------


def test_serve_runs_uvicorn_and_says_where(monkeypatch, capsys):
    import uvicorn

    ran = {}

    def fake_run(app, host=None, port=None, **kwargs):
        ran["host"] = host
        ran["port"] = port
        ran["app"] = app

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert main(["serve", "--port", "9999"]) == 0
    assert ran["port"] == 9999
    assert "9999" in capsys.readouterr().out


def test_alpha_measures_a_png(tmp_path, capsys):
    """The transparency of a PNG is measurable, so an agent can CHECK it.

    The skill tells an agent that a cut-out has to be verified rather
    than assumed, and this is how.
    """
    from test_research import make_png

    path = tmp_path / "cutout.png"
    path.write_bytes(make_png(8, 4, transparent=2))
    assert main(["alpha", str(path)]) == 0
    out = capsys.readouterr().out
    assert "50.0%" in out
    assert "RGBA" in out


def test_alpha_reports_a_file_that_is_not_a_png(tmp_path, capsys):
    path = tmp_path / "not.png"
    path.write_bytes(b"definitely not a png")
    assert main(["alpha", str(path)]) == 1
    assert "not a PNG" in capsys.readouterr().err


def test_alpha_says_so_when_there_is_no_file(tmp_path, capsys):
    assert main(["alpha", str(tmp_path / "missing.png")]) == 1
    assert "could not read" in capsys.readouterr().err


def test_a_stale_job_cannot_supply_the_asset(monkeypatch, capsys, tmp_path):
    """The event bus replays a session's recent events, so a second
    generation in the same session sees the FIRST job's asset.ready.

    It must not save that image. This is the bug: the second generation
    returned in under a second with the first job's picture and never
    generated anything at all.
    """

    def fake_post(url, json=None, **kwargs):
        return _response(202, url, json=QUEUED)

    def fake_stream(method, url, **kwargs):
        return FakeStream(_events(
            # An EARLIER job, replayed from the session's history.
            {"type": "asset.ready", "ts": 1762000048.0,
             "data": {"job_id": "job_OLD", "asset_id": "ast_OLD"}},
            {"type": "job.finished", "ts": 1762000049.0,
             "data": {"job_id": "job_OLD", "asset_id": "ast_OLD"}},
            # This job.
            {"type": "asset.ready", "ts": 1762000500.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_NEW"}},
            {"type": "job.finished", "ts": 1762000501.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_NEW"}},
        ))

    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        return _response(200, url, content=PNG)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "get", fake_get)

    out_path = tmp_path / "second.png"
    assert main(["generate", "a lighthouse at dusk",
                 "--out", str(out_path)]) == 0

    # This job's asset, not the replayed one.
    assert fetched == ["http://127.0.0.1:8080/v1/assets/ast_NEW"]
    assert out_path.read_bytes() == PNG


def test_an_event_with_no_job_id_cannot_supply_the_asset(monkeypatch,
                                                          capsys, tmp_path):
    """The swap events carry no job id. They are shown, but they never
    decide anything."""

    def fake_post(url, json=None, **kwargs):
        return _response(202, url, json=QUEUED)

    def fake_stream(method, url, **kwargs):
        return FakeStream(_events(
            {"type": "swap.finished", "ts": 1762000049.0,
             "data": {"model": "Tongyi-MAI/Z-Image-Turbo"}},
            {"type": "asset.ready", "ts": 1762000500.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_NEW"}},
            {"type": "job.finished", "ts": 1762000501.0,
             "data": {"job_id": "job_0123456789abcdef",
                      "asset_id": "ast_NEW"}},
        ))

    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        return _response(200, url, content=PNG)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "get", fake_get)

    out_path = tmp_path / "second.png"
    assert main(["generate", "a lighthouse at dusk",
                 "--out", str(out_path)]) == 0
    assert fetched == ["http://127.0.0.1:8080/v1/assets/ast_NEW"]
