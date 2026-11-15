# TiinyMesh — Architecture Pattern

## 1. The Core Problem: The Single-URL Client Bottleneck

Autonomous agent frameworks (such as Hermes Agent, Claude Code, and OpenCode) are designed around client-side model providers: an agent config defines an API base URL, a bearer token, and a default model.

When deploying an estate of local AI appliances (such as multiple Tiiny devices) alongside desktop inference servers (OffGrid AI Desktop, Ollama, LM Studio) and cloud backends (OpenRouter, MiniMax), this single-URL abstraction breaks down:

1. **Device Fragmentation:** Each appliance has its own LAN IP, its own authenticated session, and its own resident model set.
2. **NPU Memory Constraints:** A 48 GiB NPU appliance serves only what is currently loaded. Loading an image or audio model evicts the resident chat model.
3. **Context Ceiling Limits:** Specialized coding models often ship with smaller context windows (e.g. 64K). In deep multi-turn agent loops, prompt growth causes NPU PCIe transfer stalls unless requests can route to high-context generalists (256K).
4. **Fallback Fragility:** If local hardware experiences a hardware timeout or power cycle, agent delegation halts unless a resilient cloud fallback catches the request.

TiinyMesh provides the architectural solution: **a local multiplexing gateway that presents the entire estate as a single, resilient OpenAI-compatible endpoint.**

```
                                  +------------------------------------+
                                  |            Hermes Agent            |
                                  | (Single URL: 127.0.0.1:8767/v1)   |
                                  +-----------------+------------------+
                                                    |
                                                    v
                                  +------------------------------------+
                                  |         TiinyMesh Gateway          |
                                  | - Unified Routing & Capability Map |
                                  | - Automated Model Borrow/Restore   |
                                  | - In-Flight Cloud Fallback Toggle  |
                                  | - AMC Memory & Health Witness      |
                                  +-----------------+------------------+
                                                    |
         +-------------------+----------------------+--------------------+-------------------+
         |                   |                      |                    |                   |
         v                   v                      v                    v                   v
+-----------------+ +-----------------+   +-------------------+  +---------------+   +---------------+
| Tiiny (Ant)     | | Tiiny (Octo)    |   | Mac Local Servers |  |  OpenRouter   |   |    MiniMax    |
| - Pinned Vault  | | - Flex Specialty|   | - Ollama (bge-m3) |  | - Gemini 3.8  |   | - M3.1 Flash  |
| - Qwen3.6-35B   | | - Coder/Images  |   | - OGAD (TTS/ASR)  |  | - Paid Cloud  |   | - Fallback B  |
|   (256K Ctx)    | |   (Dynamic)     |   | - LM Studio       |  |   Fallback A  |   |               |
+-----------------+ +-----------------+   +-------------------+  +---------------+   +---------------+
```

---

## 2. Dynamic Model Borrowing: Transparent Lifecycle

A Tiiny appliance serves only models that are currently loaded into its NPU RAM. If an agent calls an endpoint for an embedding or speech model that is downloaded on disk but not resident, the native device answers `404 Not Found`.

A naive solution is to permanently load every model or use external cron pollers to reload fixed sets. This fails because:
- Combined models exceeding 100% NPU budget cannot coexist.
- External reload pollers frequently interrupt long-running inference tasks mid-stream.

TiinyMesh solves this via **Transactional Model Borrowing**:

1. **Inspect Request:** TiinyMesh checks if the target has the model downloaded.
2. **Snapshot State:** If the model is not running, TiinyMesh captures the list of currently resident models.
3. **Execute Load:** Calls `POST /api/v1/models/<id>/start` on the appliance's admin interface.
4. **Serve Request:** Proxies the inference payload to completion.
5. **Restore State:** Unloads the temporary model and reloads whatever was resident beforehand (`POST /api/v1/models/<id>/stop` followed by `/start` for the evicted incumbents).

To clients, every downloaded model appears permanently online and servable, while NPU residency remains bounded.

---

## 3. Context Ceilings & NPU PCIe HDMA Timeouts

A critical discovery in multi-turn autonomous coding: **Model context ceilings are hard physical constraints on local appliances.**

- `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` has a declared context limit of **65,536 tokens** (64K).
- `Qwen/Qwen3.6-35B-A3B` has a declared context limit of **262,144 tokens** (256K).

In autonomous coding sessions, subagents repeatedly inspect repository trees, run test suites, and read implementation plans. As context accumulates past ~40,000 tokens (over 60% of a 64K model's ceiling), NPU PCIe Direct Memory Access (DMA) transfer times scale non-linearly.

On 64K models, this leads to hardware-level driver timeouts:
```json
{"status": "ready", "reason": {"code": "pcie_hdma_timeout", "message": "The NPU PCIe HDMA transfer timed out."}}
```
The appliance stops generating tokens while holding the TCP socket open indefinitely.

**The Architectural Remedy:**
In the delegation hierarchy (defined in `tiers.py`), repo-scale agentic coding is routed to **256K context generalists** (`Qwen3.6-35B-A3B`) rather than narrow 64K code specialists. The 35B model activates only ~3B parameters per token (MoE), preserves reasoning chains across turns, and easily absorbs 50K+ tokens without memory transfer faults.

---

## 4. Dual-Cloud Fallback Architecture & Live Toggling

Local hardware can become unavailable due to reboot cycles, long batch jobs, or hardware stalls. When Hermes Agent detects an unresponsive upstream endpoint (stale socket for >180s), it initiates an automated fallback.

However, hardcoding a single cloud fallback creates a single point of failure:
- An account token quota may be exhausted (resulting in `HTTP 429 RateLimitError`).
- A cloud provider's API may experience transient outages.

TiinyMesh decouples fallback policy from static configuration by implementing an **In-Flight Cloud Fallback Toggle**:

1. **State Persistence:** The `chat` capability's secondary slot is stored in `config.json` and served over `GET /mesh/fallback`.
2. **Dual-Synchronization:** When `POST /mesh/fallback` is invoked with `target: "openrouter"` or `target: "minimax"`, TiinyMesh:
   - Updates `policy.chat.secondary` in its own gateway configuration.
   - Atomically updates `delegation.fallback_providers` in Hermes Agent's `~/.hermes/config.yaml`.
3. **Visual Control:** An operator can flip cloud fallbacks with one click on the dashboard without restarting services or editing configuration files by hand.

---

## 5. Decoupled Memory & Health Witnessing

The Agent Memory Commons (AMC) consists of three host-side subsystems:
1. **Engraphis:** Semantic memory layer (SQLite database storing durable facts, decisions, and patterns).
2. **Obsidian:** Human-readable indexed memory tree (the Markdown vault).
3. **iDrive:** Replicated sandbox storage filesystem.

An early design consideration was whether to run health checking on the appliances themselves. That would require installing custom daemons on appliance OS images and consuming NPU RAM.

TiinyMesh establishes **Host-Side Witnessing**:
- The gateway runs on the host Mac alongside the memory systems.
- It probes the Engraphis SQLite database mtime, WAL state, and active process state.
- It performs bounded scans of vault note modification timestamps.
- It inspects storage mounts.
- It reports these metrics at `GET /mesh/amc` and embeds them into the main dashboard view.

The local appliances remain 100% dedicated to raw inference throughput, while operators gain total visibility into the health of their persistent memory stack.

---

## 6. Zero-Dependency Control Plane

TiinyMesh adheres strictly to standard-library Python:
- **No Third-Party Frameworks:** Uses Python's built-in `http.server`, `urllib.request`, `threading`, and `json` modules.
- **Inlined Dashboard:** Web assets (`mesh-dashboard.css` and `mesh-dashboard.js`) are compiled directly into `ui/index.html` via `ui/inline.py`. When `/ui` is requested, the server delivers a single, self-contained HTML payload. No static file routes or asset bundles are required.
- **Embedded Documentation:** The `/mesh/readme` endpoint utilizes an internal, dependency-free Markdown parser (`mdrender.py`) with strict HTML escaping, rendering documentation cleanly on any device on the network.
