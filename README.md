# AI_Articles

Published articles and essays on AI tools, agent patterns, and productivity systems.

By [Gary Garcia](https://github.com/garciacionet-alt) · `#TheStrategicTechnicalAlliancesGuy`

---

## What this repo is

A small, personal publication of reference patterns and practical essays for people using AI agents to do real work. Each article ships with a portable pattern description and a concrete implementation guide.

Articles are written from the practitioner side — after running the pattern, not before.

## Articles

| Article | What it covers | Pattern | Implementation |
|---|---|---|---|
| [Agent Memory Commons](./agent-memory-commons/) | A shared file space that lets multiple AI agents (Hermes, Claude Code, Minimax M3, OpenCode, custom openclaw) share context through a synced Obsidian vault — no coordination overhead, no API contracts | [PATTERN.md](./agent-memory-commons/PATTERN.md) | [IMPLEMENTATION.md](./agent-memory-commons/IMPLEMENTATION.md) |

More articles coming.

---

## How to read

Each article follows the same shape:

- **README** — entry point, audience, quick-start
- **PATTERN** — the portable pattern: why, what, design principles, failure modes. Read this if you want the mental model.
- **IMPLEMENTATION** — the concrete setup: env vars, commands, prompts, shell scripts, end-to-end checklist. Read this if you're going to build it.
- **scripts/** — runnable shell scripts you can copy and adapt.
- **examples/** — worked examples of the pattern in practice, copyable as templates.

If you only have ten minutes, read the article's README. If you have an hour, read README + PATTERN. If you're going to build it, also read IMPLEMENTATION and run the scripts.

## Audience

This repo is for people using AI agents to do professional work — partnerships, alliances, technical sales, product work, research — and finding the lack of inter-agent context painful.

If you only run one agent on one computer, this repo is overkill. If you run two or more agents and want them to stop re-learning the same context every session, you'll find something useful here.

## License

- **Prose content** (READMEs, PATTERN.md, IMPLEMENTATION.md) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free to share and adapt with attribution.
- **Code and scripts** (`scripts/`, `examples/`) — [MIT License](./LICENSE). See `LICENSE` for full terms.

---

*This is a personal publication. Articles represent current thinking and are subject to revision.*
