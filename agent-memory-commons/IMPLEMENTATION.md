---
title: Agent Memory Commons — Implementation Manual
status: implementation
applies-to: setting up the commons pattern with concrete tooling
companion: agent-memory-commons.md
---

# Agent Memory Commons — Implementation

> **Companion document:** This file describes the concrete setup. For the pattern itself, the design principles, the sync-directory discussion, and the layered memory architecture, see [agent-memory-commons.md](./agent-memory-commons.md).
>
> The two files together are the complete reference. This one is the working manual; the other is the shareable description.

This document assumes the reader has read or skimmed [agent-memory-commons.md](./agent-memory-commons.md) and is now wiring up the pattern in a real environment. Paths are shown with `<VENDOR>`, `<VAULT>`, `<AGENT-NAME>`, and `<WORKSPACE>` placeholders; substitute the values appropriate to your setup.

## Memory layer configuration

Before session start, the agent needs to know the paths and tools for each layer. These are the values to set:

```
# Paths (adjust to your environment)
VAULT_PATH=~/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT-NAME>/
COMMONS_ROOT=<VAULT_PATH>/_agent-<agent-name>/
OBSIDIAN_VAULT=<VAULT_PATH>

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
2. Scan the commons: read each _agent-*/README.md to identify
   which agent subspace is relevant. Then list the 5 most-recently-
   modified files in that subspace. Read each summary.
3. If the task is vague or exploratory, call:
   engraphis graph search --query "<task description>"
   --workspace <WORKSPACE-NAME>
   Read the top-5 results.
4. If the user referenced a specific Obsidian note or file, open it
   directly from <OBSIDIAN_VAULT>/<relative-path>.
5. Begin task work.
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
# commons-startup.sh — run at agent session start
VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT>/"
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
find "$AGENT_FOLDER" -name "*.md" -mtime -7 | sort -r | head -10

echo ""
echo "=== Startup scan complete. Ready to begin. ==="
```

## Vault hygiene reminder (3-month)

Run this quarterly to keep the commons navigable:

```bash
#!/bin/bash
# commons-hygiene.sh
VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT>/"

echo "=== Unclosed projects (>60 days old) ==="
find "$VAULT" -name "*.md" -mtime +60 | while read f; do
    grep -q "CLOSED" "$f" || echo "MISSING CLOSURE: $f"
done

echo ""
echo "=== Empty agent folders ==="
find "$VAULT" -type d -name "_agent-*" -empty | while read d; do
    echo "Empty: $d"
done

echo ""
echo "=== Files without date prefix ==="
find "$VAULT/_agent-*" -name "*.md" ! -name "[0-9][0-9][0-9][0-9]-*" | head -10
```

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

## End-to-end setup checklist

For first-time setup, run through these in order:

1. ☐ Identify the sync-rooted directory for the vault. Confirm a file written there appears on the second machine within a minute.
2. ☐ Create the convention folders: `_agent-handoffs/`, `_agent-<your-agent>/`, `_private/` at the vault root.
3. ☐ Add a README.md to each agent's folder using the template above.
4. ☐ Install Engraphis (or substitute vector DB) and run the one-time import.
5. ☐ Schedule the daily re-index cron job.
6. ☐ Configure the agent's startup sequence — embed the startup prompt or wire it into a `/startup` keyword.
7. ☐ Configure the agent's write check — embed the write-check prompt so it runs at session end.
8. ☐ Run a smoke test: have the agent write a test summary to its own subspace, then start a new session and confirm the startup scan picks it up.
9. ☐ Set a calendar reminder for the first quarterly hygiene pass.

Once these are in place, the commons is operational. Subsequent work is maintenance, not setup.
