"""Shared tables for the Tiiny model-routing skill.

One source of truth for the tier table, the shape signals, and the
special-model table (image generation, OCR, music). Pure data and pure
functions — no Hermes imports, no network calls, no device state — so the
delegation plugin and the standalone scripts can both use it.

**Why it is loaded by path and not by package name.** The Hermes plugin
loader executes a plugin's ``__init__.py`` through
``importlib.util.spec_from_file_location``, which does not establish package
semantics: a relative ``from .tiers import ...`` fails there. And the scripts
run outside Hermes entirely, where ``from agent...`` is not importable at all.
Loading the file by path works in both places, so the table never forks.

**The figures are the device's, read on 2026-11-01, re-verified 2026-11-03.** Every NPU share and
context window below was read from ``GET /api/v1/models/online_models`` and
checked against the live device. They go stale when TiinyOS updates the
Model Store; ``scripts/tiiny_ctl.py catalog --refresh`` says so out loud
rather than letting a stale number look authoritative.
"""

from __future__ import annotations

#: The device's OpenAI-compatible endpoint. Local, on the LAN.
TIINY_BASE_URL = "http://openai.api.tiiny/v1"

#: The device's management host. Serves the Model Store catalogue.
TIINY_HOST = "http://tiinyhost.local"

#: Provider name as configured in ``providers:`` in config.yaml.
TIINY_PROVIDER = "custom:tiiny"

#: Task tier -> (model id, NPU share, context window).
#:
#: The NPU and context figures were read from the device's own catalogue
#: endpoint. They are not decoration: the NPU share is what decides whether a
#: model can stay resident alongside the others a batch needs, and the context
#: window is the ceiling on how much a child can hold at once.
#:
#: A tier can list more than one candidate. The first is the default; the rest
#: are the fallbacks in the order the device's own descriptions support.
TIER_CHOICES: dict[str, tuple[tuple[str, int, int], ...]] = {
    "research": (
        ("InternScience/Sage-A1.5-Turbo", 48, 262144),
        ("endless-frontier/BigBang-v1-Turbo", 54, 131072),
    ),
    "index": (
        ("openai/gpt-oss-20b", 27, 131072),
    ),
    "code": (
        ("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
        ("Qwen/Qwen3-Coder-Next", 94, 131072),
    ),
    "browser": (
        ("Qwen/Qwen3.8-27B", 52, 262144),
    ),
    "draft": (
        ("Qwen/Qwen3.5-9B", 29, 131072),
    ),
    "general": (
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
    ),
}

#: Which model each tier resolves to — the first choice in its list.
TIER_MODEL: dict[str, str] = {
    tier: choices[0][0] for tier, choices in TIER_CHOICES.items()
}

#: The tier names a caller may pass explicitly.
VALID_TIERS = tuple(sorted(TIER_MODEL))

#: The generalist. Every tier falls back to it when nothing else is resident,
#: because the generalist is what the watchdog keeps resident.
GENERALIST = "Qwen/Qwen3.6-35B-A3B"

#: Shape signals. These are matched against the task goal, lowercased.
#:
#: Ordering matters: the first tier with a signal wins, so the specific
#: shapes are tested before the general ones.
SHAPE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("research", (
        "research", "literature", "survey", "investigate", "find sources",
        "web search", "search the web", "literature review", "deep dive",
        "competitive analysis", "market analysis", "sweep the",
    )),
    ("index", (
        "index", "indexing", "inventory", "classify", "classify every",
        "categorize", "catalog", "catalogue", "list every file", "walk the",
        "enumerate", "manifest", "tag every", "bulk", "batch classify",
    )),
    ("browser", (
        "browser", "click through", "web ui", "web page", "fill in the form",
        "navigate the site", "screenshot the", "scrape the page", "automate the browser",
    )),
    ("code", (
        "code", "refactor", "implement", "write a function", "bug", "debug",
        "fix the", "compile", "unit test", "patch the", "repository", "repo",
        "module", "script that", "shell script", "migrate the schema",
    )),
    ("draft", (
        "draft", "summar", "rewrite", "rephrase", "bullet", "outline",
        "condense", "shorten", "proofread", "reword", "tl;dr", "summarise",
    )),
)

#: Models that do a job rather than hold a conversation. They are not
#: delegation targets — a child speaks chat completions, and these do not —
#: so they live in their own table, chosen by what the job IS rather than by
#: the shape of a goal.
#:
#: id -> (NPU share, kind, role, when to reach for it)
SPECIAL_MODELS: dict[str, tuple[int, str, str, str]] = {
    # --- image generation ---
    "Tongyi-MAI/Z-Image-Turbo": (
        26, "image", "default — photorealism and legible text",
        "One image model that handles most things well. Also the one that "
        "renders text accurately, so it is the pick for a logo, a title card "
        "or any image with words in it. ~9s at 512x512, ~55s at 1024x1024.",
    ),
    "HiDream-ai/HiDream-O1-Image-Dev": (
        30, "image", "maximum fidelity",
        "The subject IS the detail — fur, foliage, reflections, complex "
        "light. ~34s at 1024x1024, and it goes to 2048x2048. About 3x slower "
        "than the default, so it earns its keep only when detail is the point.",
    ),
    "TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic": (
        26, "image", "realistic people",
        "The subject is a person and what matters is skin, hair and fabric. "
        "A LoRA on the Z-Image base, so it inherits its speed.",
    ),
    "YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet": (
        26, "image", "character design sheet",
        "A character turnaround — several perspectives, facial expressions "
        "and a colour palette in ONE image. A LoRA on the Z-Image base.",
    ),
    "fal/FLUX.2-klein-4B-Background-Remove": (
        26, "image", "background removal — NOT a generator",
        "You already HAVE a photo and want the subject cut out for product "
        "photography or compositing. An adapter, so it runs in the same pass.",
    ),
    # --- documents ---
    "PaddlePaddle/PP-OCRv6-Medium": (
        1, "ocr", "text extraction from images",
        "Reading text out of a scanned page, a screenshot or a photo. 1% NPU, "
        "so it costs almost nothing to keep around.",
    ),
    "PaddlePaddle/PP-DocLayoutV3": (
        20, "ocr", "document layout analysis",
        "Where the blocks are on a page — tables, columns, figures. The "
        "companion to the OCR model, not a replacement for it.",
    ),
    # --- audio ---
    "tencent/SongGeneration-v2-large": (
        28, "music", "music generation",
        "A song from a description: vocals, structure, instrumentation.",
    ),
    "RoyalCities/Foundation-1": (
        5, "music", "short instrumental clips",
        "A quick instrumental bed — a sting, a loop, a background cue. 5% NPU.",
    ),
}

#: The default model per special kind, used when no cue matches.
SPECIAL_DEFAULTS: dict[str, str] = {
    "image": "Tongyi-MAI/Z-Image-Turbo",
    "ocr": "PaddlePaddle/PP-OCRv6-Medium",
    "music": "tencent/SongGeneration-v2-large",
}

#: Cue -> model. Ordered from most specific to least; the first kind whose
#: cue matches wins, so a request that says "photorealistic logo" gets the
#: text-accurate default rather than the high-fidelity model.
SPECIAL_CUES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("image", (
        "character sheet", "turnaround", "character design", "expression sheet",
    ), "YeiYeiArt/Z-Image-Turbo-CharacterDesignSheet"),
    ("image", (
        "cut out", "cutout", "remove the background", "background removal",
        "isolate the subject", "composite",
    ), "fal/FLUX.2-klein-4B-Background-Remove"),
    ("image", (
        "maximum fidelity", "highest fidelity", "ultra detailed", "fine detail",
        "complex lighting", "reflections", "foliage", "fur",
        "2048", "4k",
    ), "HiDream-ai/HiDream-O1-Image-Dev"),
    ("image", (
        "realistic person", "realistic people", "portrait of a man",
        "portrait of a woman", "realistic human", "skin texture",
    ), "TaoBaiBai2025/Z-Image-Turbo-Creating-Realistic"),
)

#: Sizes verified to work on this device. Anything else is a guess, and the
#: device's error is precise about why.
KNOWN_GOOD_SIZES: dict[str, tuple[str, ...]] = {
    "Tongyi-MAI/Z-Image-Turbo": ("1024x1024", "1280x768", "1152x768", "1024x768", "512x512"),
    "HiDream-ai/HiDream-O1-Image-Dev": ("1024x1024", "2048x2048", "1536x1024", "1024x1536"),
}


def detect_tier(goal: str) -> str:
    """Return the task tier for a goal, or ``general`` when unrecognised.

    The shape is read from the goal text because shape is what predicts which
    model does well. A goal that mentions "index the vault" is an indexing
    job; a goal that says "refactor these three modules" is a coding job.
    Matching on the *subject* is brittle in a different way: a research task
    about code matches code keywords and gets the coder.
    """
    text = (goal or "").lower()
    for tier, signals in SHAPE_SIGNALS:
        for signal in signals:
            if signal in text:
                return tier
    return "general"


def tier_cost(tier: str) -> tuple[int, int]:
    """Return the (NPU share, context window) of a tier's default model."""
    model, npu, ctx = TIER_CHOICES[tier][0]
    return npu, ctx


def model_npu(model: str) -> int | None:
    """Return the NPU share of a model, from whichever table has it."""
    for choices in TIER_CHOICES.values():
        for name, npu, _ctx in choices:
            if name == model:
                return npu
    entry = SPECIAL_MODELS.get(model)
    if entry:
        return entry[0]
    return None


def model_context(model: str) -> int | None:
    """Return the context window of a model, from whichever table has it."""
    for choices in TIER_CHOICES.values():
        for name, _npu, ctx in choices:
            if name == model:
                return ctx
    return None


def pick_special_model(description: str, kind: str = "image") -> tuple[str, str]:
    """Choose a special model for a job description.

    Returns ``(model id, reason)``. The reason is what makes the choice
    arguable rather than magic: it names the cue that matched, or says the
    default was used because nothing more specific did.

    A cue only wins if its model is one this device can actually run. The
    candidate list is the table's entries for that kind; the *availability*
    check happens against the device's download state, which the caller
    supplies.
    """
    text = (description or "").lower()
    for cue_kind, cues, model in SPECIAL_CUES:
        if cue_kind != kind:
            continue
        for cue in cues:
            if cue in text:
                return model, f"matched '{cue}'"
    default = SPECIAL_DEFAULTS.get(kind)
    if default is None:
        raise KeyError(f"no default special model for kind {kind!r}")
    return default, "default — nothing more specific matched"
