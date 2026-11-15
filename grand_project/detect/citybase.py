"""The brass barrel a City's map node stands on (user: a city's map is never hidden and always on the barrel
base; Halls, towers and plain deadly-boss maps stand on a flat disc). Green (completed) cities keep the barrel
when their icon and beam are gone, so this finds them too.

A small logistic model on the window under a map node: gradient directions (the barrel's upright sides) plus
brass colour and brightness per band. Trained by citytrain.py (part of `python -m grand_project.detect train`)
on the user's city screenshots; stored as plain numbers in references/city_barrel.npz (no pickled code).
"""

from __future__ import annotations

import cv2
import numpy as np

from .constants import (
    CITY_BARREL_FILE,
    CITY_BARREL_SNAP,
    CITY_BARREL_WIN,
)

_model: dict | None = None


def _hog(g: np.ndarray, cell: int = 8, bins: int = 9) -> np.ndarray:
    """Histogram of gradient directions (a small HOG) of a grey window.

    Args:
        g: 2-D grey image; height and width must be multiples of `cell`.
        cell: Cell size in px.
        bins: Number of direction bins over 0..180 degrees.

    Returns:
        1-D float32 array of length (h // cell) * (w // cell) * bins, each cell's histogram normalised to unit
        length.
    """
    g = g.astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    b = (np.mod(ang, 180) / (180 / bins)).astype(int) % bins
    h, w = g.shape
    out = np.zeros((h // cell, w // cell, bins), np.float32)
    for k in range(bins):
        m = np.where(b == k, mag, 0)
        out[..., k] = m.reshape(h // cell, cell, w // cell, cell).sum(axis=(1, 3))
    out /= np.linalg.norm(out, axis=2, keepdims=True) + 1e-3
    return out.ravel()


def features(img: np.ndarray, x: float, y: float) -> np.ndarray | None:
    """Barrel features of the window under the map node at (x, y).

    The window is CITY_BARREL_WIN around the point: gradient directions (the barrel's upright sides), the brass
    share per 8 px row band and per 8 px column (lower part), and mean brightness and saturation per row band.

    Args:
        img: BGR screenshot (1080p).
        x: Map node centre x in screen px.
        y: Map node centre y in screen px.

    Returns:
        1-D float32 feature vector, or None when the window runs off the screenshot.
    """
    y0, y1, x0, x1 = CITY_BARREL_WIN
    X, Y = int(round(x)), int(round(y))
    if Y + y0 < 0 or X + x0 < 0 or Y + y1 > img.shape[0] or X + x1 > img.shape[1]:
        return None
    w = img[Y + y0 : Y + y1, X + x0 : X + x1]
    hsv = cv2.cvtColor(w, cv2.COLOR_BGR2HSV).astype(np.float32)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    brass = ((H >= 10) & (H <= 32) & (S >= 70) & (V >= 60)).astype(np.float32)
    h, ww = brass.shape
    bands = [brass[a : a + 8].mean() for a in range(0, h, 8)]
    cols = [brass[24:, c : c + 8].mean() for c in range(0, ww, 8)]
    light = [V[a : a + 8].mean() / 255 for a in range(0, h, 8)] + [S[a : a + 8].mean() / 255 for a in range(0, h, 8)]
    return np.concatenate([_hog(cv2.cvtColor(w, cv2.COLOR_BGR2GRAY)), bands, cols, light]).astype(np.float32)


def _load() -> dict | None:
    """Load the barrel model from CITY_BARREL_FILE once and keep it.

    Returns:
        Dict with "mean", "scale", "coef" and "intercept" arrays, or None when the file does not exist.
    """
    global _model
    if _model is None and CITY_BARREL_FILE.exists():
        with np.load(CITY_BARREL_FILE) as z:
            _model = {k: z[k] for k in ("mean", "scale", "coef", "intercept")}
    return _model


def probability(F: np.ndarray) -> np.ndarray:
    """Barrel probability for feature rows.

    Args:
        F: (n, k) array of `features` rows.

    Returns:
        (n,) float array of probabilities; all zeros when no model is stored.
    """
    m = _load()
    if m is None or not len(F):
        return np.zeros(len(F))
    z = ((F - m["mean"]) / m["scale"]) @ m["coef"] + m["intercept"]
    return 1.0 / (1.0 + np.exp(-z))


def barrel_p(img: np.ndarray, x: float, y: float, nodes=None) -> float:
    """Probability that the map node at (x, y) stands on a City's barrel.

    The model knows exact map node middles: with `nodes` a rough point is moved to the nearest one within
    CITY_BARREL_SNAP px first (none that close: 0).

    Args:
        img: BGR screenshot (1080p).
        x: Point x in screen px.
        y: Point y in screen px.
        nodes: Optional detected map nodes, as dicts with "x"/"y" or (x, y) pairs, to snap the point to.

    Returns:
        Probability 0..1; 0.0 when no map node is near or the window runs off the screenshot.
    """
    if nodes is not None:
        pts = np.array([(n["x"], n["y"]) if isinstance(n, dict) else n for n in nodes], float).reshape(-1, 2)
        if not len(pts):
            return 0.0
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        if d.min() > CITY_BARREL_SNAP:
            return 0.0
        x, y = pts[int(d.argmin())]
    f = features(img, x, y)
    return float(probability(f[None])[0]) if f is not None else 0.0


def save_model(path, mean, scale, coef, intercept) -> None:
    """Store the barrel model as plain arrays in an .npz file (no pickled code).

    Args:
        path: Output .npz path (normally CITY_BARREL_FILE).
        mean: Per-feature mean used to standardise features.
        scale: Per-feature scale used to standardise features.
        coef: Logistic regression weights, one per feature.
        intercept: Logistic regression intercept.
    """
    np.savez(path, mean=mean, scale=scale, coef=coef, intercept=np.asarray(intercept, float))
