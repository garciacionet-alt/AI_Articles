# The routing backend

The delegation backend that routes each subtask to the model that matches its
shape. Install it, then select it in the active profile's config.

## What it does

Core calls `route_task(task, config)` once per delegated subtask. The
backend inspects that subtask's goal, picks a tier, and returns the model,
provider, endpoint, and request overrides for that subtask alone.

Without it, `delegation.model` pins one model for every child in the batch.

## Install

1. Copy the plugin directory into your Hermes plugins tree:

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

4. Restart the agent so the plugin and the new schema are picked up.

## Verify

```bash
python3 ../scripts/route_check.py "index every file under the vault and classify each"
```

The checker prints the tier, the model, that model's NPU share and context
window, and whether it is currently resident. It makes no network calls.

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
| `browser` | `Qwen/Qwen3.8-27B` | 51% | 262144 |
| `draft` | `Qwen/Qwen3.5-9B` | 29% | 131072 |
| `general` | `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 |

**Re-read these numbers before trusting them.** They came from one device's
catalogue endpoint on 2026-10-31, when the store held 82 models. The store
changes with every TiinyOS update, and the NPU shares have already moved
once.

## Changing a tier

Three edits, in this order:

1. `TIER_CHOICES` in `plugin/__init__.py` — the model id, its NPU share, and
   its context window. All three come from the device.
2. `TIER_MODEL` — derived from `TIER_CHOICES`; it needs no separate edit
   unless a tier's default changes.
3. `SHAPE_SIGNALS` — the signals that route a task to that tier. More
   specific shapes come first; the first tier with a matching signal wins.

Then update the same table in `SKILL.md` and in the checker script, and
re-run the checker on a known goal.

## Things that will bite

- **The router never loads a model.** A load is a swap, and it evicts
  whatever was resident — including the model a sibling task is using.
  Residency is a separate, deliberate operation.
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
