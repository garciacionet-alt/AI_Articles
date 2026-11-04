# The routing backend

The delegation backend that routes each subtask to the model that matches its
shape. Install it, then select it in the active profile's config.

## What it does

Core calls `route_task(task, config)` once per delegated subtask. The
backend inspects that subtask's goal, picks a tier, and returns the model,
provider, endpoint, and request overrides for that subtask alone.

Without it, `delegation.model` pins one model for every child in the batch.

**It chooses; it never loads.** The device's resident set is a shared, finite
resource and a load is a swap that evicts whatever was resident, so the
loading half of the job lives in `scripts/tiiny_ctl.py` — a step the manager
agent takes explicitly. See [lifecycle.md](lifecycle.md).

The two halves meet at the **plan** (`~/.hermes/tiiny-plan.json`): the
controller writes it when it plans a batch, and the router reads it when it
routes each subtask. That is how a specialist the controller just loaded
becomes the specialist the child actually runs on.

## Install

1. Copy the plugin directory into your Hermes plugins tree. **Both files
   matter** — `tiers.py` holds the table the plugin and the scripts share:

   ```bash
   cp -r plugin ~/.hermes/hermes-agent/plugins/delegation/tiiny-router/
   ```

2. Add the device as a provider in the active profile's `config.yaml`:

   ```yaml
   providers:
     tiiny:
       name: tiiny
       api: http://openai.api.tiiny/v1
       key_env: TIINY_API_KEY
       transport: chat_completions
       default_model: Qwen/Qwen3.6-35B-A3B
       context_length: 262144
       extra_body:
         chat_template_kwargs:
           enable_thinking: false
       models:
         Qwen/Qwen3.6-35B-A3B: {context_length: 262144}
         Qwen/Qwen3.8-27B: {context_length: 262144}
         Qwen/Qwen3.5-9B: {context_length: 131072}
         openai/gpt-oss-20b: {context_length: 131072}
         deepreinforce-ai/Ornith-1.0-35B: {context_length: 131072}
         InternScience/Sage-A1.5-Turbo: {context_length: 262144}
   ```

   The bearer goes in the environment as `TIINY_API_KEY`.

   `models_discovered: false` matters: with it on, a live probe can wipe the
   metadata above and leave a model with the wrong context length.

3. Select the backend in the same `config.yaml`:

   ```yaml
   delegation:
     backend: tiiny-router
     fallback_providers:
       - provider: minimax
         model: MiniMax-M3
   ```

   The fallback matters: if the device is unreachable, the batch should still
   complete on a paid provider rather than fail. It should also be visible
   when it happens — a silent fallback means the local tier is not actually
   being used.

4. Restart the agent so the plugin and the new schema are picked up. If the
   agent runs under a gateway that cannot be restarted, the gateway's
   control socket reloads plugins in place:

   ```python
   from pathlib import Path
   from gateway.control_socket import reload_gateway_plugins
   from hermes_constants import get_hermes_home

   reload_gateway_plugins(Path(get_hermes_home()))
   ```

## Verify

```bash
python3 ../scripts/route_check.py "index every file under the vault and classify each"
python3 ../scripts/tiiny_ctl.py status
```

The checker prints the tier, the model, that model's NPU share and context
window, and whether it is currently resident. The controller prints the
device, the resident set, the lock, the hold and the plan.

To confirm the backend is live, delegate a batch with mixed subtasks and read
the `route` on each child's result — it carries the backend name and the
tier label.

## The tiers

| Tier | Model | NPU | Context |
|---|---|---|---|
| `research` | `InternScience/Sage-A1.5-Turbo` | 48% | 262144 |
| `research` (alt) | `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 |
| `index` | `openai/gpt-oss-20b` | 27% | 131072 |
| `code` | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 |
| `code` (alt) | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |
| `code` (heavy) | `Qwen/Qwen3-Coder-Next` | 94% | 131072 |
| `browser` | `Qwen/Qwen3.8-27B` | 52% | 262144 |
| `draft` | `Qwen/Qwen3.5-9B` | 29% | 131072 |
| `general` | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |

**Re-read these numbers before trusting them.** They came from one device's
catalogue endpoint on 2026-11-01, when the store held 82 models. The store
changes with every TiinyOS update, and the NPU shares have already moved
once.

They live in **`plugin/tiers.py`**, which is the single source of truth: the
plugin, the controller and the checker all read that one file, so they cannot
drift apart. It is loaded by path rather than by package name, because the
Hermes plugin loader executes `__init__.py` through `spec_from_file_location`
— which does not establish package semantics, so a relative import would
fail there.

## Changing a tier

Three edits, in this order, all in `plugin/tiers.py`:

1. `TIER_CHOICES` — the model id, its NPU share, and its context window. All
   three come from the device; `tiiny_ctl.py catalog --refresh` tells you
   when they have moved.
2. `TIER_MODEL` — derived from `TIER_CHOICES`; it needs no separate edit
   unless a tier's default changes.
3. `SHAPE_SIGNALS` — the signals that route a task to that tier. More
   specific shapes come first; the first tier with a matching signal wins.

Then update the same table in `SKILL.md`, and re-run the checker on a known
goal.

## Things that will bite

- **The route's shape is the credential path.** The backend returns the
  delegation section's own shape with only the model overridden — the way
  the default backend returns `dict(config)`. This is not cosmetic. A route
  with `base_url` set and `api_key` empty is a *direct endpoint*, and an
  empty key means **inherit the parent's key**. The parent runs on the paid
  provider, so the device would receive the wrong bearer and answer
  `401 auth_failed` — and the child would fall back to the paid provider,
  invisibly. Returning the section's shape puts this backend on the
  provider-resolution branch, where the device's `key_env` is honoured.
- **The router reads residency, and that changes the route.** It queries
  `GET /v1/models` on the inference endpoint (30-second cache) and picks a
  model that is actually loaded: the plan's assignment if there is one, then
  the tier's first choice, then another candidate from the same tier, then
  the generalist. A model that is not resident answers `404 "is not loaded"`,
  which Hermes treats as terminal and falls back to the paid provider — so
  routing to an unloaded model silently moves work off the device. The
  route's `label` records any substitution (`code->generalist`). If the
  lookup fails, the router fails open to the tier's first choice.
- **The router never loads a model.** A load is a swap, and it evicts
  whatever was resident — including the model a sibling task is using. The
  controller does the loading, explicitly, under a lock.
- **An unknown tier is refused.** The override fails loudly rather than
  falling back to the generalist, because a silent fallback is invisible in
  the output and expensive in the tokens.
- **The task schema is cached.** `task_parameters()` and `description()` must
  be deterministic for a given config — the schema is part of the cached
  prompt prefix, so a non-deterministic result changes the prompt between
  calls.
- **Thinking mode costs tokens on mechanical work.** The route disables it
  per request with `chat_template_kwargs`. On a small `max_tokens` budget a
  thinking model can return an empty response with the budget spent in the
  reasoning trace.
- **Hermes secrets are not in the environment.** The device key lives in
  `~/.hermes/.env` and is read through `hermes_cli.config`'s accessor. A
  plugin that reads `os.environ` finds nothing, and the residency check
  fails open on every call.
- **A partially-installed plugin fails at load, not at use.** The plugin
  loader executes `__init__.py` through `spec_from_file_location`, so
  `__init__.py` cannot use a relative import to reach `tiers.py` — it loads
  that file by path. Copy the whole `plugin/` directory, not just
  `__init__.py` and `plugin.yaml`. A tree with `__init__.py` but no
  `tiers.py` raises `ImportError` at load, and the backend is then simply
  absent from `hermes plugins list` — which reads as "never installed"
  rather than "installed wrong". Validate with
  `hermes plugins validate <dir>`.
- **The installed skill and the vault skill drift apart.** The vault copy
  under `skills/tiiny-model-routing/` is the source of truth; the installed
  copies live under `~/.hermes/skills/tiiny-model-routing/` and
  `~/.hermes/skills/mlops/tiiny-model-routing/`. A stale installed copy ends
  up carrying its own literal copy of the tier table instead of importing
  `plugin/tiers.py`, and the table starts drifting. Diff all three before
  trusting any of them, and re-sync vault → installed after any table change.
- **A saved `delegation.backend` does not change a running chat.** The
  `delegate_task` schema is cached in the prompt prefix, so a config edit
  applies from the next session (`/new`), not the current one. Verify the
  backend in a fresh process rather than expecting the current session to
  re-route:
  `python3 -c "from agent import delegation_backends as db; print(db.list_backends())"`
