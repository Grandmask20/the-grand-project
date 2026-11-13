#!/usr/bin/env bash
# Opens the Atlas Viewer (macOS / Linux). First time: run ./install.sh
cd "$(dirname "$0")/program" || exit 1
if [ -x ../.venv/bin/python ]; then PY=../.venv/bin/python; else PY="${PYTHON:-python3}"; fi
exec "$PY" atlas_viewer.py "$@"
