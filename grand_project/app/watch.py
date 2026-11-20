"""app.watch: part of AtlasSession (a mixin; see app/session.py): auto-add, the watched screenshot folder.

Each atlas watches its own folder unless a folder was picked for it (settings["watch_folders"], keyed by the
atlas's resolved path). A thread checks the folder every WATCH_POLL_MS; a file is ready when it has the same size
twice. Screenshots already in the folder that the atlas does not have (from its first screenshot on) are added
when auto-add starts; a folder that is not the atlas's own with more than WATCH_ASK of them asks first.
"""

from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

from grand_project import core

from .constants import WATCH_ASK, WATCH_POLL_MS, WATCH_RETRIES


class WatchMixin:
    """AtlasSession mixin: auto-add (see the module docstring)."""

    def _init_watch(self) -> None:
        """Start with auto-add off."""
        self._watch_on = False
        self._watch_seen: dict[str, int] = {}  # file -> size at last poll (-1: handed over to adding)
        self._watch_tries: dict[str, int] = {}
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._known_key = None
        self._known: set[str] = set()

    # ------------------------------------------------------------------ which folder
    def _atlas_key(self) -> str:
        """Return the key the open atlas's settings are kept under (its resolved path).

        Returns:
            The key, or "" with no atlas open.
        """
        return str(Path(self.path).resolve()) if self.path else ""

    def _hand_watch(self) -> str | None:
        """Return the folder picked by hand for the open atlas.

        Returns:
            The folder, or None.
        """
        self.settings.pop("watch_folder", None)  # before v1.11 one folder for every atlas: forgotten
        return self.settings.get("watch_folders", {}).get(self._atlas_key())

    def watch_dir(self) -> str:
        """Return the folder auto-add watches: one picked for this atlas, else the atlas's own folder.

        Returns:
            The folder, or "" with no atlas open.
        """
        return self._hand_watch() or (str(self.path.parent) if self.path else "")

    def watch_state(self) -> dict:
        """Return auto-add's state for the page.

        Returns:
            {"on", "folder", "picked" (a folder picked by hand)}.
        """
        return {"on": self._watch_on, "folder": self.watch_dir(), "picked": bool(self._hand_watch())}

    def set_watch_folder(self, folder: str | None) -> None:
        """Pick the folder to watch for the open atlas (None: its own folder again), restarting auto-add if on.

        Args:
            folder: The folder, or None.

        Raises:
            ValueError: With no atlas open, or when the folder does not exist.
        """
        # a request made for another atlas: refused, never applied to the one open now; the check and the change
        # in one step against a switch, without waiting for a job (AtlasLock.steady)
        with self._lock.steady():
            if not self.path:
                raise ValueError("open or create an atlas first")
            folders = self.settings.setdefault("watch_folders", {})
            if folder:
                if not Path(folder).is_dir():
                    raise ValueError(f"not a folder: {folder}")
                folders[self._atlas_key()] = str(folder)
            else:
                folders.pop(self._atlas_key(), None)
            self.save_settings()
            if self._watch_on:
                self.start_watch()
            self.events.publish("watch", self.watch_state())

    def set_watch(self, on: bool) -> None:
        """Turn auto-add on or off (and remember it).

        Args:
            on: True to watch.

        Raises:
            ValueError: Turning it on with no atlas open.
        """
        # a request made for another atlas: refused, never applied to the one open now; the check and the change
        # in one step against a switch, without waiting for a job (AtlasLock.steady)
        with self._lock.steady():
            if on:
                self.start_watch()
            else:
                self.stop_watch()
                self.settings["watch_on"] = False
                self.events.set_status("auto-add off")
            self.save_settings()

    # ------------------------------------------------------------------ the folder

    def _watch_files(self) -> dict[str, int]:
        """List the image files in the watched folder that can be screenshots (the program's own are left out).

        Returns:
            {full path: size in bytes}.
        """
        out: dict[str, int] = {}
        with contextlib.suppress(OSError):
            base = Path(self.watch_dir()).resolve()
            if base.name.endswith(("_files", "_frames", "_undo")):
                return out
            with os.scandir(base) as it:
                for e in it:
                    name = e.name
                    if Path(name).suffix.lower() not in core.IMAGE_EXT or core.is_atlas_output(name):
                        continue
                    with contextlib.suppress(OSError):
                        if e.is_file():
                            out[str(base / name)] = e.stat().st_size
        return out

    def _not_in_atlas(self, files) -> list[Path]:
        """Find screenshots of the watched folder the atlas does not have (from its first screenshot on).

        Args:
            files: Full paths of the files in the watched folder.

        Returns:
            The screenshot files, oldest first.
        """
        have_path = {str(Path(f["path"]).resolve()) for f in self.atlas.frames}
        have_name = {f["name"] for f in self.atlas.frames}
        since = None
        for f in self.atlas.frames:
            try:
                t = Path(f["path"]).stat().st_mtime
            except OSError:
                continue
            since = t if since is None else min(since, t)
        out = []
        for f in files:
            p = Path(f)
            if f in have_path or p.stem in have_name:
                continue
            try:
                t = p.stat().st_mtime
            except OSError:
                continue
            if since is None or t >= since - 1:
                out.append((t, p))
        return [p for _t, p in sorted(out)]

    def start_watch(self) -> None:
        """Start auto-add on the watched folder: screenshots there the atlas lacks are added, then new ones.

        Raises:
            ValueError: With no atlas open.
        """
        if not self.atlas or not self.path:
            raise ValueError("open or create an atlas first")
        self.stop_watch()
        self.settings["watch_on"] = True
        folder = self.watch_dir()
        files = self._watch_files()
        self._watch_seen = {k: -1 for k in files}
        todo = [q for q in self._not_in_atlas(files) if not core.is_generated(q)]
        own = Path(folder).resolve() == Path(self.path).resolve().parent
        opened = self.opened  # (one record: the atlas and its generation together)
        atlas, gen = opened.atlas, opened.gen
        self._watch_gen = gen
        self._watch_on = True
        self.events.set_status(f"watching {folder} for new screenshots")
        self.events.publish("watch", self.watch_state())

        def begin():
            """Ask about a crowded folder (waits for the page), add what is missing, then poll."""
            nonlocal todo
            crowded = todo and not own and atlas.frames and len(todo) > WATCH_ASK
            if crowded and not self.events.ask(
                f"{len(todo)} screenshots in {folder} are not in this atlas.\n\n"
                "Add them all to this atlas? (No: only new screenshots from now on.)"
            ):
                self.events.log(f"auto-add: left the {len(todo)} screenshot(s) already in {folder} out")
                todo = []
            if atlas is not self.atlas or not self._watch_on or stop.is_set():  # replaced or stopped meanwhile
                return
            self.events.log(
                f"auto-add: watching {folder}"
                + (f"; {len(todo)} screenshot(s) there are not in the atlas yet: adding them" if todo else "")
            )
            if todo:
                try:
                    self.add_screenshots(todo, mode="watch", gen=gen)  # skipped if another atlas opened meanwhile
                except ValueError as e:
                    self.events.log(f"auto-add: {e}")
            self._poll_loop(stop)

        self._watch_stop = stop = threading.Event()
        self._watch_thread = threading.Thread(target=begin, daemon=True, name="watch")
        self._watch_thread.start()

    def stop_watch(self) -> None:
        """Stop polling the watched folder (the setting is left as it is)."""
        self._watch_stop.set()
        if self._watch_on:
            self._watch_on = False
            self.events.publish("watch", self.watch_state())

    def _poll_loop(self, stop: threading.Event) -> None:
        """Poll the folder until stopped (watch thread).

        Args:
            stop: Set to stop.
        """
        while not stop.wait(WATCH_POLL_MS / 1000):
            try:
                self.poll_watch()
            except Exception as e:  # a bad poll must not end auto-add
                self.events.log(f"auto-add: checking the folder failed: {e}")

    def poll_watch(self) -> list[Path]:
        """Check the watched folder once and add screenshots that finished writing (same size twice).

        Returns:
            The screenshots handed to adding.
        """
        if not self._watch_on or not self.atlas or self._closing:
            return []
        # the atlas this watcher was started for: a check still running when another atlas opens hands its
        # screenshots to that one's jobs, which the worker then skips (user, CodeRabbit)
        gen = getattr(self, "_watch_gen", self.generation)
        # this watcher's own list (start_watch makes a new one): a check still running for the atlas before marks
        # its own, not the new watcher's (CodeRabbit)
        seen = self._watch_seen
        key = (id(self.atlas), len(self.atlas.frames))
        if self._known_key != key:
            self._known = {str(Path(f["path"]).resolve()) for f in self.atlas.frames}
            self._known_key = key
        ready = []
        for f, size in self._watch_files().items():
            prev = seen.get(f)
            if prev == -1 or f in self._known:
                continue
            if prev is not None and prev == size and size > 0:
                if core.is_generated(Path(f)):
                    seen[f] = -1  # (the program's own pictures: never added)
                else:
                    ready.append(Path(f))
            else:
                seen[f] = size
        if ready:
            try:
                # marked here, where a failure takes the marks back: marked before, a file deleted after the scan
                # made the sort fail and left the others marked, never added (CodeRabbit)
                for q in ready:
                    seen[str(q)] = -1  # handed over; a failed detection hands it back (_watch_failed)
                ready.sort(key=_mtime)
                self.events.log(f"auto-add: {len(ready)} new screenshot(s): {', '.join(q.name for q in ready)}")
                self.add_screenshots(ready, mode="watch", gen=gen)
            except Exception:
                for q in ready:  # not queued: seen again on the next polls (CodeRabbit)
                    seen.pop(str(q), None)
                raise
        return ready

    def _watch_failed(self, paths: list[str]) -> None:
        """Let the watcher try screenshots again whose detection failed (WATCH_RETRIES more tries each).

        Args:
            paths: Full paths of the screenshots whose detection failed.
        """
        for f in paths:
            self._watch_tries[f] = self._watch_tries.get(f, 0) + 1
            if self._watch_tries[f] <= WATCH_RETRIES:
                self._watch_seen.pop(f, None)  # seen again on the next polls, then queued again
                self.events.log(
                    f"auto-add: {Path(f).name} failed; trying again ({self._watch_tries[f]}/{WATCH_RETRIES})"
                )
            else:
                self.events.log(f"auto-add: {Path(f).name} failed {WATCH_RETRIES + 1} times; left out (add it by hand)")


def _mtime(p: Path) -> float:
    """A file's modified time, 0 when it is gone (deleted or renamed since the folder was read)."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0
