"""core.geometry (from atlas_builder_core.py)"""

from __future__ import annotations

import cv2
import numpy as np


def rectifier(w: int, h: int, horizon: float | None) -> np.ndarray:
    """3x3 homography: screen px -> flat map coords (1:1 with screen px at the screen centre)."""
    if horizon is None:
        return np.eye(3)
    cx, cy = w / 2.0, h / 2.0
    vh = horizon * h  # horizon row in px
    d0 = cy - vh  # centre row's distance below the horizon
    return np.array([[d0, 0, -d0 * cx], [0, d0, -d0 * cy], [0, 1, -vh]], float) / d0


def persp(H: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    if len(pts) == 0:
        return pts
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), H).reshape(-1, 2)


def screen_to_atlas(M: np.ndarray, R: np.ndarray) -> np.ndarray:
    """3x3: screenshot px -> atlas coords, for a frame placed with flat-map affine M."""
    return to3(M) @ R


def apply(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ M[:, :2].T + M[:, 2]


def to3(M: np.ndarray) -> np.ndarray:
    return np.vstack([M, [0, 0, 1]])


def invert(M: np.ndarray) -> np.ndarray:
    return np.linalg.inv(to3(M))[:2]
