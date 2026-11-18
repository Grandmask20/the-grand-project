# The Grand Project — v1.17

Builds one big map of your Path of Exile 2 atlas from your screenshots. Named after the in-game tablet, *The Grand Project*. It finds maps, paths, icons, towers and cities, and lets you search, bookmark and route through them.

The app runs in your web browser: starting it opens a page served by the program on this computer (`http://127.0.0.1:8765`). Nothing leaves your computer.

## Run it

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Double-click **`Install (run once).bat`**.
3. Double-click **`Start Atlas Viewer.bat`**. Your browser opens the app. To stop it: **File ▾ → Quit the app**.

**macOS / Linux:**

1. Install Python 3.11 or newer.
2. In a terminal, in this folder, run `./install.sh` (once). It makes a `.venv` folder and installs the packages there.
3. Run `./start.sh` (Ctrl+C in the terminal, or **File ▾ → Quit the app**, stops it).

On macOS right-click is a two-finger click (or Ctrl+click).

On first start the app opens the empty atlas **`atlases/default`**.

---

## Before you start: Steam screenshots

**Resolution:** the detector was trained on 1080p screenshots. 1440p and 4K screenshots are scaled down to 1080p and work too (4K files are about 4 times larger). Keep the game's **render resolution at 100%**: lower settings blur the maps and paths, and fewer of them are found.

Use Steam's screenshot key (**F12** by default); it's the fastest and most reliable way.

In Steam, open **Settings → In Game → Screenshots** and:

- turn on **Save an external copy of my screenshots**: this saves a full-quality PNG, which the program needs (Steam's own library copies are JPG, and the compression blurs the path dashes)
- leave **Save external HDR screenshots as AVIF** off, so the copies stay PNG
- set the **External screenshots folder** to the atlas you are building: `atlases/default/` inside this program's folder (click **Change folder** and pick it)

Screenshots then land straight in the atlas folder as `2694490_<date>_1.png`, and the app picks them up from there. Point the folder back to your usual one when you are done mapping, so your other screenshots don't end up in the atlas.

## 1. Start an atlas

1. In the app, go to the **Auto-add tab** and turn on *Add new screenshots automatically*. The app watches the open atlas's own folder, which is where Steam is now saving.
2. In game, open the atlas centred on the **fortress** (the giant walled structure in the middle) and press F12. The HUD can stay on screen; it is masked out.
3. Pan a little (keep about half the screen overlapping) and press F12 again. Repeat outward from the fortress in any direction. Each screenshot is added while you play.

For screenshots you already have, copy them into `atlases/default/` and use the **Atlas ▾** button → `default` → **Add new screenshots from its folder**.

The first screenshot becomes the centre, and every next one is placed where it overlaps the ones already in the atlas.

The fortress itself places poorly, because its walls cut the paths. Start right at its edge and move outward.

## 2. Add new maps

Any of these adds screenshots. Screenshots already in the atlas are skipped.

- **Auto-add tab → Add new screenshots automatically.** Each new screenshot that Steam saves into the atlas folder is added while you play. When the app starts (or you start watching), screenshots already in that folder that the atlas doesn't have yet are added too. **Watch another folder…** watches a different folder instead, and **Atlas folder** switches back.
- **Drag and drop** screenshot files onto the map: one is placed by hand where you drag it, several are added. (They are copied into the atlas folder.)
- **File ▾ → Add screenshots…** (File ▾ is the first button on the toolbar)
- **Atlas ▾ → (atlas) → Add new screenshots from its folder.**

A screenshot that overlaps nothing yet goes to **Waiting** (Auto-add tab). Waiting screenshots are retried whenever another one is added, and you can also click **Retry** or **Retry all**.

A screenshot that might be placed wrong is shown on the map, see-through and outlined, while the app asks whether to add it.

- **Place by hand…** (File ▾, or a waiting screenshot's **Place by hand**) shows the screenshot see-through: drag it roughly where it belongs, then press Enter or double-click.
- **Undo last add** removes the last screenshot that was added.

## 3. View the atlas

- **Mouse:** wheel to zoom at the cursor, drag to pan, right-drag (or Ctrl-drag) to tilt and turn, click a map or a path to select it (its details show in the Find tab). Zoomed in, the ground is built sharp from your screenshots themselves.
- **Keys:** `+` / `-` zoom, `0` fit, arrows pan, Esc cancels what you were doing.
- **Map buttons** (top right): zoom, compass, **⤢** fit the whole atlas, **3D** (tilted view with models of maps, towers, citadels, halls and strongholds), full screen.
- **View tab:**
  - **Background:** *Picture* (the stitched screenshots), *Vector* (flat land with the city / stronghold / ground biomes as areas) or *Off*.
  - **Show on the map:** Ground, Paths, Maps, Icons, Landmarks, Bookmarks, Names, Biomes, Recent additions, Doubtful, Removed, 3D models, Route and Debug marks.
  - **Paths:** colour (click the square), width, style (solid / dashed / dotted), and *drawn by at least N%* of the screenshots that show both maps.
  - **Maps:** colour, size and style (circles / squares / hidden).
  - **City biomes and landmarks:** their colours.
  - **Colour by:** each screenshot's area by session, oldest to newest, or *times seen* (a heatmap), in a colour spread you pick.
  - **Pictures on the map** (zoomed in): the tower picture.
  - **Reset styles** puts everything back.
- **Find tab:**
  - Search by icon name, City / Hall / Tower, bookmark, `#map`, or `x, y` to go to a spot.
  - Tick types to show them; click a type's name to list (and ring) every one of them.
  - *Only what 2+ screenshots show*, *only maps with a ticked icon* and *only potential city maps* narrow the view.
- **Screenshots** (Find tab), or right-click → *Screenshots of this spot*, lists the source screenshots for a spot.
- **Route tab:** set where you are (or right-click a map → *I'm here*), then right-click a map → *Route here*, or route to the nearest map with an icon. Routes take the fewest maps.
- **Replay** (top bar): the atlas being made as a timelapse, by time or swept out from where you started (spiral / distance / scan lines), with a camera that follows. **Record video** saves it as a `.webm` file.

## 4. Manage the atlas

- **Bookmarks:**
  - To add one: **Add bookmark** (top bar), then click the map. You can also right-click → *Add bookmark here…*, or use *Bookmark all results…* for a search.
  - The **Bookmarks tab** has groups, notes, edit, move to group and delete. Click a bookmark to go to it; the eye column hides or shows a bookmark or group.
- **Fix landmarks:** right-click a map → *This map is a…* (City / Hall / Tower / …), or right-click a landmark → *Delete* / *Restore landmark*. Edits are kept when the atlas is rebuilt.
- **City type:** right-click a City → *City type* (Vaal / Faridun / Ezomyte / … or Automatic).
- **City biomes:** click **City biome** (top bar), circle the maps with the mouse, and pick the city type. Halls, Deadly maps and Cities inside the circle become that city.
- **Several atlases:** with the **Atlas ▾** button you can:
  - switch atlas
  - add a new atlas (choose its screenshot folder)
  - rename an atlas
  - remove an atlas from the list
  - add new screenshots from an atlas's folder

  The **Atlases tab** shows every atlas as a card with a thumbnail of its map and its numbers of maps, icons and screenshots. Click a card to open it; the pencil renames it. The bin asks whether to *stop tracking* the atlas (its files stay) or *delete the whole atlas and its data* (its `atlas.json`, `atlas_frames/` and `atlas_files/`; your screenshots are never deleted).

  Each atlas lives in its own folder: `atlas.json`, plus `atlas_frames/` (detections) and `atlas_files/` (map image, exports, undo). The screenshots can sit in that same folder; the atlas never takes its own files for screenshots. Keep new ones in `atlases/`.
- **File menu:**
  - *New atlas*, *Open atlas*, *Open a screenshot folder*, *Save* (adding screenshots also saves).
  - *Re-check the whole atlas* runs the full clean-up pass again (a few minutes on a big atlas).
  - *Fix seams (clean map)* rebuilds the map image with care: each map node comes whole from one screenshot with its icons, seams stay off paths and away from screenshot edges, and lit copies win over fogged ones. It takes several minutes on a big atlas and runs in the background.
  - *Export map PNGs*.
  - *Close atlas*, *Quit the app*.

## 5. Other things

- **Log tab:** what the program did and any problems (*Save log*); the *Frame log* records how long the map takes to draw and saves it as CSV. The full log is `user_data/atlas_debug.log`.
- **Settings** (last atlas, layers, styles, watched folders) are in `user_data/viewer_settings.json`. Delete that file to start fresh.
- **Port:** the app uses port 8765, or the next free one. `python -m grand_project --port N` picks another; `--no-browser` doesn't open the browser.
- **Detector database:** `references/atlas_references.sqlite3`. It holds only the trained detector models and the icon (badge) reference pictures, with no data from anyone's atlas. Another one can be used by setting `DATABASE` in `local_paths.json`. The models are stored as skops archives, and the program only trusts the scikit-learn / numpy classes a trained model is made of. Still, only use detector databases from people you trust.

---

## Folders

| Folder | What is in it |
|---|---|
| `atlases/` | Your atlases. `default/` opens on first start. |
| `grand_project/` | The program, a Python package (see *Code layout* below). |
| `references/` | Every file the program reads: the database copy, HUD mask, icons and tower / city templates. |
| `tools/` | Helpers for improving the detector (mark checks, icon teaching, badge sheets, coverage). |
| `tests/` | Regression tests. Their screenshots and hand-made truth are not included (see below). |
| `user_data/` | Settings and the log, created on first run. |
| `atlas_test_data/` | Trimmed test data, in Git LFS and not downloaded by default (see below). |

## For developers

**Test data.** The GitHub repository has a trimmed test set in `atlas_test_data/` (about 500 MB: 20 hand-labelled screenshots with their truth, 115 crawl screenshots and two finished test atlases). It is stored with Git LFS and is **not** downloaded by a normal clone or by *Download ZIP*, so players only get the program. To get it:

```bash
git lfs install
git lfs pull --include="atlas_test_data/**"
```

The tests look for the data in `ATLAS_TEST_DATA` (environment variable) if set, then `atlas_test_data/` inside this folder, then `atlas_test_data` next to it. Without it, the tests that need it skip (under pytest they are reported as skipped). `test_atlas_builder.py` and `test_model_safety.py` need no data. Retraining the detector needs more data than the trimmed set (tower shots, painted walls), which is not included.

**Setup.** `pip install -e ".[dev]"` (or `make install`) installs the program as the `grand_project` package with pytest and ruff; `grand-project` then starts the app. Without installing, run everything from this folder with `python -m ...`.

**The page** (`frontend/`: React, TypeScript, Vite, Tailwind, shadcn/ui, MapLibre, TanStack Query, Zustand) needs Node.js 20+. In `frontend/`: `npm install` once, then `npm run build` builds it into `frontend/dist`, which the app serves. While working on it, run `python -m grand_project --no-browser` and `npm run dev` (http://localhost:5173, the API is passed to the app). `npm run lint` (Biome), `npm run typecheck` and `npm run coverage` (Vitest under coverage) are what CI runs. `make e2e` builds the page and runs the browser tests (Playwright, `frontend/e2e/`): the real app on a hand-made atlas, driven through the page; the first time, `cd frontend && npx playwright install chromium`. Releases ship the built page, so players don't need Node.js.

Run these from this folder:

- `python -m grand_project.detect score` scores the detector on the hand-labelled screenshots; `python -m grand_project.detect train` retrains it into the database. Both need the test data. `make evaluate_detector` runs the score; `make pr_precheck` runs everything to check before a pull request.
- `python -m grand_project.builder add --atlas X.json --image FOLDER` builds an atlas without the window.
- `python -m tools.atlas_marks` checks the detector against all hand-drawn mark layers and true paths.
- `python -m grand_project.detect train` also retrains the City check (a city's map node always stands on a brass barrel) from screenshots plus a `cities_truth.json` listing each city's map node (`CITY_TRUTH_SETS`); it prints a fair score first and saves `references/city_barrel.npz`. `python -m grand_project.detect train_cities [FOLDER ...]` retrains only that.
- `python -m tools.import_poe2db_art` adds poe2db's Map Content art (`references/poe2db_icons/`) as icon pictures for types with no on-screen example yet, so rare icons can still be named.
- `python -m tools.make_hud_mask SCREENSHOT` rebuilds `references/hud_mask_full.png` from a 1920×1080 atlas screenshot taken over black unexplored fog (everything not black is interface).
- Tests: `pytest` (or `make test`, `tests/Run all tests.bat`, `tests/run_all_tests.sh`); one file with `pytest tests/test_atlas_builder.py`. `pytest -m slow` adds the long one; see `tests/conftest.py`. The app's tests (`test_app_session.py`, `test_app_server.py`, the tile tests) use hand-made atlases and need no test data.
- Coverage: `make coverage` (Python: a table, and the report in `htmlcov/index.html`) and `make page_coverage` (the page: `frontend/coverage/index.html`). CI runs the tests on Windows, macOS and Linux and measures coverage on the Ubuntu jobs (offline, test data, browser tests, the page); the `tests` run's page shows the Python and page tables, and pull requests get a Python coverage comment.
- Lint: `make lint` (ruff check + format); CI runs the same on every push and pull request.

**Code layout** (`grand_project/`):

| Part | What it does |
|---|---|
| `paths.py` | every folder location (atlases, references, user data, test data) |
| `core/` | screenshots and their geometry, placing a screenshot (`register.py`), terrain matching, the atlas file (`atlas.py`), joining groups of waiting screenshots (`islands.py`), the clean map (`seams.py`) |
| `detect/` | the screenshot detector: maps, badges, landmarks, path dashes, fortress walls, the stored models, training |
| `finalize/` | the atlas-wide check after screenshots are added: path evidence, map rules, settlements, local re-checks |
| `builder.py` | detecting and adding screenshots (also a command line) |
| `cities.py`, `towers.py` | city types and biomes; hand-made tower / stronghold rules |
| `app/` | the app: `server.py` (the local web server: JSON API, event stream, tiles, the page), `session.py` (the open atlas; each other file is one part of it: adding, auto-add, map image, edits, bookmarks, Find, replay, debug marks) |
| `webmap/` | the map's tiles: map image levels, sharp ground from the screenshots, vector tiles with the vector ground and 3D models |

The page is in `frontend/src/`: `api/` (the app's client and events), `domain/` (its data types), `hooks/` (queries and actions), `store/` (page state), `logic/` (map style, routes, replay, labels: no React), `components/` (by part: `map/`, `find/`, `bookmarks/`, ...; `ui/` are shadcn/ui), `pages/`.

Each larger part keeps its tunable numbers in its own `constants.py`.

## License and credits

The code is released under the MIT License (see `LICENSE`).

Path of Exile 2 is made by Grinding Gear Games. The badge icons, tower templates and badge crops in `references/` come from the game and remain the property of Grinding Gear Games. This is an unofficial fan tool, not affiliated with or endorsed by them.
