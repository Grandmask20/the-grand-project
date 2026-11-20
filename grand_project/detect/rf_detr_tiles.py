"""Native-scale tiles for RF-DETR: what the model sees of a screenshot, the same in training and inference.

A screenshot is read as the classical detector reads it (``core.scale_screenshot``: 1440p and 4K game windows to
1080p), its game HUD is painted over (``RF_DETR_HUD_FILL``: never labelled, and its round buttons are not map
icons), and it is cut into ``RF_DETR_TILE`` px squares overlapping by ``RF_DETR_TILE_OVERLAP`` (every object lies
whole in some tile). The model sees each tile at its own size, so a 39 px map node stays 39 px.

Training cuts random tiles (``random_tile``: scale jitter, tiles centred on rare classes, render-scale blur);
inference cuts the fixed grid (``tile_origins``) and keeps a predicted box only from a tile that holds it whole.
Images are numpy arrays (H, W, 3); boxes are ``[x, y, w, h]`` in the image's pixels.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from typing import Any

import cv2
import numpy as np

from grand_project import core

from . import constants as K


def normalise(image: np.ndarray, boxes: Sequence[Sequence[float]] = ()) -> tuple[np.ndarray, list[list[float]]]:
    """A screenshot and its boxes as the detector sees them: 1440p and 4K windows scaled to 1080p.

    Args:
        image: the screenshot at its original size (any 3-channel order).
        boxes: ``[x, y, w, h]`` boxes in the original's pixels.

    Returns:
        (the scaled image, the boxes scaled with it).
    """
    scaled = core.scale_screenshot(image)
    if scaled is image or scaled.shape[:2] == image.shape[:2]:
        return image, [list(map(float, box)) for box in boxes]
    sx, sy = scaled.shape[1] / image.shape[1], scaled.shape[0] / image.shape[0]
    return scaled, [[box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy] for box in boxes]


def fill_hud(image: np.ndarray, *, rgb: bool) -> np.ndarray:
    """A copy of a (1080p-scaled) screenshot with its game HUD painted ``RF_DETR_HUD_FILL`` (cropped screenshots
    have no HUD: ``core.hud_mask`` is empty for them)."""
    height, width = image.shape[:2]
    mask = core.hud_mask(width, height) > 0
    out = image.copy()
    if mask.any():
        fill = K.RF_DETR_HUD_FILL[::-1] if rgb else K.RF_DETR_HUD_FILL
        out[mask] = fill
    return out


def pad_to_tile(image: np.ndarray, tile: int = K.RF_DETR_TILE, *, rgb: bool) -> np.ndarray:
    """The image padded right and down with the HUD grey to at least one tile each way (a small cropped shot)."""
    height, width = image.shape[:2]
    if height >= tile and width >= tile:
        return image
    fill = K.RF_DETR_HUD_FILL[::-1] if rgb else K.RF_DETR_HUD_FILL
    out = np.empty((max(height, tile), max(width, tile), 3), image.dtype)
    out[:] = fill
    out[:height, :width] = image
    return out


def _starts(size: int, tile: int, overlap: int) -> list[int]:
    """Tile starts along one axis: every ``tile - overlap`` px, the last one flush with the far edge."""
    if size <= tile:
        return [0]
    stride = max(1, tile - overlap)
    starts = list(range(0, size - tile, stride))
    if not starts or starts[-1] != size - tile:
        starts.append(size - tile)
    return starts


def tile_origins(
    width: int, height: int, tile: int = K.RF_DETR_TILE, overlap: int = K.RF_DETR_TILE_OVERLAP
) -> list[tuple[int, int]]:
    """The (left, top) of every inference tile of a ``width`` x ``height`` image (8 for 1920x1080)."""
    return [(x, y) for y in _starts(height, tile, overlap) for x in _starts(width, tile, overlap)]


def crop_boxes(
    boxes: Sequence[Sequence[float]], left: float, top: float, right: float, bottom: float
) -> tuple[list[int], list[list[float]]]:
    """Clip boxes to a crop, keeping those with at least ``RF_DETR_AUGMENT_CROP_MIN_VISIBILITY`` of their area in it.

    Returns:
        (indices of the kept boxes, their boxes relative to the crop).
    """
    keep: list[int] = []
    out: list[list[float]] = []
    for index, (x, y, w, h) in enumerate(boxes):
        x0, y0 = max(float(x), left), max(float(y), top)
        x1, y1 = min(float(x) + float(w), right), min(float(y) + float(h), bottom)
        cw, ch = x1 - x0, y1 - y0
        if cw <= 1 or ch <= 1 or cw * ch / max(1.0, float(w) * float(h)) < K.RF_DETR_AUGMENT_CROP_MIN_VISIBILITY:
            continue
        keep.append(index)
        out.append([x0 - left, y0 - top, cw, ch])
    return keep, out


def cut_by_inner_edge(
    box: Sequence[float], origin: tuple[int, int], size: tuple[int, int], tile: int = K.RF_DETR_TILE
) -> bool:
    """Whether a box predicted in a tile touches one of the tile's edges that is not the image's own edge.

    Such a box is the part of an object the tile cuts off; the tiles overlap enough that another holds it whole.

    Args:
        box: ``[x0, y0, x1, y1]`` in tile px.
        origin: the tile's (left, top) in the image.
        size: the image's (width, height).
        tile: the tile side.
    """
    x0, y0, x1, y1 = box
    left, top = origin
    width, height = size
    edge = K.RF_DETR_TILE_EDGE
    return (
        (left > 0 and x0 <= edge)
        or (top > 0 and y0 <= edge)
        or (left + tile < width and x1 >= tile - edge)
        or (top + tile < height and y1 >= tile - edge)
    )


def repeat_factors(categories: Iterable[Iterable[int]], threshold: float = K.RF_DETR_REPEAT_THRESHOLD) -> list[float]:
    """LVIS repeat-factor sampling: how often each training image is drawn per epoch.

    A class on a share ``f`` of the images has the factor ``max(1, sqrt(threshold / f))``; an image takes the largest
    factor of its classes, so images holding a rare class (locked strongholds, citadels) are seen more often.

    Args:
        categories: the class ids of each image's boxes.
        threshold: the share under which a class repeats its images.

    Returns:
        One factor (>= 1) per image.
    """
    images = [set(map(int, ids)) for ids in categories]
    if not images:
        return []
    counts: dict[int, int] = {}
    for ids in images:
        for cid in ids:
            counts[cid] = counts.get(cid, 0) + 1
    per_class = {cid: max(1.0, math.sqrt(threshold / (count / len(images)))) for cid, count in counts.items()}
    return [max((per_class[cid] for cid in ids), default=1.0) for ids in images]


def epoch_indices(factors: Sequence[float], per_image: int, rng: random.Random) -> list[int]:
    """The images drawn in one training epoch, shuffled: each ``per_image`` x its repeat factor times (the fraction
    drawn at random, so on average exactly that often)."""
    out: list[int] = []
    for index, factor in enumerate(factors):
        times = per_image * float(factor)
        whole = int(times)
        out.extend([index] * (whole + (1 if rng.random() < times - whole else 0)))
    rng.shuffle(out)
    return out


def layer_lr_scale(name: str, layers: int, decay: float) -> float:
    """The learning-rate factor of a parameter: DINOv2 backbone layers decay from the top (the paper's 0.8 per
    layer: earlier layers keep more of their pre-training), its embeddings most; everything else trains at 1.

    Args:
        name: the parameter's name in the Transformers RF-DETR model.
        layers: the backbone's encoder layers (12 for DINOv2-S).
        decay: the factor per layer.
    """
    marker = "backbone.backbone."
    if marker not in name:
        return 1.0
    rest = name.split(marker, 1)[1]
    if rest.startswith("encoder.layer."):
        layer = int(rest.split(".")[2])
        return decay ** (layers - layer)
    return decay ** (layers + 1)  # embeddings (patch, position, class tokens) and anything before the layers


def rare_classes(categories: Iterable[Iterable[int]], threshold: float = K.RF_DETR_REPEAT_THRESHOLD) -> set[int]:
    """The class ids whose repeat factor is above 1 (on fewer than ``threshold`` of the images)."""
    images = [set(map(int, ids)) for ids in categories]
    counts: dict[int, int] = {}
    for ids in images:
        for cid in ids:
            counts[cid] = counts.get(cid, 0) + 1
    return {cid for cid, count in counts.items() if count / max(1, len(images)) < threshold}


def _render_blur(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """The image as a lower in-game render scale draws it: shrunk and enlarged back (``RF_DETR_AUGMENT_RENDER_*``)."""
    low, high = K.RF_DETR_AUGMENT_RENDER_SCALE
    factor = rng.uniform(low, high)
    height, width = image.shape[:2]
    small = cv2.resize(
        image, (max(1, round(width * factor)), max(1, round(height * factor))), interpolation=cv2.INTER_AREA
    )
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


def random_tile(
    image: np.ndarray,
    boxes: Sequence[Sequence[float]],
    categories: Sequence[int],
    rng: random.Random,
    *,
    rare: set[int] = frozenset(),
    tile: int = K.RF_DETR_TILE,
) -> tuple[np.ndarray, list[int], list[list[float]]]:
    """One training tile of a 1080p screenshot: a random square, sometimes centred on a rare class's object.

    The square is ``tile`` px give or take ``RF_DETR_AUGMENT_SCALE_JITTER``, resized to ``tile``; with probability
    ``RF_DETR_AUGMENT_RENDER_PROBABILITY`` it is blurred as a lower render scale draws it (and mirrored with
    ``RF_DETR_AUGMENT_FLIP_PROBABILITY``, 0: the atlas is never mirrored). Boxes are clipped to it
    (``crop_boxes``); a square without any box is tried again (``RF_DETR_AUGMENT_CROP_ATTEMPTS``).

    Args:
        image: the screenshot (normalised, HUD filled, padded to at least one tile).
        boxes: ``[x, y, w, h]`` boxes in its pixels.
        categories: each box's class id.
        rng: the random source.
        rare: class ids whose objects tiles are centred on with probability ``RF_DETR_AUGMENT_RARE_PROBABILITY``.
        tile: the output side.

    Returns:
        (the tile, the kept boxes' indices, their boxes in tile px).
    """
    height, width = image.shape[:2]
    jitter = K.RF_DETR_AUGMENT_SCALE_JITTER
    rare_boxes = [box for box, cid in zip(boxes, categories, strict=True) if cid in rare]
    best: tuple[int, int, int, list[int], list[list[float]]] | None = None
    for _ in range(K.RF_DETR_AUGMENT_CROP_ATTEMPTS):
        side = min(width, height, round(tile * rng.uniform(1 - jitter, 1 + jitter)))
        if rare_boxes and rng.random() < K.RF_DETR_AUGMENT_RARE_PROBABILITY:
            x, y, w, h = rng.choice(rare_boxes)
            cx = x + w / 2 + rng.uniform(-side / 4, side / 4)
            cy = y + h / 2 + rng.uniform(-side / 4, side / 4)
            left = int(min(max(0, cx - side / 2), width - side))
            top = int(min(max(0, cy - side / 2), height - side))
        else:
            left, top = rng.randint(0, width - side), rng.randint(0, height - side)
        keep, kept = crop_boxes(boxes, left, top, left + side, top + side)
        if best is None or len(keep) > len(best[3]):
            best = (left, top, side, keep, kept)
        if keep:
            break
    assert best is not None  # CROP_ATTEMPTS >= 1
    left, top, side, keep, kept = best
    out = image[top : top + side, left : left + side]
    if side != tile:
        scale = tile / side
        out = cv2.resize(out, (tile, tile), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        kept = [[v * scale for v in box] for box in kept]
    if rng.random() < K.RF_DETR_AUGMENT_RENDER_PROBABILITY:
        out = _render_blur(out, rng)
    if rng.random() < K.RF_DETR_AUGMENT_FLIP_PROBABILITY:  # off by default: the atlas is never mirrored
        out = out[:, ::-1]
        kept = [[tile - box[0] - box[2], box[1], box[2], box[3]] for box in kept]
    return np.ascontiguousarray(out), keep, kept


def densest_tile(
    image: np.ndarray, boxes: Sequence[Sequence[float]], tile: int = K.RF_DETR_TILE
) -> tuple[np.ndarray, list[int], list[list[float]]]:
    """The inference tile holding the most boxes whole: a fixed tile per screenshot for the validation loss."""
    height, width = image.shape[:2]
    best: tuple[int, int, list[int], list[list[float]]] = (0, 0, [], [])
    for left, top in tile_origins(width, height, tile):
        keep, kept = crop_boxes(boxes, left, top, left + tile, top + tile)
        if len(keep) > len(best[2]):
            best = (left, top, keep, kept)
    left, top, keep, kept = best
    return np.ascontiguousarray(image[top : top + tile, left : left + tile]), keep, kept


def prepare(image: np.ndarray, boxes: Sequence[Sequence[float]] = (), *, rgb: bool) -> tuple[np.ndarray, list]:
    """Everything before tiling: normalise to 1080p, paint the HUD, pad to at least one tile."""
    image, boxes = normalise(image, boxes)
    return pad_to_tile(fill_hud(image, rgb=rgb), rgb=rgb), boxes


def nms(detections: list[dict[str, Any]], iou: float, key: str = "family") -> list[dict[str, Any]]:
    """Keep the best-scored of detections of one ``key`` (a family) overlapping by ``iou`` or more.

    Args:
        detections: dicts with "box" ``[x0, y0, x1, y1]``, "score" and ``key``.
        iou: the overlap from which two detections are one object.
        key: detections compete only with those of the same value of this field.
    """
    kept: list[dict[str, Any]] = []
    for det in sorted(detections, key=lambda d: -d["score"]):
        if all(other[key] != det[key] or box_iou(det["box"], other["box"]) < iou for other in kept):
            kept.append(det)
    return kept


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union of two ``[x0, y0, x1, y1]`` boxes."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / max(1e-9, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


__all__ = [
    "box_iou",
    "crop_boxes",
    "cut_by_inner_edge",
    "densest_tile",
    "epoch_indices",
    "fill_hud",
    "layer_lr_scale",
    "nms",
    "normalise",
    "pad_to_tile",
    "prepare",
    "random_tile",
    "rare_classes",
    "repeat_factors",
    "tile_origins",
]
