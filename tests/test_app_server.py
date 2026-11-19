"""The app's web server (app.server.AppServer): the JSON API, tiles, the event stream, safety checks, the page."""

import json
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


def test_tiles_over_http(app):
    srv, pts = app
    s = srv.session
    wx, wy = s.grid.world_px(*pts[0])
    z = s.grid.zmax
    st, h, body = call(srv, f"/api/tiles/terrain/{z}/{int(wx // 256)}/{int(wy // 256)}.jpg?v=1")
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
    assert [r["kind"] for r in res] == ["bookmark"]
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
    monkeypatch.setattr(S, "running_app", lambda port: ("http://127.0.0.1:1/", "1.0"))  # an older copy answers
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
    assert status == 200 and parts["map_image"]["state"] == "ready" and parts["model"]["state"] == "ready"
