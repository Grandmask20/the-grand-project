"""The app's web server (app.server.AppServer): the JSON API, tiles, the event stream, safety checks, the page."""

import json
import threading
import urllib.error
import urllib.request

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
    monkeypatch.setattr(srv.session, "open_atlas", lambda p: asked.append(p))
    assert S.main(["--port", str(port), str(other)]) == 0
    assert asked == [str(other.resolve())]


def test_an_older_running_copy_is_closed_for_the_update(app, monkeypatch):
    srv, _pts = app
    port = srv.server_address[1]
    quits = []
    monkeypatch.setattr(S, "running_app", lambda port: (srv.url, "1.0"))  # an older copy answers there
    monkeypatch.setattr(srv, "quit", lambda: quits.append(1))
    monkeypatch.setattr(S, "APP_QUIT_WAIT", 0.5)
    assert S.reuse_running(port, None, browser=False) is False  # starts normally (the old copy was reused)
    assert quits == [1]


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


def test_looking_for_a_running_copy_is_quick_on_free_ports():
    import time

    t0 = time.perf_counter()
    assert S.running_app(S.APP_PORT + 500) is None
    assert time.perf_counter() - t0 < 1.0  # (a refused connection takes ~2 s on Windows: 20 ports made starts ~10 s)
