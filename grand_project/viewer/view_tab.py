"""viewer.view_tab: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import paths as rc_paths

from .constants import NODE_COL, PATH_MULTI, PATH_SINGLE, STYLE_DEFAULT
from .helpers import bgr_hex, draw_map, draw_paths, hex_bgr, icon_thumb
from .settings import save_settings


class ViewTabMixin:
    # ------------------------------------------------------------------ layer toggles (under the tabs)
    LAYER_GRID = (
        ("Terrain", "Terrain"),
        ("Paths", "Paths"),
        ("Nodes", "Maps"),
        ("Icons", "Icons"),
        ("Landmarks", "Landmarks"),
        ("Bookmarks", "Bookmarks"),
        ("Labels", "Labels"),
        ("Doubtful", "Doubtful"),
        ("Removed", "Removed"),
        ("Recent additions", "New"),
        ("City & stronghold biomes", "City biomes"),
    )

    # ------------------------------------------------------------------ View tab: styles and overlays
    def style(self) -> dict:
        st = self.settings.setdefault("style", {})
        return {**STYLE_DEFAULT, **st}

    def set_style(self, **kw):
        self.settings.setdefault("style", {}).update(kw)
        save_settings(self.settings)
        self.request_redraw()

    def _build_style_ui(self, vw):
        """View tab (user's mockup): Paths and Maps sections with a live preview each; colour squares are buttons"""
        from tkinter import colorchooser

        st = self.style()
        PW, PH = 300, 46

        def preview_paths():
            S_ = self.style()
            im = np.full((PH, PW, 3), (34, 38, 42), np.uint8)
            th = int(S_["path_width"]) or 2
            draw_paths(
                im,
                [np.array([[14, PH * 0.62], [PW * 0.45, PH * 0.3], [PW - 14, PH * 0.55]])],
                hex_bgr(S_["path_col"], PATH_MULTI),
                th,
                S_["path_style"],
            )
            return im

        def preview_maps():
            S_ = self.style()
            im = np.full((PH, PW, 3), (34, 38, 42), np.uint8)
            r = 8 * float(S_["map_size"])
            col = hex_bgr(S_["map_col"], NODE_COL["confirmed"])
            draw_map(im, (PW // 2, PH // 2), r, col, 2, S_["map_style"], self._map_pic())  # one map, centred
            return im

        previews = []

        def refresh():
            for lab, fn in previews:
                ph = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(fn(), cv2.COLOR_BGR2RGB)))
                lab.configure(image=ph)
                lab.image = ph

        def changed(**kw):
            self.set_style(**kw)
            refresh()

        def swatch(parent, key, default, text):
            box = ttk.Frame(parent)
            box.pack(side="left", padx=(0, 12))
            sw = tk.Label(
                box,
                width=3,
                height=1,
                relief="raised",
                borderwidth=2,
                cursor="hand2",
                background=self.style()[key] or bgr_hex(default),
            )
            sw.pack(side="left", padx=(0, 4))
            ttk.Label(box, text=text).pack(side="left")

            def pick(_e=None):
                got = colorchooser.askcolor(color=self.style()[key] or bgr_hex(default), title=text)[1]
                if got:
                    sw.configure(background=got)
                    changed(**{key: got})

            sw.bind("<Button-1>", pick)
            return sw, key, default

        def section(title):
            ttk.Separator(vw).pack(fill="x", pady=(10, 4))
            ttk.Label(vw, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
            lab = tk.Label(vw, borderwidth=1, relief="sunken")
            lab.pack(anchor="w", pady=(2, 4))
            return lab

        # --- Paths
        previews.append((section("Paths"), preview_paths))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        sw_list = [swatch(row, "path_col", PATH_MULTI, "colour"), swatch(row, "path_col1", PATH_SINGLE, "1 shot")]
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        self._st_width = tk.IntVar(value=int(st["path_width"]))
        ttk.Spinbox(
            row,
            from_=0,
            to=8,
            width=3,
            textvariable=self._st_width,
            command=lambda: changed(path_width=int(self._st_width.get())),
        ).pack(side="left")
        ttk.Label(row, text="width (0 = auto)").pack(side="left", padx=(4, 12))
        self._st_path = tk.StringVar(value=st["path_style"])
        cb = ttk.Combobox(
            row, textvariable=self._st_path, values=("solid", "dashed", "dotted"), width=8, state="readonly"
        )
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: changed(path_style=self._st_path.get()))
        ttk.Label(row, text="style").pack(side="left", padx=4)
        ttk.Checkbutton(
            vw, text="only what 2+ screenshots show", variable=self.multi_only, command=self.request_redraw
        ).pack(anchor="w", pady=(2, 0))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="drawn by at least").pack(side="left")
        self._st_freq = tk.DoubleVar(value=float(st["path_freq"]) * 100)
        freq_lab = ttk.Label(row, text=f"{self._st_freq.get():.0f}%", width=5)

        def on_freq(v):
            freq_lab.configure(text=f"{float(v):.0f}%")
            changed(path_freq=round(float(v) / 100, 2))

        ttk.Scale(row, from_=0, to=100, variable=self._st_freq, length=110, command=on_freq).pack(side="left", padx=4)
        freq_lab.pack(side="left")
        ttk.Label(vw, text="   of the screenshots that show both maps", foreground="#555").pack(anchor="w")

        # --- Maps
        previews.append((section("Maps"), preview_maps))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        sw_list.append(swatch(row, "map_col", NODE_COL["confirmed"], "colour"))
        ttk.Label(row, text="size").pack(side="left")
        self._st_size = tk.DoubleVar(value=float(st["map_size"]))
        ttk.Scale(
            row,
            from_=0.5,
            to=2.5,
            variable=self._st_size,
            length=120,
            command=lambda v: changed(map_size=round(float(v), 2)),
        ).pack(side="left", padx=4)
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        self._st_mstyle = tk.StringVar(value=st["map_style"])
        cb2 = ttk.Combobox(
            row,
            textvariable=self._st_mstyle,
            values=("circles", "squares", "map icons", "hidden"),
            width=10,
            state="readonly",
        )
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda e: changed(map_style=self._st_mstyle.get()))
        ttk.Label(row, text="style").pack(side="left", padx=4)

        # --- pictures
        ttk.Separator(vw).pack(fill="x", pady=(10, 4))
        ttk.Label(vw, text="Pictures on the map (zoomed in)", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self._st_ov = {}
        for key, text in (("ov_badges", "badge pictures (the icons ticked in Find)"), ("ov_towers", "tower picture")):
            v = self._st_ov[key] = tk.BooleanVar(value=bool(st[key]))
            ttk.Checkbutton(
                vw, text=text, variable=v, command=lambda k=key: changed(**{k: bool(self._st_ov[k].get())})
            ).pack(anchor="w")

        def reset():
            self.settings["style"] = {}
            save_settings(self.settings)
            d = self.style()
            self._st_path.set(d["path_style"])
            self._st_width.set(d["path_width"])
            self._st_size.set(d["map_size"])
            self._st_mstyle.set(d["map_style"])
            self._st_freq.set(d["path_freq"] * 100)
            for k, v in self._st_ov.items():
                v.set(d[k])
            for sw, _key, default in sw_list:
                sw.configure(background=bgr_hex(default))
            self.request_redraw()
            refresh()

        ttk.Button(vw, text="Reset styles", command=reset).pack(anchor="w", pady=(10, 0))
        self.root.after(200, refresh)

    def _layer_icon(self, layer: str, size: int = 20):
        """small picture for a layer toggle (PIL RGBA)"""
        from PIL import ImageDraw

        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if layer == "Terrain":
            t = getattr(self, "_terrain", None)
            if t is not None and t[0] is not None and t[0].size:
                c = t[0]
                h, w = c.shape[:2]
                crop = c[
                    h // 2 - min(h, w) // 8 : h // 2 + min(h, w) // 8, w // 2 - min(h, w) // 8 : w // 2 + min(h, w) // 8
                ]
                if crop.size:
                    return Image.fromarray(
                        cv2.cvtColor(cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                    ).convert("RGBA")
            rng = np.random.default_rng(3)
            base = np.array([70, 95, 55], np.float32) + rng.normal(0, 18, (size, size, 3))
            return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")
        if layer == "Paths":
            d.line((2, size - 4, size - 3, 3), fill=(80, 200, 255, 255), width=3)
            return im
        if layer == "Nodes":
            f = rc_paths.ref("map_node_icon.webp")
            if f.exists():
                return Image.open(f).convert("RGBA").resize((size, size), Image.LANCZOS)
        if layer == "Landmarks":
            return icon_thumb("LostTower", size)
        if layer == "Icons":
            return icon_thumb("MapBoss", size)
        if layer == "Bookmarks":
            c, r1, r2 = size / 2, size / 2 - 1, size / 5
            pts = [
                (
                    c + (r1 if k % 2 == 0 else r2) * math.sin(math.pi * k / 5),
                    c - (r1 if k % 2 == 0 else r2) * math.cos(math.pi * k / 5),
                )
                for k in range(10)
            ]
            d.polygon(pts, fill=(255, 205, 40, 255), outline=(150, 110, 0, 255))
            return im
        if layer == "Labels":
            d.rounded_rectangle(
                (1, 5, size - 2, size - 5), radius=3, fill=(245, 245, 245, 255), outline=(90, 90, 90, 255)
            )
            d.ellipse((3, size / 2 - 2, 7, size / 2 + 2), fill=(90, 90, 90, 255))
            d.line((9, size / 2, size - 5, size / 2), fill=(90, 90, 90, 255), width=2)
            return im
        if layer == "Doubtful":
            d.ellipse((1, 1, size - 2, size - 2), fill=(150, 150, 150, 255))
            d.text((size / 2 - 3, 2), "?", fill=(255, 255, 255, 255))
            return im
        if layer == "Removed":
            d.ellipse((2, 2, size - 3, size - 3), outline=(220, 40, 40, 255), width=3)
            d.line((5, 5, size - 6, size - 6), fill=(220, 40, 40, 255), width=3)
            return im
        if layer == "Recent additions":
            d.rounded_rectangle((0, 4, size - 1, size - 5), radius=3, fill=(255, 210, 0, 255))
            try:
                from PIL import ImageFont

                fnt = ImageFont.load_default(size=8)
            except Exception:
                fnt = None
            tw = d.textlength("NEW", font=fnt) if fnt else 18
            d.text(((size - tw) / 2, 5 if fnt else 5), "NEW", fill=(40, 30, 0, 255), font=fnt)
            return im
        if layer == "City & stronghold biomes":
            return icon_thumb("MapBossSpecial", size)
        d.ellipse((4, 4, size - 4, size - 4), fill=(200, 200, 200, 255))
        return im

    def _build_layer_grid(self):
        """the map layers as picture toggles, 4 per row, under the tabs (visible in every tab)"""
        from PIL import ImageTk

        g = self.layer_grid
        for w in g.winfo_children():
            w.destroy()
        ttk.Label(g, text="Show on the map", font=("TkDefaultFont", 8, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        self._layer_photos = []
        for k, (layer, label) in enumerate(self.LAYER_GRID):
            ph = ImageTk.PhotoImage(self._layer_icon(layer))
            self._layer_photos.append(ph)
            b = tk.Checkbutton(
                g,
                text=label,
                image=ph,
                compound="top",
                variable=self.layers[layer],
                indicatoron=False,
                command=self.request_redraw,
                width=72,
                font=("TkDefaultFont", 8),
                selectcolor="#cfe3ff",
                relief="raised",
                offrelief="flat",
                bd=1,
                background="#ececec",
                activebackground="#dde8f7",
                foreground="black",
                activeforeground="black",
            )
            b.grid(row=1 + k // 4, column=k % 4, padx=1, pady=1, sticky="ew")
        for c in range(4):
            g.columnconfigure(c, weight=1)
