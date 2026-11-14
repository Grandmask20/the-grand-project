"""detect.walls (from atlas_detect.py)"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core
from grand_project import paths as rc_paths

from .cache import _per_image
from .constants import DB_PATH, FORTRESS_PAINT, WALL_CORNERS, WALL_MIN_AREA, WALL_MIN_LEN, WALL_SCALES, WALL_STEP
from .models import _models, load_model, save_model


def wall_features(img: np.ndarray) -> np.ndarray:
    """per WALL_STEP px point: colour / rust-rib / dark-stone / gradient-direction densities at three scales"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k1 = np.array([[0, 1, 2], [-1, 0, 1], [-2, -1, 0]], np.float32)
    base = {
        "V": V,
        "S": S,
        "Hs": np.sin(H / 90 * np.pi),
        "Hc": np.cos(H / 90 * np.pi),
        "rust": (((H <= 16) | (H >= 175)) & (S >= 70) & (V >= 40)).astype(np.float32),
        "dark": ((S < 70) & (V >= 15) & (V < 90)).astype(np.float32),
        "green": ((H >= 30) & (H <= 90) & (S >= 60)).astype(np.float32),
        "blue": ((H >= 90) & (H <= 130) & (S >= 60)).astype(np.float32),
        "gx": np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)),
        "gy": np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)),
        "gd1": np.abs(cv2.filter2D(g, cv2.CV_32F, k1)),
        "gd2": np.abs(cv2.filter2D(g, cv2.CV_32F, k1[:, ::-1])),
    }
    o, st = WALL_STEP // 2, WALL_STEP
    out = []
    h, w = g.shape
    for k in WALL_SCALES:
        for m in base.values():
            out.append(cv2.blur(m, (k, k))[o::st, o::st])
        Vb = cv2.blur(V, (k, k))
        out.append(np.sqrt(np.maximum(cv2.blur(V * V, (k, k)) - Vb * Vb, 0))[o::st, o::st])
    yy, xx = np.mgrid[o:h:st, o:w:st]
    out.append(np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)).astype(np.float32))
    return np.stack(out, -1)


def _wall_clean(prob: np.ndarray, img: np.ndarray) -> np.ndarray:
    """wall pixels: big regions with simple (straight-ish) outlines; ragged blobs (Corruption ground) dropped"""
    b = ((prob >= 0.5) & (core.hud_mask(img.shape[1], img.shape[0]) == 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    keep = np.zeros_like(b)
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if a < WALL_MIN_AREA or max(w, h) < WALL_MIN_LEN:
            continue
        cs, _ = cv2.findContours((lab == k).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        c = max(cs, key=cv2.contourArea)
        if len(cv2.approxPolyDP(c, 14, True)) / max(1.0, cv2.arcLength(c, True) / 100) <= WALL_CORNERS:
            keep[lab == k] = 1
    return keep


@_per_image
def fortress_walls(img: np.ndarray) -> np.ndarray:
    """uint8 mask of the fortress walls (user: paths never cross them); zeros without a trained model"""
    if "fortress" not in _models:
        _models["fortress"] = load_model("fortress")
    m = _models["fortress"]
    if m is None:
        return np.zeros(img.shape[:2], np.uint8)
    F = wall_features(img)
    p = m.predict_proba(F.reshape(-1, F.shape[-1]))[:, 1].reshape(F.shape[:2]).astype(np.float32)
    p = cv2.GaussianBlur(cv2.resize(p, (img.shape[1], img.shape[0])), (0, 0), 6)
    return _wall_clean(p, img)


def wall_share(line, wall: np.ndarray, skip: float = 30.0) -> float:
    """share of a path's middle (ends left out: a wall-tower map sits on the wall) lying on wall"""
    L = np.asarray(line, float).reshape(-1, 2)
    if len(L) < 2 or not wall.any():
        return 0.0
    seg = np.hypot(*np.diff(L, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    if cum[-1] <= 2 * skip:
        return 0.0
    t = np.arange(skip, cum[-1] - skip, 6.0)
    x = np.clip(np.interp(t, cum, L[:, 0]).astype(int), 0, wall.shape[1] - 1)
    y = np.clip(np.interp(t, cum, L[:, 1]).astype(int), 0, wall.shape[0] - 1)
    return float(wall[y, x].mean())


def _lit_walls(img: np.ndarray) -> np.ndarray:
    """rough rule-based wall tops (rust ribs + dark stone), only to pick non-fortress shots for training"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = [hsv[..., i].astype(np.int16) for i in range(3)]
    rust = ((H <= 16) | (H >= 175)) & (S >= 70) & (S <= 220) & (V >= 55) & (V <= 210)
    dark = (S < 60) & (V >= 25) & (V < 90)
    m = (cv2.blur(rust.astype(np.float32), (25, 25)) > 0.14) & (cv2.blur(dark.astype(np.float32), (25, 25)) > 0.15)
    m = m.astype(np.float32)
    return _wall_clean(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)), img)


def cmd_train_fortress() -> int:
    """py atlas_detect.py train_fortress   (user-painted walls + non-fortress shots as negatives)"""
    import glob

    from sklearn.ensemble import HistGradientBoostingClassifier

    o, st = WALL_STEP // 2, WALL_STEP
    X, y = [], []
    for mf in sorted(FORTRESS_PAINT.glob("[0-9]*.png")):
        img = cv2.imdecode(np.fromfile(str(FORTRESS_PAINT / f"paint_{mf.stem}.png"), np.uint8), cv2.IMREAD_COLOR)
        lab = cv2.imdecode(np.fromfile(str(mf), np.uint8), cv2.IMREAD_UNCHANGED)[..., 3] >= 128
        hud = (core.hud_mask(img.shape[1], img.shape[0]) > 0)[o::st, o::st]
        F = wall_features(img)
        X.append(F[~hud])
        y.append(lab[o::st, o::st][~hud])
    npaint = len(X)
    S_ = rc_paths.SCREENSHOTS
    pool = (
        sorted(glob.glob(str(S_ / "random_samples" / "*.png")))[1::4]
        + sorted(glob.glob(str(S_ / "crawl" / "*.png")))[60::12]
        + sorted(glob.glob(str(S_ / "ocean" / "*.png")))[::10]
    )
    for p in pool:
        img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        if _lit_walls(img).any():
            continue
        hud = (core.hud_mask(img.shape[1], img.shape[0]) > 0)[o::st, o::st]
        F = wall_features(img)
        X.append(F[~hud])
        y.append(np.zeros(int((~hud).sum()), bool))
    m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.1, random_state=0).fit(
        np.vstack(X), np.concatenate(y)
    )
    save_model("fortress", m, {"painted": npaint, "negatives": len(X) - npaint})
    print(f"fortress wall model: {npaint} painted shots + {len(X) - npaint} non-fortress shots -> {DB_PATH.name}")
    return 0
