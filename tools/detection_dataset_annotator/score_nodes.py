"""How well the classical first guesses name map nodes, measured on reviewed screenshots.

    python -m tools.detection_dataset_annotator.score_nodes [--output-dir DIR] [--ring 19.35 38] [--limit 50]

For every reviewed screenshot, the reviewer's node boxes (their places and classes), icon boxes and landmark boxes
(citadels, halls, towers, strongholds) are taken as they are (an icon the reviewer named no type is named as the
classical detector names it, ``name_icons``); the biome ring (``detect.biomes.node_biomes``, ``BIOME_RING``) and the
city areas (``city_area_nodes``, over paths the classical tracer finds between the reviewed nodes) guess each node's
class again, and the guesses are compared with the reviewer's classes: a confusion matrix and each class's precision
and recall, for the sure guesses and for all. Use it to tune ``BIOME_*`` (``--ring`` tries another ring).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from grand_project import core
from grand_project.detect import constants as DK
from grand_project.detect import labels as L
from grand_project.detect.biomes import city_area_nodes, node_biomes
from grand_project.detect.icon_types import icon_type
from grand_project.detect.rf_detr_model import hall_node

from . import constants as K
from .detection import decode_image
from .state import resolve_path
from .store import ReviewStore


def _middle(annotation: dict[str, Any], sx: float, sy: float) -> tuple[float, float]:
    """A box's middle in detector px."""
    x, y, w, h = (float(v) for v in annotation["bbox"])
    return (x + w / 2) * sx, (y + h / 2) * sy


def name_icons(img: np.ndarray, icons: list[dict[str, Any]]) -> None:
    """Give the reviewed icons the reviewer named no type (``icon``, ``icon_unidentified``) the classical detector's
    names, in place: the guesses read names (the Delirium mist, the maps a city's area never grows through), and the
    annotator made its guesses from the classical names, whatever the boxes' labels.

    Each keeps the reviewer's place and takes the name the classical naming step (``badges.name_found_icons``) gives
    at it; "Unidentified" when it names none there.
    """
    from grand_project.detect.badges import name_found_icons, naming_book

    unnamed = [icon for icon in icons if icon["name"] in (None, "Unidentified")]
    if not unnamed:
        return
    named = name_found_icons(img, unnamed, naming_book(), influence_min=None)
    for icon in unnamed:
        near = [n for n in named if np.hypot(n["x"] - icon["x"], n["y"] - icon["y"]) <= DK.BADGE_NMS]
        best = min(near, key=lambda n: np.hypot(n["x"] - icon["x"], n["y"] - icon["y"]), default=None)
        icon["name"] = best["name"] if best is not None else "Unidentified"


def guess_nodes(
    img: np.ndarray, annotations: list[dict[str, Any]], width: int, height: int
) -> list[tuple[str, str, bool]]:
    """(reviewed class, guessed class, sure) for every reviewed node box of one screenshot."""
    from grand_project.detect.paths import path_dashes, trace_paths
    from grand_project.detect.walls import fortress_walls, wall_share

    sx, sy = img.shape[1] / width, img.shape[0] / height
    nodes, truth = [], []
    icons, landmarks, city_types = [], [], {}
    halls: list[tuple[int, list[float]]] = []
    for annotation in annotations:
        bbox = annotation.get("bbox") or [None] * 4
        if len(bbox) != 4 or any(value is None for value in bbox):
            continue  # a box stored without a place (NaN is stored as NULL): the editor and export skip it too
        label = str(annotation.get("label", ""))
        x, y = _middle(annotation, sx, sy)
        if L.is_node(label):
            nodes.append({"x": x, "y": y})
            truth.append(label)
        elif L.family(label) == "icon":
            icons.append({"name": icon_type(label), "x": x, "y": y, "score": 1.0})
        elif kind := L.landmark_kind(label):
            # Every reviewed landmark, as the classical detector reports it: the city rules keep towers, halls,
            # strongholds and other cities out of a city's area (cities.blocked_maps). A tower stands on its map
            # node, the box's bottom edge; a hall is its map node (placed below, once the icons have names).
            if kind == "Tower":
                y = (float(annotation["bbox"][1]) + float(annotation["bbox"][3])) * sy
            if kind == "City":
                city_types[len(landmarks)] = L.city_type(label)
            if kind == "Hall":
                bx, by, bw, bh = (float(v) for v in annotation["bbox"])
                halls.append((len(landmarks), [bx * sx, by * sy, (bx + bw) * sx, (by + bh) * sy]))
            landmarks.append({"kind": kind, "x": x, "y": y})
    if not nodes:
        return []
    name_icons(img, icons)
    bosses = [icon for icon in icons if icon["name"] == "MapBossSpecial"]
    for index, box in halls:
        # the hall's reviewed map node (the one under its deadly-boss icon), as the detector places a Hall
        node = hall_node(box, nodes, bosses)
        if node is not None:
            landmarks[index].update(x=node["x"], y=node["y"])
    # the paths the classical detector keeps: none across a fortress wall (detect.pipeline), or an area would grow
    # through the wall
    wall = fortress_walls(img)
    edges = [
        edge for edge in trace_paths(nodes, path_dashes(img), img) if wall_share(edge["line"], wall) < DK.WALL_CROSS
    ]
    areas = city_area_nodes(nodes, edges, icons, landmarks, city_types)
    out = []
    for index, guess in enumerate(node_biomes(img, nodes, icons)):
        if index in areas:
            # a city's own map is as sure as its city's type (proposals.node_classes), and a reviewed citadel's type
            # is sure; the rest of its area is a guess
            city, steps = areas[index]
            out.append((truth[index], L.node_label(city_type=city), steps == 0))
        else:
            label = L.node_label(biome=guess.biome) if guess.biome else L.node_label()
            out.append((truth[index], label, guess.sure))
    return out


def report(pairs: list[tuple[str, str, bool]]) -> str:
    """A confusion matrix (reviewed class down, guess across) and each class's precision and recall."""
    classes = L.node_labels()
    short = {label: label.removeprefix("map_node_") if label != "map_node" else "unknown" for label in classes}
    lines = []
    for title, chosen in (("all guesses", pairs), ("sure guesses", [p for p in pairs if p[2]])):
        counts = Counter((t, g) for t, g, _sure in chosen)
        right = sum(counts[(c, c)] for c in classes)
        lines.append(f"{title}: {len(chosen)} nodes, {right / max(1, len(chosen)):.1%} right")
        head = "reviewed/guess"
        lines.append(f"{head:<16}" + "".join(f"{short[c][:8]:>9}" for c in classes) + "   recall")
        for t in classes:
            row = [counts[(t, g)] for g in classes]
            total = sum(row)
            recall = f"{counts[(t, t)] / total:8.1%}" if total else "       -"
            lines.append(f"{short[t]:<16}" + "".join(f"{n:9d}" for n in row) + f" {recall}")
        precision = []
        for g in classes:
            total = sum(counts[(t, g)] for t in classes)
            precision.append(f"{counts[(g, g)] / total:9.1%}" if total else "        -")
        lines.append(f"{'precision':<16}" + "".join(precision))
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Score the node guesses on the reviewed screenshots of a review store."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--ring", nargs=2, type=float, metavar=("INNER", "OUTER"), help="try another BIOME_RING (px)")
    parser.add_argument("--limit", type=int, default=None, help="score at most this many screenshots")
    args = parser.parse_args(argv)
    if args.ring and not (np.isfinite(args.ring).all() and 0 <= args.ring[0] < args.ring[1]):
        parser.error("--ring needs two finite radii, 0 <= INNER < OUTER")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be 0 or more")
    ring = DK.BIOME_RING
    if args.ring:
        DK.BIOME_RING = (args.ring[0], args.ring[1])  # read live by biomes.node_biomes; put back below
    try:
        pairs, scored = _score(resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE, args.limit)
        if not pairs:
            print("No reviewed node boxes yet: review some screenshots first.")
            return 1
        print(f"{scored} reviewed screenshots with node boxes, ring {DK.BIOME_RING[0]:g}-{DK.BIOME_RING[1]:g} px\n")
        print(report(pairs))
        return 0
    finally:
        DK.BIOME_RING = ring


def _score(store_path: Path, limit: int | None) -> tuple[list[tuple[str, str, bool]], int]:
    """(reviewed class, guess, sure) of every reviewed node box, and how many screenshots had node boxes."""
    pairs: list[tuple[str, str, bool]] = []
    scored = 0
    with ReviewStore.open(store_path) as store:
        for _key, item in store.items(reviewed_only=True):
            if limit is not None and scored >= limit:
                break  # before reading the next one: --limit 0 reads none
            raw = decode_image(Path(item["path"]))
            if raw is None:
                continue
            img = core.scale_screenshot(raw)
            found = guess_nodes(img, item.get("annotations", []), raw.shape[1], raw.shape[0])
            pairs.extend(found)
            scored += bool(found)  # a screenshot without node boxes scores nothing: it uses none of --limit
    return pairs, scored


if __name__ == "__main__":
    raise SystemExit(main())
