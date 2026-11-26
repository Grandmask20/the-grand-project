"""Where everything lives (one place, so the folders can be found and changed easily).

<program folder>/
  Start The Grand Project.bat double-click to run
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
    """Find the test / training data folder.

    Looked for in this order: the ATLAS_TEST_DATA environment variable; "atlas_test_data" inside this folder
    (with a screenshots folder); "atlas_test_data" next to this folder.

    Returns:
        The folder path (it may not exist).
    """
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
    """Return a file in the references folder.

    Args:
        name: File name.

    Returns:
        Path of the file.
    """
    return REFERENCES / name


def test_data_problem() -> str | None:
    """Why the (not shipped) test screenshots can't be used.

    Returns:
        A sentence saying what is wrong (not found, or Git LFS placeholders not downloaded) and how to get
        them, or None when they are there.
    """
    shot = next((TEST_DATA / "screenshots").rglob("*.png"), None) if (TEST_DATA / "screenshots").is_dir() else None
    pointer = shot is not None and shot.stat().st_size < 1024 and shot.read_bytes()[:20].startswith(b"version https")
    if shot is None or pointer:
        return (
            f"test data {'not downloaded (Git LFS placeholders)' if pointer else 'not found'} at {TEST_DATA} "
            '(in the GitHub repo: git lfs pull --include="atlas_test_data/**"; or set ATLAS_TEST_DATA)'
        )
    return None


def need_test_data() -> None:
    """Stop if the (not shipped) test screenshots are missing; for tools that need them.

    Prints why (test_data_problem) and exits with code 0. Tests use the `data` marker instead (tests/conftest.py).
    """
    why = test_data_problem()
    if why:
        print("SKIP: " + why)
        sys.exit(0)


# the desktop app (desktop/: Electron, with this program frozen inside it) sets these: its program folder is replaced by
# each update, so the player's atlases and settings live in a folder of their own (GRAND_PROJECT_HOME: the desktop
# app's data folder, e.g. %APPDATA%/The Grand Project), and the in-app update is the desktop app's (app/updater.py)
DESKTOP = bool(os.environ.get("GRAND_PROJECT_DESKTOP"))
if os.environ.get("GRAND_PROJECT_HOME"):
    _HOME = Path(os.environ["GRAND_PROJECT_HOME"]).resolve()
    ATLASES, USER_DATA = _HOME / "atlases", _HOME / "user_data"
    DEFAULT_ATLAS = ATLASES / "default" / "atlas.json"


# the browser tests (frontend/e2e) and CI keep the app's settings and log away from the player's own
if os.environ.get("GRAND_PROJECT_USER_DATA"):
    USER_DATA = Path(os.environ["GRAND_PROJECT_USER_DATA"]).resolve()


# which copy this is: "internal" (the author's working copy: local_paths.json), "develop" (the GitHub develop
# branch, channel.txt) or "release" (the player build on GitHub main, channel.txt; also the default)
_CH = ROOT / "channel.txt"
CHANNEL = "internal" if _LOCAL.exists() else (_CH.read_text(encoding="utf-8").strip() if _CH.exists() else "release")


# the debug tools (Debug tab, right-click Debug menu, debug marks on the map): in the working copy and the
# develop branch, never in the player release (main)
DEBUG = CHANNEL != "release"


def title_tag() -> str:
    """Return what the window title adds after the version ("" for the public release).

    Returns:
        " internal" / " develop", or "" for the release.
    """
    return "" if CHANNEL == "release" else f" {CHANNEL}"
