"""Offline tests for detector-comparison report helpers."""

import numpy as np

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
