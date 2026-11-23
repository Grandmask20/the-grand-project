"""Offline tests for detector-comparison report helpers."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import compare_detectors
from tools.compare_detectors import _f1, _landmark_hits, _normalise_accuracy, _parse_match


def test_parse_match_returns_precision_recall_and_f1() -> None:
    result = _parse_match("10 of 12 match; found 10 of 20 (50%)")
    assert result["matched"] == 10
    assert result["predicted"] == 12
    assert result["reference"] == 20
    assert result["precision"] == 10 / 12
    assert result["recall"] == 0.5
    assert result["f1"] == _f1(10 / 12, 0.5)


def test_parse_match_handles_empty_summary() -> None:
    assert _parse_match("") == {
        "matched": 0,
        "predicted": 0,
        "reference": 0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }


def test_normalise_accuracy_reports_empty_detector_counts() -> None:
    result = _normalise_accuracy(
        {"screenshots": "0 / 3 placed", "maps": 0, "paths": 0, "icons": 0, "landmarks": {}},
        {"screenshots": "3 / 3 placed", "maps": 12, "paths": 8, "icons": 4, "landmarks": {"Tower": 2}},
        {},
    )
    assert result["matches"] == {
        "maps": {"matched": 0, "predicted": 0, "reference": 12, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "icons": {"matched": 0, "predicted": 0, "reference": 4, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "paths": {"matched": 0, "predicted": 0, "reference": 8, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "landmarks": {"matched": 0, "predicted": 0, "reference": 2, "precision": 0.0, "recall": 0.0, "f1": 0.0},
    }


def test_landmarks_match_one_to_one_whatever_their_order() -> None:
    """A greedy match let the first City take the reference City the second needed (both within reach of the first):
    the assignment pairs both, in either order."""
    expected = [{"kind": "City", "x": 0.0, "y": 0.0}, {"kind": "City", "x": 18.0, "y": 0.0}]
    predicted = [{"kind": "City", "x": 9.0, "y": 0.0}, {"kind": "City", "x": 1.0, "y": 0.0}]
    for order in (predicted, predicted[::-1]):
        assert _landmark_hits(order, expected, np.zeros(2), 10.0) == 2
    hall = [{"kind": "Hall", "x": 0.0, "y": 0.0}]  # another kind never matches
    assert _landmark_hits(hall, expected, np.zeros(2), 10.0) == 0
    assert _landmark_hits(predicted, expected, np.array([100.0, 0.0]), 10.0) == 0  # shifted out of reach


def test_a_rebuild_whose_detection_failed_stops_the_comparison(tmp_path: Path) -> None:
    """The builder exits 1 when a screenshot could not be detected: that is no empty atlas to score."""
    reference = tmp_path / "ref"
    reference.mkdir()
    (reference / "atlas.json").write_text("{}")
    folder = tmp_path / "res_1080_100"
    folder.mkdir()

    def rebuild(work: Path) -> None:
        raise subprocess.CalledProcessError(1, ["builder"], output=b"1 screenshots could not be detected: a.png")

    scorer = SimpleNamespace(REFERENCE="ref", rebuild=rebuild)
    backend = compare_detectors.Backend("RF-DETR", lambda img: {})
    with pytest.raises(SystemExit, match="RF-DETR: rebuilding res_1080_100 failed:\n1 screenshots could not be"):
        compare_detectors._rebuild_accuracy(backend, tmp_path, [folder], tmp_path / "model", "cpu", scorer)


def test_landmarks_are_read_as_the_scorer_counts_them(tmp_path: Path) -> None:
    """Through the scorer's view model (the user's landmark edits applied), removed ones left out."""
    loaded = []
    core = SimpleNamespace(Atlas=SimpleNamespace(load=lambda path: loaded.append(path) or "atlas"))

    def view_model(atlas):
        assert atlas == "atlas"
        return {"landmarks": [{"kind": "City", "x": 1, "y": 2, "status": "kept"},
                              {"kind": "Tower", "x": 3, "y": 4, "status": "removed: edit"}]}  # fmt: skip

    assert compare_detectors._live_landmarks(tmp_path, core, view_model) == [
        {"kind": "City", "x": 1, "y": 2, "status": "kept"}
    ]
    assert loaded == [tmp_path / "atlas.json"]
