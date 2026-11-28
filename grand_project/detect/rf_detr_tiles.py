"""Native-scale tiles for RF-DETR: what the model sees of a screenshot, the same in training and inference.

A screenshot is read as the classical detector reads it (``core.scale_screenshot``: 1440p and 4K game windows to
1080p), its game HUD is painted over (``RF_DETR_HUD_FILL``: never labelled, and its round buttons are not map
icons), and it is cut into ``RF_DETR_TILE`` px squares overlapping by ``RF_DETR_TILE_OVERLAP`` (every object lies
whole in some tile). The model sees each tile at its own size, so a 39 px map node stays 39 px.

Training cuts random tiles (``random_tile``: scale jitter, tiles centred on rare classes, render-scale blur,
brightness and contrast);
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
    # strict: a box reaching the margin but not into it is whole (the overlap is exactly the tallest box, a tower,
    # plus both margins: one tile always holds it so)
    return (
        (left > 0 and x0 < edge)
        or (top > 0 and y0 < edge)
        or (left + tile < width and x1 > tile - edge)
        or (top + tile < height and y1 > tile - edge)
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


def epoch_length(factors: Sequence[float], per_image: int) -> int:
    """How many images one training epoch draws: ``per_image`` x the sum of the repeat factors, rounded."""
    return round(sum(per_image * float(factor) for factor in factors))


def _draw_chances(weights: Sequence[float], draws: int) -> list[float]:
    """Chances in proportion to ``weights`` that add up to ``draws``, none above 1: a weight whose share would pass 1
    gets 1, and the rest share what is left (``draws`` is at most the number of weights)."""
    chances = [0.0] * len(weights)
    free = set(range(len(weights)))
    left = float(draws)
    while free:
        total = sum(weights[i] for i in free)
        full = {i for i in free if weights[i] * left >= total}
        if not full:
            for i in free:
                chances[i] = weights[i] * left / total
            break
        for i in full:
            chances[i] = 1.0
        free -= full
        left -= len(full)
    return chances


def epoch_indices(factors: Sequence[float], per_image: int, rng: random.Random) -> list[int]:
    """The images drawn in one training epoch, shuffled: each ``per_image`` x its repeat factor times.

    Always ``epoch_length`` draws (the Trainer sizes an epoch by the sampler's length): every image's whole number
    of draws, then at most one more each, by systematic sampling over chances in proportion to their fractions
    (``_draw_chances``), so an image's fraction is (about) its chance of one more.
    """
    times = [per_image * float(factor) for factor in factors]
    out = [index for index, count in enumerate(times) for _ in range(int(count))]
    extra = epoch_length(factors, per_image) - len(out)
    fractions = [(index, count - int(count)) for index, count in enumerate(times) if count > int(count)]
    if extra > 0 and fractions:
        rng.shuffle(fractions)
        chances = _draw_chances([fraction for _index, fraction in fractions], extra)
        mark, reach = rng.random(), 0.0
        drawn: set[int] = set()
        for (index, _fraction), chance in zip(fractions, chances, strict=True):
            reach += chance
            if mark < reach and extra > 0:  # one mark in each step of 1, and no chance is above 1: one draw at most
                out.append(index)
                drawn.add(index)
                extra -= 1
                mark += 1.0
        # the last mark missed the end by a rounding error (the chances summed in another order): images not drawn
        out.extend([index for index, _fraction in reversed(fractions) if index not in drawn][:extra])
    rng.shuffle(out)
    return out


_BACKBONE = "backbone.backbone."
"""Where the DINOv2 backbone's parameters sit in the Transformers RF-DETR (``model.backbone.backbone.``)."""


def layer_lr_scale(name: str, layers: int, decay: float) -> float:
    """The learning-rate factor of a backbone parameter, the reference implementation's rule
    (roboflow/rf-detr ``get_dinov2_lr_decay_rate``): layers decay from the top (the paper's 0.8 per layer: earlier
    layers keep more of their pre-training), the embeddings most, the rest of the backbone (its final layer norm)
    not at all; parameters outside the backbone get 1.

    Args:
        name: the parameter's name in the Transformers RF-DETR model.
        layers: ``backbone_config.out_indices[-1] + 1``, as the reference counts them (13 for DINOv2-S).
        decay: the factor per layer.
    """
    if _BACKBONE not in name:
        return 1.0
    rest = name.split(_BACKBONE, 1)[1]
    if rest.startswith("embeddings."):
        layer = 0
    elif rest.startswith("encoder.layer."):
        layer = int(rest.split(".")[2]) + 1
    else:
        layer = layers + 1
    return decay ** (layers + 1 - layer)


def backbone_weight_decay(name: str) -> bool:
    """Whether a backbone parameter takes weight decay: not its layer scales, embeddings, biases or norms (the
    reference's ``get_dinov2_weight_decay_rate``)."""
    rest = name.split(_BACKBONE, 1)[-1]
    return not any(part in rest for part in ("layer_scale", "embeddings", "bias", "norm"))


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


def _brightness_contrast(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """The image a little brighter or darker and with more or less contrast (``RF_DETR_AUGMENT_BRIGHTNESS`` /
    ``_CONTRAST``), as albumentations' RandomBrightnessContrast does: ``image * (1 + c) + b * 255``. The hue is left
    alone: it tells the biome."""
    alpha = 1.0 + rng.uniform(-K.RF_DETR_AUGMENT_CONTRAST, K.RF_DETR_AUGMENT_CONTRAST)
    beta = 255.0 * rng.uniform(-K.RF_DETR_AUGMENT_BRIGHTNESS, K.RF_DETR_AUGMENT_BRIGHTNESS)
    # clipped, not cv2.convertScaleAbs: that takes the absolute value, so a darkened black pixel would turn grey
    return np.clip(np.rint(image.astype(np.float32) * alpha + beta), 0, 255).astype(np.uint8)


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
    ``RF_DETR_AUGMENT_RENDER_PROBABILITY`` it is blurred as a lower render scale draws it, with
    ``RF_DETR_AUGMENT_PHOTO_PROBABILITY`` its brightness and contrast change; it is never mirrored (the atlas is
    not). Boxes are clipped to it
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
    if rng.random() < K.RF_DETR_AUGMENT_PHOTO_PROBABILITY:
        out = _brightness_contrast(out, rng)
    return np.ascontiguousarray(out), keep, kept


def prepare(image: np.ndarray, boxes: Sequence[Sequence[float]] = (), *, rgb: bool) -> tuple[np.ndarray, list]:
    """Everything before tiling: normalise to 1080p, paint the HUD, pad to at least one tile."""
    image, boxes = normalise(image, boxes)
    return pad_to_tile(fill_hud(image, rgb=rgb), rgb=rgb), boxes


def nms(detections: list[dict[str, Any]], iou: float, key: str = "family") -> list[dict[str, Any]]:
    """Keep the best-scored of detections of one ``key`` (a family) overlapping by ``iou`` or more.

    Vectorised per family (a weak model can report thousands of boxes on a screenshot while it trains).

    Args:
        detections: dicts with "box" ``[x0, y0, x1, y1]``, "score" and ``key``.
        iou: the overlap from which two detections are one object.
        key: detections compete only with those of the same value of this field.

    Returns:
        The kept detections, best score first.
    """
    groups: dict[Any, list[dict[str, Any]]] = {}
    for det in detections:
        groups.setdefault(det[key], []).append(det)
    kept: list[dict[str, Any]] = []
    for group in groups.values():
        group.sort(key=lambda d: -d["score"])
        boxes = np.asarray([d["box"] for d in group], float).reshape(-1, 4)
        areas = np.clip(boxes[:, 2] - boxes[:, 0], 0, None) * np.clip(boxes[:, 3] - boxes[:, 1], 0, None)
        alive = np.ones(len(group), bool)
        for i in range(len(group)):
            if not alive[i]:
                continue
            kept.append(group[i])
            rest = np.nonzero(alive[i + 1 :])[0] + i + 1
            if not len(rest):
                break
            w = np.minimum(boxes[i, 2], boxes[rest, 2]) - np.maximum(boxes[i, 0], boxes[rest, 0])
            h = np.minimum(boxes[i, 3], boxes[rest, 3]) - np.maximum(boxes[i, 1], boxes[rest, 1])
            inter = np.clip(w, 0, None) * np.clip(h, 0, None)
            overlap = inter / np.maximum(1e-9, areas[i] + areas[rest] - inter)
            alive[rest[overlap >= iou]] = False
    kept.sort(key=lambda d: -d["score"])
    return kept


__all__ = [
    "backbone_weight_decay",
    "crop_boxes",
    "cut_by_inner_edge",
    "epoch_indices",
    "epoch_length",
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
