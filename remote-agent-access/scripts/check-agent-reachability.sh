#!/usr/bin/env bash
#
# check-agent-reachability.sh — audit a LAN agent's remote-access setup.
#
# Implements the checklist in ../PATTERN.md. Verifies the six things that
# break this setup, and reports each one as OK / WARN / FAIL.
#
#   1. The chat gateway process is running and reports a CONNECTED state
#      (a running process is not a connection — that distinction is the
#      difference between a five-second fix and an afternoon of guessing)
#   2. The bot token is in the environment file, not in the config file
#   3. The local inference endpoint resolves and answers
#   4. The routing configuration points at the local endpoint by default
#   5. The appliance lock mechanism exists, so a model load is not evicted
#      by the background supervisor mid-run
#   6. No stale public exposure is left listening on nothing
#
# SAFETY: read-only. This script never writes, moves, or deletes anything.
# It never prints a credential value — only the NAME of a variable, and
# whether it is present. Fingerprints are not needed here; presence is
# the question.
#
# Usage:
#   ./check-agent-reachability.sh [hermes-home]
#
# Examples:
#   ./check-agent-reachability.sh
#   ./check-agent-reachability.sh ~/.hermes
#
# Exit codes:
#   0  no FAIL findings
#   1  one or more FAIL findings
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

HERMES_HOME="${1:-${HERMES_HOME:-$HOME/.hermes}}"

FAILS=0
WARNS=0

ok()   { printf '  OK    %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; WARNS=$((WARNS + 1)); }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
skip() { printf '  --    %s\n' "$1"; }

have() { command -v "$1" >/dev/null 2>&1; }

echo "Remote agent reachability check"
echo "  hermes home: $HERMES_HOME"
echo

# ---------------------------------------------------------------------------
# 1. Gateway liveness AND connection state
# ---------------------------------------------------------------------------
echo "[1] Chat gateway"

if ! have hermes; then
  warn "hermes not on PATH — cannot check the gateway"
elif ! hermes gateway status >/dev/null 2>&1; then
  fail "hermes gateway status failed — the gateway is not answering"
else
  GS="$(hermes gateway status 2>&1 || true)"

  # A process that is up is not a platform that is connected.
  if printf '%s' "$GS" | grep -qiE 'supervised|PID|running|healthy|service definition'; then
    ok "gateway service is supervised and reporting"
  else
    warn "gateway status did not report a recognisable service state"
  fi

  # The per-platform CONNECTION state is a separate fact from the process
  # being up, and it lives in gateway_state.json. That distinction is what
  # this check turns on: a supervised gateway whose chat session is
  # disconnected is silent, and looks identical to an agent that is not
  # responding — so it gets debugged in the wrong direction.
  STATEFILE="$HERMES_HOME/gateway_state.json"
  if [ -f "$STATEFILE" ] && have python3; then
    CONN="$(python3 - "$STATEFILE" <<'PYEOF' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    plats = d.get("platforms", {})
    states = {}
    for name, v in plats.items():
        if isinstance(v, dict) and "state" in v:
            states[name] = v["state"]
    if not states:
        print("none")
    else:
        good = [n for n, s in states.items() if s == "connected"]
        bad = [n for n, s in states.items() if s != "connected"]
        print("connected:%d" % len(good))
        if bad:
            print("bad:%s" % ",".join(sorted(bad)))
except Exception:
    print("unreadable")
PYEOF
)"
    case "$CONN" in
      connected:*)
        ok "platform reports CONNECTED ($(printf '%s' "$CONN" | sed -n 's/^connected:\([0-9]*\).*/\1 platform(s)/p'))"
        if printf '%s' "$CONN" | grep -q '^bad:'; then
          warn "some platforms are not connected: $(printf '%s' "$CONN" | sed -n 's/^bad://p')"
        fi
        ;;
      bad:*)
        fail "platform is NOT connected: $(printf '%s' "$CONN" | sed -n 's/^bad://p') — a running gateway with a dead session is silent"
        ;;
      none)
        warn "no platform states recorded yet — the gateway may not have connected"
        ;;
      *)
        warn "could not read the platform connection state"
        ;;
    esac
  else
    warn "no gateway_state.json — cannot verify the platform CONNECTION state (a running gateway is not a connected one)"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 2. Credential placement
# ---------------------------------------------------------------------------
echo "[2] Bot credential placement"

ENVFILE="$HERMES_HOME/.env"
CONFIG="$HERMES_HOME/config.yaml"

if [ ! -f "$ENVFILE" ]; then
  warn "no environment file at $ENVFILE — cannot check credential placement"
else
  # Report the NAME of a variable, never its value.
  if grep -qE '^[A-Z_]*TELEGRAM[A-Z_]*_BOT_TOKEN=' "$ENVFILE" 2>/dev/null; then
    ok "chat bot token is present in the environment file"
  elif grep -qiE '^[A-Z_]*BOT_TOKEN=' "$ENVFILE" 2>/dev/null; then
    ok "a bot token is present in the environment file"
  else
    warn "no bot token found in the environment file (looked for *_BOT_TOKEN=)"
  fi

  if grep -qE '^[A-Z_]*ALLOWED_USERS=' "$ENVFILE" 2>/dev/null; then
    ok "an allow-list of user IDs is present"
  else
    warn "no allow-list found — an unscoped bot is reachable by anyone who finds it"
  fi
fi

# A token in the config file is a token that gets shared.
if [ -f "$CONFIG" ]; then
  # An EMPTY value is the correct pattern: the config says which VARIABLE
  # holds the key, and the value itself lives in the environment file. Only
  # a non-empty literal is a leak. Flagging `api_key: ''` tells the reader
  # to break a working setup.
  #
  # Some values are LITERAL PLACEHOLDERS that say no key is needed at all
  # (`no-key-required` for a loopback server). Those are not credentials
  # and must not trip the check either -- so the rule matches a value that
  # LOOKS like a secret, and lets the known placeholder shapes through.
  if grep -qiE '(bot_token|api_key|secret|password|access_token)[[:space:]]*:[[:space:]]*[^[:space:]"'"'"'${<]+' "$CONFIG" 2>/dev/null \
     | grep -viE ':[[:space:]]*(no-key-required|none|null|nil|not-required|notneeded|""[[:space:]]*$|'"'"''"'"')[[:space:]]*$'; then
    fail "the config file holds a credential VALUE — move it to the environment file"
  else
    ok "no credential values in the config file (empty values and 'no key required' placeholders are correct)"
  fi
else
  skip "no config file to inspect"
fi
echo

# ---------------------------------------------------------------------------
# 3. The local inference endpoint
# ---------------------------------------------------------------------------
echo "[3] Local inference endpoint"

ENDPOINT=""
if [ -f "$CONFIG" ]; then
  # Pick the endpoint of the SELECTED provider, not the first one in the
  # file. A config with several providers would otherwise be checked
  # against whichever happens to be defined first — which checks the wrong
  # machine and reports a false OK.
  SEL="$(grep -oE '^[[:space:]]*provider:[[:space:]]*custom:[A-Za-z0-9_.-]+' "$CONFIG" 2>/dev/null | head -1 | sed 's/.*custom://')"
  if [ -n "$SEL" ]; then
    ENDPOINT="$(awk -v p="$SEL" '
      $0 ~ "^[[:space:]]*" p ":[[:space:]]*$" { inblk=1; next }
      inblk && $0 ~ "^[[:space:]]*[A-Za-z0-9_.-]+:[[:space:]]*$" { inblk=0 }
      inblk && $0 ~ "^[[:space:]]*api:[[:space:]]*http" {
        sub(/^[[:space:]]*api:[[:space:]]*/, ""); print; exit
      }
    ' "$CONFIG" 2>/dev/null)"
  fi
  # Fall back to any local http endpoint if the selected one is not
  # discoverable from the config's shape.
  if [ -z "$ENDPOINT" ]; then
    ENDPOINT="$(sed -n 's/^[[:space:]]*api:[[:space:]]*\(http[^[:space:]]*\).*/\1/p' "$CONFIG" 2>/dev/null | head -1)"
  fi
fi

if [ -z "$ENDPOINT" ]; then
  warn "no local inference endpoint found in the config"
else
  # Print the host, never a credential. The endpoint is a LAN name.
  HOSTPART="$(printf '%s' "$ENDPOINT" | sed -e 's|^[a-z]*://||' -e 's|/.*$||' -e 's|:.*$||')"
  ok "endpoint configured (host: $HOSTPART)"

  if have python3; then
    RESOLVED="$(python3 -c "
import socket, sys
try:
    print(socket.gethostbyname('$HOSTPART'))
except Exception:
    sys.exit(1)
" 2>/dev/null)"
    if [ -n "$RESOLVED" ]; then
      ok "resolves locally ($RESOLVED)"
    else
      fail "does not resolve — the agent will fall back to the cloud provider"
    fi
  else
    skip "python3 not available; cannot test resolution"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 4. Routing configuration
# ---------------------------------------------------------------------------
echo "[4] Routing configuration"

if [ ! -f "$CONFIG" ]; then
  skip "no config file to inspect"
else
  if grep -qE '^[[:space:]]*provider:[[:space:]]*custom:' "$CONFIG" 2>/dev/null; then
    ok "a custom provider is selected for delegation"
  else
    warn "delegation does not name a custom provider — bulk work may not be routed local"
  fi

  if grep -qE '^[[:space:]]*provider:[[:space:]]*custom:' "$CONFIG" 2>/dev/null; then
    NAME="$(grep -oE '^[[:space:]]*provider:[[:space:]]*custom:[A-Za-z0-9_.-]+' "$CONFIG" 2>/dev/null | head -1 | sed 's/.*custom://')"
    if [ -n "$NAME" ] && grep -qE "^[[:space:]]*${NAME}:[[:space:]]*$" "$CONFIG" 2>/dev/null; then
      ok "the selected provider '$NAME' is defined in the config"
    else
      fail "the selected provider is NOT defined in the config — delegation fails as 'unknown provider'"
    fi
  fi

  # The whole point is that local is the default and the paid path is the
  # fallback. If there is no fallback configured, a dead appliance is a failed
  # task instead of an expensive one — which is better, but worth knowing.
  if grep -qE 'fallback_providers' "$CONFIG" 2>/dev/null; then
    ok "a fallback provider is configured"
  else
    warn "no fallback provider — a dead appliance will fail tasks instead of using the cloud"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 5. The appliance lock
# ---------------------------------------------------------------------------
echo "[5] Appliance lock"

HOLD=""
for cand in "$HERMES_HOME/tiiny-hold" "$HERMES_HOME/tiiny-holdfile"; do
  [ -f "$cand" ] && HOLD="$cand" && break
done

if [ -n "$HOLD" ]; then
  ok "a hold file exists ($HOLD)"
  if [ -s "$HOLD" ]; then
    warn "the hold file is non-empty — a stale hold stops the supervisor restoring the device"
  else
    ok "the hold file is empty (no stale hold)"
  fi
else
  warn "no hold file found — a model loaded for a delegated run can be evicted mid-run"
fi

if have tiiny; then
  ok "the appliance CLI is on PATH"
else
  skip "appliance CLI not on PATH (expected if it is installed elsewhere)"
fi
echo

# ---------------------------------------------------------------------------
# 6. Stale public exposures
# ---------------------------------------------------------------------------
echo "[6] Public exposures"

if have tailscale; then
  STATUS="$(tailscale funnel status 2>/dev/null || true)"
  if [ -z "$STATUS" ] || printf '%s' "$STATUS" | grep -qi 'no funnel\|off'; then
    ok "no funnel is active"
  else
    # Report each exposure and whether it answers. A funnel that serves
    # nothing is still a funnel that serves nothing -- and that is exactly
    # the leftover a retired transport leaves behind.
    EXPOSURE="$(printf '%s' "$STATUS" | grep -oE 'https://[^ ]+' | head -1)"
    if [ -n "$EXPOSURE" ]; then
      HOSTPORT="$(printf '%s' "$EXPOSURE" | sed -e 's|^https://||' -e 's|/.*$||')"
      HOSTPART="$(printf '%s' "$HOSTPORT" | sed 's|:.*$||')"
      PORTPART="$(printf '%s' "$HOSTPORT" | sed -n 's|^[^:]*:||p')"
      [ -z "$PORTPART" ] && PORTPART=443

      if have nc; then
        if nc -z -w 3 "$HOSTPART" "$PORTPART" >/dev/null 2>&1; then
          warn "a public exposure is active and ANSWERING: $EXPOSURE — confirm it is intentional"
        else
          warn "a public exposure is active but nothing is listening behind it — close the stale tunnel"
        fi
      else
        warn "a public exposure is active: $EXPOSURE (nc unavailable, cannot test it)"
      fi
    else
      warn "a funnel is active — confirm it is intentional"
    fi
  fi
else
  skip "tailscale not on PATH"
fi

if have lsof; then
  N="$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' | grep -cE ':[0-9]+$')"
  ok "$N listening TCP port(s) on this host"
else
  skip "lsof not available"
fi
echo

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "----------------------------------------"
printf 'findings: %d FAIL, %d WARN\n' "$FAILS" "$WARNS"
if [ "$FAILS" -gt 0 ]; then
  echo "result: NOT READY — fix the FAIL findings above"
  exit 1
fi
if [ "$WARNS" -gt 0 ]; then
  echo "result: usable, with warnings"
  exit 0
fi
echo "result: all checks passed"
exit 0
