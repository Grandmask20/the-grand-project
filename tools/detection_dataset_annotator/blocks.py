"""Spatial blocks of the screenshots, which the splits draw whole (``splits.assign_splits``).

Screenshots of one atlas overlap: drawn one by one, a held-out screenshot shares most of its map nodes with training
screenshots (``ANNOTATOR_SPLIT_BLOCK_SHOTS`` has the numbers). So an atlas's screenshots (those next to its
``atlas.json``, where the app finds them, or in a folder right below it) are grouped by where they lie: k-means of
their middles in atlas units, about ``ANNOTATOR_SPLIT_BLOCK_SHOTS`` to a block. A screenshot no atlas places
(``placed_by``) is a block of its own.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import numpy as np

from grand_project.core.atlas import Atlas
from grand_project.core.geometry import persp, screen_to_atlas

from . import constants as K
from .state import relative_source


@dataclass(frozen=True, order=True)
class Block:
    """A group of screenshots that goes to one split."""

    atlas: str
    """The atlas folder (project-relative), or the screenshot itself when no atlas places it."""
    index: int = 0
    """The block's number within its atlas."""


def atlas_of(folder: Path) -> Path | None:
    """The atlas file that places a folder's screenshots: next to them, else one folder up; None without one."""
    for place in (folder, folder.parent):
        if (place / K.ANNOTATOR_ATLAS_FILE).is_file():
            return place / K.ANNOTATOR_ATLAS_FILE
    return None


def frame_middles(atlas_file: Path) -> dict[tuple[str, ...], tuple[float, float]]:
    """Each placed screenshot's middle in atlas units, by the parts of the path the atlas saved for it (split at "/"
    and "\\": an atlas made on Windows saves Windows paths)."""
    atlas = Atlas.load(atlas_file)
    out = {}
    for frame in atlas.frames:
        homography = screen_to_atlas(np.asarray(frame["M"], float), Atlas.frame_R(frame))
        x, y = persp(homography, [(frame["w"] / 2, frame["h"] / 2)])[0]
        out[PureWindowsPath(str(frame["path"])).parts] = (float(x), float(y))
    return out


def placed_by(
    middles: dict[tuple[str, ...], tuple[float, float]], atlas_dir: Path, path: Path
) -> tuple[float, float] | None:
    """The middle of the screenshot at ``path`` in its atlas: the frame whose saved path ends with the file's own path
    from the atlas folder (``x.png`` next to it, ``pre/x.png`` in a folder below), wherever the atlas was made or
    moved; a file of a frame's name elsewhere is not that frame. None when no frame (or more than one) ends so.

    Not the frame's ``sha``: a screenshot re-encoded since the atlas was made (the trimmed test data) is still the
    one it placed.
    """
    try:
        own = Path(path).resolve().relative_to(Path(atlas_dir).resolve()).parts
    except ValueError:
        return None
    found = [middle for parts, middle in middles.items() if parts[-len(own) :] == own]
    return found[0] if len(found) == 1 else None


def screenshot_blocks(
    paths: Mapping[str, Path | str],
    *,
    shots_per_block: int = K.ANNOTATOR_SPLIT_BLOCK_SHOTS,
    seed: int = K.ANNOTATOR_SPLIT_SEED,
) -> dict[str, Block]:
    """The block of every screenshot.

    Args:
        paths: image key -> screenshot path.
        shots_per_block: about how many screenshots of an atlas make a block.
        seed: the k-means seed (the same screenshots give the same blocks).

    Returns:
        Image key -> its block, for every key of ``paths``.
    """
    from sklearn.cluster import KMeans  # imported here: only an export needs it

    by_atlas: dict[Path | None, list[str]] = {}
    for key in sorted(paths):
        by_atlas.setdefault(atlas_of(Path(paths[key]).parent), []).append(key)
    out: dict[str, Block] = {}
    for atlas_file, keys in by_atlas.items():
        middles = frame_middles(atlas_file) if atlas_file is not None else {}
        where = {key: placed_by(middles, atlas_file.parent, Path(paths[key])) if middles else None for key in keys}
        placed = [key for key in keys if where[key] is not None]
        for key in set(keys) - set(placed):
            out[key] = Block(relative_source(Path(paths[key])))
        if not placed:
            continue
        points = np.array([where[key] for key in placed], float)
        count = min(len(placed), max(1, math.ceil(len(placed) / shots_per_block)))
        if count == 1:
            labels = np.zeros(len(placed), int)
        else:
            labels = KMeans(n_clusters=count, n_init=10, random_state=seed).fit_predict(points)
        atlas = relative_source(atlas_file.parent)
        for key, label in zip(placed, labels, strict=True):
            out[key] = Block(atlas, int(label))
    return out


__all__ = ["Block", "frame_middles", "placed_by", "screenshot_blocks"]
