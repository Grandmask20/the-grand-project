"""Shared setup of the dataset annotator tests (the project-wide fixtures are in ``tests/conftest.py``)."""

from __future__ import annotations

import pytest

from tools.detection_dataset_annotator import constants as K

FAKE_WORKER_MODULE = "tests.detection_dataset_annotator.fake_worker"
"""The stand-in detector worker (``fake_worker.py``), started with ``python -m`` like the real one."""


@pytest.fixture
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> str:
    """Make the worker pool start the fake worker instead of the detector (the pool reads the module live).

    Not autouse: ``test_worker.py`` checks the real worker's protocol.
    """
    monkeypatch.setattr(K, "ANNOTATOR_WORKER_MODULE", FAKE_WORKER_MODULE)
    return FAKE_WORKER_MODULE
