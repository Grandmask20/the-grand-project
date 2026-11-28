"""The export's command line (tools/detection_dataset_annotator/export.py): the page's Export button without the page,
and the truth mark a truth-seeded training round reads (the export itself is tested in test_annotator.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.detection_dataset_annotator import ReviewStore, file_hash, image_key
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.export import main


def _store(tmp_path: Path, store: ReviewStore) -> dict[str, str]:
    """A reviewed screenshot, a truth-seeded unreviewed one and a plain unreviewed one, each with a tower box."""
    folder = tmp_path / "shots"
    folder.mkdir()
    paths = {name: folder / f"{name}.png" for name in ("reviewed", "seeded", "plain")}
    for index, path in enumerate(paths.values()):
        path.write_bytes(bytes([index]))
    store.add_images(paths.values())
    keys = {name: image_key(path) for name, path in paths.items()}
    for key, path in zip(keys.values(), paths.values(), strict=True):
        result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}],
                  K.ANNOTATOR_DETECTED_SHA: file_hash(path)}  # fmt: skip
        store.record_detection(key, result, force=False)
    store.save_review(keys["reviewed"], 1, reviewed=True)
    store.save_review(
        keys["seeded"],
        1,
        extra={K.ANNOTATOR_TRUTH_MARK: "atlas_test_data/fr-atlas/truth.json"},
    )
    return keys


def test_the_command_line_exports_as_the_page_does(tmp_path: Path, review_store: ReviewStore, capsys) -> None:
    _store(tmp_path, review_store)
    out = tmp_path / "out"
    assert main(["--output-dir", str(out)]) == 0
    manifest = json.loads((out / K.ANNOTATOR_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert [Path(image["path"]).stem for image in manifest["images"]] == ["reviewed"]
    assert "1 screenshots, 1 boxes" in capsys.readouterr().out


def test_an_export_carries_the_truth_that_seeded_a_screenshot(tmp_path: Path, review_store: ReviewStore) -> None:
    _store(tmp_path, review_store)
    out = tmp_path / "out"
    assert main(["--output-dir", str(out), "--unreviewed"]) == 0
    manifest = json.loads((out / K.ANNOTATOR_MANIFEST_FILE).read_text(encoding="utf-8"))
    marks = {Path(image["path"]).stem: image.get(K.ANNOTATOR_TRUTH_MARK) for image in manifest["images"]}
    assert marks == {"reviewed": None, "seeded": "atlas_test_data/fr-atlas/truth.json", "plain": None}
    assert {image["split"] for image in manifest["images"]} <= set(K.ANNOTATOR_SPLITS)


def test_a_screenshot_changed_since_its_detection_is_left_out(
    tmp_path: Path, review_store: ReviewStore, capsys
) -> None:
    """A file whose bytes are not the ones its boxes were detected on (replaced since, here by one of its size): its
    boxes would frame another picture, so it is left out and named (CodeRabbit)."""
    _store(tmp_path, review_store)
    (tmp_path / "shots" / "plain.png").write_bytes(b"\x09")  # another picture under its name
    out = tmp_path / "out"
    assert main(["--output-dir", str(out), "--unreviewed"]) == 0
    manifest = json.loads((out / K.ANNOTATOR_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert sorted(Path(image["path"]).stem for image in manifest["images"]) == ["reviewed", "seeded"]
    assert "changed since their detection" in capsys.readouterr().out


def test_a_relative_screenshot_path_is_exported_where_the_file_is(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A screenshot added by a relative path is stored resolved (as its key resolves it), so the split ledger hashes and
    the export writes one file: the trainer reads a relative manifest path from the manifest's own folder, where the
    screenshot is not."""
    from tools.detection_dataset_annotator import export

    monkeypatch.chdir(tmp_path)
    shot = tmp_path / "shots" / "a.png"
    shot.parent.mkdir()
    shot.write_bytes(b"a")
    relative = Path("shots") / "a.png"
    review_store.add_images([relative])
    result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}],
              K.ANNOTATOR_DETECTED_SHA: file_hash(shot)}  # fmt: skip
    review_store.record_detection(image_key(relative), result, force=False)
    out = tmp_path / "out"
    export.export_dataset(review_store, out, reviewed_only=False)
    manifest = json.loads((out / K.ANNOTATOR_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["images"][0]["path"] == str(shot.resolve())


def test_a_class_only_invalid_boxes_have_is_no_class_of_the_export(tmp_path: Path, review_store: ReviewStore) -> None:
    """The classes are those of the boxes exported: a reviewer's own label whose only box is invalid (no size) is no
    class of the manifest (CodeRabbit)."""
    keys = _store(tmp_path, review_store)
    item = review_store.item(keys["reviewed"])
    boxes = [*item["annotations"], {"label": "my_label", "bbox": [5, 5, 0, 20], "source": "manual"}]
    assert review_store.save_review(keys["reviewed"], item["edit_version"], annotations=boxes)
    out = tmp_path / "out"
    assert main(["--output-dir", str(out)]) == 0
    manifest = json.loads((out / K.ANNOTATOR_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert "my_label" not in manifest["labels"].values()
    assert [a["label"] for image in manifest["images"] for a in image["annotations"]] == ["tower"]
