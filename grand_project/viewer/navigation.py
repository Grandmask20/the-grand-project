"""viewer.navigation: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import tkinter as tk

import cv2
import numpy as np

from grand_project import cities as atlas_cities
from grand_project import paths as rc_paths

from .constants import NODE_COL
from .helpers import icon_name, wheel_steps


class NavigationMixin:
    """Viewer mixin for the view maths (zoom / pan), what is shown under the filters, and the map canvas's mouse events.

    Attributes:
        FAR_ZOOM: Zoom below which map nodes and icons are stamped as dots, with no per-item drawing.
    """

    # ------------------------------------------------------------------ view maths
    def to_screen(self, pts) -> np.ndarray:
        """Convert atlas points to canvas positions for the current view.

        Args:
            pts: Points in atlas units, anything reshapeable to (n, 2).

        Returns:
            Float array of shape (n, 2) in screen px.
        """
        w, h = self.canvas_size()
        return (np.asarray(pts, float).reshape(-1, 2) - [self.cx, self.cy]) * self.z + [w / 2, h / 2]

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        """Convert a canvas position to atlas units for the current view.

        Args:
            sx: Screen x in canvas px.
            sy: Screen y in canvas px.

        Returns:
            (x, y) in atlas units.
        """
        w, h = self.canvas_size()
        return self.cx + (sx - w / 2) / self.z, self.cy + (sy - h / 2) / self.z

    def bounds(self):
        """The atlas's extent: the terrain image if there is one, else the map nodes with a 100-unit margin.

        Returns:
            (x0, y0, x1, y1) in atlas units; (-500, -300, 500, 300) for an empty atlas.
        """
        if self.pyr:
            x0, y0, s = self.t_origin
            h, w = self.pyr[0].shape[:2]
            return x0, y0, x0 + w / s, y0 + h / s
        if len(self.node_pts):
            (a, b), (c, d) = self.node_pts.min(0), self.node_pts.max(0)
            return a - 100, b - 100, c + 100, d + 100
        return -500, -300, 500, 300

    def fit(self):
        """Zoom and centre so the whole atlas fits the canvas (96% of it), then redraw.

        A pending fit is only marked done once the canvas has a real size (over 50 px wide).
        """
        x0, y0, x1, y1 = self.bounds()
        w, h = self.canvas_size()
        if w > 50:
            self._fit_pending = False
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.z = max(0.02, min(w / max(1, x1 - x0), h / max(1, y1 - y0)) * 0.96)
        self.request_redraw()

    def zoom_limits(self):
        """The allowed zoom range.

        Returns:
            (lowest, highest) zoom in screen px per atlas unit: 0.3 times the fit zoom, and 6.
        """
        x0, y0, x1, y1 = self.bounds()
        w, h = self.canvas_size()
        fit = min(w / max(1, x1 - x0), h / max(1, y1 - y0))
        return fit * 0.3, 6.0

    def zoom_at(self, sx, sy, factor):
        """Zoom by a factor, keeping the atlas point under (sx, sy) in place; clamped to zoom_limits.

        Args:
            sx: Screen x of the zoom centre in canvas px.
            sy: Screen y of the zoom centre in canvas px.
            factor: Zoom multiplier (> 1 zooms in).
        """
        wx, wy = self.to_world(sx, sy)
        lo, hi = self.zoom_limits()
        self.z = min(hi, max(lo, self.z * factor))
        w, h = self.canvas_size()
        self.cx, self.cy = wx - (sx - w / 2) / self.z, wy - (sy - h / 2) / self.z
        self.request_redraw()

    def pan_by(self, dx_screen, dy_screen):
        """Move the view by a distance on screen.

        Args:
            dx_screen: Horizontal distance in screen px (positive moves the view right).
            dy_screen: Vertical distance in screen px (positive moves the view down).
        """
        self.cx += dx_screen / self.z
        self.cy += dy_screen / self.z
        self.request_redraw()

    def center_on(self, x, y, min_zoom=1.0):
        """Centre the view on an atlas point, zooming in to at least min_zoom.

        Args:
            x: Atlas x in atlas units.
            y: Atlas y in atlas units.
            min_zoom: Lowest zoom to end up at (the zoom is never lowered).
        """
        self.cx, self.cy = x, y
        self.z = max(self.z, min_zoom)
        self.request_redraw()

    # ------------------------------------------------------------------ what is shown
    def _flags(self) -> tuple:
        """Filter toggle states, read once per frame (Tk variable reads were ~30% of a frame).

        Returns:
            (show doubtful, only what 2+ screenshots show, only maps with icons, "drawn by at least" share 0-1). During
            a frame the copy kept in _frame_flags.
        """
        if getattr(self, "_frame_flags", None) is not None:
            return self._frame_flags
        return (
            self.layers["Doubtful"].get(),
            self.multi_only.get(),
            self.only_icon_maps.get(),
            float(self.style()["path_freq"]),
        )

    FAR_ZOOM = 0.12  # below this: maps / icons as stamped dots, no per-item drawing

    def shown_masks(self):
        """node_shown / path_shown for every map node and path, kept until a filter or the atlas changes.

        Re-checking ~18k maps and ~14k paths each frame made the zoomed-out view lag.

        Returns:
            (key, nm, pm, A, B, strong, abyss, col): the cache key; bool mask of shown map nodes; bool mask of shown
            paths; each path's two map node indices; bool masks of confirmed paths (2+ screenshots or both ends) and
            abyss chains; each map node's BGR colour by status, uint8 of shape (n, 3).
        """
        key = (
            self._flags(),
            frozenset(self.icon_hidden),
            id(self.V["nodes"]),
            id(self.V["paths"]),
            len(self.icon_vars),
            self._rp_key(),  # replaying: only what was revealed so far
        )
        c = getattr(self, "_shown_cache", None)
        if c is None or c[0] != key:
            N = self.V["nodes"]
            nm = np.array([self.node_shown(n) for n in N], bool)
            if self.replay_active() and len(nm):
                nm &= self.rp["node_step"][: len(nm)] < self.rp["pos"]
            multi = key[0][1]
            P = self.V["paths"]
            if P:
                A = np.array([q["a"] for q in P], int)
                B = np.array([q["b"] for q in P], int)
                pm = nm[A] & nm[B]
                if multi:
                    pm &= np.array([q["frames"] >= 2 or bool(q.get("abyss")) for q in P], bool)
                share = key[0][3]
                if share > 0:  # drawn by too few of the screenshots that show both maps (as path_shown)
                    pm &= np.array(
                        [bool(q.get("abyss")) or q.get("seen_in", 0) >= share * max(1, q.get("frames", 0)) for q in P],
                        bool,
                    )
                strong = np.array([q.get("seen_in", q["frames"]) >= 2 or bool(q.get("both_ends")) for q in P], bool)
                abyss = np.array([bool(q.get("abyss")) for q in P], bool)
            else:
                A = B = np.zeros(0, int)
                pm = strong = abyss = np.zeros(0, bool)
            col = np.array([NODE_COL.get(n["status"], (255, 255, 255)) for n in N], np.uint8).reshape(-1, 3)
            self._shown_cache = c = (key, nm, pm, A, B, strong, abyss, col)
        return c

    def node_shown(self, n) -> bool:
        """Whether a map node passes the filters (removed map nodes never do).

        Args:
            n: Map node dict from V["nodes"].

        Returns:
            False for removed map nodes, doubtful ones with Doubtful off, single-screenshot ones under "2+
            screenshots" (unless confirmed by an icon), and, under "only maps with icons", ones without a ticked icon.
        """
        st = n["status"]
        if st == "removed":
            return False
        doubtful, multi, only_icons = self._flags()[:3]
        if st == "doubtful" and not doubtful:
            return False
        if multi and n.get("seen", 1) < 2 and st != "icon":
            return False
        if only_icons:
            shown = {icon_name(r) for r in n.get("icons", [])} - self.icon_hidden
            if not shown and not (
                "MapBossSpecial" in n.get("icons", [])
                and any(icon.startswith("Deadly Map Boss") and icon not in self.icon_hidden for icon in self.icon_vars)
            ):
                return False
        return True

    def path_shown(self, p) -> bool:
        """Whether a path passes the filters.

        Abyss chains skip the screenshot filters. A path drawn by too few of the screenshots that show both maps is
        hidden (user). Both its map nodes must be shown.

        Args:
            p: Path dict from V["paths"].

        Returns:
            True when the path is drawn.
        """
        fl = self._flags()
        if fl[1] and p["frames"] < 2 and not p.get("abyss"):
            return False
        if fl[3] > 0 and not p.get("abyss") and p.get("seen_in", 0) < fl[3] * max(1, p.get("frames", 0)):
            return False  # drawn by too few of the screenshots that show both maps (user)
        N = self.V["nodes"]
        return self.node_shown(N[p["a"]]) and self.node_shown(N[p["b"]])

    def landmark_shown(self, lm) -> bool:
        """Whether a landmark passes the filters.

        Removed landmarks follow the Removed layer; others are hidden when their kind is unticked in Find, when only
        cities are wanted and it is not a city, or when it is a city whose type is unticked.

        Args:
            lm: Landmark dict from V["landmarks"].

        Returns:
            True when the landmark is drawn.
        """
        if lm["status"].startswith("removed"):
            return self.layers["Removed"].get()
        if lm["kind"] in self.icon_hidden:
            return False
        if self.near_only() and lm["kind"] != "City":
            return False
        i = getattr(self, "_lm_index", {}).get(id(lm))
        if i is not None and not self._rp_shown("landmark", i):  # replaying: not revealed yet
            return False
        t = getattr(self, "city_type", {}).get(i)
        return not t or f"{t[0]} city" not in self.icon_hidden

    # ------------------------------------------------------------------ mouse
    def on_press(self, e, mark=False):
        """Start a pan, lasso, ghost move or bookmark click. Bound to <ButtonPress-1> and the middle button press.

        Args:
            e: The Tk event (e.x / e.y in canvas px).
            mark: Unused.
        """
        self._fl_input("press")
        self.canvas.focus_set()
        if getattr(self, "_lasso", None) is not None:
            self._lasso = [(e.x, e.y)]
            return
        if getattr(self, "_bm_mode", False):
            self._bm_click(e.x, e.y)
            return
        if self._ghost:
            self._ghost["drag"] = (e.x, e.y, self._ghost["cx"], self._ghost["cy"])
            return
        self._drag = (e.x, e.y, self.cx, self.cy, False)

    def on_drag(self, e):
        """Extend the lasso, move the ghost screenshot, or pan the map. Bound to <B1-Motion> and middle-button motion.

        A pan starts only after the mouse moved 4 px, so a click stays a click.

        Args:
            e: The Tk event (e.x / e.y in canvas px).
        """
        self._fl_input("drag")
        if getattr(self, "_lasso", None):
            self._lasso.append((e.x, e.y))
            self.request_redraw()
            return
        if self._ghost and self._ghost.get("drag"):
            x0, y0, gx, gy = self._ghost["drag"]
            self._ghost["cx"], self._ghost["cy"] = gx + (e.x - x0) / self.z, gy + (e.y - y0) / self.z
            self.request_redraw()
            return
        if not self._drag:
            return
        x0, y0, cx0, cy0, moved = self._drag
        if not moved and abs(e.x - x0) + abs(e.y - y0) < 4:
            return
        self._drag = (x0, y0, cx0, cy0, True)
        self.cx = cx0 - (e.x - x0) / self.z
        self.cy = cy0 - (e.y - y0) / self.z
        self.request_redraw()

    def on_release(self, e):
        """Finish a lasso, ghost move, debug link or click. Bound to <ButtonRelease-1> and the middle button release.

        A lasso picks the map nodes inside it and opens the biome menu. With a debug "missing path" link started, a
        click on a second map adds the mark. A click without a drag selects what is under it and shows the Find tab
        (the details, "Selected", are there).

        Args:
            e: The Tk event (e.x / e.y in canvas px).
        """
        self._fl_input("release")
        if getattr(self, "_lasso", None) is not None:
            poly, self._lasso = self._lasso, None
            self.canvas.configure(cursor="fleur")
            if len(poly) < 3:
                self.status.set("lasso cancelled")
                self.request_redraw()
                return
            sp = self.to_screen(self.node_pts) if len(self.node_pts) else np.zeros((0, 2))
            P = np.array(poly, np.float32).reshape(-1, 1, 2)
            ids = [
                i
                for i, q in enumerate(sp)
                if self.V["nodes"][i]["status"] != "removed"
                and cv2.pointPolygonTest(P, (float(q[0]), float(q[1])), False) >= 0
            ]
            if not ids:
                self.status.set("no maps inside the lasso")
                self.request_redraw()
                return
            self._lasso_ids = ids
            self._lasso_world = [self.to_world(x_, y_) for x_, y_ in poly]
            self.status.set(f"{len(ids)} maps inside: choose their biome")
            self.request_redraw()
            self._lasso_menu(ids, e.x, e.y)
            return
        if self._ghost:
            self._ghost["drag"] = None
            return
        if self._drag and not self._drag[4] and getattr(self, "_dbg_link", None) is not None:
            hit = self.pick(e.x, e.y)
            a, note = self._dbg_link
            self._dbg_link = None
            self._drag = None
            if hit and hit[0] == "node" and hit[1] != a:
                self._dbg_add("missing path", "there should be a path between these maps", note, maps=[a, hit[1]])
            else:
                self.status.set("debug: no second map clicked - link cancelled")
            return
        if self._drag and not self._drag[4]:
            hit = self.pick(e.x, e.y)
            self.select(hit)
            if hit:
                self.tabs.select(self.tab_find)  # the details ("Selected") are in the Find tab
        self._drag = None

    def on_double(self, e):
        """Zoom in 2x at the mouse, or fit the ghost screenshot when one is being placed. Bound to <Double-Button-1>.

        Args:
            e: The Tk event (e.x / e.y in canvas px).
        """
        if self._ghost:
            self.fit_ghost()
            return
        self.zoom_at(e.x, e.y, 2.0)

    def on_wheel(self, e):
        """Zoom at the mouse by 1.2 per wheel step (at most 5 steps). Bound to <MouseWheel> on the map canvas.

        Some Tk builds give wheel x/y relative to the screen, so canvas coords are derived from root coords.

        Args:
            e: The Tk event.
        """
        self._fl_input("wheel")
        # some Tk builds give wheel x/y relative to the screen: derive canvas coords from root coords
        x = e.x_root - self.canvas.winfo_rootx()
        y = e.y_root - self.canvas.winfo_rooty()
        self.zoom_at(x, y, 1.2 ** max(-5.0, min(5.0, wheel_steps(e))))

    def on_motion(self, e):
        """Show the atlas position under the mouse, the zoom and the atlas's counts in the status bar (<Motion>).

        Args:
            e: The Tk event (e.x / e.y in canvas px).
        """
        if not self.atlas:
            return
        wx, wy = self.to_world(e.x, e.y)
        st = self.V["stats"]
        extra = (
            (
                f"   |   {st.get('nodes_kept', 0)} nodes, {st.get('paths', 0)} paths "
                f"({st.get('paths_multi', 0)} seen in 2+ shots), {len(self.V['icons'])} icons"
            )
            if st
            else ""
        )
        self.status.set(f"x {wx:7.0f}  y {wy:7.0f}   zoom {self.z:.2f}   {len(self.V['frames'])} screenshots{extra}")

    def on_right(self, e):
        """Show the right-click menu for the spot / item under the mouse. Bound to the right button (and Ctrl+click).

        Offers bookmarks, screenshots of the spot, changing / deleting / restoring landmarks, "This map is a…", city
        type for cities, and the Debug submenu in the internal copy.

        Args:
            e: The Tk event (e.x / e.y in canvas px, x_root / y_root place the menu).
        """
        if not self.atlas:
            return
        wx, wy = self.to_world(e.x, e.y)
        hit = self.pick(e.x, e.y)
        m = tk.Menu(self.root, tearoff=0)
        if hit:
            self.select(hit)
            m.add_command(label="Bookmark this…", command=self.bookmark_selection)
        m.add_command(label="Add bookmark here…", command=lambda: self.add_bookmark_dialog(wx, wy))
        m.add_command(label="Screenshots of this spot", command=lambda: self.show_sources(wx, wy))
        if hit and hit[0] == "bookmark":
            m.add_separator()
            m.add_command(label="Delete bookmark", command=self.delete_bookmark)
        if hit and hit[0] == "landmark":
            lm = self.V["landmarks"][hit[1]]
            m.add_separator()
            m.add_cascade(label="Change to", menu=self._kind_menu(m, lm["x"], lm["y"], lm["kind"]))
            if lm["status"].startswith("removed"):
                m.add_command(label="Restore landmark", command=lambda: self.set_landmark(lm["x"], lm["y"], lm["kind"]))
            else:
                m.add_command(label="Delete landmark", command=lambda: self.set_landmark(lm["x"], lm["y"], ""))
        if hit and hit[0] == "node":
            nd = self.V["nodes"][hit[1]]
            m.add_separator()
            m.add_cascade(label="This map is a…", menu=self._kind_menu(m, nd["x"], nd["y"], on="map"))
        if hit and hit[0] == "landmark" and self.V["landmarks"][hit[1]]["kind"] == "City":
            i = hit[1]
            cur = self.city_type.get(i, ("", ""))
            tm = tk.Menu(m, tearoff=0)
            for t in atlas_cities.TYPES:
                tm.add_command(
                    label=("● " if cur == (t, "set") else "") + t, command=lambda t=t: self.set_city_type(i, t)
                )
            tm.add_separator()
            tm.add_command(
                label="Automatic" + (" ●" if cur[1] != "set" else ""), command=lambda: self.set_city_type(i, None)
            )
            m.add_separator()
            m.add_cascade(label="City type", menu=tm)
        if rc_paths.DEBUG:
            m.add_separator()
            m.add_cascade(label="Debug", menu=self._dbg_menu(m, hit, wx, wy))
        m.tk_popup(e.x_root, e.y_root)
