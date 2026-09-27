# Agent Memory Commons

A pattern for letting multiple AI agents — Hermes, Claude Code, Minimax M3, OpenCode, custom openclaw setups — share context with each other through a synced file tree. No coordination overhead. No API contracts. Files in a folder.

## The problem

If you run more than one AI agent, you've probably noticed they don't share context with each other. Each session starts from zero. The research agent's findings are invisible to the writing agent. The observation agent's notes are invisible to the planning agent. You become the integration layer, copying context manually from one agent's output to another agent's input.

## The pattern

An **Agent Memory Commons** is a shared file space — typically inside a synced Obsidian vault — where multiple agents agree to write into prefixed subspaces and read from anywhere. Each agent owns its own folder (`_agent-hermes/`, `_agent-claude-code/`, `_agent-offgrid/`); everyone reads freely. The folder prefix is the only mandatory metadata; everything else is free-form prose.

The payoff compounds: every agent that joins later inherits what the others learned. The cost is one convention (prefixed folders), one practice (closure lines on ended projects), and one sync routine (verify weekly that files are propagating).

## What's in this article

| Document | What it covers |
|---|---|
| [PATTERN.md](./PATTERN.md) | The pattern itself: purpose, design principles, sync directories, layered memory architecture, startup discipline, basic setup, failure modes. Portable across any single-user multi-agent setup. |
| [IMPLEMENTATION.md](./IMPLEMENTATION.md) | The concrete implementation: env vars, session-startup prompts, scan/search/write prompts, Engraphis setup, alternative vector databases, shell scripts, end-to-end setup checklist. |
| [scripts/](./scripts/) | Two shell scripts: `commons-startup.sh` for session bootstrap and `commons-hygiene.sh` for quarterly maintenance. |
| [examples/](./examples/) | A worked example: the `_agent-hermes/` README filled in. Use this as a template for your own agent subspaces. |

## Audience

This article is for people using multiple AI agents to do real work and finding the lack of inter-agent context painful. Specifically:

- Practitioners running **Hermes**, **Claude Code**, **Minimax M3**, **OpenCode**, or custom **openclaw** setups alongside each other
- Developers building their own agents and wanting them to share state with other tools
- Anyone with an Obsidian vault who wants their agents to be able to write into it without breaking their notes

If you only run one agent on one computer, this pattern is overkill. If you run two or more agents and want them to stop re-learning the same context every session, read on.

## Quick start

1. Read [PATTERN.md](./PATTERN.md) for the design rationale.
2. Read the "Basic setup" section in [IMPLEMENTATION.md](./IMPLEMENTATION.md#basic-setup) for the seven steps.
3. Run through the end-to-end [setup checklist](./IMPLEMENTATION.md#end-to-end-setup-checklist).
4. Copy [examples/_agent-hermes/](./examples/_agent-hermes/) as a template for your first agent subspace.

## Companion resources

- **LinkedIn article** (companion essay, with carousel): *link coming soon — this article will be cross-linked from a LinkedIn post in the "Data-Driven Partnerships" series.*
- **Author:** [Gary Garcia](https://github.com/garciacionet-alt) — written from the practitioner side, after running this pattern across multiple agents on a single Obsidian vault.

## License

- **Prose content** (this README, PATTERN.md, IMPLEMENTATION.md) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free to share and adapt with attribution.
- **Code and scripts** (`scripts/`, `examples/`) — [MIT License](../LICENSE). See `LICENSE` for full terms.

---

*This is the first article in the AI_Articles repo. More patterns and reference implementations will land here over time.*
