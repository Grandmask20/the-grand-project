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
from grand_project.app.events import StaleAtlas
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


def test_nothing_of_a_shows_while_b_is_being_loaded(session, two, monkeypatch):
    a, b = two
    session.open_atlas(a)
    assert any(f["corners"] for f in session.frames_payload()["frames"])
    # A's locked-stronghold search ends with a model rebuild: started just before the switch, it built B's model
    # before B's own first rebuild was seen (flaky on a slow CI machine), so it is waited for
    if getattr(session, "_lock_thread", None):
        session._lock_thread.join(10)
    seen = []
    real = session.rebuild_model

    def rebuild():
        # what the page gets if it asks between the switch and B's model: B's screenshots, no outlines of A's
        seen.append((session.path, session.V["nodes"], [f["corners"] for f in session.frames_payload()["frames"]]))
        real()

    monkeypatch.setattr(session, "rebuild_model", rebuild)
    session.open_atlas(b)
    # B's first rebuild (A's own background search may still rebuild A's model just before the switch)
    assert next(x for x in seen if x[0] == b) == (b, [], [[]])
    assert any(f["corners"] for f in session.frames_payload()["frames"])  # B's own once built


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
    assert wait_until(lambda: session.events.progress is None)  # A's build has finished
    # A's map image was dropped: a newer load claimed the build, so A's never reaches set_terrain (or is refused
    # there)...
    assert not any(ok for g, ok in shown if g == g_a)
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
    # what ran is logged with its time and the atlas's counts (user: the log said little)
    assert any("Re-check took" in line and "maps " in line for line in session.events.log_lines)


def test_the_ground_from_before_the_jobs_is_kept_while_they_run(session, two, monkeypatch):
    a, _b = two
    session.open_atlas(a)
    start = session._tile_state
    seen = []

    def job(paths, mode):
        """A job making a new map image (as pasting screenshots does)."""
        seen.append(session._tile_before)
        canvas, weight, origin = session.terrain
        session.set_terrain(canvas, weight, origin, save=False, cities=False)
        seen.append(session._tile_before)

    monkeypatch.setattr(session, "run_job", job)
    session._queue_job([], "recheck_all")
    session._queue_job([], "recheck_all")  # a second job in the same busy spell: still the ground from before both
    threading.Thread(target=session._worker, daemon=True).start()  # (after both are queued: one busy spell)
    # (until it is let go too: the worker says it's idle a moment before: CodeRabbit)
    assert wait_until(lambda: not session.working() and session._tile_before is None)
    # the ground from before both jobs, its map image levels (the page's backdrop asks for it: user, CodeRabbit)
    assert len(seen) == 4 and all(t[1] is start[1] and t[3] == start[3] and t[2] is None for t in seen)
    assert session._tile_before is None  # let go once idle: the backdrop follows the current ground


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
    session.new_atlas(b.parent.parent / "c")  # a new atlas too (auto-add was stopped and left off)
    assert session._watch_on and session.watch_dir() == str(b.parent.parent / "c")
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
    path = timed_atlas(tmp_path)
    at = core.Atlas.load(path)
    # already searched for hand badges: the open starts no search, whose late model rebuild would replan the replay
    # and drop the fog this test checks is kept (it failed on CI)
    at.lock_scanned = [f["name"] for f in at.frames]
    at.save(path)
    session.open_atlas(path)
    assert not getattr(session, "_lock_job", False)  # no search started
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


def test_a_refused_switch_leaves_auto_add_on(session, two, monkeypatch):
    a, b = two
    monkeypatch.setattr(session, "detector_ready", lambda: None)
    session.settings["watch_on"] = True
    session.open_atlas(a)
    real = session.working
    calls = iter([False, True])  # free at the first check, a job slipped in before the second

    monkeypatch.setattr(session, "working", lambda: next(calls, real()))
    with pytest.raises(ValueError, match="being added"):
        session.open_atlas(b)
    assert session.path == a and session._watch_on  # (stopped for the switch and left off: CodeRabbit)
    session.stop_watch()


def test_a_job_logs_under_its_own_atlas(session, two):
    a, b = two
    session.open_atlas(a)
    scope_a = session.events.scope
    session.open_atlas(b)
    session.events.log("A's map image could not be built", scope_a)  # a job of A's finishing after the switch
    assert not any("A's map image" in line for line in session.events.log_lines)
    assert any("A's map image" in line for line in session.events._logs[scope_a])


def test_a_bookmark_made_for_a_is_refused_once_b_is_open(session, two):
    from grand_project.app.events import StaleAtlas

    a, b = two
    session.open_atlas(a)
    g_a = session.generation
    session.open_atlas(b)
    with pytest.raises(StaleAtlas):
        session.add_bookmark(600.0, 600.0, "for A", gen=g_a)
    assert session.add_bookmark(600.0, 600.0, "for B", gen=session.generation) >= 0


def test_the_open_atlas_is_one_record(session, two):
    a, b = two
    session.open_atlas(a)
    job = session.opened  # what a job takes when it starts
    session.open_atlas(b)
    # the job's atlas, file, generation and log are all A's, whatever happened since
    assert job.path == a and job.scope == str(a.resolve()) and job.atlas is not session.atlas
    assert not session.owns(job) and session.owns(session.opened) and session.owns(session.generation)
    assert (session.atlas, session.path, session.generation) == (
        session.opened.atlas,
        session.opened.path,
        session.opened.gen,
    )  # (one source: no field can lag behind)
    assert any("switched to atlas" in line for line in session.events._logs[job.scope])  # (in A's own log)
    session.close()
    assert session.opened.atlas is None and session.events.scope == "" and session.state()["log_scope"] == ""


def test_a_stop_while_the_clean_map_loads_leaves_it_out(session, two, fake_seams, monkeypatch):
    # (GPT audit: Stop only reached a live process; once it had ended, the clean map being loaded went in anyway)
    a, _b = two
    session.open_atlas(a)
    before = session.terrain[0].copy()
    real = mapimage.np.load

    def load_then_stop(*args, **kw):
        session.stop_seams()  # pressed while the finished process's result is read
        return real(*args, **kw)

    monkeypatch.setattr(mapimage.np, "load", load_then_stop)
    session.fix_seams()
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)
    assert np.array_equal(session.terrain[0], before) and session.labels is None


def test_fix_seams_waits_for_adding_when_queued_and_stop_takes_it_off(session, two, fake_seams):
    # (you: Fix seams doesn't start while adding runs; the page asks to cancel, or queue it after adding)
    a, _b = two
    session.open_atlas(a)
    session._jobs.put(([], "recheck_all", session.generation))  # (adding runs)
    assert session.fix_seams() == "adding" and not session.seams_running()
    assert session.fix_seams(after_adding=True) == "queued" and session.state()["seams"]
    session.stop_seams()  # Stop takes it off the queue
    assert not session.state()["seams"]
    assert session.fix_seams(after_adding=True) == "queued"
    session._jobs.get()
    session._jobs.task_done()  # adding is done: the worker starts what was queued
    session._start_waiting_seams()
    assert session.seams_running()
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)


def test_a_queued_fix_seams_is_dropped_for_another_atlas(session, two, fake_seams):
    a, b = two
    session.open_atlas(a)
    session._jobs.put(([], "recheck_all", session.generation))
    assert session.fix_seams(after_adding=True) == "queued"
    session._jobs.get()
    session._jobs.task_done()
    session.open_atlas(b)  # (opening waits for adding: it takes the queued one off as it switches)
    session._start_waiting_seams()
    assert not session.seams_running() and not session.state()["seams"]


def test_each_job_has_its_own_progress_line(session):
    # (GPT audit: the map image build ending blanked adding's progress)
    ev = session.events
    ev.set_progress("adding 1 / 4")
    ev.set_progress("building the map image", owner="map")
    assert ev.progress == "adding 1 / 4 · building the map image"
    ev.set_progress(None, owner="map")
    assert ev.progress == "adding 1 / 4"
    ev.set_progress(None)
    assert ev.progress is None


@pytest.mark.parametrize("anyway", [True, False], ids=["fix-seams-anyway", "cancel"])
def test_a_queued_fix_seams_asks_first_when_adding_failed(session, two, fake_seams, monkeypatch, anyway):
    # (you: it starts only when adding finishes; failed, it says why and asks: Cancel or Fix seams anyway)
    a, _b = two
    session.open_atlas(a)
    asked = []
    monkeypatch.setattr(session.events, "ask", lambda q, **kw: (asked.append((q, kw.get("labels"))), anyway)[1])
    session._jobs.put(([], "recheck_all", session.generation))
    assert session.fix_seams(after_adding=True) == "queued"
    session._note_seams_trouble("adding failed: disk full")  # (the job failed)
    session._jobs.get()
    session._jobs.task_done()
    session._start_waiting_seams()
    assert wait_until(lambda: not session._seams_asking and asked)
    question, labels = asked[0]
    assert "disk full" in question and labels == {"title": "Fix seams", "yes": "Fix seams anyway", "no": "Cancel"}
    if anyway:
        assert wait_until(session.seams_running)
        fake_seams.release.set()
        assert wait_until(lambda: session._seams_proc is None)
    else:
        assert not session.seams_running() and not session.state()["seams"]


def test_a_stop_while_it_asks_leaves_fix_seams_off(session, two, fake_seams, monkeypatch):
    a, _b = two
    session.open_atlas(a)
    answer = threading.Event()
    monkeypatch.setattr(session.events, "ask", lambda q, **kw: answer.wait(5))
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    session._note_seams_trouble("x.png could not be read: damaged")
    session._jobs.get()
    session._jobs.task_done()
    session._start_waiting_seams()
    assert wait_until(lambda: session._seams_asking)
    session.stop_seams()  # Stop while the question is open
    answer.set()  # then "Fix seams anyway"
    assert wait_until(lambda: not session._seams_asking)
    assert not session.seams_running() and not session.state()["seams"]


def test_page_requests_made_for_the_atlas_before_are_refused(session, two):
    # (CodeRabbit: adding, placing, Re-check, auto-add and close didn't check the request's atlas)
    a, b = two
    session.open_atlas(a)
    old = session.generation
    shot = session.atlas.frames[0]["path"]
    session.open_atlas(b)
    watching = session._watch_on
    for act in (
        lambda: session.add_screenshots([shot]),
        lambda: session.place_by_hand(shot, 1.0, 2.0),
        lambda: session.recheck_all(),
        lambda: session.set_watch(not watching),
        lambda: session.set_watch_folder(None),
        lambda: session.close(),
    ):
        with session._lock.expect(old), pytest.raises(StaleAtlas):
            act()
    assert session._jobs.unfinished_tasks == 0 and session._watch_on == watching and session.path is not None


def test_a_job_queued_by_a_request_carries_the_request_s_atlas(session, two):
    # (the safety net: a switch right after the check still never runs it on the next atlas)
    a, _b = two
    session.open_atlas(a)
    gen = session.generation
    with session._lock.expect(gen):
        session._queue_job([], "recheck_all")
    assert session._jobs.queue[-1][2] == gen
    session._queue_job([], "recheck_all")  # (the app's own work: the open atlas)
    assert session._jobs.queue[-1][2] == session.generation


def test_a_stop_just_before_the_queued_start_is_kept(session, two, fake_seams):
    # (CodeRabbit: the queue was cleared before the start was claimed; a Stop in between was lost)
    a, _b = two
    session.open_atlas(a)
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    token = session._seams_waiting["token"]
    session._jobs.get()
    session._jobs.task_done()
    session.stop_seams()  # (between adding ending and the start being claimed)
    session._start_queued_seams(token)
    assert not session.seams_running() and not session.state()["seams"]


def test_an_old_answer_never_cancels_a_newer_queued_fix_seams(session, two, fake_seams, monkeypatch):
    # (CodeRabbit: Cancel on the box of a request Stop took off removed the one queued after it)
    a, _b = two
    session.open_atlas(a)
    answer = threading.Event()
    monkeypatch.setattr(session.events, "ask", lambda q, **kw: (answer.wait(5), False)[1])  # (Cancel)
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    session._note_seams_trouble("adding failed: x")
    session._jobs.get()
    session._jobs.task_done()
    session._start_waiting_seams()
    assert wait_until(lambda: session._seams_asking)
    session.stop_seams()  # the first request taken off...
    session._jobs.put(([], "recheck_all", session.generation))
    assert session.fix_seams(after_adding=True) == "queued"  # ...and a second one queued
    second = session._seams_waiting["token"]
    answer.set()  # then Cancel on the first one's box
    assert wait_until(lambda: not session._seams_asking)
    assert session._seams_waiting is not None and session._seams_waiting["token"] == second
    session._jobs.get()
    session._jobs.task_done()


def test_another_atlas_never_inherits_a_queued_fix_seams(session, two):
    # (CodeRabbit: one left from the atlas before made a request for this one report "queued", unrecorded)
    a, b = two
    session.open_atlas(a)
    session._seams_waiting = {"gen": session.generation, "token": 99}  # (as if left behind)
    session.open_atlas(b)
    assert session._seams_waiting is None and not session.state()["seams"]
    session._jobs.put(([], "recheck_all", session.generation))
    assert session.fix_seams(after_adding=True) == "queued"
    assert session._seams_waiting["gen"] == session.generation
    session._jobs.get()
    session._jobs.task_done()


def test_a_page_log_line_made_for_the_atlas_before_is_refused(session, two):
    # (CodeRabbit: checked first and written later, a switch in between put the line in the next atlas's log)
    a, b = two
    session.open_atlas(a)
    old = session.generation
    session.open_atlas(b)
    srv = AppServer(session, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _h, _b = call(srv, "/api/log", "POST", {"lines": ["clicked a map of A"]}, {"X-Atlas-Gen": str(old)})
        assert status == 409
        assert not any("clicked a map of A" in line for line in session.events.log_lines)
        status, _h, _b = call(srv, "/api/log", "POST", {"lines": ["clicked a map of B"]},
                              {"X-Atlas-Gen": str(session.generation)})  # fmt: skip
        assert status == 200 and any("clicked a map of B" in line for line in session.events.log_lines)
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()


def test_a_quick_atlas_action_waits_for_a_switch_going_on(session, two):
    # (the switch lock: a check and its change can't be split by opening another atlas)
    a, _b = two
    session.open_atlas(a)
    order = []
    with session._lock.switching():  # (a switch going on)
        t = threading.Thread(target=lambda: (session.set_watch(False), order.append("watch off")))
        t.start()
        time.sleep(0.2)
        order.append("switch done")
    t.join(5)
    assert order == ["switch done", "watch off"]


def test_failures_while_the_box_is_open_are_asked_before_fix_seams_starts(session, two, fake_seams, monkeypatch):
    # (CodeRabbit: a Yes started it without showing the failures that came in while the box was open)
    a, _b = two
    session.open_atlas(a)
    asked = []

    def ask(q, **kw):
        asked.append(q)
        if len(asked) == 1:
            session._note_seams_trouble("b.png could not be read: damaged")  # (another add fails meanwhile)
        return True

    monkeypatch.setattr(session.events, "ask", ask)
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    session._note_seams_trouble("a.png could not be read: damaged")
    session._jobs.get()
    session._jobs.task_done()
    session._start_waiting_seams()
    assert wait_until(session.seams_running)
    assert len(asked) == 2 and "a.png" in asked[0] and "b.png" in asked[1] and "a.png" not in asked[1]
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)


def test_an_undo_during_the_stronghold_search_drops_its_result(session, two, monkeypatch):
    # (CodeRabbit: the search's result put back the strongholds of the screenshots Undo took away)
    a, _b = two
    if getattr(session, "_lock_thread", None):
        session._lock_thread.join(10)
    session.open_atlas(a)
    if getattr(session, "_lock_thread", None):
        session._lock_thread.join(10)
    release, started, calls = threading.Event(), threading.Event(), []

    def find_locks(atlas, todo):
        calls.append([f["name"] for f in todo])
        if len(calls) == 1:
            started.set()
            release.wait(10)
            return [(500.0, 500.0)]  # (a hand icon in a screenshot Undo takes away)
        return []

    monkeypatch.setattr(cities, "find_locks", find_locks)
    with session._lock:
        session.atlas.lock_scanned = []
    session.scan_locks()
    assert started.wait(5)
    with session._lock:  # (what Undo does: the atlas as before, the search out of date)
        session._lock_rev = getattr(session, "_lock_rev", 0) + 1
    release.set()
    assert wait_until(lambda: len(calls) >= 2)  # (searched again, the screenshots as they are now)
    if getattr(session, "_lock_thread", None):
        session._lock_thread.join(10)
    assert not any(abs(k["x"] - 500.0) < 1 for k in session.atlas.locks)


def test_a_job_queued_while_closing_keeps_its_atlas_open(session, two, monkeypatch):
    # (CodeRabbit: a job admitted after Close's first check had its atlas closed under it)
    a, _b = two
    session.open_atlas(a)
    real_save = session.save

    def save_then_add():
        real_save()
        session._queue_job([], "recheck_all")  # (an add comes in while Close saves)

    monkeypatch.setattr(session, "save", save_then_add)
    with pytest.raises(ValueError, match="being added"):
        session.close()
    assert session.path == a and session._jobs.queue[-1][2] == session.generation
    session._jobs.get()
    session._jobs.task_done()


def test_an_older_map_image_build_never_replaces_a_newer_image(session, two):
    # (CodeRabbit: a build still running put its plain image in after the clean map; Fix seams retires builds)
    a, _b = two
    session.open_atlas(a)
    canvas, weight, origin = session.terrain
    session._terrain_job += 1  # (a newer build, or a clean map put in)
    assert session.set_terrain(canvas, weight, origin, save=False, job=session._terrain_job - 1) is False
    assert session.set_terrain(canvas, weight, origin, save=False, job=session._terrain_job) is True


def test_the_worker_goes_on_when_the_queued_fix_seams_cannot_start(two, monkeypatch, quiet_locks):
    # (CodeRabbit: a failure starting the queued Fix seams ended the worker; screenshots queued after were never added)
    s = AtlasSession(settings={}, worker=True)
    try:
        a, _b = two
        s.open_atlas(a)
        ran = []
        monkeypatch.setattr(s, "run_job", lambda paths, mode: ran.append(mode))
        monkeypatch.setattr(s, "_start_waiting_seams", lambda: (_ for _ in ()).throw(RuntimeError("no thread")))
        s._queue_job([], "recheck_all")
        assert wait_until(lambda: len(ran) == 1 and not s.working())
        s._queue_job([], "recheck_all")
        assert wait_until(lambda: len(ran) == 2)
    finally:
        s.shutdown()


def test_the_queued_start_waits_while_a_box_is_open_or_failures_wait(session, two, fake_seams):
    # (CodeRabbit: the claim started it past an open "adding didn't finish" box, or without asking about a failure)
    a, _b = two
    session.open_atlas(a)
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    token = session._seams_waiting["token"]
    session._jobs.get()
    session._jobs.task_done()
    session._seams_asking = True  # (a box is open)
    assert session.fix_seams(after_adding=True, claim=token) == "queued" and not session.seams_running()
    session._seams_asking = False
    session._note_seams_trouble("x.png could not be read")  # (a failure waits to be asked about)
    assert session.fix_seams(after_adding=True, claim=token) == "queued" and not session.seams_running()
    session._seams_trouble = []
    assert session.fix_seams(after_adding=True, claim=token) == "started"
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)


def test_the_cached_map_image_carries_its_build(session, two, monkeypatch):
    # (CodeRabbit: the cached image had no build number, so a clean map put in meanwhile could be replaced)
    a, _b = two
    session.open_atlas(a)
    got = []
    real = session.set_terrain
    monkeypatch.setattr(session, "set_terrain", lambda *args, **kw: (got.append(kw.get("job")), real(*args, **kw))[1])
    session.load_terrain(background=False)
    assert got and got[0] == session._terrain_job


def test_a_second_fix_seams_request_never_skips_an_open_box(session, two, fake_seams):
    # (CodeRabbit: a second request while "adding didn't finish" was open started it past the box's Cancel)
    a, _b = two
    session.open_atlas(a)
    session._jobs.put(([], "recheck_all", session.generation))
    session.fix_seams(after_adding=True)
    session._jobs.get()
    session._jobs.task_done()
    session._seams_asking = True  # (its box is open, adding is done)
    assert session.fix_seams(after_adding=True) == "queued" and not session.seams_running()
    assert session.fix_seams() == "queued" and not session.seams_running()
    session._seams_asking = False
    session._seams_waiting = None  # (answered Cancel)
    assert session.fix_seams() == "started"  # (none queued: at once, as before)
    fake_seams.release.set()
    assert wait_until(lambda: session._seams_proc is None)
