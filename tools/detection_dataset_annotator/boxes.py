"""What the box editor shows and sends back: its picture, its labels, and boxes mapped to saved annotations.

The editor refers to boxes by a stable annotation ``id``, so an edit maps back to the right annotation however
earlier autosaves reordered the saved list; export ignores the ids.
"""

from __future__ import annotations

import base64
import colorsys
import copy
import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import cv2

from . import constants as K
from .detection import decode_image


def editor_image_url(path: Path) -> str | None:
    """A JPEG data URL of the unmodified screenshot at source resolution, for the editor to display.

    Boxes are never drawn into it: the editor shows them as separate page elements over this picture.
    """
    image = decode_image(path)
    if image is None:
        return None
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, K.ANNOTATOR_EDITOR_JPEG_QUALITY])
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _css_color(bgr: tuple[int, int, int]) -> str:
    blue, green, red = bgr
    return f"#{red:02x}{green:02x}{blue:02x}"


def _hashed_color(label: str) -> str:
    """A stable, readable colour for labels without a fixed one (named icons, custom labels)."""
    hue = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:4], 16) % 360 / 360
    red, green, blue = colorsys.hls_to_rgb(hue, K.ANNOTATOR_HASHED_LIGHTNESS, K.ANNOTATOR_HASHED_SATURATION)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def label_palette(labels: Iterable[str]) -> list[dict[str, str]]:
    """Give each editor label a colour and, for the first ten, a number hotkey."""
    fixed = {
        label: _css_color(color) for label, color in zip(K.ANNOTATOR_CORE_LABELS, K.ANNOTATOR_LABEL_COLORS, strict=True)
    }
    fixed.update({label: _css_color(color) for label, color in K.ANNOTATOR_EXTRA_LABEL_COLORS.items()})
    hotkeys = K.ANNOTATOR_LABEL_HOTKEYS
    return [
        {"name": label, "color": fixed.get(label) or _hashed_color(label), "hotkey": hotkeys[index : index + 1]}
        for index, label in enumerate(labels)
    ]


def ensure_annotation_ids(item: dict[str, Any]) -> bool:
    """Give every annotation of a screenshot a stable, unique ``id``; return whether any was added.

    A missing or duplicate id gets the next free ``b<n>``; ``next_annotation_id`` remembers the counter, so an id
    is never handed out twice.
    """
    annotations = item.get("annotations", [])
    used = {str(annotation["id"]) for annotation in annotations if annotation.get("id") is not None}
    counter = int(item.get("next_annotation_id", 0))
    seen: set[str] = set()
    changed = False
    for annotation in annotations:
        current = annotation.get("id")
        if current is not None and str(current) not in seen:
            seen.add(str(current))
            continue
        while f"b{counter}" in used:
            counter += 1
        annotation["id"] = f"b{counter}"
        used.add(annotation["id"])
        seen.add(annotation["id"])
        counter += 1
        changed = True
    if changed:
        item["next_annotation_id"] = counter
    return changed


def _xywh(values: Any) -> tuple[float, float, float, float] | None:
    """Four floats from a bbox list, or None when it is not one."""
    try:
        x, y, width, height = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    return x, y, width, height


def editor_boxes(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Saved annotations as editor boxes, keyed by their stable ``id`` (see ``ensure_annotation_ids``)."""
    boxes = []
    for annotation in annotations:
        bbox = _xywh(annotation.get("bbox"))
        if bbox is None:
            continue
        x, y, width, height = bbox
        boxes.append(
            {
                "id": str(annotation.get("id", "")),
                "label": str(annotation.get("label", "")),
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "score": annotation.get("score"),
                "source": annotation.get("source", K.ANNOTATOR_CLASSICAL_SOURCE),
            }
        )
    return boxes


def _unchanged(annotation: dict[str, Any], label: str, bbox: list[float]) -> bool:
    """Whether an editor box still has a saved annotation's label and (within tolerance) its geometry."""
    old = annotation.get("bbox", [])
    return (
        str(annotation.get("label", "")) == label
        and len(old) == 4
        and all(abs(float(a) - b) <= K.ANNOTATOR_EDITOR_UNCHANGED_PX for a, b in zip(old, bbox, strict=True))
    )


def apply_editor_boxes(
    original: list[dict[str, Any]],
    boxes: Iterable[dict[str, Any]],
    *,
    width: int,
    height: int,
    known: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Turn the editor's boxes back into saved annotations in source-image pixels.

    Boxes are clipped to the image and dropped when under one pixel. A box whose id, label and geometry match a
    saved annotation keeps it as is (score and source included). A changed box keeps its id but becomes a manual
    box without score. ``known`` holds annotations this editor showed earlier and that are no longer saved, so an
    undone delete brings back the detector's box rather than a manual copy. A box with an id nobody knows is new;
    it keeps the editor's id (``ensure_annotation_ids`` replaces a missing or duplicate one).
    """
    by_id = {str(annotation["id"]): annotation for annotation in known if annotation.get("id") is not None}
    by_id.update({str(annotation["id"]): annotation for annotation in original if annotation.get("id") is not None})
    annotations = []
    used: set[str] = set()
    for box in boxes:
        geometry = _xywh(box.get(key) for key in ("x", "y", "w", "h"))
        label = str(box.get("label", "")).strip()
        if geometry is None or not label:
            continue
        x, y, box_width, box_height = geometry
        left, top = max(0.0, x), max(0.0, y)
        right, bottom = min(float(width), x + box_width), min(float(height), y + box_height)
        if right - left < 1 or bottom - top < 1:
            continue
        bbox = [round(left, 2), round(top, 2), round(right - left, 2), round(bottom - top, 2)]
        box_id = str(box.get("id") or "")
        fresh_id = bool(box_id) and box_id not in used
        if fresh_id:
            used.add(box_id)
            saved = by_id.get(box_id)
            if saved is not None and _unchanged(saved, label, bbox):
                annotations.append(copy.deepcopy(saved))
                continue
        annotation: dict[str, Any] = {
            "label": label,
            "bbox": bbox,
            "area": round(bbox[2] * bbox[3], 2),
            "iscrowd": 0,
            "source": K.ANNOTATOR_MANUAL_SOURCE,
        }
        if fresh_id:
            annotation["id"] = box_id
        annotations.append(annotation)
    return annotations


def annotations_changed(saved: list[dict[str, Any]], edited: list[dict[str, Any]]) -> bool:
    """Whether the edited annotations differ from the saved ones (so autosave writes only real changes)."""

    def key(annotations: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [
            (a.get("id"), a.get("label"), tuple(a.get("bbox", ())), a.get("source"), a.get("score"))
            for a in annotations
        ]

    return key(saved) != key(edited)


def editor_payload_matches(payload: Any, image_key: str, revision: int) -> bool:
    """Whether an editor message belongs to the screenshot and detection revision on screen now.

    A late message from the previous screenshot, or from before a detector rerun, must not overwrite these boxes.
    """
    return (
        isinstance(payload, dict)
        and payload.get("image_key") == image_key
        and payload.get("revision") == revision
        and isinstance(payload.get("boxes"), list)
    )
