"""app.updater: part of AtlasSession (a mixin; see app/session.py): the in-app update, as Path of Building has it.

The player release (channel "release", with manifest.json: grand_project/release_manifest.py) asks GitHub for the
latest release once a day when the app starts (a setting turns it off) and whenever the status bar's version is
pressed. A newer one is shown with its notes; Update now downloads its zip into user_data/update/, checks every
file against its manifest, works out which files change (and whether the Python packages must be installed again),
writes the plan, starts app/update_apply.py on its own and quits. That helper puts the files in place once the app has
closed, with a backup it puts back on any failure, and starts the app again; the page reloads itself on the new
version. Development copies (internal, develop: no manifest) are updated with git instead.

Only the release's own files (its manifest's) change: atlases/, user_data/, local_paths.json and .venv/ never do.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from grand_project import logs as atlas_log
from grand_project import paths as rc_paths
from grand_project import release_manifest as rm

from . import constants as K

LOG = atlas_log.get("app")


def latest_release(fetch=None) -> dict:
    """Ask GitHub for the latest release.

    Args:
        fetch: url -> parsed JSON (default: an HTTPS GET with the app's name as User-Agent; tests pass their own).

    Returns:
        {"release", "name", "notes", "url", "zip", "published"}.

    Raises:
        OSError / ValueError: When GitHub can't be reached or answers something else.
    """
    data = (fetch or _get_json)(K.UPDATE_RELEASES_URL)
    tag = str(data.get("tag_name", ""))
    if not rm.release_key(tag) or not data.get("zipball_url"):
        raise ValueError(f"GitHub's latest release has no release number ({tag!r})")
    return {
        "release": tag.lstrip("vV"),
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
        "url": data.get("html_url") or "",
        "zip": data["zipball_url"],
        "published": data.get("published_at") or "",
    }


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": K.UPDATE_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=K.UPDATE_HTTP_WAIT) as r:  # noqa: S310 (a fixed https URL)
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OSError(limit_message(e.code, e.headers) or f"GitHub answered {e.code}") from e
    except http.client.HTTPException as e:  # (an answer cut off midway: it isn't an OSError, CodeRabbit)
        raise OSError(f"GitHub's answer was cut off ({e})") from e


def limit_message(code: int, headers) -> str | None:
    """What to say when GitHub's limit of checks is used up (403 / 429 with no checks left), else None.

    Args:
        code: The HTTP status.
        headers: The answer's headers (X-RateLimit-Remaining, X-RateLimit-Reset: when it starts again, s since 1970).
    """
    if code not in (403, 429) or str(headers.get("X-RateLimit-Remaining", "")) != "0":
        return None
    reset = headers.get("X-RateLimit-Reset")
    at = time.strftime("%H:%M", time.localtime(int(reset))) if str(reset or "").isdigit() else "within the hour"
    return f"GitHub's limit of update checks from your address is used up: it answers again at {at}"


def unpack(zip_path: Path, dest: Path) -> dict:
    """Unpack a release zip (GitHub's: one top folder) and check its files against its own manifest.

    Args:
        zip_path: The zip.
        dest: An empty folder for the release's files.

    Returns:
        The release's manifest.

    Raises:
        ValueError: When it isn't a release (no manifest), a file is missing or differs from its hash, or a path in
            it would land outside `dest`.
    """
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        tops = {n.split("/", 1)[0] for n in names if n}
        top = tops.pop() + "/" if len(tops) == 1 else ""
        try:
            manifest = json.loads(z.read(top + rm.MANIFEST).decode("utf-8"))
        except (KeyError, ValueError) as e:
            raise ValueError("the download has no release manifest: not a release") from e
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, dict) or not manifest.get("release"):
            raise ValueError("the download's release manifest is broken")
        root = dest.resolve()
        for rel, want in files.items():
            out = (dest / rel).resolve()
            if root not in out.parents:
                raise ValueError(f"the download has a file outside the program folder: {rel}")
            try:
                data = z.read(top + rel)
            except KeyError as e:
                raise ValueError(f"the download lacks {rel}") from e
            if rm.content_hash(data) != want:
                raise ValueError(f"{rel} in the download isn't the release's (broken download?)")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            # its permissions as the release has them (start.sh can be run: it lost them, CodeRabbit)
            mode = (z.getinfo(top + rel).external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                out.chmod(mode)
        (dest / rm.MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def plan_files(root: Path, installed: dict, new: dict) -> tuple[list[str], list[str], bool]:
    """Which files an update changes.

    Args:
        root: The program folder.
        installed: Its manifest.
        new: The new release's manifest.

    Returns:
        (files to copy in: new or changed, files to remove: the installed release's that the new one dropped,
        whether requirements.txt changes).
    """
    copy = [f for f, h in new["files"].items() if rm.file_hash(root / f) != h]
    copy.append(rm.MANIFEST)
    drop = [f for f in installed.get("files", {}) if f not in new["files"] and (root / f).is_file()]
    return copy, drop, "requirements.txt" in copy


def console_python() -> str:
    """The interpreter for pip: python.exe beside the windowless pythonw.exe the app may run on (Windows)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return str(exe)


class UpdatesMixin:
    """AtlasSession mixin: the in-app update (see the module docstring)."""

    _update: dict
    _update_lock: threading.Lock

    def _update_state(self) -> dict:
        if not hasattr(self, "_update"):
            self._update = {
                "state": "idle",
                "latest": None,
                "error": None,
                "got": 0,
                "size": 0,
                "just": None,
                "seq": 0,
            }
            self._update_lock = threading.Lock()
        return self._update

    def update_status(self) -> dict:
        """What the page shows for the update (the status bar's version and its box).

        Returns:
            {"channel", "release", "program", "can", "why", "auto", "checked", "next", "state", "latest",
            "available", "error", "got", "size", "just", "seq"}; state is idle / checking / downloading /
            restarting /
            error; next: when GitHub may be asked again (s since 1970; 0: now), a time and not a count of seconds,
            so a page that opens the box later counts down to the same moment (user: it started again at 60).
        """
        u = self._update_state()
        seq = u["seq"]  # (first: a change made meanwhile comes with a higher number, in its own event)
        installed = rm.read(rc_paths.ROOT)
        latest = u["latest"]
        mine = installed["release"] if installed else None
        newer = bool(latest and mine and rm.release_key(latest["release"]) > rm.release_key(mine))
        can, why = self._can_update(installed)
        return {
            "channel": rc_paths.CHANNEL,
            "release": mine,
            "program": K.VERSION,
            "can": can,
            "why": why,
            "auto": bool(self.settings.get("update_auto", True)),
            "checked": self.settings.get("update_checked"),
            "next": self._next_check(),
            "state": u["state"],
            "latest": latest,
            "available": newer,
            "error": u["error"],
            "got": u["got"],
            "size": u["size"],
            "just": u["just"],
            # goes up with each change: the page keeps the newest it has (a button's answer could land after the
            # event of what followed, and showed "Checking…" for good: CodeRabbit)
            "seq": seq,
        }

    def _next_check(self) -> float:
        left = self._update_state().get("asked", -1e9) + K.UPDATE_CHECK_GAP - time.monotonic()
        return round(time.time() + left, 1) if left > 0 else 0

    def _can_update(self, installed: dict | None) -> tuple[bool, str]:
        if rc_paths.CHANNEL != "release" or installed is None:
            return False, "This is a development copy: update it with git (git pull)."
        if (rc_paths.ROOT / ".git").exists():
            return False, "This copy is a git clone: update it with git pull."
        return True, ""

    def _publish_update(self) -> None:
        u = self._update_state()
        u["seq"] += 1
        self.events.publish("update", self.update_status())

    def set_update_auto(self, on: bool) -> None:
        """Check for an update when the app starts (once a day), or only when asked."""
        self.settings["update_auto"] = bool(on)
        self.save_settings()
        self.events.log(f"Update check at start {'on' if on else 'off'}")
        self._publish_update()

    def check_update(self, background: bool = True, fetch=None) -> None:
        """Ask GitHub for the latest release (once at a time, and at most once per UPDATE_CHECK_GAP: in between the
        last answer stands).

        Args:
            background: On a thread of its own (the page's button); False runs it here (tests).
            fetch: As latest_release's.
        """
        u = self._update_state()
        with self._update_lock:
            if u["state"] in ("checking", "downloading", "restarting"):
                return
            if time.monotonic() - u.get("asked", -1e9) < K.UPDATE_CHECK_GAP:
                self._publish_update()  # (the page learns how long to wait)
                return
            u.update(state="checking", error=None, asked=time.monotonic())
        self._publish_update()

        def run() -> None:
            try:
                latest = latest_release(fetch)
                u.update(state="idle", latest=latest)
                self.settings["update_checked"] = time.time()
                self.save_settings()
                st = self.update_status()
                self.events.log(
                    f"Update check: {latest['name']} is out (you have {st['release']})"
                    if st["available"]
                    else f"Update check: you have the latest release ({st['release'] or K.VERSION})"
                )
            except Exception as e:  # noqa: BLE001 (any failure ends the check: it stayed "checking" for good)
                u.update(state="error", error=f"Couldn't reach GitHub to check for an update: {e}")
                LOG.warning(f"update check failed: {e}")
            self._publish_update()

        if background:
            threading.Thread(target=run, name="update-check", daemon=True).start()
        else:
            run()

    def check_update_at_start(self, fetch=None) -> bool:
        """The once-a-day check when the app starts (the player release, when the setting is on).

        Returns:
            True when a check was started.
        """
        st = self.update_status()
        last = st["checked"] or 0
        if not st["can"] or not st["auto"] or time.time() - float(last) < K.UPDATE_CHECK_EVERY:
            return False
        self.check_update(fetch=fetch)
        return True

    def install_update(
        self, quit_app, download=None, launch=None, background: bool = True, restart_args: list[str] | None = None
    ) -> None:
        """Download the latest release, check it, and hand over to the helper that puts it in place (the app quits).

        Args:
            quit_app: Stops the app (saves the atlas and settings first).
            download: (url, file, on_progress(got, size)) -> None (default: an HTTPS download; tests pass their own).
            launch: (argv) -> None, starts the helper (default: a process of its own).
            background: On a thread of its own; False runs it here (tests).
            restart_args: More arguments for the app's restart (its port: the page reconnects to the same address,
                and a copy started on the default port could find another one running there).

        Raises:
            ValueError: When this copy can't be updated in the app, or there is nothing newer.
        """
        st = self.update_status()
        if not st["can"]:
            raise ValueError(st["why"])
        if not st["available"]:
            raise ValueError("There is no newer release to install: check for an update first.")
        u = self._update_state()
        with self._update_lock:
            if u["state"] in ("checking", "downloading", "restarting"):
                raise ValueError("An update check or download is already running.")
            u.update(state="downloading", error=None, got=0, size=0)
        latest, mine = st["latest"], st["release"]
        self.events.log(f"Updating to {latest['name']}: downloading it")
        self._publish_update()

        def progress(got: int, size: int) -> None:
            u.update(got=got, size=size)
            self._publish_update()

        def run() -> None:
            work = rc_paths.USER_DATA / "update"
            try:
                shutil.rmtree(work, ignore_errors=True)  # (an earlier, unfinished one)
                work.mkdir(parents=True, exist_ok=True)
                zip_path = work / "release.zip"
                (download or _download)(latest["zip"], zip_path, progress)
                new = unpack(zip_path, work / "new")
                if rm.release_key(new["release"]) <= rm.release_key(mine or ""):
                    raise ValueError(f"the download is release {new['release']}, not newer than {mine}")
                installed = rm.read(rc_paths.ROOT) or {"files": {}}
                copy, drop, pip = plan_files(rc_paths.ROOT, installed, new)
                helper = work / "update_apply.py"  # (run from a copy: the program's own changes under it)
                shutil.copy2(Path(__file__).with_name("update_apply.py"), helper)
                plan = {
                    "pid": os.getpid(),
                    "root": str(rc_paths.ROOT),
                    "new": str(work / "new"),
                    "backup": str(work / "backup"),
                    "copy": copy,
                    "delete": drop,
                    "pip": pip,
                    "python": console_python(),
                    "restart": [sys.executable, "-m", "grand_project", "--no-browser", *(restart_args or [])],
                    "result": str(rc_paths.USER_DATA / K.UPDATE_RESULT),
                    "from": mine,
                    "to": new["release"],
                }
                (work / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
                self.events.log(
                    f"Updating to {latest['name']}: {len(copy)} files to replace, {len(drop)} to remove"
                    + (", Python packages to install" if pip else "")
                    + "; the app restarts"
                )
                u.update(state="restarting")
                self._publish_update()
                (launch or _launch)([sys.executable, "-I", str(helper), str(work / "plan.json")])
                quit_app()
            except Exception as e:  # noqa: BLE001 (any failure: said, nothing changed)
                u.update(state="error", error=f"The update couldn't be prepared: {e}")
                LOG.warning(f"update failed: {e}")
                self._publish_update()

        if background:
            threading.Thread(target=run, name="update-install", daemon=True).start()
        else:
            run()

    def after_update(self) -> dict | None:
        """At start: what the last update did (the helper's result), said in the log and to the page once.

        Returns:
            The result, or None when there was none.
        """
        f = rc_paths.USER_DATA / K.UPDATE_RESULT
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        f.unlink(missing_ok=True)
        if r.get("ok"):
            self.events.log(f"Updated from release {r.get('from')} to {r.get('to')}")
            shutil.rmtree(rc_paths.USER_DATA / "update", ignore_errors=True)
        else:
            self.events.log(f"The update to release {r.get('to')} failed, nothing changed: {r.get('error')}")
        self._update_state()["just"] = r
        return r


def _download(url: str, dest: Path, progress) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": K.UPDATE_AGENT})
    with urllib.request.urlopen(req, timeout=K.UPDATE_HTTP_WAIT) as r, dest.open("wb") as f:  # noqa: S310
        size = int(r.headers.get("Content-Length") or 0)
        got, last = 0, 0.0
        while chunk := r.read(K.UPDATE_CHUNK):
            f.write(chunk)
            got += len(chunk)
            if time.monotonic() - last > K.UPDATE_PROGRESS_EVERY:
                last = time.monotonic()
                progress(got, size)
        progress(got, size)


def _launch(argv: list[str]) -> None:
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen(argv, **kw)  # noqa: S603 (the app's own interpreter and helper)
