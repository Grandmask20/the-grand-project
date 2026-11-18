"""Classical-detector dataset bootstrap helpers.

This module intentionally has no Streamlit import.  It owns discovery, persistent review state, conversion of the
project detector's point/line results to editable ``xywh`` boxes, and export of both a COCO file and a manifest that
``tools.train_rf_detr`` can consume.
"""

from __future__ import annotations

import base64
import colorsys
import contextlib
import copy
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from constants import (
    BOOTSTRAP_COCO_FILE,
    BOOTSTRAP_CORE_LABELS,
    BOOTSTRAP_DEFAULT_INPUT_DIRS,
    BOOTSTRAP_DEFAULT_WORKERS,
    BOOTSTRAP_EDITOR_JPEG_QUALITY,
    BOOTSTRAP_EDITOR_UNCHANGED_PX,
    BOOTSTRAP_EXTRA_LABEL_COLORS,
    BOOTSTRAP_HIDDEN_SOURCE,
    BOOTSTRAP_ICON_SOURCE,
    BOOTSTRAP_IMAGE_EXTENSIONS,
    BOOTSTRAP_LABEL_COLORS,
    BOOTSTRAP_LABEL_HOTKEYS,
    BOOTSTRAP_MANIFEST_FILE,
    BOOTSTRAP_OPENCV_THREADS_ENV,
    BOOTSTRAP_ROOT,
    BOOTSTRAP_SCHEMA_VERSION,
    BOOTSTRAP_WORKER_MODULE,
)

from grand_project import core
from grand_project.detect import constants as detector_constants

DetectionCallback = Callable[[np.ndarray], dict[str, Any]]


def default_input_paths(project_root: Path = BOOTSTRAP_ROOT) -> list[Path]:
    """Return the requested screenshot roots relative to the project root."""
    return [project_root / relative for relative in BOOTSTRAP_DEFAULT_INPUT_DIRS]


def resolve_input_paths(values: Iterable[str], project_root: Path = BOOTSTRAP_ROOT) -> list[Path]:
    """Resolve user-entered roots, interpreting relative paths from the project root."""
    paths = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        path = Path(value).expanduser()
        paths.append((path if path.is_absolute() else project_root / path).resolve())
    return paths


def discover_images(roots: Iterable[Path]) -> list[Path]:
    """Recursively find supported image files below each input root, without duplicate paths."""
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_file() and root.suffix.lower() in BOOTSTRAP_IMAGE_EXTENSIONS:
            candidates = (root,)
        elif root.is_dir():
            candidates = root.rglob("*")
        else:
            continue
        for path in candidates:
            if path.is_file() and path.suffix.lower() in BOOTSTRAP_IMAGE_EXTENSIONS:
                resolved = path.resolve()
                found[os.path.normcase(str(resolved))] = resolved
    return sorted(found.values(), key=lambda path: str(path).casefold())


def image_key(path: Path) -> str:
    """Return a stable, filesystem-safe identifier for a screenshot."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def relative_source(path: Path, project_root: Path = BOOTSTRAP_ROOT) -> str:
    """Prefer a project-relative source name while preserving paths outside the project."""
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def new_state(
    input_roots: Iterable[Path],
    *,
    include_paths: bool = False,
    include_fortress_walls: bool = False,
    named_icons: bool = False,
) -> dict[str, Any]:
    """Create an empty review state."""
    return {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "input_roots": [str(path) for path in input_roots],
        "settings": {
            "include_paths": include_paths,
            "include_fortress_walls": include_fortress_walls,
            "named_icons": named_icons,
        },
        "images": {},
    }


def read_state(path: Path, input_roots: Iterable[Path]) -> dict[str, Any]:
    """Load a review state, or return a fresh state when the file does not exist."""
    if not path.is_file():
        return new_state(input_roots)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != BOOTSTRAP_SCHEMA_VERSION:
        raise ValueError(f"Unsupported bootstrap state version: {state.get('schema_version')}")
    state.setdefault("input_roots", [str(root) for root in input_roots])
    state.setdefault("settings", {})
    state.setdefault("images", {})
    return state


def write_json_atomic(path: Path, value: Any) -> None:
    """Write JSON through a neighboring temporary file so a rerun cannot leave half a state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist the review state."""
    write_json_atomic(path, state)


def merge_discovered_images(state: dict[str, Any], paths: Iterable[Path]) -> tuple[int, int]:
    """Add newly discovered images while preserving all existing detections and edits."""
    added = 0
    existing = 0
    images = state.setdefault("images", {})
    for path in paths:
        key = image_key(path)
        if key in images:
            existing += 1
            continue
        images[key] = {
            "path": str(path),
            "source": relative_source(path),
            "reviewed": False,
            "detected": False,
            "annotations": [],
        }
        added += 1
    return added, existing


def _read_raw_image(path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """Read raw and detector-scaled BGR images, supporting non-ASCII paths on Windows."""
    encoded = np.fromfile(str(path), dtype=np.uint8)
    raw = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    detector = core.read_screenshot(path)
    if raw is None or detector is None:
        return None
    return raw, detector


def _xywh_from_point(
    x: float,
    y: float,
    width: float,
    height: float,
    image_width: int,
    image_height: int,
    *,
    anchor: str = "center",
) -> tuple[float, float, float, float] | None:
    """Build a clipped detector-space box around a point."""
    left = x - width / 2
    top = y - height if anchor == "base" else y - height / 2
    right, bottom = left + width, top + height
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(image_width), right), min(float(image_height), bottom)
    if right - left <= 1 or bottom - top <= 1:
        return None
    return left, top, right - left, bottom - top


def _xywh_from_line(
    line: Any, pad: float, image_width: int, image_height: int
) -> tuple[float, float, float, float] | None:
    """Build a clipped detector-space box around a traced path polyline."""
    points = np.asarray(line, dtype=float).reshape(-1, 2)
    if len(points) < 2:
        return None
    left, top = points.min(axis=0) - pad
    right, bottom = points.max(axis=0) + pad
    left, top = max(0.0, float(left)), max(0.0, float(top))
    right, bottom = min(float(image_width), float(right)), min(float(image_height), float(bottom))
    if right - left <= 1 or bottom - top <= 1:
        return None
    return left, top, right - left, bottom - top


def _scaled_box(box: tuple[float, float, float, float], scale_x: float, scale_y: float) -> list[float]:
    """Convert detector-space ``xywh`` to source-image pixels."""
    x, y, width, height = box
    return [round(x * scale_x, 2), round(y * scale_y, 2), round(width * scale_x, 2), round(height * scale_y, 2)]


def _annotation(
    label: str,
    box: tuple[float, float, float, float] | None,
    *,
    scale_x: float,
    scale_y: float,
    score: float | None = None,
    source: str = "classical",
) -> dict[str, Any] | None:
    """Create one editable source-image annotation."""
    if box is None:
        return None
    scaled = _scaled_box(box, scale_x, scale_y)
    result: dict[str, Any] = {
        "label": label,
        "bbox": scaled,
        "area": round(scaled[2] * scaled[3], 2),
        "iscrowd": 0,
        "source": source,
    }
    if score is not None:
        result["score"] = round(float(score), 4)
    return result


def _icon_label(icon: dict[str, Any], named_icons: bool) -> str:
    """Return the generic or stable named icon class."""
    if not named_icons:
        return "icon"
    name = str(icon.get("name") or "unidentified").lower()
    safe = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return f"icon_{safe or 'unknown'}"


def _wall_boxes(mask: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Turn the optional classical fortress mask into connected-component boxes."""
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    boxes = []
    for x, y, width, height, area in stats[1:]:
        if area >= detector_constants.RF_DETR_WALL_MIN_AREA:
            boxes.append((float(x), float(y), float(width), float(height)))
    return boxes


def detection_annotations(
    detection: dict[str, Any],
    detector_image: np.ndarray,
    raw_image: np.ndarray,
    *,
    include_paths: bool = False,
    include_fortress_walls: bool = False,
    named_icons: bool = False,
    wall_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Convert a classical detector result to editable source-image ``xywh`` annotations."""
    detector_height, detector_width = detector_image.shape[:2]
    raw_height, raw_width = raw_image.shape[:2]
    scale_x, scale_y = raw_width / detector_width, raw_height / detector_height
    annotations: list[dict[str, Any]] = []

    def add(
        label: str, box: tuple[float, float, float, float] | None, item: dict[str, Any], source: str = "classical"
    ) -> None:
        value = _annotation(
            label,
            box,
            scale_x=scale_x,
            scale_y=scale_y,
            score=item.get("score", item.get("conf")),
            source=source,
        )
        if value:
            annotations.append(value)

    for node in detection.get("nodes", []):
        add(
            "map_node",
            _xywh_from_point(
                float(node["x"]),
                float(node["y"]),
                detector_constants.RF_DETR_MAP_BOX,
                detector_constants.RF_DETR_MAP_BOX,
                detector_width,
                detector_height,
            ),
            node,
            BOOTSTRAP_HIDDEN_SOURCE if node.get("proposal") else "classical",
        )
    for landmark in detection.get("landmarks", []):
        kind = str(landmark.get("kind", ""))
        label = {
            "Tower": "tower",
            "City": "city",
            "Hall": "hall",
            "Deadly boss map": "deadly_boss_map",
            "Breach stronghold": "breach_stronghold",
            "Locked stronghold": "locked_stronghold",
        }.get(kind)
        if label is None:
            continue
        if label == "tower":
            width, height, anchor = (
                detector_constants.RF_DETR_TOWER_WIDTH,
                detector_constants.RF_DETR_TOWER_HEIGHT,
                "base",
            )
        elif label in {"breach_stronghold", "locked_stronghold"}:
            width = height = detector_constants.RF_DETR_STRONGHOLD_BOX
            anchor = "center"
        else:
            width = height = detector_constants.RF_DETR_LANDMARK_BOX
            anchor = "center"
        add(
            label,
            _xywh_from_point(
                float(landmark["x"]),
                float(landmark["y"]),
                width,
                height,
                detector_width,
                detector_height,
                anchor=anchor,
            ),
            landmark,
        )
    for icon in detection.get("icons", []):
        add(
            _icon_label(icon, named_icons),
            _xywh_from_point(
                float(icon["x"]),
                float(icon["y"]),
                detector_constants.RF_DETR_ICON_BOX,
                detector_constants.RF_DETR_ICON_BOX,
                detector_width,
                detector_height,
            ),
            icon,
            BOOTSTRAP_ICON_SOURCE if icon.get("proposal") else "classical",
        )

    if include_paths:
        for edge in detection.get("edges", []):
            add(
                "path",
                _xywh_from_line(
                    edge.get("line", []), detector_constants.RF_DETR_PATH_PAD, detector_width, detector_height
                ),
                edge,
            )
    if include_fortress_walls and wall_mask is not None:
        for box in _wall_boxes(wall_mask):
            add("fortress_wall", box, {})
    return annotations


def run_classical_detector(
    path: Path,
    *,
    include_paths: bool = False,
    include_fortress_walls: bool = False,
    named_icons: bool = False,
) -> dict[str, Any]:
    """Read one screenshot, run the established classical detector, and return a state-ready result."""
    loaded = _read_raw_image(path)
    if loaded is None:
        raise ValueError(f"Could not read image: {path}")
    raw_image, detector_image = loaded
    from icon_proposals import hidden_nodes, map_spots, propose_icons

    from grand_project.detect.models import _models
    from grand_project.detect.pipeline import detect_classical

    detection = detect_classical(detector_image)
    # The classical finder misses most of the larger silver-rimmed icons (res atlases) and the fogged map nodes
    # under icons: add the rim candidates whose picture matches a stored icon, then a map node under every icon row
    # without one (``_models`` holds the models detect_classical loaded).
    spots = map_spots(detector_image, _models["maps"])
    detection["icons"] = detection["icons"] + propose_icons(detector_image, detection, _models["badges"], spots)
    detection["nodes"] = detection["nodes"] + hidden_nodes(detector_image, detection, detection["icons"], spots)
    wall_mask = None
    if include_fortress_walls:
        from grand_project.detect.walls import fortress_walls

        wall_mask = fortress_walls(detector_image)
    annotations = detection_annotations(
        detection,
        detector_image,
        raw_image,
        include_paths=include_paths,
        include_fortress_walls=include_fortress_walls,
        named_icons=named_icons,
        wall_mask=wall_mask,
    )
    return {
        "detected": True,
        "detector": "classical",
        "width": int(raw_image.shape[1]),
        "height": int(raw_image.shape[0]),
        "detector_width": int(detector_image.shape[1]),
        "detector_height": int(detector_image.shape[0]),
        "annotations": annotations,
        "error": None,
    }


def _read_worker_output(
    process: subprocess.Popen[str], output: queue.Queue[tuple[subprocess.Popen[str], str | None]]
) -> None:
    """Forward worker output lines to the Streamlit thread without blocking its progress updates."""
    if process.stdout is None:
        output.put((process, None))
        return
    try:
        for line in process.stdout:
            output.put((process, line))
    finally:
        output.put((process, None))


def _start_detection_worker(
    output: queue.Queue[tuple[subprocess.Popen[str], str | None]],
    opencv_threads: int,
) -> tuple[subprocess.Popen[str], threading.Thread]:
    """Start an isolated Python worker; CPU-heavy detection stays out of the Streamlit process."""
    program_dir = Path(__file__).resolve().parent
    python_paths = [str(program_dir), str(BOOTSTRAP_ROOT)]
    if os.environ.get("PYTHONPATH"):
        python_paths.append(os.environ["PYTHONPATH"])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    environment[BOOTSTRAP_OPENCV_THREADS_ENV] = str(opencv_threads)
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", BOOTSTRAP_WORKER_MODULE],
        cwd=BOOTSTRAP_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    reader = threading.Thread(
        target=_read_worker_output,
        args=(process, output),
        name=f"atlas-worker-output-{process.pid}",
        daemon=True,
    )
    reader.start()
    return process, reader


def _stop_detection_workers(
    workers: Iterable[tuple[subprocess.Popen[str], threading.Thread]],
) -> None:
    """Close worker input and reap every child, terminating only workers that fail to exit."""
    workers = list(workers)
    for process, _reader in workers:
        if process.stdin is not None and not process.stdin.closed:
            with contextlib.suppress(OSError):
                process.stdin.close()
    for process, _reader in workers:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    for _process, reader in workers:
        reader.join(timeout=2)


def detect_pending(
    state: dict[str, Any],
    *,
    include_paths: bool,
    include_fortress_walls: bool,
    named_icons: bool,
    keys: Iterable[str] | None = None,
    force: bool = False,
    max_workers: int = BOOTSTRAP_DEFAULT_WORKERS,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[int, int]:
    """Run selected detections in isolated processes and apply results as each finishes.

    Forced runs require explicit keys so a caller cannot accidentally replace every annotation in the dataset.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    selected = set(keys) if keys is not None else None
    if force and selected is None:
        raise ValueError("Forced detection requires explicit image keys")
    pending = deque(
        (key, item)
        for key, item in state.get("images", {}).items()
        if (selected is None or key in selected) and (force or not item.get("detected"))
    )
    total = len(pending)
    completed = 0
    errors = 0
    state["settings"] = {
        "include_paths": include_paths,
        "include_fortress_walls": include_fortress_walls,
        "named_icons": named_icons,
    }

    def finish(item: dict[str, Any], result: dict[str, Any] | None, error: str | None) -> None:
        nonlocal completed, errors
        if error is not None:
            if force and item.get("detected"):
                item["error"] = f"Rerun failed; kept previous detections. {error}"
            else:
                item.update({"detected": False, "error": error})
            errors += 1
        else:
            assert result is not None
            item.update(result)
            # A new revision remounts the editor, so it shows these detections instead of autosaving old boxes.
            item["edit_version"] = int(item.get("edit_version", 0)) + 1
            if force:
                item["reviewed"] = False
            completed += 1
        if progress:
            progress(completed + errors, total, str(item["path"]))

    def fail_remaining(message: str) -> None:
        while pending:
            _key, item = pending.popleft()
            finish(item, None, message)

    output: queue.Queue[tuple[subprocess.Popen[str], str | None]] = queue.Queue()
    workers: list[tuple[subprocess.Popen[str], threading.Thread]] = []
    started_workers: list[tuple[subprocess.Popen[str], threading.Thread]] = []
    active: dict[subprocess.Popen[str], tuple[str, dict[str, Any]]] = {}
    try:
        worker_count = min(max_workers, total)
        opencv_threads = max(1, (os.cpu_count() or 1) // worker_count) if worker_count else 1
        for _ in range(worker_count):
            try:
                worker = _start_detection_worker(output, opencv_threads)
            except OSError as exc:
                raise RuntimeError(f"Could not start a dataset detection worker: {exc}") from exc
            workers.append(worker)
            started_workers.append(worker)

        def dispatch(process: subprocess.Popen[str]) -> None:
            if not pending or process.poll() is not None:
                return
            key, item = pending.popleft()
            if process.stdin is None:
                finish(item, None, "Detection worker input was unavailable.")
                return
            active[process] = (key, item)
            request = {
                "key": key,
                "path": item["path"],
                "include_paths": include_paths,
                "include_fortress_walls": include_fortress_walls,
                "named_icons": named_icons,
            }
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except OSError as exc:
                active.pop(process, None)
                finish(item, None, f"Could not send screenshot to detection worker: {exc}")

        for process, _reader in workers:
            dispatch(process)

        while active or pending:
            if not workers:
                fail_remaining("All detection workers stopped before this screenshot was processed.")
                break
            try:
                process, line = output.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                workers = [worker for worker in workers if worker[0] is not process]
                record = active.pop(process, None)
                if record is not None:
                    _key, item = record
                    finish(item, None, f"Detection worker exited unexpectedly (code {process.poll()}).")
                if not workers:
                    fail_remaining("All detection workers stopped before this screenshot was processed.")
                continue
            record = active.pop(process, None)
            if record is None:
                continue
            key, item = record
            try:
                message = json.loads(line)
                if message.get("key") != key:
                    raise ValueError(f"worker returned unexpected image key {message.get('key')!r}")
                if message.get("error"):
                    finish(item, None, str(message["error"]))
                elif isinstance(message.get("result"), dict):
                    finish(item, message["result"], None)
                else:
                    raise ValueError("worker returned neither a result nor an error")
            except (json.JSONDecodeError, AttributeError, ValueError) as exc:
                finish(item, None, f"Invalid detection worker response: {exc}")
            dispatch(process)
    finally:
        _stop_detection_workers(started_workers)
    return completed, errors


def _annotation_for_export(item: dict[str, Any], label_ids: dict[str, int]) -> dict[str, Any] | None:
    """Validate one manually editable annotation for export."""
    label = str(item.get("label", "")).strip()
    if label not in label_ids:
        return None
    try:
        x, y, width, height = (float(value) for value in item["bbox"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {
        "category_id": label_ids[label],
        "bbox": [round(x, 2), round(y, 2), round(width, 2), round(height, 2)],
        "area": round(width * height, 2),
        "iscrowd": 0,
        "label": label,
        "source": item.get("source", "manual"),
    }


def _labels_for_state(state: dict[str, Any]) -> list[str]:
    """Return core labels plus all labels currently present in reviewed state."""
    labels = list(BOOTSTRAP_CORE_LABELS)
    if state.get("settings", {}).get("named_icons"):
        labels.remove("icon")
    for image in state.get("images", {}).values():
        for annotation in image.get("annotations", []):
            label = str(annotation.get("label", ""))
            if label and label not in labels:
                labels.append(label)
    return labels


def export_dataset(state: dict[str, Any], output_dir: Path, *, reviewed_only: bool = True) -> dict[str, Any]:
    """Export reviewed annotations as COCO JSON and a project-native RF-DETR manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = _labels_for_state(state)
    label_ids = {label: index for index, label in enumerate(labels)}
    image_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    image_id = annotation_id = 0
    skipped_annotations = 0
    for key, item in state.get("images", {}).items():
        if reviewed_only and not item.get("reviewed", False):
            continue
        path = Path(item["path"])
        if not path.is_file():
            continue
        width, height = int(item.get("width", 0)), int(item.get("height", 0))
        if width <= 0 or height <= 0:
            loaded = _read_raw_image(path)
            if loaded is None:
                continue
            width, height = loaded[0].shape[1], loaded[0].shape[0]
        image_rows.append(
            {
                "id": image_id,
                "file_name": str(path),
                "width": width,
                "height": height,
                "source_key": key,
                "reviewed": bool(item.get("reviewed", False)),
            }
        )
        objects = []
        for annotation in item.get("annotations", []):
            exported = _annotation_for_export(annotation, label_ids)
            if exported is None:
                skipped_annotations += 1
                continue
            annotation_rows.append({"id": annotation_id, "image_id": image_id, **exported})
            objects.append(
                {
                    "label": exported["label"],
                    "category_id": exported["category_id"],
                    "bbox": exported["bbox"],
                    "area": exported["area"],
                    "iscrowd": 0,
                    "source": exported["source"],
                }
            )
            annotation_id += 1
        manifest_rows.append(
            {
                "image_id": image_id,
                "path": str(path),
                "source": item.get("source", relative_source(path)),
                "source_type": "bootstrap_reviewed" if item.get("reviewed") else "bootstrap_unreviewed",
                "source_group": Path(item.get("source", path.name)).parts[0] if item.get("source") else "bootstrap",
                "width": width,
                "height": height,
                "reviewed": bool(item.get("reviewed", False)),
                "annotations": objects,
            }
        )
        image_id += 1

    categories = [{"id": index, "name": label, "supercategory": "atlas"} for label, index in label_ids.items()]
    coco = {
        "info": {
            "description": "The Grand Project RF-DETR bootstrap dataset",
            "version": str(BOOTSTRAP_SCHEMA_VERSION),
        },
        "licenses": [],
        "images": image_rows,
        "annotations": annotation_rows,
        "categories": categories,
    }
    manifest = {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "format": "the-grand-project-rf-detr-manifest",
        "reviewed_only": reviewed_only,
        "labels": {str(index): label for label, index in label_ids.items()},
        "images": manifest_rows,
    }
    write_json_atomic(output_dir / BOOTSTRAP_COCO_FILE, coco)
    write_json_atomic(output_dir / BOOTSTRAP_MANIFEST_FILE, manifest)
    write_json_atomic(output_dir / "labels.json", manifest["labels"])
    return {
        "images": len(image_rows),
        "annotations": len(annotation_rows),
        "classes": len(labels),
        "skipped_annotations": skipped_annotations,
        "coco_path": output_dir / BOOTSTRAP_COCO_FILE,
        "manifest_path": output_dir / BOOTSTRAP_MANIFEST_FILE,
    }


def load_source_image(path: Path) -> np.ndarray | None:
    """Load the original-size BGR image for interactive annotation."""
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def editor_image_url(path: Path) -> str | None:
    """Return a JPEG data URL of the unmodified screenshot at source resolution for the editor to display.

    Boxes are never drawn into it: the editor shows them as separate page elements over this picture.
    """
    image = load_source_image(path)
    if image is None:
        return None
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, BOOTSTRAP_EDITOR_JPEG_QUALITY])
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _css_color(bgr: tuple[int, int, int]) -> str:
    blue, green, red = bgr
    return f"#{red:02x}{green:02x}{blue:02x}"


def _hashed_color(label: str) -> str:
    """A stable, readable colour for labels without a fixed one (named icons, custom labels)."""
    hue = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:4], 16) % 360 / 360
    red, green, blue = colorsys.hls_to_rgb(hue, 0.62, 0.75)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def label_palette(labels: Iterable[str]) -> list[dict[str, str]]:
    """Give each editor label a colour and, for the first ten, a number hotkey."""
    fixed = {
        label: _css_color(color) for label, color in zip(BOOTSTRAP_CORE_LABELS, BOOTSTRAP_LABEL_COLORS, strict=True)
    }
    fixed.update({label: _css_color(color) for label, color in BOOTSTRAP_EXTRA_LABEL_COLORS.items()})
    palette = []
    for index, label in enumerate(labels):
        hotkey = BOOTSTRAP_LABEL_HOTKEYS[index] if index < len(BOOTSTRAP_LABEL_HOTKEYS) else ""
        palette.append({"name": label, "color": fixed.get(label) or _hashed_color(label), "hotkey": hotkey})
    return palette


def ensure_annotation_ids(item: dict[str, Any]) -> bool:
    """Give every annotation of a screenshot a stable, unique ``id``; return whether any was added.

    The editor refers to boxes by these ids, so an edit maps back to the right annotation however earlier
    autosaves reordered the saved list. Export ignores them.
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


def editor_boxes(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Saved annotations as editor boxes, keyed by their stable ``id`` (see ``ensure_annotation_ids``)."""
    boxes = []
    for annotation in annotations:
        try:
            x, y, width, height = (float(value) for value in annotation["bbox"])
        except (KeyError, TypeError, ValueError):
            continue
        boxes.append(
            {
                "id": str(annotation.get("id", "")),
                "label": str(annotation.get("label", "")),
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "score": annotation.get("score"),
                "source": annotation.get("source", "classical"),
            }
        )
    return boxes


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
        try:
            x, y, box_width, box_height = (float(box[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        label = str(box.get("label", "")).strip()
        if not label:
            continue
        left, top = max(0.0, x), max(0.0, y)
        right, bottom = min(float(width), x + box_width), min(float(height), y + box_height)
        if right - left < 1 or bottom - top < 1:
            continue
        bbox = [round(left, 2), round(top, 2), round(right - left, 2), round(bottom - top, 2)]
        box_id = str(box.get("id") or "")
        fresh_id = bool(box_id) and box_id not in used
        candidate = by_id.get(box_id) if fresh_id else None
        if fresh_id:
            used.add(box_id)
        if candidate is not None:
            old_bbox = candidate.get("bbox", [])
            if (
                str(candidate.get("label", "")) == label
                and len(old_bbox) == 4
                and all(
                    abs(float(old) - new) <= BOOTSTRAP_EDITOR_UNCHANGED_PX
                    for old, new in zip(old_bbox, bbox, strict=True)
                )
            ):
                annotations.append(copy.deepcopy(candidate))
                continue
        annotation: dict[str, Any] = {
            "label": label,
            "bbox": bbox,
            "area": round(bbox[2] * bbox[3], 2),
            "iscrowd": 0,
            "source": "manual",
        }
        if fresh_id:
            annotation["id"] = box_id
        annotations.append(annotation)
    return annotations


def annotations_changed(saved: list[dict[str, Any]], edited: list[dict[str, Any]]) -> bool:
    """Whether the edited annotations differ from the saved ones (so autosave writes only real changes)."""

    def key(annotations: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [
            (
                annotation.get("id"),
                annotation.get("label"),
                tuple(annotation.get("bbox", ())),
                annotation.get("source"),
                annotation.get("score"),
            )
            for annotation in annotations
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


def neighbour_key(keys: list[str], current: str, step: int) -> str | None:
    """The screenshot ``step`` places from ``current`` in the queue, or None past either end."""
    if not keys:
        return None
    if current not in keys:
        return keys[0]
    index = keys.index(current) + step
    return keys[index] if 0 <= index < len(keys) else None
