"""finalize.landmarks (from atlas_finalize.py)"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import gold_paths as gp

from .constants import (
    BARREL_BLUE,
    BARREL_LIT,
    BARREL_NCC,
    BARREL_SAT,
    CITY_BASE,
    EXCLUSIVE,
    FRAME_MARGIN,
    ICON_DUP,
    OCEAN_R,
    OCEAN_WATER,
    PARALLAX_TOL,
    SETTLE_BADGE,
    SETTLE_MERGE,
)
from .traces import _Grid, _visible

_city_tpl = None


def _barrel(img, x, y, blue_lit: bool = False) -> bool:
    """is the map base at screen (x, y) the brass barrel of a City (Halls stand on a normal base)?"""
    global _city_tpl
    if _city_tpl is None:
        t = cv2.imdecode(np.fromfile(str(CITY_BASE), np.uint8), cv2.IMREAD_COLOR)
        _city_tpl = cv2.cvtColor(t, cv2.COLOR_BGR2LAB).astype(np.float32)
    th, tw = _city_tpl.shape[:2]
    X, Y, P = int(round(x)), int(round(y)), 12
    w = img[Y - 24 - P : Y - 24 + th + P, X - tw // 2 - P : X - tw // 2 + tw + P]
    if w.shape[:2] != (th + 2 * P, tw + 2 * P):
        return False
    r = cv2.matchTemplate(cv2.cvtColor(w, cv2.COLOR_BGR2LAB).astype(np.float32), _city_tpl, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _l, (ax, ay) = cv2.minMaxLoc(r)
    body = cv2.cvtColor(w[ay : ay + th, ax : ax + tw], cv2.COLOR_BGR2HSV)[26:50, 14:46]
    hue = float(np.median(body[..., 0]))
    # brass, not blue: the silver star base of ocean maps with its blue core also fits the template
    # (crawl cities: barrel hue 17-24; ocean star bases 95-103) - unless a blue beam above lights the
    # barrel blue (a slanted City beam: hue 101, only ~75-113 beam px in the column)
    blue = BARREL_BLUE[0] <= hue <= BARREL_BLUE[1]
    return mx >= BARREL_NCC and float(body[..., 1].mean()) >= BARREL_SAT and (blue_lit or not blue)


_ocean_img = [None, None]


def _ground_classes(hsv: np.ndarray) -> np.ndarray:
    """per-pixel ground class: 0 water, 1 sand, 2 rock / snow, 3 grass, 4 forest, -1 unknown"""
    H, S, V = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    out = np.full(H.shape, -1, int)
    out[(H >= 78) & (H <= 112) & (S >= 85) & (V >= 50)] = 0  # water (blue-grey rock shadow is less saturated)
    out[(H >= 10) & (H <= 30) & (S >= 25) & (S <= 140) & (V >= 135)] = 1  # sand / desert
    out[(S < 40) & (V >= 95)] = 2  # rock / snow
    out[(H >= 30) & (H <= 55) & (S >= 70) & (V >= 95)] = 3  # bright grass
    out[(H >= 33) & (H <= 90) & (S >= 50) & (V >= 30) & (V < 95)] = 4  # dark forest
    return out


def _ocean(img, x, y) -> bool:
    """is (x, y) in the ocean / Expedition biome? There are NO cities there (nor corruption / cleansed),
    user's rule. Judged by open water around the map (an ocean map may sit on an island, so a wide circle)."""
    if _ocean_img[0] is not img:
        cls = _ground_classes(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
        bad = (
            (gp.gold_stroke_mask(img) > 0) | (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 22) | (core._valid_mask(img) == 0)
        )
        _ocean_img[0], _ocean_img[1] = img, (cls, bad)
    cls, bad = _ocean_img[1]
    h, w = cls.shape
    X, Y, R = int(round(x)), int(round(y)), OCEAN_R
    x0, x1, y0, y1 = max(0, X - R), min(w, X + R + 1), max(0, Y - R), min(h, Y + R + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = (np.hypot(xx - X, yy - Y) <= R) & ~bad[y0:y1, x0:x1]
    c = cls[y0:y1, x0:x1][m]
    c = c[c >= 0]
    return len(c) > 200 and float((c == 0).mean()) >= OCEAN_WATER


def _guessed(n: dict) -> set:
    """screenshots that only guessed this map (a hidden map from a badge row, no base seen). Atlases built
    before v0.80 have no "guessed_in": then the badge-row sightings are taken from the sources list, which
    runs parallel to the frames list."""
    if "guessed_in" in n:
        return set(n["guessed_in"])
    fr, src = list(n.get("frames", [])), list(n.get("sources", []))
    return {f for f, s in zip(fr, src, strict=False) if s == "badge row"} if len(fr) == len(src) else set()


def _one_map(maps_by, a, b, ignore=()) -> bool:
    """Two sightings (never in the same screenshot) are one object seen with parallax / a revisit offset
    when the screenshots that found one of them also show the other's spot, yet found only one there.
    A screenshot where the other spot is out of view (edge, HUD) has no say; each side needs at least one
    screenshot that does show the other spot (a map at a screen edge used to block the join)."""
    for this, other in ((a, b), (b, a)):
        shown = 0
        for name in this["frames"]:
            if name in ignore:  # a screenshot that found both proves nothing either way
                continue
            if name not in maps_by:
                return False
            f, Hi = maps_by[name]
            shown += bool(_visible(f, Hi, [[other["x"], other["y"]]], margin=FRAME_MARGIN)[1][0])
        if not shown:
            return False
    return True


def _clean_icons(atlas, maps) -> list[dict]:
    """Merge copies of one badge from different screenshots; drop Lost-tower matches (towers are
    landmarks, and the Lost-tower icon also matches Hall / City artwork)."""
    maps_by = {f["name"]: (f, Hi) for f, Hi in maps}
    icons = [dict(ic, frames=list(ic["frames"])) for ic in atlas.icons if ic["name"] != "LostTower"]
    alive = [True] * len(icons)
    pairs = []
    for d, i, j in _Grid([[ic["x"], ic["y"]] for ic in icons], PARALLAX_TOL).pairs(PARALLAX_TOL):
        a, b = icons[i], icons[j]
        if a["name"] != b["name"] and "Unidentified" not in (a["name"], b["name"]):
            continue
        if d < PARALLAX_TOL:
            pairs.append((d, i, j))
    for d, i, j in sorted(pairs):
        if not (alive[i] and alive[j]) or set(icons[i]["frames"]) & set(icons[j]["frames"]):
            continue  # seen together in one screenshot: two real badges
        a, b = icons[i], icons[j]
        if d >= ICON_DUP and not _one_map(maps_by, a, b):
            continue
        wa, wb = a["n"], b["n"]
        a["spread"] = max(a.get("spread", 0.0), b.get("spread", 0.0), float(d))  # how far its copies lay apart
        for key in ("x", "y", "bx", "by"):
            a[key] = (a[key] * wa + b[key] * wb) / (wa + wb)
        a["n"] = wa + wb
        a["frames"] = sorted(set(a["frames"]) | set(b["frames"]))
        if a["name"] == "Unidentified":
            a["name"], a["source"] = b["name"], b["source"]
        a["score"] = max(a["score"], b["score"])
        alive[j] = False
    icons = [ic for ic, ok in zip(icons, alive, strict=False) if ok]
    pts = np.array([[ic["x"], ic["y"]] for ic in icons], float).reshape(-1, 2)
    could = np.zeros(len(icons), int)
    for f, Hi in maps:
        could += _visible(f, Hi, pts, margin=FRAME_MARGIN)[1]
    for ic, c in zip(icons, could, strict=False):
        ic["could"] = int(max(c, ic["n"]))
    return icons


def _beam(img, x, y, spread=0):
    """blue / orange beam pixels in a narrow column above (x, y); with spread, the best column
    within +-spread px (a special-boss badge sits next to its building, not under the beam)"""
    h, w = img.shape[:2]
    # a building's own beam rises right above it; for a badge-only spot look only low down, so a
    # different Hall / City higher up the screen (whose beam is in the same column) doesn't count
    y0, y1 = int(max(0, y - (150 if spread else 330))), int(max(0, y - 40))
    if y1 - y0 < 40:
        return 0, 0
    best = (0, 0)
    for cx in range(int(x - spread), int(x + spread) + 1, 20) if spread else [int(x)]:
        x0, x1 = max(0, cx - 22), min(w, cx + 22)
        if x1 <= x0:
            continue
        hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        blue = int(((H >= 90) & (H <= 130) & (S >= 60) & (V >= 140)).sum())
        orange = int((((H <= 22) | (H >= 170)) & (S >= 110) & (V >= 150)).sum())
        if blue + orange > sum(best):
            best = (blue, orange)
    return best


def _settlements(atlas, maps, landmarks, icons) -> list[dict]:
    """Hall and City are the same kind of place with a special boss (user's rules): both have a
    Deadly Map Boss badge (without one it is neither: removed); a City's map stands on a brass
    barrel and usually has a blue beam (red beams happen too); a Hall has a normal map base with
    the beam on a structure next to it.  Nearby detections are one building."""
    keep = [lm for lm in landmarks if lm["kind"] not in ("City", "Hall")]
    cand = [lm for lm in landmarks if lm["kind"] in ("City", "Hall") and not lm["status"].startswith("removed: abyss")]
    groups: list[list[dict]] = []
    for lm in sorted(cand, key=lambda landmark: -landmark["n"]):
        for g in groups:
            if math.hypot(g[0]["x"] - lm["x"], g[0]["y"] - lm["y"]) < SETTLE_MERGE:
                g.append(lm)
                break
        else:
            groups.append([lm])
    focus = getattr(atlas, "_focus", None)  # local re-check: far ones are not kept anyway
    if focus:
        groups = [g for g in groups if focus[1](g[0]["x"], g[0]["y"])]
    buildings = []
    for g in groups:
        n = sum(landmark["n"] for landmark in g)
        votes = {}
        for landmark in g:
            votes[landmark["kind"]] = votes.get(landmark["kind"], 0) + landmark["n"]
        buildings.append(
            {
                "x": sum(landmark["x"] * landmark["n"] for landmark in g) / n,
                "y": sum(landmark["y"] * landmark["n"] for landmark in g) / n,
                "n": n,
                "conf": max(landmark["conf"] for landmark in g),
                "source": g[0].get("source", ""),
                "detected": votes,
                "spread": 0,
            }
        )
    # (a special-boss badge on its own is NOT a settlement: the red spiky trees carry one too)
    deadly = [ic for ic in icons if ic["name"] == "MapBossSpecial"]
    for b in buildings:
        near = sorted((math.hypot(ic["x"] - b["x"], ic["y"] - b["y"]), k) for k, ic in enumerate(deadly))
        badge = deadly[near[0][1]] if near and near[0][0] < SETTLE_BADGE else None
        clash = None
        if badge is not None:  # its map carries another exclusive type's badge
            bx0, by0 = badge.get("bx", badge["x"]), badge.get("by", badge["y"])
            clash = next(
                (
                    EXCLUSIVE[ic["name"]]
                    for ic in icons
                    if ic["name"] in EXCLUSIVE
                    and math.hypot(ic.get("bx", ic["x"]) - bx0, ic.get("by", ic["y"]) - by0) < 30
                ),
                None,
            )
            if clash:
                badge = None
        barrel = False
        if badge is not None:
            bx, by = badge.get("bx", badge["x"]), badge.get("by", badge["y"] + 24)
            for _c, f, sp in atlas.central_views(bx, by, 3):
                im = atlas.image(f["path"]) if Path(f["path"]).exists() else None
                if im is not None and _barrel(
                    im, sp[0], sp[1], max(_beam(im, sp[0], sp[1])[0], _beam(im, sp[0], sp[1], 80)[0]) >= BARREL_LIT
                ):
                    barrel = True
                    break
        views = [
            (atlas.image(f["path"]), sp)
            for _c, f, sp in atlas.central_views(b["x"], b["y"], 3)
            if Path(f["path"]).exists()
        ]
        ocean = bool(views) and 2 * sum(_ocean(im, sp[0], sp[1]) for im, sp in views) > len(views)
        blue = orange = seen = 0
        for f, Hi in maps:
            sp, ok = _visible(f, Hi, [[b["x"], b["y"]]], margin=5)
            if ok[0]:
                bl, orr = _beam(atlas.image(f["path"]), sp[0, 0], sp[0, 1], b["spread"])
                blue, orange, seen = blue + bl, orange + orr, seen + 1
        status = "kept"
        if badge is None and not clash and b["detected"].get("City", 0) >= b["detected"].get("Hall", 0):
            # a completed City loses its badge (and beam): a green map with only its citadel
            kind, why = "City", "no Deadly Map Boss badge: completed city?"
        elif badge is None:
            kind, why = "Hall", f"its map is a {clash} map" if clash else "no Deadly Map Boss badge"
            status = f"removed: {why} (not a Hall or City)"
        elif blue >= 60 and blue > 1.5 * orange:
            kind, why = "City", "blue beam"
        elif barrel:
            kind, why = "City", "brass barrel map base"
        else:
            kind, why = "Hall", "normal map base" + (", orange beam" if orange >= 100 else "")
        if ocean and kind == "City":
            kind, why = "Deadly boss map", f"ocean (Expedition) biome: never a City (was: {why})"
            if badge is None:
                status = "removed: ocean biome, no badge (not a Hall or City)"
        keep.append(
            {
                "kind": kind,
                "x": b["x"],
                "y": b["y"],
                "n": b["n"],
                "conf": b["conf"],
                "source": b["source"],
                "status": status,
                "beam": why,
                "beam_px": [blue, orange],
                "could": max(seen, b["n"]),
            }
        )
    return keep
