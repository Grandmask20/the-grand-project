"""viewer.terrain: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import logs as atlas_log

from .constants import HIRES_MAX_FRAMES, HIRES_MAX_LEVEL, HIRES_TILE, HIRES_TILE_CACHE
from .helpers import LOG


class TerrainMixin:
    """Viewer mixin for the terrain: sharp-ground tiles built from the screenshots at native resolution, plus a few
    window helpers (canvas size, the Log box, the Tk error handler).

    Sharp-ground tiles are built by one background worker thread (the terrain tile worker); everything else runs
    on the window thread.
    """

    # ------------------------------------------------------------------ fill-in areas
    # ------------------------------------------------------------------ native-resolution terrain
    def hires_wanted(self) -> bool:
        """Whether to draw sharp-ground tiles: the Terrain layer is on and the zoom is over 1.15x the map image's scale.

        Returns:
            True when sharp-ground tiles should be drawn.
        """
        return bool(self.pyr) and self.z > self.t_origin[2] * 1.15 and self.layers["Terrain"].get()

    def view_key(self, w, h):
        """A key that changes whenever the view (size, centre, zoom) changes.

        Args:
            w: Canvas width in screen px.
            h: Canvas height in screen px.

        Returns:
            (w, h, rounded cx, rounded cy, rounded zoom).
        """
        return (w, h, round(self.cx, 2), round(self.cy, 2), round(self.z, 6))

    # Sharp ground, tile by tile. A tile (level s, column i, row j) covers atlas units [i, i+1) * HIRES_TILE / s
    # by [j, j+1) * HIRES_TILE / s at s px per unit. Built by one background worker (nearest the view's middle
    # first), kept in self._tiles (least recently drawn dropped first) until the atlas or the map image changes
    # (self._tile_gen).
    def _tile_level(self) -> float:
        """The tile level for the current zoom: the next power of two up, at most HIRES_MAX_LEVEL.

        Returns:
            Level s in tile px per atlas unit.
        """
        return float(min(HIRES_MAX_LEVEL, 2.0 ** math.ceil(math.log2(max(self.z, 1e-6)))))

    def _clear_tiles(self):
        """Drop every sharp-ground tile and pending request, and the screenshot weights (a new tile generation)."""
        with self._tile_lock:
            self._tile_gen += 1
            self._tiles.clear()
            self._tile_want = []
        self._weights = {}

    def _view_tiles(self, w, h, s) -> list[tuple]:
        """Keys of the level-s tiles the view needs, nearest its middle first.

        Args:
            w: Canvas width in screen px.
            h: Canvas height in screen px.
            s: Tile level in tile px per atlas unit.

        Returns:
            List of (s, i, j) tile keys (column i, row j).
        """
        unit = HIRES_TILE / s
        hw, hh = w / 2 / self.z, h / 2 / self.z
        i0, i1 = math.floor((self.cx - hw) / unit), math.floor((self.cx + hw) / unit)
        j0, j1 = math.floor((self.cy - hh) / unit), math.floor((self.cy + hh) / unit)
        keys = [(s, i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
        return sorted(keys, key=lambda k: (k[1] + 0.5 - self.cx / unit) ** 2 + (k[2] + 0.5 - self.cy / unit) ** 2)

    def _draw_tiles(self, img, w, h):
        """Draw the sharp ground over the map image: cached tiles of this level, missing ones requested from the worker.

        While some are missing, tiles of the coarser / finer level built before are drawn under them (only then:
        drawn under every frame before, ~35 tiles a frame). Starts the terrain tile worker when tiles are missing.

        Args:
            img: BGR uint8 frame to draw into, shape (h, w, 3).
            w: Canvas width in screen px.
            h: Canvas height in screen px.
        """
        s = self._tile_level()
        z = self.z
        want = self._view_tiles(w, h, s)
        with self._tile_lock:
            gen = self._tile_gen
            have = {k: self._tiles.get((gen, *k)) for k in want}
            for k in want:
                if have[k] is not None:
                    self._tiles.move_to_end((gen, *k))
            missing = [k for k in want if have[k] is None]
            spare = []  # only while some are missing (drawn under every frame before: ~35 tiles a frame)
            for lvl in (s / 2, s * 2) if missing else ():
                spare += [t for t in (self._tiles.get((gen, *k)) for k in self._view_tiles(w, h, lvl)) if t]
            self._tile_want = missing
        for t in spare + [t for t in have.values() if t is not None]:
            self._blit_tile(img, w, h, z, t)
        self._fl_tiles_drawn(len(want) - len(missing), len(missing))
        if missing:
            self._start_tile_worker()

    def tiles_cover_view(self, w, h) -> bool:
        """Whether every tile the view needs is built and has no holes (the blurry map image under them can be skipped).

        Args:
            w: Canvas width in screen px.
            h: Canvas height in screen px.

        Returns:
            True when the tiles cover the whole view.
        """
        with self._tile_lock:
            gen = self._tile_gen
            for k in self._view_tiles(w, h, self._tile_level()):
                t = self._tiles.get((gen, *k))
                if t is None or t[2] is not None:
                    return False
        return True

    def _blit_tile(self, img, w, h, z, t):
        """Copy one sharp-ground tile into the frame, scaled to the zoom.

        The screen block is the tile's edges rounded the same way its neighbours round them, so tiles meet exactly
        (floor / ceil overlapped them by a pixel, and that pixel was blended with black: a dark line along every tile
        edge, user). At 1:1 it is a plain copy; otherwise a warp that repeats the tile's own edge pixels outside it,
        never black. A tile with holes is copied through its mask, in place.

        Args:
            img: BGR uint8 frame to draw into.
            w: Canvas width in screen px.
            h: Canvas height in screen px.
            z: Current zoom in screen px per atlas unit.
            t: The cached tile, ((s, i, j), pixels BGR uint8 (HIRES_TILE, HIRES_TILE, 3), mask uint8 or None when no
                holes).
        """
        (s, i, j), pix, mask = t
        unit = HIRES_TILE / s
        a = z / s
        tx, ty = (i * unit - self.cx) * z + w / 2, (j * unit - self.cy) * z + h / 2
        # the screen block is the tile's edges rounded the same way its neighbours round them: tiles meet exactly
        # (floor / ceil overlapped them by a pixel, and that pixel was blended with black: a dark line along
        # every tile edge, user)
        x0, y0 = max(0, round(tx)), max(0, round(ty))
        x1, y1 = min(w, round(tx + HIRES_TILE * a)), min(h, round(ty + HIRES_TILE * a))
        if x1 <= x0 or y1 <= y0:
            return
        size = (x1 - x0, y1 - y0)
        if abs(a - 1) < 1e-6 and float(tx).is_integer() and float(ty).is_integer():  # 1:1: a plain copy
            sx, sy = x0 - int(tx), y0 - int(ty)
            part = pix[sy : sy + size[1], sx : sx + size[0]]
            m = None if mask is None else mask[sy : sy + size[1], sx : sx + size[0]] > 0
        else:
            A = np.array([[a, 0, tx - x0], [0, a, ty - y0]])
            flags = cv2.INTER_LINEAR if a < 1.5 else cv2.INTER_NEAREST
            # outside the tile: its own edge pixels repeated, never black
            part = cv2.warpAffine(pix, A, size, flags=flags, borderMode=cv2.BORDER_REPLICATE)
            m = (
                None
                if mask is None
                else cv2.warpAffine(mask, A, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE) > 0
            )
        if m is None:  # a tile with no holes (most): copied whole, no per-pixel mask
            img[y0:y1, x0:x1] = part
        else:  # in place: boolean indexing copied every pixel twice
            np.copyto(img[y0:y1, x0:x1], part, where=m[..., None])

    def _start_tile_worker(self):
        """Wake the terrain tile worker, starting its background thread if it is not running."""
        self._tile_event.set()
        if self._tile_thread is None or not self._tile_thread.is_alive():
            self._tile_thread = threading.Thread(target=self._tile_worker, daemon=True)
            self._tile_thread.start()

    def _tile_worker(self):
        """Build the wanted tiles one at a time, nearest the view's middle first (the list follows the view).

        Runs forever on the terrain tile worker's background thread. A tile built for an older generation (the atlas
        or the map image changed meanwhile) is dropped; the cache keeps at most HIRES_TILE_CACHE tiles, least recently
        drawn dropped first. Each finished tile is announced to the window thread through the queue as ("tile", key).
        """
        while True:
            self._tile_event.wait()
            with self._tile_lock:
                if not self._tile_want:
                    self._tile_event.clear()
                    continue
                key = self._tile_want.pop(0)
                gen = self._tile_gen
            t_build = time.perf_counter()
            try:
                pix, mask = self._build_tile(*key)
            except Exception:
                LOG.exception(f"terrain tile {key} could not be built")
                continue
            self._fl_tile_built(key, (time.perf_counter() - t_build) * 1000)
            with self._tile_lock:
                if gen != self._tile_gen:  # the atlas or the map image changed meanwhile
                    continue
                self._tiles[(gen, *key)] = (key, pix, mask)
                while len(self._tiles) > HIRES_TILE_CACHE:
                    self._tiles.popitem(last=False)
            self._q.put(("tile", key))

    def build_view_tiles(self):
        """Build every tile the current view needs, now, on the calling thread (tests)."""
        w, h = self.canvas_size()
        for key in self._view_tiles(w, h, self._tile_level()):
            pix, mask = self._build_tile(*key)
            with self._tile_lock:
                self._tiles[(self._tile_gen, *key)] = (key, pix, mask)

    def _frame_weight(self, f):
        """Distance-to-edge weight of a screenshot (quarter resolution): each spot comes from its most central shot.

        Cached per screenshot until the tiles are cleared. Called on the terrain tile worker's thread.

        Args:
            f: Screenshot entry from atlas.frames ("name", "path").

        Returns:
            float32 array of shape (h / 4, w / 4): distance in quarter px to the nearest invalid pixel.
        """
        key = f["name"]
        if key not in self._weights:
            img = self.atlas.image(f["path"])
            v = core._valid_mask(img)
            small = cv2.resize(v, (v.shape[1] // 4, v.shape[0] // 4), interpolation=cv2.INTER_NEAREST)
            small[small > 0] = 255
            d = cv2.distanceTransform(small, cv2.DIST_L2, 3)
            self._weights[key] = d.astype(np.float32)
        return self._weights[key]

    def _build_tile(self, s, i, j):
        """Build one sharp-ground tile from the screenshots.

        Each pixel comes from the screenshot that owns it in the clean map (Fix seams), else from the one that shows it
        nearest its own middle (at most HIRES_MAX_FRAMES screenshots, nearest the tile's middle first). A tile (level s,
        column i, row j) covers atlas units [i, i+1) * HIRES_TILE / s by [j, j+1) * HIRES_TILE / s. Called on the
        terrain tile worker's thread (or by build_view_tiles).

        Args:
            s: Tile level in tile px per atlas unit.
            i: Tile column.
            j: Tile row.

        Returns:
            (pixels, mask): BGR uint8 image of shape (HIRES_TILE, HIRES_TILE, 3), and a uint8 mask of the filled pixels
            or None when the tile has no holes.
        """
        T = HIRES_TILE
        unit = T / s
        ax0, ay0 = i * unit, j * unit
        V = np.array([[s, 0, -ax0 * s], [0, s, -ay0 * s], [0, 0, 1]])
        out = np.zeros((T, T, 3), np.uint8)
        best = np.zeros((T, T), np.float32)
        frames = []
        for f, (poly, bb) in zip(list(self.atlas.frames), list(self.footprints), strict=False):
            if bb[2] < ax0 or bb[0] > ax0 + unit or bb[3] < ay0 or bb[1] > ay0 + unit:
                continue
            if not Path(f["path"]).exists():
                continue
            sp = (np.asarray(poly, float) - [ax0, ay0]) * s
            x0, y0 = np.floor(sp.min(axis=0)).astype(int)
            x1, y1 = np.ceil(sp.max(axis=0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(T, x1), min(T, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            ctr = sp.mean(axis=0)
            frames.append((math.hypot(ctr[0] - T / 2, ctr[1] - T / 2), f, (x0, y0, x1, y1)))
        frames.sort(key=lambda t: t[0])
        lab = getattr(self, "_labels", None)
        owner, idx_of, limit = None, {}, HIRES_MAX_FRAMES
        if lab is not None and self._terrain is not None:
            # which screenshot owns each tile pixel: the clean map's ownership map, warped into the tile
            ox, oy, sc = self._terrain[2]
            C2T = V @ np.array([[1 / sc, 0, ox], [0, 1 / sc, oy], [0, 0, 1]])
            owner = cv2.warpPerspective(
                lab[0], C2T, (T, T), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=-1
            )
            idx_of = {n: k for k, n in enumerate(lab[1])}
            present = set(np.unique(owner).tolist())
            frames = [t for t in frames if idx_of.get(t[1]["name"], -2) in present]
            limit = len(frames)
        S4 = np.diag([4.0, 4.0, 1.0])
        for _, f, (x0, y0, x1, y1) in frames[:limit]:
            Hf = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            M = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]]) @ V @ Hf
            size = (x1 - x0, y1 - y0)
            pix = cv2.warpPerspective(
                self.atlas.image(f["path"]), M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            wt = cv2.warpPerspective(
                self._frame_weight(f), M @ S4, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            sub_b = best[y0:y1, x0:x1]
            take = wt > sub_b
            if owner is not None:  # the clean map's owner, wherever this screenshot shows it
                take = (owner[y0:y1, x0:x1] == idx_of[f["name"]]) & (wt > 0)
            out[y0:y1, x0:x1][take] = pix[take]
            sub_b[take] = wt[take]
        mask = (best > 0).astype(np.uint8)
        return out, (None if mask.all() else mask)  # None: no holes

    def canvas_size(self) -> tuple[int, int]:
        """Size of the map canvas; inside a redraw the size asked once for the frame (each Tk query was ~90 a frame).

        Returns:
            (width, height) in screen px, at least 1 each.
        """
        fs = getattr(self, "_frame_size", None)
        if fs is not None:  # inside a redraw: asked once (each Tk query was ~90 a frame)
            return fs
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def canvas_size_half(self) -> tuple[float, float]:
        """The middle of the map canvas.

        Returns:
            (width / 2, height / 2) in screen px.
        """
        w, h = self.canvas_size()
        return w / 2, h / 2

    def _tk_error(self, tp, val, tb):
        """Handle an error inside a button / menu / key handler: logged with its traceback and shown in Log.

        Set as the Tk root's report_callback_exception.

        Args:
            tp: The exception type.
            val: The exception.
            tb: The traceback.
        """
        LOG.error("error in a window handler", exc_info=(tp, val, tb))
        with contextlib.suppress(Exception):
            self.log(f"error: {val!r} (details in {atlas_log.LOG_FILE.name})")

    def log(self, text: str):
        """Write a line to the log file and the Log box.

        Args:
            text: The message (surrounding newlines are stripped).
        """
        LOG.info(text.strip("\n"))
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.strip("\n") + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
