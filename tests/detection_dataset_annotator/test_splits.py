"""Train / validation / test splits (tools/detection_dataset_annotator/splits.py), the user's design: blocks of
screenshots binned by boxes per screenshot, drawn at random within the bins, refined so every class spreads over the
splits."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.blocks import Block
from tools.detection_dataset_annotator.splits import assign_splits, pinned_split, split_report


def _items(count: int, seed: int = 0) -> dict[str, dict[str, int]]:
    """Screenshots with 20-200 node boxes, icons on most, a rare class on one in ten."""
    rng = random.Random(seed)
    items = {}
    for i in range(count):
        counts = {"map_node_grass": rng.randint(20, 200), "icon": rng.randint(0, 40)}
        if i % 10 == 0:
            counts["reveal_button"] = 1
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
    rare = [splits[k] for k, counts in items.items() if "reveal_button" in counts]
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


def _blocked(seed: int = 0) -> tuple[dict[str, dict[str, int]], dict[str, Block]]:
    """Two atlases cut into uneven blocks (1-12 screenshots), plus loose screenshots of no atlas."""
    rng = random.Random(seed)
    items = _items(400, seed)
    keys = sorted(items)
    blocks: dict[str, Block] = {}
    at = 0
    for atlas, count in (("roa", 260), ("fr", 110)):
        index = 0
        while count > 0 and at < len(keys):
            size = min(count, rng.randint(1, 12))
            for key in keys[at : at + size]:
                blocks[key] = Block(atlas, index)
            at, count, index = at + size, count - size, index + 1
    return items, blocks


def test_a_block_goes_to_one_split_and_the_shares_hold() -> None:
    """Uneven blocks still give about 80/10/10 screenshots, and every atlas reaches every split."""
    items, blocks = _blocked()
    splits = assign_splits(items, blocks=blocks)
    by_block: dict[Block, set[str]] = {}
    for key, block in blocks.items():
        by_block.setdefault(block, set()).add(splits[key])
    assert all(len(found) == 1 for found in by_block.values())
    counts = {name: list(splits.values()).count(name) for name in K.ANNOTATOR_SPLITS}
    assert abs(counts["train"] - 320) <= 8 and abs(counts["validation"] - 40) <= 8 and abs(counts["test"] - 40) <= 8
    for atlas in ("roa", "fr"):
        assert {splits[k] for k, block in blocks.items() if block.atlas == atlas} == set(K.ANNOTATOR_SPLITS)
    assert "blocks" in split_report(items, splits, blocks)


def test_a_pinned_screenshot_takes_its_block_and_kept_splits_stay() -> None:
    """A block takes a pinned member's split, else most of its members' kept ones; a member that has a split keeps
    it (the store never moves a screenshot)."""
    items, blocks = _blocked(1)
    members: dict[Block, list[str]] = {}
    for key in sorted(blocks):
        members.setdefault(blocks[key], []).append(key)
    pinned_block, kept_block = [block for block, keys in members.items() if len(keys) >= 3][:2]
    pinned = {members[pinned_block][0]: "test"}
    kept = members[kept_block]
    # one member already in train, two in validation, the rest without a split: the rest go to validation
    fixed = {kept[0]: "train", kept[1]: "validation", kept[2]: "validation"}
    splits = assign_splits(items, blocks=blocks, pinned=pinned, fixed=fixed)
    assert {splits[key] for key in members[pinned_block]} == {"test"}
    assert splits[kept[0]] == "train"
    assert {splits[key] for key in kept[1:]} == {"validation"}


def test_block_splits_are_deterministic() -> None:
    items, blocks = _blocked(2)
    assert assign_splits(items, blocks=blocks, seed=5) == assign_splits(items, blocks=blocks, seed=5)
