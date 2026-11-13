"""PoE2 atlas builder core: add screenshots one at a time to a growing node graph.

Pure numpy + OpenCV (no new installs).  The unit of work is a *frame*: one screenshot that
the recognizer (node_recognition_0_48) has already turned into nodes, dotted-path edges and landmarks.

Registration is done on the node graph (not on terrain features):
  1. every (frame node, atlas node) pair votes for a translation; pairs whose local
     neighbour spacing agrees count more, so true correspondences pile up in one bin;
  2. the best translations are refined to a constrained affine by iteratively fitting
     mutually-nearest node pairs with a shrinking tolerance;
  3. the result is accepted only if enough nodes agree AND the terrain pixels of the two
     screenshots correlate in the overlap.  A wrong graph match fails the pixel test.
Nodes, edges and landmarks seen in several frames are merged and carry support counts, so
every extra screenshot makes an existing part of the atlas more certain.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import atlas_io

# ------------------------------------------------------------------ tunables
VOTE_BIN = 8            # px, translation histogram bin
SIG_DIST1, SIG_DIST2 = 8.0, 10.0   # neighbour-spacing agreement for a "good" pair
REFINE_TOLS = (16, 12, 8, 6, 5)
MERGE_TOL = 9.0         # px: a frame node closer than this to an atlas node IS that node
MIN_INLIERS = 8
MIN_OVERLAP_RATIO = 0.40
MIN_NCC = 0.35
SCALE_RANGE = (0.90, 1.12)
LANDMARK_MERGE = 45.0
ICON_BASE_DY = 24.0     # screen px: a map base sits this far below its icon badge (measured, 22-28)
ICON_MERGE = 14.0       # atlas units: the same badge seen in two screenshots
# The atlas camera is tilted: panning sideways moves the bottom of the screen further than the
# top, and panning up/down squashes the view.  Undoing that tilt ("rectifying") turns every pan
# into a pure shift.  HORIZON is where the map's vanishing line sits, in PIXELS above the top
# edge of the screenshot (negative = above).  It is a fixed distance, not a fraction of the image
# height: cropped Screenshot_35-38 fit -2170 px, full 1919x1079 Screenshot_39-43 fit -2150 px.
# Assumes a 1080p game window with the top of the screen kept when cropping.
# Set to None to disable (treat screenshots as flat, the pre-0.2 behaviour).
HORIZON: float | None = -2155.0
PLACEMENT = "shift"        # "shift" (pans on the flattened map) or "affine" (old behaviour)
TERRAIN_MIN_AGREE = 15     # terrain fallback: features agreeing on one shift
TERRAIN_SCALE = 1.0075     # parallax: ground texture moves ~0.75% more than the map nodes on a pan (measured
                           # on 157 crawl pairs, same on x and y); terrain shifts are divided by it so they are
                           # in map-node units. Uncorrected, a 1100-unit jump was ~10 units off and the map
                           # refine (allowed < 10) was thrown away.
PARALLAX_MIN_INLIERS = 15  # second chance for screenshots of raised ground: exact matches needed ...
PARALLAX_TOL = 20.0        # ... and this share of maps within this distance
PARALLAX_RATIO = 0.45
DROP_MIN_INLIERS = 5       # placing by hand: maps that must agree near the drop point
TERRAIN_MIN_NCC = 0.40     # ...and a stricter whole-overlap pixel check than the map route (0.35)


# ------------------------------------------------------------------ frame data
@dataclass
class Frame:
    name: str
    path: str
    sha: str
    w: int
    h: int
    pts: np.ndarray                 # (N,2) screenshot pixels
    usable: np.ndarray              # (N,) bool: real, visible bases (no hidden / icon-only guesses)
    nodes: list[dict]
    edges: list[tuple[int, int, float, str]]
    landmarks: list[dict]
    R: np.ndarray = field(default_factory=lambda: np.eye(3))   # screen px -> flat map coords

    @staticmethod
    def from_json(d: dict, horizon: float | None | str = "default") -> "Frame":
        if horizon == "default":           # module setting is in px; rectifier takes image heights
            horizon = None if HORIZON is None else HORIZON / d["height"]
        nodes = d["nodes"]
        R = rectifier(d["width"], d["height"], horizon)
        screen = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
        on_hud = on_hud_mask(screen, d["width"], d["height"])
        usable = np.array([not (n["hidden"] or n["unverified"]) for n in nodes], bool) & ~on_hud
        edges = [(e["a"], e["b"], e["conf"], e["status"]) for e in d["edges"]
                 if not (on_hud[e["a"]] or on_hud[e["b"]])]
        landmarks = [lm for lm in d["landmarks"]
                     if not on_hud_mask(np.array([[lm["x"], lm["y"]]], float), d["width"], d["height"])[0]]
        fr = Frame(d["name"], d["path"], d["sha256"], d["width"], d["height"], persp(R, screen), usable,
                   nodes, edges, landmarks, R)
        fr.on_hud = on_hud
        icons = d.get("icons", [])
        if icons:
            ip = np.array([[m["x"], m["y"]] for m in icons], float)
            keep = ~on_hud_mask(ip, d["width"], d["height"])
            icons = [m for m, k in zip(icons, keep) if k]
        fr.icons = icons                     # screen px; badges from the icon matcher
        return fr


# Game HUD on a full, uncropped window: hud_mask_full.png (white = HUD), drawn by the user on a
# 1919x1079 screenshot and scaled for other full-window sizes. Nodes / towers / badges "found" there
# are detector mistakes on the UI.
# A spot counts as UI only HUD_DEPTH px inside the outline: it is hand-drawn, real maps sat up to
# 30 px inside it, UI pieces 44+ px (random_samples_truth).
HUD_DEPTH = 35
HUD_MASK_FILE = Path(__file__).resolve().parent.parent / "references" / "hud_mask_full.png"
_hud_cache: dict = {}


def is_full_window(w: int, h: int) -> bool:
    return w >= 1850 and h >= 1040 and abs(w / h - 16 / 9) < 0.03


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# images the atlas itself writes (never screenshots): <atlas>_terrain.png, _composite.png, _network.png, ...
ATLAS_OUTPUTS = ("_terrain.png", "_terrain.npz", "_composite.png", "_network.png", "_coverage.png", "_badges.png")


def atlas_files(atlas_path) -> Path:
    """the folder for everything an atlas writes besides atlas.json and its detection cache: map image cache,
    exports, undo snapshots. A subfolder, so the atlas folder can also be the screenshot folder (user).
    Files from atlases made before v0.88 (next to atlas.json) are moved in."""
    atlas_path = Path(atlas_path)
    d = atlas_path.with_name(atlas_path.stem + "_files")
    d.mkdir(parents=True, exist_ok=True)
    for suffix in ATLAS_OUTPUTS + ("_undo",):
        old = atlas_path.with_name(atlas_path.stem + suffix)
        new = d / (atlas_path.stem + suffix)
        if old.exists() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass
    return d


def is_screenshot(p) -> bool:
    """an image file that can be a screenshot: not one of the atlas's own outputs (an old atlas may still have
    them next to atlas.json), not inside an atlas's _files / _frames folder"""
    p = Path(p)
    if p.suffix.lower() not in IMAGE_EXT or not p.is_file():
        return False
    if any(p.name.endswith(o) for o in ATLAS_OUTPUTS):
        return False
    return not p.parent.name.endswith(("_files", "_frames", "_undo"))


def screenshots_in(folder) -> list[Path]:
    """the screenshots directly in a folder, in name (= time) order"""
    try:
        return sorted(q for q in Path(folder).iterdir() if is_screenshot(q))
    except OSError:
        return []


def hud_mask(w: int, h: int, pad: int = 0) -> np.ndarray:
    """uint8 mask, 255 = game HUD (all zero for cropped screenshots), grown by pad px (shrunk if < 0)"""
    k = (w, h, pad)
    if k not in _hud_cache:
        m = np.zeros((h, w), np.uint8)
        if is_full_window(w, h):
            src = cv2.imread(str(HUD_MASK_FILE), cv2.IMREAD_GRAYSCALE)
            m = (cv2.resize(src, (w, h), interpolation=cv2.INTER_NEAREST) > 127).astype(np.uint8) * 255
            if pad:                                      # pad < 0: only spots that deep inside the HUD
                se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(pad) + 1, 2 * abs(pad) + 1))
                m = cv2.dilate(m, se) if pad > 0 else cv2.erode(m, se)
        _hud_cache[k] = m
    return _hud_cache[k]


def on_hud_mask(pts: np.ndarray, w: int, h: int, pad: float = -HUD_DEPTH) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    if not is_full_window(w, h) or not len(pts):
        return np.zeros(len(pts), bool)
    m = hud_mask(w, h, int(pad))
    x = np.clip(pts[:, 0].round().astype(int), 0, w - 1)
    y = np.clip(pts[:, 1].round().astype(int), 0, h - 1)
    return m[y, x] > 0


ROW_STEP_PX = 36.0      # screen px between neighbouring badges of one row (measured)


def row_bases(icons: list[dict]) -> list[tuple[float, float]]:
    """per badge (screen px): its map base = under the middle of the row of badges it is in. A row: badges
    at the same height, 36 px apart (72 when the middle one was missed)."""
    order = sorted(range(len(icons)), key=lambda k: icons[k]["x"])
    rows: list[list[int]] = []
    for k in order:
        m = icons[k]
        for r in rows:
            last = icons[r[-1]]
            gap = m["x"] - last["x"]
            if abs(m["y"] - last["y"]) <= 6 and (abs(gap - ROW_STEP_PX) <= 8 or abs(gap - 2 * ROW_STEP_PX) <= 8)                     and "LostTower" not in (m["name"], last["name"]):
                r.append(k)
                break
        else:
            rows.append([k])
    out = [(0.0, 0.0)] * len(icons)
    for r in rows:
        bx = (icons[r[0]]["x"] + icons[r[-1]]["x"]) / 2
        by = float(np.mean([icons[k]["y"] for k in r])) + ICON_BASE_DY
        for k in r:
            out[k] = (bx, by)
    return out


def rectifier(w: int, h: int, horizon: float | None) -> np.ndarray:
    """3x3 homography: screen px -> flat map coords (1:1 with screen px at the screen centre)."""
    if horizon is None:
        return np.eye(3)
    cx, cy = w / 2.0, h / 2.0
    vh = horizon * h                     # horizon row in px
    d0 = cy - vh                         # centre row's distance below the horizon
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


# ------------------------------------------------------------------ geometry helpers
def neighbour_signature(pts: np.ndarray) -> np.ndarray:
    """Distances to the two nearest other nodes: a cheap, zoom-stable local fingerprint."""
    if len(pts) < 3:
        return np.full((len(pts), 2), 1e6)
    from scipy.spatial import cKDTree
    d, _ = cKDTree(pts).query(pts, k=3)              # itself + the two nearest (no N x N matrix)
    return d[:, 1:3]


def vote_translations(src: np.ndarray, dst: np.ndarray, top_k: int = 8):
    s_sig, d_sig = neighbour_signature(src), neighbour_signature(dst)
    good = ((np.abs(s_sig[:, None, 0] - d_sig[None, :, 0]) < SIG_DIST1) &
            (np.abs(s_sig[:, None, 1] - d_sig[None, :, 1]) < SIG_DIST2))
    weights = np.where(good, 1.0, 0.15).ravel()
    dx = (dst[None, :, 0] - src[:, None, 0]).ravel()
    dy = (dst[None, :, 1] - src[:, None, 1]).ravel()
    x0, x1, y0, y1 = dx.min(), dx.max(), dy.min(), dy.max()
    nx, ny = max(3, int((x1 - x0) / VOTE_BIN) + 1), max(3, int((y1 - y0) / VOTE_BIN) + 1)
    hist, xe, ye = np.histogram2d(dx, dy, bins=[nx, ny], range=[[x0, x1 + 1e-6], [y0, y1 + 1e-6]],
                                  weights=weights)
    smooth = cv2.boxFilter(hist.astype(np.float32), -1, (3, 3), normalize=False)
    peaks = []
    work = smooth.copy()
    for _ in range(top_k):
        i, j = np.unravel_index(int(np.argmax(work)), work.shape)
        if work[i, j] <= 2:
            break
        peaks.append((float(work[i, j]), float(xe[i] + VOTE_BIN / 2), float(ye[j] + VOTE_BIN / 2)))
        work[max(0, i - 3):i + 4, max(0, j - 3):j + 4] = 0
    return peaks


def fit_affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Least-squares placement; None when it would be an implausible camera change.

    With the camera tilt undone a pan is a pure shift, so by default only a shift is fitted
    (PLACEMENT = "shift").  A free affine fitted ~1% squash and ~0.2 deg turns to the overlap,
    and those compounded from screenshot to screenshot into 30-45 unit offsets far from it."""
    if PLACEMENT == "shift" and HORIZON is not None:
        return np.hstack([np.eye(2), (dst - src).mean(axis=0)[:, None]])
    A = np.hstack([src, np.ones((len(src), 1))])
    sol, *_ = np.linalg.lstsq(A, dst, rcond=None)
    M = sol.T
    sv = np.linalg.svd(M[:, :2], compute_uv=False)
    if sv[1] < SCALE_RANGE[0] or sv[0] > SCALE_RANGE[1]:
        return None
    return M


def mutual_pairs(a: np.ndarray, b: np.ndarray, tol: float):
    """(i, j, dist): a[i] and b[j] are each other's nearest point, within tol"""
    if not len(a) or not len(b):
        return []
    from scipy.spatial import cKDTree
    da, ia = cKDTree(b).query(a)
    _db, ib = cKDTree(a).query(b)
    return [(i, int(ia[i]), float(da[i])) for i in range(len(a)) if ib[ia[i]] == i and da[i] <= tol]


def refine(src: np.ndarray, dst: np.ndarray, t0) -> tuple[np.ndarray, list, float]:
    M = np.array([[1, 0, t0[0]], [0, 1, t0[1]]], float)
    pairs: list = []
    for tol in REFINE_TOLS:
        pairs = mutual_pairs(apply(M, src), dst, tol)
        if len(pairs) < 4:
            break
        a = src[[p[0] for p in pairs]]
        b = dst[[p[1] for p in pairs]]
        fitted = fit_affine(a, b) if len(pairs) >= 7 else None
        if fitted is None:
            M = M.copy()
            M[:, 2] += (b - apply(M, a)).mean(axis=0)
        else:
            M = fitted
    pairs = mutual_pairs(apply(M, src), dst, REFINE_TOLS[-1])
    rmse = float(np.sqrt(np.mean([p[2] ** 2 for p in pairs]))) if pairs else 99.0
    return M, pairs, rmse


# ------------------------------------------------------------------ terrain verification
def _find_screenshot(p: str, atlas_dir: Path) -> str:
    """a screenshot path saved in an atlas, wherever the atlas now is: relative paths are relative to the
    atlas file; an absolute path that no longer exists (atlas folder moved, or copied to another computer)
    falls back to the same file name next to the atlas"""
    q = Path(p)
    if not q.is_absolute():
        return str((atlas_dir / q).resolve())
    if not q.exists() and (atlas_dir / q.name).exists():
        return str(atlas_dir / q.name)
    return p


_MASKS: dict = {}            # id(image) -> (weak ref to the image, its mask): one screenshot is compared
_MASK_CACHE = 64            # with ~30 neighbours per placement (v1.01: the mask was rebuilt every time)


def _valid_mask(frame_img: np.ndarray) -> np.ndarray:
    import weakref
    hit = _MASKS.get(id(frame_img))
    if hit is not None and hit[0]() is frame_img:
        return hit[1]
    m = _valid_mask_calc(frame_img)
    m.flags.writeable = False                            # shared: callers must not change it
    try:
        _MASKS[id(frame_img)] = (weakref.ref(frame_img), m)
        while len(_MASKS) > _MASK_CACHE:
            _MASKS.pop(next(iter(_MASKS)))
    except TypeError:                                    # (a view that cannot be weakly referenced)
        pass
    return m


def _valid_mask_calc(frame_img: np.ndarray) -> np.ndarray:
    h, w = frame_img.shape[:2]
    m = np.full((h, w), 255, np.uint8)
    m[:max(112, 0), int(w * .20):int(w * .74)] = 0     # world header / act tabs / search
    m[:94, :92] = 0
    m[:77, max(0, w - 200):] = 0
    m[max(0, h - 100):, :110] = 0                        # globe
    m[max(0, h - 100):, max(0, w - 110):] = 0
    m[max(0, h - 27):, :] = 0
    m[:, :210][int(h * .62):int(h * .96), :] = 0         # stats / chat text, left edge
    m[hud_mask(w, h) > 0] = 0                            # skill bars, globes, side icon columns
    dark = (cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY) < 14).astype(np.uint8) * 255
    dark = cv2.erode(dark, np.ones((9, 9), np.uint8))    # unexplored black fog has no texture
    m[dark > 0] = 0
    return cv2.erode(m, np.ones((7, 7), np.uint8))


def terrain_ncc(img_a: np.ndarray, img_b: np.ndarray, M_b_to_a: np.ndarray) -> tuple[float, int]:
    """Zero-mean NCC of blurred greyscale over the overlap of A and warped B (2x3 or 3x3 map)."""
    h, w = img_a.shape[:2]
    H = to3(M_b_to_a) if M_b_to_a.shape == (2, 3) else M_b_to_a
    warped = cv2.warpPerspective(img_b, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    mb = cv2.warpPerspective(_valid_mask(img_b), H, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    mask = (mb > 0) & (_valid_mask(img_a) > 0)
    mask = cv2.erode(mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    n = int(mask.sum())
    if n < 15000:
        return 0.0, n
    ga = cv2.GaussianBlur(cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY), (0, 0), 2.5).astype(np.float32)
    gb = cv2.GaussianBlur(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (0, 0), 2.5).astype(np.float32)
    # remove slow lighting differences, compare the local texture
    ga -= cv2.GaussianBlur(ga, (0, 0), 14)
    gb -= cv2.GaussianBlur(gb, (0, 0), 14)
    a, b = ga[mask], gb[mask]
    a -= a.mean()
    b -= b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return (float((a * b).sum() / den) if den > 1e-6 else 0.0), n


# ------------------------------------------------------------------ registration
@dataclass
class Registration:
    ok: bool
    reason: str
    M: np.ndarray | None = None
    inliers: int = 0
    rmse: float = 0.0
    overlap_src: int = 0
    overlap_dst: int = 0
    ratio: float = 0.0
    ncc: float = 0.0
    ncc_pixels: int = 0
    ref_frame: str = ""
    candidates: list = field(default_factory=list)


def _inside_rect(pts: np.ndarray, M: np.ndarray, w: int, h: int, R: np.ndarray | None = None,
                 margin: float = 30) -> np.ndarray:
    """atlas points that lie inside the screenshot (0..w,0..h) placed by M (after rectifier R)."""
    back = apply(invert(M), pts)
    if R is not None:
        back = persp(np.linalg.inv(R), back)
    return ((back[:, 0] > margin) & (back[:, 0] < w - margin) &
            (back[:, 1] > margin) & (back[:, 1] < h - margin))


def register(frame: Frame, atlas_pts: np.ndarray,
             footprints: list[tuple[np.ndarray, int, int, np.ndarray]]) -> tuple[Registration, list]:
    """Find M (frame px -> atlas coords) from nodes only. Terrain check is done by the caller."""
    src = frame.pts[frame.usable]
    if len(src) < MIN_INLIERS or len(atlas_pts) < MIN_INLIERS:
        return Registration(False, "too few nodes to match"), []
    best, tried = None, []
    for votes, tx, ty in vote_translations(src, atlas_pts):
        M, pairs, rmse = refine(src, atlas_pts, (tx, ty))
        inl = len(pairs)
        moved = apply(M, src)
        inside_src = np.zeros(len(src), bool)
        for FM, fw, fh, FR in footprints:
            inside_src |= _inside_rect(moved, FM, fw, fh, FR)
        inside_dst = _inside_rect(atlas_pts, M, frame.w, frame.h, frame.R)
        o_src, o_dst = int(inside_src.sum()), int(inside_dst.sum())
        ratio = inl / max(1, min(o_src, o_dst))
        cand = Registration(False, "", M, inl, rmse, o_src, o_dst, ratio)
        tried.append(cand)
        if best is None or (inl, -rmse) > (best.inliers, -best.rmse):
            best = cand
    if best is None:
        return Registration(False, "no translation peak"), []
    tried.sort(key=lambda r: (-r.inliers, r.rmse))
    return best, tried


def _horizon_of(frame: Frame) -> float | None:
    """Recover the horizon a frame was rectified with (None = flat)."""
    R = frame.R / frame.R[2, 1] if frame.R[2, 1] else frame.R
    if np.allclose(frame.R, np.eye(3)):
        return None
    return float(-R[2, 2] / frame.h)


# ------------------------------------------------------------------ the atlas
class Atlas:
    def __init__(self):
        self.nodes: list[dict] = []          # {x,y,n,frames,tower}
        self.edges: dict[tuple[int, int], dict] = {}
        self.landmarks: list[dict] = []
        self.bookmarks: list[dict] = []          # {name,category,note,x,y} set in the viewer
        self.icons: list[dict] = []              # every badge, merged across screenshots
        self.final: dict | None = None           # atlas-wide clean-up result (atlas_finalize)
        self.city_types: list[dict] = []         # {x,y,type} cities whose type was set by hand
        self.city_auto: list[dict] = []          # {x,y,d:[..]} cached look-alike distances per city type
        self.landmark_edits: list[dict] = []     # {x,y,kind[,on]} set by hand in the viewer; kind "" = deleted
        self.biome_edits: list[dict] = []        # {"biome": "Vaal city"... or "" (none), "maps": [[x, y], ...]} lassoed by hand
        self.locks: list[dict] = []              # {x,y,n} hand badges = locked Breach strongholds
        self.lock_scanned: list[str] = []        # screenshots already searched for the hand badge
        self.frames: list[dict] = []         # {name,path,sha,w,h,M,stats}
        self._images: dict[str, np.ndarray] = {}

    # -------- image access
    IMAGE_CACHE = 90                          # decoded screenshots kept in memory (~6 MB each; a terrain
                                              # check of one screenshot reads ~60 neighbours)

    _image_lock = threading.Lock()             # the viewer reads images while a worker places

    def image(self, path: str) -> np.ndarray:
        with Atlas._image_lock:
            if path in self._images:
                img = self._images.pop(path)
                self._images[path] = img                      # most recently used last
                return img
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        with Atlas._image_lock:
            self._images[path] = img
            while len(self._images) > self.IMAGE_CACHE:
                self._images.pop(next(iter(self._images)))
        return img

    def points(self) -> np.ndarray:
        return np.array([[n["x"], n["y"]] for n in self.nodes], float).reshape(-1, 2)

    @staticmethod
    def frame_R(f: dict) -> np.ndarray:
        return rectifier(f["w"], f["h"], f.get("horizon"))

    def central_views(self, x: float, y: float, n: int = 3, limit: float = 0.42):
        """the n screenshots showing atlas point (x, y) closest to their middle, as
        (offset from the middle 0..0.5, frame, screen point); only those with offset < limit"""
        out = []
        for f in self.frames:
            Hi = np.linalg.inv(screen_to_atlas(np.array(f["M"], float), self.frame_R(f)))
            p = persp(Hi, [[x, y]])[0]
            c = max(abs(p[0] / f["w"] - .5), abs(p[1] / f["h"] - .5))
            if c < limit:
                out.append((c, f, p))
        return sorted(out, key=lambda t: t[0])[:n]

    def footprints(self):
        return [(np.array(f["M"], float), f["w"], f["h"], self.frame_R(f)) for f in self.frames]

    # -------- adding frames
    def add_frame(self, frame: Frame, verify: bool = True, hints: list[str] | None = None,
                  seeds: list | None = None, commit: bool = True) -> Registration:
        """Place by the map layout; when too few maps are in the overlap (fog at the atlas edge,
        big pans), fall back to terrain features against the screenshots named in `hints`.
        commit=False only works out the placement (reg.ok, reg.M); commit it with commit_frame."""
        if any(f["sha"] == frame.sha for f in self.frames):
            return Registration(False, "this screenshot is already in the atlas")
        if not self.frames:
            reg0 = Registration(True, "first frame", np.array([[1, 0, 0], [0, 1, 0]], float))
            if commit:
                self._ingest(frame, reg0.M, reg0)
            return reg0
        reg, tried = register(frame, self.points(), self.footprints())
        reg.candidates = [(r.inliers, round(r.rmse, 2), round(r.ratio, 2)) for r in tried[:4]]
        why = None
        if reg.M is None:
            why = "no match"
        elif reg.inliers < MIN_INLIERS:
            why = f"only {reg.inliers} nodes agree (need {MIN_INLIERS})"
        elif reg.ratio < MIN_OVERLAP_RATIO and not self._parallax_ok(frame, reg):
            why = f"only {reg.ratio:.0%} of overlapping nodes agree (need {MIN_OVERLAP_RATIO:.0%})"
        elif verify:
            self._verify(frame, reg)
            if reg.ncc_pixels < 15000:
                why = "overlap too small to verify with terrain"
            elif reg.ncc < MIN_NCC:
                why = f"terrain does not match (NCC {reg.ncc:.2f} < {MIN_NCC})"
        if why is not None:
            alt = None
            for seed in (seeds or []):            # (shift, label[, where the terrain lines up])
                shift, label = seed[0], seed[1]
                at = np.asarray(seed[2], float) if len(seed) > 2 else None
                alt = self._check_shift(frame, np.asarray(shift, float), label, at) if verify else None
                if alt is not None:
                    break
            if alt is None and verify and hints:
                alt = self._terrain_register(frame, hints)
            if alt is None:
                reg.reason = why
                return reg
            reg = alt
        reg.ok, reg.reason = True, (reg.reason or "merged")
        if commit:
            self._ingest(frame, reg.M, reg)
        return reg

    def place_near(self, frame: Frame, x: float, y: float, near: float = 900.0,
                   strict: bool = False) -> Registration:
        """Line up a screenshot dropped by hand with its centre near (x, y) in atlas coordinates:
        only placements within `near` of that spot count (maps first, then terrain).  Does not
        commit; reg.ok False when nothing near there fits.  strict=True keeps the normal evidence
        thresholds (the spot is only a search hint, e.g. what the window shows); otherwise the
        spot counts as evidence (a hand drop) and fewer agreeing maps are accepted."""
        if any(f["sha"] == frame.sha for f in self.frames):
            return Registration(False, "this screenshot is already in the atlas")
        seed = np.array([x, y], float)
        if not self.frames:
            return Registration(True, "first frame", np.array([[1, 0, 0], [0, 1, 0]], float))
        best = None
        _, tried = register(frame, self.points(), self.footprints())
        # also refine straight from the dropped position (the vote may not list a peak there)
        src = frame.pts[frame.usable]
        if len(src) and len(self.nodes):
            M, pairs, rmse = refine(src, self.points(), (x, y))
            moved = apply(M, src)
            inside = np.zeros(len(src), bool)
            for FM, fw, fh, FR in self.footprints():
                inside |= _inside_rect(moved, FM, fw, fh, FR)
            n_in = int(inside.sum())
            tried = list(tried) + [Registration(False, "", M, len(pairs), rmse, n_in, n_in,
                                                len(pairs) / max(1, n_in))]
        for r in sorted(tried, key=lambda r: (-r.inliers, r.rmse)):
            if r.M is None or np.hypot(*(r.M[:, 2] - seed)) > near:
                continue
            if r.inliers < (MIN_INLIERS if strict else DROP_MIN_INLIERS) or r.ratio < MIN_OVERLAP_RATIO:
                continue
            self._verify(frame, r)
            # the drop point is evidence too: fewer agreeing maps are enough when the terrain
            # check is the stricter one used for terrain-only placements
            need = MIN_NCC if (strict or r.inliers >= MIN_INLIERS or r.ratio >= 0.5) else TERRAIN_MIN_NCC
            if r.ncc_pixels >= 15000 and r.ncc >= need:
                best = r
                break
        if best is None:                      # terrain against the screenshots around the spot
            centres = []
            for f in self.frames:
                H = screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
                c = persp(H, [[f["w"] / 2, f["h"] / 2]])[0]
                centres.append((float(np.hypot(*(c - seed))), f["name"]))
            hints = [n for d, n in sorted(centres)[:10] if d < near + 2500]
            alt = self._terrain_register(frame, hints) if hints else None
            if alt is not None and np.hypot(*(alt.M[:, 2] - seed)) <= near:
                best = alt
        if best is None:
            return Registration(False, f"nothing within {near:.0f} units of where it was dropped lines up",
                                np.array([[1, 0, x], [0, 1, y]], float))
        best.ok = True
        best.reason = best.reason or "placed near the drop point"
        return best

    def _parallax_ok(self, frame: Frame, reg: Registration) -> bool:
        """Mountainous ground: raised maps shift up to ~45 units between screenshots, so few land
        within the 5 px the agreement count uses.  Second chance: enough exact matches AND most
        maps within PARALLAX_TOL (wrong spots stay under 20% there; the terrain check follows)."""
        if reg.M is None or reg.inliers < PARALLAX_MIN_INLIERS:
            return False
        src = frame.pts[frame.usable]
        moved = apply(reg.M, src)
        P = self.points()
        n = max(1, min(reg.overlap_src, reg.overlap_dst))
        loose = len(mutual_pairs(moved, P, PARALLAX_TOL)) / n
        if loose >= PARALLAX_RATIO:
            reg.reason = f"merged (raised ground: {loose:.0%} of maps within {PARALLAX_TOL:.0f} px)"
            return True
        return False

    def commit_frame(self, frame: Frame, reg: Registration) -> None:
        """add a frame placed with add_frame(..., commit=False)"""
        if any(f["sha"] == frame.sha for f in self.frames):
            return
        self._ingest(frame, reg.M, reg)

    def _ingest(self, frame: Frame, M: np.ndarray, reg: Registration) -> None:
        moved = apply(M, frame.pts)
        atlas_pts = self.points()
        mapping: dict[int, int] = {}
        # greedy one-to-one node merge, closest pairs first
        if len(atlas_pts):
            d = np.linalg.norm(moved[:, None, :] - atlas_pts[None, :, :], axis=2)
            order = np.dstack(np.unravel_index(np.argsort(d, axis=None), d.shape))[0]
            used_a = set()
            for i, j in order:
                if d[i, j] > MERGE_TOL:
                    break
                if int(i) in mapping or int(j) in used_a:
                    continue
                mapping[int(i)], _ = int(j), used_a.add(int(j))
        new_nodes = 0
        on_hud = getattr(frame, "on_hud", np.zeros(len(moved), bool))
        hud_skipped = 0
        for i, p in enumerate(moved):
            if on_hud[i] and i not in mapping:
                hud_skipped += 1
                continue                      # a "node" on the game UI: never enters the atlas
            n = frame.nodes[i]
            if i in mapping:
                a = self.nodes[mapping[i]]
                a["x"] = (a["x"] * a["n"] + p[0]) / (a["n"] + 1)
                a["y"] = (a["y"] * a["n"] + p[1]) / (a["n"] + 1)
                a["n"] += 1
                a["frames"].append(frame.name)
                a["tower"] = a["tower"] or bool(n["tower"])
                a["icon"] = a.get("icon") or n.get("icon", "")
                a["hidden"] = a["hidden"] and bool(n["hidden"] or n["unverified"])
                if n["hidden"] or n["unverified"]:
                    a.setdefault("guessed_in", []).append(frame.name)   # only a guess there (no map base seen)
                a.setdefault("sources", []).append(str(n.get("source", "")).split("#")[0])
            else:
                mapping[i] = len(self.nodes)
                self.nodes.append({"x": float(p[0]), "y": float(p[1]), "n": 1, "frames": [frame.name],
                                   "tower": bool(n["tower"]), "icon": n.get("icon", ""),
                                   "hidden": bool(n["hidden"] or n["unverified"]),
                                   "guessed_in": [frame.name] if (n["hidden"] or n["unverified"]) else [],
                                   "sources": [str(n.get("source", "")).split("#")[0]]})
                new_nodes += 1
        mapped_ids = set(mapping.values())
        seen_now = set()
        for a, b, conf, status in frame.edges:
            ia, ib = mapping.get(a), mapping.get(b)
            if ia is None or ib is None or ia == ib:
                continue
            key = (min(ia, ib), max(ia, ib))
            seen_now.add(key)
            e = self.edges.setdefault(key, {"seen": 0, "could": 0, "confirmed": False})
            e["seen"] += 1
            e["confirmed"] = e["confirmed"] or status == "confirmed"
        # an edge "could" have been seen by this frame when both of its ends were visible in it
        for key, e in self.edges.items():
            if key[0] in mapped_ids and key[1] in mapped_ids:
                e["could"] += 1
        # landmarks: merge same kind nearby, otherwise add
        for lm in frame.landmarks:
            p = apply(M, persp(frame.R, [[lm["x"], lm["y"]]]))[0]
            for ex in self.landmarks:
                if ex["kind"] == lm["kind"] and math.hypot(ex["x"] - p[0], ex["y"] - p[1]) < LANDMARK_MERGE:
                    ex["x"] = (ex["x"] * ex["n"] + p[0]) / (ex["n"] + 1)
                    ex["y"] = (ex["y"] * ex["n"] + p[1]) / (ex["n"] + 1)
                    ex["n"] += 1
                    ex["conf"] = max(ex["conf"], lm["conf"])
                    break
            else:
                self.landmarks.append({"kind": lm["kind"], "x": float(p[0]), "y": float(p[1]), "n": 1,
                                       "conf": lm["conf"], "source": lm["source"]})
        self._merge_icons(frame, M)
        reg.reason = reg.reason or "merged"
        self.frames.append({"name": frame.name, "path": frame.path, "sha": frame.sha, "w": frame.w,
                            "h": frame.h, "M": M.tolist(), "horizon": _horizon_of(frame),
                            "stats": {"inliers": reg.inliers, "rmse": round(reg.rmse, 2),
                                      "ncc": round(reg.ncc, 3), "ratio": round(reg.ratio, 2),
                                      "reference": reg.ref_frame, "reason": reg.reason},
                            "new_nodes": new_nodes, "matched_nodes": len(frame.pts) - new_nodes - hud_skipped,
                            "hud_nodes_dropped": hud_skipped})

    def _verify(self, frame: Frame, reg: Registration) -> None:
        """terrain NCC against the placed screenshots that overlap the new one most"""
        img_new = self.image(frame.path)
        best_ncc, best_n, best_ref = -1.0, 0, ""
        H_new = screen_to_atlas(reg.M, frame.R)
        c_new = persp(H_new, [[frame.w / 2, frame.h / 2]])[0]
        for f in self.frames:
            H_ref = screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
            c_ref = persp(H_ref, [[f["w"] / 2, f["h"] / 2]])[0]
            if np.hypot(*(c_ref - c_new)) > 1.6 * max(f["w"], frame.w):
                continue                  # too far apart to overlap: skip the pixel check
            ncc, n = terrain_ncc(self.image(f["path"]), img_new, np.linalg.inv(H_ref) @ H_new)
            if n >= 15000 and ncc > best_ncc:
                best_ncc, best_n, best_ref = ncc, n, f["name"]
        reg.ncc, reg.ncc_pixels, reg.ref_frame = max(best_ncc, 0.0), best_n, best_ref

    # -------- terrain fallback
    _feat_cache: dict = {}

    def _features(self, path: str, R: np.ndarray):
        key = path
        if key in Atlas._feat_cache:
            pts, d16 = Atlas._feat_cache[key]
            return pts, (None if d16 is None else d16.astype(np.float32))
        img = self.image(path)
        sift = cv2.SIFT_create(6000)       # dark / foggy screenshots need many to find enough matches
        k, d = sift.detectAndCompute(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), _valid_mask(img))
        pts = persp(R, np.float32([p.pt for p in k])) if k else np.zeros((0, 2))
        Atlas._feat_cache[key] = (pts, None if d is None else d.astype(np.float16))   # ~1.5 MB each
        while len(Atlas._feat_cache) > 300:          # ~1 MB each
            Atlas._feat_cache.pop(next(iter(Atlas._feat_cache)))
        return pts, d

    def _terrain_register(self, frame: Frame, hints: list[str]) -> Registration | None:
        """Shift from terrain features (flattened coordinates) against hinted screenshots.  The
        game reuses identical terrain pieces in different places, so the result must also pass a
        stricter whole-overlap terrain check, and any maps in the overlap must agree."""
        by_name = {f["name"]: f for f in self.frames}
        pn, dn = self._features(frame.path, frame.R)
        if dn is None or len(pn) < 50:
            return None
        matcher = cv2.BFMatcher()
        best = None
        for name in hints:
            f = by_name.get(name)
            if f is None:
                continue
            pr, dr = self._features(f["path"], self.frame_R(f))
            if dr is None or len(pr) < 50:
                continue
            m = matcher.knnMatch(dn, dr, k=2)
            g = [x[0] for x in m if len(x) == 2 and x[0].distance < .75 * x[1].distance]
            if len(g) < TERRAIN_MIN_AGREE:
                continue
            d = pr[[x.trainIdx for x in g]] - pn[[x.queryIdx for x in g]]
            votes = [(int((np.hypot(*(d - d[k]).T) < 6).sum()), k) for k in range(len(d))]
            n_agree, k = max(votes)
            if n_agree < TERRAIN_MIN_AGREE:
                continue
            inl = np.hypot(*(d - d[k]).T) < 6
            t_ref = np.array(f["M"], float)[:, 2]
            raw = np.median(d[inl], axis=0)
            if best is None or n_agree > best[0]:
                best = (n_agree, t_ref + raw / TERRAIN_SCALE, name, t_ref + raw)
        if best is None:
            return None
        n_agree, shift, ref, at = best
        return self._check_shift(frame, shift, f"terrain ({n_agree} features agree vs {ref})", at)

    def _check_shift(self, frame: Frame, shift: np.ndarray, label: str,
                     terrain_at: np.ndarray | None = None) -> Registration | None:
        """Accept a terrain-proposed shift only if the whole overlap correlates (stricter than the
        map route) and the maps in the overlap don't clearly contradict it.  `shift` is in map units;
        `terrain_at` is where the terrain pixels line up (TERRAIN_SCALE parallax): the pixel check is
        done there, the map position is what gets stored."""
        M = np.array([[1, 0, shift[0]], [0, 1, shift[1]]], float)
        src = frame.pts[frame.usable]
        M2, pairs, rmse = (refine(src, self.points(), (shift[0], shift[1])) if len(src) and len(self.nodes)
                           else (M, [], 99.0))
        moved = apply(M, src)
        inside = np.zeros(len(src), bool)
        for FM, fw, fh, FR in self.footprints():
            inside |= _inside_rect(moved, FM, fw, fh, FR)
        n_in = int(inside.sum())
        ratio = len(pairs) / max(1, n_in)
        # Thin far-away overlaps (top strip of a screenshot, under the header, in fog) show
        # different maps to each screenshot, so map agreement only vetoes a clear contradiction.
        loose = len(mutual_pairs(moved[inside], self.points(), 20)) if n_in else 0
        if n_in >= 12 and loose == 0:
            return None
        if len(pairs) >= 3 and np.hypot(*(M2[:, 2] - shift)) < 10:
            M = M2                                   # maps refine the terrain shift
        reg = Registration(False, "", M, len(pairs), rmse, n_in, n_in, ratio)
        if terrain_at is not None:            # pixel check where the terrain lines up
            chk = Registration(False, "", M.copy(), len(pairs), rmse, n_in, n_in, ratio)
            chk.M[:, 2] += np.asarray(terrain_at, float) - shift
            self._verify(frame, chk)
            reg.ncc, reg.ncc_pixels, reg.ref_frame = chk.ncc, chk.ncc_pixels, chk.ref_frame
        else:
            self._verify(frame, reg)
        if reg.ncc_pixels < 15000 or reg.ncc < TERRAIN_MIN_NCC:
            return None
        reg.reason = label
        return reg

    def terrain_link(self, a: Frame, b: Frame) -> tuple[int, np.ndarray]:
        """Terrain features between two screenshots (placed or not): how many agree on one
        shift, and that shift in flattened coordinates (t_b = t_a + shift)."""
        pa, da = self._features(a.path, a.R)
        pb, db = self._features(b.path, b.R)
        if da is None or db is None or len(pa) < 50 or len(pb) < 50:
            return 0, np.zeros(2)
        m = cv2.BFMatcher().knnMatch(db, da, k=2)
        g = [x[0] for x in m if len(x) == 2 and x[0].distance < .75 * x[1].distance]
        if len(g) < TERRAIN_MIN_AGREE:
            return 0, np.zeros(2)
        d = pa[[x.trainIdx for x in g]] - pb[[x.queryIdx for x in g]]
        n_agree, k = max((int((np.hypot(*(d - d[q]).T) < 6).sum()), q) for q in range(len(d)))
        inl = np.hypot(*(d - d[k]).T) < 6
        return n_agree, np.median(d[inl], axis=0) / TERRAIN_SCALE

    def _merge_icons(self, frame: Frame, M: np.ndarray) -> None:
        """icon badges: the same badge (or an unidentified ring at the same spot) merges. Each badge's map
        base is its ROW's base, found in this screenshot's own pixels (up to 5 badges side by side, ~36 px
        apart, the map under the row's middle - user): grouping rows later from merged atlas positions split
        rows whose copies from two passes landed a little apart, and doubled their map."""
        icons = getattr(frame, "icons", [])
        base_of = row_bases(icons)
        for k, m in enumerate(icons):
            p = apply(M, persp(frame.R, [[m["x"], m["y"]]]))[0]
            b = apply(M, persp(frame.R, [base_of[k]]))[0]
            for ex in self.icons:
                same = ex["name"] == m["name"] or "Unidentified" in (ex["name"], m["name"])
                if same and math.hypot(ex["x"] - p[0], ex["y"] - p[1]) < ICON_MERGE:
                    k = ex["n"]
                    for key, v in (("x", p[0]), ("y", p[1]), ("bx", b[0]), ("by", b[1])):
                        ex[key] = (ex[key] * k + float(v)) / (k + 1)
                    ex["n"] += 1
                    ex["frames"].append(frame.name)
                    if ex["name"] == "Unidentified" and m["name"] != "Unidentified":
                        ex["name"], ex["source"] = m["name"], m["source"]
                    ex["score"] = max(ex["score"], m["score"])
                    break
            else:
                self.icons.append({"name": m["name"], "x": float(p[0]), "y": float(p[1]), "bx": float(b[0]),
                                   "by": float(b[1]), "n": 1, "frames": [frame.name], "score": m["score"],
                                   "source": m["source"]})

    def rebuild_icons(self, frames_by_name: dict) -> None:
        """Re-merge every screenshot's badges from its (re-labelled) detection, e.g. after
        icons were re-detected or taught.  Screenshots without a detection are skipped."""
        self.icons = []
        for f in self.frames:
            fr = frames_by_name.get(f["name"])
            if fr is not None:
                self._merge_icons(fr, np.array(f["M"], float))

    # -------- export
    def to_json(self) -> dict:
        def strength(e):
            return e["seen"] / max(1, e["could"])
        return {
            "version": "atlas-builder-0.2",
            "frames": [{**{k: v for k, v in f.items() if k != "stats"}, **f["stats"]} for f in self.frames],
            "nodes": [{"id": i, **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in n.items()}}
                      for i, n in enumerate(self.nodes)],
            "edges": [{"a": a, "b": b, "seen": e["seen"], "could": e["could"],
                       "strength": round(strength(e), 2), "confirmed": e["confirmed"]}
                      for (a, b), e in sorted(self.edges.items())],
            "landmarks": self.landmarks,
            "bookmarks": self.bookmarks,
            "icons": self.icons,
            "city_types": self.city_types,
            "city_auto": self.city_auto,
            "landmark_edits": self.landmark_edits,
            "biome_edits": self.biome_edits,
            "locks": self.locks,
            "lock_scanned": self.lock_scanned,
            "final": self.final,
        }

    def save(self, path) -> None:
        atlas_io.write_text_atomic(path, json.dumps(self.to_json(), indent=1))
        # saved detections live next to the atlas; a copy saved elsewhere (undo snapshot) has none, so keep
        # pointing at the real ones (v1.00: every auto-add re-traced ~100 screenshots from their images)
        new_dir = Path(path).with_name(Path(path).stem + "_frames")
        if getattr(self, "frames_dir", None) is None or new_dir.is_dir():
            self.frames_dir = new_dir

    @staticmethod
    def load(path) -> "Atlas":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        at = Atlas()
        at.frames_dir = Path(path).with_name(Path(path).stem + "_frames")   # saved detections (paths, dashes)
        at.nodes = [{"x": n["x"], "y": n["y"], "n": n["n"], "frames": n["frames"], "tower": n["tower"],
                     "icon": n.get("icon", ""), "hidden": n["hidden"], "sources": n.get("sources", []),
                     **({"guessed_in": n["guessed_in"]} if "guessed_in" in n else {})}
                    for n in d["nodes"]]
        at.edges = {(e["a"], e["b"]): {"seen": e["seen"], "could": e["could"], "confirmed": e["confirmed"]}
                    for e in d["edges"]}
        at.landmarks = d["landmarks"]
        at.bookmarks = d.get("bookmarks", [])
        at.icons = d.get("icons", [])
        at.final = d.get("final")
        at.city_types = d.get("city_types", [])
        at.city_auto = d.get("city_auto", [])
        at.landmark_edits = d.get("landmark_edits", [])
        at.biome_edits = d.get("biome_edits", [])
        at.locks = d.get("locks", [])
        at.lock_scanned = d.get("lock_scanned", [])
        keys = ("inliers", "rmse", "ncc", "ratio", "reference", "reason")
        at.frames = [{**{k: v for k, v in f.items() if k not in keys},
                      "stats": {k: f.get(k) for k in keys}} for f in d["frames"]]
        base = Path(path).resolve().parent
        for f in at.frames:
            f["path"] = _find_screenshot(f["path"], base)
        return at

    # -------- composite image
    def composite(self, max_pixels: int = 36_000_000, with_weight: bool = False):
        """stitched terrain: each spot from the screenshot that shows it most centrally.
        with_weight also returns the per-pixel weight, so screenshots can be pasted in later
        (paste_into) without rebuilding everything."""
        corners = []
        frames = [f for f in self.frames if Path(f["path"]).exists()]   # moved/deleted shots: skip
        if not frames:
            empty = (np.zeros((1, 1, 3), np.uint8), (0, 0, 1.0))
            return (*empty, np.zeros((1, 1), np.float32)) if with_weight else empty
        for f in frames:
            c = np.array([[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]], float)
            corners.append(persp(screen_to_atlas(np.array(f["M"], float), self.frame_R(f)), c))
        allc = np.vstack(corners)
        x0, y0 = np.floor(allc.min(axis=0)).astype(int)
        x1, y1 = np.ceil(allc.max(axis=0)).astype(int)
        W, H = int(x1 - x0), int(y1 - y0)
        scale = min(1.0, math.sqrt(max_pixels / max(1, W * H)))
        CW, CH = max(1, int(W * scale)), max(1, int(H * scale))
        best_w = np.zeros((CH, CW), np.float32)
        canvas = np.zeros((CH, CW, 3), np.uint8)
        self.paste_into(canvas, best_w, (x0, y0, scale), frames)
        if with_weight:
            return canvas, (x0, y0, scale), best_w
        return canvas, (x0, y0, scale)

    def paste_into(self, canvas, best_w, origin, frames) -> bool:
        """warp screenshots into an existing stitched canvas, each only into its own patch.
        False when one falls outside the canvas (then rebuild with composite)."""
        x0, y0, scale = origin
        CH, CW = best_w.shape
        T = np.array([[scale, 0, -x0 * scale], [0, scale, -y0 * scale], [0, 0, 1]], float)
        inside = True
        for f in frames:
            if not Path(f["path"]).exists():
                continue
            Hc = T @ screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
            c = persp(Hc, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
            if c[:, 0].min() < -1 or c[:, 1].min() < -1 or c[:, 0].max() > CW + 1 or c[:, 1].max() > CH + 1:
                inside = False
            bx0, by0 = np.maximum(np.floor(c.min(axis=0)).astype(int), 0)
            bx1, by1 = np.minimum(np.ceil(c.max(axis=0)).astype(int), [CW, CH])
            if bx1 <= bx0 or by1 <= by0:
                continue
            Hroi = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]], float) @ Hc
            size = (int(bx1 - bx0), int(by1 - by0))
            img = self.image(f["path"])
            valid = (_valid_mask(img) > 0).astype(np.uint8) * 255     # (the cached mask is read-only)
            dist = cv2.distanceTransform(valid, cv2.DIST_L2, 3)
            wmap = cv2.warpPerspective(dist, Hroi, size, flags=cv2.INTER_LINEAR, borderValue=0)
            pix = cv2.warpPerspective(img, Hroi, size, flags=cv2.INTER_LINEAR, borderValue=0)
            sub_w = best_w[by0:by1, bx0:bx1]
            take = wmap > sub_w
            canvas[by0:by1, bx0:bx1][take] = pix[take]
            sub_w[take] = wmap[take]
        return inside


def render_overlay(atlas: "Atlas", canvas: np.ndarray, origin) -> np.ndarray:
    """Nodes coloured by how many screenshots saw them; edges by how many agreed.

    node ring: orange = 1 screenshot, green = 2, cyan = 3+.
    edge: cyan = every screenshot that could see it did; amber = only one screenshot could
    see it; red = some screenshots saw it and others (that could) did not -> review.
    """
    x0, y0, sc = origin
    out = canvas.copy()
    P = lambda x, y: (int((x - x0) * sc), int((y - y0) * sc))
    if atlas.final:
        return _render_final(atlas, out, P)
    j = atlas.to_json()
    for e in j["edges"]:
        a, b = j["nodes"][e["a"]], j["nodes"][e["b"]]
        if e["could"] < 2:
            col = (0, 200, 255)
        elif e["seen"] >= e["could"]:
            col = (255, 230, 0)
        else:
            col = (60, 60, 255)
        cv2.line(out, P(a["x"], a["y"]), P(b["x"], b["y"]), col, 2, cv2.LINE_AA)
    for n in j["nodes"]:
        k = len(set(n["frames"]))
        col = {1: (0, 150, 255), 2: (0, 255, 200)}.get(k, (255, 255, 0))
        cv2.circle(out, P(n["x"], n["y"]), 9, col, 2, cv2.LINE_AA)
    for lm in j["landmarks"]:
        p = P(lm["x"], lm["y"])
        cv2.rectangle(out, (p[0] - 30, p[1] - 60), (p[0] + 30, p[1] + 10), (70, 240, 100), 2)
        cv2.putText(out, lm["kind"], (p[0] - 28, p[1] - 64), cv2.FONT_HERSHEY_SIMPLEX, .6, (70, 240, 100), 2)
    return out


def _render_final(atlas: "Atlas", out: np.ndarray, P) -> np.ndarray:
    """The atlas-wide result: paths cyan = 2+ screenshots agree, amber = one screenshot,
    magenta = abyss chain; nodes cyan = confirmed / from icon, orange = one screenshot,
    grey = doubtful; red x = removed (ghost / river glow)."""
    fin = atlas.final
    N = fin["nodes"]
    for e in fin["paths"]:
        a, b = N[e["a"]], N[e["b"]]
        strong = e.get("seen_in", e["frames"]) >= 2 or e.get("both_ends")
        col = (230, 80, 255) if e["abyss"] else (255, 220, 40) if strong else (0, 185, 255)
        line = e.get("line") or [[a["x"], a["y"]], [b["x"], b["y"]]]
        cv2.polylines(out, [np.array([P(x, y) for x, y in line], np.int32)], False, col, 2, cv2.LINE_AA)
    for n in N:
        p = P(n["x"], n["y"])
        st = n["status"]
        if st == "removed":
            if not n["why"].startswith("joined"):
                cv2.drawMarker(out, p, (60, 60, 255), cv2.MARKER_TILTED_CROSS, 12, 2)
            continue
        col = {"confirmed": (255, 220, 40), "icon": (255, 220, 40), "single": (0, 150, 255),
               "disputed": (0, 150, 255), "doubtful": (150, 150, 150)}.get(st, (255, 255, 255))
        cv2.circle(out, p, 8, col, 2, cv2.LINE_AA)
        if n["icons"]:
            txt = "+".join(sorted(set(n["icons"])))
            cv2.putText(out, txt, (p[0] + 9, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, .38, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, txt, (p[0] + 9, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, .38, (230, 140, 255), 1, cv2.LINE_AA)
    for lm in fin["landmarks"]:
        p = P(lm["x"], lm["y"])
        col = (60, 60, 255) if lm["status"].startswith("removed") else (70, 240, 100)
        cv2.rectangle(out, (p[0] - 30, p[1] - 60), (p[0] + 30, p[1] + 10), col, 2)
        cv2.putText(out, lm["kind"], (p[0] - 28, p[1] - 64), cv2.FONT_HERSHEY_SIMPLEX, .6, col, 2)
    return out
