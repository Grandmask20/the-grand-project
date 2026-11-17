"""The detector for atlas screenshots.

Stages, each scored against atlas_test_data/truth/truth.json (not shipped) with atlas_truth.score:
  1. HUD      the game's interface (hud_mask_full.png, drawn by the user) is never a map, badge or landmark
  2. maps     bright-blob candidates -> learned classifier: map (towers included) / not a map
  3. icons    gold-ring + average-icon spots -> icon classifier -> name from the icon pictures
              (badge_refs table + the labelled ones kept in the model); rows of up to 5 icons sit 24 px
              above their map, centred on it (user) -> an icon row with no map found = a hidden map
  4. landmarks Towers (classifier on found maps: the spire above them); Deadly Map Boss rows -> City (barrel
              / blue or red beam) / Hall (beam on a structure beside it) / deadly boss map; Breach
              strongholds (old purple rule), locked when a hand badge is near or no map is inside
  5. paths    amber / dim-gold / fog-orange dash mask -> dash-by-dash tracing between maps by the user's
              path rules; two dead ends meeting = a missed map; dashes around a spot are map evidence too
  6. biome    ground type per map
Modes: TRAINING fits models from the hand-labelled truth and stores them in the reference DB
(table detector_models); LIVE only reads them and never writes the DB.

    python -m grand_project.detect score         every stage tested leave-one-screenshot-out (each labelled
                                                 screenshot judged by models trained without it)
    python -m grand_project.detect train         training mode: fit every model on all labelled screenshots -> DB
    python -m grand_project.detect train_cities  only the City barrel model
    python -m grand_project.detect run IMG...    live mode: maps per screenshot (reads the DB, never writes it)
"""

from .annotate import (  # noqa: F401
    LM_STYLE,
    PATH_DRAW_SHIFT,
    annotate,
    cmd_show,
)
from .badges import (  # noqa: F401
    _row_slot,
    badge_book,
    badge_candidates,
    badge_features,
    badge_labels,
    badge_rows,
    badges_from,
    find_badges,
    name_badge,
    rim_score,
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
    CHAIN,
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
    RF_DETR_AUGMENT_CROP_ATTEMPTS,
    RF_DETR_AUGMENT_CROP_MIN_SCALE,
    RF_DETR_AUGMENT_CROP_MIN_VISIBILITY,
    RF_DETR_AUGMENT_CROP_PROBABILITY,
    RF_DETR_AUGMENT_FLIP_PROBABILITY,
    RF_DETR_CORE_LABELS,
    RF_DETR_DEFAULT_MODEL_DIR,
    RF_DETR_DEVICE_ENV,
    RF_DETR_ICON_BOX,
    RF_DETR_LANDMARK_BOX,
    RF_DETR_MAP_BOX,
    RF_DETR_MODEL_ENV,
    RF_DETR_MODEL_NAME,
    RF_DETR_NMS_IOU,
    RF_DETR_PATH_DASH_BOX,
    RF_DETR_PATH_PAD,
    RF_DETR_SCORE_THRESHOLD,
    RF_DETR_SOFT_FLAGS,
    RF_DETR_STRONGHOLD_BOX,
    RF_DETR_TOWER_HEIGHT,
    RF_DETR_TOWER_WIDTH,
    RF_DETR_USE_ENV,
    RF_DETR_WALL_MIN_AREA,
    RIM_R,
    ROW_DY,
    ROW_RESCUE,
    ROW_STEP,
    SEEN_CELL,
    SHOTS,
    STRONGHOLD_EMPTY,
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
    detect_classical,
    find_maps,
)
from .rf_detr import (  # noqa: F401
    Record,
    augment_detection_example,
    build_dataset,
    load_records,
    processor_transform,
    split_records,
)
from .rf_detr_model import (  # noqa: F401
    detect_rf_detr,
    reset_rf_detr_runtime,
    rf_detr_enabled,
    rf_detr_model_path,
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
