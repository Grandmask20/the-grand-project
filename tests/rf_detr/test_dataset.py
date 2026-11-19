"""Offline checks for the RF-DETR dataset schema helpers."""

import json
import math
import pickle
import random
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from grand_project import cities
from grand_project.detect import constants as K
from grand_project.detect import rf_detr, rf_detr_model
from grand_project.detect.constants import RF_DETR_CORE_LABELS
from grand_project.detect.rf_detr import (
    Record,
    _box,
    _load_cached_records,
    _truth_annotations,
    _wall_annotations,
    augment_detection_example,
    load_annotator_manifest,
    load_records,
    processor_transform,
    slug,
    split_records,
)
from grand_project.detect.rf_detr_model import _icon_name


def _record(index: int, group: str = "truth") -> Record:
    return Record(index, Path(f"image-{index}.png"), f"{group}/{index}", "hand_truth", group, 1920, 1080, ())


def test_box_is_clipped_to_the_source_image() -> None:
    assert _box(1920, 1080, 2, 3, 48, 48) == (0.0, 0.0, 26.0, 27.0)
    assert _box(1920, 1080, 960, 540, 48, 48) == (936.0, 516.0, 48.0, 48.0)


def test_category_slug_is_stable_and_safe() -> None:
    assert slug("Map Boss Special") == "map_boss_special"
    assert slug("!!!") == "unknown"


def test_named_icon_classes_come_back_as_the_program_spells_them() -> None:
    """Issue: "icon_abyssoverrun" came back as "Abyssoverrun" (not a type the viewer and the atlas check know)."""
    image = np.zeros((1080, 1920, 3), np.uint8)
    for name in ("AbyssOverrun", "BreachHive", "WisdomsTeachings", "LostTower", "ExpeditionShip", "ArcaneHordes"):
        assert _icon_name(f"icon_{slug(name)}", image, 960, 540) == name


def test_annotator_manifest_loads_source_paths_and_labels(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"placeholder")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "the-grand-project-rf-detr-manifest",
                "labels": {"0": "map_node", "1": "icon"},
                "images": [
                    {
                        "image_id": 7,
                        "path": str(image),
                        "source": "screenshots/shot.png",
                        "source_type": "annotator_reviewed",
                        "source_group": "screenshots",
                        "width": 1920,
                        "height": 1080,
                        "annotations": [{"label": "icon", "bbox": [10, 20, 34, 34], "source": "manual"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records, labels = load_annotator_manifest(manifest)

    assert labels == {"0": "map_node", "1": "icon"}
    assert len(records) == 1
    assert records[0].path == image
    assert records[0].annotations[0]["category_id"] == 1
    assert records[0].annotations[0]["bbox"] == (10.0, 20.0, 34.0, 34.0)


def test_core_labels_leave_derived_geometry_out_of_training() -> None:
    assert "icon" in RF_DETR_CORE_LABELS
    assert "path" not in RF_DETR_CORE_LABELS
    assert "path_dash" not in RF_DETR_CORE_LABELS
    assert "fortress_wall" not in RF_DETR_CORE_LABELS


def test_split_is_deterministic_and_keeps_source_groups_when_requested() -> None:
    records = [_record(index, "ocean" if index >= 4 else "truth") for index in range(8)]
    train_a, val_a = split_records(records, 0.25, 1337)
    train_b, val_b = split_records(records, 0.25, 1337)
    assert [record.image_id for record in train_a] == [record.image_id for record in train_b]
    assert [record.image_id for record in val_a] == [record.image_id for record in val_b]

    grouped_train, grouped_val = split_records(records, 0.25, 1337, by_source=True)
    assert {record.source_group for record in grouped_train}.isdisjoint({record.source_group for record in grouped_val})


def test_horizontal_flip_updates_boxes_without_mutating_truth(monkeypatch) -> None:
    """Train augmentation mirrors every object while leaving the stored hand truth untouched."""
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_FLIP_PROBABILITY", 1.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_CROP_PROBABILITY", 0.0)
    objects = {
        "id": [4],
        "bbox": [[10.0, 20.0, 30.0, 15.0]],
        "area": [450.0],
        "category": [2],
        "iscrowd": [0],
    }

    augmented, transformed = augment_detection_example(Image.new("RGB", (100, 80)), objects, random.Random(3))

    assert augmented.size == (100, 80)
    assert transformed["bbox"] == [[60.0, 20.0, 30.0, 15.0]]
    assert transformed["area"] == [450.0]
    assert objects["bbox"] == [[10.0, 20.0, 30.0, 15.0]]


def test_random_crop_clips_visible_boxes_and_recomputes_area(monkeypatch) -> None:
    """Crops must never pass coordinates outside the cropped image to the processor."""
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_FLIP_PROBABILITY", 0.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_CROP_PROBABILITY", 1.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_CROP_MIN_SCALE", 0.75)
    objects = {
        "id": [1, 2],
        "bbox": [[20.0, 20.0, 20.0, 20.0], [80.0, 60.0, 15.0, 15.0]],
        "area": [400.0, 225.0],
        "category": [0, 1],
        "iscrowd": [0, 0],
    }

    augmented, transformed = augment_detection_example(Image.new("RGB", (120, 100)), objects, random.Random(7))

    assert augmented.size[0] <= 120 and augmented.size[1] <= 100
    assert transformed["bbox"]
    for x, y, width, height in transformed["bbox"]:
        assert 0 <= x < augmented.width
        assert 0 <= y < augmented.height
        assert x + width <= augmented.width
        assert y + height <= augmented.height
    assert transformed["area"] == [box[2] * box[3] for box in transformed["bbox"]]


def test_truth_cities_get_typed_classes(monkeypatch) -> None:
    """User: cities are always learned by type. A truth city's own type wins; an untyped one takes the look guess."""
    monkeypatch.setattr(cities, "look_distances", lambda feats: [0.7, 0.6, 0.2])  # looks Faridun
    labels = {
        "landmarks": [
            {"kind": "City", "x": 400, "y": 400, "city_type": "Vaal", "flags": []},
            {"kind": "City", "x": 1500, "y": 600, "city_type": None, "flags": []},
            {"kind": "Hall", "x": 900, "y": 300, "flags": []},
        ]
    }
    annotations = _truth_annotations(
        labels,
        np.zeros((1080, 1920, 3), np.uint8),
        map_box=K.RF_DETR_MAP_BOX,
        icon_box=K.RF_DETR_ICON_BOX,
        landmark_box=K.RF_DETR_LANDMARK_BOX,
        tower_width=K.RF_DETR_TOWER_WIDTH,
        tower_height=K.RF_DETR_TOWER_HEIGHT,
        stronghold_box=K.RF_DETR_STRONGHOLD_BOX,
        badge_granularity="all",
        include_soft=False,
        include_paths=False,
        include_path_dashes=False,
        provenance="hand_truth",
    )
    assert [a["category_name"] for a in annotations] == ["city_vaal", "city_faridun", "hall"]
    assert "city" not in RF_DETR_CORE_LABELS
    assert set(K.RF_DETR_CITY_LABELS.values()) <= set(RF_DETR_CORE_LABELS)


def test_rf_detr_typed_city_comes_back_as_a_typed_city(monkeypatch) -> None:
    """A typed city class gives a City with its city_type; an older checkpoint's plain ``city`` an untyped City."""
    predictions = [
        {"label": "city_vaal", "box": [100.0, 100.0, 172.0, 172.0], "score": 0.9},
        {"label": "city", "box": [400.0, 100.0, 472.0, 172.0], "score": 0.8},
    ]
    monkeypatch.setattr(rf_detr_model, "_predict", lambda img: predictions)
    result = rf_detr_model.detect_rf_detr(np.zeros((360, 640, 3), np.uint8))
    cities_found = sorted((lm["x"], lm.get("city_type")) for lm in result["landmarks"] if lm["kind"] == "City")
    assert cities_found == [(136.0, "Vaal"), (436.0, None)]


def test_rf_detr_tower_keeps_its_map_node(monkeypatch) -> None:
    """As in the classical detector, a tower's map node stays in the graph flagged "tower" (paths reach it); another
    map node on the same wide tower base is a duplicate and goes; a map node farther away stays."""
    predictions = [
        {"label": "map_node", "box": [880.0, 480.0, 920.0, 520.0], "score": 0.9},  # the tower's map node (900, 500)
        {"label": "map_node", "box": [900.0, 485.0, 940.0, 525.0], "score": 0.6},  # duplicate on its base
        {"label": "map_node", "box": [1180.0, 480.0, 1220.0, 520.0], "score": 0.9},  # a neighbour (1200, 500)
        {"label": "tower", "box": [860.0, 285.0, 940.0, 505.0], "score": 0.8},  # stands on (900, 505)
    ]
    monkeypatch.setattr(rf_detr_model, "_predict", lambda img: predictions)
    result = rf_detr_model.detect_rf_detr(np.zeros((1080, 1920, 3), np.uint8))
    assert sorted((n["x"], n["y"], bool(n.get("tower"))) for n in result["nodes"]) == [
        (900.0, 500.0, True),
        (1200.0, 500.0, False),
    ]
    assert [(lm["x"], lm["y"]) for lm in result["landmarks"] if lm["kind"] == "Tower"] == [(900.0, 505.0)]


def _cache_row(data_root: Path, name: str, row: dict, image: bool = True) -> None:
    """One cached crawl detection (``<name>_detect1.json``) and its screenshot (an empty file with image=False)."""
    frames = data_root / "crawl_atlas" / "atlas_frames"
    shots = data_root / "screenshots" / "crawl"
    frames.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    (frames / f"{name}_detect1.json").write_text(json.dumps({"name": name, **row}), encoding="utf-8")
    if image:
        cv2.imwrite(str(shots / f"{name}.png"), np.zeros((1080, 1920, 3), np.uint8))
    else:
        (shots / f"{name}.png").write_bytes(b"")


def test_cached_tower_landmarks_give_one_tower_box_each(tmp_path: Path) -> None:
    """An RF-DETR row reports a tower as a landmark only; a classical row also flags its map node. Either way the
    tower is one box, and overridden box sizes apply to cached rows as to the hand truth."""
    _cache_row(tmp_path, "classical", {"nodes": [{"x": 900, "y": 500, "tower": True}], "landmarks": [
        {"kind": "Tower", "x": 900, "y": 500}]})  # fmt: skip
    _cache_row(tmp_path, "rfdetr", {"nodes": [{"x": 900, "y": 500}], "landmarks": [
        {"kind": "Tower", "x": 900, "y": 505}]})  # fmt: skip

    records = _load_cached_records(
        tmp_path, map_box=20.0, badge_granularity="all", include_paths=False, include_path_dashes=False
    )

    boxes = {r.source: [(a["category_name"], a["bbox"]) for a in r.annotations] for r in records}
    assert boxes == {
        "crawl/classical": [("map_node", (890.0, 490.0, 20.0, 20.0)), ("tower", (860.0, 280.0, 80.0, 220.0))],
        "crawl/rfdetr": [("map_node", (890.0, 490.0, 20.0, 20.0)), ("tower", (860.0, 285.0, 80.0, 220.0))],
    }


def test_max_images_stops_loading_and_empty_files_are_skipped(tmp_path: Path, monkeypatch) -> None:
    """Loading stops once max_images usable screenshots are read; an empty file is skipped and not counted."""
    _cache_row(tmp_path, "a", {"nodes": [{"x": 900, "y": 500}]}, image=False)
    for name in ("b", "c", "d"):
        _cache_row(tmp_path, name, {"nodes": [{"x": 900, "y": 500}]})
    read: list[str] = []
    real = rf_detr._source_image
    monkeypatch.setattr(rf_detr, "_source_image", lambda path: read.append(path.stem) or real(path))

    records, _labels = load_records(tmp_path, include_cached=True, max_images=2)

    assert [record.source for record in records] == ["crawl/b", "crawl/c"]
    assert read == ["a", "b", "c"]
    empty_mask = tmp_path / "1.png"
    empty_mask.write_bytes(b"")
    assert _wall_annotations(empty_mask, np.zeros((1080, 1920, 3), np.uint8)) == []


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
    image = tmp_path / "shot.png"
    image.write_bytes(b"placeholder")
    manifest = tmp_path / "manifest.json"
    item = {"path": str(image), "width": 1920, "height": 1080, "annotations": [{"label": "icon", **annotation}]}
    manifest.write_text(
        json.dumps({"format": "the-grand-project-rf-detr-manifest", "labels": {"0": "icon"}, "images": [item]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid annotator"):
        load_annotator_manifest(manifest)


def test_split_by_source_never_splits_a_group_and_keeps_one_for_training() -> None:
    records = [_record(index, "abc"[index // 2]) for index in range(6)]
    train, validation = split_records(records, 0.9, 1, by_source=True)
    assert train and validation
    assert len({record.source_group for record in train}) == 1
    assert {record.source_group for record in train}.isdisjoint({record.source_group for record in validation})
    with pytest.raises(ValueError, match="two source groups"):
        split_records([_record(index) for index in range(4)], 0.25, 1, by_source=True)


def _echo_processor(**kwargs):
    """A stand-in image processor (module level, so it pickles): returns what it is given."""
    return kwargs


def test_processor_transform_pickles_for_dataloader_workers() -> None:
    """DataLoader workers started with spawn get the transform pickled; the copy transforms like the original."""
    transform = processor_transform(_echo_processor, augment=True, seed=7)
    copy = pickle.loads(pickle.dumps(transform))
    examples = {
        "image": [Image.new("RGB", (64, 32), (200, 10, 10))],
        "image_id": [3],
        "objects": [{"id": [0], "category": [1], "bbox": [[4.0, 4.0, 10.0, 10.0]], "area": [100.0], "iscrowd": [0]}],
    }
    original, copied = transform(examples), copy(examples)
    assert copied["annotations"] == original["annotations"]
    assert [image.size for image in copied["images"]] == [image.size for image in original["images"]]
