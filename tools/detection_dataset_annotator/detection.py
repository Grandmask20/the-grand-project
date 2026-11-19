"""The classical detector's results as editable boxes in source-image pixels.

The detector works on the 1080p copy ``core.read_screenshot`` makes (1440p / 4K screenshots are scaled down) and
reports points and polylines; here they become ``xywh`` boxes scaled back to the original screenshot, so the
exported boxes fit the file the training reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from grand_project import cities, core
from grand_project.detect import constants as detect_constants
from grand_project.detect.icon_types import icon_class

from . import constants as K
from .state import DetectionOptions

Box = tuple[float, float, float, float]
"""x, y, width, height."""

DEFAULT_OPTIONS = DetectionOptions()
"""Core labels only, icons as one ``icon`` class."""


def decode_image(path: Path) -> np.ndarray | None:
    """The original-size BGR image, or None when it cannot be read (``np.fromfile`` handles non-ASCII paths)."""
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def _read_images(path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """The original screenshot and the detector's 1080p copy of it (decoded once)."""
    raw = decode_image(path)
    if raw is None:
        return None
    return raw, core.scale_screenshot(raw)


def _clip(left: float, top: float, right: float, bottom: float, width: int, height: int) -> Box | None:
    """A box clipped to the image, or None when less than a pixel of it is left."""
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(width), right), min(float(height), bottom)
    if right - left <= 1 or bottom - top <= 1:
        return None
    return left, top, right - left, bottom - top


def _box_at_point(
    x: float, y: float, box_width: float, box_height: float, width: int, height: int, *, anchor: str = "center"
) -> Box | None:
    """A clipped detector-space box around a point; with ``anchor="base"`` the box stands on the point."""
    left = x - box_width / 2
    top = y - box_height if anchor == "base" else y - box_height / 2
    return _clip(left, top, left + box_width, top + box_height, width, height)


def _box_around_line(line: Any, pad: float, width: int, height: int) -> Box | None:
    """A clipped detector-space box around a traced path polyline."""
    points = np.asarray(line, dtype=float).reshape(-1, 2)
    if len(points) < 2:
        return None
    left, top = points.min(axis=0) - pad
    right, bottom = points.max(axis=0) + pad
    return _clip(float(left), float(top), float(right), float(bottom), width, height)


def _icon_label(icon: dict[str, Any], named_icons: bool) -> str:
    """The generic ``icon`` label, or a stable ``icon_<name>`` one."""
    if not named_icons:
        return "icon"
    return icon_class(str(icon.get("name") or "Unidentified"))


def _wall_boxes(mask: np.ndarray) -> list[Box]:
    """The classical fortress-wall mask as one box per large enough connected region."""
    _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    return [
        (float(x), float(y), float(width), float(height))
        for x, y, width, height, area in stats[1:]
        if area >= detect_constants.RF_DETR_WALL_MIN_AREA
    ]


def detection_annotations(
    detection: dict[str, Any],
    detector_image: np.ndarray,
    raw_image: np.ndarray,
    options: DetectionOptions = DEFAULT_OPTIONS,
    *,
    wall_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Convert a classical detector result to editable source-image ``xywh`` annotations."""
    height, width = detector_image.shape[:2]
    raw_height, raw_width = raw_image.shape[:2]
    scale_x, scale_y = raw_width / width, raw_height / height
    annotations: list[dict[str, Any]] = []

    def add(label: str, box: Box | None, item: dict[str, Any], source: str = K.ANNOTATOR_CLASSICAL_SOURCE) -> None:
        if box is None:
            return
        x, y, box_width, box_height = box
        bbox = [
            round(x * scale_x, 2),
            round(y * scale_y, 2),
            round(box_width * scale_x, 2),
            round(box_height * scale_y, 2),
        ]
        annotation: dict[str, Any] = {
            "label": label,
            "bbox": bbox,
            "area": round(bbox[2] * bbox[3], 2),
            "iscrowd": 0,
            "source": source,
        }
        score = item.get("score", item.get("conf"))
        if score is not None:
            annotation["score"] = round(float(score), 4)
        annotations.append(annotation)

    map_box = detect_constants.RF_DETR_MAP_BOX
    for node in detection.get("nodes", []):
        box = _box_at_point(float(node["x"]), float(node["y"]), map_box, map_box, width, height)
        add("map_node", box, node, K.ANNOTATOR_HIDDEN_SOURCE if node.get("proposal") else K.ANNOTATOR_CLASSICAL_SOURCE)
    landmarks = detection.get("landmarks", [])
    # Cities are always labelled by type (user's rule); an unsure look-alike guess is flagged for the reviewer.
    city_types = cities.landmark_city_types(detector_image, landmarks)
    for index, landmark in enumerate(landmarks):
        spec = K.ANNOTATOR_LANDMARK_LABELS.get(str(landmark.get("kind", "")))
        if spec is None:
            continue
        label, box_width, box_height, anchor = spec
        source = K.ANNOTATOR_CLASSICAL_SOURCE
        if index in city_types:
            city_type, sure = city_types[index]
            label = detect_constants.RF_DETR_CITY_LABELS[city_type]
            source = K.ANNOTATOR_CLASSICAL_SOURCE if sure else K.ANNOTATOR_CITY_GUESS_SOURCE
        box = _box_at_point(
            float(landmark["x"]), float(landmark["y"]), box_width, box_height, width, height, anchor=anchor
        )
        add(label, box, landmark, source)
    icon_box = detect_constants.RF_DETR_ICON_BOX
    for icon in detection.get("icons", []):
        box = _box_at_point(float(icon["x"]), float(icon["y"]), icon_box, icon_box, width, height)
        add(
            _icon_label(icon, options.named_icons),
            box,
            icon,
            K.ANNOTATOR_ICON_SOURCE if icon.get("proposal") else K.ANNOTATOR_CLASSICAL_SOURCE,
        )
    if options.include_paths:
        for edge in detection.get("edges", []):
            add("path", _box_around_line(edge.get("line", []), detect_constants.RF_DETR_PATH_PAD, width, height), edge)
    if options.include_fortress_walls and wall_mask is not None:
        for box in _wall_boxes(wall_mask):
            add("fortress_wall", box, {})
    return annotations


def run_classical_detector(path: Path, options: DetectionOptions = DEFAULT_OPTIONS) -> dict[str, Any]:
    """Read one screenshot, run the classical detector plus the icon proposals, and return a state-ready result.

    Raises:
        ValueError: The screenshot cannot be read.
    """
    # Imported here: they load the detector models, which only the worker processes need.
    from grand_project.detect.models import _models
    from grand_project.detect.pipeline import detect_classical, ensure_models, find_maps

    from .icon_proposals import hidden_nodes, map_spots, propose_icons

    loaded = _read_images(path)
    if loaded is None:
        raise ValueError(f"Could not read image: {path}")
    raw_image, detector_image = loaded
    # The map finder runs once here and is handed to the detector: its candidates also give the faint map nodes.
    ensure_models()
    found_maps = find_maps(detector_image, _models["maps"])
    detection = detect_classical(detector_image, found_maps=found_maps)
    # The classical finder misses most of the larger silver-rimmed icons (res atlases) and the fogged map nodes
    # under icons: add the rim candidates whose picture matches a stored icon, then a map node under every icon row
    # without one.
    _maps, candidates, probabilities = found_maps
    spots = map_spots(candidates, probabilities)
    detection["icons"] = detection["icons"] + propose_icons(detector_image, detection, _models["badges"], spots)
    detection["nodes"] = detection["nodes"] + hidden_nodes(detector_image, detection, detection["icons"], spots)
    wall_mask = None
    if options.include_fortress_walls:
        from grand_project.detect.walls import fortress_walls

        wall_mask = fortress_walls(detector_image)
    return {
        "detected": True,
        "detector": K.ANNOTATOR_CLASSICAL_SOURCE,
        "width": int(raw_image.shape[1]),
        "height": int(raw_image.shape[0]),
        "detector_width": int(detector_image.shape[1]),
        "detector_height": int(detector_image.shape[0]),
        "annotations": detection_annotations(detection, detector_image, raw_image, options, wall_mask=wall_mask),
        "error": None,
    }
