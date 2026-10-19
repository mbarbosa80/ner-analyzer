#!/bin/bash
# NER Spatial Coverage Analyzer - start the server (macOS)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
LABEL="com.marcelobarbosa.ner-analyzer"
PORT="${NER_PORT:-8000}"
if [ -f "$HOME/Library/LaunchAgents/$LABEL.plist" ] && [ "$PORT" = "8000" ]; then
    launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist" >/dev/null 2>&1 || true
    launchctl kickstart "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
else
    cd "$ROOT" && PYTHONNOUSERSITE=1 NER_PORT="$PORT" nohup "$ROOT/.python/bin/python3" -s tools/serve.py >/dev/null 2>&1 &
fi
i=0
while [ $i -lt 30 ]; do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
        echo "The server answers on http://127.0.0.1:$PORT/"
        [ "${1:-}" = "--no-browser" ] || open "http://127.0.0.1:$PORT/" 2>/dev/null || true
        exit 0
    fi
    sleep 2; i=$((i + 1))
done
echo "The server did not answer within 60 s - see $ROOT/data/server.log"
exit 1
