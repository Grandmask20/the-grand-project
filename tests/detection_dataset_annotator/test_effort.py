"""Review effort (tools/detection_dataset_annotator/effort.py): what a review changed of a screenshot's pre-labels, and
the report comparing the live loop's arms."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.detection_dataset_annotator import ReviewStore, effort, image_key
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.effort import (
    Edits,
    Review,
    arm_reports,
    edit_cost,
    fit_seconds,
    report_lines,
    reviews,
    total,
)


def _box(label: str, x: float, y: float, w: float = 38.7, h: float = 38.7, **fields: Any) -> dict[str, Any]:
    return {"label": label, "bbox": [x, y, w, h], **fields}


def test_each_kind_of_edit_is_counted_per_family() -> None:
    before = [
        _box("map_node_grass", 100, 100),  # kept (a 1 px nudge is within the box rules' tolerance)
        _box("map_node_vaal", 300, 300),  # relabelled within its family
        _box("icon", 500, 500, 34, 34),  # deleted: no icon near it afterwards
        _box("tower", 700, 100, 80, 220),  # moved by 40 px: under the move overlap
    ]
    after = [
        _box("map_node_grass", 101, 100),
        _box("map_node_grass", 300, 300),
        _box("icon", 900, 500, 34, 34),  # drawn
        _box("tower", 740, 100, 80, 220),
    ]
    edits = edit_cost(before, after)
    assert edits["node"] == Edits(kept=1, relabelled=1)
    assert edits["icon"] == Edits(deleted=1, added=1)
    assert edits["tower"] == Edits(kept=1, moved=1)
    assert total(edits).edits == 4 and total(edits).kept == 2  # relabel, move, delete, add
    assert total(edits).seconds() == pytest.approx(
        2 * K.ANNOTATOR_EFFORT_SECONDS["kept"]
        + K.ANNOTATOR_EFFORT_SECONDS["relabelled"]
        + K.ANNOTATOR_EFFORT_SECONDS["moved"]
        + K.ANNOTATOR_EFFORT_SECONDS["deleted"]
        + K.ANNOTATOR_EFFORT_SECONDS["added"]
    )


def test_matching_is_one_to_one_and_the_fewest_edits() -> None:
    """Two nodes 30 px apart, the reviewed ones shifted 12 px: a greedy match could pair the first pre-label with the
    second reviewed box and leave one each side; the assignment keeps both."""
    before = [_box("map_node", 100, 100), _box("map_node", 130, 100)]
    after = [_box("map_node", 112, 100), _box("map_node", 142, 100)]
    assert edit_cost(before, after)["node"] == Edits(kept=2, moved=2)


def test_radii_scale_with_the_screenshot() -> None:
    """A 4K screenshot's boxes are twice the detector's pixels: so is the match radius (node: 20 px at 1080p)."""
    before, after = [_box("map_node", 100, 100, 77.4, 77.4)], [_box("map_node", 130, 100, 77.4, 77.4)]
    assert edit_cost(before, after)["node"] == Edits(deleted=1, added=1)
    assert edit_cost(before, after, width=3840)["node"] == Edits(kept=1, moved=1)


def test_only_the_families_asked_for_are_scored() -> None:
    before = [_box("map_node", 100, 100), _box("icon", 300, 300, 34, 34)]
    assert set(edit_cost(before, [], families=["icon"])) == {"icon"}


def _reviewed(store: ReviewStore, path: Path, final: list[dict], *, arm: str | None, active_s: float | None) -> None:
    store.add_images([path])
    key = image_key(path)
    store.record_detection(
        key, {"width": 1920, "height": 1080, "annotations": [_box("icon", 10, 10, 34, 34)]}, force=False
    )
    extra = {}
    if arm is not None:
        extra[K.ANNOTATOR_PRELABEL_FIELD] = {"source": arm}
    if active_s is not None:
        extra[K.ANNOTATOR_REVIEW_FIELD] = {"active_s": active_s}
    store.save_review(key, 1, annotations=final, reviewed=True, extra=extra)


def test_the_report_compares_the_arms(tmp_path: Path, review_store: ReviewStore) -> None:
    """Each reviewed screenshot against its pre-label snapshot, grouped by what pre-labelled it."""
    folder = tmp_path / "shots"
    folder.mkdir()
    kept = [_box("icon", 10, 10, 34, 34)]
    _reviewed(review_store, folder / "a.png", kept, arm=None, active_s=20.0)  # classical, untouched
    _reviewed(review_store, folder / "b.png", [*kept, _box("tower", 500, 100, 80, 220)], arm="rf_detr", active_s=40.0)
    rows = reviews(review_store)
    assert [(row.arm, row.edits.edits, row.active_s) for row in rows] == [("classical", 0, 20.0), ("rf_detr", 1, 40.0)]
    arms = arm_reports(rows)
    assert arms["rf_detr"].edits_per_screenshot["added"] == 1.0 and arms["classical"].active_s_median == 20.0
    lines = report_lines(rows)
    assert lines[1].startswith("classical") and lines[2].startswith("rf_detr")
    assert fit_seconds(rows) is None  # too few timed reviews to fit


def test_seconds_per_edit_are_fitted_to_the_timer() -> None:
    rows = [
        Review(f"k{i}", "classical", Edits(kept=10, added=i % 4), boxes=10 + i % 4, active_s=10 * 0.3 + (i % 4) * 6.0)
        for i in range(K.ANNOTATOR_EFFORT_MIN_FIT + 2)
    ]
    fitted = fit_seconds(rows)
    assert fitted is not None and fitted["added"] == pytest.approx(6.0, abs=0.01)
    assert fitted["kept"] == pytest.approx(0.3, abs=0.01)


def test_the_command_line_reports_the_default_store(tmp_path: Path, annotator_output_dir: Path) -> None:
    """Without ``--output-dir`` it reads the annotator's default folder (each test's own, ``tests/conftest.py``: never
    the reviewer's store) and saves the report as JSON; with nothing reviewed it says so and exits 1."""
    folder = tmp_path / "shots"
    folder.mkdir()
    with ReviewStore.open(annotator_output_dir / K.ANNOTATOR_STORE_FILE) as store:
        kept = [_box("icon", 10, 10, 34, 34)]
        _reviewed(store, folder / "a.png", [*kept, _box("tower", 500, 100, 80, 220)], arm="rf_detr", active_s=12.0)
    report = tmp_path / "effort.json"
    assert effort.main(["--json", str(report)]) == 0
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["arms"]["rf_detr"]["screenshots"] == 1
    assert saved["reviews"][0]["edits"]["added"] == 1 and saved["reviews"][0]["active_s"] == 12.0
    assert effort.main(["--output-dir", str(tmp_path / "nothing")]) == 1
