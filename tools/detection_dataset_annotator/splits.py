"""Train / validation / test splits of the exported screenshots (user's design), kept once given.

The splits draw blocks of screenshots, not single ones (``blocks.py``: an atlas's screenshots overlap, so a block
holds the screenshots of one part of an atlas and goes to one split whole; a screenshot no atlas places is a block of
its own).

1. Blocks are binned by their boxes per screenshot (quantiles, ``ANNOTATOR_SPLIT_BINS``), so every split holds
   screenshots as busy as the others (the model's queries must cover the busiest ones).
2. Bin by bin, from the quietest to the busiest, the blocks without a split are drawn in random order to the split
   missing the largest part of its share of screenshots so far (``ANNOTATOR_SPLIT_FRACTIONS``; screenshots that
   have a split count too), so every split gets screenshots of every busyness in its share, even when there are few.
3. Seeded swaps of two such blocks of one bin between two splits are kept while they bring every class's spread
   across the splits closer to the split shares (each class counts the same, whatever its size), and the splits'
   screenshots and each atlas's screenshots too (so uneven blocks keep the shares, and every atlas reaches every
   split).

Screenshots keep their split from one export to the next (the store and the split ledger keep it, the ledger by the
screenshot's bytes: ``split_ledger.py``): a later model never trains on an earlier model's validation or test
screenshots. A block takes the split of a pinned member (``ANNOTATOR_SPLIT_PINNED_TEST``: the hand truth and the
reference atlases the detector scores are measured on, always test), else the one most of its members already have;
its members that have a split keep it.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np

from . import constants as K
from .blocks import Block


def pinned_split(path: str | Path, roots: Iterable[Path] = K.ANNOTATOR_SPLIT_PINNED_TEST) -> str | None:
    """ "test" for a screenshot under one of the pinned roots, else None."""
    resolved = Path(path).resolve()
    for root in roots:
        root = Path(root).resolve()
        if resolved == root or resolved.is_relative_to(root):
            return "test"
    return None


def _bins(totals: np.ndarray, bins: int) -> np.ndarray:
    """The bin of each screenshot by its box count (quantile edges; equal counts share a bin)."""
    if len(totals) == 0:
        return np.zeros(0, int)
    edges = np.unique(np.quantile(totals, np.linspace(0, 1, bins + 1)[1:-1]))
    return np.searchsorted(edges, totals, side="right")


def _error(totals: np.ndarray, targets: np.ndarray, scale: np.ndarray) -> float:
    """How far the classes' spread over the splits is from the split shares (squared, each class weighted alike)."""
    return float((((totals - targets) / scale) ** 2).sum())


def _block_split(members: list[str], pinned: Mapping[str, str], fixed: Mapping[str, str], names: list[str]) -> int:
    """A block's split: a pinned member's, else the one most of its members have (ties: the first split), else -1."""
    for key in members:
        if pinned.get(key) in names:
            return names.index(pinned[key])
    kept = Counter(names.index(fixed[key]) for key in members if fixed.get(key) in names)
    return min(kept, key=lambda split: (-kept[split], split)) if kept else -1


def assign_splits(
    items: Mapping[str, Mapping[str, int]],
    *,
    fractions: tuple[float, ...] = K.ANNOTATOR_SPLIT_FRACTIONS,
    seed: int = K.ANNOTATOR_SPLIT_SEED,
    pinned: Mapping[str, str] | None = None,
    fixed: Mapping[str, str] | None = None,
    blocks: Mapping[str, Block] | None = None,
    atlases: Mapping[str, str] | None = None,
    bins: int = K.ANNOTATOR_SPLIT_BINS,
    rounds: int = K.ANNOTATOR_SPLIT_ROUNDS,
) -> dict[str, str]:
    """Give every screenshot a split.

    Args:
        items: image key -> {class: boxes of it} for every screenshot to split.
        fractions: each split's share, in ``ANNOTATOR_SPLITS`` order.
        seed: the random draw's seed.
        pinned: image key -> split it must be in (wins over ``fixed``, and takes its block along).
        fixed: image key -> split it already has (kept).
        blocks: image key -> its block (``blocks.screenshot_blocks``); a key without one is a block of its own.
        atlases: image key -> the atlas it belongs to, for each atlas's balance (default its block's): a copy joined
            into another atlas's block (``split_ledger.join_blocks``) moves with that block but counts for its own.
        bins: bins of boxes per screenshot.
        rounds: swaps tried in the refinement.

    Returns:
        Image key -> split, for every key of ``items``.
    """
    names = list(K.ANNOTATOR_SPLITS)
    if len(fractions) != len(names) or not np.isclose(sum(fractions), 1.0) or min(fractions) < 0:
        raise ValueError(f"fractions must be {len(names)} shares adding up to 1: {fractions}")
    keys = sorted(items)  # sorted: the same screenshots give the same draw whatever order they come in
    if not keys:
        return {}
    pinned, fixed, blocks = dict(pinned or {}), dict(fixed or {}), dict(blocks or {})
    block_of = {key: blocks.get(key, Block(key)) for key in keys}
    atlas_of = {key: (atlases or {}).get(key, block_of[key].atlas) for key in keys}
    groups = sorted(set(block_of.values()))
    index = {block: i for i, block in enumerate(groups)}
    members: list[list[str]] = [[] for _ in groups]
    for key in keys:
        members[index[block_of[key]]].append(key)
    size = np.array([len(m) for m in members], float)

    # What the splits balance, per block: its boxes of every class, its screenshots, and its screenshots under the
    # name of its atlas (atlases of several blocks: each atlas reaches every split).
    classes = sorted({name for counts in items.values() for name in counts})
    spread: dict[str, set[Block]] = {}  # each atlas's blocks, by its own screenshots
    for key in keys:
        spread.setdefault(atlas_of[key], set()).add(block_of[key])
    balanced = sorted(atlas for atlas, its_blocks in spread.items() if len(its_blocks) > 1)
    row: dict[str, np.ndarray] = {}  # per screenshot: its boxes of every class, 1 screenshot, 1 of its atlas
    for key in keys:
        row[key] = np.zeros(len(classes) + 1 + len(balanced))
        for c, name in enumerate(classes):
            row[key][c] = items[key].get(name, 0)
        row[key][len(classes)] = 1
        if atlas_of[key] in balanced:
            row[key][len(classes) + 1 + balanced.index(atlas_of[key])] = 1
    counts = np.array([sum((row[key] for key in keys_of), np.zeros(len(row[keys[0]]))) for keys_of in members])
    bin_of = _bins(counts[:, : len(classes)].sum(axis=1) / size, bins)
    split_of = np.array([_block_split(m, pinned, fixed, names) for m in members])
    free = split_of < 0

    def own_split(key: str, block: int) -> int:
        """The split a screenshot ends in: its pinned one, else the one it has, else its block's."""
        given = pinned.get(key) if pinned.get(key) in names else fixed.get(key)
        return names.index(given) if given in names else int(split_of[block])

    rng = random.Random(seed)
    share = np.asarray(fractions, float)
    # Bins from the quietest blocks to the busiest; in each, the blocks that have a split count first (each member
    # in the split it keeps: a block's members can have different ones), then the others in random order, each to
    # the split furthest below its share of screenshots so far: every split gets screenshots of every busyness, in its
    # share, however few there are.
    have = np.zeros(len(names))
    for b in np.unique(bin_of):
        in_bin = [int(g) for g in np.nonzero(bin_of == b)[0]]
        for g in in_bin:
            if not free[g]:
                for key in members[g]:
                    have[own_split(key, g)] += 1
        todo = [g for g in in_bin if free[g]]
        rng.shuffle(todo)
        for g in todo:
            target = share * (have.sum() + size[g])
            # the share of its target each split still misses: small splits are not starved by a big one's lead
            missing = np.where(target > 0, (target - have) / np.maximum(target, 1e-9), -np.inf)
            split = int(np.argmax(missing))
            split_of[g] = split
            have[split] += size[g]

    # refine: swaps of two free blocks of one bin between two splits, kept while they lower the error (a free block's
    # members all follow it, so a swap moves its counts whole)
    per_split = np.zeros((len(names), counts.shape[1]))
    for g, keys_of in enumerate(members):
        for key in keys_of:
            per_split[own_split(key, g)] += row[key]
    column_total = counts.sum(axis=0)
    targets = share[:, None] * column_total[None, :]
    scale = np.maximum(column_total, 1.0)[None, :]
    by_bin = {int(b): [int(g) for g in np.nonzero((bin_of == b) & free)[0]] for b in np.unique(bin_of)}
    swappable = [b for b, in_bin in by_bin.items() if len({int(split_of[g]) for g in in_bin}) > 1]
    error = _error(per_split, targets, scale)
    for _ in range(rounds if swappable else 0):
        in_bin = by_bin[rng.choice(swappable)]
        i, j = rng.sample(in_bin, 2) if len(in_bin) >= 2 else (in_bin[0], in_bin[0])
        a, b = int(split_of[i]), int(split_of[j])
        if a == b:
            continue
        diff = counts[j] - counts[i]
        trial = per_split.copy()
        trial[a] += diff
        trial[b] -= diff
        new_error = _error(trial, targets, scale)
        if new_error < error - 1e-12:
            per_split, error = trial, new_error
            split_of[i], split_of[j] = b, a
    return {key: names[own_split(key, index[block_of[key]])] for key in keys}


def split_report(
    items: Mapping[str, Mapping[str, int]], splits: Mapping[str, str], blocks: Mapping[str, Block] | None = None
) -> str:
    """Per split: screenshots, blocks, boxes per screenshot, and each class's share of its boxes against the split's
    share."""
    names = list(K.ANNOTATOR_SPLITS)
    blocks = dict(blocks or {})
    classes = sorted({name for counts in items.values() for name in counts})
    shots = {s: [k for k in items if splits.get(k) == s] for s in names}
    lines = ["split        shots  blocks  boxes/shot"]
    for s in names:
        boxes = [sum(items[k].values()) for k in shots[s]]
        mean = float(np.mean(boxes)) if boxes else 0.0
        count = len({blocks.get(k, Block(k)) for k in shots[s]})
        lines.append(f"{s:<11} {len(shots[s]):6d}  {count:6d}  {mean:10.1f}")
    lines.append("class share per split (" + " / ".join(names) + ")")
    for name in classes:
        per = [sum(items[k].get(name, 0) for k in shots[s]) for s in names]
        total = sum(per)
        shares = " / ".join(f"{p / total:4.0%}" if total else "  - " for p in per)
        lines.append(f"  {name:<24} {total:7d}  {shares}")
    return "\n".join(lines)


__all__ = ["assign_splits", "pinned_split", "split_report"]
