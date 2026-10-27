# Tiiny Documentation Map — Every Document Your Device Ships With

**You do not have to go hunting.** A new Tiiny comes with more documentation
than the official links suggest — including two full cloud documentation sites
that nobody tells you about, and a live API reference running on the device
itself. This is the map.

Everything below was verified by enumeration on a real Tiiny z01 on
2026-10-27 — every URL was fetched, every page count was counted from the
site's own manifest, not guessed.

**Updated 2026-10-27 (second pass).** This version adds §8's delete recipe,
contributed by Zolon (Tiiny co-creator, author of Engraphis) on Discord and
verified against the device: the delete endpoint, its five caveats, and the
three things that survive it. Where the vendor's own documentation and the
device disagree, both are given.

> **A note on what you are looking at.** This document separates two things
> that look identical in a data dump but are not the same:
>
> - **Shipped documentation** — present on every new device. This is what you
>   get, and it is what this guide is about.
> - **Your own data** — the memories, facts and summaries that *you* create by
>   using the device. On the machine this was measured on, the knowledge base
>   also held 12 days of one owner's conversation history and three personal
>   files. **That is not factory content.** If you see it in someone else's
>   device dump, it is theirs, not Tiiny's.
>
> The split matters because a device that looks "well documented" may simply be
> one person who used it a lot. See §7 for how to tell them apart.

---

## 1. The six documentation surfaces at a glance

| # | Surface | Where | What it holds |
|---|---|---|---|
| 1 | **Tiiny Server Swagger UI** | `http://<device-ip>/docs` | Live API reference — 36 operations, the management API |
| 2 | **Tiiny Server ReDoc** | `http://<device-ip>/redoc` | The same 36 operations, rendered as readable prose |
| 3 | **SimpleMem KB Swagger UI** | `http://<device-ip>/kb/docs` | Live API reference — 50 paths / 59 operations, the knowledge-base service |
| 4 | **SimpleMem KB ReDoc** | `http://<device-ip>/kb/redoc` | The same spec, rendered as readable prose |
| 5 | **Tiiny Developers** | `https://dev.tiiny.ai` | **24 pages — the real SDK and API reference** |
| 6 | **Tiiny Help** | `https://help.tiiny.ai` | **27 pages — end-user guide, troubleshooting, and the legal/policy text** |

Surfaces 1–4 are two OpenAPI specifications, each rendered twice (Swagger for
browsing, ReDoc for reading). Surfaces 5–6 are **two entirely separate
documentation websites** — they share no page content at all (zero identical
page bodies), and they cover the same ground from different angles: `dev` is
written for someone integrating, `help` for someone using the device. Neither
one alone is the whole story.

**Everything on surfaces 1–4 works without a token.** Point any browser at
`http://<device-ip>/docs` and it renders. No API key, no login, no headers.
This is the fastest way to see exactly what your device can do.

### Finding your device's IP

```bash
tiiny scan          # lists devices with their IP address
```

Or on macOS/Windows, read it from the device's own discovery endpoint:

```bash
curl http://<device-ip>:39218/device.json
```

That returns the device name, serial number, hostname, USB/LAN addresses, and
the port the service is on. It needs no authentication.

---

## 2. Surfaces 5 and 6 — the two cloud sites (the big ones)

These are the ones that answer "how do I use this thing," and both are
referenced from the device's own user guide — but only in one sentence, which
is why so many people never find them.

### `dev.tiiny.ai` — for developers and integrators

24 published pages. The full inventory:

| Group | Pages |
|---|---|
| **Get Started** | Overview · Quick Start · API Key |
| **Concepts** | Overview · Model Management · Device & Network · Vault · Connectors · Personalization |
| **Inference** | Overview · OpenAI · Anthropic · Ollama · Tiiny (SDK) |
| **API Reference** | Overview · Authentication · Models & Inference · Hardware · Vault · Connector · Profile · Other · CLI Management |
| **Error Handling** | Debug logs |

Every API Reference page gives you the same operation **twice** — once as a
CLI command and once as a `curl` call — so it works whichever way you
integrate.

### `help.tiiny.ai` — for people using the device day to day

27 published pages, in a different structure entirely:

| Group | Pages |
|---|---|
| **Getting Started** | Set Up Tiiny & First Chat |
| **Device & Settings** | Hardware & Safety · TiinyOS & Account · Network · Storage · Performance · System Update |
| **Core Features** | Chat & Task Mode · Models · Vault & Memory · Agent Apps |
| **Integrations** | Overview · Connect Agents · Connectors · MCP · API Access |
| **Security & Privacy** | Your Data · Permissions |
| **Support** | Troubleshooting · Contact Us · Creator Earnings |
| **What's New** | Updates |
| **TiinyVerse Legal & Policies** | Terms of Service · Privacy Policy · Community Guidelines · Account Deletion Notice · Cookie Policy |

**Two things worth knowing here.** The *Updates* page is a running changelog
with direct download links for each TiinyOS build — it currently lists
**TiinyOS 1.0.2 · Service 0.1.36**, released 2026-10-27. And the legal pages
are the **actual published terms you agreed to** (TiinyVerse Terms of Service,
Privacy Policy, Community Guidelines, Account Deletion Notice, Cookie Policy) —
readable in full, which is more than most vendors offer.

The *Your Data* page is also unusually concrete: a table of every data type
(device password, prompts, uploaded files, memories, model files, inference
cache, exported backup), where it is stored, what triggers a network call, who
the recipient is, and whether the user initiated it.

### How to read both sites without a browser

They are single-page apps. There is no `sitemap.xml` and no search index
file — but the content is all there in two JavaScript files:

```bash
# The navigation tree, with a status field per page
curl -s https://dev.tiiny.ai/docs-manifest.js

# All page content as markdown
curl -s https://dev.tiiny.ai/docs-data.js
```

The manifest is a JSON object with `groups[].pages[]`, and each page has a
`route`, `title`, `file`, and `status`. **Pages with `status: "draft"` are
not published** — their content is absent from `docs-data.js` and they are
not fetchable directly.

> **A trap worth knowing:** if you script a link audit against these sites,
> it will report ~19 broken links that are all fine. The app rewrites them at
> runtime through a routing table in `app.js` — old-style short slugs
> (`./reference/vault`) and group-prefixed relative links (`./openai` →
> `inference-openai`) both resolve. Resolve links the way the app does
> (`routeForPath()` in `app.js`), not by string-matching.

---

## 3. Surfaces 1–4 — the live API reference on your device

Your device serves its own API documentation, and it is the most accurate
version available because it is generated from the code that is actually
running.

### The management API — `/docs`

36 operations under `/api/v1`, in five groups:

- **Account** — `auth`, `bind_email`, `change_mail`, `change_password`,
  `check_mail_code`, `login_with_mail_code`, `reset_password`, `send_mail_code`,
  `set_main_password`, `upload_feedback`, …
- **Apps** — `GET /api/v1/apps` (the Agent Store catalog) and `GET /api/v1/apps/icons`
- **Chat history** — `GET /api/v1/chat/history/`, `GET .../sessions`, `DELETE .../{session_id}`
- **System** — `ac_power`, `base_urls`, `device_info`, `performance`, `reboot`,
  `setting`, `shutdown`, `status`, `storage`, `storage/agent`, `storage/llm`
- **Web apps** — `GET /api/v1/webapp/`, `/running`, `POST /start`, `POST /stop`

### The knowledge-base service — `/kb/docs`

The KB service is the least documented and most capable thing on the device.
50 paths, 59 operations, in eight groups:

| Group | What it does |
|---|---|
| **System** | `GET /kb/health` — service status, degraded reasons, slot state |
| **Dialogue Ingestion** | `POST /kb/add`, `/add-batch`, `/add/stream` — turn a conversation into memories |
| **Finalization** | `POST /kb/finalize`, `/finalize/stream` — generate embeddings for a source |
| **Conversation Queue** | `GET /kb/conversation_days`, `GET/DELETE /kb/conversation_days/{day}`, `POST .../retry` |
| **Query & Retrieval** | `GET/POST /kb/query`, `/query/stream`, `GET/POST /kb/retrieve`, `POST /kb/context` |
| **File Sources** | `GET /kb/sources`, `/sources/files`, `/sources/conversations`, `PATCH /kb/sources/{id}`, `GET /kb/files/{source_id}` |
| **User Context** | `GET/PUT /kb/user-context`, `/user-context/profile`, `/user-context/versions`, `/versions/{id}/restore` |
| **Administration** | `GET/POST /kb/memory/facts`, `DELETE/PATCH /kb/memory/facts/{id}`, `GET/POST /kb/memory/proposals` + approve/reject, `/kb/memory/model`, `/kb/memory/schedule`, `/kb/memory/scope` |
| **Backup** | `GET /v1/backup`, `/v1/backup/inspect`, `POST /v1/restore`, `/v1/restore/inspect` |

A few of these are worth calling out because they are not in any official guide:

- **`GET /kb/files/{source_id}`** returns the **original file**, byte for byte —
  not a chunk or a summary. Pull the 19.6 MB user guide PDF down this way.
- **`GET /kb/memory/facts`** returns typed facts with `confidence`, `status`,
  `evidence`, and `qualifiers` — a structured layer above the raw memories.
- **`GET /kb/memory/proposals`** is a **human approval queue**: writes can be
  gated for approval instead of landing immediately.
- **`GET /kb/user-context/versions`** is versioned, restorable user context.
- **`POST /kb/model/chat/completions`** is a byte-level passthrough to the
  device's internal title model. The spec is explicit that it is **not** a
  general-purpose model proxy.

### One endpoint group is declared but not mounted

`/v1/backup` and `/v1/restore` appear in the spec and **404 at every URL you
try** — with a `/kb` prefix, without one, as GET and as POST. They collide
with the inference namespace. Do not plan on them; the Backup & Restore
feature is still in draft on the docs site (§6).

### The `/v1/*` inference surface is in neither spec

The OpenAI-compatible endpoints — `/v1/chat/completions`, `/v1/embeddings`,
`/v1/images/generations`, `/v1/audio/transcriptions`, `/v1/audio/speech` —
**do not appear in either `openapi.json`**, even though they are the bulk of
what most people use. They are covered only in `dev.tiiny.ai/#inference-openai`.

---

## 4. Documentation you did not have to install

Some of the most useful reference material is *already on the device*, waiting
to be read.

### The user guide ships preloaded

The knowledge base contains a **preloaded copy of the entire user guide** as
48 memory entries. On the device measured, those entries reassemble into
about **46 KB of markdown covering all 11 chapters**:

1. Hardware, Power, and Safe Use
2. Getting Started
3. Using and Managing Models
4. **Vault and Knowledge Base**
5. Chat
6. Agent Apps
7. Dashboard and Usage Statistics
8. Settings and Device Management
9. **SDK and API Integration** ← the pointer to `dev.tiiny.ai`
10. Data Privacy and Security
11. Troubleshooting

You can read it in full without downloading anything:

```bash
tiiny vault query "Tiiny" -t 0.2     # chunked retrieval
```

Or pull the whole thing as text:

```bash
curl -s "http://<device-ip>/kb/memories?limit=500" \
  -H "Authorization: Bearer $TIINY_API_KEY"
```

Chapter 4 covers the Vault end to end — supported file types
(`.doc .docx .txt .csv .xlsx .pdf .html .md`), the 20 MB per-file limit, and
the upload → chunk → vectorize → retrieve pipeline. Chapter 9 is where
`dev.tiiny.ai` is named. Chapter 10 is the data-privacy table.

### The model catalog carries a description per model

`GET /api/v1/models/` returns 29 entries, and each one has a `desc` field
containing a full prose description of the model, plus `capabilities`,
`input`, `output`, `params`, `npu_usage`, and a `thinking` object that tells
you whether reasoning mode is supported and whether it is on by default:

```json
"thinking": {
  "supported": true,
  "toggleable": true,
  "enabled_by_default": true
}
```

This is a model card for every model in the store, served from your own
device — useful for choosing a model without leaving your LAN.

Note the trailing slash on `/api/v1/models/`. Without it the device
answers `301 Moved Permanently`, and `curl` will not follow the redirect
unless you add `-L`.

### The Agent Store catalog ships with full descriptions

`GET /api/v1/apps` returns the catalog of installable agents, each with a
`app_desc` explaining what it does, its categories, tags, platform, version
and download URL. On the device measured, the catalog listed 13 agents — only
7 of which were actually installed as running containers. The other 6 were
available but not present.

---

## 5. The CLI is documentation too

Every command documents itself. The top-level `tiiny --help` groups the
commands by purpose — Authentication, Model Management, Inference, Knowledge
Base, Hardware, Connectors — and every subcommand has its own `--help` with
flags and defaults. `tiiny __complete ""` enumerates the complete command
list, which is the reliable way to see everything the CLI can do.

**The CLI groups commands by domain**, so `tiiny vault --help` will show you
the full file-management surface (add, download, index, ls, query, rename, rm,
summary-config) even if you did not know the word "vault" for it.

### Where the CLI and the docs disagree — read this before you copy a command

The vendor docs at `dev.tiiny.ai` show the knowledge-base commands as
**`tiiny kb`**:

```bash
tiiny kb ls          # ← what the docs say
```

**The shipped CLI has no `kb` subcommand.** You will get
`unknown command "kb" for "tiiny"`. The command is:

```bash
tiiny vault ls       # ← what actually works
```

The docs also show `tiiny backup` and `tiiny restore`, which **do not exist
yet** in the shipped CLI. Those belong to the Backup & Restore feature, whose
two documentation pages are still unpublished drafts (§6). The docs are
describing the CLI as it will be; your binary is the CLI as it is.

**Rule of thumb: run `tiiny <command> --help` and trust that over any
screenshot of the docs.** This gap will close when Backup & Restore ships.

---

## 6. What is published, and what is still a draft

Two documentation pages on `dev.tiiny.ai` are marked `status: "draft"` in the
site's own manifest:

- **Backup & Restore** (Concepts)
- **Backup & Restore** (API Reference)

Draft pages are excluded from the published content bundle and are not
directly fetchable. They are visible only as navigation entries and as the
`tiiny backup` / `tiiny restore` rows on the API Reference overview — which
are, as noted, themselves links to commands that don't exist yet.

So: if you find yourself reading about a backup feature that you cannot run,
you are reading the future. That is expected, not a broken install.

---

## 7. Telling shipped documentation apart from your own data

This is the part that trips people up, so here is the reliable method.

### The three-layer knowledge base

Your device's knowledge base holds three distinct layers. Only the first is
factory content.

| Layer | What it is | Shipped? |
|---|---|---|
| **Preloaded guide** | The user guide, as ~48 memory entries | ✅ **Yes — on every device** |
| **Your uploaded files** | Whatever you put in the Vault | ❌ Your data |
| **Your conversation history** | Nightly summaries of your chats with the device | ❌ Your data |

### How to tell them apart, precisely

The separation is visible in the API response, not guesswork:

- **Preloaded entries** have an `entry_id` of the form
  `preload-tiiny-user-guide#entry-N`, a **`null` timestamp**, a `topic` of
  `document_chunk`, and no `Source file:` prefix in their text.
- **Your entries** have a **UUID** `entry_id`, a **real timestamp**, and their
  text begins with `Source file: `.

So this filter separates them exactly:

```bash
curl -s "http://<device-ip>/kb/memories?limit=500" \
  -H "Authorization: Bearer $TIINY_API_KEY" \
| python3 -c "
import json,sys
items=json.load(sys.stdin)['items']
pre=[i for i in items if i['entry_id'].startswith('preload-')]
own=[i for i in items if not i['entry_id'].startswith('preload-')]
print(f'shipped guide entries: {len(pre)}')
print(f'your own entries:       {len(own)}')
print('your source files:')
import collections
c=collections.Counter()
for i in own:
    t=i['lossless_restatement']
    if 'Source file:' in t: c[t.split('Source file:')[1].split(chr(10))[0].strip()]+=1
for k,v in c.most_common(): print(f'   {v:4}  {k}')
"
```

On the device measured, this returned **48 shipped guide entries** and **195
personal entries** — the 195 tracing back to 12 dated conversation files, plus
three uploaded files.

**A useful sanity check for a brand-new device:** the personal layer should be
**empty**. If a device already has conversation days or uploaded files, either
it has been used, or someone else's data is on it. On a device you just
unboxed, `GET /kb/sources/files` should return no files, and
`GET /kb/sources/conversations` should be empty too.

### The honest version of the number

It is easy to see a knowledge base with 243 memories and 56 typed facts and
conclude the device is richly documented out of the box. **It is not.** On
the device measured, the breakdown was:

| | Count | Whose? |
|---|---|---|
| Preloaded guide entries | 48 | Tiiny's |
| Personal memory entries | 195 | the owner's |
| Typed facts | 56 | the owner's (distilled from their conversations) |
| Conversation days | 12 | the owner's |
| Uploaded files | 3 | the owner's |

The 56 "facts" were all derived from the owner's own work — pricing models,
CRM choices, sprint plans. **None of that is Tiiny documentation.** If you
read a device dump and see facts about someone's company, that is their
private data, and you should not treat it as reference material.

---

## 8. Privacy notes worth reading before you upload anything

These come from `help.tiiny.ai/#yourdata` and `#permissions`, plus what the
API itself exposes.

- **Prompts, uploaded files, and images are stored locally by default.** The
  network trigger is Web Search, when you enable it — and then *part of your
  task content* may reach a search engine. If your task contains something
  sensitive, leave Web Search off.
- **Memories are local to the device** and are never sent online.
- **Connectors require internet** and act within the permissions you
  authorize, under the third party's own policies.
- **Some MCP servers need desktop automation or manual verification** and may
  not work when installed on the device rather than on your computer.
- **Do not put API keys or bot tokens in a shared config, a screenshot, or a
  support report** — the help site says this twice, in the API Access page
  and the Permissions page.

### One practical warning about the knowledge base

The knowledge base is a **retrieval** system. Anything you upload becomes
retrievable text that can be echoed back in an answer. **Do not upload a file
containing secrets** — a credentials file, a `.env`, a key ring export.

On the device measured, a credentials file *had* been uploaded. It was
retrievable three different ways: the original file download endpoint, the
semantic query endpoint (which returned the raw token inside its `answer`
field), and the CLI's own vault query. If you want to remove it:

```bash
tiiny vault ls                       # find the exact filename first
tiiny vault rm "CREDENTIALS.md" -y   # removes it from the device index only
```

This is a delete in your store, so check the file is what you think it is
before running it.

---

### If you want it gone: deleting a captured day

The knowledge base keeps captured chats as **one "conversation day" per
date**. You can list them and delete whole days over the API.

*(This recipe is from Zolon, a Tiiny co-creator, on Discord — verified
against the device on 2026-10-27.)*

```bash
# list the days
curl -H "Authorization: Bearer YOUR_KEY" \
  "http://<device-ip>/kb/conversation_days?limit=500"

# delete one day
curl -X DELETE -H "Authorization: Bearer YOUR_KEY" \
  "http://<device-ip>/kb/conversation_days/2026-10-26"
```

Windows PowerShell:

```powershell
Invoke-RestMethod -Method Delete -Headers @{Authorization="Bearer YOUR_KEY"} \
  "http://<device-ip>/kb/conversation_days/2026-10-26"
```

**Five things to know before you run it.**

1. **It deletes the whole day** — including your TiinyOS chats in the vault
   for that day. Those stay in the TiinyOS chat history itself.
2. **There is no way to delete just the API chats.** API turns and TiinyOS
   turns are merged into one day file before the vault sees them, and a day
   is the finest unit the API offers.
3. **Days marked `queued`** have not been summarised yet. Days marked
   `summarized` may already have produced memory facts — though the delete
   response reports `deleted_facts` and `deleted_proposals` counters, which
   suggests those come too.
4. **It cannot be undone.** There is no dry-run and no undo endpoint.
5. **It is not a complete erasure.** Three things survive it — see below.

#### What survives a day delete

| Survives | Why it matters |
|---|---|
| **The raw per-call log** in `/data/backend/tiiny_model_data/mixin` — one file per conversation day | This is where a call is written *before* any summarisation touches it. The delete does not touch this directory. |
| **User-context versions** — the response explicitly reports them as `context_versions_retained` | On a device with 20 versions, those carry derived text from the days you deleted. |
| **An encrypted log on the device** | Reported by Zolon from direct inspection. Not reachable over the HTTP API, so it cannot be checked from outside. |

**A deleted day does not come back** — but only because the importer tracks
records it has already consumed (`skipped_records` sits alongside
`imported_records` in the import counters), not because the source data is
gone.

Zolon's own summary of the concern is the right frame: *"There is an
encrypted log on the device that likely has a mirror of everything that this
does not touch. This is still a great concern for me."*

Whether you can delete an API call's **raw** record — as opposed to the
vault's summarised view of it — is the open question, and it is not
something the device answers from outside.

## 9. A five-minute orientation for a new owner

If you have just unboxed a Tiiny, this is the shortest useful path.

1. **Get the device IP.** `tiiny scan`, or `curl http://<ip>:39218/device.json`.
2. **Open the live API reference in a browser:** `http://<ip>/docs` — no token
   needed. Then `http://<ip>/kb/docs` for the knowledge-base service.
3. **Read the developer docs:** <https://dev.tiiny.ai>. Start at *Quick Start*,
   then *Concepts → Vault*, then *API Reference → Vault*.
4. **Read the user docs:** <https://help.tiiny.ai>. Start at *Set Up Tiiny &
   First Chat*, then *Chat & Task Mode*, then *Your Data*.
5. **Read the guide that is already on the device** — chapter 4 covers the
   Vault, chapter 9 points at the developer docs.
6. **Check the model catalog:** `curl http://<ip>/api/v1/models/ -H "Authorization: Bearer $KEY"`.
   Every model has a description.
7. **Confirm your device is clean:** `GET /kb/sources/files` should be empty on
   a device you just unboxed.

---

## 10. Quick reference

```bash
# Device IP and identity
tiiny scan
curl http://<ip>:39218/device.json

# Live API docs — open in a browser, no token needed
http://<ip>/docs
http://<ip>/redoc
http://<ip>/kb/docs
http://<ip>/kb/redoc

# Raw specs
curl -s http://<ip>/openapi.json | jq '.paths | keys'
curl -s http://<ip>/kb/openapi.json | jq '.paths | keys'

# Cloud documentation
https://dev.tiiny.ai      # 24 pages — SDK & API reference
https://help.tiiny.ai     # 27 pages — user guide, troubleshooting, legal

# Enumerate a cloud doc site without a browser
curl -s https://dev.tiiny.ai/docs-manifest.js    # nav tree + publish status
curl -s https://dev.tiiny.ai/docs-data.js        # all page content

# Read the guide already on your device
tiiny vault query "Tiiny" -t 0.2
curl -s "http://<ip>/kb/memories?limit=500" -H "Authorization: Bearer $KEY"

# Model catalog with full descriptions (trailing slash required)
curl -s http://<ip>/api/v1/models/ -H "Authorization: Bearer $KEY"

# Agent Store catalog
curl -s http://<ip>/api/v1/apps -H "Authorization: Bearer $KEY"

# Is this knowledge base mine or Tiiny's?
#   preload-* entry_id + null timestamp  -> shipped guide
#   UUID entry_id + real timestamp      -> yours
```

---

## 11. Known gaps and rough edges

Honest list, so you don't lose an afternoon to any of them.

| Gap | What you will see |
|---|---|
| **Docs say `tiiny kb`, CLI has `tiiny vault`** | `unknown command "kb"`. Use `tiiny vault`. |
| **`tiiny backup` / `tiiny restore` documented but absent** | `unknown command`. The feature is in draft. |
| **`/v1/backup` and `/v1/restore` are declared but unmounted** | 404 at every URL. |
| **The `/v1/*` inference endpoints are in no spec** | Check `dev.tiiny.ai/#inference-openai` instead. |
| **Two doc pages are unpublished drafts** | Visible in the nav, absent from the content. |
| **Link audits report false breakage on the doc sites** | Resolve via `routeForPath()` in `app.js`. |
| **File size limit is stated two ways** | The user guide says **20 MB** per file; the dev docs say the CLI rejects files over **200 MB**. The guide is the conservative number — use 20 MB. |
| **The KB spec changes** | It grew from 46 paths / 54 operations to 50 / 59 in one day. Re-count it; do not trust a number from any doc, including this one. |
| **The nightly summary pipeline can fail silently** | `GET /kb/memory/schedule` reports `last_outcome`. If summaries stop appearing, check it — a missing model is the usual cause. |
| **`tiiny load` / `tiiny unload` need a real terminal** | From a script or agent they fail with a TTY error. Run them in a terminal. |
| **API calls are captured but not viewable** | Your calls land in the knowledge base as a conversation day. There is no interface that shows them individually — only `/kb/conversation_days/{day}` for the summarised day, and a delete for the whole day. See §8. |
| **The KB service is barely documented** | 50 paths and 59 operations, and the surface that matters most — the `/kb/*` service — is in neither the device's own docs nor `dev.tiiny.ai`. It is discoverable, but only if you already know to look. |
| **A deleted day does not delete the raw call** | The delete clears the vault's summarised view. The per-day raw log, the retained user-context versions, and an encrypted device log all survive. See §8. |

---

## Where this came from

Enumerated and verified on a Tiiny z01 (TiinyOS 1.0.2 / service 0.1.36,
device ID `TNYM…redacted`) on 2026-10-27. Every URL in this document
was fetched and every count was taken from the site's own manifest or the
device's own API response — not from a previous document. Where the vendor's
own documentation contradicts itself, both versions are given above.

## Related

- [`api-call-logging.md`](./api-call-logging.md) — where an API call
  actually goes, why it is not visible in any interface, and what a delete does
  and does not reach

---

Corrections and additions welcome — open an issue on this repository, or post
them in the Discord channel. Either way they will fold into the next
revision.  -@Antattack and Friendlybot
