"""Settings for the RF-DETR dataset bootstrapper."""

from __future__ import annotations

from pathlib import Path

from grand_project.detect.constants import RF_DETR_CORE_LABELS

BOOTSTRAP_IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
"""Image suffixes accepted during recursive screenshot discovery."""

BOOTSTRAP_DEFAULT_INPUT_DIRS = (
    "atlas_test_data/res_atlases",
    "atlas_test_data/roa-atlas",
    "atlas_test_data/screenshots",
)
"""Repository-relative screenshot roots requested for the first bootstrap pass."""

BOOTSTRAP_DEFAULT_OUTPUT_DIR = "runs/rf-detr-bootstrap"
"""Repository-relative folder holding review state and exported training data."""

BOOTSTRAP_DEFAULT_WORKERS = 4
"""Concurrent detector processes: balances CPU use against each process's full-resolution image memory."""

BOOTSTRAP_WORKER_MODULE = "bootstrap_dataset_program.worker"
"""Python module launched as an isolated detector worker process."""

BOOTSTRAP_OPENCV_THREADS_ENV = "GRAND_PROJECT_BOOTSTRAP_OPENCV_THREADS"
"""OpenCV thread limit per worker to prevent nested CPU oversubscription."""

BOOTSTRAP_STATE_FILE = "review_state.json"
"""Filename for the editable detector results and review flags."""

BOOTSTRAP_MANIFEST_FILE = "manifest.json"
"""Filename for the project-native RF-DETR manifest export."""

BOOTSTRAP_COCO_FILE = "annotations.json"
"""Filename for the interoperable COCO object-detection export."""

BOOTSTRAP_SCHEMA_VERSION = 1
"""Version of the bootstrap review-state and manifest schemas."""

BOOTSTRAP_DERIVED_LABELS = ("path", "fortress_wall")
"""Optional derived labels: traced paths (including dashes) and fortress walls."""

BOOTSTRAP_CORE_LABELS = tuple(RF_DETR_CORE_LABELS)
"""The eight sparse object classes used by the current RF-DETR training run."""

BOOTSTRAP_ALL_LABELS = BOOTSTRAP_CORE_LABELS + BOOTSTRAP_DERIVED_LABELS
"""All labels that can be emitted by the bootstrapper."""

BOOTSTRAP_LABEL_COLORS = (
    (255, 100, 80),
    (80, 190, 255),
    (100, 230, 120),
    (190, 120, 255),
    (255, 190, 50),
    (80, 220, 220),
    (220, 100, 180),
    (130, 180, 255),
)
"""BGR box colours for the eight core labels, in ``BOOTSTRAP_CORE_LABELS`` order, chosen to read on the atlas."""

BOOTSTRAP_EXTRA_LABEL_COLORS = {"path": (60, 230, 255), "fortress_wall": (170, 170, 170)}
"""BGR box colours for the optional derived labels (yellow like the paths themselves, grey for walls)."""

BOOTSTRAP_LABEL_HOTKEYS = "1234567890"
"""Number keys that pick a label in the editor, assigned in label-palette order (core, derived, then custom)."""

BOOTSTRAP_EDITOR_JPEG_QUALITY = 92
"""JPEG quality of the editor's copy of the screenshot: about 0.5 MB at 1080p, visually identical to the source.
The copy is only for display; the screenshot file is never changed and export points at the original."""

BOOTSTRAP_EDITOR_CHIP_PX = 11
"""Label chip font size in screen pixels. Small, so a chip over a 43 px map-node box does not hide its neighbours
(the staged canvas's large chips covered most of a 1080p atlas)."""

BOOTSTRAP_EDITOR_AUTOSAVE_MS = 500
"""Quiet time after the last box edit before the editor sends its boxes to Python to save."""

BOOTSTRAP_EDITOR_HEIGHT = 760
"""Editor height in pixels: fits a 1080p laptop screen under the Streamlit header and the screenshot row."""

BOOTSTRAP_EDITOR_UNCHANGED_PX = 0.5
"""A box within this many source pixels of its detected geometry still counts as the detector's box."""

BOOTSTRAP_ICON_ROW_DY = (18.0, 42.0)
"""Detector px (1080p) an icon's centre sits above its map node. The classical finder's ``ROW_DY`` is 24 (crawl
screenshots); the res atlases' larger, silver-rimmed icons measured 26-36 above their map node."""

BOOTSTRAP_ICON_ROW_DX = 100.0
"""Detector px an icon may sit left or right of its map node: a row of five icons 36-41 px apart, plus slack."""

BOOTSTRAP_ICON_NODE_CLEAR = 14.0
"""A rim candidate this close (detector px) to a map node is the map node's own disc, not an icon."""

BOOTSTRAP_ICON_NMS = 26.0
"""Detector px within which a proposal duplicates a found icon or a better proposal. Icons in a row are at least
34 px apart, so neighbours in a row survive."""

BOOTSTRAP_ICON_MATCH_SURE = 0.06
"""Picture distance (1 - correlation, as in ``icon_refs.MAX_DIST``) up to which a rim candidate in an icon row is
proposed as an icon on the match alone. Measured on res_1080_100 and crawl screenshots: real icons the frozen
classifier rejected matched at 0.00-0.10 (MapBoss, Essence, Hideout, bookmarks 0.00-0.05), terrain from 0.086 up."""

BOOTSTRAP_ICON_MATCH = 0.11
"""Largest picture distance for any icon proposal. Between this and ``BOOTSTRAP_ICON_MATCH_SURE`` (Corruption and
Abyss icons matched at 0.07-0.10, terrain at 0.086-0.12) the icon must also be centred over a map node or be a row
neighbour of a found icon."""

BOOTSTRAP_ICON_MATCH_FAINT = 0.095
"""Largest picture distance for a weak match whose only support is a faint map node under it. Real icons over
fogged map nodes on res_1080_100 matched at 0.074-0.093; on the 20 labelled screenshots terrain over a faint map
candidate matched at 0.097-0.109 (AncientTrove, Expedition, TwiceLockedBoxes, GrandMirror pictures)."""

BOOTSTRAP_ICON_CENTRED = 6.0
"""Detector px left or right of a map node within which a weak match counts as that map node's single icon."""

BOOTSTRAP_ICON_ROW_GAP = (34.0, 44.0)
"""Detector px between neighbouring icons of one row (crawl icons 36, res atlas icons 40-41), and
``BOOTSTRAP_ICON_ROW_HEIGHT`` px of height difference allowed between them."""

BOOTSTRAP_ICON_ROW_HEIGHT = 5.0
"""Detector px two icons of one row may differ in height (as ``badge_rows``)."""

BOOTSTRAP_ICON_BATCH = 64
"""Candidates named per matrix product: about 70 MB of float32 against the ~1200 stored pictures."""

BOOTSTRAP_ICON_SOURCE = "icon_match"
"""Annotation source of icons proposed by picture match (the editor shows it), versus ``classical``."""

BOOTSTRAP_SPOT_MIN = 0.005
"""Map probability from which a map candidate the map classifier rejected counts as a faint (fogged) map node that
an icon may stand on. The classical row rescue's 0.02 (``ROW_RESCUE``) missed the fogged map node under a pair of
Abyss icons on res_1080_100 (it scored 0.0198)."""

BOOTSTRAP_HIDDEN_MIN_PAIRS = 3
"""Icons centred above a found map node needed to measure the screenshot's icon-to-map-node offset; with fewer the
classical ``ROW_DY`` (24 px, crawl screenshots) is used."""

BOOTSTRAP_HIDDEN_SNAP = 8.0
"""Detector px within which a hidden map node moves onto a faint map candidate (the fogged map node's own glow)."""

BOOTSTRAP_HIDDEN_SOURCE = "icon_row"
"""Annotation source of map nodes added under an icon row that had none (the editor shows it)."""

BOOTSTRAP_ROOT = Path(__file__).resolve().parent.parent
"""The project root used to resolve the default relative paths."""
