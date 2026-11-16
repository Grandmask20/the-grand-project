"""viewer.replay_panel: the replay / timelapse player and "Colour by when taken" (a mixin; see viewer/app.py).

A tab at the bottom right of the map ("Timelapse") folds out a player (user's mock-up; like a demo player): restart,
step back, play / pause, step forward, end; the replay type; a timeline with a tick where each batch of screenshots
starts (coloured by session) that can be clicked or dragged; and settings (length, speed, screenshots per step,
camera, export to GIF).

While the panel is open the map shows only what was revealed so far: the ground of the revealed screenshots (the
newest fading in), and the map nodes, paths, icons and landmarks they saw (viewer.replay works out when each
appears). The usual extras (bookmarks, Find rings, selection, legend) are left out so a GIF shows just the atlas.
"""

from __future__ import annotations

import math
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image

from . import replay as R
from .constants import (
    REPLAY_CAMERA_EASE,
    REPLAY_CAMERAS,
    REPLAY_DEFAULTS,
    REPLAY_FOLLOW_SPAN,
    REPLAY_GIF_FPS,
    REPLAY_GIF_MAX_FRAMES,
    REPLAY_SESSION_COLS,
    REPLAY_SPEEDS,
    REPLAY_TICK_MS,
    REPLAY_TINT_ALPHA,
    REPLAY_TYPES,
)
from .helpers import LOG, bgr_hex, put_text
from .settings import save_settings

PANEL_BG, PANEL_FG, PANEL_GOLD, PANEL_DIM = "#17191d", "#e6e2d6", "#c9a45c", "#8a8576"


class ReplayMixin:
    """Viewer mixin for the replay / timelapse panel and colouring screenshots by when they were taken."""

    # ------------------------------------------------------------------ state
    def replay_active(self) -> bool:
        """Whether the replay panel is open (the map then shows only what was revealed so far).

        Returns:
            True while replaying.
        """
        return getattr(self, "rp", None) is not None

    def _rp_key(self):
        """What the reveal masks depend on: the plan and the number of steps shown (None when not replaying).

        Returns:
            A hashable key for the viewer's mask caches, or None.
        """
        rp = getattr(self, "rp", None)
        return None if rp is None else (id(rp["plan"]), math.ceil(rp["pos"] - 1e-9))

    def _rp_settings(self) -> dict:
        """The replay settings: REPLAY_DEFAULTS overlaid with the saved ones.

        Returns:
            Dict (type, camera, length, speed, per_step, gif_width).
        """
        return {**REPLAY_DEFAULTS, **self.settings.get("replay", {})}

    def _rp_set(self, **kw):
        """Change and save replay settings.

        Args:
            **kw: Setting names (see _rp_settings) and their values.
        """
        self.settings.setdefault("replay", {}).update(kw)
        save_settings(self.settings)

    # ------------------------------------------------------------------ the panel
    def _build_replay_panel(self):
        """Make the "Timelapse" tab at the bottom of the map and its fold-out player (hidden until opened)."""
        font = ("TkDefaultFont", 9)
        self._rp_tab = tk.Label(
            self.root,
            text="▲  Timelapse",
            bg=PANEL_BG,
            fg=PANEL_GOLD,
            font=("TkDefaultFont", 9, "bold"),
            padx=14,
            pady=3,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=PANEL_GOLD,
        )
        self._rp_tab.bind("<Button-1>", lambda _e: self.toggle_replay())
        # bottom right: the colour legend runs along the bottom left and middle of the map
        self._rp_tab.place(in_=self.canvas, relx=1.0, rely=1.0, x=-14, anchor="se")
        p = self._rp_panel = tk.Frame(self.root, bg=PANEL_BG, highlightthickness=1, highlightbackground=PANEL_GOLD)

        def button(parent, text, cmd, width=3):
            """A flat player button."""
            b = tk.Label(parent, text=text, width=width, bg="#262930", fg=PANEL_FG, font=("TkDefaultFont", 11))
            b.configure(cursor="hand2", padx=4, pady=1, highlightthickness=1, highlightbackground="#3a3d45")
            b.bind("<Button-1>", lambda _e: cmd())
            return b

        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=8, pady=(6, 2))
        button(row, "⏮", lambda: self._rp_seek(0.0)).pack(side="left", padx=1)
        button(row, "◀◀", lambda: self._rp_step(-1)).pack(side="left", padx=1)
        self._rp_play_btn = button(row, "▶", self._rp_toggle_play, width=4)
        self._rp_play_btn.pack(side="left", padx=1)
        button(row, "▶▶", lambda: self._rp_step(1)).pack(side="left", padx=1)
        button(row, "⏭", lambda: self._rp_seek(float("inf"))).pack(side="left", padx=1)
        st = self._rp_settings()
        self._rp_gear = button(row, "⚙", self._rp_toggle_settings)
        self._rp_gear.pack(side="right", padx=1)
        self._rp_type = tk.StringVar(value=st["type"])
        cb = ttk.Combobox(row, textvariable=self._rp_type, values=REPLAY_TYPES, width=12, state="readonly")
        cb.pack(side="right", padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: (self._rp_set(type=self._rp_type.get()), self._rp_replan()))
        tk.Label(row, text="replay type", bg=PANEL_BG, fg=PANEL_DIM, font=font).pack(side="right")
        self._rp_info = tk.StringVar(value="")
        tk.Label(row, textvariable=self._rp_info, bg=PANEL_BG, fg=PANEL_FG, font=font).pack(side="left", padx=12)

        self._rp_line = tk.Canvas(p, height=30, bg=PANEL_BG, highlightthickness=0, cursor="hand2")
        self._rp_line.pack(fill="x", padx=10, pady=(2, 6))
        for seq in ("<Button-1>", "<B1-Motion>"):
            self._rp_line.bind(seq, self._rp_click_line)
        self._rp_line.bind("<Configure>", lambda _e: self._rp_draw_line())

        s = self._rp_settings_row = tk.Frame(p, bg=PANEL_BG)  # shown by the gear button
        self._rp_vars = {}

        def labelled(text, widget):
            """Pack a small label and its control into the settings row."""
            tk.Label(s, text=text, bg=PANEL_BG, fg=PANEL_DIM, font=font).pack(side="left", padx=(8, 3))
            widget.pack(side="left")

        v = self._rp_vars["length"] = tk.StringVar(value=f"{st['length']:g}")
        sp = ttk.Spinbox(s, from_=3, to=600, increment=5, width=5, textvariable=v, command=self._rp_read_settings)
        sp.bind("<FocusOut>", lambda _e: self._rp_read_settings())
        sp.bind("<Return>", lambda _e: self._rp_read_settings())
        labelled("length (s)", sp)
        v = self._rp_vars["speed"] = tk.StringVar(value=f"{st['speed']:g}x")
        cb = ttk.Combobox(s, textvariable=v, values=[f"{x:g}x" for x in REPLAY_SPEEDS], width=5, state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rp_read_settings())
        labelled("speed", cb)
        v = self._rp_vars["per_step"] = tk.StringVar(value=str(st["per_step"]))
        sp = ttk.Spinbox(s, from_=1, to=50, width=4, textvariable=v, command=self._rp_read_settings)
        sp.bind("<FocusOut>", lambda _e: self._rp_read_settings())
        sp.bind("<Return>", lambda _e: self._rp_read_settings())
        labelled("screenshots per step", sp)
        v = self._rp_vars["camera"] = tk.StringVar(value=st["camera"])
        cb = ttk.Combobox(s, textvariable=v, values=REPLAY_CAMERAS, width=14, state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rp_read_settings())
        labelled("camera", cb)
        b = button(s, "Export GIF…", self._rp_export_gif, width=11)
        b.configure(font=font)
        b.pack(side="right", padx=(10, 2))

    def toggle_replay(self):
        """Open the replay panel, or close it (the "Timelapse" tab)."""
        if self.replay_active():
            self.close_replay()
        else:
            self.open_replay()

    def open_replay(self):
        """Open the player: the map switches to replay mode at the end (the whole atlas), ready to play."""
        if not self.atlas or not self.atlas.frames:
            self.status.set("open an atlas with screenshots first")
            return
        self.rp = {"pos": 0.0, "playing": False, "view": (self.cx, self.cy, self.z), "exporting": False}
        self._rp_replan()
        self.rp["pos"] = float(self.rp["plan"].n_steps)
        self._rp_panel.place(in_=self.canvas, relx=0.5, rely=1.0, anchor="s", relwidth=0.86)
        self.root.update_idletasks()
        self._rp_tab.configure(text="▼  Timelapse")
        self._rp_tab.place(in_=self.canvas, relx=0.93, rely=1.0, x=0, y=-self._rp_panel.winfo_height(), anchor="se")
        self._rp_tab.lift()
        self._rp_update_ui()
        self.request_redraw()

    def close_replay(self):
        """Close the player and put the view back where it was before."""
        rp = getattr(self, "rp", None)
        if rp is None or rp["exporting"]:
            return
        self.rp = None
        self._rp_panel.place_forget()
        self._rp_tab.configure(text="▲  Timelapse")
        self._rp_tab.place(in_=self.canvas, relx=1.0, rely=1.0, x=-14, y=0, anchor="se")
        self.cx, self.cy, self.z = rp["view"]
        self.request_redraw()

    def _rp_toggle_settings(self):
        """Show or hide the settings row (the gear button)."""
        if self._rp_settings_row.winfo_ismapped():
            self._rp_settings_row.pack_forget()
        else:
            self._rp_settings_row.pack(fill="x", padx=6, pady=(0, 6))
        self.root.update_idletasks()
        if self.replay_active():
            self._rp_tab.place_configure(y=-self._rp_panel.winfo_height())

    def _rp_read_settings(self):
        """Store the settings row's values (bad numbers fall back to the old ones) and re-plan if needed."""
        st = self._rp_settings()
        try:
            length = min(600.0, max(3.0, float(self._rp_vars["length"].get())))
        except ValueError:
            length = st["length"]
        try:
            per_step = min(50, max(1, int(float(self._rp_vars["per_step"].get()))))
        except ValueError:
            per_step = st["per_step"]
        speed = float(self._rp_vars["speed"].get().rstrip("x") or 1)
        camera = self._rp_vars["camera"].get()
        self._rp_vars["length"].set(f"{length:g}")
        self._rp_vars["per_step"].set(str(per_step))
        self._rp_set(length=length, per_step=per_step, speed=speed, camera=camera)
        if self.replay_active() and per_step != st["per_step"]:
            self._rp_replan()

    # ------------------------------------------------------------------ plan
    def _rp_replan(self):
        """Work out the replay for the open atlas (type / per-step changed, or screenshots were added meanwhile).

        Keeps the same share of the replay shown. Map nodes and icons appear with the first screenshot that saw them;
        landmarks (and map nodes / icons no listed screenshot is known for) with the first one whose area holds them.
        """
        rp = getattr(self, "rp", None)
        if rp is None or not self.atlas:
            return
        st = self._rp_settings()
        old = rp.get("plan")
        share = rp["pos"] / old.n_steps if old is not None and old.n_steps else 1.0
        frames = self.atlas.frames
        plan = R.make_plan(frames, self.footprints, st["type"], st["per_step"])
        late = plan.n_steps  # not found: shown with everything at the end

        def steps(items, pts):
            """Steps of map nodes / icons: by their screenshots, else by the areas holding them."""
            s = R.item_steps([it.get("frames", []) for it in items], frames, plan.step_of, default=-1)
            miss = np.nonzero(s < 0)[0]
            if len(miss):
                s[miss] = R.point_steps(np.asarray(pts, float)[miss], self.footprints, plan.step_of, default=late)
            return s

        V = self.V
        rp["plan"] = plan
        rp["node_step"] = steps(V["nodes"], self.node_pts) if V["nodes"] else np.zeros(0, int)
        rp["icon_step"] = steps(V["icons"], [[i["x"], i["y"]] for i in V["icons"]]) if V["icons"] else np.zeros(0, int)
        lm_pts = np.array([[lm["x"], lm["y"]] for lm in V["landmarks"]], float).reshape(-1, 2)
        rp["lm_step"] = R.point_steps(lm_pts, self.footprints, plan.step_of, default=late)
        rp["polys"] = np.array([np.asarray(p, float) for p, _bb in self.footprints]).reshape(-1, 4, 2)
        rp["pos"] = share * plan.n_steps
        self._rp_draw_line()
        self._rp_update_ui()
        self.request_redraw()

    def _rp_shown(self, kind: str, i: int) -> bool:
        """Whether a map node / icon / landmark is revealed yet (always True when not replaying).

        Args:
            kind: "node", "icon" or "landmark".
            i: Its index in V["nodes"] / V["icons"] / V["landmarks"].

        Returns:
            True when it is drawn.
        """
        rp = getattr(self, "rp", None)
        if rp is None:
            return True
        arr = rp[{"node": "node_step", "icon": "icon_step", "landmark": "lm_step"}[kind]]
        return i >= len(arr) or arr[i] < rp["pos"]

    # ------------------------------------------------------------------ playback
    def _rp_toggle_play(self):
        """Play / pause; playing from the end starts again from the beginning."""
        rp = self.rp
        if rp is None or rp["exporting"]:
            return
        if not rp["playing"] and rp["pos"] >= rp["plan"].n_steps:
            rp["pos"] = 0.0
            self._rp_camera(1.0)
        rp["playing"] = not rp["playing"]
        rp["last"] = time.perf_counter()
        self._rp_update_ui()
        if rp["playing"]:
            self._rp_tick()

    def _rp_rate(self) -> float:
        """Steps per second: the whole replay takes `length` seconds at 1x (user: set the length, get the speed).

        Returns:
            Steps per second.
        """
        st = self._rp_settings()
        return self.rp["plan"].n_steps / max(1.0, st["length"]) * st["speed"]

    def _rp_tick(self):
        """One playback frame (a Tk `after` timer while playing): move on, move the camera, redraw."""
        rp = getattr(self, "rp", None)
        if rp is None or not rp["playing"] or rp["exporting"]:
            return
        now = time.perf_counter()
        rp["pos"] = min(float(rp["plan"].n_steps), rp["pos"] + (now - rp["last"]) * self._rp_rate())
        rp["last"] = now
        if rp["pos"] >= rp["plan"].n_steps:
            rp["playing"] = False
        self._rp_camera(REPLAY_CAMERA_EASE)
        self._rp_update_ui()
        self._redraw()
        if rp["playing"]:
            self.root.after(REPLAY_TICK_MS, self._rp_tick)

    def _rp_seek(self, pos: float):
        """Jump to a place in the replay (the camera jumps too).

        Args:
            pos: Steps shown (clamped to 0..number of steps).
        """
        rp = getattr(self, "rp", None)
        if rp is None or rp["exporting"]:
            return
        rp["pos"] = float(min(max(pos, 0.0), rp["plan"].n_steps))
        self._rp_camera(1.0)
        self._rp_update_ui()
        self._redraw()  # now, so dragging along the timeline follows the mouse

    def _rp_step(self, d: int):
        """Go one step back or forward (pausing).

        Args:
            d: -1 or +1.
        """
        rp = getattr(self, "rp", None)
        if rp is None:
            return
        rp["playing"] = False
        pos = rp["pos"]
        self._rp_seek(math.ceil(pos - 1e-9) - 1 if d < 0 else math.floor(pos + 1e-9) + 1)

    # ------------------------------------------------------------------ camera
    def _rp_box(self, which: str):
        """Atlas box around the revealed screenshots ("revealed") or those of the step coming in ("newest").

        Args:
            which: "revealed" or "newest".

        Returns:
            (x0, y0, x1, y1), or None when there are none.
        """
        rp = self.rp
        s = rp["plan"].step_of
        cur = max(0, math.ceil(rp["pos"] - 1e-9) - 1)
        sel = s < max(rp["pos"], 1e-9) if which == "revealed" else s == cur
        P = rp["polys"][sel] if len(rp["polys"]) else rp["polys"]
        if not len(P):
            P = rp["polys"][s == 0]
        if not len(P):
            return None
        return (*P.reshape(-1, 2).min(axis=0), *P.reshape(-1, 2).max(axis=0))

    def _rp_camera(self, ease: float, size: tuple[int, int] | None = None):
        """Move the view toward where the camera setting wants it.

        "whole atlas": the end view (the whole atlas fitted) from the start. "grow with atlas": fitted to what was
        revealed so far. "follow newest": on the screenshots coming in, REPLAY_FOLLOW_SPAN screenshots across.

        Args:
            ease: Share of the way to move (1 = jump there).
            size: (w, h) of the frame (default: the map canvas).
        """
        w, h = size or self.canvas_size()
        cam = self._rp_settings()["camera"]
        if cam == "follow newest":
            box = self._rp_box("newest")
            if box is None:
                return
            tx, ty = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            tz = w / (REPLAY_FOLLOW_SPAN * 1920.0)
        else:
            box = self._rp_box("revealed") if cam == "grow with atlas" else self.bounds()
            if box is None:
                return
            x0, y0, x1, y1 = box
            if cam == "grow with atlas":
                pad = 0.08 * max(x1 - x0, y1 - y0)
                x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
            tx, ty = (x0 + x1) / 2, (y0 + y1) / 2
            tz = max(0.02, min(w / max(1.0, x1 - x0), h / max(1.0, y1 - y0)) * 0.96)
        self.cx += (tx - self.cx) * ease
        self.cy += (ty - self.cy) * ease
        self.z = math.exp(math.log(self.z) + (math.log(tz) - math.log(self.z)) * ease)

    # ------------------------------------------------------------------ timeline and info
    def _rp_click_line(self, e):
        """Seek by clicking or dragging on the timeline.

        Args:
            e: The Tk mouse event on the timeline canvas.
        """
        rp = getattr(self, "rp", None)
        if rp is None:
            return
        rp["playing"] = False
        x0, x1 = 8, max(9, self._rp_line.winfo_width() - 8)
        self._rp_seek((e.x - x0) / (x1 - x0) * rp["plan"].n_steps)

    def _rp_draw_line(self):
        """Draw the timeline: a band coloured by session, a tick where each batch of screenshots starts, the head."""
        c = getattr(self, "_rp_line", None)
        rp = getattr(self, "rp", None)
        if c is None:
            return
        c.delete("all")
        if rp is None:
            return
        plan = rp["plan"]
        w = c.winfo_width()
        x0, x1 = 8, max(9, w - 8)
        n = max(1, plan.n_steps)
        first = {}  # session of each step: that of its first screenshot
        for i in plan.order:
            first.setdefault(int(plan.step_of[i]), plan.session_of[i])
        start = 0
        for s in range(1, n + 1):  # one band per run of steps in the same session
            if s == n or first.get(s) != first.get(start):
                col = bgr_hex(REPLAY_SESSION_COLS[first.get(start, 0) % len(REPLAY_SESSION_COLS)])
                c.create_rectangle(x0 + (x1 - x0) * start / n, 13, x0 + (x1 - x0) * s / n, 17, fill=col, width=0)
                start = s
        for s in plan.ticks:
            col = bgr_hex(REPLAY_SESSION_COLS[first.get(s, 0) % len(REPLAY_SESSION_COLS)])
            x = x0 + (x1 - x0) * s / n
            c.create_line(x, 6, x, 24, fill=col, width=2)
        c.create_rectangle(0, 0, 0, 0, fill=PANEL_GOLD, outline="#000000", tags="head")
        self._rp_move_head()

    def _rp_move_head(self):
        """Move the timeline's head to the current place."""
        rp = getattr(self, "rp", None)
        c = getattr(self, "_rp_line", None)
        if rp is None or c is None:
            return
        x0, x1 = 8, max(9, c.winfo_width() - 8)
        x = x0 + (x1 - x0) * rp["pos"] / max(1, rp["plan"].n_steps)
        c.coords("head", x - 4, 3, x + 4, 27)

    def _rp_counts(self) -> tuple[int, int, float | None]:
        """Screenshots and map nodes revealed so far, and when the newest revealed screenshot was taken.

        Returns:
            (screenshots, map nodes, time or None).
        """
        rp = self.rp
        plan = rp["plan"]
        shots = int(np.count_nonzero(plan.step_of < rp["pos"]))
        alive = np.array([n["status"] != "removed" for n in self.V["nodes"]], bool)
        maps = int(np.count_nonzero(alive & (rp["node_step"] < rp["pos"]))) if len(alive) else 0
        cur = math.ceil(rp["pos"] - 1e-9) - 1
        t = plan.step_time[cur] if 0 <= cur < len(plan.step_time) else None
        return shots, maps, t

    def _rp_update_ui(self):
        """Refresh the play button, the info text and the timeline head."""
        rp = getattr(self, "rp", None)
        if rp is None:
            return
        self._rp_play_btn.configure(text="❚❚" if rp["playing"] else "▶")
        shots, maps, t = self._rp_counts()
        when = f"   {R.session_label(t)}" if t is not None else ""
        self._rp_info.set(f"screenshots {shots} / {len(self.atlas.frames)}   maps {maps}{when}")
        self._rp_move_head()

    # ------------------------------------------------------------------ drawing (called by DrawingMixin._render)
    def _rp_mask_ground(self, img, w, h):
        """Keep the ground of the revealed screenshots only; the screenshots coming in fade in.

        Args:
            img: The map image after the terrain (BGR).
            w: Image width.
            h: Image height.

        Returns:
            The masked image.
        """
        rp = self.rp
        P = rp["polys"]
        if not len(P):
            return img
        s = rp["plan"].step_of
        pos = rp["pos"]
        full = math.floor(pos)
        q = ((P - [self.cx, self.cy]) * self.z + [w / 2, h / 2]).astype(np.int32)
        mask = np.zeros((h, w), np.uint8)
        # one screenshot at a time: several overlapping areas in one fillPoly cancel where they overlap (even-odd),
        # which hid the ground wherever two screenshots overlap (black squares and strips: user)
        if pos > full:
            for k in np.nonzero(s == full)[0]:
                cv2.fillConvexPoly(mask, q[k], int(255 * (pos - full)))
        for k in np.nonzero(s < full)[0]:  # over the fading ones: older ground stays whole
            cv2.fillConvexPoly(mask, q[k], 255)
        # not revealed yet = black, like the parts of the map image no screenshot gave ground (each screenshot's
        # cut-away top and HUD leave strips): a revealed screenshot's no-ground corners then blend in instead of
        # showing as black squares on grey (user)
        m = mask[..., None].astype(np.uint16)
        return ((img.astype(np.uint16) * m) // 255).astype(np.uint8)

    def _rp_overlay(self, img, w, h):
        """Outline the screenshots coming in, and write when they were taken and how many are shown (top left).

        Args:
            img: The finished map image (BGR, changed in place).
            w: Image width.
            h: Image height.
        """
        rp = self.rp
        plan = rp["plan"]
        P = rp["polys"]
        cur = math.ceil(rp["pos"] - 1e-9) - 1
        if len(P) and cur >= 0 and rp["pos"] < plan.n_steps:
            q = ((P[plan.step_of == cur] - [self.cx, self.cy]) * self.z + [w / 2, h / 2]).astype(np.int32)
            cv2.polylines(img, list(q), True, (255, 255, 255), 1, cv2.LINE_AA)
        shots, maps, t = self._rp_counts()
        sess = next((plan.session_of[i] for i in plan.order if plan.step_of[i] == cur), 0)
        col = REPLAY_SESSION_COLS[sess % len(REPLAY_SESSION_COLS)]
        cv2.rectangle(img, (8, 8), (360, 58), (16, 16, 18), -1)
        cv2.circle(img, (22, 24), 6, col, -1, cv2.LINE_AA)
        put_text(img, R.session_label(t) if t is not None else "", (36, 30), (235, 235, 235), 0.55)
        put_text(img, f"screenshots {shots} / {len(plan.order)}   maps {maps}", (16, 50), (200, 200, 200), 0.48)

    def _draw_age_tint(self, img, w, h, mode: str):
        """Tint each screenshot's area by when it was taken (user / issue #16): by session, or oldest to newest.

        Newer screenshots are drawn over older ones.

        Args:
            img: The map image after the terrain (BGR).
            w: Image width.
            h: Image height.
            mode: "by session" or "oldest to newest".

        Returns:
            The tinted image.
        """
        info = self._age_info()
        if info is None:
            return img
        order, sess, rank = info
        P = np.array([np.asarray(p, float) for p, _bb in self.footprints]).reshape(-1, 4, 2)
        if not len(P):
            return img
        q = ((P - [self.cx, self.cy]) * self.z + [w / 2, h / 2]).astype(np.int32)
        layer = img.copy()
        ramp = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(-1, 1), cv2.COLORMAP_PLASMA)[:, 0]
        for i in order:  # oldest first: newer screenshots on top
            if mode == "by session":
                col = REPLAY_SESSION_COLS[sess[i] % len(REPLAY_SESSION_COLS)]
            else:
                col = tuple(int(v) for v in ramp[int(rank[i] * 255)])
            cv2.fillPoly(layer, [q[i]], col)
        return cv2.addWeighted(layer, REPLAY_TINT_ALPHA, img, 1 - REPLAY_TINT_ALPHA, 0)

    def _age_info(self):
        """Time order, session and age rank (0 oldest .. 1 newest) of every screenshot; kept until the atlas changes.

        Returns:
            (order, session per screenshot, rank per screenshot), or None without screenshots.
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
        order, sess, rank, _times = c[1]
        return order, sess, rank

    def age_legend(self) -> list[tuple[str, tuple]]:
        """Legend entries for "Colour by when taken" by session: each session's start and colour (at most 6).

        Returns:
            [(text, BGR colour)].
        """
        info = self._age_info()
        if info is None:
            return []
        order, sess, _rank = info
        times = self._age_cache[1][3]
        starts = {}
        for i in order:
            starts.setdefault(sess[i], times[i])
        items = [
            (R.session_label(t), REPLAY_SESSION_COLS[s % len(REPLAY_SESSION_COLS)]) for s, t in sorted(starts.items())
        ]
        return items[-6:]

    # ------------------------------------------------------------------ GIF
    def _rp_export_gif(self):
        """Save the replay as an animated GIF (asks where), rendering it frame by frame without blocking the window.

        Uses the replay's length and speed, REPLAY_GIF_FPS frames a second (at most REPLAY_GIF_MAX_FRAMES), and the
        map view's shape at the GIF width setting. The last frame stays up for 2 s.
        """
        rp = getattr(self, "rp", None)
        if rp is None or rp["exporting"]:
            return
        stem = Path(self.path).parent.name if self.path else "atlas"
        out = filedialog.asksaveasfilename(
            title="Save the timelapse as",
            defaultextension=".gif",
            filetypes=[("GIF animation", "*.gif")],
            initialdir=str(Path.home()),
            initialfile=f"{stem}_timelapse.gif",
        )
        if not out:
            return
        st = self._rp_settings()
        cw, ch = self.canvas_size()
        W = int(st["gif_width"])
        H = max(2, int(round(W * ch / max(1, cw) / 2)) * 2)
        n = int(min(REPLAY_GIF_MAX_FRAMES, max(2, round(st["length"] / st["speed"] * REPLAY_GIF_FPS))))
        saved = (self.cx, self.cy, self.z, rp["pos"], rp["playing"])
        rp.update(exporting=True, playing=False)
        frames: list = []
        LOG.info(f"replay: exporting {n} frames at {W}x{H} to {out}")

        def chunk(start=0):
            """Render a few frames, then let the window breathe."""
            for k in range(start, min(n, start + 4)):
                rp["pos"] = rp["plan"].n_steps * k / (n - 1)
                self._rp_camera(1.0 if k == 0 else REPLAY_CAMERA_EASE, (W, H))
                self._frame_size = (W, H)
                try:
                    img = self.render(W, H)
                finally:
                    self._frame_size = None
                pic = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                frames.append(pic.quantize(256, method=Image.Quantize.FASTOCTREE))
            self._rp_info.set(f"exporting GIF: frame {len(frames)} / {n}")
            if len(frames) < n:
                self.root.after(1, chunk, len(frames))
            else:
                finish()

        def finish():
            """Put the view back and write the file on a background thread."""
            self.cx, self.cy, self.z, rp["pos"], _playing = saved
            rp["exporting"] = False
            self._rp_update_ui()
            self.request_redraw()
            ms = int(1000 / REPLAY_GIF_FPS)

            def write():
                """Write the GIF (background thread)."""
                try:
                    frames[0].save(
                        out,
                        save_all=True,
                        append_images=frames[1:],
                        duration=[ms] * (len(frames) - 1) + [2000],
                        loop=0,
                        disposal=1,
                    )
                    mb = Path(out).stat().st_size / 1e6
                    self._q.put(("status", f"timelapse saved: {out} ({len(frames)} frames, {mb:.1f} MB)"))
                except Exception as e:
                    LOG.exception("GIF export failed")
                    self._q.put(("status", f"could not save the GIF: {e}"))

            self.status.set("writing the GIF ...")
            threading.Thread(target=write, daemon=True).start()

        chunk()
