"""The box editor's key matching and guess styling (component/annotator.js), with the palette Python sends it.

The editor is plain JavaScript without a build step, so its pure parts are tested with Node's own test runner
(``editor_keys.test.mjs``); the test is skipped where Node is not installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from grand_project import paths
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator import label_names, label_palette

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_editor_keys_and_guess_styling(tmp_path: Path) -> None:
    labels = label_names([], named_icons=True, paths=True, walls=True)
    palette = tmp_path / "palette.json"
    palette.write_text(
        json.dumps({"palette": label_palette(labels), "guessSources": sorted(K.ANNOTATOR_GUESS_SOURCES)}),
        encoding="utf-8",
    )
    test_file = Path(__file__).with_name("editor_keys.test.mjs")
    result = subprocess.run(
        [NODE, "--test", str(test_file)],
        cwd=paths.ROOT,
        # the whole environment: Node on Windows cannot start its random number generator without SYSTEMROOT
        env={**os.environ, "ANNOTATOR_TEST_PALETTE": str(palette)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
