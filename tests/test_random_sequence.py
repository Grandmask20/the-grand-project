"""Randomised placement test: random runs of crawl screenshots that are known to line up, plus one decoy
from far away on the atlas, built into fresh atlases from the cached detections.

Each run must place every chained screenshot where the full crawl atlas (or direct terrain matching) puts
it, and must NOT merge the decoy anywhere (it shares nothing with the run).

    python -m tests.test_random_sequence [--atlas .../crawl_atlas/atlas.json] [--folder .../screenshots/crawl]
                                         [--runs 6] [--length 3] [--seed N]
"""

from __future__ import annotations

import argparse
import hashlib
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np

from grand_project import paths as rc_paths

rc_paths.need_test_data()
TD = rc_paths.TEST_DATA
from grand_project import builder as B  # noqa: E402
from grand_project import core as C  # noqa: E402

TOL = 10.0  # atlas units: terrain matching and map placement differ by 2-8 on
# raised ground (parallax); real placement errors are tens of units
LINK_MAX = 650.0  # atlas units between two consecutive crawl shots that surely overlap (screens are 1920 wide)
DECOY_MIN = 4000.0  # a decoy is at least this far from every screenshot of the run


def copy_cache(images, src_cache: Path, dst_cache: Path):
    dst_cache.mkdir(parents=True, exist_ok=True)
    for im in images:
        h = hashlib.sha256(Path(im).read_bytes()).hexdigest()[:16]
        shutil.copy(src_cache / f"{h}_detect1.json", dst_cache / f"{h}_detect1.json")


def chains(shots: list[Path], pos: dict, length: int) -> list[int]:
    """start indexes of runs of `length` consecutive shots where every neighbouring pair overlaps"""
    linked = [np.hypot(*(pos[b.stem] - pos[a.stem])) <= LINK_MAX for a, b in zip(shots, shots[1:], strict=False)]
    return [k for k in range(len(shots) - length + 1) if all(linked[k : k + length - 1])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", default=str(TD / "crawl_atlas/atlas.json"))
    ap.add_argument("--folder", default=str(TD / "screenshots/crawl"))
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--length", type=int, default=3)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10**6)
    rng = random.Random(seed)
    big_path = Path(a.atlas)
    big = C.Atlas.load(big_path)
    pos = {f["name"]: np.array(f["M"], float)[:, 2] for f in big.frames}
    shots = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() == ".png" and p.stem in pos)
    starts = chains(shots, pos, a.length)
    src_cache = big_path.with_name(big_path.stem + "_frames")
    print(
        f"seed {seed}: {a.runs} runs of {a.length} linked crawl screenshots (+1 decoy), "
        f"{len(starts)} possible runs in {len(shots)} screenshots"
    )
    if not starts:
        print("FAILED: no run of linked screenshots in the test data")
        return 1
    fails = 0
    for _run in range(a.runs):
        k = rng.choice(starts)
        seq = shots[k : k + a.length]
        if rng.random() < 0.5:
            seq = seq[::-1]  # also test reverse order
        far = [p for p in shots if min(np.hypot(*(pos[p.stem] - pos[s.stem])) for s in seq) >= DECOY_MIN]
        decoy = rng.choice(far) if far else None
        order = list(seq)
        if decoy is not None:
            order.insert(rng.randrange(1, len(order) + 1), decoy)  # after the first (the first one is the centre)
        work = Path(tempfile.mkdtemp())
        copy_cache(order, src_cache, work / "t_frames")
        frames = [B.extract_frame(p, Path("unused"), work / "t_frames") for p in order]
        at = C.Atlas()
        added, refused = B.place_frames(at, frames, log=lambda *_: None)
        got = {f["name"]: np.array(f["M"], float)[:, 2] for f in at.frames}
        chain = [f for f in frames if decoy is None or f.name != decoy.stem]
        # judge each neighbouring pair against direct terrain matching when it is strong (the crawl
        # atlas has its own small drift in places), otherwise against the crawl atlas
        errs, how = [], set()
        for f1, f2 in zip(chain[:-1], chain[1:], strict=False):
            if f1.name not in got or f2.name not in got:
                continue
            n, shift = at.terrain_link(f1, f2)
            ref = shift if n >= 40 else pos[f2.name] - pos[f1.name]
            how.add("terrain" if n >= 40 else "crawl atlas")
            errs.append(float(np.hypot(*((got[f2.name] - got[f1.name]) - ref))))
        errs = errs or [0.0]
        chain_placed = sum(f.name in got for f in chain)
        decoy_merged = decoy is not None and decoy.stem in got
        # every linked screenshot placed, placed right, and the unrelated one kept out
        ok = chain_placed == len(chain) and max(errs) <= TOL and not decoy_merged
        fails += not ok
        print(
            f"  {'ok  ' if ok else 'FAIL'} #{k}-#{k + a.length - 1} {'reversed' if seq[0] != shots[k] else 'in order'}"
            f" + decoy {decoy.stem[-8:] if decoy else '-'} at {order.index(decoy) if decoy else '-'}: "
            f"chain {chain_placed}/{len(chain)} placed, decoy {'MERGED' if decoy and decoy.stem in got else 'kept out'}"
            f", max difference {max(errs):.1f} units (vs {', '.join(sorted(how)) or '-'})"
        )
        shutil.rmtree(work, ignore_errors=True)
    print(
        "PASS: random sequences (linked shots placed right, decoys kept out)"
        if not fails
        else f"FAILED: {fails} of {a.runs} runs (seed {seed})"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
