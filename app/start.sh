#!/usr/bin/env bash
# NER Spatial Coverage Analyzer - macOS / Linux launcher
set -euo pipefail
cd "$(dirname "$0")"
exec python3 run.py "$@"
