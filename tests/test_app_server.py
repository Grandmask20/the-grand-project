"""The app's web server (app.server.AppServer): the JSON API, tiles, the event stream, safety checks, the page."""

import json
import logging
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
    # the classical detector, whatever this machine's setting (an RF-DETR one would answer True and be restarted)
    from grand_project.detect import rf_detr_model

    monkeypatch.setattr(rf_detr_model, "rf_detr_enabled", lambda: False)
    assert S.running_app(port) == (srv.url, S.VERSION, False)
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
    monkeypatch.setattr(S, "running_app", lambda port: ("http://127.0.0.1:1/", "1.0", False))
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


def test_a_start_with_another_detector_says_the_running_copy_keeps_its_own(monkeypatch, capsys):
    """A start with GRAND_PROJECT_USE_RF_DETR finds a copy running the classical detector: it hands over and says the
    flag was not applied (it was reused silently: CodeRabbit)."""
    from grand_project.detect import constants as DK

    monkeypatch.setattr(S, "running_app", lambda port: ("http://127.0.0.1:1/", S.VERSION, False))
    monkeypatch.setenv(DK.RF_DETR_USE_ENV, "1")
    assert S.reuse_running(1, None, browser=False) == S.HANDED
    assert "uses the classical detector" in capsys.readouterr().out
    monkeypatch.setattr(S, "running_app", lambda port: ("http://127.0.0.1:1/", S.VERSION, True))
    assert S.reuse_running(1, None, browser=False) == S.HANDED
    assert "detector" not in capsys.readouterr().out  # the same detector: nothing to say


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
    monkeypatch.setattr(S, "running_app", lambda p: (f"http://127.0.0.1:{port}/", "1.0", False))  # an older copy...
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


# ------------------------------------------------------------------ uploads arriving at once


def test_pictures_uploaded_at_once_under_one_name_each_keep_their_own_file(tmp_path, runs):
    # the free name was checked, then written: two pictures dropped together under one name could both find it free
    # and the second overwrote the first (one screenshot lost, both answered with the same path)
    old = S.sys.getswitchinterval()
    S.sys.setswitchinterval(1e-6)  # threads switch as often as they can: the race shows up in a few rounds
    try:
        for r in range(runs(20)):
            folder = tmp_path / str(r)
            folder.mkdir()
            pictures = [bytes([k]) * (1 + k) for k in range(8)]
            start = threading.Barrier(len(pictures))
            saved: dict[int, Path] = {}

            def upload(k: int, folder=folder, start=start, saved=saved, pictures=pictures) -> None:
                start.wait(5)
                saved[k] = S.save_upload(folder, "shot.png", pictures[k])

            threads = [threading.Thread(target=upload, args=(k,)) for k in range(len(pictures))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            assert len(set(saved.values())) == len(pictures), f"round {r}: two pictures were given one file"
            for k, path in saved.items():
                assert path.read_bytes() == pictures[k], f"round {r}: a picture was overwritten"
    finally:
        S.sys.setswitchinterval(old)


def test_the_same_picture_uploaded_again_keeps_its_file(tmp_path):
    first = S.save_upload(tmp_path, "shot.png", b"one")
    other = S.save_upload(tmp_path, "shot.png", b"two")
    assert S.save_upload(tmp_path, "shot.png", b"one") == first != other
    assert sorted(p.read_bytes() for p in tmp_path.iterdir()) == [b"one", b"two"]


def test_an_upload_that_fails_as_its_file_closes_leaves_no_cut_off_picture(tmp_path, monkeypatch):
    """A full disk can fail the close (its flush) as well as the write: the file this upload made is removed, a
    picture already there under the name is kept (CodeRabbit)."""
    real = open

    class FailingClose:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()
            raise OSError("disk full")

        def write(self, data):
            return self.f.write(data)

    (tmp_path / "shot.png").write_bytes(b"one")
    monkeypatch.setattr(S, "open", lambda path, mode: FailingClose(real(path, mode)), raising=False)
    with pytest.raises(OSError, match="disk full"):
        S.save_upload(tmp_path, "shot.png", b"two")
    assert [(p.name, p.read_bytes()) for p in tmp_path.iterdir()] == [("shot.png", b"one")]


def test_a_second_drop_waits_until_the_first_writer_has_closed_its_file(tmp_path, monkeypatch):
    """The same picture dropped twice: the second gets the file only once the first upload closed it (it found it
    whole while the writer was still open, whose close could still fail and remove it: CodeRabbit)."""
    import threading

    real = open
    writing, release = threading.Event(), threading.Event()

    class SlowClose:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            writing.set()
            release.wait(5)
            self.f.close()

        def write(self, data):
            self.f.write(data)
            self.f.flush()  # the bytes are in the file: a reader would take it for whole

    monkeypatch.setattr(S, "open", lambda path, mode: SlowClose(real(path, mode)), raising=False)
    got = {}
    first = threading.Thread(target=lambda: got.setdefault("first", S.save_upload(tmp_path, "shot.png", b"one")))
    first.start()
    assert writing.wait(5)
    second = threading.Thread(target=lambda: got.setdefault("second", S.save_upload(tmp_path, "shot.png", b"one")))
    second.start()
    second.join(0.3)
    assert second.is_alive()  # waits for the first writer
    release.set()
    first.join(5)
    second.join(5)
    assert got["first"] == got["second"] == tmp_path / "shot.png"


def test_an_upload_for_the_atlas_switched_away_while_it_came_in_is_refused(app, tmp_path):
    import http.client

    srv, _pts = app
    (tmp_path / "b").mkdir()
    b, _pts_b, _img = make_atlas(tmp_path / "b")
    a_folder = srv.session.path.parent
    before = {p.name for p in a_folder.iterdir()} | {p.name for p in b.parent.iterdir()}
    data = b"\x89PNG" + b"x" * 1000
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=10)
    conn.putrequest("POST", "/api/upload")
    for k, v in {
        "X-Grand": "1",
        "X-Filename": "late.png",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(data)),
        S.GEN_HEADER: str(srv.session.generation),  # made for atlas A
    }.items():
        conn.putheader(k, v)
    conn.endheaders()
    conn.send(data[:100])
    srv.session.open_atlas(b)  # B opens while the picture is still coming in
    conn.send(data[100:])
    res = conn.getresponse()
    assert res.status == 409 and json.loads(res.read())["stale"]
    conn.close()
    after = {p.name for p in a_folder.iterdir()} | {p.name for p in b.parent.iterdir()}
    assert after == before  # saved in neither atlas's folder
