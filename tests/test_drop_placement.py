"""Randomised test of hand placement: a crawl screenshot dropped up to ~600 units off where it
belongs must be lined up by Atlas.place_near.

    py test_drop_placement.py [--runs 8] [--seed N]
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))
import rc_paths  # noqa: E402
rc_paths.need_test_data()
TD = rc_paths.TEST_DATA
import atlas_builder as B            # noqa: E402
import atlas_builder_core as C       # noqa: E402
import test_random_sequence as T     # noqa: E402

TOL = 10.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10 ** 6)
    rng = random.Random(seed)
    big_path = TD / "crawl_atlas/atlas.json"
    big = C.Atlas.load(big_path)
    truth = {f["name"]: np.array(f["M"], float)[:, 2] for f in big.frames}
    shots = sorted(p for p in (TD / "screenshots/crawl").iterdir() if p.suffix == ".png" and p.stem in truth)
    print(f"seed {seed}")
    fails = unplaced = 0
    for _ in range(a.runs):
        k = rng.randrange(len(shots) - 4)
        seq = shots[k:k + 4]
        w = Path(tempfile.mkdtemp())
        T.copy_cache(seq, big_path.with_name("atlas_frames"), w / "f")
        fr = [B.extract_frame(p, Path("x"), w / "f") for p in seq]
        at = C.Atlas()
        B.place_frames(at, fr[:3], log=lambda *_: None)
        names = [f["name"] for f in at.frames]
        if fr[0].name not in names:
            continue
        want = truth[fr[3].name] - truth[fr[0].name] + np.array(at.frames[names.index(fr[0].name)]["M"])[:, 2]
        # where the screenshot really belongs per the atlas itself (crawl atlas drifts a little)
        r0 = at.add_frame(fr[3], hints=names, commit=False)
        if r0.ok and np.hypot(*(r0.M[:, 2] - want)) < 25:
            want = r0.M[:, 2]
        off = np.array([rng.uniform(-500, 500), rng.uniform(-400, 400)])
        r = at.place_near(fr[3], *(want + off))
        err = float(np.hypot(*(r.M[:, 2] - want))) if r.ok else float("nan")
        # placed wrongly = failure; not placed = the viewer asks to use the drop position as is
        ok = (not r.ok) or err <= TOL
        fails += not ok
        unplaced += not r.ok
        tag = "ok  " if r.ok and ok else ("ask " if not r.ok else "FAIL")
        print(f"  {tag} #{k + 3}: dropped {np.hypot(*off):.0f} units off -> "
              + (f"error {err:.1f} ({r.reason[:40]})" if r.ok else f"not placed: {r.reason}"))
        shutil.rmtree(w, ignore_errors=True)
    print(f"{unplaced} of {a.runs} could not be lined up (the viewer then asks to keep the drop position)")
    print("PASS: drop placement (no wrong placements)" if not fails else f"FAILED: {fails} wrong placements (seed {seed})")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
