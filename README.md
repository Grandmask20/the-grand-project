# The Grand Project — v1.03

Builds one big map of your Path of Exile 2 atlas from your screenshots. Named after the in-game tablet, *The Grand Project*. It finds maps, paths, icons, towers and cities, and lets you search and bookmark them.

## Run it

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Double-click **`Install (run once).bat`**.
3. Double-click **`Start Atlas Viewer.bat`**.

On first start the viewer opens the empty atlas **`atlases/default`**.

---

## Before you start: Steam screenshots

**Play at 1920×1080 (1080p).** The detector was trained only on 1080p screenshots, and map, badge and tower sizes are measured in 1080p pixels. Screenshots at other resolutions (1440p, 4K, ultrawide) are not scaled and will not be recognised. If your monitor is larger, set the game to 1920×1080 (windowed or fullscreen) while taking atlas screenshots.

Use Steam's screenshot key (**F12** by default); it's the fastest and most reliable way.

In Steam, open **Settings → In Game** and:

- turn on **Save an uncompressed copy**: the program needs the PNG, because JPG compression blurs the path dashes
- set the **screenshot folder** to one you can find

Screenshots then land there as `2694490_<date>_1.png`.

## 1. Start an atlas

1. Open the atlas in game, centred on the **fortress** (the giant walled structure in the middle). Press F12; the HUD can stay on screen, it is masked out.
2. Pan a little (keep about half the screen overlapping) and press F12 again. Repeat outward from the fortress in any direction.
3. In the viewer, go to the **Auto-add tab → Watch folder…**, pick your Steam screenshot folder, and tick *Add new screenshots automatically*. Each screenshot is now added while you play.

   For screenshots you already have, copy them into `atlases/default/` and use the **Atlas ▾** button → `default` → **Add new screenshots from its folder**.

The first screenshot becomes the centre, and every next one is placed where it overlaps the ones already in the atlas.

The fortress itself places poorly, because its walls cut the paths. Start right at its edge and move outward.

## 2. Add new maps

Any of these adds screenshots. Screenshots already in the atlas are skipped.

- **Auto-add tab → Watch folder…** Pick your Steam screenshot folder and tick *Add new screenshots automatically*. Each new screenshot is added while you play. When the viewer starts (or you start watching), screenshots already in that folder that the atlas doesn't have yet are added too.
- **Drag and drop** screenshot files onto the map.
- **File ▾ → Add screenshots…** (File ▾ is the first button on the toolbar)
- **Atlas ▾ → (atlas) → Add new screenshots from its folder.**

A screenshot that overlaps nothing yet goes to **Waiting** (Auto-add tab). Waiting screenshots are retried whenever another one is added, and you can also click **Retry selected** or **Retry all**.

- **Place by hand…** drops a screenshot where you click.
- **Undo last add** removes the last screenshot that was added.

## 3. View the atlas

- **Mouse:** wheel to zoom at the cursor, drag to pan, click a map or a path to select it (its details show in the Find tab).
- **Keys:** `+` / `-` zoom, `0` fit, arrows pan.
- **Layer grid** (under the tabs) shows or hides Terrain, Paths, Maps, Icons, Landmarks, Bookmarks, Labels, Doubtful, Removed, New (recent additions) and City biomes.
- **View tab:**
  - **Fit**, **Zoom in** and **Zoom out**.
  - *Only what 2+ screenshots show* hides anything seen only once, which is less certain.
  - **Paths:** colour (click the square), width, style (solid / dashed / dotted), and *only what 2+ screenshots show*, with a live preview.
  - **Maps:** colour, size and style (circles / squares / map icons / hidden), with a live preview.
  - **Pictures on the map** (zoomed in): badge pictures and the tower picture.
  - **Reset styles** puts everything back.
- **Find tab:**
  - Search by icon name, City / Hall / Tower, bookmark or `#map`.
  - Tick icons to show them.
  - *Hide maps without a ticked icon* and *Only potential city maps* narrow the view.
- **Screenshots** (Find tab), or right-click → *Screenshots of this spot*, lists the source screenshots for a spot.

## 4. Manage the atlas

- **Bookmarks:**
  - To add one: **Add bookmark** (top bar), then click the map. You can also right-click → *Add bookmark here…*, or use *Bookmark all results…* for a search.
  - The **Bookmarks tab** has groups, notes, edit, move to group and delete. Click a bookmark to go to it; the eye column hides or shows a bookmark or group.
- **Fix landmarks:** right-click a map → *This map is a…* (City / Hall / Tower / …), or right-click a landmark → *Delete* / *Restore landmark*. Edits are kept when the atlas is rebuilt.
- **City type:** right-click a City → *City type* (Vaal / Faridun / Ezomyte / … or Automatic).
- **City biomes:** click **Draw city biome**, circle the maps with the mouse, and pick the city type. Halls, Deadly maps and Cities inside the circle become that city.
- **Several atlases:** with the **Atlas ▾** button you can:
  - switch atlas
  - add a new atlas (choose its screenshot folder)
  - rename an atlas
  - remove an atlas from the list
  - add new screenshots from an atlas's folder

  Each atlas lives in its own folder: `atlas.json`, plus `atlas_frames/` (detections) and `atlas_files/` (map image, exports, undo). The screenshots can sit in that same folder; the atlas never takes its own files for screenshots. Keep new ones in `atlases/`.
- **File menu:**
  - *New atlas*, *Open atlas*, *Save* (Ctrl+S; adding screenshots also saves).
  - *Re-check whole atlas* runs the full clean-up pass again (a few minutes on a big atlas).
  - *Export map PNGs*.

## 5. Other things

- **Log tab:** what the program did and any problems. The full log is `user_data/atlas_debug.log`.
- **Settings** (last atlas, window, watched folder) are in `user_data/viewer_settings.json`. Delete that file to start fresh on the default atlas.
- **Detector database:** `references/atlas_references.sqlite3`. It holds only the trained detector models and the icon (badge) reference pictures, with no data from anyone's atlas. *File → Detector database…* picks another one.

---

## Folders

| Folder | What is in it |
|---|---|
| `atlases/` | Your atlases. `default/` opens on first start. |
| `program/` | The program. `atlas_viewer.py` is the window and `atlas_detect.py` the screenshot detector. `atlas_builder*.py` and `atlas_finalize.py` place screenshots and clean up the atlas. All folder locations are in `rc_paths.py`. |
| `references/` | Every file the program reads: the database copy, HUD mask, icons and tower / city templates. |
| `tools/` | Helpers for improving the detector (mark checks, icon teaching, badge sheets, coverage). |
| `tests/` | Regression tests. Their screenshots and hand-made truth are not included (see below). |
| `user_data/` | Settings and the log, created on first run. |

## For developers

This folder is shareable and contains no screenshots from anyone's atlas.

The test and training data (screenshots, hand-made truth and marks, and two finished test atlases) are kept outside it, in a folder named `atlas_test_data` next to this one. You can also set the `ATLAS_TEST_DATA` environment variable to its location. Without that folder, the tests and tools that need it print `SKIP` and stop. `test_atlas_builder.py` needs no data.

Run these from the folder named:

- `program/`: `py atlas_detect.py score` scores the detector on the 10 hand-labelled screenshots. `py atlas_detect.py train` retrains it into the database. Both need the test data.
- `program/`: `py atlas_builder.py add --atlas X.json --image FOLDER` builds an atlas without the window.
- `tools/`: `py atlas_marks.py` checks the detector against all hand-drawn mark layers and true paths.
- `tests/`: double-click `Run all tests.bat`, or run any `test_*.py` on its own. `test_atlas_viewer.py` opens a window for about 20 s.

## License and credits

The code is released under the MIT License (see `LICENSE`).

Path of Exile 2 is made by Grinding Gear Games. The badge icons, tower templates and badge crops in `references/` come from the game and remain the property of Grinding Gear Games. This is an unofficial fan tool, not affiliated with or endorsed by them.
