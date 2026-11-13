"""Randomised false-merge test: a screenshot must NOT be placed into an atlas built from a far-away
part of the crawl (no real overlap).

    py test_false_merge.py [--runs 10] [--seed N]
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10 ** 6)
    rng = random.Random(seed)
    big_path = TD / "crawl_atlas/atlas.json"
    big = C.Atlas.load(big_path)
    pos = {f["name"]: np.array(f["M"], float)[:, 2] for f in big.frames}
    shots = sorted(p for p in (TD / "screenshots/crawl").iterdir() if p.suffix == ".png" and p.stem in pos)
    print(f"seed {seed}")
    wrong = 0
    for _ in range(a.runs):
        k = rng.randrange(len(shots) - 6)
        base = shots[k:k + 6]
        far = [q for q in shots if min(np.hypot(*(pos[q.stem] - pos[b.stem])) for b in base) > 4000]
        q = rng.choice(far)
        w = Path(tempfile.mkdtemp())
        T.copy_cache(base + [q], big_path.with_name("atlas_frames"), w / "f")
        frames = [B.extract_frame(p, Path("x"), w / "f") for p in base]
        at = C.Atlas()
        B.place_frames(at, frames, log=lambda *_: None)
        fq = B.extract_frame(q, Path("x"), w / "f")
        r = at.add_frame(fq, hints=[f["name"] for f in at.frames], commit=False)
        wrong += r.ok
        print(f"  {'FAIL' if r.ok else 'ok  '} atlas from #{k}-#{k + 5} + far screenshot {q.stem[-8:-2]}: "
              + (f"PLACED ({r.reason})" if r.ok else f"refused ({r.reason[:50]})"))
        shutil.rmtree(w, ignore_errors=True)
    print("PASS: no false merges" if not wrong else f"FAILED: {wrong} false merges (seed {seed})")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
