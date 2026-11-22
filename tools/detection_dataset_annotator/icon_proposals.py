"""Extra icon proposals for the dataset annotator: rim first, then the picture inside it.

The classical finder (``detect.badges.find_badges``) decides "is this an icon?" with a frozen classifier trained on
the crawl screenshots' small gold-rimmed icons. On the res atlases most icons are larger with a silver
rim: they are still rim candidates, and naming matches them to a stored icon picture almost exactly, but the
classifier rejects them, so the annotator showed few or no icons there.

For a dataset that a reviewer corrects, missing an icon costs more than proposing a wrong one, so this module
proposes an icon at every rim candidate that both sits where icons sit (in a row just above a map node) and closely
matches a stored icon picture. It only adds annotator boxes; the program's own icon finder is unchanged (user's
rule: teaching icons must never change what is found).
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from grand_project import core, icon_refs
from grand_project.detect import badges
from grand_project.detect import constants as detect_constants

from . import constants as K

_HALF = icon_refs.SIZE // 2
_MASK_Y, _MASK_X = (np.nonzero(icon_refs._MASK)[0] - _HALF), (np.nonzero(icon_refs._MASK)[1] - _HALF)
_STEPS = range(-icon_refs.SHIFT, icon_refs.SHIFT + 1)
_SHIFTS = np.array([(dy, dx) for dy in _STEPS for dx in _STEPS])  # name_badge's alignment search, dy and dx
_REACH = _HALF + icon_refs.SHIFT  # name_badge's shifted crop must lie inside the screenshot


def picture_book(book: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    """The names and picture features naming compares against: the stored pictures plus the badge model's own."""
    stored = icon_refs.refs()
    names = stored.names + list(book.get("names", []))
    features = np.vstack([stored.F, book["F"]]) if len(book.get("names", [])) else stored.F
    return names, np.ascontiguousarray(features, dtype=np.float32)


def name_icons(img: np.ndarray, pts: np.ndarray, names: list[str], features: np.ndarray) -> list[tuple[str, float]]:
    """Name many icon candidates at once; the same result as ``badges.name_badge`` for each point.

    ``name_badge`` blurs each shifted crop and makes 49 matrix-vector products per point (about 0.2 s). Here the
    screenshot is blurred once (the compared pixels lie more than the blur's reach inside every crop, so the values
    are identical) and every point and shift goes through one matrix product per batch.

    Args:
        img: BGR screenshot (1080p).
        pts: (n, 2) int array of icon centres x, y in detector px.
        names: Name of each row in ``features``.
        features: (m, k) picture features (``icon_refs.feature``).

    Returns:
        One (name, distance) per point, as ``name_badge`` returns them.
    """
    pts = np.asarray(pts, dtype=int).reshape(-1, 2)
    results: list[tuple[str, float]] = [("Unidentified", 9.0)] * len(pts)
    height, width = img.shape[:2]
    inside = (
        (pts[:, 0] - _REACH >= 0)
        & (pts[:, 0] + _REACH <= width)
        & (pts[:, 1] - _REACH >= 0)
        & (pts[:, 1] + _REACH <= height)
    )
    order = np.nonzero(inside)[0]
    if not len(names) or not len(order):
        return results
    blurred = cv2.GaussianBlur(img, (0, 0), 1.5)
    colours = icon_refs.refs().colours
    for start in range(0, len(order), K.ANNOTATOR_ICON_BATCH):
        chunk = order[start : start + K.ANNOTATOR_ICON_BATCH]
        ys = pts[chunk, 1][:, None, None] + _SHIFTS[None, :, 0, None] + _MASK_Y[None, None, :]
        xs = pts[chunk, 0][:, None, None] + _SHIFTS[None, :, 1, None] + _MASK_X[None, None, :]
        vectors = blurred[ys, xs].astype(np.float32)  # (points, shifts, pixels, 3)
        vectors -= vectors.mean(axis=2, keepdims=True)
        vectors = vectors.reshape(len(chunk), len(_SHIFTS), -1)
        norms = np.linalg.norm(vectors, axis=2, keepdims=True)
        vectors = np.where(norms > 1e-6, vectors / np.maximum(norms, 1e-6), vectors)
        correlation = features @ vectors.reshape(-1, vectors.shape[2]).T
        distance = 1.0 - correlation.reshape(len(names), len(chunk), len(_SHIFTS)).max(axis=2)
        for column, index in enumerate(chunk):
            x, y = int(pts[index, 0]), int(pts[index, 1])
            d = np.minimum(distance[:, column], 9.0)
            d[~icon_refs.colour_ok(names, colours, icon_refs.crop(img, x, y))] = 9.0
            best = int(np.argmin(d))
            name = names[best] if d[best] <= icon_refs.MAX_DIST else "Unidentified"
            results[index] = (name, float(d[best]))
    return results


def map_spots(pts: np.ndarray, prob: np.ndarray) -> np.ndarray:
    """Faint map nodes: map candidates the map classifier gave at least ``ANNOTATOR_SPOT_MIN``.

    Args:
        pts: (n, 2) map candidates x, y in detector px (``pipeline.find_maps``, the run the detector was given).
        prob: (n,) map probability of each candidate.

    Returns:
        (k, 2) float array of x, y in detector px.
    """
    return np.asarray(pts)[np.asarray(prob) >= K.ANNOTATOR_SPOT_MIN].astype(float).reshape(-1, 2)


def _in_row(pts: np.ndarray, anchors: np.ndarray, nodes: np.ndarray) -> np.ndarray:
    """Per candidate: whether it sits in an icon row above an anchor (and not on a found map node's own disc).

    Args:
        pts: (n, 2) candidate x, y in detector px.
        anchors: (k, 2) map nodes and faint map nodes x, y in detector px.
        nodes: (j, 2) found map nodes.

    Returns:
        (n,) bool array.
    """
    if not len(pts) or not len(anchors):
        return np.zeros(len(pts), dtype=bool)
    dx = pts[:, None, 0] - anchors[None, :, 0]
    dy = anchors[None, :, 1] - pts[:, None, 1]
    above = (dy >= K.ANNOTATOR_ICON_ROW_DY[0]) & (dy <= K.ANNOTATOR_ICON_ROW_DY[1])
    in_row = (above & (np.abs(dx) <= K.ANNOTATOR_ICON_ROW_DX)).any(axis=1)
    if len(nodes):
        distance = np.hypot(pts[:, None, 0] - nodes[None, :, 0], pts[:, None, 1] - nodes[None, :, 1]).min(axis=1)
        in_row &= distance > K.ANNOTATOR_ICON_NODE_CLEAR
    return in_row


def _centred(x: float, y: float, anchors: np.ndarray) -> bool:
    """Whether a map node or faint map node sits right under x, y (a single icon, or a pair's middle)."""
    if not len(anchors):
        return False
    dy = anchors[:, 1] - y
    return bool(
        (
            (np.abs(anchors[:, 0] - x) <= K.ANNOTATOR_ICON_CENTRED)
            & (dy >= K.ANNOTATOR_ICON_ROW_DY[0])
            & (dy <= K.ANNOTATOR_ICON_ROW_DY[1])
        ).any()
    )


def _stands_on(x: float, y: float, dist: float, nodes: np.ndarray, spots: np.ndarray) -> bool:
    """Whether a weak match at x, y (or a pair's middle) stands centred on a map node.

    A faint map node is weaker evidence than a found one, so leaning on it takes a closer match
    (``ANNOTATOR_ICON_MATCH_FAINT``).
    """
    return _centred(x, y, nodes) or (dist <= K.ANNOTATOR_ICON_MATCH_FAINT and _centred(x, y, spots))


def _row_neighbours(ax: float, ay: float, bx: float, by: float) -> bool:
    """Whether two icons are side by side in one row."""
    low, high = K.ANNOTATOR_ICON_ROW_GAP
    return abs(ay - by) <= K.ANNOTATOR_ICON_ROW_HEIGHT and low <= abs(ax - bx) <= high


def _points(items: list[dict[str, Any]]) -> np.ndarray:
    return np.array([(item["x"], item["y"]) for item in items], dtype=float).reshape(-1, 2)


def propose_icons(
    img: np.ndarray, detection: dict[str, Any], book: dict[str, Any], spots: np.ndarray | None = None
) -> list[dict[str, Any]]:
    """Icons the classical finder missed: rim candidates in an icon row whose picture matches a stored icon.

    A close match (``ANNOTATOR_ICON_MATCH_SURE``) is enough on its own. A weaker one must also be centred over a
    map node, be the row neighbour of a found icon, or form a pair with another weak match whose middle is centred
    over a map node (a row of two stands centred on its map node); leaning on a faint map node takes a closer match.

    Args:
        img: BGR screenshot (1080p), the one ``detection`` was made from.
        detection: The classical detector's result (``nodes`` and ``icons`` are used).
        book: The trained "badges" model (its own labelled pictures, ``names`` and ``F``).
        spots: (k, 2) faint map nodes (``map_spots``). An icon over a fogged map node the finder missed leans on
            one of these instead (an icon always stands on a map node: user's rule).

    Returns:
        New icons as dicts {"x", "y", "score", "name", "dist", "proposal": True}; ``score`` is 1 - distance, as the
        classifier did not vouch for them.
    """
    nodes = _points(detection.get("nodes", []))
    spots = np.zeros((0, 2)) if spots is None else np.asarray(spots, dtype=float).reshape(-1, 2)
    anchors = np.vstack([nodes, spots])
    pts, _ring, _extra = badges.badge_candidates(img)
    pts = pts[_in_row(pts.astype(float), anchors, nodes)]
    if not len(pts):
        return []
    names, features = picture_book(book)
    matches = []
    for (name, dist), (x, y) in zip(name_icons(img, pts, names, features), pts, strict=True):
        if dist > K.ANNOTATOR_ICON_MATCH or name in ("Unidentified", icon_refs.NOT_A_BADGE):
            continue
        if name.endswith("Influence"):
            continue  # a weak circle named a biome influence is usually terrain (user's rule)
        if name == detect_constants.EXPEDITION and not badges._in_water(img, float(x), float(y)):
            continue  # Expedition only appears in the water zone (user's rule)
        matches.append((dist, name, float(x), float(y)))
    matches.sort(key=lambda match: match[0])

    found = [(float(icon["x"]), float(icon["y"])) for icon in detection.get("icons", [])]
    proposals: list[dict[str, Any]] = []

    def taken(match: tuple[float, str, float, float]) -> bool:
        return any(np.hypot(match[2] - fx, match[3] - fy) <= K.ANNOTATOR_ICON_NMS for fx, fy in found)

    def accept(match: tuple[float, str, float, float]) -> None:
        dist, name, x, y = match
        found.append((x, y))
        proposals.append(
            {"x": x, "y": y, "score": round(1.0 - dist, 3), "name": name, "dist": round(dist, 3), "proposal": True}
        )

    pending = matches
    while pending:  # weak matches may lean on an icon accepted in an earlier pass
        waiting = []
        for match in pending:
            if taken(match):
                continue
            dist, _name, x, y = match
            neighbour = any(_row_neighbours(x, y, fx, fy) for fx, fy in found)
            if dist <= K.ANNOTATOR_ICON_MATCH_SURE or neighbour or _stands_on(x, y, dist, nodes, spots):
                accept(match)
            else:
                waiting.append(match)
        if len(waiting) == len(pending):  # no progress: try pairs of weak matches centred over a map node
            pair = next(
                (
                    (first, second)
                    for i, first in enumerate(waiting)
                    for second in waiting[i + 1 :]
                    if _row_neighbours(first[2], first[3], second[2], second[3])
                    and _stands_on(
                        (first[2] + second[2]) / 2,
                        (first[3] + second[3]) / 2,
                        max(first[0], second[0]),
                        nodes,
                        spots,
                    )
                ),
                None,
            )
            if pair is None:
                break
            for match in pair:
                accept(match)
            waiting = [match for match in waiting if not taken(match)]
        pending = waiting
    return proposals


def _icon_rows(icons: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group icons side by side into rows (as ``badges.badge_rows``, with the larger icons' spacing too).

    One icon of a row may be missed, so twice the gap also joins.
    """
    low, high = K.ANNOTATOR_ICON_ROW_GAP
    rows: list[list[dict[str, Any]]] = []
    for icon in sorted(icons, key=lambda item: item["x"]):
        for row in rows:
            gap = icon["x"] - row[-1]["x"]
            if abs(icon["y"] - row[-1]["y"]) <= K.ANNOTATOR_ICON_ROW_HEIGHT and (
                low <= gap <= high or 2 * low <= gap <= 2 * high
            ):
                row.append(icon)
                break
        else:
            rows.append([icon])
    return rows


def node_offset(icons: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> float:
    """How far below its icons this screenshot's map nodes sit: the median over icons centred above a map node.

    Crawl screenshots measure 24 px (``ROW_DY``), the res atlases 31-36; fewer than
    ``ANNOTATOR_HIDDEN_MIN_PAIRS`` pairs fall back to ``ROW_DY``.
    """
    found = _points([node for node in nodes if not node.get("hidden")])
    offsets = []
    for icon in icons:
        if not len(found):
            break
        dx = found[:, 0] - icon["x"]
        dy = found[:, 1] - icon["y"]
        low, high = K.ANNOTATOR_ICON_ROW_DY
        below = (np.abs(dx) <= K.ANNOTATOR_ICON_CENTRED) & (dy >= low) & (dy <= high)
        if below.any():
            offsets.append(float(dy[below].min()))
    if len(offsets) < K.ANNOTATOR_HIDDEN_MIN_PAIRS:
        return float(detect_constants.ROW_DY)
    return float(np.median(offsets))


def hidden_nodes(
    img: np.ndarray, detection: dict[str, Any], icons: list[dict[str, Any]], spots: np.ndarray | None = None
) -> list[dict[str, Any]]:
    """A map node under every icon row that has none: an icon always stands on a map node (user's rule).

    The map node goes under the row's middle at this screenshot's icon-to-map-node offset, snapped to a faint map
    node there when there is one. As in the classical finder, a row with a visible map node within ``HIDDEN_SNAP``
    px of that spot already has its map node.

    Args:
        img: BGR screenshot (1080p).
        detection: The classical detector's result (``nodes`` is used).
        icons: All icons of the screenshot (classical and proposed).
        spots: (k, 2) faint map nodes (``map_spots``) to snap to.

    Returns:
        New map nodes as dicts {"x", "y", "hidden": True, "source": "icon row", "proposal": True}.
    """
    nodes = detection.get("nodes", [])
    on_nodes = [icon for icon in icons if icon.get("source") != "square button"]  # ship buttons stand on water
    offset = node_offset(on_nodes, nodes)
    known = _points(nodes)
    visible = _points([node for node in nodes if not node.get("hidden")])
    spots = np.zeros((0, 2)) if spots is None else np.asarray(spots, dtype=float).reshape(-1, 2)
    height, width = img.shape[:2]
    found: list[dict[str, Any]] = []

    def clear(x: float, y: float, others: np.ndarray) -> bool:
        """Whether a map node at x, y keeps clear of the known map nodes and of other rows' icons."""
        if len(known) and np.hypot(known[:, 0] - x, known[:, 1] - y).min() <= detect_constants.MAP_NMS:
            return False
        # an icon of another row there: this row is a marker pinned above that icon, not a row above a map node
        return not (len(others) and np.hypot(others[:, 0] - x, others[:, 1] - y).min() <= K.ANNOTATOR_ICON_NMS)

    for row in _icon_rows(on_nodes):
        x = (row[0]["x"] + row[-1]["x"]) / 2  # the map node sits under the row's middle (user's rule)
        y = float(np.mean([icon["y"] for icon in row]))
        y += offset
        if len(visible) and np.hypot(visible[:, 0] - x, visible[:, 1] - y).min() <= detect_constants.HIDDEN_SNAP:
            continue  # a visible map node this close is the row's map node, not a hidden one next to it (user's rule)
        # the row's own icons stand right above its map node (a single one ROW_DY above, closer than ICON_NMS)
        mine = {id(icon) for icon in row}
        others = _points([icon for icon in icons if id(icon) not in mine])
        if not clear(x, y, others):
            continue
        if len(spots):
            distance = np.hypot(spots[:, 0] - x, spots[:, 1] - y)
            nearest = int(np.argmin(distance))
            snapped = float(spots[nearest, 0]), float(spots[nearest, 1])
            if distance[nearest] <= K.ANNOTATOR_HIDDEN_SNAP and clear(*snapped, others):
                x, y = snapped  # else the estimate, which is clear of both
        if not (0 <= x < width and 0 <= y < height) or core.on_hud_mask([(x, y)], width, height, pad=0)[0]:
            continue
        node = {"x": round(x, 1), "y": round(y, 1), "hidden": True, "source": "icon row", "proposal": True}
        found.append(node)
        known = np.vstack([known, [(x, y)]]) if len(known) else np.array([(x, y)])
    return found
