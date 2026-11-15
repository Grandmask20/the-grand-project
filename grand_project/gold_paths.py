"""Gold path dashes of a screenshot and how well a straight / gently bowed line between two maps is covered
by them (used by the atlas-wide path check in atlas_finalize)."""

from __future__ import annotations

import cv2
import numpy as np

MAX_EXITS = 5


def gold_stroke_mask(image: np.ndarray) -> np.ndarray:
    """Find short golden dashes, filtering large gold scenery and icon art.

    Keeps gold-coloured blobs (HSV 7..31 hue) of 2..47 px area that fit in 26 x 26 px and are at least 3 px long.

    Args:
        image: BGR screenshot.

    Returns:
        (h, w) uint8 mask, 255 = path dash pixel.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colors = cv2.inRange(hsv, np.array([7, 78, 83]), np.array([31, 255, 255]))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(colors, 8)
    keep = np.zeros(count, dtype=np.uint8)
    for k in range(1, count):
        _, _, w, h, area = stats[k]
        if 2 <= area <= 47 and w <= 26 and h <= 26 and max(w, h) >= 3:
            keep[k] = 255
    return keep[labels]


_T = np.linspace(0.09, 0.91, 39)
_BOWS = np.array([-0.13, 0.0, 0.13])
_GROUPS = np.array([0, 5, 10, 15, 20, 25, 30, 35])  # = np.array_split(39 samples, 8)


def route_score(field: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    """Score how well a straight / gently bowed line between two maps is covered by path dashes.

    Evidence must be distributed across the *whole* segment, not one tree.
    (all three bows at once; same result as the per-bow loop it replaced in v1.01, ~5x faster)

    Args:
        field: (h, w) distance in px from each pixel to the nearest dash (a distance transform of the
            gold_stroke_mask).
        start: (2,) one map node position, px.
        end: (2,) the other map node position, px.

    Returns:
        Score 0..1 of the best of the three bows; 0.0 for lines shorter than 34 px or longer than 285 px.
    """
    delta = end - start
    length = float(np.linalg.norm(delta))
    if not 34 <= length <= 285:
        return 0.0
    tangent = delta / length
    perpendicular = np.array([-tangent[1], tangent[0]])
    h, w = field.shape
    # Some actual PoE lines are gently bowed rather than mathematically straight.
    loc = start + _T[:, None] * delta  # (39, 2)
    off = (4 * _T * (1 - _T) * length)[None, :, None] * _BOWS[:, None, None] * perpendicular  # (3, 39, 2)
    loc = loc[None] + off
    x = np.clip(np.rint(loc[..., 0]).astype(int), 0, w - 1)
    y = np.clip(np.rint(loc[..., 1]).astype(int), 0, h - 1)
    distance = field[y, x]  # (3, 39)
    support = np.clip((10 - distance) / 10, 0, 1)
    coverage = (np.maximum.reduceat(support, _GROUPS, axis=1) >= 0.22).mean(axis=1)
    consistency = (support >= 0.17).mean(axis=1)
    score = 0.46 * coverage + 0.36 * consistency + 0.18 * support.mean(axis=1)
    # The atlas uses repeated short, *separate* gold strokes, not a
    # continuous highlight or merely nearby gold scenery. Confirm several
    # actual pixel-level contacts, with gaps between them. Broad distance
    # transform proximity alone produced spurious links in Breach terrain.
    near = distance <= 3.5
    runs = near[:, 0].astype(int) + np.count_nonzero(near[:, 1:] & ~near[:, :-1], axis=1)
    contacts = np.logical_or.reduceat(near, _GROUPS, axis=1).sum(axis=1)
    weak = (runs < (3 if length >= 95 else 2)) | (contacts < (3 if length < 95 else 4))
    score = np.where(weak, score * 0.82, score)
    return float(max(0.0, score.max()))


def _crosses(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> bool:
    """True interior segment intersection (sharing a node is allowed).

    Args:
        a: (2,) first segment start.
        b: (2,) first segment end.
        c: (2,) second segment start.
        d: (2,) second segment end.

    Returns:
        True when the segments a-b and c-d cross.
    """

    def orient(p, q, r):
        """Return the cross product (q - p) x (r - p): the side of p-q that r lies on.

        Args:
            p: (2,) point.
            q: (2,) point.
            r: (2,) point.

        Returns:
            Positive / negative for the two sides, 0 on the line.
        """
        v = q - p
        u = r - p
        return float(v[0] * u[1] - v[1] * u[0])

    return orient(a, b, c) * orient(a, b, d) < -1e-4 and orient(c, d, a) * orient(c, d, b) < -1e-4
