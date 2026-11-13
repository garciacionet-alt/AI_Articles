#!/usr/bin/env bash
# tiiny-swap.sh — run a command against a specific Tiiny model, safely.
#
# PURPOSE
# -------
# A Tiiny model load is a SWAP, not an add: NPU-RAM is finite and shared, so
# loading a model evicts whatever was resident. Two things then have to be
# true for the swap to be safe:
#
#   1. No other agent is using the device. A load under another agent's feet
#      evicts the model its child is running on, and that child then gets a
#      404 and falls back to the paid provider. `tiiny_ctl.py ensure` and
#      `tiiny_ctl.py load` check the cross-agent lock for exactly this.
#
#   2. The model the delegation config expects must come back afterwards.
#      --restore reloads the required set so the next delegated child finds
#      its model.
#
# NOTE: there is no longer a five-minute watchdog. It was retired on
# 2026-11-10 because it restored a fixed set — which drifted across three
# scripts — and because `tiiny_ctl.py ensure` loads what a batch actually
# needs, on demand. The hold file below is kept as a record of what was
# deliberately loaded; it no longer stops anything from firing.
#
# USAGE
# -----
#   tiiny-swap.sh <model_id> -- <command> [args...]
#
#   tiiny-swap.sh endless-frontier/BigBang-v1-Turbo -- \
#       my-long-research-script.sh
#
# Without a command it just loads the model, holds it, and prints what is
# resident — useful when you want the model up and will restore it later with
# tiiny-swap.sh --restore.
#
#   tiiny-swap.sh --restore      # drop the hold and reload the required set
#
# The hold file is ~/.hermes/tiiny-hold. It lists the model ids that are
# deliberately resident. --restore and --clear exist to tidy it up.

set -uo pipefail

TIINY_BIN="$HOME/.local/tiiny/bin/tiiny"
HOLD_FILE="$HOME/.hermes/tiiny-hold"
REQUIRED_MODELS=(
  "Qwen/Qwen3.6-35B-A3B"
  # The router's `index` tier. This list mirrors `REQUIRED_MODELS` in
  # tiiny_ctl.py, which is the canonical copy — every other copy of this
  # file is a symlink into it, so the two cannot drift.
  "openai/gpt-oss-20b"
)
# Speech is NOT in this list. ASR and TTS moved to Off Grid AI Desktop on
# 2026-11-10 — the appliance serializes one heavy stream at a time, so TTS
# queued behind its own LLM turn, and OGAD serves speech without touching
# the NPU pool. Restoring them here would put 12% of a shared pool back on
# every --restore for models nothing calls.

die() { printf 'tiiny-swap: %s\n' "$1" >&2; exit 1; }

[ -x "$TIINY_BIN" ] || die "tiiny CLI not found at $TIINY_BIN"

# --- clear the hold ----------------------------------------------------------
# Releasing the hold has to work in every context, including sandboxes where
# deletion is blocked. So: truncate first (a write always works), then try to
# remove the file, then VERIFY. An empty hold file is a released hold.
#
# The verify matters, because a script that prints "hold cleared" without
# checking leaves a stale record that `status` then reports as live.
clear_hold() {
  : > "$HOLD_FILE" 2>/dev/null || true
  rm -f "$HOLD_FILE" 2>/dev/null || true
  [ -s "$HOLD_FILE" ] && return 1
  return 0
}

# --- restore mode ------------------------------------------------------------
if [ "${1:-}" = "--restore" ]; then
  if clear_hold; then
    echo "hold cleared; restoring required models..."
  else
    echo "tiiny-swap: WARNING - could not release the hold at $HOLD_FILE." >&2
    echo "tiiny-swap: status will keep reporting it as held. Remove that file by hand." >&2
  fi
  for m in "${REQUIRED_MODELS[@]}"; do
    if script -q /dev/null "$TIINY_BIN" load "$m" -y >/dev/null 2>&1; then
      echo "  loaded $m"
    else
      echo "  FAILED $m" >&2
    fi
  done
  echo "resident now:"
  "$TIINY_BIN" top
  exit 0
fi

if [ "${1:-}" = "--clear" ]; then
  if clear_hold; then
    echo "hold cleared (models left as-is)"
  else
    echo "tiiny-swap: WARNING - could not release the hold at $HOLD_FILE." >&2
  fi
  exit 0
fi

MODEL="${1:-}"
[ -n "$MODEL" ] || die "usage: tiiny-swap.sh <model_id> [-- command...] | --restore | --clear"
shift || true

# --- write the hold BEFORE loading ------------------------------------------
# Write the record before loading, so `status` shows what is resident because
# of this swap and not as a leftover from an earlier one.
printf '%s\n' "$MODEL" > "$HOLD_FILE"
echo "hold written for $MODEL"

# --- load --------------------------------------------------------------------
echo "loading $MODEL..."
if ! script -q /dev/null "$TIINY_BIN" load "$MODEL" -y >/dev/null 2>&1; then
  echo "tiiny-swap: load failed for $MODEL" >&2
  rm -f "$HOLD_FILE"
  exit 1
fi
echo "loaded. resident:"
"$TIINY_BIN" top

# --- run the command ---------------------------------------------------------
if [ "${1:-}" = "--" ]; then
  shift
  if [ "$#" -eq 0 ]; then
    echo "tiiny-swap: model is up and held. Run 'tiiny-swap.sh --restore' when done."
    exit 0
  fi
  echo "running: $*"
  "$@"
  rc=$?
  echo "command exited $rc; restoring required models..."
  "$0" --restore
  exit $rc
fi

echo "tiiny-swap: model is up and held. Run 'tiiny-swap.sh --restore' when done."
