"""Offline tests for detector-comparison report helpers."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import compare_detectors
from tools.compare_detectors import _landmark_hits, _normalise_accuracy, _parse_match


def test_parse_match_returns_precision_recall_and_f1() -> None:
    result = _parse_match("10 of 12 match; found 10 of 20 (50%)")
    assert result["matched"] == 10
    assert result["predicted"] == 12
    assert result["reference"] == 20
    assert result["precision"] == 10 / 12
    assert result["recall"] == 0.5
    assert result["f1"] == pytest.approx(0.625)


def test_parse_match_handles_empty_summary() -> None:
    assert _parse_match("") == {
        "matched": 0,
        "predicted": 0,
        "reference": 0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }


def test_normalise_accuracy_reports_empty_detector_counts() -> None:
    result = _normalise_accuracy(
        {"screenshots": "0 / 3 placed", "maps": 0, "paths": 0, "icons": 0, "landmarks": {}},
        {"screenshots": "3 / 3 placed", "maps": 12, "paths": 8, "icons": 4, "landmarks": {"Tower": 2}},
        {},
    )
    assert result["matches"] == {
        "maps": {"matched": 0, "predicted": 0, "reference": 12, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "icons": {"matched": 0, "predicted": 0, "reference": 4, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "paths": {"matched": 0, "predicted": 0, "reference": 8, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "landmarks": {"matched": 0, "predicted": 0, "reference": 2, "precision": 0.0, "recall": 0.0, "f1": 0.0},
    }


def test_landmarks_match_one_to_one_whatever_their_order() -> None:
    """A greedy match let the first City take the reference City the second needed (both within reach of the first):
    the assignment pairs both, in either order."""
    expected = [{"kind": "City", "x": 0.0, "y": 0.0}, {"kind": "City", "x": 18.0, "y": 0.0}]
    predicted = [{"kind": "City", "x": 9.0, "y": 0.0}, {"kind": "City", "x": 1.0, "y": 0.0}]
    for order in (predicted, predicted[::-1]):
        assert _landmark_hits(order, expected, np.zeros(2), 10.0) == 2
    hall = [{"kind": "Hall", "x": 0.0, "y": 0.0}]  # another kind never matches
    assert _landmark_hits(hall, expected, np.zeros(2), 10.0) == 0
    assert _landmark_hits(predicted, expected, np.array([100.0, 0.0]), 10.0) == 0  # shifted out of reach


def test_a_rebuild_whose_detection_failed_stops_the_comparison(tmp_path: Path) -> None:
    """The builder exits 1 when a screenshot could not be detected: that is no empty atlas to score."""
    reference = tmp_path / "ref"
    reference.mkdir()
    (reference / "atlas.json").write_text("{}")
    folder = tmp_path / "res_1080_100"
    folder.mkdir()

    def rebuild(work: Path) -> None:
        raise subprocess.CalledProcessError(1, ["builder"], output=b"1 screenshots could not be detected: a.png")

    scorer = SimpleNamespace(REFERENCE="ref", rebuild=rebuild)
    backend = compare_detectors.Backend("RF-DETR", lambda img: {})
    with pytest.raises(SystemExit, match="RF-DETR: rebuilding res_1080_100 failed:\n1 screenshots could not be"):
        compare_detectors._rebuild_accuracy(backend, tmp_path, [folder], tmp_path / "model", "cpu", scorer)


def test_landmarks_are_read_as_the_scorer_counts_them(tmp_path: Path) -> None:
    """Through the scorer's view model (the user's landmark edits applied), removed ones left out."""
    loaded = []
    core = SimpleNamespace(Atlas=SimpleNamespace(load=lambda path: loaded.append(path) or "atlas"))

    def view_model(atlas):
        assert atlas == "atlas"
        return {"landmarks": [{"kind": "City", "x": 1, "y": 2, "status": "kept"},
                              {"kind": "Tower", "x": 3, "y": 4, "status": "removed: edit"}]}  # fmt: skip

    assert compare_detectors._live_landmarks(tmp_path, core, view_model) == [
        {"kind": "City", "x": 1, "y": 2, "status": "kept"}
    ]
    assert loaded == [tmp_path / "atlas.json"]


def test_only_the_scorers_own_no_placement_is_scored_as_an_empty_atlas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scorer says when the builder placed nothing (False): that atlas is scored empty. A missing file or program
    is an error, never an empty atlas (CodeRabbit)."""
    reference = tmp_path / "ref"
    reference.mkdir()
    (reference / "atlas.json").write_text("{}")
    folder = tmp_path / "res_1080_100"
    folder.mkdir()
    backend = compare_detectors.Backend("classical", lambda img: {})

    def missing(work: Path) -> bool:
        raise FileNotFoundError("python")

    with pytest.raises(FileNotFoundError):
        compare_detectors._rebuild_accuracy(
            backend, tmp_path, [folder], tmp_path / "model", "cpu", SimpleNamespace(REFERENCE="ref", rebuild=missing)
        )
    written = []
    scorer = SimpleNamespace(REFERENCE="ref", rebuild=lambda work: False, _import=lambda: (None, None))
    monkeypatch.setattr(compare_detectors, "_write_empty_atlas", lambda work: written.append(work.name))
    with pytest.raises(AttributeError):  # (the stand-in scorer has no numbers(): it stops after the rebuilds)
        compare_detectors._rebuild_accuracy(backend, tmp_path, [folder], tmp_path / "model", "cpu", scorer)
    assert written == ["res_1080_100"]


def test_timing_waits_only_for_the_device_that_infers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CPU run on a CUDA machine never synchronises CUDA; a CUDA device does (CodeRabbit)."""
    torch = pytest.importorskip("torch")
    calls = []
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device=None: calls.append(device))
    compare_detectors._synchronise_accelerator(None)
    compare_detectors._synchronise_accelerator(torch.device("cpu"))
    assert calls == []
    compare_detectors._synchronise_accelerator(torch.device("cuda"))
    assert calls == [torch.device("cuda")]


def test_the_scorer_comes_from_this_checkout_not_the_data_folder() -> None:
    """The atlas folder given on the command line is data: its own score_atlases.py is never run (CodeRabbit)."""
    assert compare_detectors.SCORER.is_relative_to(compare_detectors.project_paths.ROOT)
    assert compare_detectors.SCORER.is_file()


def test_landmarks_are_not_matched_by_place_without_a_shift_from_the_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    """No shift (the scorer found no map node to line the atlases up by) is not a zero shift: the counts are kept and
    nothing is matched by place; an explicit [0, 0] still matches (CodeRabbit)."""
    landmarks = {"Tower": [{"kind": "Tower", "x": 10.0, "y": 10.0}]}
    monkeypatch.setattr(compare_detectors, "_live_landmarks", lambda folder, core, view: landmarks["Tower"])
    kept = dict(scorer_core=None, view_model=None)
    none = compare_detectors._add_landmark_metrics(Path("a"), Path("b"), {}, 15.0, **kept)
    assert none["landmarks"] == "0 of 1 match; found 0 of 1 (0%)"
    zero = compare_detectors._add_landmark_metrics(Path("a"), Path("b"), {"shift": [0.0, 0.0]}, 15.0, **kept)
    assert zero["landmarks"] == "1 of 1 match; found 1 of 1 (100%)"


def test_a_checkpoint_replaced_while_it_is_copied_is_never_scored(tmp_path: Path, monkeypatch) -> None:
    """A training run publishes a new best/ by renaming a folder in: a copy across that is refused and removed."""
    given = tmp_path / "best"
    given.mkdir()
    (given / "model.safetensors").write_bytes(b"weights")
    copy = tmp_path / "copy"
    compare_detectors._copy_checkpoint(given, copy)
    assert (copy / "model.safetensors").read_bytes() == b"weights"

    real = compare_detectors.shutil.copytree

    def copy_then_swap(source, target, *args, **kwargs):
        real(source, target, *args, **kwargs)
        given.rename(tmp_path / "previous")
        (tmp_path / "next").mkdir()
        (tmp_path / "next").rename(given)

    monkeypatch.setattr(compare_detectors.shutil, "copytree", copy_then_swap)
    swapped = tmp_path / "swapped"
    with pytest.raises(SystemExit, match="replaced while it was copied"):
        compare_detectors._copy_checkpoint(given, swapped)
    assert not swapped.exists()
