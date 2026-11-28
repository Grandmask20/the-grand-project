"""Hugging Face dataset preparation for the RF-DETR detector.

Training data comes from one place: the screenshots exported by the dataset annotator
(``tools/detection_dataset_annotator``: ``manifest.json``). Its classes are the labels of ``labels.py`` and each
screenshot carries the train / validation / test split the split ledger keeps (the hand-labelled truth screenshots
are pinned to test, so ``python -m grand_project.detect score`` keeps measuring unseen screenshots).
Reviewed screenshots are the training data. Unreviewed classical boxes are not: they would teach the classical
detector's mistakes, which the model is meant to get past. The one opt-in exception (``truth_seeded``, a bootstrap
round) is a screenshot a hand-labelled biome truth seeded: its city areas and citadels are the truth's.

The model sees native-scale tiles of the screenshots (``rf_detr_tiles.py``): training cuts random tiles each time an
image is drawn (``TileTransform``), so the saved dataset holds whole screenshots and boxes in their own pixels.

This module does not import ``datasets`` or ``transformers`` at import time: the classical detector and its offline
tests work without the optional training stack.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import random
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import constants as K
from . import labels as L
from . import rf_detr_tiles as T


@dataclass(frozen=True)
class Record:
    """One source image and its annotations in source-image pixels."""

    image_id: int
    path: Path
    source: str
    source_type: str
    width: int
    height: int
    annotations: tuple[dict[str, Any], ...]
    sha256: str
    """The SHA-256 of the screenshot's bytes as the export recorded them."""
    split: str = "train"


def _annotation(label: str, raw: dict[str, Any], name_to_id: dict[str, int], manifest_path: Path) -> dict[str, Any]:
    """One manifest box as a record annotation; raises ValueError for an unknown label or an invalid box."""
    if label not in name_to_id:
        raise ValueError(f"Annotator annotation uses unknown label {label!r}: {manifest_path}")
    try:
        bbox = tuple(float(value) for value in raw["bbox"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid annotator bbox in {manifest_path}") from exc
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox) or bbox[2] <= 0 or bbox[3] <= 0:
        raise ValueError(f"Invalid annotator bbox in {manifest_path}: {bbox}")
    try:
        area = float(raw.get("area", bbox[2] * bbox[3]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid annotator area in {manifest_path}") from exc
    if not math.isfinite(area):
        raise ValueError(f"Invalid annotator area in {manifest_path}: {area}")
    return {
        "category_name": label,
        "category_id": name_to_id[label],
        "bbox": bbox,
        "area": area,
        "iscrowd": int(raw.get("iscrowd", 0)),
    }


def load_annotator_manifest(
    manifest_path: Path,
    max_images: int | None = None,
    *,
    truth_seeded: bool = False,
    data: dict[str, Any] | None = None,
) -> tuple[list[Record], dict[str, str]]:
    """Load the screenshots and boxes exported by ``tools.detection_dataset_annotator``.

    The manifest keeps source image paths and ``xywh`` boxes, so nothing is copied. It must give every screenshot its
    split. Only the screenshots it marks reviewed are loaded: an export with "reviewed screenshots only" off also
    holds unreviewed ones, whose boxes are the classical detector's guesses, never training data. With
    ``truth_seeded`` the unreviewed screenshots a biome truth seeded (their ``truth``) are loaded too.

    Args:
        manifest_path: the annotator's ``manifest.json``.
        max_images: keep only this many screenshots (a smoke test), every split kept represented.
        truth_seeded: also the unreviewed screenshots a hand-labelled biome truth seeded (a bootstrap round).
        data: the manifest as the caller already parsed it (one read: what it checked and hashed is what is loaded);
            relative screenshot paths still lie next to ``manifest_path``.

    Returns:
        (the records, id -> class name).

    Raises:
        ValueError: not an annotator manifest, a class the labels do not have (``load_detector`` would refuse the
            model), a screenshot without a split, a bad box.
        FileNotFoundError: no screenshot of the manifest exists.
    """
    manifest_path = Path(manifest_path)
    if data is None:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("format") != K.RF_DETR_MANIFEST_FORMAT:
        raise ValueError(f"Not an annotator RF-DETR manifest: {manifest_path}")
    labels = {str(index): str(name) for index, name in data.get("labels", {}).items()}
    if not labels:
        raise ValueError(f"Annotator manifest has no labels: {manifest_path}")
    exported = [labels[str(index)] for index in range(len(labels))]
    admitted = []
    for item in data.get("images", []):
        seeded = truth_seeded and not item.get("reviewed") and bool(item.get("truth"))
        if item.get("reviewed") or seeded:  # unreviewed classical boxes would teach the classical detector's mistakes
            admitted.append((item, seeded))
    # the classes the admitted screenshots use: a retired label only a left-out screenshot carries is no class
    used = {str(raw.get("label", "")) for item, _seeded in admitted for raw in item.get("annotations", [])}
    unknown = sorted(name for name in exported if not L.known(name) and name in used)
    if unknown:
        # checked before training: a model with these classes would be refused at inference (load_detector)
        raise ValueError(
            f"{manifest_path} has classes the labels do not have ({', '.join(unknown)}): relabel or rerun those "
            "screenshots in the annotator and export again"
        )
    # the manifest's order kept, numbered again without the unknown classes nothing admitted uses
    label_names = [name for name in exported if L.known(name)]
    name_to_id = {name: index for index, name in enumerate(label_names)}
    records: list[Record] = []
    for item, seeded in admitted:
        image_path = Path(str(item.get("path", "")))
        if not image_path.is_absolute():
            image_path = manifest_path.parent / image_path
        if not image_path.is_file():
            continue
        split = str(item.get("split") or "")
        if split not in K.RF_DETR_SPLITS:
            raise ValueError(f"Screenshot {image_path} has no split in {manifest_path}: export it again")
        if not item.get(K.RF_DETR_MANIFEST_SHA):
            raise ValueError(f"Screenshot {image_path} has no SHA-256 in {manifest_path}: export it again")
        annotations = tuple(
            _annotation(str(raw.get("label", "")), raw, name_to_id, manifest_path)
            for raw in item.get("annotations", [])
        )
        records.append(
            Record(
                image_id=int(item.get("image_id", len(records))),
                path=image_path,
                source=str(item.get("source", image_path.name)),
                source_type=K.RF_DETR_TRUTH_SEEDED_SOURCE if seeded else str(item["source_type"]),
                width=int(item["width"]),
                height=int(item["height"]),
                annotations=annotations,
                sha256=str(item[K.RF_DETR_MANIFEST_SHA]),
                split=split,
            )
        )
    if max_images is not None:
        if max_images < 1:
            raise ValueError("max_images must be positive")
        records = _limit(records, max_images)
    if not records:
        raise FileNotFoundError(f"No usable images in annotator manifest: {manifest_path}")
    return records, {str(index): name for index, name in enumerate(label_names)}


def _limit(records: list[Record], count: int) -> list[Record]:
    """At most ``count`` records, taken in turn from each split, so a smoke test still has every split."""
    by_split = {split: [r for r in records if r.split == split] for split in K.RF_DETR_SPLITS}
    out: list[Record] = []
    while len(out) < count and any(by_split.values()):
        for split in K.RF_DETR_SPLITS:
            if by_split[split] and len(out) < count:
                out.append(by_split[split].pop(0))
    return out


def records_by_split(records: list[Record]) -> dict[str, list[Record]]:
    """The records of each split (every split present, maybe empty).

    Raises:
        ValueError: no training or no validation screenshot.
    """
    out = {split: [record for record in records if record.split == split] for split in K.RF_DETR_SPLITS}
    if not out["train"] or not out["validation"]:
        raise ValueError(
            "Need at least one training and one validation screenshot: review more screenshots and export again "
            f"(have {len(out['train'])} train, {len(out['validation'])} validation)"
        )
    return out


def _features(label_names: list[str]):
    """Construct explicit Hugging Face features lazily."""
    from datasets import ClassLabel, Features, Image, Sequence, Value

    return Features(
        {
            "image": Image(),
            "image_id": Value("int64"),
            "source": Value("string"),
            "source_type": Value("string"),
            "width": Value("int32"),
            "height": Value("int32"),
            "objects": {
                "id": Sequence(Value("int64")),
                "area": Sequence(Value("float32")),
                "bbox": Sequence(Sequence(Value("float32"), length=4)),
                "category": Sequence(ClassLabel(names=label_names)),
                "iscrowd": Sequence(Value("int8")),
            },
        }
    )


def _rows(records: list[Record], check_bytes: Callable[[Record, str], None] | None = None) -> Iterator[dict[str, Any]]:
    """The records in the Hugging Face object-detection schema, one at a time (a split's screenshots are never all in
    memory), each screenshot's bytes read once and embedded (training never reads the file again: what was checked is
    what it trains on), after ``check_bytes(record, their SHA-256)`` (it raises to stop the build)."""
    for record in records:
        data = Path(record.path).read_bytes()
        if check_bytes is not None:
            check_bytes(record, hashlib.sha256(data).hexdigest())
        yield (
            {
                # no path: given an existing file, datasets keeps only the path and reads the file again when saving
                "image": {"bytes": data, "path": None},
                "image_id": record.image_id,
                "source": record.source,
                "source_type": record.source_type,
                "width": record.width,
                "height": record.height,
                "objects": {
                    "id": list(range(len(record.annotations))),
                    "area": [float(annotation["area"]) for annotation in record.annotations],
                    "bbox": [list(map(float, annotation["bbox"])) for annotation in record.annotations],
                    "category": [int(annotation["category_id"]) for annotation in record.annotations],
                    "iscrowd": [int(annotation["iscrowd"]) for annotation in record.annotations],
                },
            }
        )


def _write_split(records: list[Record], features, path: Path, check_bytes) -> Any:
    """One split written to an Arrow file ``RF_DETR_DATASET_WRITE_BATCH`` screenshots at a time, and read back
    memory-mapped: the bytes ``check_bytes`` saw go into the file as they are."""
    from datasets import Dataset
    from datasets.arrow_writer import ArrowWriter

    with ArrowWriter(features=features, path=str(path), writer_batch_size=K.RF_DETR_DATASET_WRITE_BATCH) as writer:
        for row in _rows(records, check_bytes):
            writer.write(features.encode_example(row))
        writer.finalize()
    return Dataset.from_file(str(path))


def build_dataset(
    records: list[Record],
    *,
    label_map: dict[str, str],
    output_dir: Path,
    provenance: dict[str, Any] | None = None,
    check_bytes: Callable[[Record, str], None] | None = None,
) -> Any:
    """Create and save a ``DatasetDict`` (train, validation, test, as the records' splits say).

    The folder holds the screenshots' bytes (``_rows``; ``check_bytes`` sees each one's SHA-256 first),
    ``labels.json`` and ``metadata.json``: the screenshots per split and kind (reviewed, truth-seeded), the tile, and
    ``provenance`` (the manifest's and the ledger's SHA-256: which data a model saw). The labels and metadata are
    written last, so a build cut off leaves no folder to reuse (``train_rf_detr`` builds beside the dataset in use and
    swaps the new one in).

    Raises:
        ValueError: no training or no validation screenshot.
        FileExistsError: ``output_dir`` exists and is not empty.
    """
    from datasets import Dataset, DatasetDict

    splits = records_by_split(records)
    features = _features([label_map[str(index)] for index in range(len(label_map))])
    folder = Path(output_dir)
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError(f"dataset output directory is not empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    scratch = folder / "rows"
    scratch.mkdir()
    # an empty split (no test screenshot yet) from empty columns: no file to match the features
    dataset = DatasetDict(
        {
            split: _write_split(chosen, features, scratch / f"{split}.arrow", check_bytes)
            if chosen
            else Dataset.from_dict({name: [] for name in features}, features=features)
            for split, chosen in splits.items()
        }
    )
    # an empty split (no test screenshot yet) is not saved: datasets cannot load an empty one back (load_dataset)
    DatasetDict({split: rows for split, rows in dataset.items() if len(rows)}).save_to_disk(str(folder))
    del dataset
    gc.collect()  # the scratch files' maps closed (Windows keeps a mapped file)
    shutil.rmtree(scratch)
    (folder / "labels.json").write_text(json.dumps(label_map, indent=2) + "\n", encoding="utf-8")
    kinds: dict[str, dict[str, int]] = {}
    for split, chosen in splits.items():
        for record in chosen:
            kinds.setdefault(split, {}).setdefault(record.source_type, 0)
            kinds[split][record.source_type] += 1
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "format": "huggingface-datasets-object-detection",
                **{f"{split}_images": len(chosen) for split, chosen in splits.items()},
                "kinds": kinds,
                "labels": label_map,
                "tile": K.RF_DETR_TILE,
                **(provenance or {}),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return load_dataset(folder)


def load_dataset(folder: Path) -> Any:
    """A dataset ``build_dataset`` saved, every split there (one saved without screenshots comes back empty, with the
    others' features)."""
    from datasets import Dataset, DatasetDict, load_from_disk

    saved = load_from_disk(str(folder))
    features = next(iter(saved.values())).features
    empty = Dataset.from_dict({name: [] for name in features}, features=features)
    return DatasetDict({split: saved.get(split, empty) for split in K.RF_DETR_SPLITS})


class TileTransform:
    """The batched training transform: each screenshot becomes one native-scale tile, processed for the model.

    A random tile every time an image is drawn (``rf_detr_tiles.random_tile``: scale jitter, tiles centred on rare
    classes, render-scale blur; no flips: the atlas is never mirrored; evaluation runs the whole tiled inference). A
    module-level class, not a closure, so a dataset carrying it can be pickled into DataLoader worker processes
    (spawn, on Windows and macOS); each worker draws its own random tiles.
    """

    def __init__(self, processor, *, seed: int = 1337, rare: frozenset[int] = frozenset()) -> None:
        self.processor = processor
        self.seed = seed
        self.rare = set(rare)
        self._rng: random.Random | None = None

    def _random(self) -> random.Random:
        """This worker's random source: in a DataLoader worker its seed (torch gives each worker a new one every
        epoch, drawn from ``torch.manual_seed``: workers and epochs draw different tiles), else ``seed``."""
        if self._rng is None:
            try:
                from torch.utils.data import get_worker_info

                info = get_worker_info()
            except ImportError:  # pragma: no cover - the transform is only used with torch installed
                info = None
            self._rng = random.Random(info.seed if info is not None else self.seed)
        return self._rng

    def tile(self, image, objects: dict[str, Any]) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """One screenshot's tile (RGB) and its boxes as COCO annotations (category_id, bbox, area, iscrowd)."""
        array = np.asarray(image.convert("RGB"))
        array, boxes = T.prepare(array, objects.get("bbox", ()), rgb=True)
        categories = [int(c) for c in objects.get("category", ())]
        tile, keep, kept = T.random_tile(array, boxes, categories, self._random(), rare=self.rare)
        crowd = list(objects.get("iscrowd", [0] * len(categories)))
        annotations = [
            {"category_id": categories[i], "bbox": box, "area": float(box[2] * box[3]), "iscrowd": int(crowd[i])}
            for i, box in zip(keep, kept, strict=True)
        ]
        return tile, annotations

    def __call__(self, examples: dict[str, list[Any]]) -> dict[str, Any]:
        images = []
        annotations = []
        for image, image_id, objects in zip(examples["image"], examples["image_id"], examples["objects"], strict=True):
            tile, boxes = self.tile(image, objects)
            images.append(tile)
            annotations.append({"image_id": image_id, "annotations": [{"image_id": image_id, **box} for box in boxes]})
        return self.processor(images=images, annotations=annotations, return_tensors="pt")


def tile_transform(processor, *, seed: int = 1337, rare: frozenset[int] = frozenset()) -> TileTransform:
    """Return the batched training tile transform (``TileTransform``)."""
    return TileTransform(processor, seed=seed, rare=rare)


__all__ = [
    "Record",
    "load_dataset",
    "TileTransform",
    "build_dataset",
    "load_annotator_manifest",
    "records_by_split",
    "tile_transform",
]
