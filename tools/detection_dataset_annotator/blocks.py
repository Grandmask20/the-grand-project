"""Spatial blocks of the screenshots, which the splits draw whole (``splits.assign_splits``).

Screenshots of one atlas overlap: drawn one by one, a held-out screenshot shares most of its map nodes with training
screenshots (``ANNOTATOR_SPLIT_BLOCK_SHOTS`` has the numbers). So an atlas's screenshots (those next to its
``atlas.json``, where the app finds them) are grouped by where they lie: k-means of their middles in atlas units, about
``ANNOTATOR_SPLIT_BLOCK_SHOTS`` to a block. A screenshot no atlas places is a block of its own.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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


def frame_middles(atlas_file: Path) -> dict[str, tuple[float, float]]:
    """Each placed screenshot's middle in atlas units, by its file name without the suffix (the frame's name)."""
    atlas = Atlas.load(atlas_file)
    out = {}
    for frame in atlas.frames:
        homography = screen_to_atlas(np.asarray(frame["M"], float), Atlas.frame_R(frame))
        x, y = persp(homography, [(frame["w"] / 2, frame["h"] / 2)])[0]
        out[str(frame["name"])] = (float(x), float(y))
    return out


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

    by_folder: dict[Path, list[str]] = {}
    for key in sorted(paths):
        by_folder.setdefault(Path(paths[key]).parent, []).append(key)
    out: dict[str, Block] = {}
    for folder, keys in by_folder.items():
        atlas_file = folder / K.ANNOTATOR_ATLAS_FILE
        middles = frame_middles(atlas_file) if atlas_file.is_file() else {}
        placed = [key for key in keys if Path(paths[key]).stem in middles]
        for key in set(keys) - set(placed):
            out[key] = Block(relative_source(Path(paths[key])))
        if not placed:
            continue
        points = np.array([middles[Path(paths[key]).stem] for key in placed], float)
        count = min(len(placed), max(1, math.ceil(len(placed) / shots_per_block)))
        if count == 1:
            labels = np.zeros(len(placed), int)
        else:
            labels = KMeans(n_clusters=count, n_init=10, random_state=seed).fit_predict(points)
        atlas = relative_source(folder)
        for key, label in zip(placed, labels, strict=True):
            out[key] = Block(atlas, int(label))
    return out


__all__ = ["Block", "frame_middles", "screenshot_blocks"]
