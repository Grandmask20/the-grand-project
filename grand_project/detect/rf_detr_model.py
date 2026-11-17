"""Optional RF-DETR inference backend.

The backend is deliberately opt-in.  It loads the fine-tuned Transformers model only when
``GRAND_PROJECT_USE_RF_DETR=1`` (or ``true`` / ``on``) is present, and returns the same detector result shape as the
classical pipeline.  Torch and Transformers stay lazy imports so normal installs and offline tests do not need the
training stack.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from grand_project import core

from .constants import (
    RF_DETR_DEFAULT_MODEL_DIR,
    RF_DETR_DEVICE_ENV,
    RF_DETR_MODEL_ENV,
    RF_DETR_NMS_IOU,
    RF_DETR_SCORE_THRESHOLD,
    RF_DETR_USE_ENV,
    WALL_CROSS,
)
from .landmarks import expedition_rules, ship_markers
from .paths import path_dashes as classical_path_dashes
from .paths import trace_paths
from .walls import fortress_walls, wall_share

_RUNTIME: dict[str, Any] | None = None


def rf_detr_enabled() -> bool:
    """Return whether the optional RF-DETR detector was explicitly enabled."""
    return os.environ.get(RF_DETR_USE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def rf_detr_model_path() -> Path:
    """Return the configured fine-tuned model directory."""
    value = os.environ.get(RF_DETR_MODEL_ENV)
    return Path(value).expanduser() if value else RF_DETR_DEFAULT_MODEL_DIR


def reset_rf_detr_runtime() -> None:
    """Forget a loaded model; useful when a test swaps the model path or feature flag."""
    global _RUNTIME
    _RUNTIME = None


def _device(torch):
    """Select the configured device, preferring the same accelerators as the trainer."""
    value = os.environ.get(RF_DETR_DEVICE_ENV, "auto").strip().lower()
    if value == "auto":
        value = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    return torch.device(value)


def _labels(model_dir: Path, model) -> dict[int, str]:
    """Read the saved label map, falling back to the Transformers config."""
    label_file = model_dir / "labels.json"
    if label_file.is_file():
        raw = json.loads(label_file.read_text(encoding="utf-8"))
        return {int(index): str(name) for index, name in raw.items()}
    return {int(index): str(name) for index, name in model.config.id2label.items()}


def _load_runtime() -> dict[str, Any]:
    """Load the processor and model once, failing clearly when the feature flag is misconfigured."""
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    model_dir = rf_detr_model_path()
    if not model_dir.is_dir():
        raise RuntimeError(
            f"RF-DETR is enabled but its model directory does not exist: {model_dir}. "
            "Run  make train_rf_detr  or set GRAND_PROJECT_RF_DETR_MODEL."
        )
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        processor = AutoImageProcessor.from_pretrained(model_dir)
        model = AutoModelForObjectDetection.from_pretrained(model_dir)
    except Exception as exc:
        raise RuntimeError(f"could not load the RF-DETR model from {model_dir}: {exc}") from exc
    device = _device(torch)
    model.to(device)
    model.eval()
    _RUNTIME = {"processor": processor, "model": model, "device": device, "labels": _labels(model_dir, model)}
    return _RUNTIME


def _canonical_label(label: str) -> str:
    """Normalise labels from the saved map or a hand-edited Transformers config."""
    text = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    aliases = {
        "map": "map_node",
        "map_base": "map_node",
        "landmark_tower": "tower",
        "landmark_city": "city",
        "landmark_hall": "hall",
        "landmark_deadly_boss_map": "deadly_boss_map",
        "landmark_breach_stronghold": "breach_stronghold",
        "landmark_locked_stronghold": "locked_stronghold",
        "path_segment": "path",
    }
    return aliases.get(text, text)


def _iou(a: list[float], b: list[float]) -> float:
    """Intersection over union for two ``xyxy`` boxes."""
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(1e-6, area_a + area_b - intersection)


def _dedupe(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply class-wise greedy NMS because DETR post-processing does not always suppress duplicates."""
    kept = []
    for label in sorted({d["label"] for d in detections}):
        candidates = sorted((d for d in detections if d["label"] == label), key=lambda d: -d["score"])
        selected = []
        for candidate in candidates:
            if all(_iou(candidate["box"], other["box"]) < RF_DETR_NMS_IOU for other in selected):
                selected.append(candidate)
        kept.extend(selected)
    return kept


def _predict(img: np.ndarray) -> list[dict[str, Any]]:
    """Run the model and return class names, scores and screen-pixel boxes."""
    import torch
    from PIL import Image

    runtime = _load_runtime()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    inputs = runtime["processor"](images=Image.fromarray(rgb), return_tensors="pt")
    inputs = {key: value.to(runtime["device"]) if torch.is_tensor(value) else value for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = runtime["model"](**inputs)
    target_sizes = torch.tensor([img.shape[:2]], device=runtime["device"])
    result = runtime["processor"].post_process_object_detection(
        outputs, threshold=RF_DETR_SCORE_THRESHOLD, target_sizes=target_sizes
    )[0]
    detections = []
    for box, score, label_id in zip(result["boxes"], result["scores"], result["labels"], strict=True):
        detections.append(
            {
                "label": _canonical_label(runtime["labels"].get(int(label_id), str(int(label_id)))),
                "score": float(score),
                "box": [float(value) for value in box.tolist()],
            }
        )
    return _dedupe(detections)


def _centre(box: list[float]) -> tuple[float, float]:
    """Return the centre of an ``xyxy`` box."""
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _icon_name(label: str, img: np.ndarray, x: float, y: float) -> str:
    """Recover the project's icon spelling from a generic or named RF-DETR class."""
    if label == "icon":
        try:
            from grand_project import icon_refs

            from .badges import name_badge

            refs = icon_refs.refs()
            name, _ = name_badge(img, x, y, refs.names, refs.F)
            return name
        except Exception:
            return "Unidentified"
    suffix = label.removeprefix("icon_")
    if suffix == "expeditionship":
        return "ExpeditionShip"
    try:
        from grand_project import icon_refs

        for name in icon_refs.refs().names:
            if re.sub(r"[^a-z0-9]+", "", name.lower()) == suffix.replace("_", ""):
                return name
    except Exception:
        pass  # the RF-DETR detector can still report the stable class without the optional icon database
    return "".join(part.title() for part in suffix.split("_")) or "Unidentified"


def _wall_mask(img: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    """Build a wall mask by merging RF-DETR wall boxes with the precise classical wall mask."""
    walls = [d for d in detections if d["label"] == "fortress_wall"]
    mask = fortress_walls(img)
    for item in walls:
        x0, y0, x1, y1 = map(round, item["box"])
        box_mask = np.zeros(img.shape[:2], np.uint8)
        cv2.rectangle(box_mask, (x0, y0), (x1, y1), 1, -1)
        mask = np.maximum(mask, box_mask)
    return mask


def detect_rf_detr(img: np.ndarray) -> dict:
    """Detect one screenshot with RF-DETR and return the classical detector's result shape."""
    detections = _predict(img)
    h, w = img.shape[:2]
    centres = [_centre(d["box"]) for d in detections]
    on_hud = core.on_hud_mask(np.asarray(centres, float), w, h, pad=0) if centres else np.zeros(0, bool)
    detections = [d for d, hidden in zip(detections, on_hud, strict=True) if not hidden]

    nodes = []
    for item in detections:
        if item["label"] != "map_node":
            continue
        x, y = _centre(item["box"])
        nodes.append({"x": x, "y": y, "score": round(item["score"], 3), "source": "rf-detr"})

    icons = []
    for item in detections:
        if not item["label"].startswith("icon"):
            continue
        x, y = _centre(item["box"])
        icons.append(
            {
                "name": _icon_name(item["label"], img, x, y),
                "x": round(x, 1),
                "y": round(y, 1),
                "score": round(item["score"], 3),
                "source": "rf-detr",
            }
        )

    landmarks = []
    towers = []
    for item in detections:
        label = item["label"]
        if label == "tower":
            # Tower annotations are anchored at the map base; the bottom of the predicted box is that point.
            x = (item["box"][0] + item["box"][2]) / 2
            y = item["box"][3]
            towers.append((x, y, item["score"]))
        elif label in {"city", "hall", "deadly_boss_map", "breach_stronghold", "locked_stronghold"}:
            x, y = _centre(item["box"])
            kind = {
                "city": "City",
                "hall": "Hall",
                "deadly_boss_map": "Deadly boss map",
                "breach_stronghold": "Breach stronghold",
                "locked_stronghold": "Locked stronghold",
            }[label]
            landmarks.append({"kind": kind, "x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3)})

    for x, y, score in towers:
        landmarks.append({"kind": "Tower", "x": round(x, 1), "y": round(y, 1), "score": round(score, 3)})
        if nodes:
            distances = np.hypot([node["x"] - x for node in nodes], [node["y"] - y for node in nodes])
            nearest = int(np.argmin(distances))
            if distances[nearest] <= 55:
                # The classical detector reports a tower as a landmark, not as an ordinary graph node.
                nodes.pop(nearest)
                continue

    predicted_dashes = np.asarray([_centre(d["box"]) for d in detections if d["label"] == "path_dash"], float).reshape(
        -1, 2
    )
    # The learned path-dash class handles dim and unusual paths; the established amber detector supplies a
    # safe fallback when a checkpoint has not learned enough dash examples yet.
    dashes = predicted_dashes if len(predicted_dashes) >= 2 else classical_path_dashes(img)
    edges = trace_paths(nodes, dashes, img)
    wall = _wall_mask(img, detections)
    edges = [edge for edge in edges if wall_share(edge["line"], wall) < WALL_CROSS]
    icons.extend(ship_markers(img))
    nodes, icons, landmarks = expedition_rules(nodes, icons, landmarks)
    return {
        "width": w,
        "height": h,
        "nodes": nodes,
        "landmarks": landmarks,
        "icons": icons,
        "edges": edges,
    }


__all__ = ["detect_rf_detr", "reset_rf_detr_runtime", "rf_detr_enabled", "rf_detr_model_path"]
