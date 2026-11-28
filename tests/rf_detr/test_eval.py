"""Task metrics of RF-DETR checkpoints (grand_project/detect/rf_detr_eval.py)."""

import pytest

from grand_project import truth
from grand_project.detect import constants as K
from grand_project.detect.rf_detr_eval import average_precision, evaluate, format_report


def test_default_match_radii_are_the_detector_score_radii() -> None:
    """Each family's default match radius (``RF_DETR_EVAL_RADIUS``) is the radius ``python -m grand_project.detect
    score`` scores the hand truth with (``truth.MAP_R``, ``BADGE_R``, ``LM_R``)."""
    assert K.RF_DETR_EVAL_RADIUS["node"] == truth.MAP_R
    assert K.RF_DETR_EVAL_RADIUS["icon"] == truth.BADGE_R
    assert K.RF_DETR_EVAL_RADIUS["button"] == truth.BADGE_R <= K.RF_DETR_BUTTON_SHIFT  # every match can be named
    for family in ("citadel", "hall", "tower", "stronghold"):
        assert K.RF_DETR_EVAL_RADIUS[family] == truth.LM_R


def test_average_precision() -> None:
    assert average_precision([True, True], 2) == pytest.approx(1.0)
    assert average_precision([False, True], 1) == pytest.approx(0.5)
    assert average_precision([True, False, True], 4) == pytest.approx(0.25 + 0.25 * 2 / 3)
    assert average_precision([], 3) == 0.0 and average_precision([True], 0) == 0.0


def test_families_are_scored_apart_and_classes_within_them() -> None:
    """A node found with the wrong biome is still found (recall), but its class is wrong (class accuracy). A
    prediction under the threshold counts for AP (the whole ranking) but not for recall or precision."""
    truths = [
        [
            {"label": "map_node_grass", "x": 100, "y": 100},
            {"label": "map_node_desert", "x": 300, "y": 100},
            {"label": "citadel_stone", "x": 500, "y": 500},
            {"label": "map_node_grass", "x": 900, "y": 900},
        ]
    ]
    predictions = [
        [
            {"label": "map_node_grass", "x": 103, "y": 98, "score": 0.9},
            {"label": "map_node_grass", "x": 305, "y": 101, "score": 0.8},  # right place, wrong biome
            {"label": "map_node", "x": 700, "y": 100, "score": 0.7},  # nothing there
            {"label": "citadel_iron", "x": 520, "y": 480, "score": 0.6},
            {"label": "map_node_grass", "x": 900, "y": 900, "score": 0.1},  # right, but under the threshold
        ]
    ]
    result = evaluate(predictions, truths)
    node, citadel = result["families"]["node"], result["families"]["citadel"]
    assert (node["truths"], node["predictions"]) == (3, 3)
    assert node["recall"] == pytest.approx(2 / 3) and node["precision"] == pytest.approx(2 / 3)
    assert node["class_accuracy"] == 0.5
    ranked = average_precision([True, True, False, True], 3)  # 0.9, 0.8, 0.7 (nothing there), 0.1
    assert node["ap"] == pytest.approx(ranked) and ranked > average_precision([True, True, False], 3)
    assert citadel["recall"] == 1.0 and citadel["class_accuracy"] == 0.0
    assert result["mean_ap"] == pytest.approx((ranked + 1.0) / 2)
    assert "node" in format_report(result)
    with pytest.raises(ValueError):
        evaluate(predictions, [])
