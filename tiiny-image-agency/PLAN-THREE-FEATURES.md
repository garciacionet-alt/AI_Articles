# Three more features — the plan

> **For Hermes:** use subagent-driven-development to execute this plan
> task-by-task. Phases K, L and M below.

**Goal:** three features the user asked for — a browsable model-card
tab, a notice-and-benchmark path for new models, and a saved-reference
workflow that makes repeated work consistent.

**Architecture:** the Agency keeps its one-path rule. Every new surface
reads through the API; nothing reaches the appliance except the
orchestrator. The three features share one prerequisite — a tab strip —
and one measurement — how the appliance actually accepts an image.

**Tech stack:** Python 3.11, FastAPI, SQLite, SSE, vanilla HTML/CSS/JS.

---

## The measurements, and what they change

Three things were measured before this plan was written, and two of
them changed the design.

### M10 — the appliance DOES take an image into generation

**This reverses an earlier conclusion, and the earlier conclusion was
wrong because the probe's detector was broken.**

The first probe sent a mistyped field and looked for the field's NAME
in the error text. The appliance answers

```
[json.exception.type_error.302] type must be string, but is number
```

without naming the field, so every candidate looked "ignored". The
truth was in the status code:

| field | answer | meaning |
|---|---|---|
| `image` | 400 `type must be string` | **recognised — a string** |
| `images` | 400 `type must be array` | **recognised — an array** |
| `image_url`, `init_image`, `input_image`, `source_image`, `image_base64`, `reference_image` | 200 | ignored, and a generation happened anyway |

So the endpoint has an image field, and `images` is a LIST. That matters
directly: a multi-reference feature has a wire format.

**But recognised is not honoured.** The second probe asked for "remove
the red half, leaving only the blue" — a prompt that mentions blue, so
a text-only model could have produced a blue picture. That test could
not distinguish the two cases and proved nothing.

The decisive test used a prompt no text-only model can answer —
*"reproduce this image as a pencil sketch, keeping the composition"* —
on an input that is half pure red and half pure blue, with a
**no-image control** alongside it.

| variant | time | half-difference | what came back |
|---|---|---|---|
| **control (no image)** | **16.3 s** | 35.8 | **a random bald man's face** |
| `image` = raw base64 | 33.9 s | 59.3 | **the input**: a rectangle split vertically, dense hatching left, light right |
| `image` = data URL | 34.4 s | 1.5 | the input's rectangle, faint vertical division |
| `images` = [raw base64] | 34.0 s | 36.0 | the input, split inverted |
| `images` = [data URL] | 34.0 s | 40.0 | the input's structure |

**Two independent signals agree.** The control drew a completely
different subject — a face, not a rectangle. Every image-bearing variant
drew the rectangle with its vertical division. And the timing splits
cleanly: **16.3 s without an image, ~34 s with one** — eighteen extra
seconds of the model reading the picture.

**The conclusion:** `image` (string) and `images` (array) both work, and
the image genuinely conditions the output. This was verified visually as
well as numerically: the control is a face, the image variant is the
input.

**The open question this leaves:** which models accept it? The
catalogue says `input: Text,Image` and `supported: ['Image Editing']`
for `Qwen/Qwen-Image-2.1`, the community quant, and the four FLUX
adapters — but `black-forest-labs/FLUX.2-klein-4B` says `input: Text`
only. The Agency's `device.generate()` sends no image field at all
today, so **every drag-and-drop edit has been text-only**. Phase N
fixes that, and Phase N.0 measures which models actually honour it.

### M11 — there is no new model to notice today, and the catalogue has no "since" field

The catalogue holds **92 rows**: 50 `not_downloaded`, 37 `downloaded`,
5 `running`. **All 15 Text-to-Image rows are already downloaded** — the
user installed them all. The 50 not-downloaded rows are TTS, ASR,
embedding and classification models.

`need_update` is `False` on all 92 rows, so it cannot signal a new
model. The usable signals are `created_time` (73 distinct values, oldest
2025-12-31, newest 2026-11-04) and `udpate_time`.

**So the app must keep its own watermark** — the set of catalogue ids
seen at the last check — and diff against it. There is no vendor
"what's new" endpoint to ask.

`tools/build_registry.py` already has the vocabulary for this: a model
in the store with no overlay entry is `uncharacterised`, and is
deliberately kept OUT of the registry so nobody routes to a model
nobody has measured.

### M12 — the lineage already holds everything a reference needs

A reference at the recipe level needs: the requirements, the model that
was chosen, the dialect, the resolved size, the prompt, the modifiers,
and the critique. **All of it is already in the lineage** the service
writes, and the dialect translator already knows how to write a prompt
in a given model's dialect.

So the recipe-level reference is a data-structure change, not an
appliance change. And the overlay already carries `max_refs: 10` and
`edit_ops: [instruction_edit, local_edit, identity_preservation]` on
exactly the two models the catalogue says take `Text,Image` — the
curated layer was already written for this and the code never used it.

---

## Phase K — the tab strip

The prerequisite for features 1 and 3.

### Task K1: the tab strip in the markup

**Files:** modify `app/web/index.html`

Three tabs: **Make**, **Models**, **References**. The existing
conversation, canvas, roles, alternatives, dialog and lineage move into
the Make panel untouched. The card block moves out of the canvas column
into the Models panel. The References panel starts empty.

```html
<div class="tabs" role="tablist">
    <button class="tab active" data-tab="make" role="tab"
            aria-selected="true">Make</button>
    <button class="tab" data-tab="models" role="tab"
            aria-selected="false">Models</button>
    <button class="tab" data-tab="references" role="tab"
            aria-selected="false">References</button>
</div>
```

Each panel is a `<section class="panel" id="panel-make">` and only the
active one is visible.

**Verify:** `grep -c 'class="tab' app/web/index.html` returns 3.

### Task K2: the tab behaviour

**Files:** modify `app/web/app.js`, `app/web/style.css`

```javascript
function showTab(name) {
    for (const tab of document.querySelectorAll('.tab')) {
        const active = tab.dataset.tab === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
    }
    for (const panel of document.querySelectorAll('.panel')) {
        panel.classList.toggle('hidden', panel.id !== 'panel-' + name);
    }
}
```

Wire it to clicks on `.tab`. The Models tab loads its cards the first
time it is opened — not at page load, because that is a request the
user did not ask for.

**Files:** create `app/tests/test_web.py` additions

```python
def test_the_surface_has_three_tabs(index_html: str):
    for name in ("make", "models", "references"):
        assert f'data-tab="{name}"' in index_html, (
            f"there is no {name} tab")


def test_the_surface_switches_tabs(app_js: str):
    assert "showTab" in app_js, "the tabs do not switch"
    assert "aria-selected" in app_js, "the tabs do not report their state"
```

### Task K3: commit

```bash
cd ~/.hermes/tia
git add app/web/index.html app/web/app.js app/web/style.css app/tests/test_web.py
git commit -m "The surface gets a tab strip: Make, Models, References"
```

---

## Phase L — Feature 1: the model card browser

### Task L1: one request for every card

**Files:** modify `app/src/tis/api.py`, `app/src/tis/service.py`

`GET /v1/models/card?model_id=…` is one card per request. A browser
tab showing 17 cards would make 17 round trips.

```python
@app.get("/v1/models/cards")
async def model_cards():
    """Every card in the catalogue, in one request.

    The single-card route exists for a link to one model; a browser
    listing wants all of them, and seventeen round trips to draw a
    grid is a grid that arrives in pieces.
    """
    cards = agency.all_model_cards()
    return {"cards": cards}
```

**Files:** modify `app/src/tis/service.py`

```python
def all_model_cards(self) -> list[dict]:
    """Every model's card, in catalogue order."""
    cards = []
    for spec in self.registry.models:
        if spec.kind != "image_generator":
            continue
        cards.append(self.model_card(spec.id))
    return cards
```

**Files:** modify `app/tests/test_api.py`

```python
def test_the_card_browser_gets_every_card_in_one_request(client):
    response = client.get("/v1/models/cards")
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) >= 15
    assert all("advertised" in card for card in cards)
```

### Task L2: the card grid

**Files:** modify `app/web/index.html`, `app/web/app.js`, `app/web/style.css`

The Models panel: a filter row, then a grid of cards. Each card shows
the id, role, NPU%, speed, alpha, artifacts, a "measured" badge, and
the one-line summary. Clicking a card opens the full card — *advertised*
/ *measured* / *what we have noticed* — in a detail pane beside the
grid.

**The three parts stay visually distinct.** The distance between what
the device advertises and what we measured is the interesting part of a
card, and flattening them into one paragraph destroys the reason the
card exists.

### Task L3: the filters

**Files:** modify `app/web/app.js`

Filter by artifact, by "measured / not measured", by "can see" (for the
conversation models), and a text search over id and summary. Filters
run against the already-fetched card list — no request per keystroke.

### Task L4: commit

```bash
git add app/src/tis/api.py app/src/tis/service.py app/web/ app/tests/
git commit -m "A tab where the model cards can actually be browsed"
```

---

## Phase M — Feature 2: notice a new model, ask, download, benchmark

### Task M1: the catalogue diff

**Files:** create `app/src/tis/catalogue.py`

The vendor has no "what's new" endpoint, so the app keeps its own
watermark.

```python
@dataclass(frozen=True)
class NewModel:
    """A text-to-image model the appliance offers that we have not seen."""
    model_id: str
    name: str
    npu_usage: int
    size_bytes: int
    created_time: int
    description: str


def find_new_image_models(catalogue: list[dict],
                          seen: Collection[str]) -> list[NewModel]:
    """The image models in the catalogue that are not in ``seen``.

    Only Text-to-Image rows: the appliance also lists 50 text-to-speech
    and embedding models, and a notice about those is noise.
    """
```

**Files:** create `app/tests/test_catalogue.py`

```python
def test_a_new_image_model_is_noticed():
    catalogue = [{"fullname": "acme/New", "type": "Text-to-Image",
                  "npu_usage": 30, "status": "not_downloaded"}]
    assert [m.model_id for m in find_new_image_models(catalogue, set())] \
        == ["acme/New"]


def test_a_text_to_speech_model_is_not_a_notice():
    catalogue = [{"fullname": "acme/TTS", "type": "Text-to-Speech"}]
    assert find_new_image_models(catalogue, set()) == []


def test_a_model_we_have_seen_is_not_new_again():
    catalogue = [{"fullname": "acme/New", "type": "Text-to-Image"}]
    assert find_new_image_models(catalogue, {"acme/New"}) == []
```

### Task M2: the watermark

**Files:** modify `app/src/tis/config.py`, `app/src/tis/service.py`

The seen-ids live in a small JSON file next to the registry, so they
survive a restart and the app does not re-announce everything on every
boot.

```python
def _seen_path(self) -> Path:
    return self.settings.registry_path.parent / "seen-models.json"


def seen_models(self) -> set[str]:
    """The catalogue ids we have already looked at."""
    path = self._seen_path()
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(payload.get("seen") or [])


def remember_models(self, model_ids: Iterable[str]) -> None:
    """Remember these ids, so they are not offered again."""
```

### Task M3: the watcher

**Files:** modify `app/src/tis/service.py`

A background thread polls the catalogue every `CATALOGUE_POLL_SECONDS`
(900 — fifteen minutes) and publishes an event when something new
appears.

```python
def _watch_catalogue(self) -> None:
    """Notice new models, and ask.

    The poll is every fifteen minutes because the catalogue is a
    270 KB document that changes when the VENDOR changes it, not when
    the user does anything. Polling faster would be work for nothing.

    The notice is an event, not a download: ten GiB must never move
    because a row appeared in a catalogue.
    """
```

The event:

```python
self.events.publish("catalogue.new_model", session_id, {
    "model": new.model_id,
    "name": new.name,
    "npu_usage": new.npu_usage,
    "size_bytes": new.size_bytes,
})
```

### Task M4: the notice in the surface

**Files:** modify `app/web/index.html`, `app/web/app.js`, `app/web/style.css`

A **banner**, not a modal. The user may be mid-generation, and a modal
that interrupts a 200-second job to ask about a download is a modal that
costs more than the download.

The banner says what the model is, how big it is, what it would cost
in NPU, and offers two buttons: **Download & benchmark** and **Not
now**. "Not now" dismisses it — and the model stays in the seen-set, so
it is not asked about again until it changes.

### Task M5: the download-and-benchmark job

**Files:** modify `app/src/tis/service.py`

```python
def benchmark_model(self, model_id: str,
                    session_id: str = "default") -> str:
    """Download a model, measure it, and give it a card.

    This is a long job: a download is minutes and the eleven probes
    are three to thirty-five minutes more. It goes through the same
    global worker as a generation, so it cannot run at the same time
    as one, and it takes the appliance hold for the same reason.
    """
```

The sequence, reusing what exists:

1. `self._download(work, spec)` — the existing path, with the storage
   check, the progress events and the timeout.
2. `ModelResearcher.characterise(model_id)` — the existing eleven
   probes, the vision judge, the card and the overlay entry.
3. **Write a provisional overlay entry.** This is the one new thing.
   `tools/build_registry.py` deliberately keeps a model with no overlay
   entry out of the registry, because routing to a model nobody has
   characterised means routing on a guess. A benchmarked model has been
   characterised — but its overlay entry is machine-written, so it is
   flagged `provisional: true` and the card says so.
4. **Rebuild the registry and reload it in the running server.** This is
   where the "server holds the registry it started with" bug bites: the
   registry is loaded once at startup, so without a reload the new model
   is measured but not routable, and the surface keeps offering the old
   answer.
5. Publish `model.benchmarked`.

### Task M6: commit

```bash
git add app/src/tis/catalogue.py app/src/tis/config.py app/src/tis/service.py \
        app/web/ app/tests/
git commit -m "Notice a new model, ask before downloading it, then benchmark it"
```

---

## Phase N — Feature 3: a saved reference

**This is the phase that changes the most, because M10 changed it.**

### Task N0: measure which models honour an image

**Files:** create `app/tests/test_image_input.py`, create
`tools/probe_image_input.py`

M10 proved the endpoint accepts `image` and `images`. It did NOT prove
which models use them. The catalogue says `input: Text,Image` for
`Qwen/Qwen-Image-2.1`, the community quant and the four FLUX adapters,
and `input: Text` for the FLUX base — but the catalogue is a claim.

The probe reuses the half-red/half-blue input and the
"reproduce this image as a pencil sketch" prompt, with the no-image
control for each model, and measures the half-difference. The test is
whether the output carries the input's vertical division.

**The result goes into the overlay as a measured fact** — `image_input:
yes` or `no` — and the resolver uses it: a model that cannot take an
image is never chosen for an edit.

**This is a gate.** Phase N.1 onward depends on it.

### Task N1: the device sends the image

**Files:** modify `app/src/tis/device.py`

```python
def generate(self, model: str, prompt: str, size: str,
             image: bytes | None = None) -> bytes:
    """Generate an image, optionally conditioned on a source image.

    The source goes in as `image` — a bare base64 string, which is
    what the appliance accepts. The data-URL form also works, and the
    bare form was measured to preserve the input's structure more
    faithfully, so it is the one used.

    MEASURED 2026-11-07: a half-red/half-blue rectangle sent as
    `image` came back as a pencil sketch of that rectangle, with the
    vertical split intact. The same prompt with no image drew a
    completely different subject.
    """
    body: dict[str, Any] = {"model": model, "prompt": prompt,
                             "size": size, "n": 1}
    if image:
        body["image"] = base64.b64encode(image).decode("ascii")
```

**Files:** modify `app/src/tis/device.py` — the `Device` protocol
signature to match, and `app/tests/test_device.py`:

```python
def test_the_source_image_travels_with_the_request(fake_device):
    ...
    assert body["image"] == base64.b64encode(png).decode("ascii")


def test_no_image_means_no_image_field(fake_device):
    ...
    assert "image" not in body
```

### Task N2: the orchestrator passes the source through

**Files:** modify `app/src/tis/orchestrator.py`

`Orchestrator.generate()` gains a `source: bytes | None` parameter and
hands it to `device.generate()`. The critic still sees the OUTPUT.

### Task N3: the reference store

**Files:** create `app/src/tis/references.py`

A reference is an asset plus a recipe. It is stored byte-for-byte like
an asset, because a round trip through an image library is exactly
where a transparent background quietly becomes an opaque one.

```python
@dataclass(frozen=True)
class Reference:
    """A saved result, kept so the next one can match it."""
    id: str
    png: bytes
    name: str
    requirements: dict
    model_id: str
    dialect: str
    size: str
    prompt: str
    modifiers: tuple[str, ...]
    critique: dict | None
    created_at: float
```

`ReferenceStore` mirrors `AssetStore`: a directory of PNGs and JSON
sidecars, `ref_` prefixed ids, byte-preserving writes.

**Files:** create `app/tests/test_references.py`

```python
def test_a_reference_keeps_the_bytes_it_was_given(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"the original bytes"
    store = ReferenceStore(tmp_path)
    reference = store.save(png, recipe={...})
    assert store.get(reference.id).png == png
```

### Task N4: the API

**Files:** modify `app/src/tis/api.py`

| route | what it does |
|---|---|
| `POST /v1/references` | save an asset as a named reference |
| `GET /v1/references` | list them, newest first |
| `GET /v1/references/{id}` | one reference, with its recipe |
| `DELETE /v1/references/{id}` | forget it |
| `POST /v1/generate` | accepts `reference_id` |

`POST /v1/generate` with a `reference_id` means: *use this reference's
model, requirements, dialect and size, and make the requested subject
in that style.*

**The reference's model is a strong preference, not an absolute.** If
the reference's model cannot do the new job — a transparent background
was required and the reference's model cannot do that — the resolver
says so and offers an alternative. Same rule as the user's explicit
model choice: honoured when capability-compatible, explained when not.

### Task N5: the surface

**Files:** modify `app/web/index.html`, `app/web/app.js`, `app/web/style.css`

- A **Save as reference** button on a successful image, with a name
  field.
- The **References** tab: thumbnails, names, the model and requirements
  each was made with, and a **Use this** button that puts the
  reference into the composer.
- The composer shows which reference is active, and lets it be cleared.

### Task N6: the CLI and the skill

**Files:** modify `app/src/tis/cli.py`, the three copies of
`skills/tiiny-image-agency/SKILL.md`

```
tis reference save ast_0123456789abcdef --name "newsletter header"
tis reference list
tis reference use ref_0123456789abcdef
```

The skill's guidance changes: a reference pins the model and the
dialect, so a repeated job is a repeated job.

### Task N7: commit

```bash
git add app/src/tis/ app/web/ app/tests/ tools/ skills/
git commit -m "A saved reference: the model, the dialect and the style, kept"
```

---

## What this plan does not claim

- **That every model accepts an image.** M10 measured the endpoint, not
  the catalogue. Task N0 measures the models.
- **That a pixel reference reproduces a style exactly.** It conditions
  the model; it does not pin it. A reference is a strong input, not a
  lock.
- **That the appliance has a "new models" signal.** It does not. M11
  measured that `need_update` is always false, and the app keeps its
  own watermark instead.
- **That the benchmark is quick.** Eleven probes at 16–188 seconds each
  is three to thirty-five minutes, on an appliance that does one thing
  at a time.
