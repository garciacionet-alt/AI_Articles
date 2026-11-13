# AI_Articles

Published articles and essays on AI tools, agent patterns, and productivity systems.

By [Gary Garcia](https://github.com/garciacionet-alt) · `#TheStrategicTechnicalAlliancesGuy`

[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/garciacionet-alt/badge.svg)](https://hub.xerj.org/contributors/garciacionet-alt)

---

## What this repo is

A small, personal publication of reference patterns and practical essays for people using AI agents to do real work. Each article ships with a portable pattern description and a concrete implementation guide.

Articles are written from the practitioner side — after running the pattern, not before.

## Articles

| Article | What it covers | Pattern | Implementation |
|---|---|---|---|
| [Agent Memory Commons](./agent-memory-commons/) | A shared file space that lets multiple AI agents (Hermes, Claude Code, Minimax M3, OpenCode, OpenHuman, custom openclaw) share context through a synced Obsidian vault — no coordination overhead, no API contracts — plus the operating layer that keeps it legible: a root protocol file, a closed frontmatter vocabulary, a read-only linter, live views, and a session-end ritual, and an optional version-control add-on for keeping a history of the vault's own structure | [PATTERN.md](./agent-memory-commons/PATTERN.md) | [IMPLEMENTATION.md](./agent-memory-commons/IMPLEMENTATION.md) |
| [Bot Identity](./bot-identity/) | One credential per bot. Every framework makes multi-agent easy; almost none tell you to give each bot its own channel token and OAuth grant — and without one you cannot scope, revoke, or attribute anything to a specific agent | [PATTERN.md](./bot-identity/PATTERN.md) | [IMPLEMENTATION.md](./bot-identity/IMPLEMENTATION.md) |
| [Tiiny Model Routing](./tiiny-model-routing/) | Routing delegated subtasks to the right model on a local appliance — the tier table, the NPU budget that constrains it, a delegation backend that routes per task, and a swap script that survives the watchdog | [README.md](./tiiny-model-routing/README.md) | [PATTERN.md](./tiiny-model-routing/PATTERN.md) · [IMPLEMENTATION.md](./tiiny-model-routing/IMPLEMENTATION.md) |
| [Tiiny Two Boxes](./tiiny-two-boxes/) | Running two local appliances as one system — the per-device credential, address and lock a second box needs, the vault/flex role split that stops the boxes evicting each other, and the failures that look like hardware problems but are not | [README.md](./tiiny-two-boxes/README.md) | [PATTERN.md](./tiiny-two-boxes/PATTERN.md) · [IMPLEMENTATION.md](./tiiny-two-boxes/IMPLEMENTATION.md) |
| [Tiiny Image Agency](./tiiny-image-agency/) | An image-generation API on a local appliance — words become a requirement vector, a deterministic resolver picks the model and explains itself, residency is managed as one transaction against a shared NPU pool, and a browser surface shows what the device is doing. Ships the whole application, its 465 tests, and the skill. **Built on macOS; a Linux or Windows port is wanted and is three known edits away** | [README.md](./tiiny-image-agency/README.md) | [PATTERN.md](./tiiny-image-agency/PATTERN.md) · [IMPLEMENTATION.md](./tiiny-image-agency/IMPLEMENTATION.md) |
| [Remote Agent Access](./remote-agent-access/) | Reaching an agent on your LAN from anywhere without opening a port — a chat bot as the remote control, the three planes of the design, and the routing that makes your own hardware worth reaching | [README.md](./remote-agent-access/README.md) | [PATTERN.md](./remote-agent-access/PATTERN.md) · [IMPLEMENTATION.md](./remote-agent-access/IMPLEMENTATION.md) |
| [Private Agent Network](./private-agent-network/) | A private network for an agent estate that spans machines — your agent's core in a cloud VPS, your files on a machine at home, neither able to reach the other. The tailnet that joins them, the one public listener that genuinely has to be public, the name trap that breaks webhook URLs silently, and the healthchecks that exercise the path instead of the process | [README.md](./private-agent-network/README.md) | [PATTERN.md](./private-agent-network/PATTERN.md) · [IMPLEMENTATION.md](./private-agent-network/IMPLEMENTATION.md) |
| [Tiiny guides](./Tiiny/) | Reference for the Tiiny Octo and the TiinyOS software it ships — every documentation surface the device exposes, how to tell the shipped documentation apart from your own data, where your API calls actually go, and what every model in the Model Store is actually good at | [README.md](./Tiiny/README.md) | [api-call-logging.md](./Tiiny/api-call-logging.md) · [model-catalogue.md](./Tiiny/model-catalogue.md) |

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
