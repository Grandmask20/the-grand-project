"""Fixes from CodeRabbit's review of the web app (PR #37), one test each: the case it described, now handled."""

import json
import threading
import urllib.request
from types import SimpleNamespace

import numpy as np
import pytest

from grand_project import cities
from grand_project.app.events import Events
from grand_project.app.server import AppServer
from grand_project.app.session import AtlasSession
from tests.test_app_session import features
from tests.webmap_data import make_atlas


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    s = AtlasSession(settings={}, worker=False)
    path, _pts, _img = make_atlas(tmp_path)
    s.open_atlas(path)
    yield s
    s.shutdown()


def test_debug_numbers_never_come_back(session):
    a = session.add_debug_mark("wrong map", "x", "", maps=[3])["id"]
    b = session.add_debug_mark("wrong map", "x", "", maps=[4])["id"]
    session.delete_debug_mark(b)  # the newest: its number was handed out again
    c = session.add_debug_mark("wrong map", "x", "", maps=[5])["id"]
    session.clear_debug_marks()  # all of them: numbering started at D1 again
    d = session.add_debug_mark("wrong map", "x", "", maps=[6])["id"]
    assert (a, b, c, d) == (1, 2, 3, 4)


def test_a_failed_undo_can_be_tried_again(session, tmp_path):
    session._undo = [{"file": str(tmp_path / "gone.json"), "names": ["x.png"]}]
    with pytest.raises(OSError):
        session._run_undo()
    assert len(session._undo) == 1  # still there


def test_waiting_screenshots_are_retried_by_identity(session, tmp_path):
    a, b, c = (SimpleNamespace(path=tmp_path / f"{n}.png") for n in "abc")
    session._pending_watch = [a, b, c]
    assert session.retry_waiting([1]) == 1
    _paths, mode, _gen = session._jobs.get()
    session._jobs.task_done()
    assert mode == ("retry", [str(b.path)])  # B itself, even if A is placed before the job runs


def test_near_only_lists_keep_the_cities(session):
    session.set_ui_settings({"near_only": True})
    rows = session.search("city").get("results", [])
    assert any(r["kind"] == "landmark" for r in rows)


def test_a_hidden_landmark_type_has_no_3d_model(session):
    with session._lock:
        session.atlas.final["landmarks"].append({"kind": "Tower", "x": 700.0, "y": 300.0, "status": "kept"})
    session.rebuild_model()
    towers = lambda: [f for f in features(session, "solids") if f[2].get("kind") == "Tower"]  # noqa: E731
    shown = len(features(session, "solids"))
    session.set_ui_settings({"hidden_types": ["Tower"]})
    assert len(features(session, "solids")) < shown and not towers()  # (its model stayed with the type hidden)


def test_another_clean_map_is_another_sharp_tile_folder(session):
    session.labels = (np.zeros((40, 40), np.int16), ["a"])
    one = session._sharp_folder().name
    session.labels = (np.ones((40, 40), np.int16), ["a"])
    assert session._sharp_folder().name != one


def test_screenshots_are_seen_again_when_handing_them_over_fails(session, monkeypatch, tmp_path):
    shot = session.path.parent / "2694940_20250101120000_1.png"
    shot.write_bytes(b"x" * 100)
    session._watch_on, session._watch_seen = True, {}

    def broken(*a, **kw):
        raise ValueError("the detector database is missing")

    monkeypatch.setattr(session, "add_screenshots", broken)
    session.poll_watch()  # size noted
    with pytest.raises(ValueError):
        session.poll_watch()
    assert str(shot) not in session._watch_seen  # (it was marked handed over: never tried again)
    session._watch_on = False


def test_a_dropped_listener_is_told(monkeypatch):
    ev = Events()
    q = ev.listen()
    for k in range(q.maxsize + 1):
        ev.publish("log", k)
    assert getattr(q, "dropped", False)  # its stream ends, and the page reconnects


def test_different_uploads_of_one_name_get_their_own_files(session):
    srv = AppServer(session, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:

        def up(data: bytes) -> str:
            req = urllib.request.Request(srv.url + "api/upload", data=data, method="POST")
            req.add_header("X-Grand", "1")
            req.add_header("X-Filename", "shot.png")
            req.add_header("Content-Type", "application/octet-stream")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())["path"]

        paths = [up(b"one"), up(b"two"), up(b"three"), up(b"one")]
        assert len(set(paths[:3])) == 3 and paths[3] == paths[0]  # the same picture again: the same file
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()
