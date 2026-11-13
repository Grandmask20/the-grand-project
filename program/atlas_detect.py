"""One detector for atlas screenshots (replaces node_recognition + icon matcher + path finder; being built).

Stages, each scored against atlas_test_data/truth/truth.json (not shipped) with atlas_truth.score:
  1. HUD      the game's interface (hud_mask_full.png, drawn by the user) is never a map, badge or landmark
  2. maps     bright-blob candidates -> learned classifier: map (towers included) / not a map
  3. badges   gold-ring + average-badge spots -> badge classifier -> name from the badge pictures
              (badge_refs table + the labelled ones kept in the model); rows of up to 5 badges sit 24 px
              above their map, centred on it (user) -> a badge row with no map found = a hidden map
  4. landmarks Towers (classifier on found maps: the spire above them); Deadly Map Boss rows -> City (barrel
              / blue or red beam) / Hall (beam on a structure beside it) / deadly boss map; Breach
              strongholds (old purple rule), locked when a hand badge is near or no map is inside
  5. paths    amber / dim-gold / fog-orange dash mask -> dash-by-dash tracing between maps by the user's
              path rules; two dead ends meeting = a missed map; dashes around a spot are map evidence too
  6. biome    ground type per map
Modes: TRAINING fits models from the hand-labelled truth and stores them in the reference DB
(table detector_models); LIVE only reads them and never writes the DB.

    py atlas_detect.py score       stage 1 on the old detector's output, then stage 2 tested
                                   leave-one-screenshot-out (trained on 9, scored on the 10th)
    py atlas_detect.py train       training mode: fit the map + badge models on all labelled screenshots -> DB
    py atlas_detect.py run IMG...  live mode: maps per screenshot (reads the DB, never writes it)
"""
from __future__ import annotations

import hashlib
import io
import json
import pickle
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import atlas_builder_core as core  # noqa: E402
import atlas_icon_refs as icon_refs  # noqa: E402
import atlas_truth  # noqa: E402

DETECTOR_ID = "detect1"   # in builder cache file names: results of another detector are never reused
import rc_paths  # noqa: E402
TESTS = rc_paths.TEST_DATA
TRUTH = TESTS / "truth" / "truth.json"
SHOTS = rc_paths.SCREENSHOTS / "random_samples"
CACHE = TESTS / "old_detector_cache"   # (not shipped: old-detector comparison only)
TOWER_REFS = TESTS / "truth" / "tower_refs.json"   # towers / maps in the user's tower shots
TRUTH_SETS = [(TRUTH, SHOTS),                                        # (truth.json, its screenshots)
              (TESTS / "truth_ocean" / "truth.json", rc_paths.SCREENSHOTS / "ocean")]   # ocean / Expedition round
EXTRA_MAPS = TESTS / "truth" / "extra_maps.json"   # maps only: the user's path-marked shots
DB_PATH = rc_paths.DATABASE

# stage 2 settings
BLOB_SIGMA = (2, 7)        # difference of blurs on brightness: a map base's glow
BLOB_MIN = 10              # catches 759 of 766 labelled visible maps
BLOB_WIN = 15
R = 16                     # map-base patch radius (px at 1080p)
RIM_R = 48                 # tower rims are ~3x a map rim (user): gold measured out to here
MAP_NMS = 22
MAP_MERGE = 30           # two map finds closer than this are one map (duplicates sat 24-38 px apart; 10 labelled
                         # shots: 32 -> 27 wrong, 1 real pair lost - real maps are rarely < 30 px apart)
MAP_MIN = 0.5              # probability to call a candidate a map
NOT, MAP = 0, 1
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
            out[k] = [i for i, bad in zip(items, on) if not bad]
    return out


# ---------------------------------------------------------------- stage 2
def map_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32)
    dog = cv2.GaussianBlur(v, (0, 0), BLOB_SIGMA[0]) - cv2.GaussianBlur(v, (0, 0), BLOB_SIGMA[1])
    peak = dog >= cv2.dilate(dog, np.ones((BLOB_WIN, BLOB_WIN), np.uint8))
    hud = core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH)
    ys, xs = np.nonzero(peak & (dog > BLOB_MIN) & (hud == 0))
    return np.stack([xs, ys], 1), dog[ys, xs]


_yy, _xx = np.mgrid[-R:R + 1, -R:R + 1]
_rad = np.hypot(_xx, _yy)
_RINGS = [(_rad >= a) & (_rad < a + 2) for a in range(0, R, 2)]
_ang = np.arctan2(_yy, _xx)
_SECT = [(np.floor((_ang + np.pi) / (np.pi / 4)) % 8 == k) & (_rad >= 4) & (_rad < 12) for k in range(8)]
_Y2, _X2 = np.mgrid[-RIM_R:RIM_R + 1, -RIM_R:RIM_R + 1]
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
    planes = np.stack([hsv[..., 2], hsv[..., 1], lab[..., 0], lab[..., 1], lab[..., 2], np.cos(hrad), np.sin(hrad),
                       np.zeros_like(mag), mag] + [mag * (obin == k) for k in range(8)], -1)      # (H, W, 17)
    cx = pts[:, 0].astype(int) + P if n else np.zeros(0, int)
    cy = pts[:, 1].astype(int) + P if n else np.zeros(0, int)
    oy, ox = np.mgrid[-R:R + 1, -R:R + 1]
    oy2, ox2 = np.mgrid[-RIM_R:RIM_R + 1, -RIM_R:RIM_R + 1]

    def masks(ms):
        M = np.stack([m.ravel().astype(np.float32) for m in ms], 1)
        return M / M.sum(0)                                   # columns: averaging weights

    ring_w = masks(_RINGS)                                    # (1089, 8)
    ring_of = np.argmax(np.stack([m.ravel() for m in _RINGS], 1), 1)   # ring of each patch pixel (outside: unused)
    sect_w = masks(_SECT)
    reg_w = np.stack([(_rad < 8).ravel(), ((_rad >= 8) & (_rad <= R)).ravel()], 1).astype(np.float32)
    in5_w = masks([_rad < 5])
    wide_w = masks([_rad2 < 8] + _WIDE)
    all2_w = np.full(((2 * RIM_R + 1) ** 2, 1), 1.0 / (2 * RIM_R + 1) ** 2, np.float32)
    out = np.zeros((n, 1 + 8 * 8 + 3 + 2 * 9 + 81 + 3 + 1 + len(_WIDE) * 2 + 2), np.float32)
    for s in range(0, n, 512):                                # in chunks: ~512 x 1089 x 17 floats
        Y, X = cy[s:s + 512], cx[s:s + 512]
        k = len(Y)
        pat = planes[Y[:, None, None] + oy, X[:, None, None] + ox].reshape(k, -1, planes.shape[-1])   # (k, 1089, 17)
        r = np.einsum("kpc,pm->kmc", pat, ring_w)            # ring means per plane (k, 8, 17)
        Vr = r[..., 0]
        dev = (pat[..., 0] - Vr[:, ring_of]) ** 2             # two-pass spread (exact, no E[x^2]-E[x]^2 rounding)
        Vstd = np.sqrt(dev @ ring_w)
        ringf = np.stack([Vr, Vstd, r[..., 1], r[..., 2], r[..., 3], r[..., 4], r[..., 5], r[..., 6]], -1).reshape(k, -1)
        sv = pat[..., 0] @ sect_w                             # (k, 8)
        sectf = np.stack([sv.std(1), sv.min(1), sv.max(1)], 1)
        gradf = []
        for c in range(2):                                    # centre / outer region
            wsum = reg_w[:, c]
            hist = np.einsum("kpb,p->kb", pat[..., 9:17], wsum)
            msum = pat[..., 8] @ wsum
            gradf += [hist / (hist.sum(1, keepdims=True) + 1e-6), (msum / wsum.sum())[:, None]]
        thumbs = np.stack([cv2.resize(g[y - R:y + R + 1, x - R:x + R + 1], (9, 9), interpolation=cv2.INTER_AREA)
                           for y, x in zip(Y, X)]).astype(np.float32).reshape(k, -1)
        thumbs = (thumbs - thumbs.mean(1, keepdims=True)) / (thumbs.std(1, keepdims=True) + 1)
        wv = hsv[..., 2][Y[:, None, None] + oy2, X[:, None, None] + ox2].reshape(k, -1)
        wg = gold[Y[:, None, None] + oy2, X[:, None, None] + ox2].reshape(k, -1)
        wmean = (wv @ all2_w)[:, 0]
        wstd = wv.std(1)
        c5 = (pat[..., 0] @ in5_w)[:, 0]
        goldf = wg @ wide_w                                   # (k, 1 + len(_WIDE))
        vwide = wv @ wide_w[:, 1:]
        out[s:s + k] = np.hstack([dogv[s:s + k, None], ringf, sectf] + gradf +
                                 [thumbs, wmean[:, None], wstd[:, None], (c5 - wmean)[:, None], goldf, vwide,
                                  (pts[s:s + k, 0] / w)[:, None], (pts[s:s + k, 1] / h)[:, None]])
    return out


def candidate_labels(pts: np.ndarray, t: dict) -> np.ndarray:
    """truth -> NOT / MAP per candidate, -1 = leave out of training (near a map but not its centre,
    near a tower base, off-centre or behind-HUD maps, 'maybe' spots)"""
    lab = np.zeros(len(pts), int)
    towers = [l for l in t["landmarks"] if l["kind"] == "Tower"]
    good = [m for m in t["maps"] if not ({"offcenter", "ui"} & set(m["flags"]))]
    soft = [m for m in t["maps"] if {"offcenter", "ui"} & set(m["flags"])] + t["maybe"]
    for m in good:
        d = np.hypot(pts[:, 0] - m["x"], pts[:, 1] - m["y"])
        tower = any(np.hypot(l["x"] - m["x"], l["y"] - m["y"]) < 20 for l in towers)
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
    return [{"x": float(pts[i][0]), "y": float(pts[i][1]), "score": round(float(p[i]), 3)}
            for i in _keep_best(pts, p, MAP_MIN, MAP_MERGE)]


def find_maps(img: np.ndarray, model) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """-> maps, all candidates, their map probability (badge rows can still rescue a weak one)"""
    pts, dv = map_candidates(img)
    if not len(pts):
        return [], pts, np.zeros(0)
    prob = model.predict_proba(np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))]))
    return _nms(pts, prob), pts, prob[:, MAP]


# ---------------------------------------------------------------- stage 5
# Paths are amber dotted lines. Dashes: bright amber (R>145, G>95, R-G>32, G-B>35, B<145; user / GPT)
# or dimmer gold that is brighter than its surroundings (shadowed paths), or washed-out orange (Delirium
# fog), small dash-sized blobs only,
# HUD removed. Traced dash by dash between maps by the user's rules: gentle turns, a walk ends at the first
# map on its way (towers: wider), real dotted lines have regular dash spacing, paths never cross / fork /
# share a route (best walks kept first), and two dead ends meeting = a map the map finder missed. Path dashes around a spot are also map
# evidence: maps are where paths end or meet (user).
DASH_AREA, DASH_SIZE = (2, 60), 26


_PER_IMAGE: dict = {}       # (function, id(image)) -> (weak ref to the image, result)


def _per_image(fn):
    """remember fn(img) for the last few images: one detection asks for the same dashes / walls up to 3x
    (v1.03; results are made read-only so no caller can change the shared copy)"""
    import functools
    import weakref

    def _freeze(r):
        if isinstance(r, np.ndarray):
            r.flags.writeable = False
        elif isinstance(r, tuple):
            for x in r:
                _freeze(x)
        return r

    @functools.wraps(fn)
    def wrapper(img):
        key = (fn.__name__, id(img))
        hit = _PER_IMAGE.get(key)
        if hit is not None and hit[0]() is img:
            return hit[1]
        r = _freeze(fn(img))
        try:
            _PER_IMAGE[key] = (weakref.ref(img), r)
        except TypeError:
            return r
        while len(_PER_IMAGE) > 12:
            _PER_IMAGE.pop(next(iter(_PER_IMAGE)))
        return r
    return wrapper


@_per_image
def path_dashes(img: np.ndarray) -> np.ndarray:
    b, g, r = [img[..., i].astype(np.int16) for i in range(3)]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = [hsv[..., i].astype(np.int16) for i in range(3)]
    lift = cv2.morphologyEx(hsv[..., 2], cv2.MORPH_TOPHAT, np.ones((7, 7), np.uint8)).astype(np.int16)
    amber = (r > 145) & (g > 95) & (r - g > 32) & (g - b > 35) & (b < 145)
    dim = (H >= 8) & (H <= 30) & (S >= 110) & (V >= 55) & (lift >= 18)
    fog = (H >= 8) & (H <= 30) & (S >= 60) & (S < 110) & (V >= 110) & (lift >= 15)   # washed out by Delirium fog
    m = ((amber | dim | fog) & (core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH) == 0)).astype(np.uint8)
    _n, _l, st, cen = cv2.connectedComponentsWithStats(m, 8)
    ok = ((st[1:, 4] >= DASH_AREA[0]) & (st[1:, 4] <= DASH_AREA[1]) &
          (st[1:, 2] <= DASH_SIZE) & (st[1:, 3] <= DASH_SIZE))
    return cen[1:][ok].astype(float)


def path_features(pts, dashes: np.ndarray) -> np.ndarray:
    """dashes in rings around a spot, and in how many of 12 directions dashes leave it"""
    F = []
    for x, y in pts:
        v = dashes - (x, y) if len(dashes) else np.zeros((0, 2))
        d = np.hypot(v[:, 0], v[:, 1])
        f = [float(((d >= a) & (d < b)).sum()) for a, b in ((0, 10), (10, 20), (20, 32), (32, 48))]
        sel = (d >= 12) & (d < 45)
        sect = np.bincount(((np.arctan2(v[sel, 1], v[sel, 0]) + np.pi) / (2 * np.pi) * 12).astype(int) % 12,
                           minlength=12) if sel.any() else np.zeros(12)
        f += [float((sect > 0).sum()), float((sect >= 2).sum())]
        F.append(f)
    return np.asarray(F, np.float32).reshape(len(F), 6)


PATH_START = (9.0, 50.0)       # px from a map centre where its dotted lines may begin (badges and the ring often
                               # hide the first dashes: at 30 px, 20 of 34 user-marked missed lines never started)
PATH_STEP, PATH_JUMP = 22.0, 36.0  # next dash / bridged gap (dash spacing along a line ~8-11 px)
PATH_LAT = (3.5, 0.12)         # the next dash must lie within 3.5 px + 12% of the step of where the curve so far
                               # predicts it (gap jumps: 70% of that) - paths bend gently and steadily (user)
PATH_BEND_MAX = 1 / 90         # tightest bend: radius 90 px
PATH_BEND_SMOOTH = 0.5         # how fast the learned bend follows each step
PATH_MAX_ANG = 50.0            # never more than this off the predicted heading
PATH_ARRIVE, PATH_ARRIVE_TOWER = 18.0, 34.0   # a walk passing this close to a map ends there (first map on the way)
PATH_MAX_STEPS, PATH_MIN_DASHES, PATH_MAX_DETOUR = 120, 3, 1.8
PATH_SPACING = (5.0, 15.0)     # a real dotted line: most steps between neighbouring dashes are this long
PATH_REGULAR = 0.55            # ... at least this share of them (Vaal city lights are irregular)
PATH_LOOSE_DASHES = 6         # a walk this long that reaches no map: a map may be at its end
PATH_LOOSE_MEET = 25.0        # ... two such ends (from different maps) this close: a map there (user: paths show maps)
PATH_END_RESCUE = (0.02, 40)  # ... and a map candidate at least this likely within this many px of it (the
                              # meeting point is often a bit off the real map - user)
PATH_SINGLE_END_ON = False     # OFF: on the 10 labelled shots it added 42 maps, ~34 of them amber trees, tower
                              # flames / tops and lit structures that also end dotted-looking chains
PATH_SINGLE_END = (6, 30.0)   # ONE regular line of 6+ dashes running out in view, with a weak map candidate
                              # within 30 px past its end, is a map too (3 random shots: 8 of 10 such were
                              # maps the user circled)
PATH_SNAP = 40.0              # a line that runs out this close in front of a map ends AT that map (user: a
                              # dead end next to a map with paths is that map, not a second one)
PATH_MAX_DEGREE = 5           # paths per map (6 is never seen - user)
PATH_LEAVE_ANGLE = 18.0       # two paths never leave a map in the same direction (no forks / shared routes)
PATH_AHEAD = 30.0            # a dead end counts only if the image this far ahead of it is in view
PATH_MEET_MANY = 99          # 3+ dead ends meeting need no map score: OFF (20 labelled shots: +2 wrong maps, 0 right)
PATH_MEET_COS = 0.5          # two dead ends meeting come in from directions > 60 deg apart
PATH_SHARE = 2                 # dashes two paths may share (next to a common map)


def _walks_raw(nodes: list[dict], dashes: np.ndarray, loose: list | None = None) -> list[dict]:
    """every walk from every map along the dashes until it reaches another map; walks that follow a
    regular dotted line but reach no map are added to `loose` (their end point and direction).
    Each dash's neighbours are looked up once; each step only tests the maps near it."""
    N = np.array([[n["x"], n["y"]] for n in nodes], float)
    rad = np.array([PATH_ARRIVE_TOWER if n.get("tower") else PATH_ARRIVE for n in nodes])
    if len(dashes) == 0 or len(N) < 2:
        return []
    from scipy.spatial import cKDTree
    tree = cKDTree(dashes)
    mtree = cKDTree(N)
    rmax = float(rad.max())
    nbr = [np.array(x, int) for x in tree.query_ball_point(dashes, PATH_JUMP)]
    nvec = [dashes[k] - dashes[i] for i, k in enumerate(nbr)]
    nlen = [np.hypot(v[:, 0], v[:, 1]) for v in nvec]
    cos_max = np.cos(np.radians(PATH_MAX_ANG))
    in_walk = np.zeros(len(dashes), bool)
    out = []
    for a, A in enumerate(N):
        for s in tree.query_ball_point(A, PATH_START[1]):
            p = dashes[s]
            r0 = float(np.hypot(*(p - A)))
            if r0 < PATH_START[0]:
                continue
            d = (p - A) / r0
            used, line, steps, length = [s], [A.copy(), p.copy()], [], r0
            in_walk[s] = True
            cur = s                                  # p is dashes[cur]
            w = 0.0                                  # bend per px, learned along the walk
            end = None
            for _ in range(PATH_MAX_STEPS):
                best = None
                K, V, Ls = nbr[cur], nvec[cur], nlen[cur]
                free = ~in_walk[K] & (Ls >= 2)
                for R, tol in ((PATH_STEP, 1.0), (PATH_JUMP, 0.7)):
                    m = free & (Ls <= R)
                    if not m.any():
                        continue
                    k_, v_, L_ = K[m], V[m], Ls[m]
                    ang = w * L_ / 2                             # heading the curve predicts over each step
                    ca, sa = np.cos(ang), np.sin(ang)
                    ex, ey = d[0] * ca - d[1] * sa, d[0] * sa + d[1] * ca
                    fwd = v_[:, 0] * ex + v_[:, 1] * ey
                    lat = np.abs(ex * v_[:, 1] - ey * v_[:, 0])
                    ok = (fwd > 0) & (fwd >= L_ * cos_max) & (lat <= (PATH_LAT[0] + PATH_LAT[1] * L_) * tol)
                    if ok.any():
                        cost = np.where(ok, L_ + 3.0 * lat, np.inf)
                        j = int(np.argmin(cost))
                        best = (float(cost[j]), int(k_[j]), v_[j] / L_[j], float(L_[j]))
                        break
                q = dashes[best[1]] if best else p + d * PATH_STEP     # last stretch: towards a map just ahead
                # first map on the way: the segment p -> q passes a map's ring
                seg = q - p
                near = np.array(mtree.query_ball_point(p, float(np.hypot(*seg)) + rmax), int)
                near = near[near != a]
                if len(near):
                    Nn = N[near]
                    t = np.clip(((Nn - p) @ seg) / max(float(seg @ seg), 1e-9), 0, 1)
                    dist = np.hypot(*(p + t[:, None] * seg - Nn).T)
                    hit = np.nonzero(dist < rad[near])[0]
                    if len(hit):
                        b = int(near[hit[np.argmin(t[hit])]])
                        end = b
                        length += float(np.hypot(*(N[b] - p)))
                        break
                if best is None:
                    near = np.array(mtree.query_ball_point(p, PATH_SNAP), int)    # ran out just in front of a map
                    near = near[near != a]
                    if len(near):
                        dn = np.hypot(*(N[near] - p).T)
                        ahead = ((N[near] - p) @ d) > 0
                        cand = np.nonzero((dn <= PATH_SNAP) & ahead)[0]
                        if len(cand):
                            end = int(near[cand[np.argmin(dn[cand])]])
                            length += float(np.hypot(*(N[end] - p)))
                    break
                _, k, u, L = best
                turn = float(np.arctan2(d[0] * u[1] - d[1] * u[0], d @ u))  # heading change this step
                w = (1 - PATH_BEND_SMOOTH) * w + PATH_BEND_SMOOTH * float(np.clip(2 * turn / max(L, 1.0), -PATH_BEND_MAX, PATH_BEND_MAX))
                d = u.copy()
                p = dashes[k]
                cur = k
                used.append(k)
                in_walk[k] = True
                line.append(p.copy())
                steps.append(L)
                length += L
            in_walk[used] = False
            if end is None and loose is not None and len(used) >= PATH_LOOSE_DASHES:
                st = np.array(steps)
                if ((st >= PATH_SPACING[0]) & (st <= PATH_SPACING[1])).mean() >= PATH_REGULAR:
                    loose.append((p + d * 10.0, a, d.copy()))
            if end is None or len(used) < PATH_MIN_DASHES:
                continue
            straight = float(np.hypot(*(N[end] - A)))
            if straight < 25 or length > PATH_MAX_DETOUR * straight:
                continue
            st = np.array(steps) if steps else np.array([10.0])
            regular = float(((st >= PATH_SPACING[0]) & (st <= PATH_SPACING[1])).mean())
            if regular < PATH_REGULAR:
                continue
            out.append({"a": a, "b": end, "dashes": used, "line": line + [N[end].copy()],
                        "score": len(used) / max(1.0, straight / 10.0) * regular / (length / straight)})
    return out


def _cross(l1: np.ndarray, l2: np.ndarray) -> bool:
    """do two drawn lines cross (proper intersection of any segments)?"""
    if (l1.min(0) > l2.max(0)).any() or (l2.min(0) > l1.max(0)).any():
        return False
    p1, p2 = l1[:-1, None], l1[1:, None]
    q1, q2 = l2[None, :-1], l2[None, 1:]
    def side(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    return bool(((side(p1, p2, q1) * side(p1, p2, q2) < 0) & (side(q1, q2, p1) * side(q1, q2, p2) < 0)).any())


def maps_from_paths(nodes: list[dict], dashes: np.ndarray, img: np.ndarray, map_pts: np.ndarray,
                    map_p: np.ndarray, rounds: int = 3) -> list[dict]:
    """maps the map finder missed: where dotted lines from two different maps both run out, there is a
    map (paths never cross or fork - user). A line that runs into the HUD, the screen edge or black fog
    has not ended, it is only out of view: such ends do not count, and two lines must come in from
    clearly different directions. Our walks also stop where a few dashes go undetected, so the map
    finder must have seen a (weak) map candidate at the meeting point too. Repeated: a new map can open
    more lines."""
    valid = core._valid_mask(img)
    h, w = valid.shape

    def in_view(p, d):
        q = p + d * PATH_AHEAD
        x, y = int(round(q[0])), int(round(q[1]))
        return 0 <= x < w and 0 <= y < h and valid[y, x] > 0

    found: list[dict] = []
    for _ in range(rounds):
        loose = [(p, a, d) for p, a, d in (lambda L: (_walks(nodes + found, dashes, L), L)[1])([]) if in_view(p, d)]
        new: list[dict] = []
        for p, a, d in loose:
            mates = [q for q, b, e in loose if b != a and np.hypot(*(q - p)) <= PATH_LOOSE_MEET
                     and float(d @ e) < PATH_MEET_COS]
            if not mates and not PATH_SINGLE_END_ON:
                continue
            c = np.mean([p] + mates, 0) if mates else p + d * 10.0   # one line alone: the map is just past its end
            if any(np.hypot(c[0] - n["x"], c[1] - n["y"]) < 30 for n in nodes + found + new):
                continue
            dd = np.hypot(map_pts[:, 0] - c[0], map_pts[:, 1] - c[1]) if len(map_pts) else np.zeros(0)
            reach = PATH_END_RESCUE[1] if mates else PATH_SINGLE_END[1]
            # 3+ lines from different maps running out at one spot: a map, however unlit its base (user's
            # grey bases the map model rates ~0); the nearest candidate (any score) places it
            many = len({b for q, b, e in loose if b != a and np.hypot(*(q - p)) <= PATH_LOOSE_MEET
                        and float(d @ e) < PATH_MEET_COS}) >= PATH_MEET_MANY - 1
            floor = 0.0 if many else PATH_END_RESCUE[0]
            ok = (dd <= reach) & (map_p >= floor) if len(dd) else dd.astype(bool)
            if not ok.any():
                if not many:
                    continue
                x, y = float(c[0]), float(c[1])
                if any(np.hypot(x - n["x"], y - n["y"]) < 30 for n in nodes + found + new):
                    continue
                new.append({"x": x, "y": y, "score": 0.0, "source": "path ends"})
                continue
            j = int(np.argmax(np.where(ok, map_p, -1)))
            x, y = float(map_pts[j][0]), float(map_pts[j][1])
            if any(np.hypot(x - n["x"], y - n["y"]) < 30 for n in nodes + found + new):
                continue                       # several meeting points snapped to the same map: add it once
            new.append({"x": x, "y": y, "score": round(float(map_p[j]), 3), "source": "path ends"})
        if not new:
            break
        found += new
    return found


def _no_diamond_shortcuts(kept: list[dict], nodes: list[dict]) -> list[dict]:
    """the old diamond rule: a path a-b is a shortcut across a diamond when maps on BOTH sides of it are
    joined to both a and b by kept paths; the four sides are the real paths"""
    N = np.array([[n["x"], n["y"]] for n in nodes], float)
    adj: dict = {}
    for w in kept:
        adj.setdefault(w["a"], set()).add(w["b"])
        adj.setdefault(w["b"], set()).add(w["a"])
    out = []
    for w in kept:
        a, b = w["a"], w["b"]
        axis = N[b] - N[a]
        length = float(np.hypot(*axis))
        sides = set()
        for k in (adj.get(a, set()) & adj.get(b, set())) - {a, b}:
            cross = float(axis[0] * (N[k][1] - N[a][1]) - axis[1] * (N[k][0] - N[a][0]))
            if abs(cross) >= length * 16:
                sides.add(cross > 0)
        if len(sides) < 2:
            out.append(w)
    return out


def walk_paths(nodes: list[dict], dashes: np.ndarray) -> list[dict]:
    """paths between the maps (hidden ones too): {a, b (node indices), conf, status, dashes, line}.
    Walks along the dashes, then keeps the best walks first; a walk that crosses a kept path, reuses its
    dashes, joins two maps already joined, leaves a map in the same direction as a kept path, or gives a
    map more than 5 paths is dropped (paths never cross, fork or share a route - user); then the diamond
    rule."""
    walks = sorted(_walks(nodes, dashes), key=lambda w: -w["score"])
    kept, owner, pairs = [], {}, set()
    degree: dict = {}
    leave: dict = {}                                            # map -> directions its kept paths leave in

    def leaving(line, at_start):
        L = np.asarray(line, float)
        L = L if at_start else L[::-1]
        far = next((q for q in L[1:] if np.hypot(*(q - L[0])) >= 25), L[-1])
        v = far - L[0]
        return v / max(1e-6, float(np.hypot(*v)))

    cos_leave = np.cos(np.radians(PATH_LEAVE_ANGLE))
    for w in walks:
        key = (min(w["a"], w["b"]), max(w["a"], w["b"]))
        if key in pairs:
            continue
        if degree.get(w["a"], 0) >= PATH_MAX_DEGREE or degree.get(w["b"], 0) >= PATH_MAX_DEGREE:
            continue
        da, db = leaving(w["line"], True), leaving(w["line"], False)
        if any(float(da @ u) > cos_leave for u in leave.get(w["a"], [])) or                 any(float(db @ u) > cos_leave for u in leave.get(w["b"], [])):
            continue
        if sum(1 for k in w["dashes"] if k in owner) > PATH_SHARE:
            continue
        L = np.array(w["line"], float)
        inner = L[2:-2] if len(L) > 5 else L                 # ends meet at maps: only the middle may not cross
        if any(_cross(inner, np.array(o["line"], float)) for o in kept):
            continue
        kept.append(w)
        pairs.add(key)
        degree[w["a"]] = degree.get(w["a"], 0) + 1
        degree[w["b"]] = degree.get(w["b"], 0) + 1
        leave.setdefault(w["a"], []).append(da)
        leave.setdefault(w["b"], []).append(db)
        for k in w["dashes"]:
            owner[k] = len(kept)
    kept = _no_diamond_shortcuts(kept, nodes)
    return [{"a": int(min(w["a"], w["b"])), "b": int(max(w["a"], w["b"])),
             "conf": round(min(1.0, len(w["dashes"]) / 10), 3), "status": "traced", "dashes": len(w["dashes"]),
             "line": [[round(float(x), 1), round(float(y), 1)] for x, y in (w["line"] if w["a"] < w["b"] else w["line"][::-1])]}
            for w in kept]


# Paths from the strict amber mask (user / GPT filter: every dotted line in it is a real path). Each dash is a
# short stroke pointing along its path; trees, flames and rings are blobs that point nowhere. Dashes link to
# the next dash along their own direction into chains, chains are joined across a missed dash or two, cut where
# they pass through a map, and each piece between two maps is a path. The walk above only fills in pairs the
# chains missed, and only when its drawn line runs on the dots. On all user marks + amber lines (7 shots):
# dotted lines covered 74% -> 83%, drawn paths on dots 61% -> 78%, drifting lines drawn right 32% -> 94%.
CHAIN = {"area": (3, 60), "len": (3.0, 16.0), "elong": 1.6, "gap": (4.0, 30.0), "ang": 25.0, "side": 4.0,
         "stitch": 45.0, "stitch_ang": 30.0, "map_r": 70.0, "map_ang": 40.0, "through": 24.0, "min_dashes": 3}
WALK_FILL_ON_DOTS = 0.6        # a walk path fills in only if this share of its drawn line is on amber dashes


@_per_image
def amber_dashes(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """strict amber filter -> dash strokes: centres and unit directions"""
    b, g, r = [img[..., i].astype(np.int16) for i in range(3)]
    m = ((r > 145) & (g > 95) & (r - g > 32) & (g - b > 35) & (b < 145)).astype(np.uint8)
    m[core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH) > 0] = 0
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    C, U = [], []
    for k in range(1, n):
        if not (CHAIN["area"][0] <= st[k, 4] <= CHAIN["area"][1]):
            continue
        ys, xs = np.nonzero(lab[st[k, 1]:st[k, 1] + st[k, 3], st[k, 0]:st[k, 0] + st[k, 2]] == k)
        pts = np.stack([xs, ys], 1).astype(float)
        if len(pts) < 3:
            continue
        ev, evec = np.linalg.eigh(np.cov((pts - pts.mean(0)).T) + np.eye(2) * 0.08)
        if np.sqrt(ev[1] / ev[0]) < CHAIN["elong"] or not (CHAIN["len"][0] <= 4 * np.sqrt(ev[1]) <= CHAIN["len"][1]):
            continue
        C.append(cen[k])
        U.append(evec[:, 1])
    return np.array(C, float).reshape(-1, 2), np.array(U, float).reshape(-1, 2)


def _dash_links(C: np.ndarray, U: np.ndarray) -> set:
    """each dash links to its best neighbour ahead and behind along its own direction; mutual links kept"""
    from scipy.spatial import cKDTree
    if len(C) < 2:
        return set()
    T = cKDTree(C)
    ca = np.cos(np.radians(CHAIN["ang"]))
    best = {}
    for i in range(len(C)):
        for side in (1, -1):
            u = U[i] * side
            cand = []
            for j in T.query_ball_point(C[i], CHAIN["gap"][1]):
                v = C[j] - C[i]
                d = float(np.hypot(*v))
                if j == i or d < CHAIN["gap"][0]:
                    continue
                along = float(v @ u)
                lat = abs(u[0] * v[1] - u[1] * v[0])
                if along <= 0 or along / d < ca or lat > CHAIN["side"] + 0.12 * d or abs(float(U[j] @ U[i])) < ca:
                    continue
                cand.append((d + 3 * lat, j))
            if cand:
                best[(i, side)] = min(cand)[1]
    return {(min(i, j), max(i, j)) for (i, _s), j in best.items() if i in (best.get((j, 1)), best.get((j, -1)))}


def _chain_end(pts: np.ndarray, first: bool) -> tuple[np.ndarray, np.ndarray]:
    e, inn = (pts[0], pts[min(3, len(pts) - 1)]) if first else (pts[-1], pts[max(-4, -len(pts))])
    o = e - inn
    return e, o / max(1e-6, float(np.hypot(*o)))


def dash_chains(C: np.ndarray, U: np.ndarray) -> list[list[int]]:
    """linked dashes as chains; chain ends that line up across a short gap are joined, closest pair first
    (a heap of candidate end pairs, refreshed only for the chain that just changed)"""
    import heapq
    from scipy.spatial import cKDTree
    adj: dict = {}
    for i, j in _dash_links(C, U):
        adj.setdefault(i, []).append(j)
        adj.setdefault(j, []).append(i)
    seen: set = set()
    chs: list[list[int]] = []
    starts = [k for k in adj if len(adj[k]) != 2] + list(adj)      # open chains first, then closed loops
    for s0 in starts:
        if s0 in seen:
            continue
        ch, prev, cur = [s0], None, s0
        seen.add(s0)
        while True:
            nx = [k for k in adj[cur] if k != prev and k not in seen]
            if not nx:
                break
            prev, cur = cur, nx[0]
            ch.append(cur)
            seen.add(cur)
        chs.append(ch)
    ca = np.cos(np.radians(CHAIN["stitch_ang"]))
    alive = {cid: c for cid, c in enumerate(chs)}
    order = {cid: cid for cid in alive}                # position in the list (for the final order)
    ends: dict = {}                                    # (cid, first) -> (dash index, outward dir)
    for cid, c in alive.items():
        if len(c) >= 2:
            for f in (True, False):
                ends[(cid, f)] = (c[0] if f else c[-1], _chain_end(C[c], f)[1])
    tree = cKDTree(C) if len(C) else None
    end_at: dict = {}                                  # dash index -> end key (an end sits on a dash)
    for k, (di, _o) in ends.items():
        end_at.setdefault(di, set()).add(k)
    heap: list = []

    def push_for(k):
        di, o1 = ends[k]
        for dj in tree.query_ball_point(C[di], CHAIN["stitch"]):
            for k2 in end_at.get(dj, ()):
                if k2 == k or k2[0] == k[0] or k2 not in ends:
                    continue
                v = C[dj] - C[di]
                d = float(np.hypot(*v))
                o2 = ends[k2][1]
                if d < 1 or float(v @ o1) / d < ca or float(-v @ o2) / d < ca:
                    continue
                heapq.heappush(heap, (d, min(order[k[0]], order[k2[0]]), k, k2))

    for k in list(ends):
        push_for(k)
    nxt = len(chs)
    while heap:
        _d, _o, k1, k2 = heapq.heappop(heap)
        if k1 not in ends or k2 not in ends:
            continue                                   # one of the ends was used / changed since
        (i, fi), (j, fj) = k1, k2
        a = alive.pop(i)
        b = alive.pop(j)
        merged = (a[::-1] if fi else a) + (b if fj else b[::-1])
        for k in ((i, True), (i, False), (j, True), (j, False)):
            if k in ends:
                end_at[ends[k][0]].discard(k)
                del ends[k]
        cid = nxt
        nxt += 1
        alive[cid] = merged
        order[cid] = min(order[i], order[j])
        for f in (True, False):
            k = (cid, f)
            ends[k] = (merged[0] if f else merged[-1], _chain_end(C[merged], f)[1])
            end_at.setdefault(ends[k][0], set()).add(k)
        for f in (True, False):
            push_for((cid, f))
    return [alive[c] for c in sorted(alive, key=lambda c: order[c])]


def chain_paths(nodes: list[dict], C: np.ndarray, U: np.ndarray) -> list[dict]:
    """dash chains cut where they pass through a map; each piece between two maps is a path"""
    N = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
    if not len(N) or not len(C):
        return []
    cm = np.cos(np.radians(CHAIN["map_ang"]))

    def attach(e, o):
        v = N - e
        d = np.hypot(*v.T)
        ok = np.nonzero((d <= 12) | ((d <= CHAIN["map_r"]) & ((v @ o) / np.maximum(d, 1e-6) >= cm)))[0]
        return int(ok[np.argmin(d[ok])]) if len(ok) else None

    best: dict = {}
    for ch in dash_chains(C, U):
        pts = C[ch]
        pieces, cur, start = [], [0], None
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            ab = b - a
            t = np.clip(((N - a) @ ab) / max(float(ab @ ab), 1e-9), 0, 1)
            d = np.hypot(*(a + t[:, None] * ab - N).T)
            m = int(np.argmin(d))
            if d[m] <= CHAIN["through"]:
                pieces.append((start, cur, m))
                start, cur = m, [k + 1]
            else:
                cur.append(k + 1)
        pieces.append((start, cur, None))
        for sa, idx, sb in pieces:
            q = pts[idx]
            if len(idx) < CHAIN["min_dashes"] and (sa is None or sb is None):
                continue
            if sa is None and len(q) >= 2:
                sa = attach(*_chain_end(q, True))
            if sb is None and len(q) >= 2:
                sb = attach(*_chain_end(q, False))
            if sa is None or sb is None or sa == sb:
                continue
            line = [N[sa].tolist()] + q.tolist() + [N[sb].tolist()]
            key = (min(sa, sb), max(sa, sb))
            if sa > sb:
                line = line[::-1]
            if key not in best or len(idx) > best[key]["dashes"]:
                best[key] = {"a": key[0], "b": key[1], "conf": round(min(1.0, len(idx) / 10), 3), "status": "chain",
                             "dashes": len(idx), "line": [[round(float(x), 1), round(float(y), 1)] for x, y in line]}
    return list(best.values())


def _on_dots(line, tree) -> float:
    L = np.asarray(line, float)[1:-1]
    if len(L) < 2:
        return 0.0
    P = np.concatenate([a + (b - a) * np.linspace(0, 1, max(1, int(np.hypot(*(b - a)) // 4)), endpoint=False)[:, None]
                        for a, b in zip(L[:-1], L[1:])])
    return float((tree.query(P)[0] <= 8).mean())


def trace_paths(nodes: list[dict], dashes: np.ndarray, img: np.ndarray | None = None,
                amber: tuple | None = None) -> list[dict]:
    """paths between the maps: amber dash chains first, then walk paths for pairs they missed that run on
    the dots and cross nothing (no map gets more than PATH_MAX_DEGREE). `amber` = amber_dashes(img), if known."""
    if img is None and amber is None:
        return walk_paths(nodes, dashes)
    from scipy.spatial import cKDTree
    C, U = amber if amber is not None else amber_dashes(img)
    out = chain_paths(nodes, C, U)
    if not len(C):
        return out + walk_paths(nodes, dashes)
    tree = cKDTree(np.vstack([C, dashes]) if len(dashes) else C)   # dim / fog dashes count as dots here
    pairs = {(e["a"], e["b"]) for e in out}
    deg: dict = {}
    for e in out:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    for w in walk_paths(nodes, dashes):
        k = (w["a"], w["b"])
        if k in pairs or deg.get(k[0], 0) >= PATH_MAX_DEGREE or deg.get(k[1], 0) >= PATH_MAX_DEGREE:
            continue
        if _on_dots(w["line"], tree) < WALK_FILL_ON_DOTS:
            continue
        L = np.array(w["line"], float)
        if any(_cross(L[2:-2] if len(L) > 5 else L, np.array(o["line"], float)) for o in out):
            continue
        out.append(w)
        pairs.add(k)
        deg[k[0]] = deg.get(k[0], 0) + 1
        deg[k[1]] = deg.get(k[1], 0) + 1
    return out


SEEN_CELL = 40              # px: cell of the "clearly visible" grid saved with a detection
WALL_CELL = 16              # px: cell of the fortress-wall grid saved with a detection
WALL_STEP, WALL_SCALES = 8, (9, 25, 61)
WALL_MIN_AREA, WALL_MIN_LEN, WALL_CORNERS = 12000, 200, 1.3
WALL_CROSS = 0.15           # a path whose middle runs this much over fortress wall goes through it: not real
FORTRESS_PAINT = TESTS / "fortress_paint"   # user-painted walls: <k>.png alpha masks over paint_<k>.png


def wall_features(img: np.ndarray) -> np.ndarray:
    """per WALL_STEP px point: colour / rust-rib / dark-stone / gradient-direction densities at three scales"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k1 = np.array([[0, 1, 2], [-1, 0, 1], [-2, -1, 0]], np.float32)
    base = {"V": V, "S": S, "Hs": np.sin(H / 90 * np.pi), "Hc": np.cos(H / 90 * np.pi),
            "rust": (((H <= 16) | (H >= 175)) & (S >= 70) & (V >= 40)).astype(np.float32),
            "dark": ((S < 70) & (V >= 15) & (V < 90)).astype(np.float32),
            "green": ((H >= 30) & (H <= 90) & (S >= 60)).astype(np.float32),
            "blue": ((H >= 90) & (H <= 130) & (S >= 60)).astype(np.float32),
            "gx": np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)), "gy": np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)),
            "gd1": np.abs(cv2.filter2D(g, cv2.CV_32F, k1)), "gd2": np.abs(cv2.filter2D(g, cv2.CV_32F, k1[:, ::-1]))}
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
    m = ((cv2.blur(rust.astype(np.float32), (25, 25)) > 0.14) & (cv2.blur(dark.astype(np.float32), (25, 25)) > 0.15))
    m = m.astype(np.float32)
    return _wall_clean(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)), img)


def cmd_train_fortress() -> int:
    """py atlas_detect.py train_fortress   (user-painted walls + non-fortress shots as negatives)"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    import glob
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
    pool = sorted(glob.glob(str(S_ / "random_samples" / "*.png")))[1::4] +         sorted(glob.glob(str(S_ / "crawl" / "*.png")))[60::12] + sorted(glob.glob(str(S_ / "ocean" / "*.png")))[::10]
    for p in pool:
        img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        if _lit_walls(img).any():
            continue
        hud = (core.hud_mask(img.shape[1], img.shape[0]) > 0)[o::st, o::st]
        F = wall_features(img)
        X.append(F[~hud])
        y.append(np.zeros(int((~hud).sum()), bool))
    m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.1, random_state=0).fit(np.vstack(X), np.concatenate(y))
    save_model("fortress", m, {"painted": npaint, "negatives": len(X) - npaint})
    print(f"fortress wall model: {npaint} painted shots + {len(X) - npaint} non-fortress shots -> {DB_PATH.name}")
    return 0


def dash_record(img: np.ndarray) -> dict:
    """what the atlas-wide path check needs from a screenshot, saved with its detection so the check never
    re-reads or re-traces the image: every path dash (amber strokes + dim / fog dashes, screen px) and a
    coarse grid of where the atlas is clearly visible (not dark fog, not HUD) - there an empty stretch along
    a path really means "no path"; elsewhere it means nothing (user)"""
    dim = path_dashes(img)
    C, _U = amber_dashes(img)
    pts = np.vstack([np.asarray(C, float).reshape(-1, 2), np.asarray(dim, float).reshape(-1, 2)])
    h, w = img.shape[:2]
    ok = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) >= 30) & (core._valid_mask(img) > 0)
    gh, gw = (h + SEEN_CELL - 1) // SEEN_CELL, (w + SEEN_CELL - 1) // SEEN_CELL
    pad = np.zeros((gh * SEEN_CELL, gw * SEEN_CELL), bool)
    pad[:h, :w] = ok
    grid = pad.reshape(gh, SEEN_CELL, gw, SEEN_CELL).mean(axis=(1, 3)) >= 0.6
    wall = fortress_walls(img)
    wh, ww = (h + WALL_CELL - 1) // WALL_CELL, (w + WALL_CELL - 1) // WALL_CELL
    wp = np.zeros((wh * WALL_CELL, ww * WALL_CELL), np.float32)
    wp[:h, :w] = wall
    wg = wp.reshape(wh, WALL_CELL, ww, WALL_CELL).mean(axis=(1, 3)) >= 0.5
    return {"dash_pts": np.round(pts).astype(int).tolist(),
            "amber_pts": np.round(np.asarray(C, float).reshape(-1, 2)).astype(int).tolist(),
            "seen_grid": ["".join("1" if v else "0" for v in row) for row in grid],
            "wall_grid": ["".join("1" if v else "0" for v in row) for row in wg]}


def screen_paths(img_dashes: tuple, pts: np.ndarray, ok: np.ndarray, tower: np.ndarray | None = None) -> dict:
    """for the builder's atlas-wide check: paths between given map positions (screen px) of one screenshot,
    using only the maps inside it (ok). img_dashes = (path_dashes(img), amber_dashes(img)).
    -> {(i, j): {"dashes", "from", "line", "detour"}}, i < j indices into pts (the atlas_trace format)"""
    dashes, amber = img_dashes
    vis = np.nonzero(ok)[0]
    nodes = [{"x": float(pts[i][0]), "y": float(pts[i][1]), "tower": bool(tower[i]) if tower is not None else False}
             for i in vis]
    out = {}
    for e in trace_paths(nodes, dashes, amber=amber):
        i, j = int(vis[e["a"]]), int(vis[e["b"]])
        L = np.asarray(e["line"], float)
        straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
        length = float(np.hypot(*np.diff(L, axis=0).T).sum())
        out[(min(i, j), max(i, j))] = {"dashes": int(e["dashes"]), "line": (L if i < j else L[::-1]).tolist(),
                                       "detour": length / straight,
                                       "from": {i, j} if e.get("status") == "chain" else {i}}
    return out


_WALK_MEMO: dict = {}


def _walks(nodes: list[dict], dashes: np.ndarray, loose: list | None = None) -> list[dict]:
    """_walks_raw, remembered for the last maps + dashes: tracing repeats the dead-end search's last round"""
    key = (len(dashes), float(dashes.sum()) if len(dashes) else 0.0,
           tuple((round(n["x"], 2), round(n["y"], 2), bool(n.get("tower"))) for n in nodes))
    if _WALK_MEMO.get("key") != key:
        lo: list = []
        _WALK_MEMO.clear()
        _WALK_MEMO.update(key=key, out=_walks_raw(nodes, dashes, lo), loose=lo)
    if loose is not None:
        loose.extend(_WALK_MEMO["loose"])
    return _WALK_MEMO["out"]


# ---------------------------------------------------------------- stage 3
RING_MIN = 25              # gold-ring filter at the rim radius (10.5 px)
TEMPLATE_MIN = 0.90        # or: correlation with the average stored badge (catches white badges on bright ground)
BADGE_MIN = 0.5            # badge probability
BADGE_ROW_MIN = 0.1        # ... enough when the spot fits a row: next to a badge, or a row slot above a map
BADGE_NMS = 18
HIDDEN_SNAP = 45.0         # no hidden map for a badge row with a visible map this close under it
ROW_RESCUE = (0.02, 14)    # a badge row with no map under it: take a map candidate this likely within this
                           # many px (on the 10 samples: +29 maps right, +5 wrong); else it is a hidden map
ROW_DY, ROW_STEP = 24, 36  # row 24 px above the map base, badges 36 px apart, centred on the map


def _ring_kernel(r0: float, r1: float, R: int = 15) -> np.ndarray:
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    k = ((np.hypot(xx, yy) >= r0) & (np.hypot(xx, yy) < r1)).astype(np.float32)
    return k / k.sum()


_K_RIM, _K_IN, _K_OUT = _ring_kernel(9.5, 11.5), _ring_kernel(7, 9), _ring_kernel(12.5, 14.5)
_badge_tpl: dict = {}


def _template() -> tuple[np.ndarray, np.ndarray]:
    """average stored badge (grey) and its rim mask"""
    if not _badge_tpl:
        g = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) for _n, im in icon_refs.load()
             if im.shape[:2] == (icon_refs.SIZE, icon_refs.SIZE)]
        yy, xx = np.mgrid[:icon_refs.SIZE, :icon_refs.SIZE]
        r = np.hypot(xx - icon_refs.SIZE / 2 + .5, yy - icon_refs.SIZE / 2 + .5)
        _badge_tpl["t"] = np.mean(g, 0).astype(np.float32)
        _badge_tpl["m"] = ((r >= 8.5) & (r <= 13.5)).astype(np.float32)
    return _badge_tpl["t"], _badge_tpl["m"]


def badge_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> points, ring score, extra features (ring score, template score, best stored-badge correlation)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    v = hsv[..., 2]
    gold = (((hsv[..., 0] >= 10) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 60)) * 1.0).astype(np.float32)
    ring = (cv2.filter2D(v, -1, _K_RIM) - 0.5 * (cv2.filter2D(v, -1, _K_IN) + cv2.filter2D(v, -1, _K_OUT))
            + 40 * cv2.filter2D(gold, -1, _K_RIM))
    tpl, msk = _template()
    tm = np.nan_to_num(cv2.matchTemplate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), tpl,
                                         cv2.TM_CCORR_NORMED, mask=msk))
    o = icon_refs.SIZE // 2
    ncc = np.zeros_like(v)
    ncc[o:o + tm.shape[0], o:o + tm.shape[1]] = tm
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
        idx = np.nonzero(ok[s0:s0 + 2048])[0] + s0
        if not len(idx):
            continue
        v = blur[(Y[idx] - r)[:, None] + my, (X[idx] - r)[:, None] + mx].astype(np.float32)   # (k, npix, 3)
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


def _keep_best(pts: np.ndarray, p: np.ndarray, thr: float, r: float) -> list[int]:
    """indices of the most likely points (p >= thr), best first, dropping any within r of a kept one"""
    keep: list[int] = []
    for i in np.argsort(-p):
        if p[i] < thr:
            break
        if all(np.hypot(*(pts[i] - pts[k])) > r for k in keep):
            keep.append(i)
    return keep


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
            d = np.minimum(d, 1 - F @ icon_refs.feature(big[dy:dy + icon_refs.SIZE, dx:dx + icon_refs.SIZE]))
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


def badges_from(img: np.ndarray, pts: np.ndarray, p: np.ndarray, book: dict, maps: list[dict],
                map_pts: np.ndarray, map_p: np.ndarray) -> tuple[list, list]:
    """badge probabilities -> named badges + more maps: under a badge row with no map found, the best weak
    map candidate (source 'badge row'), or else a hidden map"""
    icons = [{"x": float(pts[i][0]), "y": float(pts[i][1]), "score": round(float(p[i]), 3)}
             for i in _keep_best(pts, p, BADGE_MIN, BADGE_NMS)]
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
        cx = (row[0]["x"] + row[-1]["x"]) / 2          # the map sits under the row's middle (user)
        cy = float(np.mean([b["y"] for b in row])) + ROW_DY
        if any(np.hypot(cx - m["x"], cy - m["y"]) <= MAP_NMS for m in maps + more):
            continue
        d = np.hypot(map_pts[:, 0] - cx, map_pts[:, 1] - cy) if len(map_pts) else np.zeros(0)
        ok = (d <= ROW_RESCUE[1]) & (map_p >= ROW_RESCUE[0]) if len(d) else d.astype(bool)
        if ok.any():
            j = int(np.argmax(np.where(ok, map_p, -1)))
            more.append({"x": float(map_pts[j][0]), "y": float(map_pts[j][1]), "score": round(float(map_p[j]), 3),
                         "source": "badge row"})
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


def find_badges(img: np.ndarray, model: dict, maps: list[dict], map_pts: np.ndarray,
                map_p: np.ndarray) -> tuple[list, list]:
    pts, ring, extra = badge_candidates(img)
    if not len(pts):
        return [], []
    p = model["clf"].predict_proba(badge_features(img, pts, ring, extra))[:, 1]
    return badges_from(img, pts, p, model, maps, map_pts, map_p)


# ---------------------------------------------------------------- stage 4
# Towers: tall dark spires ~50 px wide and up to ~200 px high standing on their map (the base), green
# glow at the foot, a flame on top while active. Tower vs map: classifier on found maps (tall window
# above the map + the old hand-made tower rules as one more feature; 20 labelled towers so far).
TOWER_MIN = 0.9          # 10 samples: 15 right, 1 wrong, 5 missed (old detector 12 / 1 / 8)
TOWER_NMS = 45           # a tower base is wide: other "maps" this close are the same tower
TOWER_BADGES = (45, 100, 230)  # a badge row this close sideways and 100-230 px above a tower is the tower's
# Deadly Map Boss badge -> its map (under the row's middle) is a City / Hall / plain deadly boss (user rules,
# thresholds from the 14 labelled ones: 13 right)
CITY_BLUE = 150            # blue beam pixels (column above the map, or +-80 px) -> City
HALL_ORANGE = 700          # orange beam pixels within +-80 px (the beam on the Hall's structure)
RED_CITY = 200             # some orange right above the map itself: a City with a red beam
STRONGHOLD_EMPTY = 120     # a Breach stronghold with no map found this close is locked (only ground shows)
_TP = 220


def tower_features(img: np.ndarray, pts, old_towers: list) -> np.ndarray:
    """per map: brightness / colour / vertical edges / green glow / flame in a grid of boxes up to 200 px
    above it, the width of the green glow at its foot, a dark-column profile, and whether the old tower
    rules found a tower there"""
    big = cv2.copyMakeBorder(img, _TP, _TP, _TP, _TP, cv2.BORDER_REFLECT)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV).astype(np.float32)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx, gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0)), np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((H >= 40) & (H <= 85) & (S > 90) & (V > 120)).astype(np.float32)
    flame = (((H <= 22) | (H >= 170)) & (S > 120) & (V > 170)).astype(np.float32)
    F = []
    for x, y in pts:
        X, Y = int(x) + _TP, int(y) + _TP
        f = []
        for y0, y1 in ((-200, -150), (-150, -100), (-100, -60), (-60, -25), (-25, 12)):
            for x0, x1 in ((-30, -12), (-12, 12), (12, 30)):
                sl = (slice(Y + y0, Y + y1), slice(X + x0, X + x1))
                f += [V[sl].mean(), S[sl].mean(), gx[sl].mean() / (gy[sl].mean() + 1), green[sl].mean(), flame[sl].mean()]
        for a, b in ((0, 12), (12, 24), (24, 36), (36, 50)):
            f.append(np.concatenate([green[Y - 12:Y + 10, X - b:X - a].ravel(), green[Y - 12:Y + 10, X + a:X + b].ravel()]).mean())
        col = V[Y - 160:Y - 20, X - 40:X + 41].mean(0)
        f += [col[30:51].mean() - np.r_[col[:15], col[-15:]].mean(), col.std()]
        f.append(float(any(np.hypot(t[0] - x, t[1] - y) < 45 for t in old_towers)))
        F.append(f)
    return np.asarray(F, np.float32).reshape(len(F), -1)


def old_landmarks(img: np.ndarray) -> dict:
    """the hand-made landmark rules (atlas_towers): towers and purple Breach strongholds"""
    import atlas_towers as poi
    lms = poi.detect_landmarks(img)
    return {"towers": [(l.x, l.y) for l in lms if l.kind == "Tower"],
            "strongholds": [(l.x, l.y) for l in lms if l.kind == "Breach stronghold"]}


def tower_labels(pts, t: dict) -> np.ndarray:
    towers = [l for l in t["landmarks"] if l["kind"] == "Tower"]
    return np.array([int(any(np.hypot(l["x"] - x, l["y"] - y) < 25 for l in towers)) for x, y in pts], int)


def deadly_kind(img: np.ndarray, x: float, y: float) -> tuple[str, str]:
    """the map at (x, y) carries a Deadly Map Boss badge: City / Hall / plain deadly boss, and why"""
    import atlas_finalize as fin
    blue, orange = fin._beam(img, x, y)
    sblue, sorange = fin._beam(img, x, y, spread=80)
    if fin._ocean(img, x, y):                       # ocean (Expedition) biome: never a City (user's rule)
        if sorange >= HALL_ORANGE:
            return "Hall", "beam on a structure next to it (ocean)"
        return "Deadly boss map", "ocean biome: no cities"
    if fin._barrel(img, x, y, max(blue, sblue) >= fin.BARREL_LIT):
        return "City", "brass barrel map base"
    if max(blue, sblue) >= CITY_BLUE:
        return "City", "blue beam"
    if sorange >= HALL_ORANGE:
        return "Hall", "beam on a structure next to it"
    if orange >= RED_CITY:
        return "City", "red beam right above the map"
    return "Deadly boss map", "no beam"


def landmarks_from(img: np.ndarray, nodes: list[dict], icons: list[dict], tower_p: np.ndarray,
                   old: dict) -> tuple[list[dict], list[dict]]:
    """-> landmarks, nodes (towers marked; hidden maps that were really a tower's badge row removed)"""
    out = []
    nodes = [dict(n) for n in nodes]
    vis = [n for n in nodes if not n.get("hidden")]
    gone = set()
    for k in np.argsort(-np.asarray(tower_p, float)):
        n = vis[k]
        if tower_p[k] < TOWER_MIN:
            break
        if id(n) in gone:
            continue
        n["tower"] = True
        out.append({"kind": "Tower", "x": n["x"], "y": n["y"], "score": round(float(tower_p[k]), 3)})
        gone |= {id(o) for o in vis if o is not n and np.hypot(o["x"] - n["x"], o["y"] - n["y"]) <= TOWER_NMS}
    nodes = [n for n in nodes if id(n) not in gone]
    vis = [n for n in nodes if not n.get("hidden")]
    towers = [l for l in out]
    dx, up0, up1 = TOWER_BADGES
    nodes = [n for n in nodes if not (n.get("hidden") and any(abs(n["x"] - t["x"]) <= dx and up0 - 30 <= t["y"] - n["y"] <= up1
                                                            for t in towers))]
    for row in badge_rows(icons):
        if not any(b["name"] == "MapBossSpecial" for b in row):
            continue
        mx, my = (row[0]["x"] + row[-1]["x"]) / 2, float(np.mean([b["y"] for b in row])) + ROW_DY
        if any(abs(mx - t["x"]) <= dx and up0 <= t["y"] - my + ROW_DY <= up1 for t in towers):
            continue                                    # a tower's badges, not a map of its own
        kind, why = deadly_kind(img, mx, my)
        out.append({"kind": kind, "x": round(mx, 1), "y": round(my, 1), "why": why})
    locks = __import__("atlas_cities").locks_in(img)
    for x, y in old["strongholds"]:
        hand = any(np.hypot(x - a, y - b) < 200 for a, b in locks)
        empty = not any(np.hypot(x - n["x"], y - n["y"]) < STRONGHOLD_EMPTY for n in vis)
        kind = "Locked stronghold" if hand or empty else "Breach stronghold"
        out.append({"kind": kind, "x": float(x), "y": float(y),
                    "why": "hand badge" if hand else "no maps inside" if empty else "purple structure"})
    return out, nodes


def find_landmarks(img: np.ndarray, model, nodes: list[dict], icons: list[dict]) -> tuple[list, list]:
    old = old_landmarks(img)
    vis = [n for n in nodes if not n.get("hidden")]
    p = model.predict_proba(tower_features(img, [(n["x"], n["y"]) for n in vis], old["towers"]))[:, 1] \
        if vis else np.zeros(0)
    return landmarks_from(img, nodes, icons, p, old)


# ---------------------------------------------------------------- models in the DB
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS detector_models (
                     name TEXT PRIMARY KEY, blob BLOB NOT NULL, info TEXT, created TEXT NOT NULL)""")
    return c


def save_model(name: str, model, info: dict) -> None:
    """training mode only"""
    buf = io.BytesIO()
    pickle.dump(model, buf)
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO detector_models VALUES (?, ?, ?, ?)",
                  (name, buf.getvalue(), json.dumps(info), datetime.now().isoformat(timespec="seconds")))


# The models are scikit-learn objects stored as pickles. A plain pickle.loads would run any code a tampered
# database carried (e.g. one picked with File > Detector database...), so only the classes a trained model is
# made of may be loaded; anything else is refused before it runs.
_MODEL_CLASSES = {
    ("numpy", "dtype"), ("numpy", "ndarray"),
    ("numpy._core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "scalar"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy.core.multiarray", "scalar"),     # numpy < 2
    ("numpy.random._pcg64", "PCG64"), ("numpy.random._pickle", "__bit_generator_ctor"),
    ("numpy.random._pickle", "__generator_ctor"), ("numpy.random.bit_generator", "SeedSequence"),
    ("numpy.random.bit_generator", "__pyx_unpickle_SeedSequence"),
    ("sklearn._loss._loss", "CyHalfBinomialLoss"), ("sklearn._loss.link", "Interval"),
    ("sklearn._loss.link", "LogitLink"), ("sklearn._loss.loss", "HalfBinomialLoss"),
    ("sklearn.ensemble._hist_gradient_boosting.binning", "_BinMapper"),
    ("sklearn.ensemble._hist_gradient_boosting.gradient_boosting", "HistGradientBoostingClassifier"),
    ("sklearn.ensemble._hist_gradient_boosting.predictor", "TreePredictor"),
    ("sklearn.preprocessing._label", "LabelEncoder"),
}


class UnsafeModel(Exception):
    """a stored model refers to something that is not part of a trained detector model"""


class _ModelUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) not in _MODEL_CLASSES:
            raise UnsafeModel(f"the detector database contains {module}.{name}, which is not part of a detector "
                              "model: refused (use the database that came with the program)")
        return super().find_class(module, name)


def safe_model_loads(blob: bytes):
    """unpickle a stored detector model, allowing only the classes such a model is made of"""
    return _ModelUnpickler(io.BytesIO(blob)).load()


def load_model(name: str):
    """live mode: read-only"""
    c = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT blob FROM detector_models WHERE name = ?", (name,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        c.close()
    return safe_model_loads(row[0]) if row else None


# ---------------------------------------------------------------- commands
def _labelled() -> tuple[dict, dict]:
    """truth (all TRUTH_SETS) + per screenshot: image, map (points, features, labels), badge (points, features,
    labels). Ship markers are not ring badges: left out of the badge training."""
    truth, where = {}, {}
    for tf, shots in TRUTH_SETS:
        if tf.exists():
            for name, t in json.loads(tf.read_text(encoding="utf-8")).items():
                truth[name] = dict(t, badges=[b for b in t["badges"] if not b["name"].startswith("ExpeditionShip")])
                where[name] = shots / name
    data = {}
    for name, t in truth.items():
        img = cv2.imdecode(np.fromfile(str(where[name]), np.uint8), cv2.IMREAD_COLOR)
        pts, dv = map_candidates(img)
        bp, ring, extra = badge_candidates(img)
        dashes = path_dashes(img)
        old = old_landmarks(img)
        tp = [(m["x"], m["y"]) for m in t["maps"] if "ui" not in m["flags"]]
        data[name] = {"img": img, "old": old, "dashes": dashes, "path": where[name],
                      "towers": (tp, tower_features(img, tp, old["towers"]), tower_labels(tp, t)),
                      "maps": (pts, np.hstack([map_features(img, pts, dv), path_features(pts, dashes)]),
                               candidate_labels(pts, t)),
                      "badges": (bp, badge_features(img, bp, ring, extra), badge_labels(bp, t))}
    return truth, data


def _tower_refs() -> tuple[np.ndarray, np.ndarray]:
    """extra tower training data: the user's 'pure tower references' shots (9 towers panned across the
    screen, projected into every shot; the maps found there are the non-towers)"""
    if not TOWER_REFS.exists():
        return np.zeros((0, 0)), np.zeros(0)
    X, y = [], []
    for f, v in json.loads(TOWER_REFS.read_text(encoding="utf-8")).items():
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        if img is None or not v["items"]:
            continue
        X.append(tower_features(img, [(i["x"], i["y"]) for i in v["items"]], v["old_towers"]))
        y += [int(i["tower"]) for i in v["items"]]
    return np.vstack(X), np.array(y)


def _extra_maps() -> dict:
    """extra map training data (maps only, no badge / landmark labels): the user's path-marked shots,
    where they circled the missed maps - mostly plain unlit bases the 10 labelled shots barely have"""
    if not EXTRA_MAPS.exists():
        return {}
    out = {}
    for f, v in json.loads(EXTRA_MAPS.read_text(encoding="utf-8")).items():
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        pts, dv = map_candidates(img)
        t = {"maps": [dict(m, flags=[]) for m in v["maps"]], "maybe": [], "landmarks": []}
        out[f] = (pts, np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))]),
                  candidate_labels(pts, t))
    return out


TREE_NEG_WEIGHT = 1.0        # x15 tried: 48 -> 64 wrong maps on the labelled shots


def _tree_rounds():
    """(key file, labels file, labels name the maps?) of every arborist round"""
    return [(TESTS / "trees" / "trees_key.json", TESTS / "trees" / "trees_labels.txt", True),
            (TESTS / "trees2" / "trees2_key.json", TESTS / "trees2" / "trees2_labels.txt", False)]


def _tree_examples() -> tuple[np.ndarray, np.ndarray] | None:
    """map training rows from the arborist sheets: every tile is a labelled map / not-a-map spot (orange foliage,
    beams, Corruption ground and copper-rimmed bases look alike to the map model). Round 1 lists the maps,
    round 2 the non-maps."""
    import re
    X, y = [], []
    for kf, lf, lists_maps in _tree_rounds():
        if not kf.exists() or not lf.exists():
            continue
        key = json.loads(kf.read_text(encoding="utf-8"))
        text = " ".join(line.split("#")[0] for line in lf.read_text(encoding="utf-8").splitlines())
        ids = {m.group(1).upper() for m in re.finditer(r"\b([A-Za-z]\d+)\b(\([^)]*\))?", text)
               if not (m.group(2) and "map base" in m.group(2).lower())}   # "U21(map base ...)" = a map
        if not ids and "none" not in text.lower():
            continue                                   # not labelled yet
        by_shot: dict = {}
        for t in key:
            p = Path(t["path"]) if "path" in t else rc_paths.ROOT.parent / "rc-1" / "atlases" / "default" / t["shot"]
            by_shot.setdefault(str(p), []).append(t)
        for p, items in by_shot.items():
            if not Path(p).exists():
                continue
            img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            pts, dv = map_candidates(img)
            if not len(pts):
                continue
            F = np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))])
            wall = fortress_walls(img)
            for t in items:
                x0, y0 = int(t["x"]), int(t["y"])
                if wall[max(0, y0 - 60):y0 + 60, max(0, x0 - 60):x0 + 60].mean() > 0.15:
                    continue                           # fortress special maps: never training examples (user)
                d = np.hypot(pts[:, 0] - t["x"], pts[:, 1] - t["y"])
                k = int(np.argmin(d))
                if d[k] <= 3:
                    X.append(F[k])
                    listed = t["id"].upper() in ids
                    y.append(int(listed if lists_maps else not listed))
    return (np.array(X), np.array(y)) if X else None


def _fit(data: dict, names, stage: str, weight: float = 5, leaf: int = 20):
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = np.vstack([data[n][stage][1][data[n][stage][2] >= 0] for n in names])
    y = np.concatenate([data[n][stage][2][data[n][stage][2] >= 0] for n in names])
    if stage == "maps" and data.get("_extra_maps"):
        X = np.vstack([X] + [v[1][v[2] >= 0] for v in data["_extra_maps"].values()])
        y = np.concatenate([y] + [v[2][v[2] >= 0] for v in data["_extra_maps"].values()])
    sw = np.ones(len(y))
    if stage == "maps" and data.get("_trees") is not None:
        X = np.vstack([X, data["_trees"][0]])
        y = np.concatenate([y, data["_trees"][1]])
        # hand-labelled look-alikes (orange trees, beams, Corruption ground) weigh like the maps (class 1 x weight)
        sw = np.concatenate([sw, np.where(data["_trees"][1] == 0, TREE_NEG_WEIGHT, 1.0)])
    if stage == "towers" and "_tower_refs" in data:
        X = np.vstack([X, data["_tower_refs"][0]])
        y = np.concatenate([y, data["_tower_refs"][1]])
        sw = np.ones(len(y))
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, class_weight={0: 1, 1: weight}, min_samples_leaf=leaf,
                                          random_state=0).fit(X, y, sample_weight=sw if len(sw) == len(y) else None)


def _fit_all(truth: dict, data: dict, names) -> dict:
    book = badge_book(truth, {n: data[n]["img"] for n in names}, names)
    return {"maps": _fit(data, names, "maps"), "badges": dict(book, clf=_fit(data, names, "badges")),
            "towers": _fit(data, names, "towers", weight=5)}


def _run_stages(d: dict, models: dict) -> dict:
    img = d["img"]
    pts, X, _l = d["maps"]
    prob = models["maps"].predict_proba(X)
    nodes = _nms(pts, prob)
    bp, BX, _l = d["badges"]
    icons, more = badges_from(img, bp, models["badges"]["clf"].predict_proba(BX)[:, 1], models["badges"], nodes,
                              pts, prob[:, MAP])
    nodes = nodes + more
    vis = [n for n in nodes if not n.get("hidden")]
    tp = models["towers"].predict_proba(tower_features(img, [(n["x"], n["y"]) for n in vis], d["old"]["towers"]))[:, 1]
    lms, nodes = landmarks_from(img, nodes, icons, tp, d["old"])
    lms = [l for l, on in zip(lms, core.on_hud_mask([(l["x"], l["y"]) for l in lms], img.shape[1], img.shape[0], pad=0))
           if not on]                                     # a landmark inside the HUD outline is HUD art
    nodes = nodes + maps_from_paths(nodes, d["dashes"], img, pts, prob[:, MAP])
    nodes, icons, lms = expedition_rules(nodes, icons, lms)
    return {"nodes": nodes, "landmarks": lms, "icons": icons, "edges": trace_paths(nodes, d["dashes"], img)}


def cmd_score() -> int:
    t0 = time.time()
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    before, after, new = {}, {}, {}
    for name in truth:
        img = data[name]["img"]
        cf = CACHE / f"{hashlib.sha256(Path(data[name]['path']).read_bytes()).hexdigest()[:16]}.json"
        if cf.exists():
            r = json.loads(cf.read_text(encoding="utf-8"))
            before[name], after[name] = r, drop_hud(r, img.shape[1], img.shape[0])
        new[name] = _run_stages(data[name], _fit_all(truth, data, [n for n in truth if n != name]))
    for title, outs in (("old detector", before), ("old detector + stage 1 (HUD)", after),
                        ("NEW stages 2-4 (leave-one-screenshot-out)", new)):
        print(f"\n== {title}")
        atlas_truth.print_score(atlas_truth.score(truth, outs))
    print(f"\nhidden maps from badge rows: {sum(1 for o in new.values() for n in o['nodes'] if n.get('hidden'))}")
    (TRUTH.parent / "last_score_outputs.json").write_text(json.dumps(new, default=float), encoding="utf-8")
    print(f"{time.time() - t0:.0f} s")
    return 0


def cmd_train() -> int:
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    data["_trees"] = _tree_examples()
    if data["_trees"] is not None:
        print(f"arborist round: {len(data['_trees'][1])} labelled spots ({int(data['_trees'][1].sum())} maps)")
    m = _fit_all(truth, data, list(truth))
    nm = int(sum((d["maps"][2] == 1).sum() for k, d in data.items() if not k.startswith("_")))
    nb = int(sum((d["badges"][2] == 1).sum() for k, d in data.items() if not k.startswith("_")))
    save_model("maps", m["maps"], {"screenshots": len(truth), "maps": nm})
    save_model("badges", m["badges"], {"screenshots": len(truth), "badges": nb, "pictures": len(m["badges"]["names"])})
    nt = int(sum(d["towers"][2].sum() for k, d in data.items() if not k.startswith("_")) + data["_tower_refs"][1].sum())
    save_model("towers", m["towers"], {"screenshots": len(truth), "towers": nt})
    print(f"trained on {len(truth)} screenshots: map model ({nm} maps), badge model ({nb} badges, "
          f"{len(m['badges']['names'])} labelled pictures) -> {DB_PATH.name}")
    return 0


EXPEDITION = "Expedition"
NOT_ON_EXPEDITION = ("Hall", "Tower")     # user: Halls / Towers / Hideouts appear in the ocean, never with an
EXP_REACH = (40, 15, 40)                  # Expedition badge.  badge -> its map: |dx| <= 40, 15 <= dy <= 40


def expedition_rules(nodes: list[dict], icons: list[dict], lms: list[dict]) -> tuple[list, list, list]:
    """Ocean (Expedition biome) rules, user's:
    - an Expedition badge sits right above a VISIBLE ocean map: a hidden map under its row is shown
      (its star base is often too unlike the gold-rimmed bases the map model knows)
    - a map with an Expedition badge is never a Hall, Tower or Hideout: those calls are dropped
      (a Hall keeps its Deadly Map Boss badge: a plain deadly boss map; a Hideout badge in the row goes)"""
    dx, y0, y1 = EXP_REACH
    exp = [b for b in icons if b.get("name") == EXPEDITION]
    if not exp:
        return nodes, icons, lms

    def under(x, y):
        return any(abs(x - b["x"]) <= dx and y0 <= y - b["y"] <= y1 for b in exp)

    nodes = [dict(n) for n in nodes]
    for n in nodes:
        if n.get("hidden") and under(n["x"], n["y"]):
            n["hidden"] = False
            n["source"] = "under Expedition badge"
        if n.get("tower") and under(n["x"], n["y"]):
            n["tower"] = False
    out = []
    for l in lms:
        if l["kind"] in NOT_ON_EXPEDITION and under(l["x"], l["y"]):
            if l["kind"] == "Hall":
                out.append(dict(l, kind="Deadly boss map", why="Expedition badge: never a Hall"))
            continue                                          # Tower: an ordinary ocean map
        out.append(l)
    rows = badge_rows(icons)
    drop = {id(b) for r in rows if any(b.get("name") == EXPEDITION for b in r) for b in r if b.get("name") == "Hideout"}
    icons = [b for b in icons if id(b) not in drop]
    return nodes, icons, out


def ship_markers(img: np.ndarray) -> list[dict]:
    """Expedition ship markers (ocean biome): the square button with a ship symbol (user: boat), from the
    same finder as the locked strongholds' hand badges"""
    import atlas_cities
    return [{"name": "ExpeditionShip", "x": int(b["x"]), "y": int(b["y"]), "score": b["symbol"], "source": "square button"}
            for b in atlas_cities.square_buttons(img) if b["kind"] == "ship"]


_models: dict = {}


def detect(img: np.ndarray) -> dict:
    """live mode: everything built so far for one screenshot (same shape as the old detector's result)"""
    for k in ("maps", "badges", "towers"):
        if k not in _models:
            _models[k] = load_model(k)
            if _models[k] is None:
                raise RuntimeError(f"no {k} model in the DB yet: run  py atlas_detect.py train")
    nodes, mp, mprob = find_maps(img, _models["maps"])
    icons, more = find_badges(img, _models["badges"], nodes, mp, mprob)
    lms, nodes = find_landmarks(img, _models["towers"], nodes + more, icons)
    lms = [l for l, on in zip(lms, core.on_hud_mask([(l["x"], l["y"]) for l in lms], img.shape[1], img.shape[0], pad=0))
           if not on]                                     # a landmark inside the HUD outline is HUD art
    dashes = path_dashes(img)
    nodes = nodes + maps_from_paths(nodes, dashes, img, mp, mprob)
    nodes, icons, lms = expedition_rules(nodes, icons, lms)
    icons = icons + ship_markers(img)
    wall = fortress_walls(img)
    edges = [e for e in trace_paths(nodes, dashes, img) if wall_share(e["line"], wall) < WALL_CROSS]
    return {"width": img.shape[1], "height": img.shape[0], "nodes": nodes, "landmarks": lms, "icons": icons,
            "edges": edges}


def cmd_run() -> int:  # noqa: E302
    for f in sys.argv[2:]:
        t0 = time.time()
        r = detect(cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR))
        hid = sum(1 for n in r["nodes"] if n.get("hidden"))
        kinds = {}
        for l in r["landmarks"]:
            kinds[l["kind"]] = kinds.get(l["kind"], 0) + 1
        print(f"{Path(f).name}: {len(r['nodes']) - hid} maps, {hid} hidden maps, {len(r['icons'])} badges, "
              f"{len(r['edges'])} paths, {kinds} "
              f"in {time.time() - t0:.1f} s")
    return 0


LM_STYLE = {"Tower": ((90, 230, 90), (60, 180)), "Breach stronghold": ((230, 120, 230), (90, 110)),
            "Locked stronghold": ((230, 120, 230), (90, 110)), "City": ((80, 200, 255), (110, 130)),
            "Hall": ((60, 150, 255), (110, 130)), "Deadly boss map": ((60, 60, 255), (60, 70))}
PATH_DRAW_SHIFT = -5          # px: paths drawn beside the game's own dotted lines, not on top of them


def annotate(img: np.ndarray, r: dict) -> np.ndarray:
    """everything the detector found, drawn on the screenshot (old-style notation, no subway)"""
    v = img.copy()
    cyan, pink = (255, 220, 60), (230, 130, 230)
    for e in r["edges"]:
        L = np.array(e["line"], float) + (PATH_DRAW_SHIFT, 0)
        seg = np.hypot(*np.diff(L, axis=0).T)
        pos = np.concatenate([[0], np.cumsum(seg)])
        for t in np.arange(0, pos[-1], 6.0):                # dotted
            i = min(int(np.searchsorted(pos, t, side="right")) - 1, len(seg) - 1)
            f = (t - pos[i]) / max(seg[i], 1e-6)
            q = L[i] + f * (L[i + 1] - L[i])
            cv2.circle(v, (int(q[0]), int(q[1])), 1, cyan, -1, cv2.LINE_AA)
    for n in r["nodes"]:
        x, y = int(n["x"]), int(n["y"])
        if n.get("hidden"):
            cv2.drawMarker(v, (x, y), pink, cv2.MARKER_SQUARE, 14, 1)
            cv2.putText(v, "Hidden", (x + 10, y + 4), 0, 0.45, pink, 1, cv2.LINE_AA)
        elif not n.get("tower"):
            cv2.circle(v, (x, y), 10, cyan, 2, cv2.LINE_AA)
            cv2.putText(v, "Map", (x + 12, y - 4), 0, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(v, "Map", (x + 12, y - 4), 0, 0.45, cyan, 1, cv2.LINE_AA)
    for l in r["landmarks"]:
        col, (w, h) = LM_STYLE.get(l["kind"], ((255, 255, 255), (80, 80)))
        x, y = int(l["x"]), int(l["y"])
        top = y - h + 15 if l["kind"] == "Tower" else y - h // 2
        cv2.rectangle(v, (x - w // 2, top), (x + w // 2, top + h), col, 2)
        cv2.drawMarker(v, (x, y), col, cv2.MARKER_CROSS, 10, 1)
        label = l["kind"] + (f" ({l['city_type']})" if l.get("city_type") else "")
        cv2.putText(v, label, (x + w // 2 + 4, top + 14), 0, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(v, label, (x + w // 2 + 4, top + 14), 0, 0.5, col, 1, cv2.LINE_AA)
    for b in r["icons"]:
        x, y = int(b["x"]), int(b["y"])
        cv2.circle(v, (x, y), 12, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(v, b["name"], (x - 24, y - 15), 0, 0.33, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(v, b["name"], (x - 24, y - 15), 0, 0.33, (255, 255, 255), 1, cv2.LINE_AA)
    return v


def cmd_show() -> int:
    """py atlas_detect.py show OUT_DIR IMG...   (or: show OUT_DIR random N  -> N random unlabelled samples)"""
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = sys.argv[3:]
    if files[:1] == ["random"]:
        import random
        truth = json.loads(TRUTH.read_text(encoding="utf-8"))
        pool = sorted(p for p in SHOTS.glob("*.png") if p.name not in truth)
        files = [str(p) for p in random.sample(pool, int(files[1]) if len(files) > 1 else 3)]
    for f in files:
        t0 = time.time()
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        r = detect(img)
        cv2.imwrite(str(out / f"{Path(f).stem}_annotated.png"), annotate(img, r))
        (out / f"{Path(f).stem}_detect.json").write_text(json.dumps(r, default=float), encoding="utf-8")
        hid = sum(1 for n in r["nodes"] if n.get("hidden"))
        print(f"{Path(f).name}: {len(r['nodes']) - hid} maps, {hid} hidden, {len(r['icons'])} badges, "
              f"{len(r['edges'])} paths, {len(r['landmarks'])} landmarks, {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    cmds = {"score": cmd_score, "train": cmd_train, "train_fortress": cmd_train_fortress, "run": cmd_run, "show": cmd_show}
    if sys.argv[1:2] and sys.argv[1] in cmds:
        raise SystemExit(cmds[sys.argv[1]]())
    print(__doc__)
