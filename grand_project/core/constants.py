"""core.constants (from atlas_builder_core.py)"""

from __future__ import annotations

from grand_project import paths as rc_paths

# ------------------------------------------------------------------ tunables
SCREEN_HEIGHT = 1080  # px: every screenshot is scaled to this height when read (the detector's size)
VOTE_BIN = 8  # px, translation histogram bin


SIG_DIST1, SIG_DIST2 = 8.0, 10.0  # neighbour-spacing agreement for a "good" pair


REFINE_TOLS = (16, 12, 8, 6, 5)


MERGE_TOL = 9.0  # px: a frame node closer than this to an atlas node IS that node


MIN_INLIERS = 8


MIN_OVERLAP_RATIO = 0.40


MIN_NCC = 0.35


SCALE_RANGE = (0.90, 1.12)


LANDMARK_MERGE = 45.0


ICON_BASE_DY = 24.0  # screen px: a map base sits this far below its icon badge (measured, 22-28)


ICON_MERGE = 14.0  # atlas units: the same badge seen in two screenshots


# The atlas camera is tilted: panning sideways moves the bottom of the screen further than the
# top, and panning up/down squashes the view.  Undoing that tilt ("rectifying") turns every pan
# into a pure shift.  HORIZON is where the map's vanishing line sits, in PIXELS above the top
# edge of the screenshot (negative = above).  It is a fixed distance, not a fraction of the image
# height: cropped Screenshot_35-38 fit -2170 px, full 1919x1079 Screenshot_39-43 fit -2150 px.
# Assumes a 1080p game window with the top of the screen kept when cropping.
# Set to None to disable (treat screenshots as flat, the pre-0.2 behaviour).
HORIZON: float | None = -2155.0


PLACEMENT = "shift"  # "shift" (pans on the flattened map) or "affine" (old behaviour)


TERRAIN_MIN_AGREE = 15  # terrain fallback: features agreeing on one shift


TERRAIN_SCALE = 1.0075  # parallax: ground texture moves ~0.75% more than the map nodes on a pan (measured


# on 157 crawl pairs, same on x and y); terrain shifts are divided by it so they are
# in map-node units. Uncorrected, a 1100-unit jump was ~10 units off and the map
# refine (allowed < 10) was thrown away.
PARALLAX_MIN_INLIERS = 15  # second chance for screenshots of raised ground: exact matches needed ...


PARALLAX_TOL = 20.0  # ... and this share of maps within this distance


PARALLAX_RATIO = 0.45


DROP_MIN_INLIERS = 5  # placing by hand: maps that must agree near the drop point


TERRAIN_MIN_NCC = 0.40  # ...and a stricter whole-overlap pixel check than the map route (0.35)


# Game HUD on a full, uncropped window: hud_mask_full.png (white = HUD), from a 1920x1080 screenshot taken
# over black unexplored fog (everything not black is interface; the stat text blocks are filled whole, their
# numbers change width), scaled for other full-window sizes. Nodes / towers / badges "found" there are detector
# mistakes on the UI. A spot counts as UI HUD_DEPTH px inside the outline: map nodes half behind the HUD
# have their middle just inside it.
HUD_DEPTH = 8


HUD_MASK_FILE = rc_paths.ref("hud_mask_full.png")


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# every PNG the program writes carries this text tag; the screenshot check skips tagged files, so a map image,
# thumbnail or export left in a screenshot folder is never added as a screenshot (user: an overview image
# landed in Waiting)
GENERATED_TAG = b"GrandProject"


# images the atlas itself writes (never screenshots): <atlas>_terrain.png, _composite.png, _network.png, ...
ATLAS_OUTPUTS = ("_terrain.png", "_terrain.npz", "_composite.png", "_network.png", "_coverage.png", "_badges.png")
# ...and old icon-labelling sheets "<atlas>_badges_<round>.png" written before images were tagged (user: auto-add
# tried to add six of them in an old crawl atlas folder)
ATLAS_OLD_SHEETS = r"_badges_(after|check|round\d+)\.png$"  # (only these names: review)


ROW_STEP_PX = 36.0  # screen px between neighbouring badges of one row (measured)


# clean map (Fix seams, core/seams.py)
SEAM_SCORE_SCALE = 4  # screenshot scores are worked out at 1/4 size (smooth anyway)
SEAM_DARK = 25  # grey level: at or below this a spot counts as unseen fog
SEAM_LIT = 60  # ... and from this on as fully lit
SEAM_DARK_FLOOR = 0.35  # a dark spot keeps this share of its score: a lit copy wins clearly
SEAM_LIT_BLUR = 25  # (at 1/4 size: ~100 px) how lit an area is, not single dark rocks / water: no specks
SEAM_GRID = 8  # atlas units per ownership cell
# costs (one unit = one cell of plain seam between two views of a spot right in their middles)
# a screenshot's well-seen middle (user, 1920x1080 px): a trapezoid, (y, half width) of its top and bottom
SEAM_MIDDLE_TOP, SEAM_MIDDLE_BOTTOM = (241, 630), (1005, 302)
SEAM_DATA_W = 12.0  # cost of taking a spot on the edge of a screenshot's middle (0 at its centre, grows outside)
SEAM_S_FULL = 200  # px from a screenshot's edge / HUD (x how lit) from where a spot costs nothing more
SEAM_EDGE_W = 8.0  # cost of taking a spot right at a screenshot's edge / HUD, or in its fog
SEAM_OFF_W = 3.0  # seam: + this times how far off each screenshot's middle the spot is (0 middle, 1 trapezoid edge)
SEAM_SHIFT_W = 2.0  # seam: + this per 1000 units between the two screenshots
SEAM_TEX_W = 3.0  # seam weight: x(1 + this) through busy ground
SEAM_PATH_W = 10.0  # ... + this on paths
SEAM_NODE_W = 300.0  # ... + this on map nodes and their icons
SEAM_NODE_R, SEAM_ICON_R, SEAM_PATH_HALF = 38, 28, 8  # atlas units: map node / icon cores, path band
SEAM_NEAR_SHARE, SEAM_NEAR_FALL = 0.3, 70  # around a core: this share of SEAM_NODE_W, falling to 0 this many units away
SEAM_CYCLES = 2  # alpha-expansion rounds over all screenshots
SEAM_FLOW_SCALE = 64  # costs to integer capacities


# groups of waiting screenshots (core/islands.py)
ISLAND_MIN = 2  # screenshots in an island before it is matched as one piece
ISLAND_CANDIDATES = 12  # shifts passing the quick count that get the exact check
ISLAND_TERRAIN_TRIES = 3  # of those passing it, the best this many get the terrain check
ISLAND_COVER_CELL = 20.0  # atlas units: grid cell for "which area does an atlas / a group cover"
ISLAND_QUICK_TOL = 8.0  # px: a map counts as landing on one in the quick count (shifts are rounded to 4 units)


# worker processes (fileio.process_pool: detecting many screenshots at once, the atlas-wide check's path tracing)
# Each worker's thread pools (OpenCV, OpenMP, BLAS, PyTorch) are limited to its share of the CPU: the CPUs divided
# among the workers. Uncapped, every worker started one thread per CPU (the map and tower models' predict, OpenCV),
# and 4 workers detecting 16 screenshots took 4.33 s per screenshot instead of 1.63 s capped (22-thread Ryzen 9 7900X,
# screenshots/crawl, 2026-11-27); 1, 2 or 5 threads per worker made no difference once capped.
POOL_THREAD_ENV_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
"""Thread limits set in each worker for libraries it loads later (PyTorch for RF-DETR reads them when it starts)."""
