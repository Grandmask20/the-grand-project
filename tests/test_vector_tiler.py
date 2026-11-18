"""Vector tiles made when asked for (webmap.tiles.VectorTiler), and the clipping they use."""

from grand_project.webmap.mvt import ring_area
from grand_project.webmap.tiles import Grid, VectorTiler, _clip_line, _clip_polygon
from tests.webmap_data import read_tile


def test_clip_polygon_to_the_tile():
    (ring,) = _clip_polygon([[(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]], 0, 4096)
    assert sorted(ring) == [(0, 0), (0, 50), (50, 0), (50, 50)] and ring_area(ring) > 0
    reversed_outer = [(10.0, 10.0), (10.0, 90.0), (90.0, 90.0), (90.0, 10.0)]  # wrong way round: turned
    assert ring_area(_clip_polygon([reversed_outer], 0, 4096)[0]) > 0
    assert _clip_polygon([[(-90.0, -90.0), (-10.0, -90.0), (-10.0, -10.0)]], 0, 4096) == []  # outside


def test_clip_line_keeps_the_part_inside():
    pieces = _clip_line([(-1000, 100), (1000, 100), (1000, 5000)], -10, 4106)
    assert pieces == [[(-10, 100), (1000, 100), (1000, 4106)]]
    assert _clip_line([(-500, -500), (-400, -300)], 0, 4096) == []


def _all_points(tiler: VectorTiler, z: int, layer: str) -> dict:
    """Every point feature of a layer at level z, in world px at that level (copies in tile buffers dropped)."""
    out = {}
    for tx in range(2**z):
        for ty in range(2**z):
            for _g, ((_c, x, y),), props, fid in read_tile(tiler.tile(z, tx, ty)).get(layer, []):
                if 0 <= x < 4096 and 0 <= y < 4096:
                    out[fid] = (tx * 256 + x / 16, ty * 256 + y / 16, props)
    return out


def test_points_land_where_they_are_at_every_level():
    g = Grid((0, 0, 1), 1500, 900)
    pts = [(10.0, 20.0), (700.5, 450.25), (1499.0, 899.0)]
    feats = [{"kind": "point", "pts": [g.world_px(x, y)], "id": i, "props": {"id": i}} for i, (x, y) in enumerate(pts)]
    tiler = VectorTiler({"maps": feats}, g)
    for z in (g.zmax, g.zmax - 2):
        f = 2.0 ** (z - g.zmax)
        got = _all_points(tiler, z, "maps")
        assert sorted(got) == [0, 1, 2]
        for i, (x, y) in enumerate(pts):
            wx, wy = g.world_px(x, y)
            assert abs(got[i][0] - wx * f) <= 0.05 and abs(got[i][1] - wy * f) <= 0.05, (z, i)


def test_dense_layers_wait_for_their_level_and_empty_tiles_are_empty():
    g = Grid((0, 0, 1), 1500, 900)
    icon = {"kind": "point", "pts": [g.world_px(100, 100)], "id": 0, "props": {"name": "Breach"}}
    tiler = VectorTiler({"icons": [icon]}, g, min_zoom={"icons": g.zmax})
    assert _all_points(tiler, g.zmax, "icons") and not _all_points(tiler, g.zmax - 1, "icons")
    assert tiler.tile(g.zmax, 0, 0) == b""  # the world's corner: nothing there


def test_a_line_crossing_tiles_is_in_each_of_them():
    g = Grid((0, 0, 1), 1500, 900)
    line = {"kind": "line", "pts": [g.world_px(0, 100), g.world_px(1400, 100)], "id": 3, "props": {"abyss": True}}
    tiler = VectorTiler({"paths": [line]}, g)
    ty = int(g.world_px(0, 100)[1] // 256)
    hit = [tx for tx in range(2**g.zmax) if read_tile(tiler.tile(g.zmax, tx, ty)).get("paths")]
    assert len(hit) >= 1400 // 256  # every tile it runs through
