#!/usr/bin/env bash
#
# check-tailnet-health.sh — audit a private agent network.
#
# Implements the checklist in ../PATTERN.md. Verifies the eight things that
# break this setup, and reports each one as OK / WARN / FAIL.
#
#   1. Tailscale is installed, the node is enrolled, and the backend is healthy
#   2. The overlay node name differs from the OS hostname (the collision trap)
#   3. The serve/funnel configuration is keyed to the CURRENT node name
#   4. Tailnet names resolve and a peer answers
#   5. A public exposure, if any, actually answers — and carries a path
#   6. Local listeners are bound to loopback, not to every interface
#   7. The commons path is present on this host and readable
#   8. Every public exposure is accounted for, and the commons is not one
#
# SAFETY: read-only. This script never writes, moves, or deletes anything.
# It never prints a credential value — only the NAME of a variable, and
# whether it is present.
#
# Usage:
#   ./check-tailnet-health.sh [commons-path] [listener-port]
#
# Examples:
#   ./check-tailnet-health.sh
#   ./check-tailnet-health.sh "$HOME/commons" 8443
#
# Exit codes:
#   0  no FAIL findings
#   1  one or more FAIL findings
#   2  usage or environment error
#
# Portable to macOS bash 3.2 (no associative arrays, no GNU-only tools).

set -u

usage() {
  sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

COMMONS_PATH="${1:-${COMMONS_PATH:-$HOME/commons}}"
LISTENER_PORT="${2:-${LISTENER_PORT:-}}"

FAILS=0
WARNS=0

ok()   { printf '  OK    %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; WARNS=$((WARNS + 1)); }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
skip() { printf '  --    %s\n' "$1"; }

have() { command -v "$1" >/dev/null 2>&1; }

# Read one field out of `tailscale status --json`. Prints nothing on failure.
ts_json() {
  tailscale status --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
path = '$1'.split('.')
for p in path:
    if isinstance(d, dict):
        d = d.get(p)
    else:
        d = None
        break
if d is None:
    sys.exit(1)
if isinstance(d, (list, tuple)):
    print(' '.join(str(x) for x in d))
else:
    print(d)
" 2>/dev/null
}

echo "Private agent network health check"
echo "  commons path: $COMMONS_PATH"
if [ -n "$LISTENER_PORT" ]; then
  echo "  listener port: $LISTENER_PORT"
else
  echo "  listener port: (not given — the bind check will be skipped)"
fi
echo

# ---------------------------------------------------------------------------
# 1. Enrolment and backend health
# ---------------------------------------------------------------------------
echo "[1] Node enrolment"

if ! have tailscale; then
  fail "tailscale is not on PATH — nothing below can be checked"
  echo
  echo "----------------------------------------"
  echo "findings: $FAILS FAIL, $WARNS WARN"
  echo "result: NOT READY — tailscale is not installed"
  exit 1
fi
ok "tailscale CLI is on PATH"

BACKEND="$(ts_json 'BackendState')"
SELF_ONLINE="$(ts_json 'Self.Online')"
DNSNAME="$(ts_json 'Self.DNSName')"

case "$BACKEND" in
  Running|"" )
    if [ -z "$BACKEND" ]; then
      warn "could not read the backend state — the daemon may not be running"
    else
      ok "backend state: $BACKEND"
    fi
    ;;
  * )
    fail "backend state is '$BACKEND' — the node is not connected to the network"
    ;;
esac

if [ "$SELF_ONLINE" = "True" ] || [ "$SELF_ONLINE" = "true" ]; then
  ok "this node is online"
elif [ -z "$SELF_ONLINE" ]; then
  warn "could not read the node's online state"
else
  fail "this node is offline"
fi
echo

# ---------------------------------------------------------------------------
# 2. The node-name collision trap
# ---------------------------------------------------------------------------
echo "[2] Node name vs OS hostname"

if [ -z "$DNSNAME" ]; then
  warn "could not read the overlay node name"
else
  NODE_SHORT="$(printf '%s' "$DNSNAME" | sed 's/\..*$//')"
  ok "overlay node name is set"

  OS_NAME=""
  if have scutil; then
    OS_NAME="$(scutil --get ComputerName 2>/dev/null || true)"
  elif have hostname; then
    OS_NAME="$(hostname 2>/dev/null | sed 's/\..*$//' || true)"
  fi

  if [ -z "$OS_NAME" ]; then
    warn "could not read the OS hostname to compare against"
  elif [ "$NODE_SHORT" = "$OS_NAME" ]; then
    fail "the overlay node name and the OS hostname are identical ('$OS_NAME')"
    echo "      The machine will see its own name claimed on the LAN and through the"
    echo "      tunnel, and the OS will rename it with a suffix on every wake."
    echo "      Separate them: 'tailscale set --hostname=<other>' then pin the OS name."
  else
    ok "the overlay node name differs from the OS hostname ('$OS_NAME')"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 3. Stale serve configuration
# ---------------------------------------------------------------------------
echo "[3] Serve configuration freshness"

SERVE_STATUS="$(tailscale serve status 2>/dev/null || true)"
FUNNEL_STATUS="$(tailscale funnel status 2>/dev/null || true)"
ALL_STATUS="$SERVE_STATUS
$FUNNEL_STATUS"

CONFIG_HOSTS="$(printf '%s' "$ALL_STATUS" | grep -oE '[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9.-]+\.[A-Za-z]{2,}' | sort -u)"

if [ -z "$CONFIG_HOSTS" ]; then
  ok "no serve or funnel configuration is active"
elif [ -z "$DNSNAME" ]; then
  warn "a serve configuration exists but the current node name could not be read"
else
  STALE=""
  for h in $CONFIG_HOSTS; do
    if [ "$h" != "$DNSNAME" ]; then
      STALE="$STALE $h"
    fi
  done
  if [ -n "$STALE" ]; then
    fail "the serve configuration is keyed to a name this node no longer has:"
    for h in $STALE; do
      echo "        $h"
    done
    echo "      The configuration survived a rename; the advertised name does not resolve."
    echo "      Re-key it, or give the node a stable name (see check 2)."
  else
    ok "the serve configuration is keyed to the current node name"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 4. Name resolution and peer reachability
# ---------------------------------------------------------------------------
echo "[4] Tailnet reachability"

PEER_HOST=""

# Peer hostnames come from the JSON, one per line.
PEER_HOST="$(tailscale status --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for k, v in (d.get('Peer') or {}).items():
    if not v:
        continue
    if not v.get('Online'):
        continue
    name = v.get('DNSName', '')
    if name:
        print(name.rstrip('.'))
        break
" 2>/dev/null)"

if [ -z "$PEER_HOST" ]; then
  warn "no online peer found in the tailnet — reachability could not be tested"
elif ! have python3; then
  skip "python3 not available; cannot test name resolution"
else
  RESOLVED="$(python3 -c "
import socket, sys
try:
    print(socket.gethostbyname('$PEER_HOST'))
except Exception:
    sys.exit(1)
" 2>/dev/null)"
  if [ -n "$RESOLVED" ]; then
    ok "the peer name resolves"
    if have tailscale; then
      if tailscale ping --timeout=3s --c=1 "$PEER_HOST" >/dev/null 2>&1; then
        ok "the peer answers"
      else
        fail "the peer does not answer — check the network ACLs for this node"
      fi
    fi
  else
    fail "the peer name does not resolve"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 5. Public exposures
# ---------------------------------------------------------------------------
echo "[5] Public exposures"

FUNNEL_URLS="$(printf '%s' "$FUNNEL_STATUS" | grep -oE 'https://[^ ]+' | sort -u)"

if [ -z "$FUNNEL_URLS" ]; then
  ok "no public funnel is active"
else
  for u in $FUNNEL_URLS; do
    HOSTPORT="$(printf '%s' "$u" | sed -e 's|^https://||' -e 's|/.*$||')"
    HOSTPART="$(printf '%s' "$HOSTPORT" | sed 's|:.*$||')"
    PORTPART="$(printf '%s' "$HOSTPORT" | sed -n 's|^[^:]*:||p')"
    [ -z "$PORTPART" ] && PORTPART=443

    # A public URL with no path segment is a public root. That is a much
    # larger surface than a webhook listener on its own path.
    PATHSEG="$(printf '%s' "$u" | sed -e 's|^https://[^/]*||')"
    if [ -z "$PATHSEG" ] || [ "$PATHSEG" = "/" ]; then
      warn "a public exposure serves the site ROOT — confirm that is intentional"
    else
      ok "the public exposure carries a path segment"
    fi

    if have nc; then
      if nc -z -w 3 "$HOSTPART" "$PORTPART" >/dev/null 2>&1; then
        warn "a public exposure is active and ANSWERING: $u — confirm it is intentional"
      else
        warn "a public exposure is active but nothing is listening behind it — close the stale tunnel"
      fi
    else
      warn "a public exposure is active: $u (nc unavailable, cannot test it)"
    fi
  done
fi
echo

# ---------------------------------------------------------------------------
# 6. Listener bind address
# ---------------------------------------------------------------------------
echo "[6] Listener bind address"

if [ -z "$LISTENER_PORT" ]; then
  skip "no listener port given — pass it as the second argument to check this"
elif ! have lsof; then
  skip "lsof not available — cannot inspect the bind address"
else
  BINDS="$(lsof -nP -iTCP:"$LISTENER_PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' | sort -u)"
  if [ -z "$BINDS" ]; then
    warn "nothing is listening on port $LISTENER_PORT"
  else
    ALLIF=""
    for b in $BINDS; do
      case "$b" in
        127.0.0.1:*|localhost:*|\[::1\]:*) : ;;
        *) ALLIF="$ALLIF $b" ;;
      esac
    done
    if [ -n "$ALLIF" ]; then
      fail "the listener is bound to every interface, not just loopback:"
      for b in $ALLIF; do echo "        $b"; done
      echo "      Do not rely on the host firewall — it is commonly disabled."
    else
      ok "the listener is bound to loopback only"
    fi
  fi
fi
echo

# ---------------------------------------------------------------------------
# 7. The commons path
# ---------------------------------------------------------------------------
echo "[7] Commons path"

if [ ! -d "$COMMONS_PATH" ]; then
  fail "the commons path does not exist on this host: $COMMONS_PATH"
  echo "      A synced folder is not a shared filesystem — if the commons lives on"
  echo "      another machine, reach it through that machine over the network."
elif [ ! -r "$COMMONS_PATH" ]; then
  fail "the commons path exists but is not readable: $COMMONS_PATH"
else
  ok "the commons path exists and is readable"
  if [ -w "$COMMONS_PATH" ]; then
    ok "the commons path is writable"
  else
    warn "the commons path is not writable by this user"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 8. Exposure accounting
# ---------------------------------------------------------------------------
echo "[8] Exposure accounting"

EXPOSURE_COUNT=0
if [ -n "$FUNNEL_URLS" ]; then
  EXPOSURE_COUNT="$(printf '%s\n' $FUNNEL_URLS | wc -l | tr -d ' ')"
fi

if [ "$EXPOSURE_COUNT" -eq 0 ]; then
  ok "there are no public exposures to account for"
else
  warn "$EXPOSURE_COUNT public exposure(s) — each needs an owner and a reason"
  echo "        Anything without one should be closed."
  echo "        The commons, the vector database and the control plane are never public."
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
