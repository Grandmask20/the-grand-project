"""viewer.autoadd: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import os
import queue
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np

from grand_project import builder, core
from grand_project import cities as atlas_cities
from grand_project import finalize as atlas_finalize
from grand_project import paths as rc_paths
from grand_project.core import islands

from .constants import (
    PROFILE,
    RECENT_COL,
    RECENT_FADE,
    RECENT_KEEP,
    UNDO_KEEP,
    WATCH_ASK,
    WATCH_BATCH,
    WATCH_POLL_MS,
    WATCH_RETRIES,
    WEAK_INLIERS,
    WEAK_NCC,
)
from .helpers import LOG, put_text
from .settings import save_settings


class AutoAddMixin:
    """Adding screenshots in the Viewer window: the background worker and its queue, auto-add (the watched
    folder), hand placement (drag a file in), undo / recently added / waiting, saving and closing.

    A mixin of the Viewer class (viewer/app.py). The worker thread changes the atlas only while holding
    `self._lock` and talks to the window through `self._q` ((kind, value) messages, handled by `_handle` on
    the window thread); methods run on the window (Tk) thread unless they say otherwise.
    """

    # ------------------------------------------------------------------ progress on the map
    def _set_progress(self, text):
        """Shows (or clears) the progress box on the map and the status bar text.

        The box keeps the time the first text was shown and counts seconds from it; while it is shown the map
        is redrawn every 500 ms so the dots and seconds move.

        Args:
            text: The progress text, or None to remove the box.
        """
        self._progress = (text, self._progress[1] if self._progress else time.time()) if text else None
        if text:
            self.status.set(text)
        self.request_redraw()
        if text and not getattr(self, "_progress_tick", None):
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _tick_progress(self):
        """Redraws the progress box every 500 ms while it is shown (a Tk `after` timer)."""
        self._progress_tick = None
        if self._progress:
            self.request_redraw()
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _draw_progress(self, img, w, h):
        """Draws the progress box (text, moving dots, seconds since it started) at the top right of the map image.

        Args:
            img: The map image being drawn (BGR, changed in place).
            w: Image width (screen px).
            h: Image height (screen px).
        """
        if not self._progress:
            return
        text, t0 = self._progress
        dots = "." * (1 + int(time.time() * 2) % 3)
        line = f"{text.rstrip('.…')}{dots}   {time.time() - t0:.0f}s"
        tw = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0][0] + 4  # the text and its outline
        x0 = w - tw - 36
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (25, 25, 25), -1)
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (0, 200, 255), 1)
        put_text(img, line, (x0 + 12, 33), (0, 220, 255), 0.55)

    def _draw_pending(self, img):
        """Outlines the just-placed screenshots, drawn until the map updates.

        Args:
            img: The map image being drawn (BGR, changed in place).
        """
        for poly in self._pending_outline:
            pts = self.to_screen(poly).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 220, 255), 2, cv2.LINE_AA)

    # ------------------------------------------------------------------ hand placement (drag a file in)
    def start_ghost(self, path: Path, sx=None, sy=None):
        """Shows a see-through screenshot to put roughly in place; Enter / double-click fits it.

        The screenshot follows drags on the map; Esc cancels.

        Args:
            path: The screenshot file.
            sx: Where to put its middle, x on the map canvas (screen px); default: the middle of the map.
            sy: Where to put its middle, y on the map canvas (screen px); default: the middle of the map.
        """
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            return
        img = core.read_screenshot(str(path))
        if img is None:
            self.status.set(f"not an image: {path.name}")
            return
        w, h = self.canvas_size()
        sx = w / 2 if sx is None else sx
        sy = h / 2 if sy is None else sy
        cx, cy = self.to_world(sx, sy)
        R = core.rectifier(
            img.shape[1], img.shape[0], core.constants.HORIZON / img.shape[0] if core.constants.HORIZON else None
        )
        small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)
        self._ghost = {
            "path": Path(path),
            "img": small,
            "R": R @ np.diag([2.0, 2.0, 1.0]),
            "w": img.shape[1],
            "h": img.shape[0],
            "cx": cx,
            "cy": cy,
            "drag": None,
        }
        self.canvas.focus_set()
        self.status.set(
            f"{path.name}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels)"
        )
        self.request_redraw()

    def _draw_ghost(self, img, w, h):
        """Draws the screenshot being placed by hand, see-through and outlined, with a hint how to fit it.

        Args:
            img: The map image being drawn (BGR, changed in place).
            w: Image width (screen px).
            h: Image height (screen px).
        """
        g = self._ghost
        if not g:
            return
        V = np.array([[self.z, 0, -self.cx * self.z + w / 2], [0, self.z, -self.cy * self.z + h / 2], [0, 0, 1]])
        H = V @ np.array([[1, 0, g["cx"]], [0, 1, g["cy"]], [0, 0, 1]]) @ g["R"]
        warped = cv2.warpPerspective(g["img"], H, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
        mask = cv2.warpPerspective(np.full(g["img"].shape[:2], 255, np.uint8), H, (w, h), flags=cv2.INTER_NEAREST) > 0
        img[mask] = cv2.addWeighted(warped, 0.55, img, 0.45, 0)[mask]
        corners = core.persp(
            H, [[0, 0], [g["img"].shape[1], 0], [g["img"].shape[1], g["img"].shape[0]], [0, g["img"].shape[0]]]
        ).astype(np.int32)
        cv2.polylines(img, [corners], True, (0, 220, 255), 2, cv2.LINE_AA)
        c = corners.mean(axis=0).astype(int)
        put_text(img, "Enter / double-click: fit it here    Esc: cancel", (c[0] - 190, c[1]), (0, 220, 255), 0.55)

    def fit_ghost(self):
        """Lines up the screenshot placed by hand near where it was put (a "drop" job for the worker).

        Bound to <Return> on the map canvas; also called by a double-click.
        """
        g, self._ghost = self._ghost, None
        if not g:
            return
        self.request_redraw()
        if not self._detector_ready():
            return
        self._queue_job([g["path"]], ("drop", g["cx"], g["cy"]))

    def _cancel_lasso(self):
        """Stops drawing a city biome lasso (Esc on the map canvas)."""
        self._lasso = None
        self.canvas.configure(cursor="fleur")
        self.status.set("lasso cancelled")
        self.request_redraw()

    def _cancel_bm_mode(self):
        """Leaves bookmark mode without adding a bookmark (Esc on the map canvas)."""
        if getattr(self, "_bm_mode", False):
            self._bm_mode = False
            self.canvas.configure(cursor="fleur")
            self.status.set("bookmark cancelled")

    def cancel_ghost(self):
        """Drops the screenshot being placed by hand (Esc on the map canvas)."""
        self._ghost = None
        self.status.set("placement cancelled")
        self.request_redraw()

    def on_drop(self, e):
        """Handles screenshot files dropped on the map (drag and drop, needs tkinterdnd2).

        Bound to <<Drop>> on the map canvas. One file is shown where it was dropped to be placed by hand;
        several files are added the normal way.

        Args:
            e: The Tk (tkinterdnd2) event; `e.data` holds the file list.
        """
        files = [Path(f) for f in self.root.tk.splitlist(e.data)]
        files = [f for f in files if core.is_screenshot(f)]
        if not files:
            self.status.set("drop screenshot image files (.png, .jpg)")
            return
        x = e.x_root - self.canvas.winfo_rootx()
        y = e.y_root - self.canvas.winfo_rooty()
        if len(files) > 1:  # several files: add them the normal way
            self.add_screenshots(files)
            return
        self.start_ghost(files[0], x, y)

    def ask_place(self):
        """Asks for a screenshot file and starts placing it by hand (File > Place a screenshot by hand)."""
        p = filedialog.askopenfilename(
            title="Screenshot to place by hand",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
            initialdir=self._hand_watch() or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if p:
            self.start_ghost(Path(p))

    def save(self):
        """Saves the atlas (File > Save, Ctrl/Cmd+S).

        If the worker holds the atlas lock for more than 0.2 s, tries again 1.5 s later instead of waiting.
        """
        if not self.atlas or not self.path:
            return
        if not self._lock.acquire(timeout=0.2):  # worker busy: it saves when it finishes
            self.root.after(1500, self.save)
            return
        try:
            self.atlas.save(self.path)
        finally:
            self._lock.release()
        self.status.set(f"saved {self.path}")

    def save_if_dirty(self):
        """Saves the open atlas, if there is one (before opening another atlas)."""
        if self.atlas and self.path:
            self.save()

    def export_pngs(self):
        """Writes the map PNGs (<stem>_composite.png and _network.png) into the atlas's files folder
        (File > Export map PNGs).
        """
        if not self.atlas or not self.path or not self.atlas.frames:
            return
        builder.export(self.atlas, self.path)
        self.log(f"wrote {self.path.stem}_composite.png and _network.png in {core.atlas_files(self.path).name}/")

    def refinalize(self):
        """Starts a full re-check of the atlas, in the background (minutes on a large atlas)."""
        if not self.atlas or not self.atlas.frames:
            return
        self._queue_job([], "recheck_all")

    def on_close(self):
        """Closes the window (window close button, File > Exit).

        While the worker has jobs, the step in progress is finished and saved first (closing used to drop it:
        the save waited for the worker's lock and the window was gone before it ran); jobs still queued are
        left (auto-add finds their screenshots in the folder next time). A second click while waiting offers to
        quit at once without saving.
        """
        if self.working():
            if self._closing:  # second click while waiting
                if messagebox.askyesno(
                    "Atlas viewer",
                    "Quit now without waiting?\n\nThe step in progress is lost; the atlas keeps what was saved last.",
                ):
                    self._finish_close(save=False)
                return
            if not messagebox.askyesno(
                "Atlas viewer",
                "Screenshots are still being processed.\n\nClose once the current step is finished and saved? "
                "(Screenshots still queued are left out; auto-add finds them in the folder next time.)",
            ):
                return
            self._closing = True
            self._drop_queued_jobs()
            self.status.set("closing: finishing the current step first")
            self.root.after(200, self._close_when_idle)
            return
        self._finish_close()

    def _close_when_idle(self):
        """Checks every 200 ms until the worker is idle, then closes the window."""
        if self.working():
            self.root.after(200, self._close_when_idle)
            return
        self._finish_close()

    def _finish_close(self, save: bool = True):
        """Stops Fix seams, saves the atlas and the window settings (size, layers, hidden icons), and destroys the
        window.

        Args:
            save: False to quit without saving the atlas.
        """
        self._closing = True
        self.stop_seams()
        if save and self.atlas and self.path:
            with self._lock:  # the worker is idle; a PNG export may hold it for a moment
                self.atlas.save(self.path)
        self.settings["geometry"] = self.root.geometry()
        self.settings["layers"] = {k: v.get() for k, v in self.layers.items()}
        self.settings["multi_only"] = self.multi_only.get()
        self.settings["icons_hidden"] = sorted(self.icon_hidden)
        save_settings(self.settings)
        self.root.destroy()

    # ------------------------------------------------------------------ adding screenshots
    def _detector_ready(self) -> bool:
        """Checks that the detector database (paths.DATABASE) is there; otherwise says so in a message box
        (nothing can be detected).

        Returns:
            True when it is there.
        """
        if rc_paths.DATABASE.exists():
            return True
        messagebox.showerror(
            "Atlas viewer",
            f"The detector database is missing:\n{rc_paths.DATABASE}\n\n"
            "Reinstall, or set DATABASE in local_paths.json.",
        )
        return False

    def ask_add(self):
        """Asks for screenshot files and adds them (File > Add screenshots).

        With no atlas open, a new atlas is made first. The folder is remembered for next time.
        """
        if self.working():
            return
        if not self.atlas or not self.path:
            self.new_atlas()
            if not self.atlas or not self.path:
                return
        paths = filedialog.askopenfilenames(
            title="Add atlas screenshots",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All", "*.*")],
            initialdir=self.settings.get("shots_dir", self._initial_dir()),
        )
        if paths:
            self.settings["shots_dir"] = str(Path(paths[0]).parent)
            self.add_screenshots([Path(p) for p in paths])

    def working(self) -> bool:
        """Tells whether a job is queued or running (any kind: added by hand, auto-add, re-check, undo, retry,
        drop).

        Opening or switching atlases waits for this: a job works on the atlas it was queued for.

        Returns:
            True while there is work.
        """
        return self._busy or self._jobs.unfinished_tasks > 0

    def _queue_job(self, paths, mode):
        """Hands a job to the background worker, tagged with the atlas it is for (not started while closing).

        Args:
            paths: Screenshot files (may be empty, e.g. for "undo" or "recheck_all").
            mode: The kind of job: "manual", "watch", "recheck_all", "undo", ("drop", x, y) with x, y in atlas
                units, or ("retry", indices into the waiting list or None for all).
        """
        if self._closing:
            self.log(f"closing: {len(paths) or 'a'} job(s) not started")
            return
        self._jobs.put((list(paths), mode, self.atlas))

    def _drop_queued_jobs(self):
        """Forgets jobs that have not started (closing)."""
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                return
            self._jobs.task_done()

    def add_screenshots(self, paths: list[Path], sync: bool = False, mode: str = "manual"):
        """Adds screenshots to the atlas, normally through the background worker.

        A "manual" add turns the Add button off until it is done.

        Args:
            paths: Screenshot files.
            sync: True to run the job now on the calling thread and handle its messages at once (tests).
            mode: "manual" (added by hand) or "watch" (auto-add); see _queue_job.
        """
        if not self._detector_ready():
            return
        if mode == "manual":
            self._busy = True
            self.btn_add.state(["disabled"])
        if sync:
            self._run_job(list(paths), mode)
            self._drain_queue()
        else:
            self._queue_job(paths, mode)

    # ------------------------------------------------------------------ background worker
    def _worker(self):
        """The background worker thread: runs queued jobs one at a time, forever.

        Auto-add screenshots that arrived meanwhile are run as one batch (up to WATCH_BATCH), so one re-check
        covers them (v1.00 re-checked after every 2-3: ~45 s each). A job queued for an atlas that is no longer
        open is skipped. Failures are logged and reported to the window.
        """
        while True:
            paths, mode, atlas = self._jobs.get()
            jobs = 1
            if mode == "watch":  # screenshots that arrived meanwhile: one batch, one re-check
                paths = list(paths)  # (v1.00 re-checked after every 2-3: ~45 s each)
                with self._jobs.mutex:
                    q = self._jobs.queue
                    while q and q[0][1] == "watch" and q[0][2] is atlas and len(paths) < WATCH_BATCH:
                        paths += q.popleft()[0]
                        jobs += 1
            try:
                if atlas is not self.atlas or self._closing:  # queued for an atlas that is no longer open
                    self._q.put(("log", f"skipped a job queued for another atlas ({mode})"))
                    self._q.put(("done", mode))
                else:
                    self._run_job(paths, mode)
            except Exception as e:
                LOG.exception(f"adding failed ({mode}): {paths}")
                self._q.put(("log", f"adding failed: {e}"))
                if mode == "watch":  # the watcher tries these again
                    self._q.put(("watch_failed", [str(p) for p in paths]))
                self._q.put(("done", mode))
            finally:
                for _ in range(jobs):
                    self._jobs.task_done()

    def _cache_dir(self) -> Path:
        """Returns the detection cache folder of the open atlas (<stem>_frames next to the atlas file).

        Returns:
            The folder.
        """
        return self.path.with_name(self.path.stem + "_frames")

    def _redetect(self, paths: list[Path]):
        """Detects these screenshots again with the current detector (their caches are rewritten). Worker thread.

        Args:
            paths: Screenshot files.
        """
        self.log(f"Re-check: {len(paths)} screenshot(s) were detected by an older detector: detecting them again")
        self._q.put(("progress", f"detecting {len(paths)} screenshots again (newer detector)"))
        for p, err in builder.detect_uncached(paths, self._cache_dir(), log=lambda t: self._q.put(("log", t))).items():
            LOG.warning(f"{Path(p).name}: detection failed in a worker: {err}")
        for i, p in enumerate(paths, 1):
            self._q.put(("progress", f"detecting again {p.name} ({i}/{len(paths)})"))
            try:
                builder.extract_frame(p, self._cache_dir())
            except Exception as e:
                LOG.exception(f"{p.name}: detection failed")
                self._q.put(("log", f"{p.name}: detection failed: {e}"))

    def _run_job(self, paths, mode):
        """Runs one job: detects the screenshots, places them in the atlas, updates the map image and saves.

        Worker thread (or the window thread when added with sync=True). "recheck_all" first detects again
        screenshots detected by an older detector (user: Re-check = rescan), then re-checks the whole atlas.
        Each placement saves an undo snapshot first; added screenshots are pasted into the map image and, for
        auto-add, maps and paths around them are re-checked. Ends with a "placed" message to the window.

        Args:
            paths: Screenshot files.
            mode: The kind of job; see _queue_job.
        """
        if mode == "undo":
            self._run_undo()
            return
        retry = isinstance(mode, tuple) and mode[0] == "retry"
        if mode == "recheck_all":
            # screenshots detected by an older detector are detected again first (user: Re-check = rescan)
            stale = [
                Path(f["path"])
                for f in self.atlas.frames
                if Path(f["path"]).exists() and not builder.is_cached(Path(f["path"]), self._cache_dir())
            ]
            if stale:
                self._redetect(stale)
            self._q.put(("progress", "re-checking the whole atlas"))
            with self._lock:
                self.atlas.rebuild_icons(builder.cached_frames(self.path, self.atlas.frames))
                atlas_finalize.finalize(self.atlas, log=lambda t: self._q.put(("log", t)))
                self.atlas.save(self.path)
            self._q.put(("placed", ("recheck", 1, [], len(self.atlas.frames))))
            return
        cache_dir = self.path.with_name(self.path.stem + "_frames")
        frames = []
        failed = []
        if len(paths) > 1:
            self._q.put(("progress", f"detecting {len(paths)} screenshots"))
            for p, err in builder.detect_uncached(paths, cache_dir, log=lambda t: self._q.put(("log", t))).items():
                LOG.warning(f"{Path(p).name}: detection failed in a worker: {err}")
        for i, p in enumerate(paths, 1):
            self._q.put(("progress", f"detecting {p.name} ({i}/{len(paths)})"))
            try:
                fr = builder.extract_frame(p, cache_dir)
                frames.append(fr)
                self._q.put(("log", f"{p.name}: {int(fr.usable.sum())} maps, {len(getattr(fr, 'icons', []))} icons"))
            except Exception as e:
                LOG.exception(f"{p.name}: detection failed")
                self._q.put(("log", f"{p.name}: detection failed: {e}"))
                failed.append(str(p))
        if failed and mode == "watch":  # the watcher tries these again (it had marked them as handed over)
            self._q.put(("watch_failed", failed))
        self._q.put(("progress", "placing"))
        with self._lock:
            before = len(self.atlas.frames)
            snapshot = self._snapshot()
            if retry:  # waiting screenshots, searched again
                idx = mode[1]
                aside = [f for k, f in enumerate(self._pending_watch) if idx is not None and k not in idx]
                self._pending_watch = [f for k, f in enumerate(self._pending_watch) if idx is None or k in idx]
                added, refused = self._place_watched([])
                self._pending_watch += aside
                refused = [Path(f.path).name for f in self._pending_watch]
            elif isinstance(mode, tuple):  # dropped by hand near (x, y)
                added, refused = self._place_dropped(frames, mode[1], mode[2])
            elif mode == "manual":
                lines = []
                added, refused = builder.place_frames(self.atlas, frames, log=lines.append)
                for ln in lines:
                    if ln.strip().startswith(("MERGED", "first", "NOT ADDED", "final")) or "==" in ln:
                        self._q.put(("log", ln))
            else:
                added, refused = self._place_watched(frames)
            if added:
                new = self.atlas.frames[-added:]
                self._q.put(("added_names", ([f["name"] for f in new], snapshot)))
                self._q.put(("outline", [self._poly(f) for f in new]))
                if not self._paste_terrain(new):  # outside the map: rebuild it in the background
                    self._q.put(("rebuild_terrain", None))
                if mode != "manual":
                    self._q.put(("progress", "updating maps and paths around the new screenshot"))
                    builder.recheck(self.atlas, [f["name"] for f in new], log=lambda t: self._q.put(("log", t)))
                self._q.put(("progress", "saving"))
                self.atlas.save(self.path)
            else:  # nothing added: nothing to undo
                with contextlib.suppress(OSError):
                    snapshot.unlink()
        self._q.put(("placed", (mode, added, refused, before)))

    # ------------------------------------------------------------------ undo / recent additions
    def _undo_dir(self) -> Path:
        """Returns the undo snapshot folder of the open atlas (<stem>_undo in its files folder), made if missing.

        Returns:
            The folder.
        """
        d = core.atlas_files(self.path) / (self.path.stem + "_undo")
        d.mkdir(exist_ok=True)
        return d

    def _snapshot(self) -> Path:
        """Saves the atlas as it is before an add (worker thread, under the lock).

        Returns:
            The snapshot file.
        """
        f = self._undo_dir() / f"before_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.atlas.frames)}.json"
        self.atlas.save(f)
        return f

    def _remember_add(self, names, snapshot):
        """Records an add for undo (keeping the last UNDO_KEEP; older snapshot files are deleted) and adds the
        screenshots to the recently added list (one screenshot per entry, the last RECENT_KEEP).

        Args:
            names: Names of the screenshots added.
            snapshot: The snapshot file of the atlas before the add.
        """
        self._undo.append({"file": snapshot, "names": names})
        while len(self._undo) > UNDO_KEEP:
            old = self._undo.pop(0)
            with contextlib.suppress(OSError):
                Path(old["file"]).unlink()
        self.recent += list(names)  # one screenshot per entry, in the order they were added
        self.recent = self.recent[-RECENT_KEEP:]
        self._recent_pick = None
        self._refresh_recent()

    def _refresh_recent(self):
        """Refills the Recently added list (newest first) and the Waiting list (with how often each was tried),
        and turns the Undo button on or off.
        """
        self.recent_list.delete(0, "end")
        for k, n in enumerate(reversed(self.recent)):  # newest first, line by line
            self.recent_list.insert("end", ("NEWEST  " if k == 0 else f"{k:>4}    ") + n)
        self.btn_undo.state(["!disabled"] if self._undo else ["disabled"])
        self.wait_list.delete(0, "end")
        tries = getattr(self, "_wait_tries", {})
        for fr in self._pending_watch:
            name = Path(fr.path).name
            n = tries.get(name, 0)
            self.wait_list.insert("end", f"{name}   - waiting, tried {n}x" if n else f"{name}   - queued")

    def goto_recent(self, index=None):
        """Centres the map on a recently added screenshot and outlines it until the next add.

        Called from <<ListboxSelect>> on the Recently added list and by Go to newest.

        Args:
            index: Line in the list (0 = newest); None uses the selected line.
        """
        if index is None:
            sel = self.recent_list.curselection()
            if not sel:
                return
            index = sel[0]
        flat = list(reversed(self.recent))
        if index >= len(flat):
            return
        f = next((f for f in self.atlas.frames if f["name"] == flat[index]), None)
        if f is None:
            return
        self._recent_pick = f["name"]  # outlined on the map until the next add
        c = self._poly(f).mean(axis=0)
        self.center_on(c[0], c[1], min_zoom=0.25)
        self.request_redraw()

    def undo_last(self):
        """Removes the screenshots added last, after asking (Undo last add, Ctrl/Cmd+Z); runs as an "undo" job."""
        if not self._undo or self.working():
            return
        names = self._undo[-1]["names"]
        if not messagebox.askyesno("Undo last add", "Remove the screenshot(s) added last?\n\n" + "\n".join(names)):
            return
        self._queue_job([], "undo")

    def _run_undo(self):
        """Puts the atlas back to its snapshot from before the last add, keeping the bookmarks. Worker thread."""
        entry = self._undo.pop()
        self._q.put(("progress", "undoing the last add"))
        with self._lock:
            old = core.Atlas.load(entry["file"])
            keep_bookmarks = self.atlas.bookmarks
            for attr in ("nodes", "edges", "landmarks", "frames", "icons", "final"):
                setattr(self.atlas, attr, getattr(old, attr))
            self.atlas.bookmarks = keep_bookmarks
            self.atlas.save(self.path)
        with contextlib.suppress(OSError):
            Path(entry["file"]).unlink()
        self._q.put(("undone", entry["names"]))

    def retry_waiting(self, selected: bool = True):
        """Searches again for screenshots in the waiting queue, e.g. after others were placed; runs in the
        background like an auto-add.

        Args:
            selected: True for the ones selected in the Waiting list, False for all.
        """
        if not self._pending_watch:
            self.status.set("nothing is waiting")
            return
        idx = None
        if selected:
            sel = self.wait_list.curselection()
            if not sel:
                self.status.set("select a waiting screenshot first (or use Retry all)")
                return
            idx = [k for k in sel if k < len(self._pending_watch)]
        self.status.set(f"retrying {len(idx) if idx else len(self._pending_watch)} waiting screenshot(s)")
        self._queue_job([], ("retry", idx))

    def place_waiting(self):
        """Takes the selected waiting screenshot out of the queue and starts placing it by hand (Place by hand)."""
        sel = self.wait_list.curselection()
        if not sel or sel[0] >= len(self._pending_watch):
            return
        fr = self._pending_watch.pop(sel[0])
        self._refresh_recent()
        self.start_ghost(Path(fr.path))

    def _draw_recent(self, img):
        """Outlines recent additions on the map.

        The newest screenshot is outlined; the 4 before it fade out (5 in all, one screenshot each, not per
        batch); a screenshot clicked in the Recently added list is outlined too. Shown when the Recent additions
        layer is on.

        Args:
            img: The map image being drawn (BGR, changed in place).
        """
        if not self.recent or not self.atlas or not self.layers["Recent additions"].get():
            return
        by_name = {f["name"]: f for f in self.atlas.frames}
        older = list(reversed(self.recent[:-1]))[: RECENT_FADE - 1]  # newest-but-one first
        for k, n in reversed(list(enumerate(older))):  # draw the oldest first
            alpha = 1 - (k + 1) / RECENT_FADE  # 0.8, 0.6, 0.4, 0.2: fades with age
            f = by_name.get(n)
            if f is None:
                continue
            layer = img.copy()
            pts = self.to_screen(self._poly(f)).astype(np.int32)
            cv2.polylines(layer, [pts], True, RECENT_COL, 2, cv2.LINE_AA)
            cv2.addWeighted(layer, alpha, img, 1 - alpha, 0, dst=img)
        marks = [(self.recent[-1], "newest: ", RECENT_COL)]
        pick = getattr(self, "_recent_pick", None)
        if pick and pick != self.recent[-1]:
            marks.append((pick, "", (255, 255, 255)))
        for n, label, col in marks:
            f = by_name.get(n)
            if f is None:
                continue
            pts = self.to_screen(self._poly(f)).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 0, 0), 6, cv2.LINE_AA)
            cv2.polylines(img, [pts], True, col, 3, cv2.LINE_AA)
            top = pts[np.argmin(pts[:, 1])]
            put_text(img, label + n[-10:], (top[0] + 6, top[1] + 22), col, 0.55)

    def _poly(self, f):
        """Returns a screenshot's outline on the atlas.

        Args:
            f: A frame dict from `atlas.frames`.

        Returns:
            Its 4 corners in atlas units, shape (4, 2).
        """
        H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
        return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])

    def _place_dropped(self, frames, x, y):
        """Lines up screenshots put roughly in place by hand near there. Worker thread.

        One that can't be lined up is added exactly where it was put, if the user says so.

        Args:
            frames: The detected screenshots.
            x: Atlas x where it was put (atlas units).
            y: Atlas y where it was put (atlas units).

        Returns:
            (number added, names not added).
        """
        added, refused = 0, []
        for fr in frames:
            name = Path(fr.path).name
            reg = self.atlas.place_near(fr, x, y)
            if reg.ok:
                d = np.hypot(*(reg.M[:, 2] - [x, y]))
                self.atlas.commit_frame(fr, reg)
                added += 1
                self._q.put(("log", f"{name}: lined up {d:.0f} units from where you put it ({reg.reason})"))
            elif "already" in reg.reason:
                self._q.put(("log", f"{name}: already in the atlas"))
            elif self._ask(
                f"{name} could not be lined up with the atlas near where you put it "
                f"({reg.reason}).\n\nAdd it exactly where you put it?"
            ):
                reg.ok, reg.reason = True, "placed by hand"
                self.atlas.commit_frame(fr, reg)
                added += 1
                self._q.put(("log", f"{name}: placed by hand where you put it"))
            else:
                refused.append(name)
        return added, refused

    def _concerns(self, frame, reg) -> list[str]:
        """Lists reasons to ask before adding a watched screenshot (normally none).

        A weak match: placed by terrain alone or with few maps agreeing (WEAK_INLIERS), and low terrain
        agreement (WEAK_NCC).

        Args:
            frame: The detected screenshot.
            reg: Its placement result.

        Returns:
            The reasons as text.
        """
        out = []
        few = reg.reason.startswith("terrain") or reg.inliers <= WEAK_INLIERS
        if few and reg.ncc < WEAK_NCC:
            maps = "no maps to compare" if reg.reason.startswith("terrain") else f"only {reg.inliers} maps agree"
            out.append(f"the match is weak ({maps}, terrain agreement {reg.ncc:.2f})")
        return out

    def _ask(self, question: str, preview=None) -> bool:
        """Asks a yes / no question on the window thread and waits for the answer (worker thread).

        Args:
            question: The question text.
            preview: Optional (screenshot path, 3x3 screen px -> atlas transform) of where a screenshot would be
                added: shown on the map while the question is open (_show_weak_preview).

        Returns:
            The answer.
        """
        self._q.put(("ask", (question, preview)))
        return self._answer.get()

    @staticmethod
    def _preview_of(frame, reg):
        """Where a screenshot would go if it were added (for the weak-match preview).

        Args:
            frame: The screenshot (core.Frame).
            reg: Its proposed placement (core.Registration).

        Returns:
            (screenshot path, 3x3 transform from its screen px to atlas units).
        """
        return frame.path, core.screen_to_atlas(np.array(reg.M, float), frame.R)

    def _show_weak_preview(self, preview) -> None:
        """Shows a screenshot where it would be added, see-through and outlined, and centres the view on it.

        Used while "Check this screenshot" asks about a weak match (user: say Yes / No seeing where it goes).

        Args:
            preview: (screenshot path, 3x3 screen px -> atlas transform), or None for no preview.
        """
        self._weak_preview = None
        if not preview:
            return
        path, H = preview
        img = core.read_screenshot(str(path))
        if img is None:
            return
        small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)
        H2 = np.asarray(H, float) @ np.diag([2.0, 2.0, 1.0])  # half-size picture px -> atlas
        self._weak_preview = {"img": small, "H": H2}
        c = core.persp(H2, [[small.shape[1] / 2, small.shape[0] / 2]])[0]
        self.center_on(float(c[0]), float(c[1]), min_zoom=0.25)
        self._redraw()  # now: the question box can hold up the window's own redraws

    def _draw_weak_preview(self, img, w, h) -> None:
        """Draws the weak-match preview (see _show_weak_preview) into the map image.

        Args:
            img: The map image being drawn (BGR, changed in place).
            w: Image width (screen px).
            h: Image height (screen px).
        """
        p = getattr(self, "_weak_preview", None)
        if not p:
            return
        V = np.array([[self.z, 0, -self.cx * self.z + w / 2], [0, self.z, -self.cy * self.z + h / 2], [0, 0, 1]])
        H = V @ p["H"]
        sh, sw = p["img"].shape[:2]
        warped = cv2.warpPerspective(p["img"], H, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
        mask = cv2.warpPerspective(np.full((sh, sw), 255, np.uint8), H, (w, h), flags=cv2.INTER_NEAREST) > 0
        img[mask] = cv2.addWeighted(warped, 0.6, img, 0.4, 0)[mask]
        corners = core.persp(H, [[0, 0], [sw, 0], [sw, sh], [0, sh]]).astype(np.int32)
        cv2.polylines(img, [corners], True, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.polylines(img, [corners], True, (0, 165, 255), 2, cv2.LINE_AA)
        top = corners[np.argmin(corners[:, 1])]
        label = "would be added here - answer in the question box"
        put_text(img, label, (int(top[0]) + 6, int(top[1]) - 8), (0, 165, 255), 0.55)

    def _place_one(self, fr):
        """Places a screenshot anywhere in the atlas by its maps (without committing it). Worker thread.

        Terrain is compared with the newest screenshots first (the next one usually overlaps them). (v1.03: the
        "visible area first" search was dropped - placing is fast enough everywhere and it found nothing the
        full search missed.)

        Args:
            fr: The detected screenshot.

        Returns:
            The placement result.
        """
        hints = [f["name"] for f in self.atlas.frames[-6:]][::-1]
        return self.atlas.add_frame(fr, hints=hints, commit=False)

    def _place_watched(self, frames):
        """Places screenshots one at a time, as they arrive; earlier ones that did not fit are retried. Worker
        thread.

        Rounds repeat while anything was added. A weak match is asked about first. When nothing more fits and
        at least ISLAND_MIN are waiting, the waiting screenshots joined to each other (mini-atlases) may fit as
        a group. What still does not fit stays in the waiting list.

        Args:
            frames: Newly detected screenshots (the waiting ones are tried too).

        Returns:
            (number added, names still waiting).
        """
        added, todo = 0, self._pending_watch + frames
        self._pending_watch = []
        progress = True
        while progress and todo:
            progress, left = False, []
            for fr in todo:
                reg = self._place_one(fr)
                name = Path(fr.path).name
                if not reg.ok:
                    if "already in the atlas" not in reg.reason:
                        left.append(fr)
                        self._wait_tries = getattr(self, "_wait_tries", {})
                        self._wait_tries[name] = self._wait_tries.get(name, 0) + 1
                        self._q.put(("log", f"{name}: no place found yet ({reg.reason}); will retry"))
                    continue
                worry = self._concerns(fr, reg) if self.atlas.frames else []
                if worry:
                    q = (
                        f"{name} would be added, but " + "; and ".join(worry) + ".\n\n"
                        "Add it anyway? (No = leave it out; you can add it later with Add screenshots.)"
                    )
                    if not self._ask(q, preview=self._preview_of(fr, reg)):
                        self._q.put(("log", f"{name}: left out by you"))
                        continue
                self.atlas.commit_frame(fr, reg)
                added += 1
                progress = True
                self._q.put(("log", f"{name}: added ({reg.inliers} maps agree, terrain {reg.ncc:.2f})"))
            todo = left
            if not progress and len(todo) >= islands.ISLAND_MIN:
                # still waiting: the waiting screenshots joined to each other (mini-atlases) may fit as a group
                joined = islands.merge_waiting(self.atlas, todo, log=lambda t: self._q.put(("log", t)))
                if joined:
                    added += len(joined)
                    progress = True  # others may fit next to the group now
                    shas = {f.sha for f in joined}
                    todo = [f for f in todo if f.sha not in shas]
        self._pending_watch = todo
        return added, [Path(f.path).name for f in todo]

    def _after_placed(self, info):
        """Updates the window after a job: the model, the lists, the status and the log.

        Handles the "placed" message. The first screenshots of an atlas also build the map image and fit the
        view; an add by hand turns the Add button back on and writes the map PNGs in the background.

        Args:
            info: (mode, number added, names not added, number of screenshots before).
        """
        mode, added, refused, before = info
        self._set_progress(None)
        self._refresh_recent()
        if added:
            self.rebuild_model()  # the map image was already updated by pasting
            if before == 0:
                self.rebuild_terrain()
                self._fit_pending = True
                self.fit()
            self.request_redraw()
        if isinstance(mode, tuple):
            mode = "retry" if mode[0] == "retry" else "drop"
        if mode == "manual":
            msg = f"added {added} screenshot(s)"
            if refused:
                msg += f"; not placed (no overlap found): {', '.join(refused)}"
            self._busy = False
            self.btn_add.state(["!disabled"])
            if added:
                threading.Thread(target=self._export_quiet, daemon=True).start()
        elif mode == "drop":
            msg = "screenshot added" if added else "screenshot not added"
        elif mode == "recheck":
            msg = "whole atlas re-checked"
        elif mode == "retry":
            msg = f"retry: {added} waiting screenshot(s) placed" + (
                f"; {len(refused)} still waiting" if refused else ""
            )
        else:
            msg = f"auto-add: {added} new screenshot(s) added" + (
                f"; {len(refused)} NOT added yet (see Auto-add tab: place by hand)" if refused else ""
            )
            if refused and not added:
                self.tabs.select(self.tab_auto)
        self.status.set(msg)
        self.log(msg)

    def _export_quiet(self):
        """Background thread: writes the map PNGs; a failure is only logged."""
        try:
            with self._lock:
                builder.export(self.atlas, self.path)
        except Exception as e:
            LOG.exception("PNG export failed")
            self._q.put(("log", f"PNG export failed: {e}"))

    # ------------------------------------------------------------------ watched folder
    def _atlas_key(self) -> str:
        """Returns the key the open atlas's settings are kept under (its resolved file path).

        Returns:
            The key, or "" with no atlas open.
        """
        return str(Path(self.path).resolve()) if getattr(self, "path", None) else ""

    def _hand_watch(self) -> str | None:
        """Returns the folder picked by hand for the open atlas.

        Each atlas remembers its own; a folder picked for one atlas used to follow you to the next and pour its
        screenshots into it (the one folder for every atlas used before v1.11 is forgotten here).

        Returns:
            The folder, or None.
        """
        self.settings.pop("watch_folder", None)  # before v1.11 one folder for every atlas: forgotten
        return self.settings.get("watch_folders", {}).get(self._atlas_key())

    def _watch_dir(self) -> str:
        """Returns the folder auto-add watches: one chosen by hand for this atlas, otherwise the open atlas's own
        folder (where Steam should save the screenshots while you map: README).

        Returns:
            The folder, or "" with no atlas open.
        """
        hand = self._hand_watch()
        if hand:
            return hand
        return str(self.path.parent) if getattr(self, "path", None) else ""

    def _show_watch_label(self):
        """Shows which folder auto-add watches, in the Auto-add tab."""
        d = self._watch_dir()
        self.watch_label.set(
            ("watching: " if self._hand_watch() else "watching this atlas's folder: ") + d
            if d
            else "open an atlas first"
        )

    def use_atlas_folder(self):
        """Forgets a hand-picked folder: watch the open atlas's own folder again (Atlas folder button)."""
        self.settings.setdefault("watch_folders", {}).pop(self._atlas_key(), None)
        save_settings(self.settings)
        self._show_watch_label()
        if self.watch_var.get():
            self.start_watch()

    def ask_watch_folder(self):
        """Asks for a folder to watch for the open atlas and saves it (Watch folder… button)."""
        d = filedialog.askdirectory(
            title="Folder your screenshots are saved to",
            initialdir=self._hand_watch() or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if d:
            if not self._atlas_key():
                self.status.set("open or create an atlas first")
                return
            self.settings.setdefault("watch_folders", {})[self._atlas_key()] = d
            self._show_watch_label()
            save_settings(self.settings)
            if self.watch_var.get():
                self.start_watch()

    def toggle_watch(self):
        """Turns auto-add on or off (the Add new screenshots automatically box) and saves the setting."""
        if self.watch_var.get():
            if not self._watch_dir():
                self.status.set("open or create an atlas first")
                self.watch_var.set(False)
                return
            self.start_watch()
        else:
            self.settings["watch_on"] = False
            self.status.set("auto-add off")
        save_settings(self.settings)

    def _watch_files(self) -> dict[str, int]:
        """Lists the image files in the watched folder that can be screenshots by name.

        The folder is listed once (os.scandir: sizes come with the listing) and its path resolved once:
        resolving and checking every file each poll took ~750 ms every 2 s in a folder of 1261 screenshots,
        freezing the window (user's frame log). The program's own folders (_files, _frames, _undo) and output
        images are left out.

        Returns:
            {full path: size in bytes}.
        """
        out = {}
        with contextlib.suppress(OSError):
            base = Path(self._watch_dir()).resolve()
            if base.name.endswith(("_files", "_frames", "_undo")):
                return out
            with os.scandir(base) as it:
                for e in it:
                    name = e.name
                    if Path(name).suffix.lower() not in core.IMAGE_EXT or name.endswith(core.ATLAS_OUTPUTS):
                        continue
                    with contextlib.suppress(OSError):
                        if e.is_file():
                            out[str(base / name)] = e.stat().st_size
        return out

    def start_watch(self, initial=False):
        """Starts auto-add on the watched folder.

        New files in the folder are added from now on - and screenshots already there that the atlas does not
        have yet (taken while the program was closed, or left over: user), from the atlas's first screenshot
        on, so a big screenshot folder doesn't pull in old shots of something else. An empty atlas takes them
        all. Images the program wrote are never added. A folder that isn't the atlas's own with more than
        WATCH_ASK such screenshots asks first.

        Args:
            initial: True when called at program start (the method does not use it).
        """
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            self.watch_var.set(False)
            return
        self.settings["watch_on"] = True
        files = self._watch_files()
        self._watch_seen = {k: -1 for k in files}  # -1: handed over to adding (not watched for changes)
        todo = [q for q in self._not_in_atlas(files) if not core.is_generated(q)]  # tagged images never added
        own = Path(self._watch_dir()).resolve() == Path(self.path).resolve().parent
        # a folder that isn't this atlas's own, full of screenshots it doesn't have: likely another atlas's
        crowded = todo and not own and self.atlas.frames and len(todo) > WATCH_ASK
        if crowded and not messagebox.askyesno(
            "Add screenshots?",
            f"{len(todo)} screenshots in\n{self._watch_dir()}\nare not in this atlas.\n\n"
            "Add them all to this atlas? (No: only new screenshots from now on.)",
        ):
            self.log(f"auto-add: left the {len(todo)} screenshot(s) already in {self._watch_dir()} out")
            todo = []
        self._show_watch_label()
        self.status.set(f"watching {self._watch_dir()} for new screenshots")
        self.log(
            f"auto-add: watching {self._watch_dir()}"
            + (f"; {len(todo)} screenshot(s) there are not in the atlas yet: adding them" if todo else "")
        )
        if todo:
            self.add_screenshots(todo, mode="watch")
        if not getattr(self, "_watch_job", None):
            self._watch_job = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _not_in_atlas(self, files) -> list[Path]:
        """Finds screenshots of the watched folder the atlas does not have (by file or by name).

        Only those from the atlas's first screenshot on (all of them for an empty atlas).

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

    def _watch_failed(self, paths: list[str]):
        """Let the watcher try screenshots again whose detection failed (window thread).

        The watcher marks a file as handed over when it is queued; a failure used to leave it marked, so a
        screenshot that was unreadable for a moment was never retried (GPT audit). Each file gets WATCH_RETRIES
        more tries, picked up by the next polls; after that it is logged and left alone.

        Args:
            paths: Full paths of the screenshots whose detection failed.
        """
        tries = self.__dict__.setdefault("_watch_tries", {})
        for f in paths:
            tries[f] = tries.get(f, 0) + 1
            if tries[f] <= WATCH_RETRIES:
                getattr(self, "_watch_seen", {}).pop(f, None)  # seen again on the next polls, then queued again
                self.log(f"auto-add: {Path(f).name} failed; trying again ({tries[f]}/{WATCH_RETRIES})")
            else:
                self.log(f"auto-add: {Path(f).name} failed {WATCH_RETRIES + 1} times; left out (add it by hand)")

    def _poll_watch(self):
        """Checks the watched folder (every WATCH_POLL_MS, a Tk `after` timer) and adds new screenshots.

        A file counts as finished writing when it has the same size twice. The atlas's known paths are resolved
        only when the atlas changes (resolving ~800 paths every 2 s cost the window thread).
        """
        self._watch_job = None
        if not self.watch_var.get() or not self.atlas or self._closing:
            return
        key = (id(self.atlas), len(self.atlas.frames))
        if getattr(self, "_known_key", None) != key:  # resolving ~800 paths every 2 s cost the window thread
            self._known = {str(Path(f["path"]).resolve()) for f in self.atlas.frames}
            self._known_key = key
        known = self._known
        ready = []
        for f, size in self._watch_files().items():
            prev = self._watch_seen.get(f)
            if prev == -1 or f in known:
                continue
            if prev is not None and prev == size and size > 0:  # finished writing: same size twice
                ready.append(Path(f))
                self._watch_seen[f] = -1  # handed over; a failed detection hands it back (_watch_failed)
            else:
                self._watch_seen[f] = size
        ready = [q for q in ready if not core.is_generated(q)]  # an image the program wrote (tagged): never added
        if ready:
            ready.sort(key=lambda q: q.stat().st_mtime)
            self.log(f"auto-add: {len(ready)} new screenshot(s): {', '.join(q.name for q in ready)}")
            self.add_screenshots(ready, mode="watch")
        self._watch_job = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _drain_queue(self):
        """Handles every message waiting in the queue from background threads (window thread).

        With PROFILE on, a message that took over 0.2 s is printed.
        """
        while True:
            try:
                kind, val = self._q.get_nowait()
            except queue.Empty:
                return
            t_msg = time.perf_counter()
            try:
                self._handle(kind, val)
            finally:
                dt = time.perf_counter() - t_msg
                if PROFILE and dt > 0.2:
                    print(f"[viewer] slow on the window thread: {kind} took {dt:.2f}s", flush=True)

    def _handle(self, kind, val):
        """Handles one message from a background thread (window thread).

        Args:
            kind: The message kind: "status", "tile", "atlas_cards", "atlas_numbers", "progress",
                "added_names", "undone", "outline", "rebuild_terrain", "terrain_img", "log", "locks", "placed",
                "done", "ask" or "watch_failed".
            val: The message value; its shape depends on the kind.
        """
        match kind:
            case "status":
                self.status.set(val)
            case "watch_failed":
                self._watch_failed(val)
            case "tile":  # a sharp ground tile is ready
                self.request_redraw()
            case "atlas_cards":  # a thumbnail was written
                self.refresh_atlas_cards()
            case "atlas_numbers":
                self._got_atlas_numbers(val)
            case "progress":
                self._set_progress(val)
            case "added_names":
                self._remember_add(*val)
            case "undone":
                self.recent = [n for n in self.recent if n not in set(val)]
                self._refresh_recent()
                self.rebuild_model()
                self._terrain = None
                self.rebuild_terrain()
                self._set_progress(None)
                self.status.set(f"undone: {', '.join(val)}")
                self.log(f"undone: {', '.join(val)}")
            case "outline":
                self._pending_outline = val
                self.request_redraw()
            case "rebuild_terrain":
                self.rebuild_terrain()
            case "terrain_img":
                job, canvas, weight, origin, labels = (*val, None)[:5]
                if job is None or job == "seams" or job == self._terrain_job:
                    self._set_terrain(canvas, weight, origin, labels=labels)
                    if job == "seams":
                        self._seams_ready(labels[1])
                    self.footprints = [
                        (poly, (*poly.min(axis=0), *poly.max(axis=0)))
                        for poly in (self._poly(f) for f in self.atlas.frames)
                    ]
                    if self._progress and self._progress[0].startswith("building the map"):
                        self._set_progress(None)
            case "log":
                self.log(val)
            case "locks":
                self._lock_job = False
                if val and val[0] is self.atlas:
                    _atlas, names, found = val
                    self.atlas.locks = atlas_cities.merge_locks(self.atlas.locks, found)
                    self.atlas.lock_scanned = sorted(set(self.atlas.lock_scanned) | set(names))
                    if self.path:
                        self.atlas.save(self.path)
                    if found:
                        self.log(f"{len(self.atlas.locks)} locked Breach stronghold(s) (hand badge)")
                    self.rebuild_model()
                    self.request_redraw()
                    self.scan_locks()  # screenshots added meanwhile
            case "placed":
                self._after_placed(val)
            case "done":
                self.scan_locks()
                self._set_progress(None)
                self._busy = False
                self.btn_add.state(["!disabled"])
            case "ask":  # a question from the worker; for a weak match, the screenshot is shown where it would go
                question, preview = val if isinstance(val, tuple) else (val, None)
                view = (self.cx, self.cy, self.z)  # the preview centres on the screenshot; No puts the view back
                self._show_weak_preview(preview)
                if self._weak_preview:
                    question += "\n\n(It is shown and outlined on the map.)"
                answer = False
                try:
                    answer = messagebox.askyesno("Check this screenshot", question)
                finally:
                    if self._weak_preview is not None and not answer:  # not added: back to where you were
                        self.cx, self.cy, self.z = view  # (Yes stays, to show where it went: GPT audit)
                    self._weak_preview = None
                    self.request_redraw()
                self._answer.put(answer)

    def _poll_queue(self):
        """Handles background messages every 150 ms (a Tk `after` timer, for the window's lifetime)."""
        self._drain_queue()
        self.root.after(150, self._poll_queue)
