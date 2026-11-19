"""Offline checks for the RF-DETR dataset schema helpers."""

import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

from grand_project import cities
from grand_project.detect import constants as K
from grand_project.detect import rf_detr_model
from grand_project.detect.constants import RF_DETR_CORE_LABELS
from grand_project.detect.rf_detr import (
    Record,
    _box,
    _truth_annotations,
    augment_detection_example,
    load_annotator_manifest,
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
