"""detect.pipeline"""

from __future__ import annotations

import contextlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from grand_project import core

from .badges import find_badges, special_icons
from .constants import DETECT_PREFETCH_THREADS, MAP, WALL_CROSS
from .landmarks import expedition_rules, find_landmarks, old_landmarks, ship_markers, square_buttons
from .maps import _nms, map_candidates, map_features
from .models import _models, load_model
from .paths import amber_dashes, maps_from_paths, path_dashes, path_features, trace_paths
from .rf_detr_model import detect_rf_detr, rf_detr_enabled
from .walls import fortress_walls, wall_share


def find_maps(img: np.ndarray, model) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Find the map nodes of a screenshot with the map classifier.

    Args:
        img: BGR screenshot (1080p).
        model: The trained "maps" classifier (predict_proba over map_features + path_features).

    Returns:
        (maps, pts, p): maps as dicts {"x", "y", "score"} after non-maximum suppression, all candidates as an
        (n, 2) int array of x, y in screen px, and their (n,) map probability (badge rows can still rescue a
        weak one).
    """
    pts, dv = map_candidates(img)
    if not len(pts):
        return [], pts, np.zeros(0)
    prob = model.predict_proba(np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))]))
    return _nms(pts, prob), pts, prob[:, MAP]


def ensure_models() -> None:
    """Load the classical detector's models into ``_models`` once.

    Raises:
        RuntimeError: A model is not in the DB yet.
    """
    for k in ("maps", "badges", "towers"):
        if k not in _models:
            model = load_model(k)
            if model is None:  # not cached: a later call looks again (once the model is trained)
                raise RuntimeError(f"no {k} model in the DB yet: run  python -m grand_project.detect train")
            _models[k] = model


@contextlib.contextmanager
def _prefetch(img: np.ndarray):
    """Work out the screenshot's image-only stages on helper threads while the detection goes on.

    The dashes, the special icons, the landmark rules, the fortress walls and the square buttons read nothing but
    the screenshot, and are mostly OpenCV, which runs beside Python: a single detection used one core of the several
    its worker may use. Each is remembered per image (cache._per_image), so when the detection reaches it, it takes
    the result (or waits for it): the same functions on the same screenshot, so the same results. Threads: at most
    the process's OpenCV share less one (a capped worker stays within its share); none with a share of 1.

    Args:
        img: BGR screenshot (1080p).

    Yields:
        Nothing; the helper threads are done when the block ends.
    """
    threads = min(DETECT_PREFETCH_THREADS, cv2.getNumThreads() - 1)
    if threads < 1:
        yield
        return
    with ThreadPoolExecutor(threads, thread_name_prefix="detect") as ex:
        # in the order the detection needs them (the map finder reads the dashes first)
        for stage in (path_dashes, special_icons, old_landmarks, fortress_walls, amber_dashes, square_buttons):
            ex.submit(stage, img)  # (an error is raised again where the detection asks for that stage)
        yield


def _detect_classical(img: np.ndarray, found_maps: tuple[list[dict], np.ndarray, np.ndarray] | None = None) -> dict:
    """Run the existing classical detector for one screenshot.

    This runs map nodes, icons, landmarks, map nodes found from paths, the Expedition rules, ship markers and paths.

    Args:
        img: BGR screenshot (1080p).
        found_maps: ``find_maps(img, _models["maps"])`` when the caller has it already (see detect_classical).

    Returns:
        Dict with "width", "height" (px), "nodes", "landmarks", "icons" and "edges" (paths) lists.

    """
    ensure_models()
    with _prefetch(img):
        return _classical_stages(img, found_maps)


def _classical_stages(img: np.ndarray, found_maps: tuple[list[dict], np.ndarray, np.ndarray] | None) -> dict:
    """The classical detector's stages in order (see _detect_classical)."""
    nodes, mp, mprob = found_maps if found_maps is not None else find_maps(img, _models["maps"])
    icons, more = find_badges(img, _models["badges"], nodes, mp, mprob)
    lms, nodes = find_landmarks(img, _models["towers"], nodes + more, icons)
    landmark_points = [(item["x"], item["y"]) for item in lms]
    lms = [
        landmark
        for landmark, on in zip(lms, core.on_hud_mask(landmark_points, img.shape[1], img.shape[0], pad=0), strict=False)
        if not on
    ]
    dashes = path_dashes(img)
    nodes = nodes + maps_from_paths(nodes, dashes, img, mp, mprob)
    nodes, icons, lms = expedition_rules(nodes, icons, lms)
    icons = icons + ship_markers(img)
    wall = fortress_walls(img)
    edges = [e for e in trace_paths(nodes, dashes, img) if wall_share(e["line"], wall) < WALL_CROSS]
    return {
        "width": img.shape[1],
        "height": img.shape[0],
        "nodes": nodes,
        "landmarks": lms,
        "icons": icons,
        "edges": edges,
    }


def detect_classical(img: np.ndarray, *, found_maps: tuple[list[dict], np.ndarray, np.ndarray] | None = None) -> dict:
    """Run the established classical detector explicitly.

    The public entry point is useful for benchmark tools that need to compare both detector backends in the same
    process.  Normal application code should keep using :func:`detect`, which selects the configured backend.

    Args:
        img: BGR screenshot (1080p).
        found_maps: The result of ``find_maps(img, _models["maps"])`` (after ``ensure_models()``) for callers that
            use the map candidates too (the dataset annotator), so the map finder (~1.7 s) runs only once.
    """
    return _detect_classical(img, found_maps)


def detect(img: np.ndarray) -> dict:
    """Detect one screenshot with the configured backend.

    The classical detector remains the default.  Set ``GRAND_PROJECT_USE_RF_DETR=1`` to use the optional
    fine-tuned RF-DETR model; both backends return the same ``nodes``, ``icons``, ``landmarks`` and ``edges`` shape.
    """
    return detect_rf_detr(img) if rf_detr_enabled() else detect_classical(img)


def cmd_run() -> int:  # noqa: E302
    """Command `python -m grand_project.detect run IMG...`: detect each screenshot and print what was found.

    Screenshot paths are read from sys.argv. Live mode: reads the DB, never writes it.

    Returns:
        0 (process exit code).
    """
    for f in sys.argv[2:]:
        t0 = time.time()
        r = detect(core.read_screenshot(f))
        hid = sum(1 for n in r["nodes"] if n.get("hidden"))
        kinds = {}
        for landmark in r["landmarks"]:
            kinds[landmark["kind"]] = kinds.get(landmark["kind"], 0) + 1
        print(
            f"{Path(f).name}: {len(r['nodes']) - hid} maps, {hid} hidden maps, {len(r['icons'])} icons, "
            f"{len(r['edges'])} paths, {kinds} "
            f"in {time.time() - t0:.1f} s"
        )
    return 0
