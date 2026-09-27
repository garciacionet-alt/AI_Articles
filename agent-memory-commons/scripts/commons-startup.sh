#!/bin/bash
# commons-startup.sh — run at agent session start to load recent commons context
#
# Usage:
#   ./commons-startup.sh
#
# What it does:
#   1. Reads each _agent-*/README.md to identify what each agent subspace contains
#   2. Lists recent files in your own agent subspace (modified in the last 7 days)
#   3. Prints a summary you can scan to decide what to read in detail

VAULT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/<VENDOR>/<VAULT>/"
AGENT_FOLDER="$VAULT/_agent-<name>/"

echo "=== Agent subspace READMEs ==="
for d in "$VAULT"/_agent-*/; do
    if [ -f "$d/README.md" ]; then
        echo "--- $d"
        head -10 "$d/README.md"
    fi
done

echo ""
echo "=== Recent files in $AGENT_FOLDER ==="
if [ -d "$AGENT_FOLDER" ]; then
    find "$AGENT_FOLDER" -name "*.md" -mtime -7 | sort -r | head -10
else
    echo "(agent folder does not exist yet — this is fine for a new setup)"
fi

echo ""
echo "=== Startup scan complete. Ready to begin. ==="
