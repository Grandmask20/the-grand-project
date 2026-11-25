"""Sharp ground past the map image (webmap.sharp.SharpTiles): built from the screenshots themselves."""

import cv2
import numpy as np

from grand_project import core
from grand_project.webmap.sharp import SharpTiles
from grand_project.webmap.tiles import Grid, RasterTiler


def test_a_sharp_tile_pixel_is_the_screenshots_own(tmp_path):
    yy, xx = np.mgrid[0:1080, 0:1920]
    at, shots = core.Atlas(), {}
    for name, dx, blue in (("a", 0, 40), ("b", 900, 120)):
        img = np.dstack([60 + xx * 150 // 1920, 60 + yy * 150 // 1080, np.full_like(xx, blue)]).astype(np.uint8)
        cv2.imwrite(str(tmp_path / f"{name}.png"), img)
        shots[name] = img
        at.frames.append({"name": name, "path": str(tmp_path / f"{name}.png"), "sha": name, "w": 1920, "h": 1080,
                          "M": [[1.0, 0, dx], [0, 1.0, 0]], "stats": {}})  # fmt: skip
    canvas, origin, _w = at.composite(max_pixels=2_000_000, with_weight=True)
    grid = Grid(origin, canvas.shape[1], canvas.shape[0])
    footprints = [core.footprint(at, f) for f in at.frames]
    sharp = SharpTiles(at, footprints, grid, RasterTiler(canvas, grid), grid.deepest(2.0), folder=tmp_path / "sharp")
    z = sharp.zdeep
    assert sharp.has(z) and not sharp.has(grid.zmax)
    k = 2 ** (z - grid.zmax)
    f = at.frames[0]
    H = core.screen_to_atlas(np.array(f["M"], float), at.frame_R(f))
    for sx, sy in ((700, 500), (400, 300), (850, 700)):  # where only screenshot a shows the ground
        wx, wy = grid.world_px(*core.persp(H, [[sx, sy]])[0])
        wx, wy = wx * k, wy * k
        tx, ty = int(wx // 256), int(wy // 256)
        tile = cv2.imdecode(np.frombuffer(sharp.jpeg(z, tx, ty), np.uint8), cv2.IMREAD_COLOR)
        got = tile[int(wy - ty * 256), int(wx - tx * 256)].astype(int)
        assert np.abs(got - shots["a"][sy, sx].astype(int)).max() <= 12, (sx, sy, got)
        assert (tmp_path / "sharp" / str(z) / str(tx) / f"{ty}.jpg").is_file()  # kept for next time


def test_a_sharp_tile_missing_a_screenshot_lost_mid_build_is_not_kept_in_its_folder(tmp_path, monkeypatch):
    img = np.full((1080, 1920, 3), 90, np.uint8)
    cv2.imwrite(str(tmp_path / "a.png"), img)
    at = core.Atlas()
    at.frames.append({"name": "a", "path": str(tmp_path / "a.png"), "sha": "a", "w": 1920, "h": 1080,
                      "M": [[1.0, 0, 0], [0, 1.0, 0]], "stats": {}})  # fmt: skip
    canvas, origin, _w = at.composite(max_pixels=2_000_000, with_weight=True)
    grid = Grid(origin, canvas.shape[1], canvas.shape[0])
    footprints = [core.footprint(at, f) for f in at.frames]
    sharp = SharpTiles(at, footprints, grid, RasterTiler(canvas, grid), grid.deepest(2.0), folder=tmp_path / "sharp")
    z = sharp.zdeep
    k = 2 ** (z - grid.zmax)
    wx, wy = grid.world_px(960.0, 540.0)
    tx, ty = int(wx * k // 256), int(wy * k // 256)
    monkeypatch.setattr(at, "image", lambda path: None)  # (deleted after the "picture there?" check, no copy)
    left = []
    assert sharp.jpeg(z, tx, ty, skipped=left) is not None and left == ["a"]
    assert not (tmp_path / "sharp" / str(z) / str(tx) / f"{ty}.jpg").exists()  # (made again next time)
