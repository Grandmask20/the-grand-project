"""The pattern match the icon and map node state namers share (icon_refs.shift_dists)."""

import numpy as np

from grand_project import icon_refs


def _picture(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, (icon_refs.SIZE, icon_refs.SIZE, 3), dtype=np.uint8)


def test_a_picture_found_a_few_px_off_matches_itself_best(seed):
    pics = [_picture(seed), _picture(seed + 1)]
    F = np.array([icon_refs.feature(p) for p in pics], np.float32)
    img = np.zeros((200, 200, 3), np.uint8)
    img[80 : 80 + icon_refs.SIZE, 90 : 90 + icon_refs.SIZE] = pics[1]
    centre = (90 + icon_refs.SIZE // 2, 80 + icon_refs.SIZE // 2)
    d, crop = icon_refs.shift_dists(img, centre[0] + icon_refs.SHIFT, centre[1] - 2, F)  # off by up to SHIFT px
    assert d[1] < 1e-4 < d[0]
    assert crop.shape == (icon_refs.SIZE, icon_refs.SIZE, 3)


def test_a_crop_past_the_edge_is_not_compared():
    F = np.zeros((1, int(icon_refs._MASK.sum()) * 3), np.float32)
    assert icon_refs.shift_dists(np.zeros((200, 200, 3), np.uint8), 5, 100, F) is None


def test_the_shifted_match_is_the_feature_of_each_shifted_crop(seed):
    """Blurring the crop once gives what feature gives each shifted crop (the icon namer's loop before shift_dists)."""
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (120, 120, 3), dtype=np.uint8)
    F = np.array([icon_refs.feature(_picture(seed + k)) for k in range(4)], np.float32)
    d, crop = icon_refs.shift_dists(img, 60.3, 58.7, F)
    big = icon_refs.crop(img, 60.3, 58.7, icon_refs.SIZE + 2 * icon_refs.SHIFT)
    size, shift = icon_refs.SIZE, icon_refs.SHIFT
    old = np.full(len(F), 9.0, np.float32)
    for dy in range(2 * shift + 1):
        for dx in range(2 * shift + 1):
            old = np.minimum(old, 1 - F @ icon_refs.feature(big[dy : dy + size, dx : dx + size]))
    np.testing.assert_allclose(d, old, atol=1e-5)
    np.testing.assert_array_equal(crop, big[shift : shift + size, shift : shift + size])
