"""research.py — characterise what each model actually does.

The device's own description of a model cannot be trusted. TiinyOS's
catalogue carries the CharacterDesignSheet text verbatim on
TaoBaiBai2025's entry — a copy-paste bug in the device's own catalogue,
measured and recorded in MEASUREMENTS.md. So the curated layer of the
registry — what each model specialises in, what prompt it wants, which
sizes it accepts — is built from MEASUREMENTS, not from prose. This
module is the machine that makes them.

THE LOOP

  for each model in the catalogue
      load it, and generate a fixed matrix of probes
      measure each probe
          transparency, from the pixels — no model involved
          the artifact, the style and the text, from a vision model that
          LOOKS at the image
      unload the model
      judge the images with the generalist
      write an overlay entry and a model card

The judging is a SECOND pass, after the image model has been unloaded.
The flagship occupies 62% of the NPU pool and the generalist 47%; they
cannot share it, so a judge that looked while the image model was
resident would not fit — and the measurements would be taken on a
device that could not generate them.

WHY THE PIXELS AND NOT THE VISION MODEL

Transparency is the one fact a vision model cannot give you. A
transparent image composited onto a viewer's background looks opaque, so
"does this model render a transparent background" has to be answered
from the pixels. Everything else — what kind of picture it is, whether
the words are legible — is a question about what is IN the picture, and
that is exactly what a vision model is for.

WHAT IT PRODUCES

  - an overlay entry: the machine-readable summary that the resolver
    and the dialect translator already read
  - a model card: the human-readable summary, with the evidence
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from .device import Device, DeviceError
from .imaging import alpha_stats, read_info
from .registry import ModelSpec, Registry

#: The appliance's generalist: an image-text-to-text model, so it can be
#: shown a picture and asked about it. It is also a reasoning model,
#: which is why the device gives it a generous token budget.
JUDGE_MODEL = "Qwen/Qwen3.6-35B-A3B"

#: The artifacts the loop tests for.
ARTIFACT_CHOICES = ("icon", "logo", "photo", "poster", "comic",
                    "infographic", "illustration")


@dataclass(frozen=True)
class Probe:
    """One measurement to take.

    ``dimension`` is what the probe is FOR, ``question`` is what the
    vision model is asked. A probe with no question is measured from
    the pixels alone.
    """

    name: str
    prompt: str
    dimension: str
    size: str = "1024x1024"
    question: str = ""


#: One probe per artifact. The prompt is deliberately plain and the same
#: subject — a red fox — everywhere, so that what changes between the
#: probes is the ARTIFACT and nothing else.
ARTIFACT_PROMPTS: dict[str, str] = {
    "icon": "a simple app icon of a red fox head, centred on a plain background",
    "logo": "a minimal black wordmark logo for a brand called FOX",
    "photo": "a photograph of a red fox in a field at dawn",
    "poster": "a poster for a concert on Saturday night, with a red fox as the mascot",
    "comic": "a comic book panel showing a fox as the hero",
    "infographic": "an infographic about the life cycle of a red fox",
    "illustration": "an illustration of a red fox in a forest",
}

#: One probe per style.
STYLE_PROMPTS: dict[str, str] = {
    "flat": "a flat vector illustration of a red fox",
    "realistic": "a photorealistic portrait of a red fox",
}

#: The probe that asks for a transparent background.
ALPHA_PROBE = Probe(
    name="alpha",
    prompt="a red fox head, isolated, on a fully transparent background",
    dimension="alpha",
)

#: The probe that asks for words, so that legibility can be judged.
TEXT_PROBE = Probe(
    name="text",
    prompt="a poster with the words OPEN LATE in large letters",
    dimension="text",
    question=(
        "Copy any text that appears in this image, exactly as it is "
        "written. If there is no text at all, reply with the single word "
        "NONE."
    ),
)

#: The sizes the loop tries.
SIZE_PROBES: tuple[Probe, ...] = (
    Probe(name="size-512", prompt="a red fox in a forest",
          dimension="size", size="512x512"),
    Probe(name="size-1024x768", prompt="a red fox in a forest",
          dimension="size", size="1024x768"),
)


def default_probes(full: bool = False) -> list[Probe]:
    """The matrix.

    The short matrix tests one thing per dimension: the artifacts, the
    two styles that matter most, transparency, and text. The full matrix
    adds the size sweep and the remaining styles.

    Each probe is one generation, and a generation is 54 seconds at best
    and three minutes at worst, so the short matrix is about fifteen
    minutes per model.
    """
    probes: list[Probe] = []
    for artifact, prompt in ARTIFACT_PROMPTS.items():
        probes.append(Probe(
            name=f"artifact-{artifact}",
            prompt=prompt,
            dimension="artifact",
            question=(
                "Is this image most like an ICON, a LOGO, a PHOTO, a "
                "POSTER, a COMIC, an INFOGRAPHIC, or an ILLUSTRATION? "
                "Reply with one of those words and nothing else."
            ),
        ))
    for style, prompt in STYLE_PROMPTS.items():
        probes.append(Probe(
            name=f"style-{style}",
            prompt=prompt,
            dimension="style",
            question=(
                "Is this image FLAT VECTOR, PHOTOREALISTIC, or neither? "
                "Reply with one of those three and nothing else."
            ),
        ))
    probes.append(ALPHA_PROBE)
    probes.append(TEXT_PROBE)
    if full:
        probes.extend(SIZE_PROBES)
    return probes


class ProbeResult(BaseModel):
    """What one probe found."""

    probe: str
    dimension: str
    prompt: str
    size: str
    question: str = ""
    ok: bool = False
    answer: str = ""
    transparent_pct: float = 0.0
    partial_pct: float = 0.0
    has_alpha_channel: bool = False
    seconds: float = 0.0
    error: str = ""
    image: str = ""


class ModelCard(BaseModel):
    """What one model is, and what was measured to say so.

    This is the summary the application reads and the user is shown. It
    is written from measurements, so every field in it has an evidence
    entry behind it.
    """

    model_id: str
    name: str = ""
    role: str = ""
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    styles: list[str] = Field(default_factory=list)
    text_rendering: str = "unknown"
    alpha: str = "unknown"
    transparent_pct: float = 0.0
    quality: str = "unknown"
    speed: str = "unknown"
    sizes_verified: list[str] = Field(default_factory=list)
    sizes_rejected: list[str] = Field(default_factory=list)
    probes: list[ProbeResult] = Field(default_factory=list)
    measured_at: str = ""


class ModelResearcher:
    """Measure what a model does, and write it down."""

    def __init__(self, device: Device, registry: Registry,
                 output_dir: Path, judge_model: str = JUDGE_MODEL,
                 residency: Any = None):
        self.device = device
        self.registry = registry
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.judge_model = judge_model
        self.residency = residency

    # -- the loop ----------------------------------------------------------

    def characterise(self, model_id: str,
                     probes: Iterable[Probe] | None = None) -> ModelCard:
        """Research one model, and return its card."""
        spec = self.registry.by_id(model_id)
        chosen = list(probes) if probes is not None else default_probes()

        results = self._generate(spec, chosen)
        self._judge(results)
        return self._card(spec, results)

    def _generate(self, spec: ModelSpec,
                  probes: list[Probe]) -> list[ProbeResult]:
        """Generate every probe, and measure its pixels.

        The model is held resident for the whole pass, and the hold and
        the watchdog lock are taken through the residency manager, so
        the run cannot collide with another agent's work on the device.
        """
        if self.residency is not None:
            with self.residency.swap_to(spec.id):
                return self._generate_probes(spec, probes)
        return self._generate_probes(spec, probes)

    def _generate_probes(self, spec: ModelSpec,
                          probes: list[Probe]) -> list[ProbeResult]:
        results: list[ProbeResult] = []
        for probe in probes:
            started = time.monotonic()
            try:
                image = self.device.generate(spec.id, probe.prompt, probe.size)
            except DeviceError as exc:
                results.append(ProbeResult(
                    probe=probe.name, dimension=probe.dimension,
                    prompt=probe.prompt, size=probe.size,
                    question=probe.question, ok=False, error=str(exc),
                    seconds=round(time.monotonic() - started, 1),
                ))
                continue

            path = self.output_dir / (
                f"{spec.id.replace('/', '__')}__{probe.name}.png")
            path.write_bytes(image)
            stats = alpha_stats(image)
            results.append(ProbeResult(
                probe=probe.name, dimension=probe.dimension,
                prompt=probe.prompt, size=probe.size, question=probe.question,
                ok=True, seconds=round(time.monotonic() - started, 1),
                image=str(path),
                transparent_pct=stats.transparent_pct,
                partial_pct=stats.partial_pct,
                has_alpha_channel=stats.has_alpha_channel,
            ))
        return results

    def _judge(self, results: list[ProbeResult]) -> None:
        """Look at each image and answer what it was asked.

        The image model has been unloaded by now, so the generalist fits
        on its own.
        """
        pending = [r for r in results if r.ok and r.question and r.image]
        if not pending:
            return
        if self.residency is not None:
            with self.residency.swap_to(self.judge_model):
                self._judge_each(pending)
            return
        self._judge_each(pending)

    def _judge_each(self, pending: list[ProbeResult]) -> None:
        """Ask the judge about each image."""
        for result in pending:
            try:
                image = Path(result.image).read_bytes()
            except OSError:
                continue
            try:
                answer = self.device.vision(self.judge_model, result.question,
                                            image)
            except DeviceError as exc:
                result.error = str(exc)
                continue
            result.answer = answer.strip()

    # -- the summary -------------------------------------------------------

    def _card(self, spec: ModelSpec, results: list[ProbeResult]) -> ModelCard:
        """Turn the measurements into a card."""
        card = ModelCard(
            model_id=spec.id,
            name=spec.raw.get("name") or "",
            role=spec.role,
            measured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            probes=results,
        )

        # The artifacts the model actually produced.
        for result in results:
            if result.dimension != "artifact" or not result.ok:
                continue
            answer = result.answer.strip().strip(".").upper()
            for choice in ARTIFACT_CHOICES:
                if choice.upper() in answer:
                    if choice not in card.artifacts:
                        card.artifacts.append(choice)
                    break

        # The styles it actually produced.
        for result in results:
            if result.dimension != "style" or not result.ok:
                continue
            answer = result.answer.strip().strip(".").upper()
            for style in STYLE_PROMPTS:
                token = {"flat": "FLAT", "realistic": "PHOTOREALISTIC"}[style]
                if token in answer and style not in card.styles:
                    card.styles.append(style)

        # Transparency, from the pixels.
        for result in results:
            if result.dimension != "alpha" or not result.ok:
                continue
            card.transparent_pct = result.transparent_pct
            card.alpha = "yes" if result.transparent_pct > 1.0 else "no"

        # Legibility, from what the judge could read.
        for result in results:
            if result.dimension != "text" or not result.ok:
                continue
            answer = result.answer.strip()
            # The judge copies the text as it is laid out, so a poster
            # with the words on two lines comes back as "OPEN\nLATE".
            # Compare on flattened whitespace: the judge was RIGHT and a
            # naive substring check scored a legible poster as mangled.
            flat = " ".join(answer.split()).upper()
            if not answer or flat.startswith("NONE"):
                card.text_rendering = "none"
            elif "OPEN LATE" in flat:
                card.text_rendering = "best"
            else:
                card.text_rendering = "weak"

        # The sizes that worked.
        for result in results:
            if result.dimension != "size":
                continue
            if result.ok:
                card.sizes_verified.append(result.size)
            else:
                card.sizes_rejected.append(result.size)

        card.strengths, card.limitations = self._strengths(card)
        card.summary = self._summary(card)
        return card

    def _strengths(self, card: ModelCard) -> tuple[list[str], list[str]]:
        """What this model is good at, and what it is not."""
        strengths: list[str] = []
        limitations: list[str] = []
        if card.artifacts:
            strengths.append("produced " + ", ".join(card.artifacts))
        if card.styles:
            strengths.append("handled " + " and ".join(card.styles) + " style")
        if card.alpha == "yes":
            strengths.append(
                f"rendered a transparent background "
                f"({card.transparent_pct}% of the pixels)")
        if card.text_rendering == "best":
            strengths.append("rendered legible text")
        elif card.text_rendering == "weak":
            limitations.append("drew text that was not legible")
        elif card.text_rendering == "none":
            limitations.append("drew no text at all")
        if card.alpha == "no":
            limitations.append("rendered an opaque background")
        if card.sizes_rejected:
            limitations.append(
                "refused the sizes " + ", ".join(card.sizes_rejected))
        return strengths, limitations

    def _summary(self, card: ModelCard) -> str:
        """One paragraph, for a person to read."""
        bits = []
        if card.artifacts:
            bits.append("measured good at " + ", ".join(card.artifacts))
        if card.styles:
            bits.append("handled " + " and ".join(card.styles) + " style")
        if card.alpha == "yes":
            bits.append(f"rendered {card.transparent_pct}% transparent pixels")
        elif card.alpha == "no":
            bits.append("rendered an opaque background")
        if card.text_rendering == "best":
            bits.append("got text right")
        elif card.text_rendering == "weak":
            bits.append("mangled text")
        if not bits:
            return "No measurement was taken."
        return ("Measured on the appliance: " + "; ".join(bits) + ".")

    # -- the machine-readable half -----------------------------------------

    def overlay_entry(self, card: ModelCard) -> dict[str, Any]:
        """The overlay entry for a card.

        This is the curated layer the resolver and the dialect
        translator already read. The fields the measurements cannot
        decide — the prompt dialect, the edit operations — are left to
        the curator and are not overwritten here.
        """
        return {
            "role": card.role,
            "artifact": list(card.artifacts),
            "alpha": card.alpha == "yes",
            "text_rendering": card.text_rendering,
            "style": list(card.styles),
            "sizes_verified": list(card.sizes_verified),
            "sizes_rejected": list(card.sizes_rejected),
            "notes": card.summary,
        }


def write_card(card: ModelCard, path: Path) -> Path:
    """Write the card as JSON, beside its evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
