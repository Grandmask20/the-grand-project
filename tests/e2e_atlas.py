"""Makes what the browser tests (frontend/e2e) work on: the atlas they open, and screenshots to add.

    python -m tests.e2e_atlas FOLDER          (emptied first) prints the atlas file's path

FOLDER/e2e           the hand-made atlas the app's tests use (15 maps, a Vaal city, a bookmark), with its screenshot
FOLDER/user_data     the app's settings while testing (GRAND_PROJECT_USER_DATA)
FOLDER/shots/<set>   made-up screenshots (no maps on them) for adding: the detection, its worker processes, the job
                     queue, auto-add and the page all run as with real ones, the screenshots just never line up
FOLDER/crawl         8 consecutive real crawl screenshots, only when the test data is there (Git LFS)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from grand_project import paths as rc_paths
from tests.webmap_data import make_atlas

# made-up screenshot sets: name -> how many (the spec adds each set once: a detection cached by an earlier set
# would make a job too quick to watch)
SHOT_SETS = {"batch": 6, "queued_a": 3, "queued_b": 3, "late": 3, "watch": 3}
CRAWL = slice(100, 108)  # consecutive crawl screenshots that line up (test_atlas_folder uses 100-103)


def made_up_screenshot(seed: int) -> np.ndarray:
    """A 1920x1080 picture for the detector: soft noise, nothing it takes for a map.

    Args:
        seed: Makes each one different.

    Returns:
        BGR image.
    """
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (135, 240, 3)).astype(np.uint8)
    return cv2.resize(small, (1920, 1080), interpolation=cv2.INTER_CUBIC)


def main(folder: str) -> Path:
    """Write the atlas, its map image cache and screenshot, and the screenshots to add.

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

    seed = 0
    for name, n in SHOT_SETS.items():
        d = base / "shots" / name
        d.mkdir(parents=True)
        for i in range(n):
            seed += 1
            # Steam's file names (app id, time, number): what the app expects of a screenshot
            cv2.imwrite(str(d / f"2694490_20261118{seed:02d}{i:02d}00_1.png"), made_up_screenshot(seed))
    (base / "watched").mkdir()  # auto-add's folder: the spec copies the "watch" set into it while it watches

    if rc_paths.test_data_problem() is None:
        crawl = sorted((rc_paths.TEST_DATA / "screenshots" / "crawl").glob("*.png"))[CRAWL]
        (base / "crawl").mkdir()
        for p in crawl:
            shutil.copy2(p, base / "crawl" / p.name)
    return path


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "e2e-run"))
