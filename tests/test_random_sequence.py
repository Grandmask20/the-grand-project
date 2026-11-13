"""Randomised placement test: random runs of consecutive crawl screenshots, built into fresh
atlases from the cached detections, compared with where the full crawl atlas put them.

    py test_random_sequence.py [--atlas ../atlas_test_data/crawl_atlas/atlas.json]
                               [--folder ../atlas_test_data/screenshots/crawl] [--runs 6] [--length 3] [--seed N]
"""
from __future__ import annotations

import argparse
import hashlib
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
import atlas_builder as B          # noqa: E402
import atlas_builder_core as C     # noqa: E402

TOL = 10.0                         # atlas units: terrain matching and map placement differ by 2-8 on
                                   # raised ground (parallax); real placement errors are tens of units


def copy_cache(images, src_cache: Path, dst_cache: Path):
    dst_cache.mkdir(parents=True, exist_ok=True)
    for im in images:
        h = hashlib.sha256(Path(im).read_bytes()).hexdigest()[:16]
        shutil.copy(src_cache / f"{h}_detect1.json", dst_cache / f"{h}_detect1.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", default=str(TD / "crawl_atlas/atlas.json"))
    ap.add_argument("--folder", default=str(TD / "screenshots/crawl"))
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--length", type=int, default=3)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10 ** 6)
    rng = random.Random(seed)
    big_path = Path(a.atlas)
    big = C.Atlas.load(big_path)
    truth = {f["name"]: np.array(f["M"], float)[:, 2] for f in big.frames}
    shots = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() == ".png" and p.stem in truth)
    src_cache = big_path.with_name(big_path.stem + "_frames")
    print(f"seed {seed}: {a.runs} runs of {a.length} consecutive screenshots from {len(shots)}")
    fails = unjoined = 0
    for run in range(a.runs):
        k = rng.randrange(0, len(shots) - a.length + 1)
        seq = shots[k:k + a.length]
        if rng.random() < 0.5:
            seq = seq[::-1]                                   # also test reverse order
        work = Path(tempfile.mkdtemp())
        copy_cache(seq, src_cache, work / "t_frames")
        frames = [B.extract_frame(p, Path("unused"), work / "t_frames") for p in seq]
        at = C.Atlas()
        added, refused = B.place_frames(at, frames, log=lambda *_: None)
        got = {f["name"]: np.array(f["M"], float)[:, 2] for f in at.frames}
        # judge each neighbouring pair against direct terrain matching when it is strong (the crawl
        # atlas has its own small drift in places), otherwise against the crawl atlas
        errs, how = [], set()
        for f1, f2 in zip(frames[:-1], frames[1:]):
            if f1.name not in got or f2.name not in got:
                continue
            n, shift = at.terrain_link(f1, f2)
            ref = shift if n >= 40 else truth[f2.name] - truth[f1.name]
            how.add("terrain" if n >= 40 else "crawl atlas")
            errs.append(float(np.hypot(*((got[f2.name] - got[f1.name]) - ref))))
        errs = errs or [0.0]
        # wrong placement = failure; a screenshot that shares too little with the others to join
        # (big jumps happen in a crawl) is reported, not failed
        ok = max(errs) <= TOL
        fails += not ok
        unjoined += added < len(seq)
        tag = "FAIL" if not ok else ("ok  " if added == len(seq) else "gap ")
        print(f"  {tag} #{k}-#{k + a.length - 1} {'reversed' if seq[0] != shots[k] else 'in order'}: "
              f"{added}/{len(seq)} placed, max difference {max(errs):.1f} units (vs {', '.join(sorted(how))})"
              + (f", not placed: {refused}" if refused else ""))
        shutil.rmtree(work, ignore_errors=True)
    print(f"{unjoined} of {a.runs} runs had a screenshot too far from the others to join")
    print("PASS: random sequences (no wrong placements)" if not fails
          else f"FAILED: {fails} of {a.runs} runs placed wrongly (seed {seed})")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
