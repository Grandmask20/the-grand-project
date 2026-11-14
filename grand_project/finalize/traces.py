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
        cand = [
            i
            for gx in range(cx - k, cx + k + 1)
            for gy in range(cy - k, cy + k + 1)
            for i in self.cells.get((gx, gy), ())
        ]
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


_GOLD: dict = {}  # screenshot path -> (dash centres, distance-to-gold field, float16)


GOLD_CACHE = 160  # ~4 MB each; kept between checks so local updates re-use them (a local


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
            return [(f, sp, ok, r) for (f, sp, ok), r in zip(views, res, strict=False)]
        except Exception:
            if log:
                log("parallel path tracing failed, tracing one screenshot at a time")
    return [(f, sp, ok, atlas_detect.screen_paths(_dashes(atlas, f), sp, ok, tower)) for f, sp, ok in views]


_SAVED: dict = {}


SAVED_CACHE = 400


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
    if data is None:  # cut-off cache: treated as not cached
        return None
    if any(k not in data for k in ("dash_pts", "seen_grid", "wall_grid", "amber_pts")):
        img = atlas.image(f["path"]) if Path(f["path"]).exists() else None
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
    _GOLD[key] = (cen[1:].astype(float), np.minimum(dist, 255).astype(np.float16))  # fractions matter (3.5 px)
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


def _diamond_shortcut(points, grid, i, j, supported) -> bool:
    """atlas_paths._is_diamond_shortcut, looking only at maps near the link (the original
    walks every map in the atlas per link: 85% of a 22-minute check on a 8k-map atlas)."""
    a, b = points[[i, j]]
    axis = b - a
    length = float(np.linalg.norm(axis))
    if length < 48:
        return False

    def evidence(x, y):
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
    """atlas_paths._bypasses_two_shorter_paths, looking only at maps near the link."""
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
