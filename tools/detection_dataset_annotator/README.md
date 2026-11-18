# Detection dataset annotator

This Streamlit app seeds an RF-DETR object-detection dataset from the existing classical atlas detector. It
recursively scans the three default screenshot roots (`res_atlases`, `roa-atlas` and `screenshots` in the test data), runs the classical detector, and shows its boxes over each screenshot in a box
editor where a reviewer fixes labels and geometry, draws missed detections, deletes false ones, and marks the
screenshot reviewed.

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
drew are dashed.

Edits save themselves half a second after the last change, and before moving to another screenshot. The status line
in the side panel says when they are saved.

| Key or mouse | Action |
| --- | --- |
| Drag on the screenshot | draw a box with the current label |
| Click / Shift+click | select / add to the selection (the smallest box under the pointer wins) |
| Alt+click | cycle through boxes stacked under the pointer |
| Drag a box / a handle | move / resize |
| `1` … `9`, `0` | label the selected boxes, or pick the label for new boxes (numbers shown in the side panel) |
| `Del`, `Backspace` | delete selected |
| `Ctrl+D` / `Ctrl+A` | duplicate selected / select all |
| Arrows (`Shift` for 10 px) | move selected by 1 px |
| `Alt`+Arrows (`Shift` for 10 px) | resize selected by 1 px |
| `,` / `.` (`Shift` for 5 px) | shrink / grow selected by 1 px on every side, keeping each box's centre |
| `Tab` / `Shift+Tab` | next / previous box |
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

Shortcuts work after a click in the editor and stop after a click elsewhere on the page (for example in the sidebar).
The side panel also has the label list with counts, and the selected box's label and X/Y/W/H in source pixels.

## Detection and export

The app writes `review_state.json` in the output folder (default `runs/detection-dataset`) while work is in
progress. Exporting writes:

- `annotations.json`: COCO object-detection JSON with absolute `file_name` paths.
- `manifest.json`: the project-native manifest accepted by `make prepare_rf_detr_data` through
  `RF_DETR_ANNOTATOR_MANIFEST=...`.
- `labels.json`: stable numeric IDs and labels.

Only reviewed screenshots are exported by default. The classical detector provides map nodes, icons, towers, cities,
halls, deadly-boss maps, and Breach strongholds. City subtype is not a separate detection class.

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

The side panel shows each box's source: `classical`, `icon_match` (step 1) or `icon_row` (step 2). Review them like
any other box. This changes only the annotator's boxes, never what the program's own detector finds. Screenshots
detected before these steps have to be rerun to get the extra boxes. The thresholds are `ANNOTATOR_ICON_...`,
`ANNOTATOR_SPOT_MIN` and `ANNOTATOR_HIDDEN_...` in `constants.py`.

Icons are one `icon` class by default; “Name icons by type” labels them with classes such as `icon_mapboss`. This
changes labels, not icon finding, so processed screenshots must be rerun to apply it.

Optional derived labels have independent toggles: paths (including their dashes) are grouped as `path`, and fortress
walls use `fortress_wall`. They are optional because production inference currently derives them with the classical
tracer and wall mask. Detection uses four concurrent processes by default (adjustable in the sidebar), divides
OpenCV's CPU threads between them, saves progress every ten images, and updates the progress indicator as each
screenshot finishes. “Rerun detection” replaces one screenshot's boxes; “Rerun all screenshots” requires confirmation
because successful reruns replace annotations and clear review flags. A failed rerun keeps its previous detections and
review flag.

## Code

| Module | What it does |
| --- | --- |
| `app.py` | the Streamlit page (sidebar, queue, autosave and navigation callbacks) |
| `component/` | the box editor: a small Streamlit component (plain JavaScript and CSS, no build step) |
| `state.py` | screenshot discovery, `review_state.json`, detection options, labels, the review queue |
| `detection.py` | the classical detector's points and paths as boxes in source-image pixels |
| `icon_proposals.py` | the extra icons and hidden map nodes (above) |
| `pool.py`, `worker.py` | detection in worker processes (`python -m tools.detection_dataset_annotator.worker`) |
| `boxes.py` | the editor's boxes mapped back to saved annotations by stable id |
| `export.py` | COCO and manifest export |
| `constants.py` | every threshold and setting (`ANNOTATOR_...`) |

Tests: `pytest tests/test_dataset_annotator.py tests/test_dataset_annotator_icons.py
tests/test_dataset_annotator_worker.py`.
