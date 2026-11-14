# AGENTS.md

Notes for AI coding agents (and new contributors) working on The Grand Project. Read this before starting a task;
the README covers what the program does and how players use it.

## What this is

A Path of Exile 2 atlas mapper: it stitches the player's atlas screenshots into one map, detects map nodes, paths,
icons and landmarks (towers, cities, halls, strongholds), and shows them in a Tk viewer. Python 3.11+, OpenCV,
NumPy, SciPy, scikit-learn. It must run on Windows, macOS and Linux.

## Words (use the author's terms in code comments, docs and replies)

- **map nodes**: the circular maps on the atlas that paths lead to (the code often says "maps" or "nodes")
- **paths**: the yellow dashed lines between map nodes
- **icons**: the round pictures above a map node (the code calls them "badges"; say "icons" to people)
- **cities**: a map node with the red deadly-boss icon and a citadel next to it; its map node always stands on a
  brass barrel (completed, green cities keep the barrel but lose icon and beam). Three types: Ezomyte, Vaal,
  Faridun (desert); Ezomyte and Vaal biomes look alike.
- **citadels**: the structure next to a city (Vaal: stepped pyramid; Ezomyte: dark walled ring; Faridun:
  green-roofed fortress in sand); always the same orientation
- **halls**: deadly-boss map on a normal base with an orange beam on a structure next to it
- **deadly bosses**: map nodes with the red "powerful map boss" icon

## Layout

`grand_project/` is the package (see the README's *Code layout* table): `core/` (screenshots, placement, the atlas
file, terrain, waiting groups `islands.py`, clean map `seams.py`), `detect/` (the per-screenshot detector),
`finalize/` (the atlas-wide check), `viewer/` (the window, one mixin per file), plus `builder.py`, `cities.py`,
`towers.py`, `paths.py` (every folder location). `tools/` are developer helpers, `tests/` regression tests,
`references/` every data file the program reads.

## Conventions

- **Constants live in the package's `constants.py`** (`core/constants.py`, `detect/constants.py`,
  `finalize/constants.py`, `viewer/constants.py`), never at the top of the module that uses them. Give them a
  prefix that says where they belong (`SEAM_...`, `ISLAND_...`, `CITY_BARREL_...`) and a comment saying what the
  number means and, if it was measured or tuned, on what. A constant a test patches is read live through the
  module (`K.HORIZON`, not a copied name).
- **Imports and running**: always `python -m package.module` (tests: `python -m tests.test_x`, tools:
  `python -m tools.x`). No `sys.path` hacks. Subpackage `__init__.py` files re-export names explicitly.
- **Lint before every commit**: `ruff check grand_project tools tests` and `ruff format grand_project tools tests`
  (line length 120; CI fails on unformatted code). `make lint` runs both.
- **Cross-platform**: no Windows-only APIs; paths with `pathlib`; launchers exist for both `.bat` and `.sh`.
- **Screenshots** are read with `core.read_screenshot` (scales 1440p / 4K whole game windows to 1080p); training
  and reference images are not.
- **Models**: no pickles from outside. Detector models are skops archives loaded with an allowlist
  (`test_model_safety`); small models are stored as plain arrays in `.npz` (e.g. `references/city_barrel.npz`).
- **Viewer**: never block the Tk thread. Background work goes through the viewer's queue; CPU-heavy work that
  would starve the window (Python's GIL) runs as its own process (`python -m grand_project.core.seams ...`), not a
  thread and not `multiprocessing` (spawn re-runs the caller's main script).
- **Comments** explain why, in plain words; user rules are marked as such ("user's rule").

## Tests

Offline tests (CI runs these): `test_atlas_builder test_atlas_io test_model_safety test_atlas_folder
test_random_sequence test_drop_placement test_false_merge test_detect_pairs`. `test_atlas_viewer` opens a window
(about a minute) and `test_waiting_islands` takes ~10 minutes. Tests needing the trimmed test data skip without it
(Git LFS, see README). Detector changes: compare `python -m grand_project.detect score` before and after. When
piping test output on Windows set `PYTHONIOENCODING=utf-8` (some checks print non-ASCII).

## Git workflow

- `develop` is the default branch; `main` is protected and only updated from develop by `make_release.py`
  (player release, no debug options or test files) through a pull request.
- **Never push straight to develop.** Work on a branch and open a pull request to `develop`, so changes can be
  reviewed first.
- Don't commit test outputs, local data (`local_paths.json`, `user_data/`, atlases) or large binaries outside LFS.
- Bump `__version__` (`grand_project/__init__.py`, `pyproject.toml`, README title) once per round of changes.
