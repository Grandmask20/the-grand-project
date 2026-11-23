"""Friends' atlases from live sharing (app.friends.FriendsMixin, through the session): sent whole, kept, opened
read-only in the real map with the friend's view."""

import pytest

from grand_project import paths as rc_paths
from grand_project.app.friends import unpack_file
from grand_project.app.session import AtlasSession
from tests.test_app_session import points
from tests.webmap_data import make_atlas


@pytest.fixture
def friends(tmp_path, monkeypatch):
    """A friend sharing their atlas (they), and you, with your own atlas open (me)."""
    monkeypatch.setattr(rc_paths, "USER_DATA", tmp_path / "user_data")
    they, me = AtlasSession(settings={}, worker=False), AtlasSession(settings={}, worker=False)
    (tmp_path / "theirs").mkdir()
    (tmp_path / "mine").mkdir()
    theirs, _pts, _img = make_atlas(tmp_path / "theirs")
    mine, _pts, _img = make_atlas(tmp_path / "mine")
    they.open_atlas(theirs)
    me.open_atlas(mine)
    yield they, me, mine
    they.shutdown()
    me.shutdown()


def test_their_atlas_comes_whole_and_opens_as_they_see_it(friends):
    they, me, mine = friends
    they.set_ui_settings({"hidden_types": ["Ritual"], "layers": {"Removed": True}})
    path = me.save_friend("Nyx", they.share_payload()["file"], {"x": 1.0, "y": 2.0, "node": 3})
    me.open_atlas(path)
    assert me.friend_open() == "Nyx"
    assert me.atlas_summary()["name"] == "Nyx's atlas" and me.atlas_summary()["friend"] == "Nyx"
    # their maps where they have them, in the same frame (no ground picture: a blank one of their map image's frame)
    assert sorted(points(me, "maps")) == sorted(points(they, "maps"))
    assert (me.grid.x0, me.grid.y0) == (they.grid.x0, they.grid.y0)
    assert me.terrain[0].max() == 0
    # their view: their filters and position
    view = me.ui_settings()
    assert view["hidden_types"] == ["Ritual"] and view["layers"]["Removed"]
    assert view["ui"]["player"] == {"x": 1.0, "y": 2.0, "node": 3, "atlas": str(me.path)}
    assert list(points(me, "removed")) == [15]
    # yours, back with your atlas
    me.open_atlas(mine)
    assert me.friend_open() is None and me.ui_settings()["hidden_types"] == []


def test_a_friends_atlas_is_read_only_and_never_one_of_yours(friends):
    they, me, mine = friends
    path = me.save_friend("Nyx", they.share_payload()["file"])
    me.open_atlas(path)
    assert me.friend_refuses("POST", "/api/landmark") and me.friend_refuses("POST", "/api/bookmarks")
    assert not me.friend_refuses("PATCH", "/api/settings") and not me.friend_refuses("GET", "/api/bookmarks")
    assert not me.friend_refuses("POST", "/api/atlas/open")
    before = (me.path.stat().st_mtime_ns, me.path.read_text())
    me.save()
    assert (me.path.stat().st_mtime_ns, me.path.read_text()) == before
    assert me.settings["last_atlas"] == str(mine)  # (yours opens at start, and is the one to go back to)
    assert all(not a["json"].startswith(str(rc_paths.USER_DATA)) for a in me.known_atlases())
    me.open_atlas(mine)
    assert not me.friend_refuses("POST", "/api/landmark")


def test_changing_their_view_is_for_this_visit_only(friends):
    they, me, mine = friends
    me.set_ui_settings({"multi_only": True, "ui": {"side_width": 300}})
    path = me.save_friend("Nyx", they.share_payload()["file"])
    me.open_atlas(path)
    assert me.ui_settings()["multi_only"] is False  # (theirs)
    me.set_ui_settings({"near_only": True, "ui": {"side_width": 420}})
    assert me.ui_settings()["near_only"] is True
    assert "near_only" not in me.settings or me.settings["near_only"] is False  # (yours untouched)
    assert me.settings["ui"]["side_width"] == 420  # (the page's own: yours, kept)
    me.open_atlas(mine)
    assert me.ui_settings()["multi_only"] is True and me.ui_settings()["near_only"] is False


def test_their_atlas_keeps_coming_the_open_one_read_again(friends):
    they, me, _mine = friends
    path = me.save_friend("Nyx", they.share_payload()["file"])
    me.open_atlas(path)
    gen = me.generation
    with they._lock:
        they.atlas.final["nodes"][3]["status"] = "removed"
    they.rebuild_model()
    me.save_friend("Nyx", they.share_payload()["file"])
    assert 3 not in points(me, "maps") and me.generation == gen  # (in place: the same atlas, the map stays)
    me.set_friend_player("Nyx", {"x": 5.0, "y": 6.0, "node": 1})
    assert me.ui_settings()["ui"]["player"]["node"] == 1


def test_what_is_sent_and_what_is_listed(friends):
    they, me, mine = friends
    data = unpack_file(they.share_payload()["file"])
    assert all("/" not in f["path"] and "\\\\" not in f["path"] for f in data["atlas"]["frames"])  # (names only)
    assert set(data["map"]) == {"origin", "width", "height"}
    path = me.save_friend("Nyx / the 2nd", they.share_payload()["file"])
    listed = me.friends_payload()
    assert listed["own"] == str(mine)
    assert listed["friends"] == [{"name": "Nyx / the 2nd", "json": path, "updated": listed["friends"][0]["updated"],
                                  "open": False, "maps": 15}]  # fmt: skip
    with pytest.raises(ValueError):
        me.save_friend("Nyx", "zbroken")
    assert len(me.friends_payload()["friends"]) == 1  # (nothing kept of the broken one)
