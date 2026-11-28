"""The store's steps as one run (tools/detection_dataset_annotator/build_store.py): back up, discover, remove what
discovery leaves out, detect, seed the biome truths; a second run changes nothing."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from tools.detection_dataset_annotator import (
    ReviewStore,
    StoreLayoutError,
    build_store,
    file_hash,
    image_key,
    relative_source,
    truth_seed,
)
from tools.detection_dataset_annotator import constants as K


@pytest.fixture(autouse=True)
def readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The screenshot files here are a few bytes (their bytes tell copies apart): seeding reads each as a blank
    1920x1080 picture, the size it was detected in, with its own bytes' SHA-256."""

    def blank(path: Path) -> tuple[np.ndarray, str]:
        return np.zeros((1080, 1920, 3), np.uint8), file_hash(path)

    monkeypatch.setattr(truth_seed, "_raw_image", blank)


def _truth(tmp_path: Path, files: list[Path]) -> Path:
    """A truth placing the screenshots 1:1 (identity M, no tilt), each by its name and bytes, with one Vaal area map
    at (600, 500)."""
    data = {
        "maps": [[600.0, 500.0, "Vaal city"]],
        "biomes": [{"type": "Vaal city", "maps": [0], "city": {"x": 600.0, "y": 500.0, "assumed": True}}],
        "screenshots": [
            {
                "name": f.stem,
                "file": f.name,
                "w": 1920,
                "h": 1080,
                "M": [[1, 0, 0], [0, 1, 0]],
                "horizon": None,
                "sha256": file_hash(f),
            }
            for f in files
        ],
    }
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def old_store(tmp_path: Path) -> dict[str, Path]:
    """A store built before discovery left copies and atlas pictures out, and a screenshot it has not seen yet.

    ``a-atlas`` sorts before ``z-copies``, so discovery keeps the atlas's own files: ``z-copies/ok_a.png`` is a copy
    to remove, ``z-copies/ok_b.png`` a copy that was reviewed (kept), ``a-atlas/atlas_files/ok_map.png`` an atlas
    picture (removed), ``a-atlas/ok_new.png`` new (discovered, then detected by the fake worker).
    """
    root = tmp_path / "shots"
    files = {
        "a": root / "a-atlas" / "ok_a.png",
        "b": root / "a-atlas" / "ok_b.png",
        "copy_a": root / "z-copies" / "ok_a.png",
        "copy_b": root / "z-copies" / "ok_b.png",
        "map": root / "a-atlas" / "atlas_files" / "ok_map.png",
        "new": root / "a-atlas" / "ok_new.png",
    }
    for name, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.removeprefix("copy_").encode())
    with ReviewStore.open(tmp_path / "out" / K.ANNOTATOR_STORE_FILE, [root]) as store:
        held = [files[name] for name in ("a", "b", "copy_a", "copy_b", "map")]
        store.add_images(held)
        node = {"label": "map_node_grass", "bbox": [580.0, 480.0, 40.0, 40.0], "source": "classical"}
        for path in held:
            result = {"width": 1920, "height": 1080, "annotations": [node], K.ANNOTATOR_DETECTED_SHA: file_hash(path)}
            store.record_detection(image_key(path), result, force=False)
        store.save_review(image_key(files["copy_b"]), 1, reviewed=True)
    return files


def _labels(store: ReviewStore, path: Path) -> list[tuple[str, str]]:
    item = store.item(image_key(path))
    assert item is not None
    return [(box["label"], box["source"]) for box in item["annotations"]]


def test_a_run_brings_an_old_store_up_to_date_and_a_second_changes_nothing(
    tmp_path: Path, old_store: dict[str, Path], fake_worker: str
) -> None:
    truth = _truth(tmp_path, [old_store["a"]])
    lines: list[str] = []
    done = build_store.build(tmp_path / "out", truths=[truth], workers=1, say=lines.append)

    assert done == Counter({"added": 1, "removed": 2, "kept reviewed": 1, "detected": 1, "seeded": 1})
    # the name as the run prints it: a file outside the project is named by its own (on Windows, backslashed) path
    assert any("kept, reviewed" in line and relative_source(old_store["copy_b"]) in line for line in lines)
    with ReviewStore.open(tmp_path / "out" / K.ANNOTATOR_STORE_FILE) as store:
        assert sorted(Path(path).relative_to(tmp_path).as_posix() for path in store.paths().values()) == [
            "shots/a-atlas/ok_a.png",
            "shots/a-atlas/ok_b.png",
            "shots/a-atlas/ok_new.png",
            "shots/z-copies/ok_b.png",
        ]
        assert _labels(store, old_store["a"]) == [("map_node_vaal", K.ANNOTATOR_TRUTH_SOURCE)]
        assert _labels(store, old_store["b"]) == [("map_node_grass", "classical")]  # the truth does not place it
    (backup,) = (tmp_path / "out").glob(K.ANNOTATOR_BUILD_BACKUP.format(stamp="*"))
    with ReviewStore.open(backup) as before:
        assert len(before.paths()) == 5

    again = build_store.build(tmp_path / "out", truths=[truth], workers=1, say=lines.append)
    assert again == Counter({"kept reviewed": 1})  # every other count is 0
    assert len(list((tmp_path / "out").glob(K.ANNOTATOR_BUILD_BACKUP.format(stamp="*")))) == 2


def test_a_dry_run_says_what_would_change_and_changes_nothing(tmp_path: Path, old_store: dict[str, Path]) -> None:
    truth = _truth(tmp_path, [old_store["a"]])
    store_file = tmp_path / "out" / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_file) as store:
        before = {key: store.item(key) for key in store.paths()}

    done = build_store.build(tmp_path / "out", truths=[truth], dry_run=True, say=lambda line: None)
    # the seed sees the store as it is: the copy of ok_a.png, not removed in a dry run, has its name
    assert done == Counter({"added": 1, "removed": 2, "kept reviewed": 1, "seeded": 2})
    with ReviewStore.open(store_file) as store:
        assert {key: store.item(key) for key in store.paths()} == before
    assert list((tmp_path / "out").glob(K.ANNOTATOR_BUILD_BACKUP.format(stamp="*"))) == []
    # the store file as it was too: opened read only (no journal mode set, no tables made)
    assert sorted(path.name for path in (tmp_path / "out").iterdir() if not path.name.endswith(("-wal", "-shm"))) == [
        K.ANNOTATOR_STORE_FILE
    ]
    # without a store, a dry run plans from an empty one: what discovery would queue (copies and atlas pictures not)
    lines: list[str] = []
    planned = build_store.build(tmp_path / "none", roots=[tmp_path / "shots"], dry_run=True, say=lines.append)
    assert planned == Counter({"added": 3})
    assert any("3 screenshots not detected yet" in line for line in lines)
    assert not (tmp_path / "none").exists()


def test_a_discovered_copy_is_never_queued(tmp_path: Path) -> None:
    """A copy discovery leaves out is not added only to be removed again: the store gets the original alone."""
    root = tmp_path / "shots"
    for folder in ("a", "b"):
        (root / folder).mkdir(parents=True)
        (root / folder / "shot.png").write_bytes(b"same bytes")
    lines: list[str] = []
    done = build_store.build(tmp_path / "out", roots=[root], truths=[], detect=False, say=lines.append)
    assert done["added"] == 1 and done["removed"] == 0
    with ReviewStore.open(tmp_path / "out" / K.ANNOTATOR_STORE_FILE) as store:
        assert [Path(path).relative_to(root).as_posix() for path in store.paths().values()] == ["a/shot.png"]


def test_a_missing_truth_file_is_an_error_but_a_missing_default_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(FileNotFoundError):
        build_store.build(tmp_path / "out", roots=[tmp_path], truths=[tmp_path / "no.json"], say=lambda line: None)
    monkeypatch.setattr(K, "ANNOTATOR_TRUTH_FILES", (tmp_path / "gone" / "truth.json",))
    lines: list[str] = []
    build_store.build(tmp_path / "out", roots=[tmp_path], say=lines.append)
    assert any("no truth file" in line for line in lines)


def test_the_next_command_s_folder_is_quoted_for_cmd_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """cmd.exe takes & | < > ^ ( ) literally only inside double quotes (CodeRabbit); POSIX keeps shlex's quoting."""
    monkeypatch.setattr(build_store.os, "name", "nt")
    assert build_store._quoted(r"C:\data\R&D (new)") == r'"C:\data\R&D (new)"'
    monkeypatch.setattr(build_store.os, "name", "posix")
    assert build_store._quoted("R&D (new)") == "'R&D (new)'"


def test_an_unusable_worker_count_stops_before_the_store_is_opened(tmp_path: Path) -> None:
    """--workers 0 with detection on is refused before any change; --no-detect never needs a count."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit):
        build_store.main(["--output-dir", str(out), "--root", str(tmp_path), "--workers", "0"])
    assert not out.exists()
    assert build_store.main(["--output-dir", str(out), "--root", str(tmp_path), "--workers", "0", "--no-detect"]) == 0


def test_a_backup_never_takes_a_name_another_backup_holds(tmp_path: Path, review_store: ReviewStore) -> None:
    """The target is claimed before SQLite opens it: a second backup of the same name raises, the first stays."""
    target = tmp_path / "backup.sqlite3"
    review_store.backup(target)
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        review_store.backup(target)
    assert target.read_bytes() == before


def _older_layout(store_file: Path) -> None:
    """The store as an older annotator built it: no review generation column, no pre-label snapshots."""
    import contextlib
    import sqlite3

    with contextlib.closing(sqlite3.connect(store_file, isolation_level=None)) as db:
        db.execute("ALTER TABLE images DROP COLUMN review_generation")
        db.execute("DROP TABLE prelabels")


def test_a_store_of_an_older_layout_is_brought_up_to_date_keeping_its_work(
    tmp_path: Path, old_store: dict[str, Path]
) -> None:
    """User: a layout change carries every box, review flag and split over (a backup of the old file kept); a dry run
    says so and changes nothing; once upgraded, a second run finds it up to date."""
    store_file = tmp_path / "out" / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_file) as store:
        store.claim_splits({image_key(old_store["b"]): "test"})
        before = {key: store.item(key) for key in store.paths()}
    _older_layout(store_file)
    with pytest.raises(StoreLayoutError, match="images.review_generation.*build_store"):
        ReviewStore.open(store_file)
    unchanged = store_file.read_bytes()

    lines: list[str] = []
    build_store.build(tmp_path / "out", truths=[], dry_run=True, say=lines.append)
    assert store_file.read_bytes() == unchanged and any("a run would back it up" in line for line in lines)

    lines.clear()
    build_store.build(tmp_path / "out", truths=[], detect=False, say=lines.append)
    assert any("every row copied into the new layout" in line for line in lines)
    with ReviewStore.open(store_file) as store:
        kept = [key for key in before if store.item(key) is not None]  # (the run's step 3 removes the copies)
        assert len(kept) == 3 and all(store.item(key) == before[key] for key in kept)  # boxes, reviews, splits, extra
        assert store.item(image_key(old_store["b"]))["split"] == "test"
        assert store.item(image_key(old_store["copy_b"]))["reviewed"] is True
        assert store.prelabels(image_key(old_store["a"])) == []  # (the table it lacked starts empty)
    (backup,) = (tmp_path / "out").glob(K.ANNOTATOR_BUILD_BACKUP.format(stamp="*"))
    with pytest.raises(StoreLayoutError):
        ReviewStore.open(backup)  # the old file as it was

    lines.clear()
    build_store.build(tmp_path / "out", truths=[], detect=False, say=lines.append)
    assert "  up to date" in lines


def test_a_backup_name_taken_meanwhile_is_never_written_over(tmp_path: Path, old_store: dict[str, Path]) -> None:
    """The layout upgrade's backup claims its file exclusively: a name a second run (or a person) took since the name
    was chosen makes it choose another, and what is there is kept as it is (CodeRabbit)."""
    store_file = tmp_path / "out" / K.ANNOTATOR_STORE_FILE
    ReviewStore.open(store_file).close()
    _older_layout(store_file)
    names = []
    real = build_store._backup_path

    def taken_first(output_dir):
        path = real(output_dir)
        if not names:
            path.write_bytes(b"someone else's backup")  # claimed between choosing the name and writing to it
        names.append(path)
        return path

    build_store._backup_path = taken_first
    try:
        build_store.build(tmp_path / "out", truths=[], detect=False, say=lambda line: None)
    finally:
        build_store._backup_path = real
    assert names[0].read_bytes() == b"someone else's backup"
    assert len(names) == 2 and names[1].is_file() and names[1] != names[0]


def test_a_store_that_is_not_there_is_not_made_by_the_layout_upgrade(tmp_path: Path) -> None:
    """The upgrade reads the old store read-write but never creates it: a missing path raises, and no empty database is
    left in its place (CodeRabbit)."""
    import sqlite3

    from tools.detection_dataset_annotator.store import upgrade_layout

    missing = tmp_path / "none.sqlite3"
    with pytest.raises(sqlite3.Error):
        upgrade_layout(missing)
    assert not missing.exists()
