"""app.keeping: part of AtlasSession (a mixin; see app/session.py): screenshots kept safe to delete.

The user's design (2026-11-14): inside the atlas's own folder, the screenshots' 1080p copies in terrain/ (the map's
pictures are read from them once a screenshot is gone: core.Atlas.picture) and the originals, once detected, in
used/, safe to delete then: what was detected stays with the atlas (atlas.json and its saved detections), and the
pictures come from the copies. Screenshots outside the atlas's own folder (Steam's, say) are never moved or touched:
only copied (user's rule).

A Reddit player asked whether deleting old screenshots loses their data (2026-11-25): the detections didn't, but the
map image rebuilt without them lost their ground, and the path check crashed on a missing picture.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from grand_project import core
from grand_project import logs as atlas_log

from .constants import KEEP_COPY_MB, KEEP_SECONDS_PER_SHOT

if TYPE_CHECKING:
    from .session import Opened

LOG = atlas_log.get("app")


class KeepingMixin:
    """AtlasSession mixin: the screenshots' copies (terrain/) and the detected originals' folder (used/)."""

    def keep_info(self) -> dict:
        """What the "Keep copies" prompt says about the open atlas (read only, no lock: a job may hold it).

        Returns:
            {"shots", "copied" (a copy kept), "todo" (to copy: the screenshot there, no copy yet), "lost" (neither:
            its picture is gone), "move" (in the atlas's own folder: moved to used/ once copied), "mb" and "seconds"
            (the copies' estimated size and time)}.
        """
        rec = self.opened
        atlas, path = rec.atlas, rec.path
        if atlas is None or path is None:
            raise ValueError("no atlas open")
        folder = path.parent.resolve()
        copied = todo = lost = move = 0
        for f in list(atlas.frames):
            shot, copy = Path(f["path"]), atlas.copy_path(f["path"])
            here, kept = shot.exists(), copy is not None and copy.exists()
            copied += kept
            todo += here and not kept
            lost += not here and not kept
            # (moved only where its name is free in used/: _keep_screenshots)
            move += (
                here and shot.parent.resolve() == folder and not (folder / core.SCREENSHOTS_USED / shot.name).exists()
            )
        return {
            "shots": len(atlas.frames),
            "copied": copied,
            "todo": todo,
            "lost": lost,
            "move": move,
            "mb": round(todo * KEEP_COPY_MB, 1),
            "seconds": round(todo * KEEP_SECONDS_PER_SHOT),
        }

    def keep_all(self) -> None:
        """Keep copies of every screenshot of the open atlas and move the detected ones in its folder to used/ (a
        "keep_all" job: minutes on a large atlas).

        Raises:
            ValueError: With no screenshots.
        """
        self._lock.refuse_stale()  # (made for another atlas: refused at once, see _queue_job)
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots to keep")
        self._queue_job([], "keep_all")

    def _run_keep(self) -> None:
        """The "keep_all" job (worker thread): every screenshot of the open atlas (_keep_screenshots)."""
        rec = self.opened
        with self._lock:
            names = [f["name"] for f in rec.atlas.frames] if rec.atlas else []
        self._keep_screenshots(rec, names)
        self._done(f"copies kept of {len(names)} screenshot(s)")

    def _unkeep(self, frames: list[dict]) -> None:
        """Put screenshots an Undo takes out of the atlas back from used/ into the atlas's folder (under the session
        lock, the open atlas): in used/, auto-add never saw them again, and deleting used/ deleted screenshots the
        atlas no longer holds (self review).

        Args:
            frames: The atlas frames being taken out.
        """
        if self.path is None:
            return
        folder = self.path.parent.resolve()
        back = 0
        for f in frames:
            src = Path(f["path"])
            try:
                if src.parent.resolve() != folder / core.SCREENSHOTS_USED or not src.exists():
                    continue
                dst = folder / src.name
                if dst.exists():
                    continue
                src.rename(dst)
                back += 1
            except OSError as e:
                LOG.warning(f"{src.name}: not moved back from {core.SCREENSHOTS_USED}/ ({e})")
        if back:
            self.events.log(f"{back} screenshot(s) put back from {core.SCREENSHOTS_USED}/ (undone: not in the atlas)")

    def _copy_detected(self, frames: list) -> None:
        """Keep copies of screenshots just detected, before they are placed (worker thread, no lock: file work on
        the job's own atlas, which can't be switched while the job runs).

        Args:
            frames: The detected screenshots (core.Frame, .path).
        """
        atlas = self.atlas
        if atlas is None or not frames:
            return
        for i, fr in enumerate(frames, 1):
            self.events.set_progress(f"keeping copies of the new screenshots {i} / {len(frames)}")
            try:
                atlas.write_copy(str(fr.path))
            except OSError as e:  # (a full disk, a locked folder: kept after the job instead, or not at all)
                LOG.warning(f"{Path(str(fr.path)).name}: no copy kept ({e})")

    def _keep_screenshots(self, rec: Opened, names: list[str]) -> None:
        """Keep copies of these screenshots of an atlas, then move the ones in its own folder into used/. Worker
        thread, after the job that added them: the copies are file work, outside the session lock; the moves and the
        paths they change happen under it, only while that atlas is still the open one.

        Args:
            rec: The atlas's record, taken by the job.
            names: The screenshots (their names in atlas.frames).
        """
        atlas, path = rec.atlas, rec.path
        if atlas is None or path is None or not names:
            return
        with self._lock:
            want = set(names)
            todo = [(f["name"], f["path"]) for f in atlas.frames if f["name"] in want]
        copied = []
        for i, (name, shot) in enumerate(todo, 1):
            self.events.set_progress(f"keeping copies of the screenshots {i} / {len(todo)}")
            try:
                if atlas.write_copy(shot):
                    copied.append((name, shot))
            except OSError as e:  # (a full disk, a locked folder: the screenshot stays where it is)
                LOG.warning(f"{name}: no copy kept ({e})")
        # the time a screenshot without a Steam name was taken comes from its file: kept with the atlas now, so
        # deleting it doesn't lose its place in "oldest to newest" and the timelapse
        with self._lock:
            frames_now = {f["name"]: f for f in atlas.frames}
        times = {}
        for name, _shot in copied:
            f = frames_now.get(name)
            if f is not None and f.get("taken") is None and not core.STEAM_TIME.search(name):
                t = core.capture_time(f)
                if t is not None:
                    times[name] = t
        folder = path.parent.resolve()
        moves = []
        for name, shot in copied:
            src = Path(shot)
            try:
                inside = src.parent.resolve() == folder  # (the atlas's own folder: never elsewhere, user's rule)
            except OSError:
                continue
            dst = folder / core.SCREENSHOTS_USED / src.name
            if inside and src.exists() and not dst.exists():
                moves.append((name, src, dst))
        if not moves and not times:
            return
        with self._lock:
            if not self.owns(rec):
                return  # another atlas opened since: this one keeps its screenshots where they are
            for f in atlas.frames:
                if f["name"] in times and f.get("taken") is None:
                    f["taken"] = times[f["name"]]
            moved = 0
            for name, src, dst in moves:
                try:
                    dst.parent.mkdir(exist_ok=True)
                    src.rename(dst)  # (the same folder's drive: one step)
                except OSError as e:  # (Steam still writing it, a virus scanner: left where it is)
                    LOG.warning(f"{name}: not moved to {core.SCREENSHOTS_USED}/ ({e})")
                    continue
                for f in atlas.frames:
                    if f["name"] == name and Path(f["path"]) == src:
                        f["path"] = str(dst)
                moved += 1
            if moved or times:
                atlas.save(path)
            if moved:
                self.events.log(
                    f"{moved} screenshot(s) moved to {core.SCREENSHOTS_USED}/ (detected: safe to delete, the atlas "
                    f"keeps their copies in {core.SCREENSHOT_COPIES}/)",
                    rec.scope,
                )
