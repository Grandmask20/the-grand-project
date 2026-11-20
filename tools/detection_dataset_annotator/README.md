# Detection dataset annotator

This Streamlit app seeds an RF-DETR object-detection dataset from the existing classical atlas detector. It
recursively scans the three default screenshot roots (`res_atlases`, `roa-atlas` and `screenshots` in the test data;
an atlas's own `atlas_files/` map pictures are skipped), runs the classical detector, and shows its first guesses over
each screenshot in a box editor where a reviewer fixes labels and geometry, draws missed objects, deletes false ones,
and marks the screenshot reviewed. The labels are described below ([Labels](#labels)); exports feed
`python -m tools.train_rf_detr` ([Training](#training)).

Run it from the project folder:

```sh
make install_annotator   # pip install -e ".[annotator]": Streamlit
make annotate_dataset    # python -m tools.detection_dataset_annotator
```

Arguments after `python -m tools.detection_dataset_annotator` go to `streamlit run` (for example
`--server.port 8600`).

## Reviewing a screenshot

The screenshot is shown as a plain picture and every box is a separate element above it: boxes are never drawn into
the screenshot, the file is never changed, and boxes are saved as numbers in original-image pixels (also for 1440p
and 4K screenshots). Boxes are coloured by label; a box's label chip shows when you hover over it or select it
(`L` shows them all), so the chips don't hide the map nodes around it. Classical boxes are solid, boxes you changed or
drew are dashed, and guesses to check first are dotted: an unsure citadel type, biome or city area (below). The
sidebar's "Most guesses first" orders the queue by how many dotted boxes a screenshot has.

Edits save themselves half a second after the last change, and before moving to another screenshot. The status line
in the side panel says when they are saved.

| Key or mouse | Action |
| --- | --- |
| Drag on the screenshot | draw a box with the current label |
| Click / Shift+click | select / add to the selection (the smallest box under the pointer wins) |
| Alt+click | cycle through boxes stacked under the pointer |
| Drag a box / a handle | move / resize |
| `Ctrl`+drag | move the selected boxes, even from a handle (small boxes are all handle) |
| `1` … `8` | label the selected boxes as a map node class (`1` biome unknown, `2` grass, `3` desert, `4` water, `5` mountain, `6` Ezomyte, `7` Vaal, `8` Faridun city area), or pick it for new boxes |
| `9`, `0` | hall, tower |
| `Shift+1` … `Shift+8` | Iron, Stone, Copper citadel; Breach stronghold, reveal button; icon; path, fortress wall (keys shown in the side panel) |
| `/` | find a label: type words of its name, its icon's poe2db name or other names; `Enter` uses the first match, `Esc` clears |
| `Del`, `Backspace` | delete selected |
| `Ctrl+D` / `Ctrl+A` | duplicate selected / select all |
| Arrows (`Shift` for 10 px) | move selected by 1 px |
| `Alt`+Arrows (`Shift` for 10 px) | resize selected by 1 px |
| `,` / `.` (`Shift` for 5 px) | shrink / grow selected by 1 px on every side, keeping each box's centre |
| `J` / `K` | next / previous box |
| `Ctrl+Z` / `Ctrl+Shift+Z`, `Ctrl+Y` | undo / redo |
| `Esc` | cancel a drag, deselect, close help |
| Wheel, `+` / `-` | zoom (wheel zooms around the pointer); with boxes selected, grow / shrink them by 1 px on every side, keeping each box's centre (`Shift`+wheel: 5 px) |
| `Ctrl`+wheel | zoom, also with boxes selected |
| `Space`+drag, middle drag | pan |
| `F` | fit the screenshot |
| `C` | centre the screenshot, keeping the zoom |
| `H` / `L` | hide boxes / show every label |
| `Enter` | mark reviewed and go to the next screenshot |
| `Shift+Enter` | toggle reviewed |
| `N` or `]` / `P` or `[` | next / previous screenshot |
| `?` | shortcut help |

Shortcuts work while the screenshot has the focus: after a click on it or on a side-panel button, not after a click
elsewhere on the page (for example in the sidebar). `Tab` moves the focus as usual and `Enter` presses a focused button.
The side panel also has the label list with counts, and the selected box's label, its box rule (what the box must
cover) and X/Y/W/H in source pixels.

Each label shows its picture next to its name: an icon label (`icon_breachhive`) its icon's art from poe2db
(`references/poe2db_icons`, else a stored on-screen picture of it) and its poe2db name ("Breach Hive"); the map node,
tower and reveal-button labels a picture of what they mark (the registry's `picture`). The box
chips and the selected box's panel show the same picture, so an icon on the screenshot can be compared with it. The
finder above the list (`/`) narrows it down; clicking a label (or `Enter` in the finder) labels the selected boxes.

## Detection and export

The work in progress (detections, edits, review flags, the detection settings) is kept in `review_state.sqlite3` in the
output folder (default `tools/detection_dataset_annotator/detection-dataset`, which git ignores), a SQLite database
(`store.py`). Each edit and each detection result saves only its own screenshot, in a few milliseconds however many
screenshots are detected, and several browser tabs and a detection run can save at the same time. Exporting writes
into the same folder:

- `annotations.json`: COCO object-detection JSON with absolute `file_name` paths.
- `manifest.json`: the project-native manifest accepted by `make prepare_rf_detr_data` through
  `RF_DETR_ANNOTATOR_MANIFEST=...`.
- `labels.json`: the numeric class ids and their classes.

Only reviewed screenshots are exported by default. Every exported screenshot gets a train / validation / test split,
which the store keeps ([Splits](#splits)). A label in use that is not one of the dataset's (a reviewer's own, or one
the labels no longer have) is exported as a class of its own and named in a warning: rerun those screenshots.

## Labels

The labels are one registry, `RF_DETR_LABEL_INFO` in `grand_project/detect/constants.py`, read through
`grand_project/detect/labels.py`: titles, colours, keys, pictures and the box rule the side panel shows all come from
it:

| Label | Box | First guess |
| --- | --- | --- |
| `map_node` | node box (38.7 px) centred on the map node; only when its ground can't be seen (fog, screen edge) or told | too little ground seen around it |
| `map_node_grass`, `_desert`, `_water`, `_mountain` | node box; the ground around it is green (grass, swamp, forest), sand, water / ocean, white rock or snow | the ground ring (below) |
| `map_node_ezomyte`, `_vaal`, `_faridun` | node box; the map lies in that city's area (the citadel's own map included) | the city's area grown through the paths (below), always dotted |
| `citadel_iron` (Ezomyte), `citadel_stone` (Vaal), `citadel_copper` (Faridun) | 80 px box on the city's own map node and its brass barrel | the classical City and its type by look (below) |
| `hall` | the hall's map node and the whole hall structure beside it: the building its orange beam rises from, not the beam | the node box joined with the structure under the beam |
| `tower` | as before: standing on its node up to the spire | classical |
| `breach_stronghold` | 150 px on the purple Breach stronghold structure, locked or open | classical (both kinds) |
| `reveal_button` | 68×66 px on a square framed button that reveals maps when clicked: a locked stronghold's hand, the Expedition ship, … | the classical square-button finder, every kind (below) |
| `icon` (`icon_<type>` with “Name icons by type”) | 34 px on any round map icon, the red deadly-boss icon included, except the Lost Tower and Checkpoint icons (no labels: `RF_DETR_ICON_EXCLUDED`) | classical finder and namer, plus the extra proposals (below) |
| `path`, `fortress_wall` | optional derived boxes, offered only with their sidebar options | classical tracer and wall mask |

Rules for every screenshot: box every visible object of every class (at least half on screen); the game's HUD is
never labelled (training and inference paint it over). Every map node has exactly one node box: its city's area if it
lies in one, else its biome. A deadly-boss map has no box of its own: its node box and its deadly-boss icon's box
say it; a city is its node box, its citadel box and (unless completed) its deadly-boss icon; a hall likewise with its
hall box. The `icon_*influence` icons are map mods (a desert map can carry a Grass Influence), not the map's biome.
The Lost Tower and Checkpoint icons are not labelled at all: no box is proposed for them, exports leave them out, and
the RF-DETR detector does not report them. The Expedition ship is no icon: it is a reveal button (below).

**Biome guesses** (`grand_project/detect/biomes.py`, the PM's idea): the ground in a ring around the node, from its box
out to the disc Fix seams protects (`BIOME_RING`, 19-38 px), each pixel classified as in
`finalize.landmarks._ground_classes` (path strokes, fog and icon boxes left out); the biome with the largest share wins.
A map in the ocean is water whatever its island. White under a Delirium map's mist (that map and the maps within
`BIOME_MIST_REACH`) is not mountain: it is left out and the guess dotted. A guess under `BIOME_SURE_SHARE` /
`BIOME_SURE_MARGIN` is dotted (`biome_guess`). `python -m tools.detection_dataset_annotator.score_nodes` compares the
guesses with reviewed screenshots (a confusion matrix; `--ring IN OUT` tries another ring).

**City areas**: on one screenshot, `cities.potential_maps` grows each city's area from its own map through the traced
paths with the atlas-wide rules (about 10 maps, tightly linked, never through a Unique map, Tower, Hall, merchant ...,
not behind the citadel). A screenshot may cut an area off, so these are always dotted (`city_area_guess`); the
citadel's own map is as sure as the city's type.

**Citadel types**: the classical detector only finds that a map node is a city (its brass barrel); the type comes from
the look of the ground around it, as in the program's atlas-wide city types (`grand_project/cities.py`): the ~540×360
px window above the city's map node is matched against the labelled city looks in `references/city_refs.npz`. Two
cities closer than `TRIO_GAP` (680 px) never share a type, and the clearest city is decided first. A guess whose two
best types are less than `CITY_LOOK_SURE` apart, or whose window is cut off by the screenshot edge, is dotted
(`city_guess`): check its citadel (Vaal: stepped pyramid; Ezomyte: dark walled ring; Faridun: green-roofed fortress in
sand). Relabelling or editing a box makes it `manual`.

**Halls**: the hall structure stands beside its map node (on the measured halls up and left of it); its orange beam's
column (`finalize.landmarks._beam_column`, the column the classical Hall test judged) places it, and the hall box joins
it with the node box (`RF_DETR_HALL_STRUCTURE_*`).

**Reveal buttons** (user): the square framed buttons that reveal maps when clicked (a locked Breach stronghold's hand
reveals its cluster of Breach maps, the Expedition ship the ocean's maps) share one frame, so they are one class,
`reveal_button`, whatever their kind. As with icons, the model finds them and the classical code names them: the
symbol inside the frame (`cities.name_button`; `cities.square_buttons` proposes them here). A new kind of button needs
a picture of its symbol, not a new class. A Breach stronghold looks the same locked or open: one `breach_stronghold`
class, locked when a hand button stands within `STRONGHOLD_LOCK_REACH` or no map node is inside
(`landmarks.stronghold_kind`, in both detectors).

### Changing the labels

1. Change the registry (`RF_DETR_LABEL_INFO`; append a new label at the end, with a `parent` when it splits an older
   class, so a further fine-tuned model starts it from that class's row).
2. Optionally teach `grand_project/detect/proposals.py` a first guess for it.
3. **Rerun all screenshots** (sidebar): detection replaces their boxes and clears their review flags, so review them
   again. An export names any label left from before in a warning.
4. Export, and train with `--init-from` the earlier model: the classes it already had keep their rows by name.

The first time this annotator opens a store made before splits were kept, it upgrades the database and keeps a copy of
it next to it (`review_state.sqlite3.v1-backup`). An annotator from before the upgrade refuses the upgraded store.

## Splits

Every exported screenshot gets its split once and keeps it (`splits.py`), so a later model never trains on an earlier
model's test screenshots. The hand truth and reference atlases that `python -m grand_project.detect score` and
`tools/compare_detectors.py` measure on (`ANNOTATOR_SPLIT_PINNED_TEST`) are always test. The others (the user's
design):

1. binned by exported boxes per screenshot (`ANNOTATOR_SPLIT_BINS` quantiles), so every split has quiet and busy
   screenshots alike (the model's queries must cover the busiest);
2. bin by bin, in random order, each drawn to the split missing the most of its share so far
   (`ANNOTATOR_SPLIT_FRACTIONS`, 80/10/10);
3. refined by seeded swaps within a bin while they bring every class's spread over the splits closer to the shares
   (each class counts the same, so rare ones reach every split too).

The export shows the balance (screenshots, boxes per screenshot, each class's share per split). Screenshots of one
atlas overlap, so a random split puts views of the same spots in train and test: the test numbers overstate how a
model does on a new player's atlas; the pinned hand truth gives a fairer one.

## Training

`make prepare_rf_detr_data` (or `python -m tools.train_rf_detr --annotator-manifest .../manifest.json
--dataset-only`) builds the Hugging Face dataset from the export; `make train_rf_detr` trains. The model sees
native-scale 768 px tiles of the 1080p screenshots with the HUD painted over (a node keeps its 39 px), never mirrored
(the atlas is not); icons are found as one `icon` class and named by the classical detector's naming step
(`badges.name_found_icons`: the stored and the icon model's pictures, the whole-icon templates), reveal buttons as one
`reveal_button` class named by their symbol (`cities.name_button`). See `tools/train_rf_detr.py` for the recipe (the
RF-DETR paper's:
per-layer learning-rate decay, EMA, best checkpoint by validation mean AP per family).

## Detection details

Icons and the map nodes under them get two extra steps (`icon_proposals.py`). The classical finder's frozen classifier
was trained on the crawl screenshots' small gold-rimmed icons and rejects most of the larger silver-rimmed ones (on a
res atlas screenshot it finds 4 of about 35), and the map finder misses dim, fogged map nodes.

1. **Icons.** Every icon-rim candidate in an icon row above a map node is proposed when its picture closely matches a
   stored icon picture. A near-exact match is enough. A weaker match must also be centred over its map node, sit next
   to an icon in the same row, or form a pair whose middle is centred over a map node. A fogged map node the finder
   missed counts too (a map candidate it rated at least `ANNOTATOR_SPOT_MIN`), but only for a closer match.
2. **Hidden map nodes.** An icon always stands on a map node, so every icon row with no map node under its middle gets
   one, at the icon-to-map-node offset measured on that screenshot. It is snapped to the fogged map node's glow when
   there is one. As in the classical finder, a visible map node within 45 px (`HIDDEN_SNAP`) is already the row's map
   node. Ship buttons and markers pinned above another icon never get one.

The side panel shows each box's source: `classical`, `city_guess`, `biome_guess`, `city_area_guess` (above),
`icon_match` (step 1) or `icon_row` (step 2). Review them like
any other box. This changes only the annotator's boxes, never what the program's own detector finds. Screenshots
detected before these steps have to be rerun to get the extra boxes. The thresholds are `ANNOTATOR_ICON_...`,
`ANNOTATOR_SPOT_MIN` and `ANNOTATOR_HIDDEN_...` in `constants.py`.

Icons are labelled `icon` by default (the deadly-boss icon too, and the label list then offers only `icon`); “Name icons by type”
labels them with their type, such as `icon_mapboss`. This changes labels, not icon finding, so processed screenshots
must be rerun to apply it. With it, every icon type the program knows (`ICON_INFO` in
`grand_project/detect/constants.py`: every poe2db Map Content / Map Legend icon, but the left-out types above) is a
label, whether or not the classical detector named one yet. Named or not, an export gives the detector one `icon`
class for them (`labels.export_class`): the detector finds icons and the classical naming step names them
(`badges.name_found_icons`), as it names the classical finder's icons, so a new icon type never needs retraining and rare types (19 of 87 had 5 boxes or fewer) are no classes
the model could not learn. Icons the detector could not name are `icon_unidentified`.

Optional derived labels have independent toggles: paths (including their dashes) are grouped as `path`, and fortress
walls use `fortress_wall`. They are optional because production inference currently derives them with the classical
tracer and wall mask.

Detection runs in worker processes, by default one per CPU but two, as far as the memory allows (each worker needs
about 1.3 GB; adjustable in the sidebar). Each worker gets its share of the CPU's threads for OpenCV, OpenMP and
BLAS: left uncapped, every worker's map and tower models start one OpenMP thread per CPU, and four workers ran 4.2×
slower. Each worker is kept two screenshots ahead, each result is saved as it arrives (a stopped run keeps what it
finished), and the progress indicator updates as each screenshot finishes. On a 22-thread Ryzen 9 7900X, 1,265 screenshots take about half an
hour. “Rerun detection” replaces one screenshot's boxes; “Rerun all screenshots” requires confirmation
because successful reruns replace annotations and clear review flags. A failed rerun keeps its previous detections and
review flag.

## Code

| Module | What it does |
| --- | --- |
| `app.py` | the Streamlit page (sidebar, queue, autosave and navigation callbacks) |
| `component/` | the box editor: a small Streamlit component (plain JavaScript and CSS, no build step) |
| `state.py` | screenshot discovery, detection options, labels, the review queue |
| `store.py` | the review state in `review_state.sqlite3`: one screenshot per save, safe between sessions |
| `detection.py` | runs the classical detector; its result becomes boxes through `grand_project/detect/proposals.py` |
| `icon_proposals.py` | the extra icons and hidden map nodes (above) |
| `pool.py`, `worker.py` | detection in worker processes, driven by asyncio (`python -m tools.detection_dataset_annotator.worker`) |
| `boxes.py` | the editor's boxes mapped back to saved annotations by stable id |
| `export.py` | COCO and manifest export |
| `splits.py` | train / validation / test splits |
| `score_nodes.py` | the biome and city-area guesses against reviewed screenshots |
| `constants.py` | every threshold and setting (`ANNOTATOR_...`); the labels are the registry's (above) |

Tests: `pytest tests/detection_dataset_annotator` (the worker pool's tests run against a stand-in worker,
`tests/detection_dataset_annotator/fake_worker.py`).
