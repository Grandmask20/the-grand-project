"""The classical detector's map candidates and their features (grand_project/detect/maps.py)."""

from __future__ import annotations

import cv2
import numpy as np

from grand_project.detect import maps


def test_the_hue_angle_table_holds_what_each_pixel_worked_out():
    # map_features looks the cos / sin of a pixel's hue angle up instead of working it out per pixel: the table must
    # hold exactly the per-pixel values (float32 hue / 90 * pi), or the features (and the maps found) change
    hue = cv2.cvtColor(np.arange(180, dtype=np.uint8).repeat(3).reshape(1, 180, 3), cv2.COLOR_BGR2HSV)[..., 0]
    hue = np.unique(np.concatenate([hue.ravel(), np.arange(180, dtype=np.uint8)]))
    per_pixel = hue.astype(np.float32) / 90 * np.pi
    assert np.array_equal(maps._HUE_COS[hue], np.cos(per_pixel))
    assert np.array_equal(maps._HUE_SIN[hue], np.sin(per_pixel))
    assert maps._HUE_COS.dtype == maps._HUE_SIN.dtype == np.float32


def test_features_have_one_row_per_candidate():
    rng = np.random.default_rng(3)
    img = cv2.GaussianBlur(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8), (0, 0), 2)
    pts, dv = maps.map_candidates(img)
    F = maps.map_features(img, pts, dv)
    assert F.shape[0] == len(pts) and F.dtype == np.float32 and np.isfinite(F).all()
    assert maps.map_features(img, pts[:0], dv[:0]).shape == (0, F.shape[1])
