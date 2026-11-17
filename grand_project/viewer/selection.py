"""viewer.selection: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import re
import tkinter as tk

from .helpers import icon_aliases, icon_label, icon_name


class SelectionMixin:
    """Viewer mixin for the selection, its details ("Selected" in the Find tab) and the Find search."""

    # ------------------------------------------------------------------ selection / info
    def select(self, item):
        """Select an item, show its details and redraw.

        Args:
            item: (kind, index) as from pick(), with kind "node", "path", "landmark", "icon" or "bookmark"; or None to
                clear the selection.
        """
        self.sel = item
        self.show_info()
        self.request_redraw()

    def item_pos(self, item) -> tuple[float, float]:
        """Where an item is on the atlas (a path: the middle between its two map nodes).

        Args:
            item: (kind, index) with kind "node", "path", "landmark", "icon" or "bookmark".

        Returns:
            (x, y) in atlas units.
        """
        kind, i = item
        if kind == "path":
            p = self.V["paths"][i]
            a, b = self.V["nodes"][p["a"]], self.V["nodes"][p["b"]]
            return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        if kind == "icon" and i < len(self.icon_pts):  # where it is drawn: in its map node's row
            return float(self.icon_pts[i][0]), float(self.icon_pts[i][1])
        src = {"node": self.V["nodes"], "landmark": self.V["landmarks"], "icon": self.V["icons"]}.get(kind)
        n = src[i] if src is not None else self.atlas.bookmarks[i]
        return float(n["x"]), float(n["y"])

    def sel_valid(self) -> bool:
        """Check the selection and drop it if its item no longer exists (deleted bookmark, rebuilt atlas).

        Returns:
            True when something valid is selected.
        """
        if not self.sel:
            return False
        kind, i = self.sel
        size = {
            "node": len(self.V["nodes"]),
            "landmark": len(self.V["landmarks"]),
            "icon": len(self.V["icons"]),
            "path": len(self.V["paths"]),
            "bookmark": len(self.atlas.bookmarks) if self.atlas else 0,
        }.get(kind, 0)
        if not 0 <= i < size:
            self.sel = None
            return False
        return True

    def show_info(self):
        """Write the selected item's details into the "Selected" box of the Find tab.

        Map nodes: icons, screenshots that show it, paths, status, abyss chain, tower foot, potential city and nearby
        city. Paths: end map nodes, how it was found, how many screenshots draw it. Landmarks: kind, screenshots,
        confidence, city type, locked stronghold, status. Icons: name, screenshots, match score, city map or not.
        Bookmarks: name, group, note. Always the position. With nothing selected, a hint.
        """
        lines = []
        self.sel_valid()
        if self.sel and self.atlas:
            kind, i = self.sel
            if kind == "node":
                n = self.V["nodes"][i]
                deg = [p for p in self.V["paths"] if i in (p["a"], p["b"])]
                multi = sum(p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends", False) for p in deg)
                icons = ", ".join(icon_name(k) for k in n.get("icons", []))
                lines += [
                    f"Map #{i}" + (f": {icons}" if icons else ""),
                    f"found in {n['seen']} of {n['could']} screenshot(s) that show it",
                    f"{len(deg)} path(s), {multi} confirmed (traced from both ends or in 2+ shots)",
                ]
                st = {
                    "confirmed": "confirmed by several screenshots",
                    "icon": "confirmed by its icon",
                    "single": "only one screenshot shows it",
                    "disputed": "1 of 2 screenshots, kept: a path reaches it",
                    "doubtful": "doubtful: one screenshot, no icon, no path",
                }.get(n["status"], n["status"])
                lines.append(st)
                if n.get("abyss"):
                    lines.append(
                        {"start": "Abyss chain: first map", "final": "Abyss chain: final map", "chain": "Abyss chain"}[
                            n["abyss"]
                        ]
                    )
                if n.get("tower"):
                    lines.append("Tower foot (path endpoint)")
                if i in self.potential:
                    lines.append(self.potential_text(i))
                if self.near_city_text(i):
                    lines.append(self.near_city_text(i))
                if n.get("origin") == "from icon":
                    lines.append("map base not detected; placed under its icon")
            elif kind == "path":
                p = self.V["paths"][i]
                a, b = self.V["nodes"][p["a"]], self.V["nodes"][p["b"]]
                lines += [
                    f"Path: map #{p['a']} ({a['x']:.0f}, {a['y']:.0f}) - map #{p['b']} ({b['x']:.0f}, {b['y']:.0f})",
                    {
                        "traced": "traced along its dashes",
                        "straight": "straight link (gold along it, not traced)",
                        "abyss": "Abyss chain link",
                    }.get(p.get("kind"), p.get("kind", "")),
                    f"drawn by {p.get('seen_in', 0)} of {p.get('frames', 0)} screenshot(s) that show both maps",
                ]
                if "ends_in" in p:
                    lines.append(
                        f"traced end to end in {p['ends_in']}, confirmed by {p['confirm']} more, "
                        f"denied by {p['deny']}; {p['dashes']} dashes on its clearest trace"
                    )
            elif kind == "landmark":
                lm = self.V["landmarks"][i]
                lines += [
                    lm["kind"],
                    f"found in {lm['n']} of {lm.get('could', lm['n'])} screenshot(s)",
                    f"confidence {lm['conf']:.2f}, detected by {lm.get('source', '')}",
                ]
                if i in self.city_type:
                    t, how = self.city_type[i]
                    lines.insert(0, f"{t} city")
                    lines.append(
                        {
                            "set": "type set by hand (right-click to change)",
                            "trio": "type from its trio: the cities next to it are the other two types",
                            "look-alike": "type guessed by look; right-click to set it",
                        }[how]
                    )
                if i in getattr(self, "locked_ids", ()):
                    lines.insert(0, "Locked Breach stronghold")
                    lines.append("locked (hand badge): only its ground shows, no maps yet")
                if lm.get("beam"):
                    lines.append(f"{lm['kind']} because: {lm['beam']}")
                if lm["status"] != "kept":
                    lines.append(lm["status"])
            elif kind == "icon":
                ic = self.V["icons"][i]
                lines += [
                    icon_label(ic),
                    f"seen in {ic['n']} screenshot(s), match {ic['score']:.2f}",
                    f"raw name: {ic['name']}",
                ]
                v = getattr(self, "icon_node", {}).get(i)
                if v is not None and v in getattr(self, "blocked", {}):
                    lines.append(f"not a city map ({self.blocked[v]})")
                elif self.near_city_text(v):
                    lines.append(self.near_city_text(v))
            else:
                b = self.atlas.bookmarks[i]
                lines += [f"★ {b['name']}", f"group: {self.bm_group(b)}"]
                if b.get("note"):
                    lines.append(b["note"])
            x, y = self.item_pos(self.sel)
            lines.append(f"position {x:.0f}, {y:.0f}")
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(lines) if lines else "Click a map, icon, landmark or bookmark.")
        self.info.configure(state="disabled")

    # ------------------------------------------------------------------ search
    def _item_node(self, item):
        """The map node an item belongs to.

        Args:
            item: (kind, index) as in select().

        Returns:
            The map node index for a map node or an icon on one, else None.
        """
        kind, i = item
        if kind == "node":
            return i
        if kind == "icon":
            return getattr(self, "icon_node", {}).get(i)
        return None

    def _fill_results(self, labels):
        """Show the Find hits in the results list, then redraw (the hits get rings on the map).

        With "only near a city" ticked, hits not near a city are dropped (from self.hits too). Icons near a city get
        "⌂ <city type>" and items with a bookmark on them a ★.

        Args:
            labels: One display text per entry of self.hits, in the same order (changed in place).
        """
        if getattr(self, "only_near_city", None) is not None and self.only_near_city.get():
            keep = [k for k, it in enumerate(self.hits) if self.near_city_text(self._item_node(it))]
            self.hits = [self.hits[k] for k in keep]
            labels = [labels[k] for k in keep]
        for k, it in enumerate(self.hits):
            t = getattr(self, "near_city", {}).get(self._item_node(it))
            if t and it[0] == "icon":
                labels[k] += f"   ⌂ {t[0]}" + ("" if t[1] == 0 else " +1")
        for k, (item, s_) in enumerate(zip(self.hits, labels, strict=False)):
            if item[0] != "bookmark" and self.bookmark_at(*self.item_pos(item)) is not None:
                s_ = "★ " + s_
            labels[k] = s_
        self.results.delete(0, "end")
        for s_ in labels:
            self.results.insert("end", s_)
        self.request_redraw()

    def run_search(self):
        """Search the atlas for the text in the Find box and list the matches.

        Two numbers ("x, y") centre the map there and mark it with a cross (user: no more hot-or-cold panning).
        Otherwise matches bookmarks (name, group, note), landmarks, icons (name or alias), potential city /
        stronghold maps, and "#<n>" for map node n.
        """
        self._last_list = None
        q = self.query.get().strip().lower()
        self.hits = []
        self.results.delete(0, "end")
        if hasattr(self, "type_counts") and self.atlas:
            self.rebuild_icon_filter()
        if not self.atlas or not q:
            self.request_redraw()
            return

        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*", q)
        if m:  # coordinates (user: no more hot-or-cold panning)
            x, y = float(m.group(1)), float(m.group(2))
            self._goto = (x, y)
            self.center_on(x, y, min_zoom=1.0)
            self.status.set(f"centred on {x:.0f}, {y:.0f} (marked with a cross)")
            self.request_redraw()
            return
        labels = []
        for i, b in enumerate(self.atlas.bookmarks):
            if q in f"{b['name']} {self.bm_group(b)} {b.get('note', '')}".lower():
                self.hits.append(("bookmark", i))
                labels.append(f"[bookmark] {b['name']}  ({self.bm_group(b)})")
        for i, lm in enumerate(self.V["landmarks"]):
            if q in self.lm_name(i).lower() and not lm["status"].startswith("removed"):
                self.hits.append(("landmark", i))
                labels.append(f"{self.lm_name(i)}  (seen {lm['n']}x)")
        for i, ic in enumerate(self.V["icons"]):
            nice = icon_label(ic)
            if q in nice.lower() or q in icon_aliases(ic["name"]):
                self.hits.append(("icon", i))
                labels.append(f"{nice}  (seen {ic['n']}x)")
        if len(q) >= 4 and q in "potential city map potential stronghold map":
            for v, (lab, st) in self.potential.items():
                if st and q in self.potential_kind(lab).lower():
                    self.hits.append(("node", v))
                    labels.append(self.potential_text(v))
        m = re.fullmatch(r"#(\d+)", q)
        if m and int(m.group(1)) < len(self.V["nodes"]):
            self.hits.append(("node", int(m.group(1))))
            labels.append(f"Map #{m.group(1)}")
        self._fill_results(labels)
        self.status.set(f'{len(labels)} match(es) for "{q}"')

    def goto_result(self, box: tk.Listbox, index: list):
        """Centre on and select the item picked in a results list. Bound to <<ListboxSelect>> on the list.

        Args:
            box: The listbox whose selection is read.
            index: The items listed in it, in the same order (e.g. self.hits).
        """
        sel = box.curselection()
        if not sel or sel[0] >= len(index):
            return
        item = index[sel[0]]
        x, y = self.item_pos(item)
        self.center_on(x, y, min_zoom=1.0)
        self.select(item)
