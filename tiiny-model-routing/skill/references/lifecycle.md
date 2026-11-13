# The delegation lifecycle

The detail behind the procedure in `SKILL.md`: what each step is protecting
against, what the files on disk mean, and what to do when a step fails.

## The state machine

```
   plan ──► reserve ──► load ──► delegate ──► release
    │           │          │                     │
    │           │          └── hold file ────────┘
    │           └── lock file + hot.md notice
    └── plan file
```

Three files carry state, and they have different owners and different
lifetimes.

| File | Written by | Meaning | Cleared by |
|---|---|---|---|
| `~/.hermes/tiiny-plan.json` | `plan` | which model was assigned to which goal | `release` |
| `~/.hermes/tiiny-lock.json` | `reserve` | who has the device, and until when | `release` |
| `~/.hermes/tiiny-hold` | `load` | these models are deliberately resident | `release` |

The plan is shared with the router, which is why it lives in the **base**
Hermes home: every profile's manager agent must see the same plan.

## The lock

### The mutex

`~/.hermes/tiiny-lock.json`. Its contents are the lock:

```json
{
  "state": "held",
  "owner": "<agent>",
  "task": "vault index + research sweep",
  "models": ["openai/gpt-oss-20b"],
  "created": 1793564901.2,
  "expires": 1793566701.2,
  "pid": 4711
}
```

It is taken under `flock` on the file, so two agents racing for it are
serialised by the kernel rather than by hope. The critical section is short —
read, check, write — and the lock itself outlives the process, because the
file's contents are the lock.

**A lock that expires is not a lock that can wedge the device.** The
expiry is what makes a crashed agent survivable: the next agent to reserve
takes over an expired lock and says so, rather than being told the device
has been busy for six hours. A lock with no expiry would need a human to
clear it, and a human is exactly what is missing when a batch fails at 3am.

**Release is a write, not a delete.** The sandbox this runs in cannot unlink
files outside the session workspace, so the released state is written into
the file and the file stays. An empty or released lock file is a released
lock.

### The announcement

The mutex is machine truth, and only Hermes profiles read it. The AMC's
shared surface is `hot.md` — the vault-wide board of what is in flight — so
the lock is announced there in a marked block:

```markdown
<!-- tiiny-device-lock:start -->
**Tiiny is BUSY — do not schedule device work.**
Held by `<agent>` for vault index + research sweep since 12:41. Models:
openai/gpt-oss-20b. Lock expires 13:11.
<!-- tiiny-device-lock:end -->
```

The markers make the edit idempotent and contained: the controller replaces
the text between them and touches nothing else in the file, so an agent
editing `hot.md` elsewhere is not disturbed. If the markers are absent, the
block is appended.

## The hold

`~/.hermes/tiiny-hold` records what an agent deliberately loaded: *these
models are resident because this batch asked for them.*

**It used to be an interlock.** A five-minute watchdog read this file and
reloaded nothing while it existed, so the hold was what stopped a policy
poller from evicting a long batch's model mid-run. That watchdog was retired
on 2026-11-10, so the file no longer stops anything from firing.

What replaced it is `tiiny_ctl.py ensure --model <id>`, called before
delegating. It is idempotent, it checks the cross-agent lock, and it fails
loudly when a model does not land — which is the property the hold could
never provide, because a hold only ever *prevented* something.

Three rules still hold, because they are about the file's shape:

1. **Write it before the load.** `status` should report what the batch is
   about to have, not what it had a moment ago.
2. **The first line is the one that matters.** In a multi-wave batch the
   controller rewrites the hold as each wave starts, so the first line is
   always a model that is resident for the whole of that wave.
3. **An emptied hold file is a released hold.** Truncation is a write, and a
   write works where deletion is blocked.

**A stale hold is now a reporting bug, not an outage.** With no poller to
disable, a hold left behind makes `status` claim a resident set that is no
longer true. `release` clears the hold and *verifies* it, because a script
that prints "hold cleared" without checking is how that happens.

## The NPU budget

NPU-RAM is one finite shared pool. Two facts decide everything:

- A model takes a fixed share: 27%, 47%, 50%, 48%.
- **A load is a swap.** It evicts whatever was resident. Loading a model
  that does not fit does not fail — the device makes room, and it chooses
  what to make room from.

That second point is the one that bites. The device does not know what the
batch needs, so it will keep a 47% generalist and evict the 27% model the
batch just asked for. The controller therefore decides what stays, **before**
it loads:

- the wave's own models are sacred;
- of everything else resident, the cheapest are kept while they fit in what
  is left (a 5% TTS model is worth keeping; a 47% generalist is not, when a
  wave needs the pool);
- everything dropped is restored by `release`.

This was not a design preference. It was found by running it: the first
wave-1 load evicted the very model the wave had asked for, and the child
would have answered `404 "is not loaded"` and fallen back to MiniMax.

### Waves

A batch whose models total more than 100% is split into waves. The packing
is first-fit decreasing, with already-resident models placed first, so a
model that is already loaded stays loaded instead of being evicted and
re-loaded.

Each wave is a separate delegation call, because the device serves one
generation-heavy stream at a time.

## One stream at a time

Measured directly on the device:

- Two parallel 500-word generations on the same model finished at 59.6s and
  29.4s — one waited for the other.
- Two on *different* models still serialised. The NPU is one shared pool of
  silicon; loading a second model does not create a second slot, it splits
  the same hardware.
- A short call on the same model as an in-flight generation waits for that
  generation, regardless of size — a 2-token request waited 28 seconds
  behind a 30-second one. A short call on a *different* model slips through.
- Two heavy children deadlock: the device keeps answering `/health`, keeps
  showing the model loaded, and answers nothing. A stalled child is
  indistinguishable from a slow one until you measure the endpoint yourself.

The working pattern is **two workstreams on two providers**: a heavy device
child and a separate cloud stream finish at wall clock ≈ max, not sum. The
parent's own cloud route is already a separate stream, so parent work and
one device child genuinely run in parallel.

Steering does not rescue a stalled child — a steer is appended to the next
tool result, and a child stuck waiting for a model response never reaches
that boundary. Stop it and re-dispatch.

## When a step fails

| Symptom | What it means | What to do |
|---|---|---|
| Child returns `404 "<model>" is not loaded` | the model is not resident | `tiiny_ctl.py load --wave N`, then re-dispatch |
| Child fell back to `minimax / MiniMax-M3` | the device was unreachable, cold, or the model was missing | read the child's `route`; run `status` |
| Child hangs, no error | two heavy children, or a contended device | stop it, re-dispatch one at a time |
| `reserve` refuses | another agent has the device | wait for the expiry, or ask that agent to release |
| `load` reports a model missing | it is not downloaded, or it did not fit | check the plan's `state` column |
| The device is missing models later | a stale hold, or a batch that was never released | `tiiny_ctl.py release --force` |
| `tiiny load` fails with "could not open a new TTY" | the CLI needs a pseudo-terminal | the controller wraps it in `script -q /dev/null`; do not call the CLI bare |

## Verifying a child's work

A child's report is a self-report. Recompute what it claims from the
primary record, with a script, and render what it built — a delivered HTML
file is not done when it parses.

Two things worth checking specifically:

- **The route label.** `code→generalist` means the specialist was not
  available and the child ran on the generalist instead. That is a routing
  outcome worth knowing about, not a failure.
- **The device was actually used.** The route label and the child's model
  are how you know the work ran on the box rather than on the paid plan.
