#!/usr/bin/env bash
# Installs the Python packages the viewer needs (macOS / Linux). Run once: ./install.sh
# Needs Python 3.11+ with Tk (macOS: python.org installer, or `brew install python-tk`;
# Debian/Ubuntu: `sudo apt install python3-tk`).
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" - <<'PYEOF'
import sys
if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required (found %d.%d)." % sys.version_info[:2])
try:
    import tkinter
except ImportError:
    sys.exit("This Python has no Tk. macOS: use the python.org installer or `brew install python-tk`. "
             "Debian/Ubuntu: `sudo apt install python3-tk`.")
PYEOF
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo 'Done. Now run ./start.sh'
