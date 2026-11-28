"""Compare the classical detector with a fine-tuned RF-DETR detector.

Accuracy is measured by rebuilding temporary copies of the standard resolution atlases (``res_atlases`` in the test
data, built from the author's ``atlas-tests``).  The saved
``res_4k_100`` atlas is kept as a fixed reference, so both backends are compared with the same reference rather than
with an atlas produced by themselves.  The reference is the sharpest view of the same three atlas locations, not
hand-labelled truth; a match means that a detector found the same map node, icon, path or landmark in that reference.

Speed is measured on the screenshots in ``roa-atlas``.  The images are decoded before each timed detector call, so
the reported latency is detector time rather than disk and PNG decoding time.  RF-DETR model loading is reported as
warm-up time and excluded from steady-state latency.

Run from the project folder:

    python -m tools.compare_detectors
    python -m tools.compare_detectors --max-images 20 --atlas res_1080_100
    python -m tools.compare_detectors --output detector-comparison.json

The RF-DETR checkpoint defaults to ``runs/rf-detr-small/best`` and can be changed with ``--model-dir``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from grand_project import core
from grand_project import paths as project_paths
from grand_project.detect.constants import (
    RF_DETR_DEFAULT_MODEL_DIR,
    RF_DETR_DEVICE_ENV,
    RF_DETR_MODEL_ENV,
    RF_DETR_USE_ENV,
)
from grand_project.detect.pipeline import detect_classical
from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries
from grand_project.detect.rf_detr_model import (
    checkpoint_digest,
    detect_rf_detr,
    folder_identity,
    reset_rf_detr_runtime,
)


@dataclass(frozen=True)
class Backend:
    """One detector backend and its human-readable report name."""

    name: str
    detect: Callable[[np.ndarray], dict[str, Any]]


@contextmanager
def _backend_environment(backend: Backend, model_dir: Path, device: str) -> Iterator[None]:
    """Set only the detector environment inherited by atlas-builder subprocesses."""
    names = (RF_DETR_USE_ENV, RF_DETR_MODEL_ENV, RF_DETR_DEVICE_ENV)
    old = {name: os.environ.get(name) for name in names}
    try:
        os.environ.pop(RF_DETR_USE_ENV, None)
        if backend.name == "RF-DETR":
            os.environ[RF_DETR_USE_ENV] = "1"
            os.environ[RF_DETR_MODEL_ENV] = str(model_dir)
            if device != "auto":
                os.environ[RF_DETR_DEVICE_ENV] = device
            else:
                os.environ.pop(RF_DETR_DEVICE_ENV, None)
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


SCORER = project_paths.ROOT / "atlas_test_data" / "res_atlases" / "score_atlases.py"
"""The atlas scorer, this checkout's own: the atlas folder given on the command line is data, never code to run."""


def _score_module(scorer_path: Path = SCORER):
    """Load this checkout's atlas scorer (it takes the atlas folders it scores as arguments)."""
    if not scorer_path.is_file():
        raise FileNotFoundError(f"atlas scorer not found: {scorer_path}")
    spec = importlib.util.spec_from_file_location("grand_project_atlas_test_scorer", scorer_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load atlas scorer: {scorer_path}")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    return scorer


def _atlas_folders(atlas_root: Path, requested: list[str] | None, scorer) -> list[Path]:
    """Find standard atlas folders in the scorer's stable display order."""
    folders = sorted(p.parent for p in atlas_root.glob("res_*/atlas.json") if p.is_file())
    if requested:
        wanted = set(requested)
        folders = [folder for folder in folders if folder.name in wanted]
        missing = wanted - {folder.name for folder in folders}
        if missing:
            raise FileNotFoundError(f"requested atlas folder(s) not found: {', '.join(sorted(missing))}")
    if not folders:
        raise FileNotFoundError(f"no res_*/atlas.json folders found below {atlas_root}")
    order = {name: index for index, name in enumerate(getattr(scorer, "ORDER", []))}
    return sorted(folders, key=lambda folder: (order.get(folder.name, 999), folder.name))


def _copy_atlas_input(source: Path, destination: Path, *, include_cache: bool) -> None:
    """Copy only files needed by the scorer, leaving generated outputs out of the temporary run."""
    destination.mkdir(parents=True, exist_ok=True)
    for image in source.glob("*.png"):
        shutil.copy2(image, destination / image.name)
    if include_cache:
        shutil.copy2(source / "atlas.json", destination / "atlas.json")
        cache = source / "atlas_frames"
        if cache.is_dir():
            shutil.copytree(cache, destination / "atlas_frames")


def _write_empty_atlas(folder: Path) -> None:
    """Create the normal empty-atlas shape when a detector places no screenshots."""
    (folder / "atlas.json").write_text(json.dumps(core.Atlas().to_json(), indent=1) + "\n", encoding="utf-8")
    (folder / "atlas_frames").mkdir(exist_ok=True)


def _rebuild_accuracy(
    backend: Backend,
    atlas_root: Path,
    folders: list[Path],
    model_dir: Path,
    device: str,
    scorer,
) -> dict[str, Any]:
    """Rebuild temporary atlases and score them against the fixed sharp reference atlas."""
    reference_name = getattr(scorer, "REFERENCE", "res_4k_100")
    reference_source = atlas_root / reference_name
    if not reference_source.is_dir():
        raise FileNotFoundError(f"fixed reference atlas not found: {reference_source}")

    with tempfile.TemporaryDirectory(prefix="grand-project-detector-accuracy-") as temporary:
        root = Path(temporary)
        reference = root / "reference"
        _copy_atlas_input(reference_source, reference, include_cache=True)
        run_folders: list[Path] = []
        for source in folders:
            destination = root / source.name
            _copy_atlas_input(source, destination, include_cache=False)
            run_folders.append(destination)

        with _backend_environment(backend, model_dir, device):
            for folder in run_folders:
                print(f"  {backend.name}: rebuilding {folder.name} ...", flush=True)
                try:
                    placed = scorer.rebuild(folder)
                except subprocess.CalledProcessError as failed:
                    # the builder exits 1 when a screenshot could not be detected: no score for a broken backend
                    output = (failed.stdout or b"") + (failed.stderr or b"")
                    if isinstance(output, bytes):
                        output = output.decode("utf-8", "replace")
                    tail = "\n".join(output.strip().splitlines()[-10:])
                    raise SystemExit(f"{backend.name}: rebuilding {folder.name} failed:\n{tail}") from failed
                if placed is False:
                    # the builder ran without error and placed nothing (the scorer says so): an empty atlas. A missing
                    # file or program is an error, never scored as empty
                    print(f"    {backend.name}: no screenshots placed in {folder.name}; scoring it as empty")
                    _write_empty_atlas(folder)

        scorer_core, view_model = scorer._import()
        reference_numbers = scorer.numbers(reference, scorer_core, view_model)
        results = {}
        for folder in run_folders:
            numbers = scorer.numbers(folder, scorer_core, view_model)
            comparison = scorer.compare_to_reference(numbers, reference_numbers)
            comparison = _add_landmark_metrics(
                folder, reference, comparison, scorer.MATCH, scorer_core=scorer_core, view_model=view_model
            )
            results[folder.name] = _normalise_accuracy(numbers, reference_numbers, comparison)
        return {"reference": reference_name, "atlases": results}


def _category_count(numbers: dict[str, Any], category: str) -> int:
    """Count one scored category, including landmark counters from the atlas scorer."""
    value = numbers.get(category, 0)
    return sum(value.values()) if isinstance(value, dict) else int(value)


def _normalise_accuracy(
    numbers: dict[str, Any], reference_numbers: dict[str, Any], comparison: dict[str, Any]
) -> dict[str, Any]:
    """Convert scorer summaries into metrics, including empty-detector runs with explicit zero scores."""
    metrics = {}
    for category in ("maps", "icons", "paths", "landmarks"):
        if category in comparison:
            summary = _parse_match(comparison[category])
        else:
            predicted = _category_count(numbers, category)
            reference = _category_count(reference_numbers, category)
            summary = {
                "matched": 0,
                "predicted": predicted,
                "reference": reference,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            }
        metrics[category] = summary
    return {
        "screenshots": numbers["screenshots"],
        "maps": numbers["maps"],
        "paths": numbers["paths"],
        "icons": numbers["icons"],
        "landmarks": numbers["landmarks"],
        "matches": metrics,
        "shift": comparison.get("shift", [0.0, 0.0]),
    }


def _parse_match(text: str) -> dict[str, Any]:
    """Parse one match summary emitted by ``score_atlases.compare_to_reference``."""
    match = re.search(r"(\d+) of (\d+) match; found (\d+) of (\d+) \((\d+)%\)", text)
    if match is None:
        return {"matched": 0, "predicted": 0, "reference": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    matched, predicted, _found, reference, _percent = (int(value) for value in match.groups())
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    return {
        "matched": matched,
        "predicted": predicted,
        "reference": reference,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
    }


def _f1(precision: float, recall: float) -> float:
    """Return the harmonic mean of precision and recall."""
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _live_landmarks(folder: Path, scorer_core, view_model) -> list[dict[str, Any]]:
    """The non-removed landmarks of a scored atlas as the scorer counts them (``view_model`` of the loaded atlas:
    the user's landmark edits included)."""
    landmarks = view_model(scorer_core.Atlas.load(folder / "atlas.json"))["landmarks"]
    return [landmark for landmark in landmarks if not str(landmark.get("status", "kept")).startswith("removed")]


def _landmark_hits(
    predicted: list[dict[str, Any]], expected: list[dict[str, Any]], shift: np.ndarray, match_distance: float
) -> int:
    """How many landmarks match one-to-one, kind by kind: the most pairs within ``match_distance`` (after the shift),
    the closest among those, whatever order the landmarks come in."""
    from scipy.optimize import linear_sum_assignment

    hits = 0
    for kind in {lm.get("kind") for lm in predicted} & {lm.get("kind") for lm in expected}:
        mine = np.array([[float(lm["x"]), float(lm["y"])] for lm in predicted if lm.get("kind") == kind]) + shift
        theirs = np.array([[float(lm["x"]), float(lm["y"])] for lm in expected if lm.get("kind") == kind])
        distance = np.hypot(mine[:, None, 0] - theirs[None, :, 0], mine[:, None, 1] - theirs[None, :, 1])
        eligible = distance <= match_distance
        # a pair out of reach costs more than every pair in reach together: the most pairs first, then the closest
        never = (min(distance.shape) + 1) * match_distance + 1.0
        rows, cols = linear_sum_assignment(np.where(eligible, distance, never))
        hits += int(eligible[rows, cols].sum())
    return hits


def _add_landmark_metrics(
    folder: Path, reference: Path, comparison: dict[str, Any], match_distance: float, *, scorer_core, view_model
) -> dict[str, Any]:
    """Match final landmarks by kind and position using the map-derived alignment shift."""
    predicted = _live_landmarks(folder, scorer_core, view_model)
    expected = _live_landmarks(reference, scorer_core, view_model)
    # no shift from the scorer (no map node to line the atlases up by) is no zero shift: the landmarks are counted and
    # none is matched by place; an explicit [0, 0] is a real alignment
    shift = comparison.get("shift")
    hits = 0 if shift is None else _landmark_hits(predicted, expected, np.asarray(shift, float), match_distance)
    recall = hits / len(expected) if expected else 0.0
    comparison["landmarks"] = f"{hits} of {len(predicted)} match; found {hits} of {len(expected)} ({recall:.0%})"
    return comparison


def _model_device(backend: Backend):
    """The device the backend's model runs on (the loaded RF-DETR's, ``auto`` resolved), or None: the classical
    detector, or no model loaded yet."""
    if backend.name != "RF-DETR":
        return None
    from grand_project.detect import rf_detr_model

    runtime = rf_detr_model._RUNTIME
    return None if runtime is None else runtime.get("device")


def _synchronise_accelerator(device) -> None:
    """Wait for that device's asynchronous work before taking the next timing sample: a CUDA or Apple GPU only, never
    another accelerator than the one inferring (a CPU run on a CUDA machine must not start a CUDA context)."""
    kind = getattr(device, "type", None)
    if kind not in ("cuda", "mps"):
        return
    import torch

    if kind == "cuda":
        torch.cuda.synchronize(device)
    elif hasattr(torch, "mps") and hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()


def _detection_counts(result: dict[str, Any]) -> dict[str, int]:
    """Summarise one detector output for the speed report."""
    return {
        "maps": sum(not node.get("hidden") for node in result.get("nodes", [])),
        "icons": len(result.get("icons", [])),
        "landmarks": len(result.get("landmarks", [])),
        "paths": len(result.get("edges", [])),
    }


def _benchmark_speed(
    backend: Backend,
    image_paths: list[Path],
    model_dir: Path,
    device: str,
) -> dict[str, Any]:
    """Measure warm-up and steady-state detector latency on the same screenshot list."""
    if not image_paths:
        raise FileNotFoundError("no PNG screenshots found for the speed benchmark")
    reset_rf_detr_runtime()
    first = core.read_screenshot(image_paths[0])
    if first is None:
        raise ValueError(f"could not read benchmark screenshot: {image_paths[0]}")
    with _backend_environment(backend, model_dir, device):
        started = time.perf_counter()  # (nothing to wait for before the model is loaded)
        backend.detect(first)
        device = _model_device(backend)
        _synchronise_accelerator(device)
        warmup_seconds = time.perf_counter() - started

        timings: list[float] = []
        totals = {"maps": 0, "icons": 0, "landmarks": 0, "paths": 0}
        for image_path in image_paths:
            image = core.read_screenshot(image_path)
            if image is None:
                raise ValueError(f"could not read benchmark screenshot: {image_path}")
            _synchronise_accelerator(device)
            started = time.perf_counter()
            result = backend.detect(image)
            _synchronise_accelerator(device)
            timings.append(time.perf_counter() - started)
            for key, value in _detection_counts(result).items():
                totals[key] += value

    mean = statistics.fmean(timings)
    return {
        "images": len(timings),
        "warmup_seconds": warmup_seconds,
        "mean_seconds": mean,
        "median_seconds": statistics.median(timings),
        "p95_seconds": float(np.percentile(timings, 95)),
        "min_seconds": min(timings),
        "max_seconds": max(timings),
        "images_per_second": 1 / mean if mean else 0.0,
        "detections": totals,
    }


def _speed_paths(root: Path, maximum: int | None) -> list[Path]:
    """Return the ROA screenshots in deterministic order."""
    images = sorted(root.glob("*.png"))
    if not images:
        raise FileNotFoundError(f"no PNG screenshots found below {root}")
    return images[:maximum] if maximum is not None else images


def _print_accuracy(report: dict[str, Any]) -> None:
    """Print the accuracy table."""
    print("Accuracy vs fixed res_4k_100 reference (res_atlases)")
    print("atlas              backend       maps P/R/F1       icons P/R/F1      paths P/R/F1      landmarks P/R/F1")
    for backend_name, backend_report in report.items():
        for atlas_name, atlas_report in backend_report["atlases"].items():
            values = []
            for category in ("maps", "icons", "paths", "landmarks"):
                metric = atlas_report["matches"].get(category, {})
                values.append(
                    f"{metric.get('precision', 0):.0%}/{metric.get('recall', 0):.0%}/{metric.get('f1', 0):.0%}"
                )
            print(f"{atlas_name:<18} {backend_name:<12} {values[0]:<16} {values[1]:<16} {values[2]:<16} {values[3]}")
    print("P/R/F1 = precision / recall / F1; the reference is the sharpest view, not hand-labelled truth.")


def _print_speed(report: dict[str, Any]) -> None:
    """Print the speed table."""
    print("\nSpeed on roa-atlas (detector call only; image decoding excluded)")
    print("backend       images   warm-up    mean       median     p95        images/s")
    for name, values in report.items():
        print(
            f"{name:<12} {values['images']:>6}   {values['warmup_seconds']:>7.2f}s  "
            f"{values['mean_seconds']:>7.3f}s  {values['median_seconds']:>7.3f}s  "
            f"{values['p95_seconds']:>7.3f}s  {values['images_per_second']:>8.2f}"
        )


def _parse_args() -> argparse.Namespace:
    """Parse comparison options."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--atlas-tests", type=Path, default=project_paths.TEST_DATA / "res_atlases")
    parser.add_argument("--roa-atlas", type=Path, default=project_paths.TEST_DATA / "roa-atlas")
    parser.add_argument("--model-dir", type=Path, default=RF_DETR_DEFAULT_MODEL_DIR)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--max-images", type=int, help="speed benchmark limit; default is every roa-atlas screenshot")
    parser.add_argument("--atlas", dest="atlas_names", action="append", help="accuracy atlas name; may be repeated")
    parser.add_argument("--accuracy-only", action="store_true")
    parser.add_argument("--speed-only", action="store_true")
    parser.add_argument("--output", type=Path, help="also save the complete report as JSON")
    args = parser.parse_args()
    if args.accuracy_only and args.speed_only:
        parser.error("--accuracy-only and --speed-only cannot be used together")
    if args.max_images is not None and args.max_images < 1:
        parser.error("--max-images must be positive")
    return args


def _copy_checkpoint(given: Path, model_dir: Path) -> None:
    """Copy a checkpoint folder, which must be one published generation throughout: a training run publishes a new
    ``best/`` by renaming a complete folder in (``train_rf_detr.swap_in``), so the folder's identity changes, and a copy
    made across that would hold files of two models (or fail on the one removed). That copy is never scored.

    Raises:
        SystemExit: the folder was replaced while it was copied.
    """
    try:
        before = folder_identity(given)
        shutil.copytree(given, model_dir)
        same = folder_identity(given) == before
    except OSError:  # (the old generation is removed under the copy)
        same = False
    if not same:
        shutil.rmtree(model_dir, ignore_errors=True)
        raise SystemExit(f"{given} was replaced while it was copied (a training run kept a new best): run it again")


def main() -> int:
    """Run both detector comparisons and return a process exit code."""
    prefer_pip_cuda_libraries()  # RF-DETR on CUDA needs PyTorch's own cuDNN, before torch loads (rf_detr_cuda)
    args = _parse_args()
    given = args.model_dir.expanduser().resolve()
    if not given.is_dir():
        raise SystemExit(f"RF-DETR model directory does not exist: {given} (use --model-dir)")
    with tempfile.TemporaryDirectory(prefix="grand-project-compare-model-") as temporary:
        # one copy of the checkpoint for both phases: a best/ a training run swaps in meanwhile never mixes two models
        # into one report
        model_dir = Path(temporary) / given.name
        _copy_checkpoint(given, model_dir)
        return _compare(args, given, model_dir)


def _compare(args: argparse.Namespace, given: Path, model_dir: Path) -> int:
    """``main`` with the checkpoint copied to ``model_dir``."""
    backends = [Backend("classical", detect_classical), Backend("RF-DETR", detect_rf_detr)]
    report: dict[str, Any] = {
        "model": {"dir": str(given), "digest": checkpoint_digest(model_dir)},
        "accuracy": {},
        "speed": {},
    }
    if not args.speed_only:
        atlas_root = args.atlas_tests.expanduser().resolve()
        scorer = _score_module()
        folders = _atlas_folders(atlas_root, args.atlas_names, scorer)
        for backend in backends:
            report["accuracy"][backend.name] = _rebuild_accuracy(
                backend, atlas_root, folders, model_dir, args.device, scorer
            )
        _print_accuracy(report["accuracy"])

    if not args.accuracy_only:
        image_paths = _speed_paths(args.roa_atlas.expanduser().resolve(), args.max_images)
        for backend in backends:
            print(f"\n{backend.name}: timing {len(image_paths)} screenshots ...", flush=True)
            report["speed"][backend.name] = _benchmark_speed(backend, image_paths, model_dir, args.device)
        _print_speed(report["speed"])

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nsaved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
