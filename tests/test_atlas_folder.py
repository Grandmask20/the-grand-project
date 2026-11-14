"""The atlas folder used as the screenshot folder (user's first choice): the atlas's own files must never be
taken for screenshots.   python -m tests.test_atlas_folder

1. 4 consecutive crawl screenshots copied into a folder; atlas.json made in that same folder; added twice
   (the second time nothing may be new: no atlas output counted as a screenshot)
2. everything the atlas wrote besides atlas.json + its detection cache sits in atlas_files/
3. an atlas from before v0.88 (outputs next to atlas.json) gets them moved into atlas_files/ and they are
   ignored as screenshots even where they still lie
"""

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
from grand_project import paths as rc_paths  # noqa: E402

rc_paths.need_test_data()
TD = rc_paths.TEST_DATA

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from grand_project import builder as B  # noqa: E402
from grand_project import core  # noqa: E402

ok = True


def check(cond, what):
    global ok
    ok &= bool(cond)
    print(("ok   " if cond else "FAIL ") + what)


crawl = sorted((TD / "screenshots" / "crawl").glob("*.png"))[100:104]
cache = TD / "crawl_atlas" / "atlas_frames"
work = Path(tempfile.mkdtemp())
for p in crawl:
    shutil.copy2(p, work / p.name)
atlas_path = work / "atlas.json"
frames_dir = work / "atlas_frames"
frames_dir.mkdir()
for p in crawl:  # cached detections: no detector run needed
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    shutil.copy2(cache / f"{h}_detect1.json", frames_dir / f"{h}_detect1.json")

shots = core.screenshots_in(work)
check(len(shots) == 4, f"4 screenshots in the atlas folder ({len(shots)})")
at = core.Atlas()
frames = [B.extract_frame(p, Path("unused"), frames_dir) for p in shots]
added, refused = B.place_frames(at, frames, log=lambda *_: None)
at.save(atlas_path)
B.export(at, atlas_path)
cv2.imencode(".png", np.zeros((3128, 3994, 3), np.uint8))[1].tofile(
    str(core.atlas_files(atlas_path) / "atlas_terrain.png")
)  # what the viewer's map cache writes
check(added == 4, f"all 4 placed ({added})")

top = sorted(p.name for p in work.iterdir() if p.is_file())
check(
    top == sorted([p.name for p in crawl] + ["atlas.json"]),
    f"only the screenshots + atlas.json at the top of the folder ({len(top)} files)",
)
check(
    all((work / "atlas_files" / n).exists() for n in ("atlas_composite.png", "atlas_network.png", "atlas_terrain.png")),
    "exports + map cache in atlas_files/",
)
again = core.screenshots_in(work)
check([p.name for p in again] == [p.name for p in shots], "adding the folder again finds only the same 4 screenshots")

# an old atlas: outputs next to atlas.json
old = Path(tempfile.mkdtemp())
for n in ("atlas_terrain.png", "atlas_composite.png", "atlas_network.png"):
    cv2.imencode(".png", np.zeros((8, 8, 3), np.uint8))[1].tofile(str(old / n))
(old / "atlas_undo").mkdir()
shutil.copy2(crawl[0], old / crawl[0].name)
check(
    [p.name for p in core.screenshots_in(old)] == [crawl[0].name], "old outputs next to atlas.json are not screenshots"
)
d = core.atlas_files(old / "atlas.json")
check(
    sorted(p.name for p in d.iterdir())
    == ["atlas_composite.png", "atlas_network.png", "atlas_terrain.png", "atlas_undo"],
    "old outputs moved into atlas_files/",
)
check(sorted(p.name for p in old.iterdir() if p.is_file()) == [crawl[0].name], "nothing generated left at the top")

shutil.rmtree(work, ignore_errors=True)
shutil.rmtree(old, ignore_errors=True)
print("PASS: atlas folder = screenshot folder" if ok else "FAILED: atlas folder = screenshot folder")
if "pytest" in sys.modules:  # under pytest: a failure, not an exit
    assert ok, "see the FAIL lines above"
else:
    sys.exit(0 if ok else 1)
