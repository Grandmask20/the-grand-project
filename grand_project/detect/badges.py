"""detect.badges (from atlas_detect.py)"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core, icon_refs

from .constants import (
    BADGE_MIN,
    BADGE_NMS,
    BADGE_ROW_MIN,
    HIDDEN_SNAP,
    MAP_NMS,
    RING_MIN,
    ROW_DY,
    ROW_RESCUE,
    ROW_STEP,
    TEMPLATE_MIN,
)
from .maps import _keep_best, map_features


def _ring_kernel(r0: float, r1: float, R: int = 15) -> np.ndarray:
    yy, xx = np.mgrid[-R : R + 1, -R : R + 1]
    k = ((np.hypot(xx, yy) >= r0) & (np.hypot(xx, yy) < r1)).astype(np.float32)
    return k / k.sum()


_K_RIM, _K_IN, _K_OUT = _ring_kernel(9.5, 11.5), _ring_kernel(7, 9), _ring_kernel(12.5, 14.5)


_badge_tpl: dict = {}


def _template() -> tuple[np.ndarray, np.ndarray]:
    """average stored badge (grey) and its rim mask"""
    if not _badge_tpl:
        g = [
            cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
            for _n, im in icon_refs.load()
            if im.shape[:2] == (icon_refs.SIZE, icon_refs.SIZE)
        ]
        yy, xx = np.mgrid[: icon_refs.SIZE, : icon_refs.SIZE]
        r = np.hypot(xx - icon_refs.SIZE / 2 + 0.5, yy - icon_refs.SIZE / 2 + 0.5)
        _badge_tpl["t"] = np.mean(g, 0).astype(np.float32)
        _badge_tpl["m"] = ((r >= 8.5) & (r <= 13.5)).astype(np.float32)
    return _badge_tpl["t"], _badge_tpl["m"]


def badge_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> points, ring score, extra features (ring score, template score, best stored-badge correlation)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    v = hsv[..., 2]
    gold = (((hsv[..., 0] >= 10) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 60)) * 1.0).astype(np.float32)
    ring = (
        cv2.filter2D(v, -1, _K_RIM)
        - 0.5 * (cv2.filter2D(v, -1, _K_IN) + cv2.filter2D(v, -1, _K_OUT))
        + 40 * cv2.filter2D(gold, -1, _K_RIM)
    )
    tpl, msk = _template()
    tm = np.nan_to_num(
        cv2.matchTemplate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), tpl, cv2.TM_CCORR_NORMED, mask=msk)
    )
    o = icon_refs.SIZE // 2
    ncc = np.zeros_like(v)
    ncc[o : o + tm.shape[0], o : o + tm.shape[1]] = tm
    k = np.ones((9, 9), np.uint8)
    pk = ((ring >= cv2.dilate(ring, k)) & (ring > RING_MIN)) | ((ncc >= cv2.dilate(ncc, k)) & (ncc > TEMPLATE_MIN))
    ys, xs = np.nonzero(pk & (core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH) == 0))
    pts = np.stack([xs, ys], 1)
    best = _best_ref_corr(img, pts)
    extra = np.stack([ring[ys, xs], ncc[ys, xs], best], 1).reshape(-1, 3)
    return pts, ring[ys, xs], extra


def _best_ref_corr(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """per point: best correlation with any stored badge picture (icon_refs.feature on every crop, but with
    the image blurred once - the blur never reaches the compared circle from a crop edge)"""
    R = icon_refs.refs()
    out = np.zeros(len(pts), np.float32)
    if not len(R) or not len(pts):
        return out
    blur = cv2.GaussianBlur(img, (0, 0), 1.5)
    r = icon_refs.SIZE // 2
    my, mx = np.nonzero(icon_refs._MASK)
    X = np.round(pts[:, 0]).astype(int)
    Y = np.round(pts[:, 1]).astype(int)
    h, w = img.shape[:2]
    ok = (Y - r >= 0) & (Y - r + icon_refs.SIZE <= h) & (X - r >= 0) & (X - r + icon_refs.SIZE <= w)
    for s0 in range(0, len(pts), 2048):
        idx = np.nonzero(ok[s0 : s0 + 2048])[0] + s0
        if not len(idx):
            continue
        v = blur[(Y[idx] - r)[:, None] + my, (X[idx] - r)[:, None] + mx].astype(np.float32)  # (k, npix, 3)
        v -= v.mean(axis=1, keepdims=True)
        v = v.reshape(len(idx), -1)
        nrm = np.linalg.norm(v, axis=1, keepdims=True)
        v = np.where(nrm > 1e-6, v / np.maximum(nrm, 1e-12), v)
        out[idx] = (v @ R.F.T).max(1)
    return out


def badge_features(img: np.ndarray, pts: np.ndarray, ring: np.ndarray, extra: np.ndarray) -> np.ndarray:
    return np.hstack([map_features(img, pts, ring), extra])


def badge_labels(pts: np.ndarray, t: dict) -> np.ndarray:
    """1 = the candidate closest to a labelled badge (within 6 px), -1 = other candidates on it"""
    lab = np.zeros(len(pts), int)
    for b in t["badges"]:
        d = np.hypot(pts[:, 0] - b["x"], pts[:, 1] - b["y"])
        lab[(d < 12) & (lab == 0)] = -1
        j = int(np.argmin(d)) if len(d) else 0
        if len(d) and d[j] <= 6:
            lab[j] = 1
    return lab


def _row_slot(x: float, y: float, maps: list[dict]) -> bool:
    """x, y is where a badge of a row of 1-5 above one of the maps would sit"""
    for m in maps:
        dx, dy = x - m["x"], y - (m["y"] - ROW_DY)
        if abs(dy) <= 5 and abs(dx) <= 2 * ROW_STEP + 5 and min(abs(dx - k * ROW_STEP / 2) for k in range(-4, 5)) <= 5:
            return True
    return False


def name_badge(img: np.ndarray, x: float, y: float, names: list[str], F: np.ndarray) -> tuple[str, float]:
    """closest badge picture (stored + labelled), trying +-3 px shifts -> (name, 1 - correlation)"""
    big = icon_refs.crop(img, x, y, icon_refs.SIZE + 2 * icon_refs.SHIFT)
    if big is None or not len(names):
        return "Unidentified", 9.0
    d = np.full(len(names), 9.0, np.float32)
    for dy in range(2 * icon_refs.SHIFT + 1):
        for dx in range(2 * icon_refs.SHIFT + 1):
            d = np.minimum(d, 1 - F @ icon_refs.feature(big[dy : dy + icon_refs.SIZE, dx : dx + icon_refs.SIZE]))
    k = int(np.argmin(d))
    return (names[k] if d[k] <= icon_refs.MAX_DIST else "Unidentified"), float(d[k])


def badge_rows(icons: list[dict]) -> list[list[dict]]:
    """badges side by side (same height, 36 px apart; one badge of a row may be missed, so 72 px also
    joins) -> rows, left to right"""
    rows: list[list[dict]] = []
    for b in sorted(icons, key=lambda b: b["x"]):
        for r in rows:
            gap = b["x"] - r[-1]["x"]
            if abs(b["y"] - r[-1]["y"]) <= 5 and (abs(gap - ROW_STEP) <= 6 or abs(gap - 2 * ROW_STEP) <= 8):
                r.append(b)
                break
        else:
            rows.append([b])
    return rows


def badges_from(
    img: np.ndarray,
    pts: np.ndarray,
    p: np.ndarray,
    book: dict,
    maps: list[dict],
    map_pts: np.ndarray,
    map_p: np.ndarray,
) -> tuple[list, list]:
    """badge probabilities -> named badges + more maps: under a badge row with no map found, the best weak
    map candidate (source 'badge row'), or else a hidden map"""
    icons = [
        {"x": float(pts[i][0]), "y": float(pts[i][1]), "score": round(float(p[i]), 3)}
        for i in _keep_best(pts, p, BADGE_MIN, BADGE_NMS)
    ]
    for i in _keep_best(pts, p, BADGE_ROW_MIN, BADGE_NMS):
        x, y = float(pts[i][0]), float(pts[i][1])
        if p[i] >= BADGE_MIN or any(np.hypot(x - b["x"], y - b["y"]) <= BADGE_NMS for b in icons):
            continue
        mate = any(abs(y - b["y"]) <= 5 and abs(abs(x - b["x"]) - ROW_STEP) <= 5 for b in icons)
        if mate or _row_slot(x, y, maps):
            icons.append({"x": x, "y": y, "score": round(float(p[i]), 3), "row": True})
    R = icon_refs.refs()
    names = R.names + book["names"]
    F = np.vstack([R.F, book["F"]]) if len(book["names"]) else R.F
    out = []
    for b in icons:
        nm, d = name_badge(img, b["x"], b["y"], names, F)
        if nm != icon_refs.NOT_A_BADGE:
            out.append(dict(b, name=nm, dist=round(d, 3)))
    more: list[dict] = []
    for row in badge_rows(out):
        cx = (row[0]["x"] + row[-1]["x"]) / 2  # the map sits under the row's middle (user)
        cy = float(np.mean([b["y"] for b in row])) + ROW_DY
        if any(np.hypot(cx - m["x"], cy - m["y"]) <= MAP_NMS for m in maps + more):
            continue
        d = np.hypot(map_pts[:, 0] - cx, map_pts[:, 1] - cy) if len(map_pts) else np.zeros(0)
        ok = (d <= ROW_RESCUE[1]) & (map_p >= ROW_RESCUE[0]) if len(d) else d.astype(bool)
        if ok.any():
            j = int(np.argmax(np.where(ok, map_p, -1)))
            more.append(
                {
                    "x": float(map_pts[j][0]),
                    "y": float(map_pts[j][1]),
                    "score": round(float(map_p[j]), 3),
                    "source": "badge row",
                }
            )
        elif not any(np.hypot(cx - m["x"], cy - m["y"]) <= HIDDEN_SNAP for m in maps + more if not m.get("hidden")):
            # (a visible map this close is the row's map, not a hidden one next to it - user)
            more.append({"x": round(cx, 1), "y": round(cy, 1), "hidden": True, "source": "badge row"})
    return out, more


def badge_book(truth: dict, imgs: dict, names) -> dict:
    """labelled badge pictures of these screenshots (kept inside the badge model, not in badge_refs)"""
    nm, F = [], []
    for n in names:
        for b in truth[n]["badges"]:
            c = icon_refs.crop(imgs[n], b["x"], b["y"])
            if c is not None:
                nm.append(b["name"])
                F.append(icon_refs.feature(c))
    return {"names": nm, "F": np.array(F, np.float32)}


def find_badges(
    img: np.ndarray, model: dict, maps: list[dict], map_pts: np.ndarray, map_p: np.ndarray
) -> tuple[list, list]:
    pts, ring, extra = badge_candidates(img)
    if not len(pts):
        return [], []
    p = model["clf"].predict_proba(badge_features(img, pts, ring, extra))[:, 1]
    return badges_from(img, pts, p, model, maps, map_pts, map_p)
