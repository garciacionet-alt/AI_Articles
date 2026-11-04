# Implementation: A Private Network for Your Agents

The concrete setup. The reasoning is in [PATTERN.md](./PATTERN.md); this is the
wiring.

Written against **Tailscale** on macOS and Linux, with an agent runtime that
speaks HTTP on a local port and a commons of files on a synced folder. The
shape transfers to other overlay networks; the commands do not.

Throughout, these are placeholders:

| Placeholder | What it is |
|---|---|
| `<TAILNET>` | Your tailnet's DNS suffix, e.g. `example-tailnet.ts.net` |
| `<NODE-NAME>` | The overlay node name for a machine — chosen independently of its OS hostname |
| `<AMC-HOST>` | The machine that holds the Agent Memory Commons |
| `<VPS-NODE>` | The cloud node the agent's core runs on |
| `<LISTENER-PORT>` | The local port your webhook listener binds to |
| `<WEBHOOK-PATH>` | The path segment the provider posts to |

---

## Part 1 — Build the estate

### 1.1 Enrol the nodes

Every machine that participates — the one holding the commons, the cloud VM the
agent runs on — is a node in the tailnet.

```bash
tailscale up
tailscale status
```

Enrolment is the authentication. A node that is not enrolled cannot open a
session to one that is, whatever port it asks for. That is the whole point:
the network's policy replaces per-service auth for the private half of the
estate.

Give each node a name you will keep. You will refer to it in ACLs, in serve
configurations, and in healthchecks.

### 1.2 Separate the node name from the OS hostname

This is the step people skip, and it is the one that causes outages later.
**Do it before anything is keyed to the node name.**

On macOS, the overlay node name follows the OS `ComputerName` by default.
Break the link explicitly:

```bash
# 1. The overlay node name — this is the stable identity.
tailscale set --hostname=<NODE-NAME>

# 2. Pin the OS names so they cannot drift underneath you either.
sudo scutil --set ComputerName "<NODE-NAME>-host"
sudo scutil --set HostName "<NODE-NAME>-host"
sudo scutil --set LocalHostName "<NODE-NAME>-host"
```

Then **verify** the two names are actually different, because the order of
operations matters and a half-applied change looks fine:

```bash
# The overlay name
tailscale status --json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))"

# The OS names
scutil --get ComputerName
scutil --get LocalHostName
```

The two must differ. If they match, the machine sees its own name claimed once
on the LAN and once through the tunnel, and the local resolver will start
renaming it with an incrementing suffix — on every wake and every reboot.

> **A note on `scutil`.** `scutil --set HostName` can appear to hang *after* the
> write has already landed. If it does not return, the change is probably
> applied — check with `scutil --get HostName` before retrying. Retrying a
> command that already succeeded is how a repair becomes a second incident.

### 1.3 Know which class each service is in

| Class | Command | Reachable from |
|---|---|---|
| LAN only | a LAN-resolvable name, e.g. `http://appliance.local:80` | Your LAN |
| Tailnet | `tailscale serve --bg <LISTENER-PORT>` | Tailnet nodes only |
| Public | `tailscale funnel --bg <LISTENER-PORT>` | The internet, with a secret |

Check what is currently exposed:

```bash
tailscale serve status
tailscale funnel status
```

Both print the configuration and the hostname it is keyed against. **That
hostname is the thing that goes stale** — see Part 4.

### 1.4 Bind local services to loopback and authenticate them

Do not rely on the host firewall. On a default macOS install the application
firewall is **off**, which means anything bound to `0.0.0.0` is reachable from
the LAN and from every peer on the tailnet under the default permissive policy.

So: bind services to `127.0.0.1` and require a token.

```bash
# A listener that serves the tailnet, bound to loopback, behind a proxy.
# The proxy is the thing that decides who can reach it.
tailscale serve --bg --https=8443 http://127.0.0.1:<LISTENER-PORT>
```

A bearer in the environment, never in a config file that gets shared:

```bash
# ${AGENT_HOME}/.env
SERVICE_API_TOKEN=$(openssl rand -hex 32)
```

And the check that it is actually bound where you think it is:

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep <LISTENER-PORT>
```

If that shows `0.0.0.0:<LISTENER-PORT>` rather than `127.0.0.1:<LISTENER-PORT>`,
the service is exposed to the LAN and should be rebound before you go further.

---

## Part 2 — Webhooks: public ingress for one listener

### 2.1 Decide whether you need a public endpoint at all

A long-poll client holds an outbound connection and needs nothing opened. A
push provider needs a URL.

```bash
# Polling: no listener, no public URL, no certificate to expire.
# Push:    a listener, a public URL, a secret, forever.
```

If the thing you are integrating supports polling, use polling. Stand up a
public endpoint only when the provider genuinely pushes.

### 2.2 Run the listener on loopback

```bash
# Bind to loopback. The funnel proxies to it; nothing else can reach it.
python3 -m http.server <LISTENER-PORT> --bind 127.0.0.1
```

In a real service, the same rule: the listener binds `127.0.0.1`, and the
overlay proxy is the only thing that talks to it.

### 2.3 Expose it — and put the path in the target

```bash
tailscale funnel --bg --set-path=<WEBHOOK-PATH> \
  http://127.0.0.1:<LISTENER-PORT>/<WEBHOOK-PATH>
```

Read that command carefully. The path appears **twice**, and that is not a
typo.

`--set-path=<WEBHOOK-PATH>` is the **mount point** — the prefix the proxy
advertises and strips. The target's path is what the **backend receives**.
Because the prefix is stripped before forwarding, the target must carry the
path too, or the backend receives `/` and answers 404.

| `--set-path` | Proxy target | Path the backend saw |
|---|---|---|
| `/probe` | `http://127.0.0.1:9999` | `/` — prefix stripped |
| `/probe` | `http://127.0.0.1:9999/probe` | `/probe` ✓ |

### 2.4 Two secrets, not one

The path segment is not the authentication. Treat it as a first filter, not a
credential.

- **In the path:** a high-entropy segment, so that a scanner that finds the URL
  still cannot post to it.
- **In the payload:** a signature the sender computes with a shared secret,
  checked on every request. This is the thing that actually authenticates.

```bash
# Generate the path secret. The value is never printed and never stored
# anywhere except the provider's config and this environment file.
openssl rand -hex 32

# ${AGENT_HOME}/.env
WEBHOOK_PATH_SECRET=<generated-value>
WEBHOOK_SIGNING_SECRET=<generated-value>
WEBHOOK_URL=https://<NODE-NAME>.<TAILNET>/<WEBHOOK-PATH>
```

**Never print the value, never commit it, never put it in a URL you paste into
a ticket.** A secret in a URL is a secret in your shell history and in any log
that records the URL.

The listener must fail closed. If the signing secret is missing, refuse to
start rather than accept unsigned requests.

### 2.5 Verify from a network that is not yours

This is the test that actually proves the webhook works, and it is the one
people skip.

```bash
# From a phone on cellular data, or from a browser on a different network:
curl -sS -o /dev/null -w '%{http_code}\n' "https://<NODE-NAME>.<TAILNET>/<WEBHOOK-PATH>"
```

Then check what the **backend** saw, not just what the client got:

```bash
tail -20 <LOGFILE>          # the path the handler logged
```

If the client sees 404 and the provider says "registered, no errors", you have
the path-stripping bug from Part 2.3.

---

## Part 3 — The cloud agent and the commons

### 3.1 Enrol the cloud node

```bash
tailscale up
tailscale status
```

The cloud VM joins as a **peer**, not as a client of your machine. A peer can
open a session to a peer; a client cannot.

### 3.2 Authenticate the session with a scoped key

Prefer a key over a password, and scope it to one account on the target.

```bash
# On the target host, authorise the cloud node's key for one account.
# In Tailscale SSH this is a policy statement; in plain SSH over the tailnet
# it is an authorised_keys line with a forced command.
```

Then verify from the cloud side:

```bash
# From the cloud node:
tailscale ping <AMC-HOST>
ssh <AMC-HOST> 'echo tailnet-ssh-ok'
```

**"Ping" and "SSH" are different claims.** The first says the node is
reachable; the second says the credential works. Test both.

### 3.3 Reach the commons files

The commons is a folder on a synced volume. **A synced folder is not a shared
filesystem** — it is one folder on one machine, replicated. The cloud agent
does not mount it, and nothing will make it mount it.

So the agent reaches the files *through the host that owns them*, over the
tailnet:

```bash
# From the cloud node: read the commons as the target host sees it.
ssh <AMC-HOST> 'cat ~/commons/_agent-<name>/memory.md'
```

For writes, the same path with the same discipline — one agent, one subspace:

```bash
ssh <AMC-HOST> 'cat > ~/commons/_agent-<name>/handoff.md' < local.md
```

> **Scope the writes.** The commons's isolation is a directory boundary: each
> agent writes only to `_agent-<name>/`. A cloud agent with unrestricted write
> access to the host has no boundary at all, and that is the moment the
> convention stops being a convention. Give the cloud identity write access to
> the subspaces it needs and nothing else.

### 3.4 Reach the LAN-only services

The services behind the host are LAN-only by design. Do not move that boundary
— tunnel to the host and let the host forward.

```bash
# From the cloud node: a local port that lands on the host's LAN.
ssh -N -L 127.0.0.1:<LOCALPORT>:127.0.0.1:80 <AMC-HOST>

# Then call it as if it were local.
curl -sS http://127.0.0.1:<LOCALPORT>/v1/models \
  -H "Authorization: Bearer $SERVICE_API_KEY"
```

The LAN service keeps answering on the local network, to a connection that now
originates somewhere else. Nothing about the service had to change, and no
port was opened.

**A credential that crosses the tunnel is still a credential.** Read it
transiently into an environment variable for the one command that needs it,
and unset it afterwards:

```bash
export SERVICE_API_KEY="$(ssh <AMC-HOST> 'cat ~/secrets/service_api_key')"
curl -sS http://127.0.0.1:<LOCALPORT>/v1/models -H "Authorization: Bearer $SERVICE_API_KEY"
unset SERVICE_API_KEY
```

Do not write it to a file on the cloud node. Do not put it in the command
line of a long-running process. Do not print it.

### 3.5 The hybrid case, end to end

**A real deployment.** The author's personal agent, *Pax*, runs in *Muse* — a
hybrid platform whose core is a cloud VPS and whose desktop client runs on the
author's machine. The core holds the agent's context; the client has the
author's files. The two halves need each other.

After the VPS joined the tailnet and key-based access was authorised:

```bash
# On the VPS — the tailnet path to the author's machine.
ssh <AMC-HOST> 'echo tailnet-ok'

# On the VPS — a tunnel to the LAN-only inference service behind it.
ssh -N -L 127.0.0.1:<LOCALPORT>:127.0.0.1:80 <AMC-HOST>

# On the VPS — the inference call, with the key read transiently.
export SERVICE_API_KEY="$(ssh <AMC-HOST> 'cat ~/secrets/service_api_key')"
curl -sS http://127.0.0.1:<LOCALPORT>/v1/chat/completions \
  -H "Authorization: Bearer $SERVICE_API_KEY" \
  -d '{"model": "<MODEL-ID>", "messages": [{"role": "user", "content": "hello"}]}'
unset SERVICE_API_KEY
```

The verification that matters is a **round trip with a checksum**, not a
`200 OK`:

```bash
# Write a file on the cloud side, pull it across, and compare.
ssh <AMC-HOST> 'cat > /tmp/transfer-check.bin' < /tmp/local-copy.bin
shasum -a 256 /tmp/local-copy.bin
ssh <AMC-HOST> 'shasum -a 256 /tmp/transfer-check.bin'
```

Two matching digests prove the path moved the bytes you meant it to move. A
successful connection proves only that something answered.

**What this does not change.** The cloud half still runs in someone else's
infrastructure. The overlay network makes the network path private and
authenticated; it does not make the machine yours, and it does not make the
vendor's storage of your conversation history private. If the platform stores
history in its cloud, the device is private-compute with cloud-backed storage,
not fully local — and the article should say so rather than let the word
"private" do all the work.

---

## Part 4 — Healthchecks

### 4.1 The three questions

Every path in this design needs three separate checks, and a check that
answers one of them does not answer the others.

| Question | Check | Reads as |
|---|---|---|
| Is the node on the network? | `tailscale status --json` → `BackendState`, `Self.Online` | The node is enrolled and connected |
| Does the path answer? | `tailscale ping <peer>`; resolve the name; open the port | The route works |
| Does the service answer? | request the exact advertised path and read the response | The thing users depend on works |

And the fourth, which is the one that catches the most incidents:

| Is the configuration still pointing at the right name? | compare the serve/funnel hostname against `Self.DNSName` | The exposure is not stale |

### 4.2 The script

```bash
bash scripts/check-tailnet-health.sh
```

It is read-only. It reports `OK` / `WARN` / `FAIL` per check, never prints a
secret value, and exits non-zero when it finds something. Checks:

1. Tailscale CLI present, node enrolled, backend state healthy
2. The overlay node name differs from the OS hostname
3. The serve/funnel configuration is keyed to the **current** node name
4. The tailnet names resolve, and a peer answers
5. A public exposure, if any, actually answers — and carries a path segment
6. The listener is bound to loopback, not to every interface
7. The commons path is present on this host and readable
8. Every public exposure is accounted for

### 4.3 Run it on a schedule

```bash
# Every fifteen minutes, quietly, with the exit code preserved.
*/15 * * * * /path/to/check-tailnet-health.sh >/dev/null 2>&1
```

A healthcheck that only runs when you think something is wrong is a debugging
tool, not a healthcheck. Schedule it, and make the scheduler care about the
exit code.

If you use a monitoring service, the check should be an endpoint it can poll
rather than a cron job whose output nobody reads. The script's output is
deliberately shaped for that: one line per finding, a summary, and an exit
code.

### 4.4 What to do when it fails

Work down the list, in order:

| Finding | First thing to check |
|---|---|
| Node not enrolled / backend unhealthy | The overlay service on that machine |
| Node name equals the OS hostname | The separation from §1.2 — before anything else |
| Serve/funnel keyed to a stale name | Whether the node was renamed since the config was written |
| Name does not resolve | Whether the tailnet DNS is answering, then the name itself |
| Peer does not answer | ACLs first, then the peer, then the network |
| Public exposure does not answer | Whether anything is listening behind it — and close it if not |
| Listener bound to `0.0.0.0` | Rebind to `127.0.0.1`; do not rely on the host firewall |
| Commons path missing | Whether the host is the one that owns it |

---

## Part 5 — End-to-end checklist

**The estate**

- [ ] Every participating machine is enrolled as a node
- [ ] Each node has a deliberate, stable name
- [ ] The overlay node name differs from the OS hostname, and the OS hostname
      is pinned
- [ ] Every local service binds `127.0.0.1`, not `0.0.0.0`
- [ ] The host firewall is not carrying the security burden

**Webhooks**

- [ ] Polling was ruled out before a public endpoint was created
- [ ] Exactly one listener is public, on its own port, with its own secret
- [ ] The advertised path also appears in the proxy target
- [ ] The path carries a high-entropy segment, and the payload carries a
      signature
- [ ] The endpoint was verified from a network that is not yours
- [ ] The backend was verified to have received the advertised path
- [ ] The secret is in an environment file, never printed, never committed

**The cloud agent**

- [ ] The cloud node is enrolled as a peer
- [ ] The session is authenticated with a scoped key, and both a ping and an
      SSH round trip have been tested
- [ ] The agent reaches the commons through the host that owns it
- [ ] The agent's write access is scoped to the subspaces it needs
- [ ] LAN-only services are reached by tunnelling to the host
- [ ] Credentials crossing the tunnel are read transiently and unset

**Health**

- [ ] The healthcheck exercises the path, not the process
- [ ] It runs on a schedule, and the exit code is acted on
- [ ] Fallback usage is logged, so a silent switch to a paid endpoint is visible
- [ ] Retired transports are closed and the exposure list is audited

**Privacy**

- [ ] Nothing published names your devices, your tailnet, your nodes, your
      network, or your personal files

---

## Part 6 — Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| Webhook stopped after a rename | Serve config keyed to the old node name | Compare the funnel hostname against `Self.DNSName` |
| Webhook registered, every request 404s | Proxy stripped the path | Put the path in the target as well |
| Cloud agent cannot reach the host | Not enrolled, or the ACL denies it | `tailscale status`, then the policy |
| Cloud agent reaches the host, sees no files | A synced folder is not a shared filesystem | Reach the files through the host |
| LAN service unreachable from the cloud | No tunnel, or the service is bound to loopback | The tunnel, and the bind address |
| Everything healthy, agent still not working | The check tested a process | Exercise the path |
| Duplicate replies on one bot | Polling and push both active | One transport per endpoint |
| A stale public URL still resolves | The transport was retired, the exposure was not | Close it, audit on a schedule |
| Machine renames itself on wake | OS hostname and overlay node name collide | Separate them, pin the OS names |

---

## Related

- [PATTERN.md](./PATTERN.md) — the reasoning behind every step here.
- [Remote Agent Access](../remote-agent-access/IMPLEMENTATION.md) — the
  chat-platform transport, which needs no public endpoint at all.
- [Agent Memory Commons](../agent-memory-commons/IMPLEMENTATION.md) — what
  lives in the commons the cloud agent is reaching.
- [Bot Identity](../bot-identity/PATTERN.md) — scoping the credentials these
  paths carry.
