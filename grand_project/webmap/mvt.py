"""webmap.mvt: a small Mapbox Vector Tile (2.1) encoder: points, lines and polygons with simple properties.

No dependency: a vector tile is a short protocol-buffers message (layers -> features -> geometry commands), written
here by hand. Coordinates are tile-local integers (0..extent; a little outside is allowed, see WEBMAP_MVT_BUFFER).
"""

from __future__ import annotations

import struct

_POINT, _LINESTRING, _POLYGON = 1, 2, 3
_MOVE_TO, _LINE_TO, _CLOSE_PATH = 1, 2, 7


def _varint(n: int) -> bytes:
    """Encode a non-negative integer as a protocol-buffers varint.

    Args:
        n: The integer (>= 0).

    Returns:
        Its varint bytes.
    """
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _zigzag(n: int) -> int:
    """Map a signed integer to the unsigned zigzag form (0, -1, 1, -2 -> 0, 1, 2, 3).

    Args:
        n: The signed integer.

    Returns:
        Its zigzag value.
    """
    return (n << 1) ^ (n >> 63)


def _key(field: int, wire: int) -> bytes:
    """Encode a field key.

    Args:
        field: Field number.
        wire: Wire type (0 varint, 1 64-bit, 2 length-delimited, 5 32-bit).

    Returns:
        The key bytes.
    """
    return _varint((field << 3) | wire)


def _bytes_field(field: int, data: bytes) -> bytes:
    """Encode a length-delimited field (string, sub-message or packed list).

    Args:
        field: Field number.
        data: The field's bytes.

    Returns:
        The encoded field.
    """
    return _key(field, 2) + _varint(len(data)) + data


def _packed(field: int, values: list[int]) -> bytes:
    """Encode a packed repeated uint32 field.

    Args:
        field: Field number.
        values: Non-negative integers.

    Returns:
        The encoded field (empty bytes for an empty list).
    """
    if not values:
        return b""
    return _bytes_field(field, b"".join(_varint(v) for v in values))


def _value(v) -> bytes:
    """Encode a property value as an MVT Value message.

    Args:
        v: str, bool, int or float (anything else is stored as its str()).

    Returns:
        The Value message bytes.
    """
    if isinstance(v, bool):
        return _key(7, 0) + _varint(int(v))
    if isinstance(v, int):
        return _key(6, 0) + _varint(_zigzag(v)) if v < 0 else _key(5, 0) + _varint(v)
    if isinstance(v, float):
        return _key(3, 1) + struct.pack("<d", v)
    return _bytes_field(1, str(v).encode("utf-8"))


def ring_area(ring: list[tuple[int, int]]) -> float:
    """Return a ring's signed area in tile coordinates (y down): positive for an outer ring as MVT wants it.

    Args:
        ring: The ring's vertices (not repeating the first).

    Returns:
        The signed area.
    """
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True))


def _polygon(rings: list[list[tuple[int, int]]]) -> list[int]:
    """Encode a polygon's rings (outer first, then its holes) as MVT geometry commands.

    Args:
        rings: Rings of 3+ integer vertices, not repeating the first; outer positive area, holes negative.

    Returns:
        The command integers.
    """
    out, cx, cy = [], 0, 0
    for ring in rings:
        for i, (x, y) in enumerate(ring):
            if i == 0:
                out.append(_MOVE_TO | (1 << 3))
            elif i == 1:
                out.append(_LINE_TO | ((len(ring) - 1) << 3))
            out += [_zigzag(x - cx), _zigzag(y - cy)]
            cx, cy = x, y
        out.append(_CLOSE_PATH | (1 << 3))
    return out


def _geometry(kind: int, coords: list[tuple[int, int]]) -> list[int]:
    """Encode one point or one line as MVT geometry commands (zigzag deltas from the previous position).

    Args:
        kind: _POINT or _LINESTRING.
        coords: [(x, y)] tile-local integers (one point, or 2+ line vertices).

    Returns:
        The command integers.
    """
    out, cx, cy = [], 0, 0
    for i, (x, y) in enumerate(coords):
        if i == 0:
            out.append(_MOVE_TO | (1 << 3))
        elif i == 1 and kind == _LINESTRING:
            out.append(_LINE_TO | ((len(coords) - 1) << 3))
        out += [_zigzag(x - cx), _zigzag(y - cy)]
        cx, cy = x, y
    return out


class Layer:
    """One layer of a vector tile: features with properties, sharing key and value tables."""

    def __init__(self, name: str, extent: int):
        """Start an empty layer.

        Args:
            name: Layer name (the style's "source-layer").
            extent: Tile coordinate range.
        """
        self.name, self.extent = name, extent
        self.keys: dict[str, int] = {}
        self.values: dict[tuple, int] = {}
        self.features: list[bytes] = []

    def _tags(self, props: dict) -> list[int]:
        """Return the key/value index pairs of a feature's properties (None values are left out).

        Args:
            props: Property name -> value.

        Returns:
            [key index, value index, ...].
        """
        tags = []
        for k, v in props.items():
            if v is None:
                continue
            ki = self.keys.setdefault(k, len(self.keys))
            vk = (type(v).__name__, v)
            vi = self.values.setdefault(vk, len(self.values))
            tags += [ki, vi]
        return tags

    def add(self, kind: str, coords: list, props: dict, fid: int | None = None) -> None:
        """Add a feature.

        Args:
            kind: "point", "line" or "polygon".
            coords: Tile-local integer coordinates: one for a point, 2+ for a line; for a polygon its rings (outer
                first with positive ring_area, then its holes with negative), each 3+ vertices not repeating the
                first.
            props: Property name -> str / bool / int / float (None left out).
            fid: Optional feature id (>= 0).
        """
        geom_type = {"point": _POINT, "line": _LINESTRING, "polygon": _POLYGON}[kind]
        msg = b""
        if fid is not None:
            msg += _key(1, 0) + _varint(fid)
        msg += _packed(2, self._tags(props))
        msg += _key(3, 0) + _varint(geom_type)
        geom = _polygon(coords) if geom_type == _POLYGON else _geometry(geom_type, coords)
        msg += _packed(4, geom)
        self.features.append(msg)

    def encode(self) -> bytes:
        """Encode the layer message.

        Returns:
            The Layer message bytes.
        """
        msg = _key(15, 0) + _varint(2) + _bytes_field(1, self.name.encode("utf-8"))
        msg += b"".join(_bytes_field(2, f) for f in self.features)
        msg += b"".join(_bytes_field(3, k.encode("utf-8")) for k in self.keys)
        msg += b"".join(_bytes_field(4, _value(v)) for (_t, v) in self.values)
        msg += _key(5, 0) + _varint(self.extent)
        return msg


def encode_tile(layers: list[Layer]) -> bytes:
    """Encode a vector tile from its layers (empty layers are left out).

    Args:
        layers: The tile's layers.

    Returns:
        The tile's bytes (uncompressed).
    """
    return b"".join(_bytes_field(3, layer.encode()) for layer in layers if layer.features)
