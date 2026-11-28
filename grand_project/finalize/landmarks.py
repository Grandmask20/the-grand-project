"""finalize.landmarks (from atlas_finalize.py)"""

from __future__ import annotations

import math
import weakref

import cv2
import numpy as np

from grand_project import core
from grand_project import gold_paths as gp

from .constants import (
    EXCLUSIVE,
    FRAME_MARGIN,
    ICON_DUP,
    OCEAN_R,
    OCEAN_WATER,
    PARALLAX_TOL,
    SAME_MAP,
    SETTLE_BADGE,
    SETTLE_MERGE,
)
from .traces import _evict_oldest, _Grid, _visible


def _barrel(img, x, y, nodes=None) -> bool:
    """Tell whether the map base at screen (x, y) is the brass barrel of a City (Halls stand on a normal base).

    Uses detect.citybase, a model trained on the user's city screenshots.

    Args:
        img: the screenshot (BGR image).
        x: x of the map node in screen px.
        y: y of the map node in screen px.
        nodes: that screenshot's detected map nodes as an (N, 2) array in screen px, so a rough point is moved
            onto the map node's middle; None to use (x, y) as given.

    Returns:
        True when the barrel probability is >= CITY_P.
    """
    from grand_project.detect import citybase
    from grand_project.detect.constants import CITY_P

    return citybase.barrel_p(img, x, y, nodes) >= CITY_P


def _screen_nodes(atlas, f, x, y, reach: float = 80.0) -> np.ndarray:
    """Return the atlas's map nodes near atlas point (x, y), in screenshot f's pixels.

    A map node seen in few screenshots right next to a better-seen one (within SAME_MAP) is the same map (not
    yet merged): only the better-seen one counts, or a rough point could snap onto the stray copy a few px off
    the map's middle.

    Args:
        atlas: the core.Atlas.
        f: the screenshot (frame) dict.
        x: x of the point in atlas units.
        y: y of the point in atlas units.
        reach: how far from (x, y) map nodes are taken, per axis (atlas units).

    Returns:
        An (N, 2) array of map node positions in f's screen px (empty (0, 2) when none).
    """
    cand = sorted(
        (n for n in atlas.nodes if abs(n["x"] - x) < reach and abs(n["y"] - y) < reach),
        key=lambda n: -len(n.get("frames", [])),
    )
    near: list[list[float]] = []
    for n in cand:
        if all(math.hypot(n["x"] - a, n["y"] - b) > SAME_MAP for a, b in near):
            near.append([n["x"], n["y"]])
    if not near:
        return np.zeros((0, 2))
    Hi = np.linalg.inv(core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f)))
    return core.persp(Hi, near)


_OCEAN: dict = {}  # id(screenshot) -> (weak ref to it, ground classes, unusable pixels): recent ones kept
_OCEAN_KEEP = 24  # the re-check goes back and forth between screenshots (one kept: ~300 rebuilds per 80 adds)


def _ground_classes(hsv: np.ndarray) -> np.ndarray:
    """Classify each pixel's ground by colour.

    Args:
        hsv: the screenshot in OpenCV HSV (H 0-179, S and V 0-255), shape (h, w, 3).

    Returns:
        An (h, w) int8 array: 0 water, 1 sand, 2 rock / snow, 3 grass, 4 forest, -1 unknown (int8: _OCEAN_KEEP
        of them in int64 were ~380 MB, kept after every re-check).
    """
    H, S, V = hsv[..., 0].astype(np.int16), hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
    out = np.full(H.shape, -1, np.int8)
    out[(H >= 78) & (H <= 112) & (S >= 85) & (V >= 50)] = 0  # water (blue-grey rock shadow is less saturated)
    out[(H >= 10) & (H <= 30) & (S >= 25) & (S <= 140) & (V >= 135)] = 1  # sand / desert
    out[(S < 40) & (V >= 95)] = 2  # rock / snow
    out[(H >= 30) & (H <= 55) & (S >= 70) & (V >= 95)] = 3  # bright grass
    out[(H >= 33) & (H <= 90) & (S >= 50) & (V >= 30) & (V < 95)] = 4  # dark forest
    return out


def ground_of(img) -> tuple[np.ndarray, np.ndarray]:
    """Return a screenshot's per-pixel ground class and the pixels to ignore.

    Recent screenshots are kept (_OCEAN_KEEP).

    Args:
        img: the screenshot (BGR image); cached by object identity.

    Returns:
        (ground classes as in _ground_classes, bool mask of pixels to ignore: path dashes, black, outside the view),
        both of shape (h, w).
    """
    got = _OCEAN.get(id(img))
    # (a weak ref: the screenshot goes when the atlas's own cache lets it go, not kept here as well; the identity
    # check stays, an id can be reused)
    if got is None or got[0]() is not img:
        cls = _ground_classes(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
        bad = (
            (gp.gold_stroke_mask(img) > 0) | (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 22) | (core._valid_mask(img) == 0)
        )
        got = (weakref.ref(img), cls, bad)
        _OCEAN.pop(id(img), None)
        _OCEAN[id(img)] = got
        _evict_oldest(_OCEAN, _OCEAN_KEEP)  # (the idle release may clear it meanwhile)
    return got[1], got[2]


def _ocean(img, x, y) -> bool:
    """Tell whether (x, y) is in the ocean / Expedition biome.

    There are NO cities there (nor corruption / cleansed), user's rule. Judged by open water around the map
    (an ocean map may sit on an island, so a wide circle of OCEAN_R px).

    Args:
        img: the screenshot (BGR image).
        x: x of the map node in screen px.
        y: y of the map node in screen px.

    Returns:
        True when over 200 usable pixels lie in the circle and at least OCEAN_WATER of them are water.
    """
    cls, bad = ground_of(img)
    h, w = cls.shape
    X, Y, R = int(round(x)), int(round(y)), OCEAN_R
    x0, x1, y0, y1 = max(0, X - R), min(w, X + R + 1), max(0, Y - R), min(h, Y + R + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = (np.hypot(xx - X, yy - Y) <= R) & ~bad[y0:y1, x0:x1]
    c = cls[y0:y1, x0:x1][m]
    c = c[c >= 0]
    return len(c) > 200 and float((c == 0).mean()) >= OCEAN_WATER


def _guessed(n: dict) -> set:
    """Return the screenshots that only guessed this map (a hidden map from an icon row, no base seen).

    Atlases built before v0.80 have no "guessed_in": then the badge-row sightings are taken from the sources
    list, which runs parallel to the frames list.

    Args:
        n: the atlas map node dict (uses "guessed_in", or "frames" and "sources").

    Returns:
        A set of screenshot names (empty when the lists do not line up).
    """
    if "guessed_in" in n:
        return set(n["guessed_in"])
    fr, src = list(n.get("frames", [])), list(n.get("sources", []))
    return {f for f, s in zip(fr, src, strict=False) if s == "badge row"} if len(fr) == len(src) else set()


def _one_map(maps_by, a, b, ignore=()) -> bool:
    """Tell whether two sightings are one object seen with parallax / a revisit offset.

    Two sightings (never in the same screenshot) are one object when the screenshots that found one of them
    also show the other's spot, yet found only one there. A screenshot where the other spot is out of view
    (edge, HUD) has no say; each side needs at least one screenshot that does show the other spot (a map at
    a screen edge used to block the join).

    Args:
        maps_by: screenshot name -> (frame dict, atlas-to-screen homography).
        a: the first sighting (map node or icon dict with "x", "y" in atlas units and "frames").
        b: the second sighting, same shape.
        ignore: screenshot names to skip (ones that found both prove nothing either way).

    Returns:
        True when they are one object; False also when a finding screenshot is not in maps_by.
    """
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
    """Merge copies of one icon from different screenshots; drop Lost-tower matches.

    Towers are landmarks, and the Lost-tower icon also matches Hall / City artwork. Copies closer than
    PARALLAX_TOL with the same name (or one Unidentified) that no screenshot saw together are merged when
    closer than ICON_DUP or judged one object by _one_map; positions are weighted by sightings, "spread"
    records how far the copies lay apart.

    Args:
        atlas: the core.Atlas (uses atlas.icons).
        maps: list of (frame dict, atlas-to-screen homography) for every screenshot.

    Returns:
        A list of merged icon dicts (copies of atlas.icons) with "could" set: how many screenshots show the spot.
    """
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
    """Count blue / orange beam pixels in a narrow column (44 px wide) above (x, y).

    With spread, the best column within +-spread px is used (a special-boss icon sits next to its building,
    not under the beam), and only the 150 px above are searched instead of 330.

    Args:
        img: the screenshot (BGR image).
        x: x of the building in screen px.
        y: y of the building in screen px.
        spread: how far left / right to look for the beam column (screen px); 0 for just x.

    Returns:
        (blue pixel count, orange pixel count) of the best column; (0, 0) when too near the top.
    """
    _cx, blue, orange = _beam_column(img, x, y, spread)
    return blue, orange


def _beam_column(img, x, y, spread=0) -> tuple[int, int, int]:
    """Find the beam column of _beam: where it is, besides its blue / orange pixel counts.

    The dataset's hall box uses where it is: the hall structure stands under its beam (detect/proposals.py).

    Args:
        img: the screenshot (BGR image).
        x: x of the building in screen px.
        y: y of the building in screen px.
        spread: how far left / right to look for the beam column (screen px); 0 for just x.

    Returns:
        (x of the best column's middle, blue pixel count, orange pixel count); (round(x), 0, 0) when too near the
        top or no column holds a beam pixel.
    """
    h, w = img.shape[:2]
    # a building's own beam rises right above it; for a badge-only spot look only low down, so a
    # different Hall / City higher up the screen (whose beam is in the same column) doesn't count
    y0, y1 = int(max(0, y - (150 if spread else 330))), int(max(0, y - 40))
    if y1 - y0 < 40:
        return int(round(x)), 0, 0
    best = (int(round(x)), 0, 0)
    for cx in range(int(x - spread), int(x + spread) + 1, 20) if spread else [int(x)]:
        x0, x1 = max(0, cx - 22), min(w, cx + 22)
        if x1 <= x0:
            continue
        hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        blue = int(((H >= 90) & (H <= 130) & (S >= 60) & (V >= 140)).sum())
        orange = int((((H <= 22) | (H >= 170)) & (S >= 110) & (V >= 150)).sum())
        if blue + orange > best[1] + best[2]:
            best = (cx, blue, orange)
    return best


def _settlements(atlas, maps, landmarks, icons) -> list[dict]:
    """Decide which City / Hall detections are kept and which kind each one is.

    Hall and City are the same kind of place with a special boss (user's rules): both have a Deadly Map Boss
    icon (without one it is neither: removed, except a completed City, which keeps only its citadel); a City's
    map stands on a brass barrel (always, user; beams vary: every type can show blue); a Hall has a normal map
    base with the beam on a structure next to it. Nearby detections (within SETTLE_MERGE) are one building.
    A map carrying another exclusive type's icon is neither, and the ocean / Expedition biome never has a City.

    Args:
        atlas: the core.Atlas (screenshots, map nodes, images).
        maps: list of (frame dict, atlas-to-screen homography) for every screenshot.
        landmarks: the landmark dicts so far (kind, x, y, n, conf, status ...).
        icons: the merged icons from _clean_icons.

    Returns:
        The landmarks: all non-City / Hall ones unchanged, plus one dict per building with kind, x, y, n,
        conf, source, status, beam (the reason for its kind), beam_px ([blue, orange]) and could.
    """
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
            # most of the screenshots that show it centrally must see the barrel: one view a few px off can look
            # like one (a map node's orb seen too high)
            bx, by = badge.get("bx", badge["x"]), badge.get("by", badge["y"] + 24)
            votes = [
                _barrel(im, sp[0], sp[1], _screen_nodes(atlas, f, bx, by))
                for _c, f, sp in atlas.central_views(bx, by, 3)
                if (im := atlas.image(f["path"])) is not None  # (the screenshot, else its copy)
            ]
            barrel = bool(votes) and 2 * sum(votes) > len(votes)
        views = [
            (im, sp)
            for _c, f, sp in atlas.central_views(b["x"], b["y"], 3)
            if (im := atlas.image(f["path"])) is not None  # (the screenshot, else its copy)
        ]
        ocean = bool(views) and 2 * sum(_ocean(im, sp[0], sp[1]) for im, sp in views) > len(views)
        blue = orange = seen = 0
        for f, Hi in maps:
            sp, ok = _visible(f, Hi, [[b["x"], b["y"]]], margin=5)
            if ok[0] and (im := atlas.image(f["path"])) is not None:  # (no picture left: no beam seen there)
                bl, orr = _beam(im, sp[0, 0], sp[0, 1], b["spread"])
                blue, orange, seen = blue + bl, orange + orr, seen + 1
        status = "kept"
        if badge is None and not clash and b["detected"].get("City", 0) >= b["detected"].get("Hall", 0):
            # a completed City loses its badge (and beam): a green map with only its citadel
            kind, why = "City", "no Deadly Map Boss badge: completed city?"
        elif badge is None:
            kind, why = "Hall", f"its map is a {clash} map" if clash else "no Deadly Map Boss badge"
            status = f"removed: {why} (not a Hall or City)"
        elif barrel:  # a City's map always stands on the barrel (user); every city type can have a blue beam
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
