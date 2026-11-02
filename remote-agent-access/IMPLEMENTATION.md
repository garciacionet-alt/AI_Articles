# Implementation: Reaching a LAN Agent From Anywhere

The concrete setup. The reasoning is in [PATTERN.md](./PATTERN.md); this is
the wiring.

Verified against **Hermes Agent** (messaging gateway with Telegram, Discord,
Slack, WhatsApp) and a local OpenAI-compatible inference appliance. The
shape transfers to other agent runtimes, but the commands do not.

## What you are building

```
   phone / browser
        │
        ▼
   chat platform  ◄──── outbound long-lived HTTPS from your host ────┐
        ▲                                                            │
        │                                                            │
   your agent host  (always on, on your LAN) ◄──────────────────────┘
        │
        ▼
   local inference appliance   (LAN-resolvable name, bearer on the host)
```

Two independent things are configured:

1. **The control plane** — a chat platform, so you can reach the agent.
2. **The compute plane** — a LAN endpoint for the appliance, so bulk work is
   local and free.

They have separate configuration, separate credentials, and separate failure
modes. Keep them separate.

---

## Part 1 — The control plane

### 1.1 Create the bot and get its token

For Telegram, use **@BotFather** to create a bot. It returns a token that
looks like `123456789:AAH...`. That token is a full credential: anyone
holding it can act as the bot. Treat it like a password.

Put it in the environment file, never in `config.yaml`:

```bash
# ${HERMES_HOME:-~/.hermes}/.env
TELEGRAM_BOT_TOKEN=123456789:AAH...
TELEGRAM_ALLOWED_USERS=111111111,222222222
TELEGRAM_HOME_CHANNEL=-1001234567890
```

`TELEGRAM_ALLOWED_USERS` is the allow-list. **Set it.** An unscoped bot on
the public internet is a stranger's compute, and your appliance is attached
to it. The IDs are your own numeric Telegram user IDs — you can find yours by
messaging the bot and reading the update payload.

`TELEGRAM_HOME_CHANNEL` is where unsolicited output goes. Point it at a
channel you own.

### 1.2 Point the gateway at the chat platform

```bash
hermes gateway setup
```

The wizard enables the platform and writes the credentials. It can also be
done by hand in `config.yaml` — but prefer `hermes config set KEY VAL` over
editing the file, because a stray indent in `config.yaml` corrupts the live
gateway.

To check the connection rather than the process:

```bash
hermes gateway status
```

**Look for a connection state, not just a running process.** These are
different claims. A gateway can be running while its chat session is
disconnected, and the symptom of that is silence — which looks identical to
"the agent is not responding" and gets debugged in the wrong direction.

### 1.3 Run the gateway as a supervised service

An agent you reach from a phone has to be up when you reach for it. Run it
under a service manager that restarts it:

```bash
hermes gateway install
hermes gateway start
hermes gateway status
```

On macOS this installs a launchd agent; on Linux, a systemd user unit. The
install is idempotent — it rewrites the unit to match the current install
rather than stacking a second copy.

### 1.4 Verify from outside the LAN

The real test is not from the desk. Message the bot from a phone on cellular
data, or from a browser on a network that is not your own. A control plane
that only works on the LAN is not a control plane.

---

## Part 2 — The alternate transport: inbound webhooks

Part 1 needs no public URL and no listener. **That is the point, and you
should not add one without a reason.**

But some things want to *trigger* the agent rather than be *talked to*: a
GitHub webhook, a Stripe event, a monitoring alert, a sensor. Those need an
inbound HTTP endpoint with an authenticated request path. That is a different
problem, and it deserves different plumbing.

### 2.1 Enable the webhook platform

```bash
hermes gateway setup
# or, by hand:
hermes config set platforms.webhook.enabled true
hermes config set platforms.webhook.extra.port 8644
```

Or via the environment file:

```bash
WEBHOOK_ENABLED=true
WEBHOOK_PORT=8644
WEBHOOK_SECRET=your-global-hmac-secret
```

Restart the gateway and confirm:

```bash
curl http://localhost:8644/health
# {"status": "ok"}
```

### 2.2 Make it reachable — and only it

The webhook endpoint needs a public URL. Options, in order of preference:

| Method | Exposure | Notes |
|---|---|---|
| **Reverse proxy on your own host** | Your host's address only | Needs a certificate and a public IP |
| **Tunnel (ngrok, cloudflared)** | Tunnel operator's domain | Convenient; read their retention policy |
| **VPN / overlay network** | Your tailnet only | Best if every caller is already on the net |

If you use a tunnel, bind it to the webhook port **only**. Do not point a
tunnel at a general-purpose port on a machine that also runs your agent — you
would be publishing the agent's own surface to get at a feature.

### 2.3 Subscribe

```bash
hermes webhook subscribe github-prs \
  --events "pull_request" \
  --prompt "PR #{{payload.number}}: {{payload.title}}" \
  --skills "github-code-review" \
  --deliver github_comment
```

Each subscription gets an auto-generated HMAC-SHA256 secret. The adapter
validates the signature on every incoming POST. **Never disable signature
validation** — it is the only thing between the public internet and an agent
with filesystem access.

For notifications that need no reasoning, `--deliver-only` sends the
rendered prompt straight to the chat with no agent run and no LLM cost.

---

## Part 3 — The compute plane

### 3.1 Give the appliance a LAN-resolvable name

The appliance should be reachable by a name that resolves **inside your
network and nowhere else**. Do not publish it, and do not use a name that
embeds your network's identity.

```bash
# Verify it resolves locally and that the port answers
python3 -c "import socket; print(socket.gethostbyname('appliance.local'))"
nc -z -w 3 appliance.local 80 && echo "reachable"
```

### 3.2 Put the bearer on the host, in the environment file

```bash
# ${HERMES_HOME:-~/.hermes}/.env
APPLIANCE_API_KEY=your-bearer-token
```

Not in `config.yaml` — that file holds settings and gets shared, screenshotted
and pasted into issues. Not in a repository. Not in a published article.

### 3.3 Point the agent's provider at the local endpoint

In `config.yaml`:

```yaml
providers:
  appliance:
    name: appliance
    api: http://appliance.local/v1
    key_env: APPLIANCE_API_KEY
    transport: chat_completions
    default_model: Qwen/Qwen3.6-35B-A3B
    context_length: 131072
```

`key_env` names the *variable*, not the value. Hermes reads the value from
the environment file at runtime, so the secret never enters the config.

### 3.4 Make the routing decision visible — the important part

This is the step people skip, and it is the one that costs money.

**Log which provider served each task.** A run that silently fell back to a
paid API is a run you are paying for and did not know about. The fallback
has to be observable, and ideally alertable.

The delegate step takes an explicit provider and model, so the routing
decision is made at the call site:

```python
result = delegate_task(
    tasks=[{
        "goal": "Index the corpus and classify each record.",
        "context": "...",
    }],
    delegation={
        "provider": "custom:appliance",
        "model": "Qwen/Qwen3.6-35B-A3B",
    },
)
```

Two things to get right:

- **The local endpoint is the default.** Set `delegation.provider` to the
  appliance so bulk work goes local without every call site remembering to.
- **Fallback usage is logged and alerts.** A spike in cloud fallbacks means
  the appliance is unreachable — and if you are not watching, that is a
  bill you discover later.

> **A note on the provider string.** `custom:<name>` selects a provider
> defined under `providers:` in `config.yaml`. A provider registered but not
> named correctly fails as "unknown provider" rather than "device
> unreachable", which sends you looking in the wrong place.

---

## Part 4 — The appliance lock

An inference appliance with a fixed memory pool does not host two models at
once. **Loading a model evicts whatever was resident.** So the appliance
needs a holder: a mechanism that keeps a deliberately-loaded model resident
while a background supervisor wants to reload its own set, plus a restore
step that puts the expected model back afterwards.

Without it, the failure is intermittent and genuinely confusing: a delegated
child runs for four minutes and then gets a `404` from the appliance. That
404 means *not resident* — **not** "bad model". The client cannot tell those
apart, and both look like a broken endpoint.

The shape of a working swap wrapper:

```bash
#!/usr/bin/env bash
# tiiny-swap.sh — run a command against a specific model, safely.
#
# A model load is a SWAP, not an add: the memory pool is finite and shared,
# so loading a model evicts whatever was resident. Two things must be true:
#
#   1. The watchdog must not fight it. The watchdog reloads its REQUIRED
#      set every five minutes and would evict the model we just loaded, so
#      write a hold file first; the watchdog sees the hold and reloads
#      nothing.
#   2. The model the delegation config expects must come back afterwards.
#      The required set is restored at the end, in the order the watchdog
#      would use, so the next delegated child finds its model.
#
# USAGE
#   tiiny-swap.sh <model_id> -- <command> [args...]
#   tiiny-swap.sh --restore      # drop the hold and reload the required set
#
# The hold file lists deliberately-resident models. A STALE HOLD is the
# hazard: one left behind stops the watchdog from ever restoring the
# device. --restore and --clear exist for that.

set -uo pipefail

TIINY_BIN="$HOME/.local/tiiny/bin/tiiny"
HOLD_FILE="$HOME/.hermes/tiiny-hold"

# ... resolve the model, write the hold, run the command, restore ...
```

The invariant to preserve: **after any delegated run, the device is in the
state the delegation config expects.** A swap that does not restore leaves
the next child to fail with a 404, on a different task, some minutes later —
which is close to undebuggable.

`~/.hermes/scripts/tiiny-swap.sh --restore` drops a stale hold and reloads
the required set. Run it when you suspect the device is stuck.

For the full appliance lifecycle — the memory budget, the model catalogue,
and how to choose — see
[Tiiny Model Routing](../tiiny-model-routing/IMPLEMENTATION.md).

---

## Part 5 — Audit the exposures

Replacing a transport leaves the old exposure behind. The URL still
resolves, the certificate is still valid, and nothing is listening.

```bash
# What is on the tailnet, and what is exposed?
tailscale status
tailscale funnel status

# What is actually listening on this host?
lsof -nP -iTCP -sTCP:LISTEN

# Does the exposed port answer?
nc -z -w 3 <exposed-host> <port> && echo "ANSWERS" || echo "nothing listening"
```

**Close what you no longer use.** An open port to nothing is still an open
port — harmless until something else binds it.

The bundled checker does all of this and more:

```bash
bash scripts/check-agent-reachability.sh
```

It is read-only, prints findings rather than secret values, and exits
non-zero when it finds a problem.

---

## End-to-end checklist

**Control plane**

- [ ] Bot created, token in the environment file only
- [ ] Allow-list of user IDs set
- [ ] Gateway installed as a supervised service
- [ ] `hermes gateway status` reports a **connected** state
- [ ] A message sent from a phone on cellular data gets a reply

**Compute plane**

- [ ] Appliance reachable by a LAN-resolvable name
- [ ] Bearer in the environment file, referenced by `key_env`
- [ ] Provider configured with the local endpoint as the default
- [ ] A delegated task logs the appliance as the serving provider
- [ ] Fallback to the cloud provider is logged and alertable

**Appliance lifecycle**

- [ ] A swap wrapper holds the model against the watchdog
- [ ] The wrapper restores the expected model after every run
- [ ] `--restore` is known and works

**Hygiene**

- [ ] No public exposure without an owner and a reason
- [ ] Stale exposures closed
- [ ] Nothing published names your device, network, or tailnet

---

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| Bot silent from outside, fine on the LAN | Gateway not connected to the platform | `hermes gateway status` — look at connection state, not process state |
| Agent replies as the wrong personality | Two gateways, one bot token | One token, one gateway |
| Every message answered twice | Polling and a webhook both active on one bot | One transport per bot |
| Delegated child gets a 404 from the appliance | Model not resident — evicted | The hold file; run `--restore` |
| Task completes, bill rises | Appliance unreachable, cloud fallback fired | Provider logging on the delegate step |
| Appliance unreachable by name | DNS or the appliance is down | Resolve the name locally; `nc -z` the port |
| Works on the desk, not from the phone | Testing from the wrong network | Test on cellular, from a browser off-network |

---

## Related

- [PATTERN.md](./PATTERN.md) — the reasoning behind every step here.
- [Tiiny Model Routing](../tiiny-model-routing/) — model selection and the
  appliance lifecycle.
- [Bot Identity](../bot-identity/) — scoping the bot token correctly.
