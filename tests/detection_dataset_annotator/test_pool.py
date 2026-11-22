"""The annotator's asyncio worker pool, run against the fake worker (``fake_worker.py``, see ``conftest.py``) and a
review store in ``tmp_path``."""

from __future__ import annotations

import os
import sys
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from tools.detection_dataset_annotator import ReviewStore, image_key, pool
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.state import DetectionOptions

pytestmark = pytest.mark.usefixtures("fake_worker")

OPTIONS = DetectionOptions()


def _add(store: ReviewStore, tmp_path: Path, *names: str) -> dict[str, str]:
    """One undetected screenshot per name (the fake worker only looks at the name); return name -> image key."""
    paths = [tmp_path / f"{name}.png" for name in names]
    store.add_images(paths)
    return {name: image_key(path) for name, path in zip(names, paths, strict=True)}


def _items(store: ReviewStore, keys: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The saved screenshots by name."""
    return {name: store.item(key) for name, key in keys.items()}


def test_every_screenshot_is_detected_with_progress(tmp_path: Path, review_store: ReviewStore) -> None:
    names = [f"ok{i}" for i in range(7)] + ["slow0", "big0"]
    keys = _add(review_store, tmp_path, *names)
    review_store.set_settings(DetectionOptions(named_icons=True))
    calls: list[tuple[int, int, str]] = []

    completed, failed = pool.detect_pending(
        review_store, OPTIONS, max_workers=3, progress=lambda *call: calls.append(call)
    )

    assert (completed, failed) == (len(names), 0)
    assert [done for done, _total, _path in calls] == list(range(1, len(names) + 1))
    assert all(total == len(names) for _done, total, _path in calls)
    items = _items(review_store, keys)
    for item in items.values():
        assert item["detected"] is True and item["edit_version"] == 1
    assert len(items["big0"]["padding"]) == 200_000  # longer than asyncio's default line limit
    assert review_store.settings() == OPTIONS


def test_a_screenshot_error_fails_only_that_screenshot(tmp_path: Path, review_store: ReviewStore) -> None:
    keys = _add(review_store, tmp_path, "ok0", "error0", "ok1")

    assert pool.detect_pending(review_store, OPTIONS, max_workers=2) == (2, 1)

    images = _items(review_store, keys)
    assert images["error0"]["detected"] is False
    assert images["error0"]["error"] == "ValueError: Could not read image"
    assert images["ok0"]["detected"] and images["ok1"]["detected"]


def test_a_crashed_worker_fails_its_screenshots_and_the_others_finish(
    tmp_path: Path, review_store: ReviewStore
) -> None:
    names = ["crash0"] + [f"ok{i}" for i in range(8)]
    keys = _add(review_store, tmp_path, *names)

    completed, failed = pool.detect_pending(review_store, OPTIONS, max_workers=2)

    assert completed + failed == len(names)
    assert 1 <= failed <= K.ANNOTATOR_WORKER_IN_FLIGHT  # the crash and what was queued behind it on that worker
    assert review_store.item(keys["crash0"])["error"] == "Detection worker exited unexpectedly (code 3)."


def test_a_stuck_worker_is_stopped_and_the_others_finish(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that answers nothing within ANNOTATOR_WORKER_ANSWER_S is stopped: the screenshots it holds fail and
    stay retryable, the other worker goes on."""
    monkeypatch.setattr(K, "ANNOTATOR_WORKER_ANSWER_S", 1.0)
    names = ["hang0"] + [f"ok{i}" for i in range(6)]
    keys = _add(review_store, tmp_path, *names)

    completed, failed = pool.detect_pending(review_store, OPTIONS, max_workers=2)

    assert completed + failed == len(names)
    assert 1 <= failed <= K.ANNOTATOR_WORKER_IN_FLIGHT  # the stuck one and what was queued behind it on that worker
    items = _items(review_store, keys)
    assert items["hang0"]["detected"] is False
    assert items["hang0"]["error"] == "Detection worker did not answer within 1 s; it was stopped."
    assert sum(item["detected"] for item in items.values()) == completed


def test_screenshots_left_when_every_worker_crashed_fail(tmp_path: Path, review_store: ReviewStore) -> None:
    names = [f"crash{i}" for i in range(4)]
    keys = _add(review_store, tmp_path, *names)

    assert pool.detect_pending(review_store, OPTIONS, max_workers=1) == (0, 4)

    errors = [review_store.item(keys[name])["error"] for name in names]
    assert errors[: K.ANNOTATOR_WORKER_IN_FLIGHT] == ["Detection worker exited unexpectedly (code 3)."] * 2
    assert set(errors[K.ANNOTATOR_WORKER_IN_FLIGHT :]) == {
        "All detection workers stopped before this screenshot was processed."
    }


def test_a_failed_rerun_keeps_the_previous_detections(tmp_path: Path, review_store: ReviewStore) -> None:
    key = _add(review_store, tmp_path, "error0")["error0"]
    box = {"label": "map_node", "bbox": [1, 2, 3, 4], "iscrowd": 0}
    review_store.record_detection(key, {"detected": True, "annotations": [box]}, force=False)
    review_store.save_review(key, 1, reviewed=True)
    previous = review_store.item(key)

    assert pool.detect_pending(review_store, OPTIONS, keys=[key], force=True, max_workers=1) == (0, 1)

    item = review_store.item(key)
    assert item.pop("error").startswith("Rerun failed; kept previous detections.")
    assert item == previous


def test_a_rerun_replaces_detections_and_clears_review(tmp_path: Path, review_store: ReviewStore) -> None:
    keys = _add(review_store, tmp_path, "ok0", "ok1")
    review_store.record_detection(keys["ok0"], {"detected": True, "annotations": []}, force=False)
    review_store.save_review(keys["ok0"], 1, reviewed=True)

    assert pool.detect_pending(review_store, OPTIONS, keys=[keys["ok0"]], force=True) == (1, 0)

    items = _items(review_store, keys)
    assert items["ok0"]["reviewed"] is False and items["ok0"]["edit_version"] == 2
    assert items["ok1"]["detected"] is False  # not selected


def test_bad_arguments_are_refused(tmp_path: Path, review_store: ReviewStore) -> None:
    assert pool.detect_pending(review_store, OPTIONS) == (0, 0)  # nothing to detect
    _add(review_store, tmp_path, "ok0")
    with pytest.raises(ValueError, match="explicit image keys"):
        pool.detect_pending(review_store, OPTIONS, force=True)
    with pytest.raises(ValueError, match="positive"):
        pool.detect_pending(review_store, OPTIONS, max_workers=0)


def test_workers_get_their_share_of_every_thread_pool(tmp_path: Path, review_store: ReviewStore) -> None:
    keys = _add(review_store, tmp_path, "ok0", "ok1", "ok2")

    pool.detect_pending(review_store, OPTIONS, max_workers=2)

    expected = str(max(1, pool.cpu_count() // 2))
    for item in _items(review_store, keys).values():
        assert set(item["threads"].values()) == {expected}
        assert set(item["threads"]) == {K.ANNOTATOR_OPENCV_THREADS_ENV, *K.ANNOTATOR_THREAD_ENV_VARS}


@pytest.mark.skipif(sys.platform == "win32", reason="checks the process ids with os.kill(pid, 0)")
def test_no_worker_outlives_the_run(tmp_path: Path, review_store: ReviewStore) -> None:
    keys = _add(review_store, tmp_path, *(f"ok{i}" for i in range(6)))

    pool.detect_pending(review_store, OPTIONS, max_workers=3)

    for pid in {item["pid"] for item in _items(review_store, keys).values()}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_a_stop_from_the_progress_callback_is_raised_unwrapped(tmp_path: Path, review_store: ReviewStore) -> None:
    """Streamlit's stop / rerun signals are raised inside the progress callback and must reach Streamlit as is; the
    screenshot finished before the stop is already saved."""

    class StopRun(BaseException):
        pass

    def progress(_done: int, _total: int, _path: str) -> None:
        raise StopRun

    keys = _add(review_store, tmp_path, "slow0", "slow1", "slow2")
    with pytest.raises(StopRun):
        pool.detect_pending(review_store, OPTIONS, max_workers=2, progress=progress)
    assert sum(item["detected"] for item in _items(review_store, keys).values()) >= 1


def test_default_workers_fit_the_machine() -> None:
    assert 1 <= pool.default_workers() <= pool.cpu_count()


def test_a_screenshot_removed_while_it_was_detected_is_skipped(tmp_path: Path, review_store: ReviewStore) -> None:
    """A rebuild removed a screenshot while its answer was on the way: the answer is dropped and the run goes on; a
    KeyError for a screenshot still in the store is a bug, and raised."""
    keys = _add(review_store, tmp_path, "gone", "kept")
    seen: list[int] = []
    run = pool._Run(
        store=review_store, pending=deque(), force=False, progress=lambda done, total, path: seen.append(done)
    )
    run.total = 2
    review_store.remove_unreviewed([keys["gone"]])
    run.succeed((keys["gone"], "gone.png"), {"width": 1920, "height": 1080, "annotations": []})
    run.fail((keys["gone"], "gone.png"), "boom")
    assert (run.completed, run.errors, run.removed, seen) == (0, 0, 2, [1, 2])

    def broken(key, result, *, force):
        raise KeyError("a bug")

    review_store.record_detection = broken  # type: ignore[method-assign]
    with pytest.raises(KeyError, match="a bug"):
        run.succeed((keys["kept"], "kept.png"), {"annotations": []})
