"""app.query: part of AtlasSession (a mixin; see app/session.py): what the page asks about the atlas.

Clicking (what is under a point), the details of an item, Find (search and the type list), listing every item of a
type, the screenshots that show a spot, and the map graph the page finds routes on.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np

from grand_project import cities as atlas_cities
from grand_project import core

from .bookmarks import bm_group
from .constants import POTENTIAL_TYPES
from .icons import icon_aliases, icon_label, icon_name

KINDS = ("node", "path", "landmark", "icon", "bookmark")


class QueryMixin:
    """AtlasSession mixin: questions about the atlas (see the module docstring)."""

    # ------------------------------------------------------------------ items
    def item_valid(self, kind: str, i: int) -> bool:
        """Tell whether an item exists.

        Args:
            kind: "node", "path", "landmark", "icon" or "bookmark".
            i: Its index.

        Returns:
            True when it exists.
        """
        size = {
            "node": len(self.V["nodes"]),
            "landmark": len(self.V["landmarks"]),
            "icon": len(self.V["icons"]),
            "path": len(self.V["paths"]),
        }.get(kind, 0)
        if kind == "bookmark":  # (an id, not a place in the list)
            return any(u == i for u, _b in self.bookmarks_by_id())
        return 0 <= i < size

    def item_pos(self, kind: str, i: int) -> tuple[float, float]:
        """Return where an item is on the atlas (a path: midway between its maps; an icon: in its map's row).

        Args:
            kind: The item kind.
            i: Its index.

        Returns:
            (x, y) in atlas units.
        """
        if kind == "path":
            p = self.V["paths"][i]
            a, b = self.V["nodes"][p["a"]], self.V["nodes"][p["b"]]
            return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        pts = self.D.get("icon_pts")
        if kind == "icon" and pts is not None and i < len(pts):
            return float(pts[i][0]), float(pts[i][1])
        src = {"node": self.V["nodes"], "landmark": self.V["landmarks"], "icon": self.V["icons"]}.get(kind)
        n = src[i] if src is not None else self._bookmark(i)
        return float(n["x"]), float(n["y"])

    def item_node(self, kind: str, i: int) -> int | None:
        """Return the map node an item belongs to (a map node itself, or an icon's map).

        Args:
            kind: The item kind.
            i: Its index.

        Returns:
            The map node index, or None.
        """
        if kind == "node":
            return i
        if kind == "icon":
            return self.D.get("icon_node", {}).get(i)
        return None

    def potential_text(self, i: int) -> str:
        """Describe a map's place in a biome: "Vaal city (its own map)", "Potential Vaal city map (2 steps away)".

        Args:
            i: Map node index (in D["potential"]).

        Returns:
            The text.
        """
        lab, st = self.D["potential"][i]
        if st == 0:
            return f"{lab} (its own map)"
        return f"Potential {lab} map ({st} step{'s' if st > 1 else ''} away)"

    def near_city_text(self, v: int | None) -> str:
        """Return the "Potential city: ..." line for a map ("" when not on / next to a city biome).

        Args:
            v: Map node index, or None.

        Returns:
            The text.
        """
        t = self.D.get("near_city", {}).get(v) if v is not None else None
        if not t:
            return ""
        lab, st = t
        return f"Potential city: {'on the' if st == 0 else '1 step from the'} {lab} biome"

    def info(self, kind: str, i: int) -> dict:
        """Return an item's details for the Selected box and what can be done with it.

        Args:
            kind: The item kind.
            i: Its index.

        Returns:
            {"kind", "id", "title", "lines", "x", "y", plus "landmark_kind", "city_type", "removed", "group",
            "name", "note", "node" where they apply}.

        Raises:
            ValueError: When there is no such item.
        """
        if kind not in KINDS or not self.item_valid(kind, i):
            raise ValueError("no such item")
        V, D = self.V, self.D
        # a landmark standing on a map is that map, one item: its own click box lay over the map's, which could
        # hardly be clicked, and the map's own could only make it a landmark (you). A removed one, or one apart
        # from any map (a locked stronghold), stays an item of its own.
        wanted = None  # (a landmark asked for: the one its map's actions act on, of two on one map: CodeRabbit)
        if kind == "landmark" and i in D.get("landmark_node", {}):
            kind, i, wanted = "node", D["landmark_node"][i], i
        lines: list[str] = []
        out: dict = {"kind": kind, "id": i}
        if kind == "node":
            n = V["nodes"][i]
            deg = [p for p in V["paths"] if i in (p["a"], p["b"])]
            multi = sum(p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends", False) for p in deg)
            icons = ", ".join(icon_name(k) for k in n.get("icons", []))
            marks = sorted((k for k, v in D.get("landmark_node", {}).items() if v == i), key=lambda k: k != wanted)
            # a map carrying a landmark is shown as that landmark (its lines below the map's)
            name = self.landmark_name(marks[0]) if marks else ""
            out["title"] = (f"{name} (map #{i})" if name else f"Map #{i}") + (f": {icons}" if icons else "")
            lines += [
                f"found in {n['seen']} of {n['could']} screenshot(s) that show it",
                f"{len(deg)} path(s), {multi} confirmed (traced from both ends or in 2+ shots)",
                {
                    "confirmed": "confirmed by several screenshots",
                    "icon": "confirmed by its icon",
                    "single": "only one screenshot shows it",
                    "disputed": "1 of 2 screenshots, kept: a path reaches it",
                    "doubtful": "doubtful: one screenshot, no icon, no path",
                    "removed": "removed",
                }.get(n["status"], n["status"]),
            ]
            if n.get("abyss"):
                lines.append(
                    {"start": "Abyss chain: first map", "final": "Abyss chain: final map"}.get(
                        n["abyss"], "Abyss chain"
                    )
                )
            if n.get("tower"):
                lines.append("Tower foot (path endpoint)")
            if i in D.get("potential", {}):
                lines.append(self.potential_text(i))
            if self.near_city_text(i):
                lines.append(self.near_city_text(i))
            if n.get("origin") == "from icon":
                lines.append("map base not detected; placed under its icon")
            for k in marks:
                lines += (
                    [f"{self.landmark_name(k)}:"] + [f"  {t}" for t in self._landmark_lines(k)]
                    if k == marks[0]
                    else [f"{self.landmark_name(k)} here"]
                )
            if marks:
                out["landmark"] = marks[0]
                # what's needed to change that landmark from its map: a click on a landmark selects its map, whose
                # menu only made it into a landmark, so a City found there could not be made a normal map (user)
                lm, ct = V["landmarks"][marks[0]], D.get("city_type", {}).get(marks[0])
                out["on_landmark"] = {
                    "id": marks[0],
                    "title": self.landmark_name(marks[0]),
                    "x": lm["x"],
                    "y": lm["y"],
                    "landmark_kind": lm["kind"],
                    "city_type": ct[0] if ct and ct[1] == "set" else None,
                }
            out["node"] = i
        elif kind == "path":
            p = V["paths"][i]
            a, b = V["nodes"][p["a"]], V["nodes"][p["b"]]
            out["title"] = f"Path: map #{p['a']} - map #{p['b']}"
            # the whole path, for the selection to light it up end to end as the old window did (user)
            out["line"] = p.get("line") or [[a["x"], a["y"]], [b["x"], b["y"]]]
            lines += [
                f"from ({a['x']:.0f}, {a['y']:.0f}) to ({b['x']:.0f}, {b['y']:.0f})",
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
            lm = V["landmarks"][i]
            out["title"] = self.landmark_name(i)
            lines += self._landmark_lines(i)  # (a landmark on a map is shown as that map, above)
            ct = D.get("city_type", {}).get(i)
            out.update(
                landmark_kind=lm["kind"],
                removed=lm["status"].startswith("removed"),
                city_type=(ct[0] if ct and ct[1] == "set" else None),
                city_types=list(atlas_cities.TYPES) if lm["kind"] == "City" else [],
            )
        elif kind == "icon":
            ic = V["icons"][i]
            out["title"] = icon_label(ic)
            lines += [f"seen in {ic['n']} screenshot(s), match {ic['score']:.2f}", f"raw name: {ic['name']}"]
            v = D.get("icon_node", {}).get(i)
            if v is not None and v in D.get("blocked", {}):
                lines.append(f"not a city map ({D['blocked'][v]})")
            elif self.near_city_text(v):
                lines.append(self.near_city_text(v))
            out["node"] = v
            out["icon"] = ic["name"]
        else:
            b = self._bookmark(i)
            out["title"] = f"★ {b['name']}"
            lines.append(f"group: {bm_group(b)}")
            if b.get("note"):
                lines.append(b["note"])
            out.update(name=b["name"], group=bm_group(b), note=b.get("note", ""))
        x, y = self.item_pos(kind, i)
        lines.append(f"position {x:.0f}, {y:.0f}")
        out.update(lines=lines, x=x, y=y)
        if kind != "bookmark":
            bm = self.bookmark_at(x, y)
            lm = out.get("on_landmark")
            if bm is None and lm:  # one made on its landmark, which stands up to LANDMARK_NODE_REACH away (self review)
                bm = self.bookmark_at(lm["x"], lm["y"])
            out["bookmark"] = bm
            # its own name, group and note with it: the page edits it from these (with the list's, which comes
            # separately, an edit could pair this id with another moment's list, or guess them before it loaded:
            # CodeRabbit)
            if bm is not None:
                b = self._bookmark(bm)
                out["bookmark_of"] = {"id": bm, "name": b["name"], "group": bm_group(b), "note": b.get("note", "")}
            # a map with a landmark is named after it ("Vaal city", not "Map #12")
            named = ("landmark", lm["id"]) if lm else (kind, i)
            out["suggest"] = (
                dict(zip(("name", "group"), self.default_name(*named), strict=True)) if kind != "path" else None
            )
        return out

    # ------------------------------------------------------------------ clicking
    def _landmark_lines(self, i: int) -> list[str]:
        """Return a landmark's detail lines: how it was found, its city type's source, why it is this kind."""
        lm, D = self.V["landmarks"][i], self.D
        n_seen = lm.get("n", 0)  # (a landmark added by hand has no counts)
        lines = [
            f"found in {n_seen} of {lm.get('could', n_seen)} screenshot(s)",
            f"confidence {lm.get('conf', 1.0):.2f}, detected by {lm.get('source', 'you')}",
        ]
        ct = D.get("city_type", {}).get(i)
        if ct:
            lines.append(
                {
                    "set": "type set by hand",
                    "trio": "type from its trio: the cities next to it are the other two types",
                    "look-alike": "type guessed by look; set it by hand if wrong",
                }.get(ct[1], ct[1])
            )
        if i in D.get("locked", ()):
            lines.append("locked (hand badge): only its ground shows, no maps yet")
        if lm.get("beam"):
            lines.append(f"{lm['kind']} because: {lm['beam']}")
        if lm["status"] != "kept":
            lines.append(lm["status"])
        return lines

    def pick(self, x: float, y: float, z: float, layers: dict | None = None) -> tuple[str, int] | None:
        """Find what is under a point: bookmark, then the nearest icon or landmark, then a map (clickable even when
        hidden), then a path, then anywhere inside a city / stronghold biome circle.

        Args:
            x: Atlas x of the click.
            y: Atlas y of the click.
            z: Screen px per atlas unit (the map's zoom).
            layers: Layer name -> shown (default: the saved layers).

        Returns:
            (kind, index), or None.
        """
        if not self.atlas:
            return None
        L = layers or self.ui_settings()["layers"]
        fl = self._flags()
        style = self.ui_settings()["style"]
        best, bd = None, 1e9
        if L.get("Bookmarks", True):
            for i, b in self.bookmarks_by_id():
                if self.bookmark_shown(b) and not b.get("route"):  # (a saved route has no pin to click)
                    d = math.hypot((b["x"] - x) * z, (b["y"] - y) * z + 14)
                    if d < 16 and d < bd:
                        best, bd = ("bookmark", i), d
        if best:
            return best
        pts = self.D.get("icon_pts")
        if L.get("Icons", True) and pts is not None and len(pts):
            d = np.hypot(pts[:, 0] - x, pts[:, 1] - y) * z
            for i in np.argsort(d)[:8]:
                if d[i] < max(9, 15 * z) and self.icon_visible(int(i), fl):
                    best, bd = ("icon", int(i)), float(d[i])
                    break
        if L.get("Landmarks", True):
            s = max(0.12, z)
            hw, top, bot = max(5, 30 * s), max(8, 60 * s), max(2, 10 * s)
            for i, lm in enumerate(self.V["landmarks"]):
                if not self.landmark_shown(i, fl):
                    continue
                px, py = (x - lm["x"]) * z, (y - lm["y"]) * z
                if -hw <= px <= hw and -top <= py <= bot:
                    d = math.hypot(px, py + top / 2)
                    if d < bd:
                        best, bd = ("landmark", i), d
        npts = self.D.get("node_pts")
        if npts is not None and len(npts):
            d = np.hypot(npts[:, 0] - x, npts[:, 1] - y) * z
            r = float(min(13, max(2, 8 * z))) * float(style.get("map_size", 1.0))
            for i in np.argsort(d)[:5]:
                if self.V["nodes"][i]["status"] == "removed":
                    continue
                if d[i] < max(10, r + 5) and (d[i] < bd or (best and best[0] == "landmark")):
                    best, bd = ("node", int(i)), float(d[i])
                break
        if best is None and L.get("Paths", True) and self.V["paths"]:
            best = self._pick_path(x, y, z, fl)
        potential = self.D.get("potential", {})
        if best is None and L.get("City & stronghold biomes", True) and potential and npts is not None:
            ids = [v for v, (lab, _st) in potential.items() if _pkind(lab) not in fl["hidden"]]
            if ids:
                d = np.hypot(npts[ids, 0] - x, npts[ids, 1] - y) * z
                k = int(np.argmin(d))
                if d[k] <= max(4, int(44 * z)):
                    best = ("node", int(ids[k]))
        return best

    def _pick_path(self, x: float, y: float, z: float, fl: dict) -> tuple[str, int] | None:
        """Return the shown path within 7 screen px of a point.

        Args:
            x: Atlas x.
            y: Atlas y.
            z: Screen px per atlas unit.
            fl: _flags().

        Returns:
            ("path", index), or None.
        """
        N = self.V["nodes"]
        node_ok = [self.node_shown(n, fl) for n in N]
        q = np.array([x, y], float)
        best, bd = None, 7.0 / max(z, 1e-9)
        for k, p in enumerate(self.V["paths"]):
            if not self.path_shown(p, node_ok, fl):
                continue
            L = np.array(p.get("line") or [[N[p["a"]]["x"], N[p["a"]]["y"]], [N[p["b"]]["x"], N[p["b"]]["y"]]], float)
            L[0], L[-1] = (N[p["a"]]["x"], N[p["a"]]["y"]), (N[p["b"]]["x"], N[p["b"]]["y"])
            lo, hi = L.min(axis=0) - bd, L.max(axis=0) + bd
            if not (lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]):
                continue
            a, b = L[:-1], L[1:]
            ab = b - a
            t = np.clip(((q - a) * ab).sum(1) / np.maximum(1e-9, (ab * ab).sum(1)), 0, 1)
            d = float(np.min(np.hypot(*(a + t[:, None] * ab - q).T)))
            if d < bd:
                best, bd = ("path", k), d
        return best

    # ------------------------------------------------------------------ Find
    def _hit_rows(self, hits: list[tuple[str, int]], notes: list[str] | None = None) -> list[dict]:
        """Turn hits into result rows, each as the page names it (the Selected window's title, with no counts), with
        its picture, the map it is on and that map's icons (user: rows like "icon  text", a map with all its icons).
        Only near a city when that is ticked.

        Args:
            hits: (kind, index) pairs.
            notes: A line under each one's name (None: where it is).

        Returns:
            [{"kind", "id", "label", "x", "y", "icon", "map", "icons", "note", "bookmarked"}]: "icon" the raw name
            of its picture (None: the page's own: a map's art, a bookmark's sign), "icons" [{"name", "label"}].
        """
        from .constants import PLACE_ICON

        near = self.ui_settings()["near_only"]
        nc = self.D.get("near_city", {})
        rows = []
        for k, (kind, i) in enumerate(hits):
            v = self.item_node(kind, i)
            city = kind == "landmark" and "city" in str(self.V["landmarks"][i].get("kind", "")).lower()
            if near and not city and not self.near_city_text(v):
                continue
            x, y = self.item_pos(kind, i)
            # a landmark's map too (item_node has none for it), for its map and icons (CodeRabbit)
            if kind == "landmark":
                v = self.D.get("landmark_node", {}).get(i)
            icons = self.V["nodes"][v].get("icons", []) if v is not None and kind != "bookmark" else []
            icon = None
            if kind == "node":
                label = f"Map #{i}"  # (its icons follow it as pictures, named in their tooltips)
            elif kind == "landmark":
                label = self.landmark_name(i)
                kind_of = self.V["landmarks"][i]["kind"]
                icon = PLACE_ICON.get(label.rstrip("?")) or PLACE_ICON.get(kind_of)
            elif kind == "icon":
                ic = self.V["icons"][i]
                label, icon = icon_label(ic), ic["name"]
            else:
                b = self._bookmark(i)
                label = b["name"]
            note = notes[k] if notes and notes[k] else ""
            if not note:
                if kind == "bookmark":
                    note = bm_group(self._bookmark(i))
                elif kind != "node" and v is not None:
                    note = f"on map #{v}"
            t = nc.get(v)
            if t and kind == "icon":
                note += f" · ⌂ {t[0]}" + ("" if t[1] == 0 else " +1")
            rows.append(
                {
                    "kind": kind,
                    "id": i,
                    "label": label,
                    "x": x,
                    "y": y,
                    "icon": icon,
                    "map": v if kind != "bookmark" else None,
                    "icons": [{"name": r, "label": icon_name(r)} for r in icons],
                    "note": note,
                    "bookmarked": kind != "bookmark" and self.bookmark_at(x, y) is not None,
                }
            )
        return rows

    def search(self, q: str) -> dict:
        """Search the atlas: "x, y" goes there; else bookmarks (name, group, note), landmarks, icons (name or alias),
        maps by their icons, potential city / stronghold maps, and "#<n>" for map n. Loosely: words in any order, a
        typo, letters left out (find_score); the best matches first.

        Args:
            q: The search text.

        Returns:
            {"goto": [x, y]} for coordinates, else {"results": [rows]}.
        """
        q = q.strip().lower()
        if not self.atlas or not q:
            return {"results": []}
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*", q)
        if m:
            return {"goto": [float(m.group(1)), float(m.group(2))]}
        m = re.fullmatch(r"#\s*(\d+)|map\s*#?\s*(\d+)", q)
        if m:
            n = int(m.group(1) or m.group(2))
            return {"results": self._hit_rows([("node", n)]) if n < len(self.V["nodes"]) else []}
        found: dict[tuple[str, int], tuple[float, int, str]] = {}  # hit: (score, order, note), each hit once

        def add(score: float | None, hit: tuple[str, int], note: str = "") -> None:
            if score is not None and (hit not in found or score > found[hit][0]):
                found[hit] = (score, found[hit][1] if hit in found else len(found), note)

        for i, b in self.bookmarks_by_id():
            add(find_score(q, b["name"], f"{bm_group(b)} {b.get('note', '')}"), ("bookmark", i))
        for i, lm in enumerate(self.V["landmarks"]):
            if not lm["status"].startswith("removed"):
                add(find_score(q, self.landmark_name(i)), ("landmark", i))
        for i, ic in enumerate(self.V["icons"]):
            add(find_score(q, icon_label(ic), icon_aliases(ic["name"])), ("icon", i))
        # a map by its icons (user: "abyss" with Maps on found nothing: only the icons were searched)
        potential = self.D.get("potential", {})
        for v, n in enumerate(self.V["nodes"]):
            if n["status"] == "removed":
                continue
            note = self.potential_text(v) if potential.get(v, ("", 0))[1] else ""
            for raw in n.get("icons", []):
                add(find_score(q, icon_name(raw), icon_aliases(raw)), ("node", v), note)
        for v, (lab, st) in potential.items():
            if st:
                add(find_score(q, _pkind(lab)) if len(q) >= 4 else None, ("node", v), self.potential_text(v))
        best = sorted(found.items(), key=lambda f: (-f[1][0], f[1][1]))
        return {"results": self._hit_rows([h for h, _f in best], [f[2] for _h, f in best])}

    def list_type(self, label: str) -> list[dict]:
        """List every map / place of one type (a type row clicked in Find).

        Args:
            label: A potential type, "<type> city", a place type, or an icon label.

        Returns:
            Result rows.
        """
        hits, notes = [], []
        D = self.D
        if label in POTENTIAL_TYPES:
            for v, (lab, st) in sorted(D.get("potential", {}).items(), key=lambda t: (t[1][0], t[1][1])):
                if st and _pkind(lab) == label:
                    hits.append(("node", v))
                    notes.append(self.potential_text(v))
        elif label.endswith(" city"):
            for i, (t, how) in D.get("city_type", {}).items():
                if f"{t} city" == label:
                    hits.append(("landmark", i))
                    v = D.get("landmark_node", {}).get(i)
                    where = f"on map #{v} · " if v is not None else ""
                    notes.append(where + ("type set by hand" if how == "set" else f"type from its {how}"))
        elif label in D.get("place_types", []):
            for i, lm in enumerate(self.V["landmarks"]):
                if lm["kind"] == label and not lm["status"].startswith("removed"):
                    hits.append(("landmark", i))
                    notes.append("")
        else:
            for i, ic in enumerate(self.V["icons"]):
                if icon_label(ic) == label:
                    hits.append(("icon", i))
                    notes.append("")
        return self._hit_rows(hits, notes)

    def types(self) -> dict:
        """Return Find's type list: "Places" and "Map icons", with counts (only near a city when ticked), the
        icon picture of each and whether it is shown.

        Returns:
            {"sections": [{"title", "rows": [{"label", "count", "icon", "shown", "aliases"}]}]}.
        """
        from .constants import PLACE_ICON

        D = self.D
        counts = dict(D.get("counts", {}))
        if self.ui_settings()["near_only"]:
            near = {}
            fl = {**self._flags(), "hidden": set()}
            for i, ic in enumerate(self.V["icons"]):
                if self.icon_visible(i, {**fl, "near": True}):
                    near[icon_label(ic)] = near.get(icon_label(ic), 0) + 1
            for k in ("City", "Ezomyte city", "Vaal city", "Faridun city", "Potential city map"):
                if k in counts:
                    near[k] = counts[k]
            counts = near
        hidden = set(self.ui_settings()["hidden_types"])
        raw_of: dict[str, str] = {}
        for ic in self.V["icons"]:
            raw_of.setdefault(icon_label(ic), ic["name"])
        sections = []
        for title, labels in (("Places", D.get("place_types", [])), ("Map icons", D.get("icon_types", []))):
            rows = [
                {
                    "label": lab,
                    "count": counts.get(lab, 0),
                    "icon": (PLACE_ICON.get(lab) if title == "Places" else raw_of.get(lab)) or "Unidentified",
                    "shown": lab not in hidden,
                    "aliases": icon_aliases(raw_of[lab]) if lab in raw_of else "",
                }
                for lab in labels
                if lab in counts
            ]
            if rows:
                sections.append({"title": title, "rows": rows})
        return {"sections": sections}

    # ------------------------------------------------------------------ screenshots of a spot
    def frames_at(self, x: float, y: float) -> list[tuple[dict, float, float]]:
        """Find the screenshots that cover a spot, best view first (the spot nearest their middle).

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            (frame dict, x, y in its px) per screenshot.
        """
        out = []
        for f in self.atlas.frames if self.atlas else []:
            H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            p = core.persp(np.linalg.inv(H), [[x, y]])[0]
            if 0 <= p[0] < f["w"] and 0 <= p[1] < f["h"]:
                out.append((f, float(p[0]), float(p[1])))
        out.sort(key=lambda t: max(abs(t[1] / t[0]["w"] - 0.5), abs(t[2] / t[0]["h"] - 0.5)))
        return out

    def sources(self, x: float, y: float) -> list[dict]:
        """Return the screenshots that show a spot (Screenshots of this spot).

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            [{"name", "w", "h", "px", "py" (the spot in its px), "exists"}].
        """
        return [
            {"name": f["name"], "w": f["w"], "h": f["h"], "px": px, "py": py, "exists": Path(f["path"]).exists()}
            for f, px, py in self.frames_at(x, y)
        ]

    def screenshot_jpeg(self, name: str, width: int = 0) -> bytes | None:
        """Return a screenshot of the atlas as JPEG, scaled down to a width.

        Args:
            name: Its name in atlas.frames.
            width: Width in px (0: full size).

        Returns:
            The JPEG bytes, or None when unknown or missing.
        """
        f = next((f for f in (self.atlas.frames if self.atlas else []) if f["name"] == name), None)
        if f is None:
            return None
        img = core.read_screenshot(f["path"])
        if img is None:
            return None
        if 0 < width < img.shape[1]:
            img = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------------ routes
    def graph(self) -> dict:
        """Return the map graph the page finds routes on: the maps shown and the paths between them.

        Returns:
            {"nodes": [{"id", "x", "y", "icons", "status"}], "edges": [{"a", "b", "line"?}]}.
        """
        fl = self._flags()
        N = self.V["nodes"]
        ok = [self.node_shown(n, fl) for n in N]
        nodes = [
            {"id": i, "x": n["x"], "y": n["y"], "icons": sorted(set(n.get("icons") or [])), "status": n["status"]}
            for i, n in enumerate(N)
            if ok[i]
        ]
        edges = []
        for p in self.V["paths"]:
            if self.path_shown(p, ok, fl):
                e = {"a": p["a"], "b": p["b"]}
                if len(p.get("line") or []) > 2:
                    e["line"] = p["line"]
                edges.append(e)
        return {"nodes": nodes, "edges": edges}


def _pkind(label: str) -> str:
    """Return the Find type a biome's potential map is listed under.

    Args:
        label: Biome label.

    Returns:
        "Potential stronghold map" or "Potential city map".
    """
    return "Potential stronghold map" if label == "Breach stronghold" else "Potential city map"


def _words(text: str) -> list[str]:
    """The words of a text, lower case, without punctuation ("Map #12: Breach" -> map, 12, breach); any letters
    (a bookmark named "東京" is one word: CodeRabbit)."""
    return re.findall(r"[^\W_]+", text.lower())


def _close(a: str, b: str) -> bool:
    """Whether two words are the same but for a typo or two (4+ letters: a short word must be right)."""
    from difflib import SequenceMatcher

    return len(a) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.8


def find_score(q: str, name: str, more: str = "") -> float | None:
    """How well Find's text matches a thing, loosely (user: the search was not fuzzy): None for no match, else higher
    for better. In its name the whole text, then its words in any order (each the start of a word, or in one), then
    words with a typo, then its letters in order close together ("abys dep" and "abydep" find "Abyssal Depths");
    in its other words (aliases, a bookmark's group or note) the same, lower.

    Args:
        q: The search text, lower case.
        name: The thing's name.
        more: Its other words.

    Returns:
        The score, or None.
    """
    best = None
    for text, weight in ((name, 0), (more, -15)):
        t = text.lower()
        if not t.strip():
            continue
        words = _words(t)
        qw = _words(q)
        # the text as typed first, whatever it is made of (punctuation only too)
        if t.strip() == q:
            score = 110
        elif q in t:
            score = 100 if t.startswith(q) else 90
        elif not qw:
            score = None
        elif all(any(w.startswith(x) for w in words) for x in qw):
            score = 80
        elif all(any(x in w for w in words) for x in qw):
            score = 70
        elif all(any(w.startswith(x) or x in w or _close(x, w) for w in words) for x in qw):
            score = 60
        else:
            score = _in_order(q.replace(" ", ""), "".join(words))
        if score is not None and (best is None or score + weight > best):
            best = score + weight
    return best


def _in_order(q: str, t: str) -> float | None:
    """q's letters in t in order, close together (3+ letters, the span at most twice q's length): 40, or None."""
    if len(q) < 3:
        return None
    start = t.find(q[0])
    while start >= 0:
        k, j = 0, start
        # (no further than a match may reach: a long note costs no more: CodeRabbit)
        while j < len(t) and k < len(q) and j - start < 2 * len(q):
            if t[j] == q[k]:
                k += 1
            j += 1
        if k == len(q) and j - start <= 2 * len(q):
            return 40.0
        start = t.find(q[0], start + 1)
    return None
