"""Gold path dashes of a screenshot and how well a straight / gently bowed line between two maps is covered
by them (used by the atlas-wide path check in atlas_finalize)."""
from __future__ import annotations

import cv2
import numpy as np


MAX_EXITS = 5


def gold_stroke_mask(image: np.ndarray) -> np.ndarray:
    """Find short golden dashes, filtering large gold scenery and icon art."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colors = cv2.inRange(hsv, np.array([7, 78, 83]), np.array([31, 255, 255]))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(colors, 8)
    keep = np.zeros(count, dtype=np.uint8)
    for k in range(1, count):
        _, _, w, h, area = stats[k]
        if 2 <= area <= 47 and w <= 26 and h <= 26 and max(w, h) >= 3:
            keep[k] = 255
    return keep[labels]


_T = np.linspace(.09, .91, 39)
_BOWS = np.array([-.13, 0., .13])
_GROUPS = np.array([0, 5, 10, 15, 20, 25, 30, 35])      # = np.array_split(39 samples, 8)


def route_score(field: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    """Evidence must be distributed across the *whole* segment, not one tree.
    (all three bows at once; same result as the per-bow loop it replaced in v1.01, ~5x faster)"""
    delta = end - start
    length = float(np.linalg.norm(delta))
    if not 34 <= length <= 285:
        return 0.
    tangent = delta / length
    perpendicular = np.array([-tangent[1], tangent[0]])
    h, w = field.shape
    # Some actual PoE lines are gently bowed rather than mathematically straight.
    loc = start + _T[:, None] * delta                                     # (39, 2)
    off = (4 * _T * (1 - _T) * length)[None, :, None] * _BOWS[:, None, None] * perpendicular   # (3, 39, 2)
    loc = loc[None] + off
    x = np.clip(np.rint(loc[..., 0]).astype(int), 0, w - 1)
    y = np.clip(np.rint(loc[..., 1]).astype(int), 0, h - 1)
    distance = field[y, x]                                                # (3, 39)
    support = np.clip((10 - distance) / 10, 0, 1)
    coverage = (np.maximum.reduceat(support, _GROUPS, axis=1) >= .22).mean(axis=1)
    consistency = (support >= .17).mean(axis=1)
    score = .46 * coverage + .36 * consistency + .18 * support.mean(axis=1)
    # The atlas uses repeated short, *separate* gold strokes, not a
    # continuous highlight or merely nearby gold scenery. Confirm several
    # actual pixel-level contacts, with gaps between them. Broad distance
    # transform proximity alone produced spurious links in Breach terrain.
    near = distance <= 3.5
    runs = near[:, 0].astype(int) + np.count_nonzero(near[:, 1:] & ~near[:, :-1], axis=1)
    contacts = np.logical_or.reduceat(near, _GROUPS, axis=1).sum(axis=1)
    weak = (runs < (3 if length >= 95 else 2)) | (contacts < (3 if length < 95 else 4))
    score = np.where(weak, score * .82, score)
    return float(max(0., score.max()))


def _crosses(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> bool:
    """True interior segment intersection (sharing a node is allowed)."""
    def orient(p, q, r):
        v = q-p; u = r-p
        return float(v[0]*u[1]-v[1]*u[0])
    return (orient(a,b,c)*orient(a,b,d) < -1e-4 and
            orient(c,d,a)*orient(c,d,b) < -1e-4)


