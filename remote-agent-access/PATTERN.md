# Reaching an Agent on Your LAN From Anywhere

## The shape of the problem

You have a machine at home. It holds something worth reaching — a local
inference appliance, a box of models, a data set, a build agent. And you want
to use it from somewhere that is not home.

The instinct is to expose it. Open a port, put it behind a hostname, point a
VPN at it, tunnel it through a service that relays HTTP. That instinct is
how home servers end up in breach notifications: every one of them is a
device that trusted a piece of paper about what the internet looks like.

There is a different move available, and it is the one this article is about.

**Put the agent where the agent already is, and reach the agent with something
that is already designed to be reached.**

That is the whole pattern. The agent stays on the LAN. The compute stays
local. What crosses the internet is a **conversation**, not a connection to
your infrastructure.

## Why a chat platform is the right remote control

Most remote-access designs answer the question "how do I open a channel to my
server?" The chat-platform design answers a different question: "how do I
reach my agent, wherever my agent already runs?"

A messaging bot is the rare piece of software that is *already* built for
this. It has:

| Property | Why it matters here |
|---|---|
| **Identity already solved** | The platform handles sign-in, device trust, session revocation. You do not build an auth layer for your home server. |
| **Already reachable** | It has a web client. A browser on any work machine, any network, is a terminal for your agent. No VPN client, no tunnel, no port. |
| **Already encrypted** | Transport security is the platform's problem, and it is a problem they have solved properly. |
| **Already rate-limited and monitored** | Abuse controls exist without you writing them. |
| **Already has a notification path** | The agent can answer you on the phone. |

Read that table again from the other direction. Every row is a piece of
security engineering you would otherwise have to do yourself, on a device
that sits inside your home network, to expose a model server.

The traffic pattern is what makes it safe. Consider what actually crosses the
network boundary:

```
   your agent (on the LAN)  ──── outbound HTTPS ────>  chat platform
        ▲                                                  │
        └────────── your message, back the same way ◄─────┘
```

**The connection is outbound and long-lived.** Your machine dials the
platform and holds the line open. The platform never connects *to* you. There
is no inbound port on your network, no listener, nothing for a scanner to
find, and nothing to authenticate at the boundary because the boundary is
never crossed.

This is the same shape as a phone call, and the comparison is exact. A phone
does not expose an inbound port to the exchange. It registers with it, and
the exchange calls back over a connection the phone opened. You have been
using this pattern your entire life without thinking about it, because it is
how the ordinary world stays connected without anyone writing a firewall
rule.

## The three planes

The system that results has three distinct planes, and the most common
architectural mistake is to conflate them.

| Plane | Direction | What crosses | Failure mode when wrong |
|---|---|---|---|
| **Control** | You → agent | A conversation. Prompts, files, results. | — |
| **Compute** | Agent → LAN appliance | An OpenAI-compatible API call on the local network. | Token spend on a paid API, or an appliance you cannot reach |
| **Trust** | Agent → cloud model | The frontier model that does the reasoning. | Your reasoning happening somewhere you cannot see it, at a per-token price |

Each plane can fail, and each fails differently.

The **compute plane** is the one that is easy to get wrong. An agent that
cannot reach the appliance it is supposed to be using will not fail — it will
happily substitute the cloud model and complete the task, and you will pay
per token for work you already own hardware to do. That failure is silent,
it is expensive, and it will not show up in a log unless you go looking for
it. So the design has to make the local path the *default* and the paid path
the *fallback*, and it has to be visible which one ran.

The **trust plane** is where judgement happens. Bulk work — indexing a
directory, sweeping a web, classifying a corpus — does not need frontier
reasoning and should not pay for it. That is the routing decision, and it
belongs to the same skill that owns the appliance, because the router and the
device have to be managed together. When the appliance swaps models, the
router's view of what is resident has to change with it.

## Routing is what makes the appliance worth having

Reaching your LAN from a phone is not the interesting part. Plenty of tools
do that. The interesting part is what you can now *do* from the phone that
you could not do from the desk.

A home inference appliance holds an entire model library. Models on that
appliance are not charged per token. So an agent that can route work to the
appliance has a fundamentally different cost profile from one that cannot:

- A research sweep that would cost real money on a frontier API is free on
  local silicon.
- A bulk classification of thousands of files is a throughput problem, not a
  reasoning problem — exactly what a local appliance is for.
- A long-running job does not have to fit inside a request timeout, because
  it is not inside a request.

So the access pattern and the compute pattern are the same pattern. You reach
the agent from the phone; the agent farms the work to the appliance; the
appliance does the part that does not need judgement. The phone is a
**terminal for the router**, and the router is what turns "I can reach my
server" into "my server is worth reaching."

There is a second-order effect that matters just as much. When the appliance
is on your LAN and the agent can reach it, the *agent itself* can be on your
LAN too — no inbound exposure of any kind — and the LAN becomes a private
workspace the agent can work in on your behalf. Local files, local services,
local devices. The chat platform is the remote control for that whole
workspace.

## The design rules

### DR-1: The agent dials out. Nothing dials in.

The working path is an outbound, long-lived connection from your machine to
the chat platform. Do not add an inbound listener to make it "more
responsive" unless you have measured a problem that only inbound solves.

If you find yourself opening a port, you have changed the pattern. The
question to ask is: *which piece of my design would break if this port did
not exist?* If the answer is "none," close it.

### DR-2: Keep the compute plane on the LAN, and make the fallback visible.

The appliance is addressed by a LAN-resolvable name and a bearer that never
leaves the machine. The agent's config points at the local endpoint. The
cloud model is the fallback, not the default.

**Make the routing decision observable.** A run that quietly fell back to the
paid API is a run you are paying for and did not know about. Log which
provider served which task. If the log line does not say, the system is
lying to you by omission.

### DR-3: One credential per bot, and scope it to the chat.

The bot token is a full credential: it speaks for the agent, and anyone
holding it can act as the agent. It belongs in the environment file, never
in a config file that gets shared, never in a repository, never in a
published article.

Scope it further where the platform allows it: an allow-list of user IDs
means an unknown number cannot drive your agent even if they find the bot.
This is the difference between "a bot that is on the internet" and "a bot
that talks to you."

See [Bot Identity](../bot-identity/PATTERN.md) for the full argument on
per-bot credentials — this article assumes it.

### DR-4: The appliance is a shared resource with one writer.

An inference appliance with a fixed memory pool does not host two models at
once. Loading a model evicts whatever was resident. So the appliance needs a
**lock**: a holder mechanism that keeps a deliberately-loaded model resident
while a background supervisor wants to reload its own set, and a restore step
that puts the expected model back when the work is done.

Without it, the failure is intermittent and maddening: a delegated child
runs for four minutes and then gets a 404 from the appliance, which means
*not resident*, not *wrong model*. The 404 is the symptom. The cause is two
supervisors disagreeing about what should be loaded.

### DR-5: The delivery path and the trigger path are different mechanisms.

Once an agent runs on a server, two different things want to happen:

1. **You want to talk to it** (the control plane) — long polling on a chat
   platform. This is the pattern above.
2. **Other services want to trigger it** (GitHub, Stripe, a monitor, a
   sensor) — inbound HTTP POSTs with a signature.

These are genuinely different problems and conflating them is what produces
the mess. Polling has no inbound listener and no public URL. Webhooks need a
public URL and an authenticated request path.

**Do not put a webhook on the chat platform's path.** If you want inbound
triggers, give them their own listener, with its own HMAC secret, its own
port, and their own reachability mechanism — and leave the chat path alone.
A tunnel that exposes one service should not be asked to expose two.

### DR-6: The appliance's identity on the LAN is not a secret, but treat it as one anyway.

A hostname that resolves only inside your network discloses that you run
that device, and to whom. It is not a credential. But an article that names
your device, your tailnet, and your network tells a stranger which three
strings to try. Publish the shape of the design, not the identifiers of your
installation.

## Failure modes

| # | Failure | What you see | Why it happened | Fix |
|---|---|---|---|---|
| 1 | Agent is unreachable from outside | Works on the LAN, silent from the phone | The gateway is not running, or the chat platform session is not connected | The control plane is a *process*, not a config. Supervise it; check connection state, not just that the process exists. |
| 2 | The appliance is on, but the agent uses the cloud model anyway | Task completes, token bill rises | The appliance was unreachable, so the fallback fired silently | DR-2. Log the provider per task, and alert on fallback usage. |
| 3 | Delegated child returns a 404 | `404` from the appliance | The model is not resident — a supervisor evicted it | DR-4. Not-resident and bad-model look identical from the client's side; the client cannot tell them apart. |
| 4 | Bot answers, but as the wrong agent | Replies from an unexpected personality | Two gateways claimed the same bot token | DR-3. One token, one gateway. See Bot Identity. |
| 5 | Duplicate replies | Every message answered twice | Polling and a webhook were both active on the same bot | DR-5. One transport per bot. Telegram refuses both at once, which is a useful error, but only if you read it. |
| 6 | The tunnel is on, serving nothing | A public URL resolves to a dead port | A transport was retired and the exposure was left behind | Close what you no longer use. An open port to nothing is still an open port. |

Failure 6 is worth dwelling on, because it is the one you are most likely to
inherit rather than create. **Replacing a transport leaves the old exposure
behind.** The Funnel is on, the certificate is valid, the URL resolves — and
nothing is listening. It is harmless today and a liability the moment
something else binds that port. Audit exposures on a schedule, not on the day
you notice them.

## The checklist

- [ ] The chat gateway runs as a supervised service and reports a *connection*
      state, not merely a running process.
- [ ] The agent can reach the appliance by a LAN-resolvable name, with a
      bearer that exists only on the host.
- [ ] The local endpoint is the default; the cloud model is an explicit
      fallback, and fallback use is logged and alertable.
- [ ] The bot token is in the environment file, is per-bot, and is scoped to
      an allow-list of user IDs.
- [ ] The appliance has a holder mechanism that survives the background
      supervisor, and a restore step that runs after every delegated job.
- [ ] The delivery path and the trigger path use different mechanisms, on
      different ports, with different credentials.
- [ ] Every public exposure — tunnel, funnel, reverse proxy — has an owner
      and a reason. Anything without one is closed.
- [ ] Nothing published names your device, your network, or your tailnet.

## What this article does not cover

- **Multi-agent coordination.** One agent, one appliance.
- **Voice and other modalities.** The control plane is text; the pattern
  generalises, but the details do not transfer directly.
- **Webhook triggers in depth.** Covered as a distinct mechanism in DR-5 and
  in the implementation guide, not as the subject of this article.
- **Multi-profile gateways.** Running several independent agents on one host
  changes the credential story considerably.

## Related

- [Tiiny Model Routing](../tiiny-model-routing/PATTERN.md) — choosing and
  loading the right model for a subtask, and the appliance lifecycle that
  constrains it. This article's routing plane depends on it.
- [Bot Identity](../bot-identity/PATTERN.md) — one credential per bot, and
  why the chat token in DR-3 is scoped the way it is.
