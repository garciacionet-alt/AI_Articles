"""A fake Tiiny Pocket Lab that fails the way the real appliance fails.

Everything in here was MEASURED on the appliance on 2026-11-05:

  * a load is a swap, but it evicts only as MUCH as it needs, largest
    first — the 55% Coder loaded into the 86% default set settles at 94%,
    not at 55%;
  * an unload removes the named model and leaves the rest alone;
  * admission is not execution — a generation succeeds at 81% occupancy and
    fails above it with HTTP 500, code 150004;
  * a model that is not resident answers 404, code 404.

The point of the fake is that most of the suite runs against it, so it has
to fail the way the device fails.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Iterable

from tis.device import DeviceError
from tis.registry import Registry

# The appliance's own resident models and their measured NPU cost.
APPLIANCE_MODELS: dict[str, int] = {
    "Qwen/Qwen3.6-35B-A3B": 47,
    "openai/gpt-oss-20b": 27,
    "Qwen/Qwen3-ASR-1.7B": 7,
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": 5,
    "Supertone/supertonic-3": 0,
    "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo": 55,
}

# The watchdog restores these five — 86% of the NPU in total. The Coder is
# deliberately absent: the agent holds that one itself.
DEFAULT_RESIDENT: tuple[str, ...] = (
    "Qwen/Qwen3.6-35B-A3B",
    "openai/gpt-oss-20b",
    "Qwen/Qwen3-ASR-1.7B",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Supertone/supertonic-3",
)

# A generation is admitted at this occupancy and refused above it.
ADMISSION_LIMIT = 81

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_bytes(
    width: int = 1,
    height: int = 1,
    colour: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> bytes:
    """A real PNG, built by hand — Pillow is not in the test environment."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeDevice:
    """The fake appliance.

    It knows every model's NPU cost — the image models from the registry,
    the appliance's own models from the measured table — and it enforces
    the residency rules the real device enforces.
    """

    def __init__(
        self,
        registry: Registry | Path | str,
        *,
        resident: Iterable[str] | None = None,
        replies: dict[str, str] | None = None,
    ):
        self.registry = (
            registry if isinstance(registry, Registry) else Registry.load(Path(registry))
        )
        self._costs: dict[str, int] = dict(APPLIANCE_MODELS)
        for model in self.registry.models:
            self._costs[model.id] = model.npu_usage
        self._costs[self.registry.planner.id] = self.registry.planner.npu_usage
        self._resident: list[str] = list(
            DEFAULT_RESIDENT if resident is None else resident
        )
        self._replies = dict(replies or {})
        self.calls: list[tuple[str, ...]] = []
        #: The prompts passed to chat(), in order. Useful for asserting that
        #: a component told the judge what it was judging.
        self.prompts: list[str] = []
        #: The models on the fake's disk, and the downloads in flight.
        self._downloaded: set[str] = {
            model.id for model in self.registry.models if model.downloaded
        }
        self._downloading: dict[str, float] = {}
        #: The fake's disk, in bytes. Big enough for every model.
        self._total_bytes = 512 * 1024 ** 3
        #: How far a download advances on each poll, in percent.
        self._download_step = 25.0
        #: The messages the fake's download returns.
        self.downloads: list[str] = []

    # --- residency ---------------------------------------------------------

    def cost_of(self, model: str) -> int:
        """The NPU cost of a model, in percent."""
        try:
            return self._costs[model]
        except KeyError:
            raise DeviceError(
                f"unknown model: {model}", retryable=True, status=404, code=404
            ) from None

    def occupancy(self) -> int:
        """The total NPU cost of the resident set, in percent."""
        return sum(self.cost_of(model) for model in self._resident)

    def resident(self) -> list[str]:
        return list(self._resident)

    def set_resident(self, models: Iterable[str]) -> None:
        """Pin the resident set — for tests that need a measured state."""
        wanted = list(dict.fromkeys(models))
        for model in wanted:
            self.cost_of(model)
        self._resident = wanted

    def load(self, model: str) -> None:
        self.cost_of(model)
        self.calls.append(("load", model))
        # A load is a swap, but the device evicts only as MUCH AS IT NEEDS.
        #
        # Measured 2026-11-05 at 17:23: with the five-model default set
        # resident (86%) and the 55% Coder loaded, the device settled at
        # 94% — it evicted the 47% generalist and kept the 0%, 5%, 7% and
        # 27% models alongside. Evicting the largest first reproduces that.
        #
        # This matters because the product's hot path depends on it: the
        # 55% planner and a 26% image model fit together at 81%, and the
        # critic needs the planner to stay resident. A fake that evicted
        # everything could not express that path at all.
        wanted = [m for m in self._resident if m != model]
        wanted.append(model)
        total = sum(self.cost_of(m) for m in wanted)
        while total > 100:
            candidates = [m for m in wanted
                          if m != model and self.cost_of(m) > 0]
            if not candidates:
                break
            victim = max(candidates, key=self.cost_of)
            wanted.remove(victim)
            total -= self.cost_of(victim)
        self._resident = wanted

    def unload(self, model: str) -> None:
        self.cost_of(model)
        self.calls.append(("unload", model))
        # Unloading removes the named model and leaves the rest alone.
        #
        # On the appliance the device may also reclaim other models it no
        # longer wants to hold — measured once, where unloading a 27% model
        # also dropped a 62% one — but its reclamation policy is not
        # characterised, so the fake does the minimal thing.
        #
        # That errs toward a HIGHER occupancy, which is the safe direction:
        # the fake fails a generation more readily than the real device
        # does, so a test that passes here passes there.
        self._resident = [m for m in self._resident if m != model]

    # --- the catalogue, the disk, and the download -------------------------

    def catalogue(self) -> list[dict]:
        """The store catalogue, as the fake's downloads change it.

        Each poll advances an in-flight download, so a caller that polls
        really does watch it progress rather than being handed the end
        state at once.
        """
        for model, progress in list(self._downloading.items()):
            advanced = progress + self._download_step
            if advanced >= 100.0:
                self._downloading.pop(model, None)
                self._downloaded.add(model)
            else:
                self._downloading[model] = advanced

        rows = []
        for model in self.registry.models:
            if model.id in self._downloading:
                status = "downloading"
                progress = self._downloading[model.id]
            elif model.id in self._downloaded:
                status = "downloaded"
                progress = 100.0
            else:
                status = "not_downloaded"
                progress = 0.0
            rows.append({
                "fullname": model.id,
                "status": status,
                "progress": progress,
                "tags": [{"size": model.size_bytes}],
            })
        return rows

    def storage(self) -> dict:
        """The fake's disk: total, used, remaining."""
        used = 0
        for model in self._downloaded:
            try:
                used += self.registry.by_id(model).size_bytes
            except Exception:
                continue
        return {
            "total_bytes": self._total_bytes,
            "used_bytes": used,
            "remaining_bytes": max(0, self._total_bytes - used),
        }

    def download(self, model: str) -> str:
        """Start a download. The fake completes it over the next polls."""
        self.downloads.append(model)
        if model not in self._downloaded:
            self._downloading.setdefault(model, 0.0)
        return f"started downloading {model}"

    def vision(self, model: str, question: str, image: bytes) -> str:
        """Answer a question about an image.

        Scripted, like chat(): the reply is looked up by the judge's
        model id, so a test can say what the vision model "saw".
        """
        self.calls.append(("vision", model))
        self.prompts.append(question)
        reply = self._replies.get(model)
        if reply is None:
            reply = "ILLUSTRATION"
        return reply

    def chat(self, model: str, prompt: str, **kw) -> dict:
        self.calls.append(("chat", model))
        self.prompts.append(prompt)
        if model not in self._resident:
            raise DeviceError(
                f'"{model}" is not loaded.', retryable=True, status=404, code=404
            )
        entry = self._replies.get(model)
        if isinstance(entry, list):
            # A list scripts SEQUENTIAL replies, so a test can make the
            # critic fail once and then pass. The last reply repeats once
            # the list runs out.
            reply = entry.pop(0) if len(entry) > 1 else entry[0]
        elif entry is not None:
            reply = entry
        else:
            reply = f"{model} received: {prompt}"
        return {
            "choices": [{"message": {"role": "assistant", "content": reply}}],
            "model": model,
        }

    def generate(self, model: str, prompt: str, size: str) -> bytes:
        self.calls.append(("generate", model, size))
        if model not in self._resident:
            raise DeviceError(
                f'"{model}" is not loaded.', retryable=True, status=404, code=404
            )
        # Admission is not execution: the model is resident and the
        # appliance has accepted the request, but the work still fails when
        # there is not enough NPU left to run it.
        if self.occupancy() > ADMISSION_LIMIT:
            # The appliance's own failure: HTTP 500, code 150004. It clears
            # when NPU is freed, so it is retryable.
            raise DeviceError(
                "The operation failed to complete.",
                retryable=True,
                status=500,
                code=150004,
            )
        return png_bytes()
