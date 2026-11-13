"""Where everything lives (one place, so the folders can be found and changed easily).

    <program folder>/
      Start Atlas Viewer.bat      double-click to run
      atlases/default/            the atlas opened on first start (screenshots + atlas.json)
      references/                 the reference database + every picture / data file the program reads
      program/                    the program (this folder)
      tools/                      labelling / training helpers (for improving the detector)
      tests/                      tests (their screenshots / truth are NOT shipped: see TEST_DATA)
      user_data/                  viewer settings and the debug log (made on first run)
"""
import os
import sys
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent
ROOT = PROGRAM.parent
REFERENCES = ROOT / "references"
DATABASE = REFERENCES / "atlas_references.sqlite3"
ATLASES = ROOT / "atlases"
DEFAULT_ATLAS = ATLASES / "default" / "atlas.json"
USER_DATA = ROOT / "user_data"
# test / training data (screenshots of a real atlas, hand-made truth). Looked for in this order: the
# ATLAS_TEST_DATA environment variable; "atlas_test_data" inside this folder (the GitHub repo keeps a trimmed
# set there, in Git LFS); "atlas_test_data" next to this folder (the full private set).
def _test_data() -> Path:
    if os.environ.get("ATLAS_TEST_DATA"):
        return Path(os.environ["ATLAS_TEST_DATA"])
    inside = ROOT / "atlas_test_data"
    return inside if (inside / "screenshots").is_dir() else ROOT.parent / "atlas_test_data"


TEST_DATA = _test_data()
SCREENSHOTS = TEST_DATA / "screenshots"

# a working copy can point at private data with ROOT/local_paths.json (NOT in the shared release), e.g.
#   {"DATABASE": "../node_references_0_18.sqlite3", "TEST_DATA": "../atlas_test_data"}
# relative paths are relative to ROOT
_LOCAL = ROOT / "local_paths.json"
if _LOCAL.exists():
    import json as _json
    for _k, _v in _json.loads(_LOCAL.read_text(encoding="utf-8")).items():
        if _k in ("DATABASE", "TEST_DATA", "ATLASES", "USER_DATA"):
            _p = Path(_v)
            globals()[_k] = (_p if _p.is_absolute() else ROOT / _p).resolve()
    SCREENSHOTS = TEST_DATA / "screenshots"
    DEFAULT_ATLAS = ATLASES / "default" / "atlas.json"


def ref(name: str) -> Path:
    """a file in the references folder"""
    return REFERENCES / name


def need_test_data() -> None:
    """for tests / tools that need the (not shipped) test screenshots: explain and stop if they are missing"""
    shot = next((TEST_DATA / "screenshots").rglob("*.png"), None) if (TEST_DATA / "screenshots").is_dir() else None
    pointer = shot is not None and shot.stat().st_size < 1024 and shot.read_bytes()[:20].startswith(b"version https")
    if shot is None or pointer:
        why = (f"test data {'not downloaded (Git LFS placeholders)' if pointer else 'not found'} at {TEST_DATA} "
               "(in the GitHub repo: git lfs pull --include=\"atlas_test_data/**\"; or set ATLAS_TEST_DATA)")
        if "pytest" in sys.modules:                     # under pytest: skip this file, don't end the whole run
            import pytest
            pytest.skip(why, allow_module_level=True)
        print("SKIP: " + why)
        sys.exit(0)


# which copy this is: "internal" (working copy with private data), "rc-1" (test release) or "release"
# (the public one); make_release.py writes channel.txt
_CH = ROOT / "channel.txt"
CHANNEL = "internal" if _LOCAL.exists() else (_CH.read_text(encoding="utf-8").strip() if _CH.exists() else "release")


def title_tag() -> str:
    """what the window title adds after the version ("" for the public release)"""
    return "" if CHANNEL == "release" else f" {CHANNEL}"
