#!/bin/bash
# NER Spatial Coverage Analyzer - forgot the password? Set a new one (macOS).
# Same tool as reset-password.bat: lists the accounts, asks which one and the
# new password twice. Works with the app running.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT" && PYTHONNOUSERSITE=1 "$ROOT/.python/bin/python3" -s tools/reset_password.py "$@"
rc=$?
if [ -z "${NER_NOPAUSE:-}" ] && [ -t 0 ]; then printf '\nPress Enter to close.'; read -r _ || true; fi
exit $rc
