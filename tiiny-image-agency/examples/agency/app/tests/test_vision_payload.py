"""The vision payload: what goes on the wire to a model that can see.

THE REASONING PROBLEM
----------------------
The appliance's generalist is a reasoning model. It thinks before it
answers, and the thinking is not part of the reply. Measured on the live
judge prompt on 2026-11-07:

  * thinking ON, 2500 tokens  - the reply was sometimes prose that did
    not follow the format and sometimes nothing at all
  * thinking ON, 8000 tokens  - HTTP 502 from the upstream
  * thinking OFF, 8000 tokens - HTTP 200, 80 completion tokens, and a
    well-formed VERDICT

An empty reply looks exactly like a model that cannot see. The fix is to
ask for no thinking.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tis.config import Settings
from tis.device import TiinyDevice

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d76360000002000154a24f7d0000000049454e44ae42"
    "6082"
)


class _Recorder:
    """Stands in for the appliance's request layer."""

    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload or {
            "choices": [{"message": {"content": "VERDICT: pass"}}]
        }
        self.body = None

    def __call__(self, method, path, body=None, **kw):
        self.body = body
        return self.status, self.payload


@pytest.fixture
def device():
    return TiinyDevice(Settings(base_url="http://example.invalid",
                                api_key="test"))


def test_the_judge_asks_for_no_thinking(device, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(device, "_request", recorder)

    device.vision("Qwen/Qwen3.6-35B-A3B", "What is in this image?", PNG)

    assert recorder.body["chat_template_kwargs"] == {"enable_thinking": False}


def test_the_budget_is_generous(device, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(device, "_request", recorder)

    device.vision("Qwen/Qwen3.6-35B-A3B", "What is in this image?", PNG)

    assert recorder.body["max_tokens"] >= 2500


def test_the_image_goes_as_a_data_url(device, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(device, "_request", recorder)

    device.vision("Qwen/Qwen3.6-35B-A3B", "What is in this image?", PNG)

    parts = recorder.body["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_the_reply_is_the_content(device, monkeypatch):
    recorder = _Recorder(payload={"choices": [
        {"message": {"content": "VERDICT: fail\nREASON: the sky is grey"}}]})
    monkeypatch.setattr(device, "_request", recorder)

    answer = device.vision("Qwen/Qwen3.6-35B-A3B", "What is in this image?", PNG)
    assert answer.startswith("VERDICT: fail")


def test_an_empty_reply_is_an_empty_string_not_an_error(device, monkeypatch):
    """The empty reply is the failure the critic has to explain."""
    recorder = _Recorder(payload={"choices": [{"message": {"content": ""}}]})
    monkeypatch.setattr(device, "_request", recorder)

    assert device.vision("Qwen/Qwen3.6-35B-A3B", "q", PNG) == ""


def test_the_payload_is_json_serialisable(device, monkeypatch):
    """A body that cannot be encoded is a body that never reaches the wire."""
    recorder = _Recorder()
    monkeypatch.setattr(device, "_request", recorder)

    device.vision("Qwen/Qwen3.6-35B-A3B", "What is in this image?", PNG)
    assert json.loads(json.dumps(recorder.body)) == recorder.body
