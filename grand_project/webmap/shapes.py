"""webmap.shapes: the vector ground of the web map (land and biome areas as polygons) and the icon pictures.

Land is where the screenshots show ground (the map image's non-black part). Biome areas come from the app's own
data: the maps a City or Breach stronghold biome covers (grand_project.cities.biomes); no icon makes a biome (user:
"<X>Influence" icons drew Grass / Water areas). Each such map is a disc; discs of one biome close to each other are
joined, the area is cut back to the ground nearer its own maps than any other map (rounded off), and the outline is
traced into polygons.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from grand_project import paths as rc_paths
from grand_project.app.constants import ICON_INFO

from .constants import (
    WEBMAP_BIOME_COLOUR,
    WEBMAP_BIOME_JOIN,
    WEBMAP_BIOME_KEEP,
    WEBMAP_BIOME_R,
    WEBMAP_BIOME_SMOOTH,
    WEBMAP_ICON_RING,
    WEBMAP_ICON_SPRITE,
    WEBMAP_LAND_JOIN,
    WEBMAP_SHAPE_CELL,
)

ICON_ART = rc_paths.ref("poe2db_icons")


def _trace(mask: np.ndarray, to_atlas, simplify: float) -> list[list[list[tuple[float, float]]]]:
    """Trace a mask into polygons (outer ring, then its holes) in atlas units.

    Args:
        mask: uint8 mask (255 = inside).
        to_atlas: Function (col, row) -> (x, y) atlas units for mask cell corners.
        simplify: Douglas-Peucker tolerance in cells.

    Returns:
        Polygons, each [outer ring, hole, ...] of (x, y) atlas points.
    """
    contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return []
    hier = hier[0]
    polys = []
    for i, c in enumerate(contours):
        if hier[i][3] != -1:  # a hole: added with its outer ring
            continue
        rings = [c]
        j = hier[i][2]
        while j != -1:
            rings.append(contours[j])
            j = hier[j][0]
        out = []
        for r in rings:
            r = cv2.approxPolyDP(r, simplify, True).reshape(-1, 2)
            if len(r) >= 3:
                out.append([to_atlas(float(x), float(y)) for x, y in r])
        if out and len(rings[0]) >= 3:
            polys.append(out)
    return polys


def land_polygons(image: np.ndarray, origin: tuple[float, float, float]) -> list:
    """Return where the map image shows ground, as polygons in atlas units.

    Args:
        image: The map image (BGR; black = no screenshot there).
        origin: (x0, y0, scale) of the map image.

    Returns:
        Polygons ([outer ring, holes...] of (x, y) atlas points).
    """
    x0, y0, sc = origin
    f = max(1.0, WEBMAP_SHAPE_CELL * sc)  # map image px per grid cell
    # the brightest channel per pixel, by OpenCV: numpy's max over the colour axis took ~0.6 s on a big atlas (user)
    b, g, r = cv2.split(image)
    brightest = cv2.max(cv2.max(b, g), r)
    small = cv2.resize(
        (brightest > 12).astype(np.uint8) * 255,
        (max(1, round(image.shape[1] / f)), max(1, round(image.shape[0] / f))),
        interpolation=cv2.INTER_AREA,
    )
    mask = (small > 127).astype(np.uint8) * 255
    k = max(1, round(WEBMAP_LAND_JOIN / WEBMAP_SHAPE_CELL))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
    sx, sy = image.shape[1] / mask.shape[1], image.shape[0] / mask.shape[0]
    return _trace(mask, lambda c, r: (x0 + c * sx / sc, y0 + r * sy / sc), 0.8)


def biome_kind(label: str) -> str:
    """Return the colour group of a biome label ("Vaal city" -> "Vaal", "Breach stronghold" -> "Breach").

    Args:
        label: Biome label (several joined with " / " use the first).

    Returns:
        A WEBMAP_BIOME_COLOUR key.
    """
    first = label.split(" / ")[0]
    return first.replace(" city", "").replace(" stronghold", "") if first != "City" else "City"


def biome_polygons(nodes: list[dict], potential: dict) -> list[tuple[str, list]]:
    """Return the biome areas as polygons, one set per biome kind.

    An area never reaches over a map outside it: it keeps the ground nearer its own maps than any other map, rounded
    off, with a small hole kept around every other map (WEBMAP_BIOME_KEEP). Discs around its maps covered close
    neighbours that were not in the biome, and joining the discs bridged over them (user: maps painted "no biome"
    stayed under the area, 161 of 939 on the crawl atlas).

    Args:
        nodes: The map nodes (app.model.view_model order; "x", "y", "status").
        potential: Map node index -> (biome label, steps) from grand_project.cities.biomes.

    Returns:
        [(kind, polygons)], kind a WEBMAP_BIOME_COLOUR key.
    """
    from scipy.spatial import cKDTree

    groups: dict[str, list[int]] = {}
    for i, (label, _steps) in potential.items():
        if nodes[i]["status"] != "removed":
            groups.setdefault(biome_kind(label), []).append(i)
    if not groups:
        return []
    alive = np.array([i for i, nd in enumerate(nodes) if nd["status"] != "removed"])
    tree = cKDTree(np.array([[nodes[i]["x"], nodes[i]["y"]] for i in alive], float))
    out = []
    C, R = WEBMAP_SHAPE_CELL, WEBMAP_BIOME_R
    for kind, idx in groups.items():
        pts = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in idx], float)
        ox, oy = pts.min(axis=0) - 2 * R
        w, h = (np.ceil((pts.max(axis=0) + 2 * R - [ox, oy]) / C)).astype(int) + 1
        mask = np.zeros((h, w), np.uint8)
        for x, y in pts:
            cv2.circle(mask, (round((x - ox) / C), round((y - oy) / C)), round(R / C), 255, -1, cv2.LINE_AA)
        k = max(1, round(WEBMAP_BIOME_JOIN / C / 2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
        mask = (mask > 127).astype(np.uint8) * 255
        # a spot stays only when its nearest map is one of this biome's (a map in another biome or in none keeps the
        # ground around it); the cut is then rounded off, and a small hole stays around every map outside the biome so
        # rounding never covers one (at most half the way to the nearest map of this biome: map nodes ~30 apart)
        rr, cc = np.nonzero(mask)
        _d, near = tree.query(np.column_stack([ox + cc * C, oy + rr * C]))
        own_cell = np.isin(alive[near], np.array(idx))
        mine = np.zeros(mask.shape, np.float32)
        mine[rr[own_cell], cc[own_cell]] = 1.0
        sm = max(1, round(WEBMAP_BIOME_SMOOTH / C))
        mask = (cv2.GaussianBlur(mine, (2 * sm + 1,) * 2, 0) > 0.5).astype(np.uint8) * 255
        own, own_tree = set(idx), cKDTree(pts)
        lo, hi = np.array([ox, oy]), np.array([ox + w * C, oy + h * C])
        for j in tree.query_ball_point((lo + hi) / 2, float(np.hypot(*(hi - lo))) / 2 + WEBMAP_BIOME_KEEP):
            i = int(alive[j])
            if i not in own:
                x, y = nodes[i]["x"], nodes[i]["y"]
                r = min(WEBMAP_BIOME_KEEP, own_tree.query([x, y])[0] / 2)
                cv2.circle(mask, (round((x - ox) / C), round((y - oy) / C)), max(1, round(r / C)), 0, -1, cv2.LINE_AA)
        mask = (mask > 127).astype(np.uint8) * 255
        polys = _trace(mask, lambda c, r, ox=ox, oy=oy: (ox + c * C, oy + r * C), 1.0)
        if polys and kind in WEBMAP_BIOME_COLOUR:
            out.append((kind, polys))
    return out


def icon_sprite(name: str) -> np.ndarray:
    """Return an icon type's picture for the map: the game's badge art when the program has it, else a disc.

    "full__<name>" art is the whole badge; "inner__<name>" art is the picture inside the ring, cut round here and
    given a brass ring; types without art get a disc in their ICON_INFO colour.

    Args:
        name: Icon type name.

    Returns:
        BGRA uint8 (WEBMAP_ICON_SPRITE, WEBMAP_ICON_SPRITE, 4).
    """
    S = WEBMAP_ICON_SPRITE
    full, inner = ICON_ART / f"full__{name}.webp", ICON_ART / f"inner__{name}.webp"
    yy, xx = np.mgrid[0:S, 0:S]
    d = np.hypot(xx - (S - 1) / 2, yy - (S - 1) / 2)
    if full.exists():
        img = _read(full)
        if img is not None:
            return cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
    out = np.zeros((S, S, 4), np.uint8)
    if inner.exists() and (img := _read(inner)) is not None:
        art = cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
        out[..., :3] = art[..., :3]
    else:
        out[..., :3] = ICON_INFO.get(name, ("", (230, 140, 255), ""))[1]
    out[..., 3] = np.clip((S / 2 - d) * 255, 0, 255).astype(np.uint8)  # round, soft edge
    cv2.circle(out, (S // 2, S // 2), S // 2 - 4, (*WEBMAP_ICON_RING, 255), 4, cv2.LINE_AA)
    cv2.circle(out, (S // 2, S // 2), S // 2 - 1, (20, 20, 20, 255), 2, cv2.LINE_AA)
    return out


def _read(path: Path) -> np.ndarray | None:
    """Read an icon art file as BGRA.

    Args:
        path: The .webp file.

    Returns:
        BGRA image, or None when it cannot be read.
    """
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img
