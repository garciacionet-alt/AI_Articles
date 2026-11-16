# The Pattern: Earned Proactivity

Six principles, and the reasoning behind each default. This is the portable
half — the half that survives being rewritten for a different agent.

---

## 1. Proactivity is a permission, not a feature

An agent that offers to help is making a claim on your attention. Attention
is the scarce resource, and a proactive agent spends it whether or not the
thing it noticed was worth the spend.

So the first question is not "what can the agent notice?" It is "**on what
terms is it allowed to speak?**" Everything else in this pattern is
downstream of that.

The mechanism here is a score per objective. It is not the only possible
one — a confidence bar, a decay curve, a per-channel mute — but it has one
property that matters: **it is inspectable**. You can look at why an
objective fired, and why one stopped firing, without reading the code.

## 2. Silence is the default output

A scheduled job that produces a message every cycle has trained you to
ignore the channel. This is the most common way a proactive system fails:
not by being wrong, but by being constant.

Two rules follow:

- **A cycle with nothing to say prints a sentinel, not a sentence.** The
  sentinel (`[SILENT]`) is what a scheduler recognises and suppresses. A
  sentence would be delivered.
- **The sentinel is the contract, not the absence of output.** A job that
  prints nothing at all is indistinguishable from a job that crashed. A
  job that prints `[SILENT]` is distinguishable from both.

The distinction is small and it is the whole difference between an agent
that is quiet and an agent that is broken.

## 3. Fail closed on anything you cannot evaluate

The engine evaluates two kinds of condition:

- **Self-contained** — `day_of_week`, `hour_range`. A clock decides.
- **Context-dependent** — `meeting_in_minutes`, `task_due_in_days`,
  `has_new_job_alerts`. The caller must supply the fact.

When the context is absent, the condition is not evaluable, and an
unevaluable condition does not fire.

This is the principle that has the most counter-intuitive default in the
whole system. The natural implementation is to treat "I have no information"
as "the condition holds" — to return `true` and let the action proceed. It
feels permissive, and it feels harmless, and it is the single defect that
made an earlier version of this code fire two objectives on every cycle
forever, silently, at two in the morning.

The reasoning against it:

> **An objective that fires on a condition nobody checked is not a
> safeguard. It is a coincidence that happens to be scheduled.**

And the same applies to a trigger *key* the engine does not recognise. The
engine cannot know what the author meant by a key it has never seen, and
guessing in the direction of "fire anyway" is guessing in the direction of
waking somebody up.

Two sub-rules make this concrete:

- **Unknown key → do not fire.** A trigger key outside the known set is a
  reason to withhold.
- **Known key, missing context → do not fire.** A legitimate trigger with
  no data behind it is the same situation.

## 4. A pattern must earn the right to fire

The scoring curve is deliberately arranged so that **nothing fires just
because it exists**:

```
0.5  new and unvouched — below threshold
0.6  granted at the threshold — fires from now on
0.7  one success
0.8  two successes
1.0  maximum
```

and downward:

```
0.9 → 0.7   one ignore
    → 0.5   two ignores — stops firing
    → 0.3   three ignores
```

with recovery requiring three more successes.

Two properties matter more than the exact numbers:

**Asymmetry.** One success promotes; two demotions demote. The bar is
**easier to climb than to fall off**, which sounds backwards and is
deliberate: an objective should get a hearing, but it should not get many.
The cost of a false positive is asymmetric too — a bad objective that
keeps firing is much worse than a good one that stays quiet for a week.

**The new pattern cannot fire on its own.** 0.5 is below 0.6, and an
objective with no history cannot climb out of that hole: it does not fire,
so it cannot succeed, so it stays at 0.5. That is not a rounding error in
the design — it is the design. A default score equal to the threshold
means everything fires immediately, and the trust mechanism becomes
decoration. Below the threshold means the mechanism is load-bearing.

Which leaves the obvious question: what starts one? A **grant**. The grant
is the score an objective is given before it has any history, and it is
the only thing that can start an objective. The daily scan grants one
automatically — the model's confidence that the pattern is real becomes
the pattern's starting score — and a hand-written objective grants one
itself, by declaring `initial_score`. The grant is spent on the first
firing; after that the score is earned, and only earned, by outcomes.

That distinction is the whole point. A grant is a vouch: someone looked at
this pattern and said it was worth one hearing. Everything after it has to
be earned.

**The downward branch is the whole point.** A score that only rises is a
ratchet, not a trust score. It looks like the mechanism works — the number
goes up, the objective keeps firing — while providing no information at
all. The value of trust scoring is entirely in the branch that is hardest
to observe: the objective you ignored. Which is why a test suite for this
system must assert both directions, and why "the score went up" is never
evidence that the scoring works.

## 5. Keep the loop free of the expensive part

Three of the five modules need no model at all: the evaluation loop, the
trigger matching, the trust arithmetic. Only the daily pattern scan calls
one.

This is a structural property, not an optimisation. It means:

- **The core loop is free.** Running it every fifteen minutes costs
  nothing.
- **The core loop cannot be taken down by a model outage.** A failed scan
  leaves yesterday's objectives in place and tomorrow's undiscovered. The
  daemon keeps working.
- **The intimate data can stay local.** Pattern detection reads your work
  history — task titles, cron output, session summaries. Running it against
  a local model means that history never leaves the machine. That is only
  possible because the expensive step is isolated.

The general rule: **put the model where it is needed, and nowhere else.**
Every place you can move a decision into plain code is a place the system
gets cheaper, faster, and more private.

## 6. Offer, do not act

Every action in this system writes a file. Nothing sends, publishes,
deletes, or commits.

The value of proactivity is that it shortens the gap between noticing and
acting. It does not follow that the human should be removed from the loop —
it follows that the human should be removed from the *typing*, not from the
*deciding*.

The concrete form: the agent writes a task to an inbox, with a checkbox
for review and one for completion. The person looks at a queue instead of
remembering to look. That is the entire interaction, and it is enough.

## Where the boundaries are

The pattern is about **earned** proactivity, and it draws its edges in three
places.

**Trigger evaluation is not pattern learning.** The engine evaluates
conditions the author wrote. The scan proposes new ones. Keeping those
separate means a bad proposal cannot reach an action on its own — it has
to be saved as an objective, and an objective has to earn trust before it
does anything.

**Detection is not action.** A pattern found with 0.95 confidence is a
*proposal*. Confidence in the detection is not permission to act; the
trust score is. These are two different questions and they have two
different answers.

**Noticing is not deciding.** See principle 6.

---

## Failure modes, and what each one teaches

These are not hypotheticals. Each one shipped in an earlier version of this
code, and each one had the same symptom: **the system looked healthy while
doing nothing.**

### A test harness that exercises a different path than production

The harness configured its module paths correctly; the daemon did not. The
tests passed. The daemon could not start.

*The harness was right about itself and wrong about the program.* A green
suite is evidence about the code the test touches. If the test constructs
its own environment and the program constructs its own, the test is not
testing the program.

**What to do:** assert the program's own path resolution in the harness.
Make the test check the wiring, not just the logic.

### A query that names a column the schema does not have

The reader selected `updated_at`. The schema had `created_at`,
`completed_at`, and no `updated_at`. The query raised, the exception was
caught and turned into a warning, and the function returned an empty list.
The detector reported zero tasks on every run.

*The failure was caught and reported as a non-event.* Swallowing an
exception converts "this is broken" into "there is nothing here" — and
"there is nothing here" is indistinguishable from the truth.

**What to do:** derive the column list from the live schema. And when a
query fails, make the failure loud enough that it cannot be mistaken for an
empty result.

### Two components whose shapes disagree at the boundary

The detector's model emitted nested triggers; the engine read flat ones.
Both were reasonable. The saved objective held keys the engine did not
recognise, so under principle 3 it could never fire — and it looked
perfectly well-formed in the file.

*A boundary is where two designs meet, and it is where nobody looks.* Each
component was tested against its own expectations.

**What to do:** put the translation at the boundary, and test the round
trip — producer's output, through the translation, into the consumer.

### A hardcoded path

One machine's directory layout and one private LAN address, written into
the source. It worked on that machine.

*It works on exactly one machine, which is the failure that costs the
most.* A path that is wrong everywhere else is not a portability problem
to be fixed later; it is a portability problem that will be found by
someone else, at runtime, on their own hardware.

**What to do:** read every path and endpoint from the environment with a
working default. Then assert it — a test that fails if a machine-specific
string appears in the source.

### A score that only goes up

The easiest defect to write, because every visible behaviour is correct:
the score rises, the objective fires, the system looks like it is learning.

*The mechanism can look like it works while measuring nothing.* Trust
scoring's entire value is in the downward branch, and that branch is
invisible in a happy-path demo.

**What to do:** test the downward branch explicitly. A scoring system whose
tests only ever assert increases is not tested.

---

## The checklist

If you are building this shape, these are the properties that matter, and
each one has a test:

- [ ] A cycle with nothing to say emits a sentinel, and the sentinel is
      what suppresses it
- [ ] An unevaluable trigger does **not** fire
- [ ] An unrecognised trigger key does **not** fire
- [ ] A new objective starts **below** the threshold
- [ ] The score falls when an objective is ignored
- [ ] The core loop runs with no model available
- [ ] Every action writes a file; nothing sends
- [ ] No machine-specific path or address is in the source
- [ ] The harness asserts the program's own path resolution
- [ ] A producer's output is translated at the boundary, and the round trip
      is tested

## See also

- `IMPLEMENTATION.md` — the concrete setup: environment, commands, the
  end-to-end checklist
- `README.md` — the article this pattern implements
