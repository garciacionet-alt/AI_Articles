# A Private Network for Your Agents

**Your agent runs in someone else's cloud. Your files are at home. Neither can
reach the other.**

That sentence is the whole problem, and it is becoming the normal shape of an
agent installation rather than the exception. The vendor's platform hosts the
agent's core because that is where a hosted agent lives. The desktop client
runs on your machine because that is where your files live. The two halves
need each other, and between them there is a network boundary that neither
side controls.

The same setup creates a second gap you did not choose. Something outside has
to push to you — a GitHub webhook, a payment event, a monitor, a sensor. Those
arrive as inbound requests from a stranger's computer, and a stranger's
computer cannot join your private network.

Most answers to both gaps are the same answer: open a port, forward it, let
the internet route to it. It works, and it works right up until the day a
scanner finds it.

## The answer this article is about

**Put the machines on a private network, and let reachability be a property of
the network instead of a property of each service.**

An overlay network gives you authenticated, encrypted reachability between
devices you enrolled, with names that mean something and no inbound ports on
either side. The same tool can open a public door — but only for a named
listener, one at a time, which is what makes it usable for webhooks without
making it dangerous for everything else.

The rule that keeps this safe is short:

> **The commons is tailnet-only. Public ingress is a per-listener decision,
> never a per-machine one.**

Your vault, your vector database, your agent's control plane: private. One
webhook endpoint, with a secret in the path and a signature on the payload:
public. Everything else: private.

## Three classes, not one

Most of the trouble comes from treating "reachable" as a single property. It
is three, and they have different costs:

| Class | Who can reach it | Use it for |
|---|---|---|
| **Local** | Your LAN only | The appliance, the local model server, anything with no reason to leave the building |
| **Tailnet** | Machines you enrolled | The commons, the vector database, the control plane, anything private |
| **Public** | Anyone who finds the URL | A webhook listener — and nothing else |

The mistake that costs money is using the third class for something belonging
in the second. The commons does not need to be public. A vector database
certainly does not.

## The two gaps, solved differently

**A third party has to push to you.** A webhook is a stranger knocking with a
signed envelope. They need a public URL, and the endpoint has to authenticate
them — twice, ideally: a high-entropy segment in the path, and a signature
over the payload.

**Your cloud agent has to reach your files.** And this one has three nested
hops, each with its own credential:

```
   your cloud agent (VPS)
          │  ← overlay network, authenticated
          ▼
   your machine (holds the commons)
          │  ← LAN
          ▼
   your LAN-only services
```

The middle hop is the one people forget: **a synced folder is not a shared
filesystem.** The commons lives in a sync folder on one machine, so the cloud
agent reaches the files *through the host that owns them*, over the network.

## The two traps

Neither of these is obvious, and both are silent.

**The configuration outlives the name.** An overlay node's name is derived from
the machine's operating-system hostname by default, and the serve
configuration that makes a webhook URL work is keyed by that name. Rename the
node — by an OS update, a hostname policy, a repair — and the configuration
survives, still advertising a name that no longer resolves. The network is
fine. The configuration is stale. **Give the overlay node a name that differs
from the OS hostname, and pin the OS names.**

**A path prefix is a mount point, not a rewrite.** The proxy strips the prefix
before forwarding. Advertise `/probe` and proxy to `http://127.0.0.1:9999`, and
the backend receives `/` and answers 404 — while the advertised URL looks
perfect, the provider reports the webhook as registered with no errors, and
the service logs a healthy connection. **If the path is in the advertised URL,
it must also be in the proxy target.**

## Healthcheck the path

A process being up is a claim about a process. A connection being established
is a claim about a connection. A file being visible is a claim about a file.
None of them implies the next one.

The healthcheck has to **exercise the path**: resolve the name, open the
connection, transfer a byte, request the exact advertised path from outside
and read what the backend received. And it has to run on a schedule — a
healthcheck nobody runs is a diary, not a healthcheck.

## A real deployment

This is not a hypothetical.

The author's own personal agent, **Pax**, runs in **Muse** — a hybrid agent
platform whose core is a cloud VPS while its desktop client runs on the
author's machine. The core holds the agent's context; the client has the
author's files.

Enabling it over an overlay network took three moves: the cloud VM joined the
network as a **node of its own** rather than as a client of the author's
machine; the session was authenticated with a **scoped key** rather than a
password; and the LAN hop was **tunnelled rather than exposed**, so the
services behind it kept answering on the local network to a connection that now
originates somewhere else.

After that, the cloud agent could reach the commons and the LAN-only compute —
with no public endpoint and no new listening port on the author's machine.

**What it did not solve, and should not pretend to:** the cloud half still runs
in someone else's infrastructure. The overlay network makes the *network path*
private and authenticated. It does not make the *machine* yours, and it does
not make the vendor's storage of your conversation history private. If the
platform keeps your history in its cloud, the device is private-compute with
cloud-backed storage — not fully local. Say that plainly rather than letting
the word "private" do all the work.

## What this article covers

| Document | What it covers |
|---|---|
| [PATTERN.md](./PATTERN.md) | The portable pattern: the three classes of reachability, the two gaps, the identity trap, healthchecking the path, eight design rules, eight failure modes with their real symptoms, and a reference checklist. Read this for the mental model. |
| [IMPLEMENTATION.md](./IMPLEMENTATION.md) | The concrete setup: enrolling and naming the nodes, exposing one listener, the path-in-the-target rule, authenticating the cloud session, reaching the commons and the LAN services, the healthcheck and how to schedule it, and an end-to-end checklist. Read this if you are going to build it. |
| [scripts/check-tailnet-health.sh](./scripts/check-tailnet-health.sh) | A read-only checker for the eight things that break this setup: enrolment, the node-name collision, stale serve configuration, name resolution, peer reachability, public exposures that answer nothing, a listener bound to every interface, and the commons path itself. Prints findings, never secret values. |

## Audience

This article is for someone whose agents span more than one machine and who
would rather not open a port to make that work.

Specifically:

- People running an agent whose core is a cloud VM while their files are on a
  machine at home
- Operators of **Hermes** or comparable agent runtimes, in particular anyone
  using a messaging gateway with Telegram, Discord, Slack, or WhatsApp
- Anyone who has to accept inbound webhooks and has to decide what that costs
  them in exposure
- Anyone who has been surprised by a service that was configured correctly and
  still did not work

If all your agents run on one machine and nothing outside needs to reach you,
this is more machinery than you need — and the honest version of this advice
is that a long-poll client needs no public endpoint at all.

## The one-line version

Put the machines on a private network. Keep the commons on it and nothing
else. Open one public listener for the one thing that genuinely needs pushing
to you. And check the path, not the process.

---

## Related articles

- [Remote Agent Access](../remote-agent-access/) — reaching an agent on your
  LAN with a chat bot instead of a network, and why the two approaches are not
  interchangeable.
- [Agent Memory Commons](../agent-memory-commons/) — the shared file space this
  network exists to give access to.
- [Bot Identity](../bot-identity/) — one credential per bot. The keys these
  paths carry are real credentials, and that article is about scoping them.
