"""The map's vector tiles and 3D scene while a job holds the session lock (app.mapimage, _made_under_lock).

A job (adding, re-checking) holds the lock for minutes. A change during it (the new screenshots pasted into the map
image, a filter) made the page ask for new vector tiles, and each request waited for the job: they took all the
browser's connections, so even the ground of a spot jumped to stayed black until the job ended (user).
"""

import threading
import time

import pytest

from grand_project import cities
from grand_project.app import constants as K
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas

HOLD = 6.0  # seconds the "job" holds the lock: well past any answer that doesn't wait for it
WAIT = K.TILER_LOCK_WAIT  # the app's own (the other tests wait longer: conftest)


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "TILER_LOCK_WAIT", WAIT)
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])  # (no locked-stronghold search behind the test)
    s = AtlasSession(settings={}, worker=False)
    path, _pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    # (opening starts the locked-stronghold search, which ends with a filter version of its own: waited for,
    # it landed in the middle of a test's versions)
    t = getattr(s, "_lock_thread", None)
    if t:
        t.join(60)
    yield s
    s.shutdown()


class Job:
    """Holds the session lock on a thread of its own, as a job placing screenshots does, after a change made under it
    (`change`), until let go."""

    def __init__(self, session, change=None):
        self.s, self.change = session, change
        self.holding, self.go = threading.Event(), threading.Event()
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        with self.s._lock:
            if self.change:
                self.change()
            self.holding.set()
            self.go.wait(HOLD)

    def __enter__(self):
        self.t.start()
        assert self.holding.wait(10)
        return self

    def __exit__(self, *exc):
        self.go.set()
        self.t.join(10)


def tile(s) -> bytes:
    """A vector tile at the spot of the atlas's first map."""
    g, n = s.grid, s.V["nodes"][0]
    wx, wy = g.world_px(n["x"], n["y"])
    return s.vector_tile(g.zmax, int(wx // 256), int(wy // 256))


def answered_soon(fn):
    """fn's answer and whether it came well before the job let go."""
    t0 = time.monotonic()
    out = fn()
    return out, time.monotonic() - t0 < HOLD / 2


def refreshed(s, before: int) -> bool:
    """Wait for the refresh after the job: a new filter version told to the page, its tiler made already."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        v = s._vector
        told = any(e["kind"] == "filters" and e["data"] == s.filter_version for e in list(s.events.history))
        if s.filter_version > before and v is not None and v[0] == s._tiles_key(False) and told:
            return True  # (told right after the locked step it was made in)
        time.sleep(0.05)
    return False


def test_a_new_map_image_during_a_job_keeps_the_tiles_made_before_until_it_lets_go(session):
    before = tile(session)
    filters = session.filter_version
    with Job(session, lambda: session.set_terrain(*session.terrain, save=False, cities=False)):
        assert session._vector[0] != session._tiles_key(False)  # (the map image changed: its tiles are out of date)
        data, soon = answered_soon(lambda: tile(session))
        assert soon and data == before  # what the map showed before, at once: not after the job
        assert session.filter_version == filters  # (no refresh while the job holds the lock)
    assert refreshed(session, filters)  # then the page asks again, and gets the new ones without waiting


def test_a_filter_changed_during_a_job_keeps_the_tiles_made_before(session):
    before = tile(session)
    filters = session.filter_version
    with Job(session):
        session.set_ui_settings({"layers": {"Removed": True}})  # a filter the tiles hold (from the page: no lock)
        data, soon = answered_soon(lambda: tile(session))
        assert soon and data == before  # (dropped by the filter change, every request waited for the job)
    assert refreshed(session, filters + 1)


def test_with_a_refresh_waiting_the_lock_isnt_waited_for_at_all(session, monkeypatch):
    before = tile(session)
    monkeypatch.setattr(K, "TILER_LOCK_WAIT", HOLD)  # (waited for in full, an answer would come after the job)
    with Job(session, lambda: session.set_terrain(*session.terrain, save=False, cities=False)):
        monkeypatch.setattr(session, "_refresh_waiting", {session.opened.gen})  # a refresh pending: lock taken
        data, soon = answered_soon(lambda: tile(session))
        assert soon and data == before  # (each of a move's ~50 tiles waited its turn before: self review)


def test_the_refresh_makes_anew_only_what_was_asked_for(session):
    session.scene_3d()  # the 3D view opened once, then the flat map again
    tile(session)
    scene_before = session._scene3d[0]
    filters = session.filter_version
    with Job(session, lambda: session.set_terrain(*session.terrain, save=False, cities=False)):
        tile(session)  # only the flat map's tiles asked for meanwhile
    assert refreshed(session, filters)
    assert session._scene3d[0] == scene_before  # not made anew under the lock: it was never asked for (self review)


def test_the_3d_scene_during_a_job_is_the_one_made_before(session):
    before = session.scene_3d()
    with Job(session, lambda: session.set_terrain(*session.terrain, save=False, cities=False)):
        data, soon = answered_soon(session.scene_3d)
        assert soon and data == before


def test_another_atlass_tiles_are_never_answered(session, tmp_path):
    tile(session)  # the first atlas's tiler made
    (tmp_path / "other").mkdir()
    other, _pts, _img = make_atlas(tmp_path / "other")
    session.open_atlas(other)  # (its tiles not asked for yet: the slot still holds the first atlas's)
    assert session._vector[3] != session.opened.gen
    with Job(session) as job:
        threading.Timer(1.0, job.go.set).start()  # the job lets go after a second
        t0 = time.monotonic()
        tile(session)
        assert time.monotonic() - t0 >= 0.9  # waited for the lock: the other atlas's tiles weren't answered
    assert session._vector[3] == session.opened.gen  # made for this atlas


def refresh_calls(session, monkeypatch, name: str) -> list:
    """Record the atlases (generations) a session method was called for from a refresh thread."""
    calls, real = [], getattr(session, name)

    def spy(*a, **kw):
        if threading.current_thread().name == "tiles-refresh":
            calls.append(session.opened.gen)
        return real(*a, **kw)

    monkeypatch.setattr(session, name, spy)
    return calls


def join_background(session) -> None:
    """Wait for the refresh threads and the locked-stronghold search (its own filter version: not the refresh's)."""
    for t in threading.enumerate():
        if t.name == "tiles-refresh" or t is getattr(session, "_lock_thread", None):
            t.join(10)


def test_the_refresh_is_dropped_when_another_atlas_opened_meanwhile(session, tmp_path, monkeypatch):
    (tmp_path / "other").mkdir()
    other, _pts, _img = make_atlas(tmp_path / "other")
    bumped = refresh_calls(session, monkeypatch, "filters_changed")
    with session._lock:  # (this thread holds it: the refresh waits)
        session._refresh_when_free("_vector", session.opened.gen)
        session.open_atlas(other)  # another atlas opened before the lock is free
    join_background(session)
    # no new version from the refresh for the atlas opened since (its own versions tell the page); checked on the
    # refresh's own calls: the second atlas's stronghold search bumps the version too (CodeRabbit)
    assert bumped == []
    assert not session._refresh_waiting  # (and a later answer from old tiles can ask for a refresh again)


def test_a_map_image_moved_during_the_wait_isnt_answered_with_the_old_grid(session):
    tile(session)
    canvas, weight, (x0, y0, scale) = session.terrain
    holding, go = threading.Event(), threading.Event()

    def job():
        with session._lock:
            session.set_terrain(canvas, weight, (x0, y0, scale), save=False, cities=False)  # a paste: same grid
            holding.set()
            time.sleep(K.TILER_LOCK_WAIT / 3)  # the request is waiting for the lock by now
            session.set_terrain(canvas, weight, (x0 - 40, y0, scale), save=False, cities=False)
            go.wait(1.0)

    t = threading.Thread(target=job, daemon=True)
    t.start()
    assert holding.wait(10)
    t0 = time.monotonic()
    tile(session)
    # the grid asked again after the wait: it changed, so the request waited for the job (CodeRabbit)
    assert time.monotonic() - t0 >= 0.9
    t.join(10)
    assert session._vector[2].to_json() == session.grid.to_json()


def test_tiles_cut_for_another_grid_are_never_answered(session):
    tile(session)
    x0, y0, scale = session.terrain[2]
    canvas, weight = session.terrain[0], session.terrain[1]
    with Job(
        session, lambda: session.set_terrain(canvas, weight, (x0 - 40, y0, scale), save=False, cities=False)
    ) as job:
        threading.Timer(1.0, job.go.set).start()  # the job lets go after a second
        t0 = time.monotonic()
        tile(session)
        # waited for the lock: the map image lies elsewhere now, and features cut for the old grid sat off its ground
        assert time.monotonic() - t0 >= 0.9  # (CodeRabbit)
    assert session._vector[2].to_json() == session.grid.to_json()


def test_a_refresh_for_an_atlas_closed_meanwhile_keeps_the_next_atlass(session, tmp_path, monkeypatch):
    (tmp_path / "other").mkdir()
    other, _pts, _img = make_atlas(tmp_path / "other")
    made_for = refresh_calls(session, monkeypatch, "_vector_made")  # the atlases tiles were made for
    with session._lock:  # (this thread holds it: both refreshes wait)
        first = session.opened.gen
        session._refresh_when_free("_vector", first)
        session.open_atlas(other)
        session._refresh_when_free("_vector", session.opened.gen)  # the second's, asked while the first's waits
    join_background(session)
    # the second atlas's refresh ran (taken by the first's waiter, it was dropped with it: CodeRabbit); the first's not
    assert made_for == [session.opened.gen] and first != session.opened.gen
    assert not session._refresh_waiting and not session._refresh_stale
