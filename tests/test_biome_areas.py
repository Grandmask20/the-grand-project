"""Biome areas on the web map (webmap.shapes.biome_polygons) and hand-painted biomes (cities.biomes)."""

import cv2
import numpy as np

from grand_project.webmap.shapes import biome_polygons


def node(x, y, status="confirmed"):
    return {"x": float(x), "y": float(y), "status": status}


def covered(polys, x, y):
    """Whether the point lies inside any of the kind's polygons (inside the outer ring, in none of its holes)."""

    def within(ring):
        return cv2.pointPolygonTest(np.array(ring, np.float32).reshape(-1, 1, 2), (float(x), float(y)), False) >= 0

    return any(within(poly[0]) and not any(within(r) for r in poly[1:]) for poly in polys)


def test_an_area_never_covers_a_map_outside_it():
    # a row of maps 100 apart (closer than the 140 disc): the middle one was painted "no biome"
    nodes = [node(x, 0) for x in (0, 100, 200, 300, 400)]
    potential = {0: ("Vaal city", 0), 1: ("Vaal city", 1), 3: ("Vaal city", 1), 4: ("Vaal city", 2)}
    ((kind, polys),) = biome_polygons(nodes, potential)
    assert kind == "Vaal"
    assert not covered(polys, 200, 0)  # before: the neighbours' discs and the join covered it
    for x in (0, 100, 300, 400):
        assert covered(polys, x, 0), x


def test_two_biomes_side_by_side_do_not_overlap():
    nodes = [node(0, 0), node(90, 0), node(180, 0), node(270, 0)]
    potential = {0: ("Vaal city", 0), 1: ("Vaal city", 1), 2: ("Faridun city", 1), 3: ("Faridun city", 0)}
    areas = dict(biome_polygons(nodes, potential))
    assert covered(areas["Vaal"], 90, 0) and not covered(areas["Vaal"], 180, 0)
    assert covered(areas["Faridun"], 180, 0) and not covered(areas["Faridun"], 90, 0)


def test_removed_maps_and_no_biomes_draw_nothing():
    assert biome_polygons([node(0, 0)], {}) == []
    assert biome_polygons([node(0, 0, "removed")], {0: ("Vaal city", 0)}) == []


def test_a_painted_biome_reaches_every_map_node_on_the_spot():
    from types import SimpleNamespace

    from grand_project.cities import biomes

    # two map nodes on one spot (a map seen twice) and one apart
    V = {"nodes": [node(500, 500), node(503, 501), node(900, 500)], "paths": [], "icons": [], "landmarks": []}
    at = SimpleNamespace(locks=[], landmark_edits=[], biome_edits=[{"biome": "Vaal city", "maps": [[501.0, 500.0]]}])
    pot = biomes(at, V)["potential"]
    assert pot == {0: ("Vaal city", 0), 1: ("Vaal city", 0)}  # before: only the nearer one
    at.biome_edits.append({"biome": "", "maps": [[500.0, 500.0]]})
    assert biomes(at, V)["potential"] == {}
