"""viewer.constants (from atlas_viewer.py)"""

from __future__ import annotations

import os
import sys

from grand_project import __version__, core
from grand_project.detect.constants import ICON_INFO  # noqa: F401  (the icon table lives with the detector)

VERSION = __version__  # one place: grand_project/__init__.py

# --- platform differences (Windows / macOS / Linux) ---
IS_MAC = sys.platform == "darwin"


IS_WIN = sys.platform == "win32"


MOD = "Command" if IS_MAC else "Control"  # shortcut modifier: Cmd on macOS, Ctrl elsewhere


MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"


# Tk numbers the mouse buttons differently on macOS: 2 is the right button and 3 the middle one
BTN_MIDDLE, BTN_RIGHT = (3, 2) if IS_MAC else (2, 3)


MONO_FONT = "Menlo" if IS_MAC else ("Consolas" if IS_WIN else "DejaVu Sans Mono")


CATEGORIES = [
    "Boss",
    "Unique map",
    "Abyss",
    "Breach",
    "Delirium",
    "Expedition",
    "Ritual",
    "Tower",
    "City",
    "Hall",
    "Farm spot",
    "Note",
    "Other",
]


# BGR colours (OpenCV draws the map)
BG = (26, 22, 20)


NODE_COL = {
    "confirmed": (255, 220, 40),
    "icon": (255, 220, 40),
    "single": (0, 150, 255),
    "disputed": (0, 150, 255),
    "doubtful": (140, 140, 140),
}


PATH_MULTI = (255, 215, 40)  # scored in 2+ screenshots


PATH_SINGLE = (0, 185, 255)  # only one screenshot shows both ends


PATH_ABYSS = (230, 80, 255)


LANDMARK_COL = {
    "Tower": (100, 235, 100),
    "City": (255, 200, 80),
    "Hall": (60, 150, 255),
    "Breach stronghold": (235, 110, 225),
    "Locked stronghold": (150, 90, 150),
    "Deadly boss map": (50, 50, 255),
}


BOOKMARK_COL = (40, 210, 255)


SELECT_COL = (255, 255, 255)


HIT_COL = (0, 255, 255)


REMOVED_COL = (70, 70, 255)


STYLE_DEFAULT = {
    "path_style": "solid",
    "path_width": 0,
    "path_col": "",
    "path_col1": "",
    "map_col": "",
    "map_size": 1.0,
    "map_style": "circles",
    "path_freq": 0.0,
    "ov_towers": False,
    "age_tint": "off",  # View tab "Colour by": one of COLOUR_BY
    "colour_spread": "plasma",  # ...its colours for oldest to newest / times seen: one of COLOUR_SPREADS
}  # View tab


ICON_ROW_DY, ICON_ROW_STEP = 24, 36  # icons are drawn in a row this far above their map node, this far apart,
# centred on it: the detector's row rule (detect.constants ROW_DY, ROW_STEP), so icons line up like in the game


TYPE_ROW_H = 26  # px per row of the type list in Find (its icon pictures are 22 px)


SIDE_WIDTH = 400  # side panel width in px at first start (was a fixed 360: cramped, user); the sash changes it
SIDE_MIN = 330  # ...and the narrowest it can be dragged (the 7 tab headers still fit)


IMAGE_EXT = core.IMAGE_EXT


WATCH_BATCH = 24  # auto-add: screenshots waiting in the queue are added together (one re-check)


WATCH_ASK = 50  # a hand-picked folder (not the atlas's own) with more screenshots the atlas lacks: ask first
WATCH_POLL_MS = 2000  # how often the watched folder is checked
DETECT_LOG_EVERY = 50  # detecting many screenshots: a progress line in the debug log every this many
WATCH_RETRIES = 2  # a watched screenshot whose detection failed is tried this many more times


TERRAIN_PIXELS = 40_000_000  # stitched map size limit


SAME_SPOT = 28.0  # atlas units: a bookmark this close to a thing IS that thing's bookmark


# (a map's badge sits ~24 above its base; maps are >= ~36 apart)
SNAP_PX = 16  # bookmark mode: clicks this close (screen px) to a map/icon snap to it


RECENT_KEEP = 200  # screenshots listed under Recently added (one line each, newest first)


RECENT_FADE = 5  # ...of which the newest 5 are outlined on the map: 100% fading to 0


UNDO_KEEP = 10  # atlas snapshots kept for "Undo last add"


RECENT_COL = (255, 0, 255)  # outline of the newest screenshot(s); older recent ones fade


# A placement is "weak" only when BOTH signs are poor (crawl: correct placements went down to
# 9 agreeing maps, 13% were terrain-only; terrain agreement 2nd percentile 0.43) -> ~1-2% asked
WEAK_INLIERS = 9  # at most this many agreeing maps (or terrain only) ...


WEAK_NCC = 0.45  # ... AND terrain agreement below this


PROFILE = bool(os.environ.get("ATLAS_VIEWER_PROFILE"))  # print slow window-thread steps


HIRES_MAX_FRAMES = 30  # screenshots warped at native resolution for one zoomed-in tile
# Zoomed in, the ground is drawn from the screenshots themselves in fixed tiles at fixed zoom levels, kept in
# memory: panning reuses them (a whole-view picture was thrown away on every pan, so each drag showed the blurry
# map first and then swapped the ground: user). A level is a power of 2 in px per atlas unit, at least the zoom.
HIRES_TILE = 512  # px per side of one tile
HIRES_TILE_CACHE = 160  # tiles kept (~1 MB each)
HIRES_MAX_LEVEL = 2.0  # px per atlas unit; zoomed in further, the level-2 tiles are scaled up
ATLAS_THUMB = (112, 84)  # px: an atlas's thumbnail on its card in the Saved atlases tab
ATLAS_RETRY_S = 60.0  # s: a card whose numbers / thumbnail could not be read is tried again after this
ATLAS_RETRIES = 3  # ...at most this many reads per atlas and session
# frame log (Debug tab / ATLAS_FRAME_LOG=1): a check every FRAME_TICK_MS; later than that by more than
# FRAME_STALL_MS = the window did not respond (a stall)
FRAME_TICK_MS = 15
PATH_CELL = 512.0  # atlas units: dashes are sorted into cells this big; a frame only touches those in view
FRAME_STALL_MS = 50


PLACE_ICON = {
    "City": "MapBossSpecial",
    "Hall": "MapBossSpecial",
    "Breach stronghold": "MapBossSpecial",
    "Tower": "LostTower",
    "Ezomyte city": "MapBossSpecial",
    "Vaal city": "MapBossSpecial",
    "Faridun city": "MapBossSpecial",
    "Potential city map": "GrassInfluence",
    "Potential stronghold map": "Breach",
}  # place rows in the Find list: shown with these icons


CITY_COL = {
    "Ezomyte": (90, 210, 90),
    "Vaal": (240, 150, 50),
    "Faridun": (240, 215, 130),
    "Breach": (225, 80, 235),
}  # tint of the maps a city / stronghold biome may cover


POTENTIAL_TYPES = ("Potential city map", "Potential stronghold map")


LANDMARK_KINDS = ("City", "Hall", "Tower", "Breach stronghold", "Locked stronghold", "Deadly boss map")


EDIT_SAME = 90.0  # atlas units: a hand edit applies to the landmark this close (landmarks drift


# a little between re-checks)
EDIT_SPOT = 15.0  # a new edit replaces an older one only at the same spot


# --- replay / timelapse (viewer.replay, viewer.replay_panel) and colouring screenshots by when they were taken
REPLAY_TYPES = ("by time", "spiral", "distance", "scan lines")  # the order things are revealed in
# (by placement was dropped: by time covers it, user). Scan lines: columns from the right, each top to bottom.
REPLAY_REVEALS = ("screenshots", "area")  # spiral / distance / scan lines: whole screenshots, or a smooth sweep
REPLAY_CAMERAS = ("whole atlas", "grow with atlas", "follow newest")  # where the view goes while replaying
REPLAY_SMOOTHING = {"off": 0.0, "light": 0.12, "medium": 0.35, "heavy": 0.9}  # s: camera easing time constant
REPLAY_DEFAULTS = {
    "type": "by time",
    "reveal": "screenshots",
    "camera": "whole atlas",
    "smoothing": "light",
    "length": 20.0,  # s: how long the timelapse is (the GIF; the preview at 1x)
    "speed": 1.0,  # preview speed only (user)
    "per_step": 1,  # screenshots revealed per step
    "gif_width": 800,  # px of an exported GIF (its height follows the map view's shape)
}
REPLAY_SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
REPLAY_TICK_MS = 40  # playback frame time (25 fps)
REPLAY_SESSION_GAP = 30 * 60  # s between two screenshots that starts a new session (colours, timeline)
REPLAY_BATCH_GAP = 60  # s between two screenshots that starts a new batch (a tick on the timeline)
REPLAY_SPIRAL_PITCH = 900.0  # atlas units between turns of the spiral (about half a screenshot's width)
REPLAY_SCAN_COLUMN = 1920.0  # atlas units: width of a scan-line column (one screenshot)
REPLAY_AREA_STEPS = 400  # reveal by area: the sweep is split into this many steps (timeline resolution)
REPLAY_AREA_RES = 1024  # reveal by area: the sweep field is worked out on a grid this many cells on its long side
REPLAY_AREA_SOFT = 0.02  # reveal by area: the sweep's edge fades over this share of the whole sweep
REPLAY_FOLLOW_SPAN = 2.5  # "follow newest": the view is this many screenshot widths across
REPLAY_GIF_FPS = 15
REPLAY_GIF_MAX_FRAMES = 450  # 30 s at 15 fps; a longer replay is sampled more sparsely
REPLAY_TINT_ALPHA = 0.32  # how strongly "Colour by" tints the map
COLOUR_BY = ("off", "by session", "oldest to newest", "times seen")  # View tab "Colour by" (times seen = heatmap)
COLOUR_SPREADS = {  # View tab colour spread for oldest-to-newest and times seen: name -> OpenCV colour map
    "plasma": 15,  # cv2.COLORMAP_PLASMA
    "heat (inferno)": 14,  # cv2.COLORMAP_INFERNO
    "viridis": 16,  # cv2.COLORMAP_VIRIDIS
    "turbo": 20,  # cv2.COLORMAP_TURBO
    "cool to warm": 2,  # cv2.COLORMAP_JET
}
HEAT_RES = 1024  # times seen: counted on a grid this many cells on the atlas's long side
# session colours (BGR), in order; more sessions than colours repeat them
REPLAY_SESSION_COLS = (
    (60, 200, 255),
    (255, 160, 60),
    (120, 230, 120),
    (220, 110, 255),
    (80, 110, 255),
    (255, 230, 120),
    (200, 200, 200),
    (40, 160, 160),
)


LABEL_GRID_PX = 64  # icon names: screen boxes are looked up in a grid of cells this big (helpers.BoxGrid)
