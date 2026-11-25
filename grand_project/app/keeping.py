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

import numpy as np

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
        self._sort_dump(rec)
        self._done(f"copies kept of {len(names)} screenshot(s)")

    def _sort_dump(self, rec: Opened) -> None:
        """Sort an atlas's detected originals into used/ and dump/ by how much of the map picture each owns
        (core.owned_shares): under OWNER_DUMP_SHARE of its own area it is dump (everything it shows is shown better
        by a more central screenshot), else used. Only originals already in used/ or dump/ of the atlas's own folder
        move, and only those whose status changed (none, usually). Their copies all stay, so one sent to dump can
        win its spots back (a newer one undone or deleted) and return to used/. After every add, undo, Fix seams and
        keep job; worker or Fix seams' thread.

        Args:
            rec: The atlas's record.
        """
        atlas, path = rec.atlas, rec.path
        if atlas is None or path is None or not self.owns(rec):
            return
        frames, labels = self._ownership_input(atlas, rec)
        try:
            shares = core.owned_shares(atlas, frames, labels)
        except Exception:  # (never the job's end: a failure only leaves the folders as they are)
            LOG.exception("sorting the screenshots into used/ and dump/ failed")
            return
        folder = path.parent.resolve()
        used, dump = folder / core.SCREENSHOTS_USED, folder / core.SCREENSHOTS_DUMP
        moves = []
        for f in frames:
            src = Path(f["path"])
            try:
                here = src.parent.resolve()
            except OSError:
                continue
            if here not in (used, dump) or not src.exists():
                continue  # (not yet kept, elsewhere, or deleted: left alone)
            want = dump if shares.get(f["name"], 1.0) < core.OWNER_DUMP_SHARE else used
            if want == here or (want / src.name).exists():
                continue
            # used/ is safe to delete only with the copies: slim down removed the ones of dump, so one going back
            # gets its copy again first (self review)
            try:
                if want == used and not atlas.write_copy(str(src)):
                    continue
            except OSError as e:
                LOG.warning(f"{f['name']}: no copy kept, left in {core.SCREENSHOTS_DUMP}/ ({e})")
                continue
            moves.append((f["name"], src, want / src.name))
        if not moves:
            return
        with self._lock:
            if not self.owns(rec):
                return
            to_dump = back = 0
            for name, src, dst in moves:
                if not src.exists() or dst.exists():
                    continue  # (moved meanwhile, by another sort or the player; rename replaces a file on Linux/macOS)
                try:
                    dst.parent.mkdir(exist_ok=True)
                    src.rename(dst)
                except OSError as e:
                    LOG.warning(f"{name}: not moved to {dst.parent.name}/ ({e})")
                    continue
                for f in atlas.frames:
                    if f["name"] == name and Path(f["path"]) == src:
                        f["path"] = str(dst)
                        if dst.parent == used:
                            f.pop("slimmed", None)  # (its copy is back)
                to_dump += dst.parent == dump
                back += dst.parent == used
            if to_dump or back:
                atlas.save(path)
                parts = []
                if to_dump:
                    parts.append(f"{to_dump} to {core.SCREENSHOTS_DUMP}/ (shown better by others: delete these first)")
                if back:
                    parts.append(f"{back} back to {core.SCREENSHOTS_USED}/ (they show a spot best again)")
                self.events.log("screenshots sorted: " + "; ".join(parts), rec.scope)

    def _dump_names(self, atlas, rec: Opened | None, wait: bool = True, clean: bool = False) -> list[str] | None:
        """Return the screenshots that own (almost) no spot of the map picture (core.owned_shares under
        OWNER_DUMP_SHARE): the clean map's ownership for the open atlas when there is one, else the grid.

        Args:
            atlas: The atlas.
            rec: Its record when it is the open one (its clean map), else None.
            wait: Wait for the session lock to read the clean map with its screenshots (False: a prompt, which
                never waits for a job).
            clean: Only from the clean map's ownership (None without one): the grid knows placements only, not
                each screenshot's fog, so it never decides what is deleted (slim down; CodeRabbit).

        Returns:
            Their names, or None (clean, and no clean map that fits the screenshots).
        """
        frames, labels = self._ownership_input(atlas, rec, wait)
        if clean and labels is None:
            return None
        shares = core.owned_shares(atlas, frames, labels)
        return [n for n, v in shares.items() if v < core.OWNER_DUMP_SHARE]

    def _ownership_input(self, atlas, rec: Opened | None, wait: bool = True) -> tuple[list[dict], tuple | None]:
        """Return what core.owned_shares works from: the screenshots, and the clean map's ownership while rec is the
        open atlas, taken as one under the session lock (a change can't come between them).

        Args:
            atlas: The atlas.
            rec: Its record when it is the open one, else None (the grid).
            wait: Wait for the session lock; False (a prompt, never waiting for a job): without it, from the grid.

        Returns:
            (copies of its frames that have a picture, (ownership map, names, origin) or None). Only screenshots with
            a picture compete: one with neither file nor copy won every tie, and a copy that was the last picture
            of a spot was slimmed away (CodeRabbit). The clean map only when its names are the screenshots as they
            are: it names one an undo took out, or misses one added while the map image is made again (CodeRabbit).
        """
        locked = rec is not None and self._lock.acquire(blocking=wait)
        try:
            frames = [dict(f) for f in list(atlas.frames)]  # (a copy: placing appends meanwhile)
            # (unlocked, a prompt: the clean map as it is now; the names check below drops it when it doesn't fit)
            lab, ter = (self.labels, self.terrain) if rec is not None and self.owns(rec) else (None, None)
        finally:
            if locked:
                self._lock.release()
        everyone = {f["name"] for f in frames}
        frames = [f for f in frames if atlas.has_picture(f["path"])]
        labels = None
        if lab is not None and ter is not None:
            names, pictured = set(lab[1]), {f["name"] for f in frames}
            if names <= everyone and pictured <= names and not self._lost_own_spots(lab, pictured):
                labels = (lab[0], list(lab[1]), ter[2])
        return frames, labels

    @staticmethod
    def _lost_own_spots(lab: tuple, pictured: set[str]) -> bool:
        """Tell whether a screenshot with no picture left still owns spots of a clean map: those spots count for no
        one, so a screenshot showing them too looked like it showed nothing, and slim down took the last picture of
        them (CodeRabbit). One slimmed away owns none: the clean map still fits then.

        Args:
            lab: (ownership map, names) of the clean map.
            pictured: The names of the screenshots with a picture.
        """
        lost = [k for k, n in enumerate(lab[1]) if n not in pictured]
        if not lost:
            return False
        counts = np.bincount(lab[0].ravel().astype(np.int64) + 1, minlength=len(lab[1]) + 1)[1:]
        return any(counts[k] > 0 for k in lost)

    def slim_info(self, atlas, rec: Opened | None = None) -> dict:
        """What Re-check's slim down would remove: the copies of screenshots in dump (owning no spot of the map).

        Args:
            atlas: The atlas (the open one, or another read from its file: the Re-check prompt).
            rec: Its record when it is the open one.

        Returns:
            {"count", "mb" of the copies there now, "clean": whether there is a clean map to tell (Fix seams):
            without one slim down removes nothing}.
        """
        names = self._dump_names(atlas, rec, wait=False, clean=True)
        if names is None:
            return {"count": 0, "mb": 0.0, "clean": False}
        by_name = {f["name"]: f for f in list(atlas.frames)}
        sizes = []
        for n in names:
            f = by_name.get(n)
            c = atlas.copy_path(f["path"]) if f is not None else None
            if c is not None and c.exists():
                sizes.append(c.stat().st_size)
        return {"count": len(sizes), "mb": round(sum(sizes) / 1e6, 1), "clean": True}

    def _slim_down(self, rec: Opened) -> None:
        """Re-check's slim down (the remembered "recheck_slim" setting, user: packaged with Re-check): remove the
        copies of the screenshots owning no spot of the map, by the clean map's ownership only (it knows each
        screenshot's fog; the grid doesn't). Disk saved, at a cost: one whose original is gone too can't win a spot
        back later (a newer one undone or deleted). Worker thread, end of a Re-check.

        Args:
            rec: The atlas's record, taken by the Re-check.
        """
        if not self.settings.get("recheck_slim") or rec.atlas is None:
            return
        atlas = rec.atlas
        try:
            found = self._dump_names(atlas, rec, clean=True)
        except Exception:
            LOG.exception("slim down: the screenshots' ownership couldn't be worked out")
            return
        if found is None:
            self.events.log(
                "slim down: nothing removed, it needs a clean map (Fix seams) of the screenshots as they are now: only "
                "that knows, fog included, which ones show no spot of the map",
                rec.scope,
            )
            return
        names = set(found)
        removed = freed = 0
        slimmed = []
        for f in list(atlas.frames):
            if f["name"] not in names:
                continue
            c = atlas.copy_path(f["path"])
            if c is None or not c.exists():
                continue
            try:
                size = c.stat().st_size
                c.unlink()
            except OSError as e:
                LOG.warning(f"slim down: {c.name} not removed ({e})")
                continue
            removed += 1
            freed += size
            slimmed.append(f)
        if slimmed:  # (kept with the atlas: gone for good later, they're no "screenshots not found" warning)
            with self._lock:
                if self.owns(rec):
                    for f in slimmed:
                        f["slimmed"] = True
                    atlas.save(rec.path)
        if removed:
            self.events.log(
                f"slim down: removed the copies of {removed} screenshot(s) that show no spot of the map "
                f"({freed / 1e6:.0f} MB)",
                rec.scope,
            )

    def _unkeep(self, frames: list[dict]) -> None:
        """Put screenshots an Undo takes out of the atlas back from used/ or dump/ into the atlas's folder (under the
        session lock, the open atlas): there, auto-add never saw them again, and deleting those folders deleted
        screenshots the atlas no longer holds (self review).

        Args:
            frames: The atlas frames being taken out.
        """
        if self.path is None:
            return
        folder = self.path.parent.resolve()
        back = 0
        kept_in = (folder / core.SCREENSHOTS_USED, folder / core.SCREENSHOTS_DUMP)
        for f in frames:
            src = Path(f["path"])
            try:
                if src.parent.resolve() not in kept_in or not src.exists():
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
                atlas.write_copy(str(fr.path), getattr(fr, "sha", None))  # (not in the atlas yet: its content)
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
            c = atlas.copy_path(shot)
            if c is not None and not c.exists():  # (most were copied as they were detected: no second count)
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
