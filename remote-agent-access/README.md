# Reaching an Agent on Your LAN From Anywhere

**You built something useful on a machine at home. You are at work, and you
want to use it.**

Most answers to that problem go in the wrong direction. They open a port.
They tunnel a service. They put a hostname on your home network and give it
to the internet — and they leave an exposed surface on a device that sits
inside your walls, reachable by anyone who finds the address.

There is a better move, and it is the one this article is about.

**Keep the agent at home. Reach it with something that was already built to
be reached.**

Your messaging app already solved the hard parts: identity, encryption,
device trust, rate limiting, a web client that works from any browser on any
network, and a notification path to your phone. A chat bot turns all of that
into a remote control for an agent that never leaves your LAN.

The traffic is a conversation, not a connection to your infrastructure. Your
machine dials out to the messaging platform and holds the line open. Nothing
dials in. There is no inbound port to scan, nothing to authenticate at the
boundary, and nothing for a scanner to find.

## The three planes

The design that results has three separate planes, and the most common
mistake is to blend them:

| Plane | Direction | What crosses it | Where it fails |
|---|---|---|---|
| **Control** | You → agent | A conversation: prompts, files, results | The chat gateway is a process, and processes die |
| **Compute** | Agent → LAN appliance | An OpenAI-compatible API call, inside your network | Silently falls back to a paid API and you never notice |
| **Trust** | Agent → cloud model | The frontier reasoning you actually want to pay for | Local work started costing per-token money |

The middle plane is where the real trap is. An agent that cannot reach the
appliance it is supposed to be using **will not fail** — it will quietly
substitute the cloud model, complete the task, and send you an invoice. That
failure is silent, it is expensive, and it does not appear in a log unless
you go looking for it.

## Why routing is what makes it worth doing

Reaching a home server from a phone is not interesting. Plenty of tools do
that.

The interesting part is what you can now do from the phone that you could not
do from the desk. A local inference appliance holds an entire model library,
and models on it are not charged per token. An agent that can route work to
the appliance gets a different cost profile entirely: the research sweep that
would have cost real money is free on local silicon, the bulk classification
of thousands of files is a throughput problem rather than a reasoning
problem, and a long job does not have to fit inside a request timeout because
it is not inside a request.

Access and compute are the same pattern. You reach the agent from the phone;
the agent farms the work to the appliance; the appliance does the part that
does not need judgement.

And because the agent is on your LAN, the LAN itself becomes a private
workspace it can work in on your behalf — your files, your services, your
devices — with the chat app as the remote control for all of it.

## What this article covers

| Document | What it covers |
|---|---|
| [PATTERN.md](./PATTERN.md) | The portable pattern: why a chat platform is the right remote control, the three planes, six design rules, six failure modes with their real symptoms, and a reference checklist. Read this for the mental model. |
| [IMPLEMENTATION.md](./IMPLEMENTATION.md) | The concrete setup: the gateway, the polling transport, the alternate webhook transport, the appliance and routing configuration, the appliance lock, and an end-to-end setup checklist. Read this if you are going to build it. |
| [scripts/check-agent-reachability.sh](./scripts/check-agent-reachability.sh) | A read-only checker for the six things that break this setup: gateway liveness, chat connection state, appliance reachability, routing configuration, credential placement, and stale public exposures. Prints findings, never secret values. |

## Audience

This article is for someone running an agent on a machine they control, who
wants to reach it from elsewhere, and who would rather not open a port to do
it.

Specifically:

- People running a local inference appliance, a home server, or a self-hosted
  model library on a network they own
- Operators of **Hermes** or comparable agent runtimes, in particular anyone
  using the messaging gateway with Telegram, Discord, Slack, or WhatsApp
- Anyone routing delegated work between a paid frontier model and local
  hardware, and worried about how to tell which one actually ran
- Teams that have an agent on a server and a colleague on a laptop who wants
  to use it

If you have no local compute and no concern about per-token cost, this is
more machinery than you need — point your agent at a cloud model and skip to
the end.

## The one-line version

Keep the agent at home. Reach it with a chat bot. Point its bulk work at the
hardware you already own. Make the fallback visible. Close the ports you no
longer use.

---

## Related articles

- [Bot Identity](../bot-identity/) — one credential per bot. The chat token
  that makes this pattern work is a full credential, and this article scopes
  it the way that article argues it should be scoped.
- [Tiiny Model Routing](../tiiny-model-routing/) — choosing and loading the
  right model for each subtask, and the appliance lifecycle that constrains
  it. The compute plane in this article depends on it.
- [Agent Memory Commons](../agent-memory-commons/) — giving several agents a
  shared memory, so the agent you reach from your phone knows what the agent
  at your desk knows.
