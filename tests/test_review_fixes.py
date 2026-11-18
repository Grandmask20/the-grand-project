"""Fixes from CodeRabbit's review of the web app (PR #37), one test each: the case it described, now handled."""

import json
import threading
import urllib.request
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from grand_project import cities
from grand_project.app.events import Events
from grand_project.app.server import AppServer
from grand_project.app.session import AtlasSession
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
    k = len(session.V["landmarks"]) - 1  # the tower

    def models():
        return json.loads(session.scene_3d())["models"]

    assert any(m["pick"] == f"landmark:{k}" for m in models())
    shown = len(models())
    session.set_ui_settings({"hidden_types": ["Tower"]})
    assert len(models()) < shown and not any(m["pick"] == f"landmark:{k}" for m in models())


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


def test_a_failing_job_keeps_the_waiting_island(session, tmp_path, monkeypatch):
    island = [SimpleNamespace(path=tmp_path / f"{n}.png", sha=f"sha-{n}") for n in "abc"]
    session._pending_watch = list(island)

    def broken(fr):
        raise RuntimeError("a preview failed")

    monkeypatch.setattr(session, "_place_one", broken)
    with pytest.raises(RuntimeError):
        session._place_watched([])
    assert session._pending_watch == island  # (emptied at the start, a failure lost them for good)


def test_a_weak_match_preview_shows_what_it_joins(session, tmp_path):
    shot = tmp_path / "shot.png"
    cv2.imwrite(str(shot), np.full((1080, 1920, 3), 90, np.uint8))
    # the atlas's map nodes, as placement pairs against them (Atlas.points)
    session.atlas.nodes = [{"x": n["x"], "y": n["y"]} for n in session.atlas.final["nodes"][:15]]
    pts = session.atlas.points()[:6]
    frame = SimpleNamespace(path=shot, R=np.eye(3), pts=pts, usable=np.ones(len(pts), bool))
    reg = SimpleNamespace(M=np.array([[1.0, 0, 0], [0, 1.0, 0]]), ref_frame="a")  # its maps on the atlas's own
    pv = session._preview_of(frame, reg)
    assert len(pv["agree"]) == 6  # the maps it agrees with, ringed on the map
    near = pv["near"]
    assert all(near[0] <= x <= near[2] and near[1] <= y <= near[3] for x, y in pv["agree"])


def test_a_question_lets_go_of_the_session_lock_while_open(session):
    free = []

    def ask(question, preview=None):  # the page's side: another request needs the lock meanwhile
        t = threading.Thread(target=lambda: free.append(session._lock.acquire(timeout=2) and session._lock.release()))
        t.start()
        t.join()
        return True

    session.events.ask = ask
    with session._lock:  # as the job holds it
        assert session._ask("add it?") is True
        assert session._lock._is_owned()  # taken back for the rest of the job
    assert free == [None]  # (acquired: the request didn't wait for the answer)


def test_the_waiting_list_stays_shown_while_a_question_is_open(session, tmp_path, monkeypatch):
    island = [SimpleNamespace(path=tmp_path / f"{n}.png", sha=f"sha-{n}") for n in "abc"]
    session._pending_watch = list(island)
    seen = []
    monkeypatch.setattr(session, "_place_one", lambda fr: SimpleNamespace(ok=True, reason="", inliers=9, ncc=0.4))
    monkeypatch.setattr(session, "_concerns", lambda fr, reg: ["the match is weak"])
    monkeypatch.setattr(session, "_preview_of", lambda fr, reg: None)
    monkeypatch.setattr(session, "_show_placed", lambda shas: None)
    monkeypatch.setattr(session.atlas, "commit_frame", lambda fr, reg: None)

    def ask(question, preview=None):
        seen.append([f.sha for f in session._pending_watch])  # what the page shows meanwhile
        return False  # No: left out

    session.events.ask = ask
    session._place_watched([])
    assert seen[0] == ["sha-a", "sha-b", "sha-c"]  # (it read empty while the question was open)


def test_a_landmark_model_selects_the_map_node_it_marks(session):
    n4 = session.V["nodes"][4]
    with session._lock:
        session.atlas.final["landmarks"].append({"kind": "Hall", "x": n4["x"] + 6, "y": n4["y"] - 4, "status": "kept"})
    session.rebuild_model()
    k = len(session.V["landmarks"]) - 1
    assert session.D["landmark_node"][k] == 4
    picks = {m["pick"] for m in json.loads(session.scene_3d())["models"]}
    assert "node:4" in picks and f"landmark:{k}" not in picks  # (it selected the landmark, its map not lit up)
    assert session.info("landmark", k)["node"] == 4
    node = session.info("node", 4)
    assert node["landmark"] == k and any("here" in str(line) for line in node["lines"])
    # a hand-added landmark (no counts) still has details
    with session._lock:
        session.atlas.final["landmarks"].append({"kind": "Tower", "x": 9000.0, "y": 9000.0, "status": "kept"})
    session.rebuild_model()
    assert session.info("landmark", len(session.V["landmarks"]) - 1)["title"]


def test_a_failing_retry_keeps_the_ones_set_aside(session, tmp_path, monkeypatch):
    a, b = (SimpleNamespace(path=tmp_path / f"{n}.png", sha=f"sha-{n}") for n in "ab")
    session._pending_watch = [a, b]

    def broken(frames):
        raise RuntimeError("placing failed")

    monkeypatch.setattr(session, "_place_watched", broken)
    monkeypatch.setattr(session, "_snapshot", lambda: tmp_path / "snap.json")
    with pytest.raises(RuntimeError):
        session.run_job([], ("retry", [str(b.path)]))
    assert {f.sha for f in session._pending_watch} == {"sha-a", "sha-b"}  # (A, set aside, was lost)


def test_one_taken_out_during_a_question_stays_out(session, tmp_path, monkeypatch):
    a, b = (SimpleNamespace(path=tmp_path / f"{n}.png", sha=f"sha-{n}") for n in "ab")
    session._pending_watch = [a, b]
    monkeypatch.setattr(
        session, "_place_one", lambda fr: SimpleNamespace(ok=fr is b, reason="no match", inliers=9, ncc=0.4)
    )
    monkeypatch.setattr(session, "_concerns", lambda fr, reg: ["the match is weak"])
    monkeypatch.setattr(session, "_preview_of", lambda fr, reg: None)
    monkeypatch.setattr(session, "_show_placed", lambda shas: None)

    def ask(question, preview=None):
        session.take_waiting(0)  # A taken out by hand while B's question is open
        return False

    session.events.ask = ask
    session._place_watched([])
    assert "sha-a" not in [f.sha for f in session._pending_watch]  # (A came back when the job ended)


def test_icons_stand_on_a_tower_drawn_for_a_map_node(session):
    with session._lock:
        session.atlas.final["nodes"][4]["tower"] = True  # marked as a tower, with no Tower landmark
    session.rebuild_model()
    node_ok = [session.node_shown(n, session._flags()) for n in session.V["nodes"]]
    shapes = session._solid_shapes(node_ok)
    tower = max(sh["top"] for sh in shapes if sh["pick"] == ("node", 4) and sh["top"] < 300)
    assert session._model_tops(shapes)[4] == tower > session._model_tops(shapes)[3]  # (it stood on the pillar)


def test_a_tower_hidden_by_a_filter_isnt_drawn_by_its_map_node(session, monkeypatch):
    n4 = session.V["nodes"][4]
    with session._lock:
        session.atlas.final["nodes"][4]["tower"] = True
        session.atlas.final["landmarks"].append({"kind": "Tower", "x": n4["x"] + 30, "y": n4["y"], "status": "kept"})
    session.rebuild_model()
    node_ok = [session.node_shown(n, session._flags()) for n in session.V["nodes"]]
    pillar = len([sh for sh in session._solid_shapes(node_ok) if sh["pick"] == ("node", 3)])
    monkeypatch.setattr(type(session), "landmark_shown", lambda self, k, fl: False)  # (as "near only" hides it)
    assert len([sh for sh in session._solid_shapes(node_ok) if sh["pick"] == ("node", 4)]) == pillar


def test_a_locked_stronghold_marks_no_map_node():
    from grand_project.app.session import landmark_nodes

    nodes = [{"x": 0.0, "y": 0.0, "status": "kept"}]
    lms = [{"x": 20.0, "y": 0.0, "kind": "Breach stronghold", "status": "kept"}]
    assert landmark_nodes(nodes, lms) == {0: 0}
    assert landmark_nodes(nodes, lms, {0}) == {}
