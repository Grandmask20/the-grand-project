"""Randomised false-merge test: a screenshot must NOT be placed into an atlas built from a far-away part of the
crawl (no real overlap).

    pytest tests/test_false_merge.py [--runs 10] [--seed N]
"""

from __future__ import annotations

import numpy as np
import pytest

from grand_project import builder as B
from grand_project import core as C

pytestmark = pytest.mark.data

FAR = 4000.0  # atlas units: the screenshot is at least this far from every screenshot of the atlas


def test_far_screenshot_is_not_merged(crawl, rng, runs, seed, copy_cache, tmp_path):
    """A screenshot from far away is refused by an atlas of six consecutive crawl screenshots."""
    merged = []
    for run in range(runs(10)):
        k = rng.randrange(len(crawl.shots) - 6)
        base = crawl.shots[k : k + 6]
        far = [q for q in crawl.shots if min(np.hypot(*(crawl.pos[q.stem] - crawl.pos[b.stem])) for b in base) > FAR]
        q = rng.choice(far)
        cache = tmp_path / f"run{run}"
        copy_cache([*base, q], crawl.cache, cache)
        at = C.Atlas()
        B.place_frames(at, [B.extract_frame(p, cache) for p in base], log=lambda *_: None)
        r = at.add_frame(B.extract_frame(q, cache), hints=[f["name"] for f in at.frames], commit=False)
        print(
            f"  {'FAIL' if r.ok else 'ok  '} atlas from #{k}-#{k + 5} + far screenshot {q.stem[-8:-2]}: "
            + (f"PLACED ({r.reason})" if r.ok else f"refused ({r.reason[:50]})")
        )
        if r.ok:
            merged.append(f"#{k}-#{k + 5} + {q.stem}")
    assert not merged, f"false merges (seed {seed}): {merged}"
