#!/usr/bin/env bash
# tiiny_box.sh — run the Tiiny controller against one named box.
#
# WHY THIS EXISTS
# ---------------
# One controller, several appliances. The controller's endpoints, credential
# and shared state all come from the environment, so pointing it at a
# different box is a matter of setting them - and getting that wrong is
# how two agents end up fighting over one NPU pool, or how one box's
# catalogue refresh silently replaces the other's baseline.
#
# The boxes are declared in a small file, one section per box:
#
#   # ~/.config/hermes/tiiny-boxes.conf
#   [vault]
#   host    = 192.0.2.50
#   key_env = TIINY_API_KEY
#
#   [flex]
#   host     = 192.0.2.51
#   key_env  = TIINY_API_KEY_2
#   own_lock = yes
#
# `own_lock = yes` gives that box its own lock, hold, plan and catalogue
# snapshot. Leave it OFF for the box whose default paths the scheduled jobs
# and the other agents on the machine already use: two agents sharing one
# pool must share one lock. The second box needs its own, because it is a
# different pool with a different lock.
#
# Usage
#   tiiny_box.sh <box> <tiiny_ctl.py args...>
#
#   tiiny_box.sh vault status
#   tiiny_box.sh flex  status
#   tiiny_box.sh flex  ensure --model "Qwen/Qwen3.8-27B"
set -uo pipefail

BOXES_CONF="${TIINY_BOXES_CONF:-$HOME/.config/hermes/tiiny-boxes.conf}"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"

# The controller itself lives in the sibling article family in this
# repository (tiiny-model-routing/scripts/tiiny_ctl.py). A clone of the
# repo has it there; a deployed install has it in ~/.hermes/scripts. Look
# in both so this script works for a reader who just cloned the repo, and
# let TIINY_CTL override both.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolve_ctl() {
  if [ -n "${TIINY_CTL:-}" ]; then
    echo "$TIINY_CTL"
    return
  fi
  for candidate in \
    "$HOME/.hermes/scripts/tiiny_ctl.py" \
    "$SCRIPT_DIR/../../tiiny-model-routing/scripts/tiiny_ctl.py" \
    "$SCRIPT_DIR/../tiiny-model-routing/scripts/tiiny_ctl.py"
  do
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}
CTL="$(resolve_ctl)"

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

BOX="${1:-}"
if [ $# -gt 0 ]; then shift; fi
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac
if [ -z "$BOX" ]; then
  usage
  exit 2
fi
if [ ! -f "$BOXES_CONF" ]; then
  echo "tiiny_box: no boxes file at $BOXES_CONF" >&2
  echo "  create it with one [name] section per box (see the header of this script)" >&2
  exit 2
fi
if [ ! -f "$CTL" ]; then
  echo "tiiny_box: the controller is missing." >&2
  echo "  looked for: \$TIINY_CTL, ~/.hermes/scripts/tiiny_ctl.py," >&2
  echo "              and ../tiiny-model-routing/scripts/tiiny_ctl.py" >&2
  echo "              next to this script (that is where it lives in a clone" >&2
  echo "              of the article repository)." >&2
  exit 2
fi

section_value() {
  awk -v want="$BOX" -v key="$1" '
    /^[ \t]*\[/ {
      line = $0
      gsub(/^[ \t]+|[ \t]+$/, "", line)
      cur = substr(line, 2, length(line) - 2)
      next
    }
    cur == want {
      line = $0
      sub(/^[ \t]*/, "", line)
      eq = index(line, "=")
      if (eq == 0) next
      k = substr(line, 1, eq - 1)
      gsub(/[ \t]/, "", k)
      if (k == key) {
        v = substr(line, eq + 1)
        gsub(/^[ \t]+|[ \t]+$/, "", v)
        print v
        exit
      }
    }
  ' "$BOXES_CONF"
}

HOST="$(section_value host)"
KEY_ENV="$(section_value key_env)"
OWN_LOCK="$(section_value own_lock)"

if [ -z "$HOST" ]; then
  echo "tiiny_box: no host for box '$BOX' in $BOXES_CONF" >&2
  exit 2
fi
if [ -z "$KEY_ENV" ]; then
  echo "tiiny_box: no key_env for box '$BOX' in $BOXES_CONF" >&2
  exit 2
fi

export TIINY_API_KEY="$(grep -E "^${KEY_ENV}=" "$HERMES_ENV" 2>/dev/null | head -1 | cut -d= -f2-)"
if [ -z "${TIINY_API_KEY:-}" ]; then
  echo "tiiny_box: $KEY_ENV is not set in $HERMES_ENV" >&2
  exit 2
fi

export TIINY_HOST="http://$HOST"
export TIINY_BASE_URL="http://$HOST/v1"

if [ "$OWN_LOCK" = "yes" ]; then
  export TIINY_LOCK_FILE="$HOME/.hermes/tiiny-lock-$BOX.json"
  export TIINY_HOLD_FILE="$HOME/.hermes/tiiny-hold-$BOX"
  export TIINY_PLAN_FILE="$HOME/.hermes/tiiny-plan-$BOX.json"
  export TIINY_SNAPSHOT_FILE="$HOME/.hermes/tiiny-catalogue-$BOX.json"
fi

exec python3 "$CTL" "$@"
