"""Settings for the detection dataset annotator (tools.detection_dataset_annotator)."""

from __future__ import annotations

from grand_project import paths
from grand_project.detect.constants import (
    RF_DETR_CORE_LABELS,
    RF_DETR_LANDMARK_BOX,
    RF_DETR_STRONGHOLD_BOX,
    RF_DETR_TOWER_HEIGHT,
    RF_DETR_TOWER_WIDTH,
)

# ---- screenshots and output folders ----------------------------------------------------------------------------

ANNOTATOR_IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
"""Image suffixes accepted during recursive screenshot discovery."""

ANNOTATOR_DEFAULT_INPUT_DIRS = (
    paths.TEST_DATA / "res_atlases",
    paths.TEST_DATA / "roa-atlas",
    paths.TEST_DATA / "screenshots",
)
"""Screenshot roots of the first annotation pass (in the test data, so ``local_paths.json`` applies)."""

ANNOTATOR_DEFAULT_OUTPUT_DIR = "runs/detection-dataset"
"""Project-relative folder holding the review state and the exported training data."""

ANNOTATOR_STATE_FILE = "review_state.json"
"""Filename for the editable detector results and review flags."""

ANNOTATOR_MANIFEST_FILE = "manifest.json"
"""Filename for the project-native RF-DETR manifest export (read by ``rf_detr.load_annotator_manifest``)."""

ANNOTATOR_COCO_FILE = "annotations.json"
"""Filename for the interoperable COCO object-detection export."""

ANNOTATOR_LABELS_FILE = "labels.json"
"""Filename for the exported numeric label ids."""

ANNOTATOR_SCHEMA_VERSION = 1
"""Version of the review-state and manifest schemas."""

ANNOTATOR_MANIFEST_FORMAT = "the-grand-project-rf-detr-manifest"
"""The manifest's ``format`` value; ``rf_detr.load_annotator_manifest`` refuses other files."""

# ---- detector worker processes ---------------------------------------------------------------------------------

ANNOTATOR_DEFAULT_WORKERS = 4
"""Concurrent detector processes: balances CPU use against each process's full-resolution image memory."""

ANNOTATOR_MAX_WORKERS = 8
"""Most detector processes the sidebar offers (a 4K screenshot needs about 1 GB per process)."""

ANNOTATOR_WORKER_MODULE = "tools.detection_dataset_annotator.worker"
"""Python module launched (``python -m``, from the project folder) as an isolated detector worker process."""

ANNOTATOR_OPENCV_THREADS_ENV = "GRAND_PROJECT_ANNOTATOR_OPENCV_THREADS"
"""OpenCV thread limit per worker, so the workers together do not oversubscribe the CPU."""

ANNOTATOR_WORKER_POLL_S = 0.25
"""Seconds between checks of the worker output queue while detection runs."""

ANNOTATOR_WORKER_EXIT_S = 10.0
"""Seconds a worker may take to exit after its input closes before it is terminated."""

ANNOTATOR_SAVE_EVERY = 10
"""Finished screenshots between saves of the review state during a detection run."""

# ---- labels ----------------------------------------------------------------------------------------------------

ANNOTATOR_CORE_LABELS = tuple(RF_DETR_CORE_LABELS)
"""The eight sparse object classes used by the current RF-DETR training run."""

ANNOTATOR_DERIVED_LABELS = ("path", "fortress_wall")
"""Optional derived labels: traced paths (including dashes) and fortress walls."""

ANNOTATOR_ALL_LABELS = ANNOTATOR_CORE_LABELS + ANNOTATOR_DERIVED_LABELS
"""All labels the annotator can emit before icon naming and custom labels."""

ANNOTATOR_LANDMARK_LABELS = {
    "Tower": ("tower", RF_DETR_TOWER_WIDTH, RF_DETR_TOWER_HEIGHT, "base"),
    "City": ("city", RF_DETR_LANDMARK_BOX, RF_DETR_LANDMARK_BOX, "center"),
    "Hall": ("hall", RF_DETR_LANDMARK_BOX, RF_DETR_LANDMARK_BOX, "center"),
    "Deadly boss map": ("deadly_boss_map", RF_DETR_LANDMARK_BOX, RF_DETR_LANDMARK_BOX, "center"),
    "Breach stronghold": ("breach_stronghold", RF_DETR_STRONGHOLD_BOX, RF_DETR_STRONGHOLD_BOX, "center"),
    "Locked stronghold": ("locked_stronghold", RF_DETR_STRONGHOLD_BOX, RF_DETR_STRONGHOLD_BOX, "center"),
}
"""Classical landmark kind -> (label, box width, box height, anchor) in detector px. A tower's point is its base,
so its box stands on the point; every other box is centred on it."""

ANNOTATOR_CLASSICAL_SOURCE = "classical"
"""Annotation source of boxes the classical detector found."""

ANNOTATOR_MANUAL_SOURCE = "manual"
"""Annotation source of boxes a reviewer drew or changed."""

ANNOTATOR_LABEL_COLORS = (
    (255, 100, 80),
    (80, 190, 255),
    (100, 230, 120),
    (190, 120, 255),
    (255, 190, 50),
    (80, 220, 220),
    (220, 100, 180),
    (130, 180, 255),
)
"""BGR box colours for the eight core labels, in ``ANNOTATOR_CORE_LABELS`` order, chosen to read on the atlas."""

ANNOTATOR_EXTRA_LABEL_COLORS = {"path": (60, 230, 255), "fortress_wall": (170, 170, 170)}
"""BGR box colours for the optional derived labels (yellow like the paths themselves, grey for walls)."""

ANNOTATOR_HASHED_LIGHTNESS = 0.62
"""HLS lightness of the hashed colours of labels without a fixed one: light enough to read on the dark atlas."""

ANNOTATOR_HASHED_SATURATION = 0.75
"""HLS saturation of the hashed label colours."""

ANNOTATOR_LABEL_HOTKEYS = "1234567890"
"""Number keys that pick a label in the editor, assigned in label-palette order (core, derived, then custom)."""

# ---- box editor ------------------------------------------------------------------------------------------------

ANNOTATOR_EDITOR_JPEG_QUALITY = 92
"""JPEG quality of the editor's copy of the screenshot: about 0.5 MB at 1080p, visually identical to the source.
The copy is only for display; the screenshot file is never changed and export points at the original."""

ANNOTATOR_EDITOR_CHIP_PX = 11
"""Label chip font size in screen pixels. Small, so a chip over a 43 px map-node box does not hide its neighbours
(the staged canvas's large chips covered most of a 1080p atlas)."""

ANNOTATOR_EDITOR_AUTOSAVE_MS = 500
"""Quiet time after the last box edit before the editor sends its boxes to Python to save."""

ANNOTATOR_EDITOR_HEIGHT = 760
"""Editor height in pixels: fits a 1080p laptop screen under the Streamlit header and the screenshot row."""

ANNOTATOR_EDITOR_UNCHANGED_PX = 0.5
"""A box within this many source pixels of its detected geometry still counts as the detector's box."""

ANNOTATOR_EDITOR_IMAGE_CACHE = 8
"""Screenshots whose editor copy (a data URL) Streamlit keeps in memory, for quick back-and-forth."""

ANNOTATOR_SESSION_SELECTED = "selected_image"
"""Streamlit session key: the image key of the screenshot on screen."""

ANNOTATOR_SESSION_HIDE_REVIEWED = "hide_reviewed"
"""Streamlit session key of the "Hide reviewed screenshots" checkbox (the action callback reads it)."""

ANNOTATOR_SESSION_MOUNTED_EDITOR = "mounted_editor"
"""Streamlit session key: the editor key last mounted, to reset its save counter and undo memory on a new one."""

ANNOTATOR_SESSION_NOTICE = "detection_notice"
"""Streamlit session key: a message shown as a toast after the next rerun."""

# ---- icon and hidden map-node proposals (icon_proposals.py) ----------------------------------------------------

ANNOTATOR_ICON_ROW_DY = (18.0, 42.0)
"""Detector px (1080p) an icon's centre sits above its map node. The classical finder's ``ROW_DY`` is 24 (crawl
screenshots); the res atlases' larger, silver-rimmed icons measured 26-36 above their map node."""

ANNOTATOR_ICON_ROW_DX = 100.0
"""Detector px an icon may sit left or right of its map node: a row of five icons 36-41 px apart, plus slack."""

ANNOTATOR_ICON_NODE_CLEAR = 14.0
"""A rim candidate this close (detector px) to a map node is the map node's own disc, not an icon."""

ANNOTATOR_ICON_NMS = 26.0
"""Detector px within which a proposal duplicates a found icon or a better proposal. Icons in a row are at least
34 px apart, so neighbours in a row survive."""

ANNOTATOR_ICON_MATCH_SURE = 0.06
"""Picture distance (1 - correlation, as in ``icon_refs.MAX_DIST``) up to which a rim candidate in an icon row is
proposed as an icon on the match alone. Measured on res_1080_100 and crawl screenshots: real icons the frozen
classifier rejected matched at 0.00-0.10 (MapBoss, Essence, Hideout, bookmarks 0.00-0.05), terrain from 0.086 up."""

ANNOTATOR_ICON_MATCH = 0.11
"""Largest picture distance for any icon proposal. Between this and ``ANNOTATOR_ICON_MATCH_SURE`` (Corruption and
Abyss icons matched at 0.07-0.10, terrain at 0.086-0.12) the icon must also be centred over a map node or be a row
neighbour of a found icon."""

ANNOTATOR_ICON_MATCH_FAINT = 0.095
"""Largest picture distance for a weak match whose only support is a faint map node under it. Real icons over
fogged map nodes on res_1080_100 matched at 0.074-0.093; on the 20 labelled screenshots terrain over a faint map
candidate matched at 0.097-0.109 (AncientTrove, Expedition, TwiceLockedBoxes, GrandMirror pictures)."""

ANNOTATOR_ICON_CENTRED = 6.0
"""Detector px left or right of a map node within which a weak match counts as that map node's single icon."""

ANNOTATOR_ICON_ROW_GAP = (34.0, 44.0)
"""Detector px between neighbouring icons of one row (crawl icons 36, res atlas icons 40-41), and
``ANNOTATOR_ICON_ROW_HEIGHT`` px of height difference allowed between them."""

ANNOTATOR_ICON_ROW_HEIGHT = 5.0
"""Detector px two icons of one row may differ in height (as ``badge_rows``)."""

ANNOTATOR_ICON_BATCH = 64
"""Candidates named per matrix product: about 70 MB of float32 against the ~1200 stored pictures."""

ANNOTATOR_ICON_SOURCE = "icon_match"
"""Annotation source of icons proposed by picture match (the editor shows it), versus ``classical``."""

ANNOTATOR_SPOT_MIN = 0.005
"""Map probability from which a map candidate the map classifier rejected counts as a faint (fogged) map node that
an icon may stand on. The classical row rescue's 0.02 (``ROW_RESCUE``) missed the fogged map node under a pair of
Abyss icons on res_1080_100 (it scored 0.0198)."""

ANNOTATOR_HIDDEN_MIN_PAIRS = 3
"""Icons centred above a found map node needed to measure the screenshot's icon-to-map-node offset; with fewer the
classical ``ROW_DY`` (24 px, crawl screenshots) is used."""

ANNOTATOR_HIDDEN_SNAP = 8.0
"""Detector px within which a hidden map node moves onto a faint map candidate (the fogged map node's own glow)."""

ANNOTATOR_HIDDEN_SOURCE = "icon_row"
"""Annotation source of map nodes added under an icon row that had none (the editor shows it)."""
