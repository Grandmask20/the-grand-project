"""webmap.solids: the web map's 3D view: map nodes, towers, citadels, halls and strongholds as extruded shapes.

The atlas knows where each structure stands and what it is (landmark kind, city type, locked or not), not its
outline, so each kind gets a model in its own style, built of extruded shapes (flat tops: a roof or a cone is steps):

- a map node: a plinth, its pillar in its icon colour and a light cap;
- a tower (the game's Lost / Precursor towers, with the Precursor Beacon on top): a stone shaft narrowing upwards
  with bands, a crenellated crown and the beacon;
- a Vaal citadel (the Stone Citadel: Vaal pyramids and monuments): a stepped pyramid with stairs, a pillared temple on
  top, obelisks;
- an Ezomyte one (the Iron Citadel: a walled town of many buildings and one mansion): crenellated walls and towers,
  houses and the mansion;
- a Faridun one (the Copper Citadel: tents, tarps, carts and stone pillars): tents, pillars, carts and a domed hall;
- a city of no known type: a small walled town with a keep;
- a hall: a long hall with a stepped roof, pillars, and its orange beam;
- a Breach stronghold: pointed crystals.

Sizes are in atlas units (one atlas unit is about one screenshot pixel); the app turns heights into the metres
MapLibre extrudes by (app.mapimage). The beams (#ff8c1a, #9fe8ff) are their own shapes, in their own colours (View:
beams off), and nothing else uses those colours.
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


def _rect(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    """Return an axis-aligned rectangle around a point.

    Args:
        x: Centre x.
        y: Centre y.
        w: Width (along x).
        h: Depth (along y).

    Returns:
        The ring's corners.
    """
    return [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]


def _wall(outer: list[tuple[float, float]], inner: list[tuple[float, float]], base: float, top: float, colour: str):
    """Return a wall: a ring with its inside cut out (the hole's corners the other way round)."""
    return _solid([outer, list(reversed(inner))], base, top, colour)


def _cone(x: float, y: float, r: float, base: float, top: float, colour: str, n: int = 8, steps: int = 4) -> list:
    """Return a cone (a roof, a tent, a crystal's point, a dome's top) as steps narrowing upwards.

    Args:
        x: Centre x.
        y: Centre y.
        r: Radius at its foot.
        base: Bottom height.
        top: Top height.
        colour: CSS colour.
        n: Corners.
        steps: Steps.

    Returns:
        The shapes.
    """
    dz = (top - base) / steps
    return [
        _solid([_ngon(x, y, r * (0.12 + 0.88 * (1 - k / steps)), n, 22.5)], base + dz * k, base + dz * (k + 1), colour)
        for k in range(steps)
    ]


def _dome(x: float, y: float, r: float, base: float, colour: str, steps: int = 4) -> list:
    """Return a dome as steps, round in profile (a quarter circle)."""
    out = []
    for k in range(steps):
        z0, z1 = r * k / steps, r * (k + 1) / steps
        out.append(_solid([_ngon(x, y, math.sqrt(max(r * r - z0 * z0, 1.0)), 12)], base + z0, base + z1, colour))
    return out


def _merlons(points: list[tuple[float, float]], size: float, base: float, top: float, colour: str) -> list:
    """Return the merlons of a battlement: a small block at each point."""
    return [_solid([_square(px, py, size)], base, top, colour) for px, py in points]


def _along_square(x: float, y: float, side: float, gap: float) -> list[tuple[float, float]]:
    """Return points along a square's sides, about gap apart (its corners included)."""
    h, n = side / 2, max(2, round(side / gap))
    pts = []
    for k in range(n):
        t = -h + side * k / n
        pts += [(x + t, y - h), (x + h, y + t), (x - t, y + h), (x - h, y - t)]
    return pts


def _house(x: float, y: float, w: float, d: float, wall: float, colour: str, roof: str) -> list:
    """Return a house: its walls and a roof stepping up along its length (a gable, in steps)."""
    out = [_solid([_rect(x, y, w, d)], 0, wall, colour)]
    for k, f in enumerate((1.08, 0.72, 0.38)):
        out.append(_solid([_rect(x, y, w * 1.04, d * f)], wall + k * d * 0.16, wall + (k + 1) * d * 0.16, roof))
    return out


def map_pillar(x: float, y: float, icons: list[str], colour: str, node: int) -> list[dict]:
    """Return the pillar of a map node: a dark plinth, the pillar in its colour (taller for a boss map), a light cap.

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
    r = K["map_r"]
    top = K["boss_map"] if any(i in _DEADLY for i in icons) else K["map"]
    return [
        _solid([_ngon(x, y, r * 1.22)], 0, top * 0.22, "#3a3d44", node=node),  # plinth
        _solid([_ngon(x, y, r)], top * 0.22, top, colour, node=node),
        _solid([_ngon(x, y, r * 0.55)], top, top + r * 0.35, "#e8e2cf", node=node),  # light cap
    ]


def _tower(x: float, y: float) -> list:
    """A Lost / Precursor tower: a stone shaft narrowing upwards, banded, a crenellated crown, the beacon on top."""
    S = [_solid([_ngon(x, y, 30, 8, 22.5)], 0, 12, "#6c6e74")]  # plinth
    for z0, z1, r, c in ((12, 60, 20, "#8d8f95"), (60, 108, 18, "#878990"), (108, 145, 16, "#8d8f95")):
        S.append(_solid([_ngon(x, y, r, 8, 22.5)], z0, z1, c))
    S += [_solid([_ngon(x, y, r, 8, 22.5)], z, z + 4, "#6f7178") for z, r in ((58, 21.5), (106, 19.5))]  # bands
    S.append(_solid([_ngon(x, y, 25, 8, 22.5)], 145, 155, "#6f7178"))  # crown
    S += _merlons(_ngon(x, y, 22, 8, 22.5), 7, 155, 165, "#7a7c82")
    S.append(_solid([_ngon(x, y, 9, 8)], 155, 168, "#5d5f66"))  # the beacon's pedestal
    S += [_solid([_ngon(x, y, 7, 6)], 168, 196, "#9fe8ff"), _solid([_ngon(x, y, 3.5, 6)], 196, 206, "#9fe8ff")]
    return S


def _vaal(x: float, y: float) -> list:
    """The Stone Citadel: a stepped pyramid with stairs up each side, a pillared temple on top, two obelisks."""
    S = []
    sides = (160, 124, 88, 52)
    for k, side in enumerate(sides):
        S.append(_solid([_square(x, y, side)], 28 * k, 28 * (k + 1), ("#b8955a", "#c29f62", "#cba86a", "#d4b273")[k]))
    # the stairs: a step block up the middle of each side, reaching each level
    for k, side in enumerate(sides):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cx, cy = x + dx * (side / 2 + 7), y + dy * (side / 2 + 7)
            w, d = (14, 22) if dx else (22, 14)
            S.append(_solid([_rect(cx, cy, w, d)], 28 * k, 28 * k + 14, "#a88650"))
    S.append(_solid([_square(x, y, 40)], 112, 116, "#e2c27e"))  # the temple's floor
    S += [_solid([_square(px, py, 6)], 116, 136, "#e8cc8c") for px, py in _ngon(x, y, 17, 4, 45)]  # its pillars
    S += [_solid([_square(x, y, 22)], 116, 136, "#d9b877"), _solid([_square(x, y, 42)], 136, 142, "#c9a363")]
    S += _cone(x, y, 18, 142, 158, "#c9a363", 4, 3)
    for px, py in ((x - 96, y + 52), (x + 96, y - 52)):  # obelisks
        S += [_solid([_square(px, py, 12)], 0, 6, "#a88650"), _solid([_square(px, py, 8)], 6, 70, "#c29f62")]
        S += _cone(px, py, 5, 70, 80, "#d4b273", 4, 2)
    return S


def _ezomyte(x: float, y: float) -> list:
    """The Iron Citadel: a walled town of many buildings and one mansion, dark stone and slate."""
    S = [_wall(_ngon(x, y, 92, 24), _ngon(x, y, 80, 24), 0, 26, "#4a4a50")]
    S += _merlons(_ngon(x, y, 86, 32, 5), 6, 26, 33, "#55555c")
    for px, py in _ngon(x, y, 86, 6, 15):  # wall towers with pointed roofs
        S += [_solid([_ngon(px, py, 13)], 0, 56, "#55555c")] + _cone(px, py, 15, 56, 80, "#2f3036")
    for k, (hx, hy) in enumerate(_ngon(x, y, 56, 7, 8)):  # houses inside the walls
        w, d = (24, 18) if k % 2 else (18, 24)
        S += _house(hx, hy, w, d, 22, "#6a6560", "#33343a")
    # the mansion: a long block with a steep roof and two towers
    S += _house(x, y, 54, 32, 34, "#5d5d64", "#2b2c31")
    for tx in (x - 30, x + 30):
        S += [_solid([_square(tx, y, 14)], 0, 58, "#55555c")] + _cone(tx, y, 10, 58, 82, "#2b2c31")
    return S


def _faridun(x: float, y: float) -> list:
    """The Copper Citadel: tents and tarps, caravan carts and stone pillars round a domed hall, on sand."""
    S = [_wall(_square(x, y, 170), _square(x, y, 156), 0, 14, "#c9b07a")]  # a low sand wall
    S += [  # stone pillars in a ring
        s
        for px, py in _ngon(x, y, 70, 10, 18)
        for s in (_solid([_square(px, py, 9)], 0, 46, "#a99060"), _solid([_square(px, py, 12)], 46, 50, "#8f7a50"))
    ]
    cloth = ("#b5653a", "#d8c28f", "#9c4a2e", "#c98f4a")
    for k, (tx, ty) in enumerate(_ngon(x, y, 52, 6, 30)):  # tents
        S += _cone(tx, ty, 14, 0, 26, cloth[k % 4], 6, 3)
    for cx, cy in ((x - 60, y + 66), (x + 64, y - 62), (x + 66, y + 58)):  # carts: a bed and a tarp
        S += [_solid([_rect(cx, cy, 20, 11)], 3, 9, "#7a5a3a"), _solid([_rect(cx, cy, 16, 9)], 9, 17, "#d8c28f")]
    S += [_solid([_square(x, y, 50)], 0, 34, "#d3bb86"), _solid([_square(x, y, 54)], 34, 38, "#b89d68")]  # the hall
    S += _dome(x, y, 22, 38, "#3f8a5a")
    S += [_solid([_ngon(x, y, 3, 6)], 60, 72, "#c9a24a")]  # its finial
    return S


def _town(x: float, y: float) -> list:
    """A city of no known type: a small walled town, crenellated, round a keep."""
    S = [_wall(_square(x, y, 150), _square(x, y, 136), 0, 24, "#6c6a66")]
    S += _merlons(_along_square(x, y, 143, 18), 6, 24, 31, "#77756f")
    for px, py in _ngon(x, y, 71.5 * math.sqrt(2), 4, 45):  # corner towers
        S += [_solid([_square(px, py, 18)], 0, 38, "#77756f"), _solid([_square(px, py, 22)], 38, 42, "#5f5d5b")]
    for hx, hy in ((x - 40, y - 40), (x + 40, y - 40), (x - 40, y + 40), (x + 40, y + 40)):
        S += _house(hx, hy, 26, 20, 16, "#8a8178", "#6b4a3a")
    S += [_solid([_square(x, y, 46)], 0, 64, "#7c7a78"), _solid([_square(x, y, 52)], 64, 70, "#5f5d5b")]  # the keep
    S += _merlons(_along_square(x, y, 48, 12), 6, 70, 78, "#6c6a66")
    return S


def _hall(x: float, y: float) -> list:
    """A hall: a platform, a long hall with a stepped roof, a pillared front, and the orange beam that marks it."""
    S = [_solid([_rect(x, y, 96, 74)], 0, 8, "#5a5048")]
    S.append(_solid([_rect(x, y, 76, 50)], 8, 40, "#6d6258"))
    for k, d in enumerate((58, 44, 30, 16)):  # the roof, stepping up along its length
        S.append(_solid([_rect(x, y, 82, d)], 40 + 6 * k, 46 + 6 * k, "#4a3f37"))
    S += [_solid([_square(x - 30 + 20 * k, y + 32, 6)], 8, 40, "#857a6e") for k in range(4)]  # pillars in front
    S.append(_solid([_ngon(x, y, 6)], 64, 420, "#ff8c1a"))  # the beam
    return S


def _breach(x: float, y: float, locked: bool) -> list:
    """A Breach stronghold: pointed crystals on dark rubble; a locked one dim and low."""
    S = [_solid([_ngon(x, y, 40, 9, 10)], 0, 4, "#2a1630")]
    tall = (140, 95, 120, 80, 110, 70, 100)
    colour = "#5a2a66" if locked else "#b84fd6"
    tip = "#6b3a78" if locked else "#e09af0"
    for k, (px, py) in enumerate([(x, y), *_ngon(x, y, 26, 6, 10)]):
        h = tall[k] * (0.45 if locked else 1)
        r = 11 if k == 0 else 8
        S.append(_solid([_ngon(px, py, r, 5, 18 * k)], 4, 4 + h * 0.7, colour))
        S += _cone(px, py, r * 0.9, 4 + h * 0.7, 4 + h, tip, 5, 3)
    return S


def structure(kind: str, x: float, y: float, city_type: str = "", locked: bool = False) -> list[dict]:
    """Return the model of a landmark.

    Args:
        kind: Landmark kind ("City", "Hall", "Tower", "Breach stronghold", "Deadly boss map").
        x: Its x (atlas units).
        y: Its y.
        city_type: "Vaal" / "Ezomyte" / "Faridun" for a City whose type is known, else "".
        locked: A locked Breach stronghold (hand icon).

    Returns:
        The shapes (empty for an unknown kind: a Deadly boss map has no building in the game, only its red icon; a
        red post stood on it: user).
    """
    if kind == "Tower":
        return _tower(x, y)
    if kind == "City":
        return {"Vaal": _vaal, "Ezomyte": _ezomyte, "Faridun": _faridun}.get(city_type, _town)(x, y)
    if kind == "Hall":
        return _hall(x, y)
    if kind == "Breach stronghold":
        return _breach(x, y, locked)
    return []
