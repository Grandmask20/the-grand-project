"""viewer.panels: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from .constants import PLACE_ICON, POTENTIAL_TYPES, TYPE_ROW_H
from .helpers import icon_aliases, icon_label, icon_thumb


class PanelsMixin:
    """Viewer mixin for the type list in Find (places and map icons, with show-on-map ticks) and the icon filter."""

    # ------------------------------------------------------------------ side panel text
    def _wrap(self, parent, **kw):
        """A label whose text wraps to the side panel's width (it follows the panel when its sash is dragged).

        Args:
            parent: The widget to put the label in.
            **kw: ttk.Label options (text, textvariable, foreground, justify, ...).

        Returns:
            The ttk.Label (not yet packed).
        """
        lab = ttk.Label(parent, wraplength=self._wrap_width(), **kw)
        self._wrap_labels.append(lab)
        return lab

    def _wrap_width(self) -> int:
        """Text width for the side panel's labels: the panel's width less its tab and frame padding.

        Returns:
            Width in px (the panel's starting width before it is shown).
        """
        w = self.side.winfo_width() if self.side.winfo_ismapped() else int(self.settings.get("side_width", 400))
        return max(200, w - 44)

    def _rewrap(self, _e=None):
        """Re-wrap the side panel's labels to its new width. Bound to <Configure> on the side panel.

        Args:
            _e: The Tk event (unused).
        """
        w = self._wrap_width()
        if w == getattr(self, "_wrapped_at", None):
            return
        self._wrapped_at = w
        for lab in self._wrap_labels:
            with contextlib.suppress(tk.TclError):
                lab.configure(wraplength=w)

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
            return  # nothing changed: keep the list
        self._type_list_key = key
        # drawn as items on the one canvas, not 4 widgets per row: on Windows each widget is its own window and
        # all of them repaint at every step of a window resize (~190 here made resizing lag and smear, user)
        c = self.icon_canvas
        c.delete("all")
        self._thumb_photos = []
        self.type_rows = []  # the labels listed, top to bottom (tests read it)
        photos = self.__dict__.setdefault("_photo_cache", {})
        kept = {lab: self.icon_vars[lab].get() for lab in self.icon_vars}
        self.icon_vars = {}
        raw_of = {}
        for ic in self.V["icons"]:
            raw_of.setdefault(icon_label(ic), ic["name"])
        y = 4
        for title, labels in (("Places", self.place_types), ("Map icons", self.icon_types)):
            labels = [lab for lab in labels if lab in counts]
            shown = [
                lab for lab in labels if not q or q in lab.lower() or (lab in raw_of and q in icon_aliases(raw_of[lab]))
            ]
            for lab in labels:  # keep ticks of rows filtered out of view
                self.icon_vars[lab] = tk.BooleanVar(value=kept.get(lab, lab not in self.icon_hidden))
            if not shown:
                continue
            c.create_text(6, y, text=title, anchor="nw", fill="#666", font=("TkDefaultFont", 8, "bold"))
            y += 18
            for lab in shown:
                raw = PLACE_ICON.get(lab) if title == "Places" else raw_of.get(lab, "")
                tag = f"row{len(self.type_rows)}"
                self.type_rows.append(lab)
                mid = y + TYPE_ROW_H // 2
                c.create_rectangle(8, mid - 6, 20, mid + 6, outline="#555", fill="white", tags=(tag, "tick"))
                c.create_text(14, mid, text="", fill="black", font=("TkDefaultFont", 9, "bold"), tags=(tag, "mark"))
                photo = photos.get(raw or "Unidentified")
                if photo is None:
                    photo = photos[raw or "Unidentified"] = ImageTk.PhotoImage(icon_thumb(raw or "Unidentified"))
                self._thumb_photos.append(photo)
                c.create_image(38, mid, image=photo, tags=(tag, "tick"))
                c.create_text(
                    54, mid, text=f"{lab}  ({counts.get(lab, 0)})", anchor="w", fill="black", tags=(tag, "name")
                )
                y += TYPE_ROW_H
        c.configure(scrollregion=(0, 0, 1, y + 4))
        self._paint_ticks()
        c.yview_moveto(0)

    def _bind_type_list(self):
        """Bind clicks on the type list's rows, once (the bindings belong to the tags, so they outlast every rebuild
        of the rows; binding them at each rebuild piled up callbacks: review)."""
        c = self.icon_canvas
        c.tag_bind("tick", "<Button-1>", self._on_type_tick)
        c.tag_bind("mark", "<Button-1>", self._on_type_tick)
        c.tag_bind("name", "<Button-1>", self._on_type_name)
        c.tag_bind("name", "<Enter>", lambda _e: c.configure(cursor="hand2"))
        c.tag_bind("name", "<Leave>", lambda _e: c.configure(cursor=""))

    def _type_row_at(self, e) -> str | None:
        """The type label of the list row that was clicked.

        Args:
            e: The Tk event on the list canvas.

        Returns:
            The label, or None when the click was not on a row.
        """
        for tag in self.icon_canvas.gettags("current"):
            if tag.startswith("row"):
                return self.type_rows[int(tag[3:])]
        return None

    def _on_type_tick(self, e):
        """Flip a type's show-on-map tick. Bound to clicks on a row's tick box and picture.

        Args:
            e: The Tk event.
        """
        lab = self._type_row_at(e)
        if lab in self.icon_vars:
            self.icon_vars[lab].set(not self.icon_vars[lab].get())
            self.on_icon_filter()

    def _on_type_name(self, e):
        """List every map / place of a type. Bound to clicks on a row's name.

        Args:
            e: The Tk event.
        """
        lab = self._type_row_at(e)
        if lab is not None:
            self.list_type(lab)

    def _paint_ticks(self):
        """Draw each listed row's tick mark from its tick (after any change to the ticks)."""
        c = self.icon_canvas
        for n, lab in enumerate(getattr(self, "type_rows", [])):
            v = self.icon_vars.get(lab)
            c.itemconfigure(f"row{n}&&mark", text="✓" if v is not None and v.get() else "")

    def _scroll_icons(self, e):
        """Scroll the type list, never past its ends (that left smeared copies of the rows on Windows).

        Bound to <MouseWheel>, <Button-4> and <Button-5> on every row of the list.

        Args:
            e: The Tk event (e.delta, or e.num 4 / 5 on Linux).

        Returns:
            "break", so Tk does not scroll anything else.
        """
        c = self.icon_canvas
        first, last = c.yview()
        step = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
        if (step < 0 and first <= 0.0) or (step > 0 and last >= 1.0):
            return "break"
        c.yview_scroll(step * 3, "units")
        c.update_idletasks()
        return "break"

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
            if w is getattr(self, "icon_canvas", None):
                return self._scroll_icons(e)
            if w is getattr(self, "atl_canvas", None):
                return self._scroll_canvas(self.atl_canvas, e)
            w = w.master
        return None

    @staticmethod
    def _scroll_canvas(c, e):
        """Scroll a canvas list by the wheel, never past its ends.

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
        self._paint_ticks()
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
