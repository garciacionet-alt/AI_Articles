---
title: Agent Memory Commons — Pattern Description and Setup
status: design-pattern
applies-to: any single-user setup with multiple AI agents and one or more computers
companion: agent-memory-commons-implementation.md
updated: 2026-10-20
---

# Agent Memory Commons

> **Companion document:** This file describes the pattern. For the concrete implementation — Engraphis setup, env vars, session-startup prompts, and shell scripts — see [agent-memory-commons-implementation.md](./agent-memory-commons-implementation.md).

## Purpose

An **Agent Memory Commons** is a shared file space in which multiple AI agents — running in different processes, on different computers, for different purposes — can leave observations, work products, and notes that other agents can read. The commons is not a database. It is a structured file tree that all participating agents agree to write into and read from.

The purpose is to let agents **inherit context from one another without coordination overhead.** When one agent does work for a user and writes a summary to the commons, every other agent that later works on a related problem can read that summary and start with that context. The user does not have to re-explain prior work, and the next agent does not have to start from zero.

The commons is distinct from three other things an agent typically has:

- **Agent-internal memory.** A small, structured store of facts about the user and operating conventions, injected into every session. Lives inside the agent's runtime, not in the commons.
- **A vector database.** A semantic-search layer that lets an agent retrieve relevant context by meaning, not by exact filename. May index files that live in the commons; the index itself is not the commons.
- **A personal knowledge tree.** A note-taking structure (Obsidian, Logseq, plain Markdown folders) where the user captures their own thinking. The user owns this; agents may write into prefixed subspaces within it.

The commons is the **integration layer** between these. Agent-internal memory is for behavioral defaults. Vector databases are for retrieval. The personal knowledge tree is the human's own. The commons is what lets an agent's work product become part of the user's broader record and become readable by other agents later.

## Why this matters

Without a commons, every agent session starts from zero. The user has to re-explain prior work, prior decisions, prior context. Each agent makes decisions that may contradict decisions other agents made in adjacent sessions. The user becomes the integration layer, manually copying context from one agent's output to another agent's input.

With a commons, agents accumulate shared context over time. A research agent's findings become available to a writing agent. An observation agent's notes become available to a planning agent. The user does not have to relay context manually. Decisions become traceable across the work product of multiple agents.

The cost is hygiene: a commons without discipline becomes a swamp. The rest of this document describes the practices that keep a commons useful as it grows.

## Design principles

**No agent owns the commons.** Each agent writes into its own prefixed subspace. Reads from anywhere. This makes coordination unnecessary — agents do not need to know each other exists, do not need API contracts, do not need to negotiate who writes what where.

**Provenance is structural.** A folder prefixed with an agent name is owned by that agent. A file without an agent prefix is owned by the user. This convention is the only metadata that is mandatory; everything else is free-form prose.

**Files are durable.** Files in the commons are not ephemeral. They persist across agent sessions, across computer reboots, across software upgrades. An observation that was correct at the moment it was written remains readable years later, even if its subject matter has moved on.

**New agents join for free.** When a new agent arrives, it can begin reading the commons immediately. It does not need onboarding beyond knowing the path. It begins writing into its own prefixed subspace as soon as it produces work product.

**The commons maintains its own hygiene.** The artifacts that keep the commons legible — the protocol file, the linter, the views, the session-end ritual — live inside the commons. A commons that depends on the user remembering to tidy it is not a system; it is a folder with good intentions.

## Sync directories and the multi-computer commons

A single computer's commons is straightforward: an agent writes to disk, another agent reads from disk. The complication arises when the user works across more than one computer — a laptop on the road, a desktop at the office, a workstation in the home office — and expects the commons to be coherent across all of them.

The simplest mechanism is a **sync directory**: a folder that the operating system or a third-party sync service replicates across machines. The user's note-taking app (Obsidian, Logseq, Notion) typically already provides this: the vault is a local folder that the app syncs to the cloud and back down to every device the user opens it on. Other sync options include:

- **iCloud Drive.** On macOS, iCloud Drive folders are reachable under `~/Library/Mobile Documents/`. Files written there are pushed to other devices signed into the same iCloud account within seconds to minutes. This is the sync mechanism Obsidian vaults typically use on Apple platforms.
- **Syncthing.** A peer-to-peer sync service that replicates a folder across machines directly, with no central server. Useful when the user does not want third-party cloud storage to hold the commons.
- **Dropbox / Google Drive / OneDrive.** Third-party file-syncing services that all provide a folder-on-disk that replicates to the cloud and to other devices. Suitable for the commons as long as the agent writes atomically (write the full file, do not partial-write).
- **Git.** A version-controlled folder, manually pushed and pulled. Slower but produces a complete history. Best for users who want full traceability of changes.

The commons lives inside a sync-rooted directory. The sync service handles replication. Agents on each machine read and write the same files. The path that an agent on the laptop sees is the same path that an agent on the desktop sees, modulo per-machine directory aliases (a symlink or shortcut at `~/Vault/` pointing to the sync root, for example).

When choosing a sync mechanism, three properties matter:

- **Latency.** How quickly does a write on one machine become visible on another? For an agent to read what another agent just wrote in the same session, latency must be sub-minute. iCloud and Dropbox typically satisfy this; manual git push does not.
- **Conflict resolution.** If two agents on two machines edit the same file simultaneously, what happens? iCloud, Dropbox, and Syncthing all keep both copies and surface a conflict file; the user resolves manually. For a commons where agents typically write to distinct files, conflicts are rare; for files that multiple agents might update, a single-writer convention is wise.
- **Offline behavior.** What happens when the laptop is offline for a day? Syncthing and git queue changes and replay on reconnect. iCloud and Dropbox queue as well. The commons remains consistent across machines once both come back online.

A useful property of the file-tree commons is that it survives sync limitations better than a database would. If a write is delayed, the file simply appears later. If a conflict occurs, the agent or user resolves it manually. The system is degraded, not broken.

## Roles in a layered memory architecture

A complete memory architecture for an agent-assisted workflow involves several layers, each with a different role. The commons is one layer among several.

**Layer 1: Agent-internal memory.** A small, structured store of facts and conventions that is injected into every session. Typical size: 1,500 to 3,000 characters. Typical contents: who the user is, environment facts, standing conventions, decision rules that apply regardless of task. This layer is loaded into the model's context automatically. It is not a file the agent writes to during work — it is edited through explicit memory operations and is intended to be persistent across sessions.

The role of agent-internal memory is to encode **behavioral defaults**. *Soft-brags are out. The cadence is Tuesday and Thursday. The user prefers file-by-default over memory.* These are facts that should affect every session, regardless of what work the session is doing.

**Layer 2: Personal knowledge tree.** A note-taking structure the user maintains for their own thinking. On Apple platforms, this is often an Obsidian vault synced via iCloud Drive. The user writes here by hand or by capturing from other tools. It is the user's primary surface for their own notes.

The role of the personal knowledge tree is to be the **human's own record**. It is not optimized for agents; it is optimized for the user. The folder structure, naming conventions, and content style reflect the user's preferences.

**Layer 3: Agent memory commons.** A shared file space where agents write work products, observations, and notes. Distinct from the personal knowledge tree in that agents write here, not the user. Usually located inside the personal knowledge tree (a folder prefixed with the agent name), so both the user and other agents can see it.

The role of the commons is **inter-agent context**. When one agent finishes work, the next agent should not start from zero. The commons makes prior work available.

**Layer 4: Vector database.** A semantic-search layer that lets agents retrieve context by meaning rather than by exact filename. May index files that live in the commons and the personal knowledge tree. The index itself is separate from the data; the data is the source of truth.

The role of the vector database is **retrieval at scale**. Once the commons grows to hundreds of files, exact-filename search starts to lose its edge. A vector index lets an agent ask "what have I written about partner advisory councils?" and receive relevant files even if the exact term is not in the filename.

The four layers compose. Agent-internal memory carries behavioral defaults into every session. The personal knowledge tree holds the user's own notes. The commons holds work products from prior agent sessions, organized by agent. The vector database indexes both, providing semantic retrieval when filename-based search falls short.

A common mistake is conflating layers. Treating the commons as a replacement for agent-internal memory produces bloat — behavioral defaults that should be loaded every session become page-in loads from disk. Treating the personal knowledge tree as the commons means the user's notes get mixed with machine-generated summaries. The layers are distinct in role, and the right move when designing a system is to identify which layer a given piece of information belongs to.

## When to load from the commons

The commons only provides value if agents actually read from it. This requires a session startup discipline — a small set of rules that run at the beginning of every session, before any task work begins.

**The session startup sequence:**

1. **Agent-internal memory loads automatically.** Not a decision — this is the agent runtime's base context. Do not skip this.
2. **Scan the commons for task-relevant recent files.** Before starting any task, look for files in the relevant agent subspaces that were modified recently (last 7 days) and are related to the current topic. To find which agent subspace is relevant, read each `_agent-*/README.md` first — these tell you what each folder contains. This is not a full read — it is a lightweight scan of recently-modified files in subspaces that are likely to be relevant.
3. **Query the vector database if the task is exploratory.** If the task is vague or broad ("what's our current thinking on X?"), the vector index can surface relevant files even when filenames are not exact matches. Call the semantic search layer with the task description and read the top results.
4. **Open specific Obsidian notes when the user references them.** If the user says "see my note at..." or references a specific document, open it directly. Do not route through the vector index for specific references.
5. **Write to the commons when the session produces work worth preserving.** Before ending a session, ask: will another agent working on this topic need what I produced? If yes, write a summary to the relevant agent subspace. Use date prefixes. Close the file properly.

**The read/write distinction matters.** Reading from the commons is proactive — it happens at session start, every session, for every non-trivial task. Writing is selective — it happens only when the work product has reuse value. Over-writing to the commons is a failure mode: files that are not useful to other agents clutter the commons and dilute signal. When in doubt, write the summary; when confident the work has no reuse value, skip it.

**The trigger heuristic for writing:**
- Did the session produce a decision, a finding, a drafted document, or a status update? → write a summary.
- Did the session produce ephemeral observations, scratch work, or debugging output? → keep locally, do not write to commons.

**The trigger heuristic for searching the vector database:**
- Specific file or topic name known → open directly.
- Vague or exploratory question ("what do we know about X?") → semantic search.
- User's own notes referenced → open the Obsidian file directly.
- Task spans multiple agents or a long time horizon → vector search + scan of recent files.

## Basic setup

The following describes a minimal commons setup. Paths are abstracted; replace with paths appropriate to the user's environment. For the concrete implementation of these steps — including vector-DB installation, env vars, and shell scripts — see [agent-memory-commons-implementation.md](./agent-memory-commons-implementation.md).

Steps 1 to 7 are the minimum viable commons: enough to start, not enough to survive the first year of use. The operating layer that comes after them is what keeps it navigable once the folder stops being small.

### 1. Choose a sync-rooted directory

Pick a directory that is already synced across the user's machines. On Apple platforms with an Obsidian vault, this is typically:

```
~/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<OBSIDIAN-VAULT-NAME>/
```

The directory should be:

- **Already reachable from every device** the user works from. Test by writing a file on one device and confirming it appears on another within a minute.
- **Durable across reboots and software updates.** iCloud Drive directories and Obsidian vaults typically satisfy this.
- **Not inside an application-specific container.** Some applications sandbox their data; the commons should not be inside such a container, because other agents on other machines will not have access.

### 2. Create the agent subspace convention

Inside the chosen directory, create one prefixed folder per agent. The convention is `_agent-name/` (underscore prefix to distinguish from user-owned folders, lowercase, hyphenated).

Example:

```
<COMMONS-ROOT>/
├── _agent-A/         ← folder for agent A's work
├── _agent-B/         ← folder for agent B's work
├── _agent-C/         ← folder for agent C's work
└── ...               ← user-owned folders, no prefix
```

Each agent's folder is its own workspace. The agent writes only into its own prefixed folder. The agent reads from any folder in the commons.

### 3. Add a README.md to each agent's folder

The README states:

- **What this folder is.** One sentence.
- **Who writes here.** The agent's name and version.
- **What is authoritative vs. observational.** Some folders contain primary work product (research findings, drafted documents). Some contain secondary observations (screen-time logs, transcribed meetings). The README declares which is which.
- **The naming convention used inside the folder.** Date-prefixed (`YYYY-MM-DD-title.md`), topic-prefixed (`topic-summary.md`), or free-form. Each agent picks what fits its work.

The README does not need to be long. One paragraph is sufficient. The startup-scan step in the previous section ("read each `_agent-*/README.md` first") depends on these READMEs existing.

### 4. Establish a sync verification routine

Once a week, the user opens the commons from a second device and confirms that a recently-written file is present. This is a small manual check that catches sync failures early — the kinds of failures where iCloud silently stops syncing because of a quota, or a Syncthing device falls out of the cluster.

The check is not an automated test. It is a five-second habit, like checking that the calendar is syncing.

### 5. Establish a closure convention

When a project ends, the agent that owned it writes a single line at the top of its project folder:

```
<!-- CLOSED YYYY-MM-DD -->
```

That line tells every other agent: this work is finished. Do not build on it. The closure line is not deleted. It accumulates as a record of what has been completed.

This is the single most important hygiene practice. Without it, the commons accumulates stale work product that other agents treat as current. With it, the commons stays navigable.

Note: this closure marker is reserved for *project folders*. Individual session summaries within an agent's subspace are not "closed" — they are simply complete. Mixing the two markers creates ambiguity for later grep-based searches.

### 6. Index the commons with a vector database

Once the commons grows beyond approximately 200 files, exact-filename search starts to lose its edge. A vector index provides semantic retrieval — an agent can ask "what have I written about partner advisory councils?" and receive relevant files even when the exact term does not appear in any filename. The index is additive; the file tree is always the source of truth.

The recommended approach is to use a tool that natively supports Obsidian vault imports and incremental updates. [Engraphis](https://engraphis.com) is one such tool. It understands Obsidian's vault structure (frontmatter, tags, wikilinks), imports files as semantic memories, and maintains a vector index. The import is one-shot per run; the tool handles updates (files that changed since the last import are re-imported with `--on-conflict replace`).

The concrete setup commands, daily re-index cron, alternatives table, and upgrade paths live in the [implementation document](./agent-memory-commons-implementation.md#index-the-commons-with-a-vector-database).

#### Scope and exclusion

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

### 7. Optional: a hygiene pass at three months

After three months of operation, spend an hour reviewing the commons. Look for:

- Folders that have not been written to in 60+ days and are not closed. Add closure lines.
- Filename inconsistencies within an agent's folder. Standardize.
- Files whose content has aged out of usefulness. Move them to an `_archive/` folder inside the agent's subspace, or delete.

This is not a one-time cleanup. It is a recurring practice, like reviewing the calendar at the start of a new season.

## The operating layer

The seven steps above produce a folder with a convention in it. They do not produce a commons that is still legible six months later. Conventions decay silently: nothing breaks, the links rot, the frontmatter drifts, and one day an agent cannot tell whether a document is current or last year's.

The answer is an operating layer — a small set of artifacts that keep the commons honest without requiring anyone to police it by hand. Six pieces, each cheap, each doing a job that is invisible when it works and expensive when it is missing.

**A protocol file at the root.** One short file, loaded automatically by whatever agent runtime touches the vault, answering the questions every new agent asks: where do artifacts go, which conventions are mandatory, what must never be touched. Keep it under a page. The moment it grows past that, it stops being read.

**A frontmatter vocabulary.** Two fields on every note, and a closed set of values for each. `type:` says what kind of note it is. `status:` says where the note is in its life — and it is a lifecycle state, never a description. `active` and `stale` are states; "verified Oct 16 against v1.29" is a note, and it belongs in its own field. A closed vocabulary exists so that a tool can filter on it without a human reading every file.

**`stale` as the pruning marker.** Nothing is ever deleted automatically. A note marked `stale` enters a queue, and a human approves every removal. This is what makes it safe to write a lot: the cost of an unwanted note is one flag, not a deleted file and a revert.

**A read-only linter.** A script that reports — and never modifies — the failure modes a reader cannot see: links that point at nothing, pages nothing links to, wikilinks that resolve to no file, frontmatter that has drifted outside the vocabulary. It must be strictly read-only. A linter that rewrites files is a mutator wearing a lint coat, and one day it will rewrite something someone cared about.

> **The linter must never be satisfied by deleting a document.** When a lint fails on an orphan page, the fix is to link it from somewhere real, or to mark it `stale` — not to remove it. A lint pass that quietly deletes content is a data-loss event with a green exit code.

**Live views.** A database-style view over the vault — a typed-note index and a pruning queue — so the state of the commons is legible in the user's note app without running a script. Views read the frontmatter vocabulary, which is exactly why that vocabulary has to be closed and typed.

**A session-end ritual.** Every session ends the same way: refresh the status file, capture anything durable in the semantic layer, and write a hand-off only when the next step is genuinely someone else's job. The ritual is short because it runs every time; anything that takes more than a minute will not survive the first busy week.

The semantic layer deserves one more rule, because that is where a commons quietly turns into a transcript log. Durable claims are classified on two axes: **how the memory behaves** (a standing fact, a procedure, an episode of something that happened) and **what kind of thought it is** (context, a decision, a mistake, a pattern, a snapshot of the world at a point in time). Every claim also carries a stable subject key, so a later claim about the same thing supersedes the earlier one instead of piling up beside it. Without classification and a subject key, a semantic layer becomes a search index over sentences nobody wrote on purpose. The concrete tool calls are in the implementation document.

## Common failure modes and mitigations

**Stale data accumulates.** Old projects sit in agent folders, undated, and other agents treat them as current. *Mitigation: closure lines on every ended project; mark superseded notes `status: stale` so they enter the pruning queue; periodic hygiene pass.*

**Filename collisions across agents.** Two agents write `summary.md` on the same day, both without date prefixes. *Mitigation: date-prefixed filenames (`YYYY-MM-DD-summary.md`); agent-prefixed folders do most of the work.*

**Sync latency surprises an agent.** An agent writes a file and immediately tries to read it from a second machine that has not synced yet. *Mitigation: the agent that writes is the only consumer that reads immediately; cross-machine reads happen in later sessions, after sync has had time to propagate.*

**The sync service resurrects deleted files.** A file deleted from the working tree can reappear minutes later with its original timestamp, because the sync daemon is still holding it. "The file is gone" and "the file is gone" can both be true within the same hour. *Mitigation: after any delete, re-check the filesystem rather than trusting the exit code of the tool that performed the delete. A trash utility that reports success while leaving the file in place is the normal case here, not the exception.*

**The workspace cannot delete.** Agents often run in a sandbox where unlink, rename, and move are denied. A "move" attempted there fails halfway and leaves both halves behind, which is worse than not moving at all. *Mitigation: perform a move as a copy plus a redirect stub, hand the real deletion to a script run from a normal terminal, and verify the final state against the filesystem.*

**Version control inside a restricted workspace is a trap.** Git takes a lock file before it writes an index. In a sandbox that cannot remove lock files, the write fails, the lock is left behind, and the next legitimate `git` command — from a human, in a real terminal — is blocked by the agent's leftover. Worse, some version-control libraries offer an "index rebuild" convenience that materialises the entire tree back into the working directory, silently reverting uncommitted work while appearing to succeed. *Mitigation: commit from a normal terminal, or from a library that writes the index without lock files; never call an API that writes the tree to disk to "fix" the index; stage an explicit list of paths rather than the whole tree, and verify what you wrote afterwards.*

**The note application owns its own data files.** View and configuration files written by a note app are rewritten whenever the app saves them — keys reordered, comments stripped, formatting normalised. Editing them by hand is a treadmill, and every save produces a spurious diff. *Mitigation: keep documentation in ordinary Markdown files rather than inside the app's data files; write the data files in the app's own normalised style; expect them to churn in version control and exclude them when that churn is noise.*

**Frontmatter drifts.** Notes accumulate fields that no longer mean anything — a status that became a sentence, a type that was invented locally. Nothing breaks, and the views built on those fields quietly stop working. *Mitigation: a closed vocabulary for `type:` and `status:`, enforced by the linter, so drift shows up as a warning instead of as a silently empty view.*

**The semantic layer becomes a transcript log.** Everything that happened gets written down, so nothing can be found. *Mitigation: classify every durable claim by kind, give it a stable subject key, and keep only what another agent would need to pick the work up.*

**Privacy surface.** Agent-written files in the commons may contain sensitive material — transcripts, drafts of private correspondence, internal observations. *Mitigation: keep raw observation streams in the observing agent's local storage; only structured summaries enter the commons. For additional isolation, use a `_private/` folder in the vault root: anything inside it is excluded from indexing by convention. Do not place sensitive files outside this folder if exclusion from the index is required.*

**Vector index drift.** If a vector index is added, it can drift out of sync with the file tree. *Mitigation: re-index on a schedule, or trigger re-indexing when a file's mtime changes.*

## What this pattern is not

- **Not a replacement for the user's own notes.** The user owns the unprefixed folders. Agents do not write there.
- **Not a database.** No schema enforcement, no ACID guarantees. The structure is structural; the discipline is convention.
- **Not a single source of truth.** Different agents may have different views of the same event. Each is its own perspective. The user reconciles when needed.
- **Not a substitute for agent-internal memory.** Behavioral defaults and operating conventions belong in agent-internal memory, not in the commons. The commons is for work product, not for "this is how the user prefers responses."

## Variants

The pattern adapts to several setups:

- **Single computer, single agent.** The commons is just a folder. There is no sync to worry about.
- **Single computer, multiple agents.** Same as above; agents read from one folder, write to prefixed subspaces.
- **Multiple computers, single agent.** The sync directory handles cross-machine coherence. The agent may run on each machine or only one.
- **Multiple computers, multiple agents.** The full pattern described above. Sync directory plus prefixed subspaces plus sync verification routine.

Each variant adds complexity only where it is needed.

## Summary

The Agent Memory Commons is a small, simple pattern that solves a real problem: how to let multiple agents working for the same user share context without coordination overhead. The implementation cost is one convention (prefixed agent folders), one practice (closure lines on ended projects), one sync routine (verify weekly that files are propagating), and one operating layer — a root protocol file, a closed frontmatter vocabulary, a read-only linter, live views, and a session-end ritual.

The last item is what separates a commons that works from a folder that used to work. The pattern is easy to adopt and easy to lose: conventions decay quietly, and the only thing that keeps a commons navigable is a small set of artifacts that check themselves. The payoff compounds — every agent that joins later inherits what the others learned, and every session that ends properly leaves the next one something to stand on.
