"""Scoring a link on the gold dotted line (gold_paths.route_score)."""

import cv2
import numpy as np

from grand_project import gold_paths as gp


def _field() -> np.ndarray:
    """Distance field of a dotted line from (100, 200) to (300, 200), as the path check keeps it (float16)."""
    gold = np.zeros((400, 400), np.uint8)
    for x in range(100, 300, 12):
        gold[199:201, x : x + 5] = 255
    return np.minimum(cv2.distanceTransform(255 - gold, cv2.DIST_L2, 3), 255).astype(np.float16)


def test_a_float16_field_scores_as_its_float32_copy():
    f16 = _field()
    a, b, off = np.array([100.0, 200.0]), np.array([300.0, 200.0]), np.array([100.0, 260.0])
    assert gp.route_score(f16, a, b) == gp.route_score(f16.astype(np.float32), a, b)
    assert gp.route_score(f16, a, off) == gp.route_score(f16.astype(np.float32), a, off)
    assert gp.route_score(f16, a, b) > gp.route_score(f16, a, off)  # (on the line beats beside it)
