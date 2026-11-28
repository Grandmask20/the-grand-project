"""Model pre-labels: a fine-tuned RF-DETR checkpoint proposes boxes beside the classical detector's, for the next
round of review (the iterative loop: classical detection and an ever-refined model take turns).

    python -m tools.detection_dataset_annotator.model_prelabel --model runs/rf-detr-small/best
        [--share 0.5] [--seed S] [--policy union] [--limit N] [--dry-run] [--output-dir D]

Only unreviewed **training** screenshots without a reviewer's box are pre-labelled: a validation or test screenshot
reviewed from a model's pre-labels would lean toward the model, and the model would then be scored on its own
answers (user's rule: held-out screenshots keep the classical pre-labels). The screenshots the model trained on
(``RF_DETR_TRAINED_ON`` in its folder) are left too: their pre-labels would only replay its training labels; so are
the ones a hand truth seeded (a truth-seeded round trusts their boxes). A screenshot reviewed, edited, truth-seeded or
pre-labelled by another pass while this one runs (the page open beside it) keeps what it has: each save checks that
first, in the same write.

The loop is measured as an A/B test: the eligible screenshots' spatial blocks (the split ledger's) are drawn, a
``--share`` of them get the model's pre-labels and the others keep the classical ones, and every screenshot records
its arm (``ANNOTATOR_PRELABEL_FIELD``), so ``effort`` compares the arms' review edits and times. Each block's arm is
planned in the store before any work (``ReviewStore.claim_prelabel_arms``): a block keeps it, and so does one an
earlier pass gave an arm (``recorded_arms``), for its later screenshots and after a pass that failed (its screenshots
stay eligible until their arm's work is saved).

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
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from grand_project import core
from grand_project.detect import constants as DK
from grand_project.detect.labels import export_class
from grand_project.detect.proposals import box_at_point, clip_box
from grand_project.detect.rf_detr_model import trained_on

from . import constants as K
from .effort import box_family, corners, match_boxes

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
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    """Join a screenshot's classical pre-labels and a model's boxes (``ANNOTATOR_PRELABEL_POLICIES``).

    Args:
        classical: the current pre-labels (the classical detector's, maybe truth-seeded).
        model: the model's annotations (``model_annotations``).
        policy: ``classical`` (the pre-labels as they are), ``model`` (the model's boxes; a hand truth's or a
            reviewer's box is kept in place of the model's there), ``relabel`` (the pre-labels, with the class of the
            model's box each matches) or ``union`` (those, plus the model's boxes no pre-label matches).
        scale: the boxes' pixels per detector pixel (``effort.pixel_scale``; the match radii are the detector's).

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
        return merge(protected, model, "union", scale=scale)
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
            # a named classical icon (icon_mapboss ...) is the model's one icon class: both say so, the name stays
            if theirs_box["label"] in (box["label"], export_class(str(box["label"]))):
                box["source"] = DK.RF_DETR_SOURCE_MODEL  # both say so: no longer a guess
            else:
                box["label"] = theirs_box["label"]
                box["source"] = DK.RF_DETR_SOURCE_MODEL_GUESS  # the model changed the class: check it first
            box["score"] = theirs_box.get("score")
    if policy == "union":
        out += [dict(a) for j, a in enumerate(model) if j not in matched_model]
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


def checkpoint_state(model_dir: Path) -> tuple[str | None, frozenset[str]]:
    """What identifies a kept model's state: the SHA-256 of its weights (None without them) and the screenshots it
    trained on (``trained_on``)."""
    from .state import file_hash

    weights = model_dir / "model.safetensors"
    return (file_hash(weights) if weights.is_file() else None), frozenset(trained_on(model_dir))


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


def draw_arms(
    blocks: Mapping[str, str], share: float, seed: int, given: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Image key -> its arm (``rf_detr`` or ``classical``): a block that already has an arm keeps it (``given``);
    of the others a ``share`` (rounded) get the model, by a seeded draw of whole blocks (neighbouring screenshots
    overlap: one block, one arm).

    Args:
        blocks: image key -> its spatial block (the ledger's; a key of its own when it has none).
        share: the fraction of the new blocks the model pre-labels.
        seed: the draw's seed.
        given: block -> the arm an earlier pass gave its screenshots (``recorded_arms``).
    """
    given = dict(given or {})
    names = sorted(set(blocks.values()) - set(given))
    random.Random(seed).shuffle(names)
    chosen = set(names[: round(share * len(names))])
    arm = {block: DK.RF_DETR_SOURCE_MODEL if block in chosen else K.ANNOTATOR_CLASSICAL_SOURCE for block in names}
    return {key: given.get(block) or arm[block] for key, block in blocks.items()}


def recorded_arms(items: Iterable[tuple[str, Mapping[str, Any]]], blocks: Mapping[str, str]) -> dict[str, str]:
    """Block -> the arm earlier passes gave its screenshots (``ANNOTATOR_PRELABEL_FIELD``; the most common one), so a
    block's later screenshots (a ``--limit`` pass, newly detected ones) join the same arm."""
    counts: dict[str, Counter[str]] = {}
    for key, item in items:
        arm = (item.get(K.ANNOTATOR_PRELABEL_FIELD) or {}).get("source")
        if arm and key in blocks:
            counts.setdefault(blocks[key], Counter())[str(arm)] += 1
    return {block: arms.most_common(1)[0][0] for block, arms in counts.items()}


def _blocks(items: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, str]:
    """Image key -> its ledger block: the row of its file and detected bytes, else its file's rows when they all name
    one block (a copy's own name too; rows that disagree decide nothing), else the key itself."""
    from .split_ledger import read_ledger_rows

    exact: dict[tuple[str, str], str] = {}
    by_file: dict[str, set[str]] = {}
    for entry in read_ledger_rows():
        exact.setdefault((entry.file, entry.sha256), entry.block)
        by_file.setdefault(entry.file, set()).add(entry.block)
    out = {}
    for key, item in items:
        source = str(item.get("source"))
        block = exact.get((source, str(item.get(K.ANNOTATOR_DETECTED_SHA))))
        if block is None and len(by_file.get(source, ())) == 1:
            (block,) = by_file[source]
        out[key] = block or key
    return out


def main(argv: list[str] | None = None) -> int:
    """Pre-label the eligible training screenshots: a share of their blocks by the model, the rest classical."""
    from .split_ledger import _ledger_lock
    from .state import resolve_path
    from .store import ReviewStore

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, default=DK.RF_DETR_DEFAULT_MODEL_DIR, help="a fine-tuned model folder")
    parser.add_argument("--share", type=float, default=0.5, help="fraction of the blocks the model pre-labels")
    parser.add_argument("--seed", type=int, default=0, help="the draw of the blocks")
    # "classical" gives no model boxes: its screenshots would join the model's arm with the classical pre-labels
    policies = [policy for policy in K.ANNOTATOR_PRELABEL_POLICIES if policy != K.ANNOTATOR_CLASSICAL_SOURCE]
    parser.add_argument("--policy", default=K.ANNOTATOR_PRELABEL_POLICY, choices=policies)
    parser.add_argument("--limit", type=int, default=None, help="pre-label at most this many screenshots")
    parser.add_argument("--dry-run", action="store_true", help="say what would be pre-labelled, change nothing")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    args = parser.parse_args(argv)
    if not 0.0 <= args.share <= 1.0:
        parser.error("--share must be between 0 and 1")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be 0 or more")  # a negative one would count from the end of the list
    model_dir = resolve_path(args.model)
    # the weights' hash and the screenshots they trained on, read once: the weights loaded later must be these
    checkpoint = checkpoint_state(model_dir)
    model_sha, trained = checkpoint
    round_name = f"{model_dir.parent.name}/{model_dir.name} {time.strftime('%Y-%m-%d %H:%M')}"
    store_path = resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE
    if not store_path.is_file():  # opening it would create an empty store (and its folder)
        print(f"0 screenshots eligible: no annotator store at {store_path}")
        return 0
    # a dry run reads the store only: no journal change, no plan written
    with ReviewStore.open(store_path, read_only=args.dry_run) as store:
        # the store and the ledger read in one step under the ledger's lock: an export settling splits claims them in
        # the store first and writes the ledger rows after (both under the lock), so a screenshot read between the
        # two had a training split but no block yet, and took one of its own (CodeRabbit)
        with _ledger_lock():
            every = list(store.items())
            blocks = _blocks(every)
        todo = eligible(every, set(trained))
        # every eligible block is drawn, whatever --limit leaves for later: the share is of all of them, not of a pass.
        # A block keeps the arm planned for it before (a pass that failed or stopped) or an earlier pass gave it.
        given = {**store.prelabel_plan(), **recorded_arms(every, blocks)}
        arms = draw_arms({key: blocks[key] for key, _item in todo}, args.share, args.seed, given)
        if not args.dry_run and todo:
            # planned before any work, so a model pass that fails leaves its blocks in the model's arm for the next
            plan = store.claim_prelabel_arms({blocks[key]: arms[key] for key, _item in todo})
            arms = {key: plan.get(blocks[key], arm) for key, arm in arms.items()}
        if args.limit is not None:
            todo = todo[: args.limit]
        counts = dict(Counter(arms[key] for key, _item in todo))
        members: dict[str, set[str]] = {}
        for key, block in blocks.items():
            members.setdefault(block, set()).add(key)
        print(f"{len(todo)} screenshots eligible; arms {counts} (policy {args.policy}, model {model_dir})")
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
        for key, item in todo:
            if item.get("split") != "train":  # never: eligible() takes training screenshots only (user's rule)
                raise RuntimeError(f"refusing to pre-label a {item.get('split')} screenshot: {item['path']}")
            record = {"source": arms[key], "policy": args.policy, "round": round_name}
            # its block's other screenshots have no other arm, checked in the save (another pass may run beside this)
            one_arm = {"arm_block": (members[blocks[key]], arms[key])}
            if arms[key] == K.ANNOTATOR_CLASSICAL_SOURCE:
                if not store.save_review(
                    key, int(item["edit_version"]), extra={K.ANNOTATOR_PRELABEL_FIELD: record}, **guard, **one_arm
                ):
                    skipped += 1
                continue
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
            boxes = merge(base, model, args.policy, scale=raw_size[0] / detector_size[0])
            record.update(model=str(model_dir), model_sha=model_sha, found=len(model))
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
                **one_arm,
            ):
                done += 1
                if done % 50 == 0:
                    print(f"  {done} pre-labelled", flush=True)
            else:
                skipped += 1
        print(
            f"done: {done} screenshots pre-labelled by the model, {skipped} left (unreadable, changed since its "
            "detection, or reviewed, edited, seeded, detected again or given another arm meanwhile) "
            f"({json.dumps(counts)})"
        )
    return 0


__all__ = [
    "ChangedScreenshot",
    "UnreadableScreenshot",
    "checkpoint_state",
    "draw_arms",
    "eligible",
    "merge",
    "model_annotations",
    "predict",
    "recorded_arms",
    "snap",
    "trained_on",
]


if __name__ == "__main__":
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    raise SystemExit(main())
