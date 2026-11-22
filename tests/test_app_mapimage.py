"""The map's vector tiles and 3D scene while a job holds the session lock (app.mapimage, _made_under_lock).

A job (adding, re-checking) holds the lock for minutes. A change during it (the new screenshots pasted into the map
image, a filter) made the page ask for new vector tiles, and each request waited for the job: they took all the
browser's connections, so even the ground of a spot jumped to stayed black until the job ended (user).
"""

import threading
import time

import pytest

from grand_project import cities
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas

HOLD = 6.0  # seconds the "job" holds the lock: well past any answer that doesn't wait for it


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])  # (no locked-stronghold search behind the test)
    s = AtlasSession(settings={}, worker=False)
    path, _pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
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
        if s.filter_version > before and v is not None and v[0] == s._tiles_key(False):
            return any(e["kind"] == "filters" and e["data"] == s.filter_version for e in s.events.history)
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


def test_the_refresh_is_dropped_when_another_atlas_opened_meanwhile(session, tmp_path):
    (tmp_path / "other").mkdir()
    other, _pts, _img = make_atlas(tmp_path / "other")
    with session._lock:  # (this thread holds it: the refresh waits)
        session._refresh_when_free()
        session.open_atlas(other)  # another atlas opened before the lock is free
        filters = session.filter_version
    for t in threading.enumerate():
        if t.name == "tiles-refresh":
            t.join(10)
    assert session.filter_version == filters  # not bumped for the atlas opened since (its own versions tell the page)
    assert not session._refresh_waiting  # (and a later answer from old tiles can ask for a refresh again)
