"""What the box editor shows and sends back: its picture, its labels, and boxes mapped to saved annotations.

The editor refers to boxes by a stable annotation ``id``, so an edit maps back to the right annotation however
earlier autosaves reordered the saved list; export ignores the ids.
"""

from __future__ import annotations

import base64
import colorsys
import copy
import functools
import hashlib
import io
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import cv2
from PIL import Image

from grand_project import paths
from grand_project.detect.constants import ICON_INFO, RF_DETR_LABEL_INFO
from grand_project.detect.icon_types import file_picture, icon_picture, icon_type

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


@functools.cache
def label_picture(label: str) -> str:
    """A WebP data URL of the picture shown next to a label in the editor, or "" for a label without one.

    A registry label shows the picture its entry names (an icon type or a references/ file), an ``icon_<type>`` label
    its icon type's picture (its poe2db art, else a stored on-screen picture).
    """
    size = K.ANNOTATOR_LABEL_PICTURE_PX
    art = RF_DETR_LABEL_INFO.get(label, {}).get("picture")
    if art is None:
        name = icon_type(label)
        picture = icon_picture(name, size) if name else None
    elif art in ICON_INFO:
        picture = icon_picture(art, size)
    else:
        picture = file_picture(paths.ref(art), size)
    if picture is None:
        return ""
    buffer = io.BytesIO()  # Pillow, not OpenCV: OpenCV's lossy WebP drops the transparency
    Image.fromarray(cv2.cvtColor(picture, cv2.COLOR_BGRA2RGBA)).save(
        buffer, "WEBP", quality=K.ANNOTATOR_LABEL_PICTURE_QUALITY, method=6
    )
    return "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def label_text(label: str) -> tuple[str, str]:
    """A label's title (its registry title, else an icon's poe2db name, else "") and the words it can be found by.

    Returns:
        (title, search): e.g. ("Breach Hive", "icon_breachhive breach hive breach hive, complete all breach hives").
    """
    name = icon_type(label)
    icon_title, _colour, aliases = ICON_INFO[name] if name else ("", None, "")
    title = RF_DETR_LABEL_INFO.get(label, {}).get("title") or icon_title
    return title, " ".join(part for part in (label, title, icon_title, aliases) if part).lower()


def _hotkey(key: str) -> dict[str, Any]:
    """A registry key ("1", "shift+1") as the editor matches and shows it: the key's code and whether Shift is held
    (``event.code`` is the same on every keyboard layout; Shift+1 types "!" on one and "+" on another)."""
    shift = key.startswith("shift+")
    digit = key.removeprefix("shift+")
    return {"hotkey": f"⇧{digit}" if shift else digit, "code": f"Digit{digit}", "shift": shift}


def label_palette(labels: Iterable[str]) -> list[dict[str, Any]]:
    """Give each editor label its colour, picture, title, box rule and hotkey (the registry's; hashed colours and no
    key for icon types and custom labels)."""
    palette = []
    for label in labels:
        entry = RF_DETR_LABEL_INFO.get(label, {})
        title, search = label_text(label)
        color = entry.get("color")
        key = entry.get("key")
        palette.append(
            {
                "name": label,
                "color": _css_color(color) if color else _hashed_color(label),
                "picture": label_picture(label),
                "title": title,
                "rule": entry.get("rule", ""),
                "search": search,
                **(_hotkey(key) if key else {"hotkey": "", "code": "", "shift": False}),
            }
        )
    return palette


def ensure_annotation_ids(item: dict[str, Any]) -> bool:
    """Give every annotation of a screenshot a stable, unique ``id``; return whether any was added.

    A missing or duplicate id gets the next free ``b<n>``; ``next_annotation_id`` remembers the counter, past every
    ``b<n>`` kept too (saved whenever it moves), so an id is never handed out twice: not even a deleted box's, whose
    old annotation the editor's undo memory still knows by it.
    """
    annotations = item.get("annotations", [])
    used = {str(annotation["id"]) for annotation in annotations if annotation.get("id") is not None}
    start = int(item.get("next_annotation_id", 0))
    numbers = [int(name[1:]) for name in used if name[:1] == "b" and name[1:].isdigit()]
    counter = max([start, *(number + 1 for number in numbers)])
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
    if counter != start:
        item["next_annotation_id"] = counter
    return changed


def _xywh(values: Any) -> tuple[float, float, float, float] | None:
    """Four floats from a bbox list, or None when it is not one."""
    try:
        x, y, width, height = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        return None  # NaN would pass every clip and be saved (and an infinite size would fill the screenshot)
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

    Boxes are clipped to the image and dropped when under one pixel. A box whose id, label and geometry (within
    ``ANNOTATOR_EDITOR_UNCHANGED_PX``: the editor rounds) match a saved annotation keeps it as is (score and source
    included). A changed box keeps its id but becomes a manual box without score. ``known`` holds annotations this
    editor showed earlier and that are no longer saved (the server's memory of them), so an undone edit or delete
    brings back the detector's box rather than a manual copy. A box with an id nobody knows is new; it keeps the
    editor's id (``ensure_annotation_ids`` replaces a missing or duplicate one).

    The editor sends each box's ``source``: one it marked ``manual`` (moved, resized, typed in or relabelled) is an
    edit however small, so it is saved as one and never takes a detector box's score back by landing where it was;
    only a box the editor still has as the detector's (untouched, or undone to it) keeps the saved or known one. A
    box without a ``source`` is judged by its geometry alone.
    """
    remembered = {str(annotation["id"]): annotation for annotation in known if annotation.get("id") is not None}
    by_id = {**remembered}
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
        edited = box.get("source") == K.ANNOTATOR_MANUAL_SOURCE
        if fresh_id:
            used.add(box_id)
            saved = by_id.get(box_id)
            if saved is not None and box.get("source") and saved.get("source") != box["source"]:
                # undone to an earlier version: the one this editor was shown with that source
                earlier = remembered.get(box_id)
                saved = earlier if earlier is not None and earlier.get("source") == box["source"] else saved
            if saved is not None and not edited and _unchanged(saved, label, bbox):
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
