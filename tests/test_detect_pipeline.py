"""The classical detector's pipeline (grand_project/detect/pipeline.py): the image-only stages on helper threads."""

from __future__ import annotations

import pytest

from grand_project.detect import pipeline


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
        helped = pipeline.detect(img.copy())  # (copies: nothing remembered for them yet)
        monkeypatch.setattr(pipeline, "DETECT_PREFETCH_THREADS", 0)
        alone = pipeline.detect(img.copy())
        monkeypatch.setattr(pipeline, "DETECT_PREFETCH_THREADS", 3)
        assert json.dumps(helped, sort_keys=True, default=str) == json.dumps(alone, sort_keys=True, default=str)
