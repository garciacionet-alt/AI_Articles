# TiinyMesh: Multi-Target Inference Gateway & Control Panel

**One OpenAI-compatible endpoint across local appliances, Mac-side servers, and cloud providers.**

TiinyMesh aggregates multiple Tiiny hardware appliances (e.g. TinyAnt and TiinyOcto), local inference servers (OffGrid AI Desktop, Ollama, LM Studio), and cloud platforms (OpenRouter, MiniMax) behind a single local URL (`http://127.0.0.1:8767/v1`). It provides dynamic model discovery, capability-based routing, automated model borrowing, host-side Agent Memory Commons (AMC) health monitoring, and an in-flight cloud fallback toggle.

Standard library only. Python 3.8+.

---

## Companion to Tiiny Model Routing

TiinyMesh is the architecture and gateway companion to **[Tiiny Model Routing](../tiiny-model-routing/README.md)**:

- **The Model Router** (`tiiny-model-routing`) is a client-side delegation plugin for Hermes Agent. It analyzes a subagent's task shape and routes it to the optimal model tier (code, research, index, browser, general) while controlling thinking trace depth.
- **TiinyMesh** is the server-side gateway that sits between the agent and the hardware. It allows the model router—which is single-URL by design—to address an entire fleet of appliances, local servers, and cloud fallbacks without hardcoding device IP addresses or juggling device tokens.
- **Two Boxes** (`tiiny-two-boxes`) addresses hardware provisioning and NPU co-residency budgets; TiinyMesh provides the runtime traffic manager and visual control plane that drives them together.

---

## What It Does

| Capability | Mechanism |
|---|---|
| **Unified `/v1` Endpoint** | Standard OpenAI `/v1/chat/completions`, `/v1/embeddings`, `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/images/generations` routes. Any OpenAI-compatible client can connect. |
| **Model Namespacing & Priority** | Models are addressed as `target/model` (e.g. `tiiny-ant/Qwen/Qwen3.6-35B-A3B`) or as bare model IDs resolved by priority ranking. |
| **Capability Routing** | Omit the model name and requests route to configured defaults (e.g. embeddings to Ollama 1024-dim `bge-m3`, TTS to local speech, image gen to local DiT). |
| **Automated Model Borrowing** | A Tiiny appliance serves only what is resident. When a request asks for a downloaded model, TiinyMesh snapshots current residency, loads the specialist, serves the request, and restores the prior state. |
| **OpenRouter Target & Credits** | Exposes OpenRouter models (`openrouter/<slug>`). Polls account credit balances (`/api/v1/credits` via management key) with automatic fallback to per-key cap/usage monitoring (`/api/v1/key`). |
| **AMC Health Witnessing** | Probes host-side Agent Memory Commons subsystems (Engraphis SQLite memory, Obsidian vault indexing, and iDrive sandbox storage) without consuming appliance NPU cycles. |
| **MiniMax Quota & Auto-Switch** | Polls MiniMax Token Plan quota (`/v1/token_plan/remains` 5h & weekly windows). Proactively auto-switches to OpenRouter when quota is exhausted (<10%), and auto-recovers when the reset timer elapses. |
| **Transparent 429 Failover** | Intercepts HTTP 429 rate-limit errors in `mesh.py` and transparently retries completions through the cloud secondary (OpenRouter Gemini) without failing client requests. |
| **In-Flight Cloud Fallback Toggle** | Switch the gateway's secondary chat fallback and Hermes agent's delegation fallback between MiniMax (M3.1 Flash) and OpenRouter (Gemini 3.8 Flash) with a single click. |
| **Live Activity Telemetry** | Samples each appliance's own NPU status and reports idle / busy / offline, live compute load, active request count, and the reservation holding the box — kept separate from the NPU *memory* meter, which says what is resident rather than what is computing. |
| **Disk Capacity Awareness** | Reads the appliance's own storage breakdown to report total, used, and remaining bytes per target, plus the model-store and agent-app share. Disk is the second half of the capacity constraint, after NPU headroom, and it is often the binding one. |
| **Model Discovery & Placement** | `GET /mesh/find?q=` searches the complete store catalogue, scores models against the words of a request, then prices each placement — ready, load, un-reside (naming the model that must go), or download — with NPU headroom and disk free per target. |
| **Single-File Control Panel** | Responsive dark/light dashboard at `/ui` with zero external JS/CSS dependencies. Built from source via `python3 ui/inline.py`. |
| **Rendered Documentation** | `/mesh/readme` serves the project documentation parsed into styled HTML using an internal standard-library Markdown renderer. |

---

## Source

The gateway ships with this family, so a reader can clone the repository and
run it rather than re-implement it from the prose. The source tree is
[`src/`](./src/):

```
tiiny-mesh/src/
├── gateway.py               # HTTP gateway server and route dispatcher
├── mesh.py                  # data models, target lifecycle, borrow transactions
├── activity.py              # live device activity sampler (load, reservations)
├── find.py                  # specialty-model discovery and placement engine
├── capabilities.py          # capability classification & embedding dimensions
├── devices.py               # per-device registry
├── mesh_amc.py              # AMC host-side health witness
├── mesh_watchdog.py         # reservation watchdog
├── mdrender.py              # dependency-free Markdown to HTML parser
├── meshclient.py            # client request helper
├── minimax_quota.py         # MiniMax token plan quota client
├── openrouter.py            # OpenRouter credits client
├── selftest.py              # live estate validation (needs a live mesh)
├── config.example.json      # documented example configuration
├── ui/                      # the control panel: compiled page plus sources
└── test_*.py                # the suites that run standalone
```

**The published copy is redacted.** The source tree keeps the real appliance
addresses and device serials — the running gateway needs them — and the
publish build rewrites the published bytes: private LAN addresses become the
documentation ranges (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`), device
serials become `TNYM…redacted`, and the personal name becomes *the author*.
**No key value is in the source at all**: the code asks for the **name** of an
environment variable and reads the credential from there, so publishing the
source publishes no secret.

**The suites run without the estate.** Every `test_*.py` here passes with no
appliance, no live gateway, and no key file:

```bash
cd tiiny-mesh/src
python3 test_find.py
python3 test_activity.py
```

`selftest.py` validates a live estate and needs the mesh running, so it is
shipped for reference rather than as a standalone check.

---

## Quick Start

```bash
cp config.example.json config.json
# Edit config.json with your local target endpoints and key environment variable names
export TIINY_MESH_CONFIG="$PWD/config.json"
python3 gateway.py
```

The gateway starts on `http://127.0.0.1:8767` and generates a bearer token in `~/.hermes/mesh/gateway_key`.

Run test completions:

```bash
# Chat completion via mesh
curl -s http://127.0.0.1:8767/v1/chat/completions \
  -H "Authorization: Bearer $(cat ~/.hermes/mesh/gateway_key)" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3.6-35B-A3B","messages":[{"role":"user","content":"hello"}]}'

# Open Control Panel in browser
open http://127.0.0.1:8767/ui
```

---

## Routes Summary

```
# OpenAI-Compatible API
POST /v1/chat/completions      routed by model id or capability
POST /v1/embeddings            routed by capability, dimension tagged
POST /v1/audio/speech          routed by capability, audio/wav passthrough
POST /v1/audio/transcriptions  multipart, routed by capability
POST /v1/images/generations    routed by capability
GET  /v1/models                chat-routable models across all targets

# Mesh Admin & Monitoring
GET  /mesh/targets             every target, health, latency, model counts
GET  /mesh/catalogue           complete catalog across all capabilities
GET  /mesh/health              health summary
GET  /mesh/npu/<target>        NPU memory headroom and utilization
GET  /mesh/activity           per-target idle/busy/offline, live load, reservations
GET  /mesh/storage            per-target disk capacity (total, used, remaining, breakdown)
GET  /mesh/storage/<target>   one target's disk capacity and breakdown
GET  /mesh/find?q=<terms>     specialty-model discovery and placement pricing
GET  /mesh/status/<target>     system status (CPU/RAM/storage)
GET  /mesh/store/<target>      online model store catalog
GET  /mesh/running/<target>    currently resident models
POST /mesh/lifecycle           appliance model download / start / stop / boot
GET  /mesh/openrouter/credits  OpenRouter credit balance and key limits
GET  /mesh/minimax/quota       MiniMax token plan quota & reset countdown
GET  /mesh/amc                 Agent Memory Commons health matrix
GET  /mesh/fallback            current cloud fallback status
POST /mesh/fallback            toggle fallback between openrouter and minimax
GET  /mesh/readme              styled HTML view of documentation

# Control Panel UI
GET    /ui                     single-file dashboard page
GET    /mesh/ui                aggregated status payload for the UI
GET    /mesh/policy            static routing policy map
POST   /mesh/policy            update primary/secondary routing rules
GET    /ui/background          custom dashboard background image
POST   /ui/background          upload custom background
DELETE /ui/background          remove custom background
```

---

## Deep Dive

- **[PATTERN.md](./PATTERN.md)**: Architectural pattern, local-first economics, NPU co-residency constraints, and failure recovery.
- **[IMPLEMENTATION.md](./IMPLEMENTATION.md)**: File-by-file implementation, code structure, testing suite, and configuration reference.
