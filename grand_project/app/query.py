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
            "bookmark": len(self.atlas.bookmarks) if self.atlas else 0,
        }.get(kind, 0)
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
        n = src[i] if src is not None else self.atlas.bookmarks[i]
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
        lines: list[str] = []
        out: dict = {"kind": kind, "id": i}
        if kind == "node":
            n = V["nodes"][i]
            deg = [p for p in V["paths"] if i in (p["a"], p["b"])]
            multi = sum(p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends", False) for p in deg)
            icons = ", ".join(icon_name(k) for k in n.get("icons", []))
            out["title"] = f"Map #{i}" + (f": {icons}" if icons else "")
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
            lines += [
                f"found in {lm['n']} of {lm.get('could', lm['n'])} screenshot(s)",
                f"confidence {lm['conf']:.2f}, detected by {lm.get('source', '')}",
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
            b = self.atlas.bookmarks[i]
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
            out["bookmark"] = bm
            out["suggest"] = (
                dict(zip(("name", "group"), self.default_name(kind, i), strict=True)) if kind != "path" else None
            )
        return out

    # ------------------------------------------------------------------ clicking
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
            for i, b in enumerate(self.atlas.bookmarks):
                if self.bookmark_shown(b):
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
    def _hit_rows(self, hits: list[tuple[str, int]], labels: list[str]) -> list[dict]:
        """Turn hits into result rows: only near a city when that is ticked; ⌂ for icons near a city, ★ for
        items with a bookmark on them.

        Args:
            hits: (kind, index) pairs.
            labels: One text per hit.

        Returns:
            [{"kind", "id", "label", "x", "y"}].
        """
        near = self.ui_settings()["near_only"]
        nc = self.D.get("near_city", {})
        rows = []
        for (kind, i), label in zip(hits, labels, strict=True):
            v = self.item_node(kind, i)
            city = kind == "landmark" and "city" in str(self.V["landmarks"][i].get("kind", "")).lower()
            if near and not city and not self.near_city_text(v):
                continue
            t = nc.get(v)
            if t and kind == "icon":
                label += f"   ⌂ {t[0]}" + ("" if t[1] == 0 else " +1")
            x, y = self.item_pos(kind, i)
            if kind != "bookmark" and self.bookmark_at(x, y) is not None:
                label = "★ " + label
            rows.append({"kind": kind, "id": i, "label": label, "x": x, "y": y})
        return rows

    def search(self, q: str) -> dict:
        """Search the atlas: "x, y" goes there; else bookmarks (name, group, note), landmarks, icons (name or alias),
        potential city / stronghold maps, and "#<n>" for map n.

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
        hits, labels = [], []
        for i, b in enumerate(self.atlas.bookmarks):
            if q in f"{b['name']} {bm_group(b)} {b.get('note', '')}".lower():
                hits.append(("bookmark", i))
                labels.append(f"[bookmark] {b['name']}  ({bm_group(b)})")
        for i, lm in enumerate(self.V["landmarks"]):
            if q in self.landmark_name(i).lower() and not lm["status"].startswith("removed"):
                hits.append(("landmark", i))
                labels.append(f"{self.landmark_name(i)}  (seen {lm.get('n', 1)}x)")  # (one added by hand has no count)
        for i, ic in enumerate(self.V["icons"]):
            nice = icon_label(ic)
            if q in nice.lower() or q in icon_aliases(ic["name"]):
                hits.append(("icon", i))
                labels.append(f"{nice}  (seen {ic['n']}x)")
        if len(q) >= 4 and q in "potential city map potential stronghold map":
            for v, (lab, st) in self.D.get("potential", {}).items():
                if st and q in _pkind(lab).lower():
                    hits.append(("node", v))
                    labels.append(self.potential_text(v))
        m = re.fullmatch(r"#(\d+)", q)
        if m and int(m.group(1)) < len(self.V["nodes"]):
            hits.append(("node", int(m.group(1))))
            labels.append(f"Map #{m.group(1)}")
        return {"results": self._hit_rows(hits, labels)}

    def list_type(self, label: str) -> list[dict]:
        """List every map / place of one type (a type row clicked in Find).

        Args:
            label: A potential type, "<type> city", a place type, or an icon label.

        Returns:
            Result rows.
        """
        hits, labels = [], []
        D = self.D
        if label in POTENTIAL_TYPES:
            for v, (lab, st) in sorted(D.get("potential", {}).items(), key=lambda t: (t[1][0], t[1][1])):
                if st and _pkind(lab) == label:
                    hits.append(("node", v))
                    labels.append(self.potential_text(v))
        elif label.endswith(" city"):
            for i, (t, how) in D.get("city_type", {}).items():
                if f"{t} city" == label:
                    hits.append(("landmark", i))
                    labels.append(f"{self.landmark_name(i)}  ({'set by hand' if how == 'set' else how})")
        elif label in D.get("place_types", []):
            for i, lm in enumerate(self.V["landmarks"]):
                if lm["kind"] == label and not lm["status"].startswith("removed"):
                    hits.append(("landmark", i))
                    labels.append(f"{lm['kind']}  (seen {lm['n']}x)")
        else:
            for i, ic in enumerate(self.V["icons"]):
                if icon_label(ic) == label:
                    hits.append(("icon", i))
                    labels.append(f"{label}  (seen {ic['n']}x)")
        return self._hit_rows(hits, labels)

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
