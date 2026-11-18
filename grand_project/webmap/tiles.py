"""webmap.tiles: the map's coordinates, its raster tiles (the map image) and its vector tiles, made when asked for.

MapLibre only knows the Web Mercator world, so the atlas is laid on it as a flat picture: at the most detailed tile
level `zmax` one map image pixel is one world pixel, and the picture sits in the middle half of the world (a quarter
of the world from its top-left corner). The margin keeps every point, and the page's pan limits around the picture,
inside the latitudes MapLibre accepts (the world's own edge is at 85 degrees). Every point is placed through world
pixels; longitude / latitude (for the page) are only the exact Mercator names of those pixels, so the picture, the
dots and the lines always line up.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .constants import WEBMAP_JPEG_QUALITY, WEBMAP_MVT_BUFFER, WEBMAP_MVT_EXTENT, WEBMAP_TILE
from .mvt import Layer, encode_tile, ring_area


class Grid:
    """Atlas units <-> world pixels <-> longitude / latitude, for one map image."""

    def __init__(self, origin: tuple[float, float, float], width: int, height: int):
        """Set up the grid for a map image.

        Args:
            origin: (x0, y0, scale) of the map image: atlas (x, y) is image px ((x - x0) * scale, (y - y0) * scale).
            width: Map image width in px.
            height: Map image height in px.
        """
        self.x0, self.y0, self.scale = (float(v) for v in origin)
        self.width, self.height = int(width), int(height)
        # the smallest level whose world holds the picture in its middle half: world = WEBMAP_TILE * 2 ** zmax px
        self.zmax = max(0, math.ceil(math.log2(max(self.width, self.height, 1) / WEBMAP_TILE))) + 1
        self.world = WEBMAP_TILE * 2**self.zmax
        self.offset = self.world // 4  # world px of the picture's top-left corner (both axes); 64 * 2**z at level z

    def deepest(self, px_per_unit: float) -> int:
        """Return the deepest tile level, so tiles get as sharp as px_per_unit (sharp ground past zmax).

        Args:
            px_per_unit: Wanted px per atlas unit at the deepest level.

        Returns:
            The level (zmax when the map image is already that sharp).
        """
        return self.zmax + max(0, math.ceil(math.log2(px_per_unit / self.scale - 1e-9)))

    def tile_area(self, z: int, x: int, y: int) -> tuple[float, float, float]:
        """Return what a tile past zmax covers on the atlas.

        Args:
            z: Tile level (>= zmax).
            x: Tile column.
            y: Tile row.

        Returns:
            (ax0, ay0, s): atlas point of the tile's top-left corner, and px per atlas unit at that level.
        """
        f = 2.0 ** (z - self.zmax)
        ax0 = (x * WEBMAP_TILE / f - self.offset) / self.scale + self.x0
        ay0 = (y * WEBMAP_TILE / f - self.offset) / self.scale + self.y0
        return ax0, ay0, self.scale * f

    def to_json(self) -> dict:
        """Return the grid's numbers (the page places the map from them).

        Returns:
            {"x0", "y0", "scale", "width", "height"}.
        """
        return {"x0": self.x0, "y0": self.y0, "scale": self.scale, "width": self.width, "height": self.height}

    def world_px(self, x: float, y: float) -> tuple[float, float]:
        """Convert an atlas point to world px at level zmax.

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            (wx, wy) world px.
        """
        return (x - self.x0) * self.scale + self.offset, (y - self.y0) * self.scale + self.offset

    def lnglat(self, x: float, y: float) -> list[float]:
        """Convert an atlas point to the longitude / latitude MapLibre uses for it.

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            [lng, lat] in degrees, rounded to 7 places (~1 cm on the equator: far below a pixel here).
        """
        wx, wy = self.world_px(x, y)
        lng = wx / self.world * 360.0 - 180.0
        lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy / self.world))))
        return [round(lng, 7), round(lat, 7)]

    def bounds(self) -> list[list[float]]:
        """Return the map image's corners as [[west, south], [east, north]] in degrees.

        Returns:
            The bounds MapLibre's fitBounds / maxBounds take.
        """
        to = lambda wx, wy: [  # noqa: E731
            wx / self.world * 360.0 - 180.0,
            math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy / self.world)))),
        ]
        o = self.offset
        (w, n), (e, s) = to(o, o), to(o + self.width, o + self.height)
        return [[w, s], [e, n]]


def _clip_segment(p, q, lo: float, hi: float):
    """Clip a segment to the square [lo, hi] x [lo, hi] (Liang-Barsky).

    Args:
        p: (x, y) start.
        q: (x, y) end.
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        ((x, y), (x, y)) of the part inside, or None when it misses the square.
    """
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - lo), (dx, hi - x0), (-dy, y0 - lo), (dy, hi - y0)):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def _clip_line(pts: list[tuple[float, float]], lo: float, hi: float) -> list[list[tuple[int, int]]]:
    """Clip a polyline to a square, as integer tile coordinates.

    Args:
        pts: Polyline vertices (tile-local floats).
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        The pieces inside (each 2+ distinct integer vertices).
    """
    pieces, cur = [], []
    for p, q in zip(pts, pts[1:], strict=False):
        c = _clip_segment(p, q, lo, hi)
        if c is None:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
            continue
        a = (round(c[0][0]), round(c[0][1]))
        b = (round(c[1][0]), round(c[1][1]))
        if not cur or cur[-1] != a:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = [a]
        if b != cur[-1]:
            cur.append(b)
    if len(cur) >= 2:
        pieces.append(cur)
    return pieces


def _clip_ring(ring: list[tuple[float, float]], lo: float, hi: float) -> list[tuple[int, int]]:
    """Clip a polygon ring to the square [lo, hi] x [lo, hi] (Sutherland-Hodgman), as integer tile coordinates.

    Args:
        ring: The ring's vertices (tile-local floats, not repeating the first).
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        The clipped ring (consecutive duplicates removed); fewer than 3 vertices when nothing is left.
    """
    pts = list(ring)
    for axis, edge, keep_above in ((0, lo, True), (0, hi, False), (1, lo, True), (1, hi, False)):
        if not pts:
            break
        inside = (lambda p, a=axis, e=edge: p[a] >= e) if keep_above else (lambda p, a=axis, e=edge: p[a] <= e)
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(_cross(prev, cur, axis, edge))
                out.append(cur)
            elif inside(prev):
                out.append(_cross(prev, cur, axis, edge))
        pts = out
    res = []
    for x, y in pts:
        q = (round(x), round(y))
        if not res or res[-1] != q:
            res.append(q)
    if len(res) > 1 and res[0] == res[-1]:
        res.pop()
    return res


def _cross(p, q, axis: int, edge: float) -> tuple[float, float]:
    """Return where segment p-q crosses the line coordinate[axis] = edge.

    Args:
        p: (x, y) start.
        q: (x, y) end.
        axis: 0 for a vertical line x = edge, 1 for a horizontal one.
        edge: The line's coordinate.

    Returns:
        The crossing point.
    """
    t = (edge - p[axis]) / (q[axis] - p[axis])
    return p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])


def _clip_polygon(rings: list[list[tuple[float, float]]], lo: float, hi: float) -> list[list[tuple[int, int]]]:
    """Clip a polygon (outer ring, then holes) to a square, oriented the way MVT wants (outer positive area).

    Args:
        rings: Outer ring first, then holes (tile-local floats).
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        The clipped rings (outer first); [] when the outer ring is gone.
    """
    out = []
    for k, ring in enumerate(rings):
        r = _clip_ring(ring, lo, hi)
        a = ring_area(r) if len(r) >= 3 else 0.0
        if abs(a) < 1:
            if k == 0:
                return []
            continue
        if (a > 0) != (k == 0):  # outer ring positive, holes negative
            r.reverse()
        out.append(r)
    return out


def _add_feature(get_layer, name: str, ft: dict, z: int, zmax: int, tx: int, ty: int) -> None:
    """Clip one feature to one tile and add it to the tile's layer.

    Args:
        get_layer: Function (name) -> the tile's mvt.Layer of that name (made on first use).
        name: Layer name.
        ft: The feature ({"kind", "pts" or "rings" in world px at zmax, "props", "id"}).
        z: Tile level.
        zmax: The grid's most detailed level (the feature's coordinates are at it).
        tx: Tile column.
        ty: Tile row.
    """
    E, B, T = WEBMAP_MVT_EXTENT, WEBMAP_MVT_BUFFER, WEBMAP_TILE
    f = 2.0 ** (z - zmax)
    k = E / T
    if ft["kind"] == "polygon":
        rings = [[((x * f - tx * T) * k, (y * f - ty * T) * k) for x, y in ring] for ring in ft["rings"]]
        clipped = _clip_polygon(rings, -B, E + B)
        if clipped:
            get_layer(name).add("polygon", clipped, ft["props"], ft.get("id"))
        return
    local = [((x * f - tx * T) * k, (y * f - ty * T) * k) for x, y in ft["pts"]]
    if ft["kind"] == "point":
        x, y = local[0]
        if -B <= x <= E + B and -B <= y <= E + B:
            get_layer(name).add("point", [(round(x), round(y))], ft["props"], ft.get("id"))
    else:
        for piece in _clip_line(local, -B, E + B):
            get_layer(name).add("line", piece, ft["props"], ft.get("id"))


def _bbox(ft: dict) -> tuple[float, float, float, float]:
    """Return a feature's box in world px at zmax.

    Args:
        ft: The feature.

    Returns:
        (x0, y0, x1, y1).
    """
    pts = ft["rings"][0] if ft["kind"] == "polygon" else ft["pts"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


class VectorTiler:
    """Vector tiles made when asked for, from features kept in memory (the app serves the live atlas this way).

    Features are sorted into a grid of cells (world px at zmax) so a tile only looks at those near it.
    """

    CELL = WEBMAP_TILE * 4  # world px at zmax per index cell

    def __init__(self, layers: dict[str, list[dict]], grid: Grid, min_zoom: dict[str, int] | None = None):
        """Index the features.

        Args:
            layers: Layer name -> features (see write_vector_tiles).
            grid: The grid (gives zmax).
            min_zoom: Layer name -> lowest tile level it is put in (dense layers are left out of the far-out
                tiles: they are not drawn there and made those tiles slow).
        """
        self.grid, self.layers, self.min_zoom = grid, layers, min_zoom or {}
        self.index: dict[tuple[int, int], list[tuple[str, int]]] = {}
        C = self.CELL
        for name, feats in layers.items():
            for i, ft in enumerate(feats):
                x0, y0, x1, y1 = _bbox(ft)
                ft["_bb"] = (x0, y0, x1, y1)
                for cx in range(int(x0 // C), int(x1 // C) + 1):
                    for cy in range(int(y0 // C), int(y1 // C) + 1):
                        self.index.setdefault((cx, cy), []).append((name, i))

    def tile(self, z: int, x: int, y: int) -> bytes:
        """Encode one vector tile.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            The tile's bytes (b"" when nothing is in it: an empty tile is a valid one).
        """
        zmax, T, C = self.grid.zmax, WEBMAP_TILE, self.CELL
        f = 2.0 ** (z - zmax)
        pad = WEBMAP_MVT_BUFFER / (WEBMAP_MVT_EXTENT / T) / f  # the buffer, in world px at zmax
        x0, y0 = x * T / f - pad, y * T / f - pad
        x1, y1 = (x + 1) * T / f + pad, (y + 1) * T / f + pad
        seen: set[tuple[str, int]] = set()
        tile_layers: dict[str, Layer] = {}

        def get_layer(name: str) -> Layer:
            """Return the tile's layer of that name, made on first use.

            Args:
                name: Layer name.

            Returns:
                The Layer.
            """
            return tile_layers.setdefault(name, Layer(name, WEBMAP_MVT_EXTENT))

        for cx in range(int(x0 // C), int(x1 // C) + 1):
            for cy in range(int(y0 // C), int(y1 // C) + 1):
                for key in self.index.get((cx, cy), ()):
                    if key in seen:
                        continue
                    seen.add(key)
                    name, i = key
                    if z < self.min_zoom.get(name, 0):
                        continue
                    ft = self.layers[name][i]
                    bx0, by0, bx1, by1 = ft["_bb"]
                    if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                        continue
                    _add_feature(get_layer, name, ft, z, zmax, x, y)
        order = list(self.layers)  # layers in the order given (MapLibre draws by style order anyway)
        return encode_tile([tile_layers[n] for n in order if n in tile_layers])


class RasterTiler:
    """Map image tiles made when asked for: each level is the one below halved, placed at the grid's offset."""

    def __init__(self, image: np.ndarray, grid: Grid):
        """Keep the map image.

        Args:
            image: The map image (BGR uint8), at the grid's offset at level zmax.
            grid: Its grid.
        """
        self.grid = grid
        self.levels: dict[int, np.ndarray] = {grid.zmax: image}

    def level(self, z: int) -> np.ndarray:
        """Return the map image at level z (made from the level above on first use).

        Args:
            z: Level 0..zmax.

        Returns:
            The image.
        """
        if z not in self.levels:
            up = self.level(z + 1)
            h, w = up.shape[:2]
            self.levels[z] = cv2.resize(up, (max(1, (w + 1) // 2), max(1, (h + 1) // 2)), interpolation=cv2.INTER_AREA)
        return self.levels[z]

    def pixels(self, z: int, x: int, y: int) -> np.ndarray | None:
        """Return one tile's pixels (levels 0..zmax).

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            BGR (WEBMAP_TILE, WEBMAP_TILE, 3), or None when the tile holds no ground.
        """
        if z > self.grid.zmax or z < 0:
            return None
        T = WEBMAP_TILE
        img = self.level(z)
        h, w = img.shape[:2]
        off = self.grid.offset >> (self.grid.zmax - z)
        x0, y0 = max(0, x * T - off), max(0, y * T - off)
        x1, y1 = min(w, (x + 1) * T - off), min(h, (y + 1) * T - off)
        if x1 <= x0 or y1 <= y0:
            return None
        crop = img[y0:y1, x0:x1]
        if not crop.any():
            return None
        tile = np.zeros((T, T, 3), np.uint8)
        dx, dy = x0 + off - x * T, y0 + off - y * T
        tile[dy : dy + crop.shape[0], dx : dx + crop.shape[1]] = crop
        return tile

    def jpeg(self, z: int, x: int, y: int) -> bytes | None:
        """Return one tile as JPEG.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            The JPEG bytes, or None when the tile holds no ground.
        """
        px = self.pixels(z, x, y)
        if px is None:
            return None
        ok, buf = cv2.imencode(".jpg", px, [cv2.IMWRITE_JPEG_QUALITY, WEBMAP_JPEG_QUALITY])
        return buf.tobytes() if ok else None
