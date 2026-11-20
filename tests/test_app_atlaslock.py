"""app.atlaslock: a page change meant for one atlas is refused once another is open, checked under the session lock
in the same step as the edit (GPT audit: the server checked only as the request came in)."""

import json
import threading

import pytest

from grand_project.app.atlaslock import AtlasLock
from grand_project.app.events import StaleAtlas
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def opened(tmp_path):
    s = AtlasSession(settings={}, worker=False)
    path, pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    yield s, path, pts, tmp_path
    s.shutdown()


def test_an_edit_meant_for_the_atlas_before_is_refused(opened):
    s, path, pts, tmp = opened
    b = s.add_bookmark(pts[1][0], pts[1][1], "mine", "G")
    gen = s.generation  # (the page's request, made for this atlas)
    s.new_atlas(tmp / "other" / "atlas.json")  # another opened before it is handled
    with s._lock.expect(gen), pytest.raises(StaleAtlas):
        s.edit_bookmark(b, "renamed", "G", "")
    with s._lock.expect(gen), pytest.raises(StaleAtlas):
        s.set_landmark(pts[2][0], pts[2][1], "Tower")
    s.open_atlas(path)
    names = {x["name"] for x in s.atlas.bookmarks}
    assert "mine" in names and "renamed" not in names  # the first atlas: untouched


def test_an_edit_for_the_open_atlas_and_background_work_go_through(opened):
    s, path, pts, tmp = opened
    b = s.add_bookmark(pts[1][0], pts[1][1], "mine", "G")
    with s._lock.expect(s.generation):
        s.edit_bookmark(b, "renamed", "G", "")
    assert s.atlas.bookmarks[-1]["name"] == "renamed"
    s.edit_bookmark(b, "again", "G", "")  # (no expectation: the app's own work, which checks owns() itself)
    assert s.atlas.bookmarks[-1]["name"] == "again"


def test_the_lock_is_let_go_when_it_refuses():
    gen = [1]
    lock = AtlasLock(lambda: gen[0])
    gen[0] = 2
    with lock.expect(1), pytest.raises(StaleAtlas), lock:
        pass
    done = []
    t = threading.Thread(target=lambda: (lock.acquire(), done.append(1), lock.release()))
    t.start()
    t.join(2)
    assert done == [1]  # (another thread can take it: it wasn't kept)


def test_the_state_is_made_from_one_atlas_and_stamped_with_it(tmp_path):
    from grand_project.app.server import AppServer
    from tests.test_app_server import call

    path, pts, _img = make_atlas(tmp_path)
    s = AtlasSession(settings={}, worker=False)
    s.open_atlas(path)
    srv = AppServer(s, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        real = s.map_info
        switched = []

        def map_info_switching():
            if not switched:  # another atlas opens while the first answer is put together
                switched.append(1)
                s.new_atlas(tmp_path / "other" / "atlas.json")
            return real()

        s.map_info = map_info_switching
        status, headers, body = call(srv, "/api/state")
        st = json.loads(body)
        assert status == 200 and headers["X-Atlas-Gen"] == str(s.generation)
        assert st["atlas"]["path"].endswith(str(tmp_path / "other" / "atlas.json").split("\\")[-1])
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()
        s.shutdown()


def test_letting_go_frees_every_level_and_takes_them_back():
    # (GPT audit: a question asked while the lock was held twice let go of one level only)
    lock = AtlasLock(lambda: 1)
    took = []
    with lock, lock, lock.let_go():
        t = threading.Thread(target=lambda: (lock.acquire(), took.append(1), lock.release()))
        t.start()
        t.join(2)
        assert took == [1]  # (another thread got it while let go)
    assert not lock._is_owned()  # (both levels taken back, then both let go by the with blocks)
