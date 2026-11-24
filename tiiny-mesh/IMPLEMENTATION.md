# TiinyMesh — Implementation Guide

This guide details the implementation of TiinyMesh: module structure, configuration schema, testing commands, and deployment steps.

Standard library only. Python 3.8+.

---

## 1. Directory Structure

```
tiiny-mesh/
├── gateway.py               # Main HTTP gateway server and route dispatcher
├── mesh.py                  # Mesh data models, target lifecycle, and borrow transactions
├── capabilities.py          # Model capability classification & embedding dimensions
├── openrouter.py            # OpenRouter credits client & key usage fallback
├── minimax_quota.py         # MiniMax token plan quota client (5h rolling & weekly)
├── mesh_amc.py              # AMC host-side health witness (Engraphis, Obsidian, iDrive)
├── activity.py              # Live device activity sampler (compute load, reservations, history)
├── find.py                  # Specialty-model discovery & placement engine (read-only)
├── mdrender.py              # Dependency-free Markdown to HTML parser
├── meshclient.py            # Test and client request helper
├── config.example.json      # Documented example configuration
├── ui/
│   ├── index.html           # Compiled single-file Control Panel dashboard
│   ├── mesh-dashboard.css   # Dashboard stylesheet source
│   ├── mesh-dashboard.js    # Dashboard UI script source
│   └── inline.py            # Build script that inlines CSS/JS into index.html
├── test_minimax_quota.py    # MiniMax quota client offline test suite
├── test_failover.py         # Transparent 429 failover test suite
├── test_openrouter.py       # OpenRouter target & catalogue resolution test
├── test_openrouter_credits.py # Credits client & caching offline test
├── test_amc.py              # AMC health probe offline test
├── test_activity.py         # Activity monitor offline test (states, history, busy streaks)
├── test_find.py             # Model finder & placement offline test (scoring, budgets, eviction)
├── test_mdrender.py         # Markdown renderer & XSS escaping test
├── selftest.py              # Live estate validation script
└── test_routes.py           # Comprehensive gateway route test
```

---

## 2. Configuration (`config.json`)

TiinyMesh reads its configuration from `~/.hermes/mesh/config.json` (or the path set in `TIINY_MESH_CONFIG`).

```json
{
  "defaults": {
    "embedding": "ollama/bge-m3:latest",
    "tts": "ogad",
    "asr": "ogad",
    "image_gen": "tiiny-octo",
    "chat": "tiiny-ant/Qwen/Qwen3.6-35B-A3B"
  },
  "policy": {
    "chat": {
      "primary": "tiiny-ant/Qwen/Qwen3.6-35B-A3B",
      "secondary": "openrouter/google/gemini-3.8-flash"
    },
    "embedding": {
      "primary": "ollama/bge-m3:latest",
      "secondary": "tiiny-ant/Qwen/Qwen3-Embedding-0.6B"
    },
    "asr": {
      "primary": "ogad",
      "secondary": "tiiny-ant/Qwen/Qwen3-ASR-1.7B"
    },
    "image_gen": {
      "primary": "tiiny-octo",
      "secondary": "tiiny-octo/Tongyi-MAI/Z-Image-Turbo"
    },
    "tts": {
      "primary": "ogad"
    }
  },
  "targets": {
    "tiiny-ant": {
      "kind": "tiiny",
      "admin_url": "http://192.0.2.10",
      "base_url": "http://192.0.2.10/v1",
      "key_env": "TIINY_API_KEY",
      "priority": 10,
      "keep_resident": ["Qwen/Qwen3.6-35B-A3B"],
      "capabilities": ["chat", "vision", "embedding", "rerank", "asr", "tts", "image_gen"],
      "note": "Primary appliance (256K context vault generalist)"
    },
    "tiiny-octo": {
      "kind": "tiiny",
      "admin_url": "http://192.0.2.11",
      "base_url": "http://192.0.2.11/v1",
      "key_env": "TIINY_API_KEY_2",
      "priority": 11,
      "capabilities": ["chat", "vision", "embedding", "rerank", "asr", "tts", "image_gen"],
      "note": "Flex appliance for on-demand specialists"
    },
    "ollama": {
      "kind": "openai",
      "base_url": "http://127.0.0.1:11434/v1",
      "priority": 30,
      "capabilities": ["chat", "embedding"],
      "note": "Local embedding tier — bge-m3 (1024 dimensions)"
    },
    "minimax": {
      "kind": "openai",
      "base_url": "https://api.minimax.io/v1",
      "key_env": "MINIMAX_API_KEY",
      "models": ["MiniMax-M3", "MiniMax-M3.1-Flash"],
      "priority": 60,
      "capabilities": ["chat", "reasoning"],
      "note": "Cloud target B"
    },
    "openrouter": {
      "kind": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "key_env": "OPENROUTER_API_KEY",
      "models": [],
      "priority": 70,
      "capabilities": ["chat"],
      "note": "Cloud target A (dynamic catalogue)"
    }
  }
}
```

---

## 3. Core Modules

### 3.1 Gateway Server (`gateway.py`)
Implements Python's `ThreadingHTTPServer`. Dispatches requests to the appropriate target, proxies streaming chat completions, handles model borrow lifecycle, and exposes management endpoints.

Key features:
- **Loopback Public Reads:** Informational endpoints (`/ui`, `/mesh/ui`, `/mesh/amc`, `/mesh/readme`, `/mesh/fallback`, `/mesh/openrouter/credits`) do not require bearer tokens, allowing browsers to render the dashboard seamlessly.
- **State Writes:** All state-modifying requests (`POST /mesh/policy`, `POST /mesh/lifecycle`, `POST /mesh/fallback`) enforce bearer token validation.
- **Background Daemon Workers:**
  - `_restore_worker()`: Ensures required models are loaded on reboot if configured.
  - `_credits_worker()`: Periodically refreshes cached OpenRouter credit balances every 24 hours.

### 3.2 Dynamic Borrow & Lifecycle (`mesh.py`)
Implements `Target` and `Mesh` dataclasses. Manages model resolution and on-demand borrowing:

```python
def borrow(self, target: Target, model: str) -> dict:
    if target.kind != "tiiny":
        return {"needed": False, "was_resident": [], "ok": True}
    state = catalogue(target)
    running = [r["model_id"] for r in state["models"] if r.get("status") == "running"]
    if model in running:
        return {"needed": False, "was_resident": running, "ok": True}
    
    # Load requested specialist over appliance HTTP API
    r = self.lifecycle(target.id, model, "start")
    return {"needed": True, "was_resident": running, "ok": r.get("ok"), "status": r.get("status")}

def unborrow(self, target: Target, model: str, was_resident: list[str]) -> list[dict]:
    if target.kind != "tiiny":
        return []
    # Stop temporary specialist and restore prior incumbents
    self.lifecycle(target.id, model, "stop")
    for lost in was_resident:
        self.lifecycle(target.id, lost, "start")
```

### 3.3 OpenRouter Credits Client (`openrouter.py`)
Performs credit balance and limit monitoring with atomic file caching:
- Attempts `GET https://openrouter.ai/api/v1/credits` with `OPENROUTER_MANAGEMENT_KEY` to compute `balance = total_credits - total_usage`.
- If a management key is missing or returns `403 Forbidden`, falls back to `GET https://openrouter.ai/api/v1/key` using `OPENROUTER_API_KEY` to report `limit_remaining` and `usage`.
- Utilizes `mesh._ssl_context()` to guarantee certificate chain resolution across macOS Python runtimes.

### 3.4 MiniMax Quota Monitoring & Transparent Failover (`minimax_quota.py` & `mesh.py`)
- **Quota Client:** Queries `GET https://api.minimax.io/v1/token_plan/remains` every 5 minutes to track 5-hour rolling and weekly remaining quota percentages and reset countdowns.
- **Auto-Switch:** Automatically flips the secondary fallback to OpenRouter when weekly quota hits 0% (status 2), and automatically re-engages MiniMax when the reset window elapses.
- **Transparent 429 Failover:** `Mesh.chat()` catches upstream HTTP 429 rate-limit responses, intercepts the error, and immediately re-executes the completion through the secondary cloud fallback target (`openrouter/google/gemini-3.8-flash`) without surfacing an error to the caller.

### 3.5 AMC Health Witnessing (`mesh_amc.py`)
Queries host-side memory subsystems and outputs status:
- **Engraphis:** Checks `engraphis.db` and WAL mtime. Returns `up` if written within 24h, `degraded` if older, or `down` if missing.
- **Obsidian:** Verifies the `Obsidian` application process and runs a bounded scan (up to 20,000 files / 3.0s ceiling) for the latest note mtime.
- **iDrive:** Checks volume mount points and `os.statvfs` capacity. Returns `not-configured` when unmounted.

### 3.6 Markdown Renderer (`mdrender.py`)
Transforms Markdown into clean HTML with zero dependencies. Escapes `<script>`, `&`, `<`, and `>` tags to prevent XSS while parsing headings, code blocks, lists, and tables into responsive HTML for `/mesh/readme`.

### 3.7 Activity Monitor (`activity.py`)
Samples each appliance's own `/api/v1/npu/status` on an interval and keeps a rolling history, so the gateway can say whether a box is **idle**, **busy**, or **offline** rather than reporting only what is resident.
- **Two numbers, deliberately separate.** NPU *memory* is how much of the pool the resident models have allocated; NPU *load* is how much the silicon is computing right now. A box with a 47% model loaded and nothing running reads 47% and is idle.
- **Busy detection.** `busy` when a request is in flight **or** utilisation is above 10%. The device reports 0.0% while idle and 75-97% during a generation, so the threshold sits in the wide empty middle.
- **Reservations attributed.** A hold says who *claimed* the box; the device says whether it is *actually working*. Both are reported, because a hold can be stale — written by an agent that has since died — and a busy box with no reservation is exactly the case worth seeing.
- **Busy streaks.** `busy_since` walks backward through the current contiguous busy streak, so it reports when the box *started* being busy, not when the newest sample arrived.

### 3.8 Model Finder (`find.py`)
Answers "which model can do this job, and what would it cost to run it?" by searching the **complete** store catalogue — not just the resident models an OpenAI-compatible `/v1/models` route lists.
- **Score and placement are separate outputs.** The score says how well a model fits the words of the request, matched against the device's own type, capabilities, description, tags, and recommendation rank. The placement says what it would cost to run it on each box.
- **Exact type matching.** Capability types are compared exactly, not by substring: `Image-Text-to-Text` is a vision-chat model and is not a `Text-to-Image` generator.
- **Two independent constraints.** NPU headroom and disk capacity are separate limits. A model can fit in NPU but have nowhere to live on disk, or fit on disk but require evicting a resident model.
- **The NPU budget is 95, not 100.** A co-resident set must sum to 95 or less, because residency carries runtime and KV-cache overhead that the declared NPU share does not show.
- **Eviction candidates are resident models only.** Stopping a merely *downloaded* model frees no NPU share, so only `running` models can be evicted, and the smallest non-generalist is preferred so the fallback stays resident as long as possible.
- **Read-only by construction.** The finder discovers and prices; it never downloads, stops, or makes a model resident.

---

## 4. Testing Suite

The implementation includes nine self-contained test suites:

```bash
# Test MiniMax token plan quota client and caching (offline fixtures)
python3 test_minimax_quota.py

# Test transparent in-flight HTTP 429 failover to secondary cloud target
python3 test_failover.py

# Test OpenRouter target configuration and model namespacing
python3 test_openrouter.py

# Test OpenRouter credits calculation and cache TTL (offline fixtures)
python3 test_openrouter_credits.py

# Test AMC health probes across mock directories
python3 test_amc.py

# Test activity sampling: states, reservations, history, busy streaks
python3 test_activity.py

# Test model discovery and placement: scoring, NPU budget, disk, eviction
python3 test_find.py

# Test Markdown parser and XSS escaping
python3 test_mdrender.py

# Run end-to-end estate selftest against live hardware & cloud targets
python3 selftest.py

# Run gateway route verification (chat, embeddings, TTS, image generation)
python3 test_routes.py
```

---

## 5. Operations & UI Compilation

### Building the Single-File Dashboard
When editing `ui/mesh-dashboard.css` or `ui/mesh-dashboard.js`, regenerate `ui/index.html`:

```bash
python3 ui/inline.py
```

### In-Flight Fallback Toggling via API
To switch the mesh's secondary chat fallback and Hermes's delegation fallback:

```bash
# Switch to OpenRouter Gemini 3.8 Flash
curl -s -X POST http://127.0.0.1:8767/mesh/fallback \
  -H "Authorization: Bearer $(cat ~/.hermes/mesh/gateway_key)" \
  -H "Content-Type: application/json" \
  -d '{"target":"openrouter"}'

# Switch to MiniMax M3.1 Flash
curl -s -X POST http://127.0.0.1:8767/mesh/fallback \
  -H "Authorization: Bearer $(cat ~/.hermes/mesh/gateway_key)" \
  -H "Content-Type: application/json" \
  -d '{"target":"minimax"}'
```
