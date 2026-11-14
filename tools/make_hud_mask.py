"""Build references/hud_mask_full.png (white = game interface) from a 1920x1080 screenshot of the atlas taken
over black unexplored fog: everything that isn't black there is interface.

    python -m tools.make_hud_mask "path/to/black_screenshot.png"

On top of the bright pixels: gaps up to GAP px are closed (no map nodes "found" between letters or between
buttons), the dark insides of buttons / globes are filled, and a few areas are filled whole because what is
drawn there changes (stat numbers change width, the act-tab row and side strips sit apart from the frame).
"""

from __future__ import annotations

import sys

import cv2
import numpy as np

from grand_project import paths

BLACK = 6  # brightest channel above this = interface (unexplored fog stays at 0..4)
GAP = 25  # px: gaps this narrow inside the interface are closed
EDGE = 2  # px: grown at the end (soft, glowing edges)
# filled whole (1920x1080 px), marked by the user
FILL_RECTS = [
    (690, 0, 1240, 96),  # act-tab row, joined to the header
    (0, 0, 48, 201),  # top-left edge, buttons down to the left column
    (0, 750, 243, 1080),  # Life / Shield / Ward / Reserved and the left globe
    (1720, 780, 1920, 1080),  # Mana / Spirit / Rage and the right globe
    (1855, 726, 1920, 780),  # ... joined to the right icon column
]
FILL_POLYS = [
    [(243, 921), (476, 931), (636, 940), (636, 1080), (243, 1080)],  # bottom-left bar out to the counter box
]


def build(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    m = (img.max(axis=2) > BLACK).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (GAP, GAP)))
    sx, sy = w / 1920, h / 1080
    for x0, y0, x1, y1 in FILL_RECTS:
        m[round(y0 * sy) : round(y1 * sy), round(x0 * sx) : round(x1 * sx)] = 255
    for poly in FILL_POLYS:
        cv2.fillPoly(m, [np.round(np.array(poly) * [sx, sy]).astype(np.int32)], 255)
    # fill enclosed dark insides: everything not reachable from the middle of the screen is interface
    ff = m.copy()
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (w // 2, h // 2), 128)
    m = np.where(ff == 128, 0, 255).astype(np.uint8)
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * EDGE + 1, 2 * EDGE + 1)))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    img = cv2.imdecode(np.fromfile(sys.argv[1], np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.shape[:2] != (1080, 1920):
        sys.exit("need a 1920x1080 screenshot")
    m = build(img)
    out = paths.ref("hud_mask_full.png")
    cv2.imencode(".png", m)[1].tofile(str(out))
    print(f"{out}: {100 * (m > 0).mean():.1f}% interface")


if __name__ == "__main__":
    main()
