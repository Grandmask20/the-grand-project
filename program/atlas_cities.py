"""City types (Ezomyte / Vaal / Faridun) and the maps around cities and Breach strongholds.

City types
    Cities come in trios: one Ezomyte (grass, round citadel), one Vaal (big stepped pyramid) and one
    Faridun (desert, green ornate statues) a few maps apart. Two cities closer than TRIO_GAP atlas px
    were never of the same type on the test atlas (25 of 25 pairs). A trio is a close TRIANGLE (not a
    line); a complete trio is used up, and a city next to two known, still-free cities of different
    types that form a triangle with it gets the third type. Partners may be hidden in the fog, so this
    is a guess too. Older note: a city whose close neighbours
    are known gets the type that is left ("trio"). Otherwise it takes the type of the most alike
    labelled city in city_refs.npz (colour + edge-direction look of the ground around the city,
    "look-alike"). Faridun is easy to tell by its sand; Vaal vs Ezomyte by look alone is weak, so
    the trio rule and hand-set types (atlas.city_types, right-click in the viewer) win over it.

Potential maps
    Maps within a few path steps of a City or a Breach stronghold may take on its biome.
"""

from __future__ import annotations

from pathlib import Path

import atlas_builder_core as core
import cv2
import numpy as np
import rc_paths

TYPES = ("Ezomyte", "Vaal", "Faridun")
TRIO_GAP = 680  # atlas px: closer cities always differ in type
TRIO_SIDE = 1150  # atlas px: the longest side of a trio triangle seen on the crawl atlas ~1074
MIN_ANGLE = 20  # degrees: trios are triangles, not lines
SAME_CITY = 150  # atlas px: a stored type / cached look belongs to the city this close
REFS = rc_paths.ref("city_refs.npz")
LOCK_ICON = rc_paths.ref("lock_icon.png")  # the hand badge of a locked Breach stronghold
LOCK_SAME = 150.0  # atlas units: hand badges this close are the same one
COLOR_W = 2.0  # weight of the colour histogram against the edge directions
_refs = None


def _edge_dirs(g: np.ndarray) -> np.ndarray:
    g = g.astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    b = np.minimum(((np.arctan2(gy, gx) % np.pi) / np.pi * 9).astype(int), 8)
    return np.concatenate(
        [
            np.bincount(b[i : i + 16, j : j + 16].ravel(), mag[i : i + 16, j : j + 16].ravel(), 9)
            for i in range(0, 64, 16)
            for j in range(0, 96, 16)
        ]
    )


def window_feature(win: np.ndarray) -> np.ndarray:
    """look of the ground around a city base (BGR window ~540x360 px, base at the bottom middle)"""
    win = cv2.resize(win, (192, 128), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(win, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [12, 6], [0, 180, 0, 256]).ravel()
    h /= h.sum() + 1e-9
    d = _edge_dirs(cv2.resize(cv2.cvtColor(win, cv2.COLOR_BGR2GRAY), (96, 64)))
    d /= np.linalg.norm(d) + 1e-9
    return np.concatenate([np.sqrt(h) * COLOR_W, d]).astype(np.float32)


def city_features(atlas, x: float, y: float, n: int = 3) -> list[np.ndarray]:
    """features of the city at atlas (x, y) from the n screenshots that show it most centrally"""
    out = []
    for _c, f, p in atlas.central_views(x, y, n, limit=0.4):
        if not Path(f["path"]).exists():
            continue
        im = atlas.image(f["path"])
        if im is None:
            continue
        X, Y = int(p[0]), int(p[1])
        win = im[max(0, Y - 220) : Y + 140, max(0, X - 270) : X + 270]
        if win.shape[0] >= 200 and win.shape[1] >= 300:
            out.append(window_feature(win))
    return out


def _load_refs():
    global _refs
    if _refs is None:
        if REFS.exists():
            z = np.load(REFS)
            _refs = (z["feats"], [str(t) for t in z["types"]])
        else:
            _refs = (np.zeros((0, 1), np.float32), [])
    return _refs


def look_distances(feats: list[np.ndarray]) -> list[float] | None:
    """distance to the most alike labelled city of each type (TYPES order); None without a view"""
    R, T = _load_refs()
    if not feats or not len(R):
        return None
    best = [9.0, 9.0, 9.0]
    for u in feats:
        d = np.linalg.norm(R - u, axis=1)
        for k, t in enumerate(T):
            i = TYPES.index(t)
            best[i] = min(best[i], float(d[k]))
    return best


def nearest_map(pts: np.ndarray, alive: np.ndarray, x: float, y: float) -> tuple[int, float]:
    """index of the nearest live map to (x, y) and its distance (-1, inf with no maps)"""
    if not len(pts):
        return -1, float("inf")
    d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
    d[~alive] = np.inf
    v = int(np.argmin(d))
    return v, float(d[v])


def _near(items: list[dict], x, y, gap=SAME_CITY):
    best, bd = None, gap
    for it in items:
        d = float(np.hypot(it["x"] - x, it["y"] - y))
        if d < bd:
            best, bd = it, d
    return best


def city_types(atlas, cities: list[dict], compute_missing=True) -> list[tuple[str, str]]:
    """(type, how) for each city dict {x,y}; how is "set" (by hand), "trio" or "look-alike".
    Look-alike distances are cached in atlas.city_auto (computed for new cities when allowed)."""
    n = len(cities)
    out: list[tuple[str, str] | None] = [None] * n
    dist: list[list[float] | None] = [None] * n
    for k, c in enumerate(cities):
        s = _near(atlas.city_types, c["x"], c["y"])
        if s:
            out[k] = (s["type"], "set")
            continue
        a = _near(atlas.city_auto, c["x"], c["y"])
        if a is None and compute_missing:
            d = look_distances(city_features(atlas, c["x"], c["y"]))
            if d is not None:
                a = {"x": round(c["x"], 1), "y": round(c["y"], 1), "d": [round(v, 4) for v in d]}
                atlas.city_auto.append(a)
        dist[k] = a["d"] if a else None
    P = np.array([[c["x"], c["y"]] for c in cities], float).reshape(-1, 2)
    D = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1]) if n else np.zeros((0, 0))

    def allowed(k):
        taken = {out[j][0] for j in np.nonzero(D[k] < TRIO_GAP)[0] if j != k and out[j]}
        return [t for t in TYPES if t not in taken]

    def triangle(i, j, k):
        """a trio is a close TRIANGLE (all sides < TRIO_SIDE, no angle under MIN_ANGLE), not a line"""
        a_, b_, c_ = D[j, k], D[i, k], D[i, j]
        if max(a_, b_, c_) >= TRIO_SIDE:
            return None
        cosmax = max(
            (b_ * b_ + c_ * c_ - a_ * a_) / (2 * b_ * c_ + 1e-9),
            (a_ * a_ + c_ * c_ - b_ * b_) / (2 * a_ * c_ + 1e-9),
            (a_ * a_ + b_ * b_ - c_ * c_) / (2 * a_ * b_ + 1e-9),
        )
        if cosmax > np.cos(np.radians(MIN_ANGLE)):
            return None
        return a_ + b_ + c_

    in_trio: set[int] = set()
    tris = []
    for i in range(n):
        nb = [j for j in np.nonzero(D[i] < TRIO_SIDE)[0] if j > i]
        for x_, j in enumerate(nb):
            for k in nb[x_ + 1 :]:
                if triangle(i, j, k) is not None:
                    tris.append((i, j, k))

    def close_trios():
        """complete trios (three types, one triangle) are used up: their cities decide nothing else"""
        for i, j, k in tris:
            if out[i] and out[j] and out[k] and len({out[i][0], out[j][0], out[k][0]}) == 3:
                in_trio.update((i, j, k))

    while True:
        changed = True
        while changed:  # trio rule until nothing more follows from it
            changed = False
            close_trios()
            for k in range(n):
                if out[k] is not None:
                    continue
                best_t = None  # the tightest triangle with two known, free cities
                near = [j for j in np.nonzero(D[k] < TRIO_SIDE)[0] if j != k and out[j] and j not in in_trio]
                for x_, j1 in enumerate(near):
                    for j2 in near[x_ + 1 :]:
                        if out[j1][0] == out[j2][0]:
                            continue
                        per = triangle(k, j1, j2)
                        if per is not None and (best_t is None or per < best_t[0]):
                            best_t = (per, j1, j2)
                if best_t:
                    left = [t for t in TYPES if t not in (out[best_t[1]][0], out[best_t[2]][0])]
                    out[k] = (left[0], "trio")
                    in_trio.update((k, best_t[1], best_t[2]))
                    changed = True
        open_ = [k for k in range(n) if out[k] is None and dist[k] is not None]
        if not open_:
            break
        # decide the clearest look-alike next (biggest margin between the two best allowed types)
        best = None
        for k in open_:
            al = allowed(k) or list(TYPES)
            ds = sorted((dist[k][TYPES.index(t)], t) for t in al)
            margin = ds[1][0] - ds[0][0] if len(ds) > 1 else 9.0
            if best is None or margin > best[0]:
                best = (margin, k, ds[0][1])
        out[best[1]] = (best[2], "look-alike")
    return [o if o else ("", "") for o in out]


def set_type(atlas, x: float, y: float, typ: str | None) -> None:
    """store (or with typ None/"" forget) a hand-set type for the city at x, y"""
    atlas.city_types = [c for c in atlas.city_types if np.hypot(c["x"] - x, c["y"] - y) >= SAME_CITY]
    if typ:
        atlas.city_types.append({"x": round(x, 1), "y": round(y, 1), "type": typ})


def ground_sampler(canvas: np.ndarray, weight: np.ndarray, origin, radius: float = 70.0):
    """function (x, y) -> look of the ground around an atlas point (Lab mean + spread) from the
    stitched map image (BGR canvas, origin (x0, y0, px per unit)); None where nothing was seen"""
    x0, y0, s0 = origin
    lab = cv2.cvtColor(canvas, cv2.COLOR_BGR2LAB).astype(np.float32)
    r = max(2, int(round(radius * s0)))
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
    disc = np.hypot(xx, yy) <= r
    H, W = canvas.shape[:2]

    def at(x, y):
        cx, cy = int(round((x - x0) * s0)), int(round((y - y0) * s0))
        if cx - r < 0 or cy - r < 0 or cx + r + 1 > W or cy + r + 1 > H:
            return None
        m = disc & (weight[cy - r : cy + r + 1, cx - r : cx + r + 1] > 0)
        if m.sum() < disc.sum() * 0.5:
            return None
        px = lab[cy - r : cy + r + 1, cx - r : cx + r + 1][m]
        return np.concatenate([px.mean(0), px.std(0)])  # spread: Faridun ground is flat, desert mottled

    return at


SHIP_BUTTON = rc_paths.ref("ship_button.png")  # the Expedition ship marker: same square button, ship symbol
BUTTON_FRAME = 0.86  # frame match (symbol area masked): real buttons 0.87-1.0, anything else <= 0.854
BUTTON_SYMBOL = 0.7  # symbol match: real hands / ships 0.87-1.0, anything else <= 0.5
BUTTON_EDGE = 3  # px of the template kept as the symbol's margin
_buttons: dict = {}


def _button_refs():
    if not _buttons:
        lock = cv2.imdecode(np.fromfile(str(LOCK_ICON), np.uint8), cv2.IMREAD_GRAYSCALE)
        h, w = lock.shape
        mask = np.full((h, w), 255, np.uint8)
        mask[14 : h - 14, 14 : w - 14] = 0  # the symbol: ignored when finding the frame
        sym = {"lock": lock[14 : h - 14, 14 : w - 14]}
        if SHIP_BUTTON.exists():
            ship = cv2.imdecode(np.fromfile(str(SHIP_BUTTON), np.uint8), cv2.IMREAD_GRAYSCALE)
            sym["ship"] = cv2.resize(ship, (w, h))[14 : h - 14, 14 : w - 14]
        _buttons.update(frame=lock, mask=mask, symbols=sym)
    return _buttons


def square_buttons(img) -> list[dict]:
    """the square framed buttons on the atlas (user: the locked stronghold's hand badge and the Expedition
    ship marker share it): found by their frame, then named by the symbol inside - 'lock', 'ship', or
    'unknown' for a symbol not taught yet. Full size, ~70 ms."""
    R = _button_refs()
    t = R["frame"]
    h, w = t.shape
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    r = np.nan_to_num(cv2.matchTemplate(g, t, cv2.TM_CCORR_NORMED, mask=R["mask"]), nan=0, posinf=0, neginf=0)
    # HUD art: only matches whose centre is well inside the HUD outline (a button can sit right next to it)
    hud = cv2.erode((core.hud_mask(g.shape[1], g.shape[0]) > 0).astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
    r[hud[h // 2 : h // 2 + r.shape[0], w // 2 : w // 2 + r.shape[1]]] = 0
    out = []
    while True:
        _mn, mx, _l, (x, y) = cv2.minMaxLoc(r)
        if mx < BUTTON_FRAME:
            return out
        r[max(0, y - h) : y + h, max(0, x - w) : x + w] = 0
        c = g[y + 14 - BUTTON_EDGE : y + h - 14 + BUTTON_EDGE, x + 14 - BUTTON_EDGE : x + w - 14 + BUTTON_EDGE]
        best, kind = -1.0, "unknown"
        for k, sy in R["symbols"].items():
            if c.shape[0] < sy.shape[0] or c.shape[1] < sy.shape[1]:
                continue
            v = float(cv2.matchTemplate(c, sy, cv2.TM_CCOEFF_NORMED).max())
            if v > best:
                best, kind = v, k
        if best < BUTTON_SYMBOL:
            if mx < 0.9:  # a weak frame with no known symbol: not a button
                continue
            kind = "unknown"
        out.append({"kind": kind, "x": x + w / 2, "y": y + h / 2, "frame": round(mx, 3), "symbol": round(best, 3)})


def locks_in(img) -> list[tuple[float, float]]:
    """screen positions of hand badges (locked Breach strongholds) in one screenshot"""
    return [(b["x"], b["y"]) for b in square_buttons(img) if b["kind"] == "lock"]


def find_locks(atlas, frames) -> list[tuple[float, float]]:
    """atlas positions of the hand badges in the given screenshots"""
    out = []
    for f in frames:
        if not Path(f["path"]).exists():
            continue
        im = atlas.image(f["path"])
        if im is None:
            continue
        found = locks_in(im)
        if found:
            H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
            out += [(float(q[0]), float(q[1])) for q in core.persp(H, found)]
    return out


def merge_locks(locks: list[dict], found: list[tuple[float, float]]) -> list[dict]:
    """add found hand badges to the stored list (same badge seen in several screenshots: averaged)"""
    locks = [dict(k) for k in locks]
    for x, y in found:
        for k in locks:
            if np.hypot(k["x"] - x, k["y"] - y) < LOCK_SAME:
                n = k["n"]
                k["x"], k["y"], k["n"] = (
                    round((k["x"] * n + x) / (n + 1), 1),
                    round((k["y"] * n + y) / (n + 1), 1),
                    n + 1,
                )
                break
        else:
            locks.append({"x": round(x, 1), "y": round(y, 1), "n": 1})
    return locks


def potential_maps(
    nodes: list[dict],
    paths: list[dict],
    sources: list[tuple[float, float, str]],
    count: int = 10,
    hops: int = 3,
    snap: float = 90.0,
    ground=None,
    area_kinds: tuple = ("Breach stronghold",),
    area_reach: float = 520.0,
    area_blind: float = 230.0,
    area_merge: float = 350.0,
    area_hops: int = 6,
    area_snap: float = 260.0,
    pool_r: float = 260.0,
    far_r: float = 700.0,
    alike: float = 10.0,
    rich: float = 5.0,
    poor: float = 1.5,
    blocked: dict[int, str] | None = None,
    unique_ok: tuple = ("Vaal city",),
    hard_off: dict | None = None,
    behind: float = -0.2,
) -> dict[int, tuple[str, int]]:
    """the maps a City / Breach stronghold biome may cover: node index -> (label, steps).

    Cities: about 10 maps (+-2), linked tightly to each other (often a square grid of paths) with
    few paths leading out. Each city grows such a cluster from its own map (step 0: the nearest map
    within `snap` px), at most `hops` steps out, preferring maps with more links into the cluster,
    maps that close a square (4-map loop) with it, and maps on the city's kind of ground; the size
    in count+-2 that leaves the fewest paths out (and the least foreign ground) is kept.

    Breach strongholds (`area_kinds`): no size limit; a roughly round patch of their own ground:
    stronghold boxes within `area_merge` are one stronghold (its centre = their mean), and every map
    within `area_reach` of the centre reached through such maps (`area_blind` when there are too
    few strongholds to learn the Breach ground from).

    Ground (see ground_sampler): each kind of city has its own ground everywhere (flat bright sand
    for Faridun, dark purple rock for Breach, ...), but the city's own map sits on dark buildings
    and often at the edge of its patch, so the ground is LEARNED per label: how much more common a
    map's ground look (within `alike` Lab units) is among maps within `pool_r` of all sources with
    that label than among maps farther than `far_r` from every source. At least `rich` times more
    common = this kind's ground; `poor` or less = clearly not (crawl atlas, Faridun: sand maps 4-17,
    maps across the border 1-2). Labels with fewer than 3 sources get no ground term.
    Rules from the user (cities): a city never connects to a Unique map, Tower, merchant,
    corruption / cleansed map, Hall, Breach stronghold, hideout or Abyss map, and nothing reached
    only through one of those is a city map (`blocked`: node -> reason; the exception is a Unique
    map inside a Vaal city, `unique_ok`, taken but not grown through). A city's citadel (its own
    map) is always at an EDGE of its biome, so maps behind it (direction against the side where
    its own kind of ground and maps lie, cosine below `behind`) are left out. Maps on clearly
    foreign ground are left out for Faridun (always desert; `hard_off`), elsewhere only penalised.
    A map claimed by two sources keeps the nearer; ties list both ("A / B")."""
    pts = np.array([[nd["x"], nd["y"]] for nd in nodes], float).reshape(-1, 2)
    alive = np.array([nd.get("status") != "removed" for nd in nodes], bool)
    adj: dict[int, set[int]] = {}
    for p in paths:
        a, b = p["a"], p["b"]
        if alive[a] and alive[b] and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    res: dict[int, tuple[str, int]] = {}
    if not len(pts):
        return res
    gcache: dict[int, np.ndarray | None] = {}

    def g(v):
        if ground is None:
            return None
        if v not in gcache:
            gcache[v] = ground(*pts[v])
        return gcache[v]

    merged, used = [], set()  # stronghold boxes close together = one stronghold
    for k, (x, y, label) in enumerate(sources):
        if k in used:
            continue
        if label in area_kinds:
            grp = [
                j
                for j, (x2, y2, l2) in enumerate(sources)
                if j not in used and l2 == label and np.hypot(x2 - x, y2 - y) < area_merge
            ]
            used.update(grp)
            merged.append(
                (float(np.mean([sources[j][0] for j in grp])), float(np.mean([sources[j][1] for j in grp])), label)
            )
        else:
            merged.append((x, y, label))
    sources = merged
    starts = []
    for x, y, label in sources:
        s, ds = nearest_map(pts, alive, x, y)
        if ds <= (area_snap if label in area_kinds else snap):
            starts.append((s, x, y, label))
    enrich: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    if ground is not None and starts:
        GV = np.zeros((len(pts), 6), np.float32)
        ok = np.zeros(len(pts), bool)
        for v in np.nonzero(alive)[0]:
            gv = g(v)
            if gv is not None:
                GV[v], ok[v] = gv, True
        S = np.array([[x, y] for _s, x, y, _l in starts], float)
        dmin = np.full(len(pts), 1e9)
        for k in range(0, len(S), 64):
            dmin = np.minimum(
                dmin,
                np.hypot(pts[:, None, 0] - S[None, k : k + 64, 0], pts[:, None, 1] - S[None, k : k + 64, 1]).min(
                    axis=1
                ),
            )
        B = GV[ok & (dmin > far_r)]
        for label in {lab for *_r, lab in starts}:
            T = np.array([[x, y] for _s, x, y, lab in starts if lab == label], float)
            if len(T) < 3 or len(B) < 50:
                continue
            dl = np.full(len(pts), 1e9)
            for k in range(0, len(T), 64):
                dl = np.minimum(
                    dl,
                    np.hypot(pts[:, None, 0] - T[None, k : k + 64, 0], pts[:, None, 1] - T[None, k : k + 64, 1]).min(
                        axis=1
                    ),
                )
            enrich[label] = (GV[ok & (dl < pool_r)], B)
    rcache: dict[tuple[str, int], float] = {}

    def ratio(label, v):
        key = (label, v)
        if key not in rcache:
            Pt, B = enrich[label]
            x = g(v)
            a = (np.linalg.norm(Pt - x, axis=1) < alike).mean()
            b = (np.linalg.norm(B - x, axis=1) < alike).mean()
            rcache[key] = float((a + 1e-3) / (b + 1e-3))
        return rcache[key]

    for s, x, y, label in starts:

        def off(v, label=label):  # 0 = this kind's ground ... 2 = clearly not
            if label not in enrich or g(v) is None:
                return 0.0
            r = ratio(label, v)
            return float(np.clip(np.log(rich / r) / np.log(rich / poor), 0.0, 1.0)) * 2.0

        seen = {s: 0}  # path steps from the source map
        front = [s]
        if label in area_kinds:
            # a round patch around the stronghold: distance from its centre, tighter when its
            # ground can't be checked (fewer than 3 strongholds to learn the Breach ground from)
            reach = area_reach if label in enrich else area_blind
            for step in range(1, area_hops + 1):
                nxt = []
                for u in front:
                    for v in adj.get(u, ()):
                        if (
                            v not in seen
                            and off(v) < 1.0
                            and (blocked or {}).get(v) not in ("Hall", "Tower", "another city")
                            and np.hypot(pts[v, 0] - x, pts[v, 1] - y) <= reach
                        ):
                            seen[v] = step
                            nxt.append(v)
                front = nxt
            keep = list(seen)
        else:
            blk = blocked or {}

            def barred(v, blocked_maps=blk, city_start=s, city_label=label):  # never a city map
                r = blocked_maps.get(v)
                return v != city_start and r is not None and not (r == "Unique map" and city_label in unique_ok)

            def dead_end(v, blocked_maps=blk, city_start=s):  # a Unique map in a Vaal city: taken, not grown through
                return v != city_start and blocked_maps.get(v) == "Unique map"

            # hard ground cut only where the user says the ground is always the same (Faridun =
            # desert); Ezomyte / Vaal ground is too varied, it only counts as a penalty there
            cut_at = (hard_off if hard_off is not None else {"Faridun city": 1.6}).get(label, 9.0)
            for step in range(1, hops + 1):
                nxt = []
                for u in front:
                    if dead_end(u):
                        continue
                    for v in adj.get(u, ()):
                        if v not in seen and not barred(v) and off(v) < cut_at:
                            seen[v] = step
                            nxt.append(v)
                front = nxt
            # which side of the citadel the city lies on: where its maps and its ground are
            vec = np.zeros(2)
            for v, st in seen.items():
                d = pts[v] - pts[s]
                n = float(np.hypot(*d))
                if v != s and n > 1:
                    vec += (2.0 - off(v)) / (1 + st) * d / n
            if np.hypot(*vec) > 0.8:
                u = vec / np.hypot(*vec)
                for v in [v for v in seen if v != s]:
                    d = pts[v] - pts[s]
                    if float(d @ u) / max(1.0, float(np.hypot(*d))) < behind:
                        del seen[v]
            grown, best = [s], None
            inside = {s}
            mismatch = 0.0

            def squares(c, cluster=inside):  # 4-map loops c would close with the cluster
                nb = [w for w in adj[c] if w in cluster]
                return sum(len((adj[a] & adj[b] & cluster) - {c}) for i, a in enumerate(nb) for b in nb[i + 1 :])

            while len(grown) < count + 3:
                cand = {v for u in inside if not dead_end(u) for v in adj.get(u, ()) if v not in inside and v in seen}
                if not cand:
                    break
                v = max(
                    cand,
                    key=lambda c: (
                        len(adj[c] & inside) + 0.5 * min(2, squares(c)) - 1.5 * off(c),
                        -seen[c],
                        -float(np.hypot(*(pts[c] - pts[s]))),
                    ),
                )
                grown.append(v)
                inside.add(v)
                mismatch += off(v)
                if len(grown) - 1 >= count - 2:
                    cut = sum(len(adj.get(u, set()) - inside) for u in inside)
                    cost = cut + 1.5 * mismatch
                    if best is None or cost < best[0]:
                        best = (cost, len(grown))
            keep = grown[: best[1]] if best else grown
        for v in keep:
            st = seen[v]
            old = res.get(v)
            if old is None or st < old[1]:
                res[v] = (label, st)
            elif st == old[1] and label not in old[0].split(" / "):
                res[v] = (f"{old[0]} / {label}", st)
    return res


# map types a city never connects to (user's rule); a Unique map is allowed inside a Vaal city
BLOCK_ICONS = {
    "UniqueMap": "Unique map",
    "Trader": "merchant",
    "Corruption": "corruption",
    "CorruptionNexus": "corruption",
    "CorruptionNexusNoGrowth": "corruption",
    "Sanctification": "cleansed",
    "SanctificationBoss": "cleansed",
    "Hideout": "hideout",
    "Abyss": "Abyss",
    "AbyssOverrun": "Abyss",
    "AbyssalDepths": "Abyss",
}
BLOCK_PLACES = {"Hall": "Hall", "Breach stronghold": "Breach stronghold", "Tower": "Tower", "City": "another city"}


def icon_maps(nodes: list[dict], icons: list[dict], reach: float = 45.0) -> dict[int, int]:
    """icon index -> the map it belongs to (nearest map to the icon's base, within `reach`)"""
    pts = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
    alive = np.array([n.get("status") != "removed" for n in nodes], bool)
    out = {}
    if not len(pts) or not alive.any() or not icons:
        return out
    from scipy.spatial import cKDTree  # (v1.03: one map search per badge took ~1 s per redraw)

    live = np.nonzero(alive)[0]
    q = np.array([[ic.get("bx", ic["x"]), ic.get("by", ic["y"])] for ic in icons], float)
    d, k = cKDTree(pts[live]).query(q)
    for i in np.nonzero(d <= reach)[0]:
        out[int(i)] = int(live[k[i]])
    return out


def blocked_maps(
    nodes: list[dict],
    icons: list[dict],
    landmarks: list[dict],
    icon_node: dict[int, int] | None = None,
    snap: float = 90.0,
) -> dict[int, str]:
    """maps that are never city maps: node -> reason (Unique map, merchant, corruption, cleansed,
    hideout, Abyss, Tower, Hall, Breach stronghold, another city's own map)"""
    out: dict[int, str] = {}
    for v, n in enumerate(nodes):
        if n.get("status") == "removed":
            continue
        for raw in n.get("icons", []):
            if raw in BLOCK_ICONS:
                out.setdefault(v, BLOCK_ICONS[raw])
        if n.get("tower"):
            out.setdefault(v, "Tower")
        if n.get("abyss"):
            out.setdefault(v, "Abyss")
    for i, v in (icon_node if icon_node is not None else icon_maps(nodes, icons)).items():
        if icons[i]["name"] in BLOCK_ICONS:
            out.setdefault(v, BLOCK_ICONS[icons[i]["name"]])
    pts = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
    alive = np.array([n.get("status") != "removed" for n in nodes], bool)
    for lm in landmarks:
        if lm["kind"] not in BLOCK_PLACES or lm.get("status", "").startswith("removed") or not len(pts):
            continue
        v, dv = nearest_map(pts, alive, lm["x"], lm["y"])
        if dv <= snap:
            out.setdefault(v, BLOCK_PLACES[lm["kind"]])
    return out


def near_city(
    nodes: list[dict], paths: list[dict], potential: dict[int, tuple[str, int]], blocked: dict[int, str]
) -> dict[int, tuple[str, int]]:
    """potential city maps: node -> (city label, 0 = on its biome / 1 = one path step from it)"""
    alive = [n.get("status") != "removed" for n in nodes]
    adj: dict[int, set[int]] = {}
    for p in paths:
        a, b = p["a"], p["b"]
        if alive[a] and alive[b]:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    out = {v: (lab, 0) for v, (lab, _st) in potential.items() if "city" in lab.lower()}
    for v, (lab, _z) in list(out.items()):
        for w in adj.get(v, ()):
            if w not in out and w not in blocked:
                out[w] = (lab, 1)
    return out
