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
    monkeypatch.setattr(at, "image", lambda path, **kw: None)  # (deleted after the "picture there?" check, no copy)
    left = []
    assert sharp.jpeg(z, tx, ty, skipped=left) is not None and left == ["a"]
    assert not (tmp_path / "sharp" / str(z) / str(tx) / f"{ty}.jpg").exists()  # (made again next time)


def test_the_zoomed_in_ground_keeps_its_own_few_screenshots_not_the_placements(tmp_path):
    # (reading through the placements' cache filled all 90 of it, ~540 MB, when panning or opening Find's pictures)
    from grand_project.webmap.constants import WEBMAP_SHARP_IMAGES

    yy, xx = np.mgrid[0:1080, 0:1920]
    at = core.Atlas()
    for k in range(WEBMAP_SHARP_IMAGES + 3):
        img = np.dstack([60 + xx * 150 // 1920, 60 + yy * 150 // 1080, np.full_like(xx, 40 + k)]).astype(np.uint8)
        cv2.imwrite(str(tmp_path / f"s{k}.png"), img)
        at.frames.append({"name": f"s{k}", "path": str(tmp_path / f"s{k}.png"), "sha": f"s{k}", "w": 1920, "h": 1080,
                          "M": [[1.0, 0, 50.0 * k], [0, 1.0, 0]], "stats": {}})  # fmt: skip
    canvas, origin, _w = at.composite(max_pixels=2_000_000, with_weight=True)
    at.release_images()
    grid = Grid(origin, canvas.shape[1], canvas.shape[0])
    footprints = [core.footprint(at, f) for f in at.frames]
    sharp = SharpTiles(at, footprints, grid, RasterTiler(canvas, grid), grid.deepest(2.0))
    for f in at.frames:
        assert sharp._weight(f).dtype == np.float32  # (warped as float32)
    assert at._images == {}  # (none put in the placements' cache)
    assert len(sharp._images) == WEBMAP_SHARP_IMAGES and sharp.holding()
    assert next(iter(sharp._weights.values())).dtype == np.float16  # (kept at half the size)
    z = sharp.zdeep
    k = 2 ** (z - grid.zmax)
    wx, wy = grid.world_px(960.0, 540.0)
    assert sharp.jpeg(z, int(wx * k // 256), int(wy * k // 256)) is not None
    assert sharp.release() == WEBMAP_SHARP_IMAGES and not sharp.holding()


def test_a_screenshots_terrain_mask_goes_with_it():
    # (masks of screenshots let go stayed up to the cache's 64, ~2 MB each)
    import gc

    from grand_project.core import terrain

    img = np.full((1080, 1920, 3), 90, np.uint8)
    terrain._valid_mask(img)
    key = id(img)
    assert key in terrain._MASKS
    del img
    gc.collect()
    assert key not in terrain._MASKS
