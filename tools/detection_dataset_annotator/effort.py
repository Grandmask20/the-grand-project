"""Review effort: what a review changed of a screenshot's pre-labels, and how long it took.

    python -m tools.detection_dataset_annotator.effort [--output-dir D] [--json FILE]

``edit_cost`` compares the boxes a reviewer was first shown (the store's ``prelabels``) with the reviewed boxes,
family by family (a map node is one of the node classes): each pre-label is matched one-to-one to a reviewed box of
its family whose middle lies within the family's radius (``RF_DETR_EVAL_RADIUS``, as the detector is scored). A
matched box is kept or relabelled (another class of its family), and may also be moved (overlap under
``ANNOTATOR_EFFORT_MOVE_IOU``); an unmatched pre-label was deleted, an unmatched reviewed box added. The matching is
the one with the fewest of these edits. The simulated
loop (``simulate_loop``) measures pre-label policies the same way, against the PM's truth.

The report groups the reviewed screenshots by what pre-labelled them (``ANNOTATOR_PRELABEL_FIELD``: the classical
detector or an RF-DETR model, the live loop's two arms) and gives the edits per screenshot, their estimated seconds
(``ANNOTATOR_EFFORT_SECONDS``) and the review timer's active seconds; with enough timed reviews it fits the seconds per
edit to the timer (non-negative least squares).
"""

from __future__ import annotations

import argparse
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment, nnls

from grand_project import core
from grand_project.detect import constants as DK
from grand_project.detect.labels import family as label_family

from . import constants as K
from .state import write_json_atomic

EDIT_KINDS = K.ANNOTATOR_EDIT_KINDS


@dataclass
class Edits:
    """What a review did to one family's boxes (or a screenshot's, summed)."""

    kept: int = 0
    """Pre-labels whose class the review kept (moved or not: a moved one is counted in ``moved`` too)."""
    relabelled: int = 0
    """Pre-labels given another class of their family."""
    moved: int = 0
    """Pre-labels moved or resized (overlap under ``ANNOTATOR_EFFORT_MOVE_IOU``), also counted as kept or relabelled:
    its seconds are the move's, on top of the box's."""
    deleted: int = 0
    """Pre-labels the review removed."""
    added: int = 0
    """Boxes the review drew."""

    def __add__(self, other: Edits) -> Edits:
        return Edits(*(getattr(self, kind) + getattr(other, kind) for kind in EDIT_KINDS))

    @property
    def edits(self) -> int:
        """The changes a reviewer had to make (everything but the kept boxes)."""
        return self.relabelled + self.moved + self.deleted + self.added

    def seconds(self, rates: Mapping[str, float] | None = None) -> float:
        """Estimated review seconds (``ANNOTATOR_EFFORT_SECONDS``, or fitted ``rates``)."""
        rates = K.ANNOTATOR_EFFORT_SECONDS if rates is None else rates
        return sum(rates.get(kind, 0.0) * getattr(self, kind) for kind in EDIT_KINDS)


def box_family(annotation: Mapping[str, Any]) -> str:
    label = str(annotation.get("label", ""))
    return label_family(label) or label


def corners(annotation: Mapping[str, Any]) -> np.ndarray | None:
    """A box's ``[x0, y0, x1, y1]`` from its ``bbox`` (x, y, w, h), or None when it has no usable box."""
    bbox = annotation.get("bbox")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4 or any(v is None for v in bbox):
        return None
    x, y, w, h = (float(v) for v in bbox)
    if not np.isfinite([x, y, w, h]).all() or w <= 0 or h <= 0:
        return None
    return np.array([x, y, x + w, y + h])


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return float(inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter))


def match_boxes(
    before: Sequence[np.ndarray], after: Sequence[np.ndarray], radius: float, edits: np.ndarray | None = None
) -> list[tuple[int, int]]:
    """One-to-one pairs (before, after) whose middles lie within ``radius``, by an optimal assignment (a greedy match
    can pair a box with its neighbour's).

    Args:
        before: ``[x0, y0, x1, y1]`` boxes.
        after: ``[x0, y0, x1, y1]`` boxes.
        radius: the farthest two paired middles lie apart.
        edits: (len(before), len(after)) the edits each pair would count (a box left unpaired counts one: deleted or
            added): the pairing with the fewest edits, then the most pairs, then the closest. None: the most pairs,
            then the closest.
    """
    if not before or not after:
        return []
    middles_before = np.array([((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in before])
    middles_after = np.array([((a[0] + a[2]) / 2, (a[1] + a[3]) / 2) for a in after])
    distance = np.hypot(*(middles_before[:, None, :] - middles_after[None, :, :]).transpose(2, 0, 1))
    reach = distance <= radius
    if edits is None:
        # out of reach costs more than any assignment's summed distances (at most min(n, m) pairs, each within
        # radius), so one reachable pair more always wins
        never = (min(len(before), len(after)) + 1) * radius + 1.0
        rows, cols = linear_sum_assignment(np.where(reach, distance, never))
        return [(int(r), int(c)) for r, c in zip(rows, cols, strict=True) if reach[r, c]]
    n, m = distance.shape
    # three tiers, each outweighing everything below it together: an assignment's summed distances stay under
    # dist_cap (at most min(n, m) pairs, each within radius); an unpaired box costs dist_cap, so a pair fewer costs
    # 2 * dist_cap, more than any change of distances; the unpaired penalties and distances stay under
    # (n + m + 1) * dist_cap = edit, so one edit more outweighs them all. Out of reach never pairs.
    dist_cap = (min(n, m) + 1) * radius + 1.0
    edit = (n + m + 1) * dist_cap
    never = (n + m + 1) * (edit + dist_cap)
    cost = np.full((n + m, n + m), never)
    cost[:n, :m] = np.where(reach, edit * np.asarray(edits, float) + distance, never)
    cost[np.arange(n), m + np.arange(n)] = edit + dist_cap  # before i unpaired: deleted
    cost[n + np.arange(m), np.arange(m)] = edit + dist_cap  # after j unpaired: added
    cost[n:, m:] = 0.0
    rows, cols = linear_sum_assignment(cost)
    return [(int(r), int(c)) for r, c in zip(rows, cols, strict=True) if r < n and c < m and reach[r, c]]


def pixel_scale(width: float | None, height: float | None) -> float:
    """A screenshot's pixels per detector pixel: how ``core.scale_screenshot`` resizes it (1.0 for a 1080p
    screenshot, a crop, or a size that is not known)."""
    if not width or not height:
        return 1.0
    return float(width) / core.detector_size(int(width), int(height))[0]


def edit_cost(
    prelabels: Iterable[Mapping[str, Any]],
    final: Iterable[Mapping[str, Any]],
    *,
    scale: float = 1.0,
    families: Iterable[str] | None = None,
) -> dict[str, Edits]:
    """What turned ``prelabels`` into ``final``, family by family.

    Args:
        prelabels: the boxes first shown (annotation dicts: ``label``, ``bbox`` x, y, w, h).
        final: the reviewed (or reference) boxes.
        scale: the boxes' pixels per detector pixel (``pixel_scale``; the radii are the detector's 1080p ones).
        families: only these families (all by default).

    Returns:
        family -> its ``Edits``.
    """
    chosen = None if families is None else set(families)
    grouped: dict[str, tuple[list[tuple[str, np.ndarray]], list[tuple[str, np.ndarray]]]] = {}
    for side, boxes in ((0, prelabels), (1, final)):
        for annotation in boxes:
            box = corners(annotation)
            name = box_family(annotation)
            if box is None or (chosen is not None and name not in chosen):
                continue
            grouped.setdefault(name, ([], []))[side].append((str(annotation["label"]), box))
    out: dict[str, Edits] = {}
    for name, (before, after) in sorted(grouped.items()):
        radius = DK.RF_DETR_EVAL_RADIUS.get(name, max(DK.RF_DETR_EVAL_RADIUS.values())) * scale
        # what pairing each two would count: relabelled, moved (the fewest edits overall is the review's)
        cost = np.array(
            [
                [(label != other) + (_iou(box, theirs) < K.ANNOTATOR_EFFORT_MOVE_IOU) for other, theirs in after]
                for label, box in before
            ],
            float,
        ).reshape(len(before), len(after))
        pairs = match_boxes([box for _l, box in before], [box for _l, box in after], radius, cost)
        edits = Edits(deleted=len(before) - len(pairs), added=len(after) - len(pairs))
        for i, j in pairs:
            if before[i][0] != after[j][0]:
                edits.relabelled += 1
            else:
                edits.kept += 1
            if _iou(before[i][1], after[j][1]) < K.ANNOTATOR_EFFORT_MOVE_IOU:
                edits.moved += 1
        out[name] = edits
    return out


def total(edits: Mapping[str, Edits]) -> Edits:
    """The families' edits summed."""
    out = Edits()
    for value in edits.values():
        out = out + value
    return out


# ---- the report -------------------------------------------------------------------------------------------------


@dataclass
class Review:
    """One reviewed screenshot's effort."""

    key: str
    arm: str
    """What pre-labelled it: ``classical`` or ``rf_detr`` (``ANNOTATOR_PRELABEL_FIELD``), or
    ``ANNOTATOR_UNASSIGNED_ARM`` when no pass assigned it one (not part of the A/B comparison)."""
    edits: Edits
    boxes: int
    """Its reviewed boxes."""
    active_s: float | None = None
    """The review timer's active seconds (None: reviewed before the timer)."""


@dataclass
class ArmReport:
    """The effort of one pre-label arm."""

    screenshots: int = 0
    boxes_per_screenshot: float = 0.0
    edits_per_screenshot: dict[str, float] = field(default_factory=dict)
    estimated_s_per_screenshot: float = 0.0
    timed: int = 0
    active_s_median: float | None = None
    active_s_mean: float | None = None


def reviews(store) -> list[Review]:
    """The reviewed screenshots' effort: their boxes against their pre-label snapshot."""
    out = []
    for key, item in store.items(reviewed_only=True):
        prelabel = item.get(K.ANNOTATOR_PRELABEL_FIELD) or {}
        review = item.get(K.ANNOTATOR_REVIEW_FIELD) or {}
        scale = pixel_scale(item.get("width"), item.get("height"))
        edits = total(edit_cost(store.prelabels(key), item["annotations"], scale=scale))
        active = review.get("active_s")
        out.append(
            Review(
                key=key,
                arm=str(prelabel.get("source") or K.ANNOTATOR_UNASSIGNED_ARM),
                edits=edits,
                boxes=len(item["annotations"]),
                active_s=None if active is None else float(active),
            )
        )
    return out


def arm_reports(rows: Sequence[Review]) -> dict[str, ArmReport]:
    """Per arm: screenshots, boxes, edits and seconds per screenshot."""
    out: dict[str, ArmReport] = {}
    for arm in sorted({row.arm for row in rows}):
        mine = [row for row in rows if row.arm == arm]
        timed = [row.active_s for row in mine if row.active_s is not None]
        out[arm] = ArmReport(
            screenshots=len(mine),
            boxes_per_screenshot=statistics.fmean(row.boxes for row in mine),
            edits_per_screenshot={
                kind: statistics.fmean(getattr(row.edits, kind) for row in mine) for kind in (*EDIT_KINDS, "edits")
            },
            estimated_s_per_screenshot=statistics.fmean(row.edits.seconds() for row in mine),
            timed=len(timed),
            active_s_median=statistics.median(timed) if timed else None,
            active_s_mean=statistics.fmean(timed) if timed else None,
        )
    return out


def fit_seconds(rows: Sequence[Review]) -> dict[str, float] | None:
    """The seconds per box by what the review did to it, fitted to the timed reviews (non-negative least squares),
    or None with fewer than ``ANNOTATOR_EFFORT_MIN_FIT`` of them."""
    timed = [row for row in rows if row.active_s is not None]
    if len(timed) < K.ANNOTATOR_EFFORT_MIN_FIT:
        return None
    design = np.array([[getattr(row.edits, kind) for kind in EDIT_KINDS] for row in timed], float)
    seconds, _residual = nnls(design, np.array([row.active_s for row in timed], float))
    return {kind: round(float(value), 2) for kind, value in zip(EDIT_KINDS, seconds, strict=True)}


def report_lines(rows: Sequence[Review]) -> list[str]:
    """The report as lines to print."""
    if not rows:
        return ["No reviewed screenshots yet."]
    lines = [
        f"{'arm':<10} {'shots':>5} {'boxes':>6} {'edits':>6} "
        + " ".join(f"{kind:>10}" for kind in EDIT_KINDS)
        + f" {'est. s':>7} {'timed':>5} {'active s':>9}"
    ]
    for arm, report in arm_reports(rows).items():
        per = report.edits_per_screenshot
        active = "" if report.active_s_median is None else f"{report.active_s_median:9.0f}"
        lines.append(
            f"{arm:<10} {report.screenshots:5d} {report.boxes_per_screenshot:6.1f} {per['edits']:6.1f} "
            + " ".join(f"{per[kind]:10.1f}" for kind in EDIT_KINDS)
            + f" {report.estimated_s_per_screenshot:7.0f} {report.timed:5d} {active}"
        )
    lines.append("(per screenshot; active s: the review timer's median)")
    fitted = fit_seconds(rows)
    if fitted is not None:
        lines.append(f"seconds per box fitted to the timer: {fitted} (estimates: {K.ANNOTATOR_EFFORT_SECONDS})")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Print the effort report of the reviewed screenshots (and save it as JSON)."""
    from .state import resolve_path
    from .store import ReviewStore

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--json", type=Path, help="also save the report here")
    args = parser.parse_args(argv)
    store_path = resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE
    if not store_path.is_file():  # (opening it for writing would make an empty store, and its folder)
        print(f"No annotator store at {store_path}")
        return 2
    with ReviewStore.open(store_path, read_only=True) as store:
        rows = reviews(store)
    print("\n".join(report_lines(rows)))
    if args.json:
        payload = {
            "arms": {arm: asdict(report) for arm, report in arm_reports(rows).items()},
            "fitted_seconds": fit_seconds(rows),
            "reviews": [
                {
                    "key": row.key,
                    "arm": row.arm,
                    "edits": asdict(row.edits),
                    "boxes": row.boxes,
                    "active_s": row.active_s,
                }
                for row in rows
            ],
        }
        write_json_atomic(args.json, payload)  # whole or not at all: a reader sees the last report or this one
    return 0 if rows else 1


__all__ = [
    "EDIT_KINDS",
    "Edits",
    "Review",
    "arm_reports",
    "box_family",
    "corners",
    "edit_cost",
    "fit_seconds",
    "match_boxes",
    "pixel_scale",
    "report_lines",
    "reviews",
    "total",
]


if __name__ == "__main__":
    raise SystemExit(main())
