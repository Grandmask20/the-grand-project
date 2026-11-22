"""The simulated annotation loop (tools/detection_dataset_annotator/simulate_loop.py): rounds revealing a hand-labelled
atlas's training blocks, and the gold / silver scoring of pre-label policies against its truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.detection_dataset_annotator import ReviewStore, image_key, relative_source, simulate_loop
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.simulate_loop import (
    city_area,
    classical_boxes,
    held_out,
    parse_rounds,
    report_markdown,
    revealed,
    score,
)
from tools.detection_dataset_annotator.split_ledger import Entry, write_ledger

ATLAS = "atlas_test_data/fr-atlas/crawl_atlas_v076"


def _box(label: str, x: float, y: float, size: float = 38.7) -> dict:
    return {"label": label, "bbox": [x - size / 2, y - size / 2, size, size]}


def test_rounds_reveal_training_blocks_cumulatively() -> None:
    ledger = {
        f"sha{i}": Entry(f"sha{i}", split, f"{ATLAS}#{block}", f"{ATLAS}/shot{i}.png")
        for i, (split, block) in enumerate(
            [("train", 0), ("train", 0), ("train", 2), ("validation", 7), ("test", 5), ("train", 8)]
        )
    }
    assert parse_rounds("8,2; 0") == [["8", "2"], ["0"]]
    rounds = revealed(ledger, ATLAS, parse_rounds("8,2;0"))
    assert rounds == [[f"{ATLAS}/shot5.png", f"{ATLAS}/shot2.png"], [f"{ATLAS}/shot5.png", f"{ATLAS}/shot2.png",
                      f"{ATLAS}/shot0.png", f"{ATLAS}/shot1.png"]]  # fmt: skip
    with pytest.raises(ValueError, match="not a training block"):
        revealed(ledger, ATLAS, [["7"]])  # the validation block never trains
    with pytest.raises(ValueError, match="no blocks"):
        parse_rounds("8;;0")


def test_a_node_counts_for_the_truth_only_by_its_city_area() -> None:
    assert city_area({"label": "map_node_water"})["label"] == "map_node"
    assert city_area({"label": "map_node_vaal"})["label"] == "map_node_vaal"
    assert city_area({"label": "tower"})["label"] == "tower"


def test_gold_is_what_the_truth_knows_and_silver_the_rest() -> None:
    """A wrong grass/water guess is no gold edit (the truth knows city areas only); a wrong city area, a false
    citadel and a missed one are; nodes found or missed, and other families, are silver (against classical)."""
    reference = [
        _box("map_node_water", 100, 100),
        _box("map_node_vaal", 300, 300),
        _box("map_node_grass", 500, 500),
        _box("citadel_stone", 320, 320, 80),
        _box("icon", 700, 700, 34),
    ]
    prelabels = [
        _box("map_node_grass", 100, 100),  # another biome: silver, not gold
        _box("map_node_grass", 300, 300),  # missed the Vaal city area: gold relabel
        _box("map_node_ezomyte", 520, 1000),  # far from the grass node: silver add + delete
        _box("citadel_copper", 1500, 300, 80),  # a false citadel: gold delete (and the real one is a gold add)
        _box("icon", 700, 700, 34),
    ]
    result = score(prelabels, reference, width=1920)
    assert result["gold"].relabelled == 1 and result["gold"].kept == 1
    assert (result["gold"].deleted, result["gold"].added) == (1, 1)  # the citadels
    assert (result["silver"].deleted, result["silver"].added) == (1, 1)  # the node far off


def test_held_out_screenshots_are_the_atlas_truth_seeded_validation_and_test() -> None:
    images = [
        {"source": f"{ATLAS}/a.png", "split": "validation", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": f"{ATLAS}/b.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": f"{ATLAS}/c.png", "split": "train", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": "atlas_test_data/roa-atlas/d.png", "split": "test"},
    ]
    shots = held_out({"images": images}, ATLAS)
    assert [row["source"] for row in shots["validation"]] == [f"{ATLAS}/a.png"]
    assert [row["source"] for row in shots["test"]] == [f"{ATLAS}/b.png"]


def test_the_classical_boxes_are_read_from_a_store_copy(tmp_path: Path, review_store: ReviewStore) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"x")
    review_store.add_images([path])
    result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}]}
    review_store.record_detection(image_key(path), result, force=False)
    boxes = classical_boxes(review_store.path)
    (source,) = boxes
    assert boxes[source] == [{"label": "tower", "bbox": [5.0, 5.0, 20.0, 20.0], "source": None}]


def test_the_report_lists_every_policy_per_round() -> None:
    scores = {
        policy: {"gold": {"edits": 1.0, "relabelled": 1.0, "deleted": 0.0, "added": 0.0},
                 "silver": {"edits": 0.5, "added": 0.25, "deleted": 0.25}}
        for policy in K.ANNOTATOR_PRELABEL_POLICIES
    }  # fmt: skip
    text = report_markdown([{"round": 1, "train_screenshots": 63, "validation_mean_ap": 0.5,
                             "scores": {"validation": {"screenshots": 52, **scores}}}])  # fmt: skip
    assert "## Round 1: 63 training screenshots" in text and "Validation mean family AP 0.500" in text
    assert all(f"| {policy} | 1.00 |" in text for policy in K.ANNOTATOR_PRELABEL_POLICIES)


def test_a_simulation_trains_each_round_on_from_the_last_and_scores_every_policy(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round by round: the revealed screenshots (cumulative) are trained on, from the previous round's model, on one
    dataset built once; then every policy is scored on the held-out screenshots. Here the classical detector calls
    a truth Vaal node grass and the model gets it right: relabelling by the model leaves no gold edit."""
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    shots = {name: atlas / f"{name}.png" for name in ("a1", "a2", "val", "tst")}
    for index, path in enumerate(shots.values()):
        path.write_bytes(bytes([index]))
    name = relative_source(atlas)
    splits = {"a1": ("train", 0), "a2": ("train", 1), "val": ("validation", 7), "tst": ("test", 5)}
    write_ledger(
        [Entry(f"sha-{n}", split, f"{name}#{block}", relative_source(shots[n])) for n, (split, block) in splits.items()]
    )
    review_store.add_images([shots["val"], shots["tst"]])
    for n in ("val", "tst"):
        result = {"width": 1920, "height": 1080, "annotations": [_box("map_node_grass", 300, 300)]}
        review_store.record_detection(image_key(shots[n]), result, force=False)
    rows = [
        {"source": relative_source(shots[n]), "path": str(shots[n]), "split": split, K.ANNOTATOR_TRUTH_MARK: "t.json",
         "annotations": [_box("map_node_vaal", 300, 300)]}
        for n, split in (("val", "validation"), ("tst", "test"))
    ]  # fmt: skip
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"images": rows}), encoding="utf-8")

    commands = []

    def train(command, check):
        commands.append(command)
        round_dir = Path(command[command.index("--output-dir") + 1])
        (round_dir / "training_summary.json").write_text(json.dumps({"best_validation_mean_ap": 0.5}))
        dataset = Path(command[command.index("--dataset-dir") + 1])
        dataset.mkdir(parents=True, exist_ok=True)
        (dataset / "labels.json").write_text("{}")  # the first round built the dataset

    found = [{"label": "map_node_vaal", "family": "node", "score": 0.9, "box": [281.0, 281.0, 319.0, 319.0]}]
    monkeypatch.setattr(simulate_loop.subprocess, "run", train)
    monkeypatch.setattr(simulate_loop, "predict", lambda detector, path: (found, (1920, 1080), (1920, 1080)))
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})
    out = tmp_path / "sim"
    args = ["--manifest", str(manifest), "--classical-store", str(review_store.path), "--rounds", "0;1",
            "--atlas", name, "--output-dir", str(out), "--epochs", "2"]  # fmt: skip
    assert simulate_loop.main(args) == 0

    first, second = commands
    assert "--annotator-manifest" in first and "--init-from" not in first
    assert "--reuse-dataset" in second and second[second.index("--init-from") + 1] == str(out / "round-1" / "best")
    assert "--truth-seeded" in first and "--truth-seeded" in second
    subsets = [(out / f"round-{n}" / "train_subset.txt").read_text().split() for n in (1, 2)]
    assert subsets == [[relative_source(shots["a1"])], [relative_source(shots["a1"]), relative_source(shots["a2"])]]
    report = json.loads((out / "report.json").read_text())
    assert [r["train_screenshots"] for r in report] == [1, 2] and report[0]["validation_mean_ap"] == 0.5
    for split in ("validation", "test"):
        scores = report[-1]["scores"][split]
        assert scores["screenshots"] == 1
        assert scores["classical"]["gold"]["relabelled"] == 1.0 and scores["relabel"]["gold"]["edits"] == 0.0
    assert "## Round 2: 2 training screenshots" in (out / "report.md").read_text()
