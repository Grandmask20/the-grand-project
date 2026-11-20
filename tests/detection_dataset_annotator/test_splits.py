"""Train / validation / test splits (tools/detection_dataset_annotator/splits.py), the user's design: binned by
boxes per screenshot, drawn at random within the bins, refined so every class spreads over the splits."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.splits import assign_splits, pinned_split, split_report


def _items(count: int, seed: int = 0) -> dict[str, dict[str, int]]:
    """Screenshots with 20-200 node boxes, icons on most, a rare class on one in ten."""
    rng = random.Random(seed)
    items = {}
    for i in range(count):
        counts = {"map_node_grass": rng.randint(20, 200), "icon": rng.randint(0, 40)}
        if i % 10 == 0:
            counts["locked_stronghold"] = 1
        items[f"shot{i:03d}"] = counts
    return items


def test_splits_are_deterministic_whatever_the_order() -> None:
    items = _items(60)
    reversed_items = dict(reversed(list(items.items())))
    assert assign_splits(items, seed=3) == assign_splits(reversed_items, seed=3)
    assert assign_splits(items, seed=3) != assign_splits(items, seed=4)


def test_split_shares_hold_in_every_box_count_bin() -> None:
    items = _items(400)
    splits = assign_splits(items)
    counts = {name: sum(1 for s in splits.values() if s == name) for name in K.ANNOTATOR_SPLITS}
    assert counts == {"train": 320, "validation": 40, "test": 40}
    # busy and quiet screenshots are in every split alike
    busy = {name: np.mean([sum(items[k].values()) for k, s in splits.items() if s == name]) for name in counts}
    assert max(busy.values()) - min(busy.values()) < 0.1 * np.mean(list(busy.values()))


def test_a_rare_class_reaches_every_split() -> None:
    """The refinement spreads each class as the split shares say (each class counts the same, however rare)."""
    items = _items(200)
    splits = assign_splits(items)
    rare = [splits[k] for k, counts in items.items() if "locked_stronghold" in counts]
    assert sorted(set(rare)) == ["test", "train", "validation"]
    assert rare.count("train") >= 14  # 80% of 20


def test_pinned_and_given_splits_never_move() -> None:
    items = _items(50)
    pinned = {"shot000": "test", "shot001": "test"}
    fixed = {"shot002": "validation", "shot003": "train", "shot000": "train"}  # pinned wins over given
    splits = assign_splits(items, pinned=pinned, fixed=fixed)
    assert splits["shot000"] == splits["shot001"] == "test"
    assert (splits["shot002"], splits["shot003"]) == ("validation", "train")
    with pytest.raises(ValueError, match="shares"):
        assign_splits(items, fractions=(0.5, 0.5, 0.5))
    assert assign_splits({}) == {}


def test_the_hand_truth_screenshots_are_pinned_to_test(tmp_path: Path) -> None:
    root = tmp_path / "truth"
    assert pinned_split(root / "a.png", roots=[root]) == "test"
    assert pinned_split(tmp_path / "other" / "a.png", roots=[root]) is None


def test_the_split_report_shows_shares_per_class() -> None:
    items = {"a": {"icon": 3}, "b": {"icon": 1, "hall": 1}}
    report = split_report(items, {"a": "train", "b": "test"})
    assert "icon" in report and "hall" in report and "train" in report


def test_a_small_export_still_has_every_split() -> None:
    """Ten screenshots, five of them the pinned hand truth: the others still give a validation screenshot (the
    trainer needs one), drawn by the shares so far rather than bin by bin."""
    items = _items(10)
    pinned = {key: "test" for key in list(items)[:5]}
    splits = assign_splits(items, pinned=pinned)
    assert {name: list(splits.values()).count(name) for name in K.ANNOTATOR_SPLITS} == {
        "train": 4,
        "validation": 1,
        "test": 5,
    }
