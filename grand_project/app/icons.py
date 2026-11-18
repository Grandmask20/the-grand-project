"""app.icons: names, search aliases, colours, row positions and pictures of the map content icon types."""

from __future__ import annotations

import io
import re
import zipfile

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grand_project import paths as rc_paths

from .constants import ICON_INFO, ICON_ROW_DY, ICON_ROW_STEP

_PICTURES: dict = {}  # PNG bytes per (type, size) (icon_png)


def hex_bgr(h: str, default):
    """Convert a "#rrggbb" colour to BGR.

    Args:
        h: Colour text such as "#ffcc00" (the leading # is optional); empty or malformed text gives the default.
        default: Value returned when h is not a valid colour.

    Returns:
        (b, g, r) ints 0-255, or default.
    """
    try:
        h = (h or "").lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)) if len(h) == 6 else default
    except ValueError:
        return default


def bgr_hex(c) -> str:
    """Convert a BGR colour to "#rrggbb".

    Args:
        c: (b, g, r) values 0-255.

    Returns:
        The colour as "#rrggbb" text.
    """
    return f"#{int(c[2]):02x}{int(c[1]):02x}{int(c[0]):02x}"


def icon_rows(nodes: list[dict], icons: list[dict], icon_node: dict[int, int]) -> np.ndarray:
    """Where each icon is drawn: in a row above its map node, by the detector's rule.

    An icon's stored position is the average of where screenshots found it, so it drifts a few units off the row.
    The icons of one map node are put in a row ICON_ROW_DY above it, ICON_ROW_STEP apart, centred on it, in their
    left-to-right order. Icons without a map node keep their own position.

    Args:
        nodes: Map node dicts with "x", "y" (atlas units).
        icons: Icon dicts with "x", "y".
        icon_node: Icon index -> map node index (cities.icon_maps).

    Returns:
        (len(icons), 2) float array of positions in atlas units.
    """
    pts = np.array([[ic["x"], ic["y"]] for ic in icons], float).reshape(-1, 2)
    rows: dict[int, list[int]] = {}
    for i, v in icon_node.items():
        rows.setdefault(v, []).append(i)
    for v, members in rows.items():
        members.sort(key=lambda i: pts[i, 0])
        n = nodes[v]
        for k, i in enumerate(members):
            pts[i] = (n["x"] + (k - (len(members) - 1) / 2) * ICON_ROW_STEP, n["y"] - ICON_ROW_DY)
    return pts


def icon_aliases(raw: str) -> str:
    """Every name an icon type can be searched by.

    Args:
        raw: The icon's raw (game) name, e.g. "MapBoss".

    Returns:
        Lower-case text with the nice name, the aliases from ICON_INFO and the raw name.
    """
    info = ICON_INFO.get(raw)
    return f"{info[0]} {info[2]} {raw}".lower() if info else raw.lower()


def icon_name(raw: str) -> str:
    """The nice name of an icon type.

    Args:
        raw: The icon's raw (game) name.

    Returns:
        The name from ICON_INFO, else the raw name split into words ("MapBoss" -> "Map boss").
    """
    if raw in ICON_INFO:
        return ICON_INFO[raw][0]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", raw).capitalize()


def icon_label(ic: dict) -> str:
    """The text shown for an icon.

    Args:
        ic: Icon dict ("name" and an optional "label").

    Returns:
        Its label if it has one, else the nice name of its type.
    """
    return ic.get("label") or icon_name(ic["name"])


def icon_col(raw: str):
    """The colour of an icon type.

    Args:
        raw: The icon's raw (game) name.

    Returns:
        BGR tuple from ICON_INFO, violet (230, 140, 255) for unknown types.
    """
    return ICON_INFO.get(raw, ("", (230, 140, 255), ""))[1]


def icon_picture(raw: str, size: int) -> Image.Image:
    """Return the picture of an icon type.

    The game's own icon from atlas_icons.zip when there is one, otherwise a taught reference crop (icon database)
    cut to a circle, otherwise a dot in the type's colour.

    Args:
        raw: The icon's raw (game) name, e.g. "LostTower".
        size: Width and height in px.

    Returns:
        PIL RGBA image of size (size, size).
    """
    img = None
    try:
        with zipfile.ZipFile(rc_paths.ref("atlas_icons.zip")) as z:
            want = {f"AtlasIconContent{raw}.webp", f"{raw}.webp"}
            name = next((n for n in z.namelist() if n.split("/")[-1] in want), None)
            if name:
                im = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
                bbox = im.getchannel("A").point(lambda a: 255 if a > 120 else 0).getbbox()
                img = im.crop(bbox) if bbox else im
    except (OSError, zipfile.BadZipFile, ValueError):
        img = None
    if img is None:
        from grand_project import icon_refs as atlas_icon_refs

        try:
            refs = atlas_icon_refs.load(raw)[:1]
        except Exception:  # no icon database (a fresh install): the coloured dot below
            refs = []
        if refs and refs[0][1] is not None:
            c = cv2.cvtColor(refs[0][1], cv2.COLOR_BGR2RGB)
            hh, ww = c.shape[:2]
            yy, xx = np.mgrid[:hh, :ww]
            alpha = (np.hypot(xx - ww / 2 + 0.5, yy - hh / 2 + 0.5) <= min(hh, ww) / 2 - 1).astype(np.uint8) * 255
            img = Image.fromarray(np.dstack([c, alpha]), "RGBA")
    if img is None:  # no picture: a dot in the type's colour
        b, g, r = icon_col(raw)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((4, 4, size - 4, size - 4), fill=(r, g, b, 255))
    return img.resize((size, size), Image.LANCZOS)


def icon_png(raw: str, size: int = 64) -> bytes:
    """Return an icon type's picture as PNG bytes, cached per type and size.

    Args:
        raw: The icon's raw (game) name.
        size: Width and height in px.

    Returns:
        The PNG file's bytes.
    """
    key = (raw, size)
    if key not in _PICTURES:
        buf = io.BytesIO()
        icon_picture(raw, size).save(buf, "PNG")
        _PICTURES[key] = buf.getvalue()
    return _PICTURES[key]
