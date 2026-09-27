#!/bin/bash
# commons-hygiene.sh — quarterly maintenance scan of the commons
#
# Usage:
#   ./commons-hygiene.sh
#
# What it does:
#   1. Lists MD files older than 60 days that don't have a CLOSURE marker
#   2. Lists empty _agent-* folders (candidates for removal)
#   3. Lists files in _agent-* folders that don't follow the YYYY-MM-DD- naming convention

VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT>/"

echo "=== Unclosed MD files (>60 days old) ==="
if [ -d "$VAULT" ]; then
    find "$VAULT" -name "*.md" -mtime +60 | while read f; do
        grep -q "CLOSED" "$f" || echo "MISSING CLOSURE: $f"
    done
else
    echo "(VAULT path not set or not accessible — edit the script)"
fi

echo ""
echo "=== Empty agent folders ==="
find "$VAULT" -type d -name "_agent-*" -empty 2>/dev/null | while read d; do
    echo "Empty: $d"
done

echo ""
echo "=== Files without YYYY- date prefix ==="
find "$VAULT/_agent-*" -name "*.md" ! -name "[0-9][0-9][0-9][0-9]-*" 2>/dev/null | head -10

echo ""
echo "=== Hygiene scan complete. ==="
