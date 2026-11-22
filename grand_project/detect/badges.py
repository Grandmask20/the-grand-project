"""detect.badges"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core, icon_refs

from .constants import (
    BADGE_FINDER_FILE,
    BADGE_MIN,
    BADGE_NMS,
    BADGE_ROW_MIN,
    EXPEDITION,
    EXPEDITION_WATER,
    HIDDEN_SNAP,
    ICON_CLEAR,
    ICON_RIM_R,
    INFLUENCE_MIN,
    MAP_NMS,
    RIM_CANDIDATE,
    ROW_DY,
    ROW_RESCUE,
    ROW_STEP,
    SPECIAL_ICONS,
    SPECIAL_R,
)
from .maps import _keep_best
from .models import _models, load_model


def _finder() -> dict:
    """The icon finder's frozen data, loaded once from BADGE_FINDER_FILE (tools/freeze_badge_finder.py).

    The rim template is the average icon as seen on screen, used only on the rim (radii ICON_RIM_R). Never the
    stored icon pictures: those only NAME an icon.

    Returns:
        Dict with "T" (zero-mean, unit-length rim template), "M" (rim mask), "n" (rim pixel count) and "special"
        (name -> whole-icon template of the icons with their own rim).
    """
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


def _in_water(img: np.ndarray, x: float, y: float) -> bool:
    """Whether the icon's map node (ROW_DY px under it) is in the water zone.

    Enough open water around it: of the classified ground within EXPEDITION_WATER's radius, at least its share is
    water (and more than 200 px are classified).

    Args:
        img: BGR screenshot (1080p).
        x: Icon centre x in screen px.
        y: Icon centre y in screen px.

    Returns:
        True when the map node stands in open water.
    """
    from grand_project.finalize import landmarks as fl

    cls, bad = fl.ground_of(img)  # the per-screenshot ground classes (kept for recent screenshots)
    R, need = EXPEDITION_WATER
    h, w = cls.shape
    X, Y = int(round(x)), int(round(y + ROW_DY))
    x0, x1, y0, y1 = max(0, X - R), min(w, X + R + 1), max(0, Y - R), min(h, Y + R + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    c = cls[y0:y1, x0:x1][(np.hypot(xx - X, yy - Y) <= R) & ~bad[y0:y1, x0:x1]]
    c = c[c >= 0]
    return len(c) > 200 and float((c == 0).mean()) >= need


def special_icons(img: np.ndarray) -> list[dict]:
    """Icons with their own rim (SPECIAL_ICONS), found and named by a whole-icon template.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        Icons as dicts {"x", "y", "score", "name", "dist"}: template peaks above the icon's SPECIAL_ICONS threshold,
        whole on screen and clear of the HUD.
    """
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
    """Per pixel: correlation of the ring around it (radii ICON_RIM_R) with an icon's rim.

    The inside (which icon) and the outside (the map) are not looked at.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        (h, w) float32 array of normalised correlation scores.
    """
    f = _finder()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    a = cv2.filter2D(g, -1, f["T"], borderType=cv2.BORDER_REFLECT)
    s1 = cv2.filter2D(g, -1, f["M"], borderType=cv2.BORDER_REFLECT)
    s2 = cv2.filter2D(g * g, -1, f["M"], borderType=cv2.BORDER_REFLECT)
    return a / np.sqrt(np.maximum(s2 - s1 * s1 / f["n"], 1e-3))


def _clear(img: np.ndarray) -> np.ndarray:
    """Per pixel: an icon centred here is whole on the screen and clear of the HUD.

    User: the HUD is masked before detection; an icon half under it or off the screen is read from another
    screenshot. A pixel is clear when it is at least ICON_CLEAR px from the HUD and the screen edge.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        (h, w) bool array.
    """
    h, w = img.shape[:2]
    free = (core.hud_mask(w, h) == 0).astype(np.uint8)
    free[[0, -1], :] = 0
    free[:, [0, -1]] = 0
    return cv2.distanceTransform(free, cv2.DIST_L2, 3) >= ICON_CLEAR


def badge_candidates(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Icon candidates: circles whose rim looks like an icon's.

    Local maxima (9x9 px) of rim_score above RIM_CANDIDATE, clear of the HUD and screen edge.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        (pts, ring, extra): (n, 2) int array of candidate x, y in screen px, their (n,) rim score, and the same
        score as an (n, 1) 'extra' array.
    """
    sc = rim_score(img)
    pk = (sc >= cv2.dilate(sc, np.ones((9, 9), np.uint8))) & (sc > RIM_CANDIDATE) & _clear(img)
    ys, xs = np.nonzero(pk)
    pts = np.stack([xs, ys], 1).reshape(-1, 2)
    v = sc[ys, xs]
    return pts, v, v[:, None]


_ANG = np.linspace(0, 2 * np.pi, 24, endpoint=False)
_RADII = np.arange(6, 14.5, 1.0)


def badge_features(img: np.ndarray, pts: np.ndarray, ring: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """Icon classifier features per candidate, from the rim only.

    Per radius 6..14 px: how even the ring is all round, its gold share and saturation; the shape of the
    brightness profile across the radii; and the rim score. Nothing from inside the rim.

    Args:
        img: BGR screenshot (1080p).
        pts: (n, 2) array of candidate x, y in screen px (badge_candidates).
        ring: (n,) rim score of each candidate.
        extra: (n, 1) extra scores from badge_candidates (not used).

    Returns:
        (n, 4 * len(_RADII) + 2) float32 feature array.
    """
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
    """Training labels for icon candidates from a screenshot's truth.

    Args:
        pts: (n, 2) array of candidate x, y in screen px.
        t: The screenshot's truth entry with "badges" (each with "x", "y").

    Returns:
        (n,) int array: 1 = the candidate closest to a labelled badge (within 6 px), -1 = other candidates on it
        (within 12 px, left out of training), 0 = not an icon.
    """
    lab = np.zeros(len(pts), int)
    for b in t["badges"]:
        d = np.hypot(pts[:, 0] - b["x"], pts[:, 1] - b["y"])
        lab[(d < 12) & (lab == 0)] = -1
        j = int(np.argmin(d)) if len(d) else 0
        if len(d) and d[j] <= 6:
            lab[j] = 1
    return lab


def _row_slot(x: float, y: float, maps: list[dict]) -> bool:
    """Whether x, y is where a badge of a row of 1-5 above one of the map nodes would sit.

    Rows sit ROW_DY px above their map node, centred on it, with badges ROW_STEP px apart (so slots are half steps
    for even rows); 5 px tolerance.

    Args:
        x: Point x in screen px.
        y: Point y in screen px.
        maps: Map nodes as dicts with "x", "y".

    Returns:
        True when the point is on a row slot of any map node.
    """
    for m in maps:
        dx, dy = x - m["x"], y - (m["y"] - ROW_DY)
        if abs(dy) <= 5 and abs(dx) <= 2 * ROW_STEP + 5 and min(abs(dx - k * ROW_STEP / 2) for k in range(-4, 5)) <= 5:
            return True
    return False


def name_badge(img: np.ndarray, x: float, y: float, names: list[str], F: np.ndarray) -> tuple[str, float]:
    """Name an icon by its closest badge picture (stored + labelled), trying +-icon_refs.SHIFT px shifts.

    Only names whose stored pictures have a bright part of the same colour count (icon_refs.colour_ok).

    Args:
        img: BGR screenshot (1080p).
        x: Icon centre x in screen px.
        y: Icon centre y in screen px.
        names: Name of each picture row in F.
        F: (len(names), k) picture features (icon_refs.feature).

    Returns:
        (name, 1 - correlation): "Unidentified" when the closest picture is further than icon_refs.MAX_DIST, and
        ("Unidentified", 9.0) when the icon runs off the screenshot or there are no pictures.
    """
    found = icon_refs.shift_dists(img, x, y, F) if len(names) else None
    if found is None:
        return "Unidentified", 9.0
    d, c = found
    d[~icon_refs.colour_ok(names, icon_refs.refs().colours, c)] = 9.0
    k = int(np.argmin(d))
    return (names[k] if d[k] <= icon_refs.MAX_DIST else "Unidentified"), float(d[k])


def badge_rows(icons: list[dict]) -> list[list[dict]]:
    """Group icons side by side into rows.

    Same height (5 px), ROW_STEP (36 px) apart; one badge of a row may be missed, so 72 px also joins.

    Args:
        icons: Icons as dicts with "x", "y".

    Returns:
        Rows of icons, each sorted left to right.
    """
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


def naming_book() -> dict:
    """The icon model's labelled pictures, which the classical namer uses beside the stored ones (``badges_from``).

    Loaded once (into ``models._models``, where the classical detector keeps it). Without an icon model in the
    reference database the set is empty and icons are named from the stored pictures alone.

    Returns:
        {"names": [...], "F": (m, k) picture features}.
    """
    if "badges" not in _models:
        model = load_model("badges")
        if model is None:
            return {"names": [], "F": np.zeros((0, 0), np.float32)}
        _models["badges"] = model
    return _models["badges"]


def name_found_icons(
    img: np.ndarray, icons: list[dict], book: dict, *, influence_min: float | None = INFLUENCE_MIN
) -> list[dict]:
    """Name the icons a finder found, as the classical detector names them.

    The one naming step of both detectors (the classical rim finder's icons and the RF-DETR model's): each icon is
    named by its closest picture among the stored pictures (``icon_refs``) and the icon model's (``book``). Icons
    with their own rim (``SPECIAL_ICONS``) are found and named by their whole-icon template and replace a found icon
    on them. Expedition only appears in the water zone (user); an icon named "not an icon" is dropped.

    Args:
        img: BGR screenshot (1080p).
        icons: Found icons, dicts with "x", "y", "score" (kept in the result).
        book: The icon model's labelled pictures (``naming_book``): {"names": [...], "F": (m, k) array}.
        influence_min: An icon named a biome influence needs this score, else it is dropped: the rim finder's
            "very strong rim assurance" (user: weak circles named an influence are usually terrain). None for a
            finder whose score is not the rim finder's probability (the RF-DETR model, trained on reviewed boxes).

    Returns:
        The special icons, then the named found icons as dicts with "name" and "dist" (1 - correlation) added.
    """
    R = icon_refs.refs()
    names = R.names + book["names"]
    F = np.vstack([R.F, book["F"]]) if len(book["names"]) else R.F
    special = special_icons(img)  # own rims: found and named by their template, they win over the rim finder
    out = list(special)
    for b in icons:
        if any(np.hypot(b["x"] - s_["x"], b["y"] - s_["y"]) <= BADGE_NMS for s_ in special):
            continue
        nm, d = name_badge(img, b["x"], b["y"], names, F)
        if influence_min is not None and nm.endswith("Influence") and b["score"] < influence_min:
            continue  # a weak circle named a biome influence is usually terrain (user)
        if nm == EXPEDITION and not _in_water(img, b["x"], b["y"]):
            nm = "Unidentified"  # Expedition only appears in the water zone (user)
        if nm != icon_refs.NOT_A_BADGE:
            out.append(dict(b, name=nm, dist=round(d, 3)))
    return out


def badges_from(
    img: np.ndarray,
    pts: np.ndarray,
    p: np.ndarray,
    book: dict,
    maps: list[dict],
    map_pts: np.ndarray,
    map_p: np.ndarray,
) -> tuple[list, list]:
    """Turn badge probabilities into named icons and more map nodes.

    Icons are candidates with p >= BADGE_MIN, plus weaker ones (>= BADGE_ROW_MIN) that sit next to a found badge
    or on a row slot above a map node. Special icons win over the rim finder. A weak circle named a biome influence
    is usually terrain and is dropped (user); Expedition only appears in the water zone (user). Under a badge row
    with no map found comes the best weak map candidate (source 'badge row'), or else a hidden map (unless a
    visible map is within HIDDEN_SNAP px: that is the row's map - user).

    Args:
        img: BGR screenshot (1080p).
        pts: (n, 2) array of icon candidate x, y in screen px.
        p: (n,) icon probability of each candidate.
        book: Labelled badge pictures kept in the badge model: {"names": [...], "F": (m, k) array}.
        maps: Map nodes found so far, dicts with "x", "y".
        map_pts: (k, 2) array of all map candidates in screen px.
        map_p: (k,) map probability of each map candidate.

    Returns:
        (icons, more): icons as dicts {"x", "y", "score", "name", "dist"} (some with "row": True), and the extra map
        nodes as dicts with "source": "badge row" ("hidden": True for hidden map nodes).
    """
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
    out = name_found_icons(img, icons, book)
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
    """Labelled badge pictures of these screenshots (kept inside the badge model, not in badge_refs).

    Badges labelled "Unidentified" (found but not named yet) count for finding, not naming, and are skipped.

    Args:
        truth: Truth per screenshot name; each entry has "badges" with "x", "y", "name".
        imgs: Screenshot name -> BGR image.
        names: Screenshot names to use.

    Returns:
        {"names": [name, ...], "F": (m, k) float32 picture features (icon_refs.feature)}.
    """
    nm, F = [], []
    for n in names:
        for b in truth[n]["badges"]:
            if b["name"] == "Unidentified":  # a found icon nobody has named yet: counts for finding, not naming
                continue
            c = icon_refs.crop(imgs[n], b["x"], b["y"])
            if c is not None:
                nm.append(b["name"])
                F.append(icon_refs.feature(c))
    return {"names": nm, "F": np.array(F, np.float32)}


def find_badges(
    img: np.ndarray, model: dict, maps: list[dict], map_pts: np.ndarray, map_p: np.ndarray
) -> tuple[list, list]:
    """Find and name the icons of a screenshot, and the map nodes their rows reveal.

    Args:
        img: BGR screenshot (1080p).
        model: The trained "badges" model: {"clf": classifier, "names": [...], "F": picture features}.
        maps: Map nodes found so far, dicts with "x", "y".
        map_pts: (k, 2) array of all map candidates in screen px.
        map_p: (k,) map probability of each map candidate.

    Returns:
        (icons, more) as in badges_from; ([], []) when there are no candidates.
    """
    pts, ring, extra = badge_candidates(img)
    if not len(pts):
        return [], []
    p = model["clf"].predict_proba(badge_features(img, pts, ring, extra))[:, 1]
    return badges_from(img, pts, p, model, maps, map_pts, map_p)
