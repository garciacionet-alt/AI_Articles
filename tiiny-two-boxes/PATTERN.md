# Two Tiiny Boxes, One System — The Pattern

## The pattern in one paragraph

Two appliances, one system. Each box has **its own address, its own
credential, its own shared state, and a fixed role**. The role split is
what makes the pair worth more than either box alone: one box holds the
models that must always be there, the other holds the models that are
loaded on demand. Nothing about the silicon changes — the catalogue is
identical on both — and everything about the *wiring* does.

## The four properties a second box requires

A second box is not useful the moment it powers on. It becomes useful when
four properties hold, and each one is a place where the obvious approach is
wrong.

### 1. Each box is addressed by its own address

Not by the vendor's hostname. The vendor hostname resolves to a forwarder in
the desktop application, and that forwarder serves **one box at a time**,
following whichever box the application has selected. It also rejects a
client-supplied credential outright.

So the client is configured with the box's own network address, and the box
is given a DHCP reservation so the address does not move. This matters more
than it looks: a client pinned to an address the router later reassigns does
not fail loudly. It falls back to whatever the caller had as a fallback —
usually a paid API — and the failure is a bill rather than an error.

### 2. Each box has its own credential

Credentials are issued per device. The credential for one box does not open
another, and there is no account-level key that opens both. What looks like
an account key — the one a credential command prints alongside the
per-provider base URLs — is still scoped to the device whose address you
asked for.

This is the property that makes the second box a *separate* thing rather
than a second view of the first, and it is why the credentials live in
separate environment variables rather than one shared one.

### 3. The control session is one slot, not one per box

This is the trap a two-box article usually gets wrong, because it is
counter-intuitive: the control CLI keeps **one session**, and the most
recent sign-in owns it. Sign in to the second box and the first box is
signed *out* — not merely unreachable, signed out. Point the CLI at the
other address and it reports itself signed out even though the account
session is perfectly valid.

So the CLI can manage exactly one box at a time, and moving the session
between boxes is a human step: a sign-in, with a code. Two consequences
follow, and both are design decisions rather than workarounds:

- **Serve from both, manage one at a time.** Each box's API credential is
  independent, and both boxes serve inference at the same time. Only the
  control path — load, unload, download — is limited to whichever box
  holds the session.
- **Every control call must name its device.** A controller that invokes
  the CLI without naming the address lands on whichever box the CLI
  configuration happens to point at. In a fleet, that is how the wrong
  appliance gets loaded, quietly.

And note what the control session is for. **Serving and loading are
different paths.** A model that is already running answers requests
immediately — no control session, no login, nothing. The session is
required only to load, unload or download, and the device's own HTTP API
does not expose a load route at all. Logging in to serve traffic is a
sign that something else is wrong.

### 4. The shared state is per box

A controller that loads models keeps a lock, a hold, a plan, and a
catalogue snapshot. One set of those for two boxes means:

- two agents, one on each box, contend for one lock — so one of them can
  swap a model out from under the other's child;
- a catalogue refresh on one box replaces the other's baseline, so the next
  diff reports a model-store change that never happened to either box.

Make all four paths per device, with the environment as the switch.

**The exception that matters:** the box whose *default* paths the scheduled
jobs and the other agents already use must keep using the defaults. Two
agents sharing one pool must share one lock. The second box gets its own
paths because it is a different pool with a different lock. Per-device
state is not "give every box a suffix" — it is "each pool has one lock,
and the pool's regulars know where it is".

## The role split, and why it follows from stock

The two boxes carry the same models. What differs is **which ones are on
disk**, and that is what decides the roles:

- **The vault box** holds the models that must always be resident: the
  generalist, the small index model, the embedding models. It is pinned.
  Something always needs the generalist, so nothing is ever loaded over it.
- **The flex box** holds the specialists: research, code, browser, draft,
  the heavy solo models, the image models. The router loads what the batch
  needs here, and the vault box never has to give anything up.

The rule generalises: **the box you never swap is the one you keep warm,
and the box you swap is the one that holds the things you swap to.** Stock
follows role; the role follows what the work actually demands.

The measured case: one box carried sixteen models, the other forty-two, and
the forty-two included every specialist in the routing tier. Same catalogue,
same NPU figures, different roles.

## What generalises past one appliance

Nothing in this pattern is specific to a vendor. It applies to any fleet of
local accelerators where **a load is a swap**:

| Property | One device | A fleet |
|---|---|---|
| Endpoint | one address | one address per device |
| Credential | one | one per device |
| Control session | one | one slot — the most recent sign-in owns it |
| Lock / hold / plan | one set | one set per pool |
| Residency | one shared pool | one pool per device, one role each |

A fleet is not "more capacity". It is **more pools, and therefore more
things to address, authenticate and lock** — plus the one thing that makes
it worth having: a device that never has to surrender the model it is
holding.

## Failure modes

| Symptom | What it actually is |
|---|---|
| The client answers 401 against a box that is clearly on | The credential belongs to the other box. Credentials are per device |
| The control CLI says "not signed in" for a box you just used | One session slot: the second sign-in signed the first box out |
| A load reports success and the model is still absent | The control session was not authenticated; nothing loaded, and the child silently falls back |
| A load does nothing at all, with no error | The control CLI opens a terminal for its prompts; from a script it fails on that and nothing becomes resident |
| A download lands and the CLI dies with a Go deadlock | The transfer worked; the CLI's progress reporter deadlocks afterwards and the command exits non-zero. The device's own catalogue status is the truth |
| The client works, then a different box's models appear | The client is pointed at the vendor hostname. Address the boxes directly |
| Two agents evict each other's models | They share one lock file. One lock per pool |
| A catalogue diff reports models that vanished | One snapshot file for two devices. One snapshot per device |
| A box's models appear to be missing | A storage endpoint reported zero bytes while models were resident. Read the per-model status, not the storage total |
| A box answers but a renamed one does not | The display name is a label. Key everything on the device id |
| The first command against a new client fails, silently, and costs money | The provider was pinned to an address that moved. Reserve the address |

## The rule that keeps this from rotting

**A load must never be reported as successful unless the model is
resident.** The failure this prevents is invisible by construction: the
child gets a 404, the caller treats it as terminal, and the request is
answered by the paid provider instead. No error appears anywhere. A
controller that says "loaded" and "not resident" in the same breath is
worse than one that says neither.
