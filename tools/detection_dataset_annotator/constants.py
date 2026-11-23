"""Settings for the detection dataset annotator (tools.detection_dataset_annotator)."""

from __future__ import annotations

from grand_project import paths
from grand_project.detect.constants import (
    RF_DETR_GUESS_SOURCES,
    RF_DETR_MANIFEST_FORMAT,
    RF_DETR_SOURCE_CITY_GUESS,
    RF_DETR_SOURCE_CLASSICAL,
    RF_DETR_SPLITS,
)

# ---- screenshots and output folders ----------------------------------------------------------------------------

ANNOTATOR_IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
"""Image suffixes accepted during recursive screenshot discovery."""

ANNOTATOR_SKIP_DIRS = frozenset({"atlas_files"})
"""Folder names discovery never enters: an atlas folder keeps its stitched map pictures there (roa-atlas's
``atlas_terrain.png`` is 9950x4019 with 741 boxes, over the 300 objects an image may hold), not screenshots."""

ANNOTATOR_MAX_SIDE = (3840, 2160)
"""Largest screenshot (width, height) detection accepts: a 4K game window (``core.read_screenshot`` scales 1440p and
4K windows to 1080p); anything larger is not a screenshot."""

ANNOTATOR_DEFAULT_INPUT_DIRS = (
    paths.TEST_DATA / "res_atlases",
    paths.TEST_DATA / "roa-atlas",
    paths.TEST_DATA / "fr-atlas" / "crawl_atlas_v076",
    paths.TEST_DATA / "screenshots",
)
"""Screenshot roots of the first annotation pass (in the test data, so ``local_paths.json`` applies)."""

ANNOTATOR_DEFAULT_OUTPUT_DIR = "tools/detection_dataset_annotator/detection-dataset"
"""Project-relative folder holding the review store and the exported training data (git-ignored: local data)."""

ANNOTATOR_STORE_FILE = "review_state.sqlite3"
"""Filename of the review store (``store.py``): the editable detector results, review flags and dataset settings."""

ANNOTATOR_STORE_CREATED = 1
"""``PRAGMA user_version`` the review store sets once its tables are created (a new file has 0)."""

ANNOTATOR_BUILD_BACKUP = "review_state.before-build-{stamp}.sqlite3"
"""Name of the store's copy ``build_store`` makes before it changes the store (``stamp``: the local date and time)."""

ANNOTATOR_BUILD_PROGRESS_EVERY = 100
"""``build_store`` prints detection progress every this many screenshots."""

ANNOTATOR_STORE_BUSY_S = 10.0
"""Seconds a store write waits while another session (a browser tab, a detection run) writes. Writes are one
screenshot each and take milliseconds; the wait only matters when several land at once."""

ANNOTATOR_MANIFEST_FILE = "manifest.json"
"""Filename for the project-native RF-DETR manifest export (read by ``rf_detr.load_annotator_manifest``)."""

ANNOTATOR_COCO_FILE = "annotations.json"
"""Filename for the interoperable COCO object-detection export."""

ANNOTATOR_LABELS_FILE = "labels.json"
"""Filename for the exported numeric label ids."""

ANNOTATOR_SCHEMA_VERSION = 2
"""Version of the manifest schema."""

ANNOTATOR_MANIFEST_FORMAT = RF_DETR_MANIFEST_FORMAT
"""The manifest's ``format`` value; ``rf_detr.load_annotator_manifest`` refuses other files."""

# ---- train / validation / test splits (splits.py) -------------------------------------------------------------

ANNOTATOR_SPLITS = RF_DETR_SPLITS
"""The splits a screenshot can be in (the dataset's Hugging Face split names)."""

ANNOTATOR_SPLIT_FRACTIONS = (0.8, 0.1, 0.1)
"""Share of the screenshots each split gets, in ``ANNOTATOR_SPLITS`` order."""

ANNOTATOR_SPLIT_BINS = 8
"""Bins of exported boxes per screenshot (quantiles) the splits are drawn from, so each split holds screenshots as
busy as the others (user: splits aware of the detections per image, which the model's queries must cover)."""

ANNOTATOR_SPLIT_SEED = 10
"""Seed of the split's random draw, its refinement and the blocks' k-means: the same screenshots give the same splits.
Chosen with the user (2026-11-20) from seeds 0-19 with blocks of 60, by the split's own quality, no model results: the
least overlap (map nodes of held-out screenshots a training screenshot also shows: roa-atlas validation 21% / test 15%,
fr-atlas 5% / 7%) among the seeds that put both atlases in every split and every class within 6% of its share. 6 of
the 20 left fr-atlas without validation or test; 1337 left 42% on roa-atlas test. Once the split ledger holds a
screenshot's split, the seed only draws screenshots new to it."""

ANNOTATOR_SPLIT_ROUNDS = 20000
"""Swaps tried when refining the splits so every class is spread across them as the split shares say (user)."""

ANNOTATOR_SPLIT_PINNED_TEST = (
    paths.TEST_DATA / "screenshots" / "random_samples",
    paths.TEST_DATA / "screenshots" / "ocean",
    paths.TEST_DATA / "res_atlases",
)
"""Screenshots always in the test split: the hand truth and the reference atlases that ``python -m
grand_project.detect score`` and ``tools/compare_detectors.py`` measure on, so those numbers stay on unseen data."""

ANNOTATOR_ATLAS_FILE = "atlas.json"
"""An atlas's file: its screenshots lie next to it (where the app finds them) or in folders right below it (e.g.
map_state_change/pre-change/, post-change/), and it places each in atlas units."""

ANNOTATOR_SPLIT_BLOCK_SHOTS = 60
"""Screenshots per spatial block of an atlas (blocks.py; k-means of the screenshots' middles in atlas units): a block
goes to one split whole. Screenshots of an atlas overlap (a map node is on 4.5 roa-atlas / 3.3 fr-atlas screenshots
on average), so drawn one by one, 91-93% of a held-out screenshot's map nodes were also on a training screenshot.
Measured on both atlases (2026-11-20, 5 seeds): blocks of 5 / 10 / 20 / 40 screenshots leave 78 / 65 / 48 / 32% of
the held-out roa-atlas map nodes on training screenshots, 70 / 57 / 42 / 14% on fr-atlas; 60 (3 seeds) 16-31% and
5-16%, both atlases still in validation and test (80 left fr-atlas without test). User: 60, for the iterative
training rounds (with ``ANNOTATOR_SPLIT_SEED``: 21 / 15% and 5 / 7%)."""

ANNOTATOR_HASH_THREADS = 8
"""Files the split ledger hashes at once (hashlib lets go of the GIL): one thread read 820 MB/s of roa-atlas PNGs."""

ANNOTATOR_SPLIT_LEDGER = paths.ROOT / "tools" / "detection_dataset_annotator" / "splits.csv"
"""The split ledger (split_ledger.py; kept in git): every screenshot's split by the SHA-256 of its bytes, so a rebuilt
store, another machine or a copy of the file gives it the same split. The store's own image key hashes the
screenshot's path on this machine, and the store is local data."""

# ---- detector worker processes ---------------------------------------------------------------------------------

ANNOTATOR_WORKER_MODULE = "tools.detection_dataset_annotator.worker"
"""Python module launched (``python -m``, from the project folder) as an isolated detector worker process."""

ANNOTATOR_OPENCV_THREADS_ENV = "GRAND_PROJECT_ANNOTATOR_OPENCV_THREADS"
"""OpenCV thread limit per worker, so the workers together do not oversubscribe the CPU."""

ANNOTATOR_THREAD_ENV_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
"""OpenMP / BLAS thread limits set for each worker before it imports scikit-learn and NumPy. The map and tower
models are HistGradientBoostingClassifiers whose predict starts one OpenMP thread per CPU in every worker: uncapped,
4 workers ran 4.2x slower (9.2 s instead of 2.2 s per screenshot, 22-thread Ryzen 9 7900X, roa-atlas)."""

ANNOTATOR_WORKER_RESERVED_CPUS = 2
"""CPUs the default worker count leaves for the Streamlit server and the browser."""

ANNOTATOR_WORKER_MEMORY_GB = 1.5
"""Memory budgeted per worker for the default count: one worker peaked at 1.29 GB on a 1080p roa-atlas screenshot."""

ANNOTATOR_WORKER_FALLBACK = 8
"""Default worker cap where the total memory cannot be read (``os.sysconf`` is missing on Windows)."""

ANNOTATOR_WORKER_IN_FLIGHT = 2
"""Requests written ahead to each worker, so it starts its next screenshot while the annotator handles an answer
(progress, saving the result) instead of waiting for it."""

ANNOTATOR_WORKER_LINE_LIMIT = 16 * 1024 * 1024
"""Longest worker answer line in bytes (asyncio's default 64 KiB is too short for a screenshot with every path)."""

ANNOTATOR_WORKER_ANSWER_S = 300.0
"""Seconds to wait for a worker's next answer before it counts as stuck: it is stopped and the screenshots it holds
fail (they can be retried). A screenshot takes ~2-10 s, plus a few seconds of model loading for the first one."""

ANNOTATOR_WORKER_EXIT_S = 10.0
"""Seconds a worker may take to exit after its input closes before it is terminated."""

# ---- labels ----------------------------------------------------------------------------------------------------
# The labels themselves (names, colours, keys, pictures, box rules) are the registry's: RF_DETR_LABEL_INFO in
# grand_project/detect/constants.py, read through grand_project/detect/labels.py.

ANNOTATOR_CLASSICAL_SOURCE = RF_DETR_SOURCE_CLASSICAL
"""Annotation source of boxes the classical detector found."""

ANNOTATOR_MANUAL_SOURCE = "manual"
"""Annotation source of boxes a reviewer drew or changed."""

ANNOTATOR_CITY_GUESS_SOURCE = RF_DETR_SOURCE_CITY_GUESS
"""Annotation source of a citadel whose city type is an unsure look-alike guess (``cities.screenshot_city_types``:
margin under ``CITY_LOOK_SURE`` or a window cut off by the screenshot edge)."""

ANNOTATOR_GUESS_SOURCES = RF_DETR_GUESS_SOURCES
"""Sources of guessed boxes (an unsure city type, biome or city area): the editor draws them dotted and the queue
lists the screenshots with the most of them first."""

ANNOTATOR_HASHED_LIGHTNESS = 0.62
"""HLS lightness of the hashed colours of labels without a fixed one: light enough to read on the dark atlas."""

ANNOTATOR_HASHED_SATURATION = 0.75
"""HLS saturation of the hashed label colours."""

ANNOTATOR_LABEL_PICTURE_PX = 40
"""Side of the label pictures sent to the editor, px: sharp at the 34 px the inspector shows them on a 1x screen and
the 20 px of the label list on a 2x one."""

ANNOTATOR_LABEL_PICTURE_QUALITY = 85
"""WebP quality of the label pictures. They travel with every editor update: as PNG the 90 pictures of a named-icon
palette took 555 KB, as WebP (transparency kept) about 110 KB."""

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

ANNOTATOR_SESSION_RELOADS = "editor_reloads"
"""Streamlit session key: how often this session's editor was reloaded with the saved boxes because another tab saved
the screenshot first (part of the editor key, so the editor mounts anew)."""

ANNOTATOR_SESSION_NOTICE = "detection_notice"
"""Streamlit session key: a message shown as a toast after the next rerun."""

ANNOTATOR_SESSION_PRELABEL = "prelabel_process"
"""Session state key of the running model pre-label pass (``model_prelabel`` as its own process)."""

ANNOTATOR_PRELABEL_LOG = "model_prelabel-{stamp}.log"
"""A model pre-label pass's output, in the output folder (the page shows its last lines): one file per pass (``stamp``:
the time and the page's process id), so two tabs starting passes on one folder never write into one log."""

ANNOTATOR_PRELABEL_LOG_GLOB = "model_prelabel-*.log"
"""The pre-label logs of an output folder (a tab that started none shows the newest)."""

ANNOTATOR_SESSION_PRELABEL_LOG = "prelabel_log"
"""Session state key of the log of the pass this session started."""

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

# ---- seeding from an atlas's hand-labelled biome truth (truth_seed.py) -----------------------------------------

ANNOTATOR_TRUTH_FILES = (paths.TEST_DATA / "fr-atlas" / "truth.json",)
"""The hand-labelled biome truths ``build_store`` seeds the store from (the PM's fr-atlas truth, 2026-11-20)."""

ANNOTATOR_TRUTH_MARK = "truth"
"""The field (in a screenshot's ``extra``, and the export's manifest) naming the truth that seeded it: a biome truth
(``truth_seed``) vouches for its city areas and citadels, hand-checked map node positions (``node_truth``) for its map
nodes, so ``train_rf_detr --truth-seeded`` may train on it unreviewed. A detection rerun replaces ``extra``, so the
mark goes with the boxes it vouched for."""

ANNOTATOR_TRUTH_SOURCE = "biome_truth"
"""Annotation source of boxes a hand-labelled biome truth set (``truth_seed``): no guess, so drawn solid. The PM's
fr-atlas truth is about 90% right by its labeller's estimate; the classical city-area guesses it replaces were about
50% right there (2026-11-20)."""

ANNOTATOR_TRUTH_MAP_REACH = 20.0
"""Atlas units within which a node box's middle is the truth's map (the truth file's own rule: "a map within 20
atlas units is the same map"; the median map spacing is 82)."""

ANNOTATOR_NODE_TRUTH_REACH = 5.0
"""1080p px within which a map node box's middle is a hand-checked map node position (``node_truth``): the positions
are the classical detector's own map nodes, and a box clipped at the screen's edge moves its middle by ~1 px."""

ANNOTATOR_TRUTH_CITY_REACH = 60.0
"""Atlas units within which a citadel box's middle lies of a city area's map for the citadel to be that city's (the
truth's rule for a City finding its city area); a citadel farther from every city area is a false one (the fortress
ones: 91 of fr-atlas's 413 seeded citadels)."""

ANNOTATOR_TRUTH_STRONGHOLD_REACH = 250.0
"""Atlas units within which a Breach stronghold box's middle lies of a map of a truth stronghold area, for the report
only (the truth labels roughly every stronghold area: 133 of fr-atlas's 176 seeded stronghold boxes were this close)."""


# ---- the iterative loop: review effort and model pre-labels -----------------------------------------------------

ANNOTATOR_EFFORT_MOVE_IOU = 0.75
"""Overlap under which a kept box counts as moved or resized (``effort.edit_cost``): a node box (38.7 px) shifted
about 5 px, or resized about 10 %. Smaller nudges are within the box rules' tolerance."""

ANNOTATOR_SCORE_ASPECT_TOLERANCE = 0.01
"""``score_nodes``: how far a screenshot file's width / height may differ from the size its boxes were saved in (as a
ratio) and still be the same view, its boxes scaled to it (a 1440p copy of a 1080p screenshot); beyond it the file
was replaced by another view and its boxes are not scored."""

ANNOTATOR_UNASSIGNED_ARM = "unassigned"
"""The effort report's arm of a review no pre-label pass assigned an arm (reviewed before the A/B loop): its own row,
never counted in the classical control arm."""

ANNOTATOR_EFFORT_SECONDS = {"kept": 0.3, "relabelled": 1.5, "moved": 3.0, "deleted": 1.0, "added": 5.0}
"""Estimated seconds a reviewer spends per box by what the review did to it (a kept box still has to be checked).
Estimates, not measurements: ``effort report`` fits them to the review timer's active seconds once enough timed
reviews exist."""

ANNOTATOR_EFFORT_MIN_FIT = 10
"""Timed reviews from which ``effort report`` fits the seconds per edit to the active seconds."""

ANNOTATOR_IDLE_MS = 60_000
"""Milliseconds without a key or pointer event after which the review timer stops counting (a reviewer away)."""

ANNOTATOR_PRELABEL_FIELD = "prelabel"
"""The field (in a screenshot's ``extra``) saying what pre-labelled it: ``{"source": "classical" | "rf_detr",
"model", "model_sha", "policy", "round"}`` (``model_prelabel``), so the effort report compares the arms."""

ANNOTATOR_PRELABEL_PLAN = "prelabel_arms"
"""The store's ``meta`` entry holding each spatial block's planned pre-label arm (block -> ``classical`` |
``rf_detr``), kept apart from a screenshot's done mark (``ANNOTATOR_PRELABEL_FIELD``): a model pass that fails keeps
its blocks in the model's arm for the next one."""

ANNOTATOR_SQL_CHUNK = 500
"""Keys bound in one SQL query of the store (SQLite's limit is 999 in older builds)."""

ANNOTATOR_REVIEW_FIELD = "review"
"""The field (in a screenshot's ``extra``) holding its review log: ``{"active_s", "reviewed_at"}``."""

ANNOTATOR_PRELABEL_POLICIES = ("classical", "model", "relabel", "union")
"""How model pre-labels join the classical boxes (``model_prelabel.merge``): ``classical`` keeps them as they are;
``model`` takes the model's boxes instead (a hand truth's box stays); ``relabel`` keeps the classical boxes and gives
each the class of the model box it matches; ``union`` is ``relabel`` plus the boxes only the model found (dotted).
``simulate_loop`` measures which one saves the most edits."""

ANNOTATOR_PRELABEL_POLICY = "relabel"
"""The policy ``model_prelabel`` uses unless told otherwise. The simulated loop (2026-11-21, fr-atlas, the trial
recipe) chose it: after a first round of 63 screenshots it left 1.7-1.9 truth-checked edits per screenshot where the
classical boxes left 8.2-10.7, and as it keeps the classical boxes it adds none to judge; ``union`` saved as many
truth-checked edits but added 19-31 boxes per screenshot only the model found, unchecked until reviewed."""
