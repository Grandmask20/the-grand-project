"""Two atlases, one app: work started for atlas A never lands in atlas B (the atlas owner rework).

Every background job remembers the atlas generation it started under and applies its result only while that atlas is
still open: the map image build, Fix seams, the locked stronghold search, the quiet PNG export, queued screenshot jobs,
auto-add, the replay's fog and the times-seen picture. The page's changes carry the generation too (X-Atlas-Gen), so
one made for A (a bookmark id, a lasso, a placement) is refused once B is open. Each test starts work for A, switches
to B, lets the work finish and checks that B (its map image, its file, its jobs) is untouched.
"""

import copy
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project import cities, core
from grand_project.app import adding as adding_mod
from grand_project.app import mapimage, replay_data
from grand_project.app import server as S
from grand_project.app.server import AppServer
from grand_project.app.session import AtlasSession
from tests.test_app_server import call
from tests.test_app_session import timed_atlas
from tests.webmap_data import make_atlas


def wait_until(cond, timeout: float = 10.0) -> bool:
    """Wait for a background thread's result."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture
def quiet_locks(monkeypatch):
    """The locked stronghold search finds nothing (it reads screenshots these atlases don't have)."""
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])


@pytest.fixture
def session(quiet_locks):
    s = AtlasSession(settings={}, worker=False)
    yield s
    s.shutdown()


@pytest.fixture
def two(tmp_path):
    """Atlas A and atlas B: B has another map image (inverted), one bookmark of its own and no icons."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _pts, img = make_atlas(tmp_path / "a")
    b, _pts, _img = make_atlas(tmp_path / "b")
    at = core.Atlas.load(b)
    at.bookmarks = [{"name": "only in B", "group": "g", "note": "", "x": 10.0, "y": 10.0}]
    at.save(b)
    png, _npz = core.map_image_files(b)
    core.write_png(png, 255 - img, "map image")
    return a, b


def bookmark_names(s: AtlasSession) -> list[str]:
    return [b["name"] for g in s.bookmarks_payload()["groups"] for b in g["items"]]


def file_of(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the basics: what each atlas shows


def test_switching_bumps_the_generation_and_shows_only_the_open_atlas(session, two):
    a, b = two
    session.open_atlas(a)
    g_a, key_a = session.generation, session.map_info()["tile_key"]
    terrain_a = session.terrain[0].copy()
    assert session.state()["generation"] == g_a
    session.add_debug_mark("wrong map", "not a map", "", maps=[3])

    session.open_atlas(b)
    assert session.generation == g_a + 1 and session.map_info()["tile_key"] != key_a  # every tile fetched again
    assert not np.array_equal(session.terrain[0], terrain_a)  # B's own map image
    assert bookmark_names(session) == ["only in B"]
    assert session.debug_marks() == []  # A's debug mark stays in A

    session.open_atlas(a)  # and back: A as it was
    assert np.array_equal(session.terrain[0], terrain_a)
    assert bookmark_names(session) == ["farm <here>"]
    assert len(session.debug_marks()) == 1

    g = session.generation
    session.open_atlas(a)  # the same file again: a new generation too (the atlas is read again)
    assert session.generation == g + 1


def test_new_and_close_are_new_generations_too(session, two, tmp_path):
    a, _b = two
    session.open_atlas(a)
    g = session.generation
    session.new_atlas(tmp_path / "c")
    assert session.generation == g + 1 and session.terrain is None and session.map_info() is None
    session.close()
    assert session.generation == g + 2 and session.atlas is None


def test_no_switch_while_screenshots_are_being_added(session, two):
    a, b = two
    session.open_atlas(a)
    session._jobs.put(([], "undo", session.generation))  # a job waiting for the worker
    try:
        for switch in (lambda: session.open_atlas(b), lambda: session.new_atlas(b.parent / "new"), session.close):
            with pytest.raises(ValueError, match="being added"):
                switch()
        assert session.path == a
    finally:
        session._jobs.get()
        session._jobs.task_done()


# ------------------------------------------------------------------ background work started for A


def test_a_map_image_built_for_a_is_dropped_once_b_is_open(session, two, monkeypatch):
    a, b = two
    for f in core.map_image_files(a):  # A has no cached map image: it is built in the background
        f.unlink()
    release, started = threading.Event(), threading.Event()

    def slow_composite(self, **kw):
        started.set()
        release.wait(10)
        return np.full((540, 1030, 3), 7, np.uint8), (0.0, 0.0, 1.0), np.ones((540, 1030), np.float32)

    monkeypatch.setattr(core.Atlas, "composite", slow_composite)
    shown = []
    real = session.set_terrain
    monkeypatch.setattr(session, "set_terrain", lambda *a_, **kw: shown.append((kw.get("gen"), real(*a_, **kw))))
    session.open_atlas(a)
    assert started.wait(5)
    g_a = session.generation
    b_png = core.map_image_files(b)[0].read_bytes()
    session.open_atlas(b)  # B's cached map image is shown at once
    terrain_b = session.terrain[0].copy()
    release.set()
    assert wait_until(lambda: any(g == g_a for g, _ok in shown))
    assert [ok for g, ok in shown if g == g_a] == [False]  # A's map image was dropped...
    assert np.array_equal(session.terrain[0], terrain_b)  # ...B still shows its own
    assert core.map_image_files(b)[0].read_bytes() == b_png  # B's cache was not overwritten with A's picture
    assert not core.map_image_files(a)[0].exists()  # nor A's written from it (built again next time)


class FakeSeams:
    """Fix seams' process, finishing when told (or stopped)."""

    release = threading.Event()
    result = None

    def __init__(self, args, **kw):
        self.out = args[4]
        self.returncode = None
        self.stdout = self._lines()

    def _lines(self):
        FakeSeams.release.wait(10)
        yield "done\n"

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        FakeSeams.release.wait(timeout or 10)
        if self.returncode is None:
            canvas, weight = FakeSeams.result
            np.savez(self.out, canvas=canvas, weight=weight, labels=np.zeros(weight.shape, np.int16),
                     origin=np.array([0.0, 0.0, 1.0]), names=np.array(["a"]))  # fmt: skip
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -15
        FakeSeams.release.set()


@pytest.fixture
def fake_seams(monkeypatch):
    FakeSeams.release = threading.Event()
    FakeSeams.result = (np.full((540, 1030, 3), 9, np.uint8), np.ones((540, 1030), np.float32))
    monkeypatch.setattr(mapimage.subprocess, "Popen", FakeSeams)
    return FakeSeams


@pytest.mark.parametrize("stopped", [True, False], ids=["stopped-on-switch", "finished-after-switch"])
def test_fix_seams_for_a_never_shows_in_b(session, two, fake_seams, monkeypatch, stopped):
    a, b = two
    session.open_atlas(a)
    session.fix_seams()
    assert session.seams_running()
    if not stopped:  # it finishes on its own just after the switch (as if it couldn't be stopped in time)
        monkeypatch.setattr(session, "stop_seams", lambda: None)
        monkeypatch.setattr(session, "seams_running", lambda: False)
    b_png = core.map_image_files(b)[0].read_bytes()
    session.open_atlas(b)
    terrain_b = session.terrain[0].copy()
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)
    assert np.array_equal(session.terrain[0], terrain_b) and session.labels is None  # no clean map of A's
    assert core.map_image_files(b)[0].read_bytes() == b_png


def test_fix_seams_for_the_open_atlas_still_shows(session, two, fake_seams):
    a, _b = two
    session.open_atlas(a)
    session.fix_seams()
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)
    assert int(session.terrain[0][0, 0, 0]) == 9 and session.labels is not None


def test_the_locked_stronghold_search_for_a_saves_nothing_into_b(session, two, monkeypatch):
    a, b = two
    release, started = threading.Event(), threading.Event()
    searched = []

    def find_locks(atlas, todo):
        searched.append(atlas.frames[0]["path"])
        if Path(atlas.frames[0]["path"]).parent.name == "a":
            started.set()
            release.wait(10)
            return [(500.0, 500.0)]  # a hand icon in A
        return []

    monkeypatch.setattr(cities, "find_locks", find_locks)
    session.open_atlas(a)
    assert started.wait(5)
    session.open_atlas(b)  # (B's own search waits: one runs at a time)
    release.set()
    # A's search is dropped and B's runs after it
    assert wait_until(lambda: session.atlas.lock_scanned == ["a"] and not session._lock_job)
    assert len(searched) == 2
    assert session.atlas.locks == [] and file_of(b).get("locks", []) == []  # A's hand icon not in B
    assert file_of(a).get("locks", []) == [] and file_of(a).get("lock_scanned", []) == []  # A searches again later


def test_the_quiet_export_for_a_writes_nothing_once_b_is_open(session, two, monkeypatch):
    a, b = two
    exported = []
    monkeypatch.setattr(adding_mod.builder, "export", lambda atlas, path: exported.append(path))
    session.open_atlas(a)
    g_a = session.generation
    session.open_atlas(b)
    session._export_quiet(g_a)
    assert exported == []  # (it would have written A's map PNGs under B's name)
    session._export_quiet(session.generation)
    assert exported == [b]


def test_jobs_queued_for_a_are_skipped_once_b_is_open(session, two, monkeypatch):
    a, b = two
    ran = []
    monkeypatch.setattr(session, "run_job", lambda paths, mode: ran.append((session.path, mode)))
    session.open_atlas(a)
    g_a = session.generation
    session.open_atlas(b)
    threading.Thread(target=session._worker, daemon=True).start()
    session._queue_job([], "undo", gen=g_a)  # e.g. auto-add handing over A's screenshot just as B opened
    session._queue_job([], "recheck_all")  # one for B
    assert wait_until(lambda: not session.working())
    assert ran == [(b, "recheck_all")]
    assert any("skipped a job queued for another atlas" in line for line in session.events.log_lines)


def test_auto_add_follows_the_atlas(session, two, monkeypatch):
    a, b = two
    monkeypatch.setattr(session, "detector_ready", lambda: None)
    session.settings["watch_on"] = True
    session.open_atlas(a)
    first = session._watch_thread
    assert session.watch_dir() == str(a.parent)
    session.open_atlas(b)
    first.join(3)
    assert not first.is_alive()  # A's watcher stopped
    assert session._watch_on and session.watch_dir() == str(b.parent) and session._watch_gen == session.generation
    session.stop_watch()


def test_a_folder_check_still_running_for_a_hands_nothing_to_b(session, two, monkeypatch):
    a, b = two
    monkeypatch.setattr(session, "detector_ready", lambda: None)
    session.open_atlas(a)
    g_a = session.generation
    session.open_atlas(b)
    # A's watcher was mid-check when B opened: it still thinks it watches for A
    session._watch_on, session._watch_gen, session._watch_seen = True, g_a, {}
    shot = b.parent / "2694940_20250101120000_1.png"
    cv2.imwrite(str(shot), np.zeros((20, 20, 3), np.uint8))
    session.poll_watch()  # (seen once: size noted)
    assert session.poll_watch() == [shot]
    try:
        assert [job[2] for job in session._jobs.queue] == [g_a]  # tagged for A: the worker skips it
    finally:
        session._jobs.get()
        session._jobs.task_done()
        session._watch_on = False


def test_the_replay_of_a_is_closed_by_opening_b(session, two, tmp_path):
    (tmp_path / "t").mkdir()
    t = timed_atlas(tmp_path / "t")
    _a, b = two
    session.open_atlas(t)
    session.replay_open()
    assert session.replay_fog()["field"] is not None and session.replay_steps() is not None
    session.open_atlas(b)
    assert session.replay_steps() is None and session.replay_fog() == {"field": None}
    assert session._fog is None


def test_a_fog_made_for_an_old_plan_is_not_kept(session, tmp_path, monkeypatch):
    session.open_atlas(timed_atlas(tmp_path))
    session.replay_open()
    real = replay_data.base64.b64encode

    def replanned_meanwhile(data):
        session._plan = copy.copy(session._plan)  # another plan (a replay setting changed, or another atlas)
        return real(data)

    monkeypatch.setattr(replay_data.base64, "b64encode", replanned_meanwhile)
    assert session.replay_fog()["field"] is not None  # answered (the page drops it)...
    assert session._fog is None  # ...but not kept for the new plan
    monkeypatch.setattr(replay_data.base64, "b64encode", real)
    got = session.replay_fog()
    assert session._fog is got  # made for the plan it is kept with


# ------------------------------------------------------------------ the page's requests


@pytest.fixture
def app(two, quiet_locks):
    a, b = two
    session = AtlasSession(settings={}, worker=False)
    session.open_atlas(a)
    srv = AppServer(session, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, a, b
    srv.stopping = True
    srv.shutdown()
    srv.server_close()
    session.shutdown()


def test_every_answer_says_which_atlas_it_is_for(app):
    srv, _a, _b = app
    st, h, body = call(srv, "/api/state")
    assert st == 200 and h["X-Atlas-Gen"] == str(srv.session.generation) == str(json.loads(body)["generation"])
    assert call(srv, "/api/types")[1]["X-Atlas-Gen"] == str(srv.session.generation)


def test_a_change_made_for_a_is_refused_once_b_is_open(app):
    srv, a, b = app
    g_a = str(srv.session.generation)
    st, _h, _body = call(srv, "/api/atlas/open", "POST", {"path": str(b)}, {"X-Atlas-Gen": g_a})
    assert st == 200 and srv.session.path == b  # switching itself doesn't belong to one atlas
    before = file_of(b)["bookmarks"]
    st, _h, body = call(srv, "/api/bookmarks", "POST", {"x": 50, "y": 50, "name": "for A"}, {"X-Atlas-Gen": g_a})
    assert st == 409 and json.loads(body)["stale"] is True
    st, _h, _body = call(srv, "/api/atlas/save", "POST", {}, {"X-Atlas-Gen": g_a})
    assert st == 409
    srv.session.save()
    assert file_of(b)["bookmarks"] == before  # nothing of A's landed in B
    g_b = str(srv.session.generation)
    st, _h, _body = call(srv, "/api/bookmarks", "POST", {"x": 50, "y": 50, "name": "for B"}, {"X-Atlas-Gen": g_b})
    assert st == 200
    assert call(srv, "/api/atlas/save", "POST", {})[0] == 200  # (no header: an older page or a script)
    # not about one atlas: settings and answering a question go through with an old generation
    assert call(srv, "/api/settings", "PATCH", {"ui": {"labels": True}}, {"X-Atlas-Gen": g_a})[0] == 200


def test_the_times_seen_picture_is_kept_per_atlas(app, tmp_path):
    srv, _a, _b = app
    (tmp_path / "t").mkdir()
    t = timed_atlas(tmp_path / "t")
    assert call(srv, "/api/heat?upto=-1")[0] == 200
    png_a = call(srv, "/api/heat.png?upto=-1")[2]
    srv.session.open_atlas(t)
    png_t = call(srv, "/api/heat.png?upto=-1")[2]  # the page asks for the picture before its box: not A's kept one
    assert png_t != png_a and png_t == srv.session.heat_png(None)[0]


def test_the_server_knows_which_calls_belong_to_no_atlas():
    assert all(p.startswith("/api/") for p in S.GEN_FREE)
    assert not any("/api/atlas/save".startswith(p) or "/api/atlas/close".startswith(p) for p in S.GEN_FREE)
