# A Private Network for Your Agents

## The shape of the problem

Your agent estate has quietly acquired two kinds of machine.

The first is the one on your desk: it holds the files, the vector database, the
local models, the notes. The second is the one in someone else's cloud — a VPS
where the agent's core actually runs, because that is where the vendor puts it.

That second machine is the interesting one. An agent whose core is a cloud VM
is not in a data centre you control, and it is not behind your router. It has no
mount of your files, no route to your LAN, and no way to reach the commons where
your agents share what they have learned.

So you are left with two gaps, and they are not the same gap:

1. **Something outside has to push to you.** A GitHub webhook, a Stripe event,
   a monitor, a sensor. These arrive as inbound HTTP POSTs. They need a public
   URL and an authenticated request path.
2. **Your cloud agent has to reach your files.** The commons lives on your
   machine. The agent runs in a VPS. One of them has to move.

The tempting answer to both is a tunnel. Open a port, forward it, let the
internet route to it. That is how private things end up in breach
notifications, and the second gap is worse than the first: the first gap is a
narrow path you can point at one listener, while the second gap, done naively,
means the whole commons becomes reachable from a machine you do not administer.

There is a different move, and this article is about it.

**Put the machines on a private network, and let reachability be a property of
the network rather than a property of each service.**

## Three classes of reachability

Most of the difficulty in this problem comes from treating "reachable" as one
thing. It is three, and they have different costs and different blast radii.

| Class | Who can reach it | How | Cost | Use it for |
|---|---|---|---|---|
| **Local** | Your LAN only | A LAN-resolvable name | Free | The appliance, the local model server, anything that has no reason to leave the building |
| **Tailnet** | Machines you enrolled | An overlay network with its own names | A VPN client per machine | The commons, the vector database, the agent's control plane, anything private |
| **Public** | Anyone who finds the URL | A funnel or a reverse proxy | A secret in the request path, forever | A webhook listener, and nothing else |

The mistake that costs money is using the third class for something that
belongs in the second. The commons does not need to be public. A vector
database certainly does not. An agent that reads and writes your files does not.
The only thing in this list that genuinely has to be reachable from the open
internet is a webhook endpoint — because the service sending it is somebody
else's computer and you do not control their network.

**So the rule is short: the commons is tailnet-only, and public ingress is a
per-listener decision rather than a per-machine one.**

## What an overlay network actually buys you

An overlay network is a private address space with its own name resolution and
its own authentication, layered over whatever your machines already use for
connectivity. Tailscale is the one this article is written against; the
properties below are properties of the approach, not of the product.

Four things come with it:

- **A name that means something.** The tailnet has its own DNS, so a node can
  have a stable, meaningful name that is not your router's DHCP assignment and
  not the name of your local network.
- **Authentication at the network layer.** A machine that is not enrolled cannot
  open a session to one that is, whatever port it wants. The ACLs are the
  policy, and they live in one place instead of in every service's auth config.
- **Reachability across NAT.** Neither side needs a public address or an
  inbound port. The connection is made from wherever the machine can reach the
  internet.
- **An explicit public door.** The same tool that opens a private path can open
  a public one, for named listeners only, and the list of what is open is
  something you can read.

That last point is the one people miss, and it cuts both ways. The ability to
expose a service publicly *deliberately, one listener at a time* is what makes
the overlay approach workable for webhooks at all. It also means the tool
cannot be trusted with a blanket "expose this machine" setting.

## The two gaps, solved differently

### Gap one — the third party has to push to you

A webhook is a stranger knocking on your door with a signed envelope. They
cannot join your tailnet. They need a public URL, and the endpoint has to
authenticate them.

Three things have to be true, and they are separate:

1. **The URL resolves.** And it resolves *now* — not the URL you configured
   three months ago, before you renamed something.
2. **The path is right.** Not the path in the advertisement; the path the
   backend actually receives.
3. **The request is authenticated.** A secret in the path is not enough on its
   own; the payload needs a signature the sender computes with a shared secret.

Point 2 is where this goes wrong in practice, and it goes wrong *silently*,
because the proxy is doing exactly what it was told. A path prefix on a reverse
proxy is a **mount point, not a rewrite**. The proxy strips the prefix before
forwarding. So a listener configured at `/telegram`, proxied to
`http://127.0.0.1:8443`, receives the request at `/` — and answers 404, while
the advertised URL looks perfect, the provider reports the webhook as
registered with no errors, and the service logs a healthy connection.

The rule is simple and worth writing on a wall: **if the path is in the
advertised URL, it must also be in the proxy target.** Measured, on a live
deployment:

| Advertised path | Proxy target | Path the backend saw |
|---|---|---|
| `/probe` | `http://127.0.0.1:9999` | `/` — prefix stripped |
| `/probe` | `http://127.0.0.1:9999/probe` | `/probe` ✓ |

### Gap two — your cloud agent has to reach your files

This is the gap that changes the shape of your estate, and it has three layers
of nesting.

```
   your cloud agent (VPS)
          │
          │  ← overlay network, authenticated
          ▼
   your machine (holds the commons)
          │
          │  ← LAN
          ▼
   your LAN-only services (local models, local APIs)
```

Each hop is a separate reachability problem, and each has its own credential.

The outermost hop is the one people are surprised by: **the agent in the cloud
is not in your data centre, so it is not behind your firewall, and it does not
share your filesystem.** It can reach the machine that holds the commons, but
reaching the machine is not the same as reading the files — the files live in a
sync folder, and a synced folder is a folder on one machine, not a distributed
filesystem. The agent's route to the files is through the machine that owns
them, over the overlay network.

The middle hop is usually already solved. If the machine that holds the
commons also holds the LAN-only services, then a tunnel from the cloud agent
to that machine covers both — one authenticated hop, and the LAN boundary
stays where it was.

The innermost hop needs no credentials at all, because it never leaves the
building.

### A hybrid agent, concretely

This is not a hypothetical, and the shape is worth walking through because it
combines every problem in this article.

**A real deployment:** the author's own personal agent, *Pax*, runs in *Muse* —
a hybrid agent platform whose core is a cloud VPS while its desktop client runs
on the author's machine. The core is where the agent's context lives; the
client is where the author's files are. Neither half can do the other's job.

Enabling it over an overlay network took three moves:

1. **The VPS joined the tailnet as a node of its own.** Not as a client of the
   author's machine — as a peer, with its own name and its own identity in the
   network's ACLs. This is the move that decides everything else: a peer can
   open a session to a peer, so the agent can now reach the author's machine
   directly instead of asking a human to carry files across.
2. **The session was authenticated with a key, not a password.** The key lives
   on the cloud side and is scoped to one account on the author's machine.
   Authentication at the network layer means the machine that holds the commons
   does not need a second credential system for the cloud agent — it needs one
   authorized key, and the network's policy says who may use it.
3. **The LAN hop was tunnelled, not exposed.** From the cloud agent, a tunnel
   to the author's machine gave it a path to the LAN-only services behind it.
   The services did not learn that anything new had arrived; they continued to
   answer on the local network, to a connection that now originates somewhere
   else.

After that, the cloud agent could reach the commons and the LAN-only compute,
with no public endpoint and no new listening port on the author's machine.

**What this deployment did not solve, and should not pretend to:** the cloud
half still runs in someone else's infrastructure. The overlay network makes the
*network path* private and authenticated; it does not make the *machine* yours,
and it does not make the data that the vendor's platform stores private. Treat
an inference device that stores its history in a vendor's cloud as
cloud-backed storage with private compute, not as fully local. The overlay
network is one property of the system, not a property of everything downstream
of it.

## The identity trap

There is one mechanism in this article that has nothing to do with networking
and causes more outages than anything else here.

**A tailnet node's name is derived from the machine's operating-system
hostname.** On macOS, the OS hostname and the machine's name on the LAN are
the same fact, and a tunnel interface claims that same display name on the
LAN. The machine then sees its own name claimed twice — once locally, once
through the tunnel — and the local name resolver resolves the duplicate by
renaming the machine, with an incrementing suffix. The rename lands on every
wake and every reboot, because that is when the tunnel comes up and the
resolver re-runs its probe.

And the serve configuration — the mapping from a hostname to a local port, the
thing that makes a webhook URL work — is **keyed by that hostname**. Rename the
node and the configuration does not follow it. The configuration survives the
rename, still advertising the old name, which no longer resolves.

So you get this, and it is very hard to read if you are not looking for it:

| Check | Result |
|---|---|
| The old node name resolves | empty — NXDOMAIN |
| The new node name resolves | an address, correctly |
| The advertised webhook URL answers | nothing at all |
| The tunnel itself | working perfectly the whole time |

**The network was never broken. The configuration was stale.**

The fix is separation, not renaming: **give the overlay node a name that
differs from the OS hostname, and then pin the OS names.** The overlay node
becomes the stable identity that configurations are keyed against, and the OS
hostname becomes something you are free to change without consequence. Do it
the other way round and every OS rename becomes an outage.

This also means the node name is now part of your infrastructure's identity in
a way that matters. It is what your ACLs refer to, what your serve config is
keyed by, and what your healthchecks compare against.

## Healthcheck the path, not the process

This is the part that is easy to skip and expensive to skip.

A process being up is a claim about a process. A connection being established
is a claim about a connection. A file being visible is a claim about a file.
None of them implies the next one, and every one of them is the thing you will
be tempted to check.

| What you checked | What you actually proved | What is still unknown |
|---|---|---|
| The agent process is running | The process started | That it can reach the network it needs |
| The tunnel is up | A tunnel interface exists | That the path through it answers |
| The webhook URL is configured | A string is in a config file | That the provider can resolve it, and that the path survives the proxy |
| The node is in the tailnet | It is enrolled | That it can reach the commons host |
| The commons folder exists | The path is there | That the remote agent can read it |

The healthcheck has to **exercise the path**. For the tailnet: resolve the
name, open a connection, transfer a byte. For the webhook: request the exact
advertised path from outside and get the answer the listener would give. For
the cloud agent's route to the commons: read a file over the tunnel, not
`ls` the path locally.

**And it has to run on a schedule.** A healthcheck nobody runs is a
healthcheck that only reports on the day something has already broken. A
checker that exits non-zero and prints findings — and that a scheduler will
notice — is a healthcheck. One that prints a reassuring summary into a log
nobody reads is a diary.

The script that ships with this article does exactly that: it is read-only, it
reports `OK` / `WARN` / `FAIL` per check, it never prints a secret value, and
it exits non-zero when it finds something.

## The design rules

### DR-1: The commons is tailnet-only.

Never public. Not the vault, not the vector database, not the files, not the
agent's control plane. Public ingress for the commons is not a configuration
choice, it is an incident.

### DR-2: Public ingress is per-listener, never per-machine.

The unit of exposure is one service on one port with one secret. If you can
say "only the webhook listener is public", you have a defensible position. If
you have to say "the gateway is public but the rest is not", you have a
hosting habit, not a policy.

### DR-3: The overlay node name is not the OS hostname.

Separate them, and pin the OS names. Every configuration keyed to the node
name then survives an OS rename, a reinstall, or a DHCP lease change.

### DR-4: A path prefix is a mount point, not a rewrite.

If the path is in the advertised URL, it is also in the proxy target. Verify
by requesting the advertised path from outside and checking what the backend
received.

### DR-5: Polling needs no public endpoint. Only push justifies one.

A long-poll client holds an outbound connection and needs nothing opened. If
you are about to stand up a public endpoint, check that the thing you are
building genuinely cannot be a poll. When it can, polling is the better
answer — it has no URL to leak, no certificate to expire, and no provider-side
registration to go stale.

### DR-6: Healthcheck the path.

Resolve it, open it, read a byte. Never proxy for the state of a process when
the question is whether the path works.

### DR-7: One transport per trigger.

Two transports serving the same bot means duplicate replies, or a conflict
error from the provider that you have to read carefully to understand. Pick
polling or push for a given endpoint, not both.

### DR-8: Close what you retire.

Replacing a transport leaves the old exposure behind — the URL still resolves,
the certificate is still valid, and nothing is listening. An open port to
nothing is harmless today and a liability the moment something else binds that
port. Audit exposures on a schedule, not on the day you notice them.

## Failure modes

| # | Failure | What you see | Why it happened | Fix |
|---|---|---|---|---|
| 1 | Webhook stopped delivering after a rename | The URL does not resolve; the provider reports errors | The serve config is keyed to the old node name and did not follow the rename | DR-3. Separate the node name from the OS hostname, and pin the OS names. |
| 2 | Webhook is registered and healthy, but every request 404s | The provider says "registered, no errors"; the service sees a 404 | The proxy stripped the path prefix, so the backend received `/` | DR-4. Put the path in the proxy target too, and verify from outside. |
| 3 | The cloud agent cannot reach the commons host | Connection refused or timed out | The node is not enrolled, or the ACL does not permit that node to that port | Check enrollment and policy separately — they are different facts. |
| 4 | The cloud agent reaches the host but sees no files | The path is empty or missing | The commons lives in a synced folder on that host; a synced folder is not a shared filesystem | Reach the files through the host that owns them, over the overlay network. |
| 5 | The cloud agent reaches the host but cannot reach the LAN services | The local API does not answer | The LAN-only services answer on the local network; the cloud side needs a tunnel to that host | Tunnel from the cloud agent to the host. The LAN boundary does not move. |
| 6 | Everything reports healthy, and the agent is still not working | Silence, or work completing against the wrong endpoint | The healthcheck checked a process, not the path | DR-6. Exercise the path. |
| 7 | A stale public endpoint is still advertised | The URL resolves and answers nothing | The transport was retired and the exposure was left behind | DR-8. Close it, and audit on a schedule. |
| 8 | The agent quietly used a paid API instead of the local one | The task completed, the bill rose | The local path was unreachable and the fallback fired silently | Log which endpoint served each task. An unobserved fallback is an invoice you find later. |

Failure 1 deserves a second look, because it is the one you are most likely to
**inherit** rather than create. The node was renamed months ago — by an
operating-system update, by a hostname policy, by a repair — and the exposure
was left pointing at the old name. Nothing about it looks wrong from the
inside: the tunnel is up, the service is running, the configuration file has a
valid-looking URL in it.

## The checklist

- [ ] The commons, the vector database, and the agent control plane are
      reachable from the tailnet only. Nothing private is on a public endpoint.
- [ ] Every public endpoint is one named listener with one secret and one
      owner — not a machine, not a port range.
- [ ] The overlay node name differs from the OS hostname, and the OS hostname
      is pinned.
- [ ] Any advertised path also appears in the proxy target.
- [ ] The webhook endpoint is verified by requesting the advertised path from
      a network that is not yours, and the backend is verified to have
      received that path.
- [ ] The cloud agent reaches the commons over the overlay network, with a
      scoped key, and the reachability is exercised rather than assumed.
- [ ] The LAN-only services are reached by tunnelling to the host that owns
      them; the LAN boundary has not moved.
- [ ] A healthcheck exercises every path and exits non-zero on failure, and
      something runs it on a schedule.
- [ ] Every fallback path is logged, so a silent switch to a paid endpoint is
      visible when it happens.
- [ ] Retired transports are closed, and the exposure list is audited on a
      schedule.
- [ ] Nothing published names your devices, your tailnet, your nodes, or your
      network.

## What this article does not cover

- **A hosted agent as the only agent.** If the agent never runs on your
  machines, there is no commons to reach and the problem is ordinary cloud
  access.
- **Multi-tenant networks.** ACL design for a tailnet shared between several
  organisations is a policy exercise of its own.
- **The chat-platform remote control.** That is a different transport with a
  different security argument, and it has its own article — see
  [Remote Agent Access](../remote-agent-access/PATTERN.md).
- **The commons pattern itself.** How a shared file space is organised, and
  what belongs in it, is covered in
  [Agent Memory Commons](../agent-memory-commons/PATTERN.md).

## Related

- [Remote Agent Access](../remote-agent-access/PATTERN.md) — reaching a LAN
  agent with a chat bot instead of a tunnel, and why the two approaches are
  not interchangeable.
- [Agent Memory Commons](../agent-memory-commons/PATTERN.md) — the shared file
  space this network exists to give access to.
- [Bot Identity](../bot-identity/PATTERN.md) — one credential per bot, which is
  what makes a network-level credential story survivable.
