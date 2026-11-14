"""finalize.constants (from atlas_finalize.py)"""

from __future__ import annotations

from grand_project import fileio as atlas_io
from grand_project import gold_paths as gp
from grand_project import paths as rc_paths

FRAME_MARGIN = 22  # px from a screenshot edge: a node closer than this may be cut off


PARALLAX_TOL = 52.0  # maps / badges on raised ground (mountains, outcrops) shift up to ~35-45


# between screenshots: the atlas is 3D, the flattening assumes a plane
TOWER_JOIN = 44.0  # atlas units: a tower base is wide (rim ~3x a map's, user). Where a screenshot did not


# recognise the tower (cut off at the edge) it found two maps 31-40 px apart on its base;
# real maps next to a tower sat 48+ px away. Anything this close to a tower IS the tower.
TOWER_JOIN_SEEN = 2  # ...and only around a tower recognised in this many screenshots


SHARED_MIN_ALONE = 6  # ...and only when this many screenshots found a single map there


SHARED_OK, SHARED_FRAC = 1, 0.2  # copies seen together in at most 1 screenshot / 20% of them may still be one map


DUP_TOL = 26.0  # atlas units: one map found at two spots by different screenshots.


# Within one screenshot real maps are >= ~36 px apart (1st percentile).
SAME_SPOT = 14.0  # badges this close on one map are one badge


ICON_TWIN = 40.0  # a map placed from a badge this close to a found map with the same badge: one map


RATIO_GHOST, RATIO_NEAR, RATIO_COULD = 0.35, 0.70, 8  # found in <= 25% of the shots that show it, while maps


RATIO_REL, RATIO_REL_NEAR, RATIO_COULD_REL = (
    0.0,
    0.85,
    4,
)  # relative ghost rule OFF: removed ~14 real maps for 2 ghosts (atlas_test_data/ghost_check.png)


GAP_ON = True  # user's ladder: badge -> visible base -> paths with a gap; only weak bases get the gap test


GAP_FOUND = 0.6  # ...and only maps found in under 60% of their shots (user's dark real X4 3/3, X5 2/3)


GAP_SEEN = 0.85  # map confidence that counts as a clearly visible base (judged: 12 of 14 real, 1 of 6 ghosts)


GAP_R, GAP_MIN, GAP_SHOTS = 10.0, 2, 3  # px ring; a map with >= 2 amber dashes inside it in EVERY one of 3+ clear shots


JUNCTION = 3  # maps where this many traced paths end are never ghosts (run-over / gap rules)


LONELY_SEEN = 0.9  # ...and only when its base is never clearly seen (crawl: real ones 0.94+)


LONELY_ON, LONELY_SHOTS = True, 3  # maps with no badge and no path are removed (user)


RATIO_R = 200.0  # within 200 are found in >= 85% (and 8+ shots show it): a ghost (user's 2/12, 2/17)


WALL_MAP = 0.6  # a map on the fortress wall in this share of the shots that show it: wall art (user)


ICON_ATTACH_DX, ICON_ATTACH_DY = 24.0, 13.0  # base position tolerance under an icon


ICON_TOWER_SPREAD = 40.0  # a badge whose copies lay this far apart, with no map right under it, is a tower's


ICON_TOWER_REACH = (70.0, 260.0)  # ... its tower map: this far sideways, up to this far below the badge base


ICON_PAIR = 32.0  # badges of one row whose map base was not detected share one new node


ROW_GAP = 46.0  # neighbouring badges in one row over a single map (measured ~36 px)


NO_NODE_ICONS = {
    "Unidentified",
    "LostTower",
    "PlayerOrBookmark",
}  # never create a map node  # these never create a node on their own


ABYSS_NAMES = {"Abyss", "AbyssOverrun"}


ABYSS_LINK = 150.0  # max gap between successive Abyss maps in a chain


ABYSS_CLEAR = 42.0  # non-icon nodes this close to the chain line are river glow


ABYSS_TOWER_CLEAR = 60.0


PATH_THRESHOLD, TOWER_THRESHOLD, PROPOSE = 0.73, 0.63, 0.64


MAX_EXITS = gp.MAX_EXITS


PASS_CLEAR = 28.0  # a traced line running this close to a third map is not a real path


TRACE_WORKERS = atlas_io.workers(6)  # screenshots traced at once in worker processes (when there are many)


TRACE_PARALLEL_MIN = 12


TRACE_MATCH = 30.0  # px: a saved trace's end map -> the atlas map at that spot in the screenshot


CHECK_STEP = 8.0  # px between the points checked along a path


CHECK_NEAR = 9.0  # px: a dash this close to a checked point covers it


CHECK_SEEN = 0.6  # share of a path that must lie in clearly visible ground for a view to judge it


CONFIRM, DENY = 0.35, 0.12  # share of the visible part covered by dashes: confirms / denies the path


LOCAL_RETRACE = (
    0.0  # px around a map a screenshot missed, traced again (0 = off: 3x slower, recovered 1 of 5 lost paths)
)


SECTOR = 25.0  # deg: two real paths of one map are almost never closer (crawl: 3.6% under 25)


SECTOR_STRICT = (
    15.0  # deg: a nearer map this dead ahead blocks the path without further evidence (0.3% of trusted paths)
)


SECTOR_NEAR = 0.88  # ...and a map in that sector this much nearer is where the path really goes


START_LEN = 40.0  # px along a path that give its starting direction


STRAIGHT_VIEWS, STRAIGHT_MAX = 2, 200.0  # untraced links: 2+ screenshots with gold along it, <= 200 long


SEAM_ON = False  # seam joining: off (user: 0 of 10 fully right; ends snapped to wrong/doubled maps)


SEAM_MAX, SEAM_MIN = 280.0, 50.0  # atlas units: map pairs no screenshot shows together, joined over the seam


SEAM_DASHES = 6  # dashes a seam walk must run along


SEAM_PAD = 70.0  # dashes / maps this far around the pair are used for the walk


END_CONE, END_REACH, END_DASHES, END_VIEWS = 40.0, (15.0, 50.0), 2, 8  # both ends point (user)


CLUMP_R, CLUMP_N, CLUMP_SHARE = 10.0, 4, 9.0  # dash-clump check OFF (user: 11 of 12 dropped paths were real)


ONE_END_SHARE = 0.0  # OFF (debug run: rejected 15 real paths, 0 of the wrong ones) - was 0.5


RUN_OVER = 12.0  # px: a ghost sits ON the dotted line (dashes taken for a base); a real neighbour beside it


PASS_WEAK = 0.3  # a map found by under half its shots that a strong path runs through is dropped


# never traced end to end: drawn by at least this share of the shots showing both (user)
MAX_BOW_STRONG = 0.30  # traced end to end in 2+ shots (user's clear -3961,-539 path bowed more)


MAX_BOW = 0.18  # max sideways bend / map distance (user: closer maps curve less; 99% of trusted paths <= 0.18)


S_WOBBLE_PX = 0.0  # px floor for the summed-turn S test (3 let a wrong path back; seams with straight S15 are off)


S_BOW, S_BOW_PX = 0.05, 5.0  # an S bows at least this share of its length / px to each side


S_TURN = 14.0  # deg: a path bending one way and then this much the other way is not one path


ICON_DUP = 24.0  # same badge placed a few px apart by different screenshots


SETTLE_MERGE = 90.0  # Hall / City detections this close are one building


SETTLE_BADGE = 200.0  # a Hall / City has a Deadly Map Boss badge this close (crawl: 66 of 67


# cities within 26; "Halls" with none within 350 were corruption / fog / forest)
CITY_BASE = rc_paths.ref("city_base.png")  # the brass barrel a City's map stands on


BARREL_NCC, BARREL_SAT = 0.42, 88  # fitted on 30 bases the user labelled: 17 of 18 cities, 2 of 12 halls


# map types that never share a map (user's rule): hideout, city, corruption, cleansed, hall, deadly
# map boss, breach stronghold, merchant, abyss.  Badge families of one type are listed together.
EXCLUSIVE = {
    "Hideout": "hideout",
    "Corruption": "corruption",
    "CorruptionNexus": "corruption",
    "CorruptionNexusNoGrowth": "corruption",
    "Sanctification": "cleansed",
    "SanctificationBoss": "cleansed",
    "Trader": "merchant",
    "Abyss": "abyss",
    "AbyssOverrun": "abyss",
    "AbyssalDepths": "abyss",
    "Expedition": "expedition",
}  # ocean: never a Hall / City / Tower / Hideout (user)


BARREL_BLUE = (70, 130)


BARREL_LIT = 60  # blue beam px above that make a blue-tinted barrel still count


OCEAN_R, OCEAN_WATER = 350, 0.33  # water share within 350 px: ocean (Expedition) biome. 351 crawl cities: max 0.29


SETTLE_BADGE = 110.0  # a special-boss badge this close belongs to that building


# ---------------------------------------------------------------------------------- local update
CORE_PAD = 600.0  # around the new screenshots: this area's result is replaced


CONTEXT_PAD = 700.0  # evidence margin: > the longest path (300) + parallax; tested identical to a full check
