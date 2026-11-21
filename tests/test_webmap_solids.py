"""webmap.solids: each structure's model, its beams, heights and footprint."""

import math

import pytest

from grand_project.webmap.constants import WEBMAP_BEAM_MIN, WEBMAP_SOLID
from grand_project.webmap.solids import map_pillar, structure

BEAMS = ("#ff8c1a", "#9fe8ff")  # (the page's View: beams off hides these colours)
KINDS = [
    ("Tower", ""),
    ("City", "Vaal"),
    ("City", "Ezomyte"),
    ("City", "Faridun"),
    ("City", ""),
    ("Hall", ""),
    ("Breach stronghold", ""),
]


def _reach(shapes, x, y):
    return max(math.hypot(px - x, py - y) for s in shapes for r in s["rings"] for px, py in r)


@pytest.mark.parametrize(("kind", "city"), KINDS)
def test_each_model_is_detailed_whole_and_in_place(kind, city):
    S = structure(kind, 500.0, -300.0, city)
    assert len(S) >= 10  # (more than a box or two: user)
    for s in S:
        assert s["base"] < s["top"] and all(len(r) >= 3 for r in s["rings"])
    # around its spot, the size it had (icons and the next map nodes stay clear of it)
    assert _reach(S, 500.0, -300.0) <= 125
    # what is not a beam stands under WEBMAP_BEAM_MIN: the icons on it stand on its top, not on a beam
    assert max(s["top"] for s in S if s["colour"] not in BEAMS) < WEBMAP_BEAM_MIN


def test_beams_are_only_the_beams():
    hall = [s for s in structure("Hall", 0, 0) if s["colour"] in BEAMS]
    assert len(hall) == 1 and hall[0]["top"] >= WEBMAP_BEAM_MIN
    tower = [s for s in structure("Tower", 0, 0) if s["colour"] in BEAMS]
    assert tower and max(s["top"] for s in tower) == max(
        s["top"] for s in structure("Tower", 0, 0)
    )  # the beacon on top
    for kind, city in KINDS:
        if kind not in ("Hall", "Tower"):
            assert not [s for s in structure(kind, 0, 0, city) if s["colour"] in BEAMS]


def test_a_locked_stronghold_is_dim_and_low():
    open_, locked = structure("Breach stronghold", 0, 0), structure("Breach stronghold", 0, 0, locked=True)
    assert max(s["top"] for s in locked) < max(s["top"] for s in open_) * 0.6
    assert {s["colour"] for s in locked}.isdisjoint({s["colour"] for s in open_} - {"#2a1630"})


def test_walls_have_their_inside_cut_out():
    walls = [s for s in structure("City", 0, 0, "Ezomyte") if len(s["rings"]) == 2]
    assert walls and all(
        _reach([{"rings": [s["rings"][1]]}], 0, 0) < _reach([{"rings": [s["rings"][0]]}], 0, 0) for s in walls
    )


def test_no_model_for_a_deadly_boss_map_or_an_unknown_kind():
    assert structure("Deadly boss map", 0, 0) == [] and structure("Ruin", 0, 0) == []


def test_a_map_nodes_pillar_plinth_pillar_cap_all_its_own():
    S = map_pillar(10, 20, [], "#28dcff", 7)
    assert [s["colour"] for s in S] == ["#3a3d44", "#28dcff", "#e8e2cf"] and all(s["node"] == 7 for s in S)
    assert S[1]["top"] == WEBMAP_SOLID["map"]
    assert map_pillar(10, 20, ["MapBoss"], "#ff0000", 7)[1]["top"] == WEBMAP_SOLID["boss_map"]
