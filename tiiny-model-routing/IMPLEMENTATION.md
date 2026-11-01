## The implementation

This is the concrete setup: the delegation backend that routes each subtask,
the swap script that makes model changes survivable, the checker that lets a
routing decision be reviewed before it costs anything, and an end-to-end
checklist.

Everything here was built and run against a live device. Where a number
appears, it came from the device's own catalogue endpoint on 2026-10-31.

---

## 1. The delegation backend

A routing layer in Hermes is a **delegation backend plugin**. It implements
one method:

```python
def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
```

Core calls it **once per subtask**, with that subtask's `goal`, `context`,
and `index`, and expects a route: `model`, `provider`, `base_url`,
`request_overrides`, and an optional `label`.

Two methods make the backend useful rather than merely functional:

- **`task_parameters(config)`** declares extra per-task JSON-schema
  properties that get merged into `delegate_task`'s task schema. This is how
  the `tier` override becomes a real parameter a caller can set.
- **`description(config)`** returns guidance appended to the tool
  description, so the model calling `delegate_task` knows the tiers exist
  and when to force one.

Both must be **deterministic for a given config** — the task schema is part
of the cached prompt prefix, so a non-deterministic result changes the prompt
between calls.

### Plugin layout

A delegation backend is a plugin of `kind: backend`:

```
tiiny-router/
├── plugin.yaml
└── __init__.py
```

`plugin.yaml`:

```yaml
name: tiiny-router
version: 1.1.0
description: "Delegation backend that routes each subtask to the Tiiny model matching its shape."
author: Your Name (your-handle), Hermes Agent
kind: backend
```

`__init__.py` holds the provider class and a `register(ctx)` function that
calls `ctx.register_delegation_provider(...)`.

### The tier table

Every number in this table came from the device's catalogue endpoint. The
NPU share decides what can be resident alongside what; the context window
decides what a child can hold.

```python
TIER_CHOICES = {
    "research": (
        ("InternScience/Sage-A1.5-Turbo", 48, 262144),
        ("endless-frontier/BigBang-v1-Turbo", 54, 131072),
    ),
    "index": (
        ("openai/gpt-oss-20b", 27, 131072),
    ),
    "code": (
        ("deepreinforce-ai/Ornith-1.0-35B", 50, 131072),
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
        ("Qwen/Qwen3-Coder-Next", 94, 131072),
    ),
    "browser": (
        ("Qwen/Qwen3.8-27B", 51, 262144),
    ),
    "draft": (
        ("Qwen/Qwen3.5-9B", 29, 131072),
    ),
    "general": (
        ("Qwen/Qwen3.6-35B-A3B", 47, 262144),
    ),
}
```

A tier can hold several candidates. The first is the default; the rest are
fallbacks, in the order the device's own model descriptions support — and the
router actually *uses* them, because it knows which models are resident. The
next section is about that, and it is the part that makes the tier table more
than a lookup table.

### Routing to something that is loaded

A model that is not resident cannot answer. The device replies `404 "is not
loaded"`, Hermes classifies that as terminal, and the child falls back to the
paid provider. On a device whose shared NPU pool holds a handful of models at
a time, that turns a routing decision into a silent move off the local
device — and the work still completes, so nothing looks wrong.

So the router reads the device's resident set and picks something that is
actually there:

```python
def resident_models():
    """Return the model ids currently resident, or None if unknowable."""
    key = os.environ.get("TIINY_API_KEY", "").strip()
    if not key:
        return None
    try:
        request = urllib.request.Request(
            TIINY_BASE_URL + "/models",
            headers={"Authorization": "Bearer " + key},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
    except Exception:
        return None
    ids = {e["id"] for e in payload.get("data", [])
           if isinstance(e.get("id"), str) and "/" in e["id"]}
    return frozenset(ids)


def choose_model(tier):
    choices = TIER_CHOICES[tier]
    default_model = choices[0][0]

    resident = resident_models()
    if resident is None:
        return default_model, tier          # residency unknown — behave as before

    for model, _npu, _ctx in choices:
        if model in resident:
            label = tier if model == default_model else f"{tier}->{model.split('/')[-1]}"
            return model, label

    if GENERALIST in resident:
        return GENERALIST, f"{tier}->generalist"

    return default_model, tier
```

Three decisions worth naming:

**Read, never write.** The router asks the device what is resident and nothing
else. Loading is still the operator's call, made with the swap script.

**Fail open.** If the device is unreachable, the key is missing, or the lookup
times out, the router returns the tier's first choice — exactly the behaviour
from before residency was considered. A routing decision is not a place to
fail.

**Substitute, and say so.** When the tier's specialist is not resident, the
route falls back to the generalist rather than to a 404. The label records it
(`research->generalist`), so the substitution is visible in the child's result
instead of being invisible in a fallback.

### Shape detection

```python
SHAPE_SIGNALS = (
    ("research", ("research", "literature", "survey", "investigate",
                  "find sources", "web search", "deep dive", ...)),
    ("index",    ("index", "inventory", "classify", "enumerate",
                  "list every file", "walk the", "bulk", ...)),
    ("browser",  ("browser", "click through", "fill in the form",
                  "navigate the site", "screenshot the", ...)),
    ("code",     ("code", "refactor", "implement", "debug", "unit test",
                  "repository", "module", "shell script", ...)),
    ("draft",    ("draft", "summar", "rewrite", "bullet", "outline",
                  "condense", "proofread", ...)),
)

def detect_tier(goal: str) -> str:
    text = (goal or "").lower()
    for tier, signals in SHAPE_SIGNALS:
        for signal in signals:
            if signal in text:
                return tier
    return "general"
```

Ordering matters: the first tier with a matching signal wins, so the
specific shapes are tested before the general ones.

### The route

```python
def route_task(self, task, config):
    forced = task.get("tier")
    if forced:
        tier = str(forced)
        if tier not in TIER_MODEL:
            raise DelegationRouteError(
                f"Unknown tier {tier!r}. Valid tiers are: {', '.join(VALID_TIERS)}."
            )
    else:
        tier = detect_tier(str(task.get("goal") or ""))

    model, label = choose_model(tier)
    return {
        "model": model,
        "provider": "custom:tiiny",
        "base_url": "http://openai.api.tiiny/v1",
        "request_overrides": {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
        "label": label,
    }
```

Three details are decisions rather than defaults:

**`enable_thinking: false`** — several models in the catalogue run in
thinking mode by default. On a small `max_tokens` budget the response can
come back empty with the budget spent in the reasoning trace. Disabling it
per request is what makes mechanical work predictable.

**`raise DelegationRouteError`** — an unknown tier is refused, not mapped to
the fallback. The message becomes the `delegate_task` tool error the model
reads, so it should read as an instruction.

**`label`** — a short string carried on the child's result, so the route can
be read back after the fact. Without it, "which model actually ran this?" is
unanswerable. When the router substituted a model, the label says so.

### The provider and the config

The backend needs a provider entry for the device:

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

And the delegation section selects the backend:

```yaml
delegation:
  backend: tiiny-router
  fallback_providers:
    - provider: minimax
      model: MiniMax-M3
```

The fallback matters: if the device is unreachable, the batch should still
complete on a paid provider rather than fail. It should be visible when it
happens — a silent fallback means the local tier is not actually being used.

---

## 2. The swap script

Choosing a model is half the work. The other half is residency, and a load
is a **swap**: it evicts whatever was resident.

Three things have to be handled, and each one is a separate failure that
shows up differently:

| Problem | Symptom | Fix |
|---|---|---|
| `tiiny load` needs a TTY | `could not open a new TTY` from a script | `script -q /dev/null tiiny load MODEL -y` |
| The watchdog evicts a deliberate swap | The model dies mid-task | A hold file the watchdog respects |
| The displaced model is not restored | The next batch inherits a broken device | Restore the required set on exit |

The script writes the hold **before** the load, which closes the window
where the watchdog fires between the load and the hold.

```bash
#!/usr/bin/env bash
set -uo pipefail

TIINY_BIN="$HOME/.local/tiiny/bin/tiiny"
HOLD_FILE="$HOME/.hermes/tiiny-hold"

REQUIRED_MODELS=(
  "Qwen/Qwen3.6-35B-A3B"
  "Qwen/Qwen3-ASR-1.7B"
  "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
  # Preset-voice TTS (Hermes's text_to_speech tool targets this model).
  # Costs 0% NPU, so it rides alongside everything else.
  "Supertone/supertonic-3"
  # The router's `index` tier. This list MUST be identical to the watchdog's
  # REQUIRED_MODELS: a load evicts whatever does not fit, and a specialist is
  # the first thing to go, so a shorter list here means --restore leaves the
  # device without it until the next watchdog tick.
  "openai/gpt-oss-20b"
)

# --restore: drop the hold and reload the required set
if [ "${1:-}" = "--restore" ]; then
  rm -f "$HOLD_FILE"
  for m in "${REQUIRED_MODELS[@]}"; do
    script -q /dev/null "$TIINY_BIN" load "$m" -y >/dev/null 2>&1 \
      && echo "  loaded $m" || echo "  FAILED $m" >&2
  done
  "$TIINY_BIN" top
  exit 0
fi

MODEL="${1:-}"
[ -n "$MODEL" ] || { echo "usage: tiiny-swap.sh <model_id> [-- cmd] | --restore" >&2; exit 1; }
shift || true

# The hold goes first: the watchdog can fire at any moment, and a load
# followed by a hold leaves a window where the watchdog evicts what we just
# loaded.
printf '%s\n' "$MODEL" > "$HOLD_FILE"

script -q /dev/null "$TIINY_BIN" load "$MODEL" -y >/dev/null 2>&1 \
  || { echo "load failed for $MODEL" >&2; rm -f "$HOLD_FILE"; exit 1; }

if [ "${1:-}" = "--" ]; then
  shift
  "$@"
  rc=$?
  "$0" --restore
  exit $rc
fi
```

### The watchdog's half

The watchdog needs to know about the hold, and the check has to be in the
right place:

```bash
HOLD_FILE="$HOME/.hermes/tiiny-hold"

device_state() {
  if ! curl -sf --max-time 6 "$BASE/health" >/dev/null 2>&1; then
    echo "offline"; return
  fi
  # A deliberate hold wins over every other check. This must come BEFORE
  # the key and required-models checks, or a hold is reported as cold and
  # the reload evicts whatever the holder deliberately loaded.
  [ -f "$HOLD_FILE" ] && { echo "held"; return; }
  # ... the rest of the original function
}
```

And the main loop must not reload when the state is `held`:

```bash
if [ "$observed" = "held" ]; then
  effective="held"
  write_state "held" "held"
  exit 0
fi
```

**A stale hold is the hazard.** One left behind stops the watchdog from ever
restoring the device, so the script needs `--restore` and `--clear` to clear
one — and it needs to *check* that it cleared it. A script that prints "hold
cleared" without verifying is exactly how a hold outlives the batch that
created it.

Two changes remove the hazard rather than documenting it.

**The hold file is released by truncating it, not only by deleting it.**
Truncation is a write, and a write works in every context — including a
sandbox that blocks deletion outright:

```bash
clear_hold() {
  : > "$HOLD_FILE" 2>/dev/null || true     # truncate: a write always works
  rm -f "$HOLD_FILE" 2>/dev/null || true    # remove it if we are allowed to
  [ -s "$HOLD_FILE" ] && return 1           # still holding? say so.
  return 0
}
```

**The watchdog honours a hold only while it still means something.** An empty
hold file is a released hold. A hold older than a grace window is honoured
only if its model is still resident — otherwise it protects nothing and the
device is restored:

```bash
HOLD_GRACE=600

hold_active() {
  [ -f "$HOLD_FILE" ] || return 1
  local held
  held="$(head -n1 "$HOLD_FILE" 2>/dev/null | tr -d '\r')"
  [ -n "$held" ] || return 1                 # empty file = released hold

  # Fresh hold: the load it protects may not have landed yet.
  local mtime now age
  mtime="$(stat -f %m "$HOLD_FILE" 2>/dev/null || echo 0)"
  now="$(date +%s)"; age=$(( now - mtime ))
  [ "$age" -ge 0 ] && [ "$age" -le "$HOLD_GRACE" ] && return 0

  # Older than the grace window: real only if its model is still resident.
  local models
  models="$(curl -sf --max-time 8 -H "Authorization: Bearer $KEY" \
           "$BASE/v1/models" 2>/dev/null || true)"
  printf '%s' "$models" | grep -q "\"$held\"" && return 0
  printf 'ignoring stale hold (%s is not resident)\n' "$held" >&2
  return 1
}
```

The grace window covers the gap between writing the hold and finishing the
load it exists to protect — the hold is written *before* the load, precisely
so the watchdog cannot fire in between.

One more portability note, because it will bite anyone running the script
wherever temp files are restricted: bash implements a here-string (`<<<`) by
writing a temp file. Reading the previous state that way kills the script on
`set -u` with an unbound variable. Plain parameter expansion does not.

---

## 3. The routing checker

`scripts/route_check.py` applies the same tier table and the same shape
detection, then prints the tier, the model, and the budget — so a routing
decision can be checked without spawning a child.

```bash
python3 scripts/route_check.py "index every file under the vault and classify each"
python3 scripts/route_check.py --all
python3 scripts/route_check.py --tier code --alternatives "anything"
```

It makes no network calls and changes nothing on the device. The residency
line comes from `tiiny top`.

---

## 4. End-to-end checklist

- [ ] The bearer is in the environment as `TIINY_API_KEY`.
- [ ] The `tiiny` CLI is on `PATH`, and `tiiny top` answers.
- [ ] The `tiiny` provider is in `config.yaml`, with `key_env: TIINY_API_KEY`.
- [ ] The backend plugin is installed and `delegation.backend` selects it.
- [ ] The tier table's NPU shares and context windows were read from the
      device, not copied from an earlier read.
- [ ] Every model in the tier table is in the store.
- [ ] The fallback provider is configured, and its use is visible.
- [ ] The swap script is in place, and the watchdog honours the hold.
- [ ] The hold check runs before the cold-check in the watchdog.
- [ ] `route_check.py` returns the expected tier for a known goal.
- [ ] A batch with mixed subtasks shows more than one model in its results.
- [ ] After a deliberate swap, the required models are resident again.
