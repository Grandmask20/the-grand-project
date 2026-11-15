"""Build the icon finder's rim template: references/badge_finder.npz.

    python -m tools.freeze_badge_finder

Icons are found by their rim alone (it is the same on every icon), then named by what's inside. The template is
the average of the hand-labelled icons as they look on screen (each aligned to the average, two rounds); the
finder only compares the rim radii of it (detect.constants.ICON_RIM_R). Rebuild only on purpose, then retrain and
re-score the detector (python -m grand_project.detect train / score).
"""

from __future__ import annotations

import json

import cv2
import numpy as np

from grand_project.detect.constants import BADGE_FINDER_FILE, TRUTH_SETS

S = 40  # px: template size
SPECIAL = {"MapBossSpecial", "AbyssalDepths", "CorruptionNexus", "CorruptionNexusNoGrowth"}  # their own rims


def main():
    h = S // 2
    grey = []
    for tf, shots in TRUTH_SETS:
        if not tf.exists():
            continue
        for name, v in json.loads(tf.read_text(encoding="utf-8")).items():
            im = cv2.imdecode(np.fromfile(str(shots / name), np.uint8), cv2.IMREAD_GRAYSCALE)
            for b in v["badges"]:
                if b["name"] in SPECIAL or b["name"].startswith("ExpeditionShip"):
                    continue
                x, y = int(round(b["x"])), int(round(b["y"]))
                c = im[y - h : y + h, x - h : x + h]
                if c.shape == (S, S):
                    grey.append(c.astype(np.float32))
    mean = np.mean(grey, 0)
    for _ in range(2):  # align every icon to the average (labels are a pixel or two off), average again
        al = []
        for g in grey:
            r = cv2.matchTemplate(cv2.copyMakeBorder(g, 3, 3, 3, 3, cv2.BORDER_REPLICATE), mean, cv2.TM_CCOEFF_NORMED)
            _, _, _, (dx, dy) = cv2.minMaxLoc(r)
            M = np.float32([[1, 0, dx - 3], [0, 1, dy - 3]])
            al.append(cv2.warpAffine(g, M, (S, S), borderMode=cv2.BORDER_REPLICATE))
        mean = np.mean(al, 0)
    # the special icons' templates (detect.constants.SPECIAL_ICONS) are kept as they are
    keep = {}
    if BADGE_FINDER_FILE.exists():
        with np.load(BADGE_FINDER_FILE) as z:
            keep = {k: z[k] for k in z.files if k.startswith("special_")}
    np.savez_compressed(BADGE_FINDER_FILE, rim=mean.astype(np.float32), **keep)
    print(f"{BADGE_FINDER_FILE}: rim template from {len(grey)} hand-labelled icons")


if __name__ == "__main__":
    main()
