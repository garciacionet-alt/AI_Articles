"""Talking to the Tiiny Pocket Lab.

The appliance has two surfaces. Management and residency live under the
base URL; inference lives under `/v1`:

    GET  {base_url}/v1/models              -> {"data": [{"id": ...}, ...]}
    POST {base_url}/v1/chat/completions    -> {"choices": [{"message": ...}]}
    POST {base_url}/v1/images/generations  -> {"data": [{"b64_json": ...}]}

Loading and unloading a model is not an HTTP call — it goes through the
`tiiny` CLI, and the CLI needs a pty or it dies with "could not open a new
TTY". Every load and unload here is wrapped in `script -q /dev/null`.

The bearer comes from Settings and appears nowhere else: not in a log, not
in an exception message, not in a repr.
"""
from __future__ import annotations

import base64
import subprocess
from typing import Any, Protocol, runtime_checkable

import httpx

from .config import Settings

# The appliance takes minutes, not seconds, for a full-size generation.
REQUEST_TIMEOUT = 900.0
CLI_TIMEOUT = 600.0

#: How long the CLI has to START a download. The appliance does the
#: work; the CLI's part is to ask for it and get out of the way. The
#: observed CLI started the download and then died with a Go panic,
#: blocked sending progress on a channel nobody was reading — so its
#: exit is not a verdict on anything.
DOWNLOAD_CLI_TIMEOUT = 30.0

#: The token budget for a vision question. The appliance's generalist is
#: a reasoning model: it thinks first, and the thinking is not part of
#: the reply. With a small budget it spends the whole budget thinking
#: and answers nothing, which looks exactly like a model that cannot see.
#:
#: It is generous because the budget is the difference between an answer
#: and a silence: at 1200 tokens one probe in eleven came back empty.
#: It is not the whole answer — the judge's prompt is far longer than a
#: probe's question, and a reasoning model that thinks for the whole
#: budget answers nothing. The thinking is switched off as well.
VISION_MAX_TOKENS = 4000


class DeviceError(RuntimeError):
    """A device call failed.

    `retryable` says whether the same call might work after a residency
    change — a model that is not loaded is retryable; a bad prompt is not.
    An NPU exhaustion failure (code 150004) is retryable too: freeing NPU
    and trying again is exactly what fixes it.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.code = code


@runtime_checkable
class Device(Protocol):
    """What the application needs from an appliance."""

    def chat(self, model: str, prompt: str, **kw) -> dict: ...

    def generate(self, model: str, prompt: str, size: str) -> bytes: ...

    def resident(self) -> list[str]: ...

    def load(self, model: str) -> None: ...

    def unload(self, model: str) -> None: ...

    def vision(self, model: str, question: str, image: bytes) -> str: ...

    def catalogue(self) -> list[dict]: ...

    def storage(self) -> dict: ...

    def download(self, model: str) -> str: ...


class TiinyDevice:
    """The real appliance."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def __repr__(self) -> str:
        # Never the settings: they carry the bearer.
        return f"TiinyDevice(base_url={self.settings.base_url!r})"

    # --- plumbing ----------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Strip the bearer out of anything on its way to a human."""
        key = self.settings.api_key
        if key:
            text = text.replace(key, "<redacted>")
        return text

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def _request(
        self, method: str, path: str, *, body: dict | None = None
    ) -> tuple[int, Any]:
        """One HTTP call. Returns the status and the decoded payload."""
        url = f"{self.settings.inference_base}{path}"
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.request(
                    method, url, headers=self._headers(), json=body
                )
        except httpx.HTTPError as exc:
            raise DeviceError(
                self._redact(f"device call to {path} failed: {exc}"), retryable=True
            ) from None
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": {"message": response.text}}
        return response.status_code, payload

    def _management(
        self, method: str, path: str, *, body: dict | None = None
    ) -> tuple[int, Any]:
        """One call to the appliance's MANAGEMENT api.

        The inference surface is ``/v1/...``; the management surface is
        ``/api/v1/...``. Same host, same bearer.
        """
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.request(
                    method, url, headers=self._headers(), json=body
                )
        except httpx.HTTPError as exc:
            raise DeviceError(
                self._redact(f"device call to {path} failed: {exc}"),
                retryable=True,
            ) from None
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": {"message": response.text}}
        return response.status_code, payload

    def _fail(self, status: int, payload: Any, model: str | None = None) -> DeviceError:
        """Turn an error response into a DeviceError."""
        error: Any = {}
        if isinstance(payload, dict):
            error = payload.get("error") or {}
        if not isinstance(error, dict):
            error = {}
        message = error.get("message")
        code = error.get("code")
        error_type = error.get("type")
        if status == 404 and (code == 404 or error_type == "model_not_found"):
            if model:
                return DeviceError(
                    f'"{model}" is not loaded.', retryable=True, status=404, code=404
                )
            return DeviceError(
                self._redact(str(message or "not found")),
                retryable=True,
                status=404,
                code=404,
            )
        if not message:
            message = f"device call failed with status {status}"
        return DeviceError(
            self._redact(str(message)),
            # An NPU exhaustion failure clears when NPU is freed.
            retryable=code == 150004,
            status=status,
            code=code if isinstance(code, int) else None,
        )

    # --- the protocol ------------------------------------------------------

    def chat(self, model: str, prompt: str, **kw) -> dict:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            **kw,
        }
        status, payload = self._request("POST", "/chat/completions", body=body)
        if status >= 400:
            raise self._fail(status, payload, model)
        return payload

    def generate(self, model: str, prompt: str, size: str) -> bytes:
        body = {"model": model, "prompt": prompt, "size": size, "n": 1}
        status, payload = self._request("POST", "/images/generations", body=body)
        if status >= 400:
            raise self._fail(status, payload, model)
        entries = payload.get("data") if isinstance(payload, dict) else None
        if not entries:
            raise DeviceError("image generation returned no image data", status=status)
        first = entries[0]
        if first.get("b64_json"):
            try:
                return base64.b64decode(first["b64_json"])
            except (TypeError, ValueError) as exc:
                raise DeviceError(
                    self._redact(f"could not decode the generated image: {exc}")
                ) from None
        if first.get("url"):
            return self._fetch(first["url"])
        raise DeviceError("image generation returned no image data", status=status)

    def resident(self) -> list[str]:
        status, payload = self._request("GET", "/models")
        if status >= 400:
            raise self._fail(status, payload)
        entries = payload.get("data") if isinstance(payload, dict) else None
        return [
            str(entry["id"])
            for entry in entries or []
            if isinstance(entry, dict) and entry.get("id")
        ]

    def load(self, model: str) -> None:
        """Put a model into NPU memory.

        The CLI's EXIT IS NOT A VERDICT. The observed load of the 14.5
        GiB community build did the work and then sat there: the model
        was resident and the CLI had not returned after ten minutes, so
        the call timed out and the caller was told the load had failed.
        The model was loaded. The CLI had simply not got out of the way.

        So a timeout is not a failure - it is a question. The answer
        comes from the device: is the model resident now? If it is, the
        load happened and the caller should carry on. If it is not, the
        load really did fail and the caller should hear about it.

        This is the same rule the download path already follows: the
        catalogue is the authority on what the appliance did, because the
        CLI is not.
        """
        try:
            self._cli("load", model)
            return
        except DeviceError as exc:
            if "timed out" not in str(exc):
                raise
        # The CLI timed out. Ask the device what actually happened.
        if model in self.resident():
            return
        raise DeviceError(
            self._redact(f"tiiny load timed out and {model} is not resident"),
            retryable=True,
        )

    def unload(self, model: str) -> None:
        self._cli("unload", model)

    def vision(self, model: str, question: str, image: bytes) -> str:
        """Ask a model about an image.

        The appliance's chat API is OpenAI-compatible and its own models
        are image-text-to-text, so an image can be handed to them as a
        content part. That is what lets the Agency CHARACTERISE a model
        instead of trusting the device's description of it.

        The image goes inline as a data URL: the device must be able to
        fetch a URL, and the file being judged lives on this machine.

        THE BUDGET IS NOT THE ONLY PROBLEM — THE THINKING IS.
        The appliance's generalist is a REASONING model: it thinks before
        it answers, and the thinking is not part of the reply. With a
        small token budget it spends the whole budget thinking and
        answers nothing at all — which looks exactly like a model that
        cannot see.

        Measured 2026-11-07 on the live judge prompt: with thinking on,
        the reply was sometimes prose that did not follow the format and
        sometimes nothing at all; the same call with thinking off
        returned 80 tokens and a well-formed verdict. Asking for 8000
        tokens with thinking ON returned HTTP 502 from the upstream.

        So the judge asks for no thinking and a generous budget. The
        judge needs a verdict, not a deliberation, and a deliberation
        that runs out of budget is a silence that looks like blindness.
        """
        encoded = base64.b64encode(image).decode("ascii")
        body = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }],
            "max_tokens": VISION_MAX_TOKENS,
            # No thinking. The judge answers a format, not a question.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        status, payload = self._request("POST", "/chat/completions", body=body)
        if status != 200:
            raise self._fail(status, payload, model)
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise DeviceError(
                self._redact(f"the device returned no reply from {model}"),
                retryable=True,
            ) from None
        return str(message.get("content") or "")

    # --- the catalogue, the disk, and the download -------------------------

    def catalogue(self) -> list[dict]:
        """The appliance's store catalogue, live.

        Every record carries a ``status`` — "downloaded", "not_downloaded",
        "running", or "downloading" — and a ``progress`` percentage while
        a download is in flight. It is the only place the appliance says
        what is on its disk RIGHT NOW.

        A model's size is buried in the record's tags: ``tags[].size`` in
        bytes. That is the only place the device says how much disk a
        model will take, and the capacity check needs it before it can
        promise a download will fit.
        """
        status, payload = self._management("GET", "/api/v1/models/online_models")
        if status != 200:
            raise self._fail(status, payload)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "models", "results"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return rows
        return []

    def storage(self) -> dict:
        """The appliance's disk: total, used, remaining, and a breakdown.

        ``remaining_bytes`` is the number that matters. It is what a
        model's size is compared against before anything is downloaded.
        """
        status, payload = self._management("GET", "/api/v1/sys/storage")
        if status != 200:
            raise self._fail(status, payload)
        if not isinstance(payload, dict):
            raise DeviceError("the device returned no storage information")
        return payload

    def download(self, model: str) -> str:
        """Start a download, through the vendor CLI.

        The management API's download route is not discoverable — every
        shape of request to it answers 404 — so the download goes through
        the CLI, which is the supported client and which holds its OWN
        credentials. The Agency therefore never needs a second secret.

        The CLI STARTS the download and returns; the appliance does the
        work. It is also unreliable at the END of its job: the observed
        run started the download and then died with a Go panic, blocked
        sending progress on a channel nobody was reading.

        So the call is given a short timeout, and neither a non-zero exit
        nor a timeout is treated as a failure. The catalogue is the truth
        about whether the model arrived.
        """
        try:
            return self._cli("download", model, check=False,
                             timeout=DOWNLOAD_CLI_TIMEOUT)
        except DeviceError:
            # The CLI may die, or hang, after STARTING the download.
            # Whether the model arrived is the catalogue's answer, not
            # the CLI's.
            return ""

    # --- helpers -----------------------------------------------------------

    def _fetch(self, url: str) -> bytes:
        """Fetch a generated image. No bearer: the URL may point elsewhere."""
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            raise DeviceError(
                self._redact(f"could not fetch the generated image: {exc}"),
                retryable=True,
            ) from None

    def _cli(self, action: str, model: str, *, check: bool = True,
             timeout: float = CLI_TIMEOUT) -> str:
        """Load, unload, or download through the CLI.

        The CLI opens /dev/tty and dies with "could not open a new TTY"
        without a pty, so the call is wrapped in `script`.

        ``check=False`` is for the download: the CLI starts the download
        and returns while the appliance carries on with it, so its exit
        code is not a verdict on the download's outcome. The caller
        watches the catalogue instead.
        """
        command = [
            "script",
            "-q",
            "/dev/null",
            str(self.settings.tiiny_bin),
            action,
            model,
            "-y",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise DeviceError(
                self._redact(f"tiiny {action} timed out"), retryable=True
            ) from None
        except OSError as exc:
            raise DeviceError(
                self._redact(f"could not run tiiny {action}: {exc}")
            ) from None
        if result.returncode != 0 and check:
            detail = (result.stderr or result.stdout or "").strip()
            raise DeviceError(self._redact(f"tiiny {action} failed: {detail}"))
        return (result.stdout or "").strip()
