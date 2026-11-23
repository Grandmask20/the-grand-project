"""finalize.icon_time: a map's icons over time (user's rules, v1.23).

Running maps changes the atlas: a blue map that turns green always loses its icon, a blue map can lose its icon and
stay blue, and a few icons can appear on a map (user). Screenshots of one spot taken at different times can then
disagree, and the newer ones are right. Screenshots taken close together (a scan while panning, under
ICON_TIME_GAP apart) are one moment: nothing changes between them.

The detector misses an icon it plainly shows in about half the screenshots of it (crawl of the roa atlas, v1.23:
the icon's glow animates), so "not found" alone is no evidence. Where it wasn't found, the screenshot is looked at
again: the icon row above the map is searched for that icon's own pictures (icon_check). For each map seen at
more than one moment and each known icon on it, the newest moment that settles it decides:

- the icon is gone when that moment shows the map without it and an earlier one had it (it was run);
- an icon that came later on a map an earlier moment showed without it was found falsely when it is one that never
  appears (ICON_NEVER_APPEARS), or Cleansed where there was no Corruption (it only replaces Corruption);
- a deadly boss map (not a City) that was attempted stays blue and keeps only its Deadly Map Boss icon: one of its
  other icons gone takes them all.

Only known icons on maps count (user: "nodes which can be lost should ONLY be ones which were on maps and are known
icons"): not Unidentified ones, loose icons or a tower's (they float above it and shift between screenshots: an
icon whose copies lay ICON_TOWER_SPREAD apart is one, even over a map not known as a tower - user).
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from grand_project import core, icon_refs

from .constants import (
    ICON_CITY_REACH,
    ICON_DEADLY,
    ICON_NEVER_APPEARS,
    ICON_ONLY_REPLACES,
    ICON_TIME_ABSENT,
    ICON_TIME_DARK,
    ICON_TIME_DX,
    ICON_TIME_DY,
    ICON_TIME_GAP,
    ICON_TIME_MARGIN,
    ICON_TIME_PEAKS,
    ICON_TIME_PRESENT,
    ICON_TIME_RIM,
    ICON_TIME_SKIP,
    ICON_TIME_SNAP,
    ICON_TIME_TIE,
    ICON_TIME_VIEWS,
    ICON_TIME_WIDE,
    ICON_TOWER_SPREAD,
)
from .traces import _saved, _visible


def moments(times: list[float | None], gap: float = ICON_TIME_GAP) -> list[list[int]]:
    """Group screenshots into moments: taken less than `gap` s apart (one without a time stands alone).

    Args:
        times: Each screenshot's capture time (core.capture_time), or None.
        gap: Seconds between two screenshots that start a new moment.

    Returns:
        Lists of indices into times, oldest moment first.
    """
    timed = sorted((t, i) for i, t in enumerate(times) if t is not None)
    out: list[list[int]] = []
    last = None
    for t, i in timed:
        if last is None or t - last >= gap:
            out.append([])
        out[-1].append(i)
        last = t
    return out + [[i] for i, t in enumerate(times) if t is None]


def icon_check(img: np.ndarray, mx: float, my: float, name: str, anchored: bool = True, others=None) -> bool | None:
    """Look for a known icon in the icon row above a map in a screenshot.

    The row (up to 5 icons, 36 px apart, centred over the map, 24 px above it) is searched rather than one spot:
    an icon's merged position can sit between two of a row's icons. The icon anywhere a little around the row
    (ICON_TIME_WIDE) counts as there unless it sits in another map's row: keeping an icon by mistake costs less
    than losing one, and a tower's icons float off their map (roa atlas: 65 px, a Corruption icon taken for gone),
    but a neighbour's own icon of the same kind isn't this map's (roa test: Cleansed icons next to each other).

    Args:
        img: The screenshot (BGR, 1080p).
        mx: The map's x in the screenshot's px.
        my: Its y.
        name: The icon (a name with stored pictures).
        anchored: (mx, my) is where the screenshot itself found the map; else only presence is told (an unanchored
            spot may be off, so the row looked at may be another map's).
        others: The other maps the screenshot found ((n, 2) px): an icon near the row that sits in one of their rows
            is theirs.

    Returns:
        True when the icon is in or near the row, False when every rim in the row is plainly something else (or there
        is none), None when unsure (a rim it fits nearly as well as anything, the row off the screen or under the
        HUD, the map in the dark fog, no anchor, or no pictures of the icon).
    """
    from grand_project.detect import badges
    from grand_project.detect.constants import ICON_RIM_R, ROW_DY

    R = icon_refs.refs()
    rows = [k for k, n in enumerate(R.names) if n == name]
    if not rows:
        return None
    h, w = img.shape[:2]
    pad = int(math.ceil(ICON_RIM_R[1])) + icon_refs.SIZE // 2 + icon_refs.SHIFT + 2
    cy = my - ROW_DY
    x0, x1 = int(mx - ICON_TIME_DX), int(mx + ICON_TIME_DX)
    y0, y1 = int(cy - ICON_TIME_DY), int(cy + ICON_TIME_DY)
    if x0 - pad < 0 or y0 - pad < 0 or x1 + pad >= w or y1 + pad >= h:
        return None  # (part of the row off the screen)
    r = int(math.ceil(ICON_RIM_R[1]))
    if core.hud_mask(w, h)[y0 - r : y1 + r + 1, x0 - r : x1 + r + 1].any():
        # an icon missing where the HUD (the search bar, ...) covers any of the row changes nothing (user)
        return None
    around = img[max(0, int(my) - 100) : int(my) + 60, max(0, int(mx) - 100) : int(mx) + 100]
    if cv2.cvtColor(around, cv2.COLOR_BGR2GRAY).mean() < ICON_TIME_DARK:
        return None  # (in the dark fog the game draws no icons: no evidence either way)
    # the icon near the row: there (the row and ICON_TIME_WIDE around it, as far as the screen goes)
    wx0, wx1 = max(pad, x0 - ICON_TIME_WIDE), min(w - pad - 1, x1 + ICON_TIME_WIDE)
    wy0, wy1 = max(pad, y0 - ICON_TIME_WIDE), min(h - pad - 1, y1 + ICON_TIME_WIDE)
    wide = badges.rim_score(img[wy0 - pad : wy1 + pad + 1, wx0 - pad : wx1 + pad + 1])[pad:-pad, pad:-pad]
    peak = (wide >= cv2.dilate(wide, np.ones((9, 9), np.uint8))) & (wide >= ICON_TIME_RIM)
    ys, xs = np.nonzero(peak)
    near = np.asarray(others if others is not None else np.zeros((0, 2)), float).reshape(-1, 2)

    def fits(px: float, py: float) -> tuple[float, float]:
        """How well a rim fits this icon's pictures, and its best match among all pictures (1 - correlation)."""
        own = badges.name_badge(img, px, py, [name] * len(rows), R.F[rows])[1]
        return own, badges.name_badge(img, px, py, R.names, R.F)[1]

    def is_it(own: float, best: float) -> bool:
        # (a close fit that is also its best match: the player marker over a map fits Cleansed's pictures too)
        return own <= ICON_TIME_PRESENT and own <= best + ICON_TIME_TIE

    for k in np.argsort(-wide[ys, xs])[: 2 * ICON_TIME_PEAKS]:
        px, py = wx0 + xs[k], wy0 + ys[k]
        own, best = fits(px, py)
        if not is_it(own, best):
            continue
        in_row = x0 <= px <= x1 and y0 <= py <= y1
        # (in another map's row: that map's own icon)
        dx, dy = np.abs(near[:, 0] - px), np.abs(near[:, 1] - ROW_DY - py)
        theirs = bool(((dx <= ICON_TIME_DX) & (dy <= ICON_TIME_DY)).any())
        if in_row or not theirs:
            return True
    if not anchored:
        return None  # (the row looked at may be another map's: no evidence it's gone)
    sc = wide[y0 - wy0 : y1 - wy0 + 1, x0 - wx0 : x1 - wx0 + 1]  # (the row itself)
    peak = (sc >= cv2.dilate(sc, np.ones((9, 9), np.uint8))) & (sc >= ICON_TIME_RIM)
    ys, xs = np.nonzero(peak)
    if not len(xs):
        return False  # (no icon rim anywhere in the row)
    maybe = False
    for k in np.argsort(-sc[ys, xs])[:ICON_TIME_PEAKS]:
        own, best = fits(x0 + xs[k], y0 + ys[k])
        if is_it(own, best):
            return True
        # a rim plainly something else (another icon, or the namer's "not an icon" pictures, a clearly better
        # match) isn't this icon; one this icon fits nearly as well might be it
        if own <= ICON_TIME_ABSENT and own <= best + ICON_TIME_MARGIN:
            maybe = True
    return None if maybe else False


def _found_at(atlas, f: dict, sp: np.ndarray) -> tuple[np.ndarray, bool, np.ndarray]:
    """Where the screenshot itself found a map: its own map nearest to where the atlas puts it (within
    ICON_TIME_SNAP px), else that spot. The atlas's merged position projected into a screenshot drifts towards its
    edges (a Cleansed icon at x 219 was searched for in the wrong row).

    Returns:
        (the spot in the screenshot's px, whether it is the screenshot's own map: anchored, the screenshot's other
        maps (n, 2)).
    """
    rec = _saved(atlas, f)
    P = rec["P"] if rec is not None else np.zeros((0, 2))
    if len(P):
        d = np.hypot(P[:, 0] - sp[0], P[:, 1] - sp[1])
        k = int(np.argmin(d))
        if d[k] <= ICON_TIME_SNAP:
            return np.asarray(P[k], float), True, np.delete(np.asarray(P, float), k, axis=0)
    return np.asarray(sp, float), False, np.asarray(P, float).reshape(-1, 2)


def icons_over_time(
    atlas, maps: list, nodes: list[dict], alive: list[bool], icons: list[dict], skip: set, cities: list | None = None
) -> dict:
    """Decide which icons on maps changed over time (the module docstring).

    Args:
        atlas: The atlas (its saved detections: where each screenshot found each map).
        maps: (frame dict, atlas-to-screen homography) of every screenshot (traces._maps).
        nodes: The check's map nodes ("x", "y", "frames" (names of screenshots that found it), "icons" (indices
            into icons), "tower").
        alive: Per node, whether it is kept.
        icons: The check's merged icons ("name", "frames").
        skip: Icon indices already left out (duplicates).
        cities: (x, y) of the Cities: a deadly boss map that is one isn't judged as a plain deadly boss map.

    Returns:
        {"gone": icon indices a newer moment shows gone, "false": icon indices that appeared where they can't}.
    """
    when = {f["name"]: core.capture_time(f) for f, _Hi in maps}
    by_name = {f["name"]: (f, Hi) for f, Hi in maps}

    def judged(k: int) -> bool:
        """Whether an icon is judged over time at all: a known one, not left out already, not a tower's floating
        icon (copies far apart, even over a map not known as a tower - user)."""
        return (
            k not in skip and icons[k]["name"] not in ICON_TIME_SKIP and icons[k].get("spread", 0.0) < ICON_TOWER_SPREAD
        )

    asks: dict[str, list] = {}  # screenshot -> [(key, mx, my, icon name)] to look at
    plans = []
    for i, nd in enumerate(nodes):
        if not alive[i] or nd.get("tower") or not nd["icons"]:
            continue
        # (a screenshot with no known time can't be put before or after the others: left out - self review)
        views = [n for n in nd["frames"] if n in by_name and when[n] is not None]
        if len(views) < 2:
            continue
        groups = moments([when[n] for n in views])
        if len(groups) < 2:
            continue  # (all at one moment: nothing could change)
        names: dict[str, list[int]] = {}
        for k in nd["icons"]:
            if judged(k):
                names.setdefault(icons[k]["name"], []).append(k)
        for name, ks in names.items():
            found = set().union(*(set(icons[k]["frames"]) for k in ks))
            per = []  # per moment: (views, found in any)
            for g in groups:
                vs = [views[j] for j in g]
                per.append((vs, any(v in found for v in vs)))
            # what to look at again: the moments not found in, nearest the screen's middle first
            look = []
            for vs, hit in per:
                if hit:
                    continue
                pts = []
                for v in vs:
                    f, Hi = by_name[v]
                    sp, ok = _visible(f, Hi, [[nd["x"], nd["y"]]])
                    if ok[0]:
                        at, anchored, rest = _found_at(atlas, f, sp[0])
                        pts.append((math.hypot(at[0] - f["w"] / 2, at[1] - f["h"] / 2), v, at, anchored, rest))
                look.append([t[1:] for t in sorted(pts, key=lambda t: t[0])[:ICON_TIME_VIEWS]])
            plans.append((i, name, ks, per))
            for vs in look:
                for v, p, a, rest in vs:
                    asks.setdefault(v, []).append(((i, name, v), float(p[0]), float(p[1]), name, a, rest))
    seen: dict[tuple, bool | None] = {}
    for v, todo in asks.items():  # (each screenshot read once)
        f = by_name[v][0]
        img = core.read_screenshot(f["path"]) if Path(f["path"]).exists() else None
        for key, x, y, name, anchored, rest in todo:
            seen[key] = None if img is None else icon_check(img, x, y, name, anchored, rest)
    gone: set[int] = set()
    false: set[int] = set()
    verdicts_of: dict[tuple[int, str], list] = {}  # (map, icon) -> per moment: True / False / None
    for i, name, _ks, per in plans:
        verdicts = []  # per moment: True (has it), False (shows the map without it), None (unsure)
        for vs, hit in per:
            got = [seen.get((i, name, v)) for v in vs]
            verdicts.append(True if hit or any(g is True for g in got) else (False if False in got else None))
        verdicts_of[(i, name)] = verdicts
    for i, name, ks, per in plans:
        verdicts = verdicts_of[(i, name)]
        settled = [k for k, v in enumerate(verdicts) if v is not None]
        if not settled:
            continue
        first = next((k for k in settled if verdicts[k]), None)
        if verdicts[settled[-1]] is False and first is not None:
            gone.update(ks)  # the newest moment shows it gone, an earlier one had it: the map was run
            continue
        if first is None or not any(verdicts[k] is False for k in settled if k < first):
            continue  # (it was there from the first moment that settles it)
        if name in ICON_NEVER_APPEARS:
            false.update(ks)
        elif name in ICON_ONLY_REPLACES:
            before = ICON_ONLY_REPLACES[name]
            # (the one it replaces in an earlier moment: found by the detector, or confirmed by the second look -
            # the detector alone missed some: CodeRabbit)
            had = any(v is True for v in verdicts_of.get((i, before), [])[:first]) or any(
                icons[k]["name"] == before and set(icons[k]["frames"]) & {v for vs, _ in per[:first] for v in vs}
                for k in nodes[i]["icons"]
            )
            if not had:
                false.update(ks)
    # a deadly boss map that was attempted stays blue and loses every icon but its Deadly Map Boss one (user: "it'll
    # always be that the map will lose any NON deadly boss icons", not on Cities): one of them gone takes the rest
    for i, nd in enumerate(nodes):
        if not alive[i]:
            continue
        ks = [k for k in nd["icons"] if judged(k)]  # (the same icons as above: never a tower's - CodeRabbit)
        boss = [k for k in ks if icons[k]["name"] == ICON_DEADLY]
        others = [k for k in ks if icons[k]["name"] != ICON_DEADLY]
        city = any(math.hypot(nd["x"] - x, nd["y"] - y) < ICON_CITY_REACH for x, y in cities or [])
        if boss and not city and not set(boss) & gone and set(others) & gone:
            gone.update(others)
    return {"gone": gone, "false": false}
