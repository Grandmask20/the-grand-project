"""The split ledger (tools/detection_dataset_annotator/split_ledger.py): every screenshot's split by its bytes, so a
rebuilt store, another machine or a copy of a file gives it the split it had, and a disagreement stops before
anything is written."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.detection_dataset_annotator import ReviewStore, image_key, split_ledger
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.blocks import Block
from tools.detection_dataset_annotator.split_ledger import (
    Entry,
    SplitConflict,
    check_manifest,
    check_splits,
    held_out_overlap,
    join_blocks,
    read_ledger,
    read_ledger_rows,
    settle_splits,
    write_ledger,
)
from tools.detection_dataset_annotator.state import file_hash, relative_source

SHOTS = 12


def _shots(folder: Path, count: int = SHOTS) -> list[Path]:
    """Screenshot files with bytes of their own (no atlas places them: each is a block of its own)."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f"shot{i:02d}.png" for i in range(count)]
    for i, path in enumerate(paths):
        path.write_bytes(f"screenshot {i}".encode())
    return paths


def _detect(store: ReviewStore, paths: list[Path]) -> None:
    """Queue the screenshots and give each a detection with one tower box."""
    store.add_images(paths)
    for path in paths:
        result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}]}
        store.record_detection(image_key(path), result, force=False)


def _by_file(store: ReviewStore) -> dict[str, str]:
    """The store's splits by file name."""
    paths = store.paths()
    return {Path(paths[key]).name: split for key, split in store.splits().items()}


def test_the_ledger_is_written_sorted_and_read_back(split_ledger_file: Path) -> None:
    entries = [Entry("b" * 64, "test", "", "z.png"), Entry("a" * 64, "train", "atlas#3", "a.png")]
    write_ledger(entries)
    lines = split_ledger_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["sha256,split,block,file", f"{'a' * 64},train,atlas#3,a.png", f"{'b' * 64},test,,z.png"]
    assert read_ledger() == {entry.sha256: entry for entry in entries}
    assert read_ledger(split_ledger_file.parent / "none.csv") == {}


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (["sha,split", "x,train"], "columns"),
        (["sha256,split,block,file", "x,holdout,,a.png"], "unknown split"),
        (["sha256,split,block,file", "x,train,,a.png", "x,test,,b.png"], "different splits"),
    ],
)
def test_a_broken_ledger_is_refused(split_ledger_file: Path, rows: list[str], message: str) -> None:
    split_ledger_file.parent.mkdir(parents=True)
    split_ledger_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_ledger()


def test_a_rebuilt_store_gets_every_split_from_the_ledger(tmp_path: Path, review_store: ReviewStore) -> None:
    """The same files in another folder (another machine: other paths, other image keys) and a new store: every
    screenshot takes the split its bytes have in the ledger, nothing is drawn and the ledger gains nothing."""
    paths = _shots(tmp_path / "here")
    _detect(review_store, paths)
    first = settle_splits(review_store)
    assert first.origins == {"drawn": SHOTS} and first.added == SHOTS
    assert set(first.split_of.values()) == set(K.ANNOTATOR_SPLITS)  # 12 single blocks: every split gets some
    before = read_ledger()

    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(tmp_path / "here", elsewhere)
    with ReviewStore.open(tmp_path / "rebuilt" / K.ANNOTATOR_STORE_FILE) as rebuilt:
        _detect(rebuilt, sorted(elsewhere.iterdir()))
        again = settle_splits(rebuilt)
        assert again.origins == {"ledger": SHOTS} and again.added == 0
        assert _by_file(rebuilt) == _by_file(review_store)
    assert read_ledger() == before


def test_copies_share_one_split_and_keep_a_row_each(tmp_path: Path, review_store: ReviewStore) -> None:
    paths = _shots(tmp_path / "shots")
    copy = tmp_path / "copies" / paths[0].name
    copy.parent.mkdir()
    shutil.copy(paths[0], copy)
    _detect(review_store, [*paths, copy])
    settled = settle_splits(review_store)
    split = settled.split_of[image_key(paths[0])]
    assert settled.split_of[image_key(copy)] == split
    assert len(read_ledger()) == SHOTS  # one digest each
    rows = [entry for entry in read_ledger_rows() if entry.sha256 == file_hash(copy)]
    assert sorted(entry.file for entry in rows) == sorted([relative_source(paths[0]), relative_source(copy)])
    assert {entry.split for entry in rows} == {split}
    assert settle_splits(review_store).added == 0  # a second settle adds no row


def test_a_copy_whose_bytes_changed_keeps_its_originals_held_out_split(
    tmp_path: Path, review_store: ReviewStore
) -> None:
    """A copy is recorded under its own name too: saved again with other bytes and found by a rebuilt store, it keeps
    its original's split by name instead of being drawn again (perhaps into train, beside its held-out original)."""
    paths = _shots(tmp_path / "shots")
    _detect(review_store, paths)
    settled = settle_splits(review_store)
    original = next(path for path in paths if settled.split_of[image_key(path)] != "train")
    held = settled.split_of[image_key(original)]
    copy = tmp_path / "copies" / "copy.png"
    copy.parent.mkdir()
    shutil.copy(original, copy)
    _detect(review_store, [copy])
    assert settle_splits(review_store).split_of[image_key(copy)] == held
    copy.write_bytes(b"the copy, saved again")
    with ReviewStore.open(tmp_path / "rebuilt" / K.ANNOTATOR_STORE_FILE) as rebuilt:
        _detect(rebuilt, [*paths, copy])
        again = settle_splits(rebuilt)
    assert again.split_of[image_key(copy)] == held
    assert again.origins["ledger (by file name: its bytes changed)"] == 1


def test_a_split_claimed_meanwhile_that_differs_publishes_nothing(
    tmp_path: Path, review_store: ReviewStore, split_ledger_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store keeps a split claimed before this one (outside the ledger's lock): another split than the one given
    here is a conflict, and the ledger is not written."""
    paths = _shots(tmp_path / "shots", 3)
    _detect(review_store, paths)
    other = {"train": "test", "validation": "train", "test": "train"}
    asked = []

    def claim(splits, **options):
        asked.append(options)
        return {key: other[split] for key, split in splits.items()}

    monkeypatch.setattr(review_store, "claim_splits", claim)
    with pytest.raises(SplitConflict, match="given .*, store"):
        settle_splits(review_store)
    assert not split_ledger_file.exists()
    assert asked == [{"only_if_free": True}]  # all or nothing: the store writes none of them either


def test_a_manifest_row_under_a_pinned_root_must_be_test(
    tmp_path: Path, split_ledger_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hand truth and reference atlases are always test: a manifest (or store) giving one of them another split
    is named, whatever the ledger says."""
    (shot,) = _shots(tmp_path / "truth", 1)
    write_ledger([Entry(file_hash(shot), "train", "", relative_source(shot))])
    monkeypatch.setattr(split_ledger, "pinned_split", lambda path: "test" if "truth" in Path(path).parts else None)
    problems = check_manifest({"images": [{"path": str(shot), "split": "train"}]})
    assert problems == [f"{relative_source(shot)}: manifest train, pinned to test"]


def test_a_file_whose_bytes_changed_keeps_its_split_by_name(tmp_path: Path, review_store: ReviewStore) -> None:
    paths = _shots(tmp_path / "shots")
    _detect(review_store, paths)
    split = settle_splits(review_store).split_of[image_key(paths[3])]
    paths[3].write_bytes(b"saved again")
    with ReviewStore.open(tmp_path / "rebuilt" / K.ANNOTATOR_STORE_FILE) as rebuilt:
        _detect(rebuilt, paths)
        settled = settle_splits(rebuilt)
    assert settled.split_of[image_key(paths[3])] == split
    assert settled.origins["ledger (by file name: its bytes changed)"] == 1 and settled.added == 1
    assert read_ledger()[file_hash(paths[3])] == Entry(file_hash(paths[3]), split, "", relative_source(paths[3]))


def test_a_file_its_bytes_and_its_name_give_two_splits_stops_everything(
    tmp_path: Path, review_store: ReviewStore
) -> None:
    """A file now holding another screenshot's bytes: the ledger knows its bytes in one split and its name in another.
    Which one it is, a person decides: nothing is written, and the check says so too."""
    paths = _shots(tmp_path / "shots")
    _detect(review_store, paths)
    split_of = settle_splits(review_store).split_of
    first = paths[0]
    other = next(path for path in paths if split_of[image_key(path)] != split_of[image_key(first)])
    other.write_bytes(first.read_bytes())
    ledger_before = read_ledger()
    with ReviewStore.open(tmp_path / "rebuilt" / K.ANNOTATOR_STORE_FILE) as rebuilt:
        _detect(rebuilt, paths)
        with pytest.raises(SplitConflict) as raised:
            settle_splits(rebuilt)
    by_bytes, by_name = split_of[image_key(first)], split_of[image_key(other)]
    problem = f"{relative_source(other)}: ledger {by_bytes} by its bytes, {by_name} by its file name"
    assert raised.value.problems == [problem]
    assert read_ledger() == ledger_before
    manifest = {"images": [{"path": str(other), "split": by_bytes}]}
    assert check_manifest(manifest) == [problem]


def test_copies_join_their_blocks() -> None:
    """A copy in two places joins both blocks, so the neighbours of each go with it (moving only the copy into the
    other block left its own neighbours to be drawn apart)."""
    blocks = {
        "a": Block("x", 0),
        "b": Block("x", 0),
        "c": Block("y", 1),
        "d": Block("y", 1),
        "e": Block("z", 0),
        "f": Block("w", 2),
    }
    joined = join_blocks(blocks, [["c", "a"], ["e"], ["f", "d"]])
    assert joined == {**dict.fromkeys("abcdf", Block("w", 2)), "e": Block("z", 0)}


def test_a_store_split_the_ledger_disagrees_with_stops_everything(tmp_path: Path, review_store: ReviewStore) -> None:
    """A screenshot the ledger has in one split and a rebuilt store in another: nothing is claimed or written, and
    the error names the file."""
    paths = _shots(tmp_path / "shots")
    _detect(review_store, paths)
    split = settle_splits(review_store).split_of[image_key(paths[0])]
    other = next(name for name in K.ANNOTATOR_SPLITS if name != split)
    ledger_before = read_ledger()
    with ReviewStore.open(tmp_path / "rebuilt" / K.ANNOTATOR_STORE_FILE) as rebuilt:
        _detect(rebuilt, paths)
        rebuilt.claim_splits({image_key(paths[0]): other})
        with pytest.raises(SplitConflict, match=paths[0].name) as raised:
            settle_splits(rebuilt)
        assert raised.value.problems == [f"{relative_source(paths[0])}: ledger {split}, store {other}"]
        assert rebuilt.splits() == {image_key(paths[0]): other}
    assert read_ledger() == ledger_before


def test_a_pinned_screenshot_the_ledger_trains_on_stops_everything(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root pinned to test after a model trained on its screenshots would leak them: a person decides."""
    paths = _shots(tmp_path / "shots")
    write_ledger([Entry(file_hash(paths[0]), "train", "", relative_source(paths[0]))])
    monkeypatch.setattr(split_ledger, "pinned_split", lambda path: "test" if Path(path) == paths[0] else None)
    _detect(review_store, paths)
    with pytest.raises(SplitConflict, match="ledger train, pinned test"):
        settle_splits(review_store)
    assert review_store.splits() == {}


def test_check_names_what_disagrees_with_the_ledger(tmp_path: Path, review_store: ReviewStore) -> None:
    paths = _shots(tmp_path / "shots")
    _detect(review_store, paths[:-1])
    split_of = settle_splits(review_store).split_of
    assert check_splits(review_store) == []

    split = split_of[image_key(paths[0])]
    other = next(name for name in K.ANNOTATOR_SPLITS if name != split)
    manifest = {
        "images": [
            {"path": str(paths[0]), "split": other},  # moved: a leak
            {"path": str(paths[1]), "split": split_of[image_key(paths[1])]},  # as the ledger has it
            {"path": str(paths[-1]), "split": "train"},  # never settled
        ]
    }
    assert check_splits(review_store, manifest=manifest) == [
        f"{relative_source(paths[0])}: manifest {other}, ledger {split}",
        f"{relative_source(paths[-1])} (manifest train): not in the ledger",
    ]


def test_a_manifest_is_checked_without_a_store(tmp_path: Path, split_ledger_file: Path) -> None:
    """The trainer's check before it builds a dataset: by bytes (wherever the file lies), naming what moved split or
    is missing; a manifest that agrees passes."""
    paths = _shots(tmp_path / "shots", 3)
    write_ledger([Entry(file_hash(p), "train", "", relative_source(p)) for p in paths[:2]], split_ledger_file)
    copy = tmp_path / "elsewhere" / "copy.png"
    copy.parent.mkdir()
    shutil.copyfile(paths[0], copy)
    rows = [{"path": str(copy), "split": "train"}, {"path": str(paths[1]), "split": "validation"},
            {"path": str(paths[2]), "split": "test"}]  # fmt: skip
    problems = check_manifest({"images": rows})
    assert problems == [
        f"{relative_source(paths[1])}: manifest validation, ledger train",
        f"{relative_source(paths[2])} (manifest test): not in the ledger",
    ]
    assert check_manifest({"images": rows[:1]}) == []


def test_the_held_out_overlap_counts_map_nodes_training_screenshots_show(tmp_path: Path) -> None:
    """a (train) shows map nodes 0 and 2, b (validation) 0 and 1, c (test) 2: half of b's map nodes and all of c's
    are on a training screenshot."""
    nodes = [
        {"x": 0, "y": 0, "n": 2, "frames": ["a", "b"], "tower": False, "hidden": False},
        {"x": 1, "y": 0, "n": 1, "frames": ["b"], "tower": False, "hidden": False},
        {"x": 2, "y": 0, "n": 2, "frames": ["a", "c"], "tower": False, "hidden": False},
    ]
    atlas_file = tmp_path / K.ANNOTATOR_ATLAS_FILE
    atlas_file.write_text(json.dumps({"frames": [], "nodes": nodes, "edges": [], "landmarks": []}), encoding="utf-8")
    overlap = held_out_overlap(atlas_file, {"a": "train", "b": "validation", "c": "test"})
    assert overlap == {"validation": (1, 0.5), "test": (1, 1.0)}


def test_freeze_and_check_from_the_command_line(
    tmp_path: Path, review_store: ReviewStore, capsys: pytest.CaptureFixture[str]
) -> None:
    _detect(review_store, _shots(tmp_path / "shots"))
    output_dir = str(review_store.path.parent)
    assert split_ledger.main(["--output-dir", output_dir]) == 0
    assert f"{SHOTS} rows added" in capsys.readouterr().out
    assert split_ledger.main(["freeze", "--output-dir", output_dir]) == 0
    assert "0 rows added" in capsys.readouterr().out
    assert split_ledger.main(["check", "--output-dir", output_dir]) == 0
    assert "every split is the ledger's" in capsys.readouterr().out


def test_a_relative_manifest_path_lies_in_the_manifests_folder(tmp_path: Path, split_ledger_file: Path) -> None:
    """As the trainer reads the manifest (rf_detr.load_annotator_manifest): a relative path is beside it, wherever
    the check runs from."""
    (shot,) = _shots(tmp_path / "export" / "shots", 1)
    write_ledger([Entry(file_hash(shot), "train", "", relative_source(shot))], split_ledger_file)
    rows = [{"path": "shots/" + shot.name, "split": "train"}]
    assert check_manifest({"images": rows}, base=tmp_path / "export") == []


def test_the_ledger_is_held_for_one_read_check_and_write(split_ledger_file: Path) -> None:
    """A second export waits while one holds the ledger (its rows would otherwise be written over)."""
    import threading

    order: list[str] = []
    holding, done = threading.Event(), threading.Event()

    def other() -> None:
        holding.wait()
        with split_ledger._ledger_lock(split_ledger_file):
            order.append("other")
        done.set()

    thread = threading.Thread(target=other)
    thread.start()
    with split_ledger._ledger_lock(split_ledger_file):
        holding.set()
        assert not done.wait(0.3)  # still waiting for this one
        order.append("first")
    assert done.wait(10)
    thread.join()
    assert order == ["first", "other"]
