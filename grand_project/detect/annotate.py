"""detect.annotate (from atlas_detect.py)"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from .constants import SHOTS, TRUTH
from .pipeline import detect

LM_STYLE = {
    "Tower": ((90, 230, 90), (60, 180)),
    "Breach stronghold": ((230, 120, 230), (90, 110)),
    "Locked stronghold": ((230, 120, 230), (90, 110)),
    "City": ((80, 200, 255), (110, 130)),
    "Hall": ((60, 150, 255), (110, 130)),
    "Deadly boss map": ((60, 60, 255), (60, 70)),
}


PATH_DRAW_SHIFT = -5  # px: paths drawn beside the game's own dotted lines, not on top of them


def annotate(img: np.ndarray, r: dict) -> np.ndarray:
    """everything the detector found, drawn on the screenshot (old-style notation, no subway)"""
    v = img.copy()
    cyan, pink = (255, 220, 60), (230, 130, 230)
    for e in r["edges"]:
        L = np.array(e["line"], float) + (PATH_DRAW_SHIFT, 0)
        seg = np.hypot(*np.diff(L, axis=0).T)
        pos = np.concatenate([[0], np.cumsum(seg)])
        for t in np.arange(0, pos[-1], 6.0):  # dotted
            i = min(int(np.searchsorted(pos, t, side="right")) - 1, len(seg) - 1)
            f = (t - pos[i]) / max(seg[i], 1e-6)
            q = L[i] + f * (L[i + 1] - L[i])
            cv2.circle(v, (int(q[0]), int(q[1])), 1, cyan, -1, cv2.LINE_AA)
    for n in r["nodes"]:
        x, y = int(n["x"]), int(n["y"])
        if n.get("hidden"):
            cv2.drawMarker(v, (x, y), pink, cv2.MARKER_SQUARE, 14, 1)
            cv2.putText(v, "Hidden", (x + 10, y + 4), 0, 0.45, pink, 1, cv2.LINE_AA)
        elif not n.get("tower"):
            cv2.circle(v, (x, y), 10, cyan, 2, cv2.LINE_AA)
            cv2.putText(v, "Map", (x + 12, y - 4), 0, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(v, "Map", (x + 12, y - 4), 0, 0.45, cyan, 1, cv2.LINE_AA)
    for landmark in r["landmarks"]:
        col, (w, h) = LM_STYLE.get(landmark["kind"], ((255, 255, 255), (80, 80)))
        x, y = int(landmark["x"]), int(landmark["y"])
        top = y - h + 15 if landmark["kind"] == "Tower" else y - h // 2
        cv2.rectangle(v, (x - w // 2, top), (x + w // 2, top + h), col, 2)
        cv2.drawMarker(v, (x, y), col, cv2.MARKER_CROSS, 10, 1)
        label = landmark["kind"] + (f" ({landmark['city_type']})" if landmark.get("city_type") else "")
        cv2.putText(v, label, (x + w // 2 + 4, top + 14), 0, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(v, label, (x + w // 2 + 4, top + 14), 0, 0.5, col, 1, cv2.LINE_AA)
    for b in r["icons"]:
        x, y = int(b["x"]), int(b["y"])
        cv2.circle(v, (x, y), 12, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(v, b["name"], (x - 24, y - 15), 0, 0.33, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(v, b["name"], (x - 24, y - 15), 0, 0.33, (255, 255, 255), 1, cv2.LINE_AA)
    return v


def cmd_show() -> int:
    """py atlas_detect.py show OUT_DIR IMG...   (or: show OUT_DIR random N  -> N random unlabelled samples)"""
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = sys.argv[3:]
    if files[:1] == ["random"]:
        import random

        truth = json.loads(TRUTH.read_text(encoding="utf-8"))
        pool = sorted(p for p in SHOTS.glob("*.png") if p.name not in truth)
        files = [str(p) for p in random.sample(pool, int(files[1]) if len(files) > 1 else 3)]
    for f in files:
        t0 = time.time()
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        r = detect(img)
        cv2.imwrite(str(out / f"{Path(f).stem}_annotated.png"), annotate(img, r))
        (out / f"{Path(f).stem}_detect.json").write_text(json.dumps(r, default=float), encoding="utf-8")
        hid = sum(1 for n in r["nodes"] if n.get("hidden"))
        print(
            f"{Path(f).name}: {len(r['nodes']) - hid} maps, {hid} hidden, {len(r['icons'])} badges, "
            f"{len(r['edges'])} paths, {len(r['landmarks'])} landmarks, {time.time() - t0:.0f} s"
        )
    return 0
