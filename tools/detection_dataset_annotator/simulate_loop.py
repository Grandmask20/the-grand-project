"""The iterative annotation loop, simulated on a hand-labelled atlas: does an ever-refined RF-DETR model, proposing
boxes with the classical detector, leave a reviewer fewer edits than the classical detector alone?

    python -m tools.detection_dataset_annotator.simulate_loop --manifest DATASET/manifest.json \\
        --classical-store DATASET/review_state.before-loop.sqlite3 [--rounds "8,2;0,3;1,4,6"] \\
        [--atlas atlas_test_data/fr-atlas/crawl_atlas_v076] [--truth atlas_test_data/fr-atlas/truth.json] \\
        [--output-dir runs/loop-sim] [--epochs 40] [--skip-train]

Each round reveals more of the atlas's training blocks (the split ledger's spatial blocks) as if a reviewer had
reviewed them, the review being the atlas's hand truth (its truth-seeded boxes: ``train_rf_detr --truth-seeded``),
and trains a model on everything revealed so far, starting from the previous round's model (``--init-from``), as
the live loop would. After each round the model pre-labels the atlas's validation and test screenshots, which no
round trains on, and every pre-label policy (``ANNOTATOR_PRELABEL_POLICIES``: the classical boxes, the model's, the
classical boxes relabelled by the model, and those plus the model's own finds) is scored with ``effort.edit_cost``
against the truth-seeded boxes:

- **gold**: what the hand truth knows. A matched map node's city area (each node class reduced to its city area or
  none: the truth says nothing about grass or water), only for node boxes at a map of the truth (``--truth``: a node
  the truth has no map for kept its classical class, which is no truth), and the citadels (the truth deletes false
  ones and types the rest; a City it reports without a citadel box was never drawn, so a model that finds one is
  counted as wrong).
- **silver**: everything else (map nodes found or not, icons, towers, halls, strongholds, reveal buttons) compared
  with the classical detector's boxes (``--classical-store``): disagreements, which in a real review are edits or
  fixes.

The classical policy's boxes are the classical detector's from before the truth was seeded (``--classical-store``:
the store as it was, kept when the store was rebuilt). The report (``report.md``, ``report.json``) gives the edits
per screenshot of every policy after every round: the learning curve of the loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from grand_project.detect import constants as DK
from grand_project.detect import labels as L
from grand_project.detect.rf_detr_model import trained_on

from . import constants as K
from .effort import EDIT_KINDS, Edits, corners, edit_cost, match_boxes, total
from .model_prelabel import merge, model_annotations, predict
from .state import file_hash
from .truth_seed import Truth, truth_map_at

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


def revealed(
    rows: Iterable[Any], atlas: str, rounds: Sequence[Sequence[str]], train_sources: Iterable[str]
) -> list[list[str]]:
    """The training screenshots revealed by each round, cumulative, by the names the manifest gives them.

    A screenshot (a digest) may have several ledger rows, one per name its bytes were seen under: it is revealed under
    the one the manifest trains on (``train_subset`` keeps screenshots by that name).

    Args:
        rows: the split ledger's rows (``read_ledger_rows``).
        atlas: the atlas folder, as the ledger names its blocks (``<atlas>#<n>``).
        rounds: the block numbers each round adds.
        train_sources: the manifest's training screenshots (their ``source``).

    Raises:
        ValueError: a block that is not one of the atlas's training blocks, a block named twice, or a screenshot of a
            revealed block the manifest has no training screenshot for.
    """
    sources = set(train_sources)
    blocks: dict[str, dict[str, list[str]]] = {}
    for entry in rows:
        if entry.split == "train" and entry.block.startswith(f"{atlas}#"):
            names = blocks.setdefault(entry.block.rsplit("#", 1)[1], {}).setdefault(entry.sha256, [])
            names.append(entry.file)
    out: list[list[str]] = []
    seen: list[str] = []
    used: set[str] = set()
    for adds in rounds:
        for block in adds:
            if block in used:  # its screenshots would be counted twice
                raise ValueError(f"{atlas}#{block} is revealed twice: each block is revealed once")
            used.add(block)
            if block not in blocks:
                raise ValueError(f"{atlas}#{block} is not a training block (training blocks: {sorted(blocks)})")
            found, missing = [], []
            for names in blocks[block].values():
                trained = sorted(name for name in names if name in sources)
                if trained:
                    found.append(trained[0])
                else:
                    missing.append(sorted(names)[0])
            if missing:
                raise ValueError(
                    f"{len(missing)} screenshots of {atlas}#{block} are no training screenshot of the manifest: "
                    f"{sorted(missing)[:3]} (export them, with --unreviewed for truth-seeded ones)"
                )
            seen += sorted(found)
        out.append(list(seen))
    return out


def city_area(annotation: Mapping[str, Any]) -> dict[str, Any]:
    """A node box with its class reduced to its city area (or ``NO_CITY_AREA``); other boxes as they are."""
    label = str(annotation.get("label", ""))
    if L.is_node(label) and L.city_type(label) is None:
        return {**annotation, "label": NO_CITY_AREA}
    return dict(annotation)


def score(
    prelabels: Sequence[Mapping[str, Any]],
    reference: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    *,
    scale: float = 1.0,
    map_of: Callable[[Mapping[str, Any]], int | None] | None = None,
) -> dict[str, Edits]:
    """A policy's pre-labels scored: ``gold`` against the truth-seeded ``reference`` (node city areas on matched
    nodes the truth knows, the citadels) and ``silver`` against the classical ``baseline`` (node finds and every
    other family).

    Args:
        prelabels: the policy's boxes.
        reference: the truth-seeded boxes.
        baseline: the classical detector's boxes.
        scale: the boxes' pixels per detector pixel (``effort.pixel_scale``).
        map_of: a node box -> the truth map at its middle, or None where the truth has none (None: every node box
            is of one map, as without a truth). A prediction is matched only with a reference node of its own map: two
            maps' boxes near each other are never one node.
    """

    def gold_nodes_of(boxes: Sequence[Mapping[str, Any]]) -> dict[int | None, list[dict[str, Any]]]:
        out: dict[int | None, list[dict[str, Any]]] = {}
        for a in boxes:
            if L.is_node(str(a.get("label", ""))):
                at = 0 if map_of is None else map_of(a)
                if at is not None:
                    out.setdefault(at, []).append(city_area(a))
        return out

    mine, theirs = gold_nodes_of(prelabels), gold_nodes_of(reference)
    gold_nodes = Edits()
    for at in mine.keys() | theirs.keys():
        found = edit_cost(mine.get(at, []), theirs.get(at, []), scale=scale, families=["node"])
        gold_nodes = gold_nodes + found.get("node", Edits())
    citadels = edit_cost(prelabels, reference, scale=scale, families=["citadel"]).get("citadel", Edits())
    # the node finds are node_finds' (by place alone), the citadels gold's
    others = edit_cost(
        prelabels, baseline, scale=scale, families=[f for f in _families(prelabels, baseline) if f not in GOLD_FAMILIES]
    )
    silver = total(others)
    silver = silver + node_finds(prelabels, baseline, scale)
    gold = Edits(kept=gold_nodes.kept, relabelled=gold_nodes.relabelled) + citadels
    return {"gold": gold, "silver": silver}


def node_finds(prelabels: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]], scale: float) -> Edits:
    """The map nodes found or missed against the classical boxes: a one-to-one pairing by place alone, within the node
    radius (``match_boxes`` without edit costs), whatever their classes or a small move; an unpaired one is added or
    deleted. Classes are the gold score's."""
    before = [box for a in prelabels if L.is_node(str(a.get("label", ""))) and (box := corners(a)) is not None]
    after = [box for a in baseline if L.is_node(str(a.get("label", ""))) and (box := corners(a)) is not None]
    pairs = match_boxes(before, after, DK.RF_DETR_EVAL_RADIUS["node"] * scale)
    return Edits(deleted=len(before) - len(pairs), added=len(after) - len(pairs))


def _families(*sides: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({L.family(str(a.get("label", ""))) or str(a.get("label", "")) for side in sides for a in side})


def classical_boxes(store_path: Path) -> dict[str, list[dict[str, Any]]]:
    """The classical detector's boxes per screenshot (its project-relative file), read from a store copy without
    changing it."""
    out: dict[str, list[dict[str, Any]]] = {}
    # closing(): a connection's own ``with`` only ends a transaction, and an open file cannot be removed on Windows;
    # as_uri percent-encodes the path: a raw "#" or "?" in it would end the path early and drop "mode=ro"
    with closing(sqlite3.connect(f"{store_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        # LEFT JOIN: a screenshot the classical detector found nothing on has its (empty) boxes too; one never
        # detected (or whose detection failed) has none, which is no baseline
        rows = db.execute(
            "SELECT images.source, annotations.label, annotations.x, annotations.y, annotations.w, annotations.h, "
            "annotations.source FROM images LEFT JOIN annotations ON images.key = annotations.image_key "
            "WHERE images.detected = 1 ORDER BY images.position, annotations.ord"
        )
        for source, label, x, y, w, h, box_source in rows:
            boxes = out.setdefault(source, [])
            if label is not None:  # NULL: the LEFT JOIN's no box (a box's label is never NULL)
                boxes.append({"label": label, "bbox": [x, y, w, h], "source": box_source})
    return out


def _posix(source: str) -> PurePosixPath:
    """A screenshot source (or atlas folder) as a path with "/" separators on every system."""
    return PurePosixPath(source.replace("\\", "/"))


def held_out(
    manifest: Mapping[str, Any], atlas: str, base: Path | None = None, truth_source: str | None = None
) -> dict[str, list[Mapping[str, Any]]]:
    """The atlas's truth-seeded validation and test screenshots of a manifest, by split.

    Args:
        manifest: the export's manifest.
        atlas: the atlas folder, project-relative.
        base: the folder a relative ``path`` lies in (the manifest's, as ``rf_detr.load_annotator_manifest`` reads
            it); the rows come back with it joined on. None: paths as they are.
        truth_source: only rows this truth seeded (their ``ANNOTATOR_TRUTH_MARK`` is its ``Truth.source``): a row
            another truth marked is no gold for this one. None: any truth's.
    """
    out: dict[str, list[Mapping[str, Any]]] = {"validation": [], "test": []}
    for row in manifest.get("images", []):
        # by path component: "<atlas>-backup/..." is another folder. A source outside the project is an absolute
        # path with the system's separators (relative_source): on Windows its backslashes made it one component
        inside = _posix(str(row.get("source", ""))).is_relative_to(_posix(atlas))
        mark = row.get(K.ANNOTATOR_TRUTH_MARK)
        if truth_source is not None and mark and _posix(str(mark)) != _posix(truth_source):
            continue
        if row.get("split") in out and mark and inside:
            if base is not None and not Path(str(row["path"])).is_absolute():
                row = {**row, "path": str(base / str(row["path"]))}
            out[row["split"]].append(row)
    return out


def train_round(
    args: argparse.Namespace,
    round_dir: Path,
    subset: list[str],
    previous: Path | None,
    dataset_dir: Path,
    manifest_sha: str,
) -> None:
    """Train one round's model in its own process (the GPU is free again after it). ``manifest_sha``: the SHA-256 of
    the manifest bytes the simulation read (a saved dataset is reused only when built from those)."""
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
    if dataset_matches(dataset_dir, manifest_sha):
        command += ["--reuse-dataset"]
    else:  # none yet, or one built from other inputs (an earlier simulation's): built anew
        command += ["--annotator-manifest", str(args.manifest)]
        if dataset_dir.exists():
            command += ["--overwrite-dataset"]
    if previous is not None:
        command += ["--init-from", str(previous)]
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def check_round(best: Path, subset: Sequence[str], number: int) -> None:
    """Stop when a round's kept model did not train on exactly the screenshots this round reveals (its
    ``RF_DETR_TRAINED_ON``): scoring an existing model (``--skip-train``) under other rounds would report it as
    something it is not.

    Raises:
        SystemExit: the model has no training record, or it lists other screenshots.
    """
    recorded = trained_on(best)
    if not recorded:
        raise SystemExit(f"round {number}: {best} lists no training screenshots: train it again (no --skip-train)")
    wanted = set(subset)
    if recorded != wanted:
        raise SystemExit(
            f"round {number}: {best} trained on other screenshots than --rounds reveals "
            f"({len(recorded - wanted)} more, {len(wanted - recorded)} missing): train it again or use its rounds"
        )


def dataset_matches(dataset_dir: Path, manifest_sha: str) -> bool:
    """Whether a saved dataset was built from the manifest of SHA-256 ``manifest_sha`` and the split ledger as it is
    now, truth-seeded (its ``metadata.json`` provenance, ``train_rf_detr``), so a round may reuse it."""
    meta_file = dataset_dir / "metadata.json"
    if not (dataset_dir / "labels.json").is_file() or not meta_file.is_file():
        return False
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False  # a broken record (an interrupted build): built anew
    if not isinstance(meta, dict):
        return False
    ledger = K.ANNOTATOR_SPLIT_LEDGER
    return (
        meta.get("truth_seeded") is True
        # built from every screenshot (a smoke build's --max-images cap is no dataset to train rounds on)
        and "max_images" in meta
        and meta["max_images"] is None
        and meta.get("manifest_sha256") == manifest_sha
        and ledger.is_file()
        and meta.get("ledger_sha256") == file_hash(ledger)
    )


def check_manifest(summary_file: Path, manifest_sha: str, number: int) -> dict[str, Any]:
    """A round's training summary, when its model was trained on the manifest the simulation scores with (the SHA-256
    its dataset records): the manifest file can change while a round trains, and its held-out rows would then not be
    the ones the model was kept against.

    Raises:
        SystemExit: no summary, or a model trained on another manifest.
    """
    if not summary_file.is_file():
        raise SystemExit(f"round {number}: no {summary_file.name} in {summary_file.parent}: train it again")
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    trained = (summary.get("dataset") or {}).get("manifest_sha256")
    if trained != manifest_sha:
        raise SystemExit(
            f"round {number}: its model was trained on another manifest ({trained}) than the one scored "
            f"({manifest_sha}): the manifest changed meanwhile; run the simulation again"
        )
    weights = summary_file.parent / "best" / "model.safetensors"
    kept = file_hash(weights) if weights.is_file() else None
    if summary.get("best_sha256") is None or summary.get("best_sha256") != kept:
        # its scores and validation AP would be reported for another model (a run that kept a new best/ but did not
        # get to write its summary, or a best/ put there by hand)
        raise SystemExit(
            f"round {number}: {summary_file.name} is not about the model in best/ (its weights differ): train it again"
        )
    return summary


def truth_map_of(truth: Truth | None, row: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], int | None]:
    """A held-out screenshot's node box -> the truth map at its middle, or None (always, for a screenshot the truth
    does not place; one map, 0, for every box without a truth)."""
    if truth is None:
        return lambda box: 0
    shot = truth.screenshots.get(Path(str(row["path"])).name)
    if shot is None:
        return lambda box: None
    return truth_map_at(truth, shot, int(row.get("width") or shot["w"]), int(row.get("height") or shot["h"]))


def score_round(
    best: Path,
    shots: Mapping[str, list[Mapping[str, Any]]],
    classical: Mapping[str, list[dict[str, Any]]],
    truth: Truth | None = None,
) -> dict[str, Any]:
    """Every policy's edits on the held-out screenshots with a round's model, per split (per screenshot means)."""
    from grand_project.detect.rf_detr_model import load_detector

    detector = load_detector(best)
    try:
        return _score_splits(detector, shots, classical, truth)
    finally:
        # the next round trains in its own process: it gets the GPU memory this model held (PyTorch keeps it cached)
        del detector
        _free_accelerator()


def _free_accelerator() -> None:
    """Give back the GPU memory freed models leave in PyTorch's cache."""
    import gc

    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _score_splits(
    detector: Mapping[str, Any],
    shots: Mapping[str, list[Mapping[str, Any]]],
    classical: Mapping[str, list[dict[str, Any]]],
    truth: Truth | None,
) -> dict[str, Any]:
    """``score_round`` with its model loaded."""
    out: dict[str, Any] = {}
    for split, rows in shots.items():
        sums = {policy: {"gold": Edits(), "silver": Edits()} for policy in K.ANNOTATOR_PRELABEL_POLICIES}
        scored = 0
        for row in rows:
            found, detector_size, raw_size = predict(detector, Path(row["path"]))
            if raw_size != (row.get("width"), row.get("height")):
                # the file is not the one exported (replaced since): the model's boxes would be in another pixel frame
                # than the classical and truth boxes, so it is not scored
                print(
                    f"  {row['source']}: {raw_size[0]}x{raw_size[1]}, exported at {row.get('width')}x"
                    f"{row.get('height')}: changed since its detection, rerun its detection (left out)"
                )
                continue
            scored += 1
            model = model_annotations(found, detector_size, raw_size)
            base = classical.get(str(row["source"]), [])
            reference = [{"label": a["label"], "bbox": a["bbox"]} for a in row["annotations"]]
            scale = raw_size[0] / detector_size[0]
            map_of = truth_map_of(truth, row)
            for policy in K.ANNOTATOR_PRELABEL_POLICIES:
                result = score(merge(base, model, policy, scale=scale), reference, base, scale=scale, map_of=map_of)
                for part in ("gold", "silver"):
                    sums[policy][part] = sums[policy][part] + result[part]
        count = max(1, scored)
        out[split] = {
            "screenshots": scored,
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
    from .split_ledger import read_ledger_rows
    from .state import resolve_path

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True, help="an export with the truth-seeded screenshots")
    parser.add_argument("--classical-store", type=Path, required=True, help="the store before the truth was seeded")
    parser.add_argument("--rounds", default=DEFAULT_ROUNDS, help="block numbers each round reveals, rounds by ';'")
    parser.add_argument("--atlas", default="atlas_test_data/fr-atlas/crawl_atlas_v076", help="the truth's atlas folder")
    parser.add_argument(
        "--truth", default="atlas_test_data/fr-atlas/truth.json", help="the atlas's truth file (gold: its maps only)"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("runs/loop-sim"))
    parser.add_argument("--epochs", type=int, default=40, help="most epochs per round (early stopping ends sooner)")
    parser.add_argument("--skip-train", action="store_true", help="score the rounds' existing models only")
    args = parser.parse_args(argv)
    args.manifest = resolve_path(args.manifest)
    # one snapshot of the manifest: the training screenshots, the held-out rows and the rounds' checks all come from
    # these bytes (the file read again later could be another export)
    manifest_bytes = args.manifest.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)
    truth = Truth.load(resolve_path(args.truth))
    shots = held_out(manifest, args.atlas, args.manifest.parent, truth.source)
    others = [
        str(row["source"])
        for rows in held_out(manifest, args.atlas).values()
        for row in rows
        if _posix(str(row[K.ANNOTATOR_TRUTH_MARK])) != _posix(truth.source)
    ]
    if others:  # before any training: they are left out of the scores
        print(f"{len(others)} held-out screenshots another truth marked, not {truth.source}: left out ({others[:3]})")
    if not any(shots.values()):  # nothing to score: every round would train for nothing
        raise SystemExit(
            f"no validation or test screenshots of {args.atlas} seeded by {truth.source} in {args.manifest}: seed them "
            "(truth_seed) and export them with the unreviewed ones (export --unreviewed)"
        )
    train_sources = [str(row.get("source")) for row in manifest.get("images", []) if row.get("split") == "train"]
    rounds = revealed(read_ledger_rows(), args.atlas, parse_rounds(args.rounds), train_sources)
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
            train_round(args, round_dir, subset, previous, dataset_dir, manifest_sha)
        best = round_dir / "best"
        if args.skip_train:
            check_round(best, subset, number)
        summary = check_manifest(round_dir / "training_summary.json", manifest_sha, number)
        result = {
            "round": number,
            "train_screenshots": len(subset),
            "validation_mean_ap": summary.get("best_validation_mean_ap"),
            "scores": score_round(best, shots, classical, truth),
        }
        results.append(result)
        (output / "report.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(report_markdown(results), encoding="utf-8")
        print(report_markdown([result]), flush=True)
        previous = best
    return 0


__all__ = [
    "check_manifest",
    "check_round",
    "city_area",
    "classical_boxes",
    "dataset_matches",
    "held_out",
    "node_finds",
    "parse_rounds",
    "report_markdown",
    "revealed",
    "score",
    "truth_map_of",
]


if __name__ == "__main__":
    from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    raise SystemExit(main())
