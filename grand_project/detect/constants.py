"""detect.constants (from atlas_detect.py)"""

from __future__ import annotations

from pathlib import Path

from grand_project import paths as rc_paths

HERE = Path(__file__).resolve().parent


DETECTOR_ID = "detect1"  # in builder cache file names: results of another detector are never reused


TESTS = rc_paths.TEST_DATA


TRUTH = TESTS / "truth" / "truth.json"


SHOTS = rc_paths.SCREENSHOTS / "random_samples"


CACHE = TESTS / "old_detector_cache"  # (not shipped: old-detector comparison only)


TOWER_REFS = TESTS / "truth" / "tower_refs.json"  # towers / maps in the user's tower shots


TRUTH_SETS = [
    (TRUTH, SHOTS),  # (truth.json, its screenshots)
    (TESTS / "truth_ocean" / "truth.json", rc_paths.SCREENSHOTS / "ocean"),
]  # ocean / Expedition round


EXTRA_MAPS = TESTS / "truth" / "extra_maps.json"  # maps only: the user's path-marked shots
EXTRA_BADGES = TESTS / "truth" / "extra_badges.json"  # icon positions only (finder training): 50 crawl shots,
# the old and new finder's icons as reviewed by the user (paths relative to the test data)


DB_PATH = rc_paths.DATABASE


# stage 2 settings
BLOB_SIGMA = (2, 7)  # difference of blurs on brightness: a map base's glow


BLOB_MIN = 10  # catches 759 of 766 labelled visible maps


BLOB_WIN = 15


R = 16  # map-base patch radius (px at 1080p)


RIM_R = 48  # tower rims are ~3x a map rim (user): gold measured out to here


MAP_NMS = 22


MAP_MERGE = 30  # two map finds closer than this are one map (duplicates sat 24-38 px apart; 10 labelled


# shots: 32 -> 27 wrong, 1 real pair lost - real maps are rarely < 30 px apart)
MAP_MIN = 0.5  # probability to call a candidate a map


NOT, MAP = 0, 1


# ---------------------------------------------------------------- stage 5
# Paths are amber dotted lines. Dashes: bright amber (R>145, G>95, R-G>32, G-B>35, B<145; user / GPT)
# or dimmer gold that is brighter than its surroundings (shadowed paths), or washed-out orange
# fog), small dash-sized blobs only,
# HUD removed. Traced dash by dash between maps by the user's rules: gentle turns, a walk ends at the first
# map on its way (towers: wider), real dotted lines have regular dash spacing, paths never cross /
# share a route (best walks kept first), and two dead ends meeting = a map the map finder missed.
# Path dashes around a spot are also map
# evidence: maps are where paths end or meet (user).
DASH_AREA, DASH_SIZE = (2, 60), 26


PATH_START = (9.0, 50.0)  # px from a map centre where its dotted lines may begin (badges and the ring often


# hide the first dashes: at 30 px, 20 of 34 user-marked missed lines never started)
PATH_STEP, PATH_JUMP = 22.0, 36.0  # next dash / bridged gap (dash spacing along a line ~8-11 px)


PATH_LAT = (3.5, 0.12)  # the next dash must lie within 3.5 px + 12% of the step of where the curve so far


# predicts it (gap jumps: 70% of that) - paths bend gently and steadily (user)
PATH_BEND_MAX = 1 / 90  # tightest bend: radius 90 px


PATH_BEND_SMOOTH = 0.5  # how fast the learned bend follows each step


PATH_MAX_ANG = 50.0  # never more than this off the predicted heading


PATH_ARRIVE, PATH_ARRIVE_TOWER = 18.0, 34.0  # a walk passing this close to a map ends there (first map on the way)


PATH_MAX_STEPS, PATH_MIN_DASHES, PATH_MAX_DETOUR = 120, 3, 1.8


PATH_SPACING = (5.0, 15.0)  # a real dotted line: most steps between neighbouring dashes are this long


PATH_REGULAR = 0.55  # ... at least this share of them (Vaal city lights are irregular)


PATH_LOOSE_DASHES = 6  # a walk this long that reaches no map: a map may be at its end


PATH_LOOSE_MEET = 25.0  # ... two such ends (from different maps) this close: a map there (user: paths show maps)


PATH_END_RESCUE = (0.02, 40)  # ... and a map candidate at least this likely within this many px of it (the


# meeting point is often a bit off the real map - user)
PATH_SINGLE_END_ON = False  # OFF: on the 10 labelled shots it added 42 maps, ~34 of them amber trees, tower


# flames / tops and lit structures that also end dotted-looking chains
PATH_SINGLE_END = (6, 30.0)  # ONE regular line of 6+ dashes running out in view, with a weak map candidate


# within 30 px past its end, is a map too (3 random shots: 8 of 10 such were
# maps the user circled)
PATH_SNAP = 40.0  # a line that runs out this close in front of a map ends AT that map (user: a


# dead end next to a map with paths is that map, not a second one)
PATH_MAX_DEGREE = 5  # paths per map (6 is never seen - user)


PATH_LEAVE_ANGLE = 18.0  # two paths never leave a map in the same direction (no forks / shared routes)


PATH_AHEAD = 30.0  # a dead end counts only if the image this far ahead of it is in view


PATH_MEET_MANY = 99  # 3+ dead ends meeting need no map score: OFF (20 labelled shots: +2 wrong maps, 0 right)


PATH_MEET_COS = 0.5  # two dead ends meeting come in from directions > 60 deg apart


PATH_SHARE = 2  # dashes two paths may share (next to a common map)


# Paths from the strict amber mask (user / GPT filter: every dotted line in it is a real path). Each dash is a
# short stroke pointing along its path; trees, flames and rings are blobs that point nowhere. Dashes link to
# the next dash along their own direction into chains, chains are joined across a missed dash or two, cut where
# they pass through a map, and each piece between two maps is a path. The walk above only fills in pairs the
# chains missed, and only when its drawn line runs on the dots. On all user marks + amber lines (7 shots):
# dotted lines covered 74% -> 83%, drawn paths on dots 61% -> 78%, drifting lines drawn right 32% -> 94%.
CHAIN = {
    "area": (3, 60),
    "len": (3.0, 16.0),
    "elong": 1.6,
    "gap": (4.0, 30.0),
    "ang": 25.0,
    "side": 4.0,
    "stitch": 45.0,
    "stitch_ang": 30.0,
    "map_r": 70.0,
    "map_ang": 40.0,
    "through": 24.0,
    "min_dashes": 3,
}


WALK_FILL_ON_DOTS = 0.6  # a walk path fills in only if this share of its drawn line is on amber dashes


SEEN_CELL = 40  # px: cell of the "clearly visible" grid saved with a detection


WALL_CELL = 16  # px: cell of the fortress-wall grid saved with a detection


WALL_STEP, WALL_SCALES = 8, (9, 25, 61)


WALL_MIN_AREA, WALL_MIN_LEN, WALL_CORNERS = 12000, 200, 1.3


WALL_CROSS = 0.15  # a path whose middle runs this much over fortress wall goes through it: not real


FORTRESS_PAINT = TESTS / "fortress_paint"  # user-painted walls: <k>.png alpha masks over paint_<k>.png


# ---------------------------------------------------------------- stage 3
# icons are found by their rim alone (user: the rim is the same on every icon), then named by what's inside
ICON_RIM_R = (7.0, 12.5)  # px: the rim (dark line at 8-9, gold at 10-11) compared with the template; the most constant
# radii of 480 hand-labelled icons
RIM_CANDIDATE = 0.35  # rim score from which a circle is a candidate (493 of 523 labelled icons, ~1500 per shot)
ICON_CLEAR = 12.0  # px: an icon's centre this far from the HUD and the screen edge (its whole rim visible)
# icons with their own rim (not the standard one): found by a whole-icon template (in BADGE_FINDER_FILE) and named
# by it. Match level per icon: known ones on 70 screenshots scored >= 0.89 / >= 0.83, the best other spot <= 0.77 /
# <= 0.48. (Deadly-boss icons have a standard-like rim: the rim finder finds them.)
SPECIAL_ICONS = {"AbyssalDepths": 0.83, "CorruptionNexus": 0.70}
SPECIAL_R = 15  # px: the part of a special icon compared


BADGE_MIN = 0.5  # badge probability


BADGE_ROW_MIN = 0.1  # ... enough when the spot fits a row: next to a badge, or a row slot above a map


BADGE_NMS = 18


HIDDEN_SNAP = 45.0  # no hidden map for a badge row with a visible map this close under it


ROW_RESCUE = (0.02, 14)  # a badge row with no map under it: take a map candidate this likely within this


# many px (on the 10 samples: +29 maps right, +5 wrong); else it is a hidden map
ROW_DY, ROW_STEP = 24, 36  # row 24 px above the map base, badges 36 px apart, centred on the map


# ---------------------------------------------------------------- stage 4
# Towers: tall dark spires ~50 px wide and up to ~200 px high standing on their map (the base), green
# glow at the foot, a flame on top while active. Tower vs map: classifier on found maps (tall window
# above the map + the old hand-made tower rules as one more feature; 20 labelled towers so far).
TOWER_MIN = 0.9  # 10 samples: 15 right, 1 wrong, 5 missed (old detector 12 / 1 / 8)


TOWER_NMS = 45  # a tower base is wide: other "maps" this close are the same tower


TOWER_BADGES = (45, 100, 230)  # a badge row this close sideways and 100-230 px above a tower is the tower's


# Deadly Map Boss badge -> its map (under the row's middle) is a City / Hall / plain deadly boss (user rules,
# thresholds from the 14 labelled ones: 13 right)


HALL_ORANGE = 700  # orange beam pixels within +-80 px (the beam on the Hall's structure)


STRONGHOLD_EMPTY = 120  # a Breach stronghold with no map found this close is locked (only ground shows)


TREE_NEG_WEIGHT = 1.0  # x15 tried: 48 -> 64 wrong maps on the labelled shots


EXPEDITION = "Expedition"
EXPEDITION_WATER = (600, 0.15)  # Expedition only appears in the water zone (user): open water within 600 px of its map,
# at least this share (every labelled Expedition: >= 0.19; inland areas: little or none)
INFLUENCE_MIN = (
    0.9  # an icon is only named a biome influence (Mountain / Forest / ... Influence) when the finder is this
)
# sure of its rim (user: they look like terrain; "very strong rim assurance")


NOT_ON_EXPEDITION = ("Hall", "Tower")  # user: Halls / Towers / Hideouts appear in the ocean, never with an


EXP_REACH = (40, 15, 40)  # Expedition badge.  badge -> its map: |dx| <= 40, 15 <= dy <= 40


# the brass barrel under a City's map node (detect/citybase.py)
CITY_BARREL_FILE = rc_paths.ref("city_barrel.npz")
CITY_BARREL_WIN = (-20, 44, -24, 24)  # px around a map node's middle: y0, y1, x0, x1 (the orb and the barrel below it)
CITY_BARREL_SNAP = 30  # px: a rough point (under an icon row, from the atlas) is moved to the map node this close
CITY_P = 0.5  # barrel probability from which a map node is a City


# the icon finder's rim template (the average icon as seen on screen, from the hand labels), so teaching new icon
# pictures (naming) never changes which icons are found: tools/freeze_badge_finder.py
BADGE_FINDER_FILE = rc_paths.ref("badge_finder.npz")
