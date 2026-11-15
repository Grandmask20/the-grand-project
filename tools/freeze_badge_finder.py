"""Freeze what the icon FINDER uses into references/badge_finder.npz.

    python -m tools.freeze_badge_finder [DATABASE]

Finding an icon (is there one here?) and naming it (which one?) are separate. Naming compares the picture
inside the rim with every stored picture, and grows whenever icons are taught. Finding uses the rim template
(the average stored icon, compared on the rim only) and one "looks like a stored icon" score; if those followed
the stored pictures, teaching a new icon would change which icons are found. So they are frozen here, from
DATABASE (default: the current icon database), and only re-frozen on purpose (then retrain and re-score the
detector).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

from grand_project import icon_refs
from grand_project.detect.constants import BADGE_FINDER_FILE


def pictures(db: Path) -> list[np.ndarray]:
    c = sqlite3.connect(str(db))
    rows = c.execute("SELECT png FROM badge_refs ORDER BY id").fetchall()
    c.close()
    ims = [cv2.imdecode(np.frombuffer(p, np.uint8), cv2.IMREAD_COLOR) for (p,) in rows]
    return [im for im in ims if im is not None and im.shape[:2] == (icon_refs.SIZE, icon_refs.SIZE)]


def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else icon_refs.DB_PATH
    ims = pictures(db)
    template = np.mean([cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) for im in ims], 0)
    F = np.array([icon_refs.feature(im) for im in ims], np.float32)
    np.savez_compressed(BADGE_FINDER_FILE, template=template.astype(np.float32), F=F)
    print(f"{BADGE_FINDER_FILE}: {len(ims)} pictures from {db}")


if __name__ == "__main__":
    main()
