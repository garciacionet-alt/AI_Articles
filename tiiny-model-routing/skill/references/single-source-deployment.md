# One file, many locations: symlinks instead of copies

## When this applies

A policy value (a model list, a tier table, a default) has to be readable from
several places at once: `~/.hermes/scripts/`, each profile's skill tree,
`~/.hermes/shared-skills/`, the vault's own `skills/`, and a publish tree.

Copying the file to each location does not work. The copies look identical the
moment they are written and then diverge the first time anyone edits one of
them — and nobody edits five. The symptom is not an error: the edit happens,
the tool that reads a *different* copy wins, and the change appears to revert
itself.

## The shape

| Location | Kind | Why |
|---|---|---|
| the vault's `skills/<skill>/scripts/` | **real file** | canonical source; the version a human opens |
| `~/.hermes/scripts/` | symlink | what cron and ad-hoc commands run |
| each skill tier that must expose the skill | symlink | each root must have the *directory*; the *files* can point elsewhere |
| a publish tree | **real file** | git publishes content, not links |

**Why the skill directories must still each exist.** Hermes resolves a skill
per search root and refuses two candidates in the same tier, so every root that
should see the skill needs its own directory. That is a constraint on the
*directory*, not on the script inside it — and it is the reason "just use one
copy" is not available.

## The publish tree is the exception

A symlink in a git-tracked tree shows as a **typechange** (`git status` reports
`T`). The file's content is unchanged, but a commit records a symlink where
regular files were expected — and a publisher that reads content will follow
the link fine while git sees a deletion-plus-link. Either way the published
artifact is not what was reviewed.

So publish targets hold **real copies**, regenerated from canonical on every
deploy. Verify after: `git status` on that tree should show content changes or
nothing — never `T`.

## The deploy script must check links, not just diffs

A hash comparison between two files passes trivially when both are the same
link target, so `--check` can report all-clear on a tree that has silently
semantically split. Deploy must assert, per target:

1. the path exists;
2. either it is a symlink resolving to the canonical file, or (for publish
targets) its content hash equals canonical;
3. the file is executable if it is a script.

Emit one OK line per target and fail loudly on any mismatch, so `--check`
is a gate rather than a report.

## Converting an existing set of copies

1. Pick the canonical location. Prefer the vault (it is versioned and it is
   where a human looks).
2. Diff every existing copy against it — the one that differs tells you which
   copy was being edited, which is usually the bug you are chasing.
3. Copy canonical into any location that must stay real (publish tree).
4. `rm -f` and `ln -s <canonical>` the rest, driven from the deploy script so
   the step is repeatable.
5. Re-run deploy and confirm the count: *N locations, all resolving to one
   content hash*.

## Stale references survive the fix

Changing the file does not change the documents that describe it. After
trimming a policy, grep for the **old list's members** and for the **retired
tool's name** across the skill, its references, the design docs, and any
architecture note — a comment that still says "the poller reloads this" teaches
the next agent a mechanism that no longer exists, and a `grep` embedded in a
procedure is worse still, because it fails at run time.

## Counting honestly, and answering "why N"

"N copies" is ambiguous and invites a justified objection. Say **N files
across M locations, of K distinct scripts** — the distinction between a file, a
location, and a distinct artifact is the one being asked about.

**"Why do we need more than one?" is a question about the constraint, not the
inventory.** A role-per-instance table ("this one is what cron runs, that one
is what the skill tier resolves") describes what each copy *does* and leaves the
real question untouched, so it gets asked again. The answer that lands names
the mechanism that forces the duplication — a skill is resolved per search
root, every root needs its own directory, and profiles do not share a tree —
and then separates the load-bearing locations from the copies of mere
convenience.
