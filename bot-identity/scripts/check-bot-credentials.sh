#!/usr/bin/env bash
#
# check-bot-credentials.sh — detect shared credentials across bots in one installation.
#
# Implements BP-8 from ../PATTERN.md: verify credential uniqueness as a pre-flight
# check rather than assuming it.
#
# Scans a root directory of bot/profile subdirectories, hashes every credential-like
# value it finds, and reports any value held by more than one bot.
#
# SAFETY: read-only. This script never writes, moves, or deletes anything, and it
# never prints a credential value — only a truncated SHA-256 fingerprint so two
# entries can be compared by eye without exposing the secret.
#
# Usage:
#   ./check-bot-credentials.sh <root-dir> [key-pattern ...]
#
# Examples:
#   ./check-bot-credentials.sh ~/.hermes
#   ./check-bot-credentials.sh ./agents '.*_TOKEN$' '.*_SECRET$'
#
# Exit codes:
#   0  no collisions found
#   1  one or more credentials shared by more than one bot
#   2  usage or environment error
#
# Portable to macOS bash 3.2 (no associative arrays, no GNU-only tools).

set -u

usage() {
  sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

ROOT="${1:-}"
if [ -z "$ROOT" ] || [ ! -d "$ROOT" ]; then
  echo "error: usage: $0 <root-dir> [key-pattern ...]" >&2
  exit 2
fi
shift

# Credential-shaped keys. If the caller supplies patterns, use those instead.
if [ "$#" -gt 0 ]; then
  KEY_PATTERNS=("$@")
else
  KEY_PATTERNS=(
    '.*TOKEN.*'
    '.*API_?KEY.*'
    '.*CLIENT_?SECRET.*'
    '.*APP_?SECRET.*'
    '.*PASSWORD.*'
    '.*PRIVATE_?KEY.*'
    '.*SERVICE_?ACCOUNT.*'
  )
fi

# Build an ERE that matches any caller-supplied pattern.
KEY_MATCH=""
for p in "${KEY_PATTERNS[@]}"; do
  if [ -z "$KEY_MATCH" ]; then KEY_MATCH="$p"; else KEY_MATCH="$KEY_MATCH|$p"; fi
done

command -v shasum >/dev/null 2>&1 || { echo "error: shasum not found" >&2; exit 2; }

TMP_ROWS="$(mktemp "${TMPDIR:-/tmp}/botcred.XXXXXX")" || exit 2
TMP_BOTS="$(mktemp "${TMPDIR:-/tmp}/botcred.XXXXXX")" || exit 2
cleanup() { rm -f "$TMP_ROWS" "$TMP_BOTS"; }
trap cleanup EXIT INT TERM

# Each bot is a directory containing at least one .env file. The root itself counts
# as a bot if it has one — that is the common "default bot lives at the root" layout.
#
# Note: a plain `*.env` glob does not match `.env` in bash (no dotglob), and
# `.env` is the overwhelmingly common filename — so every check tests it directly
# rather than relying on glob expansion.
has_env() {
  local dir="$1" f
  [ -f "$dir/.env" ] && return 0
  for f in "$dir"/*.env; do
    [ -f "$f" ] && return 0
  done
  return 1
}

discover_bots() {
  [ -f "$ROOT/.env" ] && printf '%s\n' "(root)"
  for d in "$ROOT"/*/; do
    [ -d "$d" ] || continue
    has_env "$d" && printf '%s\n' "$(basename "$d")"
  done
  return 0
}

envfiles_for() {
  local dir f
  if [ "$1" = "(root)" ]; then dir="$ROOT"; else dir="$ROOT/$1"; fi
  [ -f "$dir/.env" ] && printf '%s\n' "$dir/.env"
  for f in "$dir"/*.env; do
    [ -f "$f" ] && printf '%s\n' "$f"
  done
  return 0
}

while IFS= read -r bot; do
  [ -z "$bot" ] && continue
  printf '%s\n' "$bot" >> "$TMP_BOTS"

  while IFS= read -r f; do
    [ -z "$f" ] && continue
    # KEY=VALUE, ignoring comments, blanks, export prefixes and quoted values.
    # Values are hashed, never emitted.
    while IFS='=' read -r key value; do
      key="${key#export }"
      # skip comments and blanks (a commented-out TOKEN=... must not be counted)
      case "$key" in
        '#'*|'') continue ;;
      esac
      [ -z "$value" ] && continue
      # strip surrounding quotes and trailing CR
      value="${value%$'\r'}"
      value="${value%\"}"; value="${value#\"}"
      value="${value%\'}"; value="${value#\'}"
      [ -z "$value" ] && continue
      # key must look like a credential
      printf '%s' "$key" | grep -Eq "$KEY_MATCH" || continue
      fp="$(printf '%s' "$value" | shasum -a 256 | cut -c1-12)"
      printf '%s\t%s\t%s\n' "$fp" "$bot" "$key" >> "$TMP_ROWS"
    done < "$f"
  done < <(envfiles_for "$bot")
done < <(discover_bots)

BOT_COUNT="$(wc -l < "$TMP_BOTS" | tr -d ' ')"
ROW_COUNT="$(wc -l < "$TMP_ROWS" | tr -d ' ')"

echo "Scanned: $ROOT"
echo "Bots found: $BOT_COUNT   credential entries: $ROW_COUNT"
echo

if [ "$ROW_COUNT" -eq 0 ]; then
  echo "No credential-shaped keys matched. Nothing to compare."
  echo "(Pass explicit patterns as extra arguments if your keys use other names.)"
  exit 0
fi

# A collision is one fingerprint held by more than one distinct bot.
COLLISIONS="$(cut -f1 "$TMP_ROWS" | sort | uniq -d)"

if [ -z "$COLLISIONS" ]; then
  echo "PASS — no credential is shared between bots."
  exit 0
fi

echo "FAIL — credentials shared by more than one bot:"
echo

for fp in $COLLISIONS; do
  # every distinct (bot,key) holding this fingerprint
  holders="$(awk -F'\t' -v f="$fp" '$1==f {print $2"\t"$3}' "$TMP_ROWS" | sort -u)"
  n="$(printf '%s\n' "$holders" | wc -l | tr -d ' ')"
  echo "  fingerprint ${fp} — held by ${n} bot(s):"
  printf '%s\n' "$holders" | while IFS=$'\t' read -r bot key; do
    [ -z "$bot" ] && continue
    printf '      %-24s %s\n' "$bot" "$key"
  done
  echo
done

printf '%s\n' \
  '' \
  'Why this matters — see ../PATTERN.md' \
  '' \
  '  A channel credential is a singleton resource. Two bots sharing one token means' \
  '  the platform picks one owner and the other goes silent rather than erroring.' \
  '' \
  '  An OAuth grant carries the union of every scope consented to, rotates refresh' \
  '  tokens on use, and attributes every action in the provider audit log to the' \
  '  grant rather than to the agent that acted. You cannot scope, revoke, or' \
  '  investigate one bot independently of the others.' \
  '' \
  'Fix: provision one credential per bot. See ../IMPLEMENTATION.md.'

exit 1