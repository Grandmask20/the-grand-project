"""A map node's biome and city area on one screenshot: the first guesses of the RF-DETR dataset's node classes.

Biome (the PM's idea): the ground in a ring around the map node, from its box out to the disc Fix seams protects
(``BIOME_RING``), classified pixel by pixel by ``finalize.landmarks.ground_of`` (water, sand, rock / snow, grass,
forest; path strokes, black fog and the HUD left out); icon boxes are left out too (their pictures are not ground).
The biome with the largest share wins (``BIOME_GROUND`` groups the ground classes as the PM did: green = grass, swamp,
forest; sand = desert; blue = water; white = mountain). A map in the ocean biome is water whatever its island's
ground (the classical rule ``finalize.landmarks._ocean``). Mountain and the white Delirium mist look alike (PM): under
a Delirium icon the white is left out and the guess is unsure.

City area: the maps a City's area covers, grown from the city's own map through the traced paths by
``cities.potential_maps`` with the atlas-wide rules (about 10 maps, tightly linked, never through a Unique map, Tower,
Hall ...; not behind the citadel), here on one screenshot. A screenshot may cut an area off, so these stay guesses.

The classical detector has limits here (user): these are first guesses for a reviewer, and the RF-DETR model is
meant to learn past them from the reviewed boxes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from grand_project import cities

from . import constants as K


@dataclass(frozen=True)
class BiomeGuess:
    """The biome guessed for one map node."""

    biome: str | None
    """"grass", "desert", "water", "mountain", or None when too little of its ground is seen."""
    sure: bool
    """Whether the guess is clear enough to need no check first (a share and a lead over the second biome)."""
    shares: dict[str, float] = field(default_factory=dict)
    """Biome -> share of the classified ring pixels ({} when nothing was seen; {"water": 1.0} in the ocean)."""


def _disc(radius: int) -> np.ndarray:
    """A float32 disc kernel of the given radius (1 inside, 0 outside)."""
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    return (np.hypot(xx, yy) <= radius).astype(np.float32)


def ocean_flags(cls: np.ndarray, bad: np.ndarray, points: np.ndarray) -> np.ndarray:
    """``finalize.landmarks._ocean`` for many points at once (it reads a 350 px disc around each: ~15 ms a point).

    The same rule: more than 200 usable classified pixels within ``OCEAN_R`` and at least ``OCEAN_WATER`` of them water.
    The disc sums come from one convolution of the screenshot (OpenCV filters a kernel this large through the DFT).

    Args:
        cls: per-pixel ground classes (``ground_of``).
        bad: pixels to ignore (``ground_of``).
        points: (N, 2) x, y of the map nodes in screen px.

    Returns:
        (N,) bool, True for a map in the ocean biome.
    """
    from grand_project.finalize.constants import OCEAN_R, OCEAN_WATER  # finalize imports detect: imported late

    points = np.asarray(points, float).reshape(-1, 2)
    if not len(points):
        return np.zeros(0, bool)
    usable = ((cls >= 0) & ~bad).astype(np.float32)
    water = ((cls == 0) & ~bad).astype(np.float32)
    kernel = _disc(OCEAN_R)
    seen = cv2.filter2D(usable, cv2.CV_32F, kernel, borderType=cv2.BORDER_CONSTANT)
    wet = cv2.filter2D(water, cv2.CV_32F, kernel, borderType=cv2.BORDER_CONSTANT)
    h, w = cls.shape
    xs = np.clip(np.round(points[:, 0]).astype(int), 0, w - 1)
    ys = np.clip(np.round(points[:, 1]).astype(int), 0, h - 1)
    n, wn = seen[ys, xs], wet[ys, xs]
    # filter2D sums in float32: round before comparing, as _ocean counts whole pixels
    n, wn = np.round(n), np.round(wn)
    return (n > 200) & (wn >= OCEAN_WATER * np.maximum(n, 1))


def _icon_mask(shape: tuple[int, int], icons: list[dict]) -> np.ndarray:
    """Pixels under an icon's box (plus ``BIOME_ICON_PAD``): icon pictures are not ground."""
    h, w = shape
    mask = np.zeros((h, w), bool)
    half = K.RF_DETR_ICON_BOX / 2 + K.BIOME_ICON_PAD
    for icon in icons:
        x, y = float(icon["x"]), float(icon["y"])
        x0, x1 = max(0, int(round(x - half))), min(w, int(round(x + half)) + 1)
        y0, y1 = max(0, int(round(y - half))), min(h, int(round(y + half)) + 1)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _row_bases(icons: list[dict]) -> list[tuple[float, float]]:
    """Each icon's map base: under the middle of its row of icons (``core.row_bases``, as the atlas places them), so
    an outer icon of a wide row finds its map node too."""
    from grand_project.core import row_bases

    return row_bases(
        [{**icon, "x": float(icon["x"]), "y": float(icon["y"]), "name": icon.get("name")} for icon in icons]
    )


def _misted(nodes: list[dict], icons: list[dict]) -> set[int]:
    """Map nodes whose ground the white mist of a ``BIOME_MIST_ICONS`` map covers: such maps, and maps within
    ``BIOME_MIST_REACH`` of one (the mist spreads over its neighbours)."""
    mist = [i for i, icon in enumerate(icons) if icon.get("name") in K.BIOME_MIST_ICONS]
    if not mist or not nodes:
        return set()
    # an icon belongs to the map node under the middle of its row (an outer icon of a wide row is far from it)
    bases = _row_bases(icons)
    based = [{**icons[i], "bx": bases[i][0], "by": bases[i][1]} for i in mist]
    sources = set(cities.icon_maps(nodes, based).values())
    if not sources:
        return set()
    pts = np.array([[float(n["x"]), float(n["y"])] for n in nodes], float)
    src = pts[sorted(sources)]
    near = np.hypot(pts[:, None, 0] - src[None, :, 0], pts[:, None, 1] - src[None, :, 1]).min(axis=1)
    return {int(i) for i in np.nonzero(near <= K.BIOME_MIST_REACH)[0]}


def node_biomes(img: np.ndarray, nodes: list[dict], icons: list[dict]) -> list[BiomeGuess]:
    """Guess every map node's biome from the ground in a ring around it.

    Args:
        img: the screenshot (BGR, 1080p as the detector reads it).
        nodes: map node dicts with "x", "y" in screen px.
        icons: icon dicts with "x", "y" (and "name") in screen px.

    Returns:
        One BiomeGuess per node, in the order of ``nodes``.
    """
    from grand_project.finalize import landmarks as fl  # finalize imports detect: imported late

    if not nodes:
        return []
    cls, bad = fl.ground_of(img)
    h, w = cls.shape
    skip = bad | _icon_mask((h, w), icons)
    inner, outer = K.BIOME_RING
    r = int(np.ceil(outer))
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
    dist = np.hypot(xx, yy)
    ring = (dist >= inner) & (dist <= outer)
    points = np.array([[float(n["x"]), float(n["y"])] for n in nodes], float)
    ocean = ocean_flags(cls, bad, points)
    misted = _misted(nodes, icons)
    biomes = sorted(set(K.BIOME_GROUND.values()))
    out: list[BiomeGuess] = []
    for index, (x, y) in enumerate(points):
        if ocean[index]:
            # the ocean rule names it water; under the Delirium mist even that is not sure (PM)
            out.append(BiomeGuess("water", index not in misted, {"water": 1.0}))
            continue
        X, Y = int(round(x)), int(round(y))
        x0, x1, y0, y1 = max(0, X - r), min(w, X + r + 1), max(0, Y - r), min(h, Y + r + 1)
        if x1 <= x0 or y1 <= y0:
            out.append(BiomeGuess(None, False))
            continue
        sub = ring[y0 - (Y - r) : y1 - (Y - r), x0 - (X - r) : x1 - (X - r)] & ~skip[y0:y1, x0:x1]
        seen = cls[y0:y1, x0:x1][sub]
        seen = seen[seen >= 0]
        mist = index in misted
        counts = dict.fromkeys(biomes, 0)
        for ground, name in K.BIOME_GROUND.items():
            if mist and name == "mountain":
                continue  # white under the mist is the mist (PM)
            counts[name] += int((seen == ground).sum())
        total = sum(counts.values())
        if total < K.BIOME_MIN_PIXELS:
            out.append(BiomeGuess(None, False))
            continue
        shares = {name: count / total for name, count in counts.items() if count}
        ranked = sorted(shares.items(), key=lambda item: -item[1])
        top, share = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        sure = share >= K.BIOME_SURE_SHARE and share - second >= K.BIOME_SURE_MARGIN and not mist
        out.append(BiomeGuess(top, sure, shares))
    return out


def city_area_nodes(
    nodes: list[dict], edges: list[dict], icons: list[dict], landmarks: list[dict], city_types: dict[int, str]
) -> dict[int, tuple[str, int]]:
    """Find the maps of each City's area on one screenshot (``cities.potential_maps`` with the atlas-wide rules).

    Args:
        nodes: map node dicts with "x", "y" in screen px (about atlas units near the screen's middle).
        edges: traced paths with "a", "b" (indices into ``nodes``).
        icons: icon dicts with "name", "x", "y".
        landmarks: the screenshot's landmarks ("kind", "x", "y"); Cities are the sources.
        city_types: landmark index -> the City's type ("Ezomyte", "Vaal", "Faridun"), sure or not.

    Returns:
        Map node index -> (city type, path steps from the city's own map; 0 = its own map). A map two cities of
        different types claim equally is left out (two cities of one type give it that type's class either way).
    """
    sources = [
        (float(landmark["x"]), float(landmark["y"]), f"{city_types[index]} city")
        for index, landmark in enumerate(landmarks)
        if landmark.get("kind") == "City" and index in city_types
    ]
    if not sources or not nodes:
        return {}
    based = [{**icon, "bx": bx, "by": by} for icon, (bx, by) in zip(icons, _row_bases(icons), strict=True)]
    blocked = cities.blocked_maps(nodes, based, landmarks)
    potential = cities.potential_maps(nodes, edges, sources, ground=None, blocked=blocked)
    out: dict[int, tuple[str, int]] = {}
    for node, (label, steps) in potential.items():
        names = label.split(" / ")  # a map claimed equally by cities of two types: no single answer
        city = names[0].removesuffix(" city")
        if len(names) == 1 and city in cities.TYPES:
            out[int(node)] = (city, int(steps))
    return out


__all__ = ["BiomeGuess", "city_area_nodes", "node_biomes", "ocean_flags"]
