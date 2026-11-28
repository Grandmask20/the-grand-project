"""app.server: the app's local web server: the JSON API, the live event stream, the map's tiles and the page.

Standard library only (http.server, one thread per request). It listens on 127.0.0.1 only. Requests that change
something must carry the X-Grand header (a page from another site can't add it without the server's leave, which it
never gives), and the Host header must be this server, so another site can't reach it through DNS tricks.

    python -m grand_project [atlas.json] [--port N] [--no-browser]
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import mimetypes
import os
import queue
import re
import select
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from grand_project import core
from grand_project import logs as atlas_log
from grand_project import paths as rc_paths
from grand_project.webmap.constants import WEBMAP_ICON_SPRITE

from .constants import (
    APP_HELLO_WAIT,
    APP_HOST,
    APP_LOCK_FILE,
    APP_PORT,
    APP_PORT_TRIES,
    APP_QUIT_WAIT,
    APP_STOP_PROBE,
    APP_URL_FILE,
    HELLO_APP,
    STATE_TRIES,
    UPLOAD_MAX,
    VERSION,
)
from .debug import DEBUG_REASONS
from .events import StaleAtlas, sse
from .icons import icon_png
from .library import list_dir, thumb_file
from .replay_data import spread_colours
from .session import AtlasSession

LOG = atlas_log.get("app")

DIST = rc_paths.ROOT / "frontend" / "dist"
SSE_PING_S = 15.0
HEADER = "X-Grand"
GEN_HEADER = "X-Atlas-Gen"  # the open atlas's generation: on every answer, and on the page's changes
# changes that don't belong to one atlas (switching atlas itself, settings, the atlas list, answers, quitting)
GEN_FREE = (
    "/api/atlas/open",
    "/api/atlas/new",
    "/api/atlas/recheck-file",
    "/api/atlas/folder",
    "/api/atlases",
    "/api/settings",
    "/api/quit",
    "/api/questions/",
    "/api/replay/close",
    "/api/update",
)


class ApiError(Exception):
    """An error answered to the page as {"error": message} with a status code."""

    def __init__(self, message: str, status: int = 400):
        """Keep the message and status.

        Args:
            message: What went wrong (shown to the user).
            status: HTTP status.
        """
        super().__init__(message)
        self.status = status


ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    """Register a handler method for a method and path pattern (named groups become keyword arguments).

    Args:
        method: "GET", "POST", "PATCH" or "DELETE".
        pattern: Regular expression for the whole path.

    Returns:
        The decorator.
    """

    def deco(fn):
        """Register fn."""
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn.__name__))
        return fn

    return deco


def _num(q: dict, key: str, default=None, cast=float):
    """Read a number from the query string.

    Args:
        q: Parsed query (parse_qs).
        key: The name.
        default: Value when missing.
        cast: float or int.

    Returns:
        The number.

    Raises:
        ApiError: When it is not a number.
    """
    if key not in q:
        if default is None:
            raise ApiError(f"missing {key}")
        return default
    try:
        return cast(q[key][0])
    except ValueError as e:
        raise ApiError(f"{key} must be a number") from e


class Handler(BaseHTTPRequestHandler):
    """One request (see the module docstring). The session is the server's `session`."""

    server_version = f"GrandProject/{VERSION}"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ plumbing
    @property
    def S(self) -> AtlasSession:
        """Return the session."""
        return self.server.session  # type: ignore[attr-defined]

    def log_message(self, fmt, *args) -> None:
        """Log requests at debug level; a map tile only when it failed (thousands a session: 6000 of a session's
        lines were tiles, hiding what happened, user)."""
        served = str(args[1]) if len(args) > 1 else ""
        # (204: no ground there; the page's own log lines are in the log already)
        if (
            args
            and (" /api/tiles/" in str(args[0]) or " /api/log " in str(args[0]))
            and served in ("200", "204", "304")
        ):
            return
        LOG.debug("http: " + fmt, *args)

    def _host_ok(self) -> bool:
        """Tell whether the Host header names this server (no DNS rebinding)."""
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        """Send a whole response.

        Args:
            status: HTTP status.
            body: The body.
            ctype: Content-Type.
            extra: More headers.
        """
        if not self._read_body and int(self.headers.get("Content-Length") or 0) > 0:
            # a body nobody read (a refused request) would be taken for the next request on this connection
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # the atlas the answer was made from when the handler knows it, else the open one (read again here, it could
        # stamp one atlas's state with the next one's generation: GPT audit)
        self.send_header(GEN_HEADER, str(self._resp_gen if self._resp_gen is not None else self.S.generation))
        if self.close_connection:
            self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _still_connected(self) -> bool:
        """Tell whether the browser still waits for this answer (it closes the connection when it gives a tile up).

        Returns:
            False when the connection was closed or reset.
        """
        try:
            readable, _w, _x = select.select([self.connection], [], [], 0)
            if not readable:
                return True
            return self.connection.recv(1, socket.MSG_PEEK) != b""  # readable with nothing: closed
        except (OSError, ValueError):
            return False

    def _json(self, data, status: int = 200) -> None:
        """Send JSON.

        Args:
            data: JSON-able data.
            status: HTTP status.
        """
        self._send(status, json.dumps(data, default=_jsonable).encode(), "application/json",
                   {"Cache-Control": "no-store"})  # fmt: skip

    def _bytes(self, data: bytes | None, ctype: str, cache: bool = True) -> None:
        """Send binary data (204 when None).

        Args:
            data: The bytes, or None.
            ctype: Content-Type.
            cache: Let the browser keep it (versioned URLs).
        """
        if data is None:
            self._send(204, b"", ctype, {"Cache-Control": "no-store"})
            return
        cc = "public, max-age=31536000, immutable" if cache else "no-store"
        self._send(200, data, ctype, {"Cache-Control": cc})

    def _body(self) -> dict:
        """Read a JSON body.

        Returns:
            The object ({} when empty).

        Raises:
            ApiError: When it is not JSON.
        """
        n = int(self.headers.get("Content-Length") or 0)
        if n > UPLOAD_MAX:
            raise ApiError("request too large", 413)
        raw = self.rfile.read(n) if n else b""
        self._read_body = True
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ApiError("the request body is not JSON") from e
        if not isinstance(data, dict):
            raise ApiError("the request body must be an object")
        return data

    def _dispatch(self, method: str) -> None:
        """Answer a request: the API, else a file of the page.

        Args:
            method: The HTTP method.
        """
        self._read_body = False  # per request (the handler lives as long as its keep-alive connection)
        self._resp_gen = None  # the atlas an answer was made from (_send's header), when the handler knows it
        if not self._host_ok():
            self._json({"error": "wrong host"}, 403)
            return
        url = urlparse(self.path)
        path = unquote(url.path)
        if not path.startswith("/api/"):
            if method in ("GET", "HEAD"):
                self._static(path)
            else:
                self._json({"error": "not found"}, 404)
            return
        stale = self.headers.get(GEN_HEADER)
        if (
            method not in ("GET", "HEAD")
            and stale is not None
            and stale != str(self.S.generation)
            and not path.startswith(GEN_FREE)
        ):
            # a change the page made for the atlas open before (a bookmark id, a lasso, a placement): not applied to
            # the one open now (user, CodeRabbit)
            self._json({"error": "the atlas changed", "stale": True}, 409)
            return
        if method not in ("GET", "HEAD") and self.headers.get(HEADER) != "1":
            self._json({"error": f"missing {HEADER} header"}, 403)
            return
        # the atlas this request was made for: its header, else the one open as it came in (a switch while it is
        # handled refuses its change: CodeRabbit)
        self._req_gen = int(stale) if stale is not None and stale.isdigit() else self.S.generation
        q = parse_qs(url.query)
        # a change is for its atlas: every edit it makes checks that atlas under the session lock, in the same step
        # (AtlasLock; checked only here before, a switch in between got the edit: GPT audit)
        changes = method not in ("GET", "HEAD") and not path.startswith(GEN_FREE)
        for m, rx, name in ROUTES:
            if m != ("GET" if method == "HEAD" else method):
                continue
            hit = rx.match(path)
            if hit:
                try:
                    with self.S._lock.expect(self._req_gen) if changes else contextlib.nullcontext():
                        getattr(self, name)(q, **hit.groupdict())
                except ApiError as e:
                    self._json({"error": str(e)}, e.status)
                except StaleAtlas:
                    self._json({"error": "the atlas changed", "stale": True}, 409)
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                except ConnectionError:  # the browser gave up on it (tiles while zooming): nothing to report
                    pass
                except Exception as e:
                    LOG.exception(f"{method} {path} failed")
                    with contextlib.suppress(OSError):
                        self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                return
        self._json({"error": "not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802
        """GET."""
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        """HEAD."""
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        """POST."""
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        """PATCH."""
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        """DELETE."""
        self._dispatch("DELETE")

    def _static(self, path: str) -> None:
        """Send a file of the built page (frontend/dist); unknown paths get index.html (the page routes itself).

        Args:
            path: The URL path.
        """
        root = DIST.resolve()
        f = (root / path.lstrip("/")).resolve()
        if not f.is_relative_to(root) or not f.is_file():
            f = root / "index.html"
        if not f.is_file():
            msg = (
                "<h1>The page isn't built</h1><p>Run <code>npm install</code> and <code>npm run build</code> in "
                "<code>frontend/</code> (or use a release, which has it built).</p>"
            )
            self._send(503, msg.encode(), "text/html; charset=utf-8")
            return
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if "/assets/" in f.as_posix() else "no-cache"
        self._send(200, f.read_bytes(), ctype, {"Cache-Control": cache})

    # ------------------------------------------------------------------ state and events
    @route("GET", "/api/state")
    def get_state(self, q) -> None:
        """The app's state (atlas, versions, work, lists, questions, log)."""
        # all of it from one atlas: made again when another was opened while it was put together (the lock isn't
        # taken: a job placing screenshots holds it for long), and stamped with that atlas (GPT audit)
        for _ in range(STATE_TRIES):
            gen = self.S.generation
            st = self.S.state()
            st["debug"] = bool(rc_paths.DEBUG)
            st["settings"] = self.S.ui_settings()
            st["map"] = self.S.map_info()
            if self.S.generation == gen:
                break
        else:  # another atlas opened during every try: refused (the page asks again), never a mix (CodeRabbit)
            raise StaleAtlas()
        self._resp_gen = gen
        self._json(st)

    @route("GET", "/api/events")
    def get_events(self, q) -> None:
        """The live event stream (Server-Sent Events)."""
        lq = self.S.events.listen()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while not self.server.stopping and not getattr(lq, "dropped", False):  # type: ignore[attr-defined]
                try:
                    ev = lq.get(timeout=SSE_PING_S)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(sse(ev))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.S.events.stop_listening(lq)

    @route("POST", r"/api/questions/(?P<qid>\d+)")
    def post_answer(self, q, qid) -> None:
        """Answer a question ({"yes"}, and "picked" for one with ticks)."""
        body = self._body()
        ok = self.S.events.answer(int(qid), bool(body.get("yes")), picked=body.get("picked"))
        self._json({"ok": ok})

    @route("GET", "/api/parts")
    def get_parts(self, q) -> None:
        """How far the map's parts are (the page's loading cover asks while it waits): never waits on the session."""
        self._json(self.S.parts.payload())

    @route("GET", "/api/hello")
    def get_hello(self, q) -> None:
        """Which program answers here and with which detector (a second start finds the copy already running:
        running_app)."""
        from grand_project.detect.rf_detr_model import rf_detr_enabled

        root = str(rc_paths.ROOT.resolve())
        self._json({"app": HELLO_APP, "version": VERSION, "root": root, "rf_detr": rf_detr_enabled()})

    @route("GET", "/api/meta")
    def get_meta(self, q) -> None:
        """What the page draws with and offers: colours, kinds, types, replay and style choices."""
        self._json(meta())

    @route("GET", "/api/settings")
    def get_settings(self, q) -> None:
        """The page's settings."""
        self._json(self.S.ui_settings())

    @route("PATCH", "/api/settings")
    def patch_settings(self, q) -> None:
        """Change the page's settings."""
        self._json(self.S.set_ui_settings(self._body()))

    @route("POST", "/api/log")
    def post_log(self, q) -> None:
        """What was done on the page (tabs, modes, selections, dialogs, errors shown): into the log file."""
        lines = self._body().get("lines", [])
        if not isinstance(lines, list):
            raise ValueError("lines must be a list")
        # into the log of the atlas the request was made for, checked with no switch possible meanwhile (checked
        # first and written later, a switch while the body was read put the lines in the next atlas's log:
        # CodeRabbit); a request for another atlas is refused
        with self.S._lock.steady():
            scope = self.S.opened.scope
            for line in lines[:50]:
                # one line each (a line break in a name made two), not too long
                self.S.events.log(" ".join(str(line).split())[:500], scope)  # (the Log tab and the log file: user)
        self._json({"ok": True})

    # ------------------------------------------------------------------ the in-app update (app/updater.py)
    @route("GET", "/api/update")
    def get_update(self, q) -> None:
        """The update's state: this copy's release, the latest one, a download going on."""
        self._json(self.S.update_status())

    @route("POST", "/api/update/check")
    def post_update_check(self, q) -> None:
        """Ask GitHub for the latest release (the answer comes as an "update" event)."""
        self.S.check_update()
        self._json(self.S.update_status())

    @route("POST", "/api/update/install")
    def post_update_install(self, q) -> None:
        """Download the latest release and hand over to the helper that puts it in place (the app restarts)."""
        try:
            port = str(self.server.server_address[1])  # (the restart comes back on it: the page reconnects)
            self.S.install_update(quit_app=self.server.quit, restart_args=["--port", port])  # type: ignore[attr-defined]
        except ValueError as e:
            raise ApiError(str(e), 409) from e
        self._json(self.S.update_status())

    @route("POST", "/api/update/auto")
    def post_update_auto(self, q) -> None:
        """Check at start (once a day), or only when asked."""
        self.S.set_update_auto(bool(self._body().get("on")))
        self._json(self.S.update_status())

    @route("POST", "/api/quit")
    def post_quit(self, q) -> None:
        """Save everything and stop the app."""
        self._json({"ok": True})
        threading.Thread(target=self.server.quit, daemon=True).start()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ atlases
    @route("GET", "/api/atlases")
    def get_atlases(self, q) -> None:
        """The Saved atlases cards."""
        self._json(self.S.atlases_payload())

    @route("GET", "/api/atlases/thumb")
    def get_thumb(self, q) -> None:
        """An atlas card's picture."""
        f = thumb_file(q.get("json", [""])[0])
        self._bytes(f.read_bytes() if f.is_file() else None, "image/png", cache=False)

    @route("POST", "/api/atlases/rename")
    def post_rename(self, q) -> None:
        """Rename a known atlas."""
        b = self._body()
        self.S.rename_atlas(b["json"], b["name"])
        self._json({"ok": True})

    @route("POST", "/api/atlases/show-folder")
    def post_show_folder(self, q) -> None:
        """Open a known atlas's folder in the system's file browser."""
        self.S.show_atlas_folder(self._body()["json"])
        self._json({"ok": True})

    @route("POST", "/api/atlases/forget")
    def post_forget(self, q) -> None:
        """Stop tracking an atlas."""
        self.S.forget_atlas(self._body()["json"])
        self._json({"ok": True})

    @route("POST", "/api/atlases/delete")
    def post_delete_atlas(self, q) -> None:
        """Delete an atlas and its data."""
        self._json({"failed": self.S.delete_atlas(self._body()["json"])})

    @route("POST", "/api/atlas/open")
    def post_open(self, q) -> None:
        """Open an atlas file (with "background": answered at once, opened behind: another start handing it over)."""
        body = self._body()
        if body.get("background"):
            # checked now (busy adding: refused, and the start says so), opened behind the page: the start
            # handing it over waited for the whole open, and a big atlas outlasted its wait (banner, user)
            if self.S.working():
                raise ValueError("wait until the screenshots being added are done")
            path = body["path"]

            def open_it() -> None:
                try:
                    self.S.open_atlas(path)
                except ValueError as e:
                    self.S.events.log(str(e))

            self.server.background(open_it)  # type: ignore[attr-defined]
            self._json({"ok": True})
            return
        self.S.open_atlas(body["path"])
        self._json(self.S.atlas_summary())

    @route("POST", "/api/atlas/new")
    def post_new(self, q) -> None:
        """Create an atlas."""
        self.S.new_atlas(self._body()["path"])
        self._json(self.S.atlas_summary())

    @route("POST", "/api/atlas/folder")
    def post_folder(self, q) -> None:
        """Open a screenshot folder's atlas (or say how many screenshots a new one would take)."""
        self._json(self.S.open_folder(self._body()["folder"]))

    @route("POST", "/api/atlas/folder/create")
    def post_folder_create(self, q) -> None:
        """Make an atlas in a screenshot folder from all its screenshots."""
        self._json({"adding": self.S.create_from_folder(self._body()["folder"])})

    @route("POST", "/api/atlas/save")
    def post_save(self, q) -> None:
        """Save the atlas."""
        self.S.save()
        self.S.events.set_status(f"saved {self.S.path}" if self.S.path else "nothing to save")
        self._json({"ok": True})

    @route("POST", "/api/atlas/close")
    def post_close(self, q) -> None:
        """Close the atlas."""
        if self.S.working():
            raise ApiError("wait until the screenshots being added are done")
        self.S.close()
        self._json({"ok": True})

    @route("POST", "/api/atlas/export")
    def post_export(self, q) -> None:
        """Write the map PNGs."""
        self._json({"files": self.S.export_pngs()})

    @route("POST", "/api/atlas/recheck")
    def post_recheck(self, q) -> None:
        """Re-check the whole atlas."""
        self.S.recheck_all()
        self._json({"ok": True})

    @route("GET", "/api/atlas/recheck-info")
    def get_recheck_info(self, q) -> None:
        """What the Re-check prompt says about an atlas (?path=: another one than the open one, read, not opened)."""
        self._json(self.S.recheck_info(q.get("path", [None])[0] or None))

    @route("POST", "/api/atlas/recheck-file")
    def post_recheck_file(self, q) -> None:
        """Re-check an atlas from the Atlases tab ({"path"}: opened first when another one is open)."""
        path = self._body().get("path")
        if not path:
            raise ApiError("no atlas given")
        self.S.recheck_atlas(path)
        self._json({"ok": True})

    @route("POST", "/api/seams")
    def post_seams(self, q) -> None:
        """Start Fix seams; while adding runs, {"adding": true} and not started (the page asks), or queued after
        it with {"after_adding": true}."""
        how = self.S.fix_seams(after_adding=bool(self._body().get("after_adding")))
        self._json({"ok": how != "adding", "adding": how == "adding", "queued": how == "queued"})

    @route("DELETE", "/api/seams")
    def delete_seams(self, q) -> None:
        """Stop Fix seams."""
        self.S.stop_seams()
        self._json({"ok": True})

    # ------------------------------------------------------------------ files on this computer
    @route("GET", "/api/fs")
    def get_fs(self, q) -> None:
        """List a folder for the file pickers."""
        self._json(list_dir(q.get("path", [""])[0], files=q.get("files", ["1"])[0] != "0"))

    @route("POST", "/api/upload")
    def post_upload(self, q) -> None:
        """Save a screenshot dropped on the page into the open atlas's folder (the raw file is the body)."""
        if not self.S.path:
            raise ApiError("open or create an atlas first")
        name = Path(unquote(self.headers.get("X-Filename") or "")).name
        if not name or Path(name).suffix.lower() not in core.IMAGE_EXT:
            raise ApiError("drop screenshot image files (.png, .jpg)")
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > UPLOAD_MAX:
            raise ApiError("the file is empty or too large", 413)
        gen = self._req_gen  # (read before the body: it can take a while)
        data = self.rfile.read(n)
        self._read_body = True
        with self.S._lock:
            opened = self.S.opened
            if not self.S.owns(gen) or opened.path is None:  # another atlas opened while it came in (CodeRabbit)
                raise StaleAtlas()
        # (the folder of the atlas it was checked for, from its own record)
        self._json({"path": str(save_upload(opened.path.parent, name, data))})

    # ------------------------------------------------------------------ adding screenshots
    @route("POST", "/api/screenshots")
    def post_screenshots(self, q) -> None:
        """Add screenshot files."""
        paths = [p for p in self._body().get("paths", []) if core.is_screenshot(Path(p))]
        if not paths:
            raise ApiError("no screenshot files")
        self.S.add_screenshots(paths)
        self._json({"queued": len(paths)})

    @route("POST", "/api/ghost")
    def post_ghost(self, q) -> None:
        """Make the see-through picture of a screenshot to place by hand."""
        self._json(self.S.ghost(self._body()["path"]))

    @route("GET", r"/api/pictures/(?P<pid>\d+)\.png")
    def get_picture(self, q, pid) -> None:
        """A kept picture (ghost / preview): not cached, its id restarts with each run (CodeRabbit)."""
        self._bytes(self.S.picture(int(pid)), "image/png", cache=False)

    @route("POST", "/api/place")
    def post_place(self, q) -> None:
        """Line up a screenshot placed by hand."""
        b = self._body()
        self.S.place_by_hand(b["path"], float(b["x"]), float(b["y"]))
        self._json({"ok": True})

    @route("POST", "/api/undo")
    def post_undo(self, q) -> None:
        """Undo the last add."""
        self._json({"names": self.S.undo_last()})

    @route("POST", "/api/waiting/retry")
    def post_retry(self, q) -> None:
        """Retry waiting screenshots."""
        self._json({"retrying": self.S.retry_waiting(self._body().get("indices"))})

    @route("POST", "/api/waiting/take")
    def post_take(self, q) -> None:
        """Take a waiting screenshot out to place it by hand."""
        self._json({"path": self.S.take_waiting(int(self._body()["index"]))})

    @route("GET", "/api/recent")
    def get_recent(self, q) -> None:
        """Outlines of the recent additions."""
        self._json(self.S.recent_outlines())

    @route("POST", "/api/recent/goto")
    def post_recent_goto(self, q) -> None:
        """Where a recently added screenshot is (and outline it)."""
        c = self.S.frame_centre(self._body()["name"])
        if c is None:
            raise ApiError("no such screenshot", 404)
        self._json({"centre": c})

    @route("POST", "/api/watch")
    def post_watch(self, q) -> None:
        """Turn auto-add on or off."""
        self.S.set_watch(bool(self._body().get("on")))
        self._json(self.S.watch_state())

    @route("POST", "/api/watch/folder")
    def post_watch_folder(self, q) -> None:
        """Pick the watched folder (null: the atlas's own)."""
        self.S.set_watch_folder(self._body().get("folder"))
        self._json(self.S.watch_state())

    # ------------------------------------------------------------------ the map
    @route("GET", "/api/map")
    def get_map(self, q) -> None:
        """The map's grid and versions."""
        self._json(self.S.map_info())

    @route("GET", r"/api/tiles/terrain/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.jpg")
    def get_terrain_tile(self, q, z, x, y) -> None:
        """A ground tile."""
        self._bytes(self.S.terrain_tile(int(z), int(x), int(y), self._still_connected), "image/jpeg")

    @route("GET", "/api/crop")
    def get_crop(self, q) -> None:
        """A small picture of the ground around a spot (Find's rows), for the atlas of generation `g` only."""
        data = self.S.crop_jpeg(_num(q, "x"), _num(q, "y"), _num(q, "g", -1, int))
        # not kept by the browser: its address (generation, map image version) starts over with each run of the app, so
        # another atlas's crop could match it later (CodeRabbit)
        self._bytes(data, "image/jpeg", cache=False)

    @route("GET", r"/api/tiles/vector/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.pbf")
    def get_vector_tile(self, q, z, x, y) -> None:
        """A vector tile."""
        replay = bool(q.get("r", [""])[0])  # the tab playing the timelapse
        self._bytes(self.S.vector_tile(int(z), int(x), int(y), replay), "application/x-protobuf")

    @route("GET", "/api/scene3d")
    def get_scene_3d(self, q) -> None:
        """The 3D view's icons, paths and models, whole (versioned URL: kept by the browser)."""
        replay = bool(q.get("r", [""])[0])  # the tab playing the timelapse
        self._bytes(self.S.scene_3d(replay), "application/json")

    @route("GET", r"/api/icons/(?P<name>[^/]+)\.png")
    def get_icon(self, q, name) -> None:
        """An icon type's picture: "sprite" for the map (badge art), else the list picture."""
        size = max(8, min(256, _num(q, "size", 32, int)))
        # the map's pictures are the list's, at the sprite size: every icon cut to its rim the same way (the badge art
        # kept its margins, so some icons were drawn smaller than others: user)
        if q.get("kind", [""])[0] == "sprite":
            size = WEBMAP_ICON_SPRITE
        self._bytes(icon_png(name, size, q.get("style", ["game art"])[0]), "image/png")

    @route("GET", "/api/graph")
    def get_graph(self, q) -> None:
        """The map graph for routes."""
        self._json(self.S.graph())

    @route("POST", "/api/pick")
    def post_pick(self, q) -> None:
        """What is under a point."""
        b = self._body()
        hit = self.S.pick(float(b["x"]), float(b["y"]), float(b["z"]), b.get("layers"))
        info = None if hit is None else self.S.info(*hit)
        LOG.info(
            "click at (%.0f, %.0f): %s",
            float(b["x"]),
            float(b["y"]),
            f"{hit[0]} {hit[1]}: {info['title']}" if info else "nothing",
        )
        self._json(info)

    @route("GET", "/api/info")
    def get_info(self, q) -> None:
        """An item's details."""
        self._json(self.S.info(q.get("kind", [""])[0], _num(q, "id", cast=int)))

    @route("GET", "/api/search")
    def get_search(self, q) -> None:
        """Find."""
        self._json(self.S.search(q.get("q", [""])[0]))

    @route("GET", "/api/types")
    def get_types(self, q) -> None:
        """Find's type list."""
        self._json(self.S.types())

    @route("GET", "/api/list")
    def get_list(self, q) -> None:
        """Every item of a type."""
        self._json({"results": self.S.list_type(q.get("type", [""])[0])})

    @route("GET", "/api/sources")
    def get_sources(self, q) -> None:
        """The screenshots that show a spot."""
        self._json(self.S.sources(_num(q, "x"), _num(q, "y")))

    @route("GET", r"/api/screenshot/(?P<name>[^/]+)")
    def get_screenshot(self, q, name) -> None:
        """A screenshot of the atlas (JPEG)."""
        self._bytes(self.S.screenshot_jpeg(name, _num(q, "w", 0, int)), "image/jpeg", cache=False)

    # ------------------------------------------------------------------ hand edits
    @route("POST", "/api/landmark")
    def post_landmark(self, q) -> None:
        """Change / add / delete a landmark."""
        b = self._body()
        self.S.set_landmark(float(b["x"]), float(b["y"]), b.get("kind", ""), b.get("on", "landmark"))
        self._json({"ok": True})

    @route("POST", "/api/map-edit")
    def post_map_edit(self, q) -> None:
        """Delete the map at a spot, or add one there (with a landmark kind)."""
        b = self._body()
        self.S.edit_map(float(b["x"]), float(b["y"]), str(b.get("op", "")), str(b.get("kind") or ""))
        self._json({"ok": True})

    @route("POST", "/api/city-type")
    def post_city_type(self, q) -> None:
        """Set a city's type (null: automatic)."""
        b = self._body()
        self.S.set_city_type(int(b["id"]), b.get("type"))
        self._json({"ok": True})

    @route("POST", "/api/lasso")
    def post_lasso(self, q) -> None:
        """How many maps a lasso holds."""
        n = len(self.S.lasso_nodes(self._body()["polygon"]))
        self.S.events.log(f"Biome select: {n} map{'' if n == 1 else 's'} inside the lasso")
        self._json({"maps": n})

    @route("POST", "/api/biome")
    def post_biome(self, q) -> None:
        """Set the biome of the maps inside a lasso."""
        b = self._body()
        self._json({"maps": self.S.set_biome(b["polygon"], b.get("biome", ""))})

    # ------------------------------------------------------------------ bookmarks
    @route("GET", "/api/bookmarks")
    def get_bookmarks(self, q) -> None:
        """Bookmarks by group."""
        self._json(self.S.bookmarks_payload())

    @route("POST", "/api/bookmarks")
    def post_bookmark(self, q) -> None:
        """Add a bookmark."""
        b = self._body()
        i = self.S.add_bookmark(float(b["x"]), float(b["y"]), b.get("name", ""), b.get("group", "Other"),
                                b.get("note", ""), gen=self._req_gen, route=b.get("route"),
                                colour=b.get("colour"), icon=b.get("icon"), plain=bool(b.get("plain")))  # fmt: skip
        if i < 0:
            raise ApiError("there is already a bookmark on that spot", 409)
        self._json({"id": i})

    @route("PATCH", r"/api/bookmarks/(?P<i>\d+)")
    def patch_bookmark(self, q, i) -> None:
        """Edit a bookmark."""
        b = self._body()
        self.S.edit_bookmark(int(i), b.get("name", ""), b.get("group", "Other"), b.get("note", ""),
                             b.get("colour"), b.get("icon"), b.get("plain"))  # fmt: skip
        self._json({"ok": True})

    @route("POST", "/api/bookmarks/route")
    def post_bookmark_route(self, q) -> None:
        """Change a saved route's maps."""
        b = self._body()
        if not isinstance(b.get("route"), dict):
            raise ApiError("a route is needed", 400)
        self.S.set_bookmark_route(int(b["id"]), b["route"], gen=self._req_gen)
        self._json({"ok": True})

    @route("POST", "/api/bookmarks/delete")
    def post_delete_bookmarks(self, q) -> None:
        """Delete bookmarks."""
        self._json({"deleted": self.S.delete_bookmarks([int(i) for i in self._body().get("ids", [])])})

    @route("POST", "/api/bookmarks/move")
    def post_move_bookmarks(self, q) -> None:
        """Move bookmarks to a group."""
        b = self._body()
        self.S.move_bookmarks([int(i) for i in b.get("ids", [])], b.get("group", "Other"))
        self._json({"ok": True})

    @route("POST", "/api/bookmarks/toggle")
    def post_toggle_bookmark(self, q) -> None:
        """Hide / show a bookmark."""
        self.S.toggle_bookmark(int(self._body()["id"]))
        self._json({"ok": True})

    @route("POST", "/api/bookmarks/all")
    def post_bookmark_all(self, q) -> None:
        """Bookmark many items into a group."""
        b = self._body()
        items = [(str(it["kind"]), int(it["id"])) for it in b.get("items", [])]
        added, skipped = self.S.bookmark_items(items, b.get("group", "Other"))
        self._json({"added": added, "skipped": skipped})

    @route("POST", "/api/groups")
    def post_group(self, q) -> None:
        """Add an empty group."""
        self.S.new_group(self._body().get("name", ""))
        self._json({"ok": True})

    @route("POST", "/api/groups/rename")
    def post_rename_group(self, q) -> None:
        """Rename a group."""
        b = self._body()
        self.S.rename_group(b["old"], b["new"])
        self._json({"ok": True})

    @route("POST", "/api/groups/look")
    def post_group_look(self, q) -> None:
        """Give a group its own colour and icon ("" for none)."""
        b = self._body()
        self.S.style_group(str(b.get("name", "")), b.get("colour"), b.get("icon"), bool(b.get("plain")))
        self._json({"ok": True})

    @route("POST", "/api/groups/delete")
    def post_delete_groups(self, q) -> None:
        """Delete empty groups."""
        names = self._body().get("names", [])
        if not isinstance(names, list):
            raise ValueError("names must be a list")
        self._json({"deleted": self.S.delete_groups([n for n in names if isinstance(n, str)])})

    @route("POST", "/api/groups/fold")
    def post_fold_groups(self, q) -> None:
        """Fold groups shut, or open them."""
        b = self._body()
        names = b.get("names")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ApiError("names: a list of group names", 400)
        self.S.fold_groups(names, bool(b.get("folded")))
        self._json({"ok": True})

    @route("POST", "/api/groups/toggle")
    def post_toggle_group(self, q) -> None:
        """Hide / show a group."""
        self.S.toggle_group(self._body()["name"])
        self._json({"ok": True})

    # ------------------------------------------------------------------ debug marks
    @route("GET", "/api/debug")
    def get_debug(self, q) -> None:
        """Debug marks."""
        self._json({"enabled": bool(rc_paths.DEBUG), "marks": self.S.debug_marks(), "reasons": DEBUG_REASONS,
                    "file": str(self.S._dbg_file() or "")})  # fmt: skip

    @route("POST", "/api/debug")
    def post_debug(self, q) -> None:
        """Add a debug mark."""
        b = self._body()
        self._json(
            self.S.add_debug_mark(
                b["kind"], b.get("reason", "other"), b.get("note", ""), b.get("x"), b.get("y"),
                [int(i) for i in b.get("maps", [])], b.get("path"),
            )
        )  # fmt: skip

    @route("DELETE", r"/api/debug/(?P<mid>\d+)")
    def delete_debug(self, q, mid) -> None:
        """Delete a debug mark."""
        self.S.delete_debug_mark(int(mid))
        self._json({"ok": True})

    @route("POST", "/api/debug/clear")
    def post_debug_clear(self, q) -> None:
        """Delete every debug mark (a copy is kept)."""
        self._json({"backup": self.S.clear_debug_marks()})

    # ------------------------------------------------------------------ colour by and replay
    @route("GET", "/api/frames")
    def get_frames(self, q) -> None:
        """Screenshot outlines, sessions, ages and colours."""
        self._json(self.S.frames_payload())

    @route("GET", "/api/ramp")
    def get_ramp(self, q) -> None:
        """A colour spread as 256 colours."""
        self._json(spread_colours(q.get("name", [""])[0]))

    @route("GET", "/api/ground")
    def get_ground(self, q) -> None:
        """Where the map image shows ground, on a grid (one byte per cell): "Colour by" tints only there."""
        got = self.S.ground_mask(_num(q, "x0", 0.0), _num(q, "y0", 0.0), _num(q, "cell", 1.0),
                                 _num(q, "w", 1, int), _num(q, "h", 1, int))  # fmt: skip
        self._bytes(got, "application/octet-stream", cache=False)

    @route("GET", "/api/heat")
    def get_heat(self, q) -> None:
        """Where the times-seen picture goes (and make it)."""
        upto = _num(q, "upto", -1.0)
        # kept for the atlas and model it was asked for (read first: one opened while it is made never gets it)
        key = (upto, self.S.generation, self.S.model_version)
        got = self.S.heat_png(None if upto < 0 else upto)
        if got is None:
            self._json(None)
            return
        self.server.heat = (key, got[0])  # type: ignore[attr-defined]
        self._json({"box": got[1]})

    @route("GET", "/api/heat.png")
    def get_heat_png(self, q) -> None:
        """The times-seen picture."""
        upto = _num(q, "upto", -1.0)
        kept = getattr(self.server, "heat", None)
        if kept is not None and kept[0] == (upto, self.S.generation, self.S.model_version):  # (CodeRabbit)
            self._bytes(kept[1], "image/png", cache=False)
            return
        got = self.S.heat_png(None if upto < 0 else upto)
        self._bytes(got[0] if got else None, "image/png", cache=False)

    @route("POST", "/api/replay/open")
    def post_replay_open(self, q) -> None:
        """Open the replay."""
        self._json(self.S.replay_open())

    @route("POST", "/api/replay/close")
    def post_replay_close(self, q) -> None:
        """Close the replay."""
        self.S.replay_close()
        self._json({"ok": True})

    @route("PATCH", "/api/replay")
    def patch_replay(self, q) -> None:
        """Change replay settings."""
        self._json(self.S.set_replay_settings(self._body()))

    @route("GET", "/api/replay/fog")
    def get_fog(self, q) -> None:
        """The fog bands."""
        self._json(self.S.replay_fog())


def meta() -> dict:
    """Return the constants the page needs (one source: app.constants and webmap.constants).

    Returns:
        Colours as CSS strings, landmark kinds, city types, biomes, style defaults and the replay's choices.
    """
    from grand_project import cities as atlas_cities
    from grand_project.webmap import constants as W

    from . import constants as C
    from .edits import BIOMES
    from .icons import bgr_hex

    return {
        "version": VERSION,
        "debug": bool(rc_paths.DEBUG),
        "colours": {
            "node": {k: bgr_hex(v) for k, v in C.NODE_COL.items()},
            "path_multi": bgr_hex(C.PATH_MULTI),
            "path_single": bgr_hex(C.PATH_SINGLE),
            "path_abyss": bgr_hex(C.PATH_ABYSS),
            "landmark": {k: bgr_hex(v) for k, v in C.LANDMARK_COL.items()},
            "city": {k: bgr_hex(v) for k, v in C.CITY_COL.items()},
            "bookmark": bgr_hex(C.BOOKMARK_COL),
            "select": bgr_hex(C.SELECT_COL),
            "hit": bgr_hex(C.HIT_COL),
            "removed": bgr_hex(C.REMOVED_COL),
            "recent": bgr_hex(C.RECENT_COL),
            "background": bgr_hex(C.BG),
            "biome": W.WEBMAP_BIOME_COLOUR,
            "land": W.WEBMAP_LAND_COLOUR,
            "status": W.WEBMAP_STATUS_COLOUR,
            "no_icon": W.WEBMAP_NO_ICON_FILL,
            "sessions": [bgr_hex(c) for c in C.REPLAY_SESSION_COLS],
        },
        "categories": C.CATEGORIES,
        "landmark_kinds": list(C.LANDMARK_KINDS),
        "city_types": list(atlas_cities.TYPES),
        "biomes": BIOMES,
        "potential_types": list(C.POTENTIAL_TYPES),
        "place_icon": C.PLACE_ICON,
        "style_default": C.STYLE_DEFAULT,
        "colour_by": list(C.COLOUR_BY),
        "colour_spreads": list(C.COLOUR_SPREADS),
        "tint_alpha": C.REPLAY_TINT_ALPHA,
        "replay": {
            "types": list(C.REPLAY_TYPES),
            "reveals": list(C.REPLAY_REVEALS),
            "cameras": list(C.REPLAY_CAMERAS),
            "smoothing": C.REPLAY_SMOOTHING,
            "speeds": list(C.REPLAY_SPEEDS),
            "defaults": C.REPLAY_DEFAULTS,
            "follow_span": C.REPLAY_FOLLOW_SPAN,
            "scan_column": C.REPLAY_SCAN_COLUMN,
            "spiral_pitch": C.REPLAY_SPIRAL_PITCH,
        },
        "recent_fade": C.RECENT_FADE,
        "icon_units": W.WEBMAP_ICON_UNITS,
        "icon_min_px": W.WEBMAP_ICON_MIN_PX,
        # bookmark pins: radius at size 1, and how far above its spot a pin "on the icon" sits (atlas units)
        "bookmark_pin": C.BOOKMARK_PIN_R,
        "icon_row_dy": C.ICON_ROW_DY,
        "bookmark_ats": list(C.BOOKMARK_ATS),
    }


_UPLOADS = threading.Lock()
"""Held while one upload creates, compares and closes its file: a second drop of the same picture never takes a file
for its own whose writer is still open (its close may yet fail and remove it: CodeRabbit)."""


def save_upload(folder: Path, name: str, data: bytes) -> Path:
    """Save a dropped screenshot in a folder under its own name, or a free name when another picture has it.

    Args:
        folder: The open atlas's folder.
        name: The file's name.
        data: The file's bytes.

    Returns:
        The file holding the picture (the one already there when it is the same picture).
    """
    with _UPLOADS:
        return _save_upload(folder / name, data)


def _save_upload(dest: Path, data: bytes) -> Path:
    """``save_upload`` with the upload lock held."""
    stem, k = dest.stem, 0
    while True:
        try:  # the name claimed in the same step as the file is made: checked first, then written, two pictures
            # dropped together under one name both found it free and the second overwrote the first
            f = open(dest, "xb")  # noqa: SIM115 (closed below, its failure included)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if dest.read_bytes() == data:  # the same picture again: its file
                    return dest
        else:
            try:
                with f:  # the write and the close (its flush can fail too: a full disk)
                    f.write(data)
            except BaseException:
                dest.unlink(missing_ok=True)  # this call made it: no cut-off picture left under the name
                raise
            return dest
        k += 1  # another picture by that name: a free name (CodeRabbit)
        dest = dest.with_name(f"{stem}_{int(time.time())}{f'_{k}' if k > 1 else ''}{dest.suffix}")


def _jsonable(o):
    """Turn numpy values and sets into JSON.

    Args:
        o: The value json could not encode.

    Returns:
        A JSON-able value.
    """
    import numpy as np

    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"{type(o).__name__} is not JSON")


class AppServer(ThreadingHTTPServer):
    """The HTTP server holding the session."""

    daemon_threads = True
    allow_reuse_address = False
    # connections waiting to be taken: a page reload asks for dozens of tiles at once, and with the default 5 the rest
    # were refused ("the app isn't running" until the next reload: user)
    request_queue_size = 256

    def __init__(self, session: AtlasSession, host: str = APP_HOST, port: int = APP_PORT):
        """Bind to the first free port from `port` (APP_PORT_TRIES tries; port 0: any free one).

        Args:
            session: The session.
            host: Address to listen on.
            port: First port to try.

        Raises:
            OSError: When no port is free.
        """
        self.session, self.stopping, self.heat = session, False, None
        # runs work behind a request (a thread; tests run it at once instead of waiting for it)
        self.background = lambda fn: threading.Thread(target=fn, daemon=True).start()
        last: OSError | None = None
        for p in [0] if port == 0 else range(port, port + APP_PORT_TRIES):
            try:
                super().__init__((host, p), Handler)
                return
            except OSError as e:
                last = e
        raise last or OSError("no free port")

    def handle_error(self, request, client_address) -> None:
        """Print a request's error, except a browser dropping its connection (a tab closed or reloaded while it was
        answered): that is no error, and its traceback filled the terminal (the browser tests showed dozens).

        Args:
            request: The connection.
            client_address: Who asked.
        """
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)

    @property
    def url(self) -> str:
        """Return the page's address."""
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def quit(self) -> None:
        """Save everything and stop serving."""
        self.stopping = True
        try:
            self.session.shutdown()
        finally:
            self.shutdown()


def _local(url: str, data: dict | None = None, timeout: float = APP_HELLO_WAIT) -> dict | None:
    """Ask a server on this computer (no proxy: a proxy set for the internet refused 127.0.0.1, CodeRabbit).

    Args:
        url: The address.
        data: A JSON body to POST (with the app's change header), or None for a GET.
        timeout: Seconds to wait.

    Returns:
        The JSON answer, or None when nothing (or something else, e.g. an SSH banner: CodeRabbit) answers.
    """
    req = urllib.request.Request(url, method="GET" if data is None else "POST")
    body = None
    if data is not None:
        req.add_header(HEADER, "1")
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    try:
        with _NO_PROXY.open(req, data=body, timeout=timeout) as r:
            answer = json.loads(r.read())
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return answer if isinstance(answer, dict) else None


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _in_use(host: str, port: int) -> bool:
    """Tell whether something listens on a port: binding it fails then. Instant, unlike a refused connection.

    Args:
        host: The address.
        port: The port.

    Returns:
        True when the port is taken.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def _stopped(host: str, port: int) -> bool:
    """Tell whether nothing listens on a port any more (a copy that was asked to quit has gone).

    The port binds again (quick, also on Windows, where a refused connection takes ~2 s), or a connection to it is
    refused: on Linux / macOS a closed port can stay unbindable for a while (connections in TIME_WAIT), which kept
    a quit copy "running" until the start gave up (CodeRabbit). Anything else (accepted, timed out) is not gone.

    Args:
        host: The address.
        port: The port.

    Returns:
        True when nothing listens there.
    """
    if not _in_use(host, port):
        return True
    try:
        with socket.create_connection((host, port), timeout=APP_STOP_PROBE):
            return False  # still accepting
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


def running_app(port: int, host: str = APP_HOST, root: Path | None = None) -> tuple[str, str, bool] | None:
    """Find this program's own copy already running on one of the ports it would take.

    Starting it again (a double-click on the launcher, which shows no window on Windows) started a second copy on
    the next port, both writing the same atlas. A copy of the program in another folder doesn't count.

    Args:
        port: The first port the app would take (APP_PORT_TRIES from there are looked at).
        host: The address it listens on.
        root: The program folder a running copy must be in (default: this one's).

    Returns:
        (the running copy's URL, its version, whether it runs the RF-DETR detector), or None.
    """
    want = str((root or rc_paths.ROOT).resolve())
    for p in range(port, port + APP_PORT_TRIES):
        if not _in_use(host, p):
            continue  # nobody listens there: not asked (a refused connection takes ~2 s on Windows: 20 ports
            # made every start ~10 s slower, user)
        url = f"http://{host}:{p}/"
        hello = _local(url + "api/hello")
        if hello and hello.get("app") == HELLO_APP and hello.get("root") == want:
            return url, str(hello.get("version", "")), bool(hello.get("rf_detr"))
    return None


HANDED, START, FAILED = "handed over", "start", "failed"  # reuse_running's outcomes


def reuse_running(port: int, atlas: str | None, browser: bool) -> str:
    """Hand this start over to the copy already running, when there is one of this version.

    The same version: its page is opened, and an atlas asked for on the command line is opened there (it was
    dropped: CodeRabbit). An older version (the folder was updated while it ran): it is asked to quit, so this
    start runs the update (the old copy kept being reused: CodeRabbit).

    Args:
        port: The first port the app would take.
        atlas: The atlas file asked for on the command line, or None.
        browser: Open the page.

    Returns:
        HANDED (the running copy took over), START (none running, or the old one quit: start normally) or FAILED
        (a hand-over that didn't work: reported, and no second copy is started, CodeRabbit).
    """
    found = running_app(port)
    if not found:
        return START
    url, version, rf_detr = found
    if version != VERSION:
        _say(f"An older copy (v{version}) is running: closing it to start v{VERSION}")
        _local(url + "api/quit", {})
        t0 = time.monotonic()
        old_port = int(url.rstrip("/").rsplit(":", 1)[1])
        while time.monotonic() - t0 < APP_QUIT_WAIT:
            # gone only when nothing listens there any more: a slow answer while it saves was taken for gone, and
            # the new copy started beside it (CodeRabbit)
            if _stopped(APP_HOST, old_port):
                return START
            time.sleep(0.25)
        # still there (saving or finishing work): two copies would write the same atlas
        _say(f"The older copy at {url} is still closing: start the app again in a moment.")
        return FAILED
    _say(f"The Grand Project is already running: {url}")
    from grand_project.detect.rf_detr_model import rf_detr_enabled

    if rf_detr != rf_detr_enabled():
        # the running copy keeps its own detector: this start's GRAND_PROJECT_USE_RF_DETR is not applied (CodeRabbit)
        detector = "RF-DETR" if rf_detr else "classical"
        note = (
            f"The running copy uses the {detector} detector: this start's GRAND_PROJECT_USE_RF_DETR was not applied "
            "(quit it and start again to switch)."
        )
        LOG.warning(note)
        _say(note)
    if browser:
        webbrowser.open(url)
    if atlas and _local(url + "api/atlas/open", {"path": str(Path(atlas).resolve()), "background": True}) is None:
        _say(f"The running copy couldn't open {atlas} (it may be adding screenshots): open it there when it's done.")
        return FAILED
    return HANDED


def take_app_lock():
    """Take this program folder's start lock (user_data/app.lock), held while the app runs.

    The look for a running copy and starting one are two steps: two launches at the same moment both found none and
    both started on the next port, writing the same atlas (CodeRabbit). The lock makes one of them wait. The system
    lets go of it when the process ends, however it ends.

    Returns:
        The open lock file (keep it while running), or None when another copy holds it.
    """
    path = rc_paths.USER_DATA / APP_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")  # noqa: SIM115 (held open for the app's life)
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _recorded_port() -> int | None:
    """Return the port the start lock's holder wrote it serves on (user_data/app.url), or None."""
    try:
        url = (rc_paths.USER_DATA / APP_URL_FILE).read_text(encoding="utf-8").strip()
        return int(url.rstrip("/").rsplit(":", 1)[1])
    except (OSError, ValueError, IndexError):
        return None


def _say(text: str) -> None:
    """Print a line when there is a console (pythonw, the Windows launcher, has none).

    Args:
        text: The line.
    """
    if sys.stdout is not None:
        print(text, flush=True)


def open_first_atlas(session: AtlasSession, given: str | None, gen: int | None = None) -> None:
    """Open the atlas given, else the last one, else (first start) the empty default atlas, with a welcome note.

    Args:
        session: The session.
        given: The atlas file from the command line, or None.
        gen: The generation the start began under: the atlas is only switched to while it is still current (one
            opened on the page meanwhile isn't replaced).
    """
    target = given or session.settings.get("last_atlas")
    welcome = False
    if not target or not Path(target).exists():
        target = rc_paths.DEFAULT_ATLAS
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            core.Atlas().save(target)
        welcome = True
    try:
        session.open_atlas(target, expect_gen=gen)
    except ValueError as e:
        session.events.log(str(e))
        return
    if welcome:
        session.events.log(
            "Welcome! This is the default atlas (atlases/default). Put screenshots in that folder and use Atlas > "
            "default > Add new screenshots from its folder. Or set Steam's external screenshot folder to it and turn "
            "on Auto-add > Add new screenshots automatically."
        )


def main(argv: list[str] | None = None) -> int:
    """Start the app: open the atlas (the one given, else the last one), serve the page and open the browser.

    With the optional RF-DETR detector on (``GRAND_PROJECT_USE_RF_DETR``), the process restarts itself once after
    reading its arguments, with PyTorch's CUDA libraries first (``rf_detr_cuda``), and goes on with the same
    arguments: ``argv`` when given, else its own command line.

    Args:
        argv: Command line (default: sys.argv).

    Returns:
        Exit code.
    """
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries
    from grand_project.detect.rf_detr_model import rf_detr_enabled

    ap = argparse.ArgumentParser(prog="python -m grand_project", description="The Grand Project atlas app.")
    ap.add_argument("atlas", nargs="?", help="atlas .json file to open (default: the last one)")
    ap.add_argument("--port", type=int, default=APP_PORT, help=f"first port to try (default {APP_PORT}; 0: any)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = ap.parse_args(argv)
    if rf_detr_enabled():  # the optional RF-DETR detector on CUDA needs PyTorch's own cuDNN, before torch loads
        prefer_pip_cuda_libraries(argv)
    if args.port:
        outcome = reuse_running(args.port, args.atlas, not args.no_browser)
        if outcome != START:  # already running: its page, not a second copy writing the same atlas (user)
            return 0 if outcome == HANDED else 1
    lock = take_app_lock()
    if lock is None:
        # another launch holds it: started at the same moment (both found none running) or still closing; it is
        # handed over to once it answers, or the lock is taken once it is gone (two copies wrote the same atlas,
        # CodeRabbit)
        t0 = time.monotonic()
        while lock is None and time.monotonic() - t0 < APP_QUIT_WAIT:
            # where the lock's holder serves (any port it was started on, also --port 0), else the default range
            at = _recorded_port()
            for port in [p for p in (at, args.port) if p]:
                if running_app(port):
                    outcome = reuse_running(port, args.atlas, not args.no_browser)
                    if outcome != START:
                        return 0 if outcome == HANDED else 1
            time.sleep(0.25)
            lock = take_app_lock()
        if lock is None:
            _say("Another copy of the app is starting or closing and doesn't answer: start it again in a moment.")
            return 1
    session = AtlasSession()
    session.after_update()  # (an update just put in place: said in the log)
    try:
        server = AppServer(session, port=args.port)
    except OSError as e:
        LOG.error(f"could not start the app's server: {e}")
        _say(f"could not start the app's server: {e}")
        return 1
    # beside the lock (not in it: on Windows its locked byte can't be read), for a launch that finds the lock taken:
    # a copy started on another port was not found, and that launch gave up (CodeRabbit)
    with contextlib.suppress(OSError):
        (rc_paths.USER_DATA / APP_URL_FILE).write_text(server.url, encoding="utf-8")
    _say(f"The Grand Project {VERSION}: {server.url}  (Ctrl+C to quit)")
    LOG.info(f"serving on {server.url}")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(server.url)).start()
    # the atlas opens behind the page: the page shows at once and says which atlas is loading (it waited for the
    # whole atlas to load first: user)
    session.opening = Path(args.atlas or session.settings.get("last_atlas") or rc_paths.DEFAULT_ATLAS).parent.name

    start_gen = session.generation  # (an atlas opened on the page meanwhile wins: CodeRabbit)

    def first_atlas() -> None:
        try:
            open_first_atlas(session, args.atlas, start_gen)
        finally:
            session.opening = None
            session.events.publish("atlas", session.atlas_summary())

    threading.Thread(target=first_atlas, daemon=True).start()
    session.check_update_at_start()  # (the player release, once a day, on a thread of its own)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        _say("closing: saving the atlas…")
        server.stopping = True
        session.shutdown()
    finally:
        server.server_close()
    return 0
