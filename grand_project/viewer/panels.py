"""viewer.panels: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None

from .constants import PLACE_ICON, POTENTIAL_TYPES
from .helpers import icon_aliases, icon_label, icon_thumb


class PanelsMixin:
    # ------------------------------------------------------------------ icon filter
    def rebuild_icon_filter(self, counts: dict[str, int] | None = None):
        """the type list in Find: places (City, Hall, Tower, Breach stronghold) then map icons, each
        with its picture, a show-on-map tick and its count; filtered by the search text"""
        if counts is not None:
            self.type_counts = counts
        counts = self.type_counts
        near = self.near_only()
        if near:  # only what is on / next to a city biome
            counts = {}
            for i, ic in enumerate(self.V["icons"]):
                if self.icon_near_city(i):
                    counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
            for k in ("City", "Ezomyte city", "Vaal city", "Faridun city", "Potential city map"):
                if k in self.type_counts:
                    counts[k] = self.type_counts[k]
        q = self.query.get().strip().lower() if hasattr(self, "query") else ""
        key = (q, near, tuple(sorted(counts.items())), tuple(self.place_types), tuple(self.icon_types))
        if key == getattr(self, "_type_list_key", None):
            return  # nothing changed: keep the widgets
        self._type_list_key = key
        for w in self.icon_frame.winfo_children():
            w.destroy()
        self._thumb_photos = []
        photos = self.__dict__.setdefault("_photo_cache", {})
        kept = {lab: self.icon_vars[lab].get() for lab in self.icon_vars}
        self.icon_vars = {}
        raw_of = {}
        for ic in self.V["icons"]:
            raw_of.setdefault(icon_label(ic), ic["name"])
        sections = [("Places", self.place_types), ("Map icons", self.icon_types)]
        r = 0
        for title, labels in sections:
            labels = [lab for lab in labels if lab in counts]
            shown = [
                lab for lab in labels if not q or q in lab.lower() or (lab in raw_of and q in icon_aliases(raw_of[lab]))
            ]
            for lab in labels:  # keep ticks of rows filtered out of view
                self.icon_vars[lab] = tk.BooleanVar(value=kept.get(lab, lab not in self.icon_hidden))
            if not shown:
                continue
            hd = tk.Label(
                self.icon_frame, text=title, background="white", foreground="#666", font=("TkDefaultFont", 8, "bold")
            )
            hd.grid(row=r, column=0, sticky="w", padx=4, pady=(4, 0))
            r += 1
            for lab in shown:
                raw = PLACE_ICON.get(lab) if title == "Places" else raw_of.get(lab, "")
                row = tk.Frame(self.icon_frame, background="white")
                row.grid(row=r, column=0, sticky="w")
                r += 1
                tk.Checkbutton(
                    row,
                    variable=self.icon_vars[lab],
                    background="white",
                    activebackground="white",
                    foreground="black",
                    selectcolor="white",
                    command=self.on_icon_filter,
                ).pack(side="left")
                photo = photos.get(raw or "Unidentified")
                if photo is None:
                    photo = photos[raw or "Unidentified"] = ImageTk.PhotoImage(icon_thumb(raw or "Unidentified"))
                self._thumb_photos.append(photo)
                tk.Label(row, image=photo, background="white").pack(side="left", padx=(0, 4))
                name = tk.Label(
                    row, text=f"{lab}  ({counts.get(lab, 0)})", background="white", foreground="black", cursor="hand2"
                )
                name.pack(side="left")
                name.bind("<Button-1>", lambda _e, lb=lab: self.list_type(lb))
                for wdg in row.winfo_children() + [row]:
                    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                        wdg.bind(seq, self._scroll_icons)
        self.icon_canvas.yview_moveto(0)

    def _scroll_icons(self, e):
        """scroll the type list, never past its ends (that left smeared copies of the rows on Windows)"""
        c = self.icon_canvas
        first, last = c.yview()
        step = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
        if (step < 0 and first <= 0.0) or (step > 0 and last >= 1.0):
            return "break"
        c.yview_scroll(step * 3, "units")
        c.update_idletasks()
        return "break"

    def list_type(self, label):
        """list every map / place of one type in the results (keeps the type list as it is)"""
        self._last_list = label
        self.hits, labels = [], []
        if label in POTENTIAL_TYPES:
            for v, (lab, st) in sorted(self.potential.items(), key=lambda t: (t[1][0], t[1][1])):
                if st and self.potential_kind(lab) == label:
                    self.hits.append(("node", v))
                    labels.append(self.potential_text(v))
        elif label.endswith(" city"):
            for i, (t, how) in self.city_type.items():
                if f"{t} city" == label:
                    self.hits.append(("landmark", i))
                    labels.append(f"{self.lm_name(i)}  ({'set by hand' if how == 'set' else how})")
        elif label in self.place_types:
            for i, lm in enumerate(self.V["landmarks"]):
                if lm["kind"] == label and not lm["status"].startswith("removed"):
                    self.hits.append(("landmark", i))
                    labels.append(f"{lm['kind']}  (seen {lm['n']}x)")
        else:
            for i, ic in enumerate(self.V["icons"]):
                if icon_label(ic) == label:
                    self.hits.append(("icon", i))
                    labels.append(f"{label}  (seen {ic['n']}x)")
        self._fill_results(labels)
        self.status.set(f"{len(labels)} {label}")

    def on_icon_filter(self):
        self.icon_hidden = {lab for lab, v in self.icon_vars.items() if not v.get()}
        self.request_redraw()

    def set_all_icons(self, on: bool):
        for v in self.icon_vars.values():
            v.set(on)
        self.on_icon_filter()

    def near_only(self) -> bool:
        v = getattr(self, "only_near_city", None)
        return bool(v is not None and v.get())

    def icon_near_city(self, i: int) -> bool:
        v = getattr(self, "icon_node", {}).get(i)
        return v is not None and v in getattr(self, "near_city", {})

    def icon_visible(self, ic) -> bool:
        if icon_label(ic) in self.icon_hidden:
            return False
        if self.near_only():
            i = getattr(self, "_icon_index", {}).get(id(ic))
            return i is not None and self.icon_near_city(i)
        return True
