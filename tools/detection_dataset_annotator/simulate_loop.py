"""The iterative annotation loop, simulated on a hand-labelled atlas: does an ever-refined RF-DETR model, proposing
boxes with the classical detector, leave a reviewer fewer edits than the classical detector alone?

    python -m tools.detection_dataset_annotator.simulate_loop --manifest DATASET/manifest.json \\
        --classical-store DATASET/review_state.before-loop.sqlite3 [--rounds "8,2;0,3;1,4,6"] \\
        [--atlas atlas_test_data/fr-atlas/crawl_atlas_v076] [--output-dir runs/loop-sim] [--epochs 40] [--skip-train]

Each round reveals more of the atlas's training blocks (the split ledger's spatial blocks) as if a reviewer had
reviewed them, the review being the atlas's hand truth (its truth-seeded boxes: ``train_rf_detr --truth-seeded``),
and trains a model on everything revealed so far, starting from the previous round's model (``--init-from``), as
the live loop would. After each round the model pre-labels the atlas's validation and test screenshots, which no
round trains on, and every pre-label policy (``ANNOTATOR_PRELABEL_POLICIES``: the classical boxes, the model's, the
classical boxes relabelled by the model, and those plus the model's own finds) is scored with ``effort.edit_cost``
against the truth-seeded boxes:

- **gold**: what the hand truth knows. A matched map node's city area (each node class reduced to its city area or
  none: the truth says nothing about grass or water), and the citadels (the truth deletes false ones and types the
  rest; a City it reports without a citadel box was never drawn, so a model that finds one is counted as wrong).
- **silver**: everything else (map nodes found or not, icons, towers, halls, strongholds, reveal buttons) compared
  with the classical detector's boxes: disagreements, which in a real review are edits or fixes.

The classical policy's boxes are the classical detector's from before the truth was seeded (``--classical-store``:
the store as it was, kept when the store was rebuilt). The report (``report.md``, ``report.json``) gives the edits
per screenshot of every policy after every round: the learning curve of the loop.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from grand_project.detect import labels as L

from . import constants as K
from .effort import EDIT_KINDS, Edits, edit_cost, total
from .model_prelabel import merge, model_annotations, predict

GOLD_FAMILIES = ("node", "citadel")
"""The families the hand truth speaks about (a node only for its city area)."""

NO_CITY_AREA = "map_node"
"""What a node class outside every city area becomes for the gold score."""

DEFAULT_ROUNDS = "8,2;0,3;1,4,6"
"""fr-atlas's training blocks revealed per round (blocks #0-#8 but validation #7 and test #5): about 60, 190 and all
421 screenshots."""


def parse_rounds(text: str) -> list[list[str]]:
    """``"8,2;0,3"`` -> the block numbers each round adds (``[["8", "2"], ["0", "3"]]``)."""
    rounds = [[part.strip() for part in chunk.split(",") if part.strip()] for chunk in text.split(";")]
    if not rounds or any(not blocks for blocks in rounds):
        raise ValueError(f"no blocks in a round: {text!r}")
    return rounds


def revealed(ledger: Mapping[str, Any], atlas: str, rounds: Sequence[Sequence[str]]) -> list[list[str]]:
    """The training screenshots (project-relative files) revealed by each round, cumulative.

    Args:
        ledger: the split ledger (``read_ledger``: sha -> Entry).
        atlas: the atlas folder, as the ledger names its blocks (``<atlas>#<n>``).
        rounds: the block numbers each round adds.

    Raises:
        ValueError: a block that is not one of the atlas's training blocks.
    """
    blocks: dict[str, list[str]] = {}
    for entry in ledger.values():
        if entry.split == "train" and entry.block.startswith(f"{atlas}#"):
            blocks.setdefault(entry.block.rsplit("#", 1)[1], []).append(entry.file)
    out: list[list[str]] = []
    seen: list[str] = []
    for adds in rounds:
        for block in adds:
            if block not in blocks:
                raise ValueError(f"{atlas}#{block} is not a training block (training blocks: {sorted(blocks)})")
            seen += sorted(blocks[block])
        out.append(list(seen))
    return out


def city_area(annotation: Mapping[str, Any]) -> dict[str, Any]:
    """A node box with its class reduced to its city area (or ``NO_CITY_AREA``); other boxes as they are."""
    label = str(annotation.get("label", ""))
    if L.is_node(label) and L.city_type(label) is None:
        return {**annotation, "label": NO_CITY_AREA}
    return dict(annotation)


def score(
    prelabels: Sequence[Mapping[str, Any]], reference: Sequence[Mapping[str, Any]], *, width: float
) -> dict[str, Edits]:
    """A policy's pre-labels against the truth-seeded reference: ``gold`` (node city areas on matched nodes, the
    citadels) and ``silver`` (node finds and every other family, against the classical boxes)."""
    gold_nodes = edit_cost(
        [city_area(a) for a in prelabels], [city_area(a) for a in reference], width=width, families=["node"]
    ).get("node", Edits())
    citadels = edit_cost(prelabels, reference, width=width, families=["citadel"]).get("citadel", Edits())
    others = edit_cost(
        prelabels, reference, width=width, families=[f for f in _families(prelabels, reference) if f != "citadel"]
    )
    silver = total({name: edits for name, edits in others.items() if name != "node"})
    node = others.get("node", Edits())
    silver = silver + Edits(deleted=node.deleted, added=node.added)
    gold = Edits(kept=gold_nodes.kept, relabelled=gold_nodes.relabelled) + citadels
    return {"gold": gold, "silver": silver}


def _families(*sides: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({L.family(str(a.get("label", ""))) or str(a.get("label", "")) for side in sides for a in side})


def classical_boxes(store_path: Path) -> dict[str, list[dict[str, Any]]]:
    """The classical detector's boxes per screenshot (its project-relative file), read from a store copy without
    changing it."""
    out: dict[str, list[dict[str, Any]]] = {}
    # closing(): a connection's own ``with`` only ends a transaction, and an open file cannot be removed on Windows
    with closing(sqlite3.connect(f"file:{store_path.as_posix()}?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT images.source, annotations.label, annotations.x, annotations.y, annotations.w, annotations.h, "
            "annotations.source FROM annotations JOIN images ON images.key = annotations.image_key "
            "ORDER BY images.position, annotations.ord"
        )
        for source, label, x, y, w, h, box_source in rows:
            out.setdefault(source, []).append({"label": label, "bbox": [x, y, w, h], "source": box_source})
    return out


def held_out(manifest: Mapping[str, Any], atlas: str) -> dict[str, list[Mapping[str, Any]]]:
    """The atlas's truth-seeded validation and test screenshots of a manifest, by split."""
    out: dict[str, list[Mapping[str, Any]]] = {"validation": [], "test": []}
    for row in manifest.get("images", []):
        if row.get("split") in out and row.get(K.ANNOTATOR_TRUTH_MARK) and str(row.get("source", "")).startswith(atlas):
            out[row["split"]].append(row)
    return out


def train_round(
    args: argparse.Namespace, round_dir: Path, subset: list[str], previous: Path | None, dataset_dir: Path
) -> None:
    """Train one round's model in its own process (the GPU is free again after it)."""
    round_dir.mkdir(parents=True, exist_ok=True)
    subset_file = round_dir / "train_subset.txt"
    subset_file.write_text("".join(f"{name}\n" for name in subset), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "tools.train_rf_detr",
        "--truth-seeded",
        "--train-subset",
        str(subset_file),
        "--output-dir",
        str(round_dir),
        "--dataset-dir",
        str(dataset_dir),
        "--epochs",
        str(args.epochs),
    ]
    command += (
        ["--reuse-dataset"] if (dataset_dir / "labels.json").is_file() else ["--annotator-manifest", str(args.manifest)]
    )
    if previous is not None:
        command += ["--init-from", str(previous)]
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def score_round(
    best: Path, shots: Mapping[str, list[Mapping[str, Any]]], classical: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Every policy's edits on the held-out screenshots with a round's model, per split (per screenshot means)."""
    from grand_project.detect.rf_detr_model import load_detector

    detector = load_detector(best)
    out: dict[str, Any] = {}
    for split, rows in shots.items():
        sums = {policy: {"gold": Edits(), "silver": Edits()} for policy in K.ANNOTATOR_PRELABEL_POLICIES}
        for row in rows:
            found, detector_size, raw_size = predict(detector, Path(row["path"]))
            model = model_annotations(found, detector_size, raw_size)
            base = classical.get(str(row["source"]), [])
            reference = [{"label": a["label"], "bbox": a["bbox"]} for a in row["annotations"]]
            for policy in K.ANNOTATOR_PRELABEL_POLICIES:
                result = score(merge(base, model, policy, width=raw_size[0]), reference, width=raw_size[0])
                for part in ("gold", "silver"):
                    sums[policy][part] = sums[policy][part] + result[part]
        count = max(1, len(rows))
        out[split] = {
            "screenshots": len(rows),
            **{
                policy: {
                    part: {**{kind: getattr(edits, kind) / count for kind in EDIT_KINDS}, "edits": edits.edits / count}
                    for part, edits in parts.items()
                }
                for policy, parts in sums.items()
            },
        }
    return out


def report_markdown(results: Sequence[Mapping[str, Any]]) -> str:
    """The rounds' scores as a Markdown report."""
    lines = ["# Simulated annotation loop", ""]
    lines.append(
        "Edits per screenshot against the hand truth (gold) and disagreements with the classical boxes (silver)."
    )
    for result in results:
        lines += ["", f"## Round {result['round']}: {result['train_screenshots']} training screenshots", ""]
        if result.get("validation_mean_ap") is not None:
            lines.append(f"Validation mean family AP {result['validation_mean_ap']:.3f}")
            lines.append("")
        for split, scores in result["scores"].items():
            lines.append(f"**{split}** ({scores['screenshots']} screenshots)")
            lines.append("")
            lines.append(
                "| policy | gold edits | relabelled | deleted | added | silver | silver added | silver deleted |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for policy in K.ANNOTATOR_PRELABEL_POLICIES:
                gold, silver = scores[policy]["gold"], scores[policy]["silver"]
                lines.append(
                    f"| {policy} | {gold['edits']:.2f} | {gold['relabelled']:.2f} | {gold['deleted']:.2f} | "
                    f"{gold['added']:.2f} | {silver['edits']:.2f} | {silver['added']:.2f} | {silver['deleted']:.2f} |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the simulated rounds and write the report."""
    from .split_ledger import read_ledger
    from .state import resolve_path

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True, help="an export with the truth-seeded screenshots")
    parser.add_argument("--classical-store", type=Path, required=True, help="the store before the truth was seeded")
    parser.add_argument("--rounds", default=DEFAULT_ROUNDS, help="block numbers each round reveals, rounds by ';'")
    parser.add_argument("--atlas", default="atlas_test_data/fr-atlas/crawl_atlas_v076", help="the truth's atlas folder")
    parser.add_argument("--output-dir", type=Path, default=Path("runs/loop-sim"))
    parser.add_argument("--epochs", type=int, default=40, help="most epochs per round (early stopping ends sooner)")
    parser.add_argument("--skip-train", action="store_true", help="score the rounds' existing models only")
    args = parser.parse_args(argv)
    args.manifest = resolve_path(args.manifest)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rounds = revealed(read_ledger(), args.atlas, parse_rounds(args.rounds))
    shots = held_out(manifest, args.atlas)
    classical = classical_boxes(resolve_path(args.classical_store))
    missing = [row["source"] for rows in shots.values() for row in rows if row["source"] not in classical]
    if missing:
        raise SystemExit(f"{len(missing)} held-out screenshots are not in the classical store: {missing[:3]}")
    print(
        f"rounds: {[len(r) for r in rounds]} training screenshots; held out: { {s: len(r) for s, r in shots.items()} }"
    )
    output = args.output_dir
    dataset_dir = output / "dataset"
    results = []
    previous: Path | None = None
    for number, subset in enumerate(rounds, 1):
        round_dir = output / f"round-{number}"
        if not args.skip_train:
            train_round(args, round_dir, subset, previous, dataset_dir)
        best = round_dir / "best"
        summary_file = round_dir / "training_summary.json"
        summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() else {}
        result = {
            "round": number,
            "train_screenshots": len(subset),
            "validation_mean_ap": summary.get("best_validation_mean_ap"),
            "scores": score_round(best, shots, classical),
        }
        results.append(result)
        (output / "report.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(report_markdown(results), encoding="utf-8")
        print(report_markdown([result]), flush=True)
        previous = best
    return 0


__all__ = ["city_area", "classical_boxes", "held_out", "parse_rounds", "report_markdown", "revealed", "score"]


if __name__ == "__main__":
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    raise SystemExit(main())
