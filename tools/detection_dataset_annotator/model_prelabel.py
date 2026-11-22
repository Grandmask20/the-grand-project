"""Model pre-labels: a fine-tuned RF-DETR checkpoint proposes boxes beside the classical detector's, for the next
round of review (the iterative loop: classical detection and an ever-refined model take turns).

    python -m tools.detection_dataset_annotator.model_prelabel --model runs/rf-detr-small/best
        [--share 0.5] [--seed S] [--policy union] [--limit N] [--dry-run] [--output-dir D]

Only unreviewed **training** screenshots without a reviewer's box are pre-labelled: a validation or test screenshot
reviewed from a model's pre-labels would lean toward the model, and the model would then be scored on its own
answers (user's rule: held-out screenshots keep the classical pre-labels). The screenshots the model trained on
(``RF_DETR_TRAINED_ON`` in its folder) are left too: their pre-labels would only replay its training labels; so are
the ones a hand truth seeded (a truth-seeded round trusts their boxes). A screenshot reviewed or edited while the pass
runs (the page open beside it) keeps its review: each save checks that first, in the same write.

The loop is measured as an A/B test: the eligible screenshots' spatial blocks (the split ledger's) are drawn, a
``--share`` of them get the model's pre-labels and the others keep the classical ones, and every screenshot records
its arm (``ANNOTATOR_PRELABEL_FIELD``), so ``effort`` compares the arms' review edits and times.

The model's boxes are snapped to the box rules (``snap``) and joined with the screenshot's current pre-labels by a
policy (``merge``, ``ANNOTATOR_PRELABEL_POLICIES``); a box the model and the classical detector agree on is
``rf_detr``, one only the model has or whose class it changed is a dotted ``rf_detr_guess``. A box a hand truth
set (``biome_truth``) keeps its class.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from grand_project import core
from grand_project.detect import constants as DK
from grand_project.detect.proposals import box_at_point, clip_box

from . import constants as K
from .effort import DETECTOR_WIDTH, box_family, corners, match_boxes

PROTECTED_SOURCES = frozenset({K.ANNOTATOR_TRUTH_SOURCE, K.ANNOTATOR_MANUAL_SOURCE})
"""Box sources whose class the model never changes: a hand truth's, a reviewer's."""


def snap(detection: Mapping[str, Any], width: int, height: int) -> list[float] | None:
    """A model detection's box (``[x0, y0, x1, y1]``, detector px) as the box rules draw its class (``x, y, w, h``):
    the fixed-size boxes centred on its middle (a tower standing on its bottom), a hall's as found. None when less
    than a pixel is left on the screenshot."""
    x0, y0, x1, y1 = (float(v) for v in detection["box"])
    x, y = (x0 + x1) / 2, (y0 + y1) / 2
    name = detection["family"]
    if name == "node":
        box = box_at_point(x, y, DK.RF_DETR_MAP_BOX, DK.RF_DETR_MAP_BOX, width, height)
    elif name == "icon":
        box = box_at_point(x, y, DK.RF_DETR_ICON_BOX, DK.RF_DETR_ICON_BOX, width, height)
    elif name == "button":
        box = box_at_point(x, y, *DK.RF_DETR_BUTTON_BOX, width, height)
    elif name == "citadel":
        box = box_at_point(x, y, DK.RF_DETR_LANDMARK_BOX, DK.RF_DETR_LANDMARK_BOX, width, height)
    elif name == "stronghold":
        box = box_at_point(x, y, DK.RF_DETR_STRONGHOLD_BOX, DK.RF_DETR_STRONGHOLD_BOX, width, height)
    elif name == "tower":
        box = box_at_point(x, y1, DK.RF_DETR_TOWER_WIDTH, DK.RF_DETR_TOWER_HEIGHT, width, height, anchor="base")
    else:  # a hall (its node and structure), a path, a wall: the model's own box
        box = clip_box(x0, y0, x1, y1, width, height)
    return None if box is None else [float(v) for v in box]


def model_annotations(
    detections: Iterable[Mapping[str, Any]], detector_size: tuple[int, int], raw_size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Model detections (detector px) as annotations in the screenshot's own pixels, snapped to the box rules."""
    width, height = detector_size
    sx, sy = raw_size[0] / width, raw_size[1] / height
    out = []
    for detection in detections:
        box = snap(detection, width, height)
        if box is None:
            continue
        bbox = [round(box[0] * sx, 2), round(box[1] * sy, 2), round(box[2] * sx, 2), round(box[3] * sy, 2)]
        out.append(
            {
                "label": detection["label"],
                "bbox": bbox,
                "area": round(bbox[2] * bbox[3], 2),
                "iscrowd": 0,
                "source": DK.RF_DETR_SOURCE_MODEL_GUESS,
                "score": round(float(detection["score"]), 4),
            }
        )
    return out


def merge(
    classical: Sequence[Mapping[str, Any]],
    model: Sequence[Mapping[str, Any]],
    policy: str,
    *,
    width: float = DETECTOR_WIDTH,
) -> list[dict[str, Any]]:
    """Join a screenshot's classical pre-labels and a model's boxes (``ANNOTATOR_PRELABEL_POLICIES``).

    Args:
        classical: the current pre-labels (the classical detector's, maybe truth-seeded).
        model: the model's annotations (``model_annotations``).
        policy: ``classical`` (the pre-labels as they are), ``model`` (the model's boxes; a hand truth's or a
            reviewer's box is kept in place of the model's there), ``relabel`` (the pre-labels, with the class of the
            model's box each matches) or ``union`` (those, plus the model's boxes no pre-label matches).
        width: the screenshot's width in the boxes' pixels (the match radii are the detector's 1080p ones).

    Returns:
        The pre-labels to show.
    """
    if policy not in K.ANNOTATOR_PRELABEL_POLICIES:
        raise ValueError(f"unknown pre-label policy {policy!r}: one of {', '.join(K.ANNOTATOR_PRELABEL_POLICIES)}")
    if policy == "classical":
        return [dict(a) for a in classical]
    if policy == "model":
        # the model's boxes in place of the classical ones, but a hand truth's or a reviewer's box stays as it is
        protected = [a for a in classical if a.get("source") in PROTECTED_SOURCES]
        return merge(protected, model, "union", width=width)
    scale = width / DETECTOR_WIDTH
    out = [dict(a) for a in classical]
    matched_model: set[int] = set()
    for name in sorted({box_family(a) for a in (*classical, *model)}):
        mine = [i for i, a in enumerate(out) if box_family(a) == name and corners(a) is not None]
        theirs = [j for j, a in enumerate(model) if box_family(a) == name and corners(a) is not None]
        radius = DK.RF_DETR_EVAL_RADIUS.get(name, max(DK.RF_DETR_EVAL_RADIUS.values())) * scale
        pairs = match_boxes([corners(out[i]) for i in mine], [corners(model[j]) for j in theirs], radius)
        for a, b in pairs:
            box, theirs_box = out[mine[a]], model[theirs[b]]
            matched_model.add(theirs[b])
            if box.get("source") in PROTECTED_SOURCES:
                continue
            if box["label"] == theirs_box["label"]:
                box["source"] = DK.RF_DETR_SOURCE_MODEL  # both say so: no longer a guess
            else:
                box["label"] = theirs_box["label"]
                box["source"] = DK.RF_DETR_SOURCE_MODEL_GUESS  # the model changed the class: check it first
            box["score"] = theirs_box.get("score")
    if policy == "union":
        out += [dict(a) for j, a in enumerate(model) if j not in matched_model]
    return out


def predict(detector: Mapping[str, Any], path: Path) -> tuple[list[dict[str, Any]], tuple[int, int], tuple[int, int]]:
    """A model's detections on a screenshot (detector px), the detector's size and the file's size.

    Raises:
        ValueError: the screenshot cannot be read.
    """
    from grand_project.detect.rf_detr_model import predict_tiles

    from .detection import decode_image

    raw = decode_image(path)
    if raw is None:
        raise ValueError(f"Could not read image: {path}")
    image = core.scale_screenshot(raw)
    found = predict_tiles(
        detector["model"],
        detector["processor"],
        image,
        detector["families"],
        detector["device"],
        threshold=DK.RF_DETR_SCORE_THRESHOLD,
    )
    return found, (image.shape[1], image.shape[0]), (raw.shape[1], raw.shape[0])


def trained_on(model_dir: Path) -> set[str]:
    """The screenshots (project-relative paths) a model trained on."""
    listed = model_dir / DK.RF_DETR_TRAINED_ON
    if not listed.is_file():
        return set()
    return {line.strip() for line in listed.read_text(encoding="utf-8").splitlines() if line.strip()}


def eligible(items: Iterable[tuple[str, Mapping[str, Any]]], skip: set[str]) -> list[tuple[str, Mapping[str, Any]]]:
    """The screenshots model pre-labels may go to: detected, unreviewed, training split, no reviewer's box, not
    pre-labelled by a model yet, not seeded by a hand truth (``ANNOTATOR_TRUTH_MARK``: its boxes are the truth's, and
    a truth-seeded training round takes them as such), and not among ``skip`` (the model's own training
    screenshots)."""
    out = []
    for key, item in items:
        if not item.get("detected") or item.get("reviewed") or item.get("split") != "train":
            continue
        if item.get("source") in skip or item.get(K.ANNOTATOR_PRELABEL_FIELD):
            continue
        if item.get(K.ANNOTATOR_TRUTH_MARK):
            continue  # a hand truth pre-labelled it, and a truth-seeded round trusts its boxes (train_rf_detr)
        if any(a.get("source") == K.ANNOTATOR_MANUAL_SOURCE for a in item.get("annotations", [])):
            continue
        out.append((key, item))
    return out


def draw_arms(blocks: Mapping[str, str], share: float, seed: int) -> dict[str, str]:
    """Image key -> its arm (``rf_detr`` or ``classical``): a ``share`` of the blocks (rounded) get the model, by a
    seeded draw of whole blocks (neighbouring screenshots overlap: one block, one arm).

    Args:
        blocks: image key -> its spatial block (the ledger's; a key of its own when it has none).
        share: the fraction of blocks the model pre-labels.
        seed: the draw's seed.
    """
    names = sorted(set(blocks.values()))
    random.Random(seed).shuffle(names)
    chosen = set(names[: round(share * len(names))])
    return {
        key: DK.RF_DETR_SOURCE_MODEL if block in chosen else K.ANNOTATOR_CLASSICAL_SOURCE
        for key, block in blocks.items()
    }


def _blocks(items: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, str]:
    """Image key -> its ledger block (by its project-relative file; the key itself when the ledger has none)."""
    from .split_ledger import read_ledger

    by_file = {entry.file: entry.block for entry in read_ledger().values()}
    return {key: by_file.get(str(item.get("source")), "") or key for key, item in items}


def main(argv: list[str] | None = None) -> int:
    """Pre-label the eligible training screenshots: a share of their blocks by the model, the rest classical."""
    from .state import resolve_path
    from .store import ReviewStore

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, default=DK.RF_DETR_DEFAULT_MODEL_DIR, help="a fine-tuned model folder")
    parser.add_argument("--share", type=float, default=0.5, help="fraction of the blocks the model pre-labels")
    parser.add_argument("--seed", type=int, default=0, help="the draw of the blocks")
    parser.add_argument("--policy", default=K.ANNOTATOR_PRELABEL_POLICY, choices=K.ANNOTATOR_PRELABEL_POLICIES)
    parser.add_argument("--limit", type=int, default=None, help="pre-label at most this many screenshots")
    parser.add_argument("--dry-run", action="store_true", help="say what would be pre-labelled, change nothing")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    args = parser.parse_args(argv)
    if not 0.0 <= args.share <= 1.0:
        parser.error("--share must be between 0 and 1")
    model_dir = resolve_path(args.model)
    from .state import file_hash

    model_sha = file_hash(model_dir / "model.safetensors") if (model_dir / "model.safetensors").is_file() else None
    round_name = f"{model_dir.parent.name}/{model_dir.name} {time.strftime('%Y-%m-%d %H:%M')}"
    with ReviewStore.open(resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE) as store:
        todo = eligible(store.items(), trained_on(model_dir))
        if args.limit is not None:
            todo = todo[: args.limit]
        arms = draw_arms(_blocks(todo), args.share, args.seed)
        counts = {arm: sum(1 for value in arms.values() if value == arm) for arm in set(arms.values())}
        print(f"{len(todo)} screenshots eligible; arms {counts} (policy {args.policy}, model {model_dir})")
        if args.dry_run or not todo:
            return 0
        detector = None
        done = skipped = 0
        for key, item in todo:
            if item.get("split") != "train":  # never: eligible() takes training screenshots only (user's rule)
                raise RuntimeError(f"refusing to pre-label a {item.get('split')} screenshot: {item['path']}")
            record = {"source": arms[key], "policy": args.policy, "round": round_name}
            if arms[key] == K.ANNOTATOR_CLASSICAL_SOURCE:
                store.save_review(key, int(item["edit_version"]), extra={K.ANNOTATOR_PRELABEL_FIELD: record})
                continue
            if detector is None:
                from grand_project.detect.rf_detr_model import load_detector

                detector = load_detector(model_dir)
            found, detector_size, raw_size = predict(detector, Path(item["path"]))
            model = model_annotations(found, detector_size, raw_size)
            boxes = merge(store.prelabels(key), model, args.policy, width=raw_size[0])
            record.update(model=str(model_dir), model_sha=model_sha, found=len(model))
            if store.save_review(
                key,
                int(item["edit_version"]),
                annotations=boxes,
                prelabel=True,
                extra={K.ANNOTATOR_PRELABEL_FIELD: record},
                untouched=True,  # a screenshot reviewed or edited meanwhile (the page is open) keeps its review
            ):
                done += 1
                if done % 50 == 0:
                    print(f"  {done} pre-labelled", flush=True)
            else:
                skipped += 1
        print(
            f"done: {done} screenshots pre-labelled by the model, {skipped} left (reviewed, edited or detected "
            f"again meanwhile) ({json.dumps(counts)})"
        )
    return 0


__all__ = ["draw_arms", "eligible", "merge", "model_annotations", "predict", "snap", "trained_on"]


if __name__ == "__main__":
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    raise SystemExit(main())
