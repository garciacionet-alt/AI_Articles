# Example — one bot, one credential

A worked before/after. Copy this shape for your own installation.

Everything here is illustrative. The values are placeholders.

---

## Before — three bots, one identity

```bash
# ~/.hermes/.env          (the default bot)
TELEGRAM_BOT_TOKEN=000000:SHARED
GOOGLE_CLIENT_ID=shared-client.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=shared-secret
GOOGLE_REFRESH_TOKEN=shared-refresh-token
```

```bash
# ~/.hermes/research/.env
TELEGRAM_BOT_TOKEN=000000:SHARED        # same token
GOOGLE_CLIENT_ID=shared-client.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=shared-secret
GOOGLE_REFRESH_TOKEN=shared-refresh-token
```

```bash
# ~/.hermes/dispatch/.env
TELEGRAM_BOT_TOKEN=000000:SHARED        # same token
GOOGLE_CLIENT_ID=shared-client.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=shared-secret
GOOGLE_REFRESH_TOKEN=shared-refresh-token
```

Every bot has a name, a personality, and a job. Not one of them has an identity.

Run the checker and it says so plainly:

```
Scanned: /Users/you/.hermes
Bots found: 3   credential entries: 12

FAIL — credentials shared by more than one bot:

  fingerprint 52e1c6918141 — held by 3 bot(s):
      (root)                   TELEGRAM_BOT_TOKEN
      dispatch                 TELEGRAM_BOT_TOKEN
      research                 TELEGRAM_BOT_TOKEN

  fingerprint 8f14e45fceea — held by 3 bot(s):
      (root)                   GOOGLE_REFRESH_TOKEN
      dispatch                 GOOGLE_REFRESH_TOKEN
      research                 GOOGLE_REFRESH_TOKEN
```

Three bots. One token. One refresh token that all three rotate out from under each other.

### What is actually wrong here

- **Which bot answers on Telegram is arbitrary.** The platform accepts one consumer per token. Two of these three are not receiving messages, and neither will report an error.
- **Scopes cannot diverge.** All three hold the union of whatever was ever consented. The research bot cannot be read-only while dispatch holds write, because there is only one grant.
- **The audit log has one author.** Every action across all three bots appears under the same client and user.
- **Revocation is all-or-nothing.** Discovering that dispatch has gone wrong means losing research as well.

---

## After — three bots, three identities

```bash
# ~/.hermes/.env          — the default bot
BOT_NAME=atlas
BOT_PURPOSE=General assistant. Coordinates the others; no direct system of record access.
TELEGRAM_BOT_TOKEN=000000:AAA
GOOGLE_CLIENT_ID=atlas.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<atlas-secret>
GOOGLE_SCOPES=
GOOGLE_REFRESH_TOKEN=
```

```bash
# ~/.hermes/research/.env
BOT_NAME=atlas-research
BOT_PURPOSE=Finds and summarises vendor research. Read-only by design.
TELEGRAM_BOT_TOKEN=000000:BBB
GOOGLE_CLIENT_ID=atlas-research.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<research-secret>
GOOGLE_SCOPES=https://www.googleapis.com/auth/drive.readonly
GOOGLE_REFRESH_TOKEN=<research-refresh-token>
BOT_MODEL=<model-id>
BOT_TOOLS=search,read
BOT_WRITE=false
```

```bash
# ~/.hermes/dispatch/.env
BOT_NAME=atlas-dispatch
BOT_PURPOSE=Sends approved outbound partner notes.
TELEGRAM_BOT_TOKEN=000000:CCC
GOOGLE_CLIENT_ID=atlas-dispatch.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<dispatch-secret>
GOOGLE_SCOPES=https://www.googleapis.com/auth/drive
GOOGLE_REFRESH_TOKEN=<dispatch-refresh-token>
BOT_MODEL=<model-id>
BOT_TOOLS=search,read,draft,send
BOT_WRITE=true
```

The checker now reports:

```
Scanned: /Users/you/.hermes
Bots found: 3   credential entries: 12

PASS — no credential is shared between bots.
```

### What changed

| | Before | After |
|---|---|---|
| Which bot answers | Arbitrary; losers silently parked | Deterministic — each token has one owner |
| Research agent's Google access | Write, because dispatch needed write | `drive.readonly`, and only that |
| Audit log author | One identity for all three actions | Three identities, one per bot |
| Revoke a bad actor | Lose everything | Revoke dispatch, keep research |
| Which bot did this? | Unanswerable | Answerable from the log |
| Per-bot model control | Inherited | Explicit |

---

## The template

```bash
BOT_NAME=atlas-<role>
BOT_PURPOSE=<one sentence. If you cannot write this, you should not create the bot.>

# Credentials — unique to this bot. Never inherited, never shared.
CHANNEL_TOKEN=<this bot's own token>

# Third-party access — its own client, its own grant, its own scopes.
OAUTH_CLIENT_ID=<this bot's own client>
OAUTH_CLIENT_SECRET=<this bot's own secret>
OAUTH_SCOPES=<minimum this purpose needs>

# Model — chosen deliberately, not inherited (BP-4)
BOT_MODEL=<model-id>

# Permissions — least privilege for this purpose (BP-5)
BOT_TOOLS=<minimum toolset>
BOT_WRITE=<true only if the purpose requires it>
```

Fill in the purpose first. Everything else follows from it.