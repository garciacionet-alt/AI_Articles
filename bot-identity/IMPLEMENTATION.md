# Bot Identity — Implementation

The concrete setup for the [pattern](./PATTERN.md): provisioning one credential per bot, wiring a second OAuth grant, and verifying the result.

Nothing here assumes a specific agent framework. Adjust paths and key names for yours.

---

## 1. Inventory what you already share

Before changing anything, know the current state.

```bash
./scripts/check-bot-credentials.sh ~/.hermes
```

The checker is read-only. It reads `.env` files, hashes every credential-shaped value, and reports any value held by more than one bot. It prints a truncated SHA-256 fingerprint, never the secret itself.

Typical output on a multi-bot installation:

```
Scanned: /Users/you/.hermes
Bots found: 4   credential entries: 9

FAIL — credentials shared by more than one bot:

  fingerprint 52e1c6918141 — held by 2 bot(s):
      (root)                   TELEGRAM_BOT_TOKEN
      alpha                    TELEGRAM_BOT_TOKEN
```

If your credentials do not use the default key patterns, pass your own:

```bash
./scripts/check-bot-credentials.sh ~/.hermes '.*TOKEN$' '.*SECRET$' '.*_KEY$'
```

**Record the result before you start.** You will want to prove the fix worked, and "it seems fine" is not a check.

---

## 2. Provision one channel token per bot

A channel credential is a singleton resource: the platform expects one owner.

For Telegram, that means registering a separate bot with BotFather for each bot that should be independently reachable, and giving each one a name users will recognise. The same principle applies to Slack apps, Discord bots, and Signal numbers.

Naming matters, because the name is what users see and what appears in your logs. `research-bot` is a purpose; `atlas-research` is an identity.

### Per-bot configuration anatomy

The layout the checker expects — one directory per bot, each with its own `.env`:

```
~/.hermes/
├── .env                  # the default bot
├── alpha/
│   └── .env              # alpha's own credentials
├── beta/
│   └── .env              # beta's own credentials
└── gamma/
    └── .env              # gamma's own credentials
```

`alpha/.env`:

```bash
# Identity
BOT_NAME=atlas-research
BOT_PURPOSE=Finds and summarises vendor research. Read-only.

# Credentials — unique to this bot, never inherited
TELEGRAM_BOT_TOKEN=000000:AAA-replace-with-atlas-token

# Model — chosen deliberately, not inherited (BP-4)
BOT_MODEL=<model-id>

# Permissions — least privilege for this purpose only (BP-5)
BOT_TOOLS=search,read
BOT_WRITE=false
```

`beta/.env`:

```bash
BOT_NAME=atlas-dispatch
BOT_PURPOSE=Sends approved outbound partner notes. Write access required.

TELEGRAM_BOT_TOKEN=000000:BBB-replace-with-dispatch-token

BOT_MODEL=<model-id>
BOT_TOOLS=search,read,draft,send
BOT_WRITE=true
```

Note what is *not* inherited: no parent include, no shared `common.env`, no fallback token. If `beta` can read a credential, it is because `beta` was given one.

---

## 3. Give each bot its own OAuth grant

This is the part people skip, and the part that costs the most later.

**Never share a refresh token between two agents.** Three failures follow if you do:

- Providers that rotate refresh tokens on use will invalidate the second agent's stored token — intermittent `invalid_grant` errors that look like provider flakiness
- The grant carries the union of every scope ever consented to, so you cannot narrow one bot's access
- Revoking the grant kills every bot using it

### Creating a separate grant

1. Register a **separate OAuth client** (or a distinct service account) for each bot. In Google Cloud, AWS, and Azure this is a separate project, app registration, or service principal per bot.
2. Request only the scopes that bot's purpose requires. A read-only agent should not consent to write scopes.
3. Complete the OAuth flow **per bot**, so each grant's refresh token is stored in that bot's own credential store.
4. Record which grant belongs to which bot. A grant with no owning bot is an orphan and should be revoked.

```bash
# alpha — read-only calendar access, its own client
GOOGLE_CLIENT_ID=<alpha-specific>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<alpha-specific-secret>
GOOGLE_SCOPES=https://www.googleapis.com/auth/calendar.readonly
GOOGLE_REFRESH_TOKEN=<alpha-specific-refresh-token>
```

```bash
# beta — write access, a different client entirely
GOOGLE_CLIENT_ID=<beta-specific>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<beta-specific-secret>
GOOGLE_SCOPES=https://www.googleapis.com/auth/calendar
GOOGLE_REFRESH_TOKEN=<beta-specific-refresh-token>
```

The two are now independently scopable, independently revocable, and independently attributable in the provider's audit log.

---

## 4. Carry the bot's name into everything it produces

BP-7 is the cheapest practice on the list and the one that pays off during an incident.

- Prefix log lines and traces with the bot name
- Include it in generated artifact filenames and metadata
- Set it as author/committer on anything the bot writes
- Include it in outbound message metadata

If your monitoring cannot tell you which agent emitted an event, the monitoring is not finished. That is the whole test.

---

## 5. Verify

Re-run the checker:

```bash
./scripts/check-bot-credentials.sh ~/.hermes
```

Expected:

```
Scanned: /Users/you/.hermes
Bots found: 4   credential entries: 11

PASS — no credential is shared between bots.
```

Because the exit code is meaningful, this drops straight into CI:

```bash
./scripts/check-bot-credentials.sh ~/.hermes || {
  echo "Shared bot credentials detected — see bot-identity/PATTERN.md"
  exit 1
}
```

A failure flag nobody reads is not a control, so make sure this fails something you actually look at.

---

## End-to-end setup checklist

- [ ] Run the checker and record the current state
- [ ] Write a one-sentence purpose for every bot (BP-1)
- [ ] Register one channel identity per bot and give it a real name (BP-2)
- [ ] Move each credential into that bot's own `.env`; delete shared copies
- [ ] Create a separate OAuth client and grant per bot, scoped to purpose (BP-3)
- [ ] Set an explicit default model per bot (BP-4)
- [ ] Set explicit least-privilege tool access per bot (BP-5)
- [ ] Confirm each bot's channel assignment is deliberate (BP-6)
- [ ] Add the bot name to logs, traces, and artifacts (BP-7)
- [ ] Re-run the checker until it reports PASS (BP-8)
- [ ] Add the checker to CI or a scheduled job that you actually see
- [ ] Revoke any orphaned grants that no bot owns

---

## Troubleshooting

**The checker finds a collision I expected.** Confirm it is a real collision and not two bots deliberately holding the same *non*-credential value. The default key patterns match on the key name, so a variable like `MAX_TOKENS` will match `.*TOKEN.*`. Pass a narrower pattern.

**Two bots must call the same API and I only have one API key.** That is the case the pattern is telling you about. Options: ask the provider for two keys, put the bots behind a thin proxy that holds the single key and tags requests per bot, or accept that you have one agent with two front-ends rather than two agents.

**My credentials are not in `.env` files.** The checker only reads `.env`. For credentials held in a secret manager or config file, the portability rule still holds — one credential per bot, independently revocable — but you will need to verify uniqueness manually or point the checker at an exported snapshot.

**A bot needs two different privilege levels.** That is two bots. Split it. If it truly must be one process, it needs one identity, and you should stop calling it two agents.