#!/bin/bash
# NER Spatial Coverage Analyzer - run the automated tests (macOS)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT" || exit 1
[ -x .python/bin/python3 ] || { echo "Run setup.command first."; exit 1; }
PYTHONNOUSERSITE=1 .python/bin/python3 -s -m pytest tests -q -p no:cacheprovider "$@"
rc=$?
echo
if [ $rc -eq 0 ]; then echo "  All tests passed."; else echo "  Some tests FAILED - see above. Exit code $rc."; fi
if [ -z "${NER_NOPAUSE:-}" ] && [ -t 0 ]; then printf '\nPress Enter to close.'; read -r _ || true; fi
exit $rc
