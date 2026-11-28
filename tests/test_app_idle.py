"""The screenshots' memory given back when the app sits idle (app.idle.IdleMixin, through the session)."""

import numpy as np

from grand_project.app.constants import IMAGE_IDLE_RELEASE_S
from grand_project.app.session import AtlasSession
from grand_project.core import terrain as core_terrain
from grand_project.finalize import landmarks as fin_landmarks
from grand_project.finalize import traces as fin_traces
from tests.webmap_data import make_atlas


def _opened(tmp_path):
    s = AtlasSession(settings={}, worker=False)
    path, _pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    t = getattr(s, "_lock_thread", None)  # (the stronghold search opening starts holds the session lock: not idle
    if t:  # time while it runs, and on a slow machine it still ran - CI on Linux / macOS)
        t.join(60)
    s.atlas._images["a.png"] = np.zeros((1080, 1920, 3), np.uint8)  # (as a placement leaves it)
    assert s.atlas.image("a.png") is not None  # (a screenshot read, from the cache: the time it was used)
    return s


def test_idle_long_enough_lets_the_screenshots_go(tmp_path):
    s = _opened(tmp_path)
    core_terrain._MASKS[1] = (None, np.zeros(4))
    fin_landmarks._OCEAN[1] = (None, np.zeros(4), np.zeros(4))
    fin_traces._GOLD["x"] = (None, np.zeros(4), (2, 2))
    used = s.atlas.images_used
    assert s.release_idle(now=used + IMAGE_IDLE_RELEASE_S - 1) == 0  # (not yet)
    assert s.release_idle(now=used + IMAGE_IDLE_RELEASE_S + 1) == 1
    assert s.atlas._images == {} and not core_terrain._MASKS and not fin_landmarks._OCEAN and not fin_traces._GOLD


def test_never_while_a_job_runs_or_with_nothing_kept(tmp_path, monkeypatch):
    s = _opened(tmp_path)
    later = s.atlas.images_used + IMAGE_IDLE_RELEASE_S + 1
    monkeypatch.setattr(type(s), "working", lambda self: True)
    assert s.release_idle(now=later) == 0 and s.atlas._images
    monkeypatch.undo()
    s.atlas.release_images()
    assert s.release_idle(now=later) == 0  # (nothing kept: nothing said)


def test_no_atlas_open_is_not_idle_work():
    assert AtlasSession(settings={}, worker=False).release_idle(now=1e9) == 0


def test_idle_also_lets_go_of_the_map_s_caches(tmp_path):
    # (the zoomed-in ground's screenshots and weights, the 3D scene: made again when needed)
    s = _opened(tmp_path)

    class Sharp:
        held = True

        def holding(self):
            return self.held

        def release(self):
            self.held = False
            return 3

    s._sharp, s._scene = Sharp(), (("k", False), b"scene")
    s._scene3d = s._scene3d_steps = object()
    assert s.release_idle(now=s.atlas.images_used + IMAGE_IDLE_RELEASE_S + 1) == 4  # (1 kept by the atlas, 3 by tiles)
    assert not s._sharp.held
    assert s._scene is None and s._scene3d is None and s._scene3d_steps is None


def test_a_job_holding_the_session_lock_is_not_idle_time(tmp_path):
    # (asked and let go in one locked step: a job starting in between used a cache as it was cleared - self review)
    import threading

    s = _opened(tmp_path)
    holding, go = threading.Event(), threading.Event()

    def job():
        with s._lock:
            holding.set()
            go.wait(10)

    t = threading.Thread(target=job, daemon=True)
    t.start()
    assert holding.wait(10)
    try:
        assert s.release_idle(now=s.atlas.images_used + IMAGE_IDLE_RELEASE_S + 1) == 0 and s.atlas._images
    finally:
        go.set()
        t.join(10)
