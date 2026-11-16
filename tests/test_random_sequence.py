"""Randomised placement test: random runs of crawl screenshots that are known to line up, plus one decoy from far
away on the atlas, built into fresh atlases from the cached detections.

Each run must place every chained screenshot where the full crawl atlas (or direct terrain matching) puts it, and
must NOT merge the decoy anywhere (it shares nothing with the run).

    pytest tests/test_random_sequence.py [--runs 6] [--seed N]
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from grand_project import builder as B
from grand_project import core as C

pytestmark = pytest.mark.data

TOL = 10.0  # atlas units: terrain matching and map placement differ by 2-8 on raised ground (parallax); real
# placement errors are tens of units
LINK_MAX = 650.0  # atlas units between two consecutive crawl shots that surely overlap (screens are 1920 wide)
DECOY_MIN = 4000.0  # a decoy is at least this far from every screenshot of the run
LENGTH = 3  # screenshots in a run


def chains(shots: list[Path], pos: dict, length: int) -> list[int]:
    """Where runs of linked screenshots start.

    Args:
        shots: crawl screenshots in time order.
        pos: {screenshot name: (x, y) atlas position} from the finished crawl atlas.
        length: screenshots in a run.

    Returns:
        Start indexes of runs of `length` consecutive shots where every neighbouring pair overlaps.
    """
    linked = [np.hypot(*(pos[b.stem] - pos[a.stem])) <= LINK_MAX for a, b in zip(shots, shots[1:], strict=False)]
    return [k for k in range(len(shots) - length + 1) if all(linked[k : k + length - 1])]


def test_linked_screenshots_placed_and_decoy_kept_out(crawl, rng, runs, seed, copy_cache, tmp_path):
    """Every linked screenshot placed within TOL (in order or reversed), the far decoy never merged."""
    starts = chains(crawl.shots, crawl.pos, LENGTH)
    assert starts, "no run of linked screenshots in the test data"
    failed = []
    for run in range(runs(6)):
        k = rng.choice(starts)
        seq = crawl.shots[k : k + LENGTH]
        if rng.random() < 0.5:
            seq = seq[::-1]  # also test reverse order
        far = [
            p for p in crawl.shots if min(np.hypot(*(crawl.pos[p.stem] - crawl.pos[s.stem])) for s in seq) >= DECOY_MIN
        ]
        decoy = rng.choice(far) if far else None
        order = list(seq)
        if decoy is not None:
            order.insert(rng.randrange(1, len(order) + 1), decoy)  # after the first (the first one is the centre)
        cache = tmp_path / f"run{run}"
        copy_cache(order, crawl.cache, cache)
        frames = [B.extract_frame(p, cache) for p in order]
        at = C.Atlas()
        B.place_frames(at, frames, log=lambda *_: None)
        got = {f["name"]: np.array(f["M"], float)[:, 2] for f in at.frames}
        chain = [f for f in frames if decoy is None or f.name != decoy.stem]
        # each neighbouring pair is judged against direct terrain matching when it is strong (the crawl atlas has
        # its own small drift in places), otherwise against the crawl atlas
        errs, how = [], set()
        for f1, f2 in zip(chain[:-1], chain[1:], strict=False):
            if f1.name not in got or f2.name not in got:
                continue
            n, shift = at.terrain_link(f1, f2)
            ref = shift if n >= 40 else crawl.pos[f2.name] - crawl.pos[f1.name]
            how.add("terrain" if n >= 40 else "crawl atlas")
            errs.append(float(np.hypot(*((got[f2.name] - got[f1.name]) - ref))))
        errs = errs or [0.0]
        placed = sum(f.name in got for f in chain)
        decoy_in = decoy is not None and decoy.stem in got
        ok = placed == len(chain) and max(errs) <= TOL and not decoy_in
        direction = "reversed" if seq[0] != crawl.shots[k] else "in order"
        print(
            f"  {'ok  ' if ok else 'FAIL'} #{k}-#{k + LENGTH - 1} {direction}"
            f" + decoy {decoy.stem[-8:] if decoy else '-'}: chain {placed}/{len(chain)} placed, decoy "
            f"{'MERGED' if decoy_in else 'kept out'}, max difference {max(errs):.1f} units"
            f" (vs {', '.join(sorted(how)) or '-'})"
        )
        if not ok:
            failed.append(
                f"#{k}: {placed}/{len(chain)} placed, max {max(errs):.1f}, decoy {'in' if decoy_in else 'out'}"
            )
    assert not failed, f"failed runs (seed {seed}): {failed}"
