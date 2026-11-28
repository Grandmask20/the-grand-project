"""The city biomes' ground sampler: all map nodes at once gives what one at a time gave."""

import numpy as np

from grand_project.cities import ground_sampler


def test_the_batch_sampler_matches_the_one_by_one_one():
    rng = np.random.default_rng(7)
    canvas = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    weight = np.ones((300, 400), np.float32)
    weight[:, :60] = 0  # a strip no screenshot showed
    at = ground_sampler(canvas, weight, (0.0, 0.0, 0.5), radius=20.0)
    points = np.array(
        [
            [400, 300],  # inside
            [5, 5],  # the disc leaves the canvas: None
            [110, 300],  # mostly over the unseen strip: None
            [790, 590],  # the far corner: None
            [600, 200],
        ],
        float,
    )
    looks, ok = at.many(points)
    for p, look, seen in zip(points, looks, ok, strict=True):
        one = at(*p)
        assert seen == (one is not None)
        if one is not None:
            assert np.allclose(look, one, atol=1e-3)
        else:
            assert not look.any()


def test_the_sampler_keeps_lab_as_uint8_and_gives_the_float32_looks():
    rng = np.random.default_rng(11)
    canvas = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    weight = np.ones((300, 400), np.float32)
    at = ground_sampler(canvas, weight, (0.0, 0.0, 0.5), radius=20.0)
    # what it gave when the whole Lab copy was kept as float32
    import cv2

    lab32 = cv2.cvtColor(canvas, cv2.COLOR_BGR2LAB).astype(np.float32)
    yy, xx = np.mgrid[-10:11, -10:11]
    px = lab32[150 - 10 : 150 + 11, 200 - 10 : 200 + 11][np.hypot(xx, yy) <= 10]
    want = np.concatenate([px.mean(0), px.std(0)])
    assert np.array_equal(at(400.0, 300.0), want)
    looks, ok = at.many(np.array([[400.0, 300.0]]))
    assert ok[0] and np.allclose(looks[0], want, atol=1e-3)
    held = [c.cell_contents for c in at.__closure__ if isinstance(c.cell_contents, np.ndarray)]
    lab = [a for a in held if a.shape == canvas.shape]
    assert lab and all(a.dtype == np.uint8 for a in lab)  # (no float32 Lab copy of the map image kept)
