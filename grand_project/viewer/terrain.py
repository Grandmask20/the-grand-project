"""viewer.terrain: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import core
from grand_project import logs as atlas_log

from .constants import HIRES_MAX_FRAMES
from .helpers import LOG


class TerrainMixin:
    # ------------------------------------------------------------------ fill-in areas
    # ------------------------------------------------------------------ native-resolution terrain
    def hires_wanted(self) -> bool:
        return bool(self.pyr) and self.z > self.t_origin[2] * 1.15 and self.layers["Terrain"].get()

    def view_key(self, w, h):
        return (w, h, round(self.cx, 2), round(self.cy, 2), round(self.z, 6))

    def _schedule_hires(self):
        if self._hires_job:
            self.root.after_cancel(self._hires_job)
        self._hires_job = self.root.after(140, self._make_hires)

    def _frame_weight(self, f):
        """distance-to-edge weight (quarter resolution) so each spot comes from its most central screenshot"""
        key = f["name"]
        if key not in self._weights:
            img = self.atlas.image(f["path"])
            v = core._valid_mask(img)
            small = cv2.resize(v, (v.shape[1] // 4, v.shape[0] // 4), interpolation=cv2.INTER_NEAREST)
            small[small > 0] = 255
            d = cv2.distanceTransform(small, cv2.DIST_L2, 3)
            self._weights[key] = d.astype(np.float32)
        return self._weights[key]

    def _make_hires(self, background=True):
        """sharp view from the screenshots themselves; built in a background thread so panning
        and adding stay smooth (the newest request wins)"""
        self._hires_job = None
        if not self.atlas or not self.hires_wanted():
            return
        w, h = self.canvas_size()
        key = self.view_key(w, h)
        cx, cy, z = self.cx, self.cy, self.z
        jobs = list(zip(list(self.atlas.frames), list(self.footprints), strict=False))
        self._hires_req = key
        if background:
            threading.Thread(target=self._hires_work, args=(key, w, h, cx, cy, z, jobs), daemon=True).start()
        else:
            self._hires_work(key, w, h, cx, cy, z, jobs)
            self._drain_queue()

    def _hires_work(self, key, w, h, cx, cy, z, jobs):
        t0 = time.perf_counter()
        V = np.array([[z, 0, -cx * z + w / 2], [0, z, -cy * z + h / 2], [0, 0, 1]])
        out = np.zeros((h, w, 3), np.uint8)
        best = np.zeros((h, w), np.float32)
        frames = []
        for f, (poly, _bb) in jobs:
            sp = (np.asarray(poly, float) - [cx, cy]) * z + [w / 2, h / 2]
            x0, y0 = np.floor(sp.min(axis=0)).astype(int)
            x1, y1 = np.ceil(sp.max(axis=0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if x1 <= x0 or y1 <= y0 or not Path(f["path"]).exists():
                continue
            ctr = sp.mean(axis=0)
            frames.append((math.hypot(ctr[0] - w / 2, ctr[1] - h / 2), f, (x0, y0, x1, y1)))
        frames.sort(key=lambda t: t[0])
        for _, f, (x0, y0, x1, y1) in frames[:HIRES_MAX_FRAMES]:
            Hf = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]]) @ V @ Hf
            size = (x1 - x0, y1 - y0)
            pix = cv2.warpPerspective(
                self.atlas.image(f["path"]), T, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            S4 = np.diag([4.0, 4.0, 1.0])
            wt = cv2.warpPerspective(
                self._frame_weight(f), T @ S4, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            sub_b = best[y0:y1, x0:x1]
            take = wt > sub_b
            out[y0:y1, x0:x1][take] = pix[take]
            sub_b[take] = wt[take]
            if time.perf_counter() - t0 > 1.5 or getattr(self, "_hires_req", key) != key:
                break  # too slow, or the view moved on
        self._q.put(("hires", (key, out, best > 0)))

    def canvas_size(self) -> tuple[int, int]:
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def canvas_size_half(self) -> tuple[float, float]:
        w, h = self.canvas_size()
        return w / 2, h / 2

    def _tk_error(self, tp, val, tb):
        """an error inside a button / menu / key handler: logged with its traceback, shown in Log"""
        LOG.error("error in a window handler", exc_info=(tp, val, tb))
        with contextlib.suppress(Exception):
            self.log(f"error: {val!r} (details in {atlas_log.LOG_FILE.name})")

    def log(self, text: str):
        LOG.info(text.strip("\n"))
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.strip("\n") + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
