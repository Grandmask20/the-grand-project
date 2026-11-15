"""Waiting screenshots that form islands, fed through the viewer's own auto-add (AutoAddMixin) on known
positions from a finished atlas (the crawl atlas, or --atlas). Every screenshot is detected again as a new
one (--cached reuses the saved detections: quick).

    python -m tests.test_waiting_islands [--seed N] [--cases 6] [--cached] [--atlas A.json --folder DIR]

Scenarios (picked by the screenshots' true positions; "shares N maps" = N of its maps land on maps of the
other side there):
  bridge       main chain; an island touching nothing of it; then a bridge sharing 10+ maps with both sides
               -> the island must cascade in once the bridge is placed
  two islands  main; island 1; island 2; bridge island1-island2 (waits); bridge main-island1 -> all in
  edge         main area; an island along its edge whose screenshots each share too few maps with it (1-6)
               but 10+ together; plus a decoy island from far away -> the island joins as a group, the decoy
               keeps waiting
"""

from __future__ import annotations

import argparse
import hashlib
import queue
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from grand_project import paths as rc_paths

rc_paths.need_test_data()
from grand_project import builder as B  # noqa: E402
from grand_project import core as C  # noqa: E402
from grand_project.viewer.autoadd import AutoAddMixin  # noqa: E402

TD = rc_paths.TEST_DATA
LINK_SHARE = 0.45  # shots inside one chain / island overlap at least this much (screen boxes)
STRONG = 10  # maps a bridge shares with each side
TOL = 12.0  # atlas units: placement vs the finished atlas (relative to the main chain)


class Feeder(AutoAddMixin):
    """just enough of the viewer to run its auto-add placement without a window"""

    def __init__(self):
        self.atlas = C.Atlas()
        self._pending_watch = []
        self._q = queue.Queue()
        self.asked = []
        self.log = []

    def _ask(self, question: str) -> bool:  # the viewer would ask; the test answers yes and counts it
        self.asked.append(question)
        return True

    def feed(self, frames):
        r = self._place_watched(list(frames))
        while not self._q.empty():
            self.log.append(str(self._q.get()[1]))
        return r


class Known:
    """true positions and maps of the finished atlas's screenshots"""

    def __init__(self, big, on_disk, cache):
        self.f = {f["name"]: f for f in big.frames if f["name"] in on_disk}
        self.names = sorted(self.f)
        self.pos = {k: np.array(f["M"], float)[:, 2] for k, f in self.f.items()}
        self.box = {}
        self.pts = {}
        self.fr = {}
        for k, f in self.f.items():
            H = C.screen_to_atlas(np.array(f["M"], float), C.rectifier(f["w"], f["h"], f.get("horizon")))
            p = C.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
            self.box[k] = np.array([*p.min(axis=0), *p.max(axis=0)])
            fr = B.extract_frame(on_disk[k], cache)
            self.fr[k] = fr
            self.pts[k] = C.apply(np.array(f["M"], float), fr.pts[fr.usable])

    def share(self, a, b) -> float:
        A, Bb = self.box[a], self.box[b]
        w = max(0.0, min(A[2], Bb[2]) - max(A[0], Bb[0]))
        h = max(0.0, min(A[3], Bb[3]) - max(A[1], Bb[1]))
        return w * h / ((A[2] - A[0]) * (A[3] - A[1]))

    def apart(self, a, b, margin=60.0) -> bool:
        A, Bb = self.box[a], self.box[b]
        return A[2] + margin < Bb[0] or Bb[2] + margin < A[0] or A[3] + margin < Bb[1] or Bb[3] + margin < A[1]

    def maps_shared(self, ks, group) -> int:
        """distinct maps of `group` that the screenshots ks land on"""
        G = np.vstack([self.pts[g] for g in group if len(self.pts[g])] or [np.zeros((0, 2))])
        if not len(G):
            return 0
        hit = set()
        tree = cKDTree(G)
        for k in ks:
            if len(self.pts[k]):
                d, i = tree.query(self.pts[k])
                hit |= {int(j) for j, dd in zip(i, d, strict=True) if dd <= C.MERGE_TOL}
        return len(hit)

    def connects(self, group, k) -> bool:
        """k is placed against the screenshots `group` by the full placement rules (maps, then the terrain
        check), like auto-add: a bridge the rules accept, not just one that looks close"""
        a = C.Atlas()
        for g in group:
            a.add_frame(self.fr[g], verify=False)
        return a.add_frame(self.fr[k], hints=list(group)[::-1], commit=False).ok  # maps AND terrain, like auto-add

    def chain(self, start, n, used, forbid, ok=lambda k: True):
        run = [start]
        while len(run) < n:
            nxt = [
                k
                for k in self.names
                if k not in used
                and k not in run
                and ok(k)
                and self.share(k, run[-1]) >= LINK_SHARE
                and self.maps_shared([k], [run[-1]]) >= STRONG
                and all(self.apart(k, x) for x in forbid)
            ]
            if not nxt:
                return None
            run.append(max(nxt, key=lambda k: self.share(k, run[-1])))
        return run


def bridge_case(rng, K: Known, two: bool):
    for _ in range(3000):
        b1 = rng.choice(K.names)
        sides = [k for k in K.names if k != b1 and K.maps_shared([b1], [k]) >= STRONG]
        pairs = [(m, i) for m in sides for i in sides if m < i and K.apart(m, i)]
        if not pairs:
            continue
        m0, i0 = rng.choice(pairs)
        main = K.chain(m0, 3, {b1, i0}, [i0])
        isl1 = main and K.chain(i0, 3, {b1, *main}, main)
        if not main or not isl1 or not K.connects(main, b1) or not K.connects([*main, b1], i0):
            continue
        if not two:
            return {"kind": "bridge", "main": main, "islands": [isl1], "decoys": [], "bridges": [b1]}
        for b2 in rng.sample(K.names, len(K.names)):
            if b2 in (b1, *main, *isl1) or not all(K.apart(b2, k) for k in main):
                continue
            if K.maps_shared([b2], isl1) < STRONG:
                continue
            far = [
                k
                for k in K.names
                if k != b2 and K.maps_shared([b2], [k]) >= STRONG and all(K.apart(k, x) for x in (*main, *isl1, b1))
            ]
            if not K.connects([*main, b1, *isl1], b2):
                continue
            for i2 in far:
                isl2 = K.chain(i2, 3, {b1, b2, *main, *isl1}, [*main, *isl1, b1])
                if isl2 and K.connects([*main, b1, *isl1, b2], i2):
                    return {
                        "kind": "two islands",
                        "main": main,
                        "islands": [isl1, isl2],
                        "decoys": [],
                        "bridges": [b2, b1],
                    }
    return None


def edge_case(rng, K: Known):
    for _ in range(3000):
        main = K.chain(rng.choice(K.names), 6, set(), [])
        if not main:
            continue
        weak = [k for k in K.names if k not in main and 1 <= K.maps_shared([k], main) <= 6]
        rng.shuffle(weak)
        for s in weak:
            isl = K.chain(s, 3, set(main), [], ok=set(weak).__contains__)
            if not isl or K.maps_shared(isl, main) < STRONG:
                continue
            others = [k for k in K.names if all(K.apart(k, x) for x in (*main, *isl))]
            rng.shuffle(others)
            for d0 in others:
                decoy = K.chain(d0, 2, {*main, *isl}, [*main, *isl])
                if decoy:
                    return {"kind": "edge", "main": main, "islands": [isl], "decoys": [decoy], "bridges": []}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int)
    ap.add_argument("--cases", type=int, default=6)
    ap.add_argument("--atlas", help="finished atlas.json with cached detections (default: the crawl atlas)")
    ap.add_argument("--folder", help="its screenshots (default: screenshots/crawl)")
    ap.add_argument("--cached", action="store_true", help="reuse the saved detections (quick)")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10**6)
    rng = random.Random(seed)
    big_path = Path(a.atlas) if a.atlas else TD / "crawl_atlas" / "atlas.json"
    folder = Path(a.folder) if a.folder else TD / "screenshots" / "crawl"
    on_disk = {p.stem: p for p in folder.glob("*.png")}
    cache = big_path.with_name(big_path.stem + "_frames")
    K = Known(C.Atlas.load(big_path), on_disk, cache)
    print(f"seed {seed}: {len(K.names)} screenshots ({'saved detections' if a.cached else 'detected as new'})")
    fails = 0
    for case in range(a.cases):
        kind = ("bridge", "two islands", "edge")[case % 3]
        sc = edge_case(rng, K) if kind == "edge" else bridge_case(rng, K, kind == "two islands")
        if sc is None:
            print(f"  --   no {kind} case found")
            continue
        work = Path(tempfile.mkdtemp())
        (work / "f").mkdir()
        isl_all = [k for isl in sc["islands"] for k in isl]
        dec_all = [k for d in sc["decoys"] for k in d]
        everything = sc["main"] + isl_all + dec_all + sc["bridges"]
        if a.cached:
            for k in everything:
                h = hashlib.sha256(on_disk[k].read_bytes()).hexdigest()[:16]
                shutil.copy(cache / f"{h}_detect1.json", work / "f")
        else:  # new screenshots: detected from the image, several at a time like auto-add does
            B.detect_uncached([on_disk[k] for k in everything], work / "f")
        fr = {k: B.extract_frame(on_disk[k], work / "f") for k in everything}
        feeder = Feeder()
        feeder.feed([fr[k] for k in sc["main"]])
        main_ok = len(feeder.atlas.frames) == len(sc["main"])
        early = 0
        for isl in sc["islands"] + sc["decoys"]:
            for k in isl:  # one at a time, as they would arrive
                feeder.feed([fr[k]])
        if sc["kind"] != "edge":
            early = len(
                set(isl_all) & {f["name"] for f in feeder.atlas.frames}
            )  # bridge cases: nothing of an island fits before its bridge
        steps = []
        for b in sc["bridges"]:
            feeder.feed([fr[b]])
            steps.append(len(feeder.atlas.frames))
        got = {f["name"]: np.array(f["M"], float)[:, 2] for f in feeder.atlas.frames}
        ref = sc["main"][0]
        errs = [float(np.hypot(*((got[k] - got[ref]) - (K.pos[k] - K.pos[ref])))) for k in got]
        missing = [k[-8:] for k in sc["main"] + isl_all + sc["bridges"] if k not in got]
        decoy_in = [k[-8:] for k in dec_all if k in got]
        groups = [m for m in feeder.log if m.startswith("waiting group") and "joined" in m]
        ok = main_ok and not early and not missing and not decoy_in and max(errs) <= TOL
        fails += not ok
        print(
            f"  {'ok  ' if ok else 'FAIL'} {sc['kind']:<11}: main {len(sc['main'])}, islands "
            f"{[len(i) for i in sc['islands']]}"
            + (f", decoy {len(dec_all)} {'MERGED ' + str(decoy_in) if decoy_in else 'kept out'}" if dec_all else "")
            + (f"; placed after each bridge {steps} of {len(everything)}" if steps else "")
            + f"; joined as a group {len(groups)}x; max error {max(errs):.1f} units"
            + (f"; {early} placed before their bridge" if early else "")
            + (f"; never placed: {missing}" if missing else "")
            + (f"; {len(feeder.asked)} weak-match question(s)" if feeder.asked else "")
        )
        if not ok:
            for m in feeder.log:
                if "waiting group" in m or "no place found" in m:
                    print("       " + m[:150])
        shutil.rmtree(work, ignore_errors=True)
    print("PASS: waiting islands join, decoys stay out" if not fails else f"FAILED: {fails} case(s) (seed {seed})")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
