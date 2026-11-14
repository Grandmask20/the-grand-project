"""Contact sheet of map badges for naming by hand.

    py atlas_badge_sheet.py --atlas my_atlas.json [--out sheet.png]

Unidentified badges (HUD excluded, one crop per badge even if several screenshots saw it) are
grouped by look; each row is one group labelled G1, G2, ...  Below them, samples of the icon
types added from poe2db, to confirm the matcher names them correctly.  Writes
<atlas>_badges.png and <atlas>_badges.json (group -> badge positions).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))
import atlas_builder_core as core  # noqa: E402

CHECK_TYPES = [
    "Sanctification",
    "Trader",
    "RogueExile",
    "StoneCircle",
    "Shrine",
    "RareMonster",
    "Checkpoint",
    "NamelessSeer",
    "AbyssalDepths",
    "ExpeditionRemnant",
    "SanctificationBoss",
]
CROP, TILE, PER_ROW = 44, 72, 14
N_GROUPS = 24


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", required=True)
    ap.add_argument("--out")
    ap.add_argument("--taught", action="store_true", help="also show rows of badges named in the icon database")
    args = ap.parse_args()
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path)
    by_name = {f["name"]: f for f in atlas.frames}
    sightings = []  # (name, atlas x, y, path, sx, sy, centrality)
    for cf in atlas_path.with_name(atlas_path.stem + "_frames").glob("*.json"):
        fr = core.Frame.from_json(json.loads(cf.read_text(encoding="utf-8")))
        f = by_name.get(fr.name)
        if f is None:
            continue
        H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        for m in fr.icons:
            p = core.persp(H, [[m["x"], m["y"]]])[0]
            c = max(abs(m["x"] / fr.w - 0.5), abs(m["y"] / fr.h - 0.5))
            sightings.append((m["name"], p[0], p[1], fr.path, m["x"], m["y"], c, m.get("source", "")))
    # one entry per badge: merge same-name sightings within 30 atlas units, keep the most central
    badges: dict[str, list] = {}
    for s in sorted(sightings, key=lambda s: s[6]):
        lst = badges.setdefault(s[0], [])
        if not any(abs(b[1] - s[1]) < 30 and abs(b[2] - s[2]) < 30 for b in lst):
            lst.append(s)
    cache: dict[str, np.ndarray] = {}

    def crop(b):
        if b[3] not in cache:
            if len(cache) > 30:
                cache.pop(next(iter(cache)))
            cache[b[3]] = cv2.imdecode(np.fromfile(b[3], np.uint8), cv2.IMREAD_COLOR)
        img = cache[b[3]]
        x, y, r = int(b[4]), int(b[5]), CROP // 2
        c = img[max(0, y - r) : y + r, max(0, x - r) : x + r]
        return c if c.shape[:2] == (CROP, CROP) else None

    unk = [(b, crop(b)) for b in badges.get("Unidentified", [])]
    unk = [(b, c) for b, c in unk if c is not None]
    feats = []
    yy, xx = np.mgrid[:CROP, :CROP]
    inner = np.hypot(xx - CROP / 2, yy - CROP / 2) < 12
    for _, c in unk:
        hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], inner.astype(np.uint8), [12, 3, 3], [0, 180, 0, 256, 0, 256]).ravel()
        hist /= max(1e-6, hist.sum())
        g = cv2.resize(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)[8:-8, 8:-8], (10, 10)).astype(np.float32).ravel()
        g = (g - g.mean()) / (g.std() + 1e-6)
        feats.append(np.concatenate([hist * 4, g * 0.08]))
    k = min(N_GROUPS, len(feats))
    if k >= 2:
        _, lab, _ = cv2.kmeans(
            np.array(feats, np.float32),
            k,
            None,
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-3),
            8,
            cv2.KMEANS_PP_CENTERS,
        )
        groups = lab.ravel() + 1
    else:
        groups = np.ones(len(feats), int)
    order = sorted(set(groups), key=lambda gnum: -int((groups == gnum).sum()))
    rows, record = [], {}

    def row(label, crops):
        crops = [cv2.resize(c, (TILE, TILE), interpolation=cv2.INTER_CUBIC) for c in crops[:PER_ROW]]
        crops += [np.zeros((TILE, TILE, 3), np.uint8)] * (PER_ROW - len(crops))
        lab = np.full((TILE, 230, 3), 30, np.uint8)
        for k, line in enumerate(label.split("\n")):
            cv2.putText(lab, line, (6, 24 + 22 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        rows.append(np.hstack([lab] + crops))

    for k, gnum in enumerate(order, 1):
        members = [unk[i] for i in np.nonzero(groups == gnum)[0]]
        row(f"G{k}  unidentified\n{len(members)} badge(s)", [c for _, c in members])
        record[f"G{k}"] = [[round(b[1], 1), round(b[2], 1)] for b, _ in members]
    rows.append(np.full((10, rows[0].shape[1], 3), 90, np.uint8))
    for t in CHECK_TYPES:
        bs = badges.get(t, [])
        cs = [c for c in (crop(b) for b in bs[:PER_ROW]) if c is not None]
        if cs:
            row(f"matched as\n{t} ({len(bs)})", cs)
    if args.taught:  # what the hand-taught references named, to check them
        rows.append(np.full((10, rows[0].shape[1], 3), 90, np.uint8))
        for t in sorted(n for n in badges if n not in CHECK_TYPES and n != "Unidentified"):
            bs = [b for b in badges[t] if b[7] == "taught"]
            cs = [c for c in (crop(b) for b in bs[:PER_ROW]) if c is not None]
            if cs:
                row(f"taught as\n{t} ({len(bs)})", cs)
    out = Path(args.out) if args.out else core.atlas_files(atlas_path) / (atlas_path.stem + "_badges.png")
    cv2.imencode(".png", np.vstack(rows))[1].tofile(str(out))
    out.with_suffix(".json").write_text(json.dumps(record), encoding="utf-8")
    print(f"{len(unk)} unidentified badges in {len(order)} groups -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
