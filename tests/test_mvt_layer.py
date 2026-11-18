"""Vector tile encoding (webmap.mvt.Layer, encode_tile): read back with a reader written from the spec."""

from grand_project.webmap.mvt import Layer, encode_tile, ring_area
from tests.webmap_data import read_tile


def test_points_and_lines_round_trip_with_their_properties():
    lay = Layer("things", 4096)
    lay.add("point", [(10, 4000)], {"s": "a|b", "n": 3, "neg": -2, "f": 1.5, "ok": True}, fid=7)
    lay.add("line", [(0, 0), (100, -50), (4196, 300)], {"s": "a|b"})
    t = read_tile(encode_tile([lay, Layer("empty", 4096)]))
    assert set(t) == {"things"}  # empty layers are left out
    (g1, p1, props1, id1), (g2, p2, props2, _id2) = t["things"]
    assert g1 == 1 and p1 == [(1, 10, 4000)] and id1 == 7
    assert props1 == {"s": "a|b", "n": 3, "neg": -2, "f": 1.5, "ok": True}
    assert g2 == 2 and [(x, y) for _c, x, y in p2] == [(0, 0), (100, -50), (4196, 300)]
    assert [c for c, *_ in p2] == [1, 2, 2] and props2 == {"s": "a|b"}


def test_a_polygon_keeps_its_hole():
    lay = Layer("areas", 4096)
    outer, hole = [(0, 0), (100, 0), (100, 100), (0, 100)], [(20, 20), (20, 80), (80, 80), (80, 20)]
    assert ring_area(outer) > 0 > ring_area(hole)  # MVT: outer positive (clockwise with y down), holes negative
    lay.add("polygon", [outer, hole], {"kind": "Vaal"})
    ((g, pts, props, _id),) = read_tile(encode_tile([lay]))["areas"]
    assert g == 3 and props == {"kind": "Vaal"}
    assert [c for c, *_ in pts] == [1, 2, 2, 2, 7, 1, 2, 2, 2, 7]
    assert [(x, y) for c, x, y in pts if c != 7] == outer + hole
