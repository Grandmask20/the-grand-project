"""Tests for selecting the optional RF-DETR detector backend."""

from __future__ import annotations

import numpy as np

from grand_project.detect import pipeline
from grand_project.detect.constants import RF_DETR_MODEL_ENV, RF_DETR_USE_ENV
from grand_project.detect.rf_detr_model import rf_detr_enabled, rf_detr_model_path


def test_rf_detr_is_disabled_without_the_flag(monkeypatch):
    """The installed application keeps using the classical detector by default."""
    monkeypatch.delenv(RF_DETR_USE_ENV, raising=False)
    assert not rf_detr_enabled()


def test_rf_detr_accepts_common_true_values(monkeypatch):
    """Shell-friendly flag spellings all select the optional backend."""
    for value in ("1", "true", "yes", "on", " TRUE "):
        monkeypatch.setenv(RF_DETR_USE_ENV, value)
        assert rf_detr_enabled()


def test_rf_detr_model_path_can_be_overridden(monkeypatch, tmp_path):
    """Tests and deployments can keep the fine-tuned checkpoint outside the repository."""
    monkeypatch.setenv(RF_DETR_MODEL_ENV, str(tmp_path))
    assert rf_detr_model_path() == tmp_path


def test_pipeline_dispatches_to_rf_detr_when_enabled(monkeypatch):
    """The feature flag selects a complete result-producing backend."""
    expected = {"nodes": [], "icons": [], "landmarks": [], "edges": []}
    monkeypatch.setattr(pipeline, "rf_detr_enabled", lambda: True)
    monkeypatch.setattr(pipeline, "detect_rf_detr", lambda img: expected)
    assert pipeline.detect(np.zeros((8, 8, 3), dtype=np.uint8)) is expected
