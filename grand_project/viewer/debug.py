"""viewer.debug: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import json
import math
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import core

from .constants import PATH_ABYSS, VERSION
from .helpers import draw_paths, put_text


class DebugMixin:
    # ------------------------------------------------------------------ debug marks (internal copy only)
    def _dbg_file(self) -> Path | None:
        return core.atlas_files(self.path) / "debug_marks.json" if self.path else None

    def _dbg_marks(self) -> list:
        fp = self._dbg_file()
        if fp is None:
            return []
        key = str(fp)
        if getattr(self, "_dbg_cache", (None,))[0] != key:
            try:
                marks = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
            except (OSError, ValueError):
                marks = []
            for i_, m_ in enumerate(marks, 1):  # a mark keeps its D number for good (user)
                m_.setdefault("id", i_)
            self._dbg_cache = (key, marks)
        return self._dbg_cache[1]

    def _dbg_save(self):
        fp = self._dbg_file()
        if fp is not None:
            fp.write_text(json.dumps(self._dbg_marks(), indent=1), encoding="utf-8")
        self._dbg_refresh()
        self.request_redraw()

    def _dbg_refresh(self):
        if not hasattr(self, "dbg_list"):
            return
        self.dbg_list.delete(0, "end")
        for k, mk in enumerate(self._dbg_marks(), 1):
            self.dbg_list.insert(
                "end",
                f"D{mk.get('id', k)}  {mk['kind']}: {mk['reason']}"
                + (f" - {mk['note']}" if mk.get("note") else "")
                + f"  ({mk['x']:.0f}, {mk['y']:.0f})",
            )
        fp = self._dbg_file()
        self.dbg_file_lab.configure(text=f"{len(self._dbg_marks())} mark(s) in {fp}" if fp else "")

    def _dbg_goto(self):
        sel = self.dbg_list.curselection()
        if sel:
            mk = self._dbg_marks()[sel[0]]
            self.center_on(mk["x"], mk["y"], min_zoom=1.0)

    def _dbg_delete(self):
        sel = self.dbg_list.curselection()
        if sel:
            del self._dbg_marks()[sel[0]]
            self._dbg_save()

    def _dbg_shots(self, x, y, k=5) -> list[str]:
        """the screenshots that show (x, y) best (nearest their centre)"""
        return [f["name"] for f, _x, _y in self.frames_at(x, y)[:k]]

    def _dbg_add(self, kind, reason, note, x=None, y=None, maps=(), path=None):
        from tkinter import simpledialog

        if note is None:
            note = simpledialog.askstring("Debug mark", f"{kind}: {reason}\nNote (optional):", parent=self.root)
            if note is None:  # cancelled
                return
        N = self.V["nodes"]
        mk = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "reason": reason,
            "note": note or "",
            "version": VERSION,
            "maps": [],
        }
        for i in maps:
            n = N[i]
            mk["maps"].append(
                {
                    "id": int(i),
                    "x": round(n["x"], 1),
                    "y": round(n["y"], 1),
                    "status": n["status"],
                    "seen": n.get("seen"),
                    "could": n.get("could"),
                    "origin": n.get("origin"),
                    "icons": n.get("icons", []),
                    "why": n.get("why", ""),
                }
            )
        if path is not None:
            p = self.V["paths"][path]
            mk["path"] = {
                k_: p.get(k_)
                for k_ in ("a", "b", "kind", "frames", "seen_in", "both_ends", "ends_in", "confirm", "deny", "dashes")
            }
            mk["path"]["ends"] = [
                [round(N[p["a"]]["x"], 1), round(N[p["a"]]["y"], 1)],
                [round(N[p["b"]]["x"], 1), round(N[p["b"]]["y"], 1)],
            ]
        if x is None:
            pts = [(m_["x"], m_["y"]) for m_ in mk["maps"]] or (
                [tuple(np.mean(mk["path"]["ends"], 0))] if path is not None else []
            )
            x, y = float(np.mean([q[0] for q in pts])), float(np.mean([q[1] for q in pts]))
        mk["x"], mk["y"] = round(float(x), 1), round(float(y), 1)
        mk["screenshots"] = self._dbg_shots(mk["x"], mk["y"])
        marks = self._dbg_marks()
        mk["id"] = max([m_.get("id", i_ + 1) for i_, m_ in enumerate(marks)] + [0]) + 1  # never reused
        marks.append(mk)
        self._dbg_save()
        self.status.set(f"debug mark saved: {kind} ({reason})")

    def _dbg_menu(self, parent, hit, wx, wy):
        dm = tk.Menu(parent, tearoff=0)
        if hit and hit[0] in ("node", "icon"):
            i = hit[1] if hit[0] == "node" else getattr(self, "icon_node", {}).get(hit[1])
            if i is not None:
                for reason in (
                    "not a map (no base there)",
                    "map is in the wrong spot",
                    "duplicate of a map next to it",
                    "wrong paths at this map",
                    "other",
                ):
                    dm.add_command(
                        label=f"Map: {reason}…", command=lambda r=reason: self._dbg_add("wrong map", r, None, maps=[i])
                    )
                dm.add_separator()

                def start_link():
                    self._dbg_link = (i, "")
                    self.status.set("debug: now click the map this one should have a path to")

                dm.add_command(label="Missing path from here: click the other map", command=start_link)
                dm.add_separator()
        if hit and hit[0] == "path":
            for reason in (
                "no path here",
                "wrong end map",
                "crosses / runs through a structure",
                "wrong shape",
                "other",
            ):
                dm.add_command(
                    label=f"Path: {reason}…", command=lambda r=reason: self._dbg_add("wrong path", r, None, path=hit[1])
                )
            dm.add_separator()
        for reason in ("visible map base", "hidden map (paths lead in)", "other"):
            dm.add_command(
                label=f"Add a map here: {reason}…",
                command=lambda r=reason: self._dbg_add("missing map", r, None, x=wx, y=wy),
            )
        return dm

    def _dbg_draw(self, img):
        col = (255, 0, 255)
        for k, mk in enumerate(self._dbg_marks(), 1):
            p = self.to_screen([[mk["x"], mk["y"]]])[0]
            x, y = int(p[0]), int(p[1])
            if mk["kind"] in ("missing path", "wrong path") and (len(mk["maps"]) == 2 or mk.get("path")):
                ends = mk["path"]["ends"] if mk.get("path") else [[m_["x"], m_["y"]] for m_ in mk["maps"]]
                q = self.to_screen(ends).astype(int)
                if mk["kind"] == "missing path":
                    draw_paths(img, [q], col, 2, "dotted")
                else:
                    cv2.line(img, tuple(q[0]), tuple(q[1]), col, 2, cv2.LINE_AA)
                    cv2.drawMarker(img, (x, y), col, cv2.MARKER_TILTED_CROSS, 18, 2)
            elif mk["kind"] == "missing map":
                cv2.drawMarker(img, (x, y), col, cv2.MARKER_CROSS, 26, 2)
            else:
                cv2.circle(img, (x, y), 18, col, 2, cv2.LINE_AA)
                cv2.drawMarker(img, (x, y), col, cv2.MARKER_TILTED_CROSS, 16, 2)
            put_text(img, f"D{mk.get('id', k)}", (x + 14, y - 12), col, 0.45)

    def pick(self, sx, sy) -> tuple[str, int] | None:
        if not self.atlas:
            return None
        best, bd = None, 1e9
        if self.layers["Bookmarks"].get():
            for i, b in enumerate(self.atlas.bookmarks):
                if not self.bookmark_shown(b):
                    continue
                p = self.to_screen([[b["x"], b["y"]]])[0]
                d = math.hypot(p[0] - sx, p[1] - sy + 14)
                if d < 16 and d < bd:
                    best, bd = ("bookmark", i), d
        if best:
            return best
        if self.layers["Icons"].get() and len(self.icon_pts):
            sp = self.to_screen(self.icon_pts)
            d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
            i = int(np.argmin(d))
            if d[i] < max(9, 15 * self.z) and d[i] < bd:
                best, bd = ("icon", i), d[i]
        if self.layers["Landmarks"].get():
            for i, lm in enumerate(self.V["landmarks"]):
                if not self.landmark_shown(lm):
                    continue
                p = self.to_screen([[lm["x"], lm["y"]]])[0]
                hw, top, bot = self.landmark_box()
                if p[0] - hw <= sx <= p[0] + hw and p[1] - top <= sy <= p[1] + bot:
                    d = math.hypot(p[0] - sx, p[1] - top / 2 - sy)
                    if d < bd:
                        best, bd = ("landmark", i), d
        if len(self.node_pts):
            # maps are clickable even when hidden (layer off, filtered out): a click right on a map's centre
            # selects the map, also inside a landmark's box (only removed maps are never picked)
            sp = self.to_screen(self.node_pts)
            d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
            for i in np.argsort(d)[:5]:
                if self.V["nodes"][i]["status"] == "removed":
                    continue
                if d[i] < max(10, self.node_radius() + 5) and (d[i] < bd or best and best[0] == "landmark"):
                    best, bd = ("node", int(i)), d[i]
                break
        if best is None and self.layers["Paths"].get() and self.V["paths"]:
            best = self._pick_path(sx, sy)
        if best is None and self.layers["City & stronghold biomes"].get() and getattr(self, "potential", None):
            ids = [v for v, (lab, _st) in self.potential.items() if self.potential_kind(lab) not in self.icon_hidden]
            if ids:  # anywhere inside a biome circle selects its map
                sp = self.to_screen(self.node_pts[ids])
                d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
                k = int(np.argmin(d))
                if d[k] <= max(4, int(44 * self.z)):
                    best = ("node", int(ids[k]))
        return best

    def _path_pieces(self, ST, th, c_multi, c_single) -> dict:
        """{(colour, width): (all piece points in atlas units, start index of each piece)} for the shown paths,
        cut into dashes / dots for the style; cached until paths, filters, style or zoom change"""
        z = round(self.z, 3)
        key = (
            id(self.V["paths"]),
            id(self.V["nodes"]),
            self._flags(),
            frozenset(self.icon_hidden),
            ST["path_style"],
            th,
            c_multi,
            c_single,
            z if ST["path_style"] != "solid" else 0,
        )
        c = getattr(self, "_pp_cache", None)
        if c is not None and c[0] == key:
            return c[1]
        N = self.V["nodes"]
        groups: dict = {}
        style = ST["path_style"]
        on = (max(6.0, 5.0 * th) if style == "dashed" else 0.6) / max(z, 1e-3)
        period = on + (max(4.0, 3.0 * th) if style == "dashed" else max(5.0, 4.0 * th)) / max(z, 1e-3)
        for p in self.V["paths"]:
            if not self.path_shown(p):
                continue
            strong = p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends")
            col = PATH_ABYSS if p.get("abyss") else c_multi if strong else c_single
            wdt = th + (1 if p.get("abyss") else 0)
            L = np.array(p.get("line") or [[N[p["a"]]["x"], N[p["a"]]["y"]], [N[p["b"]]["x"], N[p["b"]]["y"]]], float)
            L[0] = (N[p["a"]]["x"], N[p["a"]]["y"])
            L[-1] = (N[p["b"]]["x"], N[p["b"]]["y"])
            g = groups.setdefault((col, wdt if style != "dotted" else max(2, 2 * wdt)), [])
            if style == "solid":
                g.append(L)
                continue
            seg = np.hypot(*np.diff(L, axis=0).T)
            cum = np.concatenate([[0], np.cumsum(seg)])
            if cum[-1] < 1e-6:
                continue
            t0 = np.arange(0, cum[-1], period)
            t1 = np.minimum(t0 + on, cum[-1])
            a_ = np.column_stack([np.interp(t0, cum, L[:, 0]), np.interp(t0, cum, L[:, 1])])
            b_ = np.column_stack([np.interp(t1, cum, L[:, 0]), np.interp(t1, cum, L[:, 1])])
            g.extend(np.stack([a_, b_], 1))
        out = {}
        for k, pieces in groups.items():
            if not pieces:
                continue
            lens = np.array([len(x) for x in pieces])
            out[k] = (np.vstack(pieces), np.concatenate([[0], np.cumsum(lens)[:-1]]))
        self._pp_cache = (key, out)
        return out

    def _path_atlas_line(self, p) -> np.ndarray:
        """a path's line in atlas units with its ends on its maps, exactly as it is drawn"""
        N = self.V["nodes"]
        L = np.array(p.get("line") or [[N[p["a"]]["x"], N[p["a"]]["y"]], [N[p["b"]]["x"], N[p["b"]]["y"]]], float)
        L[0] = (N[p["a"]]["x"], N[p["a"]]["y"])
        L[-1] = (N[p["b"]]["x"], N[p["b"]]["y"])
        return L

    def _pick_path(self, sx, sy):
        """the path within a few px of the click (clicks right on a map pick the map first)"""
        q = np.array([sx, sy], float)
        best, bd = None, 7.0
        for k, p in enumerate(self.V["paths"]):
            if not self.path_shown(p):
                continue
            L = self.to_screen(self._path_atlas_line(p))
            lo, hi = L.min(axis=0) - bd, L.max(axis=0) + bd
            if not (lo[0] <= sx <= hi[0] and lo[1] <= sy <= hi[1]):
                continue
            a, b = L[:-1], L[1:]
            ab = b - a
            t = np.clip(((q - a) * ab).sum(1) / np.maximum(1e-9, (ab * ab).sum(1)), 0, 1)
            d = float(np.min(np.hypot(*(a + t[:, None] * ab - q).T)))
            if d < bd:
                best, bd = ("path", k), d
        return best
