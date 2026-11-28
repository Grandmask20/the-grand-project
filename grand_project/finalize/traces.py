"""finalize.traces (from atlas_finalize.py)"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import detect as atlas_detect
from grand_project import fileio as atlas_io
from grand_project import gold_paths as gp
from grand_project import logs as atlas_log

from .constants import CHECK_NEAR, CHECK_STEP, FRAME_MARGIN, TRACE_PARALLEL_MIN, TRACE_WORKERS

_log = atlas_log.printer("finalize")


class _Grid:
    """Spatial index: points in square cells, so 'what is near here' looks at a few cells
    instead of the whole atlas (the atlas-wide check was quadratic: 35 min for 8k maps).

    Attributes:
        pts: the points as an (N, 2) float array (atlas units, or screen px for screen points).
        cell: the cell size, same units as the points.
        cells: (cell x, cell y) -> indices of the points in that cell.
    """

    def __init__(self, pts, cell: float):
        """Put the points into square cells.

        Args:
            pts: sequence of (x, y) points, any shape that reshapes to (N, 2).
            cell: the cell size, same units as the points; best near the usual search radius.
        """
        self.pts = np.asarray(pts, float).reshape(-1, 2)
        self.cell = float(cell)
        self.cells: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            self.cells.setdefault((int(x // cell), int(y // cell)), []).append(i)
        self._blocks: dict = {}  # (cell x, cell y, reach) -> candidate indices and points, in the same order

    def near(self, p, r) -> list[int]:
        """Return the indices of the points within distance r of p.

        Args:
            p: the query point (x, y).
            r: the search radius, same units as the points.

        Returns:
            A list of point indices (p itself included if it is one of the points).
        """
        c, k = self.cell, int(math.ceil(r / self.cell))
        cx, cy = int(p[0] // c), int(p[1] // c)
        block = self._blocks.get((cx, cy, k))
        if block is None:  # the cells around: gathered once (the re-check asks ~1.4 million times per 80 adds)
            cand = [
                i
                for gx in range(cx - k, cx + k + 1)
                for gy in range(cy - k, cy + k + 1)
                for i in self.cells.get((gx, gy), ())
            ]
            idx = np.array(cand, np.intp)
            block = self._blocks[(cx, cy, k)] = (idx, self.pts[idx] if len(idx) else np.zeros((0, 2)))
        idx, P = block
        if not len(idx):
            return []
        d = np.hypot(P[:, 0] - p[0], P[:, 1] - p[1])
        return idx[d <= r].tolist()

    def pairs(self, r):
        """List every pair of points closer than r.

        Args:
            r: the distance limit, same units as the points.

        Returns:
            A list of (distance, i, j) tuples with i < j.
        """
        out = []
        for i, q in enumerate(self.pts):
            for j in self.near(q, r):
                if j > i:
                    out.append((float(np.hypot(*(self.pts[j] - q))), i, j))
        return out


_GOLD: dict = {}  # screenshot path -> (dash centres, gold mask packed one bit per pixel, its (h, w))


GOLD_CACHE = 160  # ~0.3 MB each; kept between checks so local updates re-use them (a local


# re-check reads ~110: at 80 every one was decoded again each time)


def _evict_oldest(cache: dict, keep: int) -> None:
    """Let the oldest entries of a cache (most recently used last) go, down to keep.

    The idle release (app.idle) clears these caches from its own thread, without the job's lock: the keys are taken
    in one go (list() of a dict is one step under the GIL) and each is let go only if still there, so a clear
    meanwhile is harmless (iter() then next() raised RuntimeError: the dict changed size during iteration).

    Args:
        cache: the cache (insertion order: oldest first).
        keep: how many entries to keep.
    """
    extra = len(cache) - keep
    if extra > 0:
        for key in list(cache.keys())[:extra]:
            cache.pop(key, None)


_DASHES: dict = {}


def _dashes(atlas, f):
    """Return the new detector's path dashes of a screenshot, computed once (up to GOLD_CACHE are kept).

    Args:
        atlas: the core.Atlas (used to load the image).
        f: the screenshot (frame) dict (needs "path").

    Returns:
        (path_dashes result: dim / fog dashes, amber_dashes result: amber dash strokes) from the detector, or None
        when its picture can't be read (the screenshot gone, its copy too: the path detector failed on nothing,
        and the whole check with it).
    """
    key = f["path"]
    if key in _DASHES:
        _DASHES[key] = _DASHES.pop(key)
        return _DASHES[key]
    img = atlas.image(f["path"])  # (the screenshot, else its copy)
    if img is None:
        return None
    _DASHES[key] = (atlas_detect.path_dashes(img), atlas_detect.amber_dashes(img))
    while len(_DASHES) > GOLD_CACHE:
        _DASHES.pop(next(iter(_DASHES)))
    return _DASHES[key]


def _trace_one(job):
    """Trace the new detector's paths between given map positions in one screenshot (process-pool worker).

    Args:
        job: (screenshot path, map node positions in screen px as (N, 2), visible mask (N,), tower flags (N,)).

    Returns:
        The detector's screen_paths result: (i, j) -> path record (line, from, dashes ...); {} for a screenshot with
        no picture left, None when the file picked couldn't be read (deleted since: traced again through its copy).
    """

    path, sp, ok, tower = job
    if path is None:  # (its picture gone: nothing traced there)
        return {}
    img = core.read_screenshot(path)
    if img is None:  # (deleted after it was picked: _trace_views traces it again, through its copy - CodeRabbit)
        return None
    return atlas_detect.screen_paths((atlas_detect.path_dashes(img), atlas_detect.amber_dashes(img)), sp, ok, tower)


def _trace_views(atlas, views, tower, log=None):
    """Trace the paths in every view with the new detector.

    Many views (TRACE_PARALLEL_MIN or more) are traced in parallel (each screenshot is independent); otherwise,
    or when the process pool fails, in this process with the dashes cache.

    Args:
        atlas: the core.Atlas.
        views: list of (frame dict, map node positions in screen px (N, 2), visible mask (N,)).
        tower: bool array (N,) marking tower map nodes.
        log: callable taking one message string, or None.

    Returns:
        A list of (frame, screen pts, visible, traced paths) for every view; traced paths as in _trace_one.
    """

    def here(f, sp, ok):
        """Trace one view in this process (the dashes cache; the picture through atlas.image: else its copy)."""
        d = _dashes(atlas, f)
        return {} if d is None else atlas_detect.screen_paths(d, sp, ok, tower)

    if len(views) >= TRACE_PARALLEL_MIN and TRACE_WORKERS > 1:
        try:
            jobs = [(atlas.picture(f["path"]), sp, ok, tower) for f, sp, ok in views]  # (screenshot, else copy)
            with atlas_io.process_pool(TRACE_WORKERS) as ex:
                res = list(ex.map(_trace_one, jobs, chunksize=4))
            return [
                (f, sp, ok, here(f, sp, ok) if r is None else r) for (f, sp, ok), r in zip(views, res, strict=False)
            ]
        except Exception:
            if log:
                log("parallel path tracing failed, tracing one screenshot at a time")
    return [(f, sp, ok, here(f, sp, ok)) for f, sp, ok in views]


_SAVED: dict = {}


SAVED_CACHE = 400


def _saved(atlas, f):
    """Load a screenshot's saved detection for the path check (up to SAVED_CACHE are kept).

    Detections saved before v0.92 get their dash record added (from the image, once).

    Args:
        atlas: the core.Atlas (uses atlas.frames_dir).
        f: the screenshot (frame) dict (needs "sha" and "path").

    Returns:
        A dict with "P" (its maps, (N, 2) screen px), "hidden" and "score" (per map), "edges" (its traced paths),
        "tree" (KD-tree of its dashes or None), "amber" (KD-tree of amber dashes or None), "grid" (its
        clearly-visible grid) and "wall" (its fortress wall grid). None when no saved detection is found (then
        the view is traced the old way).
    """
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
    if data is None:  # cut-off cache: treated as not cached
        return None
    if any(k not in data for k in ("dash_pts", "seen_grid", "wall_grid", "amber_pts")):
        img = atlas.image(f["path"])  # (the screenshot, else its copy)
        if img is None:
            return None
        data.update(atlas_detect.dash_record(img))
        atlas_io.write_text_atomic(cf, json.dumps(data))
    D = np.asarray(data["dash_pts"], float).reshape(-1, 2)
    rec = {
        "P": np.array([[n["x"], n["y"]] for n in data["nodes"]], float).reshape(-1, 2),
        "hidden": np.array([bool(n.get("hidden")) for n in data["nodes"]], bool),
        "score": np.array([float(n.get("score", 0.5)) for n in data["nodes"]], float),
        "edges": data["edges"],
        "tree": cKDTree(D) if len(D) else None,
        "amber": (lambda A: cKDTree(A) if len(A) else None)(np.asarray(data["amber_pts"], float).reshape(-1, 2)),
        "grid": np.array([[c == "1" for c in row] for row in data["seen_grid"]], bool),
        "wall": np.array([[c == "1" for c in row] for row in data["wall_grid"]], bool),
    }
    _SAVED[key] = rec
    while len(_SAVED) > SAVED_CACHE:
        _SAVED.pop(next(iter(_SAVED)))
    return rec


def _along(line, step=CHECK_STEP, skip=18.0):
    """Return points every `step` px along a polyline, leaving out `skip` px at both ends (the map bases).

    Args:
        line: the polyline as a sequence of (x, y) points.
        step: spacing between the points, same units as line.
        skip: length left out at each end, same units as line.

    Returns:
        An (N, 2) array of points; empty (0, 2) when the line is shorter than 2 * skip or has under 2 points.
    """
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
    """Measure how much of a path a screenshot shows clearly and how much of that has dashes.

    Args:
        rec: the screenshot's saved detection from _saved.
        f: the screenshot (frame) dict (needs "w", "h").
        line: the path's line in this screenshot's px.

    Returns:
        (share of the path in clearly visible ground of this screenshot, share of that part with a dash within
        CHECK_NEAR px); (0.0, 0.0) when nothing is seen.
    """
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
    """Return the share of a path's middle on the fortress wall (user: never crossed).

    Args:
        rec: the screenshot's saved detection from _saved, or None.
        line_screen: the path's line in this screenshot's px (30 px at each end are left out).

    Returns:
        The share (0.0 to 1.0) of points along the line in wall cells; 0.0 without a wall.
    """
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
    """Return the gold path dashes of a screenshot and their distance field.

    The gold mask depends only on the image, so it is found once and kept packed one bit per pixel (~0.3 MB); the
    distance field is worked out from it on each call (~12 ms). Kept whole, the float16 fields were ~4 MB each and
    the GOLD_CACHE of them stayed in memory after every check (user: 2.6 GB idle with a big atlas).

    Args:
        atlas: the core.Atlas (used to load the image).
        f: the screenshot (frame) dict (needs "path").

    Returns:
        (dash centres as an (N, 2) float array in screen px, distance-to-gold field in screen px as float16,
        capped at 255), or None when its picture is gone (CodeRabbit: the check stopped on it).
    """
    key = f["path"]
    hit = _GOLD.pop(key, None)
    if hit is None:
        img = atlas.image(f["path"])
        if img is None:
            return None
        gold = gp.gold_stroke_mask(img)
        _, _, _, cen = cv2.connectedComponentsWithStats(gold, 8)
        hit = (cen[1:].astype(float), np.packbits(gold > 0), gold.shape)
    _GOLD[key] = hit  # most recently used last
    _evict_oldest(_GOLD, GOLD_CACHE)
    cen, packed, shape = hit
    gold = np.unpackbits(packed, count=shape[0] * shape[1]).reshape(shape) * np.uint8(255)
    dist = cv2.distanceTransform(255 - gold, cv2.DIST_L2, 3)
    return cen, np.minimum(dist, 255).astype(np.float16)  # fractions matter (3.5 px)


def _maps(atlas):
    """Return every screenshot with its atlas-to-screen homography.

    Args:
        atlas: the core.Atlas with placed screenshots.

    Returns:
        A list of (frame dict, 3x3 homography from atlas units to that screenshot's px).
    """
    out = []
    for f in atlas.frames:
        H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        out.append((f, np.linalg.inv(H)))
    return out


def _visible(f, Hi, pts, margin=FRAME_MARGIN):
    """Project atlas points into a screenshot and tell which of them it shows.

    Args:
        f: the screenshot (frame) dict (needs "w", "h").
        Hi: the 3x3 homography from atlas units to that screenshot's px.
        pts: sequence of (x, y) points in atlas units.
        margin: how far inside the screenshot's edges a point must be (screen px).

    Returns:
        (points in screen px as (N, 2), bool array (N,): inside the margin and not on the HUD).
    """
    pts = np.asarray(pts, float).reshape(-1, 2)
    sp = core.persp(Hi, pts)
    if not len(sp):
        return sp, np.zeros(0, bool)
    ok = (sp[:, 0] > margin) & (sp[:, 0] < f["w"] - margin) & (sp[:, 1] > margin) & (sp[:, 1] < f["h"] - margin)
    ok &= ~core.on_hud_mask(sp, f["w"], f["h"])
    return sp, ok


def _seg_dist(p, a, b):
    """Distance from a point to a line segment.

    Args:
        p: the point, a length-2 array.
        a: the segment's start, a length-2 array.
        b: the segment's end, a length-2 array.

    Returns:
        (distance to the nearest point of the segment, its position t along a -> b from 0 to 1).
    """
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / max(1e-9, np.dot(ab, ab)), 0, 1))
    return float(np.linalg.norm(p - (a + t * ab))), t


def _mst(pts):
    """Build a minimum spanning tree over points (Prim's algorithm; used to chain Abyss map nodes).

    Args:
        pts: (N, 2) array of points (atlas units), N >= 1.

    Returns:
        A list of N - 1 (i, j) index pairs, the tree's edges.
    """
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


def _diamond_shortcut(points, grid, i, j, supported) -> bool:
    """Tell whether a link is a diamond diagonal: atlas_paths._is_diamond_shortcut, looking only at maps near it.

    The original walks every map in the atlas per link: 85% of a 22-minute check on a 8k-map atlas. A link of
    48+ is a shortcut when supported links (>= 0.60) go round it through a third map on BOTH sides.

    Args:
        points: (N, 2) array of map node positions (atlas units).
        grid: a _Grid over points.
        i: index of one end.
        j: index of the other end.
        supported: (lower index, higher index) -> straight score of the proposed links.

    Returns:
        True when the link is a diamond diagonal.
    """
    a, b = points[[i, j]]
    axis = b - a
    length = float(np.linalg.norm(axis))
    if length < 48:
        return False

    def evidence(x, y):
        """Return the straight score of the link between map nodes x and y (0.0 when not proposed).

        Args:
            x: index of one map node.
            y: index of the other map node.

        Returns:
            The score as a float.
        """
        return supported.get(tuple(sorted((x, y))), 0.0)

    side_a, side_b = [], []
    for k in grid.near(a, length):
        if k in (i, j):
            continue
        p = points[k]
        da, db = float(np.linalg.norm(p - a)), float(np.linalg.norm(p - b))
        if max(da, db) > length * 0.96 or min(da, db) < 25:
            continue
        if min(evidence(i, k), evidence(k, j)) < 0.60:
            continue
        cross = float(axis[0] * (p[1] - a[1]) - axis[1] * (p[0] - a[0]))
        if abs(cross) < length * 16:
            continue
        (side_a if cross > 0 else side_b).append(k)
    return bool(side_a and side_b)


def _bypasses_two(points, grid, i, j, supported) -> bool:
    """Tell whether a link bypasses two shorter paths: atlas_paths._bypasses_two_shorter_paths, near maps only.

    A link of 76+ is refused when a third map between its ends (each part 30 to 0.85 of its length) has
    supported links (>= 0.64) to both ends.

    Args:
        points: (N, 2) array of map node positions (atlas units).
        grid: a _Grid over points.
        i: index of one end.
        j: index of the other end.
        supported: (lower index, higher index) -> straight score of the proposed links.

    Returns:
        True when the link runs past such a map.
    """
    a, b = points[[i, j]]
    length = float(np.linalg.norm(a - b))
    if length < 76:
        return False
    for k in grid.near(a, length):
        if k in (i, j):
            continue
        mid = points[k]
        da = float(np.linalg.norm(a - mid))
        db = float(np.linalg.norm(mid - b))
        if not (30 < da < length * 0.85 and 30 < db < length * 0.85):
            continue
        left = supported.get(tuple(sorted((i, k))), 0.0)
        right = supported.get(tuple(sorted((j, k))), 0.0)
        if min(left, right) >= 0.64:
            return True
    return False
