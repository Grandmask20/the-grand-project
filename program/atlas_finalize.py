"""Atlas-wide clean-up that uses every screenshot at once.

Run after screenshots are placed (the builder and the viewer both do).  Nothing here changes
what was detected; it decides what to *believe*, and stores the result in atlas["final"]:

1. Nodes: for each node, how many screenshots could see that spot vs. how many found a node
   there.  Found by most -> kept.  Missed by most -> ghost, removed.  Two half-merged copies of
   one node (each seen once, a few px apart) are joined.
2. Icons: every badge is attached to the map base 24 px under it.  A named badge with no base
   under it creates the node (icons are much more reliable than base detection).
3. Abyss: Abyss badges along a river form a single chain - first icon to the final map with
   two Abyss badges, one path between neighbours, nothing else touching the inner maps.
   Ghost nodes and false Towers on the glowing river are removed.
4. Paths: every candidate link is scored on the gold dotted line in EVERY screenshot that shows
   both ends (the detector's own route_score, at the merged node positions), and the scores are
   averaged.  The detector's selection rules then run once on the whole atlas: no crossings,
   at most 5 exits, no shortcut past a nearer base, no diamond diagonals.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

import atlas_builder_core as core
import atlas_io
import atlas_log
import rc_paths

_log = atlas_log.printer("finalize")
import atlas_paths as gp
import atlas_detect

FRAME_MARGIN = 22          # px from a screenshot edge: a node closer than this may be cut off
PARALLAX_TOL = 52.0        # maps / badges on raised ground (mountains, outcrops) shift up to ~35-45
                           # between screenshots: the atlas is 3D, the flattening assumes a plane
TOWER_JOIN = 44.0          # atlas units: a tower base is wide (rim ~3x a map's, user). Where a screenshot did not
                           # recognise the tower (cut off at the edge) it found two maps 31-40 px apart on its base;
                           # real maps next to a tower sat 48+ px away. Anything this close to a tower IS the tower.
TOWER_JOIN_SEEN = 2         # ...and only around a tower recognised in this many screenshots
SHARED_MIN_ALONE = 6        # ...and only when this many screenshots found a single map there
SHARED_OK, SHARED_FRAC = 1, 0.2   # copies seen together in at most 1 screenshot / 20% of them may still be one map
DUP_TOL = 26.0             # atlas units: one map found at two spots by different screenshots.
                           # Within one screenshot real maps are >= ~36 px apart (1st percentile).
SAME_SPOT = 14.0           # badges this close on one map are one badge
ICON_TWIN = 40.0           # a map placed from a badge this close to a found map with the same badge: one map
RATIO_GHOST, RATIO_NEAR, RATIO_COULD = 0.35, 0.70, 8   # found in <= 25% of the shots that show it, while maps
RATIO_REL, RATIO_REL_NEAR, RATIO_COULD_REL = 0.0, 0.85, 4   # relative ghost rule OFF: removed ~14 real maps for 2 ghosts (atlas_test_data/ghost_check.png)
GAP_ON = True              # user's ladder: badge -> visible base -> paths with a gap; only weak bases get the gap test
GAP_FOUND = 0.6            # ...and only maps found in under 60% of their shots (user's dark real X4 3/3, X5 2/3)
GAP_SEEN = 0.85           # map confidence that counts as a clearly visible base (judged: 12 of 14 real, 1 of 6 ghosts)
GAP_R, GAP_MIN, GAP_SHOTS = 10.0, 2, 3   # px ring; a map with >= 2 amber dashes inside it in EVERY one of 3+ clear shots
JUNCTION = 3               # maps where this many traced paths end are never ghosts (run-over / gap rules)
LONELY_SEEN = 0.9          # ...and only when its base is never clearly seen (crawl: real ones 0.94+)
LONELY_ON, LONELY_SHOTS = True, 3   # maps with no badge and no path are removed (user)
RATIO_R = 200.0            # within 200 are found in >= 85% (and 8+ shots show it): a ghost (user's 2/12, 2/17)
WALL_MAP = 0.6             # a map on the fortress wall in this share of the shots that show it: wall art (user)
ICON_ATTACH_DX, ICON_ATTACH_DY = 24.0, 13.0   # base position tolerance under an icon
ICON_TOWER_SPREAD = 40.0   # a badge whose copies lay this far apart, with no map right under it, is a tower's
ICON_TOWER_REACH = (70.0, 260.0)   # ... its tower map: this far sideways, up to this far below the badge base
ICON_PAIR = 32.0           # badges of one row whose map base was not detected share one new node
ROW_GAP = 46.0             # neighbouring badges in one row over a single map (measured ~36 px)
NO_NODE_ICONS = {"Unidentified", "LostTower", "PlayerOrBookmark"}   # never create a map node  # these never create a node on their own
ABYSS_NAMES = {"Abyss", "AbyssOverrun"}
ABYSS_LINK = 150.0         # max gap between successive Abyss maps in a chain
ABYSS_CLEAR = 42.0         # non-icon nodes this close to the chain line are river glow
ABYSS_TOWER_CLEAR = 60.0
PATH_THRESHOLD, TOWER_THRESHOLD, PROPOSE = .73, .63, .64
MAX_EXITS = gp.MAX_EXITS
PASS_CLEAR = 28.0          # a traced line running this close to a third map is not a real path


class _Grid:
    """Spatial index: points in square cells, so 'what is near here' looks at a few cells
    instead of the whole atlas (the atlas-wide check was quadratic: 35 min for 8k maps)."""

    def __init__(self, pts, cell: float):
        self.pts = np.asarray(pts, float).reshape(-1, 2)
        self.cell = float(cell)
        self.cells: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            self.cells.setdefault((int(x // cell), int(y // cell)), []).append(i)

    def near(self, p, r) -> list[int]:
        """indices within distance r of p"""
        c, k = self.cell, int(math.ceil(r / self.cell))
        cx, cy = int(p[0] // c), int(p[1] // c)
        cand = [i for gx in range(cx - k, cx + k + 1) for gy in range(cy - k, cy + k + 1)
                for i in self.cells.get((gx, gy), ())]
        if not cand:
            return []
        d = np.hypot(self.pts[cand, 0] - p[0], self.pts[cand, 1] - p[1])
        return [cand[q] for q in np.nonzero(d <= r)[0]]

    def pairs(self, r):
        """(distance, i, j) for every i < j closer than r"""
        out = []
        for i, q in enumerate(self.pts):
            for j in self.near(q, r):
                if j > i:
                    out.append((float(np.hypot(*(self.pts[j] - q))), i, j))
        return out


_GOLD: dict = {}            # screenshot path -> (dash centres, distance-to-gold field, float16)
GOLD_CACHE = 160            # ~4 MB each; kept between checks so local updates re-use them (a local
                            # re-check reads ~110: at 80 every one was decoded again each time)


_DASHES: dict = {}


def _dashes(atlas, f):
    """the new detector's path dashes of a screenshot (dim/fog dashes, amber dash strokes), computed once"""
    key = f["path"]
    if key in _DASHES:
        _DASHES[key] = _DASHES.pop(key)
        return _DASHES[key]
    img = atlas.image(f["path"])
    _DASHES[key] = (atlas_detect.path_dashes(img), atlas_detect.amber_dashes(img))
    while len(_DASHES) > GOLD_CACHE:
        _DASHES.pop(next(iter(_DASHES)))
    return _DASHES[key]


TRACE_WORKERS = atlas_io.workers(6)          # screenshots traced at once in worker processes (when there are many)
TRACE_PARALLEL_MIN = 12


def _trace_one(job):
    """worker: the new detector's paths between given map positions in one screenshot"""
    import cv2
    path, sp, ok, tower = job
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    return atlas_detect.screen_paths((atlas_detect.path_dashes(img), atlas_detect.amber_dashes(img)), sp, ok, tower)


def _trace_views(atlas, views, tower, log=None):
    """(frame, screen pts, visible, traced paths) for every view; many views are traced in parallel
    (each screenshot is independent), otherwise in this process with the dashes cache"""
    if len(views) >= TRACE_PARALLEL_MIN and TRACE_WORKERS > 1:
        try:
            jobs = [(f["path"], sp, ok, tower) for f, sp, ok in views]
            with atlas_io.process_pool(TRACE_WORKERS) as ex:
                res = list(ex.map(_trace_one, jobs, chunksize=4))
            return [(f, sp, ok, r) for (f, sp, ok), r in zip(views, res)]
        except Exception:
            if log:
                log("parallel path tracing failed, tracing one screenshot at a time")
    return [(f, sp, ok, atlas_detect.screen_paths(_dashes(atlas, f), sp, ok, tower)) for f, sp, ok in views]


_SAVED: dict = {}
SAVED_CACHE = 400
TRACE_MATCH = 30.0          # px: a saved trace's end map -> the atlas map at that spot in the screenshot
CHECK_STEP = 8.0            # px between the points checked along a path
CHECK_NEAR = 9.0            # px: a dash this close to a checked point covers it
CHECK_SEEN = 0.6            # share of a path that must lie in clearly visible ground for a view to judge it
CONFIRM, DENY = 0.35, 0.12  # share of the visible part covered by dashes: confirms / denies the path
LOCAL_RETRACE = 0.0         # px around a map a screenshot missed, traced again (0 = off: 3x slower, recovered 1 of 5 lost paths)
SECTOR = 25.0               # deg: two real paths of one map are almost never closer (crawl: 3.6% under 25)
SECTOR_STRICT = 15.0        # deg: a nearer map this dead ahead blocks the path without further evidence (0.3% of trusted paths)
SECTOR_NEAR = 0.88          # ...and a map in that sector this much nearer is where the path really goes
START_LEN = 40.0            # px along a path that give its starting direction
STRAIGHT_VIEWS, STRAIGHT_MAX = 2, 200.0   # untraced links: 2+ screenshots with gold along it, <= 200 long
SEAM_ON = False             # seam joining: off (user: 0 of 10 fully right; ends snapped to wrong/doubled maps)
SEAM_MAX, SEAM_MIN = 280.0, 50.0   # atlas units: map pairs no screenshot shows together, joined over the seam
SEAM_DASHES = 6            # dashes a seam walk must run along
SEAM_PAD = 70.0             # dashes / maps this far around the pair are used for the walk
END_CONE, END_REACH, END_DASHES, END_VIEWS = 40.0, (15.0, 50.0), 2, 8   # both ends point (user)
CLUMP_R, CLUMP_N, CLUMP_SHARE = 10.0, 4, 9.0    # dash-clump check OFF (user: 11 of 12 dropped paths were real)
ONE_END_SHARE = 0.0         # OFF (debug run: rejected 15 real paths, 0 of the wrong ones) - was 0.5
RUN_OVER = 12.0            # px: a ghost sits ON the dotted line (dashes taken for a base); a real neighbour beside it
PASS_WEAK = 0.3            # a map found by under half its shots that a strong path runs through is dropped
        # never traced end to end: drawn by at least this share of the shots showing both (user)
MAX_BOW_STRONG = 0.30       # traced end to end in 2+ shots (user's clear -3961,-539 path bowed more)
MAX_BOW = 0.18              # max sideways bend / map distance (user: closer maps curve less; 99% of trusted paths <= 0.18)
S_WOBBLE_PX = 0.0           # px floor for the summed-turn S test (3 let a wrong path back; seams with straight S15 are off)
S_BOW, S_BOW_PX = 0.05, 5.0   # an S bows at least this share of its length / px to each side
S_TURN = 14.0               # deg: a path bending one way and then this much the other way is not one path


def _saved(atlas, f):
    """a screenshot's saved detection for the path check: its maps (screen px), its traced paths, a tree of
    its dashes and its clearly-visible grid. Detections saved before v0.92 get their dash record added
    (from the image, once). None when no saved detection is found (then the view is traced the old way)."""
    d = getattr(atlas, "frames_dir", None)
    if d is None or not f.get("sha"):
        return None
    key = f["sha"]
    if key in _SAVED:
        _SAVED[key] = _SAVED.pop(key)
        return _SAVED[key]
    cf = Path(d) / f"{f['sha'][:16]}_{atlas_detect.DETECTOR_ID}.json"
    if not cf.exists():
        return None
    import json
    from scipy.spatial import cKDTree
    data = atlas_io.read_json(cf)
    if data is None:                                 # cut-off cache: treated as not cached
        return None
    if any(k not in data for k in ("dash_pts", "seen_grid", "wall_grid", "amber_pts")):
        img = atlas.image(f["path"]) if Path(f["path"]).exists() else None
        if img is None:
            return None
        data.update(atlas_detect.dash_record(img))
        atlas_io.write_text_atomic(cf, json.dumps(data))
    D = np.asarray(data["dash_pts"], float).reshape(-1, 2)
    rec = {"P": np.array([[n["x"], n["y"]] for n in data["nodes"]], float).reshape(-1, 2),
           "hidden": np.array([bool(n.get("hidden")) for n in data["nodes"]], bool),
           "score": np.array([float(n.get("score", 0.5)) for n in data["nodes"]], float),
           "edges": data["edges"], "tree": cKDTree(D) if len(D) else None,
           "amber": (lambda A: cKDTree(A) if len(A) else None)(np.asarray(data["amber_pts"], float).reshape(-1, 2)),
           "grid": np.array([[c == "1" for c in row] for row in data["seen_grid"]], bool),
           "wall": np.array([[c == "1" for c in row] for row in data["wall_grid"]], bool)}
    _SAVED[key] = rec
    while len(_SAVED) > SAVED_CACHE:
        _SAVED.pop(next(iter(_SAVED)))
    return rec


def _along(line, step=CHECK_STEP, skip=18.0):
    """points every `step` px along a polyline, leaving out `skip` px at both ends (the map bases)"""
    line = np.asarray(line, float).reshape(-1, 2)
    if len(line) < 2:
        return np.zeros((0, 2))
    seg = np.hypot(*np.diff(line, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    if cum[-1] <= 2 * skip:
        return np.zeros((0, 2))
    t = np.arange(skip, cum[-1] - skip, step)
    return np.column_stack([np.interp(t, cum, line[:, 0]), np.interp(t, cum, line[:, 1])])


def _coverage(rec, f, line):
    """(share of the path in clearly visible ground of this screenshot, share of that part covered by dashes)"""
    q = _along(line)
    if not len(q) or rec["tree"] is None:
        return 0.0, 0.0
    w, h = f["w"], f["h"]
    inside = (q[:, 0] > 6) & (q[:, 0] < w - 6) & (q[:, 1] > 6) & (q[:, 1] < h - 6)
    g = rec["grid"]
    gx = np.clip((q[:, 0] // atlas_detect.SEEN_CELL).astype(int), 0, g.shape[1] - 1)
    gy = np.clip((q[:, 1] // atlas_detect.SEEN_CELL).astype(int), 0, g.shape[0] - 1)
    seen = inside & g[gy, gx]
    if not seen.any():
        return 0.0, 0.0
    d, _ = rec["tree"].query(q[seen])
    return float(seen.mean()), float((d <= CHECK_NEAR).mean())


def _on_wall(rec, line_screen) -> float:
    """share of a path's middle (screen px of this screenshot) on the fortress wall (user: never crossed)"""
    if rec is None or not rec["wall"].any():
        return 0.0
    q = _along(line_screen, 6.0, 30.0)
    if not len(q):
        return 0.0
    g, c = rec["wall"], atlas_detect.WALL_CELL
    gx = np.clip((q[:, 0] // c).astype(int), 0, g.shape[1] - 1)
    gy = np.clip((q[:, 1] // c).astype(int), 0, g.shape[0] - 1)
    return float(g[gy, gx].mean())


def _gold(atlas, f):
    """gold path dashes of a screenshot: they depend only on the image, so they are computed once"""
    key = f["path"]
    if key in _GOLD:
        _GOLD[key] = _GOLD.pop(key)
        return _GOLD[key]
    img = atlas.image(f["path"])
    gold = gp.gold_stroke_mask(img)
    _, _, _, cen = cv2.connectedComponentsWithStats(gold, 8)
    dist = cv2.distanceTransform(255 - gold, cv2.DIST_L2, 3)
    _GOLD[key] = (cen[1:].astype(float), np.minimum(dist, 255).astype(np.float16))   # fractions matter (3.5 px)
    while len(_GOLD) > GOLD_CACHE:
        _GOLD.pop(next(iter(_GOLD)))
    return _GOLD[key]


def _maps(atlas):
    out = []
    for f in atlas.frames:
        H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        out.append((f, np.linalg.inv(H)))
    return out


def _visible(f, Hi, pts, margin=FRAME_MARGIN):
    pts = np.asarray(pts, float).reshape(-1, 2)
    sp = core.persp(Hi, pts)
    if not len(sp):
        return sp, np.zeros(0, bool)
    ok = (sp[:, 0] > margin) & (sp[:, 0] < f["w"] - margin) & (sp[:, 1] > margin) & (sp[:, 1] < f["h"] - margin)
    ok &= ~core.on_hud_mask(sp, f["w"], f["h"])
    return sp, ok


def _seg_dist(p, a, b):
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / max(1e-9, np.dot(ab, ab)), 0, 1))
    return float(np.linalg.norm(p - (a + t * ab))), t


def _mst(pts):
    n = len(pts)
    inside, edges = {0}, []
    while len(inside) < n:
        best = None
        for i in inside:
            for j in range(n):
                if j in inside:
                    continue
                d = float(np.linalg.norm(pts[i] - pts[j]))
                if best is None or d < best[0]:
                    best = (d, i, j)
        edges.append((best[1], best[2]))
        inside.add(best[2])
    return edges


def finalize(atlas, log=_log) -> dict:
    maps = _maps(atlas)
    maps_by = {f["name"]: (f, Hi) for f, Hi in maps}
    icons = _clean_icons(atlas, maps)
    nodes = [{"x": float(n["x"]), "y": float(n["y"]), "frames": set(n["frames"]), "tower": bool(n.get("tower")),
              "hidden": bool(n.get("hidden")), "sources": list(n.get("sources", [])), "icons": [],
              "guessed": _guessed(n), "origin": "detected"} for n in atlas.nodes]
    alive = [True] * len(nodes)
    removed_why: dict[int, str] = {}

    def P():
        return np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)

    # ---- 1a. join half-merged duplicates (each seen by different screenshots, a few px apart).
    # A copy sitting on an icon's base position keeps its position (the other copy is often a
    # node the detector anchored on the badge itself, 24 px higher).
    bases = np.array([[ic["bx"], ic["by"]] for ic in icons if ic["name"] != "LostTower"], float).reshape(-1, 2)

    base_grid = _Grid(bases, 40.0)

    def base_fit(nd):
        near = base_grid.near((nd["x"], nd["y"]), 40.0)
        if not near:
            return np.inf
        return float(np.min(np.hypot(bases[near, 0] - nd["x"], bases[near, 1] - nd["y"])))

    pts = P()
    if len(pts):
        joined = 0
        into = list(range(len(nodes)))                  # a joined map -> the map it went into

        def survivor(k):
            while into[k] != k:
                into[k] = into[into[k]]
                k = into[k]
            return k

        for _d0, i0, j0 in sorted(_Grid(pts, PARALLAX_TOL).pairs(PARALLAX_TOL)):
            # a pair whose map was already joined into another is judged with that map, where it is now
            # (otherwise two groups that each joined first were never compared - user's doubled maps)
            i, j = survivor(i0), survivor(j0)
            if i == j or not (alive[i] and alive[j]):
                continue
            dij = math.hypot(nodes[i]["x"] - nodes[j]["x"], nodes[i]["y"] - nodes[j]["y"])
            if dij >= PARALLAX_TOL:
                continue
            seen_i = nodes[i]["frames"] - nodes[i]["guessed"]       # a screenshot that only GUESSED one of
            seen_j = nodes[j]["frames"] - nodes[j]["guessed"]       # them (hidden map) proves nothing
            shared = seen_i & seen_j
            if len(shared) > max(SHARED_OK, SHARED_FRAC * len(seen_i | seen_j)):
                continue                       # seen side by side in many screenshots: two maps
            if shared and len((seen_i | seen_j) - shared) < SHARED_MIN_ALONE:
                continue                       # too few screenshots saw only one there (user: 3 wrong merges
                                               # with 2-4 such shots; the fortress map had 8)
            a, b = nodes[i], nodes[j]
            # one screenshot that found two points on one base (a raised structure, e.g. at the fortress:
            # user) no longer vetoes the join when the others found one map there
            if (dij > DUP_TOL or shared) and not _one_map(maps_by, a, b, ignore=shared):
                continue
            wa, wb = len(a["frames"]), len(b["frames"])
            fa, fb = base_fit(a), base_fit(b)
            if min(fa, fb) < 8 and abs(fa - fb) > 4:
                if fb < fa:
                    a["x"], a["y"] = b["x"], b["y"]
            else:
                a["x"], a["y"] = (a["x"] * wa + b["x"] * wb) / (wa + wb), (a["y"] * wa + b["y"] * wb) / (wa + wb)
            a["frames"] |= b["frames"]
            a["guessed"] = (a["guessed"] | b["guessed"]) - (seen_i | seen_j)
            a["tower"] |= b["tower"]
            a["hidden"] &= b["hidden"]
            a["sources"] += b["sources"]
            alive[j] = False
            into[j] = i
            removed_why[j] = f"joined into {i}"
            joined += 1

        # ---- 1b. maps on a tower's wide base are that tower, even where one screenshot found two of them
        # (it did not recognise the tower there, so the two sat 31-40 px apart: user's tower + ghost map)
        # only around a tower seen as one in 2+ screenshots (a single tower call that the later checks reject
        # left its map flagged "tower": that one must not swallow a real map next to it)
        sure = np.array([[l["x"], l["y"]] for l in atlas.landmarks
                         if l["kind"] == "Tower" and l.get("n", 1) >= TOWER_JOIN_SEEN], float).reshape(-1, 2)
        towers = [i for i in range(len(nodes)) if alive[i] and nodes[i]["tower"] and len(sure)
                  and float(np.min(np.hypot(sure[:, 0] - nodes[i]["x"], sure[:, 1] - nodes[i]["y"]))) < 25]
        towers.sort(key=lambda i: -len(nodes[i]["frames"]))
        tgrid = _Grid(P(), TOWER_JOIN)
        for i in towers:
            if not alive[i]:
                continue
            a = nodes[i]
            for j in tgrid.near((a["x"], a["y"]), TOWER_JOIN):
                if j == i or not alive[j]:
                    continue
                b = nodes[j]
                if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= TOWER_JOIN:
                    continue
                wa, wb = len(a["frames"]), len(b["frames"])
                a["x"], a["y"] = (a["x"] * wa + b["x"] * wb) / (wa + wb), (a["y"] * wa + b["y"] * wb) / (wa + wb)
                a["guessed"] = (a["guessed"] | b["guessed"]) - ((a["frames"] - a["guessed"]) | (b["frames"] - b["guessed"]))
                a["frames"] |= b["frames"]
                a["hidden"] &= b["hidden"]
                a["sources"] += b["sources"]
                alive[j] = False
                into[j] = i
                removed_why[j] = f"on the base of tower {i}"
                joined += 1

    # ---- 2. icons -> nodes.  A map can carry a ROW of badges side by side (~36 px apart, e.g.
    # Abyss + Abyss Overrun + Azmeri Spirit); the base sits under the middle of the row.
    row_of = list(range(len(icons)))

    def root(k):
        while row_of[k] != k:
            row_of[k] = row_of[row_of[k]]
            k = row_of[k]
        return k

    icon_grid = _Grid([[ic["x"], ic["y"]] for ic in icons], ROW_GAP)
    for _, a_i, b_i in icon_grid.pairs(ROW_GAP + 8):
        a, b = icons[a_i], icons[b_i]
        if "LostTower" in (a["name"], b["name"]):
            continue
        if abs(a["y"] - b["y"]) < 8 and abs(a["x"] - b["x"]) < ROW_GAP:
            row_of[root(a_i)] = root(b_i)
    rows: dict[int, list[int]] = {}
    for k in range(len(icons)):
        rows.setdefault(root(k), []).append(k)
    row_base = {}
    for members in rows.values():
        bx = float(np.mean([icons[k]["bx"] for k in members]))
        by = float(np.mean([icons[k]["by"] for k in members]))
        for k in members:
            row_base[k] = (bx, by)

    icon_nodes = []
    det_pts = P()
    det_grid = _Grid(det_pts, 40.0)
    for k, ic in enumerate(icons):
        if ic["name"] == "LostTower":
            continue
        bx, by = row_base[k]
        ic = dict(ic, bx=bx, by=by)
        best_i, best_d = None, np.inf
        for i in det_grid.near((bx, by), math.hypot(ICON_ATTACH_DX, ICON_ATTACH_DY)):
            if alive[i] and abs(nodes[i]["x"] - bx) < ICON_ATTACH_DX and abs(nodes[i]["y"] - by) < ICON_ATTACH_DY:
                dd = math.hypot(nodes[i]["x"] - bx, nodes[i]["y"] - by)
                if dd < best_d:
                    best_i, best_d = i, dd
        if best_i is not None:
            nodes[best_i]["icons"].append(k)
            continue
        if ic["name"] in NO_NODE_ICONS:
            continue
        if ic.get("spread", 0.0) >= ICON_TOWER_SPREAD:
            # copies far apart and no map right under it: a tower's badge (towers are tall, their badges float
            # high and shift between views - user). Give it to a tower map below, never make a map of it.
            tw = [i for i in det_grid.near((bx, by), ICON_TOWER_REACH[1])
                  if alive[i] and nodes[i]["tower"] and abs(nodes[i]["x"] - bx) < ICON_TOWER_REACH[0]
                  and 0 <= nodes[i]["y"] - by <= ICON_TOWER_REACH[1]]
            if tw:
                nodes[min(tw, key=lambda i: math.hypot(nodes[i]["x"] - bx, nodes[i]["y"] - by))]["icons"].append(k)
            continue
        # a second badge over a map already created from its partner badge
        near = [i for i in icon_nodes if math.hypot(nodes[i]["x"] - ic["bx"], nodes[i]["y"] - ic["by"]) < ICON_PAIR]
        if near:
            i = near[0]
            m = len(nodes[i]["icons"])
            nodes[i]["x"] = (nodes[i]["x"] * m + ic["bx"]) / (m + 1)
            nodes[i]["icons"].append(k)
            continue
        nodes.append({"x": ic["bx"], "y": ic["by"], "frames": set(ic["frames"]), "tower": False, "hidden": False,
                      "guessed": set(),
                      "sources": ["icon"], "icons": [k], "origin": "from icon"})
        alive.append(True)
        icon_nodes.append(len(nodes) - 1)

    # a map placed from a badge next to a found map carrying the same badge is that map (user: -15,1291 / -44,1278)
    for i in icon_nodes:
        if not alive[i]:
            continue
        names = {icons[k]["name"] for k in nodes[i]["icons"]}
        for j in det_grid.near((nodes[i]["x"], nodes[i]["y"]), ICON_TWIN):
            if j == i or not alive[j] or nodes[j].get("origin") == "from icon":
                continue
            if names & {icons[k]["name"] for k in nodes[j]["icons"]}:
                nodes[j]["frames"] |= nodes[i]["frames"]
                nodes[j]["icons"] = sorted(set(nodes[j]["icons"]) | set(nodes[i]["icons"]))
                alive[i] = False
                removed_why[i] = f"badge copy of map {j}"
                break

    # ---- 1b. support: how many screenshots could see each node vs. found it
    pts = P()
    could = np.zeros(len(nodes), int)
    for f, Hi in maps:
        could += _visible(f, Hi, pts)[1]
    status = []
    for i, n in enumerate(nodes):
        seen = len(n["frames"])
        n["could"] = int(max(could[i], seen))
        if not alive[i]:
            status.append("removed")
        elif n["icons"] and any(icons[k]["name"] not in NO_NODE_ICONS for k in n["icons"]):
            status.append("icon")
        elif seen >= 2:
            status.append("confirmed")
        elif could[i] <= 1:
            status.append("single")
        elif could[i] >= 3:
            status.append("removed")
            removed_why[i] = f"ghost: found in 1 of {could[i]} screenshots that show this spot"
        else:
            status.append("disputed")          # 1 of 2: decided by paths below

    # relative evidence (user): a map found by few of the screenshots that show it, among neighbours found by
    # nearly all of them, is a ghost - even when 2+ screenshots found it
    ratio = np.array([len(n["frames"]) / max(1, n["could"]) for n in nodes])
    live = [i for i in range(len(nodes)) if status[i] in ("confirmed", "disputed", "single")]
    lgrid = _Grid(pts[live], RATIO_R) if live else None
    for q, i in enumerate(live):
        n = nodes[i]
        if n["tower"] or n["icons"] or n["could"] < min(RATIO_COULD, RATIO_COULD_REL):
            continue
        nb = [live[k] for k in lgrid.near(pts[i], RATIO_R) if live[k] != i]
        if not nb:
            continue
        med = float(np.median(ratio[nb]))
        absolute = n["could"] >= RATIO_COULD and ratio[i] <= RATIO_GHOST and med >= RATIO_NEAR
        relative = med >= RATIO_REL_NEAR and ratio[i] <= RATIO_REL * med    # user D57/D55: 4/9 among 89%, 2/4 among 100%
        if absolute or relative:
            status[i] = "removed"
            removed_why[i] = (f"ghost: found in {len(n['frames'])} of {n['could']} screenshots, its neighbours in "
                              f"{float(np.median(ratio[nb])):.0%}")
    # the gap rule (user): maps (shown or hidden) are drawn OVER the dotted lines, so where a map is, the dashes
    # stop. A "map" with amber dashes inside its ring in every screenshot that clearly shows it is a dash
    # pattern, not a map
    best_score = np.ones(len(nodes))                 # (stays 1 = "clearly visible" when the gap block is off)
    if GAP_ON:
        gap_n = np.zeros(len(nodes), int)
        gap_free = np.zeros(len(nodes), bool)
        best_score = np.zeros(len(nodes))
        from scipy.spatial import cKDTree as _KD
        for f, Hi in maps:
            rec = _saved(atlas, f)
            if rec is None:
                continue
            sp, ok = _visible(f, Hi, pts)
            idx = np.nonzero(ok)[0]
            if not len(idx):
                continue
            if len(rec["P"]):                                     # the map finder's confidence at each spot
                dd, qq = _KD(rec["P"]).query(sp[idx])
                hitm = dd <= 15
                best_score[idx[hitm]] = np.maximum(best_score[idx[hitm]], rec["score"][qq[hitm]])
            cnt = (np.array([len(x) for x in rec["tree"].query_ball_point(sp[idx], GAP_R)])   # all dashes (dim too)
                   if rec["tree"] is not None else np.zeros(len(idx), int))
            gap_n[idx] += 1
            gap_free[idx[cnt < GAP_MIN]] = True
        for i in range(len(nodes)):
            if (status[i] not in ("removed", "icon") and not nodes[i]["tower"] and not nodes[i]["icons"]
                    and best_score[i] < GAP_SEEN and gap_n[i] >= GAP_SHOTS and not gap_free[i]
                    and len(nodes[i]["frames"]) < GAP_FOUND * max(1, nodes[i].get("could", 0))):
                status[i] = "removed"
                removed_why[i] = f"no gap in the dotted line in any of {gap_n[i]} screenshots: not a map"

    # maps on the fortress wall are wall art (user), unless towers
    on_wall = np.zeros(len(nodes), int)
    shown = np.zeros(len(nodes), int)
    for f, Hi in maps:
        rec = _saved(atlas, f)
        if rec is None or not rec["wall"].any():
            continue
        sp, ok = _visible(f, Hi, pts)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            continue
        g, c = rec["wall"], atlas_detect.WALL_CELL
        gx = np.clip((sp[idx, 0] // c).astype(int), 0, g.shape[1] - 1)
        gy = np.clip((sp[idx, 1] // c).astype(int), 0, g.shape[0] - 1)
        shown[idx] += 1
        on_wall[idx] += g[gy, gx]
    for i in range(len(nodes)):
        if status[i] != "removed" and not nodes[i]["tower"] and shown[i] and on_wall[i] >= WALL_MAP * shown[i]:
            status[i] = "removed"
            removed_why[i] = f"on the fortress wall in {on_wall[i]} of {shown[i]} screenshots"

    # ---- 3. abyss chains
    forced: list[tuple[int, int]] = []
    no_other: set[int] = set()
    chain_segments = []
    landmarks = [dict(lm, status="kept") for lm in atlas.landmarks]

    def abyss_count(i):
        return sum(icons[k]["name"] in ABYSS_NAMES for k in nodes[i]["icons"])

    ab = [i for i in range(len(nodes)) if status[i] != "removed" and abyss_count(i)]
    seen_ab, chains = set(), []
    for s in ab:
        if s in seen_ab:
            continue
        comp, stack = [], [s]
        seen_ab.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in ab:
                if v not in seen_ab and math.hypot(nodes[u]["x"] - nodes[v]["x"], nodes[u]["y"] - nodes[v]["y"]) < ABYSS_LINK:
                    seen_ab.add(v)
                    stack.append(v)
        if len(comp) >= 2:
            chains.append(comp)
    for comp in chains:
        cp = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in comp])
        tree = [(comp[a], comp[b]) for a, b in _mst(cp)]
        deg = {i: 0 for i in comp}
        for a, b in tree:
            deg[a] += 1
            deg[b] += 1
        overrun = lambda i: any(icons[k]["name"] == "AbyssOverrun" for k in nodes[i]["icons"])
        final = max(comp, key=lambda i: (abyss_count(i), overrun(i), -deg[i]))
        ends = [i for i in comp if deg[i] == 1 and i != final]
        start = max(ends or comp, key=lambda i: math.hypot(nodes[i]["x"] - nodes[final]["x"],
                                                          nodes[i]["y"] - nodes[final]["y"]))
        forced += tree
        no_other |= set(comp) - {start, final}
        for i in comp:
            nodes[i]["abyss"] = "final" if i == final else "start" if i == start else "chain"
        for a, b in tree:
            chain_segments.append((a, b, {start, final}))
    if chain_segments:
        def near_chain(p, clear):
            for a, b, open_ends in chain_segments:
                pa = np.array([nodes[a]["x"], nodes[a]["y"]])
                pb = np.array([nodes[b]["x"], nodes[b]["y"]])
                dist, t = _seg_dist(p, pa, pb)
                if (t < .2 and a in open_ends) or (t > .8 and b in open_ends):
                    continue           # next to the chain's entry/exit map: may be a real neighbour
                if dist < clear:
                    return True
            return False
        chain_nodes = {i for a, b, _ in chain_segments for i in (a, b)}
        cpts = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in chain_nodes])
        cgrid = _Grid(cpts, ABYSS_LINK)
        for i, n in enumerate(nodes):
            if status[i] == "removed" or i in chain_nodes or status[i] == "icon":
                continue
            if not cgrid.near((n["x"], n["y"]), ABYSS_LINK + ABYSS_TOWER_CLEAR):
                continue
            if near_chain(np.array([n["x"], n["y"]]), ABYSS_CLEAR):
                status[i] = "removed"
                removed_why[i] = "abyss river glow"
        for lm in landmarks:
            if lm["kind"] == "Tower" and near_chain(np.array([lm["x"], lm["y"]]), ABYSS_TOWER_CLEAR):
                lm["status"] = "removed: abyss river glow"

    # ---- 4. atlas-wide paths
    keep = [i for i in range(len(nodes)) if status[i] != "removed"]
    pts = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in keep], float).reshape(-1, 2)
    pos = {i: k for k, i in enumerate(keep)}
    tower = np.array([nodes[i]["tower"] for i in keep], bool)
    blocked_ends = {pos[i] for i in no_other if i in pos}
    maps_by_name = [(f["name"], Hi) for f, Hi in maps]
    views = []
    for f, Hi in maps:
        sp, ok = _visible(f, Hi, pts, margin=6)
        if ok.sum() >= 2:
            views.append((f, sp, ok))
    fields: dict[str, np.ndarray] = {}

    def field(f):
        if f["name"] not in fields:
            fields[f["name"]] = _gold(atlas, f)[1].astype(np.float32)
        return fields[f["name"]]

    cache: dict[tuple[int, int], tuple[float, int, int]] = {}
    node_views: list[set] = [set() for _ in range(len(pts))]
    for vi, (f, sp, ok) in enumerate(views):
        for i in np.nonzero(ok)[0]:
            node_views[int(i)].add(vi)
    pts_grid = _Grid(pts, 100.0)

    def score(i, j):
        key = (min(i, j), max(i, j))
        if key not in cache:
            vals = [gp.route_score(field(views[vi][0]), views[vi][1][i], views[vi][1][j])
                    for vi in sorted(node_views[i] & node_views[j])]
            cache[key] = ((float(np.mean(vals)) if vals else 0.0), len(vals),
                          sum(v >= PATH_THRESHOLD for v in vals))
        return cache[key]

    proposals = []
    n = len(pts)
    visited = set()
    for i in range(n):
        if i in blocked_ends:
            continue
        local = np.array(pts_grid.near(pts[i], 300.0), int)
        dist_l = np.linalg.norm(pts[local] - pts[i], axis=1)
        for q in np.argsort(dist_l)[1:11]:
            j = int(local[q])
            x, y = min(i, j), max(i, j)
            if j in blocked_ends or not 30 <= dist_l[q] <= 300 or (x, y) in visited:
                continue
            visited.add((x, y))
            delta = pts[y] - pts[x]
            L2 = float(delta @ delta)
            loc = np.array(pts_grid.near(pts[x], math.sqrt(L2) + 30), int)     # maps near this link
            lp = pts[loc]
            t = ((lp - pts[x]) @ delta) / L2
            nearest = pts[x] + t[:, None] * delta
            blocking = (np.linalg.norm(lp - nearest, axis=1) < 24) & (t > .12) & (t < .88) & (loc != x) & (loc != y)
            if blocking.any():
                continue
            bad = False
            for s, e in ((x, y), (y, x)):
                out = pts[e] - pts[s]
                L = float(np.linalg.norm(out))
                ls = np.array(pts_grid.near(pts[s], L), int)
                v = pts[ls] - pts[s]
                vl = np.linalg.norm(v, axis=1)
                cosang = (v @ out) / np.maximum(1e-9, vl * L)
                for k in ls[np.nonzero((vl >= 30) & (vl < L * .88) & (cosang > .936))[0]]:
                    if int(k) not in (x, y) and score(s, int(k))[0] >= .53:
                        bad = True
                        break
                if bad:
                    break
            if bad:
                continue
            c, nf, ns = score(x, y)
            if nf and c >= (TOWER_THRESHOLD if tower[x] or tower[y] else PROPOSE):
                proposals.append((x, y, c, float(np.linalg.norm(delta))))
    supported = {(x, y): c for x, y, c, _ in proposals}
    proposals = [p for p in proposals if not _diamond_shortcut(pts, pts_grid, p[0], p[1], supported)
                 and not _bypasses_two(pts, pts_grid, p[0], p[1], supported)]

    def need(i, j):
        return TOWER_THRESHOLD if tower[i] or tower[j] else PATH_THRESHOLD

    # paths as each screenshot traced them when it was detected (saved): traced once, never again (user).
    # The clearest trace of a pair gives its line; the other screenshots only confirm or deny it.
    traces: dict[tuple[int, int], dict] = {}
    Hs = {name: np.linalg.inv(Hi) for name, Hi in maps_by_name}

    def add_trace(f, i, j, line_screen, mutual, dashes):
        if i in blocked_ends or j in blocked_ends or i == j:
            return
        key = (min(i, j), max(i, j))
        L = np.asarray(line_screen, float)
        straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
        detour = float(np.hypot(*np.diff(L, axis=0).T).sum()) / straight
        t = traces.setdefault(key, {"frames": set(), "mutual": set(), "dashes": 0, "line": None, "detour": 1e9,
                                    "clear": (-1, 0.0, 0), "confirm": 0, "deny": 0, "contra": 0})
        t["frames"].add(f["name"])
        if mutual:
            t["mutual"].add(f["name"])
        t["dashes"] = max(t["dashes"], int(dashes))
        t["detour"] = min(t["detour"], detour)
        if int(dashes) >= 5 and len(L) >= 2:                # the smoothest well-dashed trace judges the curve
            ch = L[-1] - L[0]
            n2 = float(ch @ ch)
            if n2 > 1:
                v = L - L[0]
                b_ = float(np.abs(ch[0] * v[:, 1] - ch[1] * v[:, 0]).max() / n2)
                t["minbow"] = min(t.get("minbow", 9.0), b_)
        clear = (1 if mutual else 0, min(int(dashes), 8), -round(detour, 3))   # end-to-end, enough dashes, smoothest
        if clear > t["clear"]:                              # (user D31/D32: a wobbly trace drew a straight path)
            t["clear"] = clear
            line = core.persp(Hs[f["name"]], L)
            line = cv2.approxPolyDP(line.astype(np.float32).reshape(-1, 1, 2), 2.5, False).reshape(-1, 2)
            if i > j:
                line = line[::-1]
            t["line"] = line.astype(float)

    from scipy.spatial import cKDTree
    old_way = []
    for f, sp, ok in views:
        rec = _saved(atlas, f)
        if rec is None:
            old_way.append((f, sp, ok))
            continue
        vis = np.nonzero(ok)[0]
        if not len(vis) or not len(rec["P"]):
            continue
        dist, q = cKDTree(sp[vis]).query(rec["P"])
        to_atlas = {k: int(vis[q[k]]) for k in range(len(rec["P"])) if dist[k] <= TRACE_MATCH}
        # atlas maps this screenshot's own detection missed: its saved traces cannot reach them, so the area
        # around them is traced again with the atlas maps (only there: v0.91 re-traced every screenshot)
        found = set(to_atlas.values())
        missing = [int(i) for i in vis if int(i) not in found]
        if missing and LOCAL_RETRACE > 0:
            local = np.zeros(len(sp), bool)
            mp = sp[missing]
            for i in vis:
                if np.min(np.hypot(mp[:, 0] - sp[i, 0], mp[:, 1] - sp[i, 1])) <= LOCAL_RETRACE:
                    local[i] = True
            if local.sum() >= 2:
                miss = set(missing)
                for (i, j), r in atlas_detect.screen_paths(_dashes(atlas, f), sp, local, tower).items():
                    if (i in miss or j in miss) and _on_wall(rec, r["line"]) < atlas_detect.WALL_CROSS:
                        add_trace(f, i, j, r["line"], len(r["from"]) == 2, r["dashes"])
        for e in rec["edges"]:
            i, j = to_atlas.get(e["a"]), to_atlas.get(e["b"])
            if i is None or j is None:
                continue
            L = np.asarray(e["line"], float)
            if _on_wall(rec, L) >= atlas_detect.WALL_CROSS:
                continue                                    # through the fortress wall (detected before v0.92)
            seen, cov = _coverage(rec, f, L)
            dashes = int(round(cov * seen * len(_along(L))))
            dashes = max(dashes, int(round(float(e.get("conf", 0)) * 10)))   # the tracer's own count (dark ground)
            add_trace(f, i, j, L, e.get("status") == "chain", dashes)
    for f, sp, ok, res in (_trace_views(atlas, old_way, tower, log) if old_way else []):
        for (i, j), r in res.items():
            add_trace(f, i, j, r["line"] if i < j else r["line"][::-1], len(r["from"]) == 2, r["dashes"])

    # every other screenshot that shows both maps: dashes along the line confirm it; a clearly visible,
    # empty stretch denies it; dark / fog / blurred / off-screen says nothing (user's image 3)
    for (i, j), t in traces.items():
        if t["line"] is None:
            continue
        for vi in node_views[i] & node_views[j]:
            f = views[vi][0]
            if f["name"] in t["frames"]:
                continue
            rec = _saved(atlas, f)
            if rec is None:
                continue
            Ls = core.persp(maps_by[f["name"]][1], t["line"])
            if _on_wall(rec, Ls) >= atlas_detect.WALL_CROSS:
                t["deny"] += 1                              # this screenshot shows the wall in its way (one vote:
                                                            # the wall model can be a little off at its edges)
                continue
            seen, cov = _coverage(rec, f, Ls)
            if seen >= CHECK_SEEN:
                if cov >= CONFIRM:
                    t["confirm"] += 1               # dashes there (only for ranking: a wrong walk can run
                else:                               # along real dashes for most of its way)
                    t["contra"] += 1                # clearly visible, its own tracer did not draw it
                    if cov < DENY:
                        t["deny"] += 1              # clearly visible and empty

    # ---- seams: two maps that no screenshot shows together (user). Their path is a dead end in each
    # screenshot; the dashes of all screenshots around them are put together in atlas coordinates and
    # walked like one screenshot. Only pairs without any trace; the usual rules judge the result.
    seam_n = 0
    det = [] if not SEAM_ON else [nodes[keep[k]]["frames"] - nodes[keep[k]]["guessed"] for k in range(n)]   # screenshots that FOUND it
    for i in range(n if SEAM_ON else 0):
        if i in blocked_ends or not node_views[i]:
            continue
        for j in pts_grid.near(pts[i], SEAM_MAX):
            if j <= i or j in blocked_ends or not node_views[j] or (i, j) in traces:
                continue
            if det[i] & det[j] or not det[i] or not det[j]:
                continue                                    # some screenshot found both: it traced them itself
            dij = float(np.hypot(*(pts[i] - pts[j])))
            if dij < SEAM_MIN:
                continue
            lo = np.minimum(pts[i], pts[j]) - SEAM_PAD
            hi = np.maximum(pts[i], pts[j]) + SEAM_PAD
            D, src = [], {}
            for vi in node_views[i] | node_views[j]:
                f = views[vi][0]
                if f["name"] not in det[i] | det[j]:
                    continue                                # only screenshots that found one of the two
                rec = _saved(atlas, f)
                if rec is None or rec["tree"] is None:
                    continue
                q = core.persp(Hs[f["name"]], rec["tree"].data)
                q = q[(q[:, 0] >= lo[0]) & (q[:, 0] <= hi[0]) & (q[:, 1] >= lo[1]) & (q[:, 1] <= hi[1])]
                if len(q):
                    D.append(q)
                    src[f["name"]] = "i" if f["name"] in det[i] else "j"
            if len(D) < 2 or set(src.values()) != {"i", "j"}:
                continue
            D = np.unique(np.round(np.vstack(D) / 3) * 3, axis=0)           # overlapping shots: same dash once
            loc = [k for k in pts_grid.near((pts[i] + pts[j]) / 2, dij / 2 + SEAM_PAD)]
            local = [{"x": float(pts[k][0]), "y": float(pts[k][1]), "tower": bool(tower[k])} for k in loc]
            ii, jj = loc.index(i), loc.index(j)
            for w in atlas_detect.walk_paths(local, D):
                if {w["a"], w["b"]} != {ii, jj}:
                    continue
                L = np.asarray(w["line"], float)
                if w["a"] != ii:
                    L = L[::-1]
                straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
                traces[(i, j)] = {"frames": set(src), "mutual": set(), "dashes": int(w["dashes"]), "line": L,
                                  "detour": float(np.hypot(*np.diff(L, axis=0).T).sum()) / straight,
                                  "clear": (0, min(int(w["dashes"]), 8), 0.0), "confirm": 0, "deny": 0, "contra": 0, "seam": True}
                for vi in node_views[i] | node_views[j]:             # a wall on either side stops it
                    rec = _saved(atlas, views[vi][0])
                    if _on_wall(rec, core.persp(maps_by[views[vi][0]["name"]][1], L)) >= atlas_detect.WALL_CROSS:
                        traces[(i, j)]["deny"] += 99
                seam_n += 1
                break
    if log and seam_n:
        log(f"paths across screenshot seams: {seam_n} candidates")

    def could_both(i, j):
        return len(node_views[i] & node_views[j])

    def passed_maps(key, line, clear=None):
        """the third maps a path's line runs past (interior points within PASS_CLEAR, or `clear`)"""
        if line is None or len(line) < 3:
            return set()
        dense = np.vstack([np.linspace(a0, a1, 6) for a0, a1 in zip(line[:-1], line[1:])])
        ends = pts[list(key)]
        inner = dense[(np.linalg.norm(dense - ends[0], axis=1) > 20) & (np.linalg.norm(dense - ends[1], axis=1) > 20)]
        return {k for q in inner for k in pts_grid.near(q, clear or PASS_CLEAR) if k not in key}

    def weak_map(k):
        nd = nodes[keep[k]]
        return nd.get("origin") == "from icon" or len(nd["frames"]) < PASS_WEAK * max(1, nd.get("could", 1))

    ends_at: dict = {}                         # traced paths ending at each map (any screenshot)
    for (a_, b_) in traces:
        ends_at[a_] = ends_at.get(a_, 0) + 1
        ends_at[b_] = ends_at.get(b_, 0) + 1
    run_by: dict = {}
    run_over: set = set()                      # weak maps a strongly traced path runs through: ghosts (user D54 etc.)

    def passes_a_map(key, line, t=None):
        """a path never runs past a third map: interior points within PASS_CLEAR of one. A path traced end to end
        in 2+ screenshots may pass a map: a weak one there is a ghost (dropped), a well-seen one a floating map"""
        if t is not None and len(t["mutual"]) >= 2:
            on_line = passed_maps(key, line, RUN_OVER)             # ON the line only
            on_line = {k for k in on_line if ends_at.get(k, 0) < JUNCTION}
            if on_line and all(weak_map(k) for k in on_line):
                for k in on_line:
                    run_over.add(k)
                    run_by.setdefault(k, key)
                return False
            if not on_line and not (passed_maps(key, line) - set()):
                return False
            if not on_line:
                return False                                       # beside a map, not on it: allowed (floating map)
            return True                                            # through a well-seen map: two paths joined
        if line is None or len(line) < 3:
            return False
        dense = np.vstack([np.linspace(a0, a1, 6) for a0, a1 in zip(line[:-1], line[1:])])
        ends = pts[list(key)]
        inner = dense[(np.linalg.norm(dense - ends[0], axis=1) > 20) & (np.linalg.norm(dense - ends[1], axis=1) > 20)]
        if not len(inner):
            return False
        for q in inner:
            if any(k not in key for k in pts_grid.near(q, PASS_CLEAR)):
                return True
        return False

    def start_dir(line, frm):
        """unit direction a path leaves map `frm` (first START_LEN of its line)"""
        L = np.asarray(line, float)
        if np.hypot(*(L[0] - pts[frm])) > np.hypot(*(L[-1] - pts[frm])):
            L = L[::-1]
        cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(L, axis=0).T))])
        q = L[min(int(np.searchsorted(cum, START_LEN)), len(L) - 1)]
        v = q - pts[frm]
        n = float(np.hypot(*v))
        return v / n if n > 1e-6 else (L[-1] - L[0]) / max(1e-6, float(np.hypot(*(L[-1] - L[0]))))

    def skips_nearer(key, line):
        """user's sector rule: a path heading (within SECTOR) for a map that is nearer than its end goes there"""
        cos_s, cos_strict = math.cos(math.radians(SECTOR)), math.cos(math.radians(SECTOR_STRICT))
        for frm, to in (key, key[::-1]):
            d_end = float(np.hypot(*(pts[to] - pts[frm])))
            u = start_dir(line, frm)
            for k in pts_grid.near(pts[frm], d_end * SECTOR_NEAR):
                if k in key:
                    continue
                v = pts[k] - pts[frm]
                dk = float(np.hypot(*v))
                if dk < 30 or float(v @ u) / dk < cos_s:
                    continue
                kk = (min(frm, k), max(frm, k))
                if float(v @ u) / dk >= cos_strict or kk in traces or score(frm, k)[0] >= .53:
                    return True                     # dead ahead: always; in the sector: with evidence
        return False

    def bow(line):
        L = np.asarray(line, float)
        ch = L[-1] - L[0]
        n = float(np.hypot(*ch))
        if n < 1:
            return 0.0
        v = L - L[0]
        return float(np.abs(ch[0] * v[:, 1] - ch[1] * v[:, 0]).max() / n / n)

    def s_shaped(line):
        """user: a path changes direction once. S-shaped = it bows clearly to BOTH sides of the line between
        its ends (a straight trace's pixel wobble no longer counts: user's straight S15 was called S-shaped)"""
        L = np.asarray(line, float)
        if len(L) < 4:
            return False
        ch = L[-1] - L[0]
        n_ = float(np.hypot(*ch))
        if n_ < 1:
            return False
        v = L - L[0]
        side = (ch[0] * v[:, 1] - ch[1] * v[:, 0]) / n_          # signed px from the chord
        lim = max(S_BOW_PX, S_BOW * n_)
        if side.max() >= lim and side.min() <= -lim:
            return True
        # turning clearly one way and then the other (summed turns), with real bends to both sides
        a_ = np.degrees(np.arctan2(*np.diff(L, axis=0)[:, ::-1].T))
        turn = (np.diff(a_) + 180) % 360 - 180
        both = side.max() >= S_WOBBLE_PX and side.min() <= -S_WOBBLE_PX
        return both and min(turn[turn > 0].sum(), -turn[turn < 0].sum()) >= S_TURN

    def clumped(t):
        """share of the trace (in the screenshots that drew it) that runs through dash CLUMPS: a real path is
        one row of spaced dashes; amber trees and lit structures give piles of them (user: 2499 -> 2533)"""
        worst = 0.0
        for name in list(t["frames"])[:4]:
            if name not in maps_by:
                continue
            f, Hi = maps_by[name]
            rec = _saved(atlas, f)
            if rec is None or rec["tree"] is None:
                continue
            q = _along(core.persp(Hi, t["line"]), 6.0, 20.0)
            if not len(q):
                continue
            cnt = np.array([len(x) for x in rec["tree"].query_ball_point(q, CLUMP_R)])
            worst = max(worst, float((cnt >= CLUMP_N).mean()))
        return worst >= CLUMP_SHARE

    def ends_point(key, line):
        """user: a real path leaves BOTH its maps pointing at the other one. For each end, some screenshot
        that found that map shows dashes 15-50 px out of it within END_CONE degrees of the path's direction"""
        cos_c = math.cos(math.radians(END_CONE))
        for e in key:
            o = key[1] if e == key[0] else key[0]
            u = (pts[o] - pts[e]) / max(1e-6, float(np.hypot(*(pts[o] - pts[e]))))   # straight at the other map
            ok = False
            for vi in list(node_views[e])[:END_VIEWS]:
                f = views[vi][0]
                rec = _saved(atlas, f)
                if rec is None or rec["tree"] is None:
                    continue
                Hi = maps_by[f["name"]][1]
                se = core.persp(Hi, [pts[e]])[0]
                ahead = core.persp(Hi, [pts[e] + u * 40.0])[0] - se
                n_ = float(np.hypot(*ahead))
                if n_ < 1e-6:
                    continue
                ahead /= n_
                near = rec["tree"].query_ball_point(se, END_REACH[1])
                if not near:
                    continue
                v = rec["tree"].data[near] - se
                d = np.hypot(v[:, 0], v[:, 1])
                m = (d >= END_REACH[0]) & ((v @ ahead) >= cos_c * np.maximum(d, 1e-6))
                if int(m.sum()) >= END_DASHES:
                    ok = True
                    break
            if not ok:
                return False
        return True

    def trace_ok(key, t):
        if passes_a_map(key, t["line"], t):
            t["why"] = "runs past a third map"
            return False
        strong_ = len(t["mutual"]) >= 2 and not t.get("seam")
        if t["line"] is not None and t.get("minbow", bow(t["line"])) > (MAX_BOW_STRONG if strong_ else MAX_BOW):
            t["why"] = "curves too much for its length"
            return False
        strong = not t.get("seam") and (len(t["mutual"]) >= 2 or len(t["frames"]) >= 2)   # traced end to end
        if t.get("seam") and (t["dashes"] < SEAM_DASHES or t["deny"]):     # twice / in 2+ shots (seams: never)
            t["why"] = "seam: too few dashes / wall"
            return False
        if not strong and t["line"] is not None and s_shaped(t["line"]):   # user: real paths can have a mild S
            t["why"] = "s-shaped"
            return False
        if not strong and t["line"] is not None and skips_nearer(key, t["line"]):
            t["why"] = "skips a nearer map"
            return False
        support = len(t["frames"]) if not t.get("seam") else 2     # screenshots whose own tracer drew it
        if not t["mutual"] and not t.get("seam") and support < ONE_END_SHARE * could_both(*key):
            t["why"] = "only one-end traces, drawn by under half the screenshots that show both maps"
            return False
        if not strong_ and t["line"] is not None and clumped(t):
            t["why"] = "runs through clumps of dashes (amber trees / structure lights), not a row of dashes"
            return False
        if not t["mutual"] and t["line"] is not None and not ends_point(key, t["line"]):
            t["why"] = "an end map shows no dashes leaving toward the other map"
            return False
        if not t["mutual"] and t["contra"] > support:
            t["why"] = "more clear screenshots show both maps without it than drew it"
            return False
        if support >= 2 or (t["mutual"] and t["contra"] == 0):   # drawn twice, or both ends reached and no
            return t["deny"] < support                      # clear view contradicts it
        # one one-end trace (a walk that may have run on where that screenshot missed a map): kept unless a
        # clearly visible view shows both maps without it; dark / fog / off-screen views never count (user)
        if t["dashes"] >= 5 and t["contra"] == 0:
            return True
        t["why"] = "one weak one-end trace" if t["dashes"] < 5 else "one trace, and a clear view shows both maps without it"
        return False

    degree = np.zeros(n, int)
    chosen: list[tuple[int, int, float, str, np.ndarray]] = []   # i, j, confidence, kind, shape

    def shape_of(i, j, line=None):
        return line if line is not None and len(line) >= 2 else np.array([pts[i], pts[j]])

    seg_cells: dict[tuple[int, int], list[int]] = {}
    SEG_CELL = 150.0

    def cells_of(shp):
        lo, hi = np.floor(shp.min(axis=0) / SEG_CELL).astype(int), np.floor(shp.max(axis=0) / SEG_CELL).astype(int)
        return [(gx, gy) for gx in range(lo[0], hi[0] + 1) for gy in range(lo[1], hi[1] + 1)]

    pair_set: set = set()

    crossed = [None]

    def crosses(i, j, shp):
        near = {c for cell in cells_of(shp) for c in seg_cells.get(cell, ())}
        for idx in near:
            k, l, _, kind_o, other = chosen[idx]
            if len({i, j, k, l}) < 4:
                continue
            for a0, a1 in zip(shp[:-1], shp[1:]):
                for b0, b1 in zip(other[:-1], other[1:]):
                    if gp._crosses(a0, a1, b0, b1):
                        crossed[0] = (min(k, l), max(k, l), kind_o)
                        return True
        return False

    exits: dict[int, list] = {}

    def same_sector(i, j, shp):
        """another chosen path already leaves i (or j) in this direction (user's sector rule)"""
        cos_s = math.cos(math.radians(SECTOR * 0.8))
        for frm in (i, j):
            u = start_dir(shp, frm)
            if any(float(u @ w) > cos_s for w in exits.get(frm, [])):
                return True
        return False

    blocked_by: dict = {}                                  # (inspection aid) pair -> why selection refused it

    def take(i, j, conf, kind, shp):
        kk = (min(i, j), max(i, j))
        if kk in pair_set:
            return False
        if degree[i] >= MAX_EXITS or degree[j] >= MAX_EXITS:
            blocked_by.setdefault(kk, "5 paths already")
            return False
        tk = traces.get((min(i, j), max(i, j)))
        sure = tk is not None and (len(tk["mutual"]) >= 2 or len(tk["frames"]) >= 3)
        if kind != "abyss" and not sure and same_sector(i, j, shp):
            if (min(i, j), max(i, j)) in traces:
                traces[(min(i, j), max(i, j))]["why"] = "same sector as a chosen path"
            return False
        if kind != "abyss" and crosses(i, j, shp):
            blocked_by.setdefault(kk, ("crosses", crossed[0]))
            return False
        chosen.append((i, j, conf, kind, shp))
        pair_set.add((min(i, j), max(i, j)))
        for cell in cells_of(shp):
            seg_cells.setdefault(cell, []).append(len(chosen) - 1)
        degree[[i, j]] += 1
        for frm in (i, j):
            exits.setdefault(frm, []).append(start_dir(shp, frm))
        return True

    for a, b in forced:
        if a in pos and b in pos:
            take(pos[a], pos[b], 1.0, "abyss", shape_of(pos[a], pos[b]))
    ranked = sorted(((k, t) for k, t in traces.items() if trace_ok(k, t)),
                    key=lambda kt: (-len(kt[1]["mutual"]), -len(kt[1]["frames"]), -kt[1]["confirm"],
                                    -kt[1]["dashes"], round(kt[1]["detour"], 2),
                                    float(np.linalg.norm(pts[kt[0][0]] - pts[kt[0][1]]))))
    globals()["_last_traces"] = (traces, pts)
    globals()["_last_blocked"] = blocked_by
    globals()["_last_run_by"] = (run_by, pts)          # (inspection aid for tests / debugging)
    for (i, j), t in ranked:
        take(i, j, 1.0, "traced", shape_of(i, j, t["line"]))
    def walled(i, j):
        """a straight link through the fortress wall in any screenshot that shows it"""
        for vi in node_views[i] & node_views[j]:
            f, sp, _ok = views[vi]
            rec = _saved(atlas, f)
            if rec is not None and _on_wall(rec, np.array([sp[i], sp[j]])) >= atlas_detect.WALL_CROSS:
                return True
        return False

    proposals = [p for p in proposals if not walled(p[0], p[1])]
    rejected = {k for k, t in traces.items() if not trace_ok(k, t)}   # a traced pair judged not a path:
    proposals = [p for p in proposals if (min(p[0], p[1]), max(p[0], p[1])) not in rejected]   # no straight line either
    # an untraced straight link: only with gold along it in STRAIGHT_VIEWS screenshots and not too long
    # (user: missing a real path is better than a fake one - later screenshots fill the gaps)
    proposals = [p for p in proposals if score(p[0], p[1])[2] >= STRAIGHT_VIEWS and p[3] <= STRAIGHT_MAX]
    for i, j, c, L in sorted(proposals, key=lambda p: (-int(p[2] >= need(p[0], p[1])), p[3], -p[2])):
        if c >= need(i, j):
            take(i, j, c, "straight", shape_of(i, j))
    for i, j, c, L in sorted(proposals, key=lambda p: (p[3], -p[2])):     # one weak link for a lonely node
        if c < need(i, j) and PROPOSE <= c and not (degree[i] and degree[j]):
            take(i, j, c, "straight", shape_of(i, j))

    # weak maps that a path traced end to end runs straight through are ghosts: removed with their paths
    for k in run_over:
        i = keep[k]
        if status[i] != "removed":
            status[i] = "removed"
            removed_why[i] = "a path traced end to end runs through it: not a map"
    if run_over:
        chosen[:] = [c for c in chosen if c[0] not in run_over and c[1] not in run_over]
        for k in run_over:
            degree[k] = 0

    # ---- 5. nodes nobody can corroborate
    for k, i in enumerate(keep):
        if degree[k]:
            continue
        if status[i] == "disputed":
            status[i] = "removed"
            removed_why[i] = "found in 1 of 2 screenshots and no dotted path reaches it"
        elif status[i] == "single" and not nodes[i]["tower"]:
            status[i] = "doubtful"
        elif (LONELY_ON and status[i] == "confirmed" and not nodes[i]["tower"] and not nodes[i]["icons"]
              and nodes[i].get("could", 0) >= LONELY_SHOTS and best_score[i] < LONELY_SEEN):
            # user: a map with no badge and no path is very unlikely; a real floating map is rare and never hidden,
            # losing a few of them is better than keeping the ghosts. Only inside the explored area (3+ shots)
            status[i] = "removed"
            removed_why[i] = "no badge and no path reaches it"

    # ---- 6. landmarks: Halls / Cities by beam colour, then the seen / could-see test
    landmarks = _settlements(atlas, maps, landmarks, icons)
    for lm in landmarks:
        if lm["status"] != "kept" or lm.get("beam"):
            continue
        c = sum(_visible(f, Hi, [[lm["x"], lm["y"]]], margin=30)[1][0] for f, Hi in maps)
        lm["could"] = int(max(c, lm["n"]))
        if lm["n"] == 1 and c >= 3:
            lm["status"] = f"removed: found in 1 of {c} screenshots"
        elif lm["n"] == 1 and c == 2:
            lm["status"] = "disputed"

    # one of each badge per map (user): a second copy of the same badge on one map is the same badge seen
    # elsewhere (mountain parallax): the copy seen in fewer screenshots is dropped
    dup_badge: set = set()
    for nd in nodes:
        best: dict = {}
        for k in nd["icons"]:
            nm = icons[k]["name"]
            if nm == "Unidentified":
                continue
            if nm in best:
                lo, hi = sorted((best[nm], k), key=lambda q: icons[q]["n"])
                dup_badge.add(lo)
                best[nm] = hi
            else:
                best[nm] = k
        # two badges on the SAME spot of one map are one badge read two ways (Delirium / Grand Mirror / Ancient
        # Trove get confused): the reading seen more often wins (user D34-D36)
        ks = sorted((k for k in nd["icons"] if k not in dup_badge), key=lambda q: -icons[q]["n"])
        for a_, k1 in enumerate(ks):
            if k1 in dup_badge:
                continue
            for k2 in ks[a_ + 1:]:
                if k2 not in dup_badge and math.hypot(icons[k1]["x"] - icons[k2]["x"],
                                                      icons[k1]["y"] - icons[k2]["y"]) < SAME_SPOT:
                    dup_badge.add(k2)
        nd["icons"] = [k for k in nd["icons"] if k not in dup_badge]

    out_nodes = []
    for i, nd in enumerate(nodes):
        out_nodes.append({"id": i, "x": round(nd["x"], 2), "y": round(nd["y"], 2), "status": status[i],
                          "seen": len(nd["frames"]), "could": nd.get("could", 0), "frames": sorted(nd["frames"]),
                          "tower": nd["tower"], "origin": nd["origin"],
                          "icons": [icons[k]["name"] for k in nd["icons"]],
                          "abyss": nd.get("abyss", ""), "why": removed_why.get(i, "")})
    out_paths = []
    for i, j, c, kind, shp in chosen:
        t = traces.get((min(i, j), max(i, j)))
        nf = could_both(i, j)
        seen_in = len(t["frames"]) if t else (score(i, j)[2] if kind == "straight" else 0)
        rec = {"a": keep[i], "b": keep[j], "kind": kind, "frames": nf, "seen_in": seen_in,
               "both_ends": bool(t and t["mutual"]), "abyss": kind == "abyss", "score": round(c, 3)}
        if t:                                       # why it is drawn (shown when the path is selected)
            rec["ends_in"] = len(t["mutual"])
            rec["confirm"], rec["deny"] = int(t["confirm"]), int(t["deny"])
            rec["dashes"] = int(t["dashes"])
        if kind == "traced" and len(shp) > 2:
            rec["line"] = [[round(float(x), 1), round(float(y), 1)] for x, y in shp]
        out_paths.append(rec)
    stats = {
        "nodes_kept": sum(s not in ("removed",) for s in status),
        "ghosts_removed": sum(1 for i, s in enumerate(status) if s == "removed" and "ghost" in removed_why.get(i, "")),
        "river_removed": sum(1 for v in removed_why.values() if v == "abyss river glow"),
        "unsupported_removed": sum(1 for v in removed_why.values() if v.startswith("found in 1 of 2")),
        "duplicates_joined": sum(1 for v in removed_why.values() if v.startswith("joined")),
        "nodes_from_icons": len(icon_nodes),
        "doubtful": status.count("doubtful"),
        "paths": len(out_paths),
        "paths_multi": sum(p["seen_in"] >= 2 for p in out_paths),
        "paths_traced": sum(p["kind"] == "traced" for p in out_paths),
        "abyss_chains": len(chains),
        "landmarks_removed": sum(lm["status"].startswith("removed") for lm in landmarks),
    }
    # the special-boss crest marks a Hall / City boss next to the building, otherwise a deadly
    # map boss (e.g. the red spiky trees)
    settle = [lm for lm in landmarks if lm["kind"] in ("City", "Hall") and not lm["status"].startswith("removed")]
    for ic in icons:
        if ic["name"] == "MapBossSpecial":
            near = [lm for lm in settle if math.hypot(lm["x"] - ic["bx"], lm["y"] - ic["by"]) < SETTLE_BADGE]
            ic["label"] = f"Deadly Map Boss ({near[0]['kind']})" if near else "Deadly Map Boss"
    # badges to show: on a kept map, or seen by most screenshots that show the spot
    on_map = {k for i, nd in enumerate(nodes) if status[i] != "removed" for k in nd["icons"]}
    out_icons = []
    for k, ic in enumerate(icons):
        if k in dup_badge:
            continue
        if k in on_map or (ic["name"] != "Unidentified" and ic["n"] * 2 >= ic["could"]):
            out_icons.append({key: (round(v, 2) if isinstance(v, float) else v) for key, v in ic.items()})
    stats["icons_shown"] = len(out_icons)
    stats["icons_dropped"] = len(atlas.icons) - len(out_icons)
    atlas.final = {"nodes": out_nodes, "paths": out_paths, "landmarks": landmarks, "icons": out_icons,
                   "stats": stats}
    if log:
        log("final: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return atlas.final


ICON_DUP = 24.0            # same badge placed a few px apart by different screenshots
SETTLE_MERGE = 90.0        # Hall / City detections this close are one building
SETTLE_BADGE = 200.0       # a Hall / City has a Deadly Map Boss badge this close (crawl: 66 of 67
                           # cities within 26; "Halls" with none within 350 were corruption / fog / forest)
CITY_BASE = rc_paths.ref("city_base.png")   # the brass barrel a City's map stands on
BARREL_NCC, BARREL_SAT = 0.42, 88   # fitted on 30 bases the user labelled: 17 of 18 cities, 2 of 12 halls
_city_tpl = None
# map types that never share a map (user's rule): hideout, city, corruption, cleansed, hall, deadly
# map boss, breach stronghold, merchant, abyss.  Badge families of one type are listed together.
EXCLUSIVE = {"Hideout": "hideout", "Corruption": "corruption", "CorruptionNexus": "corruption",
             "CorruptionNexusNoGrowth": "corruption", "Sanctification": "cleansed",
             "SanctificationBoss": "cleansed", "Trader": "merchant", "Abyss": "abyss",
             "AbyssOverrun": "abyss", "AbyssalDepths": "abyss",
             "Expedition": "expedition"}     # ocean: never a Hall / City / Tower / Hideout (user)


def _barrel(img, x, y, blue_lit: bool = False) -> bool:
    """is the map base at screen (x, y) the brass barrel of a City (Halls stand on a normal base)?"""
    global _city_tpl
    if _city_tpl is None:
        t = cv2.imdecode(np.fromfile(str(CITY_BASE), np.uint8), cv2.IMREAD_COLOR)
        _city_tpl = cv2.cvtColor(t, cv2.COLOR_BGR2LAB).astype(np.float32)
    th, tw = _city_tpl.shape[:2]
    X, Y, P = int(round(x)), int(round(y)), 12
    w = img[Y - 24 - P:Y - 24 + th + P, X - tw // 2 - P:X - tw // 2 + tw + P]
    if w.shape[:2] != (th + 2 * P, tw + 2 * P):
        return False
    r = cv2.matchTemplate(cv2.cvtColor(w, cv2.COLOR_BGR2LAB).astype(np.float32), _city_tpl, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _l, (ax, ay) = cv2.minMaxLoc(r)
    body = cv2.cvtColor(w[ay:ay + th, ax:ax + tw], cv2.COLOR_BGR2HSV)[26:50, 14:46]
    hue = float(np.median(body[..., 0]))
    # brass, not blue: the silver star base of ocean maps with its blue core also fits the template
    # (crawl cities: barrel hue 17-24; ocean star bases 95-103) - unless a blue beam above lights the
    # barrel blue (a slanted City beam: hue 101, only ~75-113 beam px in the column)
    blue = BARREL_BLUE[0] <= hue <= BARREL_BLUE[1]
    return mx >= BARREL_NCC and float(body[..., 1].mean()) >= BARREL_SAT and (blue_lit or not blue)


BARREL_BLUE = (70, 130)
BARREL_LIT = 60            # blue beam px above that make a blue-tinted barrel still count
OCEAN_R, OCEAN_WATER = 350, 0.33   # water share within 350 px: ocean (Expedition) biome. 351 crawl cities: max 0.29
_ocean_img = [None, None]


def _ground_classes(hsv: np.ndarray) -> np.ndarray:
    """per-pixel ground class: 0 water, 1 sand, 2 rock / snow, 3 grass, 4 forest, -1 unknown"""
    H, S, V = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    out = np.full(H.shape, -1, int)
    out[(H >= 78) & (H <= 112) & (S >= 85) & (V >= 50)] = 0      # water (blue-grey rock shadow is less saturated)
    out[(H >= 10) & (H <= 30) & (S >= 25) & (S <= 140) & (V >= 135)] = 1         # sand / desert
    out[(S < 40) & (V >= 95)] = 2                                                # rock / snow
    out[(H >= 30) & (H <= 55) & (S >= 70) & (V >= 95)] = 3                       # bright grass
    out[(H >= 33) & (H <= 90) & (S >= 50) & (V >= 30) & (V < 95)] = 4            # dark forest
    return out


def _ocean(img, x, y) -> bool:
    """is (x, y) in the ocean / Expedition biome? There are NO cities there (nor corruption / cleansed),
    user's rule. Judged by open water around the map (an ocean map may sit on an island, so a wide circle)."""
    if _ocean_img[0] is not img:
        cls = _ground_classes(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
        bad = (gp.gold_stroke_mask(img) > 0) | (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 22) | (core._valid_mask(img) == 0)
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
SETTLE_BADGE = 110.0       # a special-boss badge this close belongs to that building


def _guessed(n: dict) -> set:
    """screenshots that only guessed this map (a hidden map from a badge row, no base seen). Atlases built
    before v0.80 have no "guessed_in": then the badge-row sightings are taken from the sources list, which
    runs parallel to the frames list."""
    if "guessed_in" in n:
        return set(n["guessed_in"])
    fr, src = list(n.get("frames", [])), list(n.get("sources", []))
    return {f for f, s in zip(fr, src) if s == "badge row"} if len(fr) == len(src) else set()


def _one_map(maps_by, a, b, ignore=()) -> bool:
    """Two sightings (never in the same screenshot) are one object seen with parallax / a revisit offset
    when the screenshots that found one of them also show the other's spot, yet found only one there.
    A screenshot where the other spot is out of view (edge, HUD) has no say; each side needs at least one
    screenshot that does show the other spot (a map at a screen edge used to block the join)."""
    for this, other in ((a, b), (b, a)):
        shown = 0
        for name in this["frames"]:
            if name in ignore:                     # a screenshot that found both proves nothing either way
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
            continue                  # seen together in one screenshot: two real badges
        a, b = icons[i], icons[j]
        if d >= ICON_DUP and not _one_map(maps_by, a, b):
            continue
        wa, wb = a["n"], b["n"]
        a["spread"] = max(a.get("spread", 0.0), b.get("spread", 0.0), float(d))   # how far its copies lay apart
        for key in ("x", "y", "bx", "by"):
            a[key] = (a[key] * wa + b[key] * wb) / (wa + wb)
        a["n"] = wa + wb
        a["frames"] = sorted(set(a["frames"]) | set(b["frames"]))
        if a["name"] == "Unidentified":
            a["name"], a["source"] = b["name"], b["source"]
        a["score"] = max(a["score"], b["score"])
        alive[j] = False
    icons = [ic for ic, ok in zip(icons, alive) if ok]
    pts = np.array([[ic["x"], ic["y"]] for ic in icons], float).reshape(-1, 2)
    could = np.zeros(len(icons), int)
    for f, Hi in maps:
        could += _visible(f, Hi, pts, margin=FRAME_MARGIN)[1]
    for ic, c in zip(icons, could):
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
    for cx in (range(int(x - spread), int(x + spread) + 1, 20) if spread else [int(x)]):
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
    cand = [lm for lm in landmarks if lm["kind"] in ("City", "Hall")
            and not lm["status"].startswith("removed: abyss")]
    groups: list[list[dict]] = []
    for lm in sorted(cand, key=lambda l: -l["n"]):
        for g in groups:
            if math.hypot(g[0]["x"] - lm["x"], g[0]["y"] - lm["y"]) < SETTLE_MERGE:
                g.append(lm)
                break
        else:
            groups.append([lm])
    focus = getattr(atlas, "_focus", None)                # local re-check: far ones are not kept anyway
    if focus:
        groups = [g for g in groups if focus[1](g[0]["x"], g[0]["y"])]
    buildings = []
    for g in groups:
        n = sum(l["n"] for l in g)
        votes = {}
        for l in g:
            votes[l["kind"]] = votes.get(l["kind"], 0) + l["n"]
        buildings.append({"x": sum(l["x"] * l["n"] for l in g) / n, "y": sum(l["y"] * l["n"] for l in g) / n,
                          "n": n, "conf": max(l["conf"] for l in g), "source": g[0].get("source", ""),
                          "detected": votes, "spread": 0})
    # (a special-boss badge on its own is NOT a settlement: the red spiky trees carry one too)
    deadly = [ic for ic in icons if ic["name"] == "MapBossSpecial"]
    for b in buildings:
        near = sorted((math.hypot(ic["x"] - b["x"], ic["y"] - b["y"]), k) for k, ic in enumerate(deadly))
        badge = deadly[near[0][1]] if near and near[0][0] < SETTLE_BADGE else None
        clash = None
        if badge is not None:                  # its map carries another exclusive type's badge
            bx0, by0 = badge.get("bx", badge["x"]), badge.get("by", badge["y"])
            clash = next((EXCLUSIVE[ic["name"]] for ic in icons if ic["name"] in EXCLUSIVE
                          and math.hypot(ic.get("bx", ic["x"]) - bx0, ic.get("by", ic["y"]) - by0) < 30), None)
            if clash:
                badge = None
        barrel = False
        if badge is not None:
            bx, by = badge.get("bx", badge["x"]), badge.get("by", badge["y"] + 24)
            for _c, f, sp in atlas.central_views(bx, by, 3):
                im = atlas.image(f["path"]) if Path(f["path"]).exists() else None
                if im is not None and _barrel(im, sp[0], sp[1], max(_beam(im, sp[0], sp[1])[0],
                                                                    _beam(im, sp[0], sp[1], 80)[0]) >= BARREL_LIT):
                    barrel = True
                    break
        views = [(atlas.image(f["path"]), sp)
                 for _c, f, sp in atlas.central_views(b["x"], b["y"], 3) if Path(f["path"]).exists()]
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
        keep.append({"kind": kind, "x": b["x"], "y": b["y"], "n": b["n"], "conf": b["conf"],
                     "source": b["source"], "status": status, "beam": why, "beam_px": [blue, orange],
                     "could": max(seen, b["n"])})
    return keep


def _diamond_shortcut(points, grid, i, j, supported) -> bool:
    """atlas_paths._is_diamond_shortcut, looking only at maps near the link (the original
    walks every map in the atlas per link: 85% of a 22-minute check on a 8k-map atlas)."""
    a, b = points[[i, j]]
    axis = b - a
    length = float(np.linalg.norm(axis))
    if length < 48:
        return False

    def evidence(x, y):
        return supported.get(tuple(sorted((x, y))), 0.)

    side_a, side_b = [], []
    for k in grid.near(a, length):
        if k in (i, j):
            continue
        p = points[k]
        da, db = float(np.linalg.norm(p - a)), float(np.linalg.norm(p - b))
        if max(da, db) > length * .96 or min(da, db) < 25:
            continue
        if min(evidence(i, k), evidence(k, j)) < .60:
            continue
        cross = float(axis[0] * (p[1] - a[1]) - axis[1] * (p[0] - a[0]))
        if abs(cross) < length * 16:
            continue
        (side_a if cross > 0 else side_b).append(k)
    return bool(side_a and side_b)


def _bypasses_two(points, grid, i, j, supported) -> bool:
    """atlas_paths._bypasses_two_shorter_paths, looking only at maps near the link."""
    a, b = points[[i, j]]
    length = float(np.linalg.norm(a - b))
    if length < 76:
        return False
    for k in grid.near(a, length):
        if k in (i, j):
            continue
        mid = points[k]
        da = float(np.linalg.norm(a - mid)); db = float(np.linalg.norm(mid - b))
        if not (30 < da < length * .85 and 30 < db < length * .85):
            continue
        left = supported.get(tuple(sorted((i, k))), 0.)
        right = supported.get(tuple(sorted((j, k))), 0.)
        if min(left, right) >= .64:
            return True
    return False


# ---------------------------------------------------------------------------------- local update
CORE_PAD = 600.0           # around the new screenshots: this area's result is replaced
CONTEXT_PAD = 700.0        # evidence margin: > the longest path (300) + parallax; tested identical to a full check
                           # every screenshot that sees the core is included)


def _footprint(atlas, f):
    H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
    return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])


def finalize_local(atlas, new_names: list[str], log=_log) -> dict:
    """Re-check only the area around the screenshots in new_names and splice it into the existing
    atlas-wide result.  The area gets exactly the evidence a full check would use (every
    screenshot that shows any of it), so its result matches a full check; the rest is kept."""
    if atlas.final is None:
        return finalize(atlas, log)
    polys = [_footprint(atlas, f) for f in atlas.frames if f["name"] in set(new_names)]
    if not polys:
        return atlas.final
    # one box per new screenshot (v1.01: a single box around a batch that pans across the atlas covered
    # half of it); every point of the core still has the full context margin around it
    boxes = np.array([[*p.min(axis=0), *p.max(axis=0)] for p in polys], float)
    core_b = boxes + [-CORE_PAD, -CORE_PAD, CORE_PAD, CORE_PAD]
    ctx_b = core_b + [-CONTEXT_PAD, -CONTEXT_PAD, CONTEXT_PAD, CONTEXT_PAD]

    def _in(b, x, y, pad=0.0):
        return bool(np.any((b[:, 0] - pad <= x) & (x <= b[:, 2] + pad) & (b[:, 1] - pad <= y) & (y <= b[:, 3] + pad)))

    def in_core(x, y):
        return _in(core_b, x, y)

    def in_ctx(x, y):
        return _in(ctx_b, x, y)

    sub = core.Atlas()
    sub._images = atlas._images
    sub.frames_dir = getattr(atlas, "frames_dir", None)
    # only the core's result is kept: image checks that only set a map's colour or a settlement's kind
    # are skipped further out (settlements: with a margin, a badge / merge can reach in from there)
    sub._focus = (in_core, lambda x, y: _in(core_b, x, y, SETTLE_MERGE + SETTLE_BADGE + 50))
    for f in atlas.frames:
        p = _footprint(atlas, f)
        x0, y0, x1, y1 = *p.min(axis=0), *p.max(axis=0)
        if np.any((x1 >= ctx_b[:, 0]) & (x0 <= ctx_b[:, 2]) & (y1 >= ctx_b[:, 1]) & (y0 <= ctx_b[:, 3])):
            sub.frames.append(f)
    sub.nodes = [n for n in atlas.nodes if in_ctx(n["x"], n["y"])]
    sub.icons = [i for i in atlas.icons if in_ctx(i["x"], i["y"])]
    sub.landmarks = [l for l in atlas.landmarks if in_ctx(l["x"], l["y"])]
    fin = finalize(sub, log=None)
    old = atlas.final

    nodes, old_map, sub_map = [], {}, {}
    for i, n in enumerate(old["nodes"]):
        if not in_core(n["x"], n["y"]):
            old_map[i] = len(nodes)
            nodes.append(dict(n, id=len(nodes)))
    for i, n in enumerate(fin["nodes"]):
        if in_core(n["x"], n["y"]):
            sub_map[i] = len(nodes)
            nodes.append(dict(n, id=len(nodes)))
    kept_outside = np.array([[nodes[j]["x"], nodes[j]["y"]] for j in old_map.values()
                             if nodes[j]["status"] != "removed"], float).reshape(-1, 2)
    kept_ids = [j for j in old_map.values() if nodes[j]["status"] != "removed"]

    def end_of(i):
        """sub node -> spliced node id (outside the core: the existing node at that spot)"""
        if i in sub_map:
            return sub_map[i]
        n = fin["nodes"][i]
        if len(kept_outside):
            d = np.hypot(kept_outside[:, 0] - n["x"], kept_outside[:, 1] - n["y"])
            k = int(np.argmin(d))
            if d[k] < 12:
                return kept_ids[k]
        sub_map[i] = len(nodes)
        nodes.append(dict(n, id=len(nodes)))
        return sub_map[i]

    paths, pairs = [], set()
    for p in old["paths"]:
        if p["a"] in old_map and p["b"] in old_map:
            q = dict(p, a=old_map[p["a"]], b=old_map[p["b"]])
            paths.append(q)
            pairs.add((min(q["a"], q["b"]), max(q["a"], q["b"])))
    for p in fin["paths"]:
        na, nb = fin["nodes"][p["a"]], fin["nodes"][p["b"]]
        if not (in_core(na["x"], na["y"]) or in_core(nb["x"], nb["y"])):
            continue
        a, b = end_of(p["a"]), end_of(p["b"])
        key = (min(a, b), max(a, b))
        if a != b and key not in pairs:
            pairs.add(key)
            paths.append(dict(p, a=a, b=b))
    landmarks = ([l for l in old["landmarks"] if not in_core(l["x"], l["y"])] +
                 [l for l in fin["landmarks"] if in_core(l["x"], l["y"])])
    icons = ([i for i in old.get("icons", []) if not in_core(i["x"], i["y"])] +
             [i for i in fin.get("icons", []) if in_core(i["x"], i["y"])])
    stats = dict(old.get("stats", {}))
    stats.update({
        "nodes_kept": sum(n["status"] != "removed" for n in nodes),
        "paths": len(paths),
        "paths_multi": sum(p.get("seen_in", 0) >= 2 for p in paths),
        "paths_traced": sum(p.get("kind") == "traced" for p in paths),
        "icons_shown": len(icons),
        "local_updates": stats.get("local_updates", 0) + 1,
    })
    atlas.final = {"nodes": nodes, "paths": paths, "landmarks": landmarks, "icons": icons, "stats": stats}
    if log:
        log(f"local re-check: {len(sub.frames)} of {len(atlas.frames)} screenshots, "
            f"{len(sub_map)} maps updated")
    return atlas.final
