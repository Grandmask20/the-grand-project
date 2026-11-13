"""Regression check against every mark layer the user has drawn on detector overlays.

    py atlas_marks.py            run the live detector on all marked screenshots, compare with the marks,
                                 print the result next to the previous run (atlas_marks_history.json)

Marks (screen px of the original screenshot; overlays drew paths 5 px left, PATH_DRAW_SHIFT):
  line / drift   a path that should exist (drift: right maps, wrong drawn line) -> is a path drawn along it?
  circle / box   a missed map / tower                    -> is a map found within 35 px?
  false_map / false_hidden / cross on a map               -> is it gone?
  cross / false_path on a path                           -> is that path gone?
Plus crossings: drawn paths that cross each other away from any map (never allowed - user).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))
import atlas_detect as ad  # noqa: E402

import rc_paths  # noqa: E402
rc_paths.need_test_data()
TRUTH_DIR = rc_paths.TEST_DATA / "truth"
ANN = rc_paths.TEST_DATA / "marks"
HISTORY = HERE.parent / "user_data" / "atlas_marks_history.json"
TRUE_PATHS = TRUTH_DIR / "path_marks" / "true_paths"     # user-traced complete path layers (white = a real path line)
MAP_CLEAR = 15                                      # px around a map centre left out of the path-layer score
TRUE_R = 8                                          # px: a drawn path this close to a traced line is on it
LINE_R, MAP_R, FALSE_MAP_R, FALSE_PATH_R, CROSS_CLEAR = 10, 35, 20, 14, 20


def marked_shots() -> dict:
    """screenshot path -> list of marks, from every marking round"""
    out: dict = {}
    pm = json.loads((TRUTH_DIR / "path_marks" / "marks.json").read_text(encoding="utf-8"))
    for per in pm.values():
        for key, ms in per.items():
            shot = json.loads(next((TRUTH_DIR / "path_marks").glob(key + "_*_1.json")).read_text(encoding="utf-8"))["shot"]
            out.setdefault(shot, []).extend(ms)
    for sub in ("round1", "v068", "missing_maps"):
        f = ANN / sub / "marks.json"
        if f.exists():
            for stem, ms in json.loads(f.read_text(encoding="utf-8")).items():
                out.setdefault(str(ad.SHOTS / (stem + ".png")), []).extend(ms)
    return out


def _seg_dist(p, line) -> float:
    L = np.asarray(line, float)
    a, b = L[:-1], L[1:]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
    return float(np.min(np.hypot(*(a + t[:, None] * ab - p).T)))


def crossings(r: dict) -> list:
    """points where two drawn paths cross, more than CROSS_CLEAR px from every map"""
    N = np.array([[n["x"], n["y"]] for n in r["nodes"]], float).reshape(-1, 2)
    E = [np.asarray(e["line"], float) for e in r["edges"]]
    pts = []
    for i in range(len(E)):
        for j in range(i + 1, len(E)):
            A, B = E[i], E[j]
            if (A.min(0) > B.max(0)).any() or (B.min(0) > A.max(0)).any():
                continue
            p1, p2, q1, q2 = A[:-1, None], A[1:, None], B[None, :-1], B[None, 1:]
            r_ = p2 - p1
            s_ = q2 - q1
            den = r_[..., 0] * s_[..., 1] - r_[..., 1] * s_[..., 0]
            qp = q1 - p1
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (qp[..., 0] * s_[..., 1] - qp[..., 1] * s_[..., 0]) / den
                u = (qp[..., 0] * r_[..., 1] - qp[..., 1] * r_[..., 0]) / den
            hit = (den != 0) & (t > 0) & (t < 1) & (u > 0) & (u < 1)
            for a_, b_ in zip(*np.nonzero(hit)):
                x = p1[a_, 0] + t[a_, b_] * r_[a_, 0]
                if len(N) == 0 or np.min(np.hypot(*(N - x).T)) > CROSS_CLEAR:
                    pts.append(x.tolist())
                    break
    return pts


def check(results: dict, marks: dict) -> dict:
    s = {k: [0, 0] for k in ("missed lines drawn", "drift lines drawn right", "circled maps found",
                             "false maps gone", "false hidden maps gone", "false paths gone")}
    s["crossings"] = 0
    for shot, ms in marks.items():
        r = results[shot]
        E, N = r["edges"], r["nodes"]
        for m in ms:
            k = m["kind"]
            if k in ("line", "drift"):
                key = "missed lines drawn" if k == "line" else "drift lines drawn right"
                for x, y in m["pts"]:
                    s[key][1] += 1
                    s[key][0] += any(_seg_dist(np.array([x, y], float), e["line"]) <= LINE_R for e in E)
            elif k in ("circle", "box"):
                s["circled maps found"][1] += 1
                s["circled maps found"][0] += any(np.hypot(m["x"] - n["x"], m["y"] - n["y"]) <= m.get("r", MAP_R) for n in N)
            elif k in ("false_map", "false_hidden"):
                key = "false maps gone" if k == "false_map" else "false hidden maps gone"
                s[key][1] += 1
                s[key][0] += not any(np.hypot(m["x"] - n["x"], m["y"] - n["y"]) <= FALSE_MAP_R for n in N)
            elif k in ("cross", "false_path"):
                s["false paths gone"][1] += 1
                p = np.array([m["x"] - ad.PATH_DRAW_SHIFT, m["y"]], float)
                s["false paths gone"][0] += not any(_seg_dist(p, e["line"]) <= FALSE_PATH_R for e in E)
        s["crossings"] += len(crossings(r))
    # complete path layers the user traced: recall over the traced lines, precision over the drawn lines
    rec, prec = [0, 0], [0, 0]
    for f in sorted(TRUE_PATHS.glob("*.png")) if TRUE_PATHS.exists() else []:
        shot = str(ad.SHOTS / f.name)
        if shot not in results:
            continue
        true = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) > 0
        drawn = np.zeros(true.shape, np.uint8)
        for e in results[shot]["edges"]:
            cv2.polylines(drawn, [np.asarray(e["line"], float).round().astype(np.int32)], False, 255, 1)
        rings = np.zeros(true.shape, np.uint8)                 # map centres: neither side counts there
        for n in results[shot]["nodes"]:
            cv2.circle(rings, (int(n["x"]), int(n["y"])), MAP_CLEAR, 255, -1)
        true &= rings == 0
        drawn[rings > 0] = 0
        k = np.ones((2 * TRUE_R + 1, 2 * TRUE_R + 1), np.uint8)
        near_drawn = cv2.dilate(drawn, k) > 0
        near_true = cv2.dilate(true.astype(np.uint8) * 255, k) > 0
        rec[0] += int((true & near_drawn).sum()); rec[1] += int(true.sum())
        prec[0] += int(((drawn > 0) & near_true).sum()); prec[1] += int((drawn > 0).sum())
    if rec[1]:
        s["true paths covered"] = rec
        s["drawn paths that are real"] = prec
    return s


def main() -> int:
    marks = marked_shots()
    t0 = time.time()
    results = {}
    for shot in marks:
        img = cv2.imdecode(np.fromfile(shot, np.uint8), cv2.IMREAD_COLOR)
        results[shot] = ad.detect(img)
    s = check(results, marks)
    hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    prev = hist[-1] if hist else None
    label = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d %H:%M")
    print(f"{len(marks)} marked screenshots, {time.time() - t0:.0f} s   ({label} vs {prev['label'] if prev else '-'})")
    for k, v in s.items():
        old = prev["s"].get(k) if prev else None
        if k == "crossings":
            print(f"  {k:26s} {v:4d}" + (f"   (was {old})" if old is not None else "") + "   lower is better")
        else:
            was = f"   (was {old[0]}/{old[1]})" if old else ""
            print(f"  {k:26s} {v[0]:4d}/{v[1]:<4d} {v[0] / max(1, v[1]):5.0%}{was}")
    hist.append({"label": label, "s": s})
    HISTORY.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
