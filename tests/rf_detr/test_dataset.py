"""Offline checks for the RF-DETR dataset (grand_project/detect/rf_detr.py): the annotator's manifest, its splits,
the tile transform, the saved dataset."""

import json
import math
import pickle
import random
from pathlib import Path

import pytest
from PIL import Image

from grand_project.detect import constants as K
from grand_project.detect.rf_detr import (
    Record,
    load_annotator_manifest,
    records_by_split,
    slug,
    tile_transform,
)


def _manifest(tmp_path: Path, images: list[dict], **fields) -> Path:
    """An annotator manifest (``fields`` override its keys)."""
    manifest = tmp_path / "manifest.json"
    data = {
        "format": "the-grand-project-rf-detr-manifest",
        "labels": {"0": "map_node_grass", "1": "icon"},
        "images": images,
        **fields,
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest


def _image(tmp_path: Path, name: str = "shot.png", split: str = "train", **fields) -> dict:
    path = tmp_path / name
    path.write_bytes(b"placeholder")
    return {"path": str(path), "width": 1920, "height": 1080, "split": split, "reviewed": True, "annotations": [],
            **fields}  # fmt: skip


def test_category_slug_is_stable_and_safe() -> None:
    assert slug("Map Boss Special") == "map_boss_special"
    assert slug("!!!") == "unknown"


def test_annotator_manifest_loads_paths_labels_and_splits(tmp_path: Path) -> None:
    shot = _image(
        tmp_path,
        split="validation",
        image_id=7,
        annotations=[{"label": "icon", "bbox": [10, 20, 34, 34], "source": "manual"}],
    )
    records, labels = load_annotator_manifest(_manifest(tmp_path, [shot]))
    assert labels == {"0": "map_node_grass", "1": "icon"}
    assert [(r.image_id, r.split) for r in records] == [(7, "validation")]
    assert records[0].annotations[0]["category_id"] == 1
    assert records[0].annotations[0]["bbox"] == (10.0, 20.0, 34.0, 34.0)


def test_annotator_manifest_refuses_a_missing_split(tmp_path: Path) -> None:
    """A model never learns from screenshots the annotator gave no split (their test set could leak into training)."""
    with pytest.raises(ValueError, match="no split"):
        load_annotator_manifest(_manifest(tmp_path, [_image(tmp_path, split="")]))


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param({"bbox": [math.nan, 20, 34, 34]}, id="nan x"),
        pytest.param({"bbox": [10, 20, math.inf, 34]}, id="infinite width"),
        pytest.param({"bbox": [10, 20, 34, 34], "area": math.nan}, id="nan area"),
        pytest.param({"bbox": [10, 20, 34, 34], "area": "big"}, id="area not a number"),
    ],
)
def test_annotator_manifest_refuses_non_finite_geometry(tmp_path: Path, annotation: dict) -> None:
    shot = _image(tmp_path, annotations=[{"label": "icon", **annotation}])
    with pytest.raises(ValueError, match="Invalid annotator"):
        load_annotator_manifest(_manifest(tmp_path, [shot]))


def test_max_images_keeps_every_split(tmp_path: Path) -> None:
    """A smoke test with a few screenshots still has a training and a validation screenshot."""
    shots = [_image(tmp_path, f"t{i}.png", "train") for i in range(5)]
    shots += [_image(tmp_path, "v.png", "validation"), _image(tmp_path, "x.png", "test")]
    records, _labels = load_annotator_manifest(_manifest(tmp_path, shots), max_images=3)
    assert sorted(r.split for r in records) == ["test", "train", "validation"]


def test_unreviewed_screenshots_are_no_training_data(tmp_path: Path) -> None:
    """An export with "reviewed screenshots only" off marks its unreviewed screenshots: their classical boxes are left
    out, the reviewed ones keep their splits (before max_images picks, so a smoke test never takes one either)."""
    shots = [
        _image(tmp_path, "a.png", "train"),
        _image(tmp_path, "b.png", "train", reviewed=False),
        _image(tmp_path, "c.png", "validation", reviewed=False),
        _image(tmp_path, "d.png", "validation"),
    ]
    records, _labels = load_annotator_manifest(_manifest(tmp_path, shots))
    assert [(r.path.name, r.split) for r in records] == [("a.png", "train"), ("d.png", "validation")]
    records, _labels = load_annotator_manifest(_manifest(tmp_path, shots), max_images=2)
    assert [r.path.name for r in records] == ["a.png", "d.png"]


def test_truth_seeded_screenshots_join_only_when_asked(tmp_path: Path) -> None:
    """A bootstrap round (--truth-seeded) also trains on the unreviewed screenshots a biome truth seeded (their
    ``truth`` mark), never on other unreviewed ones; by default only reviewed screenshots are training data."""
    truth = "atlas_test_data/fr-atlas/truth.json"
    shots = [
        _image(tmp_path, "a.png", "train"),
        _image(tmp_path, "b.png", "train", reviewed=False, truth=truth),
        _image(tmp_path, "c.png", "train", reviewed=False),
        _image(tmp_path, "d.png", "validation", reviewed=False, truth=truth),
    ]
    records, _labels = load_annotator_manifest(_manifest(tmp_path, shots))
    assert [r.path.name for r in records] == ["a.png"]
    records, _labels = load_annotator_manifest(_manifest(tmp_path, shots), truth_seeded=True)
    assert [(r.path.name, r.source_type) for r in records] == [
        ("a.png", "annotator_reviewed"),
        ("b.png", K.RF_DETR_TRUTH_SEEDED_SOURCE),
        ("d.png", K.RF_DETR_TRUTH_SEEDED_SOURCE),
    ]


def test_records_by_split_needs_training_and_validation() -> None:
    def record(split: str) -> Record:
        return Record(0, Path("a.png"), "a", "annotator_reviewed", "g", 1920, 1080, (), split)

    assert {k: len(v) for k, v in records_by_split([record("train"), record("validation")]).items()} == {
        "train": 1,
        "validation": 1,
        "test": 0,
    }
    with pytest.raises(ValueError, match="one training and one validation"):
        records_by_split([record("train"), record("test")])


def _echo_processor(**kwargs):
    """A stand-in image processor (module level, so it pickles): returns what it is given."""
    return kwargs


def test_tile_transform_cuts_native_scale_tiles_and_pickles() -> None:
    """Each screenshot becomes one tile the model sees at its own size; DataLoader workers started with spawn get
    the transform pickled, and the copy cuts the same tiles."""
    image = Image.new("RGB", (1920, 1080), (40, 90, 40))
    objects = {
        "id": [0, 1],
        "category": [0, 1],
        "bbox": [[900.0, 500.0, 39.0, 39.0], [905.0, 460.0, 34.0, 34.0]],
        "area": [1521.0, 1156.0],
        "iscrowd": [0, 0],
    }
    examples = {"image": [image], "image_id": [3], "objects": [objects]}
    for train in (True, False):
        transform = tile_transform(_echo_processor, train=train, seed=7)
        copy = pickle.loads(pickle.dumps(transform))
        original, copied = transform(examples), copy(examples)
        assert copied["annotations"] == original["annotations"]
        (tile,) = original["images"]
        assert tile.shape == (K.RF_DETR_TILE, K.RF_DETR_TILE, 3)
        for box in original["annotations"][0]["annotations"]:
            x, y, w, h = box["bbox"]
            assert x >= 0 and y >= 0 and x + w <= K.RF_DETR_TILE + 1e-6 and y + h <= K.RF_DETR_TILE + 1e-6
    densest = tile_transform(_echo_processor, train=False)(examples)
    assert len(densest["annotations"][0]["annotations"]) == 2  # the validation tile holds both boxes whole


def test_tiles_in_a_dataloader_worker_follow_its_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """In a DataLoader worker the tiles follow the worker's seed (new every epoch, from torch.manual_seed), so
    epochs draw different tiles; without workers, the transform's own seed."""
    data = pytest.importorskip("torch.utils.data")
    monkeypatch.setattr(data, "get_worker_info", lambda: type("Worker", (), {"id": 0, "seed": 123})())
    assert tile_transform(_echo_processor, train=True, seed=7)._random().random() == random.Random(123).random()
    monkeypatch.setattr(data, "get_worker_info", lambda: None)
    assert tile_transform(_echo_processor, train=True, seed=7)._random().random() == random.Random(7).random()


def test_annotator_manifest_errors_say_what_is_wrong(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Not an annotator"):
        load_annotator_manifest(_manifest(tmp_path, [], format="coco"))
    with pytest.raises(ValueError, match="no labels"):
        load_annotator_manifest(_manifest(tmp_path, [], labels={}))
    with pytest.raises(ValueError, match="unknown label"):
        load_annotator_manifest(
            _manifest(tmp_path, [_image(tmp_path, annotations=[{"label": "zzz", "bbox": [0, 0, 9, 9]}])])
        )
    with pytest.raises(ValueError, match=r"classes the labels do not have \(my_label\)"):
        # a reviewer's own class: the model would be refused at inference (load_detector), so it never trains
        load_annotator_manifest(_manifest(tmp_path, [_image(tmp_path)], labels={"0": "map_node", "1": "my_label"}))
    with pytest.raises(ValueError, match="Invalid annotator bbox"):
        load_annotator_manifest(_manifest(tmp_path, [_image(tmp_path, annotations=[{"label": "icon", "bbox": "box"}])]))
    with pytest.raises(ValueError, match="positive"):
        load_annotator_manifest(_manifest(tmp_path, [_image(tmp_path)]), max_images=0)


def test_relative_and_missing_screenshots(tmp_path: Path) -> None:
    """Paths relative to the manifest are found; screenshots that are gone are left out, and none left is an error."""
    shot = _image(tmp_path, "rel.png", split="train")
    shot["path"] = "rel.png"
    gone = {**_image(tmp_path, "gone.png", split="validation"), "path": str(tmp_path / "missing.png")}
    records, _labels = load_annotator_manifest(_manifest(tmp_path, [shot, gone]))
    assert [r.path for r in records] == [tmp_path / "rel.png"]
    with pytest.raises(FileNotFoundError):
        load_annotator_manifest(_manifest(tmp_path, [gone]))


def test_the_dataset_keeps_the_annotators_splits(tmp_path: Path) -> None:
    """The saved dataset has the three splits as the annotator gave them and its label map."""
    pytest.importorskip("datasets")
    from grand_project.detect.rf_detr import build_dataset

    for name in ("a", "b", "c"):
        Image.new("RGB", (64, 36), (20, 120, 20)).save(tmp_path / f"{name}.png")

    def record(index: int, name: str, split: str) -> Record:
        boxes = (
            {"category_id": 1, "bbox": (1.0, 2.0, 10.0, 10.0), "area": 100.0, "iscrowd": 0, "provenance": "manual"},
        )
        return Record(index, tmp_path / f"{name}.png", name, "annotator_reviewed", "g", 64, 36, boxes, split)

    records = [record(0, "a", "train"), record(1, "b", "validation"), record(2, "c", "test")]
    labels = {"0": "map_node_grass", "1": "icon"}
    out = tmp_path / "dataset"
    dataset = build_dataset(records, label_map=labels, output_dir=out)
    assert {split: len(rows) for split, rows in dataset.items()} == {"train": 1, "validation": 1, "test": 1}
    assert dataset["train"].features["objects"]["category"].feature.names == ["map_node_grass", "icon"]
    meta = json.loads((out / "metadata.json").read_text())
    assert (meta["tile"], meta["test_images"]) == (K.RF_DETR_TILE, 1)
    assert meta["kinds"] == {split: {"annotator_reviewed": 1} for split in ("train", "validation", "test")}
    assert json.loads((out / "labels.json").read_text()) == labels
    with pytest.raises(FileExistsError):
        build_dataset(records, label_map=labels, output_dir=out)
    no_test = build_dataset(records[:2], label_map=labels)  # no test screenshot yet: an empty test split
    assert len(no_test["test"]) == 0 and no_test["test"].features == no_test["train"].features
