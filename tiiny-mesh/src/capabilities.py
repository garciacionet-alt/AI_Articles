"""Canonical capability vocabulary for the TiinyMesh catalogue.

Every target in the mesh describes its models in its own language: the
Tiiny appliances use a `type` string and a device-specific `capabilities`
list, Off Grid AI uses a `kind` field, and the plain OpenAI targets
(Ollama, LM Studio, MiniMax) say nothing at all beyond the model id.
This module translates all of that into ONE vocabulary, so a router can
ask "can this model chat?" without caring who is serving it.

The vocabulary is fixed and closed:

    chat, reasoning, code, embedding, rerank, asr, tts, vision, image_gen,
    image_edit, ocr, audio_understand, music_gen, video_gen, three_d,
    classification, grounding

Rules the classifiers follow:

  * the type map decides. The device's own `capabilities` list can only
    ADD to what the type map said - it can never remove or contradict it.
  * when there is no type metadata at all (a generic OpenAI target), the
    model id is read, and only for ids that are unambiguous.
  * when nothing is known, the answer is `["chat"]`. A chat model is the
    most common thing in the estate and the safest default; guessing
    "embedding" for a model that turns out to be a generator is far more
    expensive than the reverse.

Embedding dimensions are measured, not documented. `embed_dimension`
returns what the server actually returned - see EMBED_DIMENSIONS below
and the note on what could not be measured.

Standard library only.
"""

from __future__ import annotations

import re

__all__ = [
    "CANONICAL_CAPABILITIES",
    "TIINY_TYPE_MAP",
    "OGAD_KIND_MAP",
    "MEASURED_TIINY_TYPES",
    "EMBED_DIMENSIONS",
    "EMBED_DIMENSIONS_BY_TARGET",
    "EMBED_DIMENSIONS_NOT_MEASURED",
    "classify_tiiny",
    "classify_ogad",
    "classify_generic",
    "is_chat_capable",
    "chat_models_only",
    "embed_dimension",
]


# --------------------------------------------------------------------------
# the vocabulary
# --------------------------------------------------------------------------

#: Every capability name this module will ever emit, in canonical order.
CANONICAL_CAPABILITIES: tuple[str, ...] = (
    "chat",
    "reasoning",
    "code",
    "embedding",
    "rerank",
    "asr",
    "tts",
    "vision",
    "image_gen",
    "image_edit",
    "ocr",
    "audio_understand",
    "music_gen",
    "video_gen",
    "three_d",
    "classification",
    "grounding",
)

#: The Tiiny store's `type` field -> canonical capabilities.
#: Every key here was read off a live device catalogue (both appliances
#: carry the identical 93-model store); see MEASURED_TIINY_TYPES.
TIINY_TYPE_MAP: dict[str, list[str]] = {
    "ASR": ["asr", "audio_understand"],
    "Image-Text-to-Text": ["chat", "vision"],
    "Image-to-3D": ["three_d"],
    "Image-to-Text": ["ocr", "vision"],
    "Music Generation": ["music_gen"],
    "Text Classification": ["classification"],
    "Text Embedding": ["embedding"],
    "Text Generation": ["chat"],
    "Text Reranking": ["rerank"],
    "Text-to-Image": ["image_gen"],
    "Text-to-Speech": ["tts"],
    "Text-to-Video": ["video_gen"],
}

#: Off Grid AI's `/v1/models` `kind` field -> canonical capabilities.
#: Measured against the live OGAD server on this Mac (14 models, 6 kinds).
OGAD_KIND_MAP: dict[str, list[str]] = {
    "chat": ["chat"],
    "vision": ["vision", "chat"],
    "image": ["image_gen"],
    "speech": ["tts"],
    "transcription": ["asr", "audio_understand"],
    "grounding_specialist": ["grounding"],
}

#: The type strings actually present in the Tiiny store catalogues.
#: Both appliances expose exactly this set, so TIINY_TYPE_MAP covers the
#: device vocabulary completely - nothing in the store is unclassified.
MEASURED_TIINY_TYPES: frozenset[str] = frozenset({
    "ASR",
    "Image-Text-to-Text",
    "Image-to-3D",
    "Image-to-Text",
    "Music Generation",
    "Text Classification",
    "Text Embedding",
    "Text Generation",
    "Text Reranking",
    "Text-to-Image",
    "Text-to-Speech",
    "Text-to-Video",
})


# --------------------------------------------------------------------------
# the device's own capability strings
# --------------------------------------------------------------------------

# The Tiiny `capabilities` field carries the device's private vocabulary:
# 'main', 'audio', 'image', 'systemone', 'voice', 'music', 'Video',
# 'Image', '3d', 'embedding', 'rerank', 'ocr', 'OCR'. These are the only
# readings taken from it. Each can only ADD to the type map's answer.
_CAPABILITY_ADDS: dict[str, str] = {
    "ocr": "ocr",
    "embedding": "embedding",
    "rerank": "rerank",
    "voice": "tts",
    "audio": "asr",
    "music": "music_gen",
    "3d": "three_d",
    "video": "video_gen",
    "main": "chat",
}

# Types that already decide the image axis. 'Image' on one of these means
# "this model works with images", not "this model generates images", so
# it must not add image_gen.
_IMAGE_TYPES: frozenset[str] = frozenset({
    "Image-Text-to-Text",
    "Image-to-3D",
    "Image-to-Text",
    "Text-to-Image",
})


def _dedup(caps: list[str]) -> list[str]:
    """Drop repeats, keeping first-seen order.

    The order is the one the type map declared, so the answer reads the
    same way the vocabulary above does. Additions from the device's own
    capability list follow, in the order the device listed them.
    """
    seen: set[str] = set()
    out: list[str] = []
    for cap in caps:
        if cap not in seen:
            seen.add(cap)
            out.append(cap)
    return out


def _norm_id(model_id: str) -> str:
    return (model_id or "").strip().lower()


# --------------------------------------------------------------------------
# classifiers
# --------------------------------------------------------------------------


def classify_tiiny(type_str: str, capabilities: list[str] | None = None,
                   model_id: str = "") -> list[str]:
    """Canonical capabilities for a Tiiny store row.

    The `type` field decides. The device's own `capabilities` list may add
    to that answer but never contradict it: 'ocr'/'OCR' adds ocr,
    'embedding' adds embedding, 'rerank' adds rerank, 'voice' adds tts and
    'audio' adds asr - each only when the type map did not already say so -
    and 'Image'/'image' adds image_gen only for a type that is not already
    an image type.

    An unknown type falls back to the conservative model-id rules, so a
    device that ships a new type still classifies rather than vanishing.
    """
    type_key = (type_str or "").strip()
    caps: list[str] = list(TIINY_TYPE_MAP.get(type_key, []))
    known_type = type_key in TIINY_TYPE_MAP

    for raw in capabilities or []:
        token = str(raw).strip().lower()
        if not token:
            continue
        if token == "image":
            if type_key not in _IMAGE_TYPES and "image_gen" not in caps:
                caps.append("image_gen")
            continue
        implied = _CAPABILITY_ADDS.get(token)
        if implied is not None and implied not in caps:
            caps.append(implied)

    if not known_type and model_id:
        for extra in classify_generic(model_id):
            if extra not in caps:
                caps.append(extra)

    return _dedup(caps)


def classify_ogad(kind: str, model_id: str = "") -> list[str]:
    """Canonical capabilities for an OGAD `/v1/models` row.

    OGAD declares a `kind`. An unknown or missing kind falls back to the
    conservative model-id rules rather than assuming chat.
    """
    key = (kind or "").strip()
    if key in OGAD_KIND_MAP:
        return list(OGAD_KIND_MAP[key])
    return classify_generic(model_id)


def classify_generic(model_id: str) -> list[str]:
    """Canonical capabilities for a target that says nothing but its id.

    Only unambiguous ids are read: anything containing 'embed' or 'bge' is
    an embedding model, 'rerank' a reranker, 'whisper' a speech recogniser
    and 'tts' a synthesiser. Everything else is chat - never a guess.
    """
    mid = _norm_id(model_id)
    if not mid:
        return ["chat"]
    tokens = set(re.split(r"[^a-z0-9]+", mid))
    if "embed" in mid or "bge" in tokens:
        return ["embedding"]
    if "rerank" in mid:
        return ["rerank"]
    if "whisper" in mid:
        return ["asr"]
    if "tts" in tokens or "text-to-speech" in mid:
        return ["tts"]
    return ["chat"]


def is_chat_capable(caps: list[str]) -> bool:
    """True when the model can serve a chat completion."""
    return "chat" in (caps or [])


def chat_models_only(rows: list[dict]) -> list[dict]:
    """Keep only the catalogue rows that can serve a chat completion.

    Each row is expected to carry a 'capabilities' key holding the
    canonical list. Rows without one are not chat models.
    """
    return [r for r in (rows or [])
            if is_chat_capable(r.get("capabilities") or [])]


# --------------------------------------------------------------------------
# embedding dimensions (measured)
# --------------------------------------------------------------------------

#: Measured embedding dimension per model id.
#:
#: Tiiny: `Qwen/Qwen3-Embedding-0.6B` was borrowed on both appliances and
#: asked for one embedding; both returned 1024 floats, so the two boxes
#: agree and the id can be keyed once.
#:
#: Mac: Ollama's `bge-m3:latest` returns 1024 and LM Studio's
#: `text-embedding-nomic-embed-text-v1.5` returns 768. OGAD ignores the
#: model field entirely and always returns 384, whatever you ask for - it
#: reports the model as `all-MiniLM-L6-v2`, which is the key used here.
EMBED_DIMENSIONS: dict[str, int] = {
    "Qwen/Qwen3-Embedding-0.6B": 1024,
    "bge-m3:latest": 1024,
    "text-embedding-nomic-embed-text-v1.5": 768,
    "all-MiniLM-L6-v2": 384,
}

#: The same measurements, kept per target.
#:
#: Use this when an id could be served by more than one target with
#: different geometry. Today the only such case is OGAD, which answers
#: 384 for any id it is handed - including `bge-m3:latest`, which Ollama
#: serves at 1024. The id-keyed map above assumes the target that owns
#: the id; this map is authoritative when the id is shared.
EMBED_DIMENSIONS_BY_TARGET: dict[str, dict[str, int]] = {
    "tiiny-ant": {
        "Qwen/Qwen3-Embedding-0.6B": 1024,
    },
    "tiiny-octo": {
        "Qwen/Qwen3-Embedding-0.6B": 1024,
    },
    "ollama": {
        "bge-m3:latest": 1024,
    },
    "lmstudio": {
        "text-embedding-nomic-embed-text-v1.5": 768,
    },
    "ogad": {
        "all-MiniLM-L6-v2": 384,
    },
}

#: Embedding models that could NOT be measured, and why.
#:
#: Both appliances list the same eight embedding models, but only
#: `Qwen/Qwen3-Embedding-0.6B` was downloaded on either box. The other
#: seven were skipped, not failed: starting a download was out of scope.
EMBED_DIMENSIONS_NOT_MEASURED: dict[str, str] = {
    "Qwen/Qwen3-Embedding-4b": "not_downloaded on both appliances",
    "Qwen/Qwen3-Embedding-8b": "not_downloaded on both appliances",
    "Qwen/Qwen3-Vl-Embedding-2b": "not_downloaded on both appliances",
    "Qwen/Qwen3-Vl-Embedding-8b": "not_downloaded on both appliances",
    "nvidia/Nemotron-3-Embed-1B-BF16": "not_downloaded on both appliances",
    "nvidia/Nemotron-3-Embed-8b-Bf16": "not_downloaded on both appliances",
    "tencent/R3-embedding-0.6b": "not_downloaded on both appliances",
}


def embed_dimension(model_id: str) -> int | None:
    """The measured embedding dimension of a model id, or None if unknown.

    None means "not measured", never "zero" and never a guess: a caller
    that gets None has to ask the server, and one that gets an int knows
    exactly how many floats to expect back.
    """
    key = (model_id or "").strip()
    if key in EMBED_DIMENSIONS:
        return EMBED_DIMENSIONS[key]
    lowered = key.lower()
    for known, dim in EMBED_DIMENSIONS.items():
        if known.lower() == lowered:
            return dim
    return None


# --------------------------------------------------------------------------
# self-check
# --------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover - manual verification
    assert TIINY_TYPE_MAP.keys() == MEASURED_TIINY_TYPES, "type map drifted from the device"
    assert is_chat_capable(["chat"]) is True
    assert is_chat_capable(["embedding"]) is False

    rows = [
        {"model_id": "chatty", "capabilities": ["chat"]},
        {"model_id": "vector", "capabilities": ["embedding"]},
    ]
    kept = chat_models_only(rows)
    assert kept == [rows[0]], "chat_models_only did not filter correctly"

    for mid, dim in EMBED_DIMENSIONS.items():
        got = embed_dimension(mid)
        assert isinstance(got, int) and got == dim, f"embed_dimension({mid!r}) -> {got!r}"

    assert classify_tiiny("Text Embedding", ["embedding"]) == ["embedding"]
    assert classify_tiiny("Image-to-3D", ["Image", "3d"]) == ["three_d"]
    assert classify_tiiny("ASR", ["audio"]) == ["asr", "audio_understand"]
    assert classify_tiiny("Text-to-Speech", ["voice"]) == ["tts"]
    assert classify_ogad("vision") == ["vision", "chat"]
    assert classify_generic("bge-m3:latest") == ["embedding"]
    assert classify_generic("gemma3:4b") == ["chat"]

    print("capabilities.py self-check OK")
    print(f"  types classified : {len(TIINY_TYPE_MAP)}")
    print(f"  ogad kinds       : {len(OGAD_KIND_MAP)}")
    print(f"  dims measured    : {len(EMBED_DIMENSIONS)}")
    print(f"  dims not measured: {len(EMBED_DIMENSIONS_NOT_MEASURED)}")

# --------------------------------------------------------------------------
# Speech voices
# --------------------------------------------------------------------------
#
# A Tiiny TTS model does NOT accept an OpenAI-style voice name. Measured on
# this firmware:
#
#   hexgrad/Kokoro-82M            accepts Kokoro's own names: af_heart,
#                                 af_bella, am_adam, bf_emma ...
#   Qwen/Qwen3-TTS-12Hz-1.7B-Base accepts nothing tried; every request
#                                 fails with "the upstream TTS model failed"
#   Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign needs a voice DESIGN prompt
#   Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice needs ref_audio + ref_text
#
# A caller that says voice="default" - which is what the OpenAI shape
# implies - gets "Unsupported speaker: default". So the mesh maps the
# generic names onto a voice the model actually has.

#: model id -> the voices it really accepts
VOICE_MAP: dict[str, tuple[str, ...]] = {
    "hexgrad/Kokoro-82M": (
        "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
        "am_adam", "am_michael",
        "bf_emma", "bf_isabella",
        "bm_george", "bm_lewis",
    ),
}

#: the generic voice names an OpenAI-shaped caller sends, and what they mean
GENERIC_VOICES: dict[str, str] = {
    "default": "af_heart",
    "alloy": "af_heart",
    "female": "af_heart",
    "male": "am_adam",
    "nova": "af_nicole",
    "onyx": "am_michael",
    "shimmer": "af_bella",
}


def voices_for(model_id: str) -> tuple[str, ...]:
    """The voices a model accepts, if we know them."""
    if model_id in VOICE_MAP:
        return VOICE_MAP[model_id]
    for mid, voices in VOICE_MAP.items():
        if model_id.endswith(mid) or mid.split("/")[-1] in model_id:
            return voices
    return ()


def resolve_voice(model_id: str, voice: str = "") -> str:
    """Map a requested voice onto one the model really has.

    An empty or generic voice becomes the model's first known voice. A
    voice the model does not have is passed through unchanged - the
    device gives a better error than the mesh would.
    """
    voices = voices_for(model_id)
    if not voices:
        return voice
    if not voice:
        return voices[0]
    if voice in voices:
        return voice
    return GENERIC_VOICES.get(voice, voice)
