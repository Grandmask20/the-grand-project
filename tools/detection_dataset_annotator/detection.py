"""The classical detector's results as editable boxes in source-image pixels.

The detector works on the 1080p copy ``core.read_screenshot`` makes (1440p / 4K screenshots are scaled down) and
reports points and polylines; here they become ``xywh`` boxes scaled back to the original screenshot, so the
exported boxes fit the file the training reads.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from grand_project import core
from grand_project.detect.labels import is_node
from grand_project.detect.proposals import dataset_boxes

from . import constants as K
from .state import DetectionOptions

DEFAULT_OPTIONS = DetectionOptions()
"""Generic ``icon`` labels (the deadly-boss icon too)."""


def _read(path: Path, *, digest: bool) -> tuple[np.ndarray, str | None] | None:
    """The original-size BGR image and, when asked, the SHA-256 of the very bytes it was decoded from (one read), or
    None when it cannot be read (``np.fromfile`` handles non-ASCII paths).

    Upright, its EXIF orientation applied (OpenCV's default): training's decoder (``datasets.Image``) applies it too,
    and so does the browser, so the editor, its boxes, the model pre-labels and training share one frame. An empty
    file is None too: OpenCV raises on an empty buffer (as handled in ``core.read_screenshot``).
    """
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    except (OSError, ValueError, cv2.error):
        return None
    if image is None:
        return None
    return image, hashlib.sha256(encoded.data).hexdigest() if digest else None


def read_with_digest(path: Path) -> tuple[np.ndarray, str] | None:
    """The original-size BGR image and the SHA-256 of the bytes it was decoded from (the picture and its identity are
    the same read of the file), or None when it cannot be read (``_read``)."""
    return _read(path, digest=True)  # type: ignore[return-value]  (digest asked: never None)


def decode_image(path: Path) -> np.ndarray | None:
    """The original-size BGR image, or None when it cannot be read (``_read``; no digest worked out)."""
    read = _read(path, digest=False)
    return None if read is None else read[0]


def _source(proposal: dict[str, Any]) -> str:
    """A box's source: a class guess (an unsure biome or city area: drawn dotted) keeps its own; else the annotator's
    own proposals (hidden map nodes, matched icons) say so, else the detector's."""
    if proposal["source"] in K.ANNOTATOR_GUESS_SOURCES:
        return proposal["source"]
    if proposal["item"].get("proposal"):
        return K.ANNOTATOR_HIDDEN_SOURCE if is_node(proposal["label"]) else K.ANNOTATOR_ICON_SOURCE
    return proposal["source"]


def detection_annotations(
    detection: dict[str, Any],
    detector_image: np.ndarray,
    raw_image: np.ndarray,
    options: DetectionOptions = DEFAULT_OPTIONS,
) -> list[dict[str, Any]]:
    """Convert a classical detector result to editable source-image ``xywh`` annotations (``dataset_boxes``)."""
    height, width = detector_image.shape[:2]
    raw_height, raw_width = raw_image.shape[:2]
    scale_x, scale_y = raw_width / width, raw_height / height
    annotations: list[dict[str, Any]] = []
    for proposal in dataset_boxes(detection, detector_image, named_icons=options.named_icons):
        x, y, box_width, box_height = proposal["box"]
        bbox = [
            round(x * scale_x, 2),
            round(y * scale_y, 2),
            round(box_width * scale_x, 2),
            round(box_height * scale_y, 2),
        ]
        annotation: dict[str, Any] = {
            "label": proposal["label"],
            "bbox": bbox,
            "area": round(bbox[2] * bbox[3], 2),
            "iscrowd": 0,
            "source": _source(proposal),
        }
        item = proposal["item"]
        score = item.get("score", item.get("conf"))
        if score is not None:
            annotation["score"] = round(float(score), 4)
        annotations.append(annotation)
    return annotations


def run_classical_detector(path: Path, options: DetectionOptions = DEFAULT_OPTIONS) -> dict[str, Any]:
    """Read one screenshot, run the classical detector plus the icon proposals, and return a state-ready result.

    Raises:
        ValueError: The screenshot cannot be read.
    """
    # Imported here: they load the detector models, which only the worker processes need.
    from grand_project.detect.landmarks import expedition_rules
    from grand_project.detect.models import _models
    from grand_project.detect.pipeline import detect_classical, ensure_models, find_maps

    from .icon_proposals import hidden_nodes, map_spots, propose_icons

    loaded = read_with_digest(path)
    if loaded is None:
        raise ValueError(f"Could not read image: {path}")
    raw_image, digest = loaded
    detector_image = core.scale_screenshot(raw_image)
    max_width, max_height = K.ANNOTATOR_MAX_SIDE
    if raw_image.shape[1] > max_width or raw_image.shape[0] > max_height:
        raise ValueError(
            f"Not a screenshot: {raw_image.shape[1]}x{raw_image.shape[0]} is larger than a {max_width}x{max_height} "
            "game window (a stitched atlas map?)"
        )
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
    # the Expedition rules again, as the detector applies them, for a proposed Expedition icon (no Hall under it)
    detection["nodes"], detection["icons"], detection["landmarks"] = expedition_rules(
        detection["nodes"], detection["icons"], detection.get("landmarks", [])
    )
    return {
        "detected": True,
        "detector": K.ANNOTATOR_CLASSICAL_SOURCE,
        "width": int(raw_image.shape[1]),
        "height": int(raw_image.shape[0]),
        "detector_width": int(detector_image.shape[1]),
        "detector_height": int(detector_image.shape[0]),
        "annotations": detection_annotations(detection, detector_image, raw_image, options),
        "error": None,
        K.ANNOTATOR_DETECTED_SHA: digest,  # the bytes these boxes frame (state.changed_since_detection)
    }
