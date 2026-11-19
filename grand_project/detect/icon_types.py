"""Icon types: the dataset classes they become and the picture that shows each one.

The types are the keys of ``ICON_INFO`` (detect/constants.py). The RF-DETR dataset and the dataset annotator label
an icon ``icon_<slug>`` (``icon_class``); ``icon_type`` turns such a class back into the type's name, so the slug's
lost capitals ("icon_abyssoverrun" -> "AbyssOverrun") come back. ``icon_picture`` is the one picture of a type, for
the annotator's label list and the viewer: its poe2db art, else a stored on-screen picture of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from grand_project import icon_refs
from grand_project import paths as rc_paths

from . import constants as K

_ALPHA_MIN = 120  # alpha from which a pixel of the art counts as part of the picture (its box is cut to them)


def slug(value: str) -> str:
    """Make a stable class suffix from an icon name.

    Lower case, every run of other characters one "_" ("Map Boss" -> "map_boss", "MapBoss" -> "mapboss").

    Args:
        value: The icon name.

    Returns:
        The suffix, "unknown" when nothing is left.
    """
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "unknown"


def icon_class(name: str) -> str:
    """The dataset class of an icon type, e.g. "MapBoss" -> "icon_mapboss".

    Args:
        name: The icon's type name.

    Returns:
        The class name.
    """
    return f"icon_{slug(name)}"


def dataset_icon_types() -> list[str]:
    """Every icon type a dataset labels, in ``ICON_INFO`` order (the annotator numbers its icon classes so).

    Returns:
        The type names, without the old names (``ICON_LEGACY``) and "Unidentified" (``ICON_NOT_A_CLASS``).
    """
    return [n for n in K.ICON_INFO if n not in K.ICON_LEGACY and n not in K.ICON_NOT_A_CLASS]


def icon_type(label: str) -> str | None:
    """The icon type of a dataset class, e.g. "icon_abyssoverrun" -> "AbyssOverrun".

    Args:
        label: A class name (``icon_class`` of a type).

    Returns:
        The type name from ``ICON_INFO``, or None for a class that is not one of them.
    """
    return {icon_class(name): name for name in K.ICON_INFO}.get(label)


def _decode(f: Path) -> np.ndarray | None:
    """A picture file as BGRA, cut to the box of its visible (alpha > _ALPHA_MIN) pixels; None if unreadable."""
    im = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    ys, xs = np.nonzero(im[..., 3] > _ALPHA_MIN)
    return im[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] if len(ys) else im


def _fit(im: np.ndarray, size: int) -> np.ndarray:
    """A BGRA picture centred on a transparent square (its sides kept) and resized to size x size."""
    h, w = im.shape[:2]
    side = max(h, w)
    square = np.zeros((side, side, 4), np.uint8)
    square[(side - h) // 2 : (side - h) // 2 + h, (side - w) // 2 : (side - w) // 2 + w] = im
    shrink = side >= size
    return cv2.resize(square, (size, size), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_LANCZOS4)


def _round(im: np.ndarray) -> np.ndarray:
    """A BGRA picture cut to the circle that fits in it (the game shows an icon's picture as a disc)."""
    h, w = im.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    disc = np.hypot(xx - w / 2 + 0.5, yy - h / 2 + 0.5) <= min(h, w) / 2 - 1
    out = im.copy()
    out[..., 3] = np.where(disc, out[..., 3], 0)
    return out


def _art(name: str) -> np.ndarray | None:
    """The type's own art: poe2db art (ICON_ART_DIR; the square atlas-tree art of "inner" files cut to the disc the
    game shows inside the rim), else its ICON_ART_FILES picture."""
    files = [(K.ICON_ART_DIR / f"{kind}__{name}.webp", kind == "inner") for kind in ("full", "inner")]
    if name in K.ICON_ART_FILES:
        files.append((rc_paths.ref(K.ICON_ART_FILES[name]), False))
    for f, disc in files:
        im = _decode(f) if f.is_file() else None
        if im is not None:
            return _round(im) if disc else im
    return None


def _stored(name: str) -> np.ndarray | None:
    """The type's first stored on-screen picture (icon database), cut to a circle."""
    refs = icon_refs.load(name)[:1]
    if not refs:
        return None
    c = refs[0][1]
    return _round(np.dstack([c, np.full(c.shape[:2], 255, np.uint8)]))


def icon_picture(name: str, size: int) -> np.ndarray | None:
    """The picture of an icon type: its art if it has some, else its first stored on-screen picture.

    Args:
        name: The icon's type name, e.g. "BreachHive".
        size: Width and height in px.

    Returns:
        (size, size, 4) BGRA uint8 picture (centred, its sides kept), or None when the type has neither.
    """
    im = _art(name)
    if im is None:
        im = _stored(name)
    return None if im is None else _fit(im, size)


def file_picture(f: Path, size: int) -> np.ndarray | None:
    """Any picture file (e.g. references/map_node_icon.webp) as icon_picture gives an icon type's.

    Args:
        f: The picture file.
        size: Width and height in px.

    Returns:
        (size, size, 4) BGRA uint8 picture, or None when the file is missing or unreadable.
    """
    im = _decode(f) if f.is_file() else None
    return None if im is None else _fit(im, size)


__all__ = ["dataset_icon_types", "file_picture", "icon_class", "icon_picture", "icon_type", "slug"]
