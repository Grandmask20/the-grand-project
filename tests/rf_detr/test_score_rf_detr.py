"""``python -m grand_project.detect score_rf_detr`` (grand_project/detect/training.py): the RF-DETR detector on the
hand-labelled screenshots, scored as ``score`` scores the classical one."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project.detect import constants as K
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
    monkeypatch.setenv(K.RF_DETR_MODEL_ENV, str(tmp_path / "model"))
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


def _one_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One hand-labelled 1080p screenshot (no maps) and a detector that finds nothing; the model folder in tmp_path."""
    shot = tmp_path / "shot.png"
    cv2.imwrite(str(shot), np.zeros((1080, 1920, 3), np.uint8))
    truth = {"shot.png": {"maps": [], "maybe": [], "not_maps": [], "landmarks": [], "badges": []}}
    monkeypatch.setattr(training, "_truth_screenshots", lambda: (truth, {"shot.png": shot}))
    monkeypatch.setattr(training, "TRUTH", tmp_path / "truth.json")
    monkeypatch.setenv(K.RF_DETR_MODEL_ENV, str(tmp_path / "model"))
    empty = {"nodes": [], "icons": [], "landmarks": [], "edges": []}
    monkeypatch.setattr(rf_detr_model, "detect_rf_detr", lambda img: dict(empty))
    (tmp_path / "model").mkdir()
    return shot


@pytest.mark.parametrize(
    ("listed", "header"),
    [
        (None, "not known to be held-out"),
        (["other.png"], "held-out: the model trained on none"),
        (["shot.png"], "NOT held-out"),
    ],
)
def test_the_score_is_held_out_only_when_the_model_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, listed, header: str
) -> None:
    """The model's own list of training screenshots (RF_DETR_TRAINED_ON) decides; without one it is not known."""
    shot = _one_shot(tmp_path, monkeypatch)
    if listed is not None:
        names = [training._project_name(shot.with_name(name)) for name in listed]
        (tmp_path / "model" / K.RF_DETR_TRAINED_ON).write_text("".join(f"{n}\n" for n in names), encoding="utf-8")
    assert training.cmd_score_rf_detr() == 0
    assert header in capsys.readouterr().out


def test_no_truth_scores_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(training, "_truth_screenshots", lambda: ({}, {}))
    monkeypatch.setattr(training, "TRUTH", tmp_path / "truth.json")
    assert training.cmd_score_rf_detr() == 1
    assert "no hand-labelled truth" in capsys.readouterr().out
    assert not (tmp_path / "last_score_outputs_rf_detr.json").exists()


def test_screenshots_are_read_as_the_program_reads_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A 4K screenshot is scaled to 1080p (its truth is in 1080p px); one that cannot be read is named and left out."""
    shot = _one_shot(tmp_path, monkeypatch)
    cv2.imwrite(str(shot), np.zeros((2160, 3840, 3), np.uint8))
    seen = []

    def detect(img: np.ndarray) -> dict:
        seen.append(img.shape)
        return {"nodes": [], "icons": [], "landmarks": [], "edges": []}

    monkeypatch.setattr(rf_detr_model, "detect_rf_detr", detect)
    assert training.cmd_score_rf_detr() == 0
    assert seen == [(1080, 1920, 3)]
    shot.write_bytes(b"not a picture")
    assert training.cmd_score_rf_detr() == 0
    assert f"cannot read {shot}" in capsys.readouterr().out
