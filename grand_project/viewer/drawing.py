"""viewer.drawing: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np
from PIL import Image, ImageTk

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import paths as rc_paths

from .constants import (
    BG,
    BOOKMARK_COL,
    CITY_COL,
    HIT_COL,
    LANDMARK_COL,
    NODE_COL,
    PATH_ABYSS,
    PATH_MULTI,
    PATH_SINGLE,
    PROFILE,
    REMOVED_COL,
    SELECT_COL,
)
from .helpers import blit_rgba, draw_map, hex_bgr, icon_col, icon_label, icon_thumb, put_text


class DrawingMixin:
    # ------------------------------------------------------------------ drawing
    def node_radius(self) -> float:
        return float(min(13, max(2, 8 * self.z))) * float(self.style()["map_size"])

    def _map_pic(self):
        if getattr(self, "_mpic", None) is None:
            fp = rc_paths.ref("map_node_icon.webp")
            self._mpic = Image.open(fp).convert("RGBA") if fp.exists() else icon_thumb("Unidentified", 48)
        return self._mpic

    def landmark_box(self):
        """half-width, height above, depth below the landmark point, in screen px (scales with zoom)"""
        s = max(0.12, self.z)
        return max(5, 30 * s), max(8, 60 * s), max(2, 10 * s)

    def request_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.root.after(8, self._redraw)

    def _redraw(self):
        self._redraw_pending = False
        w, h = self.canvas_size()
        t0 = time.perf_counter()
        img = self.render(w, h)
        self.photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        self.canvas.itemconfigure(self.img_item, image=self.photo)
        self.last_render_ms = (time.perf_counter() - t0) * 1000
        if PROFILE and self.last_render_ms > 200:
            print(f"[viewer] slow on the window thread: redraw took {self.last_render_ms / 1000:.2f}s", flush=True)

    def render(self, w: int, h: int) -> np.ndarray:
        img = np.empty((h, w, 3), np.uint8)
        img[:] = BG
        if not self.atlas:
            put_text(
                img, "File > New atlas, then Add screenshots   |   File > Open atlas", (30, 40), (220, 220, 220), 0.7
            )
            return img
        L = {k: v.get() for k, v in self.layers.items()}
        self._frame_flags = None
        self._frame_flags = self._flags()
        try:
            return self._render(img, w, h, L)
        finally:
            self._frame_flags = None

    def _render(self, img, w, h, L):
        z = self.z
        overview = z < 0.45  # zoomed out: dots, no small labels
        if L["Terrain"] and self.pyr:
            x0, y0, s0 = self.t_origin
            lvl = int(min(len(self.pyr) - 1, max(0, math.floor(math.log2(max(1e-6, s0 / z))))))
            sl = s0 / (2**lvl)
            a = z / sl
            A = np.array([[a, 0, (x0 - self.cx) * z + w / 2], [0, a, (y0 - self.cy) * z + h / 2]])
            cv2.warpAffine(self.pyr[lvl], A, (w, h), dst=img, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
            if self.hires_wanted():
                if self._hires and self._hires[0] == self.view_key(w, h):
                    img[self._hires[2]] = self._hires[1][self._hires[2]]  # screenshot pixels, 1:1
                else:
                    self._schedule_hires()  # sharpen once the view settles
            if L["Paths"] or L["Nodes"]:
                # dim the ground under the lines; a smooth slope (a step at the overview switch
                # made the map jump ~20% darker between zoom 0.50 and 0.42)
                img = cv2.convertScaleAbs(img, alpha=float(np.clip(0.72 + 0.16 * (z - 0.2), 0.72, 0.8)))
        N = self.V["nodes"]
        sp = self.to_screen(self.node_pts) if len(self.node_pts) else np.zeros((0, 2))
        vis = ((sp[:, 0] > -80) & (sp[:, 0] < w + 80) & (sp[:, 1] > -80) & (sp[:, 1] < h + 80)) if len(sp) else []
        th = 1 if z < 0.7 else 2
        if L["City & stronghold biomes"] and self.potential and len(sp):
            tint = img.copy()
            rad = max(4, int(44 * z))
            rings = []
            for i, (lab, _st) in self.potential.items():
                if (
                    not vis[i]
                    or self.potential_kind(lab) in self.icon_hidden
                    or (self.near_only() and "city" not in lab.lower())
                ):
                    continue
                cols = [
                    CITY_COL.get(part.replace(" city", "").replace(" stronghold", ""), (255, 200, 80))
                    for part in lab.split(" / ")
                ]
                pt = (int(sp[i, 0]), int(sp[i, 1]))
                cv2.circle(tint, pt, rad, cols[0], -1, cv2.LINE_AA)
                rings.append((pt, cols[-1]))
            img = cv2.addWeighted(tint, 0.38, img, 0.62, 0)
            for pt, col in rings:
                cv2.circle(img, pt, rad, col, 1 if overview else 2, cv2.LINE_AA)
        ST = self.style()
        c_multi = hex_bgr(ST["path_col"], PATH_MULTI)
        c_single = hex_bgr(ST["path_col1"], PATH_SINGLE)
        c_map = hex_bgr(ST["map_col"], None)
        pth = int(ST["path_width"]) or th
        if L["Paths"] and overview and len(sp):
            # zoomed out: one batched draw call per colour (14k paths on a large atlas), masks cached
            _k, nm, pm, A, B, strong, abyss, _c = self.shown_masks()
            keep = pm & (vis[A] | vis[B]) if len(A) else pm
            for col, sel in (
                (PATH_ABYSS, keep & abyss),
                (c_multi, keep & ~abyss & strong),
                (c_single, keep & ~abyss & ~strong),
            ):
                if sel.any():
                    segs = np.stack([sp[A[sel]], sp[B[sel]]], 1).astype(np.int32)
                    cv2.polylines(img, list(segs), False, col, 1, cv2.LINE_8)
        elif L["Paths"]:
            # pieces (whole lines, dashes or dots) are cut once in atlas units and cached; a pan only moves them
            groups = self._path_pieces(ST, pth, c_multi, c_single)
            aa = cv2.LINE_AA if z >= 0.8 else cv2.LINE_8
            for (col, wdt), (pts_a, starts) in groups.items():
                q = self.to_screen(pts_a)
                inside = (q[:, 0] > -50) & (q[:, 0] < w + 50) & (q[:, 1] > -50) & (q[:, 1] < h + 50)
                keep = np.logical_or.reduceat(inside, starts) if len(starts) else np.zeros(0, bool)
                ends = np.append(starts[1:], len(q))
                pieces = [q[a:b].astype(np.int32) for a, b, k in zip(starts, ends, keep, strict=False) if k]
                if pieces:
                    cv2.polylines(img, pieces, False, col, wdt, aa)
            if self.sel and self.sel[0] == "path" and self.sel_valid():
                p = self.V["paths"][self.sel[1]]
                line = self.to_screen(self._path_atlas_line(p))
                cv2.polylines(img, [line.astype(np.int32)], False, (0, 0, 0), pth + 6, cv2.LINE_AA)
                cv2.polylines(img, [line.astype(np.int32)], False, SELECT_COL, pth + 3, cv2.LINE_AA)
        r = self.node_radius()
        hit_nodes = {i for k, i in self.hits if k == "node"}
        far = z < self.FAR_ZOOM
        if L["Nodes"] and len(sp) and far:
            _k, nm, _pm, _A, _B, _s, _a, ncol = self.shown_masks()
            sel = np.nonzero(vis & nm)[0]
            X = np.round(sp[sel, 0]).astype(int)
            Y = np.round(sp[sel, 1]).astype(int)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xx, yy = X + dx, Y + dy
                    ok = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
                    img[yy[ok], xx[ok]] = ncol[sel[ok]]
            for i in hit_nodes:
                if i < len(sp) and vis[i]:
                    cv2.circle(img, (int(sp[i, 0]), int(sp[i, 1])), 8, HIT_COL, 2, cv2.LINE_AA)
        elif L["Nodes"] and len(sp):
            _k, nm, *_ = self.shown_masks()
            for i in np.nonzero(vis)[0]:
                n = N[i]
                pt = (int(sp[i, 0]), int(sp[i, 1]))
                if n["status"] == "removed":
                    if L["Removed"] and not n["why"].startswith("joined"):
                        cv2.drawMarker(img, pt, REMOVED_COL, cv2.MARKER_TILTED_CROSS, max(6, int(2 * r)), 2)
                    continue
                if not nm[i]:
                    continue
                col = NODE_COL.get(n["status"], (255, 255, 255))
                if c_map is not None and n["status"] in ("confirmed", "icon"):
                    col = c_map
                if ST["map_style"] == "hidden":
                    pass
                elif overview:
                    if ST["map_style"] == "squares":
                        cv2.rectangle(
                            img,
                            (pt[0] - max(2, int(r)), pt[1] - max(2, int(r))),
                            (pt[0] + max(2, int(r)), pt[1] + max(2, int(r))),
                            col,
                            -1,
                        )
                    else:
                        cv2.circle(img, pt, max(2, int(r)), col, -1, cv2.LINE_AA)
                else:
                    draw_map(img, pt, r, col, th, ST["map_style"], self._map_pic())
                if i in hit_nodes:
                    cv2.circle(img, pt, int(r + 7), HIT_COL, 2, cv2.LINE_AA)
        if L["Icons"] and len(self.icon_pts) and far:
            ip = self.to_screen(self.icon_pts)
            ck = (frozenset(self.icon_hidden), id(self.V["icons"]), self.near_only())
            if getattr(self, "_icon_far", (None,))[0] != ck:
                show = np.array(
                    [self.icon_visible(ic) and ic["name"] != "Unidentified" for ic in self.V["icons"]], bool
                )
                icol = np.array([icon_col(ic["name"]) for ic in self.V["icons"]], np.uint8).reshape(-1, 3)
                self._icon_far = (ck, show, icol)
            _ck, show, icol = self._icon_far
            X = np.round(ip[:, 0]).astype(int)
            Y = np.round(ip[:, 1]).astype(int)
            sel = np.nonzero(show & (X >= 1) & (w - 1 > X) & (Y >= 1) & (h - 1 > Y))[0]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    img[Y[sel] + dy, X[sel] + dx] = icol[sel]
        elif L["Icons"] and len(self.icon_pts):
            ip = self.to_screen(self.icon_pts)
            hit_ic = {i for k, i in self.hits if k == "icon"}
            labels = L["Labels"] and z >= 0.8
            placed: list[tuple[int, int, int, int]] = []  # label boxes, so labels never overlap
            for i, ic in enumerate(self.V["icons"]):
                x, y = int(ip[i, 0]), int(ip[i, 1])
                if not (-40 < x < w + 200 and -40 < y < h + 40):
                    continue
                if not self.icon_visible(ic):
                    continue
                if ic["name"] == "Unidentified" and overview:
                    continue
                col = icon_col(ic["name"])
                rr = max(3, int(13 * z)) if not overview else max(3, int(8 * z) + 2)
                if overview:
                    cv2.circle(img, (x, y), rr, col, -1, cv2.LINE_AA)
                    cv2.circle(img, (x, y), rr, (0, 0, 0), 1, cv2.LINE_AA)
                elif ST["ov_badges"]:
                    blit_rgba(img, icon_thumb(ic["name"], 48), x, y, 2.2 * rr)
                else:
                    cv2.circle(img, (x, y), rr, col, 2, cv2.LINE_AA)
                if i in hit_ic:
                    cv2.circle(img, (x, y), rr + 7, HIT_COL, 2, cv2.LINE_AA)
                if labels:
                    text = icon_label(ic)
                    box = (x + rr + 4, y - 8, x + rr + 4 + 8 * len(text), y + 6)
                    if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                        placed.append(box)
                        put_text(img, text, (x + rr + 4, y + 4), col, 0.42)
        if L["Landmarks"]:
            hit_lm = {i for k, i in self.hits if k == "landmark"}
            hw, top, bot = self.landmark_box()
            for i, lm in enumerate(self.V["landmarks"]):
                if not self.landmark_shown(lm):
                    continue
                p = self.to_screen([[lm["x"], lm["y"]]])[0]
                if not (-80 < p[0] < w + 80 and -80 < p[1] < h + 120):
                    continue
                removed = lm["status"].startswith("removed")
                col = REMOVED_COL if removed else LANDMARK_COL.get(lm["kind"], (200, 200, 200))
                x, y = int(p[0]), int(p[1])
                if overview:
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), col, -1)
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), (0, 0, 0), 1)
                else:
                    if ST["ov_towers"] and lm["kind"] == "Tower" and not removed:
                        blit_rgba(img, icon_thumb("LostTower", 64), x, y - int(top) / 2, 1.6 * hw)
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), col, 2, cv2.LINE_AA)
                if lm["status"] == "disputed" and not overview:
                    put_text(img, "?", (x + int(hw) - 10, y - int(top) + 16), col, 0.6, 2)
                if i in hit_lm:
                    cv2.rectangle(
                        img, (x - int(hw) - 5, y - int(top) - 5), (x + int(hw) + 5, y + int(bot) + 5), HIT_COL, 2
                    )
                if L["Labels"] and z >= 0.3:
                    put_text(img, self.lm_name(i), (x - int(hw), y - int(top) - 6), col, 0.45 if z < 1 else 0.55)
        if L["Bookmarks"]:
            hit_bm = {i for k, i in self.hits if k == "bookmark"}
            for i, b in enumerate(self.atlas.bookmarks):
                if not self.bookmark_shown(b):
                    continue
                p = self.to_screen([[b["x"], b["y"]]])[0]
                x, y = int(p[0]), int(p[1])
                if not (-40 < x < w + 300 and -40 < y < h + 40):
                    continue
                pin = np.array([[x, y], [x - 7, y - 14], [x + 7, y - 14]], np.int32)
                cv2.fillPoly(img, [pin], BOOKMARK_COL, cv2.LINE_AA)
                cv2.circle(img, (x, y - 16), 8, BOOKMARK_COL, -1, cv2.LINE_AA)
                cv2.circle(img, (x, y - 16), 8, (0, 0, 0), 1, cv2.LINE_AA)
                if i in hit_bm:
                    cv2.circle(img, (x, y - 12), 18, HIT_COL, 2, cv2.LINE_AA)
                put_text(img, b["name"], (x + 11, y - 12), BOOKMARK_COL, 0.5)
        self._draw_pending(img)
        self._draw_recent(img)
        if getattr(self, "_lasso", None) and len(self._lasso) > 1:
            cv2.polylines(img, [np.array(self._lasso, np.int32)], True, (0, 255, 255), 2, cv2.LINE_AA)
        self._draw_ghost(img, w, h)
        self._draw_progress(img, w, h)
        if self.hits:  # everything listed in Find: a ring on each
            R = int(np.clip(30 * z, 16, 34))  # grows when zooming in, stays visible zoomed out
            pts = self.to_screen([self.item_pos(it) for it in self.hits])
            for x, y in pts:
                if -40 < x < w + 40 and -40 < y < h + 40:
                    cv2.circle(img, (int(x), int(y)), R, (0, 0, 0), 5, cv2.LINE_AA)
                    cv2.circle(img, (int(x), int(y)), R, SELECT_COL, 2, cv2.LINE_AA)
        if rc_paths.DEBUG and self.path:
            if getattr(self, "_dbg_listed", None) != self.path:  # another atlas: its own marks
                self._dbg_listed = self.path
                self._dbg_refresh()
            self._dbg_draw(img)
        if getattr(self, "_goto", None) is not None:
            g = self.to_screen([self._goto])[0]
            gx, gy = int(g[0]), int(g[1])
            for c_, t_ in (((0, 0, 0), 5), ((0, 0, 255), 2)):
                cv2.line(img, (gx - 22, gy), (gx + 22, gy), c_, t_, cv2.LINE_AA)
                cv2.line(img, (gx, gy - 22), (gx, gy + 22), c_, t_, cv2.LINE_AA)
        if self.sel and self.sel_valid() and self.sel[0] != "path":
            p = self.to_screen([self.item_pos(self.sel)])[0]
            cv2.circle(img, (int(p[0]), int(p[1])), int(max(r, 10) + 10), SELECT_COL, 2, cv2.LINE_AA)
        self._legend(img, L)
        return img

    def _legend(self, img, L=None):
        h = img.shape[0]
        L = L or {}
        items = [
            ("map: 2+ shots / icon", NODE_COL["confirmed"]),
            ("1 shot", NODE_COL["single"]),
            ("path: confirmed", PATH_MULTI),
            ("single evidence", PATH_SINGLE),
            ("abyss chain", PATH_ABYSS),
        ]
        if L.get("City & stronghold biomes") and getattr(self, "potential", None):
            items += [(f"near {k}", CITY_COL[k]) for k in CITY_COL]
        x = 10
        width = 24 + sum(22 + len(t) * 8 for t, _ in items)
        cv2.rectangle(img, (4, h - 26), (min(img.shape[1] - 4, width), h - 4), (20, 20, 20), -1)
        for text, col in items:
            cv2.circle(img, (x + 6, h - 15), 5, col, -1, cv2.LINE_AA)
            put_text(img, text, (x + 15, h - 10), (215, 215, 215), 0.42)
            x += 22 + len(text) * 8
