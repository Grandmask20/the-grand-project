"""Find, details, the screenshots of a spot and the route graph (app.query: the AtlasSession part)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def opened(tmp_path):
    s = AtlasSession(settings={}, worker=False)
    path, pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    yield s, path, pts
    s.shutdown()


def test_search_needs_an_atlas_and_text(tmp_path):
    s = AtlasSession(settings={}, worker=False)
    try:
        assert s.search("vaal") == {"results": []}
    finally:
        s.shutdown()


def test_search_coordinates_go_there(opened):
    s, _path, _pts = opened
    assert s.search("") == {"results": []}
    assert s.search(" 120, -45.5 ") == {"goto": [120.0, -45.5]}
    assert s.search("120 -45") == {"goto": [120.0, -45.0]}


def test_search_finds_bookmarks_landmarks_and_map_numbers(opened):
    s, _path, _pts = opened
    rows = s.search("farm")["results"]
    assert [(r["kind"], r["id"]) for r in rows] == [("bookmark", 0)]
    assert all({"label", "x", "y"} <= r.keys() for r in rows)
    assert [r["kind"] for r in s.search("vaal")["results"]] == ["landmark"]
    assert [(r["kind"], r["id"], r["label"]) for r in s.search("#3")["results"]] == [("node", 3, "Map #3")]
    assert s.search("#99999")["results"] == []  # no such map
    assert s.search("nothing like this")["results"] == []
    assert [r["id"] for r in s.search("map 3")["results"]] == [3]  # (as "#3")


def test_search_scores_each_icon_name_once(opened, monkeypatch):
    """Every map with the same icon: its name is scored once, not once per map (self review: thousands of maps)."""
    from grand_project.app import query
    from grand_project.app.icons import icon_name

    s, _path, _pts = opened
    for n in s.V["nodes"]:
        n["icons"] = ["Abyss"]
    calls = []
    real = query.find_score
    monkeypatch.setattr(query, "find_score", lambda q, name, more="": calls.append(name) or real(q, name, more))
    rows = s.search("abyss")["results"]
    assert {r["id"] for r in rows if r["kind"] == "node"} == {
        v for v, n in enumerate(s.V["nodes"]) if n["status"] != "removed"
    }
    assert calls.count(icon_name("Abyss")) == 1


def test_search_rows_are_named_as_the_page_names_them(opened):
    s, _path, _pts = opened
    farm = s.search("farm")["results"][0]
    assert (
        farm["label"] == "farm <here>" and farm["note"] and farm["map"] is None
    )  # (no "[bookmark]", its group under it)
    vaal = s.search("vaal")["results"][0]
    assert "seen" not in vaal["label"] and vaal["icon"]  # (its place picture)
    assert all({"icon", "map", "icons", "note", "bookmarked"} <= r.keys() for r in s.search("a")["results"])


def test_a_landmarks_row_has_its_map_and_its_icons(opened):
    s, _path, _pts = opened
    vaal = next(r for r in s.search("vaal")["results"] if r["kind"] == "landmark")
    v = next(k for k, n in enumerate(s.V["nodes"]) if n.get("icons"))
    s.D.setdefault("landmark_node", {})[vaal["id"]] = v  # (item_node has none for a landmark: CodeRabbit)
    row = next(r for r in s.search("vaal")["results"] if r["kind"] == "landmark")
    assert row["map"] == v and row["icons"] and row["note"].startswith(f"on map #{v}")


def test_find_score_is_loose_and_ranks():
    from grand_project.app.query import find_score

    assert find_score("abyss", "Abyss") > find_score("abyss", "Abyssal Depths") > find_score("abyss", "", "abyss")
    assert find_score("depths abys", "Abyssal Depths") is not None  # words in any order, each a word's start
    assert find_score("abysal", "Abyssal Depths") is not None  # a typo
    assert find_score("abydep", "Abyssal Depths") is not None  # letters in order
    assert find_score("tower", "Abyssal Depths") is None
    assert find_score("ab", "Lab") is not None and find_score("xb", "Lab") is None  # (short: as typed)
    assert find_score("東京", "東京") == 110 and find_score("東", "東京 farm") == 100  # any letters (CodeRabbit)
    assert find_score("!!", "boss !!") is not None and find_score("!!", "boss") is None  # punctuation as typed


def test_find_score_in_order_stops_at_a_matchs_reach():
    from grand_project.app.query import _in_order

    assert _in_order("abz", "a" * 10000) is None  # (a long note: each start scans 6 letters, not the rest)
    assert _in_order("abd", "xxabcdxx") == 40.0 and _in_order("abd", "a" + "x" * 10 + "bd") is None


def test_landmarks_as_the_map_shows_them(opened, tmp_path):
    s, _path, _pts = opened
    marks = s.landmarks()
    assert marks and all({"id", "x", "y", "kind", "label", "node"} <= m.keys() for m in marks)
    vaal = next(m for m in marks if m["label"].startswith("Vaal"))
    assert vaal["kind"] == "Vaal city" and vaal["label"] == "Vaal city"
    s.V["landmarks"][vaal["id"]]["status"] = "removed by you"
    assert vaal["id"] not in [m["id"] for m in s.landmarks()]  # (a removed one: not shown, not shared)
    assert AtlasSession(settings={}, worker=False).landmarks() == []  # (no atlas)


def test_type_list_and_list_of_one_type(opened):
    s, _path, pts = opened
    s.set_landmark(pts[6][0], pts[6][1], "Tower", on="map")
    sections = {sec["title"]: sec["rows"] for sec in s.types()["sections"]}
    places = {r["label"]: r for r in sections["Places"]}
    assert places["Tower"]["count"] == 1 and places["Tower"]["shown"]
    rows = s.list_type("Tower")
    assert [r["kind"] for r in rows] == ["landmark"]
    assert abs(rows[0]["x"] - pts[6][0]) < 50 and abs(rows[0]["y"] - pts[6][1]) < 50
    assert s.list_type("No such type") == []


def test_details_of_a_map(opened):
    s, _path, _pts = opened
    d = s.info("node", 1)
    assert isinstance(d, dict) and d


def test_route_graph_holds_shown_maps_and_their_paths(opened):
    s, _path, _pts = opened
    g = s.graph()
    ids = {n["id"] for n in g["nodes"]}
    assert ids and all({"x", "y", "icons", "status"} <= n.keys() for n in g["nodes"])
    assert all(e["a"] in ids and e["b"] in ids for e in g["edges"])
    assert any("line" in e for e in g["edges"])  # a bent path keeps its line


def test_screenshots_of_a_spot(opened, tmp_path):
    s, _path, pts = opened
    x, y = pts[1]
    found = s.sources(x, y)
    assert [f["name"] for f in found] == ["a"] and not found[0]["exists"]  # the test atlas has no picture yet
    assert s.screenshot_jpeg("a") is None
    cv2.imwrite(str(tmp_path / "a.png"), np.full((1080, 1920, 3), 120, np.uint8))
    assert s.sources(x, y)[0]["exists"]
    jpeg = s.screenshot_jpeg("a", width=480)
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (270, 480)
    assert s.screenshot_jpeg("missing") is None
    assert s.sources(10**7, 10**7) == []  # off every screenshot


def test_a_maps_details_name_its_connected_maps_and_their_paths(opened):
    s, _path, pts = opened
    info = s.info("node", 2)
    # paths 1-2, 2-3 and the Abyss link 2-7 (its own line: three points)
    assert info["connected"] == [1, 3, 7]
    assert len(info["links"]) == 3 and any(len(line) == 3 for line in info["links"])
    assert info["heading"] == "Map #2" and info["icons"] == [{"name": "Ritual", "label": "Ritual"}]
    assert "Ritual" in info["title"] and "Ritual" not in info["heading"]  # (the box shows the icons as pictures)
    assert s.info("node", 0)["connected"] == [1]  # (not the removed map 15: the map doesn't draw that path)


def test_a_crop_of_the_ground_is_for_its_atlas_only(opened):
    s, _path, pts = opened
    x, y = pts[0]
    data = s.crop_jpeg(x, y, s.generation)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (64, 64)
    assert s.crop_jpeg(x, y, s.generation + 1) is None  # asked for another atlas: none made
    assert s.crop_jpeg(-1e6, -1e6, s.generation) is None  # no ground there


def test_a_crop_is_cut_from_one_map_image(opened, monkeypatch):
    """A map image put in while a crop is cut (its grid and tiles changed, its version not yet: set_terrain's order):
    the crop still comes from the one map image it started on (it read the grid and the tiles at different moments:
    CodeRabbit)."""
    s, _path, pts = opened
    whole = s.crop_jpeg(*pts[0], s.generation)
    assert whole is not None
    s._tiles.clear()  # (each tile made again below, from the tiling the crop holds)
    real = s._tile_from

    def mid_change(*a, **k):
        s.grid, s._raster, s._sharp = None, None, None  # (the new map image half put in)
        return real(*a, **k)

    monkeypatch.setattr(s, "_tile_from", mid_change)
    assert s.crop_jpeg(*pts[0], s.generation) == whole


def test_crops_are_not_kept_by_the_browser(opened):
    """Their address starts over with each run of the app: another atlas's could match it later (CodeRabbit)."""
    from grand_project.app import server

    sent = []

    class FakeHandler:
        S = opened[0]

        def _bytes(self, data, ctype, cache=True):
            sent.append(cache)

    x, y = opened[2][0]
    server.Handler.get_crop(FakeHandler(), {"x": [str(x)], "y": [str(y)], "g": [str(opened[0].generation)]})
    assert sent == [False]


def test_a_rows_picture_is_cut_at_its_map_not_at_the_icon(opened):
    s, _path, pts = opened
    rows = s.search("ritual")["results"]
    on_map = [r for r in rows if r["kind"] == "node"]
    assert on_map and on_map[0]["at"] is None  # (a map: where it is)
    vaal = next(r for r in s.search("vaal")["results"] if r["kind"] == "landmark")
    v = next(k for k, n in enumerate(s.V["nodes"]) if not n.get("tower") and n["status"] != "removed")
    s.D.setdefault("landmark_node", {})[vaal["id"]] = v
    row = next(r for r in s.search("vaal")["results"] if r["kind"] == "landmark")
    assert row["at"] == [s.V["nodes"][v]["x"], s.V["nodes"][v]["y"]]
    s.V["nodes"][v]["tower"] = True  # on a tower: cut where it is (user)
    row = next(r for r in s.search("vaal")["results"] if r["kind"] == "landmark")
    assert row["at"] is None
