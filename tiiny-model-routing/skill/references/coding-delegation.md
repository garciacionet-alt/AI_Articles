# Delegating coding work to a Tiiny

**The appliance writes the code. The manager agent judges it.** A paid
frontier model in the main loop is for judgement, conversation and
decisions; the token-heavy work belongs on the box on the LAN, where it
costs nothing.

A 30B model on an appliance is not a frontier model. The difference is not
capability — it is **briefing**. Give it a tight, verifiable order and it
competes. Give it a vague one and it wanders, and the manager pays for
the wandering twice: once in the box's tokens, once in a re-dispatch.

---

## 0. The shape

```
   ORDER ──▶ DISPATCH ──▶ OBSERVE ──▶ ┌──▶ ACCEPT
     ▲                                 │
     └──── CORRECT ◀───────────────────┘
```

| step | who | cost |
|---|---|---|
| Order | manager | paid, small |
| Dispatch | manager | free |
| Observe | manager | paid, small |
| Correct | manager | paid, small |
| Read, edit, test, document | appliance | free |

---

## 1. Preflight — the gate

Nothing is dispatched until this passes.

```bash
cd ~/.hermes/skills/mlops/tiiny-model-routing
python3 scripts/route_check.py --thinking off "<the goal>"
```

Read the **residency** line, not the tier line.

| residency | what to do |
|---|---|
| `loaded` | dispatch it |
| `NOT loaded` | do **not** force that tier — either load the model first, or drop the override and take the resident model |

**A forced tier overrides residency.** `delegate_task(tier=...)` selects
the tier's first choice and sends it, without checking what is loaded. A
model that is not resident answers 404; Hermes treats 404 as terminal; the
child falls back to the paid provider *invisibly*, with a good answer and
a bill. The tier is a hint; residency is the constraint.

Preflight is cheap. A silent fallback is not.

---

## 2. Box assignment

| | provider | role |
|---|---|---|
| Box A | the one `TIINY_BASE_URL` points at | primary worker — the residency probe reads this box, so this is the box a tier must be resident on |
| Box B | the other, by its own address and bearer | second worker |

**One heavy child per box.** The NPU is one pool per appliance and each
box serves one generation-heavy stream. Two children on one box starve
each other, and the failure mode is a *hang*, not an error — the device
keeps reporting healthy while it answers nothing. Two boxes give two
genuinely parallel free streams.

**A load is a swap.** It evicts whatever was resident, including the
generalist the next wave will want. Load deliberately, and restore
deliberately.

### Make the box match the router, not the router match the box

When you want a specialist and the router probes Box A, put the
specialist on **Box A**. Do not repoint `TIINY_BASE_URL`, and do not wait
for a restart.

`TIINY_BASE_URL` is read from the environment when the plugin is
imported, so changing it only takes effect in a new process. That makes
"the specialist is downloaded on Box B" look like a blocked path. It is
not. A model that is merely *downloaded* on Box A costs nothing to load,
and once it is resident there `route_check.py` reports `loaded` and the
tier routes to it with no config change at all.

Measured: downloading a 55% specialist took about 20 minutes (free, in
the background, while other work continued); loading it afterwards took
20 seconds. The download is the slow part and it is unattended — start it
early, keep working, and switch the tier when it lands.

### Each box has its own bearer, and the wrong one looks like a dead box

```
TIINY_API_KEY     -> Box A
TIINY_API_KEY_2   -> Box B
```

Point the controller at Box B without swapping the bearer and it answers
`HTTP 401 {"error":"auth_failed"}`, which the controller reports as
`device UNREACHABLE`. **That is a wrong key, not a down box**, and the
wrong conclusion from it is "the second box cannot be used". Confirm with
a one-line `curl` to that box's `/v1/models` using its own bearer before
saying anything about reachability.

Each box also needs its own lock, hold and plan files, or two agents
fight over one lock:

```bash
set -a; . ~/.hermes/.env; set +a
cd ~/.hermes/skills/mlops/tiiny-model-routing
TIINY_API_KEY="$TIINY_API_KEY_2" \
TIINY_DEVICE_ADDRESS=192.0.2.11 \
TIINY_BASE_URL=http://192.0.2.11/v1 \
TIINY_HOST=http://192.0.2.11 \
TIINY_LOCK_FILE=$HOME/.hermes/tiiny-lock-b.json \
TIINY_HOLD_FILE=$HOME/.hermes/tiiny-hold-b.json \
TIINY_PLAN_FILE=$HOME/.hermes/tiiny-plan-b.json \
python3 scripts/tiiny_ctl.py status
```

The mesh is the simpler door for both boxes when one is in front of them:
`POST /mesh/lifecycle` with `action: start|stop|download` and a `target`.

---

## 3. The work order

Copy [../templates/work-order.md](../templates/work-order.md) and fill it
in. Every order carries:

- **one job, one file.** No multi-file refactors in a single order.
- **exact absolute paths.** Never a relative path the child has to guess.
- **exact anchors.** The function to change, the literal string to match
  — quote it. "Update the routing section" is not an anchor.
- **a runnable acceptance command.** The child must make it pass, and the
  manager runs it again independently.
- **the output artifact path.**
- **no `<...>` placeholders.** The delegation backend refuses a goal
  containing an unexpanded template marker. Write the literal expected
  value.
- **a self-check before reporting.** The child runs the acceptance
  command itself and quotes the output.
- **for anything risky: write to scratch, then move into place.**
- **name the paths the child must NOT touch, and say what "shipped" means.**
  A child asked to "update the builder" will find a convenient artifact to
  run it against. If a build script writes into the live tree, the child will
  rebuild a **shipped** artifact: one that already went out, already carried
  hand-written content, and already had its own publication state recorded.
  The rebuild succeeds, reports clean, and silently replaces authored work
  with a generated blank. Write the exclusion into the order — *"edit ONLY
  `<file>`; do not run the builder against `<live path>`"* — and prefer a
  builder that refuses to overwrite an existing output directory.
- **A generated placeholder is a trap when the output already has human
  content.** If the generator writes an empty marked placeholder (an analysis
  section, a body copy, a filled-in checklist), then re-running it over
  anything a human has written into **deletes that content**, and the
  placeholder looks correct. Check what the generator writes before pointing
  it at anything that has shipped.
- **keep prompt context under 10K tokens.** Never paste a multi-wave project
  plan or multiple large reference files into a child brief. An appliance model
  with a 64K context window (like `Qwen3-Coder-30B`) experiences hardware PCIe DMA
  timeouts (`pcie_hdma_timeout`) when context approaches ~40K tokens, hanging the
  socket indefinitely without returning an error. For repo-scale multi-file
  tasks, route to a 256K context model (`Qwen3.6-35B-A3B`) or split the work into
  single-file orders.
- **proven worker recipe: Qwen3.6-35B-A3B with thinking off.** When delegating
  implementation (e.g., a standalone module + unit test suite), route to
  `Qwen/Qwen3.6-35B-A3B` on TinyAnt with `thinking: "off"`. Provide an explicit
  interface specification, input/output schemas, and a runnable acceptance
  command (`python3 test_X.py`). This avoids reasoning trace token burn, stays well
  within context limits, and reliably produces clean, 100% passing suites (e.g., 9/9
  passing tests) in one shot.

Ask for raw findings on disk early and keep the summary short. That is
what keeps a local model competitive with a frontier one — and it means a
budget-exhausted child still leaves you its artifact rather than nothing.

**Tell it to write the file before it verifies it.** An appliance
generates at roughly 20 tokens per second, so a 150-line script is minutes
of pure generation. A child that composes perfectly and never writes
loses everything if it stalls. A slightly imperfect file on disk that the
manager can fix beats a perfect one that never lands — say so in the
order itself.

That throughput is the real constraint on order size, not the model's
competence. Budget an order in minutes: one file, a few hundred lines at
most, one acceptance command. Every extra feature costs real wall-clock
time on a box.

---

## 4. Observe

- **A child's report is a self-report. The artifact is the evidence.**

- Read the **diff**, not the summary.
- **Run the acceptance command yourself.** A child that says the tests
  pass has not run your tests.
- **A child that verifies by string-matching has not verified.** A sweep
  that rewrites paths will report "N references rewritten, all resolve"
  after checking that each new path *string* is present in the file — which
  passes even when the path does not resolve from that file's own
  directory. Make the acceptance check **resolve the path**: join it
  against the directory of the file that holds it and assert the target
  exists. A relative path is only correct relative to something, and
  `../` depth is the thing a rewrite gets wrong: a file two levels below
  the root needs `../../`, and both `../` and `../../../` look plausible
  in the source.
- **A rewrite that changes what a sentence says is a corruption, not a
  fix.** Path tokens appear inside prose that *describes* a path — "the
  design system links to `../brand/tap-monogram.png`" — and rewriting
  that mention to a vault-absolute path breaks the sentence's claim
  while looking like a repair. After a bulk rewrite, read the changed
  lines in context: a mention inside a description keeps its original
  form, and only a genuine link target gets rebased.
- **Exercise every branch, especially the ones the report does not
  mention.** A child that verifies `status` and `preflight` and reports
  "acceptance passed" has told you nothing about `load` and `release`.
  Invoke each subcommand once. An argument-forwarding bug (`$1` where
  `$2` was meant) survives a green report and only shows itself when the
  branch actually runs.
- **A redacted secret looks like a hardcoded one.** Tool output can show
  `Bearer ***` where the file actually reads `Bearer $(_key)`. Check by
  length, or grep for the literal value, before raising a leak alarm —
  that is the tool protecting the secret, not the child leaking it.
- Read the **route label**. `tiiny-router` means the box served it.
  Anything else means the paid provider did the work.
- If the child ran long, look for its file on disk before concluding it
  produced nothing — the hang is often in the handover, not the work.
- **Record what you corrected, in the child's own report file.** When the
  child's work needed fixing, the report it left behind still claims the
  pre-fix state, so the next reader inherits a false record. Add the
  corrections to the report as a verification block naming each defect,
  what it was, and how it was resolved — and state plainly whether the
  child's count and its self-check were accurate.
- **After a child runs a build, check what the build TOUCHED, not only what
  it was asked to change.** A child's report lists the files it meant to
  edit; it does not list the artifacts its build wrote. Compare the
  modification times of everything the build could have reached, or hash
  the shipped files before and after. A shipped file that changed without
  appearing in the report was clobbered — and if it held authored content,
  the recovery path is whatever copy exists outside the tree (a scratch
  build directory, a version-control copy, the platform's own read-back),
  so **keep that copy before dispatching the child**.

---

## 5. Correct

A failing order gets a **second** order carrying the diff and the failure
output as evidence. Never a re-brief of the original: a re-brief pays for
the same mistake twice and gives the child no new information.

```
The change you made to <file> does this:
<the diff>

Running <the acceptance command> produces:
<the output>

Fix that, and change nothing else.
```

---

## 6. Release

After every wave: stop the specialist, restore the required set, clear
the lock and the hold. A swap that is not restored breaks every later
order, and it looks like a model problem rather than a leftover state.

---

## 7. The fallback alarm

Three guards, strongest first:

1. **Preflight** — makes it nearly impossible.
2. **The route label** — read it every wave.
3. **A ledger** — count the children whose route is not `tiiny-router`.
   That count *is* the paid spend, and it should be zero.

---

## 8. What to keep and what to give away

| Keep (paid, small) | Give away (free, large) |
|---|---|
| writing the order | reading and editing the files |
| reading the diff | running the tests |
| judging it against the spec | test scaffolding and boilerplate |
| choosing the architecture | bulk mechanical edits |
| the final acceptance call | docs, docstrings, refactors, repro scripts |

Target: **more than 80% of delegated tokens on an appliance.**

---

## 9. During a delegated run, stop the auto-loader

A gateway that puts the appliances back to their default models at startup
will evict the specialist you just loaded, mid-batch. The TiinyMesh
gateway has an `auto_restore` flag for exactly this — see the
`tiiny-mesh-multi-target` skill.

---

## 10. Rules, short

1. **The manager does not write the code.** Reaching for `patch` or
   `write_file` on the target file is the expensive model doing the
   worker's job — the exact inversion this discipline exists to prevent.
   Write the order, read the diff, run the acceptance, decide. The single
   exception is a correction you can make in one edit (a wrong variable
   reference) where a delegation round trip would cost more than the fix;
   make it, and say plainly that you did.
2. **Never force a tier whose model is not resident.** Check with
   `route_check.py` first.
3. **One heavy child per box.** Two boxes, two streams.
4. **One job per order.** One file. Exact anchors. A runnable acceptance
   command.
5. **A child's summary is not evidence.** Run the acceptance command
   yourself, and invoke every branch.
6. **Correct with a diff, not a re-brief.**
7. **Release after every wave.**
8. **Watch the route label.** It is the invoice.
