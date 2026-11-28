"""Model pre-labels (tools/detection_dataset_annotator/model_prelabel.py): an RF-DETR checkpoint's boxes beside the
classical ones, on unreviewed training screenshots only, drawn as an A/B test by spatial block."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from grand_project.detect import constants as DK
from tools.detection_dataset_annotator import ReviewStore, image_key, model_prelabel
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.model_prelabel import (
    draw_arms,
    eligible,
    merge,
    model_annotations,
    recorded_arms,
    snap,
)


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
    monkeypatch.setattr(model_prelabel, "draw_arms", lambda blocks, share, seed, given=None: arms)
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {key: key for key, _item in items})
    found = [{"label": "map_node_vaal", "family": "node", "score": 0.9, "box": [281.0, 281.0, 319.0, 319.0]}]

    def predict(detector, path, detected=None):
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


def test_a_block_keeps_the_arm_an_earlier_pass_gave_it() -> None:
    """A --limit pass (or newly detected screenshots) leaves some of a block for later: those join its arm."""
    blocks = {"a1": "atlas#0", "a2": "atlas#0", "b1": "atlas#1", "c1": "atlas#2"}
    items = [("a1", {K.ANNOTATOR_PRELABEL_FIELD: {"source": DK.RF_DETR_SOURCE_MODEL}}), ("b1", {}), ("c1", {})]
    given = recorded_arms(items, blocks)
    assert given == {"atlas#0": DK.RF_DETR_SOURCE_MODEL}
    for seed in range(5):  # whatever the draw of the other blocks
        arms = draw_arms({"a2": "atlas#0", "b1": "atlas#1", "c1": "atlas#2"}, 0.0, seed, given)
        assert arms == {"a2": DK.RF_DETR_SOURCE_MODEL, "b1": "classical", "c1": "classical"}


def test_without_a_store_nothing_is_eligible_and_nothing_is_made(tmp_path: Path, capsys) -> None:
    out = tmp_path / "no-store"
    assert model_prelabel.main(["--dry-run", "--output-dir", str(out), "--model", str(tmp_path / "model")]) == 0
    assert "0 screenshots eligible" in capsys.readouterr().out and not out.exists()


def test_a_screenshot_seeded_while_the_model_looked_keeps_the_truth(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truth seeding saved its boxes and mark while the model looked at the screenshot: the model's boxes, made from
    the older ones, are not saved, and the screenshot gets no arm."""
    path = tmp_path / "one.png"
    path.write_bytes(b"1")
    review_store.add_images([path])
    key = image_key(path)
    result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
    review_store.record_detection(key, result, force=False)
    review_store.claim_splits({key: "train"})
    monkeypatch.setattr(
        model_prelabel,
        "draw_arms",
        lambda blocks, share, seed, given=None: dict.fromkeys(blocks, DK.RF_DETR_SOURCE_MODEL),
    )
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {k: k for k, _item in items})
    seeded = [_box("map_node_vaal", 300, 300, source=K.ANNOTATOR_TRUTH_SOURCE, id="b0")]

    def predict(detector, path, detected=None):
        mark = {K.ANNOTATOR_TRUTH_MARK: "truth.json"}
        assert review_store.save_review(key, 1, annotations=seeded, extra=mark, prelabel=True, untouched=True)
        return [], (1920, 1080), (1920, 1080)

    monkeypatch.setattr(model_prelabel, "predict", predict)
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})
    (tmp_path / "model").mkdir()
    out = review_store.path.parent
    assert model_prelabel.main(["--model", str(tmp_path / "model"), "--output-dir", str(out), "--policy", "model"]) == 0
    item = review_store.item(key)
    assert [(b["label"], b["source"]) for b in item["annotations"]] == [("map_node_vaal", K.ANNOTATOR_TRUTH_SOURCE)]
    assert K.ANNOTATOR_PRELABEL_FIELD not in item


def test_a_classical_policy_is_no_model_pass(tmp_path: Path) -> None:
    """``--policy classical`` gives no model boxes: its screenshots would count in the model's arm."""
    with pytest.raises(SystemExit):
        model_prelabel.main(["--dry-run", "--output-dir", str(tmp_path), "--policy", "classical"])


def test_a_limited_pass_draws_the_arms_of_every_eligible_block(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--limit`` leaves screenshots for later, not blocks out of the draw: drawn over one block alone, a share of
    0.5 rounds to no model block at all, pass after pass."""
    folder = tmp_path / "shots"
    folder.mkdir()
    paths = [folder / f"{index}.png" for index in range(4)]
    for index, path in enumerate(paths):
        path.write_bytes(bytes([index]))
    review_store.add_images(paths)
    for path in paths:
        result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
        review_store.record_detection(image_key(path), result, force=False)
    review_store.claim_splits({image_key(path): "train" for path in paths})
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {key: key for key, _item in items})
    drawn = []
    real = model_prelabel.draw_arms

    def draw(blocks, *args):
        drawn.append(sorted(blocks))
        return real(blocks, *args)

    monkeypatch.setattr(model_prelabel, "draw_arms", draw)
    out = review_store.path.parent
    model = str(tmp_path / "model")
    assert model_prelabel.main(["--dry-run", "--limit", "1", "--output-dir", str(out), "--model", model]) == 0
    assert drawn == [sorted(image_key(path) for path in paths)]  # all four drawn; the pass does one


def test_the_store_and_the_ledger_are_read_under_the_ledgers_lock(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export claims splits in the store and then writes their ledger rows, under the ledger's lock: the pass reads
    both under it too, so it never sees a training split whose block is not written yet (CodeRabbit)."""
    import contextlib

    from tools.detection_dataset_annotator import split_ledger

    seen = []
    held = {"now": False}

    @contextlib.contextmanager
    def lock(path=None):
        held["now"] = True
        try:
            yield
        finally:
            held["now"] = False

    monkeypatch.setattr(split_ledger, "_ledger_lock", lock)
    real_items = ReviewStore.items
    monkeypatch.setattr(
        ReviewStore, "items", lambda self, **k: seen.append(("items", held["now"])) or real_items(self, **k)
    )
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: seen.append(("blocks", held["now"])) or {})
    out = review_store.path.parent
    assert model_prelabel.main(["--dry-run", "--output-dir", str(out), "--model", str(tmp_path / "model")]) == 0
    assert seen[:2] == [("items", True), ("blocks", True)]


def test_a_failed_model_pass_keeps_its_blocks_in_the_models_arm(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each block's arm is planned before any work: a pass that fails leaves its screenshots eligible, and the next
    pass (another draw) gives them the arm planned, not a new one."""
    folder = tmp_path / "shots"
    folder.mkdir()
    paths = [folder / f"{index}.png" for index in range(2)]
    for index, path in enumerate(paths):
        path.write_bytes(bytes([index]))
    review_store.add_images(paths)
    for path in paths:
        result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
        review_store.record_detection(image_key(path), result, force=False)
    keys = [image_key(path) for path in paths]
    review_store.claim_splits({key: "train" for key in keys})
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {key: key for key, _item in items})
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})

    def broken(detector, path, detected=None):
        raise RuntimeError("out of memory")

    monkeypatch.setattr(model_prelabel, "predict", broken)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    out = review_store.path.parent
    command = ["--model", str(model_dir), "--output-dir", str(out), "--policy", "relabel"]
    with pytest.raises(RuntimeError, match="out of memory"):
        model_prelabel.main([*command, "--share", "1"])
    assert review_store.prelabel_plan() == {key: DK.RF_DETR_SOURCE_MODEL for key in keys}
    assert all(K.ANNOTATOR_PRELABEL_FIELD not in review_store.item(key) for key in keys)  # still eligible

    found = [{"label": "map_node_vaal", "family": "node", "score": 0.9, "box": [281.0, 281.0, 319.0, 319.0]}]
    monkeypatch.setattr(
        model_prelabel, "predict", lambda detector, path, detected=None: (found, (1920, 1080), (1920, 1080))
    )
    assert model_prelabel.main([*command, "--share", "0", "--seed", "7"]) == 0  # a draw that would give none
    for key in keys:
        assert review_store.item(key)[K.ANNOTATOR_PRELABEL_FIELD]["source"] == DK.RF_DETR_SOURCE_MODEL
        assert [b["label"] for b in review_store.item(key)["annotations"]] == ["map_node_vaal"]


def test_a_dry_run_plans_no_arm(tmp_path: Path, review_store: ReviewStore) -> None:
    path = tmp_path / "a.png"
    path.write_bytes(b"a")
    review_store.add_images([path])
    result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
    review_store.record_detection(image_key(path), result, force=False)
    review_store.claim_splits({image_key(path): "train"})
    out = review_store.path.parent
    assert model_prelabel.main(["--dry-run", "--output-dir", str(out), "--model", str(tmp_path / "model")]) == 0
    assert review_store.prelabel_plan() == {}


def test_a_negative_limit_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        model_prelabel.main(["--dry-run", "--output-dir", str(tmp_path), "--limit", "-1"])


def test_a_model_swapped_while_the_pass_ran_stops_it(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The weights loaded must be the ones hashed and whose training screenshots were left out: a new best/ swapped in
    meanwhile stops the pass before it saves anything."""
    path = tmp_path / "a.png"
    path.write_bytes(b"a")
    review_store.add_images([path])
    result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
    review_store.record_detection(image_key(path), result, force=False)
    review_store.claim_splits({image_key(path): "train"})
    monkeypatch.setattr(model_prelabel, "_blocks", lambda items: {key: key for key, _item in items})
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_bytes(b"weights 1")

    def swapped(folder):
        (model_dir / "model.safetensors").write_bytes(b"weights 2")  # a training run kept a new best meanwhile
        return {}

    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", swapped)
    monkeypatch.setattr(model_prelabel, "predict", lambda *a: pytest.fail("predicted with another model's weights"))
    out = review_store.path.parent
    with pytest.raises(SystemExit, match="changed while this pass ran"):
        model_prelabel.main(["--model", str(model_dir), "--output-dir", str(out), "--share", "1"])
    assert K.ANNOTATOR_PRELABEL_FIELD not in review_store.item(image_key(path))


def test_a_named_classical_icon_keeps_its_name_where_the_model_finds_its_icon() -> None:
    """The model has one icon class: a named classical icon (named icons on) it agrees with keeps its name and is no
    longer a guess; a class the model really changes is still taken (and checked first)."""
    classical = [_box("icon_mapboss", 100, 100, 34), _box("map_node_grass", 400, 400)]
    model = [_model("icon", 101, 100, 34), _model("map_node_desert", 400, 401)]
    for policy in ("relabel", "union"):
        boxes = merge(classical, model, policy)
        assert [(b["label"], b["source"]) for b in boxes] == [
            ("icon_mapboss", DK.RF_DETR_SOURCE_MODEL),
            ("map_node_desert", DK.RF_DETR_SOURCE_MODEL_GUESS),
        ]


def test_a_dry_run_opens_the_store_read_only(tmp_path: Path, review_store: ReviewStore) -> None:
    """A dry run changes nothing, not even the store's journal mode (a writable open sets WAL: CodeRabbit)."""
    import sqlite3

    path = tmp_path / "a.png"
    path.write_bytes(b"a")
    review_store.add_images([path])
    review_store.record_detection(image_key(path), {"width": 1920, "height": 1080, "annotations": []}, force=False)
    review_store.claim_splits({image_key(path): "train"})
    review_store.close()
    with sqlite3.connect(review_store.path) as db:
        db.execute("PRAGMA journal_mode = DELETE")
    out = review_store.path.parent
    assert model_prelabel.main(["--dry-run", "--output-dir", str(out), "--model", str(tmp_path / "model")]) == 0
    with sqlite3.connect(review_store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


@pytest.mark.parametrize("now", ["other bytes", None])
def test_a_screenshot_changed_or_unreadable_since_its_detection_gets_no_model_boxes(
    now: str | None, tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A file that is not the bytes detected (replaced since, also by one of its size): its boxes and the model's
    would frame two pictures; one that cannot be read: said, left eligible for the next pass, the pass goes on
    (CodeRabbit). Checked on the read the model's prediction makes."""
    from tools.detection_dataset_annotator import detection

    path = tmp_path / "a.png"
    path.write_bytes(b"a")
    review_store.add_images([path])
    key = image_key(path)
    result = {"width": 1920, "height": 1080, K.ANNOTATOR_DETECTED_SHA: "detected bytes",
              "annotations": [_box("map_node_grass", 300, 300)]}  # fmt: skip
    review_store.record_detection(key, result, force=False)
    review_store.claim_splits({key: "train"})
    read = None if now is None else (np.zeros((1080, 1920, 3), np.uint8), now)
    monkeypatch.setattr(detection, "read_with_digest", lambda path: read)
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})
    monkeypatch.setattr(
        "grand_project.detect.rf_detr_model.predict_tiles", lambda *a, **k: pytest.fail("predicted a changed file")
    )
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    out = review_store.path.parent
    assert model_prelabel.main(["--model", str(model_dir), "--output-dir", str(out), "--share", "1"]) == 0
    said = capsys.readouterr().out
    assert ("changed since its detection" if now else "Could not read image") in said and "(left)" in said
    item = review_store.item(key)
    assert [b["label"] for b in item["annotations"]] == ["map_node_grass"]
    assert K.ANNOTATOR_PRELABEL_FIELD not in item  # still eligible
