"""Seeding a hand-labelled atlas's screenshots from its biome truth (tools/detection_dataset_annotator/truth_seed.py):
city areas and citadels as the truth has them, the rest as the classical guess had it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from grand_project.detect import biomes
from grand_project.detect.biomes import BiomeGuess
from tools.detection_dataset_annotator import ReviewStore, truth_seed
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.state import image_key
from tools.detection_dataset_annotator.truth_seed import Truth, seed_screenshot, seed_store

TRUTH_SOURCE = K.ANNOTATOR_TRUTH_SOURCE


def _box(label: str, x: float, y: float, source: str = "classical", size: float = 40.0) -> dict[str, Any]:
    """A box of the given size centred on (x, y)."""
    return {"label": label, "bbox": [x - size / 2, y - size / 2, size, size], "source": source}


def _truth(tmp_path: Path, files: tuple[str, ...] = ("shot.png",)) -> Truth:
    """An atlas placed 1:1 on the screenshots (identity M, no tilt): a Vaal area map at (600, 500) with its City, a map
    outside every area at (900, 500), a Faridun area map at (1200, 500) whose City no citadel box shows."""
    data = {
        "maps": [[600.0, 500.0, "Vaal city"], [900.0, 500.0, ""], [1200.0, 500.0, "Faridun city"]],
        "biomes": [
            {"type": "Vaal city", "maps": [0], "city": {"x": 600.0, "y": 500.0, "assumed": False}},
            {"type": "Faridun city", "maps": [2], "city": {"x": 1200.0, "y": 500.0, "assumed": False}},
        ],
        "screenshots": [
            {"name": Path(f).stem, "file": f, "w": 1920, "h": 1080, "M": [[1, 0, 0], [0, 1, 0]], "horizon": None}
            for f in files
        ],
    }
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return Truth.load(path)


def _boxes() -> list[dict[str, Any]]:
    return [
        _box("map_node_grass", 600, 500),  # in the Vaal area: becomes a Vaal area node
        _box("map_node_ezomyte", 900, 500, "city_area_guess"),  # a city node outside every area: its ring again
        _box("map_node_faridun", 1200, 500),  # already right: only its source changes
        _box("map_node_water", 300, 300),  # at no truth map: left
        _box("citadel_iron", 610, 510, "city_guess"),  # in the Vaal area: becomes a Stone citadel
        _box("citadel_copper", 1500, 300),  # near no city area: a false City, deleted
        _box("breach_stronghold", 1500, 700, size=150.0),  # near no stronghold area: reported
        _box("icon", 600, 470, size=34.0),
    ]


@pytest.fixture
def desert_ring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ground ring sees an unsure desert (the module is read when the ring runs)."""
    monkeypatch.setattr(biomes, "node_biomes", lambda img, nodes, icons: [BiomeGuess("desert", False)] * len(nodes))


def test_a_screenshot_takes_the_truth_city_areas_and_citadels(tmp_path: Path, desert_ring: None) -> None:
    truth = _truth(tmp_path)
    item = {"path": str(tmp_path / "shot.png"), "width": 1920, "height": 1080, "annotations": _boxes()}
    boxes, done, complete = seed_screenshot(
        item, truth.screenshots["shot.png"], truth, lambda path: np.zeros((1080, 1920, 3), np.uint8)
    )
    assert boxes is not None and complete
    labelled = [(box["label"], box["source"]) for box in boxes]
    assert labelled == [
        ("map_node_vaal", TRUTH_SOURCE),
        ("map_node_desert", "biome_guess"),
        ("map_node_faridun", TRUTH_SOURCE),
        ("map_node_water", "classical"),
        ("citadel_stone", TRUTH_SOURCE),
        ("breach_stronghold", "classical"),
        ("icon", "classical"),
    ]
    assert done["citadel deleted (no city area)"] == 1 and done["citadel retyped"] == 1
    assert done["truth City without a citadel box (draw)"] == 1  # the Faridun one
    assert done["stronghold far from truth strongholds (check)"] == 1


def test_a_screenshot_twice_seeded_changes_no_more(tmp_path: Path, desert_ring: None) -> None:
    truth = _truth(tmp_path)
    item = {"path": str(tmp_path / "shot.png"), "width": 1920, "height": 1080, "annotations": _boxes()}
    image = np.zeros((1080, 1920, 3), np.uint8)
    boxes, _done, _complete = seed_screenshot(item, truth.screenshots["shot.png"], truth, lambda path: image)
    again, _done, _complete = seed_screenshot(
        {**item, "annotations": boxes}, truth.screenshots["shot.png"], truth, lambda p: image
    )
    assert again is None


def test_the_store_is_seeded_but_reviewed_screenshots_are_left(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only unreviewed screenshots the truth places are changed; a second run changes nothing."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    paths = [tmp_path / name for name in ("shot.png", "reviewed.png", "elsewhere.png")]
    truth = _truth(tmp_path, files=("shot.png", "reviewed.png"))
    review_store.add_images(paths)
    for path in paths:
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    reviewed = review_store.item(image_key(paths[1]))
    assert reviewed is not None
    review_store.save_review(image_key(paths[1]), reviewed["edit_version"], reviewed=True)

    done, changed, placed = seed_store(review_store, truth)
    assert (changed, placed) == (1, 1)
    assert done["node -> Vaal area"] == 1
    labels = [box["label"] for box in review_store.item(image_key(paths[0]))["annotations"]]
    assert "citadel_copper" not in labels and "citadel_stone" in labels
    for untouched in paths[1:]:
        assert [box["label"] for box in review_store.item(image_key(untouched))["annotations"]] == [
            box["label"] for box in _boxes()
        ]
    assert seed_store(review_store, truth)[1] == 0


def test_every_screenshot_the_truth_places_is_marked(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The truth vouches for a placed screenshot's city areas whether it changed a box or not, so every one carries
    its mark (a truth-seeded training round takes them); changed boxes are the screenshot's new pre-labels."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    paths = [tmp_path / name for name in ("shot.png", "quiet.png", "elsewhere.png")]
    truth = _truth(tmp_path, files=("shot.png", "quiet.png"))
    review_store.add_images(paths)
    for path, boxes in zip(paths, (_boxes(), [_box("icon", 300, 300, size=34.0)], _boxes()), strict=True):
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": boxes, "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    _done, changed, placed = seed_store(review_store, truth)
    assert (changed, placed) == (1, 2)
    seeded, quiet, elsewhere = (review_store.item(image_key(path)) for path in paths)
    assert seeded[K.ANNOTATOR_TRUTH_MARK] == quiet[K.ANNOTATOR_TRUTH_MARK] == truth.source
    assert K.ANNOTATOR_TRUTH_MARK not in elsewhere
    assert review_store.prelabels(image_key(paths[0])) == seeded["annotations"]  # what a reviewer is first shown
    assert seed_store(review_store, truth)[1] == 0


def test_a_screenshot_without_boxes_still_counts_the_cities_to_draw(tmp_path: Path) -> None:
    """Nothing to seed, but the truth's Cities it shows (Vaal at 600, Faridun at 1200) are still to draw."""
    item = {"path": str(tmp_path / "shot.png"), "width": 1920, "height": 1080, "annotations": []}
    truth = _truth(tmp_path)
    boxes, done, complete = seed_screenshot(item, truth.screenshots["shot.png"], truth, lambda path: None)
    assert (boxes, complete) == (None, True)
    assert done["truth City without a citadel box (draw)"] == 2


def test_a_file_name_of_two_screenshots_is_left_alone(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The truth names its screenshots by file name only: of two different screenshots of one name in two folders
    neither is known to be its (byte copies are one screenshot: the build_store tests seed those)."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    paths = [tmp_path / "a" / "shot.png", tmp_path / "b" / "shot.png"]
    for index, path in enumerate(paths):
        path.parent.mkdir()
        path.write_bytes(bytes([index]))
    review_store.add_images(paths)
    for path in paths:
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    done, changed, _placed = seed_store(review_store, _truth(tmp_path))
    assert changed == 0
    assert done["skipped: its file name is another screenshot's too (which one the truth means is unknown)"] == 2
    assert all(K.ANNOTATOR_TRUTH_MARK not in review_store.item(image_key(path)) for path in paths)


def test_a_box_without_a_place_is_left(tmp_path: Path) -> None:
    """A box stored without a place (NaN is stored as NULL) is kept as it is, as the editor and export skip it."""
    truth = _truth(tmp_path)
    nowhere = {"label": "map_node_vaal", "bbox": [None, None, None, None], "source": "classical"}
    item = {"path": str(tmp_path / "shot.png"), "width": 1920, "height": 1080, "annotations": [nowhere]}
    assert seed_screenshot(item, truth.screenshots["shot.png"], truth, lambda path: None)[0] is None
    # nor taken to the atlas's corner (cv2.perspectiveTransform makes a NaN point (0, 0)): a citadel there would be a
    # false City, deleted
    item["annotations"] = [{"label": "citadel_copper", "bbox": [None, None, None, None], "source": "classical"}]
    assert seed_screenshot(item, truth.screenshots["shot.png"], truth, lambda path: None)[0] is None


def test_a_screenshot_that_cannot_be_read_is_left_unmarked_until_it_can(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A city node outside every area needs its ground ring: without the picture the screenshot is not the truth's
    yet, so it gets neither boxes nor mark (a truth-seeded round would take it), and the next run seeds it."""
    path = tmp_path / "shot.png"
    truth = _truth(tmp_path)
    review_store.add_images([path])
    result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
    review_store.record_detection(image_key(path), result, force=True)
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: None)
    done, changed, _placed = seed_store(review_store, truth)
    item = review_store.item(image_key(path))
    assert (
        changed == 0
        and K.ANNOTATOR_TRUTH_MARK not in item
        and done["unreadable screenshot (city nodes left, not marked)"]
    )
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    assert seed_store(review_store, truth)[1] == 1
    assert review_store.item(image_key(path))[K.ANNOTATOR_TRUTH_MARK] == truth.source


def test_an_edit_made_while_seeding_ran_is_kept(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewer edits the screenshot after seeding read it (the page open beside it): the edit stays, unmarked."""
    path = tmp_path / "shot.png"
    truth = _truth(tmp_path)
    review_store.add_images([path])
    key = image_key(path)
    result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
    review_store.record_detection(key, result, force=True)
    edit = [_box("tower", 800, 300, source=K.ANNOTATOR_MANUAL_SOURCE) | {"id": "b0"}]

    def read_while_edited(path: Path) -> np.ndarray:
        assert review_store.save_review(key, 1, annotations=edit)
        return np.zeros((1080, 1920, 3), np.uint8)

    monkeypatch.setattr(truth_seed, "_detector_image", read_while_edited)
    done, changed, _placed = seed_store(review_store, truth)
    item = review_store.item(key)
    assert changed == 0 and done["skipped: reviewed, edited or detected again meanwhile"] == 1
    assert [box["label"] for box in item["annotations"]] == ["tower"] and K.ANNOTATOR_TRUTH_MARK not in item
    # the corrections the save would have made are not counted; what the screenshot shows still is
    assert done["node -> Vaal area"] == 0 and done["citadel deleted (no city area)"] == 0
    assert done["truth City without a citadel box (draw)"] == 1


def test_a_screenshot_another_truth_seeded_is_left(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its boxes are that truth's: seeding over them would mix two truths, so it is left (rerun its detection
    first); a screenshot this truth seeded before is seeded again as usual."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    path = tmp_path / "shot.png"
    truth = _truth(tmp_path)
    review_store.add_images([path])
    key = image_key(path)
    result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
    review_store.record_detection(key, result, force=True)
    assert review_store.save_review(key, 1, extra={K.ANNOTATOR_TRUTH_MARK: "other/truth.json"})
    done, changed, _placed = seed_store(review_store, truth)
    assert changed == 0 and any("seeded by another truth (other/truth.json)" in what for what in done)
    item = review_store.item(key)
    assert item[K.ANNOTATOR_TRUTH_MARK] == "other/truth.json" and item["annotations"][0]["label"] == "map_node_grass"
    assert review_store.save_review(key, 1, extra={K.ANNOTATOR_TRUTH_MARK: None})  # no mark: seeded
    assert seed_store(review_store, truth)[1] == 1


def test_a_name_with_an_unreadable_file_is_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that cannot be hashed is not known to be the other's copy (and stops nothing); readable copies are one."""
    paths = [tmp_path / "a" / "shot.png", tmp_path / "b" / "shot.png"]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"same")
    assert not truth_seed._ambiguous(paths)
    real = truth_seed.file_hash

    def file_hash(path: Path) -> str:
        if path == paths[1]:
            raise PermissionError(path)
        return real(path)

    monkeypatch.setattr(truth_seed, "file_hash", file_hash)
    assert truth_seed._ambiguous(paths)


def test_a_name_in_another_atlas_folder_is_not_the_truths(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The truth names its screenshots by file name only: of two of one name, the one below the truth's own folder is
    seeded and marked, the other atlas's is left unchanged and unmarked."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    atlas = tmp_path / "atlas"
    mine, other = atlas / "shots" / "shot.png", tmp_path / "other" / "shot.png"
    for index, path in enumerate((mine, other)):
        path.parent.mkdir(parents=True)
        path.write_bytes(bytes([index]))
    review_store.add_images([mine, other])
    for path in (mine, other):
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    truth = _truth(atlas)
    done, changed, placed = seed_store(review_store, truth)
    assert (changed, placed) == (1, 1)
    assert review_store.item(image_key(mine))[K.ANNOTATOR_TRUTH_MARK] == truth.source
    left = review_store.item(image_key(other))
    assert K.ANNOTATOR_TRUTH_MARK not in left and left["annotations"] == review_store.prelabels(image_key(other))
    assert sum(count for what, count in done.items() if what.startswith("skipped: a truth file name outside")) == 1
    assert Truth.load(atlas / "truth.json", tmp_path / "other").places(other)  # --screenshots: another folder


def test_a_dry_run_without_a_store_makes_none(tmp_path: Path, capsys) -> None:
    _truth(tmp_path)
    out = tmp_path / "dataset"
    assert truth_seed.main([str(tmp_path / "truth.json"), "--output-dir", str(out), "--dry-run"]) == 0
    assert "nothing to seed" in capsys.readouterr().out
    assert not out.exists()


def test_a_dry_run_counts_only_screenshots_the_save_would_take(
    tmp_path: Path, review_store: ReviewStore, desert_ring: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreviewed screenshot a reviewer already edited keeps its boxes: a dry run does not count it as a change."""
    monkeypatch.setattr(truth_seed, "_detector_image", lambda path: np.zeros((1080, 1920, 3), np.uint8))
    paths = [tmp_path / name for name in ("shot.png", "edited.png")]
    truth = _truth(tmp_path, files=("shot.png", "edited.png"))
    review_store.add_images(paths)
    for path in paths:
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": _boxes(), "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    edited = review_store.item(image_key(paths[1]))
    boxes = [dict(box, source="manual") for box in edited["annotations"]]
    assert review_store.save_review(image_key(paths[1]), edited["edit_version"], annotations=boxes)
    assert seed_store(review_store, truth, dry_run=True)[1] == 1
    assert seed_store(review_store, truth)[1] == 1  # the real run takes the same one
