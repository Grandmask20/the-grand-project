"""PoE2 atlas builder core: add screenshots one at a time to a growing node graph.

Pure numpy + OpenCV (no new installs).  The unit of work is a *frame*: one screenshot that
the recognizer (node_recognition_0_48) has already turned into nodes, dotted-path edges and landmarks.

Registration is done on the node graph (not on terrain features):
  1. every (frame node, atlas node) pair votes for a translation; pairs whose local
     neighbour spacing agrees count more, so true correspondences pile up in one bin;
  2. the best translations are refined to a constrained affine by iteratively fitting
     mutually-nearest node pairs with a shrinking tolerance;
  3. the result is accepted only if enough nodes agree AND the terrain pixels of the two
     screenshots correlate in the overlap.  A wrong graph match fails the pixel test.
Nodes, edges and landmarks seen in several frames are merged and carry support counts, so
every extra screenshot makes an existing part of the atlas more certain.
"""

from .atlas import (  # noqa: F401
    Atlas,
    _find_screenshot,
)
from .constants import (  # noqa: F401
    ATLAS_OUTPUTS,
    DROP_MIN_INLIERS,
    HORIZON,
    HUD_DEPTH,
    HUD_MASK_FILE,
    ICON_BASE_DY,
    ICON_MERGE,
    IMAGE_EXT,
    LANDMARK_MERGE,
    MERGE_TOL,
    MIN_INLIERS,
    MIN_NCC,
    MIN_OVERLAP_RATIO,
    PARALLAX_MIN_INLIERS,
    PARALLAX_RATIO,
    PARALLAX_TOL,
    PLACEMENT,
    REFINE_TOLS,
    ROW_STEP_PX,
    SCALE_RANGE,
    SIG_DIST1,
    SIG_DIST2,
    TERRAIN_MIN_AGREE,
    TERRAIN_MIN_NCC,
    TERRAIN_SCALE,
    VOTE_BIN,
)
from .frame import (  # noqa: F401
    Frame,
    _hud_cache,
    atlas_files,
    hud_mask,
    is_full_window,
    is_screenshot,
    on_hud_mask,
    row_bases,
    screenshots_in,
)
from .geometry import (  # noqa: F401
    apply,
    invert,
    persp,
    rectifier,
    screen_to_atlas,
    to3,
)
from .register import (  # noqa: F401
    Registration,
    _horizon_of,
    _inside_rect,
    fit_affine,
    mutual_pairs,
    neighbour_signature,
    refine,
    register,
    vote_translations,
)
from .render import (  # noqa: F401
    _render_final,
    render_overlay,
)
from .terrain import (  # noqa: F401
    _MASK_CACHE,
    _MASKS,
    _valid_mask,
    _valid_mask_calc,
    terrain_ncc,
)
