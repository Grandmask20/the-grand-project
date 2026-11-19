"""Hugging Face dataset preparation for the RF-DETR detector.

The hand-labelled detector truth is point based.  This module turns it into COCO-style object annotations while
keeping sparse object tasks separate from derived geometry: map nodes, icons and landmarks are learned, while paths,
path dashes and fortress walls stay with the established deterministic detector.  It deliberately does not import
``datasets`` or ``transformers`` at module import time; the classical detector and its offline tests must continue to
work without the optional training stack installed.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from grand_project import cities, core

from . import constants as K
from .constants import (
    RF_DETR_CITY_LABELS,
    RF_DETR_CORE_LABELS,
    RF_DETR_ICON_BOX,
    RF_DETR_LANDMARK_BOX,
    RF_DETR_MAP_BOX,
    RF_DETR_PATH_DASH_BOX,
    RF_DETR_PATH_PAD,
    RF_DETR_SOFT_FLAGS,
    RF_DETR_STRONGHOLD_BOX,
    RF_DETR_TOWER_HEIGHT,
    RF_DETR_TOWER_NODE_REACH,
    RF_DETR_TOWER_WIDTH,
    RF_DETR_WALL_MIN_AREA,
)
from .icon_types import icon_class, slug  # noqa: F401  (slug: re-exported, see __all__)
from .paths import path_dashes, trace_paths


@dataclass(frozen=True)
class Record:
    """One source image and its detector annotations in source-image pixels."""

    image_id: int
    path: Path
    source: str
    source_type: str
    source_group: str
    width: int
    height: int
    annotations: tuple[dict[str, Any], ...]


def truth_sources(data_root: Path) -> list[tuple[Path, Path]]:
    """Return hand-truth JSON files and the screenshot folders beside them."""
    candidates = [
        (data_root / "truth" / "truth.json", data_root / "screenshots" / "random_samples"),
        (data_root / "truth_ocean" / "truth.json", data_root / "screenshots" / "ocean"),
    ]
    return [(truth, shots) for truth, shots in candidates if truth.is_file() and shots.is_dir()]


def _box(
    image_width: int,
    image_height: int,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    anchor: str = "center",
) -> tuple[float, float, float, float] | None:
    """Create a clipped detector-coordinate COCO ``xywh`` box around a point."""
    if anchor == "base":
        left, top = x - width / 2, y - height
    else:
        left, top = x - width / 2, y - height / 2
    right, bottom = left + width, top + height
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(image_width), right), min(float(image_height), bottom)
    width, height = right - left, bottom - top
    if width <= 1 or height <= 1:
        return None
    return left, top, width, height


def _clip_rect(
    image_width: int, image_height: int, left: float, top: float, right: float, bottom: float
) -> tuple[float, float, float, float] | None:
    """Clip an ``xyxy`` rectangle and return COCO ``xywh`` coordinates."""
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(image_width), right), min(float(image_height), bottom)
    if right - left <= 1 or bottom - top <= 1:
        return None
    return left, top, right - left, bottom - top


def _decode(path: Path, flags: int) -> np.ndarray | None:
    """Decode an image file, or None when it is empty or not a picture (OpenCV raises on an empty buffer)."""
    buf = np.fromfile(str(path), np.uint8)
    return cv2.imdecode(buf, flags) if buf.size else None


def _source_image(path: Path) -> tuple[np.ndarray, int, int] | None:
    """Read a source image once and return detector pixels (as core.read_screenshot gives) plus its raw dimensions."""
    raw = _decode(path, cv2.IMREAD_COLOR)
    if raw is None:
        return None
    return core.scale_screenshot(raw), int(raw.shape[1]), int(raw.shape[0])


def _annotation(
    category_name: str,
    box: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
    *,
    provenance: str,
) -> dict[str, Any]:
    """Convert a detector-coordinate box into a source-image annotation."""
    x, y, width, height = box
    scaled = (x * scale_x, y * scale_y, width * scale_x, height * scale_y)
    return {
        "category_name": category_name,
        "bbox": scaled,
        "area": scaled[2] * scaled[3],
        "iscrowd": 0,
        "provenance": provenance,
    }


def _point_annotation(
    category_name: str,
    *,
    image_width: int,
    image_height: int,
    x: float,
    y: float,
    width: float,
    height: float,
    scale_x: float,
    scale_y: float,
    anchor: str = "center",
    provenance: str,
) -> dict[str, Any] | None:
    """Build one point-derived annotation, dropping points outside the image."""
    box = _box(image_width, image_height, x, y, width, height, anchor=anchor)
    return _annotation(category_name, box, scale_x, scale_y, provenance=provenance) if box else None


def _rect_annotation(
    category_name: str,
    *,
    image_width: int,
    image_height: int,
    rect: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
    provenance: str,
) -> dict[str, Any] | None:
    """Build one rectangle-derived annotation in detector coordinates."""
    box = _clip_rect(image_width, image_height, *rect)
    return _annotation(category_name, box, scale_x, scale_y, provenance=provenance) if box else None


def _allowed(item: dict[str, Any], include_soft: bool, *, exclude_offcenter: bool = True) -> bool:
    """Exclude ambiguous labels, while retaining off-centre landmark objects whose visual extent is still valid."""
    if include_soft:
        return True
    flags = set(item.get("flags", ()))
    ignored = RF_DETR_SOFT_FLAGS if exclude_offcenter else {"ui"}
    return not (flags & ignored)


def _icon_category(name: str, granularity: str) -> str:
    """Return the RF-DETR class for a named icon."""
    return "icon" if granularity == "all" else icon_class(name)


def _landmark_category(kind: str) -> str | None:
    """Map the detector's landmark vocabulary to stable RF-DETR classes (a City's typed class: _city_categories)."""
    return {
        "Tower": "tower",
        "Hall": "hall",
        "Deadly boss map": "deadly_boss_map",
        "Breach stronghold": "breach_stronghold",
        "Locked stronghold": "locked_stronghold",
    }.get(kind)


def _city_categories(landmarks: list[dict[str, Any]], image: np.ndarray) -> dict[int, str]:
    """The typed class (``city_vaal`` ...) of every City landmark, by its index in ``landmarks``.

    Cities are always labelled by type (user's rule): a landmark's own ``city_type`` (named in the truth notes) wins;
    the others take the look-alike guess on this screenshot, as the dataset annotator's first pass does.
    """
    return {i: RF_DETR_CITY_LABELS[t] for i, (t, _sure) in cities.landmark_city_types(image, landmarks).items()}


def _path_dash_points(dashes: np.ndarray, edges: list[dict[str, Any]]) -> np.ndarray:
    """Keep only dash candidates lying close to a derived path, avoiding thousands of amber look-alikes."""
    if not len(dashes) or not edges:
        return np.zeros((0, 2), float)
    keep = np.zeros(len(dashes), bool)
    for edge in edges:
        line = np.asarray(edge.get("line", []), float).reshape(-1, 2)
        for start, end in zip(line[:-1], line[1:], strict=False):
            vector = end - start
            length_squared = float(vector @ vector)
            if length_squared <= 1:
                continue
            t = np.clip(((dashes - start) @ vector) / length_squared, 0.0, 1.0)
            nearest = start + t[:, None] * vector
            keep |= np.hypot(*(dashes - nearest).T) <= RF_DETR_PATH_DASH_BOX / 2 + 2
    return dashes[keep]


def _truth_annotations(
    labels: dict[str, Any],
    image: np.ndarray,
    *,
    map_box: float,
    icon_box: float,
    landmark_box: float,
    tower_width: float,
    tower_height: float,
    stronghold_box: float,
    badge_granularity: str,
    include_soft: bool,
    include_paths: bool,
    include_path_dashes: bool,
    provenance: str,
) -> list[dict[str, Any]]:
    """Convert one truth entry into point, icon and derived path annotations."""
    height, width = image.shape[:2]
    annotations: list[dict[str, Any]] = []

    maps = [item for item in labels.get("maps", []) if _allowed(item, include_soft)]
    for item in maps:
        out = _point_annotation(
            "map_node",
            image_width=width,
            image_height=height,
            x=float(item["x"]),
            y=float(item["y"]),
            width=map_box,
            height=map_box,
            scale_x=1.0,
            scale_y=1.0,
            provenance=provenance,
        )
        if out:
            annotations.append(out)

    tower_points = [
        (float(item["x"]), float(item["y"]))
        for item in labels.get("landmarks", [])
        if item.get("kind") == "Tower" and _allowed(item, include_soft)
    ]
    city_categories = _city_categories(labels.get("landmarks", []), image)
    for index, item in enumerate(labels.get("landmarks", [])):
        if not _allowed(item, include_soft, exclude_offcenter=False):
            continue
        category = city_categories.get(index) or _landmark_category(str(item.get("kind", "")))
        if category is None:
            continue
        x, y = float(item["x"]), float(item["y"])
        if category == "tower":
            out = _point_annotation(
                category,
                image_width=width,
                image_height=height,
                x=x,
                y=y,
                width=tower_width,
                height=tower_height,
                scale_x=1.0,
                scale_y=1.0,
                anchor="base",
                provenance=provenance,
            )
        else:
            size = stronghold_box if category in {"breach_stronghold", "locked_stronghold"} else landmark_box
            out = _point_annotation(
                category,
                image_width=width,
                image_height=height,
                x=x,
                y=y,
                width=size,
                height=size,
                scale_x=1.0,
                scale_y=1.0,
                provenance=provenance,
            )
        if out:
            annotations.append(out)

    for item in labels.get("badges", []):
        if not _allowed(item, include_soft):
            continue
        out = _point_annotation(
            _icon_category(str(item.get("name", "Unidentified")), badge_granularity),
            image_width=width,
            image_height=height,
            x=float(item["x"]),
            y=float(item["y"]),
            width=icon_box,
            height=icon_box,
            scale_x=1.0,
            scale_y=1.0,
            provenance=provenance,
        )
        if out:
            annotations.append(out)

    if include_paths:
        nodes = [
            {
                "x": float(item["x"]),
                "y": float(item["y"]),
                "tower": any(np.hypot(float(item["x"]) - tx, float(item["y"]) - ty) <= 20 for tx, ty in tower_points),
            }
            for item in maps
        ]
        dashes = path_dashes(image)
        edges = trace_paths(nodes, dashes, image)
        if include_path_dashes:
            for x, y in _path_dash_points(dashes, edges):
                out = _point_annotation(
                    "path_dash",
                    image_width=width,
                    image_height=height,
                    x=float(x),
                    y=float(y),
                    width=RF_DETR_PATH_DASH_BOX,
                    height=RF_DETR_PATH_DASH_BOX,
                    scale_x=1.0,
                    scale_y=1.0,
                    provenance="derived_path_dashes",
                )
                if out:
                    annotations.append(out)
        for edge in edges:
            line = np.asarray(edge["line"], float).reshape(-1, 2)
            if len(line) < 2:
                continue
            left, top = line.min(0) - RF_DETR_PATH_PAD
            right, bottom = line.max(0) + RF_DETR_PATH_PAD
            out = _rect_annotation(
                "path",
                image_width=width,
                image_height=height,
                rect=(float(left), float(top), float(right), float(bottom)),
                scale_x=1.0,
                scale_y=1.0,
                provenance="derived_paths",
            )
            if out:
                annotations.append(out)
    return annotations


def _wall_annotations(mask_path: Path, image: np.ndarray) -> list[dict[str, Any]]:
    """Turn an optional painted fortress-wall alpha mask into wall boxes."""
    mask = _decode(mask_path, cv2.IMREAD_UNCHANGED)
    if mask is None:
        return []
    if mask.ndim == 3:
        mask = mask[..., 3] if mask.shape[2] == 4 else cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    binary = (mask >= 128).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    height, width = image.shape[:2]
    out = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < RF_DETR_WALL_MIN_AREA:
            continue
        item = _rect_annotation(
            "fortress_wall",
            image_width=width,
            image_height=height,
            rect=(float(x), float(y), float(x + w), float(y + h)),
            scale_x=1.0,
            scale_y=1.0,
            provenance="painted_wall",
        )
        if item:
            out.append(item)
    return out


def _full(records: list[Record], limit: int | None) -> bool:
    """Whether a loader has collected ``limit`` usable records (None: no limit)."""
    return limit is not None and len(records) >= limit


def _load_wall_records(data_root: Path, *, limit: int | None = None) -> list[Record]:
    """Load optional ``fortress_paint`` screenshot/mask pairs as wall-only records (at most ``limit``)."""
    wall_dir = data_root / "fortress_paint"
    records = []
    for mask_path in sorted(wall_dir.glob("[0-9]*.png")):
        if _full(records, limit):
            break
        image_path = wall_dir / f"paint_{mask_path.stem}.png"
        loaded = _source_image(image_path) if image_path.is_file() else None
        if loaded is None:
            continue
        image, raw_width, raw_height = loaded
        annotations = _wall_annotations(mask_path, image)
        if annotations:
            records.append(
                _record(
                    image_path,
                    image,
                    source=f"fortress_paint/{image_path.name}",
                    source_type="painted_wall",
                    source_group="fortress_paint",
                    annotations=annotations,
                    raw_width=raw_width,
                    raw_height=raw_height,
                )
            )
    return records


def _record(
    image_path: Path,
    detector_image: np.ndarray,
    *,
    source: str,
    source_type: str,
    source_group: str,
    annotations: list[dict[str, Any]],
    raw_width: int,
    raw_height: int,
) -> Record:
    """Create a record, scaling detector-space annotations into source-image pixels."""
    detector_height, detector_width = detector_image.shape[:2]
    sx, sy = raw_width / detector_width, raw_height / detector_height
    scaled = []
    for item in annotations:
        x, y, width, height = item["bbox"]
        box = (x * sx, y * sy, width * sx, height * sy)
        scaled.append(dict(item, bbox=box, area=box[2] * box[3]))
    return Record(
        image_id=-1,
        path=image_path,
        source=source,
        source_type=source_type,
        source_group=source_group,
        width=raw_width,
        height=raw_height,
        annotations=tuple(scaled),
    )


def _load_truth_records(
    data_root: Path,
    *,
    map_box: float,
    icon_box: float,
    landmark_box: float,
    tower_width: float,
    tower_height: float,
    stronghold_box: float,
    include_soft: bool,
    badge_granularity: str,
    include_paths: bool,
    include_path_dashes: bool,
    limit: int | None = None,
) -> list[Record]:
    """Load hand-labelled screenshot records (at most ``limit``, in source order)."""
    records = []
    for truth_path, image_dir in truth_sources(data_root):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        source_group = truth_path.parent.name
        for filename, labels in truth.items():
            if _full(records, limit):
                return records
            image_path = image_dir / filename
            loaded = _source_image(image_path) if image_path.is_file() else None
            if loaded is None:
                continue
            image, raw_width, raw_height = loaded
            annotations = _truth_annotations(
                labels,
                image,
                map_box=map_box,
                icon_box=icon_box,
                landmark_box=landmark_box,
                tower_width=tower_width,
                tower_height=tower_height,
                stronghold_box=stronghold_box,
                badge_granularity=badge_granularity,
                include_soft=include_soft,
                include_paths=include_paths,
                include_path_dashes=include_path_dashes,
                provenance="hand_truth",
            )
            records.append(
                _record(
                    image_path,
                    image,
                    source=f"{source_group}/{filename}",
                    source_type="hand_truth",
                    source_group=source_group,
                    annotations=annotations,
                    raw_width=raw_width,
                    raw_height=raw_height,
                )
            )
    return records


def _cache_image_path(cache_path: Path, cached_path: str, data_root: Path, name: str) -> Path:
    """Resolve a cached frame path from old atlas-relative and current data-root layouts."""
    candidates = [cache_path.parent / cached_path, data_root / "screenshots" / "crawl" / f"{name}.png"]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[-1])


def _load_cached_records(
    data_root: Path,
    *,
    map_box: float = RF_DETR_MAP_BOX,
    icon_box: float = RF_DETR_ICON_BOX,
    landmark_box: float = RF_DETR_LANDMARK_BOX,
    tower_width: float = RF_DETR_TOWER_WIDTH,
    tower_height: float = RF_DETR_TOWER_HEIGHT,
    stronghold_box: float = RF_DETR_STRONGHOLD_BOX,
    badge_granularity: str,
    include_paths: bool,
    include_path_dashes: bool,
    limit: int | None = None,
) -> list[Record]:
    """Load cached crawl detections as explicitly marked pseudo-labelled records (at most ``limit``).

    Boxes have the sizes given (the same as the hand truth's in ``load_records``).
    """
    frame_dir = data_root / "crawl_atlas" / "atlas_frames"
    records = []
    for cache_path in sorted(frame_dir.glob("*_detect1.json")):
        if _full(records, limit):
            break
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        name = str(cached.get("name", cache_path.stem.removesuffix("_detect1")))
        image_path = _cache_image_path(cache_path, str(cached.get("path", "")), data_root, name)
        loaded = _source_image(image_path) if image_path.is_file() else None
        if loaded is None:
            continue
        image, raw_width, raw_height = loaded
        height, width = image.shape[:2]
        annotations = []
        for node in cached.get("nodes", []):
            item = _point_annotation(
                "map_node",
                image_width=width,
                image_height=height,
                x=float(node["x"]),
                y=float(node["y"]),
                width=map_box,
                height=map_box,
                scale_x=1.0,
                scale_y=1.0,
                provenance="cached_detector",
            )
            if item:
                annotations.append(item)
            if node.get("tower"):
                item = _point_annotation(
                    "tower",
                    image_width=width,
                    image_height=height,
                    x=float(node["x"]),
                    y=float(node["y"]),
                    width=tower_width,
                    height=tower_height,
                    scale_x=1.0,
                    scale_y=1.0,
                    anchor="base",
                    provenance="cached_detector",
                )
                if item:
                    annotations.append(item)
        # Every Tower landmark is one tower box. Classical rows report a tower twice, as a map node flagged "tower"
        # (boxed above) and as a landmark at that node; RF-DETR rows may have only the landmark (older ones dropped
        # the tower's map node). So a landmark adds a box unless a flagged node lies within RF_DETR_TOWER_NODE_REACH.
        flagged = [(float(node["x"]), float(node["y"])) for node in cached.get("nodes", []) if node.get("tower")]
        city_categories = _city_categories(cached.get("landmarks", []), image)
        for index, landmark in enumerate(cached.get("landmarks", [])):
            category = city_categories.get(index) or _landmark_category(str(landmark.get("kind", "")))
            if category is None:
                continue
            x, y = float(landmark["x"]), float(landmark["y"])
            if category == "tower":
                if any(np.hypot(x - fx, y - fy) <= RF_DETR_TOWER_NODE_REACH for fx, fy in flagged):
                    continue
                box_width, box_height, anchor = tower_width, tower_height, "base"
            else:
                size = stronghold_box if category in {"breach_stronghold", "locked_stronghold"} else landmark_box
                box_width, box_height, anchor = size, size, "center"
            item = _point_annotation(
                category,
                image_width=width,
                image_height=height,
                x=x,
                y=y,
                width=box_width,
                height=box_height,
                scale_x=1.0,
                scale_y=1.0,
                anchor=anchor,
                provenance="cached_detector",
            )
            if item:
                annotations.append(item)
        for icon in cached.get("icons", []):
            item = _point_annotation(
                _icon_category(str(icon.get("name", "Unidentified")), badge_granularity),
                image_width=width,
                image_height=height,
                x=float(icon["x"]),
                y=float(icon["y"]),
                width=icon_box,
                height=icon_box,
                scale_x=1.0,
                scale_y=1.0,
                provenance="cached_detector",
            )
            if item:
                annotations.append(item)
        if include_paths:
            edges = []
            for edge in cached.get("edges", []):
                line = np.asarray(edge.get("line", []), float).reshape(-1, 2)
                if len(line) < 2:
                    continue
                edges.append(edge)
                left, top = line.min(0) - RF_DETR_PATH_PAD
                right, bottom = line.max(0) + RF_DETR_PATH_PAD
                item = _rect_annotation(
                    "path",
                    image_width=width,
                    image_height=height,
                    rect=(float(left), float(top), float(right), float(bottom)),
                    scale_x=1.0,
                    scale_y=1.0,
                    provenance="cached_detector",
                )
                if item:
                    annotations.append(item)
            if include_path_dashes:
                for x, y in _path_dash_points(path_dashes(image), edges):
                    item = _point_annotation(
                        "path_dash",
                        image_width=width,
                        image_height=height,
                        x=float(x),
                        y=float(y),
                        width=RF_DETR_PATH_DASH_BOX,
                        height=RF_DETR_PATH_DASH_BOX,
                        scale_x=1.0,
                        scale_y=1.0,
                        provenance="derived_path_dashes",
                    )
                    if item:
                        annotations.append(item)
        records.append(
            _record(
                image_path,
                image,
                source=f"crawl/{name}",
                source_type="cached_detector",
                source_group="crawl",
                annotations=annotations,
                raw_width=raw_width,
                raw_height=raw_height,
            )
        )
    return records


def load_records(
    data_root: Path,
    *,
    map_box: float = RF_DETR_MAP_BOX,
    icon_box: float = RF_DETR_ICON_BOX,
    badge_box: float | None = None,
    landmark_box: float = RF_DETR_LANDMARK_BOX,
    tower_width: float = RF_DETR_TOWER_WIDTH,
    tower_height: float = RF_DETR_TOWER_HEIGHT,
    stronghold_box: float = RF_DETR_STRONGHOLD_BOX,
    include_soft: bool = False,
    badge_granularity: str = "all",
    include_paths: bool = False,
    include_path_dashes: bool = False,
    include_cached: bool = False,
    include_walls: bool = False,
    max_images: int | None = None,
) -> tuple[list[Record], dict[str, str]]:
    """Load truth and optional cached data, returning records and a stable ID-to-label map.

    ``badge_box`` is retained as a compatibility alias for the earlier training script.  Coordinates are always
    normalised to the source image's actual pixel dimensions before records are returned.
    """
    if badge_box is not None:
        icon_box = badge_box
    if badge_granularity not in {"name", "all"}:
        raise ValueError("badge_granularity must be 'name' or 'all'")
    if max_images is not None and max_images < 1:
        raise ValueError("max_images must be positive")

    def left() -> int | None:
        """How many more usable records the loaders may add (None: no limit); a skipped file never counts."""
        return None if max_images is None else max_images - len(records)

    records: list[Record] = []
    records.extend(
        _load_truth_records(
            data_root,
            map_box=map_box,
            icon_box=icon_box,
            landmark_box=landmark_box,
            tower_width=tower_width,
            tower_height=tower_height,
            stronghold_box=stronghold_box,
            include_soft=include_soft,
            badge_granularity=badge_granularity,
            include_paths=include_paths,
            include_path_dashes=include_path_dashes,
            limit=left(),
        )
    )
    if include_cached and left() != 0:
        records.extend(
            _load_cached_records(
                data_root,
                map_box=map_box,
                icon_box=icon_box,
                landmark_box=landmark_box,
                tower_width=tower_width,
                tower_height=tower_height,
                stronghold_box=stronghold_box,
                badge_granularity=badge_granularity,
                include_paths=include_paths,
                include_path_dashes=include_path_dashes,
                limit=left(),
            )
        )
    if include_walls and left() != 0:
        records.extend(_load_wall_records(data_root, limit=left()))
    if not records:
        raise FileNotFoundError(
            f"No usable detector screenshots found below {data_root}; download atlas_test_data or set ATLAS_TEST_DATA."
        )

    names = list(RF_DETR_CORE_LABELS)
    names.extend(sorted({a["category_name"] for r in records for a in r.annotations} - set(names)))
    label_map = {str(index): name for index, name in enumerate(names)}
    name_to_id = {name: index for index, name in enumerate(names)}
    records = [
        replace(
            record,
            image_id=index,
            annotations=tuple(
                dict(annotation, category_id=name_to_id[annotation["category_name"]])
                for annotation in record.annotations
            ),
        )
        for index, record in enumerate(records)
    ]
    return records, label_map


def load_annotator_manifest(manifest_path: Path, max_images: int | None = None) -> tuple[list[Record], dict[str, str]]:
    """Load reviewed annotations exported by ``tools.detection_dataset_annotator``.

    The manifest keeps source image paths and editable ``xywh`` boxes, so it can be converted to the same Record
    objects as the hand-labelled truth without importing Streamlit or copying the screenshots.
    """
    manifest_path = Path(manifest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("format") != "the-grand-project-rf-detr-manifest":
        raise ValueError(f"Not an annotator RF-DETR manifest: {manifest_path}")
    labels = {str(index): str(name) for index, name in data.get("labels", {}).items()}
    if not labels:
        raise ValueError(f"Annotator manifest has no labels: {manifest_path}")
    label_names = [labels[str(index)] for index in range(len(labels))]
    name_to_id = {name: index for index, name in enumerate(label_names)}
    records: list[Record] = []
    for item in data.get("images", []):
        image_path = Path(str(item.get("path", "")))
        if not image_path.is_absolute():
            image_path = manifest_path.parent / image_path
        if not image_path.is_file():
            continue
        annotations = []
        for annotation in item.get("annotations", []):
            label = str(annotation.get("label", ""))
            if label not in name_to_id:
                raise ValueError(f"Annotator annotation uses unknown label {label!r}: {manifest_path}")
            try:
                bbox = tuple(float(value) for value in annotation["bbox"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid annotator bbox in {manifest_path}") from exc
            if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox) or bbox[2] <= 0 or bbox[3] <= 0:
                raise ValueError(f"Invalid annotator bbox in {manifest_path}: {bbox}")
            try:
                area = float(annotation.get("area", bbox[2] * bbox[3]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid annotator area in {manifest_path}") from exc
            if not math.isfinite(area):
                raise ValueError(f"Invalid annotator area in {manifest_path}: {area}")
            annotations.append(
                {
                    "category_name": label,
                    "category_id": name_to_id[label],
                    "bbox": bbox,
                    "area": area,
                    "iscrowd": int(annotation.get("iscrowd", 0)),
                    "provenance": str(annotation.get("source", "annotator_reviewed")),
                }
            )
        records.append(
            Record(
                image_id=int(item.get("image_id", len(records))),
                path=image_path,
                source=str(item.get("source", image_path.name)),
                source_type=str(item.get("source_type", "annotator_reviewed")),
                source_group=str(item.get("source_group", "annotator")),
                width=int(item["width"]),
                height=int(item["height"]),
                annotations=tuple(annotations),
            )
        )
    if max_images is not None:
        if max_images < 1:
            raise ValueError("max_images must be positive")
        records = records[:max_images]
    if not records:
        raise FileNotFoundError(f"No usable images in annotator manifest: {manifest_path}")
    return records, {str(index): name for index, name in enumerate(label_names)}


def split_records(
    records: list[Record], val_fraction: float, seed: int, *, by_source: bool = False
) -> tuple[list[Record], list[Record]]:
    """Split at screenshot level, optionally keeping each truth source in one split."""
    if len(records) < 2:
        raise ValueError("Need at least two labelled screenshots for a train/validation split")
    if not 0 < val_fraction < 1:
        raise ValueError("val_fraction must be between 0 and 1")
    rng = np.random.default_rng(seed)
    if by_source:
        groups: dict[str, list[Record]] = {}
        for record in records:
            groups.setdefault(record.source_group, []).append(record)
        if len(groups) < 2:
            raise ValueError("Need at least two source groups to split by source")
        keys = list(groups)
        rng.shuffle(keys)
        target = max(1, int(np.ceil(len(records) * val_fraction)))
        validation: list[Record] = []
        # whole groups only, and the last group always stays for training
        while len(keys) > 1 and (len(validation) < target or not validation):
            validation.extend(groups.pop(keys.pop()))
        train = [record for group in groups.values() for record in group]
        return train, validation
    order = np.arange(len(records))
    rng.shuffle(order)
    val_count = min(len(records) - 1, max(1, int(np.ceil(len(records) * val_fraction))))
    validation_ids = set(order[:val_count])
    return (
        [record for index, record in enumerate(records) if index not in validation_ids],
        [record for index, record in enumerate(records) if index in validation_ids],
    )


def _features(label_names: list[str]):
    """Construct explicit Hugging Face features lazily."""
    from datasets import ClassLabel, Features, Image, Sequence, Value

    return Features(
        {
            "image": Image(),
            "image_id": Value("int64"),
            "source": Value("string"),
            "source_type": Value("string"),
            "source_group": Value("string"),
            "width": Value("int32"),
            "height": Value("int32"),
            "objects": {
                "id": Sequence(Value("int64")),
                "area": Sequence(Value("float32")),
                "bbox": Sequence(Sequence(Value("float32"), length=4)),
                "category": Sequence(ClassLabel(names=label_names)),
                "iscrowd": Sequence(Value("int8")),
            },
            "annotation_sources": Sequence(Value("string")),
        }
    )


def _rows(records: list[Record]) -> list[dict[str, Any]]:
    """Convert records to the Hugging Face object-detection schema."""
    rows = []
    for record in records:
        rows.append(
            {
                "image": str(record.path),
                "image_id": record.image_id,
                "source": record.source,
                "source_type": record.source_type,
                "source_group": record.source_group,
                "width": record.width,
                "height": record.height,
                "objects": {
                    "id": list(range(len(record.annotations))),
                    "area": [float(annotation["area"]) for annotation in record.annotations],
                    "bbox": [list(map(float, annotation["bbox"])) for annotation in record.annotations],
                    "category": [int(annotation["category_id"]) for annotation in record.annotations],
                    "iscrowd": [int(annotation["iscrowd"]) for annotation in record.annotations],
                },
                "annotation_sources": [str(a["provenance"]) for a in record.annotations],
            }
        )
    return rows


def build_dataset(
    records: list[Record],
    *,
    val_fraction: float,
    seed: int,
    output_dir: Path | None = None,
    by_source: bool = False,
    label_map: dict[str, str],
) -> Any:
    """Create a ``DatasetDict`` and optionally save it with its label metadata."""
    from datasets import Dataset, DatasetDict

    train, validation = split_records(records, val_fraction, seed, by_source=by_source)
    features = _features([label_map[str(index)] for index in range(len(label_map))])
    dataset = DatasetDict(
        {
            "train": Dataset.from_list(_rows(train), features=features),
            "validation": Dataset.from_list(_rows(validation), features=features),
        }
    )
    if output_dir is not None:
        output_dir = Path(output_dir)
        if output_dir.exists() and any(output_dir.iterdir()):
            raise FileExistsError(f"dataset output directory is not empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        dataset.save_to_disk(str(output_dir))
        (output_dir / "labels.json").write_text(json.dumps(label_map, indent=2) + "\n", encoding="utf-8")
        (output_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "format": "huggingface-datasets-object-detection",
                    "train_images": len(train),
                    "validation_images": len(validation),
                    "labels": label_map,
                    "seed": seed,
                    "validation_fraction": val_fraction,
                    "split_by_source": by_source,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return dataset


def _copy_objects(objects: dict[str, Any]) -> dict[str, Any]:
    """Copy the object columns so an on-the-fly augmentation never mutates a Dataset row."""
    return {key: list(value) for key, value in objects.items()}


def _replace_boxes(objects: dict[str, Any], keep: list[int], boxes: list[list[float]]) -> dict[str, Any]:
    """Select and update object columns after a geometric image transform."""
    count = len(objects.get("bbox", ()))
    result: dict[str, list[Any]] = {}
    for key, values in objects.items():
        if isinstance(values, (list, tuple)) and len(values) == count:
            result[key] = [values[index] for index in keep]
        else:
            result[key] = list(values) if isinstance(values, (list, tuple)) else values
    result["bbox"] = boxes
    result["area"] = [float(box[2] * box[3]) for box in boxes]
    return result


def _flip_objects(objects: dict[str, Any], image_width: int) -> dict[str, Any]:
    """Mirror detector boxes around the image's vertical centre line."""
    original = objects.get("bbox", ())
    boxes = [[float(box[0]), float(box[1]), float(box[2]), float(box[3])] for box in original]
    for box in boxes:
        box[0] = float(image_width) - box[0] - box[2]
    return _replace_boxes(objects, list(range(len(boxes))), boxes)


def _crop_objects(
    objects: dict[str, Any], crop_left: int, crop_top: int, crop_right: int, crop_bottom: int
) -> dict[str, Any] | None:
    """Clip boxes to a crop and discard objects whose visible area becomes too small."""
    keep: list[int] = []
    boxes: list[list[float]] = []
    for index, original in enumerate(objects.get("bbox", ())):
        left, top, width, height = map(float, original)
        right, bottom = left + width, top + height
        clipped_left = max(left, crop_left)
        clipped_top = max(top, crop_top)
        clipped_right = min(right, crop_right)
        clipped_bottom = min(bottom, crop_bottom)
        clipped_width = clipped_right - clipped_left
        clipped_height = clipped_bottom - clipped_top
        original_area = width * height
        visible = clipped_width * clipped_height
        if (
            clipped_width <= 1
            or clipped_height <= 1
            or visible / max(1.0, original_area) < K.RF_DETR_AUGMENT_CROP_MIN_VISIBILITY
        ):
            continue
        keep.append(index)
        boxes.append(
            [
                clipped_left - crop_left,
                clipped_top - crop_top,
                clipped_width,
                clipped_height,
            ]
        )
    if objects.get("bbox") and not boxes:
        return None
    return _replace_boxes(objects, keep, boxes)


def augment_detection_example(image, objects: dict[str, Any], rng: random.Random):
    """Apply the RF-DETR paper's conservative train-time augmentations to one labelled image.

    The atlas has a stable upright orientation, so vertical flips, rotations and colour transforms are deliberately
    omitted. Crops update the absolute ``xywh`` boxes and keep only objects with enough visible area.
    """
    from PIL import Image

    image = image.convert("RGB")
    transformed = _copy_objects(objects)
    if rng.random() < K.RF_DETR_AUGMENT_FLIP_PROBABILITY:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        transformed = _flip_objects(transformed, image.width)

    if not transformed.get("bbox") or rng.random() >= K.RF_DETR_AUGMENT_CROP_PROBABILITY:
        return image, transformed

    width, height = image.size
    for _ in range(K.RF_DETR_AUGMENT_CROP_ATTEMPTS):
        min_crop_width = max(1, min(width, int(width * K.RF_DETR_AUGMENT_CROP_MIN_SCALE)))
        min_crop_height = max(1, min(height, int(height * K.RF_DETR_AUGMENT_CROP_MIN_SCALE)))
        crop_width = rng.randint(min_crop_width, width)
        crop_height = rng.randint(min_crop_height, height)
        crop_left = rng.randint(0, width - crop_width)
        crop_top = rng.randint(0, height - crop_height)
        cropped = _crop_objects(transformed, crop_left, crop_top, crop_left + crop_width, crop_top + crop_height)
        if cropped is not None:
            return image.crop((crop_left, crop_top, crop_left + crop_width, crop_top + crop_height)), cropped
    return image, transformed


class ProcessorTransform:
    """The batched dataset transform of ``processor_transform``: a module-level class, not a closure, so a dataset
    that carries it can be pickled into DataLoader worker processes (spawn, on Windows and macOS)."""

    def __init__(self, processor, *, augment: bool = False, seed: int = 1337) -> None:
        self.processor = processor
        self.augment = augment
        self.rng = random.Random(seed)

    def __call__(self, examples: dict[str, list[Any]]) -> dict[str, Any]:
        images = []
        annotations = []
        for image, image_id, objects in zip(examples["image"], examples["image_id"], examples["objects"], strict=True):
            image = image.convert("RGB")
            if self.augment:
                image, objects = augment_detection_example(image, objects, self.rng)
            images.append(image)
            annotations.append(
                {
                    "image_id": image_id,
                    "annotations": [
                        {
                            "image_id": image_id,
                            "category_id": category,
                            "bbox": bbox,
                            "area": area,
                            "iscrowd": iscrowd,
                        }
                        for category, bbox, area, iscrowd in zip(
                            objects["category"], objects["bbox"], objects["area"], objects["iscrowd"], strict=True
                        )
                    ],
                }
            )
        return self.processor(images=images, annotations=annotations, return_tensors="pt")


def processor_transform(processor, *, augment: bool = False, seed: int = 1337) -> ProcessorTransform:
    """Return a batched transform, optionally applying seeded train-only geometric augmentation."""
    return ProcessorTransform(processor, augment=augment, seed=seed)


__all__ = [
    "ProcessorTransform",
    "Record",
    "augment_detection_example",
    "build_dataset",
    "load_records",
    "processor_transform",
    "slug",
    "split_records",
    "truth_sources",
]
