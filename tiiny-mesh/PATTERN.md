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

## 4. Dual-Cloud Fallback Architecture, Quota Monitoring & Live Toggling

Local hardware can become unavailable due to reboot cycles, long batch jobs, or hardware stalls. When Hermes Agent detects an unresponsive upstream endpoint (stale socket for >180s), it initiates an automated fallback.

However, hardcoding a single cloud fallback creates a single point of failure:
- An account token quota may be exhausted (resulting in `HTTP 429 RateLimitError`).
- A cloud provider's API may experience transient outages.

Many operators hold an annual flat-rate subscription (such as MiniMax Token Plan) alongside pay-as-you-go providers (such as OpenRouter). The ideal economic strategy is: **consume flat-rate subscription tokens first, and only spend variable cloud tokens when the subscription hits its quota or rate limit.**

TiinyMesh automates this strategy through three interlocking mechanisms:

### 4.1 Proactive Token Plan Monitoring
MiniMax exposes account quota data via `GET https://api.minimax.io/v1/token_plan/remains`. A background daemon in TiinyMesh polls this endpoint every 5 minutes:
- Tracks `current_interval_remaining_percent` (5-hour rolling window) and `current_weekly_remaining_percent` (weekly window).
- Monitors `weekly_remains_time` (millisecond countdown until quota resets).
- **Auto-Switch to OpenRouter:** When `current_weekly_status == 2` (exhausted) or remaining quota falls below a safety threshold (<10%), TiinyMesh automatically flips `policy.chat.secondary` to OpenRouter and synchronizes the agent's delegation config.
- **Auto-Recovery to MiniMax:** When the reset timer elapses and quota recovers, TiinyMesh automatically re-engages MiniMax as the primary cloud model.

### 4.2 Transparent In-Flight HTTP 429 Failover
Even with polling, sudden token bursts can trigger rate limits or TPM throttling. When an upstream cloud target returns `HTTP 429`:
- Rather than passing the 429 back to the client, `Mesh.chat()` intercepts the error.
- It immediately resolves the configured secondary fallback (`openrouter/google/gemini-3.8-flash`).
- It re-executes the completion through the fallback provider and tags the response telemetry with `failover_from: "minimax"`.
- To the calling agent, the request succeeds without crashing or timing out.

### 4.3 In-Flight Manual Override
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

---

## 7. Residency Is Not Activity

The control panel had one meter per target, and it was answering a question nobody asked. The meter showed **NPU memory** — how much of the pool the resident models had allocated — and was labelled as though it were utilisation. A box with a 47% model loaded and nothing running reads 47% and is, in the only sense that matters to a scheduler, **idle**.

Two questions, two numbers:

| question | answered by | can it be wrong? |
|---|---|---|
| How much of the pool is **allocated**? | the resident model list | no |
| How much is the silicon **computing**? | the device's own NPU status | no |

They disagree more often than expected, which is exactly why a panel that shows only one of them misleads. The device reports 0.0% while idle and 75-97% during a generation, so a busy/idle threshold at 10% sits in the wide empty middle between those two readings rather than near either edge.

**The reservation and the telemetry answer different questions, and you want both.** A hold says who *claimed* the box; the device says whether it is *actually working*. The hold can be stale — written by an agent that has since died — and the device cannot be stale, because it is the thing doing the work. Reporting the hold *alongside* the live state is what makes "busy with nobody holding it" visible as exactly that.

---

## 8. Discovery Is Not Residency: Fit and Placement Are Separate Answers

The store catalogue answers "what exists". It does not answer "what would it cost to run this here", and a system that conflates the two gives an agent a model name and leaves it to discover the consequences.

The finder keeps them apart:

- **The score** answers *how well does this model fit the request?* — matched against the device's own type, capabilities, description, tags, and recommendation rank, with a lexicon mapping plain words onto the device's vocabulary so "drawing" is an image job rather than a chat job that happens to mention pictures.
- **The placement** answers *what would it cost to run it on this box?* — and the answer is one of `ready`, `load`, `un-reside`, or `download`.

Three things follow from keeping them apart:

**Capability types must match exactly.** A substring match on "image" classifies `Image-Text-to-Text` — a vision *chat* model — as an image generator, and the chat model outranks the generator that can actually do the job.

**NPU headroom and disk capacity are independent constraints.** A model can fit in NPU and have nowhere to live on disk, or fit on disk and require evicting a resident model. The disk is the half that bites later: most specialty models live on one box, and that box is often the one that is nearly full.

**Only resident models can be evicted.** Stopping a model that is merely *downloaded* frees no NPU share. The eviction list is therefore drawn from running models only, and it prefers the smallest non-generalist, so the generalist fallback stays resident as long as possible.
