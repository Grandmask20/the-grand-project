"""app.constants: the app's settings and colours (the page gets the ones it draws with from /api/meta)."""

from __future__ import annotations

from grand_project import __version__, core
from grand_project.detect.constants import ICON_INFO  # noqa: F401  (the icon table lives with the detector)

VERSION = __version__  # one place: grand_project/__init__.py

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


SELECT_COL = (89, 230, 255)  # BGR: the selection ring, yellow (as the 3D view's selected-icon ring, user)


HIT_COL = (255, 255, 255)  # BGR: Find's rings, white edged in black, outside the selection ring (user)


REMOVED_COL = (70, 70, 255)


STYLE_DEFAULT = {
    "path_style": "solid",
    "path_width": 0,
    "path_col": "",
    "path_col1": "",
    "map_col": "",
    "map_size": 1.0,
    "map_style": "circles",
    "map_fill": "solid",  # circles / squares: "solid" (filled with the map's colour) or "bordered" (icon colour inside)
    "map_border": "",  # the border's colour when bordered ("" = by status)
    "path_freq": 0.0,
    "ov_towers": False,
    "age_tint": "off",  # View tab "Colour by": one of COLOUR_BY
    "colour_spread": "plasma",  # ...its colours for oldest to newest / times seen: one of COLOUR_SPREADS
    # the 3D view (View tab, while tilted; user): paths' height above the ground (atlas units), how far they reach
    # and icons reach (times the view centre's distance), how thin paths get far away (share of their width), and
    # below how many screen px a dash pattern turns into a line
    "d3_path_lift": 3.0,
    "d3_path_far": 2.6,
    "d3_path_taper": 0.2,
    "d3_solid_px": 8.0,
    "d3_icon_far": 2.5,
    "d3_icon_size": 1.5,  # icons' size in 3D (times their size on the ground)
    "d3_ground_far": 2.4,  # the ground fades into black from this many times the centre's distance (0: never)
    # (the d3 defaults: the user's, about what the game's own camera leaves on screen)
    "d3_model_size": 1.0,  # 3D models' size (width and height) times this
    "d3_model_height": 0.8,  # ...and their height times this again
    "d3_model_far": 2.4,  # 3D models are drawn out to this many times the centre's distance
    "d3_beams": True,  # the beams over halls and towers
    # icons on the flat map (View tab): size (times their in-game size) and picture style: "game art" (the game's own
    # icons), "poe2db art", "from screenshots" (taught crops), "flat colour" (a disc in the type's colour) or "outline"
    "icon_size": 1.0,
    "icon_style": "game art",
}  # View tab


ICON_ROW_DY, ICON_ROW_STEP = 24, 36  # icons are drawn in a row this far above their map node, this far apart,
# centred on it: the detector's row rule (detect.constants ROW_DY, ROW_STEP), so icons line up like in the game


IMAGE_EXT = core.IMAGE_EXT


WATCH_BATCH = 24  # auto-add: screenshots waiting in the queue are added together (one re-check)


WATCH_ASK = 50  # a hand-picked folder (not the atlas's own) with more screenshots the atlas lacks: ask first
WATCH_POLL_MS = 2000  # how often the watched folder is checked
DETECT_LOG_EVERY = 50  # detecting many screenshots: a progress line in the debug log every this many
WATCH_RETRIES = 2  # a watched screenshot whose detection failed is tried this many more times


TERRAIN_PIXELS = 40_000_000  # stitched map size limit


SAME_SPOT = 28.0  # atlas units: a bookmark this close to a thing IS that thing's bookmark


RECENT_KEEP = 200  # screenshots listed under Recently added (one line each, newest first)


RECENT_FADE = 5  # ...of which the newest 5 are outlined on the map: 100% fading to 0


UNDO_KEEP = 10  # atlas snapshots kept for "Undo last add"


RECENT_COL = (255, 0, 255)  # outline of the newest screenshot(s); older recent ones fade


# A placement is "weak" only when BOTH signs are poor (crawl: correct placements went down to
# 9 agreeing maps, 13% were terrain-only; terrain agreement 2nd percentile 0.43) -> ~1-2% asked
WEAK_INLIERS = 9  # at most this many agreeing maps (or terrain only) ...


WEAK_NCC = 0.45  # ... AND terrain agreement below this


ATLAS_THUMB = (112, 84)  # px: an atlas's thumbnail on its card in the Saved atlases tab


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


# --- replay / timelapse (app.replay and the page's timelapse player), and colouring screenshots by when taken
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
    "length": 20.0,  # s: how long the timelapse is (the video; the preview at 1x)
    "speed": 1.0,  # preview speed only (user)
    "per_step": 1,  # screenshots revealed per step
    "video_width": 1280,  # px of a recorded timelapse video (its height follows the map view's shape)
}
REPLAY_SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
REPLAY_SESSION_GAP = 30 * 60  # s between two screenshots that starts a new session (colours, timeline)
REPLAY_BATCH_GAP = 60  # s between two screenshots that starts a new batch (a tick on the timeline)
REPLAY_SPIRAL_PITCH = 900.0  # atlas units between turns of the spiral (about half a screenshot's width)
REPLAY_SCAN_COLUMN = 1920.0  # atlas units: width of a scan-line column (one screenshot)
REPLAY_AREA_STEPS = 400  # reveal by area: the sweep is split into this many steps (timeline resolution)
REPLAY_AREA_RES = 1024  # reveal by area: the sweep field is worked out on a grid this many cells on its long side
REPLAY_AREA_SOFT = 0.02  # reveal by area: the sweep's edge fades over this share of the whole sweep
REPLAY_FOLLOW_SPAN = 2.5  # "follow newest": the view is this many screenshot widths across
REPLAY_TINT_ALPHA = 0.22  # how strongly "Colour by" tints the map (0.32 hid the ground: user)
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


# ---------------------------------------------------------------------------------------------------- the web app
APP_HOST = "127.0.0.1"  # the app serves this computer only: the atlas is the player's own data
APP_PORT = 8765  # default port (the next free one is taken when it is in use); 0 = any free port
APP_PORT_TRIES = 20  # ports tried after APP_PORT when it is in use
APP_HELLO_WAIT = 0.5  # s: a second start waits this long per port for a running copy to answer
APP_LOCK_FILE = "app.lock"  # in user_data: held while the app runs, so two launches at once start only one copy
APP_URL_FILE = "app.url"  # in user_data: the address the lock's holder serves on (a launch finding it taken goes there)
APP_QUIT_WAIT = 40.0  # s: a newer start waits this long for an older running copy to quit (its shutdown may wait 30 s)
APP_STOP_PROBE = 3.0  # s: a connection attempt telling whether a quit copy's port still listens
HELLO_APP = "the-grand-project"  # what /api/hello answers with: the program's own copy, not another server
LOG_KEEP = 2000  # log lines kept for the Log tab of a page opened later
EVENT_HISTORY = 200  # recent events kept for a page that reconnects
TILE_CACHE = 1500  # encoded tiles (map image, sharp ground, vector) kept in memory
UPLOAD_MAX = 64 * 1024 * 1024  # bytes: one uploaded screenshot at most
FS_LIST_MAX = 5000  # entries listed by the folder browser at most

REPLAY_FOG_RES = 512  # timelapse: the "revealed yet" grid has this many cells on the atlas's long side


ICON_DRAW_REV = 3  # bump when icon_picture draws differently: the page's picture URLs carry it (icon_art_version)
ICON_ART_RECHECK = 2.0  # s: the icon art version (file times) is read again at most this often
ICON_CROP_RIM = 13.5  # px: the rim's outer edge from the centre of a taught on-screen icon crop (34 px at 1080p; the
# detector's rim reaches 12.5, detect ICON_RIM_R): the crop is cut there so it is drawn as big as the game's art
ICON_ART_INNER = 0.72  # share of an icon's radius inside its rim (the game's Map Boss icon): poe2db's inner art goes
# there, inside the game's rim

# --- weak-match previews and hand placement (app.adding)
PREVIEW_AGREE_TOL = 8  # atlas units: a weak match's map node on an atlas one counts as agreeing (core REFINE_TOLS)
PREVIEW_NEAR = 3  # a weak match's preview is shown with this many placed screenshots nearest to it
PICTURE_SIDE = 1600  # px: longest side of a flattened screenshot picture (ghost / weak-match preview)
PICTURES_KEPT = 8  # ghost / preview pictures kept for the page to fetch (the newest)

# --- a landmark's map node (app.session: the city / hall / tower / deadly boss map it marks)
# atlas units: on the crawl atlas a landmark is a median 1-7 units from its map node (at most 38) and the next map
# node 75-86 away; a Breach stronghold's map node is about 38 units below it (at most 86)
LANDMARK_NODE_REACH = 45.0
LANDMARK_NODE_REACH_STRONGHOLD = 90.0
