# Agent Hermes Commons Subspace

**What this folder is:** Work products, session summaries, and status notes produced by Hermes (the Friendly/Neko-chan persona in this setup), the conversational AI agent on this machine.

**Who writes here:** Hermes only. Other agents in this commons read from this folder but do not write to it.

**What is authoritative:** Primary work products (drafted documents, research findings, design decisions, code reviews) unless marked observational. Each file's header indicates whether the content is authoritative or observational.

**Naming convention:** `YYYY-MM-DD-<topic>.md` for session summaries. Project work gets its own subfolder: `projects/<project-slug>/<file>.md`. Closed projects get `<!-- CLOSED YYYY-MM-DD -->` at the top of their folder.

**When to read from this folder:** At session startup, scan for files modified in the last 7 days. At any point during task work, if the current topic matches a recent file, open and read it.

**When to write to this folder:** Before ending any session that produced a decision, finding, draft, or status update. Skip writing for ephemeral work (debugging, exploration, transient analysis) — that lives in `/tmp/` or scratch directories.

## Folder layout

```
_agent-hermes/
├── README.md                    ← this file
├── YYYY-MM-DD-<topic>.md        ← session summaries (one per session worth preserving)
├── projects/
│   └── <project-slug>/          ← longer-running project work
│       ├── notes.md
│       ├── drafts/
│       └── <!-- CLOSED YYYY-MM-DD --> when project ends
└── _archive/                    ← moved here when content ages out of usefulness
```

## Examples of what to write here

- A session that produced a drafted LinkedIn article → `2026-09-28-newsletter-part-1-draft.md`
- A session that produced a design decision → `2026-09-15-decision-agent-memory-commons-pattern.md`
- A status update on an ongoing project → `projects/newsletter-series/status-2026-09-29.md`

## Examples of what NOT to write here

- Debug output from a failing build → keep in `/tmp/` or scratch
- A 30-second calculation → keep local, do not commons-write
- Raw terminal output from an exploration → keep local

## See also

- [../../PATTERN.md](../../PATTERN.md) — the Agent Memory Commons pattern this subspace participates in
- [../../IMPLEMENTATION.md](../../IMPLEMENTATION.md) — concrete setup, including session-startup prompts and write-check prompts
