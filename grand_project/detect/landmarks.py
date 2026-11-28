"""detect.landmarks"""

from __future__ import annotations

import cv2
import numpy as np

from . import citybase
from .badges import badge_rows
from .cache import _per_image
from .constants import (
    CITY_P,
    EXP_REACH,
    EXPEDITION,
    HALL_ORANGE,
    NOT_ON_EXPEDITION,
    ROW_DY,
    STRONGHOLD_EMPTY,
    TOWER_BADGES,
    TOWER_MIN,
    TOWER_NMS,
)

_TP = 220


def tower_features(img: np.ndarray, pts, old_towers: list) -> np.ndarray:
    """Tower classifier features per map node (the spire above it).

    Brightness / colour / vertical edges / green glow / flame in a grid of boxes up to 200 px above it, the width
    of the green glow at its foot, a dark-column profile, and whether the old tower rules found a tower there.

    Args:
        img: BGR screenshot (1080p).
        pts: Map node middles, [(x, y), ...] in screen px.
        old_towers: Towers found by the old rules (old_landmarks), [(x, y), ...]; within 45 px counts.

    Returns:
        (len(pts), k) float32 feature array.
    """
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
                f += [
                    V[sl].mean(),
                    S[sl].mean(),
                    gx[sl].mean() / (gy[sl].mean() + 1),
                    green[sl].mean(),
                    flame[sl].mean(),
                ]
        for a, b in ((0, 12), (12, 24), (24, 36), (36, 50)):
            f.append(
                np.concatenate(
                    [green[Y - 12 : Y + 10, X - b : X - a].ravel(), green[Y - 12 : Y + 10, X + a : X + b].ravel()]
                ).mean()
            )
        col = V[Y - 160 : Y - 20, X - 40 : X + 41].mean(0)
        f += [col[30:51].mean() - np.r_[col[:15], col[-15:]].mean(), col.std()]
        f.append(float(any(np.hypot(t[0] - x, t[1] - y) < 45 for t in old_towers)))
        F.append(f)
    return np.asarray(F, np.float32).reshape(len(F), -1)


@_per_image
def square_buttons(img: np.ndarray) -> list[dict]:
    """The screenshot's square framed buttons (cities.square_buttons), found once: the locked strongholds' hands
    (landmarks_from) and the Expedition ships (ship_markers) are both read from them.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        Buttons as cities.square_buttons gives them (a copy).
    """
    from grand_project import cities as atlas_cities

    return atlas_cities.square_buttons(img)


@_per_image
def old_landmarks(img: np.ndarray) -> dict:
    """The hand-made landmark rules (atlas_towers): towers and purple Breach strongholds.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        {"towers": [(x, y), ...], "strongholds": [(x, y), ...]} in screen px.
    """
    from grand_project import towers as poi

    lms = poi.detect_landmarks(img)
    return {
        "towers": [(landmark.x, landmark.y) for landmark in lms if landmark.kind == "Tower"],
        "strongholds": [(landmark.x, landmark.y) for landmark in lms if landmark.kind == "Breach stronghold"],
    }


def tower_labels(pts, t: dict) -> np.ndarray:
    """Training labels for the tower classifier from a screenshot's truth.

    Args:
        pts: Map node middles, [(x, y), ...] in screen px.
        t: The screenshot's truth entry with "landmarks" (each with "kind", "x", "y").

    Returns:
        (len(pts),) int array: 1 when a labelled Tower is within 25 px, else 0.
    """
    towers = [landmark for landmark in t["landmarks"] if landmark["kind"] == "Tower"]
    return np.array([int(any(np.hypot(tower["x"] - x, tower["y"] - y) < 25 for tower in towers)) for x, y in pts], int)


def deadly_kind(img: np.ndarray, x: float, y: float, nodes=None) -> tuple[str, str]:
    """Decide what a map node with a Deadly Map Boss badge is: City / Hall / plain deadly boss, and why.

    A City's map always stands on the brass barrel (user); beams don't decide it: every city type can show a blue
    one, and the brown lantern structures (Halls) have orange beams. The ocean (Expedition) biome never has a City
    (user's rule).

    Args:
        img: BGR screenshot (1080p).
        x: Map node x in screen px.
        y: Map node y in screen px.
        nodes: Optional detected map nodes to snap the point to (see citybase.barrel_p).

    Returns:
        (kind, why): kind is "City", "Hall" or "Deadly boss map"; why is a short reason.
    """
    from grand_project import finalize as fin

    _sblue, sorange = fin._beam(img, x, y, spread=80)
    if fin._ocean(img, x, y):  # ocean (Expedition) biome: never a City (user's rule)
        if sorange >= HALL_ORANGE:
            return "Hall", "beam on a structure next to it (ocean)"
        return "Deadly boss map", "ocean biome: no cities"
    if citybase.barrel_p(img, x, y, nodes) >= CITY_P:
        return "City", "brass barrel map base"
    if sorange >= HALL_ORANGE:
        return "Hall", "beam on a structure next to it"
    return "Deadly boss map", "normal map base"


def landmarks_from(
    img: np.ndarray, nodes: list[dict], icons: list[dict], tower_p: np.ndarray, old: dict
) -> tuple[list[dict], list[dict]]:
    """Build the landmarks of a screenshot from tower probabilities, icon rows and the old rules.

    Towers: visible map nodes with p >= TOWER_MIN, best first, dropping other map nodes within TOWER_NMS px.
    Deadly Map Boss rows (not a tower's badges) become City / Hall / deadly boss map (deadly_kind). Completed
    (green) cities have no badge and no beam left, but still stand on the barrel. Breach strongholds are locked
    when a hand badge is within 200 px or no map node is inside (STRONGHOLD_EMPTY).

    Args:
        img: BGR screenshot (1080p).
        nodes: Map nodes, dicts with "x", "y" (and "hidden" for hidden map nodes).
        icons: Named icons, dicts with "x", "y", "name".
        tower_p: Tower probability of each visible (not hidden) map node, in order.
        old: Result of old_landmarks.

    Returns:
        (landmarks, nodes): landmarks as dicts {"kind", "x", "y", ...}, and copies of the map nodes with towers
        marked ("tower": True) and hidden maps that were really a tower's badge row removed.
    """
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
    towers = list(out)
    dx, up0, up1 = TOWER_BADGES
    nodes = [
        n
        for n in nodes
        if not (
            n.get("hidden") and any(abs(n["x"] - t["x"]) <= dx and up0 - 30 <= t["y"] - n["y"] <= up1 for t in towers)
        )
    ]
    for row in badge_rows(icons):
        if not any(b["name"] == "MapBossSpecial" for b in row):
            continue
        mx, my = (row[0]["x"] + row[-1]["x"]) / 2, float(np.mean([b["y"] for b in row])) + ROW_DY
        if any(abs(mx - t["x"]) <= dx and up0 <= t["y"] - my + ROW_DY <= up1 for t in towers):
            continue  # a tower's badges, not a map of its own
        kind, why = deadly_kind(img, mx, my, vis)
        out.append({"kind": kind, "x": round(mx, 1), "y": round(my, 1), "why": why})
    # completed (green) cities have no badge and no beam left, but still stand on the barrel
    from grand_project import finalize as fin

    for n in vis:
        x, y = n["x"], n["y"]
        if n.get("tower") or any(
            lm["kind"] in ("City", "Hall", "Deadly boss map") and np.hypot(lm["x"] - x, lm["y"] - y) < 45 for lm in out
        ):
            continue
        if citybase.barrel_p(img, x, y) >= CITY_P and not fin._ocean(img, x, y):
            out.append(
                {"kind": "City", "x": round(float(x), 1), "y": round(float(y), 1), "why": "brass barrel map base"}
            )
    locks = [(b["x"], b["y"]) for b in square_buttons(img) if b["kind"] == "lock"]  # (cities.locks_in)
    for x, y in old["strongholds"]:
        hand = any(np.hypot(x - a, y - b) < 200 for a, b in locks)
        empty = not any(np.hypot(x - n["x"], y - n["y"]) < STRONGHOLD_EMPTY for n in vis)
        kind = "Locked stronghold" if hand or empty else "Breach stronghold"
        out.append(
            {
                "kind": kind,
                "x": float(x),
                "y": float(y),
                "why": "hand badge" if hand else "no maps inside" if empty else "purple structure",
            }
        )
    return out, nodes


def find_landmarks(img: np.ndarray, model, nodes: list[dict], icons: list[dict]) -> tuple[list, list]:
    """Find the landmarks of a screenshot: run the tower model on the visible map nodes, then landmarks_from.

    Args:
        img: BGR screenshot (1080p).
        model: The trained "towers" classifier.
        nodes: Map nodes, dicts with "x", "y" (and "hidden").
        icons: Named icons, dicts with "x", "y", "name".

    Returns:
        (landmarks, nodes) as in landmarks_from.
    """
    old = old_landmarks(img)
    vis = [n for n in nodes if not n.get("hidden")]
    p = (
        model.predict_proba(tower_features(img, [(n["x"], n["y"]) for n in vis], old["towers"]))[:, 1]
        if vis
        else np.zeros(0)
    )
    return landmarks_from(img, nodes, icons, p, old)


def expedition_rules(nodes: list[dict], icons: list[dict], lms: list[dict]) -> tuple[list, list, list]:
    """Apply the ocean (Expedition biome) rules (user's).

    - An Expedition badge sits right above a VISIBLE ocean map: a hidden map under its row is shown (its star base
      is often too unlike the gold-rimmed bases the map model knows).
    - A map with an Expedition badge is never a Hall, Tower or Hideout: those calls are dropped (a Hall keeps its
      Deadly Map Boss badge: a plain deadly boss map; a Hideout badge in the row goes).

    "Under" an Expedition badge means within EXP_REACH (dx, y0..y1 px) of it.

    Args:
        nodes: Map nodes, dicts with "x", "y" (and "hidden", "tower").
        icons: Named icons, dicts with "x", "y", "name".
        lms: Landmarks, dicts with "kind", "x", "y".

    Returns:
        (nodes, icons, landmarks) after the rules; unchanged when there is no Expedition badge.
    """
    dx, y0, y1 = EXP_REACH
    exp = [b for b in icons if b.get("name") == EXPEDITION]
    if not exp:
        return nodes, icons, lms

    def under(x, y):
        """Whether a point lies under an Expedition badge (within EXP_REACH).

        Args:
            x: Point x in screen px.
            y: Point y in screen px.

        Returns:
            True when an Expedition badge is just above the point.
        """
        return any(abs(x - b["x"]) <= dx and y0 <= y - b["y"] <= y1 for b in exp)

    nodes = [dict(n) for n in nodes]
    for n in nodes:
        if n.get("hidden") and under(n["x"], n["y"]):
            n["hidden"] = False
            n["source"] = "under Expedition badge"
        if n.get("tower") and under(n["x"], n["y"]):
            n["tower"] = False
    out = []
    for landmark in lms:
        if landmark["kind"] in NOT_ON_EXPEDITION and under(landmark["x"], landmark["y"]):
            if landmark["kind"] == "Hall":
                out.append(dict(landmark, kind="Deadly boss map", why="Expedition badge: never a Hall"))
            continue  # Tower: an ordinary ocean map
        out.append(landmark)
    rows = badge_rows(icons)
    drop = {id(b) for r in rows if any(b.get("name") == EXPEDITION for b in r) for b in r if b.get("name") == "Hideout"}
    icons = [b for b in icons if id(b) not in drop]
    return nodes, icons, out


def ship_markers(img: np.ndarray) -> list[dict]:
    """Expedition ship markers (ocean biome): the square button with a ship symbol (user: boat).

    Found by the same finder as the locked strongholds' hand badges.

    Args:
        img: BGR screenshot (1080p).

    Returns:
        Icons as dicts {"name": "ExpeditionShip", "x", "y", "score", "source": "square button"}.
    """
    return [
        {"name": "ExpeditionShip", "x": int(b["x"]), "y": int(b["y"]), "score": b["symbol"], "source": "square button"}
        for b in square_buttons(img)
        if b["kind"] == "ship"
    ]
