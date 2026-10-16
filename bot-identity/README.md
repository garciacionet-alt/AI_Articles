# Bot Identity

Every current agent framework makes it easy to create many agents in one installation. Almost none of them tell you to give each agent its own credential.

This article is the practical companion to that gap. It covers what actually breaks when several bots share one identity, and the eight practices — plus a checker you can run — that prevent it.

## The problem

If you run more than one agent, you have probably given each one a name, a personality, and a job. You may not have given each one a **credential**.

Those are different things, and only one of them is an identity to the systems your agents talk to. A shared OAuth grant or a shared channel token makes four agents into one agent that happens to answer to four names.

The result is not a crash. It is worse than a crash. When one token is claimed by two gateways, one of them is quietly parked — it stops receiving, reports nothing, and the installation keeps looking healthy. Meanwhile every action your agents take lands in the provider's audit log under the same identity, so when something goes wrong there is no answer to the only question that matters: *which bot did this?*

## The pattern

**One bot, one credential.** Each bot holds its own channel token, its own OAuth grant, and its own API key — provisioned deliberately, scoped narrowly, and revocable without touching its siblings.

Everything else in this article follows from that one decision. Once credentials are per-bot, four things become possible that were not before: you can scope one bot read-only while another holds write, revoke one agent without disabling the rest, attribute an action in an audit log to a specific agent, and know which bot to look at when something fails.

The practices are named **BP-1** through **BP-8** and are stated in [PATTERN.md](./PATTERN.md).

## What's in this article

| Document | What it covers |
|---|---|
| [PATTERN.md](./PATTERN.md) | The portable pattern: what frameworks actually give you, five failure modes of shared credentials, the eight practices, a reference checklist, and the anti-patterns to avoid. Read this for the mental model. |
| [IMPLEMENTATION.md](./IMPLEMENTATION.md) | The concrete setup: provisioning one credential per bot, per-bot configuration anatomy, wiring a second OAuth grant, and an end-to-end setup checklist. Read this if you're going to build it. |
| [scripts/check-bot-credentials.sh](./scripts/check-bot-credentials.sh) | A read-only checker that finds credentials shared by more than one bot in an installation. Prints fingerprints, never secret values. |
| [examples/per-bot-config.md](./examples/per-bot-config.md) | A worked before/after showing two bots moving from a shared token to their own. Use it as a template. |

## Audience

This article is for people running several AI agents from one installation and finding that they cannot tell which one did what.

Specifically:

- Practitioners running **Hermes**, **Claude Code**, **Minimax M3**, **OpenCode**, **OpenHuman**, or custom **openclaw** setups alongside each other
- Anyone using **LangGraph**, **CrewAI**, **Mastra**, **Strands**, the **Google ADK**, the **OpenAI Agents SDK**, or the **Microsoft Agent Framework**
- Teams giving agents access to systems of record — calendar, billing, CRM, email — where "who did this" has to have an answer

If you run exactly one agent that never touches a shared credential, this is overkill. If you run two or more and have ever asked which one just did something, this is for you.

## Quick start

1. Run the checker against your agent home directory and see what you already share:

   ```bash
   ./scripts/check-bot-credentials.sh ~/.hermes
   ```

2. Read [PATTERN.md §2](./PATTERN.md#2-failure-modes) to recognise which failure you are currently in.

3. Work through [IMPLEMENTATION.md](./IMPLEMENTATION.md) to provision one credential per bot.

4. Re-run the checker until it reports `PASS`.

## Companion resources

- **LinkedIn article** — *Better Bot Practices for Business*, the business-framing essay with a 11-slide carousel. This repository holds the technical detail.
- **Related pattern:** [Agent Memory Commons](../agent-memory-commons/) — how to let the same set of agents share context. Read that one if your problem is that agents cannot see each other; read this one if your problem is that you cannot tell them apart.
- **Author:** [Gary Garcia](https://github.com/garciacionet-alt) — written from the practitioner side, after running multi-agent installations and watching the shared-credential failure happen.

## License

- **Prose content** (this README, PATTERN.md, IMPLEMENTATION.md, examples) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free to share and adapt with attribution.
- **Scripts** (`scripts/`) — [MIT License](../LICENSE). See `LICENSE` for full terms.

---

*Framework behaviour was verified against official documentation and vendor posts on 16 October 2026. Check current documentation before relying on specifics.*