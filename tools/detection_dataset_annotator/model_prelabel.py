"""Model pre-labels: a fine-tuned RF-DETR checkpoint relabels the classical detector's boxes, for the next round of
review (classical detection and an ever-refined model take turns).

    python -m tools.detection_dataset_annotator.model_prelabel --model runs/rf-detr-small/best
        [--limit N] [--dry-run] [--output-dir D]

Only unreviewed **training** screenshots without a reviewer's box are pre-labelled: a validation or test screenshot
reviewed from a model's pre-labels would lean toward the model, and the model would then be scored on its own
answers (user's rule: held-out screenshots keep the classical pre-labels). The screenshots the model trained on
(``RF_DETR_TRAINED_ON`` in its folder) are left too: their pre-labels would only replay its training labels; so are
the ones a hand truth seeded (a truth-seeded round trusts their boxes). A screenshot reviewed, edited, truth-seeded or
pre-labelled by another pass while this one runs (the page open beside it) keeps what it has: each save checks that
first, in the same write.

The model's boxes are snapped to the box rules (``snap``) and matched to the screenshot's current pre-labels
(``merge``): a box the model and the classical detector agree on is ``rf_detr``, one whose class the model changed a
dotted ``rf_detr_guess``; the classical boxes stay where they are. A box a hand truth set (``biome_truth``) or a
reviewer drew keeps its class. Each pre-labelled screenshot records the pass (``ANNOTATOR_PRELABEL_FIELD``).
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from grand_project import core
from grand_project.detect import constants as DK
from grand_project.detect.labels import export_class
from grand_project.detect.labels import family as label_family
from grand_project.detect.proposals import box_at_point, clip_box
from grand_project.detect.rf_detr_model import model_folder, trained_on

from . import constants as K

PROTECTED_SOURCES = frozenset({K.ANNOTATOR_TRUTH_SOURCE, K.ANNOTATOR_MANUAL_SOURCE})
"""Box sources whose class the model never changes: a hand truth's, a reviewer's."""


def box_family(annotation: Mapping[str, Any]) -> str:
    """A box's family (a map node is one of the node classes), else its own label."""
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


def match_boxes(before: Sequence[np.ndarray], after: Sequence[np.ndarray], radius: float) -> list[tuple[int, int]]:
    """One-to-one pairs (before, after) whose middles lie within ``radius``: the most pairs, then the closest, by an
    optimal assignment (a greedy match can pair a box with its neighbour's)."""
    if not before or not after:
        return []
    middles_before = np.array([((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in before])
    middles_after = np.array([((a[0] + a[2]) / 2, (a[1] + a[3]) / 2) for a in after])
    distance = np.hypot(*(middles_before[:, None, :] - middles_after[None, :, :]).transpose(2, 0, 1))
    reach = distance <= radius
    # out of reach costs more than any assignment's summed distances (at most min(n, m) pairs, each within radius),
    # so one reachable pair more always wins
    never = (min(len(before), len(after)) + 1) * radius + 1.0
    rows, cols = linear_sum_assignment(np.where(reach, distance, never))
    return [(int(r), int(c)) for r, c in zip(rows, cols, strict=True) if reach[r, c]]


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
    else:  # a hall (its node and structure), a reviewer's own label: the model's own box
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
    classical: Sequence[Mapping[str, Any]], model: Sequence[Mapping[str, Any]], *, scale: float = 1.0
) -> list[dict[str, Any]]:
    """A screenshot's pre-labels with the class of the model's box each matches (in its family, within the
    family's ``RF_DETR_EVAL_RADIUS``); a hand truth's or a reviewer's box keeps its class.

    Args:
        classical: the current pre-labels (the classical detector's, maybe truth-seeded).
        model: the model's annotations (``model_annotations``).
        scale: the boxes' pixels per detector pixel (the match radii are the detector's).

    Returns:
        The pre-labels to show.
    """
    out = [dict(a) for a in classical]
    for name in sorted({box_family(a) for a in (*classical, *model)}):
        mine = [i for i, a in enumerate(out) if box_family(a) == name and corners(a) is not None]
        theirs = [j for j, a in enumerate(model) if box_family(a) == name and corners(a) is not None]
        radius = DK.RF_DETR_EVAL_RADIUS.get(name, max(DK.RF_DETR_EVAL_RADIUS.values())) * scale
        pairs = match_boxes([corners(out[i]) for i in mine], [corners(model[j]) for j in theirs], radius)
        for a, b in pairs:
            box, theirs_box = out[mine[a]], model[theirs[b]]
            if box.get("source") in PROTECTED_SOURCES:
                continue
            # a named classical icon (icon_mapboss ...) is the model's one icon class: both say so, the name stays
            if theirs_box["label"] in (box["label"], export_class(str(box["label"]))):
                box["source"] = DK.RF_DETR_SOURCE_MODEL  # both say so: no longer a guess
            else:
                box["label"] = theirs_box["label"]
                box["source"] = DK.RF_DETR_SOURCE_MODEL_GUESS  # the model changed the class: check it first
            box["score"] = theirs_box.get("score")
    return out


class UnreadableScreenshot(ValueError):
    """A screenshot file that cannot be read (missing, damaged): ``predict``'s, apart from the model's own errors."""


class ChangedScreenshot(ValueError):
    """A screenshot file that is not the bytes its boxes were detected on (``state.changed_since_detection``)."""


def predict(
    detector: Mapping[str, Any], path: Path, *, detected: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], tuple[int, int], tuple[int, int]]:
    """A model's detections on a screenshot (detector px), the detector's size and the file's size.

    Args:
        detector: ``load_detector``'s model.
        path: the screenshot.
        detected: its store item, when the model's boxes join its detected ones: the bytes decoded here must be the
            ones they were detected on (checked on the same read).

    Raises:
        UnreadableScreenshot: the screenshot cannot be read.
        ChangedScreenshot: it is not the file ``detected``'s boxes were detected on.
    """
    from grand_project.detect.rf_detr_model import predict_tiles

    from .detection import read_with_digest
    from .state import changed_since_detection

    read = read_with_digest(path)
    if read is None:
        raise UnreadableScreenshot(f"Could not read image: {path}")
    raw, digest = read
    if detected is not None and changed_since_detection(detected, digest):
        raise ChangedScreenshot(f"{path} changed since its detection: rerun its detection")
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


def checkpoint_state(model_dir: Path) -> tuple[str | None, frozenset[str] | None]:
    """What identifies a kept model's state: the SHA-256 of its weights (None without them) and the screenshots it
    trained on (``trained_on``; None when it has no list of them: not known, which is not the same as a list of
    none)."""
    from .state import file_hash

    weights = model_dir / "model.safetensors"
    sha = file_hash(weights) if weights.is_file() else None
    trained = trained_on(model_dir)
    return sha, None if trained is None else frozenset(trained)


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


def main(argv: list[str] | None = None) -> int:
    """Pre-label the eligible training screenshots with the model's classes."""
    from .state import resolve_path
    from .store import ReviewStore

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model",
        default=str(DK.RF_DETR_DEFAULT_MODEL_DIR),
        help="a fine-tuned model folder, or its Hugging Face id (owner/name[@revision])",
    )
    parser.add_argument("--limit", type=int, default=None, help="pre-label at most this many screenshots")
    parser.add_argument("--dry-run", action="store_true", help="say what would be pre-labelled, change nothing")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be 0 or more")  # a negative one would count from the end of the list
    local = resolve_path(args.model)  # a relative folder is the project's
    model_dir = local if local.is_dir() else model_folder(args.model)
    # what the pass records: the folder as the runs name it, or the Hub id
    model_name = f"{model_dir.parent.name}/{model_dir.name}" if model_dir == local else args.model
    # the weights' hash and the screenshots they trained on, read once: the weights loaded later must be these
    checkpoint = checkpoint_state(model_dir)
    model_sha, trained = checkpoint
    if trained is None:
        # nothing is known of what it trained on: its own training screenshots would be taken for new ones, and
        # pre-labelled with what they were trained to say
        raise SystemExit(
            f"{model_dir} lists no training screenshots ({DK.RF_DETR_TRAINED_ON}): train it again with "
            "tools.train_rf_detr, which writes the list"
        )
    round_name = f"{model_name} {time.strftime('%Y-%m-%d %H:%M')}"
    store_path = resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE
    if not store_path.is_file():  # opening it would create an empty store (and its folder)
        print(f"0 screenshots eligible: no annotator store at {store_path}")
        return 0
    # a dry run reads the store only: no journal change
    with ReviewStore.open(store_path, read_only=args.dry_run) as store:
        todo = eligible(store.items(), set(trained))
        limit = "" if args.limit is None else f", at most {args.limit} this pass"
        print(f"{len(todo)} screenshots eligible (model {model_dir}{limit})")
        if args.dry_run or not todo:
            return 0
        detector = None
        done = skipped = 0
        # a screenshot reviewed, edited, truth-seeded or pre-labelled by another pass meanwhile (the page or another
        # tool open beside this one) keeps what it has: every save checks that in its own write
        # and stays a training screenshot (held-out ones never get model pre-labels: user's rule)
        guard = {
            "untouched": True,
            "unmarked": (K.ANNOTATOR_TRUTH_MARK, K.ANNOTATOR_PRELABEL_FIELD),
            "split": "train",
        }
        # --limit counts the screenshots saved, not the ones tried: one left (unreadable, edited meanwhile) is tried
        # once in this pass and stays eligible, and the next one is taken instead
        for key, item in todo:
            if args.limit is not None and done >= args.limit:
                break
            if item.get("split") != "train":  # never: eligible() takes training screenshots only (user's rule)
                raise RuntimeError(f"refusing to pre-label a {item.get('split')} screenshot: {item['path']}")
            if detector is None:
                from grand_project.detect.rf_detr_model import load_detector

                detector = load_detector(model_dir)
                if checkpoint_state(model_dir) != checkpoint:
                    # train_rf_detr swaps a new best/ in by renaming the folder: the weights just loaded may not be
                    # the ones hashed and whose training screenshots were left out
                    raise SystemExit(
                        f"{model_dir} changed while this pass ran (a training run kept a new best): run it again"
                    )
            base = store.prelabels(key)  # what the model's boxes are joined with: unchanged until the save
            try:
                # the bytes the model sees are the ones the boxes were detected on (else they would frame another
                # picture): checked on the read predict makes
                found, detector_size, raw_size = predict(detector, Path(item["path"]), detected=item)
            except (UnreadableScreenshot, ChangedScreenshot) as error:
                # left as it is, still eligible: a later pass takes it once it can be read (or is detected again)
                print(f"  {item['source']}: {error} (left)")
                skipped += 1
                continue
            model = model_annotations(found, detector_size, raw_size)
            boxes = merge(base, model, scale=raw_size[0] / detector_size[0])
            record = {
                "source": DK.RF_DETR_SOURCE_MODEL,
                "round": round_name,
                "model": str(model_dir) if model_dir == local else args.model,
                "model_sha": model_sha,
                "found": len(model),
            }
            if store.save_review(
                key,
                int(item["edit_version"]),
                annotations=boxes,
                prelabel=True,
                extra={K.ANNOTATOR_PRELABEL_FIELD: record},
                expect_boxes=base,
                # the stored detection is still of the bytes predict read (checked in this write)
                marked={K.ANNOTATOR_DETECTED_SHA: item.get(K.ANNOTATOR_DETECTED_SHA)},
                **guard,
            ):
                done += 1
                if done % 50 == 0:
                    print(f"  {done} pre-labelled", flush=True)
            else:
                skipped += 1
        print(
            f"done: {done} screenshots pre-labelled by the model, {skipped} left (unreadable, changed since its "
            "detection, or reviewed, edited, seeded or detected again meanwhile)"
        )
    return 0


__all__ = [
    "ChangedScreenshot",
    "UnreadableScreenshot",
    "checkpoint_state",
    "eligible",
    "merge",
    "model_annotations",
    "predict",
    "snap",
    "trained_on",
]


if __name__ == "__main__":
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    raise SystemExit(main())
