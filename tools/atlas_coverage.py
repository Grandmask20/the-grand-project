"""Coverage map: where each screenshot landed, and where the chain broke.

    python -m tools.atlas_coverage --atlas my_atlas.json --folder screenshots_folder [--out coverage.png]

Every placed screenshot is outlined and numbered in time order (file names sort by time).
Screenshots that could not be placed are listed; the last placed screenshot before each run of
unplaced ones is outlined in red, so you know where to take another pass.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
from grand_project import core  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path)
    shots = core.screenshots_in(args.folder)
    num = {p.stem: i for i, p in enumerate(shots)}
    placed = {f["name"]: f for f in atlas.frames}
    canvas, (x0, y0, sc) = atlas.composite(max_pixels=30_000_000)
    out = cv2.convertScaleAbs(canvas, alpha=0.7)

    def outline(f, col, th, label=True):
        H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        c = core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
        pts = ((c - [x0, y0]) * sc).astype(np.int32)
        cv2.polylines(out, [pts], True, col, th, cv2.LINE_AA)
        if label:
            m = pts.mean(axis=0).astype(int)
            t = f"#{num.get(f['name'], '?')}"
            cv2.putText(out, t, tuple(m), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(out, t, tuple(m), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)

    order = [p.stem for p in shots]
    for k, name in enumerate(order):
        if name in placed:
            hue = int(170 * k / max(1, len(order) - 1))  # colour runs through time
            col = cv2.cvtColor(np.uint8([[[hue, 200, 255]]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
            outline(placed[name], col, 2)
    gaps, k = [], 0
    while k < len(order):
        if order[k] in placed:
            k += 1
            continue
        j = k
        while j < len(order) and order[j] not in placed:
            j += 1
        before = next((order[i] for i in range(k - 1, -1, -1) if order[i] in placed), None)
        after = order[j] if j < len(order) else None
        gaps.append((k, j - 1, before, after))
        if before:
            outline(placed[before], (0, 0, 255), 6, label=False)
        k = j
    target = Path(args.out) if args.out else core.atlas_files(atlas_path) / (atlas_path.stem + "_coverage.png")
    cv2.imencode(".png", out)[1].tofile(str(target))
    print(f"{len(placed)} of {len(order)} screenshots placed -> {target}")
    for a, b, before, after in gaps:
        rng = f"#{a}" if a == b else f"#{a}-#{b}"
        print(
            f"  not placed: {rng} ({b - a + 1} shot(s)); last placed before: "
            f"{'#' + str(num[before]) if before else '-'}, next placed after: {'#' + str(num[after]) if after else '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
