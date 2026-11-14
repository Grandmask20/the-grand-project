"""viewer.autoadd: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import builder, core
from grand_project import cities as atlas_cities
from grand_project import finalize as atlas_finalize
from grand_project import paths as rc_paths

from .constants import (
    PROFILE,
    RECENT_COL,
    RECENT_FADE,
    RECENT_KEEP,
    UNDO_KEEP,
    WATCH_BATCH,
    WATCH_POLL_MS,
    WEAK_INLIERS,
    WEAK_NCC,
)
from .helpers import LOG, put_text
from .settings import save_settings


class AutoAddMixin:
    # ------------------------------------------------------------------ progress on the map
    def _set_progress(self, text):
        self._progress = (text, self._progress[1] if self._progress else time.time()) if text else None
        if text:
            self.status.set(text)
        self.request_redraw()
        if text and not getattr(self, "_progress_tick", None):
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _tick_progress(self):
        self._progress_tick = None
        if self._progress:
            self.request_redraw()
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _draw_progress(self, img, w, h):
        if not self._progress:
            return
        text, t0 = self._progress
        dots = "." * (1 + int(time.time() * 2) % 3)
        line = f"{text.rstrip('.…')}{dots}   {time.time() - t0:.0f}s"
        tw = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 4)[0][0]
        x0 = w - tw - 36
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (25, 25, 25), -1)
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (0, 200, 255), 1)
        put_text(img, line, (x0 + 12, 33), (0, 220, 255), 0.55)

    def _draw_pending(self, img):
        for poly in self._pending_outline:
            pts = self.to_screen(poly).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 220, 255), 2, cv2.LINE_AA)

    # ------------------------------------------------------------------ hand placement (drag a file in)
    def start_ghost(self, path: Path, sx=None, sy=None):
        """show a see-through screenshot to put roughly in place; Enter / double-click fits it"""
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            return
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
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
        g, self._ghost = self._ghost, None
        if not g:
            return
        self.request_redraw()
        if self.database() is None:
            return
        self._jobs.put(([g["path"]], ("drop", g["cx"], g["cy"])))

    def _cancel_lasso(self):
        self._lasso = None
        self.canvas.configure(cursor="fleur")
        self.status.set("lasso cancelled")
        self.request_redraw()

    def _cancel_bm_mode(self):
        if getattr(self, "_bm_mode", False):
            self._bm_mode = False
            self.canvas.configure(cursor="fleur")
            self.status.set("bookmark cancelled")

    def cancel_ghost(self):
        self._ghost = None
        self.status.set("placement cancelled")
        self.request_redraw()

    def on_drop(self, e):
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
        p = filedialog.askopenfilename(
            title="Screenshot to place by hand",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
            initialdir=self.settings.get("watch_folder") or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if p:
            self.start_ghost(Path(p))

    def save(self):
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
        if self.atlas and self.path:
            self.save()

    def export_pngs(self):
        if not self.atlas or not self.path or not self.atlas.frames:
            return
        builder.export(self.atlas, self.path)
        self.log(f"wrote {self.path.stem}_composite.png and _network.png in {core.atlas_files(self.path).name}/")

    def refinalize(self):
        """full re-check, in the background (minutes on a large atlas)"""
        if not self.atlas or not self.atlas.frames:
            return
        self._jobs.put(([], "recheck_all"))

    def on_close(self):
        if self._busy and not messagebox.askyesno("Atlas viewer", "Screenshots are still being added. Quit anyway?"):
            return
        self.save_if_dirty()
        self.settings["geometry"] = self.root.geometry()
        self.settings["layers"] = {k: v.get() for k, v in self.layers.items()}
        self.settings["multi_only"] = self.multi_only.get()
        self.settings["icons_hidden"] = sorted(self.icon_hidden)
        save_settings(self.settings)
        self.root.destroy()

    # ------------------------------------------------------------------ adding screenshots
    def database(self, ask=True) -> Path | None:
        p = self.settings.get("database")
        if p and Path(p).exists():
            return Path(p)
        for cand in (rc_paths.DATABASE,):
            if cand.exists():
                return cand
        try:
            d = builder.default_database()
            if d.exists():
                return d
        except Exception:
            LOG.warning("detector default database not found", exc_info=True)
        return self.ask_database() if ask else None

    def ask_database(self) -> Path | None:
        p = filedialog.askopenfilename(
            title="Detector reference database (node_references_*.sqlite3)",
            filetypes=[("SQLite", "*.sqlite3"), ("All", "*.*")],
            initialdir=str(rc_paths.ROOT),
        )
        if not p:
            return None
        self.settings["database"] = p
        save_settings(self.settings)
        return Path(p)

    def ask_add(self):
        if self._busy:
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

    def add_screenshots(self, paths: list[Path], sync: bool = False, mode: str = "manual"):
        if self.database() is None:
            return
        if mode == "manual":
            self._busy = True
            self.btn_add.state(["disabled"])
        if sync:
            self._run_job(list(paths), mode)
            self._drain_queue()
        else:
            self._jobs.put((list(paths), mode))

    # ------------------------------------------------------------------ background worker
    def _worker(self):
        while True:
            paths, mode = self._jobs.get()
            if mode == "watch":  # screenshots that arrived meanwhile: one batch, one re-check
                paths = list(paths)  # (v1.00 re-checked after every 2-3: ~45 s each)
                with self._jobs.mutex:
                    q = self._jobs.queue
                    while q and q[0][1] == "watch" and len(paths) < WATCH_BATCH:
                        paths += q.popleft()[0]
            try:
                self._run_job(paths, mode)
            except Exception as e:
                LOG.exception(f"adding failed ({mode}): {paths}")
                self._q.put(("log", f"adding failed: {e}"))
                self._q.put(("done", mode))

    def _run_job(self, paths, mode):
        if mode == "undo":
            self._run_undo()
            return
        retry = isinstance(mode, tuple) and mode[0] == "retry"
        if mode == "recheck_all":
            self._q.put(("progress", "re-checking the whole atlas"))
            with self._lock:
                self.atlas.rebuild_icons(builder.cached_frames(self.path))
                atlas_finalize.finalize(self.atlas, log=lambda t: self._q.put(("log", t)))
                self.atlas.save(self.path)
            self._q.put(("placed", ("recheck", 1, [], len(self.atlas.frames))))
            return
        db = self.database(ask=False)
        cache_dir = self.path.with_name(self.path.stem + "_frames")
        frames = []
        if len(paths) > 1:
            self._q.put(("progress", f"detecting {len(paths)} screenshots"))
            for p, err in builder.detect_uncached(paths, cache_dir, log=lambda t: self._q.put(("log", t))).items():
                LOG.warning(f"{Path(p).name}: detection failed in a worker: {err}")
        for i, p in enumerate(paths, 1):
            self._q.put(("progress", f"detecting {p.name} ({i}/{len(paths)})"))
            try:
                fr = builder.extract_frame(p, db, cache_dir)
                frames.append(fr)
                self._q.put(("log", f"{p.name}: {int(fr.usable.sum())} maps, {len(getattr(fr, 'icons', []))} icons"))
            except Exception as e:
                LOG.exception(f"{p.name}: detection failed")
                self._q.put(("log", f"{p.name}: detection failed: {e}"))
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
        d = core.atlas_files(self.path) / (self.path.stem + "_undo")
        d.mkdir(exist_ok=True)
        return d

    def _snapshot(self) -> Path:
        """the atlas as it is before an add (worker thread, under the lock)"""
        f = self._undo_dir() / f"before_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.atlas.frames)}.json"
        self.atlas.save(f)
        return f

    def _remember_add(self, names, snapshot):
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
        if not self._undo or self._busy:
            return
        names = self._undo[-1]["names"]
        if not messagebox.askyesno("Undo last add", "Remove the screenshot(s) added last?\n\n" + "\n".join(names)):
            return
        self._jobs.put(([], "undo"))

    def _run_undo(self):
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
        """search again for screenshots in the waiting queue (selected ones, or all), e.g. after others were
        placed; runs in the background like an auto-add"""
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
        self._jobs.put(([], ("retry", idx)))

    def place_waiting(self):
        sel = self.wait_list.curselection()
        if not sel or sel[0] >= len(self._pending_watch):
            return
        fr = self._pending_watch.pop(sel[0])
        self._refresh_recent()
        self.start_ghost(Path(fr.path))

    def _draw_recent(self, img):
        """the newest screenshot outlined; the 4 before it fade out (5 in all, one screenshot each, not per
        batch); a screenshot clicked in the Recently added list is outlined too"""
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
        H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
        return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])

    def _place_dropped(self, frames, x, y):
        """a screenshot put roughly in place by hand: line it up near there"""
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
        """reasons to ask before adding a watched screenshot (normally none)"""
        out = []
        few = reg.reason.startswith("terrain") or reg.inliers <= WEAK_INLIERS
        if few and reg.ncc < WEAK_NCC:
            maps = "no maps to compare" if reg.reason.startswith("terrain") else f"only {reg.inliers} maps agree"
            out.append(f"the match is weak ({maps}, terrain agreement {reg.ncc:.2f})")
        return out

    def _ask(self, question: str) -> bool:
        """ask on the main thread and wait for the answer (worker thread)"""
        self._q.put(("ask", question))
        return self._answer.get()

    def _place_one(self, fr):
        """anywhere in the atlas by its maps; terrain is compared with the newest screenshots first (the next
        one usually overlaps them). (v1.03: the "visible area first" search was dropped - placing is fast
        enough everywhere and it found nothing the full search missed)"""
        hints = [f["name"] for f in self.atlas.frames[-6:]][::-1]
        return self.atlas.add_frame(fr, hints=hints, commit=False)

    def _place_watched(self, frames):
        """one screenshot at a time, as they arrive; earlier ones that did not fit are retried"""
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
                    if not self._ask(q):
                        self._q.put(("log", f"{name}: left out by you"))
                        continue
                self.atlas.commit_frame(fr, reg)
                added += 1
                progress = True
                self._q.put(("log", f"{name}: added ({reg.inliers} maps agree, terrain {reg.ncc:.2f})"))
            todo = left
        self._pending_watch = todo
        return added, [Path(f.path).name for f in todo]

    def _after_placed(self, info):
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
        try:
            with self._lock:
                builder.export(self.atlas, self.path)
        except Exception as e:
            LOG.exception("PNG export failed")
            self._q.put(("log", f"PNG export failed: {e}"))

    # ------------------------------------------------------------------ watched folder
    def _watch_dir(self) -> str:
        """the folder auto-add watches: one chosen by hand, otherwise the open atlas's own folder (where Steam
        should save the screenshots while you map: README)"""
        if self.settings.get("watch_folder"):
            return self.settings["watch_folder"]
        return str(self.path.parent) if getattr(self, "path", None) else ""

    def _show_watch_label(self):
        d = self._watch_dir()
        self.watch_label.set(
            ("watching: " if self.settings.get("watch_folder") else "watching this atlas's folder: ") + d
            if d
            else "open an atlas first"
        )

    def use_atlas_folder(self):
        """forget a hand-picked folder: watch the open atlas's own folder again"""
        self.settings.pop("watch_folder", None)
        save_settings(self.settings)
        self._show_watch_label()
        if self.watch_var.get():
            self.start_watch()

    def ask_watch_folder(self):
        d = filedialog.askdirectory(
            title="Folder your screenshots are saved to",
            initialdir=self.settings.get("watch_folder") or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if d:
            self.settings["watch_folder"] = d
            self._show_watch_label()
            save_settings(self.settings)
            if self.watch_var.get():
                self.start_watch()

    def toggle_watch(self):
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
        folder = Path(self._watch_dir())
        out = {}
        with contextlib.suppress(OSError):
            for f in core.screenshots_in(folder):
                out[str(f.resolve())] = f.stat().st_size
        return out

    def start_watch(self, initial=False):
        """new files in the folder are added from now on - and screenshots already there that the atlas does not
        have yet (taken while the program was closed, or left over: user), from the atlas's first screenshot on,
        so a big screenshot folder doesn't pull in old shots of something else. An empty atlas takes them all."""
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            self.watch_var.set(False)
            return
        self.settings["watch_on"] = True
        files = self._watch_files()
        self._watch_seen = {k: -1 for k in files}  # -1: handled (not watched for changes)
        todo = self._not_in_atlas(files)
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
        """screenshots of the watched folder the atlas does not have (by file or by name), oldest first; only
        those from the atlas's first screenshot on (all of them for an empty atlas)"""
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

    def _poll_watch(self):
        self._watch_job = None
        if not self.watch_var.get() or not self.atlas:
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
                self._watch_seen[f] = -1
            else:
                self._watch_seen[f] = size
        if ready:
            ready.sort(key=lambda q: q.stat().st_mtime)
            self.log(f"auto-add: {len(ready)} new screenshot(s): {', '.join(q.name for q in ready)}")
            self.add_screenshots(ready, mode="watch")
        self._watch_job = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _drain_queue(self):
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
        if True:
            if kind == "status":
                self.status.set(val)
            elif kind == "hires":
                if val[0] == self.view_key(*self.canvas_size()):
                    self._hires = val
                    self.request_redraw()
            elif kind == "progress":
                self._set_progress(val)
            elif kind == "added_names":
                self._remember_add(*val)
            elif kind == "undone":
                self.recent = [n for n in self.recent if n not in set(val)]
                self._refresh_recent()
                self.rebuild_model()
                self._terrain = None
                self.rebuild_terrain()
                self._set_progress(None)
                self.status.set(f"undone: {', '.join(val)}")
                self.log(f"undone: {', '.join(val)}")
            elif kind == "outline":
                self._pending_outline = val
                self.request_redraw()
            elif kind == "rebuild_terrain":
                self.rebuild_terrain()
            elif kind == "terrain_img":
                job, canvas, weight, origin = val
                if job is None or job == self._terrain_job:
                    self._set_terrain(canvas, weight, origin)
                    self.footprints = [
                        (poly, (*poly.min(axis=0), *poly.max(axis=0)))
                        for poly in (self._poly(f) for f in self.atlas.frames)
                    ]
                    if self._progress and self._progress[0].startswith("building the map"):
                        self._set_progress(None)
            elif kind == "log":
                self.log(val)
            elif kind == "locks":
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
            elif kind == "placed":
                self._after_placed(val)
            elif kind == "done":
                self.scan_locks()
                self._set_progress(None)
                self._busy = False
                self.btn_add.state(["!disabled"])
            elif kind == "ask":
                self._answer.put(messagebox.askyesno("Check this screenshot", val))

    def _poll_queue(self):
        self._drain_queue()
        self.root.after(150, self._poll_queue)
