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
from tools.detection_dataset_annotator import ReviewStore, file_hash, image_key  # noqa: E402
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
            result = {"detected": True, "width": 640, "height": 360, "annotations": spec.get("boxes", []),
                      K.ANNOTATOR_DETECTED_SHA: file_hash(path)}  # fmt: skip
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


def test_a_screenshot_changed_since_its_detection_shows_no_editor(page, tmp_path: Path) -> None:
    """Its boxes would frame another picture: the page says so and asks for a rerun instead (CodeRabbit)."""
    at, store, _keys = page({"name": "a.png", "boxes": [_box("tower", 10)]})
    with store:
        cv2.imwrite(str(tmp_path / "shots" / "a.png"), np.full((360, 640, 3), 30, np.uint8))  # replaced, same size
        at.run()
        assert not at.exception
        assert any("changed since its detection" in e.value for e in at.error)


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
        (log,) = out.glob(K.ANNOTATOR_PRELABEL_LOG_GLOB)  # its own log: another tab's pass writes another
        assert "12 screenshots eligible" in log.read_text(encoding="utf-8")
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
    # after "--" the arguments are the page's own: an address there is not Streamlit's
    assert streamlit_args(app, ["--", "--server.address", "x"])[3:] == ["--server.address", "127.0.0.1", "--"] + [
        "--server.address",
        "x",
    ]
    # a blank address is none: it would make Streamlit listen on every interface, so it goes and the default stands
    loopback = ["streamlit", "run", "app.py", "--server.address", "127.0.0.1"]
    assert streamlit_args(app, ["--server.address", ""]) == loopback
    assert streamlit_args(app, ["--server.address="]) == loopback
    assert streamlit_args(app, ["--server.address", "  ", "--server.port", "8600"]) == [
        *loopback,
        "--server.port",
        "8600",
    ]
    assert streamlit_args(app, ["--server.address"]) == loopback
    assert streamlit_args(app, ["--server.address", "", "--server.address=::1"])[3:] == ["--server.address=::1"]
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "   ")
    assert streamlit_args(app, []) == loopback
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

    # a save the store refuses in its own write (another tab saved between the check and the write) reloads the
    # editor the same way, and its edit is not acknowledged
    with ReviewStore.open(store_path) as store:
        item = store.item(key)  # the tab mounts on the saved boxes, so it passes the check before the write
    monkeypatch.setattr(ReviewStore, "save_review", lambda self, *args, **kwargs: False)
    third = tab()
    assert autosave(third, 70.0, 1) == 60.0
    assert third[K.ANNOTATOR_SESSION_RELOADS] == 1 and K.ANNOTATOR_SESSION_NOTICE in third
    assert app._saved_seq_key(editor) not in third


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


def test_hiding_reviewed_screenshots_keeps_the_one_on_screen(page) -> None:
    """A reviewed screenshot in the editor stays while "Hide reviewed screenshots" is ticked: the editor is not retired
    by the filter (its edits since the last autosave were lost: CodeRabbit); the others reviewed are hidden."""
    at, store, keys = page({"name": "a.png", "reviewed": True}, {"name": "b.png", "reviewed": True}, {"name": "c.png"})
    with store:
        next(c for c in at.sidebar.checkbox if c.label == "Hide reviewed screenshots").uncheck().run()
        at.session_state[K.ANNOTATOR_SESSION_SELECTED] = keys[0]  # a.png on screen
        at.run()
        next(c for c in at.sidebar.checkbox if c.label == "Hide reviewed screenshots").check().run()
        assert not at.exception
        assert at.session_state[K.ANNOTATOR_SESSION_SELECTED] == keys[0]
        names = [Path(o.split(" · ")[0].split(" ", 1)[1]).name for o in at.selectbox[0].options]
        assert names == ["a.png", "c.png"]  # a.png (on screen) and c.png


def test_a_screenshot_picked_in_the_list_waits_for_the_editor_s_save(page) -> None:
    """With an editor on screen, picking another screenshot asks the editor to save its latest boxes and go there
    (retired at once, its edits since the last autosave were lost: CodeRabbit); the page stays until it answers."""
    at, store, keys = page({"name": "a.png", "boxes": [_box("tower", 10)]}, {"name": "b.png"})
    with store:
        at.selectbox[0].select(keys[1]).run()
        assert not at.exception
        assert at.session_state[K.ANNOTATOR_SESSION_SELECTED] == keys[0]
        assert at.session_state[K.ANNOTATOR_SESSION_GOTO] == keys[1]


def test_the_goto_action_saves_the_boxes_and_moves_whatever_the_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.detection_dataset_annotator import app
    from tools.detection_dataset_annotator.boxes import editor_boxes

    paths = [tmp_path / name for name in ("a.png", "b.png")]
    store_path = tmp_path / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_path) as store:
        store.add_images(paths)
        keys = [image_key(path) for path in paths]
        for key in keys:
            store.record_detection(
                key, {"width": 640, "height": 360, "annotations": [_box("tower", 10.0)]}, force=False
            )
        item = store.item(keys[0])
    revision, editor = int(item["edit_version"]), "editor"
    session: dict[str, Any] = {
        K.ANNOTATOR_SESSION_SELECTED: keys[0],
        K.ANNOTATOR_SESSION_PICKED: keys[1],
        K.ANNOTATOR_SESSION_MOUNTED_IMAGE: keys[0],
        app._base_key(editor): [dict(a) for a in item["annotations"]],
        app._known_key(editor): {},
    }
    monkeypatch.setattr(app.st, "session_state", session)
    app._on_pick()  # an editor on screen: the move waits for its save
    assert session[K.ANNOTATOR_SESSION_SELECTED] == keys[0] and session[K.ANNOTATOR_SESSION_GOTO] == keys[1]

    boxes = editor_boxes(item["annotations"])
    boxes[0]["x"] = 50.0  # moved since the last autosave
    action = {"type": "goto", "target": keys[1], "image_key": keys[0], "revision": revision, "seq": 1, "boxes": boxes,
              "action_id": "s-1"}  # fmt: skip
    session[editor] = {"action": action}
    app._on_action(store_path, keys[0], revision, editor, keys)
    assert session[app._action_done_key(editor)] == "s-1"  # the editor unlocks on this answer only
    with ReviewStore.open(store_path) as store:
        assert store.item(keys[0])["annotations"][0]["bbox"][0] == 50.0  # saved before the move
    assert session[K.ANNOTATOR_SESSION_SELECTED] == session[K.ANNOTATOR_SESSION_PICKED] == keys[1]
    assert K.ANNOTATOR_SESSION_GOTO not in session

    session.update({K.ANNOTATOR_SESSION_SELECTED: keys[0], app._base_key(editor): []})  # another tab saved first
    app._on_action(store_path, keys[0], revision, editor, keys)
    assert session[K.ANNOTATOR_SESSION_SELECTED] == keys[1]  # not saved (reloaded), but moved as asked

    session.pop(K.ANNOTATOR_SESSION_MOUNTED_IMAGE)
    session[K.ANNOTATOR_SESSION_PICKED] = keys[0]
    app._on_pick()  # no editor on screen: moved at once
    assert session[K.ANNOTATOR_SESSION_SELECTED] == keys[0]


def _two_screenshots(tmp_path: Path, boxes=None):
    """Two detected screenshots in a store of ``tmp_path`` and the session a mounted editor leaves."""
    from tools.detection_dataset_annotator import app

    paths = [tmp_path / name for name in ("a.png", "b.png")]
    store_path = tmp_path / K.ANNOTATOR_STORE_FILE
    with ReviewStore.open(store_path) as store:
        store.add_images(paths)
        keys = [image_key(path) for path in paths]
        for key in keys:
            store.record_detection(
                key, {"width": 640, "height": 360, "annotations": [_box("tower", 10.0)]}, force=False
            )
        item = store.item(keys[0])
    session: dict[str, Any] = {
        K.ANNOTATOR_SESSION_SELECTED: keys[0],
        K.ANNOTATOR_SESSION_PICKED: keys[0],
        K.ANNOTATOR_SESSION_MOUNTED_IMAGE: keys[0],
        app._base_key("editor"): [dict(a) for a in item["annotations"]],
        app._known_key("editor"): {},
    }
    return store_path, keys, item, session


def test_a_newer_pick_is_not_cleared_by_the_goto_the_editor_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editor answers its goto for one screenshot while another was picked meanwhile: that newer request stays
    pending (the editor goes there next), the page does not move to the older one (CodeRabbit)."""
    from tools.detection_dataset_annotator import app
    from tools.detection_dataset_annotator.boxes import editor_boxes

    store_path, keys, item, session = _two_screenshots(tmp_path)
    monkeypatch.setattr(app.st, "session_state", session)
    older, newer = keys[1], "another-key"
    session[K.ANNOTATOR_SESSION_GOTO] = newer
    action = {"type": "goto", "target": older, "image_key": keys[0], "revision": item["edit_version"], "seq": 0,
              "boxes": editor_boxes(item["annotations"]), "action_id": "s-1"}  # fmt: skip
    session["editor"] = {"action": action}
    app._on_action(store_path, keys[0], int(item["edit_version"]), "editor", [*keys, newer])
    assert session[K.ANNOTATOR_SESSION_SELECTED] == keys[0]  # not moved to the older pick
    assert session[K.ANNOTATOR_SESSION_GOTO] == newer  # and the newer one is still asked for
    assert session[app._action_done_key("editor")] == "s-1"  # the editor unlocks, then sends the newer goto


def test_a_toggle_flips_the_flag_the_reviewer_saw_not_the_one_stored_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another tab marked the screenshot reviewed after this editor showed it unreviewed: Shift+Enter meant "mark it",
    and is refused (the editor reloads), not turned into "unmark" (CodeRabbit)."""
    from tools.detection_dataset_annotator import app
    from tools.detection_dataset_annotator.boxes import editor_boxes

    store_path, keys, item, session = _two_screenshots(tmp_path)
    monkeypatch.setattr(app.st, "session_state", session)
    revision = int(item["edit_version"])
    with ReviewStore.open(store_path) as store:
        assert store.save_review(keys[0], revision, reviewed=True)  # the other tab
    action = {"type": "toggle_review", "image_key": keys[0], "revision": revision, "seq": 0, "shown_reviewed": False,
              "boxes": editor_boxes(item["annotations"]), "action_id": "s-2"}  # fmt: skip
    session["editor"] = {"action": action}
    app._on_action(store_path, keys[0], revision, "editor", keys)
    with ReviewStore.open(store_path) as store:
        assert store.item(keys[0])["reviewed"] is True  # not toggled off
    assert session[K.ANNOTATOR_SESSION_RELOADS] == 1  # the editor shows the saved state again


def test_switching_the_output_folder_waits_for_the_editor_s_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed folder is only staged: the editor on screen saves its latest boxes (its "leave" action) and the folder
    in use changes on its answer, edits since its last autosave kept (CodeRabbit)."""
    from tools.detection_dataset_annotator import app
    from tools.detection_dataset_annotator.boxes import editor_boxes

    store_path, keys, item, session = _two_screenshots(tmp_path)
    monkeypatch.setattr(app.st, "session_state", session)
    session.update({K.ANNOTATOR_SESSION_OUTPUT: "old", K.ANNOTATOR_SESSION_LEAVE: "new"})
    revision = int(item["edit_version"])
    boxes = editor_boxes(item["annotations"])
    boxes[0]["x"] = 70.0  # moved since the last autosave
    action = {"type": "leave", "target": "new", "image_key": keys[0], "revision": revision, "seq": 1, "boxes": boxes,
              "action_id": "s-3"}  # fmt: skip
    session["editor"] = {"action": action}
    app._on_action(store_path, keys[0], revision, "editor", keys)
    with ReviewStore.open(store_path) as store:
        assert store.item(keys[0])["annotations"][0]["bbox"][0] == 70.0  # saved first
    assert session[K.ANNOTATOR_SESSION_OUTPUT] == "new" and K.ANNOTATOR_SESSION_LEAVE not in session
    # a request replaced meanwhile (another folder typed): the answer to the old one changes nothing
    session.update({K.ANNOTATOR_SESSION_OUTPUT: "old", K.ANNOTATOR_SESSION_LEAVE: "newer"})
    app._on_action(store_path, keys[0], revision, "editor", keys)
    assert session[K.ANNOTATOR_SESSION_OUTPUT] == "old" and session[K.ANNOTATOR_SESSION_LEAVE] == "newer"


def test_typing_another_output_folder_changes_nothing_until_it_is_used(page, tmp_path: Path) -> None:
    """With an editor on screen the button asks for the switch (the editor is asked to save first): the folder in use
    stays, and the editor is sent the request."""
    at, store, keys = page({"name": "a.png", "boxes": [_box("tower", 10)]})
    with store:
        used = at.session_state[K.ANNOTATOR_SESSION_OUTPUT]
        other = str(tmp_path / "other")
        next(t for t in at.sidebar.text_input if t.label == "Output folder").set_value(other).run()
        assert at.session_state[K.ANNOTATOR_SESSION_OUTPUT] == used  # typed, not used
        _button(at, "Use this folder").click().run()
        assert not at.exception
        assert at.session_state[K.ANNOTATOR_SESSION_OUTPUT] == used  # the editor has to save first
        assert at.session_state[K.ANNOTATOR_SESSION_LEAVE] == other
