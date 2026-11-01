#!/usr/bin/env bash
# tiiny-swap.sh — run a command against a specific Tiiny model, safely.
#
# PURPOSE
# -------
# A Tiiny model load is a SWAP, not an add: NPU-RAM is finite and shared, so
# loading a model evicts whatever was resident. Two things then have to be
# true for the swap to be safe:
#
#   1. The watchdog must not fight it. ~/.hermes/scripts/tiiny-watch.sh
#      reloads its REQUIRED_MODELS list every five minutes, and that reload
#      would evict the model we just loaded. So this script writes a hold
#      file first; the watchdog sees the hold and reloads nothing.
#
#   2. The model the delegation config expects must come back afterwards.
#      The required set is restored at the end, in the same order the
#      watchdog would use, so the next delegated child finds its model.
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
# deliberately resident. Stale holds are the hazard: one left behind stops
# the watchdog from ever restoring the device. --restore and --clear exist
# for that.

set -uo pipefail

TIINY_BIN="$HOME/.local/tiiny/bin/tiiny"
HOLD_FILE="$HOME/.hermes/tiiny-hold"
REQUIRED_MODELS=(
  "Qwen/Qwen3.6-35B-A3B"
  "Qwen/Qwen3-ASR-1.7B"
  "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
)

die() { printf 'tiiny-swap: %s\n' "$1" >&2; exit 1; }

[ -x "$TIINY_BIN" ] || die "tiiny CLI not found at $TIINY_BIN"

# --- restore mode ------------------------------------------------------------
if [ "${1:-}" = "--restore" ]; then
  rm -f "$HOLD_FILE"
  echo "hold cleared; restoring required models..."
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
  rm -f "$HOLD_FILE"
  echo "hold cleared (models left as-is)"
  exit 0
fi

MODEL="${1:-}"
[ -n "$MODEL" ] || die "usage: tiiny-swap.sh <model_id> [-- command...] | --restore | --clear"
shift || true

# --- write the hold BEFORE loading ------------------------------------------
# The watchdog can fire at any moment. If it fires between the load and the
# hold, it evicts the model we just loaded and we are back where we started.
# Writing the hold first closes that window.
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
