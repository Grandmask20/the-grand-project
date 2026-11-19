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
