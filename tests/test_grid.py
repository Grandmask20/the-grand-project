"""The map image's grid (webmap.tiles.Grid): atlas units <-> world px <-> longitude / latitude."""

from grand_project.webmap.tiles import Grid
from tests.webmap_data import web_px


def test_points_stay_inside_the_world_and_come_back():
    g = Grid((0, 0, 1), 5000, 3000)
    assert g.world >= 2 * 5000  # the picture fills at most the middle half
    (w, s), (e, n) = g.bounds()
    assert -180 < w < e < 180 and -80 < s < n < 80
    wx, wy = web_px(*g.lnglat(1234.5, 678.9), g.world)
    assert abs(wx - (1234.5 + g.offset)) < 1e-3 and abs(wy - (678.9 + g.offset)) < 1e-3


def test_sharp_levels_reach_the_wanted_detail():
    g = Grid((-300, -200, 0.25), 4000, 3000)
    assert g.deepest(0.25) == g.zmax  # already that sharp
    assert g.deepest(2.0) == g.zmax + 3  # 0.25 -> 2 px per unit: three halvings
    ax0, ay0, s = g.tile_area(g.zmax + 1, g.offset * 2 // 256, g.offset * 2 // 256)
    assert (ax0, ay0, s) == (-300, -200, 0.5)  # the first tile of the picture starts at its corner
