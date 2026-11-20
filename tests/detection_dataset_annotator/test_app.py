"""The annotator's Streamlit page (tools/detection_dataset_annotator/app.py), run headless with Streamlit's AppTest:
the export's split report and label warnings, and the queue order. Every test points the page at a
review store in ``tmp_path`` (the live store is never opened). Skipped where Streamlit is not installed (the
annotator's optional extra)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from grand_project import paths  # noqa: E402
from tools.detection_dataset_annotator import ReviewStore, image_key  # noqa: E402
from tools.detection_dataset_annotator import constants as K  # noqa: E402

APP = paths.ROOT / "tools" / "detection_dataset_annotator" / "app.py"


@pytest.fixture
def page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A function making screenshots in a store in ``tmp_path`` and returning the page run on it."""
    shots = tmp_path / "shots"
    shots.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(K, "ANNOTATOR_DEFAULT_OUTPUT_DIR", str(out))  # read when the page builds its sidebar
    monkeypatch.setattr(K, "ANNOTATOR_DEFAULT_INPUT_DIRS", (shots,))

    def make(*specs: dict[str, Any]) -> tuple[AppTest, ReviewStore, list[str]]:
        keys = []
        store = ReviewStore.open(out / K.ANNOTATOR_STORE_FILE, [shots])
        for spec in specs:
            path = shots / spec["name"]
            cv2.imwrite(str(path), np.full((360, 640, 3), 90, np.uint8))
            store.add_images([path])
            key = image_key(path)
            result = {"detected": True, "width": 640, "height": 360, "annotations": spec.get("boxes", [])}
            store.record_detection(key, result, force=False)
            if spec.get("reviewed"):
                store.save_review(key, 1, reviewed=True)
            keys.append(key)
        return AppTest.from_file(str(APP), default_timeout=60).run(), store, keys

    yield make


def _box(label: str, x: float, source: str = "classical") -> dict[str, Any]:
    return {"label": label, "bbox": [x, 20.0, 39.0, 39.0], "area": 1521.0, "iscrowd": 0, "source": source}


def _button(at: AppTest, start: str):
    return next(b for b in at.sidebar.button if b.label.startswith(start))


def test_export_reports_splits_and_labels_the_dataset_does_not_know(page) -> None:
    """The split balance shows after an export; a label outside the dataset's (one the labels no longer have, until
    those screenshots are detected again) is named in a warning; a left-out icon type is not exported."""
    boxes = [_box("map_node_grass", 10), _box("citadel_stone", 100)]
    at, store, _keys = page(
        {"name": "a.png", "boxes": boxes, "reviewed": True},
        {"name": "b.png", "boxes": [*boxes, _box("icon_losttower", 300)], "reviewed": True},
        {"name": "c.png", "boxes": [_box("old_label", 100)], "reviewed": True},
    )
    with store:
        _button(at, "Export dataset").click().run()
        assert not at.exception
        success = at.sidebar.success[0].value
        assert "Exported 3 images and 5 boxes" in success and "Splits: train" in success
        warnings = [w.value for w in at.sidebar.warning]
        assert any("`old_label` (1)" in w and "Rerun all" in w for w in warnings)
        assert any("Skipped 1 invalid annotations or icons the dataset leaves out" in w for w in warnings)
        report = at.sidebar.code[0].value
        assert "citadel_stone" in report and "map_node_grass" in report
        assert set(store.splits().values()) <= set(K.ANNOTATOR_SPLITS) and len(store.splits()) == 3


def test_most_guesses_first_orders_the_queue(page) -> None:
    guess = K.ANNOTATOR_CITY_GUESS_SOURCE
    at, store, _keys = page(
        {"name": "a.png", "boxes": [_box("map_node", 10)]},
        {"name": "b.png", "boxes": [_box("citadel_iron", 10, guess), _box("map_node_vaal", 60, "city_area_guess")]},
        {"name": "c.png", "boxes": [_box("map_node_grass", 10, "biome_guess")]},
    )
    with store:
        assert [Path(o.split(" · ")[0].split(" ", 1)[1]).name for o in at.selectbox[0].options] == [
            "a.png",
            "b.png",
            "c.png",
        ]
        next(c for c in at.sidebar.checkbox if c.label == "Most guesses first").check().run()
        options = at.selectbox[0].options
        assert [Path(o.split(" · ")[0].split(" ", 1)[1]).name for o in options] == ["b.png", "c.png", "a.png"]
        assert options[0].endswith("2 guesses")
