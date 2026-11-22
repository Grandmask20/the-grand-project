"""Clean a screenshot's map node boxes in the review store from hand-checked map node positions.

    python -m tools.detection_dataset_annotator.node_truth atlas_test_data/map_state_change/*/states.json [--dry-run]

A ``states.json`` (``tools/node_state_sheet.py``) lists, for each screenshot of its folder, the map nodes a person
checked on a contact sheet of the classical detector's map nodes, with each one's state. The sheet showed every map
node the detector found that was not hidden and whose crop fit on the screen (``node_state_sheet._positions``); the
person left out those that are no map node ("none"). So, for every unreviewed store screenshot a ``states.json``
lists, the classical detector is run again to know which map nodes the sheet showed, and each map node box:

- at a checked position (``ANNOTATOR_NODE_TRUTH_REACH``) is kept as it is (its class stays the ground guess: the
  positions say where map nodes are, not their ground);
- at a position the sheet showed but nobody checked is deleted (no map node);
- anywhere else (at the screen's edge, a hidden map node under an icon row) is kept: nobody judged it.

No box is added: the checked positions are the detector's own. A screenshot with a checked position no box is at is
left alone (neither changed nor marked). Every other one is marked (``ANNOTATOR_TRUTH_MARK``: the ``states.json``,
project-relative), so a truth-seeded training round (``train_rf_detr --truth-seeded``) takes it. Reviewed or edited
screenshots are never changed, and a second run changes nothing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from grand_project import core, icon_refs
from grand_project.detect import labels as L

from . import constants as K
from .state import relative_source, resolve_path
from .store import ReviewStore
from .truth_seed import _detector_image


@dataclass(frozen=True)
class NodeTruth:
    """Hand-checked map node positions of one or more folders, by screenshot."""

    positions: dict[Path, np.ndarray]
    """Screenshot path (resolved) -> (N, 2) its checked map nodes, 1080p screen px."""
    marks: dict[Path, str]
    """Screenshot path -> the ``states.json`` that lists it, project-relative (its truth mark)."""

    @classmethod
    def load(cls, files: Sequence[Path]) -> NodeTruth:
        """Read ``states.json`` files ({screenshot file name: [{x, y, state}]}, next to their screenshots)."""
        positions, marks = {}, {}
        for file in files:
            file = Path(file).resolve()
            for name, items in json.loads(file.read_text(encoding="utf-8")).items():
                shot = file.parent / name
                positions[shot] = np.array([[s["x"], s["y"]] for s in items], float).reshape(-1, 2)
                marks[shot] = relative_source(file)
        return cls(positions, marks)


def judged_positions(img: np.ndarray) -> np.ndarray:
    """The map nodes a contact sheet of this screenshot showed: the classical detector's, not hidden, whose crop fits
    on the screen (as ``node_state_sheet`` made them), (N, 2) 1080p px."""
    from grand_project.detect.pipeline import detect_classical

    nodes = [n for n in detect_classical(img)["nodes"] if not n.get("hidden")]
    pts = [(n["x"], n["y"]) for n in nodes if icon_refs.crop(img, n["x"], n["y"]) is not None]
    return np.array(pts, float).reshape(-1, 2)


def seed_nodes(
    boxes: Sequence[Mapping[str, Any]], truth: np.ndarray, judged: np.ndarray, scale: float = 1.0
) -> tuple[list[dict[str, Any]] | None, Counter[str], bool]:
    """Keep or delete a screenshot's map node boxes by the checked positions.

    Args:
        boxes: its boxes (``bbox`` x, y, w, h in the screenshot's own px).
        truth: (N, 2) its checked map nodes, 1080p px.
        judged: (M, 2) the map nodes its contact sheet showed, 1080p px.
        scale: the screenshot's px per 1080p px.

    Returns:
        (its boxes now, or None when nothing changes; what was done; whether every checked position has a box).
    """
    done: Counter[str] = Counter()
    reach = K.ANNOTATOR_NODE_TRUTH_REACH
    kept, found = [], np.zeros(len(truth), bool)
    for box in boxes:
        if not L.is_node(str(box["label"])):
            kept.append(dict(box))
            continue
        x, y, w, h = box["bbox"]
        middle = np.array([(x + w / 2) / scale, (y + h / 2) / scale])
        at_truth = np.hypot(*(truth - middle).T) <= reach if len(truth) else np.zeros(0, bool)
        if at_truth.any():
            found |= at_truth
            done["map node at a checked position: kept"] += 1
            kept.append(dict(box))
        elif (
            box.get("source") != K.ANNOTATOR_HIDDEN_SOURCE
            and len(judged)
            and (np.hypot(*(judged - middle).T).min() <= reach)
        ):
            done["map node checked as none: deleted"] += 1
        else:
            done["map node nobody judged (edge, hidden): kept"] += 1
            kept.append(dict(box))
    complete = bool(found.all())
    if not complete:
        done["checked position with no map node box (left alone)"] += int((~found).sum())
    changed = len(kept) != len(boxes)
    return (kept if changed and complete else None), done, complete


def seed_store_nodes(
    store: ReviewStore,
    truth: NodeTruth,
    *,
    dry_run: bool = False,
    image: Callable[[Path], np.ndarray | None] = _detector_image,
) -> tuple[Counter[str], int, int]:
    """Clean and mark every unreviewed store screenshot the truth lists (see the module docstring).

    Returns:
        (what was done, screenshots changed, screenshots the truth lists).
    """
    todo = [
        (key, item)
        for key, item in store.items()
        if not item.get("reviewed") and item.get("detected") and Path(item["path"]).resolve() in truth.positions
    ]
    done: Counter[str] = Counter()
    changed = 0
    for key, item in todo:
        path = Path(item["path"]).resolve()
        mark = truth.marks[path]
        if item.get(K.ANNOTATOR_TRUTH_MARK) not in (None, mark):
            done["marked by another truth: left"] += 1
            continue
        img = image(path)
        if img is None:
            done["screenshot unreadable: left"] += 1
            continue
        detector_width, _h = core.detector_size(int(item["width"]), int(item["height"]))
        boxes, counts, complete = seed_nodes(
            item["annotations"], truth.positions[path], judged_positions(img), int(item["width"]) / detector_width
        )
        done.update(counts)
        if not complete or dry_run:
            changed += boxes is not None and complete
            continue
        guard = {"untouched": True, "expect_boxes": item["annotations"]}
        if boxes is None:
            if item.get(K.ANNOTATOR_TRUTH_MARK) != mark:
                store.save_review(key, int(item["edit_version"]), extra={K.ANNOTATOR_TRUTH_MARK: mark}, **guard)
            continue
        if store.save_review(
            key,
            int(item["edit_version"]),
            annotations=boxes,
            extra={K.ANNOTATOR_TRUTH_MARK: mark},
            prelabel=True,
            **guard,
        ):
            changed += 1
        else:
            done["skipped: reviewed, edited or detected again meanwhile"] += 1
    return done, changed, len(todo)


def main(argv: list[str] | None = None) -> int:
    """Clean the review store's map node boxes from ``states.json`` files and print what changed."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("states", nargs="+", help="states.json files (tools/node_state_sheet.py save)")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, change nothing")
    args = parser.parse_args(argv)
    truth = NodeTruth.load([resolve_path(f) for f in args.states])
    with ReviewStore.open(resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE) as store:
        done, changed, listed = seed_store_nodes(store, truth, dry_run=args.dry_run)
    verb = "would change" if args.dry_run else "changed"
    print(f"{listed} unreviewed screenshots listed by the checked map nodes, {verb} {changed}")
    for what, count in sorted(done.items()):
        print(f"  {what:<55} {count:7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
