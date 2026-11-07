"""The device layer: the protocol, the real adapter and the fake.

No network and no appliance here. The fake reproduces the failures we
MEASURED on the Tiiny Pocket Lab on 2026-11-05, so the rest of the suite
can exercise the real code paths without a device.
"""
from __future__ import annotations

import inspect

import pytest

from tis.config import Settings
from tis.device import Device, DeviceError, TiinyDevice
from tis.registry import Registry

from fake_device import DEFAULT_RESIDENT, FakeDevice

# Ids used across the tests.
PLANNER = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"  # 55%
FLAGSHIP = "Qwen/Qwen-Image-2.1"                      # 62%
IMAGE_HOT = "Tongyi-MAI/Z-Image-Turbo"                # 26%
ENHANCER_23 = "Qwen/Qwen-Image-2.1-PE-T2I"           # 23%
PLAIN_MODEL = "openai/gpt-oss-20b"                    # 27%

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def registry() -> Registry:
    """The catalogue the application ships with."""
    return Registry.load(Settings().registry_path)


def device(**kw) -> FakeDevice:
    return FakeDevice(registry(), **kw)


# --- the fake's residency behaviour -----------------------------------------


def test_fake_starts_on_the_default_set_at_86_percent():
    dev = device()
    assert set(dev.resident()) == set(DEFAULT_RESIDENT)
    assert dev.occupancy() == 86


def test_load_evicts_only_as_much_as_it_needs():
    """The device evicts the minimum, not everything.

    Measured 2026-11-05 at 17:23: the five-model default set (86%) plus the
    55% Coder settled at 94% — the 47% generalist went, the 0%, 5%, 7% and
    27% models stayed. Evicting the largest first reproduces that.
    """
    dev = device()
    dev.load(FLAGSHIP)
    resident = set(dev.resident())
    # The 62% flagship does not fit alongside the 47% generalist, so the
    # generalist is the one that goes.
    assert PLAIN_MODEL not in resident
    # The 0% model always survives.
    assert "Supertone/supertonic-3" in resident
    assert FLAGSHIP in resident
    # 0 + 7 + 5 + 62 = 74%
    assert dev.occupancy() == 74


def test_loading_the_coder_into_the_default_set_lands_at_94_percent():
    """The measured 17:23 observation, reproduced."""
    dev = device()
    dev.load("Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo")
    assert dev.occupancy() == 94
    assert "openai/gpt-oss-20b" in dev.resident()
    assert "Qwen/Qwen3.6-35B-A3B" not in dev.resident()


def test_a_download_the_cli_dies_on_is_not_a_failure(monkeypatch):
    """The CLI started the download and then died with a Go panic.

    Blocked sending progress on a channel nobody was reading, with the
    download already under way. That is not a verdict on the download —
    the appliance was fetching the model either way — so the Agency
    waits on the catalogue, not on the CLI's exit.
    """
    import subprocess

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    assert device.download("some/model") == ""


def test_a_load_the_cli_hangs_on_is_not_a_failure(monkeypatch):
    """The model is resident and the CLI has not returned.

    The observed load of the 14.5 GiB community build did the work and
    then sat there: the model was in NPU memory and the CLI had not
    come back after ten minutes, so the call timed out and the caller
    was told the load had failed. The model was loaded. The CLI had
    simply not got out of the way.

    So the timeout is a QUESTION, and the device answers it: is the
    model resident now?
    """
    import subprocess

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=600)

    monkeypatch.setattr(subprocess, "run", fake_run)
    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    monkeypatch.setattr(device, "resident", lambda: ["some/model"])

    device.load("some/model")  # must not raise


def test_a_load_that_timed_out_and_did_not_happen_still_fails(monkeypatch):
    """The other half: a timeout where the model is NOT resident is a
    real failure, and it has to be reported as one."""
    import subprocess

    from tis.device import DeviceError

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=600)

    monkeypatch.setattr(subprocess, "run", fake_run)
    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    monkeypatch.setattr(device, "resident", lambda: [])

    with pytest.raises(DeviceError) as error:
        device.load("some/model")
    assert "not resident" in str(error.value)


def test_a_download_ignores_a_non_zero_exit(monkeypatch):
    """The CLI panicking after the download started is not a failure."""
    import subprocess

    class Result:
        returncode = 2
        stdout = ""
        stderr = "panic: send on closed channel"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    device = TiinyDevice(Settings(api_key="k", base_url="http://example"))
    assert device.download("some/model") == ""


def test_the_planner_and_an_image_model_co_reside():
    """The hot path: 55% planner + 23% image model = 78%, which generates."""
    dev = device()
    dev.set_resident(["Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo",
                       "Supertone/supertonic-3"])
    dev.load("Tongyi-MAI/Z-Image-Turbo")
    assert dev.occupancy() == 78
    assert "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo" in dev.resident()


def test_unload_removes_only_the_named_model():
    """The fake's unload is minimal: the named model goes, the rest stay.

    The appliance may also reclaim other models it no longer wants to hold,
    but its reclamation policy is not characterised, so the fake does the
    least and errs toward a higher occupancy — the safe direction.
    """
    dev = device()
    dev.load(FLAGSHIP)
    dev.unload(FLAGSHIP)
    assert FLAGSHIP not in dev.resident()
    # 0 + 7 + 5 = 12
    assert dev.occupancy() == 12
    # The models the load did not have to evict are still there.
    assert "Qwen/Qwen3-ASR-1.7B" in dev.resident()


# --- admission is not execution -----------------------------------------------


def test_generation_at_78_percent_succeeds_and_returns_png_bytes():
    # Measured: 55% planner + 23% image model = 78% -> generation SUCCEEDED.
    dev = device(resident=[PLANNER, IMAGE_HOT])
    assert dev.occupancy() == 78
    data = dev.generate(IMAGE_HOT, "a lighthouse at dusk", "1024x1024")
    assert isinstance(data, bytes)
    assert data.startswith(PNG_SIGNATURE)


def test_generation_above_81_percent_fails_with_500_and_code_150004():
    # Measured: 23% enhancer + 62% flagship = 85% -> HTTP 500, code 150004.
    dev = device(resident=[ENHANCER_23, FLAGSHIP])
    assert dev.occupancy() == 85
    with pytest.raises(DeviceError) as ei:
        dev.generate(FLAGSHIP, "a lighthouse at dusk", "1024x1024")
    assert ei.value.status == 500
    assert ei.value.code == 150004
    assert str(ei.value) == "The operation failed to complete."


def test_the_flagship_alone_generates_successfully():
    # Measured: 62% flagship alone -> generation SUCCEEDED (~200 s).
    dev = device()
    for model in list(dev.resident()):
        dev.unload(model)
    dev.load(FLAGSHIP)
    assert dev.occupancy() == 62
    data = dev.generate(FLAGSHIP, "a lighthouse at dusk", "1024x1024")
    assert data.startswith(PNG_SIGNATURE)


def test_a_non_resident_model_raises_a_retryable_404():
    dev = device()
    with pytest.raises(DeviceError) as ei:
        dev.generate(FLAGSHIP, "a lighthouse at dusk", "1024x1024")
    assert ei.value.status == 404
    assert ei.value.code == 404
    assert ei.value.retryable is True
    assert str(ei.value) == f'"{FLAGSHIP}" is not loaded.'


# --- the protocol ------------------------------------------------------------


def test_device_error_carries_status_code_and_retryable():
    exc = DeviceError("boom", retryable=True, status=500, code=150004)
    assert str(exc) == "boom"
    assert exc.retryable is True
    assert exc.status == 500
    assert exc.code == 150004
    assert isinstance(exc, RuntimeError)


def test_tiiny_device_is_constructible_and_exposes_the_protocol_methods():
    dev = TiinyDevice(Settings(api_key="test"))
    for name in ("chat", "generate", "resident", "load", "unload"):
        assert hasattr(dev, name)


def test_both_implement_the_device_protocol():
    assert isinstance(device(), Device)
    assert isinstance(TiinyDevice(Settings(api_key="test")), Device)


def test_fake_and_real_agree_on_the_protocol_signatures():
    fake = device()
    real = TiinyDevice(Settings(api_key="test"))
    for name in ("chat", "generate", "resident", "load", "unload"):
        fake_params = list(inspect.signature(getattr(fake, name)).parameters)
        real_params = list(inspect.signature(getattr(real, name)).parameters)
        assert fake_params == real_params, f"{name} drifted between the fake and the real adapter"


# --- the bearer must never leak ----------------------------------------------


def test_no_bearer_appears_in_a_device_error_message(monkeypatch):
    key = "sk-secret-key-do-not-leak-0123456789"
    dev = TiinyDevice(Settings(api_key=key))

    def boom(method, path, *, body=None):
        return 500, {"error": {"message": f"upstream said {key}", "code": 500}}

    monkeypatch.setattr(dev, "_request", boom)
    with pytest.raises(DeviceError) as ei:
        dev.chat(PLAIN_MODEL, "hello")
    assert key not in str(ei.value)
    assert key not in repr(ei.value)


def test_no_bearer_appears_in_the_device_repr():
    key = "sk-secret-key-do-not-leak-0123456789"
    dev = TiinyDevice(Settings(api_key=key))
    assert key not in repr(dev)


def test_the_fake_and_the_real_adapter_agree_on_the_150004_failure():
    # The fake exists to fail the way the device fails, so the two must
    # report the same thing for the same measured failure.
    dev = device(resident=[ENHANCER_23, FLAGSHIP])
    with pytest.raises(DeviceError) as fake_exc:
        dev.generate(FLAGSHIP, "a lighthouse at dusk", "1024x1024")

    real = TiinyDevice(Settings(api_key="test"))
    payload = {
        "error": {
            "message": "The operation failed to complete.",
            "code": 150004,
        }
    }
    real_exc = real._fail(500, payload, FLAGSHIP)

    assert str(fake_exc.value) == str(real_exc)
    assert fake_exc.value.status == real_exc.status
    assert fake_exc.value.code == real_exc.code
    assert fake_exc.value.retryable == real_exc.retryable


def test_the_fake_and_the_real_adapter_agree_on_the_not_loaded_failure():
    dev = device()
    with pytest.raises(DeviceError) as fake_exc:
        dev.generate(FLAGSHIP, "a lighthouse at dusk", "1024x1024")

    real = TiinyDevice(Settings(api_key="test"))
    payload = {
        "error": {
            "message": f'"{FLAGSHIP}" is not loaded.',
            "type": "model_not_found",
            "code": 404,
        }
    }
    real_exc = real._fail(404, payload, FLAGSHIP)

    assert str(fake_exc.value) == str(real_exc) == f'"{FLAGSHIP}" is not loaded.'
    assert fake_exc.value.status == real_exc.status == 404
    assert fake_exc.value.code == real_exc.code == 404
    assert fake_exc.value.retryable == real_exc.retryable is True


# --- the fake's chat ---------------------------------------------------------


def test_chat_on_a_non_resident_model_raises_a_retryable_404():
    dev = device()
    with pytest.raises(DeviceError) as ei:
        dev.chat(PLANNER, "hello")
    assert ei.value.status == 404
    assert ei.value.retryable is True


def test_chat_returns_a_scripted_reply():
    dev = device(replies={PLAIN_MODEL: "a lighthouse at dusk"})
    reply = dev.chat(PLAIN_MODEL, "hello")
    assert reply["choices"][0]["message"]["content"] == "a lighthouse at dusk"
