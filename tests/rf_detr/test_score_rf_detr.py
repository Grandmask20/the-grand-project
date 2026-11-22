"""``python -m grand_project.detect score_rf_detr`` (grand_project/detect/training.py): the RF-DETR detector on the
hand-labelled screenshots, scored as ``score`` scores the classical one."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project.detect import rf_detr_model, training


def test_the_hand_truth_scores_the_rf_detr_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Its outputs go through the truth's scorer, Expedition ship markers left out as the classical score does."""
    shot = tmp_path / "shot.png"
    cv2.imwrite(str(shot), np.zeros((1080, 1920, 3), np.uint8))
    truth = {"shot.png": {"maps": [{"x": 100.0, "y": 100.0, "flags": []}], "maybe": [], "not_maps": [],
                          "landmarks": [], "badges": []}}  # fmt: skip
    monkeypatch.setattr(training, "_truth_screenshots", lambda: (truth, {"shot.png": shot}))
    monkeypatch.setattr(training, "TRUTH", tmp_path / "truth.json")
    found = {
        "nodes": [{"x": 101.0, "y": 99.0}, {"x": 900.0, "y": 500.0}],  # one right, one false
        "icons": [{"name": "ExpeditionShip", "x": 5.0, "y": 5.0}],
        "landmarks": [],
        "edges": [],
    }
    seen = []

    def detect(img: np.ndarray) -> dict:
        seen.append(img.shape)
        return json.loads(json.dumps(found))

    monkeypatch.setattr(rf_detr_model, "detect_rf_detr", detect)
    assert training.cmd_score_rf_detr() == 0
    assert seen == [(1080, 1920, 3)]
    printed = capsys.readouterr().out
    assert "RF-DETR detector" in printed
    saved = json.loads((tmp_path / "last_score_outputs_rf_detr.json").read_text())
    assert saved["shot.png"]["icons"] == [] and len(saved["shot.png"]["nodes"]) == 2
