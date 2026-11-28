"""The annotator's review store (tools/detection_dataset_annotator/store.py): screenshots and boxes in SQLite, saved
one screenshot at a time and safe between sessions."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from tools.detection_dataset_annotator import DetectionOptions, ReviewStore, image_key
from tools.detection_dataset_annotator import constants as K


def _shots(tmp_path: Path, *names: str) -> list[Path]:
    """Screenshot files (the store only reads their paths)."""
    folder = tmp_path / "shots"
    folder.mkdir(exist_ok=True)
    paths = [folder / name for name in names]
    for path in paths:
        path.write_bytes(b"x")
    return paths


def _box(label: str, x: float, **fields: Any) -> dict[str, Any]:
    return {
        "label": label,
        "bbox": [x, 20.0, 34.0, 34.0],
        "area": 1156.0,
        "iscrowd": 0,
        "source": "classical",
        **fields,
    }


def _result(*annotations: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A detection result as the worker sends it."""
    return {
        "detected": True,
        "detector": "classical",
        "width": 1920,
        "height": 1080,
        "detector_width": 1920,
        "detector_height": 1080,
        "annotations": list(annotations),
        "error": None,
        **fields,
    }


def _detected(store: ReviewStore, path: Path, *annotations: dict[str, Any]) -> str:
    """Add a screenshot and record a detection of it; return its key."""
    store.add_images([path])
    key = image_key(path)
    store.record_detection(key, _result(*annotations), force=False)
    return key


def test_discovered_screenshots_join_the_queue_once(tmp_path: Path, review_store: ReviewStore) -> None:
    """Discovery adds new screenshots at the end of the queue and keeps the ones already there as they are."""
    a, b, c = _shots(tmp_path, "a.png", "b.png", "c.png")
    assert review_store.add_images([b, a]) == (2, 0)
    key = _detected(review_store, b, _box("map_node", 10))
    assert review_store.add_images([a, b, c, c]) == (1, 3)

    queue = review_store.queue()
    assert [entry.key for entry in queue] == [image_key(b), image_key(a), image_key(c)]
    assert [(entry.detected, entry.reviewed) for entry in queue] == [(True, False), (False, False), (False, False)]
    assert review_store.item(key)["annotations"][0]["label"] == "map_node"  # kept
    fresh = review_store.item(image_key(c))
    assert fresh["path"] == str(c) and fresh["source"].endswith("c.png")
    assert (fresh["detected"], fresh["reviewed"], fresh["edit_version"], fresh["annotations"]) == (False, False, 0, [])
    assert review_store.item("missing") is None


def test_settings_and_roots_are_kept(tmp_path: Path) -> None:
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(path, [tmp_path / "shots"]) as store:
        assert store.settings() == DetectionOptions()
        assert store.input_roots() == [str(tmp_path / "shots")]
        store.set_settings(DetectionOptions(named_icons=True))
        store.set_input_roots([tmp_path / "other"])
    with ReviewStore.open(path, [tmp_path / "ignored"]) as store:  # roots are only a new store's
        assert store.settings() == DetectionOptions(named_icons=True)
        assert store.input_roots() == [str(tmp_path / "other")]


def test_a_detection_result_is_saved_with_box_ids(tmp_path: Path, review_store: ReviewStore) -> None:
    """Every box gets a stable id; the result's other fields are kept; a rerun raises the revision, clears the review
    flag and never reuses an id."""
    (path,) = _shots(tmp_path, "a.png")
    review_store.add_images([path])
    key = image_key(path)
    nan_box = {"label": "icon", "bbox": [float("nan"), 1, 2, 3], "iscrowd": 0, "source": "classical"}
    review_store.record_detection(key, _result(_box("map_node", 10, score=0.9), nan_box, pid=7), force=False)

    item = review_store.item(key)
    assert item["detected"] is True and item["edit_version"] == 1 and "error" not in item
    assert (item["width"], item["height"], item["detector"], item["pid"]) == (1920, 1080, "classical", 7)
    assert item["annotations"] == [
        {"id": "b0", **_box("map_node", 10, score=0.9)},
        {"id": "b1", "label": "icon", "bbox": [None, 1.0, 2.0, 3.0], "iscrowd": 0, "source": "classical"},
    ]  # SQLite keeps a NaN as NULL; the editor and export skip that box

    assert review_store.save_review(key, 1, reviewed=True)
    review_store.record_detection(key, _result(_box("tower", 30)), force=True)
    item = review_store.item(key)
    assert item["edit_version"] == 2 and item["reviewed"] is False and "pid" not in item
    assert [a["id"] for a in item["annotations"]] == ["b2"]

    with pytest.raises(KeyError):
        review_store.record_detection("missing", _result(), force=False)


def test_editor_saves_after_a_rerun_are_refused(tmp_path: Path, review_store: ReviewStore) -> None:
    """A save carries the revision the editor showed: after a detector rerun it changes nothing."""
    (path,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, path, _box("map_node", 10), _box("icon", 50))
    shown = review_store.item(key)

    edited = [shown["annotations"][1], _box("tower", 90, source="manual"), _box("hall", 99, id="b1")]
    assert review_store.save_review(key, 1, annotations=edited, reviewed=True)
    item = review_store.item(key)
    assert [(a["id"], a["label"]) for a in item["annotations"]] == [("b1", "icon"), ("b2", "tower"), ("b3", "hall")]
    assert item["reviewed"] is True and item["next_annotation_id"] == 4  # duplicate id b1 got a new one

    review_store.record_detection(key, _result(_box("citadel_stone", 5)), force=True)
    before = review_store.item(key)
    assert not review_store.save_review(key, 1, annotations=[], reviewed=True)  # the editor still shows revision 1
    assert review_store.item(key) == before
    assert not review_store.save_review("missing", 0, reviewed=True)


def test_two_sessions_keep_each_others_changes(tmp_path: Path) -> None:
    """A detection run and the editor (another browser tab) write to one store at once: each changes only its own
    screenshot, so neither undoes the other."""
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    a, b = _shots(tmp_path, "a.png", "b.png")
    with ReviewStore.open(path) as setup:
        key_b = _detected(setup, b, _box("map_node", 10))
        setup.add_images([a])
    with ReviewStore.open(path) as run, ReviewStore.open(path) as editor:
        run.set_settings(DetectionOptions(named_icons=True))
        shown = editor.item(key_b)
        run.record_detection(image_key(a), _result(_box("tower", 40)), force=False)
        assert editor.save_review(key_b, shown["edit_version"], annotations=[_box("icon", 60, source="manual")])
    with ReviewStore.open(path) as check:
        assert [box["label"] for box in check.item(image_key(a))["annotations"]] == ["tower"]
        assert [box["label"] for box in check.item(key_b)["annotations"]] == ["icon"]
        assert check.settings() == DetectionOptions(named_icons=True)


def _in_sessions(path: Path, *saves) -> list[Any]:
    """Run each save in its own session on its own thread, all let go at the same moment; their results in order."""
    results: list[Any] = [None] * len(saves)
    start = threading.Barrier(len(saves))

    def run(k: int) -> None:
        with ReviewStore.open(path) as store:  # (a SQLite connection belongs to the thread that made it)
            start.wait(5)
            results[k] = saves[k](store)

    threads = [threading.Thread(target=run, args=(k,)) for k in range(len(saves))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def test_a_save_waits_for_another_session_s_write_then_goes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detection run holds the write lock while it saves a result: an editor's save waits for it (up to
    ``ANNOTATOR_STORE_BUSY_S``), it doesn't fail with "database is locked"."""
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    (shot,) = _shots(tmp_path, "a.png")
    with ReviewStore.open(path) as setup:
        key = _detected(setup, shot, _box("map_node", 10))
    writing = threading.Event()
    write = ReviewStore._write

    @contextlib.contextmanager
    def seen_writing(self):
        writing.set()  # the save is at its write transaction (BEGIN IMMEDIATE next)
        with write(self):
            yield

    monkeypatch.setattr(ReviewStore, "_write", seen_writing)
    other = sqlite3.connect(str(path), isolation_level=None)
    try:
        other.execute("BEGIN IMMEDIATE")  # (another session in the middle of a write)
        saved: list[bool] = []
        editor = threading.Thread(
            target=lambda: saved.extend(_in_sessions(path, lambda s: s.save_review(key, 1, reviewed=True)))
        )
        editor.start()
        assert writing.wait(10)
        editor.join(0.5)
        assert editor.is_alive() and not saved  # waiting for the lock, not refused
    finally:
        if other.in_transaction:
            other.execute("COMMIT")
        other.close()
    editor.join(30)
    assert saved == [True]
    with ReviewStore.open(path) as check:
        assert check.item(key)["reviewed"] is True


def test_two_tabs_saving_edits_of_the_same_boxes_at_once_keep_exactly_one(tmp_path: Path, rng, runs) -> None:
    """Two browser tabs edit one screenshot from the same boxes and save together: the first save wins and the
    other is refused (it would drop the first one's edit), whichever comes first."""
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    shots = _shots(tmp_path, *(f"{k}.png" for k in range(runs(10))))
    with ReviewStore.open(path) as setup:
        keys = [_detected(setup, shot, _box("map_node", 10)) for shot in shots]
    for key in keys:
        with ReviewStore.open(path) as reader:
            shown = reader.item(key)
        edits = [[_box(label, rng.uniform(0, 100), source="manual")] for label in ("tower", "hall")]
        saved = _in_sessions(
            path,
            *(
                lambda s, e=e, key=key, shown=shown: s.save_review(
                    key, shown["edit_version"], annotations=e, expect_boxes=shown["annotations"]
                )
                for e in edits
            ),
        )
        assert sorted(saved) == [False, True], saved
        with ReviewStore.open(path) as check:
            kept = [box["label"] for box in check.item(key)["annotations"]]
        assert kept == ["tower" if saved[0] else "hall"]


def test_a_failed_detection_keeps_what_a_rerun_replaces(tmp_path: Path, review_store: ReviewStore) -> None:
    new, old = _shots(tmp_path, "new.png", "old.png")
    review_store.add_images([new])
    review_store.record_failure(image_key(new), "ValueError: Could not read image", force=False)
    item = review_store.item(image_key(new))
    assert item["detected"] is False and item["error"] == "ValueError: Could not read image"

    key = _detected(review_store, old, _box("map_node", 10))
    review_store.save_review(key, 1, reviewed=True)
    previous = review_store.item(key)
    review_store.record_failure(key, "boom", force=True)
    item = review_store.item(key)
    assert item.pop("error") == "Rerun failed; kept previous detections. boom"
    assert item == previous


def test_a_late_result_of_another_run_changes_nothing(tmp_path: Path, review_store: ReviewStore) -> None:
    """Two runs took the same new screenshot: the first result stands with the edits made since; the second one's
    result or failure (not forced) is dropped. A forced rerun still replaces it."""
    (shot,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, shot, _box("map_node", 10))
    edited = [dict(_box("tower", 40), source="manual")]
    assert review_store.save_review(key, 1, annotations=edited, reviewed=True)
    before = review_store.item(key)
    assert review_store.record_detection(key, _result(_box("icon", 70)), force=False) is False
    review_store.record_failure(key, "boom", force=False)
    assert review_store.item(key) == before
    assert review_store.record_detection(key, _result(_box("icon", 70)), force=True) is True
    rerun = review_store.item(key)
    assert [box["label"] for box in rerun["annotations"]] == ["icon"] and rerun["reviewed"] is False


def test_detection_jobs_follow_selection_and_force(tmp_path: Path, review_store: ReviewStore) -> None:
    a, b, c = _shots(tmp_path, "a.png", "b.png", "c.png")
    review_store.add_images([a, b, c])
    review_store.record_detection(image_key(b), _result(), force=False)
    keys = [image_key(path) for path in (a, b, c)]
    assert review_store.detection_jobs() == [(keys[0], str(a), 0), (keys[2], str(c), 0)]
    assert review_store.detection_jobs(keys[:2]) == [(keys[0], str(a), 0)]
    assert review_store.detection_jobs(keys[1:], force=True) == [(keys[1], str(b), 1), (keys[2], str(c), 0)]


def test_a_rerun_queued_before_an_edit_or_review_changes_nothing(tmp_path: Path, review_store: ReviewStore) -> None:
    """A forced rerun asked for, then the screenshot edited or reviewed before its result came: the result (or its
    failure) is stale and dropped, the review kept; one queued after the edit goes through (CodeRabbit)."""
    (shot,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, shot, _box("icon", 10.0))
    ((_key, _path, generation),) = review_store.detection_jobs([key], force=True)
    assert review_store.save_review(key, 1, reviewed=True)
    before = review_store.item(key)
    assert not review_store.record_detection(key, _result(_box("tower", 30)), force=True, generation=generation)
    review_store.record_failure(key, "boom", force=True, generation=generation)
    assert review_store.item(key) == before
    ((_key, _path, now),) = review_store.detection_jobs([key], force=True)
    assert review_store.record_detection(key, _result(_box("tower", 30)), force=True, generation=now)
    assert review_store.item(key)["reviewed"] is False


def test_used_labels_are_sorted_and_distinct(tmp_path: Path, review_store: ReviewStore) -> None:
    assert review_store.used_labels() == []
    a, b = _shots(tmp_path, "a.png", "b.png")
    _detected(review_store, a, _box("tower", 1), _box("map_node", 2), _box("", 3))
    _detected(review_store, b, _box("map_node", 4), _box("icon_mapboss", 5))
    assert review_store.used_labels() == ["icon_mapboss", "map_node", "tower"]


def test_items_stream_in_queue_order(tmp_path: Path, review_store: ReviewStore) -> None:
    """Export reads every screenshot in one query; stopping early leaves the store free for writes."""
    a, b, c = _shots(tmp_path, "a.png", "b.png", "c.png")
    review_store.add_images([a])
    key_b = _detected(review_store, b, _box("map_node", 1), _box("icon", 2))
    key_c = _detected(review_store, c)
    review_store.save_review(key_c, 1, reviewed=True)

    items = dict(review_store.items())
    assert list(items) == [image_key(a), key_b, key_c]
    assert items[key_b] == review_store.item(key_b) and items[image_key(a)]["annotations"] == []
    assert [key for key, _item in review_store.items(reviewed_only=True)] == [key_c]

    stream = review_store.items()
    next(stream)
    stream.close()
    assert review_store.save_review(key_b, 1, reviewed=True)


def test_splits_are_kept(tmp_path: Path, review_store: ReviewStore) -> None:
    shots = _shots(tmp_path, "a.png", "b.png")
    review_store.add_images(shots)
    assert review_store.claim_splits({image_key(shots[0]): "test"}) == {image_key(shots[0]): "test"}
    assert review_store.splits() == {image_key(shots[0]): "test"}
    assert review_store.item(image_key(shots[0]))["split"] == "test"
    assert review_store.item(image_key(shots[1]))["split"] is None


def test_an_export_claims_only_splits_nobody_gave_yet(tmp_path: Path, review_store: ReviewStore) -> None:
    """Two exports at once: the second one's draw cannot move a screenshot the first one already gave a split; it
    gets the stored split back and uses it."""
    shots = _shots(tmp_path, "a.png", "b.png", "c.png")
    review_store.add_images(shots)
    a, b, c = (image_key(shot) for shot in shots)
    review_store.claim_splits({a: "train", c: "train"})  # given by an export that finished first
    claimed = review_store.claim_splits({a: "validation", b: "validation", c: "test"})
    assert claimed == {a: "train", b: "validation", c: "train"}
    assert review_store.splits() == claimed


def test_only_unreviewed_screenshots_are_removed(tmp_path: Path, review_store: ReviewStore) -> None:
    """Removing a screenshot takes its boxes along; a reviewed one stays (its review is the work to keep), and a key
    the store does not have is no error."""
    shots = _shots(tmp_path, "a.png", "b.png")
    review_store.add_images(shots)
    a, b = (image_key(shot) for shot in shots)
    for key in (a, b):
        review_store.record_detection(key, _result(_box("tower", 1.0)), force=False)
    review_store.save_review(b, 1, reviewed=True)

    assert review_store.remove_unreviewed([a, b, "missing", a]) == [a]
    assert list(review_store.paths()) == [b]
    assert review_store.item(a) is None
    count = review_store._db.execute("SELECT COUNT(*) FROM annotations WHERE image_key = ?", (a,)).fetchone()[0]
    assert count == 0


def test_a_backup_is_the_whole_store_and_never_overwrites(tmp_path: Path, review_store: ReviewStore) -> None:
    shots = _shots(tmp_path, "a.png")
    review_store.add_images(shots)
    review_store.record_detection(image_key(shots[0]), _result(_box("tower", 1.0)), force=False)
    target = tmp_path / "copy" / "backup.sqlite3"

    review_store.backup(target)
    with ReviewStore.open(target) as copy:
        assert copy.item(image_key(shots[0]))["annotations"] == review_store.item(image_key(shots[0]))["annotations"]
    with pytest.raises(FileExistsError):
        review_store.backup(target)


def test_prelabels_are_what_a_reviewer_was_first_shown(tmp_path: Path, review_store: ReviewStore) -> None:
    """Detection and new pre-labels (truth seeding, a model) replace the snapshot the review is measured against;
    a reviewer's edits never do."""
    (path,) = _shots(tmp_path, "a.png")
    key = image_key(path)
    review_store.add_images([path])
    review_store.record_detection(key, _result(_box("icon", 10.0), _box("tower", 50.0)), force=False)
    detected = [(a["id"], a["label"]) for a in review_store.prelabels(key)]
    assert detected == [("b0", "icon"), ("b1", "tower")]
    assert review_store.save_review(key, 1, annotations=[_box("hall", 90.0, id="b0")])  # an edit
    assert [(a["id"], a["label"]) for a in review_store.prelabels(key)] == detected
    assert review_store.save_review(key, 1, annotations=[_box("map_node_vaal", 10.0)], prelabel=True)
    assert [a["label"] for a in review_store.prelabels(key)] == ["map_node_vaal"]
    review_store.record_detection(key, _result(_box("icon", 10.0)), force=True)  # a rerun starts over
    assert [a["label"] for a in review_store.prelabels(key)] == ["icon"]


def test_extra_fields_merge_and_go_with_a_rerun(tmp_path: Path, review_store: ReviewStore) -> None:
    """A truth mark or a model pre-label record is merged into a screenshot's ``extra`` under the same
    revision check as its boxes (None removes a field); a detection rerun replaces them with the boxes."""
    (path,) = _shots(tmp_path, "a.png")
    key = image_key(path)
    review_store.add_images([path])
    review_store.record_detection(key, _result(_box("icon", 10.0)), force=False)
    assert review_store.save_review(key, 1, extra={"truth": "t.json", "review": {"active_s": 3.0}})
    assert review_store.save_review(key, 1, extra={"review": None, "prelabel": {"source": "rf_detr"}})
    item = review_store.item(key)
    assert (item["truth"], item["prelabel"], "review" in item) == ("t.json", {"source": "rf_detr"}, False)
    assert not review_store.save_review(key, 0, extra={"truth": "other.json"})  # an old revision: nothing saved
    review_store.record_detection(key, _result(_box("icon", 10.0)), force=True)
    assert "truth" not in review_store.item(key)


def test_an_untouched_save_leaves_a_review_in_progress(tmp_path: Path, review_store: ReviewStore) -> None:
    """A pass beside the page (model pre-labels) saves only while nobody edited or reviewed the screenshot: the check
    and the save are one write, so an edit made meanwhile is never overwritten."""
    shots = _shots(tmp_path, "a.png", "b.png", "c.png")
    fresh, edited, reviewed = (_detected(review_store, path, _box("icon", 10.0)) for path in shots)
    assert review_store.save_review(edited, 1, annotations=[_box("tower", 10.0, id="b0")])
    assert review_store.save_review(reviewed, 1, reviewed=True)
    new = [_box("map_node_vaal", 10.0)]
    assert review_store.save_review(fresh, 1, annotations=new, prelabel=True, untouched=True)
    assert not review_store.save_review(edited, 1, annotations=new, prelabel=True, untouched=True)
    assert not review_store.save_review(reviewed, 1, annotations=new, prelabel=True, untouched=True)
    labels = {key: [a["label"] for a in review_store.item(key)["annotations"]] for key in (fresh, edited, reviewed)}
    assert labels == {fresh: ["map_node_vaal"], edited: ["tower"], reviewed: ["icon"]}


def test_a_background_save_needs_the_boxes_it_worked_from_and_no_mark(
    tmp_path: Path, review_store: ReviewStore
) -> None:
    """A pass that read a screenshot's boxes (and saw no truth mark) saves only while they are still those boxes and no
    mark was set meanwhile: another pass's boxes or mark are never overwritten from an older read."""
    first, second = _shots(tmp_path, "a.png", "b.png")
    key, marked = (
        _detected(review_store, first, _box("icon", 10.0)),
        _detected(review_store, second, _box("icon", 10.0)),
    )
    snapshot = review_store.item(key)["annotations"]
    seeded = [_box("map_node_vaal", 10.0)]
    assert review_store.save_review(key, 1, annotations=seeded, prelabel=True, untouched=True)  # another pass
    revision = review_store.item(key)["edit_version"]
    assert revision == 2  # new pre-labels: an editor showing the old boxes reloads
    late = [_box("map_node_grass", 10.0)]
    assert not review_store.save_review(key, revision, annotations=late, prelabel=True, expect_boxes=snapshot)
    assert [a["label"] for a in review_store.item(key)["annotations"]] == ["map_node_vaal"]
    assert review_store.save_review(key, revision, annotations=late, expect_boxes=review_store.item(key)["annotations"])
    assert review_store.save_review(marked, 1, extra={K.ANNOTATOR_TRUTH_MARK: "truth.json"})
    assert not review_store.save_review(marked, 1, annotations=late, unmarked=[K.ANNOTATOR_TRUTH_MARK])
    assert review_store.save_review(marked, 1, extra={"note": 1}, unmarked=["other"])


def test_new_pre_labels_turn_away_an_editor_showing_the_old_boxes(tmp_path: Path, review_store: ReviewStore) -> None:
    """An editor opened before a model or truth pass would save the old boxes (and its edits) over the pass's: the
    pass raises the revision as a detection does, so the editor's late save is refused and it reloads."""
    (path,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, path, _box("icon", 10.0))
    shown = review_store.item(key)
    assert review_store.save_review(key, shown["edit_version"], annotations=[_box("tower", 10.0)], prelabel=True)
    edited = [dict(shown["annotations"][0], label="hall")]
    assert not review_store.save_review(key, shown["edit_version"], annotations=edited)
    assert [a["label"] for a in review_store.item(key)["annotations"]] == ["tower"]
    marked = review_store.item(key)["edit_version"]
    assert review_store.save_review(key, marked, extra={"note": 1})  # no boxes: the revision stays
    assert review_store.item(key)["edit_version"] == marked


def test_a_save_can_need_its_own_mark_or_none(tmp_path: Path, review_store: ReviewStore) -> None:
    """``marked``: the field is absent or already this value; another truth's mark set meanwhile refuses the save."""
    (path,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, path, _box("icon", 10.0))
    mine = {K.ANNOTATOR_TRUTH_MARK: "states.json"}
    assert review_store.save_review(key, 1, extra=mine, marked=mine)  # absent
    assert review_store.save_review(key, 1, extra={"note": 1}, marked=mine)  # the same
    assert review_store.save_review(key, 1, extra={K.ANNOTATOR_TRUTH_MARK: "truth.json"})
    assert not review_store.save_review(key, 1, extra=mine, marked=mine)  # another truth's
    assert review_store.item(key)[K.ANNOTATOR_TRUTH_MARK] == "truth.json"


def test_an_all_or_nothing_claim_writes_none_when_one_is_taken(tmp_path: Path, review_store: ReviewStore) -> None:
    """``only_if_free``: one screenshot already in another split stops the whole claim, in the same write."""
    paths = _shots(tmp_path, "a.png", "b.png")
    keys = [_detected(review_store, path, _box("icon", 10.0)) for path in paths]
    review_store.claim_splits({keys[0]: "test"})
    assert review_store.claim_splits({keys[0]: "train", keys[1]: "train"}, only_if_free=True) == {keys[0]: "test"}
    assert review_store.splits() == {keys[0]: "test"}  # b got none
    assert review_store.claim_splits({keys[0]: "test", keys[1]: "train"}, only_if_free=True) == {
        keys[0]: "test",
        keys[1]: "train",
    }


def test_a_save_can_need_its_split(tmp_path: Path, review_store: ReviewStore) -> None:
    """Model pre-labels go to training screenshots only, checked in the save's own write."""
    shots = _shots(tmp_path, "a.png", "b.png")
    train, test = (_detected(review_store, path, _box("icon", 10.0)) for path in shots)
    review_store.claim_splits({train: "train", test: "test"})
    assert not review_store.save_review(test, 1, annotations=[], split="train")
    assert review_store.save_review(train, 1, annotations=[], split="train")
    assert review_store.untouched(test) and not review_store.untouched(train) and not review_store.untouched("gone")


def test_a_toggle_needs_the_review_flag_it_was_worked_out_from(tmp_path: Path, review_store: ReviewStore) -> None:
    """Two tabs toggling one screenshot: the second toggle, worked out from the flag before the first, is refused in
    its own write instead of undoing the first (CodeRabbit)."""
    (shot,) = _shots(tmp_path, "a.png")
    key = _detected(review_store, shot, _box("icon", 10.0))
    assert review_store.save_review(key, 1, reviewed=True, expect_reviewed=False)  # the first tab's toggle
    assert not review_store.save_review(key, 1, reviewed=True, expect_reviewed=False)  # the second's, made from False
    assert review_store.save_review(key, 1, reviewed=False, expect_reviewed=True)
    assert review_store.save_review(key, 1, reviewed=True)  # "Reviewed, next": set whatever it was
    assert review_store.item(key)["reviewed"]
