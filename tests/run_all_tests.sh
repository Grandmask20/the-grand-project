#!/usr/bin/env bash
# Runs the tests with pytest (a few minutes). Extra arguments go to pytest,
# e.g. ./tests/run_all_tests.sh -m "" for every test, the slow ones too.
cd "$(dirname "$0")/.." || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi
"$PY" -m pytest -m "not slow" "$@"
