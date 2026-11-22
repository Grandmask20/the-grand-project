"""Pre-fill the city areas and citadels of a hand-labelled atlas's screenshots in the review store from its truth.

    python -m tools.detection_dataset_annotator.truth_seed atlas_test_data/fr-atlas/truth.json [--dry-run]

The truth file (``truth.json``, described in ``atlas_test_data/fr-atlas/README.md``) gives every map of an atlas in
atlas units with the area it lies in ("Ezomyte city", "Vaal city", "Faridun city", "Breach stronghold" or ""), the
Cities, and how each screenshot is placed (``M``, ``horizon``). For every unreviewed store screenshot the truth places
(by file name), each box's middle is taken to atlas units (``core.geometry``, as the truth file says) and:

- a map node box at a truth map (``ANNOTATOR_TRUTH_MAP_REACH``) in a city's area takes that area's class. One the
  classical guess put in a city's area while the truth has it outside every city area gets its ground ring's class
  again (``biomes.node_biomes``, as the detector names a node outside city areas). Other node boxes stay as they are:
  the truth knows city areas, not the ground.
- a citadel box near no city area's map (``ANNOTATOR_TRUTH_CITY_REACH``) is deleted (the false Cities, most inside
  the fortress); the others take the city type of the area they stand in.

The boxes it sets get the source ``ANNOTATOR_TRUTH_SOURCE`` (no guess: drawn solid; the screenshot is still
reviewed). Reviewed screenshots are never changed, and a second run changes nothing. It reports what it changed, the
truth Cities a screenshot shows without a citadel box (to draw while reviewing) and the stronghold boxes far from
every truth stronghold area (to check: the truth labels roughly every stronghold area).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from grand_project import cities, core
from grand_project.core.geometry import persp, rectifier, screen_to_atlas
from grand_project.detect import constants as DK
from grand_project.detect import labels as L
from grand_project.detect.icon_types import icon_type

from . import constants as K
from .detection import decode_image
from .score_nodes import name_icons
from .state import relative_source, resolve_path
from .store import ReviewStore

CITY_AREAS = {f"{city_type} city": city_type for city_type in cities.TYPES}
"""The truth's area names of cities -> their city type."""

STRONGHOLD_AREA = "Breach stronghold"
"""The truth's area name of a Breach stronghold."""


@dataclass(frozen=True)
class Truth:
    """An atlas's hand-labelled areas, read from its truth file."""

    maps: np.ndarray
    """(N, 2) every live map in atlas units."""
    areas: list[str]
    """Each map's area ("" outside every area)."""
    cities: np.ndarray
    """(C, 2) the Cities found in the city areas (not the stand-ins of areas where none was found)."""
    screenshots: dict[str, dict[str, Any]]
    """File name -> its placement (``w``, ``h``, ``M``, ``horizon``)."""
    source: str = ""
    """The truth file, project-relative: the mark a seeded screenshot carries (``ANNOTATOR_TRUTH_MARK``)."""

    @classmethod
    def load(cls, path: Path) -> Truth:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        maps = np.array([row[:2] for row in data["maps"]], float).reshape(-1, 2)
        cities_found = [
            (area["city"]["x"], area["city"]["y"])
            for area in data["biomes"]
            if area.get("city") and not area["city"].get("assumed")
        ]
        return cls(
            maps=maps,
            areas=[str(row[2]) for row in data["maps"]],
            cities=np.array(cities_found, float).reshape(-1, 2),
            screenshots={shot["file"]: shot for shot in data["screenshots"]},
            source=relative_source(Path(path)),
        )

    def _of_areas(self, names: set[str]) -> list[int]:
        return [i for i, area in enumerate(self.areas) if area in names]

    @cached_property
    def map_tree(self) -> cKDTree:
        """Every map, for finding the one at a place."""
        return cKDTree(self.maps)

    @cached_property
    def city_maps(self) -> tuple[cKDTree, list[str]]:
        """The maps of the city areas, and each one's city type."""
        picked = self._of_areas(set(CITY_AREAS))
        return cKDTree(self.maps[picked].reshape(-1, 2)), [CITY_AREAS[self.areas[i]] for i in picked]

    @cached_property
    def stronghold_maps(self) -> cKDTree:
        """The maps of the Breach stronghold areas."""
        return cKDTree(self.maps[self._of_areas({STRONGHOLD_AREA})].reshape(-1, 2))


def _nearest(tree: cKDTree, point: np.ndarray, reach: float) -> int | None:
    """The index of the point nearest ``point`` within ``reach``, else None."""
    if tree.n == 0:
        return None
    distance, index = tree.query(point)
    return int(index) if distance <= reach else None


def _middle(box: dict[str, Any], sx: float, sy: float) -> tuple[float, float]:
    """A box's middle, scaled; NaN for a box stored without a place (the editor and export skip those too)."""
    bbox = box.get("bbox") or [None] * 4
    if any(value is None for value in bbox):
        return float("nan"), float("nan")
    x, y, w, h = (float(value) for value in bbox)
    return (x + w / 2) * sx, (y + h / 2) * sy


def _set(annotation: dict[str, Any], label: str, source: str) -> bool:
    """Give a box a label and source; whether that changed it."""
    if (annotation.get("label"), annotation.get("source")) == (label, source):
        return False
    annotation["label"], annotation["source"] = label, source
    return True


def seed_screenshot(
    item: dict[str, Any],
    shot: dict[str, Any],
    truth: Truth,
    read_image: Callable[[Path], np.ndarray | None],
) -> tuple[list[dict[str, Any]] | None, Counter[str]]:
    """One screenshot's boxes as the truth has them.

    Args:
        item: the store screenshot (``path``, ``width``, ``height``, ``annotations``).
        shot: its placement in the truth file.
        truth: the atlas's truth.
        read_image: the screenshot as the detector reads it (1080p BGR), or None; read only when a node's ground
            ring is needed.

    Returns:
        The changed boxes (None when nothing changed), and what was done (counts by kind).
    """
    done: Counter[str] = Counter()
    boxes = [dict(annotation) for annotation in item.get("annotations", [])]
    if not boxes:
        return None, done
    width, height = int(item.get("width") or shot["w"]), int(item.get("height") or shot["h"])
    sx, sy = shot["w"] / width, shot["h"] / height
    homography = screen_to_atlas(np.asarray(shot["M"], float), rectifier(shot["w"], shot["h"], shot.get("horizon")))
    places = persp(homography, [_middle(box, sx, sy) for box in boxes])
    city_maps, city_types = truth.city_maps
    changed = False
    keep = [True] * len(boxes)
    ring: list[int] = []
    for i, (box, place) in enumerate(zip(boxes, places, strict=True)):
        label = str(box.get("label", ""))
        if not np.isfinite(place).all():
            continue
        if L.is_node(label):
            at = _nearest(truth.map_tree, place, K.ANNOTATOR_TRUTH_MAP_REACH)
            if at is None:
                continue
            city_type = CITY_AREAS.get(truth.areas[at])
            if city_type is not None:
                if _set(box, L.node_label(city_type=city_type), K.ANNOTATOR_TRUTH_SOURCE):
                    changed = True
                    done[f"node -> {city_type} area"] += 1
            elif L.city_type(label):
                ring.append(i)
        elif L.family(label) == "citadel":
            at = _nearest(city_maps, place, K.ANNOTATOR_TRUTH_CITY_REACH)
            if at is None:
                keep[i], changed = False, True
                done["citadel deleted (no city area)"] += 1
                continue
            city_type = city_types[at]
            was = L.city_type(label)
            if _set(box, L.citadel_label(city_type), K.ANNOTATOR_TRUTH_SOURCE):
                changed = True
                done["citadel retyped" if was != city_type else "citadel confirmed"] += 1
        elif L.landmark_kind(label) == STRONGHOLD_AREA and (
            _nearest(truth.stronghold_maps, place, K.ANNOTATOR_TRUTH_STRONGHOLD_REACH) is None
        ):
            done["stronghold far from truth strongholds (check)"] += 1
    if ring:
        image = read_image(Path(item["path"]))
        if image is None:
            done["unreadable screenshot (city nodes left)"] += len(ring)
        else:
            changed |= _ring_again(boxes, ring, image, width, height, done)
    citadels = [
        place
        for box, place, kept in zip(boxes, places, keep, strict=True)
        if kept and L.family(box["label"]) == "citadel"
    ]
    done["truth City without a citadel box (draw)"] += _cities_missed(citadels, truth.cities, homography, shot)
    return ([box for box, kept in zip(boxes, keep, strict=True) if kept] if changed else None), done


def _ring_again(
    boxes: list[dict[str, Any]], ring: list[int], image: np.ndarray, width: int, height: int, done: Counter[str]
) -> bool:
    """Give the ``ring`` node boxes their ground ring's class, as the detector names a node outside city areas."""
    from grand_project.detect.biomes import node_biomes
    from grand_project.detect.proposals import biome_class

    sx, sy = image.shape[1] / width, image.shape[0] / height
    nodes, where = [], {}
    icons = []
    for i, box in enumerate(boxes):
        x, y = _middle(box, sx, sy)
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        if L.is_node(box["label"]):
            where[i] = len(nodes)
            nodes.append({"x": x, "y": y})
        elif L.family(box["label"]) == "icon":
            icons.append({"name": icon_type(box["label"]), "x": x, "y": y, "score": 1.0})
    name_icons(image, icons)  # the Delirium mist rule reads the icons' names
    guesses = node_biomes(image, nodes, icons)
    changed = False
    for i in ring:
        label, source = biome_class(guesses[where[i]])
        changed |= _set(boxes[i], label, source)
        done[f"node -> {label} (outside city areas)"] += 1
    return changed


def _cities_missed(citadels: list[np.ndarray], found: np.ndarray, homography: np.ndarray, shot: dict[str, Any]) -> int:
    """How many truth Cities the screenshot shows clear of its edges and HUD with no citadel box near them."""
    if len(found) == 0:
        return 0
    w, h = int(shot["w"]), int(shot["h"])
    pixels = persp(np.linalg.inv(homography), found)
    half = DK.RF_DETR_LANDMARK_BOX / 2
    hud = core.hud_mask(w, h, int(half))
    missed = 0
    for (px, py), city in zip(pixels, found, strict=True):
        if not (half <= px < w - half and half <= py < h - half) or hud[int(py), int(px)]:
            continue
        if not any(np.hypot(*(place - city)) <= K.ANNOTATOR_TRUTH_CITY_REACH for place in citadels):
            missed += 1
    return missed


def _detector_image(path: Path) -> np.ndarray | None:
    """The screenshot as the detector reads it (1080p BGR), or None when it cannot be read."""
    raw = decode_image(path)
    return None if raw is None else core.scale_screenshot(raw)


def seed_store(store: ReviewStore, truth: Truth, *, dry_run: bool = False) -> tuple[Counter[str], int, int]:
    """Seed every unreviewed store screenshot the truth places, and mark each one (``ANNOTATOR_TRUTH_MARK``, in its
    ``extra``), changed or not: the truth vouches for its city areas either way, so a truth-seeded training round
    (``train_rf_detr --truth-seeded``) can take it. Changed boxes are the screenshot's new pre-labels.

    Returns:
        (what was done, screenshots changed, screenshots the truth places).
    """
    # Read first, then write: the store's item read holds a transaction until it ends.
    todo = [
        (key, item)
        for key, item in store.items()
        if not item.get("reviewed") and item.get("detected") and Path(item["path"]).name in truth.screenshots
    ]
    done: Counter[str] = Counter()
    changed = 0
    for key, item in todo:
        boxes, counts = seed_screenshot(item, truth.screenshots[Path(item["path"]).name], truth, _detector_image)
        done.update(counts)
        mark = {K.ANNOTATOR_TRUTH_MARK: truth.source}
        if boxes is None:
            if not dry_run and item.get(K.ANNOTATOR_TRUTH_MARK) != truth.source:
                store.save_review(key, int(item["edit_version"]), extra=mark)
            continue
        if dry_run or store.save_review(key, int(item["edit_version"]), annotations=boxes, extra=mark, prelabel=True):
            changed += 1
        else:
            done["skipped: detected again meanwhile"] += 1
    return done, changed, len(todo)


def seed_lines(done: Counter[str], changed: int, placed: int, *, dry_run: bool = False) -> list[str]:
    """``seed_store``'s result as lines to print."""
    verb = "would change" if dry_run else "changed"
    lines = [f"{placed} unreviewed screenshots placed by the truth, {verb} {changed}"]
    lines += [f"  {what:<50} {count:7d}" for what, count in sorted(done.items())]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Seed the review store from a truth file and print what changed."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("truth", help="the atlas's truth file (truth.json)")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, change nothing")
    args = parser.parse_args(argv)
    truth = Truth.load(resolve_path(args.truth))
    with ReviewStore.open(resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE) as store:
        done, changed, placed = seed_store(store, truth, dry_run=args.dry_run)
    print("\n".join(seed_lines(done, changed, placed, dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
