"""app.replay_data: part of AtlasSession (a mixin; see app/session.py): the timelapse and "Colour by".

The page plays the replay; the session works out its plan (app.replay.make_plan): the step each screenshot, map,
icon and landmark appears at. While the replay is open those steps go into the vector tiles (a "step" property the
page filters on). The ground not revealed yet is covered by fog: a grid of the step each spot's ground is revealed at,
which the page draws every frame. "Colour by" needs every screenshot's outline, session and age rank, and the "times
seen" heatmap picture.
"""

from __future__ import annotations

import base64
import math

import cv2
import numpy as np

from . import replay as R
from .atlaslock import atlas_edit
from .constants import (
    COLOUR_SPREADS,
    HEAT_RES,
    REPLAY_DEFAULTS,
    REPLAY_FOG_RES,
    REPLAY_SESSION_COLS,
    REPLAY_TINT_ALPHA,
    REPLAY_TYPES,
)
from .icons import bgr_hex


def spread_colours(name: str | None) -> list[str]:
    """Return a colour spread (View tab) as 256 CSS colours.

    Args:
        name: A COLOUR_SPREADS name (default plasma).

    Returns:
        256 "#rrggbb" strings, low to high.
    """
    cmap = COLOUR_SPREADS.get(name, cv2.COLORMAP_PLASMA)
    ramp = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(-1, 1), cmap)[:, 0]
    return [bgr_hex(tuple(int(v) for v in c)) for c in ramp]


class ReplayMixin:
    """AtlasSession mixin: the timelapse and "Colour by" (see the module docstring)."""

    # ------------------------------------------------------------------ helpers
    def atlas_bounds(self) -> tuple[float, float, float, float]:
        """Return the atlas's extent: the map image, else the maps with a margin.

        Returns:
            (x0, y0, x1, y1) in atlas units.
        """
        if self.terrain is not None:
            canvas, _w, (x0, y0, s) = self.terrain
            h, w = canvas.shape[:2]
            return x0, y0, x0 + w / s, y0 + h / s
        pts = self.D.get("node_pts")
        if pts is not None and len(pts):
            (a, b), (c, d) = pts.min(0), pts.max(0)
            return a - 100, b - 100, c + 100, d + 100
        return -500, -300, 500, 300

    def replay_settings(self) -> dict:
        """Return the replay settings (REPLAY_DEFAULTS overlaid with the saved ones).

        Returns:
            {type, reveal, camera, smoothing, length, speed, per_step, ...}.
        """
        st = {**REPLAY_DEFAULTS, **self.settings.get("replay", {})}
        if st["type"] not in REPLAY_TYPES:
            st["type"] = "by time"
        return st

    def _age_info(self):
        """Return every screenshot's time order, session, age rank (0 oldest .. 1 newest) and time.

        Returns:
            (order, sessions, rank, times), or None without screenshots.
        """
        frames = self.atlas.frames if self.atlas else []
        if not frames:
            return None
        key = (id(frames), len(frames))
        c = getattr(self, "_age_cache", None)
        if c is None or c[0] != key:
            times = [R.capture_time(f) for f in frames]
            order = R.time_order(times)
            rank = np.zeros(len(frames))
            rank[order] = np.linspace(0, 1, len(frames)) if len(frames) > 1 else 1.0
            c = self._age_cache = (key, (order, R.sessions(times), rank, times))
        return c[1]

    # ------------------------------------------------------------------ Colour by
    def frames_payload(self) -> dict:
        """Return what "Colour by" and the replay draw per screenshot, plus the colours.

        Returns:
            {"frames": [{"name", "corners", "session", "rank", "time"}], "order" (oldest first), "ramp" (256 colours),
            "sessions" (colours), "legend": [{"label", "colour"}], "oldest", "newest", "alpha", "heat_top"}.
        """
        info = self._age_info()
        style = self.ui_settings()["style"]
        out = {
            "frames": [],
            "order": [],
            "ramp": spread_colours(style.get("colour_spread")),
            "sessions": [bgr_hex(c) for c in REPLAY_SESSION_COLS],
            "legend": [],
            "oldest": "",
            "newest": "",
            "alpha": REPLAY_TINT_ALPHA,
            "heat_top": self.heat_top() if info else 1,
        }
        if info is None:
            return out
        order, sess, rank, times = info
        fp = self.D.get("footprints") or []
        for i, f in enumerate(self.atlas.frames):
            corners = fp[i][0].tolist() if i < len(fp) else []
            out["frames"].append(
                {
                    "name": f["name"],
                    "corners": corners,
                    "session": int(sess[i]),
                    "rank": float(rank[i]),
                    "time": times[i],
                }  # fmt: skip
            )
        out["order"] = [int(i) for i in order]
        starts: dict[int, float | None] = {}
        for i in order:
            starts.setdefault(sess[i], times[i])
        out["legend"] = [
            {"label": R.session_label(t), "colour": out["sessions"][s % len(REPLAY_SESSION_COLS)]}
            for s, t in sorted(starts.items())
        ][-6:]
        timed = sorted(t for t in times if t is not None)
        out["oldest"] = R.session_label(timed[0]) if timed else "oldest"
        out["newest"] = R.session_label(timed[-1]) if timed else "newest"
        return out

    def _heat_grid(self, shown: np.ndarray):
        """Count how many of the shown screenshots saw each cell of a grid over the atlas.

        Args:
            shown: bool per screenshot.

        Returns:
            (counts uint16 (h, w), (x0, y0, cell)).
        """
        x0, y0, x1, y1 = self.atlas_bounds()
        cell = max(x1 - x0, y1 - y0, 1.0) / HEAT_RES
        count = np.zeros((int((y1 - y0) / cell) + 2, int((x1 - x0) / cell) + 2), np.uint16)
        H, W = count.shape
        fp = self.D.get("footprints") or []
        for i in np.nonzero(shown[: len(fp)])[0]:
            q = ((np.asarray(fp[i][0], float) - [x0, y0]) / cell).astype(np.int32)
            a, b = np.maximum(q.min(axis=0), 0), np.minimum(q.max(axis=0) + 1, [W, H])
            if (b <= a).any():
                continue
            sub = np.zeros((b[1] - a[1], b[0] - a[0]), np.uint8)
            cv2.fillConvexPoly(sub, q - a, 1)  # one area at a time (overlapping polygons in one call cancel)
            count[a[1] : b[1], a[0] : b[0]] += sub
        return count, (x0, y0, cell)

    def heat_top(self) -> int:
        """Return the most times any spot was seen (over all screenshots; fixed so replay colours don't shift).

        Returns:
            The count (at least 1).
        """
        key = (self.model_version, len(self.atlas.frames) if self.atlas else 0)
        c = getattr(self, "_heat_top", None)
        if c is None or c[0] != key:
            n = len(self.atlas.frames) if self.atlas else 0
            count, _o = self._heat_grid(np.ones(n, bool))
            c = self._heat_top = (key, max(1, int(count.max()) if count.size else 1))
        return c[1]

    def heat_png(self, upto: float | None = None) -> tuple[bytes, list[float]] | None:
        """Make the "times seen" picture: each spot coloured by how many screenshots saw it, see-through elsewhere.

        Args:
            upto: Only screenshots revealed before this replay step (None: all).

        Returns:
            (PNG bytes, [x0, y0, x1, y1] it covers in atlas units), or None without screenshots.
        """
        if not self.atlas or not self.atlas.frames:
            return None
        n = len(self.atlas.frames)
        shown = np.ones(n, bool)
        plan = getattr(self, "_plan", None)
        if upto is not None and plan is not None and len(plan.step_of) == n:
            shown = np.asarray(plan.step_of) < upto
        count, (x0, y0, cell) = self._heat_grid(shown)
        top = self.heat_top()
        cmap = COLOUR_SPREADS.get(self.ui_settings()["style"].get("colour_spread"), cv2.COLORMAP_PLASMA)
        ramp = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(-1, 1), cmap)[:, 0]
        idx = np.clip((count.astype(np.float32) - 1) / max(1, top - 1) * 255, 0, 255).astype(np.uint8)
        alpha = ((count > 0) * 255).astype(np.uint8)
        ok, buf = cv2.imencode(".png", np.dstack([ramp[idx], alpha]))
        H, W = count.shape
        return (buf.tobytes(), [x0, y0, x0 + W * cell, y0 + H * cell]) if ok else None

    # ------------------------------------------------------------------ the replay
    @atlas_edit
    def replay_open(self) -> dict:
        """Open the replay: work out its plan; the map's tiles then carry each item's step.

        Returns:
            replay_payload().

        Raises:
            ValueError: With no screenshots.
        """
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots to replay")
        self._replay_on = True
        self._replan()
        p = self._plan
        st = self.replay_settings()
        self.events.log(f"timelapse: {p.n_steps} steps ({st['type']}, {st['per_step']} per step, reveal by "
                        f"{st['reveal']}) over {len(self.atlas.frames)} screenshots")  # fmt: skip
        return self.replay_payload()

    def replay_close(self) -> None:
        """Close the replay (the map shows everything again: the tab goes back to the plain tiles)."""
        if getattr(self, "_replay_on", False):
            self._replay_on = False
            self._plan = None
            self._replay_steps = None
            self._vector_steps = None
            self._scene3d_steps = None

    @atlas_edit
    def set_replay_settings(self, changes: dict) -> dict:
        """Change replay settings; the plan is worked out again when it depends on them.

        Args:
            changes: Any of the REPLAY_DEFAULTS keys.

        Returns:
            replay_payload() when the replay is open, else the settings.
        """
        clean = {k: v for k, v in changes.items() if k in REPLAY_DEFAULTS}
        self.settings.setdefault("replay", {}).update(clean)
        self.save_settings()
        if getattr(self, "_replay_on", False) and {"type", "per_step", "reveal"} & set(clean):
            self._replan()
        return self.replay_payload() if getattr(self, "_replay_on", False) else {"settings": self.replay_settings()}

    def _replan(self) -> None:
        """Work out the plan and the step of every map, icon and landmark."""
        st = self.replay_settings()
        frames = self.atlas.frames
        fp = self.D.get("footprints") or []
        plan = R.make_plan(frames, fp, st["type"], st["per_step"], st["reveal"], self.atlas_bounds())
        late = max(0, plan.n_steps - 1)

        def steps(items, pts):
            """Steps of maps / icons: where the sweep reaches them, else when the first screenshot whose area holds
            them comes in (with the ground under them). By the screenshots that detected them, 3081 of 13697 map
            nodes of the crawl atlas came in long after their ground (a dim map node is often found only later)."""
            pts = np.asarray(pts, float).reshape(-1, 2)
            if plan.sweep is not None:
                return plan.steps_at(pts)
            s = R.point_steps(pts, fp, plan.step_of, default=-1)
            miss = np.nonzero(s < 0)[0]  # outside every screenshot's area: by the screenshots that saw it
            if len(miss):
                by = R.item_steps([items[i].get("frames", []) for i in miss], frames, plan.step_of, default=late)
                s[miss] = by
            return s

        V = self.V
        node_pts = self.D.get("node_pts", np.zeros((0, 2)))
        icon_pts = np.array([[i["x"], i["y"]] for i in V["icons"]], float).reshape(-1, 2)
        lm_pts = np.array([[lm["x"], lm["y"]] for lm in V["landmarks"]], float).reshape(-1, 2)
        self._replay_steps = {
            "node": steps(V["nodes"], node_pts) if V["nodes"] else np.zeros(0),
            "icon": steps(V["icons"], icon_pts) if V["icons"] else np.zeros(0),
            "landmark": plan.steps_at(lm_pts) if plan.sweep is not None
            else R.point_steps(lm_pts, fp, plan.step_of, default=late),
        }  # fmt: skip
        self._plan = plan
        self._fog = None
        # the timelapse tab's tiles carry this token (other tabs' plain tiles aren't made again: user)
        self.replay_token = getattr(self, "replay_token", 0) + 1

    def replay_steps(self) -> dict | None:
        """Return each item's step while the replay is open (the vector tiles carry them).

        Returns:
            {"node", "icon", "landmark": arrays}, or None.
        """
        return self._replay_steps if getattr(self, "_replay_on", False) else None

    def replay_payload(self) -> dict:
        """Return what the page's replay player needs.

        Returns:
            {"settings", "n_steps", "kind", "area" (reveal by area), "step_of" (per screenshot), "ticks",
            "step_time" (labels), "step_session", "real", "frame" (sweep frame) and "step_key" (grow camera),
            "maps_at" (maps revealed by each step, cumulative), "bounds"}.
        """
        plan = self._plan
        st = self.replay_settings()
        if plan is None:
            return {"settings": st}
        n = plan.n_steps
        first: dict[int, int] = {}
        for i in plan.order:
            first.setdefault(min(n - 1, int(plan.step_of[i])), plan.session_of[i])
        step_session, last = [], 0
        for s in range(n):
            last = first.get(s, last)
            step_session.append(int(last))
        alive = np.array([nd["status"] != "removed" for nd in self.V["nodes"]], bool)
        ns = np.asarray(self._replay_steps["node"], float)
        maps_at = []
        if len(ns):
            hist = (
                np.bincount(np.clip(np.floor(ns[alive]).astype(int), 0, n - 1), minlength=n)
                if alive.any()
                else np.zeros(n)
            )
            maps_at = np.cumsum(hist).astype(int).tolist()
        real = R.real_span(plan.times)
        took = ""
        if real > 0:
            h, m = divmod(int(real // 60), 60)
            took = f"{h} h {m} min" if h else (f"{m} min" if m else f"{int(real)} s")
        return {
            "settings": st,
            "token": getattr(self, "replay_token", 0),
            "n_steps": n,
            "kind": plan.kind,
            "area": plan.sweep is not None,
            "step_of": [float(v) for v in plan.step_of],
            "ticks": [int(t) for t in plan.ticks],
            "step_time": [R.session_label(t) if t is not None else "" for t in plan.step_time],
            "step_session": step_session,
            "real": took,
            "real_seconds": real,
            "frame": None
            if plan.frame is None
            else {
                "start": [float(v) for v in plan.frame[0]],
                "right": float(plan.frame[1]),
                "top": float(plan.frame[2]),
                "span": float(plan.frame[3]),
            },  # fmt: skip
            "step_key": None if plan.step_key is None else [float(v) for v in plan.step_key],
            "maps_at": maps_at,
            "bounds": list(self.atlas_bounds()),
        }

    def replay_fog(self) -> dict:
        """Return the fog field: for each cell of a grid over the atlas, the replay step its ground is revealed at.

        The page draws the fog from it every frame (hidden while the replay is before that step, fading in over a soft
        edge when revealing by area), so the sweep moves smoothly; fog bands of polygons snapped in steps (user).

        Returns:
            {"field": {"w", "h", "top" (the step a value of 65534 means), "data" (base64 little-endian uint16 per cell,
            row by row; 65535 = no ground there), "corners" ([lng, lat] of the grid's top left, top right, bottom
            right, bottom left)}} or {"field": None} without a plan.
        """
        plan = getattr(self, "_plan", None)
        if plan is None or self.grid is None:
            return {"field": None}
        if getattr(self, "_fog", None) is not None:
            return self._fog
        n = max(1, plan.n_steps)
        x0, y0, x1, y1 = self.atlas_bounds()
        cell = max(x1 - x0, y1 - y0, 1.0) / REPLAY_FOG_RES
        W, H = int(math.ceil((x1 - x0) / cell)) + 1, int(math.ceil((y1 - y0) / cell)) + 1
        if plan.sweep is not None:
            g, (gx, gy, gc), top = plan.sweep.grid, plan.sweep.origin, plan.sweep.top
            A = np.array([[cell / gc, 0, (x0 - gx) / gc], [0, cell / gc, (y0 - gy) / gc]], np.float32)
            key = cv2.warpAffine(g, A, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=float(top))
            steps = key.astype(np.float64) / max(float(top), 1e-9) * n
            ground = np.ones((H, W), bool)
            fp = self.D.get("footprints") or []
            if fp:  # only where screenshots show ground
                ground[:] = False
                for poly, _bb in fp:
                    m = np.zeros((H, W), np.uint8)
                    cv2.fillConvexPoly(m, ((np.asarray(poly, float) - [x0, y0]) / cell).round().astype(np.int32), 1)
                    ground |= m > 0
        else:
            fp = self.D.get("footprints") or []
            steps = np.full((H, W), np.inf)
            for i, (poly, _bb) in enumerate(fp):
                m = np.zeros((H, W), np.uint8)
                cv2.fillConvexPoly(m, ((np.asarray(poly, float) - [x0, y0]) / cell).round().astype(np.int32), 1)
                np.minimum(steps, np.where(m > 0, float(plan.step_of[i]), np.inf), out=steps)
            ground = np.isfinite(steps)
        enc = np.where(ground, np.clip(np.nan_to_num(steps, posinf=n) / n * 65534, 0, 65534), 65535).astype("<u2")
        corners = [self.grid.lnglat(x0 + cx * cell, y0 + cy * cell) for cx, cy in ((0, 0), (W, 0), (W, H), (0, H))]
        fog = {
            "field": {"w": W, "h": H, "top": n, "data": base64.b64encode(enc.tobytes()).decode(), "corners": corners}
        }
        with self._lock:  # kept only while its plan is still the replay's (a replan or atlas switch meanwhile: not)
            if getattr(self, "_plan", None) is plan:
                self._fog = fog
        return fog
