"""One detector for atlas screenshots (replaces node_recognition + icon matcher + path finder; being built).

Stages, each scored against atlas_test_data/truth/truth.json (not shipped) with atlas_truth.score:
  1. HUD      the game's interface (hud_mask_full.png, drawn by the user) is never a map, badge or landmark
  2. maps     bright-blob candidates -> learned classifier: map (towers included) / not a map
  3. badges   gold-ring + average-badge spots -> badge classifier -> name from the badge pictures
              (badge_refs table + the labelled ones kept in the model); rows of up to 5 badges sit 24 px
              above their map, centred on it (user) -> a badge row with no map found = a hidden map
  4. landmarks Towers (classifier on found maps: the spire above them); Deadly Map Boss rows -> City (barrel
              / blue or red beam) / Hall (beam on a structure beside it) / deadly boss map; Breach
              strongholds (old purple rule), locked when a hand badge is near or no map is inside
  5. paths    amber / dim-gold / fog-orange dash mask -> dash-by-dash tracing between maps by the user's
              path rules; two dead ends meeting = a missed map; dashes around a spot are map evidence too
  6. biome    ground type per map
Modes: TRAINING fits models from the hand-labelled truth and stores them in the reference DB
(table detector_models); LIVE only reads them and never writes the DB.

    py atlas_detect.py score       stage 1 on the old detector's output, then stage 2 tested
                                   leave-one-screenshot-out (trained on 9, scored on the 10th)
    py atlas_detect.py train       training mode: fit the map + badge models on all labelled screenshots -> DB
    py atlas_detect.py run IMG...  live mode: maps per screenshot (reads the DB, never writes it)
"""

from .annotate import (  # noqa: F401
    LM_STYLE,
    PATH_DRAW_SHIFT,
    annotate,
    cmd_show,
)
from .badges import (  # noqa: F401
    _K_IN,
    _K_OUT,
    _K_RIM,
    _badge_tpl,
    _best_ref_corr,
    _ring_kernel,
    _row_slot,
    _template,
    badge_book,
    badge_candidates,
    badge_features,
    badge_labels,
    badge_rows,
    badges_from,
    find_badges,
    name_badge,
)
from .cache import (  # noqa: F401
    _PER_IMAGE,
    _per_image,
)
from .constants import (  # noqa: F401
    BADGE_MIN,
    BADGE_NMS,
    BADGE_ROW_MIN,
    BLOB_MIN,
    BLOB_SIGMA,
    BLOB_WIN,
    CACHE,
    CHAIN,
    CITY_BLUE,
    DASH_AREA,
    DASH_SIZE,
    DB_PATH,
    DETECTOR_ID,
    EXP_REACH,
    EXPEDITION,
    EXTRA_MAPS,
    FORTRESS_PAINT,
    HALL_ORANGE,
    HERE,
    HIDDEN_SNAP,
    MAP,
    MAP_MERGE,
    MAP_MIN,
    MAP_NMS,
    NOT,
    NOT_ON_EXPEDITION,
    PATH_AHEAD,
    PATH_ARRIVE,
    PATH_ARRIVE_TOWER,
    PATH_BEND_MAX,
    PATH_BEND_SMOOTH,
    PATH_END_RESCUE,
    PATH_JUMP,
    PATH_LAT,
    PATH_LEAVE_ANGLE,
    PATH_LOOSE_DASHES,
    PATH_LOOSE_MEET,
    PATH_MAX_ANG,
    PATH_MAX_DEGREE,
    PATH_MAX_DETOUR,
    PATH_MAX_STEPS,
    PATH_MEET_COS,
    PATH_MEET_MANY,
    PATH_MIN_DASHES,
    PATH_REGULAR,
    PATH_SHARE,
    PATH_SINGLE_END,
    PATH_SINGLE_END_ON,
    PATH_SNAP,
    PATH_SPACING,
    PATH_START,
    PATH_STEP,
    RED_CITY,
    RIM_R,
    RING_MIN,
    ROW_DY,
    ROW_RESCUE,
    ROW_STEP,
    SEEN_CELL,
    SHOTS,
    STRONGHOLD_EMPTY,
    TEMPLATE_MIN,
    TESTS,
    TOWER_BADGES,
    TOWER_MIN,
    TOWER_NMS,
    TOWER_REFS,
    TREE_NEG_WEIGHT,
    TRUTH,
    TRUTH_SETS,
    WALK_FILL_ON_DOTS,
    WALL_CELL,
    WALL_CORNERS,
    WALL_CROSS,
    WALL_MIN_AREA,
    WALL_MIN_LEN,
    WALL_SCALES,
    WALL_STEP,
    R,
)
from .landmarks import (  # noqa: F401
    _TP,
    deadly_kind,
    expedition_rules,
    find_landmarks,
    landmarks_from,
    old_landmarks,
    ship_markers,
    tower_features,
    tower_labels,
)
from .maps import (  # noqa: F401
    _RINGS,
    _SECT,
    _WIDE,
    _X2,
    _Y2,
    _ang,
    _keep_best,
    _nms,
    _rad,
    _rad2,
    _xx,
    _yy,
    candidate_labels,
    drop_hud,
    map_candidates,
    map_features,
)
from .models import (  # noqa: F401
    _MODEL_CLASSES,
    _TRUSTED_MODEL_TYPES,
    UnsafeModel,
    _db,
    _models,
    load_model,
    safe_model_loads,
    save_model,
)
from .paths import (  # noqa: F401
    _WALK_MEMO,
    _chain_end,
    _cross,
    _dash_links,
    _no_diamond_shortcuts,
    _on_dots,
    _walks,
    _walks_raw,
    amber_dashes,
    chain_paths,
    dash_chains,
    dash_record,
    maps_from_paths,
    path_dashes,
    path_features,
    screen_paths,
    trace_paths,
    walk_paths,
)
from .pipeline import (  # noqa: F401
    cmd_run,
    detect,
    find_maps,
)
from .training import (  # noqa: F401
    _extra_maps,
    _fit,
    _fit_all,
    _labelled,
    _run_stages,
    _tower_refs,
    _tree_examples,
    _tree_rounds,
    cmd_score,
    cmd_train,
)
from .walls import (  # noqa: F401
    _lit_walls,
    _wall_clean,
    cmd_train_fortress,
    fortress_walls,
    wall_features,
    wall_share,
)
