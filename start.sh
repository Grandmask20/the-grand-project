#!/usr/bin/env bash
# Opens The Grand Project (macOS / Linux). First time: run ./install.sh
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi
exec "$PY" -m grand_project "$@"
