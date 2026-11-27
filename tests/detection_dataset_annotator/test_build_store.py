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
    build_store,
    file_hash,
    image_key,
    relative_source,
    truth_seed,
)
from tools.detection_dataset_annotator import constants as K


@pytest.fixture(autouse=True)
def readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The screenshot files here are a few bytes (their bytes tell copies apart): recording the detected bytes and
    seeding read each as a blank 1920x1080 picture, the size it was detected in, with its own bytes' SHA-256."""

    def blank(path: Path) -> tuple[np.ndarray, str]:
        return np.zeros((1080, 1920, 3), np.uint8), file_hash(path)

    monkeypatch.setattr(truth_seed, "_raw_image", blank)
    monkeypatch.setattr(build_store, "read_with_digest", blank)


def _truth(tmp_path: Path, files: list[str]) -> Path:
    """A truth placing the screenshots 1:1 (identity M, no tilt) with one Vaal area map at (600, 500)."""
    data = {
        "maps": [[600.0, 500.0, "Vaal city"]],
        "biomes": [{"type": "Vaal city", "maps": [0], "city": {"x": 600.0, "y": 500.0, "assumed": True}}],
        "screenshots": [
            {"name": Path(f).stem, "file": f, "w": 1920, "h": 1080, "M": [[1, 0, 0], [0, 1, 0]], "horizon": None}
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
            result = {"width": 1920, "height": 1080, "annotations": [node]}
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
    truth = _truth(tmp_path, ["ok_a.png"])
    lines: list[str] = []
    done = build_store.build(tmp_path / "out", truths=[truth], workers=1, say=lines.append)

    # the old detections' bytes recorded (a, b and the reviewed copy); the new one's detection (the fake worker's)
    # says no size, so it counts as changed until it is rerun
    assert done == Counter(
        {"added": 1, "removed": 2, "kept reviewed": 1, "detected": 1, "hashed": 3, "changed": 1, "seeded": 1}
    )
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
    assert again == Counter({"kept reviewed": 1, "changed": 1})  # every other count is 0
    assert len(list((tmp_path / "out").glob(K.ANNOTATOR_BUILD_BACKUP.format(stamp="*")))) == 2


def test_a_dry_run_says_what_would_change_and_changes_nothing(tmp_path: Path, old_store: dict[str, Path]) -> None:
    truth = _truth(tmp_path, ["ok_a.png"])
    store_file = tmp_path / "out" / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_file) as store:
        before = {key: store.item(key) for key in store.paths()}

    done = build_store.build(tmp_path / "out", truths=[truth], dry_run=True, say=lambda line: None)
    # the seed sees the store as it is: the copy of ok_a.png, not removed in a dry run, has its name
    assert done == Counter({"added": 1, "removed": 2, "kept reviewed": 1, "hashed": 5, "seeded": 2})
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


def test_old_detections_get_their_bytes_recorded_where_the_file_is_still_their_picture(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detection made before its bytes were kept gets the file's SHA-256 where the file is still the size it was
    detected in; one replaced by another size, or unreadable, gets none (it counts as changed: rerun it). A dry run
    records nothing."""
    paths = {name: tmp_path / f"{name}.png" for name in ("same", "resized", "gone", "new")}
    for path in paths.values():
        path.write_bytes(path.stem.encode())
    review_store.add_images(paths.values())
    for name, path in paths.items():
        result = {"width": 1920, "height": 1080, "annotations": []}
        if name == "new":
            result[K.ANNOTATOR_DETECTED_SHA] = "detected with it"
        review_store.record_detection(image_key(path), result, force=False)
    shapes = {"same": (1080, 1920, 3), "resized": (1440, 2560, 3)}
    monkeypatch.setattr(
        build_store,
        "read_with_digest",
        lambda path: (np.zeros(shapes[path.stem], np.uint8), f"bytes of {path.stem}") if path.stem in shapes else None,
    )
    counts, planned = build_store.record_digests(review_store, dry_run=True)
    assert counts == Counter({"hashed": 1, "changed": 1, "unreadable": 1})
    assert planned == {image_key(paths["same"]): "bytes of same"}
    assert K.ANNOTATOR_DETECTED_SHA not in review_store.item(image_key(paths["same"]))
    assert build_store.record_digests(review_store)[0] == counts
    shas = {name: review_store.item(image_key(path)).get(K.ANNOTATOR_DETECTED_SHA) for name, path in paths.items()}
    assert shas == {"same": "bytes of same", "resized": None, "gone": None, "new": "detected with it"}
    assert build_store.record_digests(review_store)[0] == Counter({"changed": 1, "unreadable": 1})
