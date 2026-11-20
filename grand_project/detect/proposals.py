"""The classical detector's result as the RF-DETR dataset's labelled boxes: the first guesses a reviewer corrects.

This is the one conversion from a classical result to dataset boxes (the dataset annotator uses it), so the label
rules (``RF_DETR_LABEL_INFO``) are applied in one place:

- every map node: one node box; its class says the city area it lies in, else the biome of the ground around it,
  else plain ``map_node`` (biomes.py). Guesses are marked by their source (``RF_DETR_GUESS_SOURCES``).
- every City: its citadel class (``citadel_iron`` / ``_stone`` / ``_copper``, by the look-alike city type; an unsure
  type is marked) on the city's own node and barrel.
- every Hall: the hall's node and the whole hall structure beside it (user), found under its orange beam.
- towers: as before. A map with the deadly-boss icon that is neither a city nor a hall gets no box of its own
  (user): its node box and its deadly-boss icon's box say it.
- every Breach stronghold, locked or open: a ``breach_stronghold`` box on its purple structure (the same structure
  either way; a locked one has its hand reveal button beside it).
- every square framed reveal button (``cities.square_buttons``: a locked stronghold's hand, the Expedition ship, a
  symbol not taught yet): a ``reveal_button`` box on its frame, whatever its kind (user: the classical namer names
  the kind, ``cities.name_button``).
- icons: ``icon_<type>`` with named icons, else ``icon`` (the deadly-boss icon too); every icon type is exported as
  ``icon``. The icon types that are no icon labels (``RF_DETR_ICON_EXCLUDED``: the Lost Tower and Checkpoint icons;
  the Expedition ship, which is a reveal button) get no icon box.
- optional traced paths and fortress-wall regions.

Boxes are ``(x, y, width, height)`` in the detector's pixels (the 1080p copy ``core.read_screenshot`` makes).
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from grand_project import cities

from . import constants as K
from . import labels as L
from .biomes import city_area_nodes, node_biomes
from .icon_types import icon_class

Box = tuple[float, float, float, float]
"""x, y, width, height in detector px."""


def clip_box(left: float, top: float, right: float, bottom: float, width: int, height: int) -> Box | None:
    """A box clipped to the image, or None when less than a pixel of it is left."""
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(width), right), min(float(height), bottom)
    if right - left <= 1 or bottom - top <= 1:
        return None
    return left, top, right - left, bottom - top


def box_at_point(
    x: float, y: float, box_width: float, box_height: float, width: int, height: int, *, anchor: str = "center"
) -> Box | None:
    """A clipped box around a point; with ``anchor="base"`` the box stands on the point."""
    left = x - box_width / 2
    top = y - box_height if anchor == "base" else y - box_height / 2
    return clip_box(left, top, left + box_width, top + box_height, width, height)


def box_around_line(line: Any, pad: float, width: int, height: int) -> Box | None:
    """A clipped box around a traced path's polyline."""
    points = np.asarray(line, dtype=float).reshape(-1, 2)
    if len(points) < 2:
        return None
    left, top = points.min(axis=0) - pad
    right, bottom = points.max(axis=0) + pad
    return clip_box(float(left), float(top), float(right), float(bottom), width, height)


def wall_boxes(mask: np.ndarray) -> list[Box]:
    """The classical fortress-wall mask as one box per large enough connected region."""
    _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    return [
        (float(x), float(y), float(width), float(height))
        for x, y, width, height, area in stats[1:]
        if area >= K.RF_DETR_WALL_MIN_AREA
    ]


def hall_box(img: np.ndarray, x: float, y: float) -> Box | None:
    """The hall box of a Hall whose map node is at (x, y): the node and the whole hall structure beside it.

    The structure stands under its orange beam (``finalize.landmarks._beam_column``, the column ``deadly_kind``
    judged the Hall by); with no beam seen it is put where it stood on the measured halls (up-left of the node).
    """
    from grand_project.finalize import landmarks as fl  # finalize imports detect: imported late

    height, width = img.shape[:2]
    column, _blue, orange = fl._beam_column(img, x, y, spread=K.RF_DETR_HALL_BEAM_SPREAD)
    middle = column if orange >= K.RF_DETR_HALL_BEAM_MIN else x + K.RF_DETR_HALL_STRUCTURE_DX
    box_width, box_height = K.RF_DETR_HALL_STRUCTURE_BOX
    top = y + K.RF_DETR_HALL_STRUCTURE_DY - box_height / 2
    half = K.RF_DETR_MAP_BOX / 2
    left = min(middle - box_width / 2, x - half)
    right = max(middle + box_width / 2, x + half)
    return clip_box(left, min(top, y - half), right, max(top + box_height, y + half), width, height)


def _icon_label(icon: dict[str, Any], named_icons: bool) -> str:
    """``icon_<type>`` with named icons, else ``icon`` (the deadly-boss icon too: user)."""
    return icon_class(str(icon.get("name") or "Unidentified")) if named_icons else L.GENERIC_ICON


def node_classes(
    img: np.ndarray, detection: dict[str, Any], city_types: dict[int, tuple[str, bool]]
) -> list[tuple[str, str]]:
    """Each map node's class and source: its city's area first, else the biome of its ground, else ``map_node``.

    Args:
        img: the screenshot (detector px).
        detection: the classical result ("nodes", "edges", "icons", "landmarks").
        city_types: landmark index -> (city type, sure) for the Cities (``cities.landmark_city_types``).

    Returns:
        (label, source) per node, in the order of ``detection["nodes"]``.
    """
    nodes = detection.get("nodes", [])
    icons = detection.get("icons", [])
    landmarks = detection.get("landmarks", [])
    sure_types = {city for city, sure in city_types.values() if sure}
    areas = city_area_nodes(
        nodes, detection.get("edges", []), icons, landmarks, {i: city for i, (city, _sure) in city_types.items()}
    )
    out = []
    for index, guess in enumerate(node_biomes(img, nodes, icons)):
        if index in areas:
            city, steps = areas[index]
            if steps == 0:  # the city's own map: as sure as the city's type
                source = K.RF_DETR_SOURCE_CLASSICAL if city in sure_types else K.RF_DETR_SOURCE_CITY_GUESS
            else:
                source = K.RF_DETR_SOURCE_CITY_AREA_GUESS
            out.append((L.node_label(city_type=city), source))
        elif guess.biome is None:
            out.append((L.node_label(), K.RF_DETR_SOURCE_CLASSICAL))
        else:
            source = K.RF_DETR_SOURCE_CLASSICAL if guess.sure else K.RF_DETR_SOURCE_BIOME_GUESS
            out.append((L.node_label(biome=guess.biome), source))
    return out


def dataset_boxes(
    detection: dict[str, Any],
    img: np.ndarray,
    *,
    named_icons: bool = False,
    include_paths: bool = False,
    wall_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Turn a classical detection result into labelled dataset boxes.

    Args:
        detection: the classical result (``detect_classical``: "nodes", "icons", "landmarks", "edges").
        img: the screenshot the detector read (detector px).
        named_icons: label icons by type (``icon_<type>``) instead of ``icon``.
        include_paths: add a ``path`` box around every traced path.
        wall_mask: the classical fortress-wall mask, for ``fortress_wall`` boxes (None: none).

    Returns:
        One dict per box: "label", "box" (x, y, w, h in detector px), "source" (``RF_DETR_SOURCE_*``) and "item"
        (the detection's own dict, for its score and its proposal flags).
    """
    height, width = img.shape[:2]
    out: list[dict[str, Any]] = []

    def add(label: str, box: Box | None, item: dict[str, Any], source: str = K.RF_DETR_SOURCE_CLASSICAL) -> None:
        if box is not None:
            out.append({"label": label, "box": box, "source": source, "item": item})

    landmarks = detection.get("landmarks", [])
    # Cities are always labelled by type (user's rule); an unsure look-alike guess is marked for the reviewer.
    city_types = cities.landmark_city_types(img, landmarks)
    map_box = K.RF_DETR_MAP_BOX
    for node, (label, source) in zip(detection.get("nodes", []), node_classes(img, detection, city_types), strict=True):
        add(label, box_at_point(float(node["x"]), float(node["y"]), map_box, map_box, width, height), node, source)
    for index, landmark in enumerate(landmarks):
        kind = str(landmark.get("kind", ""))
        x, y = float(landmark["x"]), float(landmark["y"])
        if kind == "City" and index in city_types:
            city, sure = city_types[index]
            box = box_at_point(x, y, K.RF_DETR_LANDMARK_BOX, K.RF_DETR_LANDMARK_BOX, width, height)
            add(
                L.citadel_label(city),
                box,
                landmark,
                K.RF_DETR_SOURCE_CLASSICAL if sure else K.RF_DETR_SOURCE_CITY_GUESS,
            )
        elif kind == "Hall":
            add("hall", hall_box(img, x, y), landmark)
        elif kind == "Tower":
            box = box_at_point(x, y, K.RF_DETR_TOWER_WIDTH, K.RF_DETR_TOWER_HEIGHT, width, height, anchor="base")
            add("tower", box, landmark)
        elif kind in ("Breach stronghold", "Locked stronghold"):
            # one structure, locked or open: its reveal button (below) says which (landmarks.stronghold_kind)
            box = box_at_point(x, y, K.RF_DETR_STRONGHOLD_BOX, K.RF_DETR_STRONGHOLD_BOX, width, height)
            add("breach_stronghold", box, landmark)
        # any other kind (a plain deadly-boss map): no box, its node box and its icon's box say it (user)
    # The reveal buttons: not in the classical result (only its ship buttons are, as icons), so found here; every
    # kind is one class, the classical namer names it (user).
    button_width, button_height = K.RF_DETR_BUTTON_BOX
    for button in cities.square_buttons(img):
        box = box_at_point(float(button["x"]), float(button["y"]), button_width, button_height, width, height)
        add("reveal_button", box, dict(button, score=button["frame"]))
    icon_box = K.RF_DETR_ICON_BOX
    for icon in detection.get("icons", []):
        if icon.get("name") in K.RF_DETR_ICON_EXCLUDED:
            continue
        box = box_at_point(float(icon["x"]), float(icon["y"]), icon_box, icon_box, width, height)
        add(_icon_label(icon, named_icons), box, icon)
    if include_paths:
        for edge in detection.get("edges", []):
            add("path", box_around_line(edge.get("line", []), K.RF_DETR_PATH_PAD, width, height), edge)
    if wall_mask is not None:
        for box in wall_boxes(wall_mask):
            add("fortress_wall", box, {})
    return out


__all__ = [
    "Box",
    "box_around_line",
    "box_at_point",
    "clip_box",
    "dataset_boxes",
    "hall_box",
    "node_classes",
    "wall_boxes",
]
