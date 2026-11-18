"""Makes the atlas the browser tests open (frontend/e2e): the hand-made one the app's tests use, with a screenshot.

python -m tests.e2e_atlas FOLDER          (emptied first) prints the atlas file's path; FOLDER/user_data is
                                          made for the app's settings (GRAND_PROJECT_USER_DATA)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from tests.webmap_data import make_atlas


def main(folder: str) -> Path:
    """Write the atlas (in FOLDER/e2e), its map image cache and its one screenshot.

    Args:
        folder: Where (emptied first, made if needed).

    Returns:
        The atlas file.
    """
    base = Path(folder)
    shutil.rmtree(base, ignore_errors=True)  # a run starts from nothing
    (base / "user_data").mkdir(parents=True)
    out = base / "e2e"
    out.mkdir()
    path, _pts, _img = make_atlas(out)
    # the atlas's one screenshot, so Screenshots of this spot has a picture to show
    shot = np.full((1080, 1920, 3), 40, np.uint8)
    cv2.putText(shot, "e2e screenshot", (700, 560), cv2.FONT_HERSHEY_SIMPLEX, 2, (200, 200, 200), 3)
    cv2.imwrite(str(out / "a.png"), shot)
    return path


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "e2e-run"))
