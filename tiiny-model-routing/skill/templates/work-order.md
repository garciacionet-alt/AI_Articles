# WORK ORDER — <one-line title>

Copy this, fill it in, and pass it as the goal/context of a delegated
subtask. Delete the guidance lines before dispatching.

## The job

<One sentence. The operation, not the subject.>

## Where

```
<absolute path to the one file this order touches>
```

Read these first, and say what to take from each:

- `<path>` — <what to copy from it>
- `<path>` — <what to copy from it>

## What to change

<The exact anchors. Quote the literal strings.>

- In `<function or section>`:
  - currently: `<the literal string that is there now>`
  - becomes: `<the literal string that must be there after>`

## What NOT to change

<The files and the parts that are out of scope. A local model edits what
it was not asked to edit if you do not fence it.>

- Do not touch `<file>`.
- Do not change the behaviour of `<thing>`.
- Do not add a dependency.

## Acceptance

The child must make this pass, and must quote the output:

```bash
<the exact command>
```

<What a passing run prints. If the command does not exist yet, say so and
give the command to create it.>

## Report back

<How many lines, what shape. Keep it short — the artifact is the
evidence, not the summary.>

- The files you changed.
- The acceptance command's output.
- Anything you could not do, and why. An admitted gap is worth more than
a plausible guess.

## If you get stuck

<Where to stop and what to write down instead of guessing. E.g. "if the
anchor string does not exist, write what you found at that location to
<scratch path> and stop.">
