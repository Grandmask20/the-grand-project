"""viewer.panels: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

from .constants import PLACE_ICON, POTENTIAL_TYPES
from .helpers import icon_aliases, icon_label, icon_thumb


class PanelsMixin:
    """Viewer mixin for the type list in Find (places and map icons, with show-on-map ticks) and the icon filter."""

    # ------------------------------------------------------------------ icon filter
    def rebuild_icon_filter(self, counts: dict[str, int] | None = None):
        """Rebuild the type list in Find: places (City, Hall, Tower, Breach stronghold) then map icons.

        Each row has its picture, a show-on-map tick and its count; rows are filtered by the search text (name or
        alias). With "only near a city" on, only icons on / next to a city biome are counted. Ticks of rows filtered
        out of view are kept. Nothing is rebuilt when nothing changed.

        Args:
            counts: Type label -> count to store as the new counts; None keeps the stored ones.
        """
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
        self.icon_canvas.yview_moveto(0)

    def _wheel_router(self, e):
        """Scroll the list under the mouse pointer, wherever in it the pointer is.

        Bound once for the whole window (bind_all <MouseWheel> / <Button-4> / <Button-5>). The icon list used to
        scroll only with the pointer on a row's text and the list focused: Windows sends wheel events to the focused
        widget, and headers and the space beside short rows had no binding (user). Lists: the icon / place type
        list (Find tab) and the Saved atlases cards.

        Args:
            e: The Tk wheel event (e.x_root / e.y_root: pointer position on the screen).

        Returns:
            "break" when a list was scrolled, else None (the event goes on, e.g. to the map's zoom).
        """
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):  # a menu or a closed window under the pointer
            return None
        while w is not None:
            for c in (getattr(self, "icon_canvas", None), getattr(self, "atl_canvas", None)):
                if c is not None and w is c:
                    return self._scroll_canvas(c, e)
            w = w.master
        return None

    @staticmethod
    def _scroll_canvas(c, e):
        """Scroll a canvas list by the wheel, never past its ends (that left smeared copies of rows on Windows).

        The one wheel handler for every list (the type list had its own copy that also repainted at once: user /
        GPT audit). It repaints at once, so rows made of widgets don't smear while scrolling.

        Args:
            c: The tk.Canvas holding the list.
            e: The Tk wheel event.

        Returns:
            "break".
        """
        first, last = c.yview()
        step = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
        if not ((step < 0 and first <= 0.0) or (step > 0 and last >= 1.0)):
            c.yview_scroll(step * 3, "units")
            c.update_idletasks()
        return "break"

    def list_type(self, label):
        """List every map / place of one type in the results (keeps the type list as it is).

        Bound to <Button-1> on a type's name in the list.

        Args:
            label: Type label: a potential city / stronghold type, "<type> city", a place type (landmark kind) or an
                icon label.
        """
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
        """Store which types are unticked (hidden on the map) and redraw. Called by each tick in the type list."""
        self.icon_hidden = {lab for lab, v in self.icon_vars.items() if not v.get()}
        self.request_redraw()

    def set_all_icons(self, on: bool):
        """Tick or untick every type in the list.

        Args:
            on: True shows every type, False hides them all.
        """
        for v in self.icon_vars.values():
            v.set(on)
        self.on_icon_filter()

    def near_only(self) -> bool:
        """Whether "only near a city" is ticked.

        Returns:
            True when only things on / next to a city biome are shown.
        """
        v = getattr(self, "only_near_city", None)
        return bool(v is not None and v.get())

    def icon_near_city(self, i: int) -> bool:
        """Whether an icon's map node is on / next to a city biome.

        Args:
            i: Icon index into V["icons"].

        Returns:
            True when the icon belongs to a map node near a city.
        """
        v = getattr(self, "icon_node", {}).get(i)
        return v is not None and v in getattr(self, "near_city", {})

    def icon_visible(self, ic) -> bool:
        """Whether an icon passes the filters (its type ticked, and near a city when only those are shown).

        Args:
            ic: Icon dict from V["icons"].

        Returns:
            True when the icon is drawn.
        """
        if icon_label(ic) in self.icon_hidden:
            return False
        if self.near_only():
            i = getattr(self, "_icon_index", {}).get(id(ic))
            return i is not None and self.icon_near_city(i)
        return True
