"""core.register (from atlas_builder_core.py)"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import constants as K
from .constants import MIN_INLIERS, PLACEMENT, REFINE_TOLS, SCALE_RANGE, SIG_DIST1, SIG_DIST2, VOTE_BIN
from .frame import Frame
from .geometry import apply, invert, persp


# ------------------------------------------------------------------ geometry helpers
def neighbour_signature(pts: np.ndarray) -> np.ndarray:
    """Distances to the two nearest other map nodes: a cheap, zoom-stable local fingerprint.

    Args:
        pts: (n, 2) map node positions.

    Returns:
        (n, 2) array of the distances to the nearest and second-nearest other node (all 1e6 with fewer than
        3 points).
    """
    if len(pts) < 3:
        return np.full((len(pts), 2), 1e6)
    from scipy.spatial import cKDTree

    d, _ = cKDTree(pts).query(pts, k=3)  # itself + the two nearest (no N x N matrix)
    return d[:, 1:3]


def vote_translations(src: np.ndarray, dst: np.ndarray, top_k: int = 8):
    """Vote for the shifts that move a screenshot's map nodes onto the atlas's.

    Every pair (screenshot node, atlas node) votes for the shift between them in a 2-D histogram of VOTE_BIN
    bins; pairs whose neighbour signatures agree (SIG_DIST1 / SIG_DIST2) count 1, the others 0.15. The
    histogram is smoothed over 3x3 bins and its highest peaks are taken, each blanking its surroundings.

    Args:
        src: (n, 2) map nodes of the new screenshot (flat map coordinates).
        dst: (m, 2) map nodes of the atlas (atlas units).
        top_k: Most peaks to return.

    Returns:
        List of (votes, tx, ty) peaks, strongest first; only peaks with more than 2 votes.
    """
    s_sig, d_sig = neighbour_signature(src), neighbour_signature(dst)
    good = (np.abs(s_sig[:, None, 0] - d_sig[None, :, 0]) < SIG_DIST1) & (
        np.abs(s_sig[:, None, 1] - d_sig[None, :, 1]) < SIG_DIST2
    )
    weights = np.where(good, 1.0, 0.15).ravel()
    dx = (dst[None, :, 0] - src[:, None, 0]).ravel()
    dy = (dst[None, :, 1] - src[:, None, 1]).ravel()
    x0, x1, y0, y1 = dx.min(), dx.max(), dy.min(), dy.max()
    nx, ny = max(3, int((x1 - x0) / VOTE_BIN) + 1), max(3, int((y1 - y0) / VOTE_BIN) + 1)
    hist, xe, ye = np.histogram2d(dx, dy, bins=[nx, ny], range=[[x0, x1 + 1e-6], [y0, y1 + 1e-6]], weights=weights)
    smooth = cv2.boxFilter(hist.astype(np.float32), -1, (3, 3), normalize=False)
    peaks = []
    work = smooth.copy()
    for _ in range(top_k):
        i, j = np.unravel_index(int(np.argmax(work)), work.shape)
        if work[i, j] <= 2:
            break
        peaks.append((float(work[i, j]), float(xe[i] + VOTE_BIN / 2), float(ye[j] + VOTE_BIN / 2)))
        work[max(0, i - 3) : i + 4, max(0, j - 3) : j + 4] = 0
    return peaks


def fit_affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Least-squares placement; None when it would be an implausible camera change.

    With the camera tilt undone a pan is a pure shift, so by default only a shift is fitted
    (PLACEMENT = "shift").  A free affine fitted ~1% squash and ~0.2 deg turns to the overlap,
    and those compounded from screenshot to screenshot into 30-45 unit offsets far from it.

    Args:
        src: (n, 2) matched points of the screenshot (flat map coordinates).
        dst: (n, 2) the atlas points they match (atlas units).

    Returns:
        2x3 affine src -> dst, or None when a free affine's scale falls outside SCALE_RANGE.
    """
    if PLACEMENT == "shift" and K.HORIZON is not None:
        return np.hstack([np.eye(2), (dst - src).mean(axis=0)[:, None]])
    A = np.hstack([src, np.ones((len(src), 1))])
    sol, *_ = np.linalg.lstsq(A, dst, rcond=None)
    M = sol.T
    sv = np.linalg.svd(M[:, :2], compute_uv=False)
    if sv[1] < SCALE_RANGE[0] or sv[0] > SCALE_RANGE[1]:
        return None
    return M


def mutual_pairs(a: np.ndarray, b: np.ndarray, tol: float):
    """Pair points of two sets that are each other's nearest point.

    Args:
        a: (n, 2) points.
        b: (m, 2) points.
        tol: Largest distance of a pair (same units as the points).

    Returns:
        List of (i, j, dist): a[i] and b[j] are each other's nearest point, within tol.
    """
    if not len(a) or not len(b):
        return []
    from scipy.spatial import cKDTree

    da, ia = cKDTree(b).query(a)
    _db, ib = cKDTree(a).query(b)
    return [(i, int(ia[i]), float(da[i])) for i in range(len(a)) if ib[ia[i]] == i and da[i] <= tol]


def refine(src: np.ndarray, dst: np.ndarray, t0) -> tuple[np.ndarray, list, float]:
    """Refine a shift into a placement by matching map nodes with shrinking tolerances.

    Starting from the shift t0, each tolerance in REFINE_TOLS pairs the nodes (mutual_pairs) and refits: a
    fit_affine with 7+ pairs, otherwise the mean remaining shift. Stops early when fewer than 4 pairs remain.

    Args:
        src: (n, 2) map nodes of the screenshot (flat map coordinates).
        dst: (m, 2) map nodes of the atlas (atlas units).
        t0: Starting shift (tx, ty) in atlas units.

    Returns:
        (M, pairs, rmse): the 2x3 placement, the mutual pairs at the last tolerance as (i, j, dist), and their
        RMS distance in atlas units (99.0 when there are none).
    """
    M = np.array([[1, 0, t0[0]], [0, 1, t0[1]]], float)
    pairs: list = []
    for tol in REFINE_TOLS:
        pairs = mutual_pairs(apply(M, src), dst, tol)
        if len(pairs) < 4:
            break
        a = src[[p[0] for p in pairs]]
        b = dst[[p[1] for p in pairs]]
        fitted = fit_affine(a, b) if len(pairs) >= 7 else None
        if fitted is None:
            M = M.copy()
            M[:, 2] += (b - apply(M, a)).mean(axis=0)
        else:
            M = fitted
    pairs = mutual_pairs(apply(M, src), dst, REFINE_TOLS[-1])
    rmse = float(np.sqrt(np.mean([p[2] ** 2 for p in pairs]))) if pairs else 99.0
    return M, pairs, rmse


# ------------------------------------------------------------------ registration
@dataclass
class Registration:
    """The result of trying to place a screenshot in the atlas.

    Attributes:
        ok: True when the placement is accepted.
        reason: Why it was accepted or rejected (shown to the user).
        M: 2x3 affine: the screenshot's flat map coordinates -> atlas coords; None when nothing was found.
        inliers: Number of map nodes that agree (mutual pairs).
        rmse: RMS distance of those pairs, atlas units.
        overlap_src: Screenshot map nodes that land inside already placed screenshots.
        overlap_dst: Atlas map nodes that lie inside the new screenshot.
        ratio: inliers / the smaller overlap count.
        ncc: Best terrain correlation against an overlapping placed screenshot (see terrain_ncc).
        ncc_pixels: Number of pixels that correlation was measured on.
        ref_frame: Name of the screenshot the terrain was compared with.
        candidates: Up to 4 other tried placements as (inliers, rmse, ratio), for the log.
    """

    ok: bool
    reason: str
    M: np.ndarray | None = None
    inliers: int = 0
    rmse: float = 0.0
    overlap_src: int = 0
    overlap_dst: int = 0
    ratio: float = 0.0
    ncc: float = 0.0
    ncc_pixels: int = 0
    ref_frame: str = ""
    candidates: list = field(default_factory=list)


def _inside_rect(
    pts: np.ndarray, M: np.ndarray, w: int, h: int, R: np.ndarray | None = None, margin: float = 30
) -> np.ndarray:
    """Tell which atlas points lie inside a placed screenshot.

    Args:
        pts: (n, 2) atlas points.
        M: 2x3 placement of the screenshot (flat map coordinates -> atlas).
        w: Screenshot width in px.
        h: Screenshot height in px.
        R: The screenshot's 3x3 rectifier, or None when its coordinates are not flattened.
        margin: Points closer than this to the screenshot's edge (screen px) count as outside.

    Returns:
        (n,) bool array: atlas points that lie inside the screenshot (0..w, 0..h) placed by M (after rectifier R).
    """
    back = apply(invert(M), pts)
    if R is not None:
        back = persp(np.linalg.inv(R), back)
    return (back[:, 0] > margin) & (back[:, 0] < w - margin) & (back[:, 1] > margin) & (back[:, 1] < h - margin)


def register(
    frame: Frame, atlas_pts: np.ndarray, footprints: list[tuple[np.ndarray, int, int, np.ndarray]]
) -> tuple[Registration, list]:
    """Find M (frame px -> atlas coords) from map nodes only. Terrain check is done by the caller.

    Each shift peak from vote_translations is refined; the one with the most agreeing nodes (then the lowest
    RMSE) wins.

    Args:
        frame: The new screenshot.
        atlas_pts: (m, 2) map nodes of the atlas (atlas units).
        footprints: Placed screenshots as (M, w, h, R), used to count the overlap.

    Returns:
        (best, tried): the best Registration (ok is still False) and every tried one, best first
        (empty when there were too few nodes or no shift peak).
    """
    src = frame.pts[frame.usable]
    if len(src) < MIN_INLIERS or len(atlas_pts) < MIN_INLIERS:
        return Registration(False, "too few nodes to match"), []
    best, tried = None, []
    for _votes, tx, ty in vote_translations(src, atlas_pts):
        M, pairs, rmse = refine(src, atlas_pts, (tx, ty))
        inl = len(pairs)
        moved = apply(M, src)
        inside_src = np.zeros(len(src), bool)
        for FM, fw, fh, FR in footprints:
            inside_src |= _inside_rect(moved, FM, fw, fh, FR)
        inside_dst = _inside_rect(atlas_pts, M, frame.w, frame.h, frame.R)
        o_src, o_dst = int(inside_src.sum()), int(inside_dst.sum())
        ratio = inl / max(1, min(o_src, o_dst))
        cand = Registration(False, "", M, inl, rmse, o_src, o_dst, ratio)
        tried.append(cand)
        if best is None or (inl, -rmse) > (best.inliers, -best.rmse):
            best = cand
    if best is None:
        return Registration(False, "no translation peak"), []
    tried.sort(key=lambda r: (-r.inliers, r.rmse))
    return best, tried


def _horizon_of(frame: Frame) -> float | None:
    """Recover the horizon a frame was rectified with (None = flat).

    Args:
        frame: The screenshot.

    Returns:
        The horizon row as a fraction of the screenshot height, or None when R is the identity.
    """
    R = frame.R / frame.R[2, 1] if frame.R[2, 1] else frame.R
    if np.allclose(frame.R, np.eye(3)):
        return None
    return float(-R[2, 2] / frame.h)
