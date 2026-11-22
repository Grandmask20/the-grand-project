"""Cleaning map node boxes from hand-checked map node positions (tools/detection_dataset_annotator/node_truth.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.detection_dataset_annotator import ReviewStore, node_truth
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.node_truth import NodeTruth, seed_nodes, seed_store_nodes
from tools.detection_dataset_annotator.state import image_key


def _box(label: str, x: float, y: float, source: str = "classical", size: float = 38.7) -> dict[str, Any]:
    return {"label": label, "bbox": [x - size / 2, y - size / 2, size, size], "source": source}


def _boxes() -> list[dict[str, Any]]:
    return [
        _box("map_node_grass", 300, 300),  # checked: kept
        _box("map_node_desert", 500, 300, "biome_guess"),  # on the sheet, checked as none: deleted
        _box("map_node", 10, 300),  # at the edge, never on the sheet: kept
        _box("map_node", 700, 300, K.ANNOTATOR_HIDDEN_SOURCE),  # hidden under an icon row: kept
        _box("icon", 300, 270, size=34.0),
    ]


TRUTH = np.array([[300.0, 300.0]])
JUDGED = np.array([[300.0, 300.0], [501.0, 299.0]])


def test_only_map_nodes_the_sheet_showed_and_nobody_checked_are_deleted():
    boxes, done, complete = seed_nodes(_boxes(), TRUTH, JUDGED)
    assert complete and boxes is not None
    assert [(b["label"], b["source"]) for b in boxes] == [
        ("map_node_grass", "classical"),
        ("map_node", "classical"),
        ("map_node", K.ANNOTATOR_HIDDEN_SOURCE),
        ("icon", "classical"),
    ]
    assert done["map node checked as none: deleted"] == 1


def test_a_checked_position_with_no_box_leaves_the_screenshot_alone():
    boxes, done, complete = seed_nodes(_boxes(), np.array([[300.0, 300.0], [900.0, 900.0]]), JUDGED)
    assert boxes is None and not complete
    assert done["checked position with no map node box (left alone)"] == 1


def test_boxes_of_a_larger_screenshot_are_measured_at_1080p():
    """A 4K screenshot's boxes are twice as far out as the 1080p positions."""
    big = [_box("map_node", 600, 600, size=77.4), _box("map_node", 1000, 600, size=77.4)]
    boxes, _done, complete = seed_nodes(big, TRUTH, JUDGED, scale=2.0)
    assert complete and boxes is not None and len(boxes) == 1


def test_the_store_is_cleaned_and_marked_once(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "pre-change"
    folder.mkdir()
    paths = [folder / name for name in ("shot.png", "quiet.png", "reviewed.png", "elsewhere.png")]
    states = {p.name: [{"x": 300.0, "y": 300.0, "state": "blue"}] for p in paths[:3]}
    (folder / "states.json").write_text(json.dumps(states), encoding="utf-8")
    monkeypatch.setattr(node_truth, "judged_positions", lambda img: JUDGED)
    review_store.add_images(paths)
    for path in paths:
        boxes = _boxes() if path.name != "quiet.png" else [_box("map_node", 300, 300)]
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": boxes, "error": None}
        review_store.record_detection(image_key(path), result, force=True)
    reviewed = review_store.item(image_key(paths[2]))
    review_store.save_review(image_key(paths[2]), reviewed["edit_version"], reviewed=True)
    truth = NodeTruth.load([folder / "states.json"])
    image = lambda path: np.zeros((1080, 1920, 3), np.uint8)  # noqa: E731

    done, changed, listed = seed_store_nodes(review_store, truth, image=image)
    assert (changed, listed) == (1, 2)
    shot, quiet, reviewed, elsewhere = (review_store.item(image_key(p)) for p in paths)
    assert len(shot["annotations"]) == 4 and len(elsewhere["annotations"]) == 5 and len(reviewed["annotations"]) == 5
    assert shot[K.ANNOTATOR_TRUTH_MARK] == quiet[K.ANNOTATOR_TRUTH_MARK] == truth.marks[paths[0].resolve()]
    assert K.ANNOTATOR_TRUTH_MARK not in elsewhere and K.ANNOTATOR_TRUTH_MARK not in reviewed
    assert seed_store_nodes(review_store, truth, image=image)[1] == 0
