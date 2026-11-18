#!/usr/bin/env bash
# Starts The Grand Project in your web browser (macOS / Linux). First time: run ./install.sh
# Ctrl+C here (or File > Quit the app on the page) stops it.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi
exec "$PY" -m grand_project "$@"
