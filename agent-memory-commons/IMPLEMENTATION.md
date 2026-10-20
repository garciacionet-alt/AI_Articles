---
title: Agent Memory Commons — Implementation Manual
status: implementation
applies-to: setting up the commons pattern with concrete tooling
companion: agent-memory-commons.md
updated: 2026-10-20
---

# Agent Memory Commons — Implementation

> **Companion document:** This file describes the concrete setup. For the pattern itself, the design principles, the sync-directory discussion, and the layered memory architecture, see [agent-memory-commons.md](./agent-memory-commons.md).
>
> The two files together are the complete reference. This one is the working manual; the other is the shareable description.

This document assumes the reader has read or skimmed [agent-memory-commons.md](./agent-memory-commons.md) and is now wiring up the pattern in a real environment. Paths are shown as placeholders — `<VAULT-PATH>`, `<VAULT-NAME>`, `<VENDOR>`, `<agent-name>`, `<WORKSPACE-NAME>`, `<PROTOCOL_FILE>`, `<STATUS_FILE>`, `<LINTER>` — substitute the values appropriate to your setup.

## Memory layer configuration

Before session start, the agent needs to know the paths and tools for each layer. These are the values to set:

```
# Paths (adjust to your environment)
VAULT_PATH=~/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT-NAME>/
COMMONS_ROOT=<VAULT_PATH>/_agent-<agent-name>/
OBSIDIAN_VAULT=<VAULT_PATH>

# Operating layer
PROTOCOL_FILE=<VAULT_PATH>/AGENTS.md             # root protocol, auto-loaded
STATUS_FILE=<VAULT_PATH>/hot.md                 # what is in flight right now
LINTER=<VAULT_PATH>/skills/memory-lint/lint.py  # read-only health check

# Vector database (Engraphis example)
ENGRAPHIS_DB=~/.engraphis/engraphis.db
ENGRAPHIS_WORKSPACE=openhuman

# Tool: semantic search over vault
#   engraphis graph search --query "<question>" --workspace openhuman
#   Returns: top-K relevant memories with titles and excerpts
```

These can live in a `.env` file, a config block in the agent's system prompt, or be loaded as agent-internal memory entries. The key is that the agent can call the vector search tool without needing to know the underlying path.

## Session startup prompt

At the beginning of every non-trivial session, run this sequence before starting task work:

```
SESSION STARTUP SEQUENCE
1. Load agent-internal memory (base context — done automatically)
2. Read the root protocol file (<PROTOCOL_FILE>). It is short, and it
   says where artifacts go and what must not be touched.
3. Read the status file (<STATUS_FILE>) to see what is in flight.
4. Scan the commons: read each _agent-*/README.md to identify
   which agent subspace is relevant. Then list the 5 most-recently-
   modified files in that subspace. Read each summary.
5. If the task is vague or exploratory, call:
   engraphis graph search --query "<task description>"
   --workspace <WORKSPACE-NAME>
   Read the top-5 results.
6. If the user referenced a specific Obsidian note or file, open it
   directly from <OBSIDIAN_VAULT>/<relative-path>.
7. Begin task work.
```

This can be embedded as a system-level startup instruction in the agent's config, or written as a reusable prompt the user triggers with a keyword like `/startup` or `/load-context`.

## Reading prompt (commons scan)

To scan the commons for relevant context without a semantic search:

```
SCAN COMMONS
Look in <COMMONS_ROOT>/ for files modified in the last 7 days.
For each file found, read the first 200 characters to determine
relevance. If relevant to the current task, read the full file.
Report what you found.
```

## Semantic search prompt (vector DB)

For exploratory or vague queries where filename search won't help:

```
SEMANTIC SEARCH
Run: engraphis graph search --query "<user's question>"
  --workspace <WORKSPACE-NAME> --limit 5
Read the results. For each result, note the title and key finding.
Synthesize a brief answer from the top results and report
which files were most relevant.
```

## Writing to the commons prompt

Before ending a session, run the write check:

```
WRITE CHECK
Did this session produce any of the following?
- A decision or conclusion
- A drafted document or deliverable
- A status update on an ongoing project
- A finding that another agent might need
If yes: write a summary to <COMMONS_ROOT>/YYYY-MM-DD-<topic>.md
using this template:

# Session Summary: <topic>
Date: YYYY-MM-DD
Agent: <agent-name>
Task: <one sentence>
Outcome: <what was decided, produced, or concluded>
Relevant files: <any files created or referenced>
Next steps: <if any>

If no: skip writing. Ephemeral work (debugging, exploration,
transient analysis) does not belong in the commons.
```

## The session-end ritual

Every session ends the same way. Three steps, in order, every time — the value is in the repetition, not in the sophistication.

```
SESSION END RITUAL
1. Refresh the status file (<STATUS_FILE>). One screen: what is in
   flight, what changed, what is blocked. Rewrite it; do not append.
2. Capture what is durable. For each standing fact, decision, mistake,
   pattern, or state snapshot worth keeping, write one claim to the
   semantic layer with its claim kind and a stable subject key.
   Do not paste documents into the semantic layer — it stores claims
   and pointers, not source text.
3. Write a hand-off only if the next step is genuinely someone else's
   job. A hand-off names the next agent, the current state, and the
   one thing that is blocked.
4. If the structure of the vault changed — files moved, added, renamed
   or deleted — run the linter before finishing:
     python3 <LINTER>
```

Step 2 is where the claim classification earns its keep; it is spelled out in "Classifying durable claims" below.

## Agent subspace README template

Place this in each agent's `_agent-<name>/README.md`:

```markdown
# Agent <name> Commons Subspace

**What this folder is:** Work products, session summaries, and
status notes produced by agent <name>.

**Who writes here:** <agent-name> only.

**What is authoritative:** Primary work products (drafts, findings,
decisions) unless marked observational. Check the file header.

**Naming convention:** `YYYY-MM-DD-<topic>.md`. Projects get a
subfolder within this space.

**When to read from this folder:** At session startup, scan for
files modified in the last 7 days. At any point during task work,
if the current topic matches a recent file, open and read it.

**When to write to this folder:** Before ending any session that
produced a decision, finding, draft, or status update. Use the
write-check prompt above.
```

## One-file agent startup script (Unix)

For agents that run as shell processes, this script runs the startup sequence:

```bash
#!/bin/bash
# commons-startup.sh — run at agent session start to load recent commons context
#
# Usage:
#   export VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT-NAME>"
#   ./commons-startup.sh
#
# What it does:
#   1. Reads each _agent-*/README.md to identify what each agent subspace contains
#   2. Lists recent files in your own agent subspace (modified in the last 7 days)
#   3. Prints a summary you can scan to decide what to read in detail

set -u
VAULT="${VAULT:-<VAULT-PATH>}"
AGENT_FOLDER="$VAULT/_agent-<name>/"

echo "=== Agent subspace READMEs ==="
for d in "$VAULT"/_agent-*/; do
    if [ -f "$d/README.md" ]; then
        echo "--- $d"
        head -10 "$d/README.md"
    fi
done

echo ""
echo "=== Recent files in $AGENT_FOLDER ==="
if [ -d "$AGENT_FOLDER" ]; then
    find "$AGENT_FOLDER" -name "*.md" -mtime -7 | sort -r | head -10
else
    echo "(agent folder does not exist yet — this is fine for a new setup)"
fi

echo ""
echo "=== Startup scan complete. Ready to begin. ==="
```

Two details in there are load-bearing. The glob in `for d in "$VAULT"/_agent-*/` sits **outside** the quotes so the shell can expand it — quoting the whole thing would pass a literal `*` to `find`. And the agent folder is guarded with `-d` before it is searched, so a fresh setup does not print a wall of errors.

## Vault hygiene reminder (3-month)

Run this quarterly to keep the commons navigable:

```bash
#!/bin/bash
# commons-hygiene.sh — quarterly maintenance scan of the commons
#
# Usage:
#   export VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT-NAME>"
#   ./commons-hygiene.sh
#
# What it does:
#   1. Lists markdown files older than 60 days that carry no closure marker
#   2. Lists empty _agent-* folders (candidates for removal)
#   3. Lists files in _agent-* folders that do not follow the YYYY-MM-DD- convention
#   4. Lists notes flagged "status: stale" — the pruning queue
#
# It reports. It never deletes.

set -u
VAULT="${VAULT:-<VAULT-PATH>}"

echo "=== Unclosed projects (>60 days old) ==="
find "$VAULT" -name "*.md" -mtime +60 -print0 |
while IFS= read -r -d '' f; do
    if ! grep -q -- "<!-- CLOSED" "$f"; then
        echo "MISSING CLOSURE: $f"
    fi
done

echo ""
echo "=== Empty agent folders ==="
find "$VAULT" -type d -name "_agent-*" -empty -print0 |
while IFS= read -r -d '' d; do
    echo "Empty: $d"
done

echo ""
echo "=== Files without date prefix ==="
for d in "$VAULT"/_agent-*/; do
    [ -d "$d" ] || continue
    find "$d" -name "*.md" ! -name "[0-9][0-9][0-9][0-9]-*" -print0 |
    while IFS= read -r -d '' f; do
        printf '%s\n' "$f"
    done
done | head -10

echo ""
echo "=== Notes flagged status: stale (pruning queue) ==="
find "$VAULT" -name "*.md" -print0 |
while IFS= read -r -d '' f; do
    if grep -q -- "^status: *stale" "$f"; then
        echo "STALE: $f"
    fi
done

echo ""
echo "=== Hygiene scan complete. ==="
```

Three bugs in the obvious version of this script are worth calling out, because all three produce wrong output rather than an error:

- **`find "$VAULT/_agent-*"` cannot work.** The glob is inside the quotes, so the shell hands `find` a literal path containing `*` and it reports nothing. The glob has to be expanded by the shell, which means it has to sit outside the quotes.
- **A pipeline into `while read f` splits on whitespace.** The default iCloud path contains a space ("Mobile Documents"), and `read` without `-r` also eats backslashes. `find … -print0` with `IFS= read -r -d ''` is the fix that keeps a path intact from end to end.
- **A literal path in the `VAULT=` assignment is a trap.** The obvious version hardcodes one machine's iCloud path and mixes it with placeholders, so on any other machine the script silently scans nothing. Take the path from the environment and fail loudly if it is unset.

The script reports; it never deletes. That is the same rule the linter follows, and for the same reason: a maintenance pass that removes files on its own is a data-loss event wearing a green exit code.

## The operating layer

Conventions decay silently. The artifacts below keep a commons honest without anyone policing it by hand. Each one is small; each one does a job that is invisible when it works and expensive when it is missing.

### The root protocol file

One short file at the vault root, loaded automatically by whatever agent runtime touches the vault. It answers the questions every new agent asks:

- Where must an artifact land?
- Which conventions are mandatory?
- What must never be touched?
- What are the known traps in this particular vault?

Keep it under a page. `AGENTS.md` is a common name for it, because it is a convention several agent runtimes already know how to load. The moment it grows past a page it stops being read — move the detail into the operating documents and leave pointers.

### The frontmatter vocabulary

Two fields on every note, with a closed set of values for each:

| Field | What it means | Values |
|---|---|---|
| `type:` | what kind of note this is | `design`, `ops`, `reference`, `protocol`, `note`, `log`, `decision`, `pattern`, … |
| `status:` | where the note is in its life | `maintained`, `active`, `draft`, `done`, `verified`, `stale`, `reference`, `archived` |

`status:` is a **lifecycle state, never a description.** "verified Oct 16 against v1.29" is a sentence, not a state — it belongs in its own field, next to `status: verified`. A sentence in `status:` breaks every view and every filter built on it, and it breaks them silently, because a view that groups on a free-text field still renders — it just renders nonsense.

`status: stale` is the pruning marker. It never deletes anything; it moves a note into the pruning queue, where a human decides. That is what makes it safe to write a lot: the cost of an unwanted note is one flag, not a deleted file and a revert.

### The read-only linter

A script that reports, and never modifies:

- relative links that resolve to nothing
- wikilinks with no matching file
- pages nothing links to
- frontmatter that has drifted outside the vocabulary
- notes flagged `status: stale`

```bash
python3 <LINTER>          # full report
python3 <LINTER> --strict # warnings become failures
python3 <LINTER> --json   # machine-readable
```

Two rules make it safe to leave in the hands of an agent:

1. **It is strictly read-only.** It opens files and prints. It does not rewrite, reformat, or "fix" anything. A linter that edits is a mutator wearing a lint coat, and one day it will rewrite something someone cared about.
2. **It is never satisfied by deleting a document.** When it reports an orphan page, the fix is to link it from somewhere real, or to mark it `stale` — not to remove it. A lint pass that quietly deletes content is a data-loss event with a green exit code.

### Live views

Two database-style views over the vault, so the state of the commons is legible in the note app without running a script:

- **A typed-note index** — every note grouped by `type:`, so the shape of the vault is visible at a glance.
- **A pruning queue** — everything marked `status: stale`, plus an aging view for notes that have not been touched in 90 or 180 days.

These views read the frontmatter vocabulary, which is why that vocabulary has to be closed and typed. They also carry an ownership caveat: a note application rewrites its own view and configuration files whenever it saves them, normalising the format and stripping comments. Write them in the application's own style, keep the documentation in ordinary Markdown files rather than inside them, and expect spurious churn in version control.

## Index the commons with a vector database

This section is the most implementation-specific part of the manual. It is written against one concrete tool — [Engraphis](https://engraphis.com) — because the user has that tool installed. The shape of the workflow is the same for other vector databases; substitute the equivalent commands.

### Why Engraphis for this setup

Engraphis is well-suited for agent session memory because it:
- Understands Obsidian's vault structure (frontmatter, tags, wikilinks)
- Imports files as semantic memories with one command
- Supports incremental updates (`--on-conflict replace`)
- Runs locally, with the database stored at a known path

The trade-off worth knowing: Engraphis embeds each file as a single vector. For Markdown notes and short documents this is fine. For long documents — transcripts, lengthy reports — a single vector averages over too much heterogeneous content and retrieval quality suffers. If chunk-level retrieval matters, see "Alternatives and the chunking question" below.

### Import setup

First, run a one-time import to seed the index:

```
engraphis import obsidian <VAULT-PATH> \
    --workspace <WORKSPACE-NAME> \
    --on-conflict replace \
    --memory-type semantic \
    --yes
```

The `--on-conflict replace` flag means: if a file changed since the last import, replace its memory entry; if it is unchanged, it is a no-op. Safe to run repeatedly.

### Daily re-index via cron

Schedule a daily import to keep the index current. The commons may be held open by an active agent session (Engraphis uses WAL mode), so the import script should checkpoint the database before importing. Example bash script:

```bash
#!/bin/bash
# Run before the import to release the WAL lock
sqlite3 ~/.engraphis/engraphis.db "PRAGMA wal_checkpoint(TRUNCATE);" || true

engraphis import obsidian <VAULT-PATH> \
    --workspace <WORKSPACE-NAME> \
    --on-conflict replace \
    --memory-type semantic \
    --yes
```

Schedule this via cron at a time when no agent session is active. On a personal machine, 6:00 AM works. The script should log output and retry on failure — a brief database lock from an active session is the most common failure mode, and it resolves itself within minutes.

### Scope and exclusion

Import the full vault (the sync-rooted folder that contains both the personal knowledge tree and the agent subspaces). The vector index will index both; retrieval across all vault content is more useful than indexing only the commons.

For privacy, create a `_private/` folder at the vault root:

```
<VAULT-ROOT>/
├── _private/          ← never indexed; put sensitive content here
├── _agent-A/
├── _agent-B/
└── ...
```

The import tool does not need to exclude this folder mechanically — if it is empty, nothing is indexed from it. The convention is: **anything in `_private/` is off-index by definition.** Do not place sensitive files outside this folder if you want them excluded.

### Alternatives and the chunking question

If chunk-level retrieval matters, Engraphis can still serve as the index; you control the chunking upstream by splitting documents before import and importing each chunk as a separate memory entry. This approach keeps Engraphis as the retrieval engine while giving you full control over chunk size and boundaries.

For a more sophisticated RAG setup from scratch, several alternatives exist:

| Tool | Chunking | Best for | Setup complexity | Limitation |
|---|---|---|---|---|
| **Chroma** | Yes (you control the splitter) | Prototyping, local-first | Very low (`pip install`, 3 lines) | Single-node only; not production-grade under concurrent load |
| **Qdrant** | Yes, with upstream text splitting | Filtered search, hybrid search, scale | Medium (Docker or managed service) | A separate process to operate |
| **pgvector** | Yes, pre-chunk externally | Existing Postgres users | Very low (`CREATE EXTENSION`) | Performance degrades above ~10M vectors |
| **Weaviate** | Yes, built-in chunking | Best hybrid (vector + keyword BM25) | Medium (Docker or managed) | More configuration overhead |
| **LanceDB** | Yes | Local-first, multi-modal future | Low (`pip install`, embedded) | Newer, less battle-tested |

The key distinction beyond chunking is **hybrid search** — combining semantic vector similarity with keyword BM25 matching. Qdrant and Weaviate both do this natively. Engraphis and pgvector do not. If you find yourself thinking "I know the exact term I want but semantic search isn't finding it," hybrid search is the answer.

**When to upgrade from Engraphis:** if your corpus grows to thousands of files, if you need chunk-level retrieval on long documents, or if hybrid search becomes a genuine requirement. The natural migration path is from Engraphis to Qdrant (self-hosted Docker) or Weaviate — both handle vault imports, maintain the vector index, and add the features Engraphis lacks.

**The upgrade sequence that makes sense:** start with Engraphis. When chunking becomes necessary, add a pre-processing step that splits documents before import. When the vault outgrows what Engraphis handles well, migrate to Qdrant or Weaviate. Measure actual retrieval quality before migrating — most personal vaults never hit Engraphis's ceiling.

## Classifying durable claims

The semantic layer is not a transcript log and not a document store. It holds **claims** — and an unclassified claim store becomes a search index over sentences nobody wrote on purpose.

Every durable claim carries two axes and one key:

| Field | The question it answers | Values |
|---|---|---|
| `mtype` | **How** does this memory behave? | `semantic` (a standing fact or rule), `procedural` (a repeatable procedure), `episodic` (something that happened), `working` (in-flight scratch) |
| `claim_kind` | **What kind of thought** is it? | `context`, `decision`, `mistake`, `pattern`, `snapshot` |
| `subject_key` | **What is it about?** | a stable string you choose — `commons.vault_root`, `linter.invariants`, `sync.deleted_files` |

The two axes are orthogonal. `mtype` says how the memory behaves — whether it is a standing rule or an episode. `claim_kind` says what kind of thought it is. A procedure that exists because a mistake taught it something is `procedural` + `mistake`. A snapshot of what the vault looked like last Tuesday is `working` + `snapshot`. **Always set both.**

The subject key is what makes the layer maintainable. A later write with the same `subject_key` **supersedes** the earlier one instead of sitting beside it. Without it you accumulate five versions of the same rule and no way to tell which one is live.

The five claim kinds, and what each one is for:

| Kind | Use it for | Example |
|---|---|---|
| `context` | durable facts about the environment | where the vault lives, which tools are installed |
| `decision` | a choice, with its rationale | "the protocol file lives at the vault root, because…" |
| `mistake` | what went wrong, and the lesson | "the sync daemon restored a deleted file — verify after deleting" |
| `pattern` | a repeatable rule | "never satisfy a lint pass by deleting a document" |
| `snapshot` | the state of the world at a point in time | the vault's file count on a given date |

A write, in the shape the tool expects:

```
engraphis_remember(
  content="The vault root is <VAULT-PATH>, synced through iCloud Drive.",
  mtype="semantic",
  claim_kind="context",
  subject_key="commons.vault_root",
  importance=0.6
)
```

Running the same call again with the same `subject_key` replaces the earlier claim instead of adding a second one. That is the whole point: the key is what keeps a durable memory from becoming a pile.

Two habits keep the layer clean. **Point, do not copy.** If a fact's home is a document, the memory holds a pointer to it — a copy goes stale the moment the document changes. And **never write documents into the semantic layer**; it is not a source-document store and not a transcript log.

## End-to-end setup checklist

For first-time setup, run through these in order:

1. ☐ Identify the sync-rooted directory for the vault. Confirm a file written there appears on the second machine within a minute.
2. ☐ Create the convention folders: `_agent-handoffs/`, `_agent-<your-agent>/`, `_private/` at the vault root.
3. ☐ Add a README.md to each agent's folder using the template above.
4. ☐ Write the root protocol file — under a page, with the artifact destinations, the mandatory conventions, and the known traps.
5. ☐ Add the frontmatter vocabulary (`type:`, `status:`) to every note, and settle which values your vault uses.
6. ☐ Install the read-only linter, and confirm it catches a deliberately broken link.
7. ☐ Create the two live views: a typed-note index and a pruning queue.
8. ☐ Install Engraphis (or substitute vector DB) and run the one-time import.
9. ☐ Schedule the daily re-index cron job.
10. ☐ Configure the agent's startup sequence — embed the startup prompt or wire it into a `/startup` keyword.
11. ☐ Configure the agent's write check — embed the write-check prompt so it runs at session end.
12. ☐ Configure the session-end ritual — status-file refresh, durable-claim capture, and a linter run whenever the vault's structure changed.
13. ☐ Choose the claim kinds you will use and your subject-key convention, then write the first five claims.
14. ☐ Run a smoke test: have the agent write a test summary to its own subspace, then start a new session and confirm the startup scan picks it up.
15. ☐ Set a calendar reminder for the first quarterly hygiene pass.

Once these are in place, the commons is operational. Subsequent work is maintenance, not setup.
