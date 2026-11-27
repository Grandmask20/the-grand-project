"""The classical detector's pipeline (grand_project/detect/pipeline.py): its models are loaded once."""

from __future__ import annotations

import pytest

from grand_project.detect import pipeline


def test_a_missing_model_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model not in the DB yet raises and is not kept as None: once it is trained, the next call loads it."""
    loaded: dict = {}
    monkeypatch.setattr(pipeline, "_models", loaded)
    monkeypatch.setattr(pipeline, "load_model", lambda name: None)
    with pytest.raises(RuntimeError, match="no maps model"):
        pipeline.ensure_models()
    assert loaded == {}
    monkeypatch.setattr(pipeline, "load_model", lambda name: f"<{name}>")
    pipeline.ensure_models()
    assert loaded == {"maps": "<maps>", "badges": "<badges>", "towers": "<towers>"}
    monkeypatch.setattr(pipeline, "load_model", lambda name: pytest.fail("loaded twice"))
    pipeline.ensure_models()  # loaded once


STAGES = ("path_dashes", "special_icons", "old_landmarks", "fortress_walls", "amber_dashes", "square_buttons")


@pytest.fixture
def cv2_threads():
    """Set OpenCV's thread share for one test (the prefetch follows it), put back afterwards."""
    import cv2

    before = cv2.getNumThreads()
    yield cv2.setNumThreads
    cv2.setNumThreads(before)


def test_the_image_only_stages_are_worked_out_on_helper_threads(monkeypatch, cv2_threads) -> None:
    import threading

    import numpy as np

    ran: list[tuple[str, str]] = []
    for name in STAGES:
        monkeypatch.setattr(pipeline, name, lambda img, name=name: ran.append((name, threading.current_thread().name)))
    img = np.zeros((4, 4, 3), np.uint8)
    cv2_threads(4)
    with pipeline._prefetch(img):
        pass
    assert sorted(n for n, _ in ran) == sorted(STAGES)  # each once
    assert all(t.startswith("detect") for _, t in ran)  # on the helpers, done when the block ends
    ran.clear()
    cv2_threads(1)  # a worker capped at one thread: no helpers (it would go over its share)
    with pipeline._prefetch(img):
        pass
    assert ran == []


@pytest.mark.data
def test_the_detection_is_the_same_with_and_without_helper_threads(test_data, monkeypatch, cv2_threads) -> None:
    import json

    from grand_project import core

    cv2_threads(4)
    for shot in sorted((test_data / "screenshots" / "random_samples").glob("*.png"))[:2]:
        img = core.read_screenshot(str(shot))
        helped = pipeline.detect_classical(img.copy())  # (copies: nothing remembered for them yet)
        monkeypatch.setattr(pipeline, "DETECT_PREFETCH_THREADS", 0)
        alone = pipeline.detect_classical(img.copy())
        monkeypatch.setattr(pipeline, "DETECT_PREFETCH_THREADS", 3)
        assert json.dumps(helped, sort_keys=True, default=str) == json.dumps(alone, sort_keys=True, default=str)
