# The Implementation

The concrete build. [PATTERN.md](PATTERN.md) is the design; this is what it
looks like in code and what it measures.

## The layout

```
tiiny-image-agency/
  app/
    pyproject.toml
    src/tis/
      api.py          the HTTP API — nine routes
      cli.py          the `tis` command, an HTTP client of the API
      service.py      the Agency: one worker, one queue, the wiring
      orchestrator.py resolve -> translate -> swap -> generate -> critique
      planner.py      words -> requirement vector, with a fallback
      resolver.py     the deterministic chooser
      registry.py     the typed model catalogue
      dialect.py      per-model prompt translation
      device.py       the adapter to the appliance
      residency.py    the transaction: locks, hold, swap, restore
      critic.py       the judge
      jobs.py         the SQLite job store
      assets.py       the byte-preserving asset store
      events.py       the event bus, with replay
      imaging.py      reading a PNG's structure
      research.py     the research cards
    tests/            465 tests
    web/              the browser surface: index.html, app.js, style.css
  registry/image-models.json   the curated catalogue
  tools/                        the registry builder, the research loop
  scripts/                      the same tools, standalone
```

Python 3.11, FastAPI, uvicorn, Pydantic, SQLite, SSE, and a frontend with no
build step at all.

## Running it

```bash
cd app
python -m pip install -e .
tis serve --port 8080
```

Then, in another terminal:

```bash
tis health
tis plan "an app icon of a fox head, flat, transparent background"
tis generate "an app icon of a fox head, flat, transparent background"
tis alpha the-icon.png
```

The appliance's bearer is read from the environment by the device adapter and
nowhere else. The CLI holds no credential — it is an HTTP client of the API,
and the API owns the appliance.

The browser surface is on the same port: <http://127.0.0.1:8080>.

### Running it on Linux or Windows

This was built on macOS. The application is portable — pure Python, four
dependencies, no compiled extensions — but three things are not, and a
porter will hit all three immediately. The [README](README.md#running-it-on-linux-and-windows--a-contribution-wanted)
has the full account; this is the working list.

| # | what | where | the fix |
|---|---|---|---|
| 1 | the `tiiny` CLI is a macOS binary, and it is the only way to load or unload a model — the management API has no load route | `app/src/tis/device.py`, `app/src/tis/config.py` | a Linux or Windows build of the vendor's CLI. It takes `--device-address`, so it works against the appliance's IP from any machine |
| 2 | the CLI needs a pty, so every load, unload and download is wrapped in `script -q /dev/null` | `app/src/tis/device.py` | macOS ships BSD `script`, Linux ships util-linux `script` with different flags. A platform check, or a Python pty |
| 3 | the watchdog lock uses `fcntl.flock` | `app/src/tis/residency.py` | POSIX. Linux is fine; Windows needs `msvcrt.locking` or a `filelock` dependency |

And one configuration change that is easy to miss: **the default base URL
resolves to `127.0.0.1` on the machine where this was developed**, because
a local macOS proxy answers on that hostname. On any other machine it will
not resolve, and the appliance has to be addressed by its LAN IP. The base
URL needs to come from the environment — `Settings(base_url=...)` today,
and an environment variable in `load_settings()` after that.

Two invariants a port must not break:

- **Bytes are never re-encoded.** Images are stored and served exactly as
  the appliance returned them.
- **The judge must be able to see.** The API refuses a text-only critic,
  and the default critic is a vision model.

## The API

| route | what it does |
|---|---|
| `POST /v1/plan` | the request -> model, justification, swap plan, download plan |
| `POST /v1/generate` | the request -> a job id. **202**, not 200 |
| `POST /v1/iterate` | an asset id and feedback -> a job id. **202** |
| `POST /v1/assets` | **upload** a PNG you already have — the bytes are the body — -> an asset id. The door for "update this image" |
| `GET /v1/assets/<id>` | the PNG, byte for byte |
| `GET /v1/assets/<id>/lineage` | the provenance as JSON, including the file's path |
| `GET /v1/session/<id>/events` | the SSE stream. `?job_id=` is optional but recommended |
| `GET /v1/npu` | the resident set and the NPU used |
| `GET /v1/health` | is the app alive, is the appliance reachable |
| `GET /v1/models` | the catalogue |
| `GET /v1/models/card?model_id=<id>` | the card for one model: advertised, measured, noticed |
| `GET /v1/roles` | the **guide**: every conversational model, whether it can see an image, its NPU cost, whether it is on the device, and whether the current pair fits the pool |
| `POST /v1/roles` | the **choice**: `{"critic": "..."}` and/or `{"conversation": "..."}`. A critic that cannot see an image is refused |

`POST /v1/generate` and `POST /v1/iterate` both take an optional
`output_path`: the finished PNG is *also* written there, byte for byte, for
an agent that wants the file at a path of its own. The agency's own copy is
written either way.

**Why 202.** A generation takes 54 to 200 seconds. A client that read 200
would reasonably believe the image was ready. The work is *queued*, so it
says 202 and hands back a job id.

**Why the card route takes a query parameter.** Every model id contains a
slash — `Tongyi-MAI/Z-Image-Turbo` — and a path segment cannot carry one.

**Why the lineage exists.** It is the record of what happened: the
requirements, the model, the prompt that was actually sent, the attempts, the
critique, and the modifiers an iteration accumulated. It is what you read when
a request comes back asking for a change.

## The conversational catalogue

`registry/roles.json` holds the models that **talk** — the conversation
agent that turns a request into a requirement vector, and the critic that
judges the result. It is a separate file from the image registry on
purpose: the image registry holds the generators, and no text model is in
it, so a single registry could not describe either role.

Twenty-six models, sixteen of which can accept an image. `vision` is
derived from the device's own record — `type == "Image-Text-to-Text"`, or
an `input` that accepts an image — so it moves when the store moves.
Prompt enhancers are excluded: an enhancer cannot hold a conversational
role.

**The critic must be one of the sixteen.** A text-only judge is refused by
`POST /v1/roles`, with the reason attached: a judge that reads text only
judges the *prompt*, and it invents a defect rather than admit the limit.
The default critic is `Qwen/Qwen3.6-35B-A3B` at 47%, which sees. The
conversation agent is unaffected — it writes the plan and never looks at a
pixel, so a 27% text model is right for it, and it costs no swap because
the watchdog already holds it.

**The guide says whether the choice works.** `GET /v1/roles` returns each
model's vision flag, NPU cost, context, and whether it is on the device,
plus a `fit` block for the current pair: the judge and a generator
against the **81% execution ceiling**, not the 100% admission limit.

The conversation agent is deliberately *not* in that sum. It writes the
scene description before the generation starts, so by the time the image
is judged its weights have been swapped out. A 47% seeing judge and the
23% default generator is 70%, which runs; summing all three roles gives
125% and wrongly suggests a seeing judge is unaffordable.

**Three things the implementation had to get right**, and each of them was
wrong at first:

- The residency manager prices a model from the image registry, then from
  a table of the appliance's own models, and otherwise said *zero*. A judge
  chosen at runtime was therefore free, the eviction plan left the pool
  above the ceiling, and the generation would have failed. The
  conversational catalogue is now its third source of prices.
- The orchestrator is handed the critic when it is built. Replacing the
  agency's copy without handing the orchestrator the new one changes the
  guide and not the judging.
- The vision payload has to ask for **no thinking**. The appliance's
  generalist is a reasoning model, and with a long prompt it spent the
  whole token budget thinking and returned an empty reply — which is
  indistinguishable from a model that cannot see.

## The registry

`registry/image-models.json` is a curated catalogue of sixteen models — fourteen
image generators and two prompt enhancers — each with its artifacts, styles,
NPU cost, alpha capability, text-rendering quality, verified sizes, and a
dialect note.

**The overlay is the source of truth; the JSON is generated.** `tools/build_registry.py`
reads `app/data/overlay.yaml` and merges it with a live snapshot of the
appliance's catalogue. The generated file is committed, and the builder is
tested to reproduce it byte for byte — so a change to the overlay shows up as
a reviewable diff in the JSON rather than as a mystery at runtime.

**A model that is listed is not a model that is downloaded.** The store
catalogue contains both, and the registry carries a `downloaded` flag that is
refreshed live before each job. The resolver will not choose a model that is
not on disk.

**Models without a curated overlay are excluded.** The store listed a model
that no overlay covered. It was left out of routing rather than routed on a
guess, and it is still visible in the catalogue for a reader to inspect.

## The research loop

`tools/research_model.py` measures a model instead of asking the vendor what
it does.

It runs a set of probes against the appliance — one per artifact, one per
style, one for alpha, one for text — and writes two files: a **card** (what
the model was measured to do) and an **overlay** (the same facts, in the
shape the registry builder consumes).

Eleven probes on one model took about fifteen minutes of generation, and the
result contradicted the appliance's own description of that model: the device
said it produced text correctly, and the probes found it mangled text every
time. The card says what the probes found.

The alpha probe is the most useful one, because it answers the question the
catalogue cannot:

```
alpha        54.9s   the percentage of fully transparent pixels, measured
```

That number is a measurement of one image, not a property of the model — and
the same model's alpha came out at 0%, then 40.76%, then 0% again across
different prompts. Which is exactly why the card records it per-probe and
why the CLI has a command to measure any PNG's alpha on demand.

## The screen

Three files, no build step, no framework, no npm. They are mounted on the API
so one port serves both, and they also work from a plain static server — the
`?api=` parameter overrides the base URL.

The layout is three panes. The **conversation** on the left, the **canvas** on
the right over a checkerboard, and three things that are always visible: the
**model badge** (which model, and why — plus the research card's measured
capabilities), the **NPU meter** (used percentage and the resident set), and
the **swap banner** (what is loading, and for how long).

**Never a silent stall.** A swap is about 20 seconds to load and 200 to
generate; a download is about five minutes and ten gigabytes. The banner
always shows a running elapsed time, and a download gets its own variant of
it.

**The PNG is never round-tripped.** It is fetched as bytes and put in an
`<img>` over a CSS checkerboard. No canvas, no decode, no re-encode — the
alpha is the product.

## The tests

368 of them, in about twelve seconds, and none of them touch the appliance.

```bash
cd app && python -m pytest -q
```

They are worth reading as a description of the invariants:

- **`test_resolver.py` and `resolver_acceptance.py`** — thirty-six selection
  cases and four occupancy cases, each asserting which model wins and why.
  The resolver is deterministic, so its output is a table.
- **`test_residency.py`** — that the swap waits for the lock, that it fails
  loudly when the lock never clears, and that the eviction plan is the
  minimum one that fits.
- **`test_events.py`** — that a late subscriber gets the replay, and that
  unsubscribing one queue does not silence another.
- **`test_cli.py`** — that the CLI sends the fields the API expects
  (`request`, not `prompt`; `feedback`, not `prompt`) and writes the PNG
  byte for byte.
- **`test_web.py`** — that the surface filters events by job id, reads the
  SSE stream as a stream, handles exactly the fourteen event names the
  agency publishes, and does not hide the image with its own CSS rule.

That last one exists because of a real bug: the image's own rule set
`display:none`, so the image was laid out at zero size and never appeared,
while the DOM reported it as loaded and visible. Only a screenshot caught it.

## What it measures

| what | the number |
|---|---|
| the NPU pool | 47.9 GiB |
| the default resident set | 5 models, 86% |
| the hot path | planner (55%) + fast image (23%) = 78%, ~55 s |
| the last working composition | 81% |
| the first failing composition | 85%, HTTP 500 `150004` |
| the flagship alone | 62%, ~200 s, planner evicted |
| a generation, end to end | 4 min 10 s (79 s swap + 3 × 54 s generation) |
| storage free | 278.2 GiB of 915.9 GiB |
| a model download | 10.6 GiB in about five minutes, ~43 MiB/s |
| prefill latency | 836 tokens 1.2 s; 67,672 tokens 123.5 s; 108,284 → HTTP 400 |

The prefill curve is its own small lesson: the context size does not consume
NPU budget at all, it only affects how long the appliance takes to think
before it starts. And past a certain size it does not slow down, it fails.

## Two open edges

**The vendor's download command panics after successfully starting a
download.** The goroutine dies at `internal/cli/model.go:499` with a blocked
channel send — after the download has begun and will complete. The agency
therefore asks the catalogue for the truth: the download is successful when
the catalogue says `downloaded`, not when the command exits.

**The critic cannot see the image.** It judges the *prompt* against the
requirement vector, because the device's chat interface takes text. It is
explicitly told it cannot see the pixels, and told that a defect it invents
costs a generation and changes nothing. That instruction came directly from a
real failure: the first live run burned three generations chasing a complaint
about a transparent background that the delivered image did not have.
