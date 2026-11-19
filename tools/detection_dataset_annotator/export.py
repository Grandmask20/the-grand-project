"""Export of the review state: COCO ``annotations.json``, the project-native ``manifest.json`` and ``labels.json``.

``grand_project.detect.rf_detr.load_annotator_manifest`` reads the manifest (``make prepare_rf_detr_data
RF_DETR_ANNOTATOR_MANIFEST=...``). Both files point at the original screenshots; nothing is copied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import constants as K
from .detection import decode_image
from .state import DetectionOptions, label_names, relative_source, write_json_atomic


@dataclass(frozen=True)
class ExportResult:
    """What ``export_dataset`` wrote."""

    images: int
    annotations: int
    classes: int
    skipped_annotations: int
    """Annotations left out: unknown label or invalid box."""
    coco_path: Path
    manifest_path: Path


def _exported_annotation(annotation: dict[str, Any], label_ids: dict[str, int]) -> dict[str, Any] | None:
    """One annotation as exported, or None when its label is unknown or its box invalid."""
    label = str(annotation.get("label", "")).strip()
    if label not in label_ids:
        return None
    try:
        x, y, width, height = (float(value) for value in annotation["bbox"])
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
        "source": annotation.get("source", K.ANNOTATOR_MANUAL_SOURCE),
    }


def _image_size(item: dict[str, Any], path: Path) -> tuple[int, int] | None:
    """The screenshot's (width, height): saved by detection, else read from the file."""
    width, height = int(item.get("width", 0)), int(item.get("height", 0))
    if width > 0 and height > 0:
        return width, height
    image = decode_image(path)
    return None if image is None else (image.shape[1], image.shape[0])


def export_dataset(state: dict[str, Any], output_dir: Path, *, reviewed_only: bool = True) -> ExportResult:
    """Export the (reviewed) annotations as COCO JSON and a project-native RF-DETR manifest.

    Screenshots that no longer exist are left out. Labels are the core labels, with named icons every icon type
    (``label_names``), then every other label in use (derived labels only when used), numbered in that order, so
    the core classes and the icon types keep their ids from one export to the next.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    options = DetectionOptions.from_settings(state.get("settings", {}))
    labels = label_names(state, named_icons=options.named_icons, derived=False)
    label_ids = {label: index for index, label in enumerate(labels)}
    image_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    skipped = 0
    for key, item in state.get("images", {}).items():
        reviewed = bool(item.get("reviewed", False))
        if reviewed_only and not reviewed:
            continue
        path = Path(item["path"])
        size = _image_size(item, path) if path.is_file() else None
        if size is None:
            continue
        width, height = size
        image_id = len(image_rows)
        image_rows.append(
            {
                "id": image_id,
                "file_name": str(path),
                "width": width,
                "height": height,
                "source_key": key,
                "reviewed": reviewed,
            }
        )
        objects = []
        for annotation in item.get("annotations", []):
            exported = _exported_annotation(annotation, label_ids)
            if exported is None:
                skipped += 1
                continue
            annotation_rows.append({"id": len(annotation_rows), "image_id": image_id, **exported})
            objects.append(
                {name: exported[name] for name in ("label", "category_id", "bbox", "area", "iscrowd", "source")}
            )
        source = item.get("source")
        manifest_rows.append(
            {
                "image_id": image_id,
                "path": str(path),
                "source": source or relative_source(path),
                "source_type": "annotator_reviewed" if reviewed else "annotator_unreviewed",
                "source_group": Path(source).parts[0] if source else "annotator",
                "width": width,
                "height": height,
                "reviewed": reviewed,
                "annotations": objects,
            }
        )

    label_map = {str(index): label for label, index in label_ids.items()}
    coco = {
        "info": {
            "description": "The Grand Project RF-DETR detection dataset",
            "version": str(K.ANNOTATOR_SCHEMA_VERSION),
        },
        "licenses": [],
        "images": image_rows,
        "annotations": annotation_rows,
        "categories": [{"id": index, "name": label, "supercategory": "atlas"} for label, index in label_ids.items()],
    }
    manifest = {
        "schema_version": K.ANNOTATOR_SCHEMA_VERSION,
        "format": K.ANNOTATOR_MANIFEST_FORMAT,
        "reviewed_only": reviewed_only,
        "labels": label_map,
        "images": manifest_rows,
    }
    coco_path = output_dir / K.ANNOTATOR_COCO_FILE
    manifest_path = output_dir / K.ANNOTATOR_MANIFEST_FILE
    write_json_atomic(coco_path, coco)
    write_json_atomic(manifest_path, manifest)
    write_json_atomic(output_dir / K.ANNOTATOR_LABELS_FILE, label_map)
    return ExportResult(
        images=len(image_rows),
        annotations=len(annotation_rows),
        classes=len(labels),
        skipped_annotations=skipped,
        coco_path=coco_path,
        manifest_path=manifest_path,
    )
