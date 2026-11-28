"""Export of the review store: COCO ``annotations.json``, the project-native ``manifest.json`` and ``labels.json``.

``grand_project.detect.rf_detr.load_annotator_manifest`` reads the manifest (``make prepare_rf_detr_data
RF_DETR_ANNOTATOR_MANIFEST=...``). Both files point at the original screenshots; nothing is copied.

Stored labels become detector classes (``labels.export_class``: icon types the detector does not keep become
``icon``, the icon types the dataset leaves out are not exported), numbered by ``labels.dataset_classes``. Labels
outside the dataset's vocabulary (a reviewer's own, or one the labels no longer have: rerun those screenshots) are
exported as classes of their own and reported (``ExportResult.unknown``). Every screenshot in the store, reviewed or
not, gets its train / validation / test split at an export (``split_ledger.settle_splits``: the ledger's, else drawn
by spatial blocks), which the store and the ledger keep: the splits are settled before the review, and an exported
screenshot carries its split, and the biome truth that seeded it (``ANNOTATOR_TRUTH_MARK``) if one did.

    python -m tools.detection_dataset_annotator.export [--output-dir D] [--unreviewed]
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from grand_project.detect.labels import dataset_classes, export_class, known

from . import constants as K
from .detection import decode_image
from .splits import split_report
from .state import changed_since_detection, relative_source, write_json_atomic

if TYPE_CHECKING:
    from .store import ReviewStore


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
    unknown: dict[str, int] | None = None
    """Exported boxes per label outside the dataset's vocabulary (``labels.known``)."""
    splits: dict[str, int] | None = None
    """Exported screenshots per split."""
    report: str = ""
    """The split balance report (``splits.split_report``)."""
    ledger_added: int = 0
    """Screenshots the split ledger gained (``split_ledger.settle_splits``)."""
    changed: tuple[str, ...] = ()
    """Screenshots left out: their file is not the one their boxes were detected on (rerun their detection)."""


def _export_bbox(annotation: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """An annotation's box as exported (x, y, w, h rounded to 0.01 px), or None when it is no box to export."""
    try:
        values = [float(value) for value in annotation["bbox"]]
        x, y, width, height = values
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None  # json would write NaN / Infinity, which is not JSON
    x, y, width, height = (round(value, 2) for value in values)
    if width <= 0 or height <= 0:  # after rounding: a box this thin would be exported as zero
        return None
    return x, y, width, height


def _exported_annotation(annotation: dict[str, Any], label_ids: dict[str, int]) -> dict[str, Any] | None:
    """One annotation as exported (under its detector class), or None when its label is unknown, retired or its box
    invalid."""
    label = export_class(str(annotation.get("label", "")).strip())
    bbox = _export_bbox(annotation)
    if label not in label_ids or bbox is None:
        return None
    x, y, width, height = bbox
    return {
        "category_id": label_ids[label],
        "bbox": [x, y, width, height],
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


def _source_group(path: Path, roots: Iterable[str]) -> str:
    """The screenshot's source for a split by source: the (most specific) discovery root it was found under, else its
    folder, so screenshots of one source stay together and different roots can be told apart."""
    resolved = path.resolve()
    under = []
    for root in roots:
        candidate = Path(root).resolve()
        if candidate != resolved and resolved.is_relative_to(candidate):
            under.append(candidate)
    return relative_source(max(under, key=lambda root: len(root.parts), default=resolved.parent))


def _publish(output_dir: Path, files: dict[str, Any]) -> None:
    """Write the export files as one generation: all of them are written to a staging folder first, then moved into
    place; if a move fails, the previous files are put back, so a reader never finds a mix of two exports."""
    staging = Path(tempfile.mkdtemp(prefix=".export-new-", dir=output_dir))
    backup = Path(tempfile.mkdtemp(prefix=".export-old-", dir=output_dir))
    keep_backup = False
    try:
        for name, value in files.items():
            write_json_atomic(staging / name, value)
        for name in files:
            if (output_dir / name).is_file():
                shutil.copy2(output_dir / name, backup / name)
        placed: list[str] = []
        try:
            for name in files:
                os.replace(staging / name, output_dir / name)
                placed.append(name)
        except BaseException:
            keep_backup = True  # until every previous file is back in place
            for name in placed:
                if (backup / name).is_file():
                    os.replace(backup / name, output_dir / name)
                else:
                    (output_dir / name).unlink()
            keep_backup = False
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if not keep_backup:
            with contextlib.suppress(OSError):
                shutil.rmtree(backup)


def export_dataset(store: ReviewStore, output_dir: Path, *, reviewed_only: bool = True) -> ExportResult:
    """Export the (reviewed) annotations as COCO JSON and a project-native RF-DETR manifest.

    Screenshots that no longer exist are left out. Classes are ``labels.dataset_classes`` of the labels the exported
    screenshots use, numbered in that order. Every screenshot of the store without a split gets one
    (``split_ledger.settle_splits``, kept in the store and the ledger); the manifest carries each exported screenshot's
    split.

    Raises:
        SplitConflict: The ledger, the store or a pinned root disagree on splits; nothing is exported.
    """
    # imported here: the ledger is also a command (python -m), which the package's import must not load first
    from .split_ledger import settle_splits

    output_dir.mkdir(parents=True, exist_ok=True)
    # One read for the splits, the classes and the boxes: a box saved meanwhile cannot have a label the classes miss.
    every = list(store.items())
    settled = settle_splits(store, every)
    split_of = settled.split_of
    # the screenshots exported, chosen before the classes: one left out gives the manifest no class of its own
    changed: list[str] = []
    chosen: list[tuple[str, dict[str, Any], Path, tuple[int, int]]] = []
    for key, item in every:
        reviewed = bool(item.get("reviewed", False))
        if reviewed_only and not reviewed:
            continue
        if not (reviewed or item.get("detected")):
            continue  # never processed: its empty box list is not a labelling
        path = Path(item["path"])  # as the store keeps it (absolute), the file the split ledger hashed
        if key not in split_of:
            continue  # its file could not be read
        if changed_since_detection(item, settled.digests.get(key)):
            changed.append(str(item.get("source") or relative_source(path)))  # its boxes frame another picture
            continue
        size = _image_size(item, path) if path.is_file() else None
        if size is None:
            continue
        chosen.append((key, item, path, size))
    # the classes of the boxes exported: one left out (no box to export) gives the manifest no class of its own
    labels = dataset_classes(
        str(annotation.get("label", "")).strip()
        for _key, item, _path, _size in chosen
        for annotation in item.get("annotations", [])
        if _export_bbox(annotation) is not None
    )
    label_ids = {label: index for index, label in enumerate(labels)}
    image_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    skipped = 0
    roots = store.input_roots()
    for key, item, path, (width, height) in chosen:
        reviewed = bool(item.get("reviewed", False))
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
                "key": key,
                "path": str(path),
                "source": source or relative_source(path),
                "source_type": "annotator_reviewed" if reviewed else "annotator_unreviewed",
                "source_group": _source_group(path, roots),
                "width": width,
                "height": height,
                "reviewed": reviewed,
                # the bytes exported (the ones its boxes were detected on): tools reading the manifest later check the
                # file still is them (simulate_loop)
                K.ANNOTATOR_DETECTED_SHA: settled.digests[key],
                **({K.ANNOTATOR_TRUTH_MARK: item[K.ANNOTATOR_TRUTH_MARK]} if item.get(K.ANNOTATOR_TRUTH_MARK) else {}),
                **(
                    {K.ANNOTATOR_TRUTH_DIGEST: item[K.ANNOTATOR_TRUTH_DIGEST]}
                    if item.get(K.ANNOTATOR_TRUTH_MARK) and item.get(K.ANNOTATOR_TRUTH_DIGEST)
                    else {}
                ),
                "annotations": objects,
            }
        )

    for row in manifest_rows:
        row["split"] = split_of[row["key"]]
    for row in image_rows:
        row["split"] = split_of[row["source_key"]]
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
    _publish(
        output_dir,
        {K.ANNOTATOR_COCO_FILE: coco, K.ANNOTATOR_MANIFEST_FILE: manifest, K.ANNOTATOR_LABELS_FILE: label_map},
    )
    counts = {row["key"]: _class_counts(row) for row in manifest_rows}
    return ExportResult(
        images=len(image_rows),
        annotations=len(annotation_rows),
        classes=len(labels),
        skipped_annotations=skipped,
        coco_path=coco_path,
        manifest_path=manifest_path,
        unknown=_unknown(manifest_rows),
        splits={split: sum(1 for row in manifest_rows if row["split"] == split) for split in K.ANNOTATOR_SPLITS},
        report=split_report(counts, split_of, settled.blocks) if counts else "",
        ledger_added=settled.added,
        changed=tuple(changed),
    )


def _unknown(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Exported boxes per label outside the dataset's vocabulary."""
    out: dict[str, int] = {}
    for row in rows:
        for annotation in row["annotations"]:
            if not known(annotation["label"]):
                out[annotation["label"]] = out.get(annotation["label"], 0) + 1
    return out


def _class_counts(row: dict[str, Any]) -> dict[str, int]:
    """A manifest screenshot's exported boxes per class."""
    out: dict[str, int] = {}
    for annotation in row["annotations"]:
        out[annotation["label"]] = out.get(annotation["label"], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    """Export the review store as the page's Export button does, and print what was written."""
    from .state import resolve_path
    from .store import ReviewStore

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument(
        "--unreviewed",
        action="store_true",
        help="export unreviewed screenshots too (truth-seeded training and model pre-labels need them)",
    )
    args = parser.parse_args(argv)
    output_dir = resolve_path(args.output_dir)
    if not (output_dir / K.ANNOTATOR_STORE_FILE).is_file():  # opening it would create an empty store and export it
        parser.error(f"no annotator store at {output_dir / K.ANNOTATOR_STORE_FILE}")
    with ReviewStore.open(output_dir / K.ANNOTATOR_STORE_FILE) as store:
        result = export_dataset(store, output_dir, reviewed_only=not args.unreviewed)
    print(
        f"{result.images} screenshots, {result.annotations} boxes, {result.classes} classes -> {result.manifest_path}"
    )
    print(f"splits: {result.splits}; ledger gained {result.ledger_added} screenshots")
    if result.skipped_annotations:
        print(f"skipped {result.skipped_annotations} invalid annotations or icons the dataset leaves out")
    if result.changed:
        print(f"left out, changed since their detection (rerun their detection): {', '.join(result.changed)}")
    if result.unknown:
        print(f"labels outside the dataset's (rerun those screenshots): {result.unknown}")
    if result.report:
        print(result.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
