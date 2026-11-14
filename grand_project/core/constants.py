"""core.constants (from atlas_builder_core.py)"""

from __future__ import annotations

from grand_project import paths as rc_paths

# ------------------------------------------------------------------ tunables
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


# Game HUD on a full, uncropped window: hud_mask_full.png (white = HUD), drawn by the user on a
# 1919x1079 screenshot and scaled for other full-window sizes. Nodes / towers / badges "found" there
# are detector mistakes on the UI.
# A spot counts as UI only HUD_DEPTH px inside the outline: it is hand-drawn, real maps sat up to
# 30 px inside it, UI pieces 44+ px (random_samples_truth).
HUD_DEPTH = 35


HUD_MASK_FILE = rc_paths.ref("hud_mask_full.png")


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


# images the atlas itself writes (never screenshots): <atlas>_terrain.png, _composite.png, _network.png, ...
ATLAS_OUTPUTS = ("_terrain.png", "_terrain.npz", "_composite.png", "_network.png", "_coverage.png", "_badges.png")


ROW_STEP_PX = 36.0  # screen px between neighbouring badges of one row (measured)
