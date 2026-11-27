# Agent Memory Commons

A pattern for letting multiple AI agents — Hermes, Claude Code, Minimax M3, OpenCode, custom openclaw setups — share context with each other through a synced file tree. No coordination overhead. No API contracts. Files in a folder.

## The problem

If you run more than one AI agent, you've probably noticed they don't share context with each other. Each session starts from zero. The research agent's findings are invisible to the writing agent. The observation agent's notes are invisible to the planning agent. You become the integration layer, copying context manually from one agent's output to another agent's input.

## The pattern

An **Agent Memory Commons** is a shared file space — typically inside a synced Obsidian vault and vector indexed using Engraphis — where multiple agents agree to write into prefixed subspaces and read from anywhere. Each agent owns its own folder (`_agent-hermes/`, `_agent-claude-code/`, `_agent-offgrid/`); everyone reads freely. The folder prefix is the only mandatory metadata; everything else is free-form prose.

The payoff compounds: every agent that joins later inherits what the others learned.

The cost is one convention (prefixed folders), one practice (closure lines on ended projects), one sync routine (verify weekly that files are propagating) — and one operating layer that keeps the whole thing legible once the folder stops being small: a root protocol file, a closed frontmatter vocabulary, a read-only linter, live views, and a session-end ritual. Without it, a commons degrades quietly: links rot, frontmatter drifts, and agents start treating last year's document as current.

One **optional add-on** sits on top of that: a Git repository over the vault tree, so the commons keeps a history of its own structure — what changed, who changed it, and how to undo a restructure that went wrong. It is not required, it does not replace the sync service, and it changes none of the pattern's commitments. Both documents cover what it adds and what it costs, so you can decide whether your commons needs it.

## What's in this article

| Document | What it covers |
|---|---|
| [PATTERN.md](./PATTERN.md) | The pattern itself: purpose, design principles, sync directories, layered memory architecture, startup discipline, basic setup, the operating layer, the **optional version-control add-on**, failure modes. Portable across any single-user multi-agent setup. |
| [IMPLEMENTATION.md](./IMPLEMENTATION.md) | The concrete implementation: env vars, session-startup and session-end prompts, the read-only linter, live views, claim classification, Engraphis setup, alternative vector databases, the **optional version-control setup**, shell scripts, end-to-end setup checklist. |
| [scripts/](./scripts/) | Four scripts: `commons-startup.sh` for session bootstrap, `commons-hygiene.sh` for quarterly maintenance, `lint.py` for the read-only frontmatter and link check, and `check_bases.py` for the view validator. All report rather than modify. |
| [Categories/](./Categories/) | The category notes. Each one defines what belongs in a category and embeds a live view of the notes that carry it. Copy the set, or define your own. |
| [Bases/](./Bases/) | The live views, as Obsidian Bases files: everything, agents, the newsletter strand, and hand-offs. Copy, rename, and edit the filters. |
| [Templates/](./Templates/) | Seven document templates — design, operations, project, reference, measurement, note and hand-off — each already carrying the frontmatter the linter expects. |
| [types.json](./types.json) | The property-to-type map Obsidian reads, so `categories` is a list, `updated` is a date, and the rest are text. Drop it into `.obsidian/`. |
| [examples/](./examples/) | A worked example: the `_agent-hermes/` README filled in. Use this as a template for your own agent subspaces. |

### The property layer, and how to adopt it

The category notes, the views and the templates are the part of the operating layer that turns a folder tree into something an agent can navigate by meaning rather than by path. Three things have to arrive together or none of them work:

1. **The categories** — a closed set of nine, each a note under `Categories/` so that `[[design]]` resolves to something rather than to a dangling link.
2. **The views** — `Bases/` files that filter on `category` and `categories`, so the axis is queryable rather than decorative.
3. **The linter** — `scripts/lint.py`, which is what keeps the vocabulary closed. It is the authority, not the prose.

The linter is the one piece that needs a word of configuration. Three folder names are **empty by default**, meaning *not configured*: `AMC_DIR`, `AMC_PUBLISH_DIR` and `AMC_SNAPSHOT_DIR`. If your vault keeps the AMC's own documents, a folder of published copies, or a dated import snapshot, set the matching variables and the linter will stop treating those files as ordinary documents:

```bash
AMC_DIR=<your-amc-folder>/ AMC_PUBLISH_DIR=<your-publish-folder>/ \
  AMC_SNAPSHOT_DIR=<your-snapshot-folder>/ \
  python3 scripts/lint.py --vault ~/your-vault
```

With them unset, the linter is still correct for a vault with no such folders — it simply has no reason to exempt them. Set only the ones that apply: a variable left unset exempts nothing, and every file under a folder you did not name is linted as an ordinary document.


## Audience

This article is for people using multiple AI agents to do real work and finding the lack of inter-agent context painful. Specifically:

- Practitioners running **Hermes**, **Claude Code**, **Minimax M3**, **OpenCode**, or custom **openclaw** setups alongside each other
- Developers building their own agents and wanting them to share state with other tools
- Anyone with an Obsidian vault who wants their agents to be able to write into it without breaking their notes

If you only run one agent on one computer, this pattern is overkill. If you run two or more agents and want them to stop re-learning the same context every session, read on.

## Quick start

1. Read [PATTERN.md](./PATTERN.md) for the design rationale.
2. Read the "Basic setup" section in [IMPLEMENTATION.md](./IMPLEMENTATION.md#basic-setup) for the seven steps, then [The operating layer](./IMPLEMENTATION.md#the-operating-layer) for what keeps the result usable.
3. Run through the end-to-end [setup checklist](./IMPLEMENTATION.md#end-to-end-setup-checklist).
4. Copy [examples/_agent-hermes/](./examples/_agent-hermes/) as a template for your first agent subspace.

## Companion resources

- **LinkedIn companion** (essay + carousel): [*Why I Built an Agent Memory Commons*](https://www.linkedin.com/pulse/why-i-built-agent-memory-commons-gary-garcia-ezs2c) — published 27 September 2026 in **The Technical Alliances Letter** newsletter. The article is also listed on my LinkedIn profile as a GitHub publication.
- **Author:** [Gary Garcia](https://github.com/garciacionet-alt) — written from the practitioner side, after running this pattern across multiple agents on a single Obsidian vault.

## License

- **Prose content** (this README, PATTERN.md, IMPLEMENTATION.md) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free to share and adapt with attribution.
- **Code and scripts** (`scripts/`, `examples/`) — [MIT License](../LICENSE). See `LICENSE` for full terms.

---

*This article is one of two in the AI_Articles repo. More patterns and reference implementations will land here over time.*
