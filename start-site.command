#!/bin/bash
# Serves the NER Analyzer website on this Mac: http://localhost:8080
# Close the Terminal window (or press Ctrl+C) to stop it.
cd "$(dirname "$0")"
PORT=8080
echo
echo "  NER Analyzer website  >  http://localhost:$PORT"
echo "  Press Ctrl+C to stop."
echo
(sleep 1; open "http://localhost:$PORT/") &
python3 -m http.server "$PORT" --bind 127.0.0.1
