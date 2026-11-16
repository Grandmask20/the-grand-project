"""viewer.helpers (from atlas_viewer.py)"""

from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image

from grand_project import logs as atlas_log
from grand_project import paths as rc_paths

from .constants import ICON_INFO, ICON_ROW_DY, ICON_ROW_STEP, IS_MAC

_BLIT: dict = {}  # picture overlays, by size (blit_rgba)
_THUMBS: dict = {}  # badge thumbnails (icon_thumb)


def wheel_steps(e) -> float:
    """Mouse-wheel notches from a <MouseWheel> event: Windows reports multiples of 120, macOS small integers.

    Args:
        e: The Tk <MouseWheel> event.

    Returns:
        Notches turned (positive = away from the user), possibly fractional.
    """
    return e.delta / (1 if IS_MAC else 120)


LOG = atlas_log.get("viewer")


def hex_bgr(h: str, default):
    """Convert a "#rrggbb" colour to BGR.

    Args:
        h: Colour text such as "#ffcc00" (the leading # is optional); empty or malformed text gives the default.
        default: Value returned when h is not a valid colour (e.g. a BGR tuple, or None).

    Returns:
        (b, g, r) ints 0-255, or default.
    """
    try:
        h = h.lstrip("#")
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


def draw_paths(img, lines, col, th, style):
    """Draw many path polylines in one draw call: solid, or cut into dashes / dots first (fast at any zoom).

    Lines shorter than 2 px are skipped when cut into dashes / dots.

    Args:
        img: BGR uint8 image to draw into.
        lines: Polylines, each an (n, 2) array of points in screen px.
        col: BGR colour.
        th: Line width in px (dots are drawn at least 2 px or twice this).
        style: "solid", "dashed" or "dotted".
    """
    if not lines:
        return
    if style == "solid":
        cv2.polylines(img, [np.asarray(L, np.int32) for L in lines], False, col, th, cv2.LINE_AA)
        return
    on = max(6.0, 5.0 * th) if style == "dashed" else 0.5
    period = on + (max(4.0, 3.0 * th) if style == "dashed" else max(5.0, 4.0 * th))
    pieces = []
    for L in lines:
        L = np.asarray(L, float)
        seg = np.hypot(*np.diff(L, axis=0).T)
        cum = np.concatenate([[0], np.cumsum(seg)])
        if cum[-1] < 2:
            continue
        t0 = np.arange(0, cum[-1], period)
        t1 = np.minimum(t0 + on, cum[-1])
        x0, y0 = np.interp(t0, cum, L[:, 0]), np.interp(t0, cum, L[:, 1])
        x1, y1 = np.interp(t1, cum, L[:, 0]), np.interp(t1, cum, L[:, 1])
        pieces.extend(np.stack([np.column_stack([x0, y0]), np.column_stack([x1, y1])], 1).astype(np.int32))
    if pieces:
        w = th if style == "dashed" else max(2, 2 * th)
        cv2.polylines(img, pieces, False, col, w, cv2.LINE_AA)


def draw_map(img, pt, r, col, th, style, pic):
    """Draw one map node in the chosen style: circles / squares / map icons / hidden.

    Args:
        img: BGR uint8 image to draw into.
        pt: Centre (x, y) in screen px.
        r: Radius in screen px.
        col: BGR colour of the circle / square outline.
        th: Outline width in px.
        style: "circles", "squares", "map icons" or "hidden".
        pic: PIL RGBA map node picture, used by "map icons" (drawn 2.8 * r wide).
    """
    x, y = int(pt[0]), int(pt[1])
    if style == "hidden":
        return
    if style == "squares":
        cv2.rectangle(img, (int(x - r), int(y - r)), (int(x + r), int(y + r)), col, th, cv2.LINE_AA)
    elif style == "map icons":
        blit_rgba(img, pic, x, y, 2.8 * r)
    else:
        cv2.circle(img, (x, y), int(r), col, th, cv2.LINE_AA)


def blit_rgba(img, pil_rgba, x, y, size):
    """Paste a PIL RGBA picture centred at (x, y), `size` px wide, blended by its alpha.

    Resized pictures are cached by (picture, size); the cache keeps at most 400.

    Args:
        img: BGR uint8 image to draw into (clipped at its edges).
        pil_rgba: The PIL RGBA picture.
        x: Centre x in screen px.
        y: Centre y in screen px.
        size: Width and height in px, clamped to 6-96.
    """
    size = int(max(6, min(96, size)))
    key = (id(pil_rgba), size)
    if key not in _BLIT:
        a = np.asarray(pil_rgba.resize((size, size), Image.LANCZOS).convert("RGBA"), np.float32)
        _BLIT[key] = (a[..., [2, 1, 0]], a[..., 3:4] / 255.0)
        while len(_BLIT) > 400:
            _BLIT.pop(next(iter(_BLIT)))
    rgb, al = _BLIT[key]
    h, w = img.shape[:2]
    x0, y0 = int(x - size / 2), int(y - size / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(w, x0 + size), min(h, y0 + size)
    if xa >= xb or ya >= yb:
        return
    sub = img[ya:yb, xa:xb].astype(np.float32)
    r_ = rgb[ya - y0 : yb - y0, xa - x0 : xb - x0]
    a_ = al[ya - y0 : yb - y0, xa - x0 : xb - x0]
    img[ya:yb, xa:xb] = (sub * (1 - a_) + r_ * a_).astype(np.uint8)


def icon_rows(nodes: list[dict], icons: list[dict], icon_node: dict[int, int]) -> np.ndarray:
    """Where each icon is drawn: in a row above its map node, by the detector's rule.

    An icon's stored position is the average of where screenshots found it, so it drifts a few units off the
    row (half were over 6 units off, some 40; user: icons didn't line up like the detection rule). The icons of
    one map node are put in a row ICON_ROW_DY above it, ICON_ROW_STEP apart, centred on it, in their left-to-right
    order. Icons without a map node keep their own position.

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
        ic: Icon dict from V["icons"] ("name" and an optional "label").

    Returns:
        Its label if it has one, else the nice name of its type.
    """
    return ic.get("label") or icon_name(ic["name"])


def icon_thumb(raw: str, size: int = 22):
    """Small RGBA picture of an icon type, cached per type and size.

    The game's own icon from atlas_icons.zip when there is one, otherwise a taught reference crop (icon database)
    cut to a circle, otherwise a dot in the type's colour.

    Args:
        raw: The icon's raw (game) name, e.g. "LostTower".
        size: Width and height in px.

    Returns:
        PIL RGBA image of size (size, size).
    """
    key = (raw, size)
    if key in _THUMBS:
        return _THUMBS[key]
    img = None
    try:
        import io
        import zipfile

        with zipfile.ZipFile(rc_paths.ref("atlas_icons.zip")) as z:
            want = {f"AtlasIconContent{raw}.webp", f"{raw}.webp"}
            name = next((n for n in z.namelist() if n.split("/")[-1] in want), None)
            if name:
                im = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
                bbox = im.getchannel("A").point(lambda a: 255 if a > 120 else 0).getbbox()
                img = im.crop(bbox) if bbox else im
    except Exception:
        img = None
    if img is None:
        from grand_project import icon_refs as atlas_icon_refs

        refs = atlas_icon_refs.load(raw)[:1]
        if refs:
            c = refs[0][1]
            if c is not None:
                c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
                hh, ww = c.shape[:2]
                yy, xx = np.mgrid[:hh, :ww]
                alpha = (np.hypot(xx - ww / 2 + 0.5, yy - hh / 2 + 0.5) <= min(hh, ww) / 2 - 1).astype(np.uint8) * 255
                img = Image.fromarray(np.dstack([c, alpha]), "RGBA")
    if img is None:  # no picture: a dot in the type's colour
        b, g, r = icon_col(raw)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        from PIL import ImageDraw

        ImageDraw.Draw(img).ellipse((4, 4, size - 4, size - 4), fill=(r, g, b, 255))
    img = img.resize((size, size), Image.LANCZOS)
    _THUMBS[key] = img
    return img


def icon_col(raw: str):
    """The colour of an icon type.

    Args:
        raw: The icon's raw (game) name.

    Returns:
        BGR tuple from ICON_INFO, violet (230, 140, 255) for unknown types.
    """
    return ICON_INFO.get(raw, ("", (230, 140, 255), ""))[1]


def put_text(img, text, org, col, scale=0.5, thick=1):
    """Draw text with a black outline so it reads on any ground.

    Args:
        img: BGR uint8 image to draw into.
        text: The text.
        org: Bottom-left (x, y) of the text in px.
        col: BGR text colour.
        scale: OpenCV font scale.
        thick: Stroke width in px (the outline is the same stroke, 1 px around it).
    """
    x, y = int(org[0]), int(org[1])
    # the outline is the same text shifted a pixel each way, not one thicker stroke: with OpenCV 5's font a
    # thicker stroke also spaces the letters wider, so the black copy drifted right of the coloured text and
    # read as doubled black text (user: progress boxes)
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        cv2.putText(img, text, (x + dx, y + dy), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick, cv2.LINE_AA)
