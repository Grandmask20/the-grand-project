"""app.bookmarks: part of AtlasSession (a mixin; see app/session.py): bookmarks and their groups.

Bookmarks are kept in the atlas file ({uid, name, group, note, x, y, created, hidden?, route?}). A saved route is a
bookmark with a "route" ({from, to, maps, line}: its first and last map's numbers when saved, how many maps it runs,
and the line along its paths in atlas units, kept so it draws and fits after the atlas is rebuilt); it has no pin on
the map and doesn't hold its spot. A bookmark's id is its uid,
which stays when others are deleted (it was its place in the list: a page still holding an old number deleted or
edited the bookmark that moved into that place, CodeRabbit); atlases from before get uids when first read.
Groups hidden on the map are kept per atlas in the settings (settings["hidden_groups"][atlas path]). Empty groups
made with New group last until the app closes, unless a bookmark is put in them.
"""

from __future__ import annotations

import math
import time

from grand_project import logs as atlas_log

from .constants import CATEGORIES, ROUTE_POINTS_MAX, SAME_SPOT
from .events import StaleAtlas
from .icons import icon_label, icon_name

LOG = atlas_log.get("app")


def bm_group(b: dict) -> str:
    """Return the group a bookmark belongs to (older atlases stored it as "category").

    Args:
        b: A bookmark dict.

    Returns:
        The group name ("Other" when it has none).
    """
    return b.get("group") or b.get("category") or "Other"


def clean_route(route: dict) -> dict:
    """Check a route sent to be saved and keep only what a saved route holds.

    Args:
        route: {"from", "to", "maps", "line": [[x, y], ...]} from the page.

    Returns:
        The route, with plain numbers.

    Raises:
        ValueError: When it isn't a route (no line of at least two points, or too long).
    """
    line = route.get("line")
    if not isinstance(line, list) or not 2 <= len(line) <= ROUTE_POINTS_MAX:
        raise ValueError("a route needs its line (2 points or more)")
    pts = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in line]
    return {"from": int(route["from"]), "to": int(route["to"]), "maps": int(route.get("maps", 0)), "line": pts}


class BookmarksMixin:
    """AtlasSession mixin: bookmarks (see the module docstring)."""

    def _bookmarks_changed(self) -> None:
        """Save the atlas and tell the page (it draws the bookmarks itself: the map's tiles stay as they are)."""
        if self.atlas is not None and self.path is not None:
            with self._lock:
                self.atlas.save(self.path)
        self.events.publish("bookmarks", None)

    def bookmarks_by_id(self) -> list[tuple[int, dict]]:
        """Return the open atlas's bookmarks with their ids (uids, given to the ones without).

        Returns:
            [(uid, bookmark dict)], in the list's order.
        """
        if not self.atlas:
            return []
        at = self.atlas
        with self._lock:
            # the next id is past every id read (an atlas from before keeps none), so no deletion lowers it
            at.bookmark_next_uid = max([at.bookmark_next_uid] + [int(b["uid"]) + 1 for b in at.bookmarks if "uid" in b])
            for b in at.bookmarks:
                if "uid" not in b:
                    b["uid"] = at.bookmark_next_uid
                    at.bookmark_next_uid += 1
            return [(int(b["uid"]), b) for b in at.bookmarks]

    def _bookmark(self, uid: int) -> dict:
        """Return a bookmark.

        Args:
            uid: Its id.

        Returns:
            The bookmark dict.

        Raises:
            ValueError: With no atlas open or no bookmark with that id (deleted meanwhile).
        """
        for u, b in self.bookmarks_by_id():
            if u == uid:
                return b
        raise ValueError("no such bookmark (deleted meanwhile?)")

    def groups(self) -> list[str]:
        """List every bookmark group (used ones and empty ones made with New group).

        Returns:
            The names, sorted case-insensitively.
        """
        g = {bm_group(b) for b in (self.atlas.bookmarks if self.atlas else [])} | self._extra_groups
        return sorted(g, key=str.lower)

    def hidden_groups(self) -> set[str]:
        """Return the groups hidden on the map for the open atlas.

        Returns:
            The group names.
        """
        key = str(self.path) if self.path else ""
        return set(self.settings.get("hidden_groups", {}).get(key, []))

    def bookmark_shown(self, b: dict) -> bool:
        """Tell whether a bookmark is drawn on the map (neither its group nor itself hidden).

        Args:
            b: A bookmark dict.

        Returns:
            True when shown.
        """
        return bm_group(b) not in self.hidden_groups() and not b.get("hidden")

    def bookmarks_payload(self) -> dict:
        """Return the bookmarks and groups for the Bookmarks tab.

        Returns:
            {"groups": [{"name", "hidden", "items": [{"id", "name", "note", "x", "y", "created", "hidden", "shown"}]}]}.
        """
        hidden = self.hidden_groups()
        by_group: dict[str, list] = {g: [] for g in self.groups()}
        for i, b in self.bookmarks_by_id():
            by_group.setdefault(bm_group(b), []).append(
                {
                    "id": i,
                    "name": b["name"],
                    "note": b.get("note", ""),
                    "x": b["x"],
                    "y": b["y"],
                    "created": b.get("created", ""),
                    "hidden": bool(b.get("hidden")),
                    "shown": self.bookmark_shown(b),
                    **({"route": b["route"]} if b.get("route") else {}),
                }
            )
        return {
            "groups": [
                {"name": g, "hidden": g in hidden, "items": sorted(items, key=lambda t: t["name"].lower())}
                for g, items in sorted(by_group.items(), key=lambda t: t[0].lower())
            ]
        }

    def bookmark_at(self, x: float, y: float) -> int | None:
        """Find a bookmark already on this spot (closer than SAME_SPOT).

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            Its id, or None.
        """
        best, bd = None, SAME_SPOT
        for i, b in self.bookmarks_by_id():
            if b.get("route"):  # (a saved route is no pin on its first map)
                continue
            d = math.hypot(b["x"] - x, b["y"] - y)
            if d < bd:
                best, bd = i, d
        return best

    def default_name(self, kind: str, i: int) -> tuple[str, str]:
        """Suggest a bookmark name and group for a map node, icon or landmark.

        Args:
            kind: "node", "icon" or "landmark".
            i: Index in the model list.

        Returns:
            (name, group).
        """
        if kind == "landmark":
            k = self.V["landmarks"][i]["kind"]
            return self.landmark_name(i), k if k in CATEGORIES else "Other"
        raws = self.V["nodes"][i].get("icons", []) if kind == "node" else [self.V["icons"][i]["name"]]
        raw = next((r for r in raws if r != "Unidentified"), raws[0] if raws else "")
        groups = (("Boss", "Boss"), ("Abyss", "Abyss"), ("Delirium", "Delirium"))
        groups += (("Unique map", "Unique"), ("Breach", "Breach"))
        cat = next((c for c, key in groups if key in raw), "Other")
        name = icon_label(self.V["icons"][i]) if kind == "icon" else (icon_name(raw) if raw else f"Map #{i}")
        return name, cat

    def add_bookmark(
        self,
        x: float,
        y: float,
        name: str,
        group: str = "Other",
        note: str = "",
        quiet=False,
        gen: int | None = None,
        route: dict | None = None,
    ) -> int:
        """Add a bookmark unless one already sits on that spot.

        Args:
            x: Atlas x.
            y: Atlas y.
            name: Its name.
            group: Its group.
            note: Free text.
            quiet: Only add it (the caller saves once after many).

        Returns:
            Its id (-1 when a bookmark was already there).

        Raises:
            ValueError: With no atlas open or no name.
        """
        if not self.atlas:
            raise ValueError("open an atlas first")
        if not name.strip():
            raise ValueError("a bookmark needs a name")
        with self._lock:  # the spot check and the append together (CodeRabbit)
            if gen is not None and not self.owns(gen):  # made for an atlas no longer open (CodeRabbit)
                raise StaleAtlas()
            route = clean_route(route) if route else None
            if route is None and self.bookmark_at(x, y) is not None:
                return -1
            # one past every id this atlas has had, kept in the atlas (a deleted one's id is never given again)
            self.bookmarks_by_id()
            i = self.atlas.bookmark_next_uid
            self.atlas.bookmark_next_uid += 1
            self.atlas.bookmarks.append(
                {
                    "uid": i,
                    "name": name.strip(),
                    "group": group.strip() or "Other",
                    "note": note,
                    "x": float(x),
                    "y": float(y),
                    "created": time.strftime("%Y-%m-%d %H:%M"),
                    **({"route": route} if route else {}),
                }
            )
        if not quiet:
            self._bookmarks_changed()
            self.events.log(f"bookmarked {name}")
        return i

    def bookmark_items(self, items: list[tuple[str, int]], group: str) -> tuple[int, int]:
        """Bookmark many map nodes / icons / landmarks into one group (Find > Bookmark all).

        Args:
            items: (kind, index) pairs.
            group: The group.

        Returns:
            (added, skipped because a bookmark was already there).
        """
        added = skipped = 0
        for kind, i in items:
            if kind == "bookmark":
                continue
            x, y = self.item_pos(kind, i)
            name, _ = self.default_name(kind, i)
            if self.add_bookmark(x, y, name, group, quiet=True) >= 0:
                added += 1
            else:
                skipped += 1
        self._bookmarks_changed()
        msg = f'bookmarked {added} into "{group}"' + (f" ({skipped} were already bookmarked)" if skipped else "")
        self.events.set_status(msg)
        self.events.log(msg)
        return added, skipped

    def edit_bookmark(self, i: int, name: str, group: str, note: str) -> None:
        """Change a bookmark's name, group and note.

        Args:
            i: Its id.
            name: New name.
            group: New group.
            note: New note.

        Raises:
            ValueError: With no such bookmark or no name.
        """
        b = self._bookmark(i)
        if not name.strip():
            raise ValueError("a bookmark needs a name")
        b.update(name=name.strip(), group=group.strip() or "Other", note=note)
        b.pop("category", None)
        self._bookmarks_changed()

    def delete_bookmarks(self, ids: list[int]) -> list[str]:
        """Delete bookmarks.

        Args:
            ids: Their ids (ones no longer there are skipped).

        Returns:
            Their names.
        """
        if not self.atlas:
            return []
        gone = set(ids)
        names = [b["name"] for u, b in self.bookmarks_by_id() if u in gone]
        with self._lock:
            self.atlas.bookmarks[:] = [b for u, b in self.bookmarks_by_id() if u not in gone]
        if names:
            LOG.info(f"deleted bookmark(s): {names}")
            self._bookmarks_changed()
        return names

    def move_bookmarks(self, ids: list[int], group: str) -> None:
        """Move bookmarks to a group.

        Args:
            ids: Their ids.
            group: The group.
        """
        for i in ids:
            self._bookmark(i)["group"] = group.strip() or "Other"
        self._bookmarks_changed()

    def new_group(self, name: str) -> None:
        """Add an empty group (kept until the app closes unless a bookmark is put in it).

        Args:
            name: The group name.
        """
        if name.strip():
            self._extra_groups.add(name.strip())
            self.events.log(f"new bookmark group {name.strip()!r}")
            self.events.publish("bookmarks", None)

    def rename_group(self, old: str, new: str) -> None:
        """Rename a group.

        Args:
            old: Its name.
            new: The new name.
        """
        new = new.strip()
        if not new or not self.atlas:
            return
        for b in self.atlas.bookmarks:
            if bm_group(b) == old:
                b["group"] = new
        if old in self._extra_groups:
            self._extra_groups.discard(old)
            self._extra_groups.add(new)
        # a hidden group stays hidden under its new name (user: renaming showed it again)
        key = str(self.path) if self.path else ""
        hg = self.settings.setdefault("hidden_groups", {})
        if old in hg.get(key, []):
            hg[key] = sorted((set(hg[key]) - {old}) | {new})
            self.save_settings()
        self.events.log(f"bookmark group {old!r} renamed to {new!r}")
        self._bookmarks_changed()

    def delete_groups(self, names: list[str]) -> int:
        """Delete empty groups (a group with bookmarks goes when its last bookmark does).

        Args:
            names: The group names.

        Returns:
            How many were deleted.
        """
        if not self.atlas:
            return 0
        used = {bm_group(b) for b in self.atlas.bookmarks}
        gone = [n for n in names if n in self._extra_groups and n not in used]
        for n in gone:
            self._extra_groups.discard(n)
        if gone:
            key = str(self.path) if self.path else ""
            hg = self.settings.setdefault("hidden_groups", {})
            if set(gone) & set(hg.get(key, [])):
                hg[key] = sorted(set(hg[key]) - set(gone))
                self.save_settings()
            self.events.log(f"deleted empty bookmark group(s): {', '.join(gone)}")
            self.events.publish("bookmarks", None)
        return len(gone)

    def toggle_group(self, g: str) -> None:
        """Hide a group on the map, or show it again (kept per atlas in the settings).

        Args:
            g: The group name.
        """
        key = str(self.path) if self.path else ""
        hg = self.settings.setdefault("hidden_groups", {})
        cur = set(hg.get(key, []))
        cur.symmetric_difference_update({g})
        hg[key] = sorted(cur)
        self.save_settings()
        self.events.log(f"bookmark group {g!r} {'hidden' if g in cur else 'shown'} on the map")
        self.events.publish("bookmarks", None)  # (drawn by the page: no tiles made again, user: it was slow)

    def toggle_bookmark(self, i: int) -> None:
        """Hide one bookmark on the map, or show it again; in a hidden group, the group is shown and only this
        bookmark of it.

        Args:
            i: Its id.
        """
        b = self._bookmark(i)
        g = bm_group(b)
        if g in self.hidden_groups():
            key = str(self.path) if self.path else ""
            hg = self.settings.setdefault("hidden_groups", {})
            hg[key] = sorted(set(hg.get(key, [])) - {g})
            self.save_settings()
            for o in self.atlas.bookmarks:
                if bm_group(o) == g:
                    o["hidden"] = o is not b  # (the bookmark itself: a list place isn't its id, CodeRabbit)
        else:
            b["hidden"] = not b.get("hidden")
        self._bookmarks_changed()
