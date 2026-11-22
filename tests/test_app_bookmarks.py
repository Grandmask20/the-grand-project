"""Bookmarks and their groups (app.bookmarks: the AtlasSession part); the basics are in test_app_session.py."""

from __future__ import annotations

import pytest

from grand_project import core
from grand_project.app.bookmarks import bm_group
from grand_project.app.events import StaleAtlas
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


def test_a_hidden_group_stays_hidden_when_renamed_and_an_empty_one_can_be_deleted(opened):
    s, _path, pts = opened
    s.new_group("Later")
    s.toggle_group("Later")
    s.rename_group("Later", "Tomorrow")  # (user: renaming showed it again)
    assert s.hidden_groups() == {"Tomorrow"}
    s.add_bookmark(pts[5][0], pts[5][1], "spot", "Kept")
    assert s.delete_groups(["Tomorrow", "Kept", "nope"]) == 1  # only an empty one: a group with bookmarks stays
    assert "Tomorrow" not in s.groups() and "Kept" in s.groups() and s.hidden_groups() == set()


def test_a_bookmark_keeps_its_id_when_another_is_deleted(opened):
    # ids were places in the list: deleting one moved the next into its place, and a page still holding that number
    # deleted or edited the wrong bookmark (CodeRabbit)
    s, path, pts = opened
    first = s.add_bookmark(pts[1][0], pts[1][1], "first")
    second = s.add_bookmark(pts[2][0], pts[2][1], "second")
    s.delete_bookmarks([first])
    assert s.info("bookmark", second)["name"] == "second"
    s.edit_bookmark(second, "renamed", "Boss", "")
    third = s.add_bookmark(pts[3][0], pts[3][1], "third")
    assert third not in (first, second)  # a deleted bookmark's id isn't given again
    with pytest.raises(ValueError):
        s.edit_bookmark(first, "gone", "Other", "")  # deleted: an error, not another bookmark
    saved = core.Atlas.load(path).bookmarks
    assert {b["uid"]: b["name"] for b in saved}[second] == "renamed"


def test_an_atlas_from_before_gets_ids_and_a_map_carries_its_bookmark(opened):
    s, _path, pts = opened
    i = s.add_bookmark(pts[4][0], pts[4][1], "here", "Boss", "a note")
    for b in s.atlas.bookmarks:
        b.pop("uid")  # as an atlas saved before ids
    ids = [u for u, _b in s.bookmarks_by_id()]
    assert len(set(ids)) == len(ids) == len(s.atlas.bookmarks)
    node = next(n for n in range(len(s.V["nodes"])) if s.info("node", n).get("bookmark") is not None)
    info = s.info("node", node)
    # the bookmark's own name, group and note come with the map (no guess while the list loads: CodeRabbit)
    assert info["bookmark_of"] == {
        "id": info["bookmark"],
        "name": "here",
        "group": "Boss",
        "note": "a note",
        "colour": "",
        "icon": "",
        "plain": False,
    }  # (and its look: an edit from the map keeps it)
    assert i >= 0


def test_a_deleted_id_is_not_given_again_after_a_restart(opened):
    # the "last id" counter started anew each session: the highest saved id deleted, the next add got it again
    # (CodeRabbit); it lives in the atlas now
    s, path, pts = opened
    before = {u for u, _b in s.bookmarks_by_id()}  # (the test atlas has one of its own)
    a = s.add_bookmark(pts[1][0], pts[1][1], "a")
    b = s.add_bookmark(pts[2][0], pts[2][1], "b")
    s.delete_bookmarks([b])
    # as after a restart, with the highest id gone from the file: only the saved counter knows it was given
    # (reopened before the deletion, the next id was worked out from b again: CodeRabbit)
    s.open_atlas(path)
    c = s.add_bookmark(pts[3][0], pts[3][1], "c")
    assert c not in (a, b)
    s.open_atlas(path)
    assert {u for u, _b in s.bookmarks_by_id()} == before | {a, c}


def test_showing_one_bookmark_of_a_hidden_group_after_a_deletion(opened):
    # it compared list places with the id: after a deletion it showed or hid the wrong ones (CodeRabbit)
    s, _path, pts = opened
    first = s.add_bookmark(pts[1][0], pts[1][1], "first", "G")
    keep = s.add_bookmark(pts[2][0], pts[2][1], "keep", "G")
    other = s.add_bookmark(pts[3][0], pts[3][1], "other", "G")
    s.delete_bookmarks([first])
    s.toggle_group("G")
    s.toggle_bookmark(keep)
    shown = {b["name"] for _u, b in s.bookmarks_by_id() if b["group"] == "G" and s.bookmark_shown(b)}
    assert shown == {"keep"} and other != keep


def test_a_saved_route_is_a_bookmark_with_its_maps_and_line_and_no_pin(opened):
    s, path, pts = opened
    line = [[pts[1][0], pts[1][1]], [pts[2][0], pts[2][1]], [pts[3][0], pts[3][1]]]
    leg = {"maps": line, "line": line}
    r = s.add_bookmark(pts[1][0], pts[1][1], "route1", "Routes", route={"from": 1, "to": 3, "maps": 2, "legs": [leg]})
    # no pin: the map it starts on can still be bookmarked, and a click there picks the map, not the route
    assert s.add_bookmark(pts[1][0], pts[1][1], "the map") >= 0
    assert s.pick(pts[1][0], pts[1][1], 1.0)[0] != "bookmark" or s.pick(pts[1][0], pts[1][1], 1.0)[1] != r
    item = next(b for g in s.bookmarks_payload()["groups"] for b in g["items"] if b["id"] == r)
    kept = [[round(x, 1), round(y, 1)] for x, y in line]
    assert item["route"] == {"from": 1, "to": 3, "maps": 2, "legs": [{"maps": kept, "line": kept}]}
    assert core.Atlas.load(path).bookmarks[-2]["route"]["to"] == 3  # kept in the atlas
    with pytest.raises(ValueError):  # one point: no route
        s.add_bookmark(0, 0, "bad", route={"from": 1, "to": 2, "legs": [{"maps": line, "line": [[0, 0]]}]})
    with pytest.raises(ValueError):  # no legs
        s.add_bookmark(0, 0, "bad", route={"from": 1, "to": 2, "legs": []})


def test_a_saved_routes_maps_change_with_a_branch(opened):
    # Add maps off the route's side makes a branch (user); the log says what it is now
    s, path, pts = opened
    main = [[pts[1][0], pts[1][1]], [pts[2][0], pts[2][1]]]
    branch = [[pts[2][0], pts[2][1]], [pts[4][0], pts[4][1]]]
    legs = [{"maps": main, "line": main}]
    r = s.add_bookmark(0, 0, "route1", route={"from": 1, "to": 2, "maps": 1, "legs": legs})
    s.set_bookmark_route(r, {"from": 1, "to": 2, "maps": 2, "legs": [*legs, {"maps": branch, "line": branch}]})
    assert len(core.Atlas.load(path).bookmarks[-1]["route"]["legs"]) == 2
    assert LOGGED in s.events.log_lines[-1]
    plain = s.add_bookmark(pts[5][0], pts[5][1], "a map")
    with pytest.raises(ValueError):  # not a route
        s.set_bookmark_route(plain, {"from": 1, "to": 2, "legs": legs})


LOGGED = "Route route1 changed: map #1 to map #2, 2 maps, 1 branch"


def test_folded_groups_are_kept_per_atlas_and_follow_a_rename(opened):
    # (user: Fold all was forgotten after a reload)
    s, path, pts = opened
    s.add_bookmark(pts[1][0], pts[1][1], "a", "G")
    s.add_bookmark(pts[2][0], pts[2][1], "b", "H")
    s.fold_groups(["G", "H"], True)
    s.fold_groups(["H"], False)
    assert {g["name"]: g["folded"] for g in s.bookmarks_payload()["groups"]}["G"] is True
    assert s.settings["folded_groups"][str(path)] == ["G"]  # kept in the settings, saved
    s.rename_group("G", "G2")
    folded = {g["name"]: g["folded"] for g in s.bookmarks_payload()["groups"]}
    assert folded["G2"] is True and folded["H"] is False and "G" not in folded
    assert any(line.endswith("Folded bookmark group(s): G, H") for line in s.events.log_lines)


def test_a_route_change_made_for_another_atlas_is_refused(opened):
    # (another atlas opened between the page's request and its change: it got the route, CodeRabbit)
    s, path, pts = opened
    main = [[pts[1][0], pts[1][1]], [pts[2][0], pts[2][1]]]
    legs = [{"maps": main, "line": main}]
    r = s.add_bookmark(0, 0, "route1", route={"from": 1, "to": 2, "maps": 1, "legs": legs})
    with pytest.raises(StaleAtlas):
        s.set_bookmark_route(r, {"from": 1, "to": 2, "maps": 1, "legs": legs}, gen=s.generation + 1)
    s.set_bookmark_route(r, {"from": 1, "to": 2, "maps": 1, "legs": legs}, gen=s.generation)


def test_a_bookmarks_look_is_kept_changed_and_cleared(opened):
    s, path, pts = opened
    i = s.add_bookmark(pts[3][0], pts[3][1], "boss", "Run", colour="#FF0000", icon="Breach")
    b = s._bookmark(i)
    assert (b["colour"], b["icon"]) == ("#ff0000", "Breach")
    s.edit_bookmark(i, "boss", "Run", "")  # an edit that doesn't send its look keeps it
    assert (s._bookmark(i)["colour"], s._bookmark(i)["icon"]) == ("#ff0000", "Breach")
    s.edit_bookmark(i, "boss", "Run", "", colour="", icon="Ritual")  # "": none of its own
    assert "colour" not in s._bookmark(i) and s._bookmark(i)["icon"] == "Ritual"
    assert core.Atlas.load(path).bookmarks[-1]["icon"] == "Ritual"  # saved
    row = next(b for g in s.bookmarks_payload()["groups"] for b in g["items"] if b["id"] == i)
    assert row["icon"] == "Ritual" and "colour" not in row
    for bad in ({"colour": "red"}, {"colour": "#12345"}, {"icon": "x" * 200}):
        with pytest.raises(ValueError):
            s.edit_bookmark(i, "boss", "Run", "", **bad)
    assert s._bookmark(i)["icon"] == "Ritual"  # (a bad look changes nothing)


def test_a_groups_look_is_saved_follows_a_rename_and_goes(opened):
    s, path, pts = opened
    s.add_bookmark(pts[3][0], pts[3][1], "boss", "Run")
    s.style_group("Run", "#00ff00", "Delirium")
    group = next(g for g in s.bookmarks_payload()["groups"] if g["name"] == "Run")
    assert (group["colour"], group["icon"]) == ("#00ff00", "Delirium")
    assert core.Atlas.load(path).group_looks == {"Run": {"colour": "#00ff00", "icon": "Delirium"}}
    s.rename_group("Run", "Daily")
    assert s.atlas.group_looks == {"Daily": {"colour": "#00ff00", "icon": "Delirium"}}
    s.style_group("Daily", "", "")
    assert s.atlas.group_looks == {}
    with pytest.raises(ValueError):
        s.style_group("No such group", "#00ff00", "")


def test_a_look_is_a_hand_edit_undo_keeps():
    assert "group_looks" in core.Atlas.HAND_EDITS and "group_looks" in core.Atlas.SAVED


def test_a_gone_groups_look_goes_with_it(opened):
    s, _path, pts = opened
    i = s.add_bookmark(pts[3][0], pts[3][1], "boss", "Run")
    s.style_group("Run", "#00ff00", "")
    s.move_bookmarks([i], "Daily")  # its last bookmark left: the group is gone, and its look
    assert "Run" not in s.groups() and s.atlas.group_looks == {}
    s.new_group("Empty")
    s.style_group("Empty", "#0000ff", "")
    assert s.delete_groups(["Empty"]) == 1 and s.atlas.group_looks == {}


def test_an_icon_can_have_no_border_and_a_symbol_is_an_icon(opened):
    s, _path, pts = opened
    i = s.add_bookmark(pts[3][0], pts[3][1], "boss", "Run", icon="Breach", plain=True)
    assert s._bookmark(i)["plain"] is True
    s.edit_bookmark(i, "boss", "Run", "")  # (kept when the edit doesn't say)
    assert s._bookmark(i)["plain"] is True
    s.edit_bookmark(i, "boss", "Run", "", icon="sym:triangle", plain=False)
    assert s._bookmark(i)["icon"] == "sym:triangle" and "plain" not in s._bookmark(i)
    s.edit_bookmark(i, "boss", "Run", "", icon="", plain=True)  # no icon: nothing to draw without a ring
    assert "plain" not in s._bookmark(i)
    s.style_group("Run", "", "Ritual", plain=True)
    assert s.atlas.group_looks["Run"] == {"icon": "Ritual", "plain": True}
    s.style_group("Run", "#ff0000", "", plain=True)
    assert s.atlas.group_looks["Run"] == {"colour": "#ff0000"}


def test_a_click_finds_a_pin_where_it_is_drawn(opened):
    s, _path, pts = opened
    x, y = pts[3]
    i = s.add_bookmark(x, y, "boss", "Run")
    # on the icon row (the default): above its map, the map itself still clickable
    assert s.pick(x, y - 24, 1.0) == ("bookmark", i)
    assert s.pick(x, y, 1.0) == ("node", 3)
    # on the map node: the pin covers its map
    s.settings.setdefault("style", {})["bookmark_at"] = "map node"
    assert s.pick(x, y, 1.0) == ("bookmark", i)
