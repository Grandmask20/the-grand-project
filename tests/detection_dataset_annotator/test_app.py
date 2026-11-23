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


def test_the_review_timer_adds_up_in_the_review_log() -> None:
    """Each editor message gives its active time (the store adds it up in the save's write); marking it reviewed
    notes when."""
    from tools.detection_dataset_annotator import app

    assert app._review_log({"active_ms": 0}, reviewed=None) == {"review_s": 0.0, "reviewed_at": None}
    assert app._review_log({"active_ms": 12_500}, reviewed=None)["review_s"] == 12.5
    assert app._review_log({"active_ms": 2_000}, reviewed=True)["reviewed_at"]


def test_pre_label_starts_the_model_pass_on_this_store(page, monkeypatch: pytest.MonkeyPatch) -> None:
    """The button runs ``model_prelabel`` as its own process (the GPU work would stall the page) on the page's output
    folder and the chosen model, logging into that folder, and is disabled while the pass runs."""
    import subprocess

    started = []

    class Running:
        def __init__(self, command, **kwargs) -> None:
            started.append((command, kwargs))
            kwargs["stdout"].write("12 screenshots eligible\n")

        def poll(self):
            return None  # still running

    monkeypatch.setattr(subprocess, "Popen", Running)
    at, store, _keys = page({"name": "a.png", "boxes": [_box("icon", 10)]})
    try:
        out = store.path.parent
        expander = next(e for e in at.sidebar.expander if e.label == "Model pre-labels")
        next(t for t in expander.text_input if t.label == "Model folder").set_value(str(out / "model"))
        _button(at, "Pre-label").click().run()
        ((command, kwargs),) = started
        assert command[1:4] == [
            "-u",
            "-m",
            "tools.detection_dataset_annotator.model_prelabel",
        ]  # unbuffered: a live log
        assert command[command.index("--output-dir") + 1] == str(out)
        assert command[command.index("--model") + 1] == str((out / "model").resolve())
        assert _button(at, "Pre-label").disabled
        assert "12 screenshots eligible" in (out / K.ANNOTATOR_PRELABEL_LOG).read_text(encoding="utf-8")
    finally:
        store.close()


def test_the_page_listens_on_this_computer_unless_told_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    """It shows any screenshot below the roots typed into it: loopback by default, an address given is kept."""
    from tools.detection_dataset_annotator.__main__ import streamlit_args

    monkeypatch.delenv("STREAMLIT_SERVER_ADDRESS", raising=False)
    app = Path("app.py")
    assert streamlit_args(app, ["--server.port", "8600"]) == [
        "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", "8600"
    ]  # fmt: skip
    assert streamlit_args(app, ["--server.address=0.0.0.0"]) == [
        "streamlit",
        "run",
        "app.py",
        "--server.address=0.0.0.0",
    ]
    assert streamlit_args(app, ["--server.address", "::"])[3:] == ["--server.address", "::"]
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    assert streamlit_args(app, []) == ["streamlit", "run", "app.py"]


def test_a_save_made_on_boxes_another_tab_changed_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two tabs edit one screenshot (one revision), each sending its whole box list: the second save, made on boxes
    the first already changed, is not stored (that tab reloads the saved boxes), and the first tab's next save is."""
    from tools.detection_dataset_annotator import app
    from tools.detection_dataset_annotator.boxes import editor_boxes

    path = tmp_path / "shot.png"
    cv2.imwrite(str(path), np.full((360, 640, 3), 90, np.uint8))
    store_path = tmp_path / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_path) as store:
        store.add_images([path])
        key = image_key(path)
        result = {"detected": True, "width": 640, "height": 360, "annotations": [_box("tower", 10.0)]}
        store.record_detection(key, result, force=False)
        item = store.item(key)
    revision, editor = int(item["edit_version"]), "editor"

    def tab() -> dict[str, Any]:
        """A browser tab's session, its editor just mounted on the saved boxes (as _render_editor does)."""
        return {app._base_key(editor): [dict(a) for a in item["annotations"]], app._known_key(editor): {}}

    def autosave(session: dict[str, Any], x: float, seq: int) -> float:
        boxes = editor_boxes(item["annotations"])
        boxes[0]["x"] = x
        session[editor] = {"edit": {"image_key": key, "revision": revision, "seq": seq, "boxes": boxes}}
        monkeypatch.setattr(app.st, "session_state", session)
        app._on_edit(store_path, key, revision, editor)
        with ReviewStore.open(store_path) as store:
            return store.item(key)["annotations"][0]["bbox"][0]

    first, second = tab(), tab()
    assert autosave(first, 50.0, 1) == 50.0
    assert autosave(second, 80.0, 1) == 50.0  # made on the boxes before the first tab's save: refused
    assert second[K.ANNOTATOR_SESSION_RELOADS] == 1 and K.ANNOTATOR_SESSION_NOTICE in second
    assert autosave(first, 60.0, 2) == 60.0  # the first tab goes on from what it saved
    assert first[app._saved_seq_key(editor)] == 2 and K.ANNOTATOR_SESSION_RELOADS not in first


def test_a_new_editor_drops_the_last_ones_session_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.detection_dataset_annotator import app

    session = {name: 1 for name in (app._saved_seq_key("old"), app._known_key("old"), app._base_key("old"))}
    session[app._saved_seq_key("new")] = 3
    monkeypatch.setattr(app.st, "session_state", session)
    app._forget("old")
    assert session == {app._saved_seq_key("new"): 3}


def test_the_undo_memory_keeps_the_detectors_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """A box saved as moved (manual) is still known as the detector had it, so Ctrl+Z can give back its provenance."""
    from tools.detection_dataset_annotator import app

    session: dict[str, Any] = {}
    monkeypatch.setattr(app.st, "session_state", session)
    detected = {"id": "b0", "label": "icon", "bbox": [1.0, 2.0, 34.0, 34.0], "source": "classical", "score": 0.8}
    app._remember("editor", [detected])
    app._remember("editor", [{**detected, "bbox": [9.0, 2.0, 34.0, 34.0], "source": "manual", "score": None}])
    assert session[app._known_key("editor")]["b0"] == detected
