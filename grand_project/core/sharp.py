"""core.sharp: sharp ground, built from the screenshots at native resolution (the app's zoomed-in tiles and the
web map's deepest levels).

The stitched map image is scaled down to fit TERRAIN_PIXELS; zoomed in, the ground is rebuilt square by square from
the screenshots themselves. Each pixel comes from the screenshot that owns it in the clean map (Fix seams), else
from the one that shows it nearest its own middle.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import cv2
import numpy as np

from .geometry import persp, screen_to_atlas
from .terrain import _valid_mask


def footprint(atlas, f: dict) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Return where a placed screenshot lies on the atlas.

    Args:
        atlas: The atlas (gives the screenshot's rectifier).
        f: The screenshot's entry from atlas.frames.

    Returns:
        (corners, bbox): the screenshot's 4 corners in atlas units, and (x0, y0, x1, y1) around them.
    """
    H = screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
    poly = persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
    return poly, (*poly.min(axis=0), *poly.max(axis=0))


def ground_weight(img: np.ndarray) -> np.ndarray:
    """Return how central each spot of a screenshot is (quarter resolution): its distance to the nearest interface
    or fog pixel. Each spot of the sharp ground comes from the screenshot where this is largest.

    Args:
        img: BGR screenshot.

    Returns:
        float32 array (h / 4, w / 4): distance in quarter px to the nearest invalid pixel.
    """
    v = _valid_mask(img)
    small = cv2.resize(v, (v.shape[1] // 4, v.shape[0] // 4), interpolation=cv2.INTER_NEAREST)
    small[small > 0] = 255
    return cv2.distanceTransform(small, cv2.DIST_L2, 3).astype(np.float32)


def build_sharp_tile(
    atlas,
    footprints: list,
    s: float,
    ax0: float,
    ay0: float,
    size: int,
    weight_of: Callable[[dict], np.ndarray],
    max_frames: int,
    labels: tuple | None = None,
    origin: tuple[float, float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build one square of sharp ground from the screenshots.

    The square covers atlas units [ax0, ax0 + size / s) by [ay0, ay0 + size / s) at s px per atlas unit. Without a
    clean map, at most max_frames screenshots are used, nearest the square's middle first.

    Args:
        atlas: The atlas (screenshots, read through atlas.image).
        footprints: footprint() of every screenshot, in atlas.frames order.
        s: Px per atlas unit.
        ax0: Atlas x of the square's left edge.
        ay0: Atlas y of the square's top edge.
        size: Square side in px.
        weight_of: ground_weight of a screenshot (the caller caches them).
        max_frames: Most screenshots warped when there is no clean map.
        labels: (ownership map, screenshot names) of the clean map (Fix seams), or None.
        origin: (x0, y0, scale) of the map image the ownership map belongs to (needed with labels).

    Returns:
        (pixels, best): BGR uint8 (size, size, 3), and float32 (size, size) weight of the screenshot each pixel came
        from (0 = no screenshot shows it).
    """
    T = size
    unit = T / s
    V = np.array([[s, 0, -ax0 * s], [0, s, -ay0 * s], [0, 0, 1]])
    out = np.zeros((T, T, 3), np.uint8)
    best = np.zeros((T, T), np.float32)
    frames = []
    for f, (poly, bb) in zip(list(atlas.frames), list(footprints), strict=False):
        if bb[2] < ax0 or bb[0] > ax0 + unit or bb[3] < ay0 or bb[1] > ay0 + unit:
            continue
        if not atlas.has_picture(f["path"]):  # (the screenshot, else its copy)
            continue
        sp = (np.asarray(poly, float) - [ax0, ay0]) * s
        x0, y0 = np.floor(sp.min(axis=0)).astype(int)
        x1, y1 = np.ceil(sp.max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(T, x1), min(T, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        ctr = sp.mean(axis=0)
        frames.append((math.hypot(ctr[0] - T / 2, ctr[1] - T / 2), f, (x0, y0, x1, y1)))
    frames.sort(key=lambda t: t[0])
    owner, idx_of, limit = None, {}, max_frames
    if labels is not None and origin is not None:
        # which screenshot owns each tile pixel: the clean map's ownership map, warped into the tile
        ox, oy, sc = origin
        C2T = V @ np.array([[1 / sc, 0, ox], [0, 1 / sc, oy], [0, 0, 1]])
        owner = cv2.warpPerspective(
            labels[0], C2T, (T, T), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=-1
        )
        idx_of = {n: k for k, n in enumerate(labels[1])}
        present = set(np.unique(owner).tolist())
        frames = [t for t in frames if idx_of.get(t[1]["name"], -2) in present]
        limit = len(frames)
    S4 = np.diag([4.0, 4.0, 1.0])
    for _, f, (x0, y0, x1, y1) in frames[:limit]:
        Hf = screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        M = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]]) @ V @ Hf
        sz = (x1 - x0, y1 - y0)
        pix = cv2.warpPerspective(atlas.image(f["path"]), M, sz, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        wt = cv2.warpPerspective(weight_of(f), M @ S4, sz, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        sub_b = best[y0:y1, x0:x1]
        take = wt > sub_b
        if owner is not None:  # the clean map's owner, wherever this screenshot shows it
            take = (owner[y0:y1, x0:x1] == idx_of[f["name"]]) & (wt > 0)
        out[y0:y1, x0:x1][take] = pix[take]
        sub_b[take] = wt[take]
    return out, best
