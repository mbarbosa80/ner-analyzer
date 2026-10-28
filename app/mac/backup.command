#!/bin/bash
# NER Spatial Coverage Analyzer - back up the data (macOS). Same tool as backup.bat.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT" && PYTHONNOUSERSITE=1 "$ROOT/.python/bin/python3" -s tools/backup.py "$@"
rc=$?
if [ -z "${NER_NOPAUSE:-}" ] && [ -t 0 ]; then printf '\nPress Enter to close.'; read -r _ || true; fi
exit $rc
