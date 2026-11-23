"""The simulated annotation loop (tools/detection_dataset_annotator/simulate_loop.py): rounds revealing a hand-labelled
atlas's training blocks, and the gold / silver scoring of pre-label policies against its truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grand_project.detect import constants as DK
from tools.detection_dataset_annotator import ReviewStore, image_key, relative_source, simulate_loop
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.simulate_loop import (
    check_round,
    city_area,
    classical_boxes,
    dataset_matches,
    held_out,
    parse_rounds,
    report_markdown,
    revealed,
    score,
)
from tools.detection_dataset_annotator.split_ledger import Entry, write_ledger
from tools.detection_dataset_annotator.state import file_hash

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
    with pytest.raises(ValueError, match="revealed twice"):
        revealed(ledger, ATLAS, parse_rounds("8;8,2"))  # its screenshots would be counted twice
    with pytest.raises(ValueError, match="revealed twice"):
        revealed(ledger, ATLAS, [["0", "0"]])


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
    result = score(prelabels, reference, reference)  # the classical boxes: where the reference has them
    assert result["gold"].relabelled == 1 and result["gold"].kept == 1
    assert (result["gold"].deleted, result["gold"].added) == (1, 1)  # the citadels
    assert (result["silver"].deleted, result["silver"].added) == (1, 1)  # the node far off


def test_held_out_screenshots_are_the_atlas_truth_seeded_validation_and_test() -> None:
    images = [
        {"source": f"{ATLAS}/a.png", "split": "validation", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": f"{ATLAS}/b.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": f"{ATLAS}/c.png", "split": "train", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": "atlas_test_data/roa-atlas/d.png", "split": "test"},
        {"source": f"{ATLAS}-backup/e.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "t.json"},  # another folder
    ]
    shots = held_out({"images": images}, ATLAS)
    assert [row["source"] for row in shots["validation"]] == [f"{ATLAS}/a.png"]
    assert [row["source"] for row in shots["test"]] == [f"{ATLAS}/b.png"]


def test_held_out_screenshots_are_the_ones_this_truth_seeded() -> None:
    """A screenshot another truth marked (a states.json's map nodes, another atlas's truth) is no gold for this one."""
    images = [
        {"source": f"{ATLAS}/a.png", "split": "validation", K.ANNOTATOR_TRUTH_MARK: "fr/truth.json"},
        {"source": f"{ATLAS}/b.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "fr\\truth.json"},  # Windows' slashes
        {"source": f"{ATLAS}/c.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "other/states.json"},
    ]
    shots = held_out({"images": images}, ATLAS, truth_source="fr/truth.json")
    assert [row["source"] for row in shots["validation"]] == [f"{ATLAS}/a.png"]
    assert [row["source"] for row in shots["test"]] == [f"{ATLAS}/b.png"]


def test_an_existing_round_is_scored_only_for_the_screenshots_it_trained_on(tmp_path: Path) -> None:
    """--skip-train scores a round's kept model: it must have trained on exactly what the round reveals."""
    best = tmp_path / "best"
    best.mkdir()
    with pytest.raises(SystemExit, match="lists no training screenshots"):
        check_round(best, ["a.png"], 1)
    (best / DK.RF_DETR_TRAINED_ON).write_text("a.png\nb.png\n", encoding="utf-8")
    check_round(best, ["b.png", "a.png"], 2)  # unchanged: scored again
    with pytest.raises(SystemExit, match=r"round 3: .*\(1 more, 0 missing\)"):
        check_round(best, ["a.png"], 3)


def test_a_relative_screenshot_path_lies_next_to_the_manifest(tmp_path: Path) -> None:
    """As the trainer reads a manifest: a relative path is in the manifest's folder, an absolute one stays."""
    mark = {K.ANNOTATOR_TRUTH_MARK: "t.json"}
    images = [
        {"source": f"{ATLAS}/a.png", "path": "shots/a.png", "split": "validation", **mark},
        {"source": f"{ATLAS}/b.png", "path": str(tmp_path / "elsewhere" / "b.png"), "split": "test", **mark},
    ]
    shots = held_out({"images": images}, ATLAS, tmp_path / "dataset")
    assert shots["validation"][0]["path"] == str(tmp_path / "dataset" / "shots" / "a.png")
    assert shots["test"][0]["path"] == str(tmp_path / "elsewhere" / "b.png")
    assert images[0]["path"] == "shots/a.png"  # the manifest's own rows are left as they are


def test_an_atlas_outside_the_project_on_windows_holds_its_screenshots() -> None:
    """Outside the project a source is an absolute path with the system's separators (Windows CI: none were found)."""
    atlas = r"C:\Users\me\Temp\atlas"
    images = [
        {"source": atlas + r"\val.png", "split": "validation", K.ANNOTATOR_TRUTH_MARK: "t.json"},
        {"source": atlas + r"-backup\tst.png", "split": "test", K.ANNOTATOR_TRUTH_MARK: "t.json"},  # another folder
    ]
    shots = held_out({"images": images}, atlas)
    assert [row["source"] for row in shots["validation"]] == [atlas + r"\val.png"] and shots["test"] == []


def test_the_classical_boxes_are_read_from_a_store_copy(tmp_path: Path, review_store: ReviewStore) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"x")
    review_store.add_images([path])
    result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}]}
    review_store.record_detection(image_key(path), result, force=False)
    nothing = tmp_path / "nothing.png"  # the classical detector found nothing on it: its boxes are none, not missing
    nothing.write_bytes(b"y")
    review_store.add_images([nothing])
    review_store.record_detection(image_key(nothing), {"width": 1920, "height": 1080, "annotations": []}, force=False)
    boxes = classical_boxes(review_store.path)
    assert boxes == {
        relative_source(path): [{"label": "tower", "bbox": [5.0, 5.0, 20.0, 20.0], "source": None}],
        relative_source(nothing): [],
    }


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
    truth = tmp_path / "truth.json"
    mark = relative_source(truth)  # as truth_seed marks the screenshots it seeded
    rows = [
        {"source": relative_source(shots[n]), "path": str(shots[n]), "split": split, K.ANNOTATOR_TRUTH_MARK: mark,
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
        (dataset / "labels.json").write_text("{}")  # the first round built the dataset, from these inputs
        provenance = {"manifest_sha256": file_hash(manifest), "ledger_sha256": file_hash(K.ANNOTATOR_SPLIT_LEDGER)}
        (dataset / "metadata.json").write_text(json.dumps({**provenance, "truth_seeded": True}))

    found = [{"label": "map_node_vaal", "family": "node", "score": 0.9, "box": [281.0, 281.0, 319.0, 319.0]}]
    monkeypatch.setattr(simulate_loop.subprocess, "run", train)
    monkeypatch.setattr(simulate_loop, "predict", lambda detector, path: (found, (1920, 1080), (1920, 1080)))
    monkeypatch.setattr("grand_project.detect.rf_detr_model.load_detector", lambda model_dir: {})
    out = tmp_path / "sim"
    # a Vaal area map where both held-out screenshots show their node (1:1)
    truth.write_text(json.dumps({
        "maps": [[300.0, 300.0, "Vaal city"]], "biomes": [],
        "screenshots": [{"name": n, "file": f"{n}.png", "w": 1920, "h": 1080, "M": [[1, 0, 0], [0, 1, 0]],
                         "horizon": None} for n in ("val", "tst")],
    }))  # fmt: skip
    args = ["--manifest", str(manifest), "--classical-store", str(review_store.path), "--rounds", "0;1",
            "--atlas", name, "--truth", str(truth), "--output-dir", str(out), "--epochs", "2"]  # fmt: skip
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


def test_gold_counts_only_nodes_the_truth_has_a_map_for_and_silver_is_against_classical() -> None:
    """A node box at no truth map kept its classical class in the reference: no gold edit either way. Silver
    compares with the classical boxes, not the reference (a reference box the classical detector never had is no
    silver edit of a policy that lacks it too)."""
    reference = [_box("map_node_vaal", 300, 300), _box("map_node_ezomyte", 600, 300), _box("tower", 900, 300, 60)]
    prelabels = [_box("map_node_grass", 300, 300), _box("map_node_grass", 600, 300)]
    baseline = [_box("map_node_grass", 300, 300), _box("map_node_grass", 600, 300)]
    known = lambda box: box["bbox"][0] < 450  # noqa: E731 - the truth has a map at the first node only
    result = score(prelabels, reference, baseline, known=known)
    assert (result["gold"].relabelled, result["gold"].kept) == (1, 0)
    assert result["silver"].edits == 0  # the tower is the reference's alone: nothing against classical


def test_a_dataset_is_reused_only_when_built_from_the_same_inputs(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    write_ledger([Entry("sha", "train", "", "a.png")])
    dataset = tmp_path / "dataset"
    assert not dataset_matches(dataset, manifest)  # none yet
    dataset.mkdir()
    (dataset / "labels.json").write_text("{}")
    meta = {"manifest_sha256": file_hash(manifest), "ledger_sha256": file_hash(K.ANNOTATOR_SPLIT_LEDGER)}
    (dataset / "metadata.json").write_text(json.dumps({**meta, "truth_seeded": True}))
    assert dataset_matches(dataset, manifest)
    (dataset / "metadata.json").write_text(json.dumps({**meta, "truth_seeded": False}))
    assert not dataset_matches(dataset, manifest)  # built without the truth-seeded screenshots
    (dataset / "metadata.json").write_text(json.dumps({**meta, "truth_seeded": True}))
    manifest.write_text('{"images": []}')
    assert not dataset_matches(dataset, manifest)  # another export
