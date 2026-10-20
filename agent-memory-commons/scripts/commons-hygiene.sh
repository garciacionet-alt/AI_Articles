#!/bin/bash
# commons-hygiene.sh — quarterly maintenance scan of the commons
#
# Usage:
#   export VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT-NAME>"
#   ./commons-hygiene.sh
#
# What it does:
#   1. Lists markdown files older than 60 days that carry no closure marker
#   2. Lists empty _agent-* folders (candidates for removal)
#   3. Lists files in _agent-* folders that do not follow the YYYY-MM-DD- convention
#   4. Lists notes flagged "status: stale" — the pruning queue
#
# It reports. It never deletes.

set -u
VAULT="${VAULT:-<VAULT-PATH>}"

echo "=== Unclosed projects (>60 days old) ==="
find "$VAULT" -name "*.md" -mtime +60 -print0 |
while IFS= read -r -d '' f; do
    if ! grep -q -- "<!-- CLOSED" "$f"; then
        echo "MISSING CLOSURE: $f"
    fi
done

echo ""
echo "=== Empty agent folders ==="
find "$VAULT" -type d -name "_agent-*" -empty -print0 |
while IFS= read -r -d '' d; do
    echo "Empty: $d"
done

echo ""
echo "=== Files without date prefix ==="
for d in "$VAULT"/_agent-*/; do
    [ -d "$d" ] || continue
    find "$d" -name "*.md" ! -name "[0-9][0-9][0-9][0-9]-*" -print0 |
    while IFS= read -r -d '' f; do
        printf '%s\n' "$f"
    done
done | head -10

echo ""
echo "=== Notes flagged status: stale (pruning queue) ==="
find "$VAULT" -name "*.md" -print0 |
while IFS= read -r -d '' f; do
    if grep -q -- "^status: *stale" "$f"; then
        echo "STALE: $f"
    fi
done

echo ""
echo "=== Hygiene scan complete. ==="
