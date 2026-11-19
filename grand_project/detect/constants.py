"""detect.constants"""

from __future__ import annotations

from pathlib import Path

from grand_project import paths as rc_paths

HERE = Path(__file__).resolve().parent


# RF-DETR training data settings. Coordinates in detector truth are measured at the detector's 1080p height;
# the dataset builder scales these boxes back to the source image before Hugging Face stores the image.
RF_DETR_MODEL_NAME = "Roboflow/rf-detr-small"
RF_DETR_USE_ENV = "GRAND_PROJECT_USE_RF_DETR"  # set to 1/true/on to select the optional RF-DETR backend
RF_DETR_MODEL_ENV = "GRAND_PROJECT_RF_DETR_MODEL"  # optional model directory override for program/tests
RF_DETR_DEVICE_ENV = "GRAND_PROJECT_RF_DETR_DEVICE"  # optional torch device override, e.g. cpu or cuda
# set by tools.train_rf_detr when it restarts itself with the pip CUDA libraries first on LD_LIBRARY_PATH (the
# dynamic linker reads it only at process start), so it restarts at most once
RF_DETR_CUDA_REEXEC_ENV = "GRAND_PROJECT_RF_DETR_CUDA_REEXEC"
RF_DETR_DEFAULT_MODEL_DIR = rc_paths.ROOT / "runs" / "rf-detr-small" / "best"
RF_DETR_SCORE_THRESHOLD = 0.35  # confidence: tuned as a safe starting point for the small fine-tuned checkpoint
RF_DETR_NMS_IOU = 0.50  # overlap: remove duplicate predictions of the same RF-DETR class
RF_DETR_MAX_TARGETS = 300  # objects/image: RF-DETR Small's default decoder query count; path dashes can exceed it
RF_DETR_MAP_BOX_SHRINK = 0.9  # factor: user's rule, the map node box is 10% smaller per side than first set
# (reviewers found it too large); only map nodes: every other box keeps its size
RF_DETR_MAP_BOX = 43.0 * RF_DETR_MAP_BOX_SHRINK  # px: square around a map node's centre: the 1080p map-base glow
# measured 48, which reviewers found too large; 43 is 20% less area (48 * sqrt(0.8)), then shrunk as above
RF_DETR_ICON_BOX = 34.0  # px: square around an icon centre, inside the standard icon rim
RF_DETR_LANDMARK_BOX = 80.0  # px: square around a city / hall / deadly-boss map point
RF_DETR_TOWER_WIDTH = 80.0  # px: tower box width around its map node
RF_DETR_TOWER_HEIGHT = 220.0  # px: tower box extends upward from its map node to the spire
RF_DETR_TOWER_NODE_REACH = 55.0  # px: a tower box's base and the map node it stands on are at most this far apart
RF_DETR_STRONGHOLD_BOX = 150.0  # px: square around a Breach stronghold structure
RF_DETR_PATH_PAD = 8.0  # px: padding around a traced path centre line
RF_DETR_PATH_DASH_BOX = 18.0  # px: square around one path dash for the low-level path detector
RF_DETR_WALL_MIN_AREA = 12000  # px²: ignore tiny connected components in optional painted wall masks
RF_DETR_SOFT_FLAGS = frozenset({"ui", "offcenter"})  # ambiguous hand labels are excluded unless requested

# RF-DETR training augmentation. These conservative values are for the 1920x1080 atlas screenshots: horizontal
# mirroring is valid for the atlas, while crops are kept large enough that sparse landmarks remain visible.
RF_DETR_AUGMENT_FLIP_PROBABILITY = 0.5  # chance: the paper recommends horizontal flips for target-domain transfer
RF_DETR_AUGMENT_CROP_PROBABILITY = 0.5  # chance: apply a random crop before the processor's resize/padding
RF_DETR_AUGMENT_CROP_MIN_SCALE = 0.75  # fraction: smallest crop side, tuned to retain most map nodes in a view
RF_DETR_AUGMENT_CROP_MIN_VISIBILITY = 0.5  # fraction: keep a clipped box only when at least half remains visible
RF_DETR_AUGMENT_CROP_ATTEMPTS = 10  # attempts: find a crop retaining at least one labelled object

# Stable classes shared by every generated dataset. Icon names are appended as icon_<slug> classes when naming is
# enabled; keeping these first means adding a new icon does not renumber the detector's core tasks.
# City type (cities.TYPES) -> its RF-DETR class: cities are always labelled by type (user's rule), so a model can tell
# Ezomyte, Vaal and Faridun cities apart. Older checkpoints with one plain "city" class still load (rf_detr_model).
RF_DETR_CITY_LABELS = {"Ezomyte": "city_ezomyte", "Vaal": "city_vaal", "Faridun": "city_faridun"}
# RF-DETR landmark class -> the classical detector's landmark kind (towers are handled apart: their box stands on
# the map node). "city" is the untyped class of older checkpoints; a typed city class also gives the City its
# city_type (rf_detr_model).
RF_DETR_LANDMARK_KINDS = {
    "city": "City",
    **{label: "City" for label in RF_DETR_CITY_LABELS.values()},
    "hall": "Hall",
    "deadly_boss_map": "Deadly boss map",
    "breach_stronghold": "Breach stronghold",
    "locked_stronghold": "Locked stronghold",
}
RF_DETR_CORE_LABELS = (
    "map_node",
    "tower",
    *RF_DETR_CITY_LABELS.values(),
    "hall",
    "deadly_boss_map",
    "breach_stronghold",
    "locked_stronghold",
    "icon",
)  # sparse objects only: paths and fortress walls are derived by the established detector


DETECTOR_ID = "detect1"  # in builder cache file names: results of another detector are never reused


TESTS = rc_paths.TEST_DATA


TRUTH = TESTS / "truth" / "truth.json"


SHOTS = rc_paths.SCREENSHOTS / "random_samples"


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
# training (citytrain.py, part of `python -m grand_project.detect train`): folders with screenshots + cities_truth.json
CITY_TRUTH_SETS = [SHOTS, rc_paths.SCREENSHOTS / "cities"]  # 10 hand-labelled + 31 city screenshots (78 cities)
CITY_TRAIN_SNAP = 40  # px: a truth point belongs to the nearest detected map node this close
CITY_TRAIN_C = 0.05  # logistic regularisation: few cities, many features
# robustness report only (training on them made the model worse): ordinary map nodes looked at a few px off
CITY_OFF_SHIFTS = [(0, -8), (0, -5), (0, 5), (0, 8), (-6, 0), (6, 0)]


# the icon finder's rim template (the average icon as seen on screen, from the hand labels), so teaching new icon
# pictures (naming) never changes which icons are found: tools/freeze_badge_finder.py
BADGE_FINDER_FILE = rc_paths.ref("badge_finder.npz")


# ---------------------------------------------------------------- icon types
# Every icon type the program knows: game icon -> (poe2db name, BGR colour, other names it can be searched by).
# Names follow poe2db.tw Waystones > Map Legends / Map Content (https://poe2db.tw/us/Waystones#MapContent); the
# viewer shows them, the dataset annotator offers each type as a label (icon_<name>, with its picture from
# ICON_ART_DIR) and the RF-DETR detector turns its classes back into these names. The annotator numbers the icon
# classes in this order, so add new types at the end.
ICON_INFO = {
    "MapBoss": ("Powerful Map Boss", (70, 120, 255), "map boss, defeat the map boss"),
    "MapBossSpecial": ("Deadly Map Boss", (50, 50, 255), "special boss, hall boss, city boss"),
    "UniqueMap": ("Unique Map", (0, 190, 255), ""),
    "Abyss": ("Abyss", (90, 230, 60), "complete all abysses, abyssal fissure"),
    "AbyssOverrun": ("Overrun by the Abyssal", (40, 190, 40), "abyss overrun, many extra abysses"),
    "AbyssalDepths": ("Abyssal Depths", (40, 160, 40), "complete the abyssal depths"),
    "AzmeriSpirit": ("Spirit Guide", (255, 200, 90), "azmeri spirit, complete all azmeri spirits, viridian wildwood"),
    "Delirium": ("Delirium", (225, 225, 225), "delirium mirror, simulacrum"),
    "Breach": ("Breach", (235, 90, 220), "unstable breaches, breach hive"),
    "Expedition": ("Expedition", (90, 200, 255), "kalguuran expedition"),
    "ExpeditionRemnant": ("Verisium Remnants", (90, 200, 255), "collect the verisium remnants"),
    "Ritual": ("Ritual", (60, 60, 200), "ritual altars"),
    "Essence": ("Essence Trove", (200, 120, 255), "essence, free all essence monsters"),
    "Irradiated": ("Irradiated", (60, 255, 200), "+1 monster level"),
    "StrongBox": ("Monstrous Treasure", (80, 170, 230), "strongbox, open all strongboxes"),
    "Incursion": ("Vaal Beacons", (120, 160, 120), "incursion, energise the vaal beacons"),
    "Shrine": ("Shrines", (200, 200, 120), "activate all shrines"),
    "RogueExile": ("Rogue Exiles", (60, 60, 230), "defeat all rogue exiles"),
    "RareMonster": ("Rare Monsters", (40, 200, 230), "defeat all rare monsters"),
    "Checkpoint": ("Checkpoints", (200, 200, 200), "activate all checkpoints"),
    "StoneCircle": ("Summoning Circles", (150, 150, 200), "stone circle, complete all summoning circles"),
    "Corruption": ("Corruption", (130, 40, 160), ""),
    "CorruptionNexus": ("Corrupted Boss", (160, 40, 200), "defeat the corrupted boss, corrupted nexus"),
    "CorruptionNexusNoGrowth": ("Corrupted Nexus", (160, 60, 200), ""),
    "Sanctification": ("Cleansed", (220, 240, 255), "sanctification"),
    "SanctificationBoss": ("Immured Fury", (200, 220, 255), "doryani"),
    "Trader": ("Wandering Trader", (120, 220, 255), "trader"),
    "NamelessSeer": ("Nameless Seer", (200, 140, 255), "seer"),
    "Hideout": ("Hideout", (200, 255, 200), "felled hideout"),
    "HideoutRed": (
        "Player Hideout",
        (230, 90, 90),
        "player hideout, player hideout modifier, red hideout, red fleur-de-lis (user: kept apart from Hideout)",
    ),
    "LostTower": ("Precursor Tower", (100, 235, 100), "lost tower, tower"),
    "Unidentified": ("Unidentified badge", (160, 160, 160), "unknown"),
    # taught by hand on the badge sheet (atlas_icon_refs, badge_refs table in the icon database);
    # poe2db Map Content names
    "MirageOfRiches": ("Mirage of Riches", (120, 200, 220), "equipment replaced"),
    "ZealousReverence": ("Zealous Reverence", (200, 120, 160), "shrine duration"),
    "SurprisingAlliances": ("Surprising Alliances", (60, 160, 230), "rogue exiles in pairs"),
    "SpiritMigration": ("Spirit Migration", (220, 140, 255), "azmeri spirit moves"),
    "PowerOfFaith": ("Power of Faith", (60, 120, 220), "additional shrines"),
    "TwiceLockedBoxes": ("Twice-Locked Boxes", (90, 160, 210), "strongboxes openable twice"),
    "BehemothsBounty": ("Behemoth's Bounty", (230, 190, 120), "map boss drops a unique"),
    "ExceptionalFind": ("Exceptional Find", (230, 170, 90), "exceptional items"),
    "GiganticUprising": ("Gigantic Uprising", (240, 200, 110), "gigantic monsters"),
    "ScatteredStones": ("Scattered Stones", (220, 180, 100), "summoning circles"),
    "TwinnedTerrors": ("Twinned Terrors", (200, 160, 90), "summoning circles additional boss"),
    "Headhunters": ("Headhunters", (60, 80, 230), "rare monster modifiers"),
    # before ArcaneHordes / ProsperousPopulous were told apart (user): only atlases saved before show it
    "ArcaneOrProsperous": (
        "Arcane Hordes / Prosperous Populous (old)",
        (60, 100, 240),
        "arcane hordes, prosperous populous, magic monsters, rarity",
    ),
    "CorruptedMirage": ("Corrupted Mirage", (40, 70, 240), "additional waystone modifiers"),
    "GrandMirror": ("Grand Mirror", (200, 200, 200), "mirror"),
    "Simulacrum": ("Simulacrum", (230, 230, 230), "delirium manifestation"),
    "IndomitableEssence": ("Indomitable Essence", (255, 200, 150), "essence"),
    "AzmeriEnergisation": ("Azmeri Energisation", (240, 90, 220), "azmeri spirits empowerment"),
    "EchoesOfPower": ("Echoes of Power", (200, 80, 180), "rare monsters duplicated"),
    "ChaoticCacophony": ("Chaotic Cacophony", (120, 200, 120), "extra of each content"),
    "GrassInfluence": ("Grass Influence", (80, 210, 120), "grass area, biome"),
    "PowerStruggle": ("Power Struggle", (230, 80, 140), "additional map bosses"),
    "HuntingGrounds": ("Hunting Grounds", (60, 220, 60), "rogue exiles rare beasts"),
    "AzmeriChampion": ("Azmeri Champion", (255, 170, 80), "map boss is possessed"),
    "LargeCongregation": ("Large Congregation", (90, 150, 210), "shrines worshippers"),
    "AncientTrove": ("Ancient Trove", (60, 120, 200), "unique trove, unique strongbox"),
    "SacredSpirit": ("Sacred Spirit", (60, 120, 255), "azmeri sacred spirit"),
    "SwarmingSpirits": ("Swarming Spirits", (200, 160, 80), "additional azmeri spirits"),
    "AzmeriBloodline": ("Azmeri Bloodline", (80, 200, 120), "rogue exile azmeri"),
    "NatureShrines": ("Nature Shrines", (140, 200, 120), "shrines azmeri spirit"),
    "RitesOfTheRogues": ("Rites of the Rogues", (40, 150, 230), "shrines rogue exile"),
    "AffluentArmies": ("Affluent Armies", (60, 210, 230), "rarity"),
    "FragmentOfImmortality": ("Fragment of Immortality", (200, 100, 200), "unlimited revivals"),
    "PersistentDevotion": ("Persistent Devotion", (120, 180, 140), "shrine buffs"),
    "CrystalisedTwinning": ("Crystalised Twinning", (220, 120, 140), "essence packs"),
    "TightPockets": ("Tight Pockets", (200, 110, 150), "gold replaced"),
    "ForestInfluence": ("Forest Influence", (60, 160, 60), "forest area, biome"),
    "MountainInfluence": ("Mountain Influence", (190, 190, 190), "mountain area, biome"),
    # named from poe2db's Map Content art (no on-screen example taught yet, or only a few)
    "WaterInfluence": ("Water Influence", (70, 150, 230), "water area, biome"),
    "SwampInfluence": ("Swamp Influence", (110, 140, 80), "swamp area, biome"),
    "DesertInfluence": ("Desert Influence", (220, 190, 120), "desert area, biome"),
    "EnergizedLeyLines": ("Energized Ley Lines", (240, 220, 150), "doubles effect of tablets"),
    "FleeingExile": (
        "Fleeing Exile",
        (90, 130, 220),
        "rogue exile, defeat all rogue exiles (the icon the atlas shows: user)",
    ),
    "GreatBeast": ("Great Beast", (200, 150, 90), "hilda's favour"),
    "MapAreaModified": ("Map Area Modified", (170, 170, 170), "world area manipulated"),
    "NotableLocation": ("Notable Location", (230, 210, 120), "important objective"),
    "SekhemasStudent": ("Sekhema's Student", (220, 180, 90), "map boss drops a djinn barya"),
    "TrialmastersTrainee": ("Trialmaster's Trainee", (200, 120, 90), "map boss drops an inscribed ultimatum"),
    "StolenPower": ("Stolen Power", (40, 120, 255), "summoning circle bosses, power of enemy slain"),
    "GlimmeringMutation": ("Glimmering Mutation", (40, 200, 255), "currency replaced with rarer varieties"),
    "PlayerOrBookmark": ("Player / bookmark marker", (255, 255, 255), "player, bookmark, pin, ritual"),
    # poe2db Map Content types added for the dataset annotator (user: every map content icon, and every other label
    # with its own look)
    "BreachHive": ("Breach Hive", (200, 80, 230), "breach hive, complete all breach hives"),
    "WisdomsTeachings": ("Wisdom's Teachings", (230, 200, 90), "monsters grant increased experience"),
    "GrandExpedition": ("Grand Expedition", (230, 160, 60), "grand expedition, kalguuran expedition"),
    # Arcane Hordes and Prosperous Populous: the same compass art, its lower half teal (Arcane) or red (Prosperous)
    "ArcaneHordes": ("Arcane Hordes", (200, 160, 60), "all monsters are at least magic, arcane hordes"),
    "ProsperousPopulous": ("Prosperous Populous", (60, 100, 240), "increased rarity of items, prosperous populous"),
    # not poe2db: the square ship buttons of the Expedition ocean (found by their own template, ship_markers)
    "ExpeditionShip": ("Expedition ship", (200, 170, 120), "ship marker, square ship button, expedition"),
}
# old names kept only so atlases saved with them still show: never a dataset class, never given pictures
ICON_LEGACY = frozenset({"ArcaneOrProsperous"})
# names that are not an icon type: an icon found but not named
ICON_NOT_A_CLASS = frozenset({"Unidentified"})
# icon pictures, named by type: "full__<Name>.webp" (the whole icon with its rim) or "inner__<Name>.webp" (atlas-tree
# art: the picture inside the rim), from poe2db (tools/import_poe2db_art.py)
ICON_ART_DIR = rc_paths.ref("poe2db_icons")
ICON_ART_FILES = {"ExpeditionShip": "ship_button.png"}  # pictures of types that have no poe2db art (references/)
