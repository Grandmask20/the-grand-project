"""Build the trimmed, public test data set into the GitHub release folder (kept there in Git LFS).

    py make_test_pack.py              # -> ../1.0/atlas_test_data
    py make_test_pack.py --to NAME    # -> ../NAME/atlas_test_data

From the full private set (../atlas_test_data) it takes only what the tests and the detector score need:
- the 10 + 10 hand-labelled screenshots and their truth (truth/, truth_ocean/)
- the first CRAWL_SHOTS crawl screenshots plus the small test atlas's own 5
- the crawl atlas and the small atlas with the cached detections of those screenshots

Every saved path is rewritten to a relative one, so it works on any computer and contains no user name.
"""

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SRC = HERE.parent / "atlas_test_data"
TARGET = HERE.parent / (sys.argv[sys.argv.index("--to") + 1] if "--to" in sys.argv else "1.0") / "atlas_test_data"
CRAWL_SHOTS = 110  # test_atlas_folder uses crawl #100-#103; the viewer test needs a long run
TRUTH_FILES = ("truth.json", "truth_key.json", "labels.txt")  # (extra_maps.json: training only, its shots not here)
OCEAN_FILES = ("truth.json", "truth_key.json", "labels_ocean.txt", "ship_marker_template.png")

README = """# Test data (trimmed)

A small part of the author's own test set, so the tests and `atlas_detect.py score` can run on any computer:

| Folder | What |
|---|---|
| `screenshots/random_samples/`, `truth/` | 10 hand-labelled screenshots and their truth |
| `screenshots/ocean/`, `truth_ocean/` | 10 hand-labelled ocean (Expedition) screenshots |
| `screenshots/crawl/` | the first {crawl} screenshots of a crawl across the atlas, plus the small atlas's 5 |
| `crawl_atlas/`, `small_atlas/` | finished atlases of those screenshots, with their cached detections |

It is stored with Git LFS and is NOT downloaded by a normal clone (see `.lfsconfig`). To get it:

    git lfs pull --include="atlas_test_data/**"

Training needs more data (tower shots, painted walls, the arborist rounds); that is not included.
"""


def _strip_paths(v):
    """any absolute file path in a JSON value -> its file name"""
    if isinstance(v, dict):
        return {_strip_paths(k): _strip_paths(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strip_paths(x) for x in v]
    if isinstance(v, str) and (v[1:3] in (":\\", ":/") or v.startswith("/home/") or v.startswith("/Users/")):
        return v.replace("\\", "/").rsplit("/", 1)[-1]
    return v


def rel_frames(atlas_json: Path, out_json: Path, keep: set[str]) -> dict:
    """copy an atlas with its screenshot paths made relative to the atlas file (frames for screenshots that
    are not in the pack keep their place, so the atlas stays whole; they simply have no image)"""
    d = json.loads(atlas_json.read_text(encoding="utf-8"))
    for f in d["frames"]:
        name = Path(f["path"]).name
        f["path"] = f"../screenshots/crawl/{name}" if name in keep else name
    out_json.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d


def copy_detections(src_dir: Path, out_dir: Path, shas: set[str]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in src_dir.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("sha256") not in shas:
            continue
        d["path"] = Path(d.get("path", "")).name  # no absolute path (the loader uses the real file)
        (out_dir / f.name).write_text(json.dumps(d), encoding="utf-8")
        n += 1
    return n


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"full test data not found at {SRC}")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "screenshots").mkdir(parents=True)
    # labelled sets
    for sub, files, shots in (("truth", TRUTH_FILES, "random_samples"), ("truth_ocean", OCEAN_FILES, "ocean")):
        (TARGET / sub).mkdir()
        for name in files:
            if not (SRC / sub / name).exists():
                continue
            if name.endswith(".json"):
                d = _strip_paths(json.loads((SRC / sub / name).read_text(encoding="utf-8")))
                (TARGET / sub / name).write_text(json.dumps(d, indent=1), encoding="utf-8")
            else:
                shutil.copy2(SRC / sub / name, TARGET / sub / name)
        truth = json.loads((SRC / sub / "truth.json").read_text(encoding="utf-8"))
        (TARGET / "screenshots" / shots).mkdir()
        for name in truth:
            shutil.copy2(SRC / "screenshots" / shots / name, TARGET / "screenshots" / shots / name)
    # crawl screenshots: the first CRAWL_SHOTS + the small atlas's own
    crawl = sorted((SRC / "screenshots" / "crawl").glob("*.png"))
    small = json.loads((SRC / "small_atlas" / "atlas.json").read_text(encoding="utf-8"))
    keep = {p.name for p in crawl[:CRAWL_SHOTS]} | {Path(f["path"]).name for f in small["frames"]}
    (TARGET / "screenshots" / "crawl").mkdir()
    for name in sorted(keep):
        shutil.copy2(SRC / "screenshots" / "crawl" / name, TARGET / "screenshots" / "crawl" / name)
    # atlases + their cached detections (only for the screenshots in the pack)
    for a in ("crawl_atlas", "small_atlas"):
        (TARGET / a).mkdir()
        d = rel_frames(SRC / a / "atlas.json", TARGET / a / "atlas.json", keep)
        shas = {f["sha"] for f in d["frames"] if Path(f["path"]).name in keep}
        n = copy_detections(SRC / a / "atlas_frames", TARGET / a / "atlas_frames", shas)
        print(f"{a}: {len(d['frames'])} frames, {n} cached detections")
    (TARGET / "README.md").write_text(README.format(crawl=CRAWL_SHOTS), encoding="utf-8")
    # nothing personal left?
    bad = [
        str(p.relative_to(TARGET))
        for p in TARGET.rglob("*")
        if p.suffix in (".json", ".txt", ".md")
        and any(s in p.read_text(encoding="utf-8", errors="ignore") for s in ("C:\\\\Users", "C:/Users", "/home/"))
    ]
    size = sum(p.stat().st_size for p in TARGET.rglob("*") if p.is_file())
    print(f"test pack: {sum(1 for _ in TARGET.rglob('*.png'))} pictures, {size / 1e6:.0f} MB -> {TARGET}")
    if bad:
        raise SystemExit(f"absolute paths left in: {bad[:5]}")


if __name__ == "__main__":
    main()
