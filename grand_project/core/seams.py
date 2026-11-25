"""Clean terrain ("Fix seams"): the stitched map built with care instead of fast.

The quick map (Atlas.composite / paste_into) takes every spot from the screenshot that shows it most centrally.
That cuts map nodes and their icons in half where two screenshots meet, lets a screenshot taken in fog paint
dark blocks over lit ground, and puts seams across paths and tall terrain. Here an ownership map ("labels":
which screenshot each spot comes from) is worked out first, on a grid of SEAM_GRID atlas units, by trading off:

- each spot wants a screenshot that shows it centrally and lit (fogged ground scores low, so a lit copy wins)
- each seam costs, per cell of its length, more
  * the farther the spot is from the middle of the two screenshots that meet there: the game's view leans
    tall things (mountains, towers) outwards from the middle of the screen, so two views of a spot far from
    their middles don't line up, worst when they come from opposing edges
  * the farther apart the two screenshots were taken (the same thing, from the views' side)
  * through busy ground (mountains, trees, buildings: where the lean shows), much more through paths and
    most through map nodes and their icons (so those come whole from one screenshot)

The cheapest ownership map overall is found with graph cuts (alpha expansion: for each screenshot in turn,
the best set of spots to hand over to it), then the map is drawn from it. The labels are kept with the map
(same grid as the map), so screenshots added quickly afterwards only take over where they are more central
than what is there (paste_into), and the zoomed-in view follows the same ownership.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, maximum_flow

from .constants import (
    SEAM_CYCLES,
    SEAM_DARK,
    SEAM_DARK_FLOOR,
    SEAM_DATA_W,
    SEAM_EDGE_W,
    SEAM_FLOW_SCALE,
    SEAM_GRID,
    SEAM_ICON_R,
    SEAM_LIT,
    SEAM_LIT_BLUR,
    SEAM_MIDDLE_BOTTOM,
    SEAM_MIDDLE_TOP,
    SEAM_NEAR_FALL,
    SEAM_NEAR_SHARE,
    SEAM_NODE_R,
    SEAM_NODE_W,
    SEAM_OFF_W,
    SEAM_PATH_HALF,
    SEAM_PATH_W,
    SEAM_S_FULL,
    SEAM_SCORE_SCALE,
    SEAM_SHIFT_W,
    SEAM_TEX_W,
)
from .geometry import persp, screen_to_atlas
from .terrain import _valid_mask_calc


def _score(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Score a screenshot for the clean map, at 1/SEAM_SCORE_SCALE size.

    Args:
        img: BGR screenshot.

    Returns:
        (score, busyness): float32 arrays at 1/SEAM_SCORE_SCALE size. score = centrality (distance from the
        interface / screenshot edge, in full-size px) x how lit (SEAM_DARK..SEAM_LIT, floor SEAM_DARK_FLOOR);
        busyness = 0..1 edge density.
    """
    small = cv2.resize(
        img, (img.shape[1] // SEAM_SCORE_SCALE, img.shape[0] // SEAM_SCORE_SCALE), interpolation=cv2.INTER_AREA
    )
    v = cv2.resize(_valid_mask_calc(img, dark=False), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    centr = cv2.distanceTransform((v > 0).astype(np.uint8), cv2.DIST_L2, 3) * SEAM_SCORE_SCALE
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lit = np.clip(
        (cv2.blur(grey, (SEAM_LIT_BLUR, SEAM_LIT_BLUR)) - SEAM_DARK) / (SEAM_LIT - SEAM_DARK), SEAM_DARK_FLOOR, 1.0
    )
    gx, gy = cv2.Sobel(grey, cv2.CV_32F, 1, 0), cv2.Sobel(grey, cv2.CV_32F, 0, 1)
    busy = np.clip(cv2.blur(cv2.magnitude(gx, gy), (5, 5)) / 120.0, 0, 1)
    return (centr * lit).astype(np.float32), busy.astype(np.float32)


def _H(atlas, f) -> np.ndarray:
    """Return a placed screenshot's screen-to-atlas homography.

    Args:
        atlas: The Atlas.
        f: A placed screenshot's record from atlas.frames.

    Returns:
        3x3 homography: screen px -> atlas units.
    """
    return screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))


class _Grid:
    """The ownership grid over the atlas (or a region of it) and each screenshot's data on it.

    Cells are SEAM_GRID atlas units wide.

    Attributes:
        atlas: The Atlas.
        frames: The placed screenshot records on the grid (labels are indices into this list).
        x0: Atlas x of the grid's left edge.
        y0: Atlas y of the grid's top edge.
        GW: Grid width in cells.
        GH: Grid height in cells.
        Tg: 3x3 map atlas units -> grid cells.
        shot: Screenshot index -> (gx0, gy0, score, busy) on the grid (float16), or None when off the grid;
            filled by load.
        centre: (n, 2) atlas position of each screenshot's centre.
    """

    def __init__(self, atlas, frames, x0, y0, GW, GH):
        """Set up an empty grid.

        Args:
            atlas: The Atlas.
            frames: Placed screenshot records to use.
            x0: Atlas x of the grid's left edge.
            y0: Atlas y of the grid's top edge.
            GW: Grid width in cells.
            GH: Grid height in cells.
        """
        self.atlas, self.frames = atlas, frames
        self.x0, self.y0, self.GW, self.GH = x0, y0, GW, GH
        self.Tg = np.array([[1 / SEAM_GRID, 0, -x0 / SEAM_GRID], [0, 1 / SEAM_GRID, -y0 / SEAM_GRID], [0, 0, 1]], float)
        self.shot: dict[int, tuple] = {}  # i -> (gx0, gy0, score, busy) on the grid (float16)
        self.centre = np.array([persp(_H(atlas, f), [[f["w"] / 2, f["h"] / 2]])[0] for f in frames], float).reshape(
            -1, 2
        )

    def window(self, i):
        """Return the grid cells screenshot i covers.

        Args:
            i: Screenshot index into frames.

        Returns:
            (gx0, gy0, w, h, Hg): the window's corner and size in cells and the 3x3 map screen px -> grid cells,
            or None when the screenshot lies off the grid.
        """
        f = self.frames[i]
        Hg = self.Tg @ _H(self.atlas, f)
        c = persp(Hg, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
        gx0, gy0 = np.maximum(np.floor(c.min(axis=0)).astype(int) - 1, 0)
        gx1, gy1 = np.minimum(np.ceil(c.max(axis=0)).astype(int) + 2, [self.GW, self.GH])
        if gx1 <= gx0 or gy1 <= gy0:
            return None
        return int(gx0), int(gy0), int(gx1 - gx0), int(gy1 - gy0), Hg

    def load(self, i):
        """Read screenshot i and keep its score / busyness on the grid.

        The score is a distance, so it is sampled (no averaging); the busyness is averaged over the cell.

        Args:
            i: Screenshot index into frames.

        Returns:
            (gx0, gy0, score, busy) as stored in shot[i], or None when the screenshot lies off the grid.
        """
        win = self.window(i)
        if win is None:
            self.shot[i] = None
            return None
        gx0, gy0, w, h, Hg = win
        sc, busy = _score(self.atlas.image(self.frames[i]["path"]))
        S = np.diag([float(SEAM_SCORE_SCALE), float(SEAM_SCORE_SCALE), 1.0])
        Hroi = np.array([[1, 0, -gx0], [0, 1, -gy0], [0, 0, 1]], float) @ Hg @ S
        # the score is a distance: sample it (no averaging), the busyness averaged over the cell
        s = cv2.warpPerspective(sc, Hroi, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
        b = cv2.warpPerspective(busy, Hroi, (w, h), flags=cv2.INTER_AREA, borderValue=0)
        self.shot[i] = (gx0, gy0, s.astype(np.float16), b.astype(np.float16))
        return self.shot[i]

    def off_middle(self, i, gx0, gy0, w, h):
        """Return 0 (screen middle) .. 1 (corner) for each cell of screenshot i's window.

        See _off_middle; positions are converted to a 1920x1080 screen.

        Args:
            i: Screenshot index into frames.
            gx0: Window's left cell.
            gy0: Window's top cell.
            w: Window width in cells.
            h: Window height in cells.

        Returns:
            (h, w) float32 array.
        """
        f = self.frames[i]
        Hs = np.linalg.inv(self.Tg @ _H(self.atlas, f))
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float64) + gx0 + 0.5, np.arange(h, dtype=np.float64) + gy0 + 0.5)
        X = Hs[0, 0] * gx + Hs[0, 1] * gy + Hs[0, 2]
        Y = Hs[1, 0] * gx + Hs[1, 1] * gy + Hs[1, 2]
        Z = Hs[2, 0] * gx + Hs[2, 1] * gy + Hs[2, 2]
        return _off_middle(X / Z * (1920 / f["w"]), Y / Z * (1080 / f["h"]))


def _off_middle(x, y):
    """Measure how far a screen spot is from the screenshot's well-seen middle.

    0 at its middle, 1 on the edge of MIDDLE (a trapezoid, SEAM_MIDDLE_TOP / SEAM_MIDDLE_BOTTOM: the tilted
    camera sees the ground near the screen's bottom steeper), more outside it.

    Args:
        x: Screen x on a 1920x1080 screen (px), array.
        y: Screen y on a 1920x1080 screen (px), same shape.

    Returns:
        float32 array of the same shape.
    """
    (ty, thw), (by, bhw) = SEAM_MIDDLE_TOP, SEAM_MIDDLE_BOTTOM
    hw = np.maximum(thw + (bhw - thw) * (y - ty) / (by - ty), 150.0)
    my, hh = (ty + by) / 2, (by - ty) / 2
    return np.maximum(np.abs(x - 960.0) / hw, np.abs(y - my) / hh).astype(np.float32)


def _data(s, e):
    """Cost of taking each spot from a screenshot: off its middle (e), near its edge / HUD or in fog (s).

    Args:
        s: Score of the screenshot on the grid (see _score).
        e: Off-middle measure on the grid (see _off_middle), same shape.

    Returns:
        (cost, feasible): float32 cost per cell, and a bool array of the cells the screenshot can give
        (score > 0.5).
    """
    s = s.astype(np.float32)
    return SEAM_DATA_W * np.minimum(e, 1.6) ** 2 + SEAM_EDGE_W * (1.0 - np.minimum(1.0, s / SEAM_S_FULL)), s > 0.5


def _protect(atlas, grid) -> np.ndarray:
    """Extra seam weight per cell: map nodes and icons (whole from one screenshot), paths.

    Cores are each map node with its icon row (the hull of the icons and their map node: one piece), plus icons
    whose map node wasn't found (the icons still mark a map node under them). Seams must not cut a core; near
    one they cost more, falling off with distance, so where they have to pass between crowded map nodes they
    keep to the middle of the gap. Uses the atlas-wide result (atlas.final); nothing is protected without it.

    Args:
        atlas: The Atlas.
        grid: The _Grid.

    Returns:
        (GH, GW) float32 extra weight.
    """
    fin = atlas.final or {}
    out = np.zeros((grid.GH, grid.GW), np.float32)
    g = lambda x, y: (int(round((x - grid.x0) / SEAM_GRID)), int(round((y - grid.y0) / SEAM_GRID)))  # noqa: E731
    by_id = {n["id"]: n for n in fin.get("nodes", [])}
    paths = np.zeros_like(out, np.uint8)
    for p in fin.get("paths", []):
        a, b = by_id.get(p["a"]), by_id.get(p["b"])
        if a is not None and b is not None:
            cv2.line(paths, g(a["x"], a["y"]), g(b["x"], b["y"]), 1, max(1, round(2 * SEAM_PATH_HALF / SEAM_GRID)))
    # cores: each map node with its icon row (the hull of the icons and their map node: one piece), plus
    # icons whose map node wasn't found (the icons still mark a map node under them)
    core = np.zeros_like(out, np.uint8)
    for n in fin.get("nodes", []):
        if n["status"] != "removed":
            cv2.circle(core, g(n["x"], n["y"]), round(SEAM_NODE_R / SEAM_GRID), 1, -1)
    rows: dict[tuple, list] = {}
    for ic in fin.get("icons", []):
        bx, by = ic.get("bx", ic["x"]), ic.get("by", ic["y"])
        rows.setdefault((round(bx / 20), round(by / 20)), []).append((ic["x"], ic["y"], bx, by))
    for row in rows.values():
        pts = []
        for x, y, bx, by in row:
            r = SEAM_ICON_R
            pts += [(x - r, y - r), (x + r, y - r), (x - r, y + r), (x + r, y + r), (bx - r, by + r), (bx + r, by + r)]
        hull = cv2.convexHull(np.array([g(x, y) for x, y in pts], np.int32))
        cv2.fillConvexPoly(core, hull, 1)
    # seams must not cut a core; near one they cost more, falling off with distance, so where they have to
    # pass between crowded map nodes they keep to the middle of the gap
    d = cv2.distanceTransform((core == 0).astype(np.uint8), cv2.DIST_L2, 3) * SEAM_GRID
    near = SEAM_NODE_W * SEAM_NEAR_SHARE * np.clip(1.0 - d / SEAM_NEAR_FALL, 0, 1)
    out += SEAM_PATH_W * paths + np.where(core > 0, SEAM_NODE_W, near)
    return out


def _pq(a, axis):
    """Return both sides (p, q) of every neighbour pair along an axis, flattened.

    Args:
        a: 2-D array.
        axis: 0 for vertical neighbours, 1 for horizontal neighbours.

    Returns:
        (p, q) 1-D arrays.
    """
    if axis == 1:
        return a[:, :-1].ravel(), a[:, 1:].ravel()
    return a[:-1, :].ravel(), a[1:, :].ravel()


def _seam(la, ea, cxa, cya, lb, eb, cxb, cyb, w):
    """Seam cost between neighbouring cells owned by la / lb (0 where the same, or one side is empty).

    The cost grows with how far off the middle both sides are and how far apart the two screenshots' centres are.

    Args:
        la: Owner (screenshot index, -1 = none) of the first cells.
        ea: Off-middle measure of the first cells in their owner.
        cxa: Atlas x of the first owner's centre.
        cya: Atlas y of the first owner's centre.
        lb: Owner of the second cells.
        eb: Off-middle measure of the second cells in their owner.
        cxb: Atlas x of the second owner's centre.
        cyb: Atlas y of the second owner's centre.
        w: Seam weight of the pair (see _protect and busyness).

    Returns:
        Array of seam costs, one per pair.
    """
    d = np.hypot(cxa - cxb, cya - cyb) / 1000.0
    c = w * (1.0 + SEAM_OFF_W * (ea + eb) + SEAM_SHIFT_W * d)
    return np.where((la != lb) & (la >= 0) & (lb >= 0), c, 0.0)


def _expand(grid, i, L, U, E, Wt):
    """One alpha expansion: hand screenshot i every cell where that lowers the total cost.

    Solved as a minimum cut over the cells screenshot i could take. L, U and E are updated in place.

    Args:
        grid: The _Grid (screenshot i must be loaded).
        i: Screenshot index.
        L: (GH, GW) int32 owner of each cell (-1 = none).
        U: (GH, GW) float32 data cost of each cell in its owner.
        E: (GH, GW) float32 off-middle measure of each cell in its owner.
        Wt: (GH, GW) float32 seam weight per cell.

    Returns:
        Number of cells moved to screenshot i.
    """
    sh = grid.shot.get(i)
    if sh is None:
        return 0
    gx0, gy0, s, _b = sh
    h, w = s.shape
    win = (slice(gy0, gy0 + h), slice(gx0, gx0 + w))
    Ea = grid.off_middle(i, gx0, gy0, w, h)
    Ua, feas = _data(s, Ea)
    Lw, Uw, Ew = L[win], U[win], E[win]
    var = feas & (Lw != i)
    n = int(var.sum())
    if n == 0:
        return 0
    cen = grid.centre
    Cx, Cy = cen[np.maximum(Lw, 0), 0], cen[np.maximum(Lw, 0), 1]
    idx = np.full(Lw.shape, -1, np.int64)
    idx[var] = np.arange(n)
    delta = np.zeros(n)  # cost(switch) - cost(keep) per variable
    delta += (Ua - Uw)[var]
    rows, cols, caps = [], [], []
    ax, ay = cen[i]
    for axis in (0, 1):
        (lp, lq), (ep, eq), (cxp, cxq), (cyp, cyq) = (_pq(a, axis) for a in (Lw, Ew, Cx, Cy))
        (eap, eaq), (vp, vq) = _pq(Ea, axis), _pq(idx, axis)
        wt = np.maximum(*_pq(Wt[win], axis))
        A = _seam(lp, ep, cxp, cyp, lq, eq, cxq, cyq, wt)  # both keep
        B = _seam(lp, ep, cxp, cyp, np.full_like(lq, i), eaq, ax, ay, wt)  # q switches
        C = _seam(np.full_like(lp, i), eap, ax, ay, lq, eq, cxq, cyq, wt)  # p switches
        both, onlyp, onlyq = (vp >= 0) & (vq >= 0), (vp >= 0) & (vq < 0), (vp < 0) & (vq >= 0)
        np.add.at(delta, vp[both], (C - A)[both])
        np.add.at(delta, vq[both], -C[both])
        lam = np.maximum(B + C - A, 0)[both]
        rows.append(vp[both])
        cols.append(vq[both])
        caps.append(lam)
        np.add.at(delta, vp[onlyp], (C - A)[onlyp])
        np.add.at(delta, vq[onlyq], (B - A)[onlyq])
    src, snk = n, n + 1
    v = np.arange(n)
    pos = delta > 0
    rows += [np.full(int(pos.sum()), src), v[~pos]]
    cols += [v[pos], np.full(int((~pos).sum()), snk)]
    caps += [delta[pos], -delta[~pos]]
    r, c = np.concatenate(rows), np.concatenate(cols)
    k = np.round(np.concatenate(caps) * SEAM_FLOW_SCALE).astype(np.int64)
    keep = k > 0
    r, c, k = r[keep], c[keep], np.minimum(k[keep], 2**30).astype(np.int32)
    G = csr_matrix((k, (r, c)), shape=(n + 2, n + 2))
    flow = maximum_flow(G, src, snk).flow
    R = (G - flow).tocsr()
    R.data[R.data < 0] = 0
    R.eliminate_zeros()
    reach = breadth_first_order(R, src, directed=True, return_predecessors=False)
    stay = np.zeros(n + 2, bool)
    stay[reach] = True
    move = ~stay[:n]
    if not move.any():
        return 0
    yy, xx = np.nonzero(var)
    yy, xx = yy[move], xx[move]
    Lw[yy, xx] = i
    Uw[yy, xx] = Ua[yy, xx]
    Ew[yy, xx] = Ea[yy, xx]
    return int(move.sum())


def clean_composite(atlas, max_pixels: int = 36_000_000, region=None, log=None):
    """Build the stitched map with clean seams.

    1. every screenshot on the grid, starting from the cheapest one per cell (no seams counted yet); 2. graph
    cuts: each screenshot in turn takes over the cells where that makes the whole map cheaper (up to
    SEAM_CYCLES rounds); 3. the ownership grid onto the canvas, and the map drawn from it. The weight is each
    spot's score in the quick map's units, so later quick adds take over only where more central.

    Args:
        atlas: The Atlas.
        max_pixels: Largest canvas size in pixels; bigger maps are scaled down.
        region: (x0, y0, x1, y1) in atlas units builds only that part (tests, previews); None for everything.
        log: Optional function taking one progress line.

    Returns:
        (canvas, (x0, y0, scale), weight, labels, frame names): BGR canvas, its origin, (h, w) float32 weight,
        (h, w) int16 owner per canvas pixel (index into frame names, -1 = none), and the screenshot names.
    """
    frames = [f for f in atlas.frames if atlas.has_picture(f["path"])]  # (the screenshot, else its copy)
    if not frames:
        z = np.zeros((1, 1), np.float32)
        return np.zeros((1, 1, 3), np.uint8), (0, 0, 1.0), z, z.astype(np.int16) - 1, []
    polys = [persp(_H(atlas, f), [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]]) for f in frames]
    if region is not None:
        rx0, ry0, rx1, ry1 = region
        keep = [
            i
            for i, p in enumerate(polys)
            if p[:, 0].max() > rx0 and p[:, 0].min() < rx1 and p[:, 1].max() > ry0 and p[:, 1].min() < ry1
        ]
        frames, polys = [frames[i] for i in keep], [polys[i] for i in keep]
        x0, y0, x1, y1 = int(rx0), int(ry0), int(math.ceil(rx1)), int(math.ceil(ry1))
    else:
        allc = np.vstack(polys)
        x0, y0 = np.floor(allc.min(axis=0)).astype(int)
        x1, y1 = np.ceil(allc.max(axis=0)).astype(int)
    W, H = int(x1 - x0), int(y1 - y0)
    scale = min(1.0, math.sqrt(max_pixels / max(1, W * H)))
    CW, CH = max(1, int(W * scale)), max(1, int(H * scale))
    T = np.array([[scale, 0, -x0 * scale], [0, scale, -y0 * scale], [0, 0, 1]], float)

    # 1. every screenshot on the grid; start from the cheapest one per cell (no seams counted yet)
    GW, GH = math.ceil(W / SEAM_GRID), math.ceil(H / SEAM_GRID)
    grid = _Grid(atlas, frames, x0, y0, GW, GH)
    L = np.full((GH, GW), -1, np.int32)
    U = np.full((GH, GW), np.inf, np.float32)
    E = np.zeros((GH, GW), np.float32)
    busy = np.zeros((GH, GW), np.float32)
    for i in range(len(frames)):
        sh = grid.load(i)
        if sh is not None:
            gx0, gy0, s, b = sh
            e = grid.off_middle(i, gx0, gy0, s.shape[1], s.shape[0])
            u, feas = _data(s, e)
            win = (slice(gy0, gy0 + s.shape[0]), slice(gx0, gx0 + s.shape[1]))
            take = feas & (u < U[win])
            L[win][take], U[win][take], E[win][take], busy[win][take] = i, u[take], e[take], b[take]
        if log and i % 100 == 99:
            log(f"clean map: read {i + 1} of {len(frames)} screenshots")
    U[L < 0] = 0
    Wt = 1.0 + SEAM_TEX_W * busy + _protect(atlas, grid)

    # 2. graph cuts: each screenshot in turn takes over the cells where that makes the whole map cheaper
    order = sorted(range(len(frames)), key=lambda i: -float(np.mean(grid.shot[i][2])) if grid.shot[i] else 0)
    for cycle in range(SEAM_CYCLES):
        moved = 0
        for k, i in enumerate(order):
            moved += _expand(grid, i, L, U, E, Wt)
            if log and k % 100 == 99:
                log(f"clean map: seams, round {cycle + 1} of {SEAM_CYCLES}: {k + 1} of {len(frames)} screenshots")
        if moved == 0:
            break

    # 3. the ownership grid onto the canvas, and the map drawn from it
    Mi = np.array([[1 / (scale * SEAM_GRID), 0, 0], [0, 1 / (scale * SEAM_GRID), 0]], np.float64)
    labels = cv2.warpAffine(
        L.astype(np.float32), Mi, (CW, CH), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=-1
    ).astype(np.int16)
    canvas = np.zeros((CH, CW, 3), np.uint8)
    best = np.zeros((CH, CW), np.float32)
    for i, f in enumerate(frames):
        roi = _roi(T @ _H(atlas, f), f, CW, CH)
        if roi is None:
            continue
        bx0, by0, size, Hroi = roi
        mine = labels[by0 : by0 + size[1], bx0 : bx0 + size[0]] == i
        if not mine.any():
            continue
        pix = cv2.warpPerspective(atlas.image(f["path"]), Hroi, size, flags=cv2.INTER_LINEAR, borderValue=0)
        canvas[by0 : by0 + size[1], bx0 : bx0 + size[0]][mine] = pix[mine]
        if log and i % 100 == 99:
            log(f"clean map: drawn {i + 1} of {len(frames)} screenshots")
    # each spot's score (the quick map's units: later quick adds take over only where more central)
    sgrid = np.zeros((GH, GW), np.float32)
    for i, sh in grid.shot.items():
        if sh is not None:
            gx0, gy0, s, _b = sh
            win = (slice(gy0, gy0 + s.shape[0]), slice(gx0, gx0 + s.shape[1]))
            mine = L[win] == i
            sgrid[win][mine] = s[mine]
    best = cv2.warpAffine(sgrid, Mi, (CW, CH), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=0)
    best[labels >= 0] = np.maximum(best[labels >= 0], 1.0)
    return canvas, (x0, y0, scale), best, labels, [f["name"] for f in frames]


def _roi(Hc, f, CW, CH):
    """Return the canvas box a screenshot lands in.

    Args:
        Hc: 3x3 map screen px -> canvas px.
        f: Placed screenshot record (w, h).
        CW: Canvas width in px.
        CH: Canvas height in px.

    Returns:
        (bx0, by0, (w, h), Hroi): box corner, box size and the 3x3 map screen px -> box px; None when the
        screenshot misses the canvas.
    """
    c = persp(Hc, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
    bx0, by0 = np.maximum(np.floor(c.min(axis=0)).astype(int), 0)
    bx1, by1 = np.minimum(np.ceil(c.max(axis=0)).astype(int), [CW, CH])
    if bx1 <= bx0 or by1 <= by0:
        return None
    Hroi = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]], float) @ Hc
    return int(bx0), int(by0), (int(bx1 - bx0), int(by1 - by0)), Hroi


def main(argv=None):
    """Build the clean map in a process of its own (the viewer stays responsive).

    Usage: python -m grand_project.core.seams ATLAS_PICKLE OUT_NPZ MAX_PIXELS. Progress lines on stdout; the
    result (canvas, origin, weight, labels, names) saved to OUT_NPZ. The pickle is written by this program's
    viewer a moment ago, in a private folder.

    Args:
        argv: [ATLAS_PICKLE, OUT_NPZ, MAX_PIXELS]; None reads sys.argv.
    """
    import pickle
    import sys

    args = sys.argv[1:] if argv is None else argv
    src, out, max_pixels = Path(args[0]), Path(args[1]), int(args[2])
    atlas = pickle.loads(src.read_bytes())  # written by this program's viewer a moment ago, in a private folder
    canvas, origin, weight, labels, names = clean_composite(
        atlas, max_pixels=max_pixels, log=lambda t: print(t, flush=True)
    )
    np.savez(out, canvas=canvas, origin=np.array(origin, float), weight=weight, labels=labels, names=np.array(names))
    print("done", flush=True)


if __name__ == "__main__":
    main()
