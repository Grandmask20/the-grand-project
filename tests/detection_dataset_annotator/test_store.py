"""The annotator's review store (tools/detection_dataset_annotator/store.py): screenshots and boxes in SQLite, saved
one screenshot at a time and safe between sessions."""

from __future__ import annotations

import errno
import os
import sys
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

    review_store.record_detection(key, _result(_box("city_vaal", 5)), force=True)
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file names can hold bytes that are not UTF-8")
def test_a_file_name_that_is_not_utf8_is_kept_as_it_is(tmp_path: Path, review_store: ReviewStore) -> None:
    """SQLite text cannot hold such a name: the path is stored as its bytes and comes back unchanged (the detector
    opens it); the name shown has the odd byte as an escape."""
    odd = tmp_path / os.fsdecode(b"shot\xff.png")
    try:
        odd.write_bytes(b"x")
    except OSError as error:
        if error.errno != errno.EILSEQ:
            raise
        # macOS (APFS, HFS+) refuses a file name that is not UTF-8, so no screenshot there has one (CI)
        pytest.skip("this file system takes only UTF-8 file names")
    assert review_store.add_images([odd]) == (1, 0)
    key = image_key(odd)
    item = review_store.item(key)
    assert item["path"] == str(odd) and Path(item["path"]).is_file()
    assert review_store.detection_jobs() == [(key, str(odd))]
    assert review_store.queue()[0].source.endswith("shot\\udcff.png")
    assert dict(review_store.items())[key]["path"] == str(odd)


def test_detection_jobs_follow_selection_and_force(tmp_path: Path, review_store: ReviewStore) -> None:
    a, b, c = _shots(tmp_path, "a.png", "b.png", "c.png")
    review_store.add_images([a, b, c])
    review_store.record_detection(image_key(b), _result(), force=False)
    keys = [image_key(path) for path in (a, b, c)]
    assert review_store.detection_jobs() == [(keys[0], str(a)), (keys[2], str(c))]
    assert review_store.detection_jobs(keys[:2]) == [(keys[0], str(a))]
    assert review_store.detection_jobs(keys[1:], force=True) == [(keys[1], str(b)), (keys[2], str(c))]


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
    gets the stored split back and uses it. A pinned screenshot (a truth screenshot: test) always takes its split."""
    shots = _shots(tmp_path, "a.png", "b.png", "c.png")
    review_store.add_images(shots)
    a, b, c = (image_key(shot) for shot in shots)
    review_store.claim_splits({a: "train", c: "train"})  # given by an export that finished first
    claimed = review_store.claim_splits({a: "validation", b: "validation", c: "test"}, overwrite={c})
    assert claimed == {a: "train", b: "validation", c: "test"}
    assert review_store.splits() == claimed
