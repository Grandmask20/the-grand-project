"""Task metrics for RF-DETR checkpoints: how well they find each family of objects, and name them within it.

The program uses where objects are (box middles), not how tight their boxes are, so predictions are matched to the
labelled boxes as ``python -m grand_project.detect score`` matches the hand truth: by the distance between middles,
within a radius per family (``RF_DETR_EVAL_RADIUS``). Per family:

- average precision (all-point interpolated, predictions in score order, each labelled box matched once);
- precision, recall and F1 at the detector's threshold (``RF_DETR_SCORE_THRESHOLD``);
- class accuracy: of the matched pairs at the threshold, the share whose class is right (the biome or city of a
  map node, the type of a citadel); a family of one class is always right.

``mean_ap``, the mean of the families' average precision (families with labelled boxes), picks the best checkpoint
(the paper picks by validation metrics; validation loss does not say what the program needs).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from . import constants as K
from .labels import family


def _middle(item: dict[str, Any]) -> tuple[float, float]:
    """The middle of a box: "x", "y" given, else the middle of "box" ``[x0, y0, x1, y1]``."""
    if "x" in item and "y" in item:
        return float(item["x"]), float(item["y"])
    x0, y0, x1, y1 = item["box"]
    return (float(x0) + float(x1)) / 2, (float(y0) + float(y1)) / 2


def average_precision(tp: Sequence[bool], total: int) -> float:
    """All-point interpolated average precision of predictions in score order.

    Args:
        tp: for each prediction (best score first), whether it matched a labelled box.
        total: how many labelled boxes there are.

    Returns:
        The area under the interpolated precision-recall curve (0 without labelled boxes).
    """
    if total <= 0:
        return 0.0
    hits = np.cumsum(np.asarray(tp, float))
    if not len(hits):
        return 0.0
    precision = hits / np.arange(1, len(hits) + 1)
    recall = hits / total
    # interpolate: the precision at each recall is the best precision at that recall or more
    precision = np.maximum.accumulate(precision[::-1])[::-1]
    previous = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - previous) * precision))


def _match_family(
    predictions: list[list[dict[str, Any]]], truths: list[list[dict[str, Any]]], radius: float
) -> tuple[list[tuple[float, bool, bool]], int]:
    """Greedily match one family's predictions to its labelled boxes, best score first, image by image.

    Returns:
        ([(score, matched, right class) per prediction in score order], how many labelled boxes there are).
    """
    ranked = sorted(
        ((float(p["score"]), image, p) for image, preds in enumerate(predictions) for p in preds),
        key=lambda item: -item[0],
    )
    taken = [np.zeros(len(t), bool) for t in truths]
    middles = [np.array([_middle(t) for t in boxes], float).reshape(-1, 2) for boxes in truths]
    out = []
    for score, image, pred in ranked:
        if not len(middles[image]):
            out.append((score, False, False))
            continue
        x, y = _middle(pred)
        dist = np.hypot(middles[image][:, 0] - x, middles[image][:, 1] - y)
        dist[taken[image]] = np.inf
        best = int(np.argmin(dist))
        if dist[best] <= radius:
            taken[image][best] = True
            out.append((score, True, truths[image][best]["label"] == pred["label"]))
        else:
            out.append((score, False, False))
    return out, sum(len(t) for t in truths)


def evaluate(
    predictions: list[list[dict[str, Any]]],
    truths: list[list[dict[str, Any]]],
    *,
    threshold: float = K.RF_DETR_SCORE_THRESHOLD,
) -> dict[str, Any]:
    """Score predictions against labelled boxes, family by family.

    Args:
        predictions: per image, the predictions: "label", "score" and "x", "y" or "box" ``[x0, y0, x1, y1]``.
        truths: per image, the labelled boxes: "label" and "x", "y" or "box".
        threshold: the score from which a prediction counts for precision, recall, F1 and class accuracy.

    Returns:
        {"families": {family: {"ap", "precision", "recall", "f1", "class_accuracy", "truths", "predictions"}},
         "mean_ap": the mean ap of the families with labelled boxes}.
    """
    if len(predictions) != len(truths):
        raise ValueError("predictions and truths must cover the same images")
    families = sorted({family(item["label"]) or item["label"] for boxes in (*predictions, *truths) for item in boxes})
    report: dict[str, Any] = {}
    for name in families:

        def mine(boxes: list[dict[str, Any]], name: str = name) -> list[dict[str, Any]]:
            return [item for item in boxes if (family(item["label"]) or item["label"]) == name]

        preds = [mine(boxes) for boxes in predictions]
        labelled = [mine(boxes) for boxes in truths]
        radius = K.RF_DETR_EVAL_RADIUS.get(name, max(K.RF_DETR_EVAL_RADIUS.values()))
        matches, total = _match_family(preds, labelled, radius)
        kept = [m for m in matches if m[0] >= threshold]
        tp = sum(1 for _score, hit, _right in kept if hit)
        precision = tp / len(kept) if kept else 0.0
        recall = tp / total if total else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        right = sum(1 for _score, hit, ok in kept if hit and ok)
        report[name] = {
            "ap": average_precision([hit for _score, hit, _right in matches], total),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "class_accuracy": right / tp if tp else 0.0,
            "truths": total,
            "predictions": len(kept),
        }
    scored = [values["ap"] for values in report.values() if values["truths"]]
    return {"families": report, "mean_ap": float(np.mean(scored)) if scored else 0.0}


def format_report(result: dict[str, Any]) -> str:
    """The evaluation as a small table, one family a line."""
    lines = [f"{'family':<11} {'AP':>6} {'P':>6} {'R':>6} {'F1':>6} {'class':>6} {'boxes':>6}"]
    for name, v in sorted(result["families"].items()):
        lines.append(
            f"{name:<11} {v['ap']:6.3f} {v['precision']:6.3f} {v['recall']:6.3f} {v['f1']:6.3f} "
            f"{v['class_accuracy']:6.3f} {v['truths']:6d}"
        )
    lines.append(f"mean AP {result['mean_ap']:.4f}")
    return "\n".join(lines)


__all__ = ["average_precision", "evaluate", "format_report"]
