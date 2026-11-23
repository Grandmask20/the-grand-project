"""Optional RF-DETR inference backend.

The backend is deliberately opt-in. It loads the fine-tuned Transformers model only when
``GRAND_PROJECT_USE_RF_DETR=1`` (or ``true`` / ``on``) is present, and returns the same detector result shape as the
classical pipeline. Torch and Transformers stay lazy imports so normal installs and offline tests do not need the
training stack.

The model sees the screenshot as it was trained: native-scale tiles with the game HUD painted over
(``rf_detr_tiles.py``). Classes of one family (a map node is one of the node classes, a citadel one of three) are
scored together: an object is found when its family's score (the sum of its classes' scores) clears the threshold,
its class is the best one within the family, and duplicates are suppressed within the family across tiles. Classes
are matched by name (the checkpoint's own label map), never by id.

What the program gets back (as the classical detector reports it): every node class is a map node (with its
``biome`` or ``city_type``); a citadel is a City with its type at the city's map node; a hall a Hall at its map node;
a deadly-boss icon whose map is neither a citadel nor a hall a "Deadly boss map". The model finds every icon as the
one ``icon`` class and the classical naming step names it (``badges.name_found_icons``), as it names the classical
finder's icons; likewise every square reveal button as ``reveal_button``, named by its symbol
(``cities.name_button``): a ship button is an ``ExpeditionShip`` icon, a hand button makes the Breach stronghold
beside it locked (``landmarks.stronghold_kind``). Paths and fortress walls come from the classical finders.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from grand_project import core
from grand_project.cities import name_button

from . import constants as K
from . import labels as L
from . import rf_detr_tiles as T
from .badges import name_found_icons, naming_book
from .landmarks import expedition_rules, stronghold_kind
from .paths import path_dashes as classical_path_dashes
from .paths import trace_paths
from .walls import fortress_walls, wall_share

_RUNTIME: dict[str, Any] | None = None


def rf_detr_enabled() -> bool:
    """Return whether the optional RF-DETR detector was explicitly enabled."""
    return os.environ.get(K.RF_DETR_USE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def rf_detr_model_path() -> Path:
    """Return the configured fine-tuned model directory."""
    value = os.environ.get(K.RF_DETR_MODEL_ENV)
    return Path(value).expanduser() if value else K.RF_DETR_DEFAULT_MODEL_DIR


def reset_rf_detr_runtime() -> None:
    """Forget a loaded model; useful when a test swaps the model path or feature flag."""
    global _RUNTIME
    _RUNTIME = None


def _device(torch):
    """Select the configured device, preferring the same accelerators as the trainer."""
    value = os.environ.get(K.RF_DETR_DEVICE_ENV, "auto").strip().lower()
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


def class_families(labels: dict[int, str]) -> dict[str, list[tuple[int, str]]]:
    """A checkpoint's classes grouped by family.

    Args:
        labels: class id -> name, as the checkpoint saved them.

    Returns:
        family -> [(class id, name)]; a class of no family (a reviewer's own label) is a family of its own.
    """
    out: dict[str, list[tuple[int, str]]] = {}
    for index, name in sorted(labels.items()):
        out.setdefault(L.family(name) or name, []).append((index, name))
    return out


def load_detector(model_dir: Path) -> dict[str, Any]:
    """Load a fine-tuned checkpoint folder: its processor, model (eval mode, on the configured device) and class
    families.

    Raises:
        RuntimeError: the folder is missing, cannot be loaded, or has classes the labels no longer have.
    """
    if not model_dir.is_dir():
        raise RuntimeError(
            f"RF-DETR is enabled but its model directory does not exist: {model_dir}. "
            "Run  make train_rf_detr  or set GRAND_PROJECT_RF_DETR_MODEL."
        )
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        processor = AutoImageProcessor.from_pretrained(model_dir)
        # safetensors only: a pickled checkpoint can run code when loaded (AGENTS.md, models)
        model = AutoModelForObjectDetection.from_pretrained(model_dir, use_safetensors=True)
    except Exception as exc:
        raise RuntimeError(f"could not load the RF-DETR model from {model_dir}: {exc}") from exc
    labels = _labels(model_dir, model)
    unknown = sorted(name for name in labels.values() if not L.known(name))
    if unknown:
        # a checkpoint of an earlier label set: its retired classes (city, locked_stronghold, ...) would be found and
        # silently dropped, so the program would lose those objects
        raise RuntimeError(
            f"the RF-DETR model in {model_dir} has classes the labels no longer have ({', '.join(unknown)}): "
            "train it again on a new export"
        )
    device = _device(torch)
    model.to(device)
    model.eval()
    return {"processor": processor, "model": model, "device": device, "families": class_families(labels)}


def _load_runtime() -> dict[str, Any]:
    """Load the configured model once (``load_detector``), failing clearly when the feature flag is misconfigured."""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = load_detector(rf_detr_model_path())
    return _RUNTIME


def family_detections(
    probs: np.ndarray, boxes: np.ndarray, families: dict[str, list[tuple[int, str]]], threshold: float
) -> list[dict[str, Any]]:
    """Turn one tile's query outputs into detections, scoring each family's classes together.

    Args:
        probs: (queries, classes) sigmoid class scores.
        boxes: (queries, 4) ``[x0, y0, x1, y1]`` boxes in tile px.
        families: ``class_families`` of the checkpoint.
        threshold: the family score a detection needs.

    Returns:
        Detections {"label", "family", "score", "box"}: per query the family with the highest score (the sum of its
        classes' scores, at most 1) when it reaches ``threshold``, labelled with its best class.
    """
    if not len(probs) or not families:
        return []
    names = list(families)
    scores = np.stack([probs[:, [i for i, _n in families[f]]].sum(axis=1) for f in names], axis=1).clip(max=1.0)
    best = scores.argmax(axis=1)
    out = []
    for query in np.nonzero(scores[np.arange(len(scores)), best] >= threshold)[0]:
        name = names[int(best[query])]
        members = families[name]
        index = int(np.argmax(probs[query, [i for i, _n in members]]))
        out.append(
            {
                "label": members[index][1],
                "family": name,
                "score": float(scores[query, best[query]]),
                "box": [float(v) for v in boxes[query]],
            }
        )
    return out


def predict_tiles(
    model, processor, img: np.ndarray, families: dict[str, list[tuple[int, str]]], device, *, threshold: float
) -> list[dict[str, Any]]:
    """Run a model over a screenshot's tiles and merge what it finds, as training showed it the screenshots.

    Args:
        model: the RF-DETR model (eval mode).
        processor: its image processor (size: one tile).
        img: the screenshot (BGR) as the detector reads it (1080p).
        families: ``class_families`` of the model's classes.
        device: the model's torch device.
        threshold: the family score a detection needs.

    Returns:
        Detections {"label", "family", "score", "box" ``[x0, y0, x1, y1]`` in screenshot px}, one per object.
    """
    import torch

    height, width = img.shape[:2]
    prepared = T.pad_to_tile(T.fill_hud(img, rgb=False), rgb=False)
    tile = K.RF_DETR_TILE
    origins = T.tile_origins(prepared.shape[1], prepared.shape[0])
    detections: list[dict[str, Any]] = []
    for start in range(0, len(origins), K.RF_DETR_INFER_BATCH):
        batch = origins[start : start + K.RF_DETR_INFER_BATCH]
        tiles = [cv2.cvtColor(prepared[y : y + tile, x : x + tile], cv2.COLOR_BGR2RGB) for x, y in batch]
        inputs = processor(images=tiles, return_tensors="pt")
        inputs = {key: value.to(device) if torch.is_tensor(value) else value for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = model(**inputs)
        probs = outputs.logits.sigmoid().float().cpu().numpy()
        centre = outputs.pred_boxes.float().cpu().numpy() * tile  # (cx, cy, w, h) of the tile, in tile px
        corners = np.concatenate([centre[..., :2] - centre[..., 2:] / 2, centre[..., :2] + centre[..., 2:] / 2], -1)
        for (x, y), tile_probs, tile_boxes in zip(batch, probs, corners, strict=True):
            for det in family_detections(tile_probs, tile_boxes, families, threshold):
                if T.cut_by_inner_edge(det["box"], (x, y), (prepared.shape[1], prepared.shape[0])):
                    continue
                x0, y0, x1, y1 = det["box"]
                box = [max(0.0, x0 + x), max(0.0, y0 + y), min(float(width), x1 + x), min(float(height), y1 + y)]
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue  # all in the padding of a screenshot smaller than a tile: nothing of it is on it
                det["box"] = box
                detections.append(det)
    return T.nms(detections, K.RF_DETR_FAMILY_NMS_IOU)


def _predict(img: np.ndarray) -> list[dict[str, Any]]:
    """Run the loaded model over a screenshot's tiles (``predict_tiles``)."""
    runtime = _load_runtime()
    return predict_tiles(
        runtime["model"],
        runtime["processor"],
        img,
        runtime["families"],
        runtime["device"],
        threshold=K.RF_DETR_SCORE_THRESHOLD,
    )


def _centre(box: list[float]) -> tuple[float, float]:
    """Return the centre of an ``xyxy`` box."""
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _inside(box: list[float], x: float, y: float) -> bool:
    """Whether a point lies in an ``xyxy`` box."""
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _name_icons(img: np.ndarray, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name the model's icons with the classical detector's naming step (``badges.name_found_icons``: the stored
    pictures and the icon model's, the whole-icon templates of the icons with their own rim, the Expedition rule).

    The model's score is not the rim finder's probability, so the rim finder's influence rule (``INFLUENCE_MIN``) is
    left out: the model learned from reviewed boxes that terrain circles are no icons.
    """
    return name_found_icons(img, found, naming_book(), influence_min=None)


def _boss_node(nodes: list[dict], x: float, y: float) -> dict | None:
    """The map node under a deadly-boss icon at (x, y): ``RF_DETR_BOSS_ROW`` below it, ``RF_DETR_BOSS_DX`` aside."""
    low, high = K.RF_DETR_BOSS_ROW
    near = [n for n in nodes if low <= n["y"] - y <= high and abs(n["x"] - x) <= K.RF_DETR_BOSS_DX]
    return min(near, key=lambda n: abs(n["x"] - x) + abs(n["y"] - y - K.ROW_DY), default=None)


def hall_node(box: list[float], nodes: list[dict], bosses: list[dict]) -> dict | None:
    """The map node a hall's box stands for: the one inside it under its deadly-boss icon, else (the icon missed) the
    one inside it nearest the box's middle, else None.

    Args:
        box: the hall's ``xyxy`` box (its map node and structure).
        nodes: map node dicts with "x", "y".
        bosses: the deadly-boss icons ("MapBossSpecial"), dicts with "x", "y".
    """
    inside = [n for n in nodes if _inside(box, n["x"], n["y"])]
    for boss in bosses:
        node = _boss_node(inside, boss["x"], boss["y"])
        if node is not None:
            return node
    cx, cy = _centre(box)
    return min(inside, key=lambda n: np.hypot(n["x"] - cx, n["y"] - cy), default=None)


def _wall_mask(img: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    """Build a wall mask by merging RF-DETR wall boxes with the precise classical wall mask."""
    mask = fortress_walls(img)
    for item in detections:
        if item["family"] != "wall":
            continue
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
    by_family: dict[str, list[dict[str, Any]]] = {}
    for d in detections:
        by_family.setdefault(d["family"], []).append(d)

    nodes = []
    for item in by_family.get("node", []):
        x, y = _centre(item["box"])
        node = {"x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3), "source": "rf-detr"}
        if biome := L.biome(item["label"]):
            node["biome"] = biome
        if city := L.city_type(item["label"]):
            node["city_type"] = city
        nodes.append(node)

    # The reveal buttons (a locked stronghold's hand, the Expedition ship ...): the model finds them, the classical
    # namer names them by their symbol (user), searching a little wider around the model's middle.
    buttons = []
    for item in by_family.get("button", []):
        x, y = _centre(item["box"])
        kind, _symbol = name_button(img, x, y, margin=K.RF_DETR_BUTTON_SHIFT)
        buttons.append({"kind": kind, "x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3)})
    button_boxes = [item["box"] for item in by_family.get("button", [])]

    found = []
    for item in by_family.get("icon", []):
        x, y = _centre(item["box"])
        if any(_inside(box, x, y) for box in button_boxes):
            continue  # an icon the model also reports on a reveal button is that button
        found.append({"x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3), "source": "rf-detr"})
    # icon types that are no icon labels: the detector does not report them as icons
    icons = [icon for icon in _name_icons(img, found) if icon["name"] not in K.RF_DETR_ICON_EXCLUDED]
    # a ship button is reported as the classical detector reports it (landmarks.ship_markers): an ExpeditionShip icon
    icons.extend(
        {"name": K.RF_DETR_BUTTON_ICONS[b["kind"]], "x": b["x"], "y": b["y"], "score": b["score"], "source": "rf-detr"}
        for b in buttons
        if b["kind"] in K.RF_DETR_BUTTON_ICONS
    )
    locks = [(b["x"], b["y"]) for b in buttons if b["kind"] == "lock"]

    landmarks: list[dict[str, Any]] = []
    own: list[dict] = []  # the map nodes the Cities and Halls are
    unplaced: list[list[float]] = []  # the boxes of the Cities and Halls with no map node found for them
    for item in by_family.get("citadel", []):
        # the City is its map node (as the classical detector reports it): the one inside the box nearest its middle
        cx, cy = _centre(item["box"])
        inside = [n for n in nodes if _inside(item["box"], n["x"], n["y"])]
        node = min(inside, key=lambda n: np.hypot(n["x"] - cx, n["y"] - cy), default=None)
        if node is not None:
            own.append(node)
        else:
            unplaced.append(item["box"])
        x, y = (node["x"], node["y"]) if node else (cx, cy)
        landmark = {"kind": "City", "x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3)}
        if city := L.city_type(item["label"]):
            landmark["city_type"] = city
        landmarks.append(landmark)
    bosses = [i for i in icons if i["name"] == "MapBossSpecial"]
    for item in by_family.get("hall", []):
        # the Hall is its map node (as the classical detector reports it)
        node = hall_node(item["box"], nodes, bosses)
        if node is not None:
            own.append(node)
        else:
            unplaced.append(item["box"])
        x, y = (node["x"], node["y"]) if node else _centre(item["box"])
        landmarks.append({"kind": "Hall", "x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3)})
    for item in by_family.get("stronghold", []):
        # one structure, locked or open: a hand reveal button beside it (or no map node inside) makes it locked, as
        # in the classical detector
        x, y = _centre(item["box"])
        kind, _why = stronghold_kind(x, y, locks, nodes)
        landmarks.append({"kind": kind, "x": round(x, 1), "y": round(y, 1), "score": round(item["score"], 3)})
    # a deadly-boss icon over a map that is neither a citadel nor a hall marks a deadly boss map (user)
    places = [d["box"] for d in [*by_family.get("citadel", []), *by_family.get("hall", [])]]
    for boss in bosses:
        node = _boss_node(nodes, boss["x"], boss["y"])
        if node is not None and any(node is mine for mine in own):
            continue  # the City's or Hall's own map
        x, y = (node["x"], node["y"]) if node else (boss["x"], boss["y"] + K.ROW_DY)
        # a map beside a City or Hall inside its box (a hall's structure is wide) is a deadly boss map of its own;
        # the box alone decides for a City or Hall with no map node found, or an icon over no map node found
        if any(_inside(box, x, y) for box in (places if node is None else unplaced)):
            continue
        landmarks.append({"kind": "Deadly boss map", "x": round(x, 1), "y": round(y, 1), "score": boss["score"]})

    for item in by_family.get("tower", []):
        # Tower boxes stand on the map node; the bottom of the predicted box is that point.
        x, y, score = (item["box"][0] + item["box"][2]) / 2, item["box"][3], item["score"]
        landmarks.append({"kind": "Tower", "x": round(x, 1), "y": round(y, 1), "score": round(score, 3)})
        if nodes:
            distances = np.hypot([node["x"] - x for node in nodes], [node["y"] - y for node in nodes])
            nearest = int(np.argmin(distances))
            if distances[nearest] <= K.RF_DETR_TOWER_NODE_REACH:
                # As in the classical detector (landmarks_from): the tower's map node stays in the graph, flagged, so
                # paths still reach it (trace_paths) and expedition_rules can unflag it; other map nodes this close
                # are the same wide tower base.
                tower = nodes[nearest]
                tower["tower"] = True
                nodes = [
                    node
                    for node in nodes
                    if node is tower or np.hypot(node["x"] - tower["x"], node["y"] - tower["y"]) > K.TOWER_NMS
                ]

    # the Expedition rules first, as in the classical detector: they clear tower flags the path tracer reads
    nodes, icons, landmarks = expedition_rules(nodes, icons, landmarks)
    edges = trace_paths(nodes, classical_path_dashes(img), img)
    wall = _wall_mask(img, detections)
    edges = [edge for edge in edges if wall_share(edge["line"], wall) < K.WALL_CROSS]
    return {
        "width": w,
        "height": h,
        "nodes": nodes,
        "landmarks": landmarks,
        "icons": icons,
        "edges": edges,
    }


__all__ = [
    "class_families",
    "detect_rf_detr",
    "family_detections",
    "hall_node",
    "load_detector",
    "predict_tiles",
    "reset_rf_detr_runtime",
    "rf_detr_enabled",
    "rf_detr_model_path",
]
