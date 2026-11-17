"""core.geometry (from atlas_builder_core.py)"""

from __future__ import annotations

import cv2
import numpy as np


def rectifier(w: int, h: int, horizon: float | None) -> np.ndarray:
    """Build the homography that flattens the atlas's tilted camera view.

    Maps screen px to flat map coordinates, 1:1 with screen px at the screen centre.

    Args:
        w: Screenshot width in px.
        h: Screenshot height in px.
        horizon: Horizon row as a fraction of the height (0..1), or None for an untilted view.

    Returns:
        3x3 homography from screen px to flat map coordinates (the identity when horizon is None).
    """
    if horizon is None:
        return np.eye(3)
    cx, cy = w / 2.0, h / 2.0
    vh = horizon * h  # horizon row in px
    d0 = cy - vh  # centre row's distance below the horizon
    return np.array([[d0, 0, -d0 * cx], [0, d0, -d0 * cy], [0, 1, -vh]], float) / d0


def persp(H: np.ndarray, pts) -> np.ndarray:
    """Apply a 3x3 homography to points.

    Args:
        H: 3x3 homography.
        pts: Points as anything numpy can reshape to (n, 2).

    Returns:
        (n, 2) float array of transformed points (empty input is returned as an empty (0, 2) array).
    """
    pts = np.asarray(pts, float).reshape(-1, 2)
    if len(pts) == 0:
        return pts
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), H).reshape(-1, 2)


def screen_to_atlas(M: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Combine a frame's flattening and placement into one screen-to-atlas homography.

    Args:
        M: 2x3 affine placing the frame's flat-map coordinates in the atlas.
        R: 3x3 rectifier of the frame (see rectifier).

    Returns:
        3x3 homography: screenshot px -> atlas coords, for a frame placed with flat-map affine M.
    """
    return to3(M) @ R


def apply(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 2x3 affine transform to points.

    Args:
        M: 2x3 affine matrix.
        pts: (n, 2) array of points.

    Returns:
        (n, 2) array of transformed points.
    """
    return pts @ M[:, :2].T + M[:, 2]


def to3(M: np.ndarray) -> np.ndarray:
    """Extend a 2x3 affine to a 3x3 matrix.

    Args:
        M: 2x3 affine matrix.

    Returns:
        3x3 matrix with [0, 0, 1] as the last row.
    """
    return np.vstack([M, [0, 0, 1]])


def invert(M: np.ndarray) -> np.ndarray:
    """Invert a 2x3 affine transform.

    Args:
        M: 2x3 affine matrix.

    Returns:
        2x3 affine matrix of the inverse transform.
    """
    return np.linalg.inv(to3(M))[:2]
