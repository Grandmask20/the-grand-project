"""webmap.solids: the web map's 3D view: map nodes, towers, citadels, halls and strongholds as extruded shapes.

The atlas knows where each structure stands and what it is (landmark kind, city type, locked or not), not its
outline, so each kind gets a simple model in its own style: a pillar per map node, a stone shaft for a tower, a
stepped pyramid for a Vaal citadel, a dark walled ring for an Ezomyte one, sand walls with a green-roofed hall for a
Faridun one, a hall with its orange beam, a crystal cluster for a Breach stronghold. Sizes are in atlas units (one
atlas unit is about one screenshot pixel); the app turns heights into the metres MapLibre extrudes by (app.mapimage).
"""

from __future__ import annotations

import math

from .constants import WEBMAP_SOLID

_DEADLY = ("MapBoss", "MapBossSpecial")


def _ngon(x: float, y: float, r: float, n: int = 8, turn: float = 0.0) -> list[tuple[float, float]]:
    """Return a regular polygon around a point.

    Args:
        x: Centre x (atlas units).
        y: Centre y.
        r: Radius.
        n: Number of corners (4: a square standing on its side when turn is 45 degrees).
        turn: Rotation in degrees.

    Returns:
        The ring's corners.
    """
    a0 = math.radians(turn)
    return [(x + r * math.cos(a0 + 2 * math.pi * k / n), y + r * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n)]


def _square(x: float, y: float, side: float) -> list[tuple[float, float]]:
    """Return an axis-aligned square around a point.

    Args:
        x: Centre x.
        y: Centre y.
        side: Side length.

    Returns:
        The ring's corners.
    """
    h = side / 2
    return [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]


def _solid(rings, base: float, top: float, colour: str, **extra) -> dict:
    """Return one extruded shape.

    Args:
        rings: Outer ring, then holes (atlas units).
        base: Bottom height (atlas units).
        top: Top height (atlas units).
        colour: CSS colour.
        **extra: More properties (e.g. node: the map node it stands for, so a click selects it).

    Returns:
        {"rings", "base", "top", "colour", ...}.
    """
    return {"rings": rings, "base": base, "top": top, "colour": colour, **extra}


def map_pillar(x: float, y: float, icons: list[str], colour: str, node: int) -> list[dict]:
    """Return the pillar of a map node: taller for a boss map, in its icon colour.

    Args:
        x: Map node x.
        y: Map node y.
        icons: Its icon names.
        colour: Its colour (first icon's, or its status colour).
        node: Its web id.

    Returns:
        The shapes.
    """
    K = WEBMAP_SOLID
    top = K["boss_map"] if any(i in _DEADLY for i in icons) else K["map"]
    return [
        _solid([_ngon(x, y, K["map_r"])], 0, top, colour, node=node),
        _solid([_ngon(x, y, K["map_r"] * 0.55)], top, top + K["map_r"] * 0.35, "#e8e2cf", node=node),  # light cap
    ]


def structure(kind: str, x: float, y: float, city_type: str = "", locked: bool = False) -> list[dict]:
    """Return the model of a landmark.

    Args:
        kind: Landmark kind ("City", "Hall", "Tower", "Breach stronghold", "Deadly boss map").
        x: Its x (atlas units).
        y: Its y.
        city_type: "Vaal" / "Ezomyte" / "Faridun" for a City whose type is known, else "".
        locked: A locked Breach stronghold (hand icon).

    Returns:
        The shapes (empty for an unknown kind).
    """
    S = []
    if kind == "Tower":
        S += [
            _solid([_square(x, y, 34)], 0, 150, "#8d8f95"),  # shaft
            _solid([_square(x, y, 46)], 150, 168, "#6f7178"),  # crown
            _solid([_ngon(x, y, 7)], 168, 196, "#9fe8ff"),  # the beacon
        ]
    elif kind == "City" and city_type == "Vaal":  # stepped pyramid
        for k, side in enumerate((160, 124, 88, 52)):
            S.append(
                _solid([_square(x, y, side)], 28 * k, 28 * (k + 1), ("#b8955a", "#c29f62", "#cba86a", "#d4b273")[k])
            )
        S.append(_solid([_square(x, y, 26)], 112, 136, "#e2c27e"))  # the temple on top
    elif kind == "City" and city_type == "Ezomyte":  # dark walled ring with wall towers and a keep
        S.append(_solid([_ngon(x, y, 88, 24), list(reversed(_ngon(x, y, 74, 24)))], 0, 42, "#4a4a50"))
        S += [_solid([_ngon(px, py, 12)], 0, 60, "#55555c") for px, py in _ngon(x, y, 81, 6, 15)]
        S += [_solid([_square(x, y, 42)], 0, 78, "#5d5d64"), _solid([_square(x, y, 50)], 78, 86, "#3e3e44")]
    elif kind == "City" and city_type == "Faridun":  # sand walls, corner towers, a green-roofed hall
        S.append(_solid([_square(x, y, 164), list(reversed(_square(x, y, 144)))], 0, 36, "#c9b07a"))
        S += [_solid([_ngon(px, py, 15)], 0, 56, "#a99060") for px, py in _ngon(x, y, 77 * math.sqrt(2), 4, 45)]
        S += [_solid([_square(x, y, 62)], 0, 40, "#d3bb86"), _solid([_square(x, y, 66)], 40, 52, "#3f8a5a")]
    elif kind == "City":  # type not known: a plain keep
        S += [_solid([_square(x, y, 70)], 0, 66, "#7c7a78"), _solid([_square(x, y, 78)], 66, 74, "#5f5d5b")]
    elif kind == "Hall":  # a hall, and the orange beam that marks it in the game
        S += [
            _solid([_square(x, y, 72)], 0, 44, "#6d6258"),
            _solid([_square(x, y, 80)], 44, 52, "#544a42"),
            _solid([_ngon(x, y, 6)], 52, 420, "#ff8c1a"),
        ]
    elif kind == "Breach stronghold":  # a cluster of crystals; a locked one is dim and low
        tall = (140, 95, 120, 80, 110, 70, 100)
        for k, (px, py) in enumerate([(x, y), *_ngon(x, y, 26, 6, 10)]):
            S.append(_solid([_ngon(px, py, 11 if k == 0 else 8, 5, 18 * k)], 0, tall[k] * (0.45 if locked else 1),
                            "#5a2a66" if locked else "#b84fd6"))  # fmt: skip
    elif kind == "Deadly boss map":
        S += [_solid([_ngon(x, y, 10, 4)], 0, 70, "#d23c3c")]
    return S
