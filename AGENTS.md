# AGENTS.md

Notes for AI coding agents (and new contributors) working on The Grand Project. Read this before starting a task;
the README covers what the program does and how players use it.

## What this is

A Path of Exile 2 atlas mapper: it stitches the player's atlas screenshots into one map, detects map nodes, paths,
icons and landmarks (towers, cities, halls, strongholds), and shows them in a web app: a local server (Python
3.11+, standard library HTTP, OpenCV, NumPy, SciPy, scikit-learn) and a React page on MapLibre (`frontend/`).
It must run on Windows, macOS and Linux.

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
`finalize/` (the atlas-wide check), `app/` (the server and the session, one mixin per file), `webmap/` (tiles),
plus `builder.py`, `cities.py`, `towers.py`, `paths.py` (every folder location). `frontend/` is the page (see the
README's developer section). `tools/` are developer helpers, `tests/` regression tests,
`references/` every data file the program reads.

## Conventions

- **Constants live in the package's `constants.py`** (`core/constants.py`, `detect/constants.py`,
  `finalize/constants.py`, `app/constants.py`, `webmap/constants.py`), never at the top of the module that uses them. Give them a
  prefix that says where they belong (`SEAM_...`, `ISLAND_...`, `CITY_BARREL_...`) and a comment saying what the
  number means and, if it was measured or tuned, on what. A constant a test patches is read live through the
  module (`K.HORIZON`, not a copied name).
- **Imports and running**: always `python -m package.module` (tests: `pytest tests/test_x.py`, tools:
  `python -m tools.x`). No `sys.path` hacks. Subpackage `__init__.py` files re-export names explicitly.
- **Lint before every commit**: `ruff check grand_project tools tests` and `ruff format grand_project tools tests`
  (line length 120; CI fails on unformatted code). `make lint` runs both. Page changes: `npm run lint`,
  `npm run typecheck`, `npm test` and `npm run build` in `frontend/`.
- **Cross-platform**: no Windows-only APIs; paths with `pathlib`; launchers exist for both `.bat` and `.sh`.
- **Screenshots** are read with `core.read_screenshot` (scales 1440p / 4K whole game windows to 1080p); training
  and reference images are not.
- **Models**: no pickles from outside. Detector models are skops archives loaded with an allowlist
  (`test_model_safety`); small models are stored as plain arrays in `.npz` (e.g. `references/city_barrel.npz`).
- **Icons: finding vs naming.** Finding (is there an icon here?) uses only frozen data (`references/badge_finder.npz`: rim template + one picture set); naming (which icon?) uses the growing stored pictures. Teaching icons must never change what is found; re-freeze only on purpose (`python -m tools.freeze_badge_finder`, then retrain and re-score).
- **App**: requests are answered on their own threads; the session changes the atlas only under its lock, and
  long work runs on the session's worker (or a background thread) and reports through `Events` (log, progress,
  versions, questions). CPU-heavy work that would starve the server (Python's GIL) runs as its own process
  (`python -m grand_project.core.seams ...`), not a thread and not `multiprocessing` (spawn re-runs the caller's
  main script). The exception is a batch of the same job (detecting many screenshots, the check's path tracing):
  it goes through `fileio.process_pool`, whose workers each keep to their share of the CPU's threads (uncapped,
  every worker started one per CPU and detection ran 2.7x slower). Anything that changes what the map's tiles hold
  bumps a version (model, map image, filters): tile URLs carry it, so the browser keeps tiles until they really
  change.
- **The open atlas is one record** (`session.opened`: atlas, path, generation, log scope), swapped only in
  `AtlasSession._switch`. Work that outlives a request takes the record once when it starts, uses its parts (never
  `self.atlas` / `self.generation` read again later), checks `owns(record)` under the lock before applying a result,
  and logs with the record's scope. A check and the claim it guards go in one locked step (a "running" flag set and
  cleared under the same lock as the result). Changes made for an atlas no longer open raise `StaleAtlas` (409).
- **Page** (`frontend/`): the structure of a shadcn/ui + TanStack Query app (`api/`, `domain/`, `hooks/`, `store/`,
  `logic/`, `components/`, `pages/`; PascalCase files). Server data through TanStack Query hooks (the app's events
  invalidate them), page-only state in the Zustand store. The map is react-map-gl's `<Map>` (`components/map/AtlasMap.tsx`):
  what it draws are components under it, each a `<Source>` and its layers (`components/map/layers/`), whose looks are
  plain functions in `logic/map/` (testable without a map); every layer has a place in `logic/map/LayerOrder.ts` and goes
  in under its slot (`MapLayer`). What react-map-gl has no component for (events, the camera, canvas pictures, custom
  WebGL layers) goes through `useMapLibre()` in a component of its own. Drawing on the map (the Biome select lasso)
  is Terra Draw's (`components/map/draw/`), its layers in their slot too. Biome
  formats it (tabs, line width 120); one test file per component / module in `__tests__/`. No new dependencies
  without a reason. Every answer carries the atlas generation (`X-Atlas-Gen`); `api/Http.ts` drops stale ones, and
  page work that spans an await (exports, a question after a load) checks `sameAtlas()` again after it. The 3D
  view's WebGL layers (`logic/*Layer3D.ts`) pick through `logic/PickPass.ts` and are added by `useCustomLayer`;
  ids and steps are worked out in the vertex shader (fragment shaders may be 16-bit).
- **Comments** explain why, in plain words; user rules are marked as such ("user's rule").

## Tests

pytest, from the program folder. `pytest` alone runs the offline tests and the ones that need the test screenshots
(those skip themselves without the Git LFS data: marker `data`); `pytest -m slow` runs the waiting-islands test
(~10 minutes), `pytest -m ""` everything. The page: `npm test` in `frontend/` (Vitest). The map's parts are tested on a
fake map (`src/test/`: `renderOnMap` with react-map-gl mocked by `ReactMapGlMock`, `FakeMap`, `FakeGl` for the 3D
view's WebGL layers); their looks stay plain functions in `logic/map/`. Randomised tests
take `--runs N --seed S` and print their seed. Shared fixtures and helpers live in `tests/conftest.py` (test data
paths, the crawl atlas, `check` for scenario tests that report every failed check, `copy_cache`, `seed` / `rng`);
use them instead of module-level setup, and `tmp_path` instead of temporary folders made by hand. Detector changes:
compare `python -m grand_project.detect score` before and after. When piping test output on Windows set
`PYTHONIOENCODING=utf-8` (some checks print non-ASCII).

The browser tests (`frontend/e2e/`, Playwright: `make e2e`) run the real app on the hand-made atlas of
`tests/e2e_atlas.py` and drive the built page: add one there for a flow that crosses the page and the app (the map,
clicking it, dialogs that save). `Adding.spec.ts` adds made-up screenshots while the page is used (the detection's
worker processes, the job queue, refusals while busy, auto-add) and `RealAdding.spec.ts` real ones from the test data
(skipped without it): run them after changing how detection or adding runs in parallel. They keep the app's settings in `e2e-run/user_data` (`GRAND_PROJECT_USER_DATA`),
never the player's. Coverage: `make coverage` (Python, settings in `pyproject.toml`) and `npm run coverage` (the
page); CI runs the tests on Windows, macOS and Linux, measures coverage on the Ubuntu jobs, shows the Python and page tables
on the `tests` run's page and comments the Python one on pull requests. Its last job, "tests passed"
(`tools/ci_tests_passed.py`), is the check to require before merging: every test passed on at least one system and
none failed (a macOS job cancelled before a runner took it doesn't block). A new
module gets its own test file (one per module or class under test).

## Git workflow

- `develop` is the default branch; `main` is protected and only updated from develop by `tools/make_release.py`
  (player release, no debug options or test files) through a pull request: `py -m tools.make_release --release 1.x`,
  the GitHub release's number (tag `v1.x`). It writes `manifest.json` (the release and a hash of each file,
  `grand_project/release_manifest.py`): the in-app update (`app/updater.py`, `app/update_apply.py`) compares it with
  the latest GitHub release's, and changes only the files listed in it.
- **Never push straight to develop.** Work on a branch and open a pull request to `develop`, so changes can be
  reviewed first.
- Don't commit test outputs, local data (`local_paths.json`, `user_data/`, atlases) or large binaries outside LFS.
- Bump `__version__` (`grand_project/__init__.py`, `pyproject.toml`, README title) once per round of changes.
