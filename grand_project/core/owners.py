"""core.owners: how much of the map picture each screenshot owns (shows best), for the dump folder.

The map image takes each spot from the screenshot that shows it furthest from its edges and interface ("most central
wins": core.Atlas.paste_into); Fix seams' clean map keeps which screenshot owns each pixel (its labels). A screenshot
owning (almost) nothing is dump: everything it shows is shown better elsewhere (the user's "worse placements of an
area"). Ownership is read from the clean map's labels when there is one; else worked out on a coarse grid from the
screenshots' placements only (no pictures read), with the same rule: cheap enough to run after every job, so a newer,
more central screenshot sends an old one to dump, and undoing it brings the old one back.
"""

from __future__ import annotations

import cv2
import numpy as np

from .constants import OWNER_GRID, OWNER_SCREEN_STEP
from .frame import hud_mask
from .geometry import screen_to_atlas
from .sharp import footprint

_TEMPLATES: dict[tuple[int, int], np.ndarray] = {}


def centrality(w: int, h: int) -> np.ndarray:
    """Return how central each spot of a screenshot is, on a coarse grid: its distance (in screen px) to the nearest
    interface pixel or edge (the map image's own rule, core.Atlas.paste_into, without per-screenshot fog).

    Args:
        w: Screenshot width in px.
        h: Screenshot height in px.

    Returns:
        float32 (ceil(h / OWNER_SCREEN_STEP), ceil(w / OWNER_SCREEN_STEP)); cached per size.
    """
    if (w, h) not in _TEMPLATES:
        tw, th = -(-w // OWNER_SCREEN_STEP), -(-h // OWNER_SCREEN_STEP)
        hud = cv2.resize(hud_mask(w, h), (tw, th), interpolation=cv2.INTER_AREA)
        valid = (hud < 128).astype(np.uint8) * 255
        valid[[0, -1], :] = 0  # (an edge counts as the end of the picture)
        valid[:, [0, -1]] = 0
        _TEMPLATES[(w, h)] = cv2.distanceTransform(valid, cv2.DIST_L2, 3).astype(np.float32) * OWNER_SCREEN_STEP
    return _TEMPLATES[(w, h)]


def owned_shares(atlas, frames: list[dict], labels=None) -> dict[str, float]:
    """Return the share of its own area each screenshot owns in the map picture.

    Args:
        atlas: The atlas (the screenshots' rectifiers).
        frames: Its frames (name, M, w, h).
        labels: (ownership map, names, origin) of a clean map (Fix seams), or None: worked out on a grid.

    Returns:
        name -> share (0..1; 0 for a screenshot that owns nothing).
    """
    if not frames:
        return {}
    if labels is not None:
        return _from_labels(atlas, frames, *labels)
    return _from_grid(atlas, frames)


def _from_labels(atlas, frames, owner_map: np.ndarray, names: list[str], origin) -> dict[str, float]:
    """owned_shares from a clean map's ownership map: its pixels per screenshot over its own area in map px."""
    scale = float(origin[2])
    counts = np.bincount(owner_map.ravel().astype(np.int64) + 1, minlength=len(names) + 1)[1:]
    owned = {n: int(counts[k]) for k, n in enumerate(names) if k < len(counts)}
    out = {}
    for f in frames:
        poly, _box = footprint(atlas, f)
        area = abs(cv2.contourArea(poly.astype(np.float32))) * scale * scale
        out[f["name"]] = owned.get(f["name"], 0) / area if area > 0 else 0.0
    return out


def _from_grid(atlas, frames) -> dict[str, float]:
    """owned_shares on a grid over the screenshots: each cell owned by the screenshot most central there."""
    polys = [footprint(atlas, f) for f in frames]
    x0 = min(b[0] for _p, b in polys)
    y0 = min(b[1] for _p, b in polys)
    x1 = max(b[2] for _p, b in polys)
    y1 = max(b[3] for _p, b in polys)
    cell = max(x1 - x0, y1 - y0, 1.0) / OWNER_GRID
    W, H = int((x1 - x0) / cell) + 2, int((y1 - y0) / cell) + 2
    best = np.zeros((H, W), np.float32)
    owner = np.full((H, W), -1, np.int32)
    seen = np.zeros(len(frames), np.int64)
    G = np.array([[1 / cell, 0, -x0 / cell], [0, 1 / cell, -y0 / cell], [0, 0, 1]])
    for k, (f, (_poly, (bx0, by0, bx1, by1))) in enumerate(zip(frames, polys, strict=True)):
        a = np.maximum(np.floor([(bx0 - x0) / cell, (by0 - y0) / cell]).astype(int), 0)
        b = np.minimum(np.ceil([(bx1 - x0) / cell, (by1 - y0) / cell]).astype(int) + 1, [W, H])
        if (b <= a).any():
            continue
        tpl = centrality(int(f["w"]), int(f["h"]))
        S = np.diag([float(OWNER_SCREEN_STEP), float(OWNER_SCREEN_STEP), 1.0])
        roi = np.array([[1, 0, -a[0]], [0, 1, -a[1]], [0, 0, 1]], float)
        Mt = roi @ G @ screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f)) @ S
        score = cv2.warpPerspective(tpl, Mt, (int(b[0] - a[0]), int(b[1] - a[1])), flags=cv2.INTER_LINEAR)
        seen[k] = int((score > 0).sum())
        sub_b, sub_o = best[a[1] : b[1], a[0] : b[0]], owner[a[1] : b[1], a[0] : b[0]]
        take = score > sub_b
        sub_b[take] = score[take]
        sub_o[take] = k
    counts = np.bincount(owner.ravel()[owner.ravel() >= 0], minlength=len(frames))
    return {f["name"]: (counts[k] / seen[k] if seen[k] else 0.0) for k, f in enumerate(frames)}
