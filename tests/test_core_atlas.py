"""The terrain feature cache's descriptors (core.atlas._compact_descriptors): smaller, same values."""

import cv2
import numpy as np

from grand_project.core.atlas import _compact_descriptors


def test_sift_descriptors_are_kept_as_uint8_without_loss():
    rng = np.random.default_rng(3)
    img = cv2.GaussianBlur(rng.integers(0, 255, (600, 800)).astype(np.uint8), (0, 0), 1.5)
    _k, d = cv2.SIFT_create(2000).detectAndCompute(img, None)
    assert d is not None and len(d)
    kept = _compact_descriptors(d)
    assert kept.dtype == np.uint8
    assert np.array_equal(kept.astype(np.float32), d)


def test_descriptors_that_are_not_whole_numbers_stay_float16():
    d = np.array([[0.5, 1.0], [300.0, 2.0]], np.float32)
    kept = _compact_descriptors(d)
    assert kept.dtype == np.float16
    assert np.array_equal(kept, d.astype(np.float16))
