#!/usr/bin/env bash
# Runs the regression tests one after another (several minutes; the viewer test opens a window).
cd "$(dirname "$0")" || exit 1
if [ -x ../.venv/bin/python ]; then PY=../.venv/bin/python; else PY="${PYTHON:-python3}"; fi
for t in test_atlas_builder test_model_safety test_atlas_folder test_random_sequence test_drop_placement test_false_merge test_detect_pairs test_atlas_viewer; do
  echo "===== $t"
  "$PY" "$t.py"
done
