"""Tests for optional classes produced by the dataset bootstrapper."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_named_icons_and_derived_classes_are_independent() -> None:
    """Named icon labels work while paths and fortress walls remain independently optional."""
    project_root = Path(__file__).resolve().parents[1]
    program_dir = project_root / "bootstrap-dataset-program"
    environment = os.environ.copy()
    python_paths = [str(program_dir), str(project_root)]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    script = """
import json
import numpy as np
from dataset_bootstrap import _labels_for_state, detection_annotations
from grand_project.detect import constants

constants.RF_DETR_WALL_MIN_AREA = 100
image = np.zeros((100, 100, 3), dtype=np.uint8)
wall_mask = np.zeros((100, 100), dtype=np.uint8)
wall_mask[10:30, 10:30] = 1
detection = {
    "edges": [{"line": [[10, 20], [90, 30]]}],
    "icons": [{"x": 50, "y": 50, "name": "Map Boss"}],
}
path_annotations = detection_annotations(
    detection, image, image, include_paths=True, named_icons=True, wall_mask=wall_mask
)
wall_annotations = detection_annotations(
    detection, image, image, include_fortress_walls=True, named_icons=True, wall_mask=wall_mask
)
print(json.dumps({
    "paths": [annotation["label"] for annotation in path_annotations],
    "walls": [annotation["label"] for annotation in wall_annotations],
    "export_labels": _labels_for_state({
        "settings": {"named_icons": True},
        "images": {"sample": {"annotations": [{"label": "icon_map_boss"}]}},
    }),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    labels = json.loads(completed.stdout)
    assert labels["paths"] == ["icon_map_boss", "path"]
    assert labels["walls"] == ["icon_map_boss", "fortress_wall"]
    assert "icon_map_boss" in labels["export_labels"]
    assert "icon" not in labels["export_labels"]
