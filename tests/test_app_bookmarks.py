"""Bookmarks and their groups (app.bookmarks: the AtlasSession part); the basics are in test_app_session.py."""

from __future__ import annotations

import pytest

from grand_project import core
from grand_project.app.bookmarks import bm_group
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def session():
    s = AtlasSession(settings={}, worker=False)
    yield s
    s.shutdown()


@pytest.fixture
def opened(session, tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    return session, path, pts


def test_group_of_a_bookmark_reads_the_old_name_too():
    assert bm_group({"group": "Boss"}) == "Boss"
    assert bm_group({"category": "Farm"}) == "Farm"  # older atlases
    assert bm_group({}) == "Other"


def test_no_bookmark_without_an_atlas_or_a_name(session, opened):
    s, _path, pts = opened
    with pytest.raises(ValueError):
        s.add_bookmark(pts[2][0], pts[2][1], "   ")
    with pytest.raises(ValueError):
        s.edit_bookmark(0, "", "g", "")
    with pytest.raises(ValueError):
        s.edit_bookmark(99, "x", "g", "")  # no such bookmark
    empty = AtlasSession(settings={}, worker=False)
    try:
        with pytest.raises(ValueError):
            empty.add_bookmark(0, 0, "x")
        assert empty.delete_bookmarks([0]) == [] and empty.groups() == []
    finally:
        empty.shutdown()


def test_bookmark_all_skips_spots_already_bookmarked(opened):
    s, path, _pts = opened
    before = len(s.atlas.bookmarks)
    items = [("node", 1), ("node", 3), ("node", 3), ("bookmark", 0)]
    added, skipped = s.bookmark_items(items, "Run 1")
    assert (added, skipped) == (2, 1)
    assert len(core.Atlas.load(path).bookmarks) == before + 2  # saved
    assert "Run 1" in s.groups()


def test_default_names_for_maps_icons_and_landmarks(opened):
    s, _path, _pts = opened
    name, group = s.default_name("node", 1)
    assert name and group in ("Boss", "Abyss", "Delirium", "Unique", "Breach", "Other")
    name, group = s.default_name("landmark", 0)
    assert name and group


def test_groups_new_renamed_and_moved(opened):
    s, path, pts = opened
    s.new_group("  Later  ")
    s.new_group("   ")  # blank: none
    assert "Later" in s.groups()
    i = s.add_bookmark(pts[5][0], pts[5][1], "spot", "Later")
    s.rename_group("Later", "Tomorrow")
    s.rename_group("Tomorrow", "  ")  # blank: kept
    assert "Tomorrow" in s.groups() and "Later" not in s.groups()
    s.move_bookmarks([i], "")  # blank: Other
    assert bm_group(core.Atlas.load(path).bookmarks[i]) == "Other"


def test_hidden_groups_are_kept_per_atlas(opened):
    s, path, _pts = opened
    s.toggle_group("g")
    assert s.hidden_groups() == {"g"} and s.settings["hidden_groups"] == {str(path): ["g"]}
    s.toggle_group("g")
    assert s.hidden_groups() == set()


def test_bookmark_at_finds_the_nearest_on_the_spot(opened):
    s, _path, pts = opened
    i = s.add_bookmark(pts[4][0], pts[4][1], "here")
    assert s.bookmark_at(pts[4][0] + 1, pts[4][1]) == i
    assert s.bookmark_at(pts[4][0] + 10_000, pts[4][1]) is None
