# The Grand Project — v1.24

Builds one big map of your Path of Exile 2 atlas from your screenshots. Named after the in-game tablet, *The Grand Project*. It finds maps, paths, icons, towers and cities, and lets you search, bookmark and route through them.

The app runs in your web browser: starting it opens a page served by the program on this computer (`http://127.0.0.1:8765`). Your atlases, screenshots and settings stay on your computer. The app goes online only for updates: it asks GitHub for the latest release once a day when it starts (to say an update is out; this can be turned off) and when you press **Check now** in the update box (click the version), and **Update now** downloads that release from GitHub (and, when it needs other Python packages, installs them from PyPI with pip). These requests send nothing of yours: GitHub sees the request, the app's name and version, and your network address, as with any website; PyPI gets pip's usual request (pip's version, Python's and your system's).

## Run it

**Which files to run:**

| | Once, to install | Every time, to start |
|---|---|---|
| **Windows** | `Install (run once).bat` | the **The Grand Project** shortcut (made by the install), or `Start The Grand Project.bat` |
| **macOS / Linux** | `./install.sh` | `./start.sh` |

### Get it

Download the newest release from the [Releases page](https://github.com/Grandmask20/the-grand-project/releases): open the top one and click **Source code (zip)**. Unzip it into a folder you can write to, e.g. `Documents\The Grand Project` (not `Program Files`). Don't use the green **Code** button on the front page: that is the developer copy, and its page isn't built.

### First time

**Windows:**

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/). In the installer, tick **"Add python.exe to PATH"**.
2. Double-click **`Install (run once).bat`**. It installs the Python packages the app needs and makes a **The Grand Project** shortcut with the tablet icon in this folder (copy it to your desktop or pin it to Start if you like), then says *Done*.

**macOS / Linux:**

1. Install Python 3.11 or newer (macOS: the [python.org](https://www.python.org/downloads/) installer or Homebrew; Linux: your package manager's `python3`, plus `python3-venv` on Debian / Ubuntu).
2. Open a terminal in this folder and run **`./install.sh`**. It makes a `.venv` folder and installs the packages there. (If it says *permission denied*: `bash install.sh`.)

### Every time

- **Windows:** double-click the **The Grand Project** shortcut (or **`Start The Grand Project.bat`**). No window opens: the app runs in the background and your browser opens its page.
- **macOS / Linux:** run **`./start.sh`** in a terminal and keep the terminal open. (On macOS right-click is a two-finger click, or Ctrl+click.)

The page is **`http://127.0.0.1:8765`**: bookmark it. Closing the browser tab doesn't stop the app: open the page again any time. Starting it again while it runs just opens its page. To stop it: **File ▾ → Quit the app** (or Ctrl+C in the terminal).

On first start the app opens the empty atlas **`atlases/default`**.

### Updating

**From 1.3 on, in the app:** the version at the top right says **Up to date** (green) or **Check update** / **Update to 1.x** (red). Click it to open the update box, and **Check now** (or **Check again**) asks GitHub for the latest release and shows what's new (at most once a minute: GitHub limits how often it answers). **Update now** downloads it, checks every file, and the app restarts on it (the page reloads by itself). Only the program's own files change: your atlases (`atlases/`) and settings (`user_data/`) stay, a file that fails to go in puts the old ones back, and the Python packages are installed again when the new release needs others. The app checks once a day when it starts (the box has the switch to turn that off).

**By hand** (an older release, or a copy the app can't update): first quit the app (**File ▾ → Quit the app**). Then download the new release and unzip it: it holds one folder (`the-grand-project-<version>`). Open that folder and copy everything in it into your current program folder, replacing the files. The release has no `atlases` or `user_data` folder, so yours are never replaced (never delete or replace those two folders yourself): your atlases (`atlases/`) and settings (`user_data/`) stay. Then run the install file again (**`Install (run once).bat`** or **`./install.sh`**): a new version can need new packages. (From 1.18 the Windows start file is `Start The Grand Project.bat`: an old `Start Atlas Viewer.bat` left in the folder can be deleted.)

### If it doesn't start

- **Windows: nothing happens, or "python is not recognized":** Python isn't on the PATH. Run the Python installer again, choose *Modify*, tick *Add Python to environment variables*, then run `Install (run once).bat` again.
- **The browser didn't open:** go to `http://127.0.0.1:8765` yourself. If that port was taken the app uses the next free one (8766, ...); the terminal (macOS / Linux) shows it, and so does `user_data/atlas_debug.log`.
- **The page says "The page isn't built":** you have the developer copy. Download the release from the Releases page instead.
- **Something else:** open a terminal in this folder and run `python -m grand_project` (macOS / Linux: `./start.sh`) to see the error; the full log is `user_data/atlas_debug.log`. 
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

1. In the app, go to the **Atlases tab → Auto-add** page and turn on *Add new screenshots automatically*. The app watches the open atlas's own folder, which is where Steam is now saving.
2. In game, open the atlas centred on the **fortress** (the giant walled structure in the middle) and press F12. The HUD can stay on screen; it is masked out.
3. Pan a little (keep about half the screen overlapping) and press F12 again. Repeat outward from the fortress in any direction. Each screenshot is added while you play.

For screenshots you already have, copy them into `atlases/default/` and use the **Atlas ▾** button → `default` → **Add new screenshots from its folder**.

The first screenshot becomes the centre, and every next one is placed where it overlaps the ones already in the atlas.

The fortress itself places poorly, because its walls cut the paths. Start right at its edge and move outward.

## 2. Add new maps

Any of these adds screenshots. Screenshots already in the atlas are skipped.

- **Atlases tab → Auto-add → Add new screenshots automatically.** Each new screenshot that Steam saves into the atlas folder is added while you play. When the app starts (or you start watching), screenshots already in that folder that the atlas doesn't have yet are added too. **Watch another folder…** watches a different folder instead, and **Atlas folder** switches back.
- **Drag and drop** screenshot files onto the map: one is placed by hand where you drag it, several are added. (They are copied into the atlas folder.)
- **File ▾ → Add screenshots…** (File ▾ is the first button on the toolbar)
- **Atlas ▾ → (atlas) → Add new screenshots from its folder.**

**Maps you have run since:** newer screenshots of a spot win over older ones. A map's icon is removed when the newest screenshots of it show the map without it (a map that turns green always loses its icon; a blue map can lose one; an attempted deadly boss map keeps only its Deadly Map Boss icon). Screenshots taken less than 30 seconds apart count as one moment, and where the detector missed an icon the app looks at the icon row again before calling it gone. Icons that never appear on a map (Corruption, the blue hideout, Abyss, Abyssal Depths, Expedition, Unique Map, the merchant), or Cleansed where there was no Corruption, are dropped when an earlier screenshot clearly showed the map without them. So keep screenshotting as you play: the atlas follows.

A screenshot that overlaps nothing yet goes to **Waiting** (Atlases tab → Auto-add). Waiting screenshots are retried whenever another one is added, and you can also click **Retry** or **Retry all**.

A screenshot that might be placed wrong is shown on the map, see-through and outlined, while the app asks whether to add it.

- **Place by hand…** (File ▾, or a waiting screenshot's **Place by hand**) shows the screenshot see-through: drag it roughly where it belongs, then press Enter or double-click.
- **Undo last add** removes the last screenshot that was added.

## 3. View the atlas

- **Mouse:** wheel to zoom at the cursor, drag to pan, right-drag (or Ctrl-drag) to tilt and turn, click a map or a path to select it: a box over the map points at it, with *Bookmark*, *Delete*, *Route here* and *Screenshots*, its icons, and its *Details* (how it was found, the maps it connects to: their paths light up with it). Esc or its x closes it. Zoomed in, the ground is built sharp from your screenshots themselves.
- **Keys:** `+` / `-` zoom, `0` fit, arrows pan, Esc cancels what you were doing (or closes the selection's box).
- **Map buttons** (top right): zoom, compass, **⤢** fit the whole atlas, **3D** (tilted view with models of maps, towers, citadels, halls and strongholds), full screen.
- **The side panel** has five tabs: Find, View, Bookmarks (with Route), Atlases (with Auto-add) and Log; it opens on Bookmarks. A narrow panel shows their icons only. The triangle on its edge hides it (and, on the map's edge, brings it back).
- **Layers** (at the bottom of the side panel, on every tab; it folds away to one line): Ground, Paths, Maps, Icons, Landmarks, Bookmarks, Names, Biomes, Recent, Removed, Routes (on, saved only, off) and Debug marks, plus 3D models while the map is tilted. Under them, the colour legend.
- **View tab** (two pages: *Map settings* and *3D view settings*; each section folds, all folded at first, and shows what is set in it while folded):
  - **Background:** *Picture* (the stitched screenshots), *Vector* (flat land with the city / stronghold / ground biomes as areas) or *Off*.
  - **Paths:** colour (click the square), width, style (solid / dashed / dotted), and *drawn by at least N%* of the screenshots that show both maps.
  - **Maps:** colour, size and style (circles / squares / map icons), previewed as a confirmed, a seen-once and a doubtful map. To hide them, turn off **Maps** in Layers.
  - **Bookmarks:** the pins' size, and whether a pin sits on the icon row above its spot or on the map node itself.
  - **City biomes and landmarks:** their colours.
  - **Colour by:** each screenshot's area by session, oldest to newest, or *times seen* (a heatmap), in a colour spread you pick.
  - **Reset styles** puts everything back.
- **Find tab:**
  - Search by icon name, City / Hall / Tower, bookmark, `#12` or `map 12`, or `x, y` to go to a spot. The search is loose: words in any order, a typo, letters left out; a map is found by its icons too.
  - One list down to the panel's bottom: tick types to show them; click a type's name to open every one of them within the list (and ring them on the map), click it again to fold it. A search's results are the list's first group. Each result shows the ground around it, where it is, and its map's icons with their counts; *Bookmark all* puts them in one group.
  - *Only what 2+ screenshots show*, *only maps with a ticked icon* and *only potential city maps* narrow the view.
- **Screenshots** (the selection's box), or right-click → *Screenshots of this spot*, lists the source screenshots for a spot.
- **Route** (Bookmarks tab → Route): set where you are (or right-click a map → *I'm here*; *I'm not here* / *Forget my position* takes it back), then right-click a map → *Route here*, or route to the nearest map with an icon. Routes take the fewest maps.
- **Map tools** (the tabs in the top bar, styled as the game's stash tabs): what a click on the map does: *Select*, *Route*, *Bookmark*, *I'm here*, *Biome* and *Place* (a screenshot by hand). The tab on is lit; click it again, *Select* or Esc to end it.
- **Route** (top bar tab): click the map it starts from, then the one it goes to; then *Track now* (the Route page shows the route as a card, its ends, its maps and how many are left with a bar, and its maps as steps: run, where you are, next; *Next map* moves you on) or *Save route…* (a bookmark: a click lights it up and fits it in view). Right-click a saved route: *Start tracking now*, or *Adjust route*: click a map to add it (past an end the route goes on; off its side it gets a branch, run where it splits off), right-click one to take it off (the bigger piece of the route stays: a map at an end goes alone). Every route (Route here, the nearest map, Route in the top bar, a saved route) is tracked the same way. *End* on the note over the map, or Esc, ends a map mode. *Next map* moves your position (*You are here*) on with it. The **Routes** layer button goes on → saved only → off.
- **Timelapse** (the tab at the map's bottom right): the atlas being made as a timelapse, by time or swept out from where you started (spiral / distance / scan lines), with a camera that follows. **Record video** saves it as a `.webm` file.

## 4. Manage the atlas

- **Bookmarks:**
  - To add one: **Add bookmark** (Bookmarks tab), then click the map. You can also right-click → *Add bookmark here…*, or use *Bookmark all results…* for a search.
  - The **Bookmarks tab** has groups, notes, edit, move to group and delete. Click a bookmark to go to it; the eye column hides or shows a bookmark or group. Pointing at a row shows its pen and bin. Tick a group to pick all of it (an empty group ticked is deleted with *Delete*), or *Select all*.
  - **Looks:** a bookmark's pen edits its name, group, note, colour and icon: a plain symbol (triangle, diamond, star, skull…) drawn in the colour, or one of the atlas's map icons or places, in a ring of the colour (the colour *none*: no ring). A group's pen renames it and gives it a look, which its bookmarks without their own take. The map draws each pin and its name in its look.
  - On a bookmarked map, right-click or the selection's box has *Edit bookmark*, and *Delete* → *Remove bookmark*.
- **Fix maps:** right-click a map → *Delete map* (a ghost map the detector made; its landmark goes with it, and so do the icons on it), or right-click where a map is missing → *Add here* → *Map* (or *City*, *Hall*, *Tower*, … for a map with that landmark). The selection's box has *Delete* → *Delete map* too. A deleted map shows with **Removed** on in Layers; *Add here* → *Map* on its spot brings it back. Like the other hand edits, they are kept when the atlas is checked again, and Undo leaves them.
- **Fix landmarks:** right-click a map → *This map is a…* (City / Hall / Tower / … or *Normal map*). A landmark standing on a map is that map: clicking either selects it, shown as the landmark (*Vaal city (map #12)*), and its box's *Delete* has *Not a City* (or Hall, …) to make it a normal map again. A deleted landmark shows with **Removed** on in Layers: right-click it → *Restore landmark*. Edits are kept when the atlas is rebuilt.
- **City type:** right-click a City → *City type* (Vaal / Faridun / Ezomyte / … or Automatic).
- **Biomes:** the **Biome** tab (top bar), circle the maps with the mouse, and pick a city type, a Breach stronghold, or *Not a biome*. Halls, Deadly maps and Cities inside the circle become that city.
- **Several atlases:** with the **Atlas ▾** button you can:
  - switch atlas
  - add a new atlas (choose its screenshot folder)
  - rename an atlas
  - remove an atlas from the list
  - add new screenshots from an atlas's folder

  The **Atlases tab** (its *Saved atlases* page) shows every atlas as a card with a thumbnail of its map and its numbers of maps, icons and screenshots. Click a card to open it; the pencil renames it; the circular arrows re-check it (it asks first, and opens it first when another atlas is open); right-click it to *Open atlas folder*. The bin asks whether to *stop tracking* the atlas (its files stay) or *delete the whole atlas and its data* (its `atlas.json`, `atlas_frames/` and `atlas_files/`; your screenshots are never deleted).

  Each atlas lives in its own folder: `atlas.json`, plus `atlas_frames/` (detections) and `atlas_files/` (map image, exports, undo). The screenshots can sit in that same folder; the atlas never takes its own files for screenshots. Keep new ones in `atlases/`.
- **File menu:**
  - *New atlas*, *Open atlas*, *Open a screenshot folder*, *Save* (adding screenshots also saves).
  - *Re-check the whole atlas* detects again the screenshots an older detector read (after an update that changed the detector, all of them once: long on a big atlas; the others keep their saved detection), then runs the atlas-wide clean-up again (a few minutes on a big atlas). It asks first, and says when the atlas was last re-checked, its screenshots in groups by when and on which version they were detected, how many will be detected again and about how long it takes (measured on your computer after the first Re-check). When it finishes, a box over the map lists what changed, in groups: *Maps*, *Paths*, *Landmarks*, *Towers*, *Biomes*, *Icons*. Each group's card shows how many things were added (+, green) and removed (−, red), and changed (~) when some moved or became another kind or biome. Click a card to list its changes with where each one is; click one to see its spot on the map, ringed. Tick *Keep?* on the groups whose changes you want and press *Apply*. An unticked group stays as it was before, on the maps it was on: e.g. untick *Biomes* and every map keeps the biome it had. Your ticks are remembered for every atlas. The map shows the atlas as it was until you apply, nothing changes if the app is closed first, and with nothing changed no box opens.
  - *Fix seams (clean map)* rebuilds the map image with care: each map node comes whole from one screenshot with its icons, seams stay off paths and away from screenshot edges, and lit copies win over fogged ones. It takes several minutes on a big atlas and runs in the background. While screenshots are being added it doesn't start: it asks to *Queue* it or cancel. A queued one starts once adding finishes; if adding failed (a screenshot couldn't be read, ...) it says why and asks: *Cancel* or *Fix seams anyway*. Screenshots added while it runs are added as usual. *Stop fixing seams* stops it, or takes a queued one off.
  - *Export map PNGs*.
  - *Close atlas*, *Quit the app*.

## 5. Other things

- **Log tab** (with a *Debug* page in the internal copy): what you did (settings changed, map tools, bookmarks, tabs, selections) and what the program did and is doing (progress, done / stopped / failed), in plain words, with any problems (*Save log*); the *Frame log* records how long the map takes to draw and saves it as CSV. The full log is `user_data/atlas_debug.log`.
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
| `tools/` | Developer helpers: improving the detector (mark checks, icon teaching, badge sheets, coverage), and making releases and the test pack (`make_release.py`, `make_test_pack.py`). |
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

**The page** (`frontend/`: React, TypeScript, Vite, Tailwind, shadcn/ui, MapLibre through react-map-gl, Terra Draw, TanStack Query, Zustand) needs Node.js 20+. In `frontend/`: `npm install` once, then `npm run build` builds it into `frontend/dist`, which the app serves. While working on it, run `python -m grand_project --no-browser` and `npm run dev` (http://localhost:5173, the API is passed to the app). `npm run lint` (Biome), `npm run typecheck` and `npm run coverage` (Vitest under coverage) are what CI runs. `make e2e` builds the page and runs the browser tests (Playwright, `frontend/e2e/`): the real app on a hand-made atlas, driven through the page; the first time, `cd frontend && npx playwright install chromium`. Releases ship the built page, so players don't need Node.js.

Run these from this folder:

- `python -m grand_project.detect score` scores the detector on the hand-labelled screenshots; `python -m grand_project.detect train` retrains it into the database. Both need the test data. `make evaluate_detector` runs the score; `make pr_precheck` runs everything to check before a pull request.
- `python -m grand_project.builder add --atlas X.json --image FOLDER` builds an atlas without the window.
- `python -m tools.atlas_marks` checks the detector against all hand-drawn mark layers and true paths.
- `python -m grand_project.detect train` also retrains the City check (a city's map node always stands on a brass barrel) from screenshots plus a `cities_truth.json` listing each city's map node (`CITY_TRUTH_SETS`); it prints a fair score first and saves `references/city_barrel.npz`. `python -m grand_project.detect train_cities [FOLDER ...]` retrains only that.
- `python -m tools.import_poe2db_art` adds poe2db's Map Content art (`references/poe2db_icons/`) as icon pictures for types with no on-screen example yet, so rare icons can still be named.
- `python -m tools.make_hud_mask SCREENSHOT` rebuilds `references/hud_mask_full.png` from a 1920×1080 atlas screenshot taken over black unexplored fog (everything not black is interface).
- `python -m tools.poe_art --ui "<the game's exported UI folder>"` remakes the page's pictures built from the game's interface art in `frontend/src/assets/poe/`: the stash tabs and the bar they stand on (recoloured and textured), the panels' frame and their dark grain; `--trim PICTURE` copies a single game picture cut to its art.
- Tests: `pytest` (or `make test`, `tests/Run all tests.bat`, `tests/run_all_tests.sh`); one file with `pytest tests/test_atlas_builder.py`. `pytest -m slow` adds the long one; see `tests/conftest.py`. The app's tests (`test_app_session.py`, `test_app_server.py`, the tile tests) use hand-made atlases and need no test data.
- Coverage: `make coverage` (Python: a table, and the report in `htmlcov/index.html`) and `make page_coverage` (the page: `frontend/coverage/index.html`). CI runs the tests on Windows, macOS and Linux and measures coverage on the Ubuntu jobs (offline, test data, browser tests, the page); the `tests` run's page shows the Python and page tables, and pull requests get a Python coverage comment. The run's last job, **tests passed**, is the one check merging needs: every test passed on at least one system and none failed anywhere, so a macOS job cancelled while waiting for a runner doesn't block.
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

The in-app update (the version at the top right: check for an update, Update now) is modelled on the update system of [Path of Building Community](https://github.com/PathOfBuildingCommunity/PathOfBuilding) ([PoE 2 version](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)): a release's list of its files with their hashes, compared with the newest release's; the files that differ checked against it and staged; and put in place when the program restarts, by a step of its own. Thanks to its contributors.

Path of Exile 2 is made by Grinding Gear Games. The badge icons, tower templates and badge crops in `references/` come from the game and remain the property of Grinding Gear Games. The page's look is built from the game's own interface art (its stash tabs, panels, buttons, dropdowns, sliders, scrollbars and icons, in `frontend/src/assets/poe/`), also the property of Grinding Gear Games. This is an unofficial fan tool, not affiliated with or endorsed by them.
