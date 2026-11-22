"""Maps deleted or added by hand (app.edits edit_map, app.model apply_map_edits): ghost maps the detector made, maps
it missed (user)."""

from __future__ import annotations

import pytest

from grand_project import core
from grand_project.app.model import apply_map_edits
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def opened(tmp_path):
    s = AtlasSession(settings={}, worker=False)
    path, pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    yield s, path, pts
    s.shutdown()


def node(i, x, y, status="confirmed"):
    return {"id": i, "x": x, "y": y, "status": status, "icons": []}


def test_a_removal_takes_the_nearest_live_map_and_the_icons_on_it():
    nodes = [node(0, 0, 0), node(1, 200, 0), node(2, 10, 0, "removed")]
    icons = [{"x": 0, "y": -20, "bx": 0, "by": 0}, {"x": 200, "y": -20, "bx": 200, "by": 0}]
    out, kept = apply_map_edits(nodes, icons, [{"x": 3, "y": 2, "op": "remove"}])
    assert out[0]["status"] == "removed" and out[0]["why"] == "removed by you"
    assert nodes[0]["status"] == "confirmed"  # (the atlas's own lists aren't changed)
    assert kept == [icons[1]]  # its icon went with it
    out, _ = apply_map_edits(nodes, icons, [{"x": 100, "y": 0, "op": "remove"}])
    assert [n["status"] for n in out] == ["confirmed", "confirmed", "removed"]  # nothing that close: nothing goes


def test_an_addition_puts_a_map_there_unless_one_is_found_since():
    nodes = [node(0, 0, 0)]
    out, _ = apply_map_edits(nodes, [], [{"x": 300, "y": 40, "op": "add"}])
    assert out[1]["id"] == 1 and (out[1]["x"], out[1]["y"]) == (300.0, 40.0) and out[1]["origin"] == "by you"
    out, _ = apply_map_edits(nodes, [], [{"x": 5, "y": 5, "op": "add"}])
    assert len(out) == 1  # a map stands there already


def test_delete_a_map_and_bring_it_back(opened):
    s, path, pts = opened
    x, y = pts[3]
    s.edit_map(x + 4, y - 3, "remove")
    assert s.V["nodes"][3]["status"] == "removed"
    assert core.Atlas.load(path).map_edits == [{"x": round(x, 1), "y": round(y, 1), "op": "remove"}]  # saved
    assert s.info("node", 3)["removed"] and "deleted by you" in s.info("node", 3)["lines"]
    assert s.search("#3")["results"] == []  # (a deleted map isn't found: it isn't drawn; self review)
    with pytest.raises(ValueError):
        s.edit_map(x, y, "remove")  # no map there any more
    s.edit_map(x, y, "add")  # adding where you deleted one brings it back
    assert s.V["nodes"][3]["status"] != "removed" and s.atlas.map_edits == []


def test_add_a_map_with_a_landmark_and_delete_it_again(opened):
    s, _path, _pts = opened
    before = len(s.V["nodes"])
    s.edit_map(2000, 2000, "add", "Hall")
    assert len(s.V["nodes"]) == before + 1 and s.V["nodes"][-1]["origin"] == "by you"
    assert any(lm["kind"] == "Hall" and lm["x"] == 2000 for lm in s.V["landmarks"])
    assert s.info("node", before)["lines"][0] == "added by you (no screenshot found it)"
    assert s.info("node", before)["added"] and not s.info("node", 3)["added"]
    hall = next(i for i, lm in enumerate(s.V["landmarks"]) if lm["kind"] == "Hall" and lm["x"] == 2000)
    assert s._landmark_lines(hall)[0] == "added by you"  # (not "found in 1 of 1 screenshot(s)")
    assert "  added by you" in s.info("landmark", hall)["lines"]  # (shown under its map)
    with pytest.raises(ValueError):
        s.edit_map(2005, 2000, "add")  # one there already
    s.edit_map(2000, 2000, "remove")  # an added map deleted: its edit goes
    assert len(s.V["nodes"]) == before and s.atlas.map_edits == []


def test_a_deleted_maps_landmark_goes_with_it(opened):
    s, _path, pts = opened
    x, y = pts[6]
    s.set_landmark(x, y, "City", "map")  # a City put on map 6 by hand: its edit just goes
    s.edit_map(x, y, "remove")
    assert not [lm for lm in s.V["landmarks"] if lm["kind"] == "City" and not lm["status"].startswith("removed")]
    assert s.atlas.landmark_edits == []  # (no delete left at its spot to reach a landmark next to it)


def test_a_detected_landmark_on_a_deleted_map_is_marked_deleted(tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    at = core.Atlas.load(path)
    at.final["landmarks"].append({"kind": "Hall", "x": pts[8][0], "y": pts[8][1], "status": "kept"})
    at.save(path)
    s = AtlasSession(settings={}, worker=False)
    try:
        s.open_atlas(path)
        assert any(lm["kind"] == "Hall" for lm in s.V["landmarks"])
        s.edit_map(pts[8][0], pts[8][1], "remove")
        assert s.atlas.landmark_edits == [
            {"x": round(pts[8][0], 1), "y": round(pts[8][1], 1), "kind": "", "on": "landmark"}
        ]
        hall = next(lm for lm in s.V["landmarks"] if lm["kind"] == "Hall")
        assert hall["status"].startswith("removed")
    finally:
        s.shutdown()


def test_a_map_brought_back_brings_its_landmark_back(tmp_path):
    """A deleted map's landmark is deleted with it; bringing the map back brings the landmark back as it was, a
    detected one and one put there by hand (it stayed deleted: self review)."""
    path, pts, _img = make_atlas(tmp_path)
    at = core.Atlas.load(path)
    at.final["landmarks"].append({"kind": "Hall", "x": pts[8][0], "y": pts[8][1], "status": "kept"})
    at.save(path)
    s = AtlasSession(settings={}, worker=False)
    try:
        s.open_atlas(path)
        x, y = pts[8]
        s.edit_map(x, y, "remove")
        s.edit_map(x, y, "add")
        hall = next(lm for lm in s.V["landmarks"] if lm["kind"] == "Hall")
        assert hall["status"] == "kept" and s.atlas.landmark_edits == [] and s.atlas.map_edits == []
        # one put on a map by hand
        x, y = pts[6]
        s.set_landmark(x, y, "City", "map")
        city = list(s.atlas.landmark_edits)
        s.edit_map(x, y, "remove")
        assert s.atlas.landmark_edits == []
        s.edit_map(x, y, "add")
        assert s.atlas.landmark_edits == city
        assert any(lm["kind"] == "City" and lm["status"] == "kept" for lm in s.V["landmarks"])
        assert core.Atlas.load(path).landmark_edits == city  # (saved)
    finally:
        s.shutdown()


def test_delete_takes_the_nearest_map(opened):
    """Two maps within reach of the click: the nearest goes, not the first found (CodeRabbit)."""
    s, _path, pts = opened
    x, y = pts[3]
    s.V["nodes"].append({**s.V["nodes"][3], "id": len(s.V["nodes"]), "x": x + 14, "y": y})  # a ghost beside map 3
    s.edit_map(x + 12, y, "remove")
    assert s.atlas.map_edits == [{"x": round(x + 14, 1), "y": round(y, 1), "op": "remove"}]


def test_a_detected_landmark_whose_kind_you_changed_goes_with_its_map(tmp_path):
    """A Hall's map deleted, brought back as a City, deleted again: the Hall goes too (it stayed: CodeRabbit)."""
    path, pts, _img = make_atlas(tmp_path)
    at = core.Atlas.load(path)
    at.final["landmarks"].append({"kind": "Hall", "x": pts[8][0], "y": pts[8][1], "status": "kept"})
    at.save(path)
    s = AtlasSession(settings={}, worker=False)
    try:
        s.open_atlas(path)
        x, y = pts[8]
        here = lambda: [  # noqa: E731
            lm["kind"]
            for lm in s.V["landmarks"]
            if not lm["status"].startswith("removed") and abs(lm["x"] - x) < 30 and abs(lm["y"] - y) < 30
        ]
        s.edit_map(x, y, "remove")
        s.edit_map(x, y, "add", "City")
        assert here() == ["City"]
        s.edit_map(x, y, "remove")
        assert here() == []
    finally:
        s.shutdown()


def test_a_map_you_added_that_a_check_found_since_can_be_deleted(tmp_path):
    """You added a map; a later check detected it too (yours is then not drawn). Deleting it deletes the detected one
    (only your add went, and the detected map stayed: CodeRabbit)."""
    path, pts, _img = make_atlas(tmp_path)
    at = core.Atlas.load(path)
    spot = (2000.0, 2000.0)
    at.map_edits = [{"x": spot[0], "y": spot[1], "op": "add"}]
    at.final["nodes"].append({**at.final["nodes"][3], "id": len(at.final["nodes"]), "x": spot[0], "y": spot[1]})
    at.save(path)
    s = AtlasSession(settings={}, worker=False)
    try:
        s.open_atlas(path)
        shown = [n for n in s.V["nodes"] if n["status"] != "removed" and (n["x"], n["y"]) == spot]
        assert len(shown) == 1 and shown[0].get("origin") == "detected"
        s.edit_map(*spot, "remove")
        assert s.atlas.map_edits == [{"x": spot[0], "y": spot[1], "op": "remove"}]
        assert not [n for n in s.V["nodes"] if n["status"] != "removed" and (n["x"], n["y"]) == spot]
    finally:
        s.shutdown()


def test_bad_map_edits_are_refused(opened):
    s, _path, pts = opened
    for args in (("move",), ("add", "Castle"), ("remove", "City")):
        with pytest.raises(ValueError):
            s.edit_map(pts[1][0], pts[1][1], *args)


def test_map_edits_are_hand_edits_undo_keeps():
    assert "map_edits" in core.Atlas.HAND_EDITS and "map_edits" in core.Atlas.SAVED
