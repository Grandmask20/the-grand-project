"""detect.constants"""

from __future__ import annotations

from pathlib import Path

from grand_project import paths as rc_paths

HERE = Path(__file__).resolve().parent


# RF-DETR: the optional detector (rf_detr_model.py), its dataset (rf_detr.py, from the annotator's export) and its
# trainer (tools/train_rf_detr.py, transformers' Trainer). The recipe follows the official roboflow/rf-detr.
RF_DETR_MODEL_NAME = "Roboflow/rf-detr-small"  # the pre-trained checkpoint fine-tuned (transformers' RfDetr port)
RF_DETR_MODEL_REVISION = "3bdc465063270f99769da5a1b4c00c68bd2d439d"  # its Hub commit (2026-05-20): a run is
# reproducible and never picks up a changed upload
RF_DETR_USE_ENV = "GRAND_PROJECT_USE_RF_DETR"  # set to 1/true/on to select the optional RF-DETR backend
RF_DETR_MODEL_ENV = "GRAND_PROJECT_RF_DETR_MODEL"  # optional model directory override for program/tests
RF_DETR_DEVICE_ENV = "GRAND_PROJECT_RF_DETR_DEVICE"  # optional torch device override, e.g. cpu or cuda
# set by tools.train_rf_detr when it restarts itself with the pip CUDA libraries first on LD_LIBRARY_PATH (the
# dynamic linker reads it only at process start), so it restarts at most once
RF_DETR_CUDA_REEXEC_ENV = "GRAND_PROJECT_RF_DETR_CUDA_REEXEC"
RF_DETR_CUDA_PATH_SEPARATOR = ":"  # LD_LIBRARY_PATH's separator (a Linux variable: never os.pathsep, which is
# ";" on Windows, where the tests fake Linux)
RF_DETR_DEFAULT_MODEL_DIR = rc_paths.ROOT / "runs" / "rf-detr-small" / "best"
RF_DETR_TRAINED_ON = "trained_on.txt"  # in a kept model's folder: the screenshots it trained on (one project-relative
# path a line), which the annotator's model pre-labels skip (they would only replay its training labels)
RF_DETR_TRAINED_ON_PARTIAL = "trained_on.partial"  # beside RF_DETR_TRAINED_ON: the list misses what an ancestor
# trained on (gone on from with --init-from, a model without its own list), so "trained on none of these" is not known
RF_DETR_RUN_SOURCES = "run_sources.txt"  # in each training checkpoint: this run's own training screenshots, which
# --resume compares (RF_DETR_TRAINED_ON there lists every screenshot the weights learned, its ancestors' too)
RF_DETR_DATASET_ID = "dataset_id.txt"  # in each training checkpoint: the SHA-256 of its dataset's metadata.json
# (manifest, ledger, kinds, limit), so --resume refuses a checkpoint of another dataset of the same screenshots
# the annotator's export (tools/detection_dataset_annotator) and the dataset loader (rf_detr.py) share these
RF_DETR_MANIFEST_FORMAT = "the-grand-project-rf-detr-manifest"  # the manifest's "format"; other files are refused
RF_DETR_SPLITS = ("train", "validation", "test")  # a screenshot's split (the Hugging Face split names)
RF_DETR_TRUTH_SEEDED_SOURCE = "annotator_truth_seeded"  # source_type of an unreviewed screenshot a biome truth
# seeded, taken only with --truth-seeded (a bootstrap round)
RF_DETR_SCORE_THRESHOLD = 0.35  # family score (the sum of a family's class scores) a detection needs; a starting
# point, to be set from a trained checkpoint's validation precision / recall
RF_DETR_MAP_BOX_SHRINK = 0.9  # factor: user's rule, the map node box is 10% smaller per side than first set
# (reviewers found it too large); only map nodes: every other box keeps its size
RF_DETR_MAP_BOX = 43.0 * RF_DETR_MAP_BOX_SHRINK  # px: square around a map node's centre: the 1080p map-base glow
# measured 48, which reviewers found too large; 43 is 20% less area (48 * sqrt(0.8)), then shrunk as above
RF_DETR_ICON_BOX = 34.0  # px: square around an icon centre, inside the standard icon rim
RF_DETR_LANDMARK_BOX = 80.0  # px: square around a citadel: the city's map node and its brass barrel
RF_DETR_TOWER_WIDTH = 80.0  # px: tower box width around its map node
RF_DETR_TOWER_HEIGHT = 220.0  # px: tower box extends upward from its map node to the spire
RF_DETR_TOWER_NODE_REACH = 55.0  # px: a tower box's base and the map node it stands on are at most this far apart
RF_DETR_STRONGHOLD_BOX = 150.0  # px: square around a Breach stronghold structure
RF_DETR_BUTTON_BOX = (68.0, 66.0)  # px: width, height of a square reveal button's frame (references/lock_icon.png,
# the frame cities.square_buttons matches at 1080p)
RF_DETR_PATH_PAD = 8.0  # px: padding around a traced path centre line
RF_DETR_WALL_MIN_AREA = 12000  # px²: ignore tiny connected components in optional painted wall masks

# RF-DETR input: native-scale tiles. Every screenshot is first read as the classical detector reads it (1440p and
# 4K windows scaled to 1080p, core.scale_screenshot), then cut into square tiles the model sees at their own size:
# map nodes (39 px) and icons (34 px) keep their size, where squashing a whole 1920x1080 screenshot into the
# checkpoint's 512x512 shrank them to ~10x18 px (the paper: input resolution drives small-object accuracy).
RF_DETR_TILE = 768  # px: tile side, one of the paper's training resolutions (a multiple of patch 16 x 2 windows)
RF_DETR_TILE_OVERLAP = 224  # px: tiles overlap at least the tallest box (a tower, 220 px), so every object lies
# whole in some tile: 8 tiles for a 1080p screenshot, ~36 objects each (a whole screenshot holds up to 275)
RF_DETR_TILE_EDGE = 2.0  # px: a predicted box this close to an inner tile edge is cut by it; another tile holds it
RF_DETR_HUD_FILL = (114, 114, 114)  # BGR: the game HUD is painted over with this grey in training and inference, so
# its round buttons never look like map icons and objects half under it are not half labelled (HUD never labelled)

# RF-DETR training augmentation. The paper keeps only horizontal flips and crops and warns that augmentations bias
# a detector toward images that never occur. The atlas has a fixed camera: citadels always face the same way and
# icons are never mirrored, so a mirrored screenshot never occurs and flips are off.
RF_DETR_AUGMENT_FLIP_PROBABILITY = 0.0  # chance: off, see above (kept as a setting for experiments)
RF_DETR_AUGMENT_CROP_MIN_VISIBILITY = 0.5  # fraction: keep a clipped box only when at least half remains visible
RF_DETR_AUGMENT_CROP_ATTEMPTS = 10  # attempts: find a tile holding at least one labelled object
RF_DETR_AUGMENT_SCALE_JITTER = 0.10  # fraction: tiles cut 10% larger or smaller and resized to RF_DETR_TILE
RF_DETR_AUGMENT_RENDER_PROBABILITY = 0.3  # chance: blur a tile as a lower in-game render scale draws it
RF_DETR_AUGMENT_RENDER_SCALE = (0.33, 1.0)  # factor: shrink and re-enlarge range, the res_atlases' 33-100% render
# scales (they change map nodes, terrain and paths; icons are UI and stay sharp, so this is an approximation)
# Brightness and contrast as the reference's small-dataset preset (AUG_CONSERVATIVE, under 500 images): players'
# in-game gamma and brightness differ; the hue is never changed, it tells the biome
RF_DETR_AUGMENT_PHOTO_PROBABILITY = 0.3  # chance: change a tile's brightness and contrast
RF_DETR_AUGMENT_BRIGHTNESS = 0.1  # fraction of 255: brightness shifted by up to this much
RF_DETR_AUGMENT_CONTRAST = 0.1  # fraction: contrast scaled by up to 1 +- this
RF_DETR_AUGMENT_RARE_PROBABILITY = 0.5  # chance: centre a training tile on a rare class's object (repeat factor > 1)
RF_DETR_TILES_PER_IMAGE = 4  # training tiles cut from each screenshot per epoch (more for rare classes, below)
RF_DETR_REPEAT_THRESHOLD = 0.1  # LVIS repeat-factor sampling: a class on fewer than this share of the training
# screenshots repeats them max(1, sqrt(threshold / share)) times (reveal buttons: on about 1 screenshot in 10)

# RF-DETR inference: classes of one family (a map node is one of the 8 node classes) are scored together, so a node
# unsure between two biomes is still found once: its family score is the sum of its classes' scores, its class
# the best of them, and duplicates are suppressed within the family (across tiles too).
RF_DETR_FAMILY_NMS_IOU = 0.50  # overlap: one object predicted twice within a family (two tiles, two classes)
RF_DETR_INFER_BATCH = 8  # tiles per forward pass (a 1080p screenshot has 8)
RF_DETR_DATASET_WRITE_BATCH = 32  # screenshots a dataset build holds in memory before writing them (~3 MB each)
RF_DETR_BOSS_ROW = (10.0, 45.0)  # px: a deadly-boss icon's map node is this far below it (the row is ROW_DY = 24
# above the map; the res atlases' larger icons sat 26-36 above it)
RF_DETR_BOSS_DX = 30.0  # px: and at most this far left or right of it (the icon is the middle one of its row)

# RF-DETR fine-tuning recipe: the paper's Appendix A as the official roboflow/rf-detr trains it (TrainConfig,
# training/param_groups.py, models/backbone/backbone.py): AdamW, the DINOv2 backbone at its own rate decayed per
# layer from the top (earlier layers keep more of their pre-training) and per component, an exponential moving
# average of the weights (EMA, the weights evaluated and kept), no warm-up and a constant rate (the paper: cosine
# schedules assume a known horizon), gradient clipping 0.1; the best checkpoint by the validation's task metrics
# (rf_detr_eval), not its loss.
RF_DETR_LEARNING_RATE = 1e-4  # everything outside the backbone and the decoder (projector, heads, queries)
RF_DETR_LR_ENCODER = 1.5e-4  # the backbone's base rate (reference lr_encoder), before the decays below
RF_DETR_LAYER_DECAY = 0.8  # factor per backbone layer from the top (rf_detr_tiles.layer_lr_scale; reference
# lr_vit_layer_decay): the top layer gets 0.8^2, the embeddings 0.8^14, the final layer norm 1
RF_DETR_COMPONENT_DECAY = 0.7  # reference lr_component_decay: the decoder learns at 0.7x, the backbone at 0.7^2 x
RF_DETR_WEIGHT_DECAY = 1e-4  # AdamW; none on biases, norms, embeddings and layer scales
RF_DETR_EMA_DECAY = 0.993  # per optimizer step (reference default): weights averaged over the last ~140 steps
RF_DETR_EMA_TAU = 100.0  # optimizer steps: the EMA's decay warms up as decay * (1 - exp(-step / tau)), so early
# averages are not stuck near the starting weights (a smoke run of 12 steps scored as if untrained without it)
RF_DETR_GRAD_CLIP = 0.1  # max gradient norm
RF_DETR_BATCH = 4  # tiles per batch; with RF_DETR_GRAD_ACCUM, 16 per optimizer step (the reference's effective batch)
RF_DETR_GRAD_ACCUM = 4  # batches per optimizer step
RF_DETR_PATIENCE = 8  # epochs without a better validation score before training stops
RF_DETR_EARLY_STOP_DELTA = 0.001  # mean AP: a smaller gain is no better score (reference early_stopping_min_delta)
# RF-DETR evaluation (rf_detr_eval): a prediction matches a box of its family whose middle is this close, px, as
# python -m grand_project.detect score matches (truth.py: MAP_R 20 for maps, BADGE_R 14 for icons, LM_R 90 for
# landmarks); tests/rf_detr/test_eval.py keeps them equal.
RF_DETR_EVAL_RADIUS = {
    "node": 20.0,
    "icon": 14.0,
    "button": 14.0,  # as icons: a reveal button's middle is as exact as an icon's (and under RF_DETR_BUTTON_SHIFT)
    "citadel": 90.0,
    "hall": 90.0,
    "tower": 90.0,
    "stronghold": 90.0,
    "path": 90.0,
    "wall": 90.0,
}

# ---- RF-DETR labels: the one registry (detect/labels.py reads it) ----------------------------------------------
# Every dataset label the annotator offers, the exporter numbers and the RF-DETR detector maps back, in export order.
# APPEND NEW LABELS AT THE END (as ICON_INFO): ids are positions, and although everything matches classes by name
# (checkpoints keep their own label map; --init-from copies class rows by name), a stable order keeps exports easy
# to compare. Icon types are not listed here: the store keeps icon_<type> labels (ICON_INFO), and the detector
# finds every one as the one `icon` class below (export_class), named by the classical namer
# (badges.name_found_icons), as the classical finder's icons are (AGENTS.md: icons, finding vs naming).
# Fields: title (shown in the editor), family (classes of one object that compete at inference: a map node is one
# of the node classes), rule (the box rule shown to the reviewer), color (BGR), key (editor hotkey: "1" or
# "shift+1"), picture (an ICON_INFO type or a references/ file), biome / city_type (what a node or citadel class
# says), landmark (the classical landmark kind it becomes), parent (the class a new class's head row starts from
# when a checkpoint is fine-tuned with --init-from), optional (derived labels, exported only when used).
_NODE_RULE = "Map node box ({:.1f} px) centred on the map node."
RF_DETR_LABEL_INFO = {
    "map_node": {
        "title": "Map node, its ground not visible",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " Only when fog, the screen edge or the HUD hides the ground "
        "around it, or the ground can't be told.",
        "color": (255, 100, 80),
        "key": "1",
        "picture": "map_node_icon.webp",
    },
    "map_node_grass": {
        "title": "Map node on green ground (grass, swamp, forest)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The ground around it (about the Fix-seams disc, 38 px) is "
        "mostly green: grass, swamp or forest.",
        "color": (70, 200, 70),
        "key": "2",
        "picture": "map_node_icon.webp",
        "biome": "grass",
        "parent": "map_node",
    },
    "map_node_desert": {
        "title": "Map node on sand (desert)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The ground around it is mostly sand.",
        "color": (90, 215, 245),
        "key": "3",
        "picture": "map_node_icon.webp",
        "biome": "desert",
        "parent": "map_node",
    },
    "map_node_water": {
        "title": "Map node in water or the ocean",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The map lies in water or the ocean (Expedition) biome, "
        "islands included.",
        "color": (240, 170, 40),
        "key": "4",
        "picture": "map_node_icon.webp",
        "biome": "water",
        "parent": "map_node",
    },
    "map_node_mountain": {
        "title": "Map node on white rock or snow (mountain)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The ground around it is mostly white rock or snow (not the "
        "white Delirium mist over other ground).",
        "color": (245, 245, 245),
        "key": "5",
        "picture": "map_node_icon.webp",
        "biome": "mountain",
        "parent": "map_node",
    },
    "map_node_ezomyte": {
        "title": "Map node in an Ezomyte city's area (Iron Citadel)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The map lies in an Ezomyte city's area (the farmland "
        "around an Iron Citadel), the citadel's own map included.",
        "color": (160, 235, 160),
        "key": "6",
        "picture": "map_node_icon.webp",
        "city_type": "Ezomyte",
        "parent": "map_node",
    },
    "map_node_vaal": {
        "title": "Map node in a Vaal city's area (Stone Citadel)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The map lies in a Vaal city's area (the farmland around a "
        "Stone Citadel), the citadel's own map included.",
        "color": (150, 140, 250),
        "key": "7",
        "picture": "map_node_icon.webp",
        "city_type": "Vaal",
        "parent": "map_node",
    },
    "map_node_faridun": {
        "title": "Map node in a Faridun city's area (Copper Citadel)",
        "family": "node",
        "rule": _NODE_RULE.format(RF_DETR_MAP_BOX) + " The map lies in a Faridun city's area (the desert around a "
        "Copper Citadel), the citadel's own map included.",
        "color": (150, 200, 235),
        "key": "8",
        "picture": "map_node_icon.webp",
        "city_type": "Faridun",
        "parent": "map_node",
    },
    "citadel_iron": {
        "title": "Iron Citadel: an Ezomyte city's own map",
        "family": "citadel",
        "rule": f"{RF_DETR_LANDMARK_BOX:.0f} px box centred on the city's own map node, framing the node and its "
        "brass barrel. The node keeps its own node box, the red deadly-boss icon its icon box.",
        "color": (200, 170, 130),
        "key": "shift+1",
        "city_type": "Ezomyte",
        "landmark": "City",
    },
    "citadel_stone": {
        "title": "Stone Citadel: a Vaal city's own map",
        "family": "citadel",
        "rule": f"{RF_DETR_LANDMARK_BOX:.0f} px box centred on the city's own map node, framing the node and its "
        "brass barrel. The node keeps its own node box, the red deadly-boss icon its icon box.",
        "color": (60, 90, 235),
        "key": "shift+2",
        "city_type": "Vaal",
        "landmark": "City",
    },
    "citadel_copper": {
        "title": "Copper Citadel: a Faridun city's own map",
        "family": "citadel",
        "rule": f"{RF_DETR_LANDMARK_BOX:.0f} px box centred on the city's own map node, framing the node and its "
        "brass barrel. The node keeps its own node box, the red deadly-boss icon its icon box.",
        "color": (50, 120, 210),
        "key": "shift+3",
        "city_type": "Faridun",
        "landmark": "City",
    },
    "hall": {
        "title": "Hall: its map node and the whole hall structure",
        "family": "hall",
        "rule": "The hall's map node and the whole hall structure beside it: the building the orange beam rises "
        "from, not the beam above it. The red deadly-boss icon keeps its icon box.",
        "color": (190, 120, 255),
        "key": "9",
        "landmark": "Hall",
    },
    "tower": {
        "title": "Tower",
        "family": "tower",
        "rule": f"{RF_DETR_TOWER_WIDTH:.0f} px wide, standing on its map node (the box's bottom edge) up to the top "
        "of the spire.",
        "color": (80, 190, 255),
        "key": "0",
        "picture": "LostTower",  # the Lost Tower icon's game art, as a picture only (the icon is no label)
        "landmark": "Tower",
    },
    "breach_stronghold": {
        "title": "Breach stronghold (locked or open)",
        "family": "stronghold",
        "rule": f"{RF_DETR_STRONGHOLD_BOX:.0f} px box centred on the purple Breach stronghold structure, locked or "
        "open (the hand reveal button beside a locked one says it is locked: reveal_button).",
        "color": (80, 220, 220),
        "key": "shift+4",
        "landmark": "Breach stronghold",
    },
    "reveal_button": {
        "title": "Reveal button (square framed: a locked stronghold's hand, the Expedition ship ...)",
        "family": "button",
        "rule": f"{RF_DETR_BUTTON_BOX[0]:.0f} x {RF_DETR_BUTTON_BOX[1]:.0f} px box on the square framed button that "
        "reveals maps when clicked (a locked Breach stronghold's hand, the Expedition ship, ...); its kind is named "
        "by the symbol inside.",
        "color": (220, 100, 180),
        "key": "shift+5",
        "picture": "lock_icon.png",
    },
    "icon": {
        "title": "Map icon, the deadly-boss icon included (its type is named by the icon pictures)",
        "family": "icon",
        "rule": f"{RF_DETR_ICON_BOX:.0f} px box centred on a round map icon (not the square Expedition ship button).",
        "color": (130, 180, 255),
        "key": "shift+6",
    },
    "path": {
        "title": "Traced path with its dashes",
        "family": "path",
        "rule": f"Box around a traced path's centre line, {RF_DETR_PATH_PAD:.0f} px padding.",
        "color": (60, 230, 255),
        "key": "shift+7",
        "optional": True,
    },
    "fortress_wall": {
        "title": "Fortress wall region",
        "family": "wall",
        "rule": "Box around one connected fortress-wall region.",
        "color": (170, 170, 170),
        "key": "shift+8",
        "optional": True,
    },
}
RF_DETR_ICON_EXCLUDED = frozenset({"LostTower", "Checkpoint", "ExpeditionShip"})  # icon types that are no icon
# labels: the annotator never boxes them as icons, exports leave them out, and the RF-DETR detector does not report
# them as icons. Lost Tower and Checkpoint are no labels at all (user); the Expedition ship is a reveal button
# (reveal_button, named by its symbol: RF_DETR_BUTTON_ICONS), not a round icon.
RF_DETR_BUTTON_ICONS = {"ship": "ExpeditionShip"}  # a reveal button's kind (cities.name_button) -> the icon the
# program reports for it, as landmarks.ship_markers does; a "lock" button makes its Breach stronghold locked
# (landmarks.stronghold_kind), an "unknown" one (a symbol not taught yet) is not reported, as in the classical detector
RF_DETR_BUTTON_SHIFT = 16  # px: how far around an RF-DETR reveal button's middle its symbol is searched (measured on
# the 195 buttons of the 1,423 dataset screenshots: every one named right up to 16 px off, none as another kind;
# 2 of 4,752 random spots reached the symbol threshold)
# Box sources of first guesses (the annotator draws guessed boxes dotted, for the reviewer to check first)
RF_DETR_SOURCE_CLASSICAL = "classical"  # a classical detector result taken as it is
RF_DETR_SOURCE_CITY_GUESS = "city_guess"  # a citadel whose type is an unsure look-alike guess (CITY_LOOK_SURE)
# Look-alike distance margin (second-best type minus best) from which one screenshot's city type guess counts as sure
# (cities.screenshot_city_types): leave-one-out over the 173 looks in city_refs.npz was 95% right overall (mostly
# Ezomyte <-> Vaal mix-ups) and 100% right (124 of 173) at a margin of 0.1 or more.
CITY_LOOK_SURE = 0.10
RF_DETR_SOURCE_BIOME_GUESS = "biome_guess"  # a node whose biome the ground ring could not tell surely
RF_DETR_SOURCE_CITY_AREA_GUESS = "city_area_guess"  # a node in a city's area (one screenshot may cut the area off)
RF_DETR_SOURCE_MODEL = "rf_detr"  # a box an RF-DETR model's pre-labels agree on with the classical detector
RF_DETR_SOURCE_MODEL_GUESS = "rf_detr_guess"  # a box only the model proposes, or a class it changed: check it first
RF_DETR_GUESS_SOURCES = frozenset(
    {RF_DETR_SOURCE_CITY_GUESS, RF_DETR_SOURCE_BIOME_GUESS, RF_DETR_SOURCE_CITY_AREA_GUESS, RF_DETR_SOURCE_MODEL_GUESS}
)


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
STRONGHOLD_LOCK_REACH = 200  # px: a Breach stronghold with a hand (lock) reveal button this close is locked


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


# a map node's biome from the ground around it (detect/biomes.py: the first guess of the map_node_<biome> classes).
# The ring is the PM's idea: the disc Fix seams protects around a map node minus the node itself. Its outer radius
# is core.constants.SEAM_NODE_R (38 atlas units, about 38 px of a 1080p screenshot); tune both with
# `python -m tools.detection_dataset_annotator.score_nodes` on reviewed screenshots.
BIOME_RING = (RF_DETR_MAP_BOX / 2, 38.0)  # px: inner radius (the map node's box) and outer radius of the ring
BIOME_MIN_PIXELS = 300  # ring pixels with a ground class needed for any guess (the whole ring holds ~3,400)
BIOME_SURE_SHARE = 0.55  # share of the classified ring the leading biome needs for a sure guess
BIOME_SURE_MARGIN = 0.25  # lead of the leading biome's share over the second one's for a sure guess
# finalize.landmarks._ground_classes (0 water, 1 sand, 2 rock / snow, 3 grass, 4 forest) -> biome. The PM's groups:
# green = grass, swamp, forest; sand = desert; blue = ocean, water; white = mountain.
BIOME_GROUND = {0: "water", 1: "desert", 2: "mountain", 3: "grass", 4: "grass"}
BIOME_MIST_ICONS = frozenset({"Delirium"})  # icons whose white mist covers the ground around their map: white
# there is the mist, not mountain (PM: mountain and Delirium both look white), so the guess leaves it out and is unsure
BIOME_MIST_REACH = 150.0  # px: the mist spreads over the maps around a Delirium map too (roa-atlas: clouds reach
# ~100-150 px from the misted maps), so maps this close to one are treated as misted as well
BIOME_ICON_PAD = 2.0  # px around an icon's box also left out of the ring (the rim's glow)


# the hall box: the hall's map node and the whole hall structure beside it (user). Measured on 6 roa-atlas halls:
# the structure (the scaffold its orange beam rises from) stands up-left of the map node, the beam ~50 px left of
# the node; the scaffold reaches from ~100 px above to ~25 px below the node, ~105 px wide around the beam.
RF_DETR_HALL_STRUCTURE_BOX = (110.0, 125.0)  # px: width and height of the structure, centred on its beam column
RF_DETR_HALL_STRUCTURE_DY = -38.0  # px: the structure box's middle above (-) the hall's map node
RF_DETR_HALL_STRUCTURE_DX = -50.0  # px: the beam column left (-) of the node when no beam is seen (left on all 6)
RF_DETR_HALL_BEAM_SPREAD = 80  # px: how far left / right of the node the beam column is looked for (as deadly_kind)
RF_DETR_HALL_BEAM_MIN = 350  # orange beam pixels from which the beam column places the structure (HALL_ORANGE / 2)


# map node states (detect/node_states.py), named like icons: RF-DETR or the map finder finds the map node, the nearest
# stored picture of its middle names the state, so new pictures never change what is found (finding vs naming)
NODE_STATES = ("grey", "blue", "green", "red")  # unreachable, can be pathed to, cleared, failed (cities and halls)
NODE_STATES_FILE = rc_paths.ref("node_states.npz")  # the pictures (tools/node_state_sheet.py freeze)
NODE_STATE_MAX_DIST = 0.40  # 1 - correlation to the nearest picture; further away the state is unsure (None)
# a map node may only take a state one of whose pictures has a brightest quarter this close in colour (Lab a/b units,
# icon_refs.bright_colour): blue glows at about (-5, -18), green at (-38, +38), grey near (0, 0)
NODE_STATE_COLOUR_TOL = 12.0
# ... and glows as much: the share of the pixels within NODE_STATE_GLOW_R px of the middle in each glow's colour band
# (OpenCV HSV: hue ranges, min saturation, min value). The pattern match removes a crop's average colour, so a
# grey map node in another light matched blue pictures; on the map_state_change screenshots (each folder named by
# the other two's pictures) this check took grey-called-blue from 4 to 1 of 1,238, NODE_STATE_GLOW_TOL 0.04-0.08
# all alike, 0.12 worse. Blue map nodes there had a blue share of 0.18-0.41 (5-95%), grey ones mostly 0
NODE_STATE_GLOW_R = 10
NODE_STATE_GLOW_BANDS = {
    "blue": (((95, 130),), 60, 110),
    "green": (((40, 85),), 90, 90),
    "red": (((0, 8), (172, 180)), 120, 90),
}
NODE_STATE_GLOW_TOL = 0.08  # largest difference in any glow's share to the nearest picture of the state
NODE_STATE_PICTURES = 100  # pictures kept per state when freezing: states weigh alike, naming stays quick
NODE_STATE_TRUTH = "states.json"  # hand-checked states next to a folder's screenshots (tools/node_state_sheet.py)
# the folders the pictures come from; never TRUTH_SETS' screenshots, which score the namer (python -m
# grand_project.detect score) and so must stay unseen
NODE_STATE_SETS = [TESTS / "map_state_change" / part for part in ("pre-change", "post-change", "single-map")]


# the icon finder's rim template (the average icon as seen on screen, from the hand labels), so teaching new icon
# pictures (naming) never changes which icons are found: tools/freeze_badge_finder.py
BADGE_FINDER_FILE = rc_paths.ref("badge_finder.npz")


# ---------------------------------------------------------------- icon types
# Every icon type the program knows: game icon -> (poe2db name, BGR colour, other names it can be searched by).
# Names follow poe2db.tw Waystones > Map Legends / Map Content (https://poe2db.tw/us/Waystones#MapContent); the
# viewer shows them, the dataset annotator offers each type as a label (icon_<name>, with its picture from
# ICON_ART_DIR; exported as the one `icon` class) and the classical naming step names the RF-DETR detector's icons
# with them (badges.name_found_icons). The annotator lists the icon labels in this order, so add new types at the
# end.
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

DETECT_DIGEST_MEMO = 20000  # screenshot hashes kept in memory (builder.file_digest), then forgotten
# bytes read from the start of a saved detection to tell its detector, version and time (builder.cache_head): those
# fields come first (name, path, sha256, detector, models, version, detected_at: ~400 bytes with a long path)
CACHE_HEAD_BYTES = 2048

# ---- detection speed (pipeline._prefetch, cache._per_image) --------------------------------------------------------
DETECT_PER_IMAGE_KEEP = 16  # results remembered per screenshot function (cache._per_image): a detection's own
# (dashes, amber dashes, walls, special icons, the landmark rules, square buttons) for the last two screenshots
DETECT_PREFETCH_THREADS = (
    3  # threads that work out a screenshot's image-only stages (dashes, special icons, the landmark
)
# rules, fortress walls, square buttons) while the detection finds its maps: they are mostly OpenCV, which runs
# beside Python. At most the process's own thread share less one (fileio.process_pool), so capped workers stay capped
PATH_FEATURE_REACH = 49.0  # px: dashes looked up around a spot for paths.path_features (its rings end at 48 px; the
# extra px keeps a dash at 47.99... that the lookup rounds the other way)
