"""Randomised test of hand placement: a crawl screenshot dropped up to ~600 units off where it belongs must be
lined up by Atlas.place_near (or not placed at all: the viewer then asks to keep the drop position).

    pytest tests/test_drop_placement.py [--runs 8] [--seed N]
"""

from __future__ import annotations

import numpy as np
import pytest

from grand_project import builder as B
from grand_project import core as C

pytestmark = pytest.mark.data

TOL = 10.0  # atlas units: a placement further than this from where it belongs is wrong


def test_dropped_screenshot_is_lined_up(crawl, rng, runs, seed, copy_cache, tmp_path):
    """Never placed wrongly: either lined up within TOL or left for the user to confirm."""
    n_runs = runs(8)
    wrong, unplaced = [], 0
    for run in range(n_runs):
        k = rng.randrange(len(crawl.shots) - 4)
        seq = crawl.shots[k : k + 4]
        cache = tmp_path / f"run{run}"
        copy_cache(seq, crawl.cache, cache)
        fr = [B.extract_frame(p, cache) for p in seq]
        at = C.Atlas()
        B.place_frames(at, fr[:3], log=lambda *_: None)
        names = [f["name"] for f in at.frames]
        if fr[0].name not in names:
            continue
        want = crawl.pos[fr[3].name] - crawl.pos[fr[0].name] + np.array(at.frames[names.index(fr[0].name)]["M"])[:, 2]
        # where the screenshot really belongs per the atlas itself (the crawl atlas drifts a little)
        r0 = at.add_frame(fr[3], hints=names, commit=False)
        if r0.ok and np.hypot(*(r0.M[:, 2] - want)) < 25:
            want = r0.M[:, 2]
        off = np.array([rng.uniform(-500, 500), rng.uniform(-400, 400)])
        r = at.place_near(fr[3], *(want + off))
        err = float(np.hypot(*(r.M[:, 2] - want))) if r.ok else float("nan")
        unplaced += not r.ok
        ok = (not r.ok) or err <= TOL
        if not ok:
            wrong.append(f"#{k + 3}: {err:.1f} units off ({r.reason})")
        print(
            f"  {'ok  ' if r.ok and ok else ('ask ' if not r.ok else 'FAIL')} #{k + 3}: dropped "
            f"{np.hypot(*off):.0f} units off -> " + (f"error {err:.1f}" if r.ok else f"not placed: {r.reason}")
        )
    print(f"{unplaced} of {n_runs} could not be lined up (the viewer then asks to keep the drop position)")
    assert not wrong, f"wrong placements (seed {seed}): {wrong}"
