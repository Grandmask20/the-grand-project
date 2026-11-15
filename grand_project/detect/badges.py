"""detect.badges (from atlas_detect.py)"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core, icon_refs

from .constants import (
    BADGE_FINDER_FILE,
    BADGE_MIN,
    BADGE_NMS,
    BADGE_ROW_MIN,
    HIDDEN_SNAP,
    ICON_CLEAR,
    ICON_RIM_R,
    MAP_NMS,
    RIM_CANDIDATE,
    ROW_DY,
    ROW_RESCUE,
    ROW_STEP,
    SPECIAL_ICONS,
    SPECIAL_R,
)
from .maps import _keep_best


def _finder() -> dict:
    """the icon finder's rim template (BADGE_FINDER_FILE, tools/freeze_badge_finder.py): the average icon as seen
    on screen, used only on the rim (radii ICON_RIM_R). Never the stored icon pictures: those only NAME an icon."""
    if not _rim:
        with np.load(BADGE_FINDER_FILE) as z:
            mean = z["rim"].astype(np.float32)
        S = mean.shape[0]
        yy, xx = np.mgrid[:S, :S]
        r = np.hypot(xx - S / 2 + 0.5, yy - S / 2 + 0.5)
        m = ((r >= ICON_RIM_R[0]) & (r < ICON_RIM_R[1])).astype(np.float32)
        t = (mean - (mean * m).sum() / m.sum()) * m
        _rim.update(T=t / np.linalg.norm(t), M=m, n=float(m.sum()))
        with np.load(BADGE_FINDER_FILE) as z:
            _rim["special"] = {k[8:]: z[k].astype(np.float32) for k in z.files if k.startswith("special_")}
    return _rim


def special_icons(img: np.ndarray) -> list[dict]:
    """icons with their own rim (SPECIAL_ICONS), found and named by a whole-icon template"""
    out: list[dict] = []
    clear = _clear(img)
    f32 = img.astype(np.float32)
    for name, t in _finder()["special"].items():
        if name not in SPECIAL_ICONS:
            continue
        S = t.shape[0]
        yy, xx = np.mgrid[:S, :S]
        m = (np.hypot(xx - S / 2 + 0.5, yy - S / 2 + 0.5) <= SPECIAL_R).astype(np.float32)
        r = np.nan_to_num(cv2.matchTemplate(f32, t, cv2.TM_CCOEFF_NORMED, mask=np.dstack([m] * 3)))
        full = np.zeros(img.shape[:2], np.float32)
        full[S // 2 : S // 2 + r.shape[0], S // 2 : S // 2 + r.shape[1]] = r
        pk = (full >= cv2.dilate(full, np.ones((9, 9), np.uint8))) & (full >= SPECIAL_ICONS[name]) & clear
        for y, x in zip(*np.nonzero(pk), strict=True):
            out.append({"x": float(x), "y": float(y), "score": round(float(full[y, x]), 3), "name": name, "dist": 0.0})
    return out


_rim: dict = {}


def rim_score(img: np.ndarray) -> np.ndarray:
    """per pixel: correlation of the ring around it (radii ICON_RIM_R) with an icon's rim - the inside (which icon)
    and the outside (the map) are not looked at"""
    f = _finder()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    a = cv2.filter2D(g, -1, f["T"], borderType=cv2.BORDER_REFLECT)
    s1 = cv2.filter2D(g, -1, f["M"], borderType=cv2.BORDER_REFLECT)
    s2 = cv2.filter2D(g * g, -1, f["M"], borderType=cv2.BORDER_REFLECT)
    return a / np.sqrt(np.maximum(s2 - s1 * s1 / f["n"], 1e-3))


def _clear(img: np.ndarray) -> np.ndarray:
    """per pixel: an icon centred here is whole on the screen and clear of the HUD (user: the HUD is masked
    before detection; an icon half under it or off the screen is read from another screenshot)"""
    h, w = img.shape[:2]
    free = (core.hud_mask(w, h) == 0).astype(np.uint8)
    free[[0, -1], :] = 0
    free[:, [0, -1]] = 0
    return cv2.distanceTransform(free, cv2.DIST_L2, 3) >= ICON_CLEAR


def badge_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> points (circles whose rim looks like an icon's), their rim score, and the same score as 'extra'"""
    sc = rim_score(img)
    pk = (sc >= cv2.dilate(sc, np.ones((9, 9), np.uint8))) & (sc > RIM_CANDIDATE) & _clear(img)
    ys, xs = np.nonzero(pk)
    pts = np.stack([xs, ys], 1).reshape(-1, 2)
    v = sc[ys, xs]
    return pts, v, v[:, None]


_ANG = np.linspace(0, 2 * np.pi, 24, endpoint=False)
_RADII = np.arange(6, 14.5, 1.0)


def badge_features(img: np.ndarray, pts: np.ndarray, ring: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """rim only: per radius 6..14 px, how even the ring is all round, its gold share and saturation; the shape of
    the brightness profile across the radii; and the rim score. Nothing from inside the rim."""
    if not len(pts):
        return np.zeros((0, 4 * len(_RADII) + 2), np.float32)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gold = ((hsv[..., 0] >= 10) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 60)).astype(np.float32)
    sat = hsv[..., 1].astype(np.float32) / 255
    h, w = g.shape
    X, Y = pts[:, 0].astype(np.float32)[:, None], pts[:, 1].astype(np.float32)[:, None]
    even, gol, sa, prof = [], [], [], []
    for r in _RADII:
        xs = np.clip(np.round(X + r * np.cos(_ANG)).astype(int), 0, w - 1)
        ys = np.clip(np.round(Y + r * np.sin(_ANG)).astype(int), 0, h - 1)
        v = g[ys, xs]
        m = v.mean(1)
        prof.append(m)
        even.append(v.std(1) / (m + 1))
        gol.append(gold[ys, xs].mean(1))
        sa.append(sat[ys, xs].mean(1))
    prof = np.stack(prof, 1)
    shape = (prof - prof.mean(1, keepdims=True)) / (prof.std(1, keepdims=True) + 1)
    spread = prof.std(1) / (prof.mean(1) + 1)
    return np.hstack(
        [np.stack(even, 1), np.stack(gol, 1), np.stack(sa, 1), shape, spread[:, None], np.asarray(ring)[:, None]]
    ).astype(np.float32)


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
    """closest badge picture (stored + labelled), trying +-3 px shifts -> (name, 1 - correlation); only names
    whose stored pictures have a bright part of the same colour (icon_refs.colour_ok)"""
    big = icon_refs.crop(img, x, y, icon_refs.SIZE + 2 * icon_refs.SHIFT)
    if big is None or not len(names):
        return "Unidentified", 9.0
    d = np.full(len(names), 9.0, np.float32)
    for dy in range(2 * icon_refs.SHIFT + 1):
        for dx in range(2 * icon_refs.SHIFT + 1):
            d = np.minimum(d, 1 - F @ icon_refs.feature(big[dy : dy + icon_refs.SIZE, dx : dx + icon_refs.SIZE]))
    s = icon_refs.SHIFT
    d[~icon_refs.colour_ok(names, icon_refs.refs().colours, big[s : s + icon_refs.SIZE, s : s + icon_refs.SIZE])] = 9.0
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
    special = special_icons(img)  # own rims: found and named by their template, they win over the rim finder
    out = list(special)
    for b in icons:
        if any(np.hypot(b["x"] - s_["x"], b["y"] - s_["y"]) <= BADGE_NMS for s_ in special):
            continue
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
