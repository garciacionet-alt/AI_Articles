# Bot Identity — Pattern

The portable pattern: why multi-agent installations need one credential per bot, what
fails when they don't have one, and the eight practices that resolve it.

For the concrete setup — provisioning tokens, per-bot configuration anatomy, and the
credential-collision check — see [IMPLEMENTATION.md](./IMPLEMENTATION.md).

---

## Summary

Every current agent framework makes it easy to create many agents in one installation. Almost none of
them tell you to give each agent its own credential.

This document restates the problem in technical terms and defines the practices that resolve it.

**The core claim:** frameworks have made agents *differentiated* but not *distinct*. They give you many
behaviours and one identity. Every serious failure mode of multi-bot systems follows from that gap.

---

## 1. What frameworks actually give you

When you add a second, third, or fourth agent to an installation, the frameworks differentiate them
**behaviourally**:

| Dimension | Typically per-agent | Typically shared |
|---|---|---|
| System prompt / instructions | ✅ Yes | — |
| Context window | ✅ Yes | — |
| Tool access | ✅ Often | — |
| Permissions | ✅ Often (tool-level) | — |
| Default model | ✅ Often configurable per agent | Inherited if left unset |
| **Channel credential (bot token)** | ❌ **No** | **Per installation** |
| **OAuth grant / API key** | ❌ **No** | **Per installation** |
| **Service account** | ❌ **No** | **Per installation** |
| **Rate limit quota** | ❌ **No** | **Per installation** |
| **Cost / usage attribution** | ❌ **No** | **Per installation** |
| **Audit attribution** | ❌ **No** | **Per installation** |

Surveyed frameworks and their multi-agent mechanisms:

- **Claude Code** — subagents, agent view, agent teams, dynamic workflows, projects. Per-agent context,
  tools, permissions, optionally model. Documentation states subagent requests "count toward the same
  usage limits as your main conversation."
- **Google ADK** — `root_agent` / `sub_agents` trees; Agent2Agent (A2A) for cross-framework agents; Agent
  Cards for discovery, served at a well-known path (the A2A spec has used both `/.well-known/agent.json`
  and `/.well-known/agent-card.json` across versions — check the spec version you are targeting).
- **Microsoft Agent Framework** — successor to Semantic Kernel and AutoGen; 1.0 GA April 2026; sequential,
  concurrent, handoff, and group-collaboration patterns.
- **OpenAI Agents SDK** — agents-as-tools (centralised) and handoffs (decentralised).
- **LangGraph** — subgraphs as the multi-agent mechanism; supervisor pattern.
- **CrewAI** — role-based crews with a manager agent in hierarchical mode.
- **Mastra** — `.network()` routing agents; supervisor, handoff, workflow, and council patterns.
- **Strands Agents (AWS)** — agents-as-tools, swarms, graphs, and meta-agents.
- **OpenClaw** — single self-hosted gateway serving many channels; "configuration is the only difference"
  between a personal assistant and a shared team deployment.

A2A Agent Cards come closest to per-agent identity, but they describe **inbound** capability discovery —
what an agent advertises to callers — not the **outbound** credential an agent uses to act.

### The one exception, and why it proves the rule

OpenAI's Dots, announced 29 September 2026, separates the two cases explicitly. A *primary* dot is a
personal convenience operating in the user's context. *Specialist* dots, for use inside an organisation,
are configured differently:

> "Your company sets up each dot with its own identity, credentials, and access to the systems it needs
> to complete its tasks."

Identity, credentials, and access — provisioned per agent, by IT, for enterprise use.

A frontier vendor independently reached the conclusion this document argues: **once agents touch systems
of record, per-agent identity stops being optional.** It was simply not reached by the frameworks, because
the frameworks are not accountable for it.

---

## 2. Failure modes

### 2.1 Channel credential contention

A bot token identifies one bot to its platform. The platform expects a single, unambiguous owner.

Run two gateways against one token and something must lose. The common outcome is worse than an error: the
losing adapter is **parked**. It stops receiving, reports no failure, and the installation continues to
look healthy. You are now talking to an agent you did not select, and the other one is unreachable for
reasons nothing in the interface will tell you.

This generalises beyond any single platform: **a channel credential is a singleton resource, and
singleton resources need an explicit owner.**

### 2.2 OAuth grant sharing

Sharing one OAuth grant across several agents produces four distinct failures.

**Refresh-token rotation.** Many providers rotate the refresh token on use and invalidate the previous one.
With two agents on one grant, agent A refreshes and agent B's stored token is now dead. The result is
intermittent `invalid_grant` errors that are non-deterministic, timing-dependent, and look like provider
flakiness. This is close to undiagnosable from the symptom.

**Scope ceiling.** A shared grant carries the union of every scope ever consented to. You cannot grant the
coder read-only calendar access while the assistant keeps write. Narrowing later requires new consent for
every agent on the grant.

**Rate-limit contention.** Quotas attach to the token or project. One agent's retry loop starves the
others. Neither agent's logs show the other as the cause, because neither agent can see the other's usage.

**Audit attribution.** Provider logs attribute an action to the OAuth client and the user, not to the
process that made the call. With several agents on one grant, every action in that log has the same author.
After an incident the useful question — *which agent did this?* — has no answer in the record.

There is a fifth, quieter failure: token caching. Any client library that caches access tokens by user or
client ID will serve one agent's cached token to another. This presents as a bizarre, impossible-to-explain
auth state.

### 2.3 Cross-installation collision

The worst case is two *installations* — say a local machine and a cloud deployment — configured against one
credential. The contention is identical, but it is now non-local, intermittent, and dependent on which
machine was awake. Diagnosis becomes guesswork because neither installation has visibility into the other.

### 2.4 Uncontainable blast radius

Permissions are a ceiling that can only be lowered for everyone simultaneously. If one bot requires write
access, every bot on the shared credential has it.

Revocation is strictly all-or-nothing. During an incident you cannot revoke the misbehaving agent without
disabling the business. The practical effect is that a compromised credential stays live longer than it
should — not from carelessness, but because containment is unavailable.

### 2.5 Silent degradation

Long-running integrations accumulate failure state that nothing surfaces. A component can sit in a
retrying, `needs_attention` condition for weeks without raising anything, because the signal lives in a
state file that a human has to go and read.

This is not exotic. It is the default experience of any agent estate that has grown past the point of
manual inspection — and it is a direct consequence of having more agents than you can watch.

---

## 3. Best practices

### BP-1 — Write the bot's purpose before you write its config

Every bot exists to do one job. Write that job down in a sentence before configuring anything.

A bot whose purpose cannot be stated in one sentence cannot be given deliberate permissions, a deliberate
model, or a deliberate scope — because you do not yet know what it needs.

*Test:* if you cannot name, in one sentence, what this bot is for, do not create it.

### BP-2 — One bot, one channel token

Each bot that can receive messages gets its own bot token, its own identity on that channel, and its own
name as it appears to users.

Shared tokens are the single most common multi-bot failure and the easiest to prevent. There is no
performance or convenience argument for sharing one.

### BP-3 — One bot, one OAuth grant

If two agents will ever hold the same OAuth grant, they are not two agents. They are one agent with a
scheduling bug.

- Never share a refresh token across agents.
- Never rely on a shared grant for two different privilege levels.
- When you need narrower scope, re-consent for that bot specifically.

### BP-4 — Choose each bot's default model deliberately

Model selection is a per-bot design decision, not a global setting. Two failure modes if you inherit:

- **A small agent on a frontier model** — a recurring bill nobody approved.
- **A complex agent on a small model** — quiet, plausible, wrong output. The more expensive failure.

Match cost, latency, and capability to the job the bot was actually defined to do in BP-1.

### BP-5 — Least privilege per bot, configured explicitly

Do not inherit permissions. Do not copy a configuration from a sibling.

The correct question is not "what can this bot be allowed to do?" but "what is the minimum this bot needs
to do its one job?"

A research agent that only reads does not need write. A triage agent that only classifies does not need a
tool that can send email. Enumerate the toolset from the purpose, not from convenience.

### BP-6 — Deliberate channel assignment

Each bot gets an explicit channel, or explicitly gets none. A bot that can be reached from every surface is
a bot nobody has decided what it is for.

Where a platform supports it, bind a distinct identity per bot per channel rather than a shared endpoint.

### BP-7 — Carry the bot's name into everything it produces

Logs, traces, generated artifacts, commit authorship, filenames, outbound message metadata.

If your monitoring cannot tell you which agent emitted an event, the monitoring is not finished. This
practice is cheap to adopt and it is the difference between an incident you can diagnose and one you can
only narrate.

### BP-8 — Verify credential uniqueness as a pre-flight check

Before an agent joins an installation, confirm that every credential it holds is not already held by a
sibling. Do this deliberately and periodically — not by assuming.

Where the platform can detect the collision and report it, surface that signal somewhere a human will
actually see it. A failure flag nobody reads is not a control.

---

## 4. Reference checklist

| # | Practice | Prevents |
|---|---|---|
| BP-1 | Purpose before config | Agents with no defined job |
| BP-2 | One bot, one channel token | Nondeterministic routing, silent adapter parking |
| BP-3 | One bot, one OAuth grant | Refresh-token races, scope ceilings, audit dead ends, all-or-nothing revocation |
| BP-4 | Deliberate default model | Unbudgeted cost; quiet low-capability failures |
| BP-5 | Explicit least privilege | Blast radius beyond one bot |
| BP-6 | Deliberate channel assignment | Undefined reach |
| BP-7 | Name in every artifact | Unattributable actions |
| BP-8 | Verify credential uniqueness | Inherited collisions |

---

## 5. Anti-patterns

- **"It's the same team, so one credential is fine."** Teams have separate logins. This is the same problem
  with a smaller blast radius expectation.
- **"We can figure out which agent did it from the logs."** Only if every artifact carries the name. If you
  have not done BP-7, you cannot.
- **"It's on an internal network."** Network location does not create identity or attribution.
- **"We'll split credentials if we ever need to."** The migration is harder than starting correct, because
  it means re-consenting every grant.
- **"The framework defaults are fine."** Every default surveyed here shares the credential. There is no
  framework that defaults to per-agent identity.

---

## 6. Why this guidance does not already exist

Because the frameworks are not accountable for it.

They sell developer capability, not operational accountability. A shared credential is simpler to ship,
simpler to document, and breaks nothing until the estate is large enough to have incidents — which is
exactly when the practitioner, not the framework, absorbs the cost.

The industry has converged on multi-agent. It has not converged on multi-identity. That gap is the
opportunity, and it is currently unclaimed.

---

## Sources

- [Claude Code — Create custom subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude — How and when to use subagents in Claude Code](https://claude.com/resources/articles/subagents-in-claude-code)
- [OpenAI — Introducing dots](https://openai.com/index/introducing-dots/)
- [Google — Agent Development Kit](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk)
- [Google — Cross-language multi-agent teams with ADK and A2A](https://developers.googleblog.com/build-cross-language-multi-agent-team-with-google-agent-development-kit-and-a2a/)
- [Microsoft — Migrate Semantic Kernel and AutoGen projects to Microsoft Agent Framework](https://devblogs.microsoft.com/agent-framework/migrate-your-semantic-kernel-and-autogen-projects-to-microsoft-agent-framework-release-candidate/)
- [OpenAI — Agents SDK: Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [LangChain — LangChain vs. AutoGen in 2026](https://www.langchain.com/resources/langchain-vs-autogen)
- [Arize — AI agent frameworks compared](https://arize.com/ai-agents/agent-frameworks/)
- [Mastra — Multi-agent systems: architectures, frameworks, and uses](https://mastra.ai/articles/multi-agent-systems)
- [AWS — Strands Agents and the model-driven approach](https://aws.amazon.com/blogs/opensource/strands-agents-and-the-model-driven-approach/)
- [AWS Builder — Building multi-agent AI systems on AWS](https://builder.aws.com/content/3K90wVAxoDopIixLVr1fnLAXWsQ/building-multi-agent-ai-systems-on-aws-architecture-orchestration-and-production-best-practices)
- [OpenClaw — Documentation](https://docs.openclaw.ai/) · [GitHub](https://github.com/openclaw/openclaw)

*Framework behaviour was read from official documentation and vendor posts on 16 October 2026. Verify
against current documentation before relying on specifics.*