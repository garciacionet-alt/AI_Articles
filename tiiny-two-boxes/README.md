# Two Tiiny Boxes, One System

**A second appliance is not a capacity upgrade. It changes how the device is
addressed, authenticated and locked, and each of those three has a trap that
stays invisible until a second box exists.**

The sibling article — [Routing Work to the Right
Model](../tiiny-model-routing/README.md) — ends on one hard constraint: NPU
is a single shared pool, a load is a swap, and a batch that needs two
specialists may not be able to hold both. That constraint is real and it is
not solvable inside one box. Adding a second box removes it, and replaces
it with three new ones, none of which are about silicon.

This article is the instruction for doing that: what has to be true of the
appliance before a second one is useful, the order to do it in, and the
specific failures that look like hardware problems and are not.

Everything here was measured on two Tiiny appliances running the same
firmware, on 2026-11-12.

## What a second box actually changes

Nothing about the models. Both boxes ship the same catalogue — the same
model ids, with the same NPU shares and the same context windows. What
changes is the plumbing around them:

| | One box | Two boxes |
|---|---|---|
| Endpoint | one address | one address **per box** |
| Credential | one device-admin bearer | **one per box** — they do not open each other |
| CLI session | one login | **one slot** — the second box's sign-in signs the first one out |
| Load/unload | the only way to change residency | still the only way |
| Lock / hold / plan | one set | **one set per box**, or two agents fight |
| Catalogue snapshot | one file | **one per box**, or a refresh replaces the other's baseline |

The last four rows are the work. The first two are the traps.

## The four traps

**The vendor hostname is not an endpoint.** It resolves to a forwarder in
the desktop application, and that forwarder serves **one box at a time**,
following whichever box the application has selected. It also rejects a
client-supplied credential outright. Address each box by its own network
address, and give it a DHCP reservation — a client pinned to an address the
router later reassigns does not fail loudly, it falls back to the paid
provider, and the failure is a bill rather than an error.

**Every box has its own credential.** There is no account-level key that
opens both. What looks like one — the credential a control command prints
alongside the per-provider base URLs — is still scoped to the device whose
address you asked for.

**The control session is one slot, and the second sign-in takes it.** The
control CLI keeps a single session, and whichever box you signed in to
last owns it — signing in to the second box signs the first one *out*.
That is the trap: sign into both boxes in turn and you end up with one
working box and no error message anywhere. Two consequences follow.
**Serve from both, manage one at a time** — each box's API credential is
independent and both serve inference at once; only the control path (load,
unload, download) is limited to the box holding the session. And **every
control call must name its device** — a controller that invokes the CLI
without naming the address lands on whichever box the CLI config points
at.

Note too that **serving and loading are different paths**: a model that is
already running answers immediately, with no session at all. The control
session is needed by the *CLI*, and the CLI is not the only way to move a
model — the device's own HTTP API does load, unload and download, so a
box that is not the signed-in one can still be managed.

**The shared state has to be per box.** One lock for two boxes means two
agents evict each other's models; one catalogue snapshot means a refresh on
one box replaces the other's baseline. The exception: the box whose default
paths the scheduled jobs already use must keep them, because two agents
sharing one pool must share one lock.

The reasoning behind each is in [PATTERN.md](./PATTERN.md). The step-by-step
setup is in [IMPLEMENTATION.md](./IMPLEMENTATION.md).

## The measured result: identical boxes, different roles

Two appliances, same firmware (`0.1.39`), same platform, 160 BF16 TOPs,
80 GB RAM, 1 TB. Both stores listed **93 models**, and every model in the
routing tier reported the **same NPU share and the same context window on
both boxes**:

| Model | NPU | Context | Model | NPU | Context |
|---|---|---|---|---|---|
| `Qwen/Qwen3.6-35B-A3B` | 47% | 262144 | `openai/gpt-oss-20b` | 27% | 131072 |
| `InternScience/Sage-A1.5-Turbo` | 48% | 262144 | `Qwen/Qwen3.5-9B` | 29% | 131072 |
| `endless-frontier/BigBang-v1-Turbo` | 54% | 131072 | `deepreinforce-ai/Ornith-1.0-35B` | 50% | 131072 |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo` | 55% | 65536 | `Qwen/Qwen3.8-27B` | 52% | 262144 |
| `openai/gpt-oss-120b` | 100% | 131072 | `Qwen/Qwen3-Coder-Next` | 94% | 131072 |

Zero differences. The tier table was measured on one box and confirmed
against the other rather than assumed to fit — which is the only reason it
is safe to use for both.

What differed was **stocking**, and that is what turns two identical boxes
into two roles:

- **The vault box** — the generalist plus the index and embedding models.
  Pinned. Never swapped, because something always needs the generalist.
- **The flex box** — the specialists: research, code, browser, draft, the
  heavy solo models, the image models. The router loads what the batch
  needs here, and the vault box never has to give anything up.

## Quick start

```bash
# 1. declare the boxes (one section each)
$EDITOR ~/.config/hermes/tiiny-boxes.conf

# 2. onboard the second box — interactive, you type your email code
bash scripts/onboard_tiiny_box.sh --device 192.0.2.51 --key-env TIINY_API_KEY_2

# 3. point a provider at each box, then restart the client

# 4. drive either box
bash scripts/tiiny_box.sh vault status
bash scripts/tiiny_box.sh flex  status
bash scripts/tiiny_box.sh flex  ensure --model "Qwen/Qwen3.8-27B"
```

`scripts/tiiny_box.sh` sets the endpoint, the credential and the state paths
for the named box, so the two boxes never contend for one lock. The
declarative form of the boxes file, and the provider blocks that go with
it, are in [IMPLEMENTATION.md](./IMPLEMENTATION.md).

## Getting a model onto a box

Three paths, and only the middle one costs anything:

| Path | Command | Costs |
|---|---|---|
| Download | `POST /api/v1/models/<id>/download` | disk only — no NPU |
| Load | `POST /api/v1/models/<id>/start` | the NPU pool — a load is a swap |
| Serve | the OpenAI-compatible endpoint | nothing; the model is already resident |

**The device's own HTTP API does the lifecycle.** All three are POST/GET on
the device, authorised with the box's bearer — no CLI, no session, no
terminal:

```bash
curl -X POST "http://192.0.2.51/api/v1/models/zai-org/GLM-OCR/download" \
     -H "Authorization: Bearer $TIINY_API_KEY_2"

curl -X POST "http://192.0.2.51/api/v1/models/zai-org/GLM-OCR/start" \
     -H "Authorization: Bearer $TIINY_API_KEY_2"

curl -X POST "http://192.0.2.51/api/v1/models/zai-org/GLM-OCR/stop" \
     -H "Authorization: Bearer $TIINY_API_KEY_2"
```

Two reasons this matters for a two-box setup. **The lifecycle needs no CLI
session**, so a box that is not the signed-in one can still be loaded,
unloaded and stocked. And **the routes are not in the device's published
OpenAPI document** — 36 paths, none of them model lifecycle — so reading
the spec says they do not exist, and they do.

The CLI still matters, and it is better at some things: `tiiny ls -r` is
the store catalogue, `tiiny ls -d` is what is on disk, and the difference
between the two is the download list. But the CLI is the only path that
needs the session, and the session is a single slot.

`tiiny download` also dies with a Go deadlock after the transfer completes
and always exits non-zero, so the device's catalogue entry — `status`,
`progress` and the byte count — is the only verdict either way.

## Pitfalls that only appear with two boxes

- **A storage endpoint is not a presence measure.** The device reports
  storage for LLM models separately, and it reported zero bytes while eight
  models were downloaded and one was running. The per-model `status` field
  in the model catalogue — `running`, `downloaded`, `downloading`,
  `not_downloaded` — is the truth, along with its `progress` and
  `npu_usage`. Reading the wrong field invents a missing-models finding.
- **The display name is not the identity.** A box was renamed in the
  desktop application, and the CLI scan, the device's own `device_name`
  and the account view each showed a different string. Key every record,
  lock, plan and provider on the **device id**, and treat the name as a
  label.
- **"ensure" must not claim a load it did not perform.** A load that fails
  leaves the model absent, and a child that expects it gets a 404 and falls
  back to the paid provider — with no error anywhere. The controller's
  verdict has to be unambiguous: either the model is resident, or the load
  failed and the exit code is non-zero. Printing "loaded" and "not
  resident" in the same breath is worse than printing neither.
- **A revoked credential looks present.** The controller reported "key
  found" — meaning it was in the environment — while every call returned
  401. Check that the device accepts the credential, not that the
  environment holds one.
- **A script that edits a credentials file must write atomically.** A
  mistyped `open(path, "w", encoding=...)` truncates the file before it
  raises. Write to a temporary file and rename it into place. A file that
  holds every provider's endpoint and credential name is not one you want
  to lose to a typo, and it is not one you can rebuild from a backup of
  itself.
- **The control session is one slot, and signing in takes it.** Signing in
  to the second box signs the first one *out*. The symptom is a box that
  worked an hour ago now answering "not signed in", with no error anywhere.
  Serve from both, manage one at a time, and have every control call name
  its device.
- **A download lands and the CLI dies with a Go deadlock.** The transfer
  succeeded, and the CLI's own progress reporter then deadlocks — every
  goroutine asleep on a channel that never signals — so the command always
  exits non-zero. The device's own catalogue entry — `status`, `progress`,
  and the byte count — is the truth. The exit code is not: it is non-zero
  on a perfectly ordinary "already downloaded" as well.
- **A load does nothing at all.** The control CLI opens a terminal for its
  prompts, and from a script it fails on that with nothing becoming
  resident. Give it a pseudo-terminal. The appliance exposes no SSH shell,
  so there is no borrowed terminal to fall back on — and `--json` does not
  avoid the prompt.
- **Verify the catalogue on both boxes before you trust the tier table on
  either.** "Same model" was an assumption until the two stores were
  compared entry by entry. They matched — but they were checked.

## Verifying the split

```bash
# both boxes reachable, each with its own credential and its own state
bash scripts/tiiny_box.sh vault status
bash scripts/tiiny_box.sh flex  status
```

And that the two catalogues really are the same:

```bash
python3 - <<'PY'
import json, os, urllib.request

env = os.path.expanduser("~/.hermes/.env")


def key(name):
    for line in open(env):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()


def models(ip, name):
    req = urllib.request.Request(
        f"http://{ip}/api/v1/models/online_models",
        headers={"Authorization": f"Bearer {key(name)}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return len(json.loads(resp.read().decode()))


print("vault:", models("192.0.2.50", "TIINY_API_KEY"))
print("flex: ", models("192.0.2.51", "TIINY_API_KEY_2"))
PY
```

Two boxes answering at once is the whole point. If one of them refuses
while the other serves, you have a credential problem, not a capacity
problem.

## What this assumes

- One appliance per box, each with its own credential and its own address.
- A local forwarder in the desktop application that serves one box at a
  time — which is why the boxes are addressed directly.
- Model lifecycle reachable two ways: the device's HTTP API
  (`POST /api/v1/models/<id>/download|start|stop`, authorised with the
  box's bearer, no session needed) and the CLI, which needs the session
  and a terminal. The HTTP routes are absent from the device's published
  OpenAPI document, so the spec is not the whole truth.
- The figures above, read on 2026-11-12. Model stores move with every
  firmware update; re-read them rather than trusting this table.
