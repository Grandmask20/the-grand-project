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
