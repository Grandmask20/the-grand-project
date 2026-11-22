"""Model pre-labels (tools/detection_dataset_annotator/model_prelabel.py): an RF-DETR checkpoint's boxes beside the
classical ones, on unreviewed training screenshots only, drawn as an A/B test by spatial block."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grand_project.detect import constants as DK
from tools.detection_dataset_annotator import ReviewStore, image_key, model_prelabel
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.model_prelabel import draw_arms, eligible, merge, model_annotations, snap


def _box(label: str, x: float, y: float, size: float = 38.7, source: str = "classical", **fields: Any) -> dict:
    return {"label": label, "bbox": [x - size / 2, y - size / 2, size, size], "source": source, **fields}


def _model(label: str, x: float, y: float, size: float = 38.7) -> dict:
    return _box(label, x, y, size, DK.RF_DETR_SOURCE_MODEL_GUESS, score=0.9)


def test_model_boxes_are_snapped_to_the_box_rules() -> None:
    """The box rules' sizes, centred on the model's middle (a tower standing on its bottom; a hall as found), and
    scaled back to a 4K screenshot's pixels."""
    found = [
        {"label": "map_node_grass", "family": "node", "score": 0.9, "box": [98.0, 99.0, 132.0, 131.0]},
        {"label": "tower", "family": "tower", "score": 0.8, "box": [500.0, 100.0, 560.0, 300.0]},
        {"label": "hall", "family": "hall", "score": 0.7, "box": [800.0, 400.0, 900.0, 520.0]},
    ]
    node, tower, hall = model_annotations(found, (1920, 1080), (3840, 2160))
    half = DK.RF_DETR_MAP_BOX / 2
    assert node["bbox"] == pytest.approx(
        [2 * (115 - half), 2 * (115 - half), 2 * DK.RF_DETR_MAP_BOX, 2 * DK.RF_DETR_MAP_BOX]
    )
    assert tower["bbox"][1] + tower["bbox"][3] == pytest.approx(600.0)  # standing on the model box's bottom (300)
    assert hall["bbox"] == pytest.approx([1600.0, 800.0, 200.0, 240.0])
    assert {box["source"] for box in (node, tower, hall)} == {DK.RF_DETR_SOURCE_MODEL_GUESS}
    assert snap({"family": "icon", "box": [-50.0, -50.0, -10.0, -10.0]}, 1920, 1080) is None  # off the screenshot


def test_the_policies_join_classical_and_model_boxes() -> None:
    classical = [
        _box("map_node_grass", 100, 100),  # the model agrees
        _box("map_node_grass", 300, 300, source="biome_guess"),  # the model says Vaal city area
        _box("map_node_ezomyte", 500, 500, source=K.ANNOTATOR_TRUTH_SOURCE),  # a hand truth: kept
        _box("icon", 700, 700, 34),  # the model misses it: kept
    ]
    model = [
        _model("map_node_grass", 102, 100),
        _model("map_node_vaal", 300, 300),
        _model("map_node_vaal", 500, 500),
        _model("tower", 900, 100, 80),  # only the model has it
    ]
    assert merge(classical, model, "classical") == classical
    # the model's boxes, but the hand truth's Ezomyte node stays where the model would have put its Vaal one
    assert merge(classical, model, "model") == [classical[2], model[0], model[1], model[3]]
    relabelled = merge(classical, model, "relabel")
    assert [(b["label"], b["source"]) for b in relabelled] == [
        ("map_node_grass", DK.RF_DETR_SOURCE_MODEL),
        ("map_node_vaal", DK.RF_DETR_SOURCE_MODEL_GUESS),
        ("map_node_ezomyte", K.ANNOTATOR_TRUTH_SOURCE),
        ("icon", "classical"),
    ]
    assert relabelled[0]["bbox"] == classical[0]["bbox"]  # the classical box stays where it was
    union = merge(classical, model, "union")
    assert union[:4] == relabelled and [b["label"] for b in union[4:]] == ["tower"]
    with pytest.raises(ValueError, match="pre-label policy"):
        merge(classical, model, "everything")


def _item(split: str, *, reviewed: bool = False, source: str = "a.png", **fields: Any) -> dict[str, Any]:
    return {"detected": True, "reviewed": reviewed, "split": split, "source": source, "annotations": [], **fields}


def test_only_unreviewed_training_screenshots_get_model_pre_labels() -> None:
    """Held-out screenshots never do (a review leaning on the model would score the model on its own answers), nor
    reviewed ones, ones a reviewer drew in, ones pre-labelled already, ones a hand truth seeded (a truth-seeded round
    trusts their boxes), or the model's own training screenshots."""
    items = [
        ("train", _item("train")),
        ("validation", _item("validation")),
        ("test", _item("test")),
        ("reviewed", _item("train", reviewed=True)),
        ("drawn", _item("train", annotations=[{"label": "icon", "source": K.ANNOTATOR_MANUAL_SOURCE}])),
        ("done", _item("train", **{K.ANNOTATOR_PRELABEL_FIELD: {"source": "rf_detr"}})),
        ("trained", _item("train", source="seen.png")),
        ("seeded", _item("train", **{K.ANNOTATOR_TRUTH_MARK: "atlas_test_data/fr-atlas/truth.json"})),
    ]
    assert [key for key, _item in eligible(items, {"seen.png"})] == ["train"]


def test_arms_are_drawn_by_whole_blocks() -> None:
    blocks = {f"k{i}": f"atlas#{i // 3}" for i in range(12)}  # 4 blocks of 3 screenshots
    arms = draw_arms(blocks, 0.5, seed=1)
    by_block: dict[str, set[str]] = {}
    for key, arm in arms.items():
        by_block.setdefault(blocks[key], set()).add(arm)
    assert all(len(kinds) == 1 for kinds in by_block.values())  # one block, one arm
    assert sum(arm == DK.RF_DETR_SOURCE_MODEL for arm in arms.values()) == 6
    assert draw_arms(blocks, 0.5, seed=1) == arms and draw_arms(blocks, 0.0, seed=1) == dict.fromkeys(arms, "classical")


def test_a_pass_pre_labels_the_model_arm_and_records_both(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model's arm gets the merged boxes as its new pre-labels, the classical arm keeps its boxes; each records
    its arm, a validation screenshot is left alone, and one a reviewer edited while the model ran keeps the edit."""
    folder = tmp_path / "shots"
    folder.mkdir()
    paths = [folder / f"{name}.png" for name in ("one", "two", "held", "busy")]
    for index, path in enumerate(paths):
        path.write_bytes(bytes([index]))
    review_store.add_images(paths)
    for path in paths:
        result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
        review_store.record_detection(image_key(path), result, force=False)
    keys = [image_key(path) for path in paths]
    review_store.claim_splits({keys[0]: "train", keys[1]: "train", keys[2]: "validation", keys[3]: "train"})
    arms = {keys[0]: DK.RF_DETR_SOURCE_MODEL, keys[1]: K.ANNOTATOR_CLASSICAL_SOURCE, keys[3]: DK.RF_DETR_SOURCE_MODEL}
    monkeypatch.setattr(model_prelabel, "draw_arms", lambda blocks, share, seed: arms)
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {key: key for key, _item in items})
    found = [{"label": "map_node_vaal", "family": "node", "score": 0.9, "box": [281.0, 281.0, 319.0, 319.0]}]

    def predict(detector, path):
        if path == paths[3]:  # the reviewer relabels this one while the model looks at it
            review_store.save_review(keys[3], 1, annotations=[_box("map_node_water", 300, 300, id="b0")])
        return found, (1920, 1080), (1920, 1080)

    monkeypatch.setattr(model_prelabel, "predict", predict)
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    out = review_store.path.parent
    assert model_prelabel.main(["--model", str(model_dir), "--output-dir", str(out), "--policy", "relabel"]) == 0
    one, two, held, busy = (review_store.item(key) for key in keys)
    assert [b["label"] for b in one["annotations"]] == ["map_node_vaal"]
    assert review_store.prelabels(image_key(paths[0]))[0]["label"] == "map_node_vaal"  # the new snapshot
    assert one[K.ANNOTATOR_PRELABEL_FIELD]["source"] == DK.RF_DETR_SOURCE_MODEL
    assert [b["label"] for b in two["annotations"]] == ["map_node_grass"]
    assert two[K.ANNOTATOR_PRELABEL_FIELD]["source"] == K.ANNOTATOR_CLASSICAL_SOURCE
    assert K.ANNOTATOR_PRELABEL_FIELD not in held
    assert [b["label"] for b in busy["annotations"]] == ["map_node_water"]  # the review in progress is kept
    assert K.ANNOTATOR_PRELABEL_FIELD not in busy and review_store.prelabels(keys[3])[0]["label"] == "map_node_grass"
