#!/bin/bash
# NER Spatial Coverage Analyzer - register the server for this account (macOS)
# (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.
#
# Writes ~/Library/LaunchAgents/com.marcelobarbosa.ner-analyzer.plist and loads
# it: the server starts now, at every sign-in, and again if it stops on its own
# (launchd's KeepAlive does what the watchdog task does on Windows). Per user,
# no administrator password. "autostart.command remove" takes it away again.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
LABEL="com.marcelobarbosa.ner-analyzer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
if [ "${1:-}" = "remove" ]; then
    rm -f "$PLIST"
    echo "Removed: the server no longer starts at sign-in."
    exit 0
fi
[ -x "$ROOT/.python/bin/python3" ] || { echo "No runtime in $ROOT/.python - run setup.command first."; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.python/bin/python3</string>
    <string>-s</string>
    <string>$ROOT/tools/serve.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONNOUSERSITE</key><string>1</string>
    <key>NER_PORT</key><string>${NER_PORT:-8000}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>20</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$ROOT/data/launchd.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/launchd.log</string>
</dict>
</plist>
PL
plutil -lint "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST" || { echo "launchctl refused the agent."; exit 1; }
launchctl kickstart "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
echo "Registered: $PLIST (starts at sign-in, restarted if it stops)."
