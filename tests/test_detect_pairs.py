"""Two adjacent screenshots through the new detector (atlas_detect): do maps and paths agree where they
overlap, and does adding the second shot complete paths the first could only see one end of?

    py test_detect_pairs.py [N] [seed]      N random consecutive pairs from atlas_test_data/screenshots/crawl (default 4)

Placement: the builder's own placements of the crawl shots (atlas_test_data/crawl_atlas/atlas.json:
screen -> atlas = M @ rectifier). Pairs are chosen among shots whose views overlap by 25-70%.
Positions below are in atlas units.
  maps in overlap      maps of one shot inside the other's view: found by the other within MATCH px?
  paths in overlap     paths with both ends seen by both shots: drawn by both?
  seam                 paths only one shot could draw (an end outside the other's view) that the pair
                       now has, i.e. what adding the second shot contributes
A picture per pair: atlas_test_data/detect_pairs_out/<pair>.png (A paths cyan, B paths magenta, maps white/yellow).
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))
import rc_paths  # noqa: E402
rc_paths.need_test_data()
TD = rc_paths.TEST_DATA
import atlas_builder_core as core  # noqa: E402
import atlas_detect as ad  # noqa: E402

CRAWL = TD / "screenshots" / "crawl"
OUT = TD / "detect_pairs_out"
MATCH = 45.0          # atlas units: the same map seen in both shots (maps on raised ground shift
                      # between views - the builder merges up to 52)
# fortress shots: walls cut every path through them (user), so they are no seam test
SKIP = {"2694490_20261109055044_1.png", "2694490_20261109055047_1.png", "2694490_20261109055713_1.png",
        "2694490_20261109055714_1.png"}
EDGE = 45.0           # px from a screen edge / the HUD: a map this close may be cut off, not counted


ATLAS = TD / "crawl_atlas" / "atlas.json"


def frames() -> dict:
    d = json.loads(ATLAS.read_text(encoding="utf-8"))
    out = {}
    for f in d["frames"]:
        f["path"] = core._find_screenshot(f["path"], ATLAS.parent)      # relative in the GitHub test data
        if Path(f["path"]).exists():
            out[Path(f["path"]).name] = f
    return out


def H_of(f) -> np.ndarray:
    return core.screen_to_atlas(np.array(f["M"], float), core.rectifier(f["w"], f["h"], f.get("horizon")))


def overlap(fa, fb) -> float:
    """share of A's screen that B also shows (sampled)"""
    g = np.stack(np.meshgrid(np.linspace(60, fa["w"] - 60, 24), np.linspace(60, fa["h"] - 60, 14)), -1).reshape(-1, 2)
    q = core.persp(np.linalg.inv(H_of(fb)) @ H_of(fa), g).reshape(-1, 2)
    return float(((q[:, 0] > 0) & (q[:, 0] < fb["w"]) & (q[:, 1] > 0) & (q[:, 1] < fb["h"])).mean())


def inside(pts_screen, w, h):
    """screen points well inside the view: away from the edges and the HUD"""
    p = np.asarray(pts_screen, float).reshape(-1, 2)
    ok = (p[:, 0] > EDGE) & (p[:, 0] < w - EDGE) & (p[:, 1] > EDGE) & (p[:, 1] < h - EDGE)
    return ok & ~core.on_hud_mask(p, w, h, pad=EDGE)


def run_pair(fa: Path, fb: Path, Fa: dict, Fb: dict) -> dict | None:
    ia = cv2.imdecode(np.fromfile(str(fa), np.uint8), cv2.IMREAD_COLOR)
    ib = cv2.imdecode(np.fromfile(str(fb), np.uint8), cv2.IMREAD_COLOR)
    h, w = ia.shape[:2]
    Ha, Hb = H_of(Fa), H_of(Fb)
    ra, rb = ad.detect(ia), ad.detect(ib)
    Hia, Hib = np.linalg.inv(Ha), np.linalg.inv(Hb)
    Pa = core.persp(Ha, [[n["x"], n["y"]] for n in ra["nodes"]]).reshape(-1, 2)
    Pb = core.persp(Hb, [[n["x"], n["y"]] for n in rb["nodes"]]).reshape(-1, 2)
    # which of A's maps fall inside B's view (and vice versa), well away from edges / HUD
    a_in_b = inside(core.persp(Hib, Pa).reshape(-1, 2), w, h) & inside([[n["x"], n["y"]] for n in ra["nodes"]], w, h)
    b_in_a = inside(core.persp(Hia, Pb).reshape(-1, 2), w, h) & inside([[n["x"], n["y"]] for n in rb["nodes"]], w, h)
    match_ab = {}
    for i in np.nonzero(a_in_b)[0]:
        d = np.hypot(*(Pb - Pa[i]).T)
        j = int(np.argmin(d))
        if d[j] <= MATCH:
            match_ab[int(i)] = j
    res = {"maps_a_in_b": int(a_in_b.sum()), "maps_a_found_by_b": len(match_ab),
           "maps_b_in_a": int(b_in_a.sum()),
           "maps_b_found_by_a": int(sum(1 for j in np.nonzero(b_in_a)[0] if np.min(np.hypot(*(Pa - Pb[j]).T)) <= MATCH))}
    ea = {(e["a"], e["b"]) for e in ra["edges"]}
    eb = {(min(e["a"], e["b"]), max(e["a"], e["b"])) for e in rb["edges"]}
    both = [(i, j) for i, j in ((a, b) for a, b in match_ab.items()) for _ in [0]]
    # paths whose two ends are matched maps (both shots see both ends)
    agree = only_a = only_b = 0
    matched = set(match_ab)
    for i in matched:
        for k in matched:
            if i >= k:
                continue
            in_a = (i, k) in ea
            bi, bk = match_ab[i], match_ab[k]
            in_b = (min(bi, bk), max(bi, bk)) in eb
            agree += in_a and in_b
            only_a += in_a and not in_b
            only_b += in_b and not in_a
    res.update(paths_both=agree, paths_only_a=only_a, paths_only_b=only_b)
    # seam: union graph over atlas maps; paths B adds that A could not see (one end outside A's view)
    b_vis_in_a = inside(core.persp(Hia, Pb).reshape(-1, 2), w, h)
    seam = sum(1 for a_, b_ in eb if b_vis_in_a[a_] != b_vis_in_a[b_])
    res["seam_paths_added_by_b"] = int(seam)
    # picture: both shots warped into one atlas canvas
    corners = np.vstack([core.persp(H, [[0, 0], [w, 0], [0, h], [w, h]]).reshape(-1, 2) for H in (Ha, Hb)])
    x0, y0 = corners.min(0)
    W, Hh = (corners.max(0) - (x0, y0)).astype(int) + 1
    T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
    can = np.maximum(cv2.warpPerspective(ia, T @ Ha, (W, Hh)) // 2, cv2.warpPerspective(ib, T @ Hb, (W, Hh)) // 2)
    for r, H, col, dx in ((ra, Ha, (255, 220, 60), -2), (rb, Hb, (255, 80, 255), 2)):
        for e in r["edges"]:
            L = core.persp(T @ H, e["line"]).reshape(-1, 2) + (dx, 0)
            cv2.polylines(can, [L.astype(np.int32)], False, col, 1, cv2.LINE_AA)
    for P, col in ((Pa, (255, 255, 255)), (Pb, (0, 230, 255))):
        for p in P - (x0, y0):
            cv2.circle(can, (int(p[0]), int(p[1])), 9, col, 1, cv2.LINE_AA)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"{fa.stem}__{fb.stem}.png"), can)
    return res


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else int(time.time()) % 10000
    F = frames()
    names = sorted(n_ for n_ in F if n_ not in SKIP)
    rng = random.Random(seed)
    print(f"seed {seed}")
    tot: dict = {}
    done = 0
    order = list(range(len(names)))
    rng.shuffle(order)
    for k in order:
        if done == n:
            break
        a_ = names[k]
        cands = [b_ for b_ in names if b_ != a_ and 0.25 <= overlap(F[a_], F[b_]) <= 0.70]
        if not cands:
            continue
        b_ = rng.choice(cands)
        t0 = time.time()
        r = run_pair(CRAWL / a_, CRAWL / b_, F[a_], F[b_])
        if r is None or r["maps_a_in_b"] < 10:
            continue
        done += 1
        for key, v in r.items():
            tot[key] = tot.get(key, 0) + v
        print(f"  {a_[-12:-6]} + {b_[-12:-6]} (overlap {overlap(F[a_], F[b_]):.0%}): maps A found by B "
              f"{r['maps_a_found_by_b']}/{r['maps_a_in_b']}, B by A {r['maps_b_found_by_a']}/{r['maps_b_in_a']} | "
              f"paths both {r['paths_both']}, only A {r['paths_only_a']}, only B {r['paths_only_b']} | seam paths "
              f"added by B {r['seam_paths_added_by_b']} ({time.time() - t0:.0f} s)", flush=True)
    if tot:
        pb = tot["paths_both"] + tot["paths_only_a"] + tot["paths_only_b"]
        print(f"TOTAL maps agree {tot['maps_a_found_by_b'] + tot['maps_b_found_by_a']}/"
              f"{tot['maps_a_in_b'] + tot['maps_b_in_a']} | paths drawn by both {tot['paths_both']}/{pb} "
              f"({tot['paths_both'] / max(1, pb):.0%}) | seam paths added {tot['seam_paths_added_by_b']}")
        (OUT / "last_run.json").write_text(json.dumps({"seed": seed, "total": tot}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
