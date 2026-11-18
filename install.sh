#!/usr/bin/env bash
# Installs the Python packages the app needs (macOS / Linux). Run once: ./install.sh
# Needs Python 3.11+. The app runs in your web browser (a local page: nothing leaves this computer).
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" - <<'PYEOF'
import sys
if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required (found %d.%d)." % sys.version_info[:2])
PYEOF
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo 'Done. Now run ./start.sh'
