"""The page's pictures made from Path of Exile 2's own interface art (frontend/src/assets/poe, © Grinding Gear Games).

    python -m tools.poe_art --ui "<the game's UI folder>" [--out frontend/src/assets/poe] [tabs bar frame grain]
    python -m tools.poe_art --trim <picture.png> [...] [--out ...]

The game's pictures carry empty space at their right and bottom; every one used is cut to its art first (--trim
does that for single pictures, the plain copies). These are made from several:

- tabs: the stash tab (stashtablit.png, stashtabunlit.png) from its grey pieces (common/tablabel{left,middle,right}),
  lined up by their bottom strips (each piece's bottom notch is where its neighbour's strip goes: user), recoloured to
  the stash tab colours (lit: the art's own top-dark / bottom-light fade onto #473a23 -> #6b5838, its foot merging
  into the bar; unlit: one flat #4e422c) and textured with the stash tab texture (stashtabwindow/stashtablabeltexture).
- bar: the bar the tabs stand on (stashtabbar.png), that texture in the bar's colour, repeating with no seam.
- frame: the panels' frame (stashframe9.png), the stash panel's gold-lined ring (stashtabwindow/stashtabbg) in nine
  parts.
- grain: the panels' dark grain (stashunavailablebg.jpg), the stash's unavailable tab (stashtabwindow).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "frontend" / "src" / "assets" / "poe"

TAB_ROWS = 44  # the tab down to just under its feet (the strips below only line the pieces up)
TAB_MIDDLES = 7  # middle pieces in a row: wider than most tabs, so the page shrinks the middle rather than stretches it
TEXTURE_DEPTH = 0.55  # how strongly the texture shows (its light and dark, around its mean)
TOP, BOTTOM, FLAT, EDGE = "#473a23", "#6b5838", "#4e422c", "#5c4c30"  # the user's stash tab colours (from the game)
FRAME_RING = 16  # px: the stash panel's frame (its gold line and the dark band inside it); the slate starts after
FRAME_MIDDLE = 64  # px: the middle span of the composed frame
BAR_ROWS = 9  # the bar: as tall as 6px at the tabs' scale (the tab's last 9 rows)
BAR_FADE = 48  # px: the bar texture's ends cross-faded so it repeats without a seam


def trimmed(im: Image.Image) -> Image.Image:
    """Return a picture cut to its art (the game's carry empty space at their right and bottom)."""
    im = im.convert("RGBA")
    a = np.asarray(im)[..., 3]
    ys, xs = np.where(a > 8)
    if not len(xs):
        return im
    return im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def _hex(h: str) -> np.ndarray:
    return np.array([int(h[i : i + 2], 16) for i in (1, 3, 5)], np.float32)


def line_up(left: np.ndarray, mid: np.ndarray, right: np.ndarray, middles: int = TAB_MIDDLES) -> np.ndarray:
    """Return the tab pieces (RGBA arrays, 50 rows) laid side by side by their bottom strips: each piece's strip
    starts where the one before ends (left's ends at its column 31; the middle's runs 9..35; right's starts at 8),
    one column over at the right piece (its first column is soft)."""
    offs = [(left, 0)] + [(mid, 23 + 27 * k) for k in range(middles)]
    offs.append((right, 23 + 27 * (middles - 1) + 35 - 8))
    width = offs[-1][1] + right.shape[1]
    out = np.zeros((left.shape[0], width, 4), np.float32)
    for p, x in offs:
        w = min(p.shape[1], width - x)
        a = p[:, :w, 3:4] / 255
        out[:, x : x + w, :3] = p[:, :w, :3] * a + out[:, x : x + w, :3] * (1 - a)
        out[:, x : x + w, 3:4] = 255 * (a + out[:, x : x + w, 3:4] / 255 * (1 - a))
    return out


def texture_light(texture: Image.Image, rows: int, width: int) -> np.ndarray:
    """Return the texture's light, around 1, `width` columns of it (its own pixels across, not stretched; repeated
    when it is narrower; its rows to `rows`)."""
    tex = trimmed(texture).convert("RGB")
    tex = tex.resize((tex.width, rows), Image.BILINEAR)
    lum = np.asarray(tex).astype(np.float32) @ np.array([0.3, 0.59, 0.11], np.float32)
    lum = np.tile(lum, (1, -(-width // lum.shape[1])))[:, :width]
    # (around the mean of the part used: so the lit tab's foot comes out the bar's colour, as the user approved)
    return 1 + TEXTURE_DEPTH * (lum / lum.mean() - 1)


def stash_tab(grey: np.ndarray, light: np.ndarray, lit: bool) -> Image.Image:
    """Return the stash tab in its colours from its grey line-up (rows: TAB_ROWS): the dark outline a shadow, the
    light line inside it the edge, the rest the fill (lit: the art's fade mapped onto the lit colours; unlit: flat)."""
    lum, alpha = grey[..., 0], grey[..., 3]
    dark = (lum < 120) & (alpha > 8)
    near = np.zeros_like(dark)
    for dy in (-1, 0, 1):
        for dx in (-2, -1, 0, 1, 2):
            near |= np.roll(np.roll(dark, dy, 0), dx, 1)
    edge = ~dark & near & (lum > 180)
    fill = ~dark & ~edge & (alpha > 8)
    rows = np.arange(grey.shape[0], dtype=np.float32)[:, None]
    top, bottom, flat, edge_c = _hex(TOP), _hex(BOTTOM), _hex(FLAT), _hex(EDGE)
    if lit:
        t = np.clip((lum - 161) / (239 - 161), 0, 1)[..., None]  # (the art's fill: grey 161 at its top, 239 below)
        col = top + (bottom - top) * t
        ecol = edge_c + (bottom - edge_c) * np.clip((rows - 26) / 14, 0, 1)[..., None]
        shadow = alpha * 0.9 * (1 - np.clip((rows - 37) / 5, 0, 1))  # (gone in its foot: it merges into the bar)
    else:
        count = fill.sum(axis=1, keepdims=True)
        row_mean = np.where(count > 0, np.where(fill, lum, 0).sum(axis=1, keepdims=True) / np.maximum(count, 1), 200)
        col = flat + ((lum - row_mean) * 0.18)[..., None]  # (the fade taken out, its fine grain kept a little)
        ecol = np.broadcast_to(edge_c, grey.shape[:2] + (3,))
        shadow = alpha * 0.9
    col = col * light[..., None]
    out = np.zeros(grey.shape, np.float32)
    out[..., :3] = np.where(fill[..., None], col, np.where(edge[..., None], ecol, 0))
    out[..., 3] = np.where(fill | edge, alpha, np.where(dark, shadow, 0))
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def make_tabs(ui: Path, out: Path) -> None:
    pieces = [
        np.asarray(trimmed(Image.open(ui / "common" / f"tablabel{n}.png"))).astype(np.float32)[:50]
        for n in ("left", "middle", "right")
    ]
    grey = line_up(*pieces)
    assert (grey[45, 4:-4, 3] > 200).all(), "the tab pieces' bottom strips don't meet"
    grey = grey[:TAB_ROWS]
    light = texture_light(
        Image.open(ui / "ingame" / "stashtabwindow" / "stashtablabeltexture.png"), TAB_ROWS, grey.shape[1]
    )
    stash_tab(grey, light, True).save(out / "stashtablit.png")
    stash_tab(grey, light, False).save(out / "stashtabunlit.png")


def make_bar(ui: Path, out: Path) -> None:
    tex = Image.open(ui / "ingame" / "stashtabwindow" / "stashtablabeltexture.png")
    light = texture_light(tex, TAB_ROWS, trimmed(tex).width)[TAB_ROWS - BAR_ROWS :]
    w = light.shape[1] - BAR_FADE
    band = light[:, :w].copy()
    f = np.linspace(0, 1, BAR_FADE)[None, :]
    band[:, :BAR_FADE] = light[:, w:] * (1 - f) + light[:, :BAR_FADE] * f
    img = np.clip(_hex(BOTTOM)[None, None, :] * band[..., None], 0, 255).astype(np.uint8)
    Image.fromarray(img, "RGB").save(out / "stashtabbar.png")


def make_frame(ui: Path, out: Path) -> None:
    im = trimmed(Image.open(ui / "ingame" / "stashtabwindow" / "stashtabbg.png"))
    w, h, r, m = im.width, im.height, FRAME_RING, FRAME_MIDDLE
    s = 2 * r + m
    f = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mx, my = w // 2 - m // 2, h // 2 - m // 2
    for box, at in (
        ((0, 0, r, r), (0, 0)),
        ((w - r, 0, w, r), (s - r, 0)),
        ((0, h - r, r, h), (0, s - r)),
        ((w - r, h - r, w, h), (s - r, s - r)),
        ((mx, 0, mx + m, r), (r, 0)),
        ((mx, h - r, mx + m, h), (r, s - r)),
        ((0, my, r, my + m), (0, r)),
        ((w - r, my, w, my + m), (s - r, r)),
    ):
        f.paste(im.crop(box), at)
    f.save(out / "stashframe9.png")


def make_grain(ui: Path, out: Path) -> None:
    im = trimmed(Image.open(ui / "ingame" / "stashtabwindow" / "stashunavailablebg.png")).convert("RGB")
    im.save(out / "stashunavailablebg.jpg", quality=88)


MAKERS = {"tabs": make_tabs, "bar": make_bar, "frame": make_frame, "grain": make_grain}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", nargs="*", help=f"what to make: {', '.join(MAKERS)} (default: all)")
    ap.add_argument("--ui", type=Path, help="the game's exported UI folder (with common/ and ingame/)")
    ap.add_argument("--trim", type=Path, nargs="+", help="game pictures to copy, cut to their art")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if bad := [w for w in a.what if w not in MAKERS]:
        ap.error(f"nothing called {', '.join(bad)} (there are {', '.join(MAKERS)})")
    a.out.mkdir(parents=True, exist_ok=True)
    for p in a.trim or []:
        trimmed(Image.open(p)).save(a.out / p.name)
        print("trimmed", p.name)
    if a.trim and not a.what:
        return 0
    if a.ui is None:
        ap.error("--ui is needed to make tabs, bar, frame or grain")
    for name in a.what or MAKERS:
        MAKERS[name](a.ui, a.out)
        print("made", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
