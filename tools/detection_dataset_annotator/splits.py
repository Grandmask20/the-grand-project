"""Train / validation / test splits of the exported screenshots (user's design), kept once given.

1. Screenshots are binned by how many boxes they export (quantiles, ``ANNOTATOR_SPLIT_BINS``), so every split holds
   screenshots as busy as the others (the model's queries must cover the busiest ones).
2. Bin by bin, from the quietest to the busiest, the screenshots without a split are drawn in random order to the
   split missing the largest part of its share so far (``ANNOTATOR_SPLIT_FRACTIONS``; screenshots that have a split
   count too),
   so every split gets screenshots of every busyness in its share, even when there are few screenshots.
3. Seeded swaps of two such screenshots of one bin between two splits are kept while they bring every class's
   spread across the splits closer to the split shares (each class counts the same, whatever its size), so rare
   classes are represented in every split too. A swap keeps the bins' counts.

Screenshots keep their split from one export to the next (the store remembers it): a later model never trains on an
earlier model's test screenshots. Pinned screenshots (``ANNOTATOR_SPLIT_PINNED_TEST``: the hand truth and the
reference atlases the detector scores are measured on) are always test.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np

from . import constants as K


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


def assign_splits(
    items: Mapping[str, Mapping[str, int]],
    *,
    fractions: tuple[float, ...] = K.ANNOTATOR_SPLIT_FRACTIONS,
    seed: int = K.ANNOTATOR_SPLIT_SEED,
    pinned: Mapping[str, str] | None = None,
    fixed: Mapping[str, str] | None = None,
    bins: int = K.ANNOTATOR_SPLIT_BINS,
    rounds: int = K.ANNOTATOR_SPLIT_ROUNDS,
) -> dict[str, str]:
    """Give every screenshot a split.

    Args:
        items: image key -> {class: exported boxes of it} for every screenshot to split.
        fractions: each split's share, in ``ANNOTATOR_SPLITS`` order.
        seed: the random draw's seed.
        pinned: image key -> split it must be in (wins over ``fixed``).
        fixed: image key -> split it already has (kept).
        bins: box-count bins.
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
    pinned, fixed = dict(pinned or {}), dict(fixed or {})
    classes = sorted({name for counts in items.values() for name in counts})
    counts = np.array([[items[key].get(name, 0) for name in classes] for key in keys], float).reshape(len(keys), -1)
    totals = counts.sum(axis=1)
    bin_of = _bins(totals, bins)
    split_of = np.full(len(keys), -1)
    for i, key in enumerate(keys):
        given = pinned.get(key) or fixed.get(key)
        if given in names:
            split_of[i] = names.index(given)
    free = split_of < 0
    rng = random.Random(seed)
    share = np.asarray(fractions, float)
    # Bins from the quietest screenshots to the busiest; in each, the screenshots that have a split count first, then
    # the others in random order, each to the split furthest below its share so far: every split gets screenshots of
    # every busyness, in its share, however few screenshots there are.
    have = np.zeros(len(names))
    for b in np.unique(bin_of):
        members = [int(i) for i in np.nonzero(bin_of == b)[0]]
        for i in members:
            if not free[i]:
                have[split_of[i]] += 1
        todo = [i for i in members if free[i]]
        rng.shuffle(todo)
        for i in todo:
            target = share * (have.sum() + 1)
            # the share of its target each split still misses: small splits are not starved by a big one's lead
            missing = np.where(target > 0, (target - have) / np.maximum(target, 1e-9), -np.inf)
            split = int(np.argmax(missing))
            split_of[i] = split
            have[split] += 1

    # refine: swaps of two free screenshots of one bin between two splits, kept while they lower the error
    per_split = np.zeros((len(names), len(classes)))
    for i, split in enumerate(split_of):
        per_split[split] += counts[i]
    class_total = counts.sum(axis=0)
    targets = share[:, None] * class_total[None, :]
    scale = np.maximum(class_total, 1.0)[None, :]
    by_bin = {int(b): [int(i) for i in np.nonzero((bin_of == b) & free)[0]] for b in np.unique(bin_of)}
    swappable = [b for b, members in by_bin.items() if len({int(split_of[i]) for i in members}) > 1]
    error = _error(per_split, targets, scale)
    for _ in range(rounds if swappable and classes else 0):
        members = by_bin[rng.choice(swappable)]
        i, j = rng.sample(members, 2) if len(members) >= 2 else (members[0], members[0])
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
    return {key: names[int(split_of[i])] for i, key in enumerate(keys)}


def split_report(items: Mapping[str, Mapping[str, int]], splits: Mapping[str, str]) -> str:
    """Per split: screenshots, boxes per screenshot, and each class's share of its boxes against the split's share."""
    names = list(K.ANNOTATOR_SPLITS)
    classes = sorted({name for counts in items.values() for name in counts})
    shots = {s: [k for k in items if splits.get(k) == s] for s in names}
    lines = ["split        shots  boxes/shot"]
    for s in names:
        boxes = [sum(items[k].values()) for k in shots[s]]
        mean = float(np.mean(boxes)) if boxes else 0.0
        lines.append(f"{s:<11} {len(shots[s]):6d}  {mean:10.1f}")
    lines.append("class share per split (" + " / ".join(names) + ")")
    for name in classes:
        per = [sum(items[k].get(name, 0) for k in shots[s]) for s in names]
        total = sum(per)
        shares = " / ".join(f"{p / total:4.0%}" if total else "  - " for p in per)
        lines.append(f"  {name:<24} {total:7d}  {shares}")
    return "\n".join(lines)


__all__ = ["assign_splits", "pinned_split", "split_report"]
