"""The annotator's review store (tools/detection_dataset_annotator/store.py): screenshots and boxes in SQLite, saved
one screenshot at a time and safe between sessions."""

from __future__ import annotations

import sqlite3
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


def test_a_store_from_a_newer_annotator_is_refused(tmp_path: Path) -> None:
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    ReviewStore.open(path).close()
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {K.ANNOTATOR_STORE_SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(ValueError, match="newer annotator"):
        ReviewStore.open(path)


_V1_SCHEMA = (
    "CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE images (key TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, path TEXT NOT NULL,
        source TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0, detected INTEGER NOT NULL DEFAULT 0, detector TEXT,
        width INTEGER, height INTEGER, detector_width INTEGER, detector_height INTEGER, error TEXT,
        edit_version INTEGER NOT NULL DEFAULT 0, next_annotation_id INTEGER NOT NULL DEFAULT 0,
        extra TEXT NOT NULL DEFAULT '{}')""",
    """CREATE TABLE annotations (image_key TEXT NOT NULL REFERENCES images(key) ON DELETE CASCADE, ord INTEGER NOT NULL,
        id TEXT NOT NULL, label TEXT NOT NULL, x REAL, y REAL, w REAL, h REAL, area REAL,
        iscrowd INTEGER NOT NULL DEFAULT 0, source TEXT, score REAL, PRIMARY KEY (image_key, ord),
        UNIQUE (image_key, id)) WITHOUT ROWID""",
    "CREATE INDEX annotations_label ON annotations(label)",
)


def test_a_version_1_store_is_upgraded_after_a_copy_is_saved(tmp_path: Path) -> None:
    """The first schema's store opens upgraded: its boxes stay as they are, its guesses are counted (for the queue's
    order), it has no splits yet, and the store as it was is kept next to it."""
    path = tmp_path / K.ANNOTATOR_STORE_FILE
    with sqlite3.connect(path) as db:
        for statement in _V1_SCHEMA:
            db.execute(statement)
        db.execute("INSERT INTO images (key, position, path, source, detected) VALUES ('k', 0, 'a.png', 'a.png', 1)")
        db.execute(
            "INSERT INTO annotations VALUES ('k', 0, 'b0', 'citadel_stone', 1, 2, 80, 80, 6400, 0, 'city_guess', NULL)"
        )
        db.execute("PRAGMA user_version = 1")
    db.close()
    with ReviewStore.open(path) as store:
        (entry,) = store.queue()
        assert entry.guesses == 1 and store.splits() == {}
        assert store.item("k")["annotations"][0]["label"] == "citadel_stone"
    backup = path.with_name(f"{path.name}.v1-backup")
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT label FROM annotations").fetchall() == [("citadel_stone",)]
    db.close()
    with ReviewStore.open(path) as store:  # opening it again changes nothing
        assert store.queue()[0].guesses == 1


def test_splits_are_kept(tmp_path: Path, review_store: ReviewStore) -> None:
    shots = _shots(tmp_path, "a.png", "b.png")
    review_store.add_images(shots)
    review_store.set_splits({image_key(shots[0]): "test"})
    assert review_store.splits() == {image_key(shots[0]): "test"}
    assert review_store.item(image_key(shots[0]))["split"] == "test"
    assert review_store.item(image_key(shots[1]))["split"] is None
