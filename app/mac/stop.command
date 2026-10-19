#!/bin/bash
# NER Spatial Coverage Analyzer - stop the server of THIS folder (macOS)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
LABEL="com.marcelobarbosa.ner-analyzer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# The launch agent restarts a server that dies; take it down first when it
# belongs to this folder.
if [ -f "$PLIST" ] && grep -q "$ROOT/tools/serve.py" "$PLIST" 2>/dev/null; then
    launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
fi
pkill -f "$ROOT/tools/serve.py" >/dev/null 2>&1 || true
pkill -f "$ROOT/.python/bin/python3 -s tools/serve.py" >/dev/null 2>&1 || true
echo "Stopped (this folder's server: $ROOT)."
echo "It starts again at the next sign-in; mac/start.command starts it now."
