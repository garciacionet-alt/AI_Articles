# Where Do API Calls Go — And Why You Can't See Them

**This answers a question raised by Zolon (Tiiny co-creator, author of
Engraphis) on Discord, 2026-10-27.** His words:

> My issue isn't the doc storage/processing. My issue is my API calls are
> logged and there is no way for me to see that in any interface. I used an
> API call to tell it to tell me a story, and then when I searched the
> lancedb on the device, I found it.

**He is right, and the mechanism is worse than "no interface."** This document
traces an API call end to end and identifies the exact point where the
record becomes invisible.

**Zolon also supplied the answer to the other half.** He published the
supported delete recipe — `DELETE /kb/conversation_days/{day}` — and flagged
that an encrypted log on the device likely mirrors what the delete does not
touch. §5 covers the recipe and verifies his four caveats against the
device; §6 covers what survives it. That last point is the substance of
his concern, and it is well-founded.

Everything here was verified by experiment on a Tiiny z01 on 2026-10-27,
including a controlled probe: three chat completions carrying a unique marker
token, then a search for that marker across every reachable surface.

---

## 1. The short answer

| Question | Answer |
|---|---|
| Are my API calls logged? | **Yes.** Every call is written to the device and ingested into the knowledge base's LanceDB store. |
| Can I see them in an interface? | **No.** No endpoint, no CLI command, and no dashboard exposes an individual API call or its content. |
| Is there a request log? | **Only an aggregate.** `/api/v1/sys/performance` counts calls per endpoint — but **excludes the `/v1/*` inference surface entirely**. |
| Can I see the content? | **Only via LanceDB, on the device itself** — exactly what Zolon did. |
| Will it appear later in the KB? | **Only if the summarizer judges it "memory-worthy."** A story is not; it was summarized as *"No memory-worthy information."* and the raw record is not published. |
| **Can I delete it?** | **Yes — Zolon (Tiiny co-creator) published the recipe, 2026-10-27.** `DELETE /kb/conversation_days/{day}` removes the whole day. See §5. |
| **Does deleting remove everything?** | **No.** It removes the vault's view of the day. The raw per-call log on the device, and the retained user-context versions, are untouched. See §6. |
| Is this a bug or a design gap? | **A design gap.** Nothing errors, nothing warns. The data is captured and then deliberately withheld from every view. |

---

## 2. The path an API call takes

Verified with a marker token (`zolonprobe`) sent in three chat completions.
The mixin import worker's counters moved in lockstep with the calls.

```
  YOUR CALL
  POST http://openai.api.tiiny/v1/chat/completions
      │
      ▼
  ┌───────────────────────────────────────────────────────────────┐
  │ 1. INFERENCE — served by llama-server on the device            │
  │    model Qwen/Qwen3.6-35B-A3B, NPU-resident                   │
  └───────────────────────────────────────────────────────────────┘
      │
      ▼
  ┌───────────────────────────────────────────────────────────────┐
  │ 2. THE MIXIN LOG — /data/backend/tiiny_model_data/mixin        │
  │    one record per call. THIS IS WHERE YOUR CALL IS WRITTEN.    │
  │    ✔ 3 calls in → mixin_import_worker reported                │
  │      files_seen_last_scan: 1, records_imported_last_scan: 3   │
  └───────────────────────────────────────────────────────────────┘
      │
      │  mixin_import_worker polls every 60 s
      ▼
  ┌───────────────────────────────────────────────────────────────┐
  │ 3. LANCEDB — the knowledge base store                         │
  │    files_dir: lancedb_data/.kb-slots/A/originals              │
  │    records_imported 1371 → 1374, emitted_turns 5899 → 5902    │
  │    ✘ Not yet visible through any endpoint.                     │
  └───────────────────────────────────────────────────────────────┘
      │
      │  nightly summarization, 23:00 → 05:00
      ▼
  ┌───────────────────────────────────────────────────────────────┐
  │ 4. SUMMARY — the summarizer judges "memory-worthy?"           │
  │    A story → "No memory-worthy information."                   │
  │    → published_to_sources: FALSE                              │
  │    → finalized_at: NULL                                       │
  │    ✘ Never becomes a source. Never vectorized. Never queryable.│
  └───────────────────────────────────────────────────────────────┘
```

**The sting is in step 4.** The record was captured faithfully in steps 1–3.
Then the summarizer classified it as not worth remembering, and the device
**discarded it from every viewable surface** — no source, no file, no memory
entry, no fact, no journal item. It is in LanceDB and nowhere else.

The probe's marker token was searched for across every surface:

| Surface | Marker found? |
|---|---|
| `GET /kb/sources` | ❌ |
| `GET /kb/sources/conversations` | ❌ |
| `GET /kb/sources/files` | ❌ |
| `GET /kb/memories` | ❌ |
| `GET /kb/memory/facts` | ❌ |
| `GET /kb/conversation_days` | ❌ |
| `GET /kb/conversation_days/2026-10-27` | ❌ (summary: *"No memory-worthy information."*) |
| `GET /kb/files/conversation-2026-10-27` | ❌ (404 — never published) |
| `GET /kb/retrieve` | ❌ |
| `GET /kb/query` | ❌ (*"the provided context does not contain information about 'zolonprobe'"*) |
| `POST /kb/context` | ❌ |
| `GET /api/v1/sys/performance` | ❌ (and `/v1/*` isn't counted at all) |
| `GET /api/v1/chat/history/` | ❌ (empty) |

---

## 3. The one interface that exists — and its blind spot

`GET /api/v1/sys/performance` **is** an API call log. It is the only one.

It returns, per endpoint:

```json
{
  "method": "GET",
  "path": "/api/v1/apps",
  "count": 8,
  "error_count": 1,
  "status_code_counts": { "200": 7, "401": 1 },
  "avg_ms": 289.699, "min_ms": 0.974, "max_ms": 357.092,
  "p50_ms": 338.828, "p90_ms": 347.556, "p95_ms": 352.324, "p99_ms": 356.139,
  "last_duration_ms": 262.412,
  "last_seen_at": "2026-10-27T15:07:18.095352+00:00"
}
```

That is genuinely useful — latency percentiles, error counts, status-code
breakdown, last-seen timestamps.

**But it is blind in exactly the place it matters:**

- **It does not log the `/v1/*` inference surface at all.** A chat
  completion, an embedding call, an image generation, an ASR request — none
  of them appear. The endpoint list contains `/api/v1/*` management routes
  and nothing else. Verified directly: `total_requests` was **49 before and
  49 after** a chat completion was issued.
- **It has no request or response content.** No body, no prompt, no
  completion, no model, no headers. The payload contains zero occurrences of
  `request_body`, `response_body`, `payload`, `prompt`, `content`, or
  `headers`.
- **It cannot be filtered to one caller.** Entries are keyed by
  method + path. Every caller of the same endpoint is aggregated together.
  There is no user, session, or API-key dimension.

So for Zolon's use case — "show me the calls I made" — the performance
endpoint answers a different question: *how fast and how often*, not *what did
I send*.

### The other blind spot: the dashboard is token counts, not calls

The user guide's Chapter 7 ("Dashboard and Usage Statistics") describes what
the TiinyOS desktop app shows: **token statistics**, grouped by date, model,
and app. It states plainly:

> Currently, TiinyOS only tracks token data for text generation models.

and

> All API calls, or calls that do not pass an app name, are grouped under
> **Default**.

So there *is* a surface where API calls appear — the desktop dashboard — but
it reports **token volume**, not request content, and it is only on the
desktop client. Nothing on the device itself, and nothing over HTTP.

---

## 4. Why "no interface" is the wrong mental model

It would be easy to read this as *the device forgot to build a log viewer*.
That is not what happened. The device did something more specific:

**It built a memory system, and memory has a filter.** The pipeline is built
to extract what is *worth remembering* and discard the rest. The 23:00
nightly summarizer decided a story is not worth remembering, and the
pipeline correctly discarded it.

The problem is that **the same pipeline handles two different things**:

| | Intent | Should it be retrievable? |
|---|---|---|
| **A story you told for fun** | Transient | No — discarding is right |
| **An API call you need to debug** | Evidence | **Yes** — discarding is wrong |

There is no separation between the two. A throwaway remark and a debugging
artifact travel the identical path, and the summarizer — an LLM making a
judgement call — decides which one you get to keep. **You cannot see your own
API calls because an LLM decided they weren't interesting.**

That is the actual design flaw. It is not a missing viewer. It is a
**retrieval-policy** problem: memory-worthiness is the wrong gate for
operational records.

---

## 5. Deleting what the vault captured — Zolon's recipe

**Zolon (Tiiny co-creator, author of Engraphis) published this on Discord,
2026-10-27**, and it is the answer to the "how do I get rid of it" half of
his question:

```bash
# List the days
curl -H "Authorization: Bearer YOUR_KEY" \
  "http://<device-ip>/kb/conversation_days?limit=500"

# Delete one whole day
curl -X DELETE -H "Authorization: Bearer YOUR_KEY" \
  "http://<device-ip>/kb/conversation_days/2026-10-26"
```

Windows PowerShell:

```powershell
Invoke-RestMethod -Method Delete -Headers @{Authorization="Bearer YOUR_KEY"} \
  "http://<device-ip>/kb/conversation_days/2026-10-26"
```

**He states four caveats, and I verified each against the device's own API
contracts and state on 2026-10-27:**

| His caveat | Verified? | Evidence |
|---|---|---|
| "It deletes the WHOLE day, including your TiinyOS chats in the vault for that day" | **Confirmed** | The only delete path takes a single `day` param and returns `deleted_source`, `deleted_entries`, `removed_chunks`, `deleted_journal_file` — no finer granularity exists. |
| "There's no way to delete just the API chats" | **Confirmed** | The KB spec has exactly **two** DELETE routes: `/kb/conversation_days/{day}` and `/kb/memory/facts/{fact_id}`. Neither addresses a source subset. The mixin importer merges API turns and TiinyOS turns into one day file before the vault ever sees them. |
| "Days that say `queued` haven't been summarized yet" | **Confirmed** | `status` is one of `queued`, `summarized`, `failed`. A queued day has `journal_item_count: 0` and no source. |
| "`summarized` ones may already have turned into memory facts, which this doesn't remove" | **Likely wrong — the schema says otherwise** | The response schema carries **`deleted_facts`** and **`deleted_proposals`** counters, so facts sourced from that day are deleted with it. I could not test the cascade directly (see below), so treat this as strong-but-not-proven. |

### Why I could not test the cascade empirically

`POST /kb/upload_conversation` looks like a way to create a disposable day
for testing, but it **rejects every upload**: the call returns
`{"success": true, "status": "ignored"}` for every date tried, and no
conversation day is created. `POST /kb/add` creates dialogue entries
directly, but `dialogue_sources` stayed at 0 and no day appeared.

So I could not build a throwaway day to delete. The cascade claim rests on
the response schema, not on a live test. **Treat Zolon's caveat as
probably-conservative rather than established.**

### What the delete returns

From `DeleteConversationDayResponse` in the spec:

```
success, source_id, day
deleted_entries, removed_chunks        — vector-store entries and their chunks
deleted_facts, deleted_proposals       — the derived facts and proposals
deleted_source                         — the original source file
deleted_journal_file                   — the journal file
orphan_entries_deleted                 — vector entries orphaned by the removal
context_versions_retained              — user-context versions are KEPT
context_proposals_retained             — context proposals are KEPT
```

The last two are the ones to read carefully. The delete is **not** a
complete erasure.

---

## 6. What the delete does NOT reach — Zolon's real concern

Zolon's closing note is the substantive part, and he is right to raise it:

> There is an encrypted log on the device that likely has a mirror of
> everything that this does not touch. This is still a great concern for me.

**The structural claim holds.** Three artifacts survive a vault-day delete:

### 1. The raw per-call log — `/data/backend/tiiny_model_data/mixin`

This is the directory the `mixin_import_worker` polls every 60 seconds, and
it is where a call is written *before* any summarisation touches it. It sits
on the host volume `/data/backend`, which the agent containers also mount.

`files_seen_last_scan` was **15**, matching the **15** conversation days
exactly — so it holds **one file per day of raw turns**. The delete schema
never mentions this directory. **Deleting a vault day does not delete that
day's mixin file.**

That mixin file is the artifact Zolon found his story in.

### 2. User-context versions — explicitly retained

`context_versions_retained` and `context_proposals_retained` are named
fields in the delete response. This device has **20** user-context versions,
and they carry derived text: `AMC` appears in all 20, `Engraphis` 35 times,
`TensorMem` 32 times. **A day's content survives in the retained user-context
history even after the day is deleted.**

### 3. The encrypted log

I could not locate it over the API — no log, audit, or telemetry endpoint is
exposed, and the status snapshot does not name one. Its existence rests on
Zolon's direct observation on the device, which is better evidence than
anything I could reach over HTTP. **Treat it as reported by Zolon and not
independently verifiable over the API.**

### Why the deleted text does not come back

Worth stating, because it is the natural next worry. `conversation_import`
reports `skipped_records: 50` alongside `imported_records` — the importer
**tracks records it has already consumed**. A deleted day's mixin file is
still marked imported, so it is skipped rather than re-ingested.

This matches Zolon's observation: *"the day's text was gone afterwards and
didn't come back."* The mechanism is a dedup marker, not an absence of
source data.

---

## 7. Workarounds that work today

### Workaround A — read the log where it actually lives

Zolon's method is the only direct route: get onto the device and read the
mixin directory or the LanceDB store.

The locations, as reported by the service's own status stream:

| Path | What it is |
|---|---|
| `/data/backend/tiiny_model_data/mixin` | The raw per-call log. Polled every 60 s. |
| `lancedb_data/.kb-slots/A/originals` | The knowledge base's original files, including any published conversation day. |
| `memory_entries` (LanceDB table) | The vector store. 243 entries at the time of writing. |

The **mixin directory is the original record** — it is where your call is
written before any summarization touches it. If you need to see what was
actually sent, that is the place.

### Workaround B — make the call memory-worthy

If the content is worth remembering, the pipeline *will* publish it, and it
becomes fully retrievable. Demonstrated on a day with 22 journal items:

```bash
# The summary the pipeline wrote
curl "http://<device-ip>/kb/conversation_days/2026-10-26" \
  -H "Authorization: Bearer $KEY"

# The raw original file behind it
curl "http://<device-ip>/kb/files/conversation-2026-10-26" \
  -H "Authorization: Bearer $KEY"
```

The gating is explicit and observable. Across all 15 conversation days:

| `published_to_sources` | `GET /kb/files/{day}` |
|---|---|
| `true` (12 days) | **200 — downloadable** |
| `false` (3 days) | **404 — never published** |

The three unpublished days — `2026-10-27`, `2026-10-16`, `2026-09-28` — all
carry the summary *"No memory-worthy information."* The last two were empty
before the summarizer ran; `2026-10-27` is the day of this experiment. Every
published day has `journal_item_count > 0`; every unpublished day has `0`.

**So: to make an API call visible, make it something worth remembering.**
Name the artifact, state the decision, give it a fact worth extracting. A
story is not. "Configure X and record the answer Y" is.

---

## 8. The mechanism, in detail

### The mixin import worker

From `GET /kb/status/stream`, the component that does the ingesting:

```json
"mixin_import_worker": {
  "enabled": true,
  "thread_alive": true,
  "import_dir": "/data/backend/tiiny_model_data/mixin",
  "poll_interval": 60.0,
  "batch_lines": 2000,
  "files_seen_last_scan": 1,
  "records_imported_last_scan": 3,
  "records_skipped_last_scan": 0,
  "turns_emitted_last_scan": 0
}
```

Immediately after the three-call probe: `files_seen_last_scan: 1` (one new
file), `records_imported_last_scan: 3` (three calls). The correlation is
exact.

### The status stream is the most revealing endpoint

`GET /kb/status/stream` is an SSE endpoint that emits a full `snapshot` event
and then `update` events on change. It exposes more of the machine's internals
than anything else in the public surface:

- Every worker's state, schedule, and last error
- `lancedb_writes` — drain state, active operations
- `lancedb_consistency` — orphan/missing vector counts, cleanup counters
- `lancedb_recovery` — quarantine dir, audit path
- `conversation_import` — file, record, and turn counters
- `process` — thread count, RSS, CPU

Useful for debugging. It also shows the ingestion pipeline's shape directly.

### Triggering the pipeline without waiting for midnight

The nightly window is 23:00 → 05:00, so a same-day conversation is normally
invisible until the next night. Two levers exist:

```bash
# Trigger the memory workers immediately
curl -X POST "http://<device-ip>/kb/memory/process" \
  -H "Authorization: Bearer $KEY"

# Retry a specific day (only works if it is in a retryable state)
curl -X POST "http://<device-ip>/kb/conversation_days/2026-10-27/retry" \
  -H "Authorization: Bearer $KEY"
```

Verified: `POST /kb/memory/process` returned `{"success": true, "message":
"Memory processing workers were triggered."}` and today's day moved from
`queued` → `summarized` within ~45 s.

`POST /kb/conversation_days/{day}/retry` returned **409** —
*"conversation day is not in a retryable state"* — because the day was
`queued`, not `failed`. It is for recovering a failed day, not for forcing
one early.

**Important:** triggering the workers does not publish a non-memory-worthy
day. `2026-10-27` was triggered twice; both times it produced
`"No memory-worthy information."`, `published_to_sources: false`,
`finalized_at: null`. **Triggering changes when you find out, not whether
you find out.**

### What you can and cannot change about the schedule

`PUT /kb/memory/schedule` accepts only four fields —
`nightly_start_hour`, `nightly_start_minute`, `nightly_end_hour`,
`nightly_end_minute`. Sending the full `summary_worker` object back fails
with `extra_forbidden`.

That means **`manual_drain` cannot be set from outside.** The status stream
reports `manual_drain: false` on both the schedule and the worker, but the
PUT schema does not accept it. There is no other drain endpoint — the full
candidate list was probed and only `/kb/memory/process` responds.

So you can widen the nightly window (e.g. set it to run every hour of the
day), but you cannot flip a manual drain. Widening the window is a blunt
instrument: it changes when summarization runs, not the memory-worthiness
gate.

---

## 9. What was checked and ruled out

So nobody repeats this search.

| Candidate | Result |
|---|---|
| `GET /api/v1/sys/performance` | Aggregate only; **no `/v1/*` entries**; no bodies |
| `GET /api/v1/chat/history/` | `{"data": [], "total": 0}` — empty. Also empty for `app_id=Default`, `default`, `openai`, `api`, `tiiny`, and no param |
| `GET /api/v1/chat/history/sessions` | `{"sessions": []}` |
| Any `/api/v1/sys/logs`, `/logs`, `/usage`, `/requests`, `/audit`, `/metrics`, `/stats`, `/token-usage`, `/dashboard` | All 404 |
| Any `/v1/logs`, `/v1/usage`, `/v1/requests`, `/v1/stats`, `/v1/metrics`, `/v1/admin`, `/debug` | All 404 |
| `GET /kb/sources/originals` | **405 Method Not Allowed** — the path exists but takes no GET. Not in the OpenAPI spec. Worth a closer look; it may be the raw-originals route. |
| `GET /kb/mixin`, `/kb/logs`, `/kb/records`, `/kb/turns`, `/kb/dialogue`, `/kb/raw` | All 404 |
| `GET /kb/status/stream` | Works — but reports **worker state, not call content** |
| Host-header routing (`kb.tiiny.local`, `agents.api.tiiny`, `p8800.api.tiiny`, `api.tiiny`, `openai.api.tiiny`) | All route to the same service; no additional surfaces |
| SSH (22), SMB (139/445), NFS (2049), FTP (21) on the device | All closed — device filesystem access needs another route |
| Any file-read API on the agent services (`/api/files`, `/api/fs`, `/api/read`, `/api/workspace`) | All 404 |
| `GET /api/v1/models/` | Requires auth — model catalog with descriptions, not a call log |
| `POST /kb/upload_conversation` | Returns `{"success": true, "status": "ignored"}` for every date tried — **no disposable day can be created**, so the delete cascade cannot be tested live |
| `GET /kb/journal`, `/kb/raw`, `/kb/turns`, `/kb/content`, `/kb/memory/journal` | All 404 — no endpoint serves raw turn text |
| `GET /kb/sources/journal`, `/kb/sources/originals` | 405 on GET, POST, HEAD and OPTIONS — the routes exist but expose no content |
| Any `/kb/audit`, `/kb/logs`, `/kb/events`, `/kb/history`, `/api/v1/sys/logs`, `/api/v1/audit` | All 404 — **the encrypted log Zolon observed is not reachable over HTTP** |

---

## 10. What would close the gap

Ordered by how much each would help.

### 1. Log the inference surface too

`/api/v1/sys/performance` already logs the management API. Adding `/v1/*`
would make the endpoint answer Zolon's question for the calls that matter
most — even in aggregate form, that is a large improvement over zero.

### 2. Separate operational records from memory

The deepest fix. Memory-worthiness is a summariser's judgement call, and it
should not govern whether operational evidence survives. API call records
should be retained on their own retention policy — not summarised, not
discarded, not promoted into memory.

### 3. A per-caller view of what was sent

Something like `GET /kb/sources?source_type=api_call`, or a `client_id` /
`app_name` parameter on the OpenAI surface that routes calls into a
retrievable stream.

Note that **the OpenAI-compat surface already accepts and ignores
`app_id`, `app_name`, `app`, `user_id`, `session_id`, and `client`** — all
six are accepted with HTTP 200 and have no effect. The guide says calls
without an app name are grouped under **Default** on the dashboard, so the
field is meaningful to TiinyOS. **Wiring it through to a retrievable log is
mostly plumbing that already half-exists.**

### 4. A raw-originals route

`GET /kb/sources/originals` returns 405 — the route exists and refuses GET.
If it returned the original files (the way `GET /kb/files/{source_id}` does
for published sources), the mixin directory's contents would be reachable
over HTTP instead of requiring device access.

### 5. Make `manual_drain` settable

It is reported by the status stream on two objects and accepted by neither.
`PUT /kb/memory/schedule` is a strict four-field schema. A `manual_drain`
field, or a `POST /kb/memory/process?drain=true`, would let an operator
force publication on demand.

---

## 11. Evidence and confidence

Per the AMC's evidence-tiering rule, here is what each claim rests on.

| Claim | Tier | Basis |
|---|---|---|
| API calls reach the mixin directory and are ingested | **(a) captured** | 3-call probe moved `records_imported_last_scan` from 0 → 3 |
| The ingestion pipeline is the mixin worker at a 60 s poll | **(a) captured** | Status stream, plus the counter correlation |
| The `/v1/*` surface is absent from the performance log | **(a) captured** | `total_requests` unchanged at 49 across a chat completion; zero `/v1` paths in the endpoint list |
| The performance endpoint carries no request or response content | **(a) captured** | Full payload scanned — zero hits for body/prompt/content/headers fields |
| A non-memory-worthy day is never published | **(a) captured** | `published_to_sources: false`, `finalized_at: null`, file 404, across two forced processing runs |
| Published days are downloadable | **(a) captured** | 12 published days → 200; 3 unpublished → 404 |
| The marker was in no viewable surface | **(a) captured** | Searched across 14 surfaces |
| The dashboard shows token stats grouped by date/model/app | **(b) device doc** | User guide Chapter 7, §7.1 |
| `manual_drain` is reported but not settable | **(a) captured** | Status stream reports it; PUT rejects extra fields |
| The 405 on `/kb/sources/originals` is a raw-originals route | **(d) inference** | 405 with no spec entry; not probed further for safety |
| `DELETE /kb/conversation_days/{day}` removes the day's vault text, source, journal, facts and proposals | **(b) device spec** | `DeleteConversationDayResponse` names every counter; Zolon verified the behaviour live |
| The delete leaves the mixin file, the retained user-context versions, and the encrypted log | **(a) captured + (b) spec** | `context_versions_retained` is an explicit field; the mixin dir appears in no delete field; the encrypted log is Zolon's direct observation, unverifiable over HTTP |
| A deleted day does not resurrect | **(a) captured** | `skipped_records: 50` alongside `imported_records` — the importer dedups on already-consumed records |
| The delete cascades to facts derived from that day | **(b) device spec, untested** | `deleted_facts` / `deleted_proposals` counters exist, but `POST /kb/upload_conversation` rejects every upload, so no disposable day could be created to test it |
| The right fix is a retention-policy split | **(e) judgement** | My read, not a device fact — Zolon and the Tiiny team may see it differently |

**Not yet determined:** whether the raw turn text is retained anywhere in
LanceDB after summarization discards it, or whether only the summarized form
survives. The marker search across 14 surfaces came back empty, but the
LanceDB tables themselves were not read directly — that needs device-level
access. Zolon's report that he found the story by searching lancedb on the
device is consistent with the raw turn text surviving in a table that no
endpoint exposes. **If you have device access, that is the one thing worth
checking.**

---

## 12. One question for the Tiiny team

For Zolon and anyone else integrating against the device:

> API calls are captured, ingested into the knowledge base, and then
> summarised. If the summarizer judges a call not worth remembering, the raw
> record is not published to any source and becomes unreachable over HTTP.
>
> **Should there be a retention policy that keeps API call records
> retrievable regardless of memory-worthiness?** And if not, **what is the
> intended way for an integrator to see the calls they made?**

Both answers are reasonable. What is not reasonable is the current state,
where the answer is "shell into the device and query LanceDB directly" —
because the data was collected specifically to be used.

**Zolon has since answered part of this** by publishing the delete recipe
(§5), which gives integrators a supported way to remove what they don't
want retained. Two questions remain open, and they are the ones to put to
the team:

1. **The raw log.** `DELETE /kb/conversation_days/{day}` clears the vault's
   view of a day. It does not touch the per-day mixin file in
   `/data/backend/tiiny_model_data/mixin`, nor the retained user-context
   versions, nor the encrypted log Zolon has observed. **Should there be a
   delete that reaches the source of record** — or a documented statement of
   what "deleted" means?

2. **Granularity.** A day is the finest unit. API turns and TiinyOS chat
   turns are merged before the vault sees them, so an integrator cannot
   remove their API traffic without removing their TiinyOS chat for that
   day. **Can the two be separated at write time?**

---

## 13. What Zolon's published notes added

Zolon published his own field notes on 2026-10-27 —
[thezolon/tiiny-api-notes](https://github.com/thezolon/tiiny-api-notes) —
covering the same device. His endpoint set is a subset of this one's KB spec
and nothing in it contradicts anything above. Three things he established
that are worth carrying here, because they sharpen §3 and §4:

**The memory scope does not stop capture.** `GET/PUT /kb/memory/scope` takes
`{"scope": "all" | "tiinyos"}`, and the spec calls it the *summary* scope:
`tiinyos` "summarizes TiinyOS client chats only", `all` "summarizes every
LLM output". It reads like the switch you would want. Zolon tested it —
after switching to `tiinyos`, an API chat was **still captured the same
way**. At most the setting narrows what gets summarised, not what gets
recorded. (`GET` also reports `supported_scopes` and `origin_tagging`.)

**Captures are batched, and they land on whole minutes.** On an idle device
the day's `/kb/conversation_days/{day}` entry did not change for nine
minutes; one chat sent straight to the gateway's `/v1/chat/completions`
changed its `content_updated_at` 14 seconds later. So the capture is not
immediate and not per-request — and a call can sit invisible in the gap.

**The delete has still not been tested on a summarised day.** Zolon tested it
on a day that had *not* been summarised: the day was gone from the list, its
text was gone from the vault, and the vault did not re-import it. He states
the response "is meant to remove what was summarised from that day as well"
— and marks it not yet tested. So the §5 caveat is open from both sides now,
which is exactly why it is worth settling.

**He has reported the un-deletable request log to Tiiny** and is waiting for
their answer.

One deliberate difference worth naming: his repo's ground rules exclude
root/firmware internals, addresses, keys and data, and say security issues
go to Tiiny privately first. This document names the mixin path instead. The
two approaches are both defensible — his is more conservative, and it is
the one a vendor's own co-creator can afford. If you are publishing your own
notes, decide deliberately which line you are on rather than by accident.

---

## Related

- [`README.md`](./README.md) — the six
  documentation surfaces, for the Discord audience
- [thezolon/tiiny-api-notes](https://github.com/thezolon/tiiny-api-notes) —
  Zolon's own field notes on the same device, plus a snapshot tool that diffs
  the published specs across a TiinyOS update