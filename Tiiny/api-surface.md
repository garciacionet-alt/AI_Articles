# Tiiny AI Pocket Lab — Complete API Surface

**What this is.** Every HTTP endpoint the Tiiny AI Pocket Lab exposes, catalogued
from the device's own OpenAPI specs on 2026-10-26. Written after finding the
device's documentation at `http://tiinyhost.local/kb/docs` — which turned out to
be one of **three** API surfaces on one device, not the only one.

**Updated 2026-11-01.** The OpenAPI specs are not the whole story. The device
also serves an undocumented `/api/services/*` family that `openapi.json` does
not describe — and it carries the **full** Agent Store catalogue. See
`services` under Surface 2.

**Author of these notes:** AntAttack (Gary Garcia)

---

## The one thing to know first

`tiinyhost.local` and `openai.api.tiiny` are **the same device**. The management
OpenAPI spec served from both is byte-identical (42,710 bytes, sha256 prefix
`fcda418e2c184cd7`). `openai.api.tiiny` resolves to `127.0.0.1` locally because a
loopback proxy answers on that name; `tiinyhost.local` resolves to the device's
real LAN address, `192.168.1.x`.

So there are **three surfaces**, one box, and **one bearer token** for all of
them:

| # | Surface | Base URL | Spec | Docs | Auth |
|---|---|---|---|---|---|
| 1 | **OpenAI-compatible** (inference) | `http://openai.api.tiiny/v1` | not published | — | bearer |
| 2 | **Management** (device control) | `http://tiinyhost.local/api/v1` | `/openapi.json` | `/docs`, `/redoc` | bearer |
| 3 | **SimpleMem Knowledge Base** | `http://tiinyhost.local/kb` | `/kb/openapi.json` | `/kb/docs`, `/kb/redoc` | bearer |

**All three accept the same device bearer** — the one in
`projects/pocketlab/CREDENTIALS.md`. Verified: the same token opens
`/api/v1/sys/status`, `/kb/sources`, and `/v1/models`.

**The KB service is the one nobody documents.** It is a full
single-user long-term-memory service — its own OpenAPI spec calls it *"HTTP
service for single-user long-term memory knowledge base"*, version 2.0.0, 54
operations across 8 functional groups. It stores facts, holds user-context
profiles with version history, runs a nightly summarization queue, and answers
semantic queries. It is on the device and it is **not** part of the Tiiny Vault
CLI surface.

### Getting the specs

```bash
curl -s http://tiinyhost.local/openapi.json    -o mgmt-openapi.json
curl -s http://tiinyhost.local/kb/openapi.json -o kb-openapi.json
```

Both are unauthenticated. The `/kb/docs` Swagger UI loads the spec from
`/kb/openapi.json`; the `/docs` UI loads `/openapi.json`.

---

## Surface 1 — OpenAI-compatible (inference)

Not in any published spec. Documented in the `tiiny-octo` skill.

| Path | Purpose |
|---|---|
| `POST /v1/chat/completions` | text + vision chat |
| `POST /v1/embeddings` | 1024-dim embeddings |
| `POST /v1/images/generations` | image gen |
| `POST /v1/audio/transcriptions` | ASR (multipart) |
| `POST /v1/audio/speech` | TTS |
| `GET /v1/models` | addressable models only |
| `GET /health` | device health + TTS availability |

**`GET /v1/openapi.json` returns 404 even with a valid bearer.** The inference
surface is undocumented by design.

---

## Surface 2 — Management API (`/api/v1`)

FastAPI, 36 paths. Spec: `/openapi.json` (42.710 KB). Docs: `/docs`, `/redoc`.

**Auth:** `Authorization: Bearer <token>`. Two exceptions — `GET /` and
`GET /api/v1/sys/device_info` need no auth, and the whole `/api/v1/account/*`
group plus `/api/v1/connect` are declared without auth in the spec (legacy;
account flows migrated to authd).

### `system`

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/api/v1/sys/ac_power/` | Get Ac Power | — |
| `POST` | `/api/v1/sys/ac_power/` | Set Ac Power | json switch*:integer |
| `POST` | `/api/v1/sys/base_urls` | Runtime Base Urls | — |
| `GET` | `/api/v1/sys/device_info` | Device Info | — |
| `GET` | `/api/v1/sys/performance` | Performance Stats | query limit:integer, sort_by:string, include_stats_endpoint:boolean |
| `POST` | `/api/v1/sys/reboot/` | Reboot | — |
| `POST` | `/api/v1/sys/setting` | Update Setting | — |
| `POST` | `/api/v1/sys/shutdown/` | Shutdown | — |
| `GET` | `/api/v1/sys/status` | System Status | — |
| `GET` | `/api/v1/sys/storage` | Storage Info | — |
| `GET` | `/api/v1/sys/storage/agent` | Agent Storage Info | — |
| `DELETE` | `/api/v1/sys/storage/agent/{agent_name}` | Delete Agent | query agent_name*:string |
| `GET` | `/api/v1/sys/storage/llm` | Llm Storage Info | — |

### `apps`

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/api/v1/apps` | Get App Index | query id:any |
| `GET` | `/api/v1/apps/icons` | Get App Icons | — |

### `services` — the Agent Store, outside the published spec

Found 2026-11-01. These live under `/api/services/`, **not** `/api/v1/`, and
they are **absent from the device's own OpenAPI spec** — `openapi.json` does not
describe them, so they are invisible to anything generated from the spec. They
are nonetheless the endpoint that carries the full Agent Store catalogue.

| Method | Path | Purpose | Returns (2026-11-01) |
|---|---|---|---|
| `GET` | `/api/services/apps/metadata` | Agent Store catalogue | `app` (18), `categories` (5), `carousel` (4), `integration_body` (16) |
| `GET` | `/api/services/cloud/apps` | Installable cloud apps | 10 |
| `GET` | `/api/services` | Installed services | 7 |

**`/api/v1/apps` is not the whole Agent Store.** It returns 13 apps;
`/api/services/apps/metadata` returns 18. The five that only the `services`
path lists are `pi` (Pi), `goose` (Goose), `cline` (Cline),
`wa-deepseekharness` (DeepSeek Harness) and `wa-tiinyvisuals` (Tiiny Image).
Every app in the 13-app list is also in the 18-app list, so the `services`
catalogue is a superset. If you are counting what the device can run, the
`/api/v1/apps` count undercounts by five.

`categories` is fixed at five — Trend, Work, Play, Develop, Category — and
every app carries all five, so the category list is a store-wide nav rather
than a per-app tag. `integration_body` is the per-app platform breakdown
(`app_type` of `browser`, `desktop`, `cli` or `extension`, with artifact URLs
and sha256 bundles).

**Two catalogues, two counts.** The Agent Store is a separate catalogue from
the Model Store and moves on its own schedule. A read of the Model Store on
2026-11-01 still showed the same 82 models with byte-identical descriptions
while the Agent Store had expanded — so "the catalogue" is ambiguous unless
you say which one.

### `history`

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/api/v1/chat/history/` | Get Chat History | query app_id:any, session_id:any, page:integer, per_page:integer |
| `GET` | `/api/v1/chat/history/sessions` | Get Sessions | query app_id*:string |
| `DELETE` | `/api/v1/chat/history/{session_id}` | Delete Chat History | query session_id*:string |

### `webapp`

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/api/v1/webapp/` | Get Web App List | — |
| `GET` | `/api/v1/webapp/running` | Get Running Web Apps | — |
| `POST` | `/api/v1/webapp/start` | Start Web App | json app_container_name*:string |
| `POST` | `/api/v1/webapp/stop` | Stop Web App | json app_container_name*:string |

### `account`

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/api/v1/account/auth` | Auth | — |
| `POST` | `/api/v1/account/bind_email` | Bind Email | — |
| `POST` | `/api/v1/account/change_mail` | Change Mail | — |
| `POST` | `/api/v1/account/change_password` | Change Password | — |
| `POST` | `/api/v1/account/check_mail_code` | Check Mail Code | — |
| `POST` | `/api/v1/account/check_mail_sign_up_status` | Check Mail Sign Up Status | — |
| `POST` | `/api/v1/account/check_main_password` | Check Main Password | — |
| `POST` | `/api/v1/account/login_with_mail_code` | Login With Mail Code | — |
| `POST` | `/api/v1/account/reset_password` | Reset Password | — |
| `POST` | `/api/v1/account/send_mail_code` | Send Mail Code | — |
| `POST` | `/api/v1/account/set_local_account_info` | Set Local Account Info | — |
| `POST` | `/api/v1/account/set_main_password` | Set Main Password | — |
| `POST` | `/api/v1/account/upload_feedback` | Upload Feedback | json mail:any, content*:string, images:any |
| `POST` | `/api/v1/connect` | Connect | — |

### Unauthenticated but reachable

| Method | Path | Returns |
|---|---|---|
| `GET` | `/` | `{"status":"ok","msg":"Hi there! Welcome to Tiiny Server!","version":"0.1.30-debug","is_activated":false}` |
| `GET` | `/api/v1/sys/device_info` | model, OS version, CPU/GPU/dNPU, RAM, storage |

**`device_info` is the cheap identity check** — no token, no side effects:
`Tiiny z01`, TiinyOS `0.1.36`, ARMv9.2, GPU G720, dNPU 160 BF16 TOPs, 80 GB
RAM, 1 TB.

---

## Surface 3 — SimpleMem Knowledge Base (`/kb`)

OpenAPI 3.1.0, version **2.0.0**, **59 operations across 50 paths**, 8 functional
groups. Spec: `/kb/openapi.json` (65.721 KB). Docs: `/kb/docs`, `/kb/redoc`.

> Re-count the spec rather than trusting a number here — it grew from 54
> operations / 46 paths on 2026-10-26 to 59 / 50 on 2026-10-27.

**Auth:** `Authorization: Bearer <same device token>` on every operation except
`GET /kb/health`, which returns `{"status":"ok","service":"simplemem-kb"}`.

**Path mapping gotcha.** The spec's paths are relative to the **service root**,
so the live URL is the spec path with the service mounted under `/kb`:

- spec `/kb/add` → live `POST /kb/add` ✅
- spec `/kb/sources` → live `GET /kb/sources` ✅
- spec `/health` → live `GET /kb/health` ✅
- spec `/kb/health` → live `GET /kb/kb/health` ❌ 404

So: **strip the leading `/kb` from the spec path and prepend `/kb`** — the
net effect is that spec paths under `/kb/` are live verbatim, and the spec's
bare `/health` is live at `/kb/health`.

**The `/v1/backup` and `/v1/restore` group does not resolve.** The spec declares
`GET /v1/backup`, `GET /v1/backup/inspect`, `POST /v1/restore/inspect`,
`POST /v1/restore` — but every candidate URL 404s (`/v1/backup`,
`/kb/v1/backup`, `/kb/v1/backup/inspect`, `/v1/backup/inspect`). These paths
also collide with the OpenAI surface's `/v1/*` namespace, where `/v1/models` and
`/v1/chat/completions` do live. The backup endpoints appear to be declared but
not mounted in this build. Do not rely on them.

### What the service actually holds

Measured live on 2026-10-26 with the device bearer:

| Store | Count |
|---|---|
| Sources (files + conversation days) | 14 |
| Memories (vector entries) | 225 |
| Memory facts | 50 |
| Conversation days | 14 |

`source_type` is the only partition axis, and it has exactly two values:
`conversation_day` (11) and `file` (3).

### Dialogue Ingestion

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/kb/add` | Add Memory | json speaker*:string, content*:string, timestamp:any, source_id:any, auto_finalize:boolean |
| `POST` | `/kb/add-batch` | Add Batch | json items:array, source_id:any, auto_finalize:boolean |
| `POST` | `/kb/add/stream` | Add Memory Stream | json speaker*:string, content*:string, timestamp:any, source_id:any, auto_finalize:boolean |

### Finalization

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/kb/finalize` | Finalize | — |
| `POST` | `/kb/finalize/stream` | Finalize Stream | — |
| `POST` | `/kb/finalize_conversation` | Finalize Conversation | — |

### Conversation Queue

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/kb/conversation_days` | List Conversation Days | query limit:integer, offset:integer |
| `DELETE` | `/kb/conversation_days/{day}` | Delete Conversation Day | query day*:string |
| `GET` | `/kb/conversation_days/{day}` | Get Conversation Day | query day*:string |
| `GET` | `/kb/memory/model` | Get Memory Processing Model | — |
| `PUT` | `/kb/memory/model` | Update Memory Processing Model | json model_id*:string |
| `POST` | `/kb/memory/process` | Trigger Memory Processing | — |
| `GET` | `/kb/memory/schedule` | Get Memory Processing Schedule | — |
| `PUT` | `/kb/memory/schedule` | Update Memory Processing Schedule | json nightly_start_hour*:integer, nightly_start_minute:integer, nightly_end_hour:any, nightly_end_minute:any |
| `POST` | `/kb/upload_conversation` | Upload Conversation | json text*:string, time*:string |
| `GET` | `/kb/upload_conversation/stats` | Upload Conversation Stats | — |

### Query & Retrieval

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/kb/context` | Build Memory Context | json query*:string, fast_mode:boolean, include_user_context:boolean, include_facts:boolean, include_vector_memories:boolean, max_tokens:any |
| `GET` | `/kb/query` | Query Get | query question*:string, fast_mode:boolean |
| `POST` | `/kb/query` | Query Post | json question*:string, fast_mode:boolean, include_memory_context:boolean, return_memory_context:boolean, memory_context_max_tokens:any |
| `POST` | `/kb/query/stream` | Query Stream | json question*:string, fast_mode:boolean, include_memory_context:boolean, return_memory_context:boolean, memory_context_max_tokens:any |
| `GET` | `/kb/retrieve` | Retrieve Get | query question*:string, fast_mode:boolean |
| `POST` | `/kb/retrieve` | Retrieve Post | json question*:string, fast_mode:boolean, include_memory_context:boolean, return_memory_context:boolean, memory_context_max_tokens:any |

### File Sources

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/kb/edit-file` | Edit File | form-data source_id*:string, file*:string, timestamp:any, auto_finalize:boolean |
| `GET` | `/kb/files/{source_id}` | Download File | query source_id*:string |
| `GET` | `/kb/sources` | List Sources | query limit:integer, offset:integer |
| `GET` | `/kb/sources/conversations` | List Conversation Sources | query limit:integer, offset:integer |
| `GET` | `/kb/sources/files` | List File Sources | query limit:integer, offset:integer |
| `PATCH` | `/kb/sources/{source_id}` | Update Source | json filename:any; query source_id*:string |
| `POST` | `/kb/upload` | Upload File | form-data file*:string, timestamp:any, finalize_now:boolean, source_id:any |
| `POST` | `/kb/upload/stream` | Upload File Stream | form-data files*:array, timestamp:any, finalize_now:boolean, source_id:any |

### User Context

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/kb/memory/facts` | List Memory Facts | query status:any, fact_type:any, subject:any, q:any, limit:integer, offset:integer |
| `POST` | `/kb/memory/facts` | Create Memory Fact | json fact_type*:string, subject:string, predicate*:string, object*:string, qualifiers:object, confidence:number, source_type:any, source_id:any, source_entry_id:any, evidence:any |
| `DELETE` | `/kb/memory/facts/{fact_id}` | Delete Memory Fact | query fact_id*:string |
| `PATCH` | `/kb/memory/facts/{fact_id}` | Patch Memory Fact | json fact_type:any, subject:any, predicate:any, object:any, qualifiers:any, confidence:any, source_type:any, source_id:any, source_entry_id:any, evidence:any; query fact_id*:string |
| `GET` | `/kb/memory/proposals` | List Memory Proposals | query status:any, risk_level:any, source_id:any, limit:integer, offset:integer |
| `POST` | `/kb/memory/proposals/{proposal_id}/approve` | Approve Memory Proposal | query proposal_id*:string |
| `POST` | `/kb/memory/proposals/{proposal_id}/reject` | Reject Memory Proposal | query proposal_id*:string |
| `GET` | `/kb/user-context` | Get User Context | — |
| `PUT` | `/kb/user-context` | Update User Context | json markdown:string |
| `PUT` | `/kb/user-context/profile` | Replace User Context Profile | json user_name:string, occupation:string, preferences:string, more_about_you:string |
| `PATCH` | `/kb/user-context/profile/{field_name}` | Patch User Context Profile Field | json value:string; query field_name*:string |
| `POST` | `/kb/user-context/upload` | Upload User Context | form-data file*:string |
| `GET` | `/kb/user-context/versions` | List User Context Versions | query limit:integer, offset:integer |
| `GET` | `/kb/user-context/versions/{version_id}` | Get User Context Version | query version_id*:string |
| `POST` | `/kb/user-context/versions/{version_id}/restore` | Restore User Context Version | query version_id*:string |

### Administration

| Method | Path | Purpose | Request |
|---|---|---|---|
| `POST` | `/kb/clear` | Clear | — |
| `POST` | `/kb/delete-memory` | Delete Memory | json source_id*:string |
| `GET` | `/kb/memories` | List Memories | query limit:integer, offset:integer |

### System

| Method | Path | Purpose | Request |
|---|---|---|---|
| `GET` | `/health` | Health | — |
| `GET` | `/kb/status/stream` | Status Stream | query max_events:any |
| `GET` | `/v1/backup` | Create Backup | — |
| `GET` | `/v1/backup/inspect` | Inspect Backup | — |
| `POST` | `/v1/restore` | Restore Backup | — |
| `POST` | `/v1/restore/inspect` | Inspect Restore | — |

---

## What this service does that the CLI does not

The `tiiny` CLI exposes the **Vault** (`tiiny vault add|index|query|rm`) — a
flat, chunked-RAG workspace over documents you upload. The **KB service is a
different thing** and is only reachable over HTTP. It has:

1. **Typed facts.** `POST /kb/memory/facts` writes a subject–predicate–object
   triple with `fact_type`, `qualifiers`, `confidence`, `status`, and
   `evidence`. That is a structured knowledge layer, not a document index.
2. **A proposal workflow.** `GET /kb/memory/proposals` lists candidate changes
   with `status` and `risk_level`; `POST /kb/memory/proposals/{id}/approve`
   and `/reject` adjudicate them. Writes can be gated rather than immediate.
3. **Versioned user context.** `GET /kb/user-context` returns a profile
   (`user_name`, `occupation`, `preferences`, `more_about_you`) plus rendered
   markdown, a token estimate, and a `target_tokens`/`max_tokens` budget.
   `GET /kb/user-context/versions` lists history;
   `POST /kb/user-context/versions/{id}/restore` rolls back.
4. **A nightly processing pipeline.** `GET /kb/memory/schedule` returns a
   `conversation_summary` worker with a window (this device: 23:00→05:00, 6
   hours), a 3600 s poll interval, a 1800 s retry interval, and a
   `last_outcome` field. `PUT /kb/memory/schedule` changes it;
   `PUT /kb/memory/model` sets the summarization model (empty string disables
   automatic summarization).
5. **A memory-context builder.** `POST /kb/context` assembles user context,
   facts, and vector memories into one budgeted string with citations and a
   token estimate — the same shape an agent wants before every turn.

### The nightly pipeline can fail

`GET /kb/memory/schedule` on this device, 2026-10-26:

```
"last_outcome": "failed",
"last_attempt_at": "2026-10-26T23:00:00+08:00",
"last_deferred_until": "2026-10-26T23:31:58+08:00",
"in_nightly_window": true
```

`GET /kb/upload_conversation/stats` showed 2 days still `queued`, 12
`summarized`, 0 failed — and 2 refinement jobs queued. The `summary_worker`
retries on a 1800 s interval and defers to the next window on failure. So the
pipeline is **self-healing but not self-reporting**: a failed night is visible
only if you read the schedule endpoint.

`GET /kb/memory/model` returned `{"model_id":"", "automatic_summary_enabled":true, "running_models":[]}`
— automatic summarization is enabled but **no model is selected and none are
running**, which is the likeliest cause of the failure. The summarization model
is a device-local model that has to be loaded, and **models unload on reboot**.

---

## Multi-agent, multi-machine: what the API actually allows

This is the question that matters if you want to build an agent memory system
on this device. Tested directly.

**What works.**

- **Any machine on the LAN can reach it.** `192.168.1.x:80` answers `/kb/health`
  directly, and `/kb/*` is bound to the LAN interface, not loopback-only.
- **Concurrent writes are safe.** Three parallel `POST /kb/add` calls with
  distinct `source_id`s all returned HTTP 200 in 0.18 s wall clock, each
  producing its own `source_id` and chunk. No lost writes, no serialization.
- **One token opens it from anywhere on the LAN.** No per-agent credential, no
  per-machine registration.

**What does not exist.**

- **No agent, machine, user, tenant, or namespace parameter anywhere in the
  spec.** A programmatic sweep of all 59 operations for
  `agent_id`, `agent_name`, `namespace`, `tenant`, `user_id`, `machine`,
  `workspace`, `project_id`, `session_id` returns **zero hits**. The service
  describes itself as *"single-user"*.
- **One shared namespace, therefore one shared blast radius.** Any agent that
  can reach the token can read *every* memory, fact, and file source, and can
  write into the same pool. `POST /kb/clear` wipes it. `POST /kb/delete-memory`
  deletes by `source_id` with no ownership check.
- **No per-agent write discipline.** Contrast the AMC, where each agent writes
  only to its own `_agent-<name>/` folder and reads from anywhere. Here, every
  writer lands in the same table and the only way to tell writers apart is the
  `source_id` string the caller invents.
- **The write path is asynchronous and lossy in the middle.** `POST /kb/add`
  returns `chunks` and `finalized:false`. Facts and memory entries are produced
  later by the nightly worker. A fact written now may not exist until tonight.

**So: can Tiiny by itself be a multi-agent, multi-machine memory system?**

**Yes as a shared store. No as a multi-agent memory *architecture*.**

What the device gives you is a **single-writer-namespace memory service with a
gated, versioned, queryable store** — genuinely more than most people would
build, and it comes with a working nightly consolidation pipeline and a
human-review proposal queue. That is a real answer for *several agents on one
machine, or several agents that don't need to know about each other*.

What it cannot give you is the thing the AMC gives you: **a shared store where
each agent also has a defined private area, and where the separation between
"what I wrote" and "what we all wrote" is enforced by the write path rather
than by convention.** On the device, isolation is a naming convention you
invent. In the AMC, it is a directory boundary.

Two more limits worth knowing before designing around this:

1. **One device is one device.** The AMC syncs a file commons across machines
   through iCloud, and the semantic layer is a separate local database per
   machine. Tiiny's KB is a single SQLite/LanceDB-shaped store on one box. If
   the box is off, every agent that depends on it has no memory — there is no
   local cache tier and no offline mode.
2. **The device is a shared finite resource.** One NPU, one generation at a
   time per model. Two agents hammering `/kb/query` (which runs inference
   server-side) contend for the same silicon, and the failure mode is a hang,
   not an error.

---

## Surface 4 — Undocumented Device Management API (`/api/v1/models/*` & `/api/v1/npu/*`)

Discovered 2026-11-16. These endpoints are completely absent from `openapi.json`
(which only lists 36 paths) but are actively served by each Tiiny appliance on port 80.
They provide direct, programmatic model lifecycle and NPU monitoring without requiring
the `tiiny` CLI or a pseudo-terminal.

**Auth:** `Authorization: Bearer <device_api_key>` (same key as Surface 2).

### Endpoints

| Method | Path | Returns / Purpose | Payload / Notes |
|---|---|---|---|
| `GET` | `/api/v1/models/` | Complete model inventory with live statuses | Returns `{"object":"list","data":[...]}`. Each entry includes `status` (`running`, `downloaded`, `not_downloaded`), `npu_usage`, `size`, `thinking`, `load_time`. |
| `GET` | `/api/v1/models/running` | Currently resident models | Returns `{"running": ["<model_id>", ...], "pending": [], "instances": {...}}`. Instant residency check. |
| `GET` | `/api/v1/models/online_models` | Model store online catalogue | Returns full store list with capabilities, parameters, and download counts. |
| `POST` | `/api/v1/models/{model_id}/start` | Start/load model into NPU memory | `POST` with empty JSON `{}`. Returns `{"message": "start loading ...", "progress": 0}`. Poll `/api/v1/models/running` until loaded. |
| `POST` | `/api/v1/models/{model_id}/stop` | Stop/unload model from NPU | `POST` with empty JSON `{}`. Returns `{"message": "stop model ... success"}`. |
| `POST` | `/api/v1/models/{model_id}/download` | Download model from store | `POST` with empty JSON `{}`. |
| `GET` | `/api/v1/npu/status` | Real-time NPU telemetry | Returns `{"hm_smi_available": true, "devices": [{"mem_used_mb": float, "mem_total_mb": 49024.0, ...}], "cpu": {...}, "memory": {...}}`. |
| `GET` | `/api/v1/sys/device_info` | Hardware specifications (unauthenticated) | Returns hardware architecture (ARMv9.2, 80 GB RAM, 190 TOPS peak INT8 across 160 TOPS dNPU + 30 TOPS SoC). |

### Important Operational Caveats

1. **The 405 Method Not Allowed Catch-All Trap:**
   Calling `POST /api/v1/models/{model}/load` or `POST /api/v1/models/{model}/unload` returns
   `405 Method Not Allowed`. This occurs because the route parameter is captured by `/api/v1/models/{model_id}`,
   and the only accepted action verbs are `/start`, `/stop`, and `/download`.
2. **`tiiny scan --json` Output Format:**
   The CLI `--json` flag is ignored by `tiiny scan`; it outputs a formatted ASCII table, not JSON. Automated tools should parse the tabular output or use mDNS directly.
3. **Multi-Device Credential Isolation:**
   The CLI flag `--device-address` overrides the target IP address but continues using the authentication key from the active configuration. Managing multiple appliances requires distinct per-device configuration files (`tiiny --config <path>`).

---

## Verification notes

Everything above was read from the device's own OpenAPI specs and confirmed by
calling the live endpoints with the device bearer. The write-path probes
(`/kb/add`, `/kb/delete-memory`) were cleaned up afterward: the device was back
to its original 14 sources with no probe entries remaining.

**Evidence tiers.** Endpoint inventories, request/response schemas, and auth
requirements are **direct** — read from the spec, confirmed by live call.
Counts (14 sources, 225 memories, 50 facts) are a **point-in-time snapshot**
from 2026-10-26 and will drift. The multi-machine and concurrency findings are
**measured** from this Mac on the same LAN. The claim about *other* machines is
inference from the LAN binding — the device answers on `192.168.1.x:80` from a
different IP on the same subnet, which is the mechanism a second machine would
use, but it was not tested from a physically separate machine.

---

## Where the detail lives

- `projects/pocketlab/CREDENTIALS.md` — bearer, model list, client code
- `projects/tiiny-discovery/README.md` — the full discovery log for the device
- [`projects/tiiny-discovery/tiiny-documentation-surfaces.md`](./tiiny-documentation-surfaces.md) — the **documentation** map: all six doc surfaces (including `dev.tiiny.ai` and `help.tiiny.ai`), the `tiiny kb` vs `tiiny vault` CLI mismatch, and the bearer-token-in-the-Vault finding
- `~/.hermes/skills/mlops/tiiny-octo/SKILL.md` — the operating skill
- `../agent-memory-commons/PATTERN.md` — the published AMC pattern
