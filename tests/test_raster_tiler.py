"""Map image tiles made when asked for (webmap.tiles.RasterTiler)."""

import cv2
import numpy as np

from grand_project.webmap.tiles import Grid, RasterTiler


def _image() -> np.ndarray:
    rng = np.random.default_rng(5)
    img = cv2.GaussianBlur(rng.integers(0, 255, (900, 1500, 3)).astype(np.uint8), (0, 0), 4)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img[:, 1030:] = 0  # unexplored: no tiles there
    return img


def test_the_deepest_tiles_put_together_give_the_map_image():
    img = _image()
    g = Grid((0, 0, 1), img.shape[1], img.shape[0])
    t = RasterTiler(img, g)
    canvas = np.zeros((g.world, g.world, 3), np.uint8)
    T = 256
    for tx in range(g.offset // T, (g.offset + img.shape[1]) // T + 1):
        for ty in range(g.offset // T, (g.offset + img.shape[0]) // T + 1):
            data = t.jpeg(g.zmax, tx, ty)
            x0, y0 = max(0, tx * T - g.offset), max(0, ty * T - g.offset)
            if not img[y0 : ty * T - g.offset + T, x0 : tx * T - g.offset + T].any():
                assert data is None, (tx, ty)  # no ground: no tile
                continue
            tile = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            canvas[ty * T : ty * T + T, tx * T : tx * T + T] = tile
    got = canvas[g.offset : g.offset + img.shape[0], g.offset : g.offset + img.shape[1]]
    assert np.abs(got.astype(int) - img.astype(int)).mean() < 4  # JPEG: close, not exact


def test_each_level_is_the_one_below_halved():
    img = _image()
    g = Grid((0, 0, 1), img.shape[1], img.shape[0])
    t = RasterTiler(img, g)
    assert t.level(g.zmax - 1).shape[:2] == (450, 750)
    assert t.pixels(g.zmax + 1, 0, 0) is None and t.pixels(-1, 0, 0) is None  # outside the levels it has
    whole = t.pixels(0, 0, 0)
    assert whole is not None and whole.shape == (256, 256, 3) and whole.any()
