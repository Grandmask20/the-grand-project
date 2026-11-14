"""detect.maps (from atlas_detect.py)"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core

from .constants import BLOB_MIN, BLOB_SIGMA, BLOB_WIN, MAP, MAP_MERGE, MAP_MIN, NOT, RIM_R, R

# Towers are maps in the path network and are labelled MAP here: a separate tower class had only
# ~17 examples and learned grass / water as "tower". Tower vs map is decided in the landmark stage.


# ---------------------------------------------------------------- stage 1
def drop_hud(result: dict, w: int, h: int) -> dict:
    """remove maps, badges and landmarks that sit on the game HUD"""
    out = dict(result)
    for k in ("nodes", "icons", "landmarks"):
        items = result.get(k, [])
        if items:
            on = core.on_hud_mask([(i["x"], i["y"]) for i in items], w, h)
            out[k] = [i for i, bad in zip(items, on, strict=False) if not bad]
    return out


# ---------------------------------------------------------------- stage 2
def map_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32)
    dog = cv2.GaussianBlur(v, (0, 0), BLOB_SIGMA[0]) - cv2.GaussianBlur(v, (0, 0), BLOB_SIGMA[1])
    peak = dog >= cv2.dilate(dog, np.ones((BLOB_WIN, BLOB_WIN), np.uint8))
    hud = core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH)
    ys, xs = np.nonzero(peak & (dog > BLOB_MIN) & (hud == 0))
    return np.stack([xs, ys], 1), dog[ys, xs]


_yy, _xx = np.mgrid[-R : R + 1, -R : R + 1]


_rad = np.hypot(_xx, _yy)


_RINGS = [(_rad >= a) & (_rad < a + 2) for a in range(0, R, 2)]


_ang = np.arctan2(_yy, _xx)


_SECT = [(np.floor((_ang + np.pi) / (np.pi / 4)) % 8 == k) & (_rad >= 4) & (_rad < 12) for k in range(8)]


_Y2, _X2 = np.mgrid[-RIM_R : RIM_R + 1, -RIM_R : RIM_R + 1]


_rad2 = np.hypot(_X2, _Y2)


_WIDE = [(_rad2 >= a) & (_rad2 < a + 8) for a in range(8, RIM_R, 8)]


def map_features(img: np.ndarray, pts: np.ndarray, dogv: np.ndarray) -> np.ndarray:
    """per candidate: brightness / colour per 2 px ring, how even the glow is around the centre,
    gradient directions, a 9x9 shape thumbnail, contrast with the surroundings, and the share of
    gold-rim colour in 8 px rings out to 48 px (a tower's rim reaches ~3x as far as a map's).
    All candidates at once: patches are stacked and every masked mean is a matrix product."""
    h, w = img.shape[:2]
    n = len(pts)
    P = RIM_R + 2
    big = cv2.copyMakeBorder(img, P, P, P, P, cv2.BORDER_REFLECT)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV).astype(np.float32)
    lab = cv2.cvtColor(big, cv2.COLOR_BGR2LAB).astype(np.float32)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag, ori = np.hypot(gx, gy), np.arctan2(gy, gx) % np.pi
    gold = ((hsv[..., 0] >= 8) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 90) & (hsv[..., 2] > 110)).astype(np.float32)
    obin = (ori / np.pi * 8).astype(int).clip(0, 7)
    hrad = hsv[..., 0] / 90 * np.pi
    planes = np.stack(
        [
            hsv[..., 2],
            hsv[..., 1],
            lab[..., 0],
            lab[..., 1],
            lab[..., 2],
            np.cos(hrad),
            np.sin(hrad),
            np.zeros_like(mag),
            mag,
        ]
        + [mag * (obin == k) for k in range(8)],
        -1,
    )  # (H, W, 17)
    cx = pts[:, 0].astype(int) + P if n else np.zeros(0, int)
    cy = pts[:, 1].astype(int) + P if n else np.zeros(0, int)
    oy, ox = np.mgrid[-R : R + 1, -R : R + 1]
    oy2, ox2 = np.mgrid[-RIM_R : RIM_R + 1, -RIM_R : RIM_R + 1]

    def masks(ms):
        M = np.stack([m.ravel().astype(np.float32) for m in ms], 1)
        return M / M.sum(0)  # columns: averaging weights

    ring_w = masks(_RINGS)  # (1089, 8)
    ring_of = np.argmax(np.stack([m.ravel() for m in _RINGS], 1), 1)  # ring of each patch pixel (outside: unused)
    sect_w = masks(_SECT)
    reg_w = np.stack([(_rad < 8).ravel(), ((_rad >= 8) & (_rad <= R)).ravel()], 1).astype(np.float32)
    in5_w = masks([_rad < 5])
    wide_w = masks([_rad2 < 8] + _WIDE)
    all2_w = np.full(((2 * RIM_R + 1) ** 2, 1), 1.0 / (2 * RIM_R + 1) ** 2, np.float32)
    out = np.zeros((n, 1 + 8 * 8 + 3 + 2 * 9 + 81 + 3 + 1 + len(_WIDE) * 2 + 2), np.float32)
    for s in range(0, n, 512):  # in chunks: ~512 x 1089 x 17 floats
        Y, X = cy[s : s + 512], cx[s : s + 512]
        k = len(Y)
        pat = planes[Y[:, None, None] + oy, X[:, None, None] + ox].reshape(k, -1, planes.shape[-1])  # (k, 1089, 17)
        r = np.einsum("kpc,pm->kmc", pat, ring_w)  # ring means per plane (k, 8, 17)
        Vr = r[..., 0]
        dev = (pat[..., 0] - Vr[:, ring_of]) ** 2  # two-pass spread (exact, no E[x^2]-E[x]^2 rounding)
        Vstd = np.sqrt(dev @ ring_w)
        ringf = np.stack([Vr, Vstd, r[..., 1], r[..., 2], r[..., 3], r[..., 4], r[..., 5], r[..., 6]], -1).reshape(
            k, -1
        )
        sv = pat[..., 0] @ sect_w  # (k, 8)
        sectf = np.stack([sv.std(1), sv.min(1), sv.max(1)], 1)
        gradf = []
        for c in range(2):  # centre / outer region
            wsum = reg_w[:, c]
            hist = np.einsum("kpb,p->kb", pat[..., 9:17], wsum)
            msum = pat[..., 8] @ wsum
            gradf += [hist / (hist.sum(1, keepdims=True) + 1e-6), (msum / wsum.sum())[:, None]]
        thumbs = (
            np.stack(
                [
                    cv2.resize(g[y - R : y + R + 1, x - R : x + R + 1], (9, 9), interpolation=cv2.INTER_AREA)
                    for y, x in zip(Y, X, strict=False)
                ]
            )
            .astype(np.float32)
            .reshape(k, -1)
        )
        thumbs = (thumbs - thumbs.mean(1, keepdims=True)) / (thumbs.std(1, keepdims=True) + 1)
        wv = hsv[..., 2][Y[:, None, None] + oy2, X[:, None, None] + ox2].reshape(k, -1)
        wg = gold[Y[:, None, None] + oy2, X[:, None, None] + ox2].reshape(k, -1)
        wmean = (wv @ all2_w)[:, 0]
        wstd = wv.std(1)
        c5 = (pat[..., 0] @ in5_w)[:, 0]
        goldf = wg @ wide_w  # (k, 1 + len(_WIDE))
        vwide = wv @ wide_w[:, 1:]
        out[s : s + k] = np.hstack(
            [dogv[s : s + k, None], ringf, sectf]
            + gradf
            + [
                thumbs,
                wmean[:, None],
                wstd[:, None],
                (c5 - wmean)[:, None],
                goldf,
                vwide,
                (pts[s : s + k, 0] / w)[:, None],
                (pts[s : s + k, 1] / h)[:, None],
            ]
        )
    return out


def candidate_labels(pts: np.ndarray, t: dict) -> np.ndarray:
    """truth -> NOT / MAP per candidate, -1 = leave out of training (near a map but not its centre,
    near a tower base, off-centre or behind-HUD maps, 'maybe' spots)"""
    lab = np.zeros(len(pts), int)
    towers = [landmark for landmark in t["landmarks"] if landmark["kind"] == "Tower"]
    good = [m for m in t["maps"] if not ({"offcenter", "ui"} & set(m["flags"]))]
    soft = [m for m in t["maps"] if {"offcenter", "ui"} & set(m["flags"])] + t["maybe"]
    for m in good:
        d = np.hypot(pts[:, 0] - m["x"], pts[:, 1] - m["y"])
        tower = any(np.hypot(tower["x"] - m["x"], tower["y"] - m["y"]) < 20 for tower in towers)
        lab[(d < (45 if tower else 25)) & (lab == NOT)] = -1
        j = int(np.argmin(d)) if len(d) else 0
        if len(d) and d[j] <= 14:
            lab[j] = MAP
    for m in soft:
        d = np.hypot(pts[:, 0] - m["x"], pts[:, 1] - m["y"])
        lab[(d < 45) & (lab == NOT)] = -1
    return lab


def _nms(pts: np.ndarray, prob: np.ndarray) -> list[dict]:
    """keep the best candidate per map"""
    p = prob[:, MAP]
    return [
        {"x": float(pts[i][0]), "y": float(pts[i][1]), "score": round(float(p[i]), 3)}
        for i in _keep_best(pts, p, MAP_MIN, MAP_MERGE)
    ]


def _keep_best(pts: np.ndarray, p: np.ndarray, thr: float, r: float) -> list[int]:
    """indices of the most likely points (p >= thr), best first, dropping any within r of a kept one"""
    keep: list[int] = []
    for i in np.argsort(-p):
        if p[i] < thr:
            break
        if all(np.hypot(*(pts[i] - pts[k])) > r for k in keep):
            keep.append(i)
    return keep
