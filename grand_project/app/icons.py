"""app.icons: names, search aliases, colours, row positions and pictures of the map content icon types."""

from __future__ import annotations

import contextlib
import io
import os
import re
import zipfile

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grand_project import paths as rc_paths

from .constants import ICON_ART_INNER, ICON_CROP_RIM, ICON_DRAW_REV, ICON_INFO, ICON_ROW_DY, ICON_ROW_STEP

_PICTURES: dict = {}  # PNG bytes per (art version, type, size, style) (icon_png)


def icon_art_version() -> str:
    """Return the version of the icon pictures: of how they are drawn and of what they are drawn from.

    The page's picture URLs carry it, so the browser (which keeps them for a year) asks again exactly when a picture
    can have changed: the drawing code (ICON_DRAW_REV), the game's art, poe2db's art, or the taught crops of the
    icon database ("from screenshots" changed with every icon taught, and stayed old: the page had a hand-bumped
    version instead).

    Returns:
        Short text, e.g. "3-1a2b3c4d".
    """
    import hashlib

    from grand_project import icon_refs

    h = hashlib.blake2b(digest_size=4)
    for p in (rc_paths.ref("atlas_icons.zip"), rc_paths.ref("poe2db_icons"), icon_refs.DB_PATH):
        try:
            h.update(str(p.stat().st_mtime_ns).encode())
        except OSError:
            h.update(b"-")
    # the newest poe2db picture too: one overwritten in place changes its own time, not its folder's (CodeRabbit)
    with contextlib.suppress(OSError), os.scandir(rc_paths.ref("poe2db_icons")) as it:
        h.update(str(max((e.stat().st_mtime_ns for e in it if e.is_file()), default=0)).encode())
    return f"{ICON_DRAW_REV}-{h.hexdigest()}"


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


def _zip_art(raw: str) -> Image.Image | None:
    """The game's own picture of an icon type from atlas_icons.zip (cropped to the icon, rim included), or None."""
    try:
        with zipfile.ZipFile(rc_paths.ref("atlas_icons.zip")) as z:
            want = {f"AtlasIconContent{raw}.webp", f"{raw}.webp"}
            name = next((n for n in z.namelist() if n.split("/")[-1] in want), None)
            if not name:
                return None
            im = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
    except (OSError, zipfile.BadZipFile, ValueError):
        return None
    bbox = im.getchannel("A").point(lambda a: 255 if a > 120 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def _rim(size: int) -> Image.Image | None:
    """The game's icon rim at `size` px: the outer ring of the Map Boss icon (inside it transparent), or None."""
    im = _zip_art("MapBoss")
    if im is None:
        return None
    im = im.resize((size, size), Image.LANCZOS)
    yy, xx = np.mgrid[:size, :size]
    r = np.hypot(xx - size / 2 + 0.5, yy - size / 2 + 0.5) / (size / 2)
    a = np.array(im.getchannel("A"))
    a[r < ICON_ART_INNER] = 0
    im.putalpha(Image.fromarray(a))
    return im


def _poe2db_art(raw: str, size: int) -> Image.Image | None:
    """poe2db's sharp art of an icon type (references/poe2db_icons): the whole icon, or the inner art set in the
    game's rim (user: the db pictures had no rim), or None."""
    try:  # a damaged picture falls through to the next source (CodeRabbit)
        return _poe2db_art_read(raw, size)
    except (OSError, ValueError):
        return None


def _poe2db_art_read(raw: str, size: int) -> Image.Image | None:
    """Read poe2db's art of an icon type (see _poe2db_art); raises when a picture can't be read."""
    folder = rc_paths.ref("poe2db_icons")
    full = folder / f"full__{raw}.webp"
    if full.exists():
        im = Image.open(full).convert("RGBA")
        bbox = im.getchannel("A").point(lambda a: 255 if a > 120 else 0).getbbox()
        return (im.crop(bbox) if bbox else im).resize((size, size), Image.LANCZOS)
    inner = folder / f"inner__{raw}.webp"
    if not inner.exists():
        return None
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    yy, xx = np.mgrid[:size, :size]
    disc = np.hypot(xx - size / 2 + 0.5, yy - size / 2 + 0.5) <= size / 2 * ICON_ART_INNER + 1
    out.paste((14, 12, 10, 255), (0, 0, size, size), Image.fromarray(disc.astype(np.uint8) * 255))
    d = round(size * ICON_ART_INNER * 0.98)
    art = Image.open(inner).convert("RGBA").resize((d, d), Image.LANCZOS)
    out.alpha_composite(art, ((size - d) // 2, (size - d) // 2))
    rim = _rim(size)
    if rim is not None:
        out.alpha_composite(rim)
    return out


def icon_picture(raw: str, size: int, style: str = "game art") -> Image.Image:
    """Return the picture of an icon type, every source drawn to the same size (rim to the edge).

    In order: the game's own icon from atlas_icons.zip; poe2db's sharp art (references/poe2db_icons, inner art put
    in the game's rim); a taught on-screen crop (icon database) cut at the rim, since the crop has a margin around
    the icon that drew those icons smaller than the others (user); a dot in the type's colour.

    Args:
        raw: The icon's raw (game) name, e.g. "LostTower".
        size: Width and height in px.

    Returns:
        PIL RGBA image of size (size, size).
    """
    if style in ("flat colour", "outline"):  # drawn from the type's colour (View tab: icon style)
        b, g, r = icon_col(raw)
        S = size * 4
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if style == "flat colour":
            d.ellipse((2, 2, S - 3, S - 3), fill=(r, g, b, 255), outline=(15, 15, 15, 255), width=S // 16)
        else:
            d.ellipse((S // 10, S // 10, S - S // 10 - 1, S - S // 10 - 1), outline=(r, g, b, 255), width=S // 8)
        return img.resize((size, size), Image.LANCZOS)
    img = None
    if style == "poe2db art":
        img = _poe2db_art(raw, size)
    if img is None and style != "from screenshots":
        img = _zip_art(raw)
    if img is None and style != "from screenshots":
        img = _poe2db_art(raw, size)
    if img is None:
        from grand_project import icon_refs as atlas_icon_refs

        try:
            refs = atlas_icon_refs.load(raw)[:1]
        except Exception:  # no icon database (a fresh install): the coloured dot below
            refs = []
        if refs and refs[0][1] is not None:
            c = cv2.cvtColor(refs[0][1], cv2.COLOR_BGR2RGB)
            hh, ww = c.shape[:2]
            r = min(ICON_CROP_RIM, min(hh, ww) / 2)  # the rim's outer edge in the crop
            cy, cx = hh / 2, ww / 2
            c = c[int(cy - r) : int(cy + r) + 1, int(cx - r) : int(cx + r) + 1]
            hh, ww = c.shape[:2]
            yy, xx = np.mgrid[:hh, :ww]
            alpha = (np.hypot(xx - ww / 2 + 0.5, yy - hh / 2 + 0.5) <= min(hh, ww) / 2).astype(np.uint8) * 255
            img = Image.fromarray(np.dstack([c, alpha]), "RGBA")
    if img is None and style == "from screenshots":  # no taught picture of this type: the game's art
        img = _zip_art(raw) or _poe2db_art(raw, size)
    if img is None:  # no picture: a dot in the type's colour
        b, g, r = icon_col(raw)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((4, 4, size - 4, size - 4), fill=(r, g, b, 255))
    return img.resize((size, size), Image.LANCZOS)


def icon_png(raw: str, size: int = 64, style: str = "game art") -> bytes:
    """Return an icon type's picture as PNG bytes, cached per type and size.

    Args:
        raw: The icon's raw (game) name.
        size: Width and height in px.

    Returns:
        The PNG file's bytes.
    """
    key = (icon_art_version(), raw, size, style)  # (a taught crop or new art: drawn again)
    hit = _PICTURES.get(key)  # read once: another request may clear the cache meanwhile (CodeRabbit)
    if hit is None:
        if len(_PICTURES) > 4000:  # old versions' pictures
            _PICTURES.clear()
        buf = io.BytesIO()
        icon_picture(raw, size, style).save(buf, "PNG")
        hit = _PICTURES[key] = buf.getvalue()
    return hit
