"""The app's web server (app.server.AppServer): the JSON API, tiles, the event stream, safety checks, the page."""

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from grand_project.app import server as S
from grand_project.app.server import AppServer
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas, read_tile


@pytest.fixture
def app(tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    session = AtlasSession(settings={}, worker=False)
    session.open_atlas(path)
    # opening starts the locked-stronghold search, which ends with a model rebuild (new versions): waited for, it
    # landed after a test read the versions and before it asked with them (CodeRabbit)
    t = getattr(session, "_lock_thread", None)
    if t:
        t.join(60)
        assert not t.is_alive(), "the locked-stronghold search didn't end"
    srv = AppServer(session, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, pts
    srv.stopping = True
    srv.shutdown()
    srv.server_close()
    session.shutdown()


def call(srv, path, method="GET", body=None, headers=None):
    """Make a request; returns (status, headers, body bytes)."""
    req = urllib.request.Request(srv.url + path.lstrip("/"), method=method)
    req.add_header("X-Grand", "1")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_state_meta_and_map(app):
    srv, _pts = app
    st, _h, body = call(srv, "/api/state")
    state = json.loads(body)
    assert st == 200 and state["atlas"]["maps"] == 15 and state["map"]["zmax"] >= 1
    meta = json.loads(call(srv, "/api/meta")[2])
    assert meta["colours"]["path_multi"].startswith("#") and "Vaal" in meta["city_types"]
    # the page colours map node bubbles by state from these
    states = meta["colours"]["node_state"]
    assert set(states) == {"grey", "blue", "green", "red"}
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in states.values())


def test_tiles_over_http(app):
    srv, pts = app
    s = srv.session
    wx, wy = s.grid.world_px(*pts[0])
    z = s.grid.zmax
    v = f"{s.map_info()['tile_key']}-{s.terrain_version}"  # (the page's address: tile key, map image version)
    st, h, body = call(srv, f"/api/tiles/terrain/{z}/{int(wx // 256)}/{int(wy // 256)}.jpg?v={v}")
    assert st == 200 and h["Content-Type"] == "image/jpeg" and body[:2] == b"\xff\xd8"
    assert "immutable" in h["Cache-Control"]  # versioned URLs: kept by the browser
    assert call(srv, f"/api/tiles/terrain/{z}/0/0.jpg")[0] == 204  # no ground there
    st, h, body = call(srv, f"/api/tiles/vector/{z}/{int(wx // 256)}/{int(wy // 256)}.pbf")
    assert h["Content-Type"] == "application/x-protobuf" and read_tile(body)["maps"]
    assert call(srv, "/api/icons/Breach.png?kind=sprite")[2][:4] == b"\x89PNG"


def test_changes_need_the_header_and_the_right_host(app):
    srv, _pts = app
    req = urllib.request.Request(srv.url + "api/atlas/save", method="POST", data=b"{}")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)  # no X-Grand header: another site's page can't add it
    assert e.value.code == 403
    assert call(srv, "/api/state", headers={"Host": "evil.example:80"})[0] == 403  # DNS rebinding
    assert call(srv, "/api/atlas/save", "POST", {})[0] == 200


def test_errors_come_back_as_json(app):
    srv, _pts = app
    st, _h, body = call(srv, "/api/bookmarks", "POST", {"x": 1, "y": 1, "name": ""})
    assert st == 400 and "name" in json.loads(body)["error"]
    assert call(srv, "/api/nothing")[0] == 404
    st, _h, body = call(srv, "/api/info?kind=node&id=9999")
    assert st == 400 and json.loads(body)["error"] == "no such item"


def test_bookmark_search_and_pick(app):
    srv, pts = app
    assert (
        json.loads(call(srv, "/api/bookmarks", "POST", {"x": pts[2][0], "y": pts[2][1], "name": "ritual"})[2])["id"]
        == 1
    )
    assert call(srv, "/api/bookmarks", "POST", {"x": pts[2][0], "y": pts[2][1], "name": "again"})[0] == 409
    res = json.loads(call(srv, "/api/search?q=ritual")[2])["results"]
    # the bookmark first (its name is the search), then the map with a Ritual icon (maps are found by their icons)
    assert [r["kind"] for r in res][0] == "bookmark" and {r["kind"] for r in res} <= {"bookmark", "node"}
    hit = json.loads(call(srv, "/api/pick", "POST", {"x": pts[5][0], "y": pts[5][1], "z": 1.0})[2])
    assert hit["kind"] == "node" and hit["id"] == 5


def test_the_event_stream_and_questions(app):
    srv, _pts = app
    lines = []
    got = threading.Event()

    def listen():
        with urllib.request.urlopen(srv.url + "api/events", timeout=10) as r:
            for raw in r:
                lines.append(raw.decode())
                if raw.startswith(b"data:") and b"hello" in raw:
                    got.set()
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    for _ in range(100):  # the stream is listening once the server has a listener
        if srv.session.events._listeners:
            break
        threading.Event().wait(0.05)
    srv.session.events.log("hello")
    assert got.wait(5) and any(line.startswith("event: log") for line in lines)

    answer = {}
    asker = threading.Thread(target=lambda: answer.setdefault("yes", srv.session.events.ask("Add it?")))
    asker.start()
    for _ in range(100):
        qs = json.loads(call(srv, "/api/state")[2])["questions"]
        if qs:
            break
        threading.Event().wait(0.05)
    assert call(srv, f"/api/questions/{qs[0]['id']}", "POST", {"yes": True})[0] == 200
    asker.join(5)
    assert answer["yes"] is True


def test_the_page_is_served_and_routes_itself(app, tmp_path, monkeypatch):
    srv, _pts = app
    # an empty page folder, not the real frontend/dist (it fails once the page was built: CodeRabbit)
    monkeypatch.setattr(S, "DIST", tmp_path / "no_page")
    assert call(srv, "/")[0] == 503  # not built: says how to build it
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "a.js").write_text("x", encoding="utf-8")
    monkeypatch.setattr(S, "DIST", dist)
    st, h, body = call(srv, "/somewhere/else")
    assert st == 200 and body == b"<html>app</html>" and "text/html" in h["Content-Type"]
    st, h, _b = call(srv, "/assets/a.js")
    assert st == 200 and "immutable" in h["Cache-Control"]
    assert call(srv, "/../../etc/passwd")[2] == b"<html>app</html>"  # never outside the page's folder


def test_tiles_and_the_3d_scene_are_kept_only_under_the_address_they_were_made_for(app):
    srv, pts = app
    s = srv.session
    wx, wy = s.grid.world_px(*pts[0])
    tile = f"/api/tiles/vector/{s.grid.zmax}/{int(wx // 256)}/{int(wy // 256)}.pbf"
    info = s.map_info()
    now = f"{info['tile_key']}-{info['model_version']}-{info['filter_version']}-{info['terrain_version']}"
    for path in (tile, "/api/scene3d"):
        assert "immutable" in call(srv, f"{path}?v={now}")[1]["Cache-Control"]  # made for it: kept
        # asked with an older address (the map changed since the page read it): answered from what is current, so
        # not kept under the old one (CodeRabbit: it stayed a year)
        st, h, _body = call(srv, f"{path}?v=older-0-0-0")
        assert st == 200 and h["Cache-Control"] == "no-store"
        # (the timelapse's tab asking for steps of a plan that isn't open: not kept either)
        assert call(srv, f"{path}?v={now}&r=7")[1]["Cache-Control"] == "no-store"


def test_the_backdrop_gets_the_ground_from_before_the_jobs_running_now(app):
    srv, pts = app
    s = srv.session
    wx, wy = s.grid.world_px(*pts[0])
    path = f"/api/tiles/terrain/{s.grid.zmax}/{int(wx // 256)}/{int(wy // 256)}.jpg"
    key, old = s.map_info()["tile_key"], s.terrain_version
    st, _h, before = call(srv, f"{path}?v={key}-{old}")
    assert st == 200
    canvas, weight, origin = s.terrain
    with s._lock:  # as the worker does when jobs begin, then a job's new map image
        s.pin_ground()
        s.set_terrain(canvas // 3, weight, origin, save=False, cities=False)
    new = s.terrain_version
    st, h, body = call(srv, f"{path}?v={key}-{old}")  # the backdrop's address: the old ground, kept
    assert st == 200 and body == before and "immutable" in h["Cache-Control"]
    st, h, body = call(srv, f"{path}?v={key}-{new}")  # the map's own: the new ground
    assert body != before and "immutable" in h["Cache-Control"]
    # an address of neither: the current ground, not kept under it (CodeRabbit: the new ground sat under the old
    # address a year, and a map image built again elsewhere put the backdrop off its place)
    st, h, other = call(srv, f"{path}?v={key}-{new + 40}")
    assert other == body and h["Cache-Control"] == "no-store"
    # another run of the app's address with this version's number (a tab outliving a restart): not kept either
    assert call(srv, f"{path}?v=0000beef.{s.opened.gen}-{new}")[1]["Cache-Control"] == "no-store"
    # past the map image's own levels the kept ground has nothing (its sharp ground reads the live atlas): the
    # current ground, not kept under the old address (CodeRabbit)
    deeper = f"/api/tiles/terrain/{s.grid.zmax + 1}/{int(wx // 128)}/{int(wy // 128)}.jpg"
    assert call(srv, f"{deeper}?v={key}-{old}")[1]["Cache-Control"] == "no-store"
    s._tile_before = None  # the jobs ended: the backdrop follows the current ground
    assert call(srv, f"{path}?v={key}-{old}")[1]["Cache-Control"] == "no-store"


def test_a_dropped_connection_is_not_printed_as_an_error(app, capsys):
    server, _pts = app
    for dropped in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        try:
            raise dropped("the tab was closed")
        except OSError:
            server.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""
    try:
        raise ValueError("a real fault")
    except ValueError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert "a real fault" in capsys.readouterr().err


def test_a_second_start_opens_the_running_app(app, monkeypatch, tmp_path):
    srv, _pts = app
    port = srv.server_address[1]
    opened, asked = [], []
    monkeypatch.setattr(S.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(S, "AtlasSession", lambda: pytest.fail("a second copy was started"))
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")  # a proxy that refuses: the probe goes direct
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert S.running_app(port) == (srv.url, S.VERSION)
    assert S.main(["--port", str(port)]) == 0 and opened == [srv.url]  # its page, not a second copy
    assert S.running_app(port, root=tmp_path) is None  # a copy of the program in another folder: not this one
    # an atlas asked for on the command line is opened by the running copy (it was dropped)
    (tmp_path / "b").mkdir()
    other, _p, _i = make_atlas(tmp_path / "b")
    monkeypatch.setattr(srv, "background", lambda fn: fn())  # (opened behind the answer: run at once here)
    monkeypatch.setattr(srv.session, "open_atlas", lambda p: asked.append(p))
    assert S.main(["--port", str(port), str(other)]) == 0
    assert asked == [str(other.resolve())]


def test_an_older_running_copy_is_closed_for_the_update(monkeypatch):
    # an older copy answers
    monkeypatch.setattr(S, "running_app", lambda port: ("http://127.0.0.1:1/", "1.0"))
    monkeypatch.setattr(S, "APP_QUIT_WAIT", 0.5)
    state = {"gone": False, "quits": 0}

    def fake(url, data=None, timeout=0):
        if url.endswith("api/quit"):
            state["quits"] += 1
            state["gone"] = state["obeys"]
            return {"ok": True}
        return None if state["gone"] else {"app": S.HELLO_APP}

    monkeypatch.setattr(S, "_local", fake)
    monkeypatch.setattr(S, "_stopped", lambda host, port: state["gone"])  # (gone: nothing listens there)
    state["obeys"] = True
    assert S.reuse_running(1, None, browser=False) == S.START and state["quits"] == 1  # it quit: the update starts
    state.update(gone=False, obeys=False)  # still closing after the wait: no second copy writing the same atlas
    assert S.reuse_running(1, None, browser=False) == S.FAILED


def test_the_start_runs_the_saved_detector(app_settings, monkeypatch):
    """The detector is the saved settings' (Log > Experimental), set as the app starts; only RF-DETR restarts the
    process with PyTorch's CUDA libraries first."""
    from grand_project.detect import detector_config, rf_detr_cuda

    restarted = []
    monkeypatch.setattr(rf_detr_cuda, "prefer_pip_cuda_libraries", lambda argv: restarted.append(argv))
    monkeypatch.setattr(S, "reuse_running", lambda port, atlas, browser: S.HANDED)  # (no server started)
    assert S.main(["--port", "1"]) == 0
    assert detector_config.current() == detector_config.DetectorConfig() and restarted == []  # nothing saved
    app_settings.write_text(json.dumps({"detection": {"rf_detr": True, "model": "me/model", "device": "cpu"}}))
    assert S.main(["--port", "1"]) == 0
    assert detector_config.current() == detector_config.DetectorConfig(rf_detr=True, model="me/model", device="cpu")
    assert restarted == [["--port", "1"]]


def test_the_page_learns_the_detector_it_can_choose(monkeypatch):
    """The Experimental tab's choices: the detector this run uses, what RF-DETR misses, the most workers."""
    from grand_project.detect import detector_config

    monkeypatch.setattr(detector_config, "rf_detr_missing", lambda: "torch")
    got = S.meta()["detection"]
    assert got["rf_detr_missing"] == "torch" and got["active"]["rf_detr"] is detector_config.current().rf_detr
    assert got["active"]["workers"] == min(detector_config.current().workers, got["max_workers"])  # (as many as run)
    assert got["max_workers"] >= 1 and got["devices"][0] == "auto" and got["default_model"]


def test_a_refused_atlas_hand_over_is_reported(app, monkeypatch, tmp_path):
    srv, _pts = app
    monkeypatch.setattr(S.webbrowser, "open", lambda url: None)

    monkeypatch.setattr(srv.session, "working", lambda: True)  # busy adding screenshots: it can't open another
    assert S.main(["--port", str(srv.server_address[1]), str(tmp_path / "x.json")]) == 1  # (it said success)


def test_the_start_doesnt_replace_an_atlas_opened_meanwhile(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _p, _i = make_atlas(tmp_path / "a")
    b, _p, _i = make_atlas(tmp_path / "b")
    session = AtlasSession(settings={}, worker=False)
    try:
        start = session.generation
        session.open_atlas(b)  # opened on the page before the start's atlas began loading
        S.open_first_atlas(session, str(a), start)
        assert session.path == b  # (it switched back to the start's atlas)
        # opened on the page while the start's atlas is being read: the start stops none of its work
        start = session.generation
        real_load, stopped = S.core.Atlas.load, []

        def load_while_b_opens(path):
            atlas = real_load(path)
            if Path(path) == a:
                session.open_atlas(b)
            return atlas

        monkeypatch.setattr(S.core.Atlas, "load", staticmethod(load_while_b_opens))
        monkeypatch.setattr(session, "stop_seams", lambda: stopped.append("seams"))
        monkeypatch.setattr(session, "stop_watch", lambda: stopped.append("watch"))
        monkeypatch.setattr(session, "seams_running", lambda: True)
        stopped.clear()
        session.settings["last_atlas"] = str(b)
        S.open_first_atlas(session, str(a), start)
        assert session.path == b and session.settings["last_atlas"] == str(b)
        assert stopped == ["watch", "seams"]  # B's own open only: the start stopped nothing of B's (it did, twice)
    finally:
        session.shutdown()


def test_something_else_on_a_port_doesnt_stop_the_start():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    def banner():
        conn, _ = sock.accept()
        conn.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")  # not HTTP: urlopen raised BadStatusLine through main
        conn.close()

    threading.Thread(target=banner, daemon=True).start()
    try:
        assert S._local(f"http://127.0.0.1:{port}/api/hello", timeout=2) is None
    finally:
        sock.close()


def test_free_ports_are_not_asked_when_looking_for_a_running_copy(monkeypatch):
    asked = []
    monkeypatch.setattr(S, "_local", lambda url, data=None, timeout=0: asked.append(url))
    monkeypatch.setattr(S, "_in_use", lambda host, port: False)  # every port free
    assert S.running_app(S.APP_PORT) is None and asked == []  # (each refused connection took ~2 s on Windows)


def test_a_quit_copy_counts_as_gone_though_its_port_wont_bind_yet(monkeypatch):
    import socket

    monkeypatch.setattr(S, "_in_use", lambda host, port: True)  # (Linux / macOS: TIME_WAIT keeps it unbindable)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        assert not S._stopped("127.0.0.1", port)  # still listening: not gone
    assert S._stopped("127.0.0.1", port)  # closed: the connection is refused, so it is gone (it waited out 40 s)
    monkeypatch.setattr(S, "running_app", lambda p: (f"http://127.0.0.1:{port}/", "1.0"))  # an older copy...
    monkeypatch.setattr(S, "_local", lambda url, data=None, timeout=0: {"ok": True})  # ...asked to quit
    assert S.reuse_running(port, None, browser=False) == S.START


def test_the_parts_answer_while_the_session_is_busy(app):
    srv, _pts = app
    with srv.session._lock:  # (a model being built holds it: the page still learns how far it is)
        status, _h, body = call(srv, "/api/parts")
    parts = json.loads(body)["parts"]
    # answered while the lock is held (the atlas's own background search may be rebuilding the model just now, so
    # its state isn't checked here)
    assert status == 200 and set(parts) == {"map_image", "model"}
    assert all(p["state"] in ("waiting", "building", "ready", "failed") for p in parts.values())


def test_one_launch_holds_the_start_lock_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(S.rc_paths, "USER_DATA", tmp_path)
    first = S.take_app_lock()
    assert first is not None and S.take_app_lock() is None  # a second launch at the same moment waits
    first.close()  # (the system lets go when the process ends)
    again = S.take_app_lock()
    assert again is not None
    again.close()


def test_a_launch_that_cant_take_the_lock_starts_no_second_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(S.rc_paths, "USER_DATA", tmp_path)
    monkeypatch.setattr(S, "reuse_running", lambda port, atlas, browser: S.START)  # none found yet
    monkeypatch.setattr(S, "running_app", lambda port: None)  # and the other launch never answers
    monkeypatch.setattr(S, "APP_QUIT_WAIT", 0.3)
    monkeypatch.setattr(S, "AtlasSession", lambda: pytest.fail("a second copy was started"))
    held = S.take_app_lock()
    try:
        assert S.main(["--port", "1", "--no-browser"]) == 1  # (both started and wrote the same atlas)
    finally:
        held.close()


def test_a_launch_without_the_lock_finds_the_copy_on_its_recorded_port(app, tmp_path, monkeypatch):
    srv, _pts = app
    monkeypatch.setattr(S.rc_paths, "USER_DATA", tmp_path)
    (tmp_path / S.APP_URL_FILE).write_text(srv.url, encoding="utf-8")  # started on a port outside the default range
    monkeypatch.setattr(S.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(S, "AtlasSession", lambda: pytest.fail("a second copy was started"))
    held = S.take_app_lock()
    try:
        assert S.main(["--no-browser"]) == 0  # handed over (it waited out 40 s and gave up)
    finally:
        held.close()


def test_the_log_skips_tiles_and_takes_the_page_s_lines(app, caplog):
    srv, pts = app
    s = srv.session
    wx, wy = s.grid.world_px(*pts[0])
    with caplog.at_level(logging.DEBUG, logger=S.LOG.name):
        call(srv, f"/api/tiles/terrain/{s.grid.zmax}/{int(wx // 256)}/{int(wy // 256)}.jpg?v=1")
        call(srv, "/api/state")
        call(srv, "/api/log", "POST", {"lines": ["Opened the Bookmarks tab", "Add bookmark started"]})
        call(srv, "/api/pick", "POST", {"x": pts[5][0], "y": pts[5][1], "z": 1.0})
    text = caplog.text
    assert "/api/tiles/" not in text and "GET /api/state" in text  # thousands of tiles a session hid the rest
    assert "Opened the Bookmarks tab" in text and "Add bookmark started" in text and "POST /api/log" not in text
    assert "click at" in text and "node 5" in text


def test_the_page_s_log_lines_and_group_names_are_checked(app, caplog):
    srv, _pts = app
    assert call(srv, "/api/log", "POST", {"lines": "not a list"})[0] == 400
    assert call(srv, "/api/groups/delete", "POST", {"names": "Farm"})[0] == 400
    with caplog.at_level(logging.INFO, logger=S.LOG.name):
        call(srv, "/api/log", "POST", {"lines": ["two\nlines"]})
    assert "two lines" in caplog.text


def test_the_start_line_names_the_release_in_a_player_release(tmp_path, monkeypatch):
    # (v1.xx counts develop's merges; players only ever see release numbers: user)
    import json

    from grand_project import paths as rc_paths
    from grand_project.app import server as srv

    (tmp_path / "manifest.json").write_text(json.dumps({"release": "1.3.1", "program": "1.29", "files": {}}))
    monkeypatch.setattr(rc_paths, "ROOT", tmp_path)
    monkeypatch.setattr(rc_paths, "CHANNEL", "release")
    assert srv.shown_version() == "release 1.3.1"
    monkeypatch.setattr(rc_paths, "CHANNEL", "internal")
    assert srv.shown_version() == f"v{srv.VERSION}"
