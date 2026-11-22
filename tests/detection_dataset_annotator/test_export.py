"""The export's command line (tools/detection_dataset_annotator/export.py): the page's Export button without the page,
and the truth mark a truth-seeded training round reads (the export itself is tested in test_annotator.py)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.detection_dataset_annotator import ReviewStore, image_key
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
    for key in keys.values():
        result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}]}
        store.record_detection(key, result, force=False)
    store.save_review(keys["reviewed"], 1, reviewed=True)
    store.save_review(keys["seeded"], 1, extra={K.ANNOTATOR_TRUTH_MARK: "atlas_test_data/fr-atlas/truth.json"})
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
