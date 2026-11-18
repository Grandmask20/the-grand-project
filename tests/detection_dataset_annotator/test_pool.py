"""The annotator's asyncio worker pool, run against the fake worker (``fake_worker.py``, see ``conftest.py``)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator import pool
from tools.detection_dataset_annotator.state import DetectionOptions

pytestmark = pytest.mark.usefixtures("fake_worker")

OPTIONS = DetectionOptions()


def _state(tmp_path: Path, *names: str) -> dict[str, Any]:
    """A review state with one undetected screenshot per name (the fake worker only looks at the name)."""
    return {"images": {name: {"path": str(tmp_path / f"{name}.png")} for name in names}}


def test_every_screenshot_is_detected_with_progress(tmp_path: Path) -> None:
    names = [f"ok{i}" for i in range(7)] + ["slow0", "big0"]
    state = _state(tmp_path, *names)
    calls: list[tuple[int, int, str]] = []

    completed, failed = pool.detect_pending(state, OPTIONS, max_workers=3, progress=lambda *call: calls.append(call))

    assert (completed, failed) == (len(names), 0)
    assert [done for done, _total, _path in calls] == list(range(1, len(names) + 1))
    assert all(total == len(names) for _done, total, _path in calls)
    for item in state["images"].values():
        assert item["detected"] is True and item["edit_version"] == 1
    assert len(state["images"]["big0"]["padding"]) == 200_000  # longer than asyncio's default line limit
    assert state["settings"] == OPTIONS.as_settings()


def test_a_screenshot_error_fails_only_that_screenshot(tmp_path: Path) -> None:
    state = _state(tmp_path, "ok0", "error0", "ok1")

    assert pool.detect_pending(state, OPTIONS, max_workers=2) == (2, 1)

    images = state["images"]
    assert images["error0"]["detected"] is False
    assert images["error0"]["error"] == "ValueError: Could not read image"
    assert images["ok0"]["detected"] and images["ok1"]["detected"]


def test_a_crashed_worker_fails_its_screenshots_and_the_others_finish(tmp_path: Path) -> None:
    names = ["crash0"] + [f"ok{i}" for i in range(8)]
    state = _state(tmp_path, *names)

    completed, failed = pool.detect_pending(state, OPTIONS, max_workers=2)

    assert completed + failed == len(names)
    assert 1 <= failed <= K.ANNOTATOR_WORKER_IN_FLIGHT  # the crash and what was queued behind it on that worker
    assert state["images"]["crash0"]["error"] == "Detection worker exited unexpectedly (code 3)."


def test_screenshots_left_when_every_worker_crashed_fail(tmp_path: Path) -> None:
    names = [f"crash{i}" for i in range(4)]
    state = _state(tmp_path, *names)

    assert pool.detect_pending(state, OPTIONS, max_workers=1) == (0, 4)

    errors = [state["images"][name]["error"] for name in names]
    assert errors[: K.ANNOTATOR_WORKER_IN_FLIGHT] == ["Detection worker exited unexpectedly (code 3)."] * 2
    assert set(errors[K.ANNOTATOR_WORKER_IN_FLIGHT :]) == {
        "All detection workers stopped before this screenshot was processed."
    }


def test_a_failed_rerun_keeps_the_previous_detections(tmp_path: Path) -> None:
    state = _state(tmp_path, "error0")
    previous = {"detected": True, "reviewed": True, "annotations": [{"label": "map_node"}], "edit_version": 4}
    state["images"]["error0"].update(previous)

    assert pool.detect_pending(state, OPTIONS, keys=["error0"], force=True, max_workers=1) == (0, 1)

    item = state["images"]["error0"]
    assert {key: item[key] for key in previous} == previous
    assert item["error"].startswith("Rerun failed; kept previous detections.")


def test_a_rerun_replaces_detections_and_clears_review(tmp_path: Path) -> None:
    state = _state(tmp_path, "ok0", "ok1")
    state["images"]["ok0"].update({"detected": True, "reviewed": True, "edit_version": 2})

    assert pool.detect_pending(state, OPTIONS, keys=["ok0"], force=True) == (1, 0)

    assert state["images"]["ok0"]["reviewed"] is False and state["images"]["ok0"]["edit_version"] == 3
    assert "detected" not in state["images"]["ok1"]  # not selected


def test_bad_arguments_are_refused(tmp_path: Path) -> None:
    state = _state(tmp_path, "ok0")
    with pytest.raises(ValueError, match="explicit image keys"):
        pool.detect_pending(state, OPTIONS, force=True)
    with pytest.raises(ValueError, match="positive"):
        pool.detect_pending(state, OPTIONS, max_workers=0)
    assert pool.detect_pending({"images": {}}, OPTIONS) == (0, 0)


def test_workers_get_their_share_of_every_thread_pool(tmp_path: Path) -> None:
    state = _state(tmp_path, "ok0", "ok1", "ok2")

    pool.detect_pending(state, OPTIONS, max_workers=2)

    expected = str(max(1, pool.cpu_count() // 2))
    for item in state["images"].values():
        assert set(item["threads"].values()) == {expected}
        assert set(item["threads"]) == {K.ANNOTATOR_OPENCV_THREADS_ENV, *K.ANNOTATOR_THREAD_ENV_VARS}


@pytest.mark.skipif(sys.platform == "win32", reason="checks the process ids with os.kill(pid, 0)")
def test_no_worker_outlives_the_run(tmp_path: Path) -> None:
    state = _state(tmp_path, *(f"ok{i}" for i in range(6)))

    pool.detect_pending(state, OPTIONS, max_workers=3)

    for pid in {item["pid"] for item in state["images"].values()}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_a_stop_from_the_progress_callback_is_raised_unwrapped(tmp_path: Path) -> None:
    """Streamlit's stop / rerun signals are raised inside the progress callback and must reach Streamlit as is."""

    class StopRun(BaseException):
        pass

    def progress(_done: int, _total: int, _path: str) -> None:
        raise StopRun

    with pytest.raises(StopRun):
        pool.detect_pending(_state(tmp_path, "slow0", "slow1", "slow2"), OPTIONS, max_workers=2, progress=progress)


def test_default_workers_fit_the_machine() -> None:
    assert 1 <= pool.default_workers() <= pool.cpu_count()
