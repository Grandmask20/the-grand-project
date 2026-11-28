"""Tests for detect.detector_config: which detector a process runs, and how it is chosen."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from grand_project import builder
from grand_project import fileio as atlas_io
from grand_project.detect import constants as K
from grand_project.detect import detector_config, pipeline
from grand_project.detect.detector_config import DetectorConfig
from grand_project.detect.rf_detr_model import rf_detr_enabled, rf_detr_model_path


def test_the_classical_detector_is_the_default():
    """The installed program keeps using the classical detector until RF-DETR is chosen."""
    assert detector_config.current() == DetectorConfig()
    assert not rf_detr_enabled()
    assert rf_detr_model_path() == K.RF_DETR_DEFAULT_MODEL_DIR


def test_saved_or_sent_settings_are_brought_into_range():
    """A device it doesn't know is "auto", a worker count below 1 is 1 and one that is no number the default; a model
    is trimmed, and keys left out keep their defaults."""
    assert DetectorConfig.from_dict({}) == DetectorConfig()
    got = DetectorConfig.from_dict({"rf_detr": 1, "model": "  me/model@v2 ", "device": " CUDA ", "workers": "0"})
    assert got == DetectorConfig(rf_detr=True, model="me/model@v2", device="cuda", workers=1)
    assert DetectorConfig.from_dict({"device": "tpu", "workers": "many", "model": None}) == DetectorConfig()
    assert DetectorConfig.from_dict(got.to_dict()) == got


def test_the_chosen_model_and_device_are_the_ones_used(detector, tmp_path):
    detector(rf_detr=True, model=str(tmp_path), device="cpu")
    assert rf_detr_enabled() and rf_detr_model_path() == tmp_path


def test_the_command_line_flags_choose_the_detector_and_pass_it_on():
    """``add_arguments`` / ``from_args`` read the flags ``cli_args`` writes (the builder run by compare_detectors)."""
    ap = argparse.ArgumentParser()
    detector_config.add_arguments(ap)
    assert detector_config.from_args(ap.parse_args([])) == DetectorConfig()
    assert detector_config.cli_args(DetectorConfig()) == []
    chosen = DetectorConfig(rf_detr=True, model="me/model", device="cpu")
    assert detector_config.from_args(ap.parse_args(detector_config.cli_args(chosen))) == chosen
    default_model = ap.parse_args(detector_config.cli_args(DetectorConfig(rf_detr=True))).rf_detr_model
    assert default_model == str(K.RF_DETR_DEFAULT_MODEL_DIR)  # (named: the builder runs in another folder)


def test_the_pipeline_dispatches_to_rf_detr_when_chosen(monkeypatch, detector):
    """The setting selects a complete result-producing backend."""
    expected = {"nodes": [], "icons": [], "landmarks": [], "edges": []}
    monkeypatch.setattr(pipeline, "detect_rf_detr", lambda img: expected)
    detector(rf_detr=True)
    assert pipeline.detect(np.zeros((8, 8, 3), dtype=np.uint8)) is expected


def test_a_missing_package_is_named(monkeypatch):
    found = {"torch"}
    monkeypatch.setattr(detector_config.importlib.util, "find_spec", lambda name: name if name in found else None)
    assert detector_config.rf_detr_missing() == "transformers"
    found.update(K.RF_DETR_PACKAGES)
    assert detector_config.rf_detr_missing() is None


def _worker_detector() -> DetectorConfig:
    return detector_config.current()


def test_the_detection_workers_run_their_parents_detector(detector):
    """Spawned workers start with the default settings: the pool hands them the parent's."""
    detector(rf_detr=True, model="me/model", device="cpu", workers=2)
    with builder._detect_pool(1) as pool:
        assert pool.submit(_worker_detector).result() == detector_config.current()


def test_the_set_worker_count_detects_at_once(monkeypatch, detector, tmp_path):
    """detect_uncached uses the settings' worker count (within the cores): one worker detects one at a time."""
    pools = []
    monkeypatch.setattr(builder, "is_cached", lambda path, cache: False)
    monkeypatch.setattr(builder, "_detect_pool", lambda workers: pools.append(workers) or atlas_io.process_pool(0))
    shots = [Path(tmp_path / f"{i}.png") for i in range(3)]
    detector(workers=1)
    assert builder.detect_uncached(shots, tmp_path) == {} and pools == []
    detector(workers=2)
    monkeypatch.setattr(atlas_io, "workers", lambda wanted: wanted)
    builder.detect_uncached(shots, tmp_path)  # (a pool of 0 workers fails: logged, detected one at a time later)
    assert pools == [2]
