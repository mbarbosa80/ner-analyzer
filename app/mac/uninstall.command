#!/bin/bash
# NER Spatial Coverage Analyzer - remove the application from this Mac.
# The data/ folder (projects, drawings, accounts, backups) is KEPT unless you
# answer "delete" - copy it somewhere first if you may need it again.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[ -f "$ROOT/VERSION" ] && [ -f "$ROOT/tools/serve.py" ] || { echo "This is not an NER Analyzer folder: $ROOT"; exit 1; }
echo "Removing the NER Analyzer installed in $ROOT"
NER_NOPAUSE=1 bash "$ROOT/mac/stop.command" >/dev/null 2>&1
NER_NOPAUSE=1 bash "$ROOT/mac/autostart.command" remove
rm -f "$HOME/Desktop/NER Analyzer.webloc"
printf 'Type "delete" to delete the data too, or press Enter to keep %s/data: ' "$ROOT"
read -r answer || answer=""
if [ "$answer" = "delete" ]; then
    rm -rf "$ROOT"
    echo "Removed, data included."
else
    find "$ROOT" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +
    echo "Removed. The data is still in $ROOT/data."
fi
