"""Find a model in the appliance stores that can do a described job.

Two questions, and they are not the same question:

  * "which model can do this?" - the device's own catalogue is the
    authority. Every appliance publishes its whole store with a type, a
    capability list, a description, its own popularity ranking, whether
    it is downloaded, how much NPU it wants, and how long it takes to
    load.
  * "what would it cost to run it here?" - the NPU budget and the disk.

The second question is the one the catalogue cannot answer on its own.
A model can be perfect for the job and still be impossible to place:
the box may have no NPU headroom beside what is already resident, or
no disk left for the weights. So every candidate carries a placement per
box, saying what each one would take.

**The NPU arithmetic is the mesh's, not this module's.** A co-resident
set must sum to 95 or less, never 100, because residency carries
runtime and KV-cache overhead that the declared NPU share does not show.
A model declaring 48% and another declaring 52% need more than the
pool, and the second load fails even though the arithmetic says it fits.

**The disk size is an estimate.** The device publishes no per-model file
size, only the pool's totals, so the size is derived from the declared
NPU share: a model's share of the 48 GiB pool is its weight file's
share of the same pool. It is close for small models and an
over-estimate for large ones, because a large model's runtime overhead
does not show in the declared number. It is enough to catch "this will
not fit on the octo", which is the case worth catching.
"""

from __future__ import annotations

import re

#: The NPU pool on both appliances (LQ50-48GB).
NPU_POOL_GB = 48

#: The share of the pool a co-resident set may use. Not 100 - see the
#: module docstring.
NPU_BUDGET = 95

#: Where the device publishes its disk usage.
STORAGE_PATH = "/api/v1/sys/storage"

#: Query words that carry no signal about WHICH model is wanted.
STOPWORDS = frozenset("""
a an the of for with to and or in on at by from as is are was were be been
being this that these those it its i me my we our you your they them
do does did done can could would should will shall may might must
please help want needs need like some any all each every both few more
most other such than then there here when where which who whom what how why
create creating creates make making made generate generating generates
new use used using get getting give given take taken also into about over
under me something anything thing way just now really very
""".split())

#: Multi-word intents, checked before the single words. "text to speech"
#: is TTS, but "speech" on its own usually means ASR, so the phrase has
#: to be seen whole.
PHRASES: dict[str, tuple[str, ...]] = {
    "text to speech": ("tts",),
    "speech to text": ("asr",),
    "text to image": ("image_gen",),
    "image to text": ("ocr",),
    "text to video": ("video_gen",),
    "text to music": ("music_gen",),
    "read aloud": ("tts",),
    "voice over": ("tts",),
    "voiceover": ("tts",),
    "remove background": ("image_gen",),
    "cut out": ("image_gen",),
    "turnaround": ("image_gen",),
    "character sheet": ("image_gen",),
}

#: Single words that name a job, mapped onto the mesh's own capability
#: vocabulary. The device's capability strings are fixed and known, so
#: this mapping is exact rather than fuzzy: a "drawing" IS an image job,
#: not a chat job that happens to mention pictures.
LEXICON: dict[str, tuple[str, ...]] = {
    # --- image generation ---
    "drawing": ("image_gen",),
    "draw": ("image_gen",),
    "picture": ("image_gen",),
    "photo": ("image_gen",),
    "photograph": ("image_gen",),
    "photorealistic": ("image_gen",),
    "realistic": ("image_gen",),
    "image": ("image_gen",),
    "images": ("image_gen",),
    "illustration": ("image_gen",),
    "illustrate": ("image_gen",),
    "painting": ("image_gen",),
    "paint": ("image_gen",),
    "sketch": ("image_gen",),
    "artwork": ("image_gen",),
    "art": ("image_gen",),
    "render": ("image_gen",),
    "poster": ("image_gen",),
    "logo": ("image_gen",),
    "banner": ("image_gen",),
    "portrait": ("image_gen",),
    "avatar": ("image_gen",),
    "character": ("image_gen",),
    "scene": ("image_gen",),
    "background": ("image_gen",),
    "headshot": ("image_gen",),
    "cartoon": ("image_gen",),
    "anime": ("image_gen",),
    "comic": ("image_gen",),
    "thumbnail": ("image_gen",),
    "icon": ("image_gen",),

    # --- OCR / document reading ---
    "ocr": ("ocr",),
    "scan": ("ocr",),
    "scanned": ("ocr",),
    "screenshot": ("ocr",),
    "receipt": ("ocr",),
    "invoice": ("ocr",),
    "form": ("ocr",),
    "handwriting": ("ocr",),
    "transcribe": ("asr",),
    "transcription": ("asr",),

    # --- speech ---
    "speech": ("asr",),
    "audio": ("asr",),
    "podcast": ("asr",),
    "interview": ("asr",),
    "voice": ("tts",),
    "speak": ("tts",),
    "narrate": ("tts",),
    "narrator": ("tts",),
    "spoken": ("tts",),
    "vocalise": ("tts",),
    "vocalize": ("tts",),

    # --- music ---
    "music": ("music_gen",),
    "song": ("music_gen",),
    "melody": ("music_gen",),
    "instrumental": ("music_gen",),
    "background music": ("music_gen",),
    "soundtrack": ("music_gen",),

    # --- other modalities ---
    "video": ("video_gen",),
    "animation": ("video_gen",),
    "3d": ("three_d",),
    "mesh": ("three_d",),
    "embed": ("embedding",),
    "embedding": ("embedding",),
    "embeddings": ("embedding",),
    "vector": ("embedding",),
    "rerank": ("rerank",),
    "ranking": ("rerank",),
    "classify": ("classification",),
    "classification": ("classification",),
    "categorise": ("classification",),
    "categorize": ("classification",),
    "sentiment": ("classification",),

    # --- conversation ---
    "chat": ("chat",),
    "answer": ("chat",),
    "conversation": ("chat",),
    "assistant": ("chat",),
    "question": ("chat",),
    "explain": ("chat",),
    "summarise": ("chat",),
    "summarize": ("chat",),
    "rewrite": ("chat",),
    "code": ("chat",),
    "coding": ("chat",),
    "program": ("chat",),
    "python": ("chat",),
    "javascript": ("chat",),
    "debug": ("chat",),
    "refactor": ("chat",),
    "vision": ("vision",),
    "look": ("vision",),
}


#: The device's own type strings, for the capabilities that have one.
#: The match is EXACT on purpose. An Image-Text-to-Text model is a
#: vision chat model, not an image generator, and a substring test on
#: "image" would call it one - which is how a chat model ends up
#: outranking the image generator for a request to draw something.
TYPE_FOR_CAP: dict[str, tuple[str, ...]] = {
    "image_gen": ("text-to-image",),
    "ocr": ("image-to-text",),
    "tts": ("text-to-speech",),
    "asr": ("asr",),
    "music_gen": ("music generation",),
    "video_gen": ("text-to-video",),
    "three_d": ("image-to-3d",),
    "embedding": ("text embedding",),
    "rerank": ("text reranking",),
    "classification": ("text classification",),
}


def terms(text: str) -> list[str]:
    """The meaningful words of a query, in order, without repeats.

    Two characters is the floor, not three: "3d" is a real capability
    on these appliances and a three-letter floor would silently drop it
    from every query that mentioned one.
    """
    out: list[str] = []
    for word in re.findall(r"[a-z0-9_+.-]+", (text or "").lower()):
        word = word.strip("._-")
        if len(word) < 2 or word in STOPWORDS or word in out:
            continue
        out.append(word)
    return out


def hints_for(text: str) -> dict[str, list[str]]:
    """Capability hints the query implies, and the word that implied them.

    The phrase table wins over the word table: "text to speech" is TTS
    even though "speech" alone points at ASR.
    """
    lowered = (text or "").lower()
    hints: dict[str, list[str]] = {}
    for phrase, caps in PHRASES.items():
        if phrase in lowered:
            hints[phrase] = list(caps)
    for word in terms(lowered):
        caps = LEXICON.get(word)
        if caps and word not in hints:
            hints[word] = list(caps)
    return hints


def score_model(row: dict, qterms: list[str], hints: dict[str, list[str]]) -> tuple[float, list[str]]:
    """Score one catalogue row against a query. Returns (score, reasons).

    The score says how well the model fits the WORDS. It says nothing
    about whether the model can be run - that is the placement's job, and
    the two are reported separately so a perfect-but-unplaceable model
    does not hide a merely-good one that is ready to go.
    """
    score = 0.0
    why: list[str] = []

    caps = {str(c).lower() for c in (row.get("capabilities") or [])}
    mtype = str(row.get("type") or "").lower()
    supported = {str(s).lower() for s in (row.get("supported") or [])}
    model_id = str(row.get("model_id") or "").lower()
    name = str(row.get("name") or "").lower()
    tags = {str(t).lower() for t in (row.get("tags") or [])}
    desc = str(row.get("desc") or "").lower()

    def type_has(cap: str) -> bool:
        # exact, not a substring: see TYPE_FOR_CAP
        return mtype in TYPE_FOR_CAP.get(cap, ())

    for word, hinted in hints.items():
        matched = None
        for cap in hinted:
            if cap in caps or type_has(cap):
                matched = cap
                break
        if matched:
            score += 30.0
            why.append(f"'{word}' means {matched}")
            continue

    for word in qterms:
        if word in hints:
            continue
        if word in caps:
            score += 14.0
            why.append(f"capability '{word}'")
        elif word in supported:
            score += 10.0
            why.append(f"supported '{word}'")
        elif word in tags:
            score += 8.0
            why.append(f"tag '{word}'")
        elif word in name or word in model_id:
            score += 12.0
            why.append(f"name '{word}'")
        elif word in desc:
            score += 5.0
            why.append(f"description '{word}'")

    # The device's own recommendation is a better tie-breaker than any
    # rule of ours: it knows what it is good at.
    rank = row.get("recommend_rank")
    if isinstance(rank, (int, float)):
        score += max(0.0, 12.0 - float(rank))
    return score, why


def incumbent_npu(rows: list[dict]) -> int:
    """The NPU share already spoken for on a box, by what is resident."""
    total = 0
    for row in rows:
        if row.get("status") == "running":
            try:
                total += int(row.get("npu_usage") or 0)
            except (TypeError, ValueError):
                pass
    return total


def norm_storage(payload) -> dict:
    """Normalise a /api/v1/sys/storage payload.

    The device publishes total/used/remaining bytes plus a per-category
    breakdown. The categories are the useful part: "LLM" is the model
    store, "Agent" is what the agent apps have taken, and the rest are
    containers and system files. Only LLM and Agent move when models
    come and go, so they are broken out.
    """
    data = payload
    if isinstance(payload, dict):
        data = payload.get("data")
    if not isinstance(data, dict):
        return {"ok": False, "error": "unreadable storage payload"}

    def num(key: str) -> int:
        try:
            return int(data.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    categories = []
    for detail in (data.get("details") or []):
        if not isinstance(detail, dict):
            continue
        size = detail.get("size_bytes") or 0
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        entry = {"name": detail.get("name") or "", "size_bytes": size,
                 "size_gb": round(size / 1e9, 1)}
        apps = []
        for app in (detail.get("apps") or []):
            if isinstance(app, dict):
                apps.append({"name": app.get("name") or "",
                             "size_bytes": int(app.get("size_bytes") or 0)})
        if apps:
            entry["apps"] = apps
        categories.append(entry)

    remaining = num("remaining_bytes")
    return {
        "ok": True,
        "total_bytes": num("total_bytes"),
        "used_bytes": num("used_bytes"),
        "remaining_bytes": remaining,
        "total_gb": round(num("total_bytes") / 1e9, 1),
        "used_gb": round(num("used_bytes") / 1e9, 1),
        "free_gb": round(remaining / 1e9, 1),
        "categories": categories,
    }


def storage_for(target, request) -> dict:
    """Read one target's disk usage. Never raises."""
    if target.kind != "tiiny":
        return {"ok": False, "error": f"{target.kind} target has no appliance disk"}
    status, payload, _ = request(target.admin(STORAGE_PATH), target.key())
    if status != 200:
        return {"ok": False, "error": f"HTTP {status}"}
    out = norm_storage(payload)
    out["target"] = target.id
    return out


def estimate_gb(npu_usage) -> float | None:
    """The weight file's rough size on disk, from its declared NPU share."""
    try:
        share = int(npu_usage)
    except (TypeError, ValueError):
        return None
    if share <= 0:
        return None
    return round(share / 100.0 * NPU_POOL_GB, 1)


def placement(target, row: dict, incumbent: int, storage: dict | None,
              running_rows: list[dict] | None = None) -> dict:
    """What it would take to run this model on this box.

    The action is the honest part:

    ``ready``       it is running; nothing to do.
    ``load``        it is on disk and fits beside what is resident.
    ``un-reside``   it is on disk but does not fit; a resident model has
                    to go first, and the one that would have to go is
                    named.
    ``download``    it is not on this box at all.
    """
    status = row.get("status") or "not_downloaded"
    npu = 0
    try:
        npu = int(row.get("npu_usage") or 0)
    except (TypeError, ValueError):
        npu = 0

    out = {
        "target": target.id,
        "status": status,
        "npu_usage": npu,
        "load_time_s": row.get("load_time"),
    }

    if target.kind != "tiiny":
        out.update({"action": "use" if status == "available" else "unavailable",
                    "npu_free": None, "fits": None})
        return out

    free = NPU_BUDGET - incumbent
    out["npu_free"] = free
    out["fits"] = npu <= free

    if storage and storage.get("ok"):
        out["disk_free_gb"] = storage.get("free_gb")
        est = estimate_gb(npu)
        out["est_size_gb"] = est
        if est is not None:
            out["disk_fits"] = est <= (storage.get("free_gb") or 0)

    if status == "running":
        out["action"] = "ready"
    elif status == "downloaded":
        out["action"] = "load" if npu <= free else "un-reside"
    else:
        out["action"] = "download"

    if out["action"] == "un-reside":
        out["evict_candidates"] = _evict_candidates(running_rows or [], incumbent, npu)
        out["note"] = (
            f"{npu}% will not fit beside {incumbent}% already resident "
            f"(headroom {free}%, budget {NPU_BUDGET}%)"
        )
    return out


def _evict_candidates(running_rows: list[dict], incumbent: int, need: int) -> list[str]:
    """Which resident models, if stopped, would make room for this one.

    The smallest sufficient set is listed first, and the generalist -
    the model every other tier falls back to - is never in it unless
    nothing else will do. Stopping a resident model costs seconds and is
    reversible in seconds; the order of this list is the order of
    preference.
    """
    free = NPU_BUDGET - incumbent
    shortfall = need - free
    if shortfall <= 0:
        return []
    candidates = []
    for row in running_rows:
        # only what is RESIDENT can be stopped to make room. A model that
        # is merely downloaded holds no NPU share and stopping it would
        # change nothing.
        if (row.get("status") or "") != "running":
            continue
        mid = row.get("model_id") or ""
        try:
            share = int(row.get("npu_usage") or 0)
        except (TypeError, ValueError):
            share = 0
        candidates.append((share, mid))
    # non-generalist first, then smallest share first
    candidates.sort(key=lambda c: (mid_is_generalist(c[1]), c[0]))
    chosen: list[str] = []
    freed = 0
    for share, mid in candidates:
        if freed >= shortfall:
            break
        chosen.append(mid)
        freed += share
    return chosen


def mid_is_generalist(model_id: str) -> bool:
    """Is this the model every other tier falls back to?"""
    return (model_id or "").lower() == "qwen/qwen3.6-35b-a3b"
