"""detect.pipeline"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from grand_project import core

from .badges import find_badges
from .constants import MAP, WALL_CROSS
from .landmarks import expedition_rules, find_landmarks, ship_markers
from .maps import _nms, map_candidates, map_features
from .models import _models, load_model
from .paths import maps_from_paths, path_dashes, path_features, trace_paths
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


def detect_classical(img: np.ndarray, *, found_maps: tuple[list[dict], np.ndarray, np.ndarray] | None = None) -> dict:
    """The classical detector on one screenshot (``detect`` picks it unless RF-DETR is enabled; the benchmark and the
    dataset annotator run it explicitly).

    Runs map nodes, icons (badges), landmarks, map nodes found from paths, the Expedition rules, ship markers and
    paths (dropping paths that cross a fortress wall).

    Args:
        img: BGR screenshot (1080p).
        found_maps: The result of ``find_maps(img, _models["maps"])`` (after ``ensure_models()``) for callers that
            use the map candidates too (the dataset annotator), so the map finder (~1.7 s) runs only once.

    Returns:
        Dict with "width", "height" (px), "nodes", "landmarks", "icons" and "edges" (paths) lists.

    Raises:
        RuntimeError: The maps, badges or towers model is not in the DB yet.
    """
    ensure_models()
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


def detect(img: np.ndarray) -> dict:
    """Live mode: one screenshot with the configured detector, the classical one unless the detector settings select
    the optional RF-DETR model (``detector_config``); both return the same ``nodes``, ``icons``, ``landmarks`` and
    ``edges``."""
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
            f"{Path(f).name}: {len(r['nodes']) - hid} maps, {hid} hidden maps, {len(r['icons'])} badges, "
            f"{len(r['edges'])} paths, {kinds} "
            f"in {time.time() - t0:.1f} s"
        )
    return 0
