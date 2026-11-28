"""Streamlit page of the detection dataset annotator. Start it from the project folder with::

    python -m tools.detection_dataset_annotator

Streamlit runs this file as a script, not as part of its package, so it imports the package by its absolute name
(the project folder is on the path because the program is started with ``python -m`` from there).
"""

from __future__ import annotations

import copy
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import streamlit as st

from grand_project.detect import constants as DK
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.boxes import (
    annotations_changed,
    apply_editor_boxes,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    label_palette,
)
from tools.detection_dataset_annotator.component import annotate
from tools.detection_dataset_annotator.export import export_dataset
from tools.detection_dataset_annotator.pool import cpu_count, default_workers, detect_pending
from tools.detection_dataset_annotator.split_ledger import SplitConflict
from tools.detection_dataset_annotator.state import (
    DetectionOptions,
    changed_since_detection,
    current_digest,
    discover_images,
    image_key,
    label_names,
    neighbour_key,
    relative_source,
    resolve_input_paths,
    resolve_path,
)
from tools.detection_dataset_annotator.store import QueueEntry, ReviewStore


@dataclass(frozen=True)
class Settings:
    """The sidebar's choices."""

    roots: tuple[Path, ...]
    output_dir: Path
    options: DetectionOptions
    max_workers: int
    hide_reviewed: bool
    reviewed_only: bool
    guesses_first: bool = False

    @property
    def store_path(self) -> Path:
        return self.output_dir / K.ANNOTATOR_STORE_FILE


# ---- the editor's autosave and navigation ----------------------------------------------------------------------


@st.cache_data(max_entries=K.ANNOTATOR_EDITOR_IMAGE_CACHE, show_spinner=False)
def _image_url(path: str, modified_ns: int) -> str | None:
    """The editor's copy of a screenshot, re-encoded only when the file changes."""
    del modified_ns  # part of the cache key only
    return editor_image_url(Path(path))


def _dataset_id(store_path: Path) -> str:
    """A short id of the review store: two output folders can hold the same screenshot at the same revision."""
    return image_key(store_path)


def _editor_key(store_path: Path, key: str, revision: int) -> str:
    reloads = int(st.session_state.get(K.ANNOTATOR_SESSION_RELOADS, 0))
    return f"annotator-{_dataset_id(store_path)}-{key}-{revision}-{reloads}"


def _saved_seq_key(editor_key: str) -> str:
    return f"saved-seq-{editor_key}"


def _action_done_key(editor_key: str) -> str:
    """The id of the editor's last action the page handled: the editor stays locked until it is told so."""
    return f"action-done-{editor_key}"


def _known_key(editor_key: str) -> str:
    return f"known-boxes-{editor_key}"


def _base_key(editor_key: str) -> str:
    """The boxes the store held when this editor last read or saved them: what its next save is made against."""
    return f"base-boxes-{editor_key}"


def _forget(editor_key: str) -> None:
    """Drop an editor's session memory (save counter, undo memory, base boxes): only the editor on screen keeps any."""
    for name in (
        _saved_seq_key(editor_key),
        _known_key(editor_key),
        _base_key(editor_key),
        _action_done_key(editor_key),
    ):
        st.session_state.pop(name, None)


def _remember(editor_key: str, annotations: list[dict[str, Any]]) -> None:
    """Keep the annotations this editor has shown, by id, so Ctrl+Z after a saved delete or edit restores them: a
    detector's (or a truth's) version is kept over a later manual one, the one an undo can give back."""
    known = st.session_state.setdefault(_known_key(editor_key), {})
    for annotation in annotations:
        if annotation.get("id") is None:
            continue
        held = known.get(str(annotation["id"]))
        if held is None or held.get("source") == K.ANNOTATOR_MANUAL_SOURCE:
            known[str(annotation["id"])] = copy.deepcopy(annotation)


def _message_item(store: ReviewStore, image_key: str, revision: int, payload: Any) -> dict[str, Any] | None:
    """The screenshot an editor message is about, or None when the message is stale: from another screenshot, or
    from before a detector rerun (whose new boxes it must not overwrite)."""
    if not editor_payload_matches(payload, image_key, revision):
        return None
    item = store.item(image_key)
    return item if item is not None and item["edit_version"] == revision else None


def _edited_annotations(item: dict[str, Any], editor_key: str, payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The annotations an editor message leaves on ``item``, or None when its boxes change nothing."""
    saved = item.get("annotations", [])
    _remember(editor_key, saved)
    edited = apply_editor_boxes(
        saved,
        payload["boxes"],
        width=int(item["width"]),
        height=int(item["height"]),
        known=st.session_state[_known_key(editor_key)].values(),
    )
    return edited if annotations_changed(saved, edited) else None


def _accepted(editor_key: str, payload: dict[str, Any], edited: list[dict[str, Any]] | None) -> None:
    """Note a saved editor message: its boxes join the undo memory and become the editor's base, and the editor is
    told its edits up to the message's ``seq`` are saved."""
    if edited is not None:
        _remember(editor_key, edited)
        st.session_state[_base_key(editor_key)] = copy.deepcopy(edited)
    st.session_state[_saved_seq_key(editor_key)] = int(payload.get("seq", 0))


def _changed_elsewhere(item: dict[str, Any], editor_key: str) -> bool:
    """Whether the screenshot's boxes are no longer the ones this editor's edits were made on: another tab saved
    them meanwhile (both edit whole box lists). Then this edit is not saved and the editor is reloaded with the saved
    boxes. An editor this session knows no base for (an old one's late message) never saves."""
    base = st.session_state.get(_base_key(editor_key))
    if base is not None and not annotations_changed(base, item.get("annotations", [])):
        return False
    if base is not None:
        _reload_editor()
    return True


def _reload_editor() -> None:
    """Show the saved boxes again in a fresh editor, saying why: this editor's edit was not saved (another tab or a
    background pass saved the screenshot first). Its edits are not acknowledged, and the queue stays where it is."""
    st.session_state[K.ANNOTATOR_SESSION_RELOADS] = int(st.session_state.get(K.ANNOTATOR_SESSION_RELOADS, 0)) + 1
    st.session_state[K.ANNOTATOR_SESSION_NOTICE] = (
        "This screenshot was saved from another tab meanwhile: your last edit was not saved, and the editor shows "
        "the saved boxes again."
    )


def _review_log(payload: dict[str, Any], *, reviewed: bool | None) -> dict[str, Any]:
    """What an editor message adds to the screenshot's review log (``save_review``'s ``review_s`` and
    ``reviewed_at``, added in the save's own write): the editor's review timer, and when it was marked reviewed."""
    active_ms = max(0.0, float(payload.get("active_ms") or 0))
    return {
        "review_s": active_ms / 1000.0,
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S") if reviewed else None,
    }


def _on_edit(store_path: Path, image_key: str, revision: int, editor_key: str) -> None:
    """Autosave: runs before the script whenever the editor sends its boxes."""
    payload = (st.session_state.get(editor_key) or {}).get("edit")
    with ReviewStore.open(store_path) as store:
        item = _message_item(store, image_key, revision, payload)
        if item is None or _changed_elsewhere(item, editor_key):
            return
        edited = _edited_annotations(item, editor_key, payload)
        log = _review_log(payload, reviewed=None)
        if (edited is not None or log["review_s"] > 0) and not store.save_review(
            image_key, revision, annotations=edited, expect_boxes=item["annotations"], **log
        ):
            _reload_editor()  # a detector rerun or another tab's save landed in between
            return
    _accepted(editor_key, payload, edited)


def _action_target(kind: str, reviewed: bool, keys: list[str], image_key: str) -> tuple[bool | None, str]:
    """A review action's new review flag (None: unchanged) and the screenshot to show next."""
    if kind in {"review_next", "toggle_review"}:
        reviewed = kind == "review_next" or not reviewed
        leaves_queue = bool(st.session_state.get(K.ANNOTATOR_SESSION_HIDE_REVIEWED, True)) and reviewed
        if kind == "review_next" or leaves_queue:
            fallback = neighbour_key(keys, image_key, -1) if leaves_queue else image_key
            return reviewed, neighbour_key(keys, image_key, 1) or fallback or image_key
        return reviewed, image_key
    step = {"next": 1, "prev": -1}.get(kind)
    return None, (neighbour_key(keys, image_key, step) if step else None) or image_key


def _use_output_folder(folder: str) -> None:
    """Switch to another output folder (its own review store): what the sidebar staged, once the editor on screen has
    saved."""
    st.session_state[K.ANNOTATOR_SESSION_OUTPUT] = folder
    st.session_state.pop(K.ANNOTATOR_SESSION_LEAVE, None)


def _select(key: str) -> None:
    """Show a screenshot: the page's own and the list's choice (a move the list asked for is done)."""
    st.session_state[K.ANNOTATOR_SESSION_SELECTED] = key
    st.session_state[K.ANNOTATOR_SESSION_PICKED] = key
    st.session_state.pop(K.ANNOTATOR_SESSION_GOTO, None)


def _unmount() -> None:
    """No editor on screen: the next one mounts fresh, without this one's saved count or undo memory."""
    st.session_state.pop(K.ANNOTATOR_SESSION_MOUNTED_IMAGE, None)
    if mounted := st.session_state.pop(K.ANNOTATOR_SESSION_MOUNTED_EDITOR, None):
        _forget(mounted)


def _on_pick() -> None:
    """The screenshot list: with an editor on screen, it is asked to save its latest boxes and go there (its "goto"
    action, ``_on_action``); retired at once, edits made since its last autosave were lost (CodeRabbit). Without
    one, the page goes there now."""
    picked = st.session_state.get(K.ANNOTATOR_SESSION_PICKED)
    shown = st.session_state.get(K.ANNOTATOR_SESSION_SELECTED)
    if picked == shown:
        st.session_state.pop(K.ANNOTATOR_SESSION_GOTO, None)
    elif st.session_state.get(K.ANNOTATOR_SESSION_MOUNTED_IMAGE) == shown:
        st.session_state[K.ANNOTATOR_SESSION_GOTO] = picked
    else:
        _select(picked)


def _on_action(store_path: Path, image_key: str, revision: int, editor_key: str, keys: list[str]) -> None:
    """Navigation and review keys: save the boxes the action carries, then move through the queue. The list's "goto"
    moves to the screenshot picked whether its save went through or not (it was asked for)."""
    action = (st.session_state.get(editor_key) or {}).get("action")
    if isinstance(action, dict):
        # handled, saved or not: the editor unlocks when the page answers with it (and only then: an autosave's answer
        # comes before)
        st.session_state[_action_done_key(editor_key)] = action.get("action_id")
    if isinstance(action, dict) and action.get("type") == "goto":
        picked = action.get("target")
        _save_action(store_path, image_key, revision, editor_key, keys, action)
        newer = st.session_state.get(K.ANNOTATOR_SESSION_GOTO)
        if newer is not None and newer != picked:
            return  # another screenshot was picked meanwhile: that request stays, and the editor goes there next
        _select(picked if picked in keys else image_key)
        return
    if isinstance(action, dict) and action.get("type") == "leave":
        target = action.get("target")
        _save_action(store_path, image_key, revision, editor_key, keys, action)  # saved or not (reloaded): it was asked
        if st.session_state.get(K.ANNOTATOR_SESSION_LEAVE) == target:
            _use_output_folder(str(target))
        return
    target = _save_action(store_path, image_key, revision, editor_key, keys, action)
    if target is not None:
        _select(target)


def _save_action(
    store_path: Path, image_key: str, revision: int, editor_key: str, keys: list[str], action: Any
) -> str | None:
    """Save what an editor action carries (its boxes, the review flag); return the screenshot to show next, or None
    when nothing was saved (a stale message, or another tab's save first: the editor is reloaded)."""
    with ReviewStore.open(store_path) as store:
        item = _message_item(store, image_key, revision, action)
        if item is None or _changed_elsewhere(item, editor_key):
            return None
        edited = _edited_annotations(item, editor_key, action)
        kind = str(action.get("type"))
        # the flag the reviewer saw when pressing the key (the editor sends it), else the one stored now
        shown = action.get("shown_reviewed")
        displayed = bool(item.get("reviewed")) if shown is None else bool(shown)
        reviewed, target = _action_target(kind, displayed, keys, image_key)
        log = _review_log(action, reviewed=reviewed)
        changes = edited is not None or reviewed is not None or log["review_s"] > 0
        # a toggle flips the flag that was on screen: saved only while the store still has it (another tab may have
        # toggled it since, and the reviewer pressed the key to undo what they saw), so the queue moves by the flag
        # saved; "Reviewed, next" sets it whatever it was
        was = displayed if kind == "toggle_review" else None
        if changes and not store.save_review(
            image_key,
            revision,
            annotations=edited,
            reviewed=reviewed,
            expect_boxes=item["annotations"],
            expect_reviewed=was,
            **log,
        ):
            _reload_editor()  # a detector rerun or another tab's save landed in between
            return None
    _accepted(editor_key, action, edited)
    return target


def _render_editor(store: ReviewStore, key: str, keys: list[str], settings: Settings) -> None:
    """Show the box editor for one screenshot."""
    item = store.item(key)
    if item is None:
        return
    path = Path(item["path"])
    if item.get("error"):
        st.error(item["error"])
    if not item.get("detected"):
        _unmount()
        st.info("This screenshot has not been processed by the classical detector yet. Press **Detect**.")
        return
    if changed_since_detection(item, current_digest(path)):
        # its boxes frame the picture detected, not the file now (replaced since, maybe by one of its size)
        _unmount()
        st.error(
            f"`{item['source']}` is missing or changed since its detection: its boxes would frame another picture. "
            "Press **Rerun detection** (it replaces its boxes)."
        )
        return
    try:
        image_url = _image_url(str(path), path.stat().st_mtime_ns)
    except OSError:
        image_url = None
    if image_url is None:
        _unmount()
        st.error(f"The screenshot could not be read: `{item['source']}`")
        return

    revision = int(item["edit_version"])  # the store gives every box an id, so the editor can refer to it
    editor_key = _editor_key(settings.store_path, key, revision)
    mounted = st.session_state.get(K.ANNOTATOR_SESSION_MOUNTED_EDITOR)
    if mounted != editor_key:
        # A freshly mounted editor counts its edits from zero, its undo history starts here, and its edits are made on
        # the boxes saved now; the editor before it keeps no memory.
        if mounted:
            _forget(mounted)
        st.session_state[K.ANNOTATOR_SESSION_MOUNTED_EDITOR] = editor_key
        st.session_state[K.ANNOTATOR_SESSION_MOUNTED_IMAGE] = key
        st.session_state[_saved_seq_key(editor_key)] = 0
        st.session_state[_known_key(editor_key)] = {}
        st.session_state[_base_key(editor_key)] = copy.deepcopy(item.get("annotations", []))
    _remember(editor_key, item.get("annotations", []))
    index = keys.index(key) if key in keys else -1
    options = settings.options
    labels = label_names(
        store.used_labels(),
        named_icons=options.named_icons,
        paths=options.include_paths,
        walls=options.include_fortress_walls,
    )
    payload = {
        "dataset": _dataset_id(settings.store_path),
        "image_key": key,
        "revision": revision,
        "reload": int(st.session_state.get(K.ANNOTATOR_SESSION_RELOADS, 0)),
        "image_url": image_url,
        "width": int(item["width"]),
        "height": int(item["height"]),
        "labels": label_palette(labels),
        "guess_sources": sorted(K.ANNOTATOR_GUESS_SOURCES),
        "boxes": editor_boxes(item.get("annotations", [])),
        "reviewed": bool(item.get("reviewed", False)),
        "position": f"{index + 1} / {len(keys)}" if index >= 0 else "",
        "has_prev": index > 0,
        "has_next": 0 <= index < len(keys) - 1,
        "saved_seq": st.session_state.get(_saved_seq_key(editor_key), 0),
        "action_done": st.session_state.get(_action_done_key(editor_key)),
        # a screenshot picked in the list: the editor saves its latest boxes and asks to go there (_on_action)
        "goto": goto if (goto := st.session_state.get(K.ANNOTATOR_SESSION_GOTO)) in keys and goto != key else None,
        # a switch of the output folder asked for: the editor saves its latest boxes first ("leave", ``_on_action``)
        "leave": st.session_state.get(K.ANNOTATOR_SESSION_LEAVE),
        "chip_px": K.ANNOTATOR_EDITOR_CHIP_PX,
        "autosave_ms": K.ANNOTATOR_EDITOR_AUTOSAVE_MS,
        "idle_ms": K.ANNOTATOR_IDLE_MS,
        "editor_height": K.ANNOTATOR_EDITOR_HEIGHT,
    }
    annotate(
        payload,
        key=editor_key,
        on_edit_change=partial(_on_edit, settings.store_path, key, revision, editor_key),
        on_action_change=partial(_on_action, settings.store_path, key, revision, editor_key, keys),
    )
    st.caption(
        f"`{item['source']}` · {item['width']} × {item['height']} · boxes are saved as source-image pixels; "
        "the screenshot file is never changed. Dotted boxes are guesses to check first. Press **?** in the editor for "
        "shortcuts."
    )


# ---- page sections ---------------------------------------------------------------------------------------------


def _output_folder_box() -> str:
    """The sidebar's output-folder box; returns the folder in use.

    Typing only stages another folder: using it retires the editor on screen (its review store is another), which
    must first save its latest boxes, so a "Use this folder" button asks the editor to (its "leave" action,
    ``_on_action``) and the switch happens on its answer; with no editor on screen it happens at once.
    """
    state = st.session_state
    state.setdefault(K.ANNOTATOR_SESSION_OUTPUT, K.ANNOTATOR_DEFAULT_OUTPUT_DIR)
    state.setdefault(K.ANNOTATOR_SESSION_OUTPUT_TEXT, state[K.ANNOTATOR_SESSION_OUTPUT])
    typed = st.text_input("Output folder", key=K.ANNOTATOR_SESSION_OUTPUT_TEXT).strip()
    if state.get(K.ANNOTATOR_SESSION_LEAVE) is not None and not state.get(K.ANNOTATOR_SESSION_MOUNTED_EDITOR):
        _use_output_folder(str(state[K.ANNOTATOR_SESSION_LEAVE]))  # no editor to wait for any more
    if typed and typed != state[K.ANNOTATOR_SESSION_OUTPUT]:
        pending = state.get(K.ANNOTATOR_SESSION_LEAVE) is not None
        if st.button("Use this folder", width="stretch", disabled=pending, help="Saves the open screenshot first"):
            state[K.ANNOTATOR_SESSION_LEAVE] = typed
            if not state.get(K.ANNOTATOR_SESSION_MOUNTED_EDITOR):
                _use_output_folder(typed)
            st.rerun()
        st.caption(f"Still using `{state[K.ANNOTATOR_SESSION_OUTPUT]}`.")
    return str(state[K.ANNOTATOR_SESSION_OUTPUT])


def _sidebar() -> Settings:
    """The dataset settings in the sidebar."""
    with st.sidebar:
        st.header("RF-DETR dataset")
        st.subheader("Dataset settings")
        input_text = st.text_area(
            "Screenshot roots (one per line)",
            value="\n".join(relative_source(root) for root in K.ANNOTATOR_DEFAULT_INPUT_DIRS),
            height=100,
            help="Paths are recursive. Relative paths are resolved from the project folder.",
        )
        output_text = _output_folder_box()
        options = DetectionOptions(
            include_paths=st.checkbox(
                "Include paths and path dashes",
                value=False,
                help="Traced paths and their dashes are emitted together as the `path` class.",
            ),
            include_fortress_walls=st.checkbox(
                "Include fortress walls",
                value=False,
                help="Export classical fortress-wall regions as a separate `fortress_wall` class.",
            ),
            named_icons=st.checkbox(
                "Name icons by type",
                value=False,
                help="Labels icons such as `icon_mapboss`, and lists every icon type (with its picture) as a label. "
                "Off, every icon is `icon` (the deadly-boss icon too). Either way the export gives the detector one "
                "`icon` class, named by the icon pictures. Changes labels only, not whether icons are found. "
                "Rerun processed screenshots to apply it.",
            ),
        )
        max_workers = st.number_input(
            "Concurrent detector workers",
            min_value=1,
            max_value=cpu_count(),
            value=min(default_workers(), cpu_count()),
            help="One detector process per worker; each needs about 1.3 GB of memory. The default uses every CPU "
            "but two, as far as the memory allows.",
        )
        st.divider()
        hide_reviewed = st.checkbox("Hide reviewed screenshots", value=True, key=K.ANNOTATOR_SESSION_HIDE_REVIEWED)
        guesses_first = st.checkbox(
            "Most guesses first",
            value=False,
            help="Order the queue by how many dotted guesses (unsure city type, biome or city area) a screenshot has.",
        )
        reviewed_only = st.checkbox("Export reviewed screenshots only", value=True)
    return Settings(
        roots=tuple(resolve_input_paths(input_text.splitlines())),
        output_dir=resolve_path(output_text),
        options=options,
        max_workers=int(max_workers),
        hide_reviewed=hide_reviewed,
        reviewed_only=reviewed_only,
        guesses_first=guesses_first,
    )


def _run_detection(
    store: ReviewStore, settings: Settings, *, keys: list[str] | None = None, force: bool = False
) -> None:
    """Detect screenshots with progress, then rerun the page to show the results.

    Each screenshot's result is saved as it arrives (``ReviewStore.record_detection``), so a run that is stopped keeps
    what it finished, and the editor (another browser tab) can keep saving meanwhile.
    """
    progress_bar = st.progress(0.0) if keys is None or len(keys) > 1 else None
    status = st.empty()

    def progress(done: int, total: int, path: str) -> None:
        if progress_bar is not None:
            progress_bar.progress(done / max(1, total), text=f"{done:,}/{total:,} complete")
        status.caption(f"Finished {Path(path).name}")

    with st.spinner("Running the classical detector…"):
        outcome = detect_pending(
            store, settings.options, keys=keys, force=force, max_workers=settings.max_workers, progress=progress
        )
    completed, errors = outcome
    skipped = (
        f"; {outcome.skipped} not saved (edited, reviewed or detected meanwhile: what is there stands)"
        if outcome.skipped
        else ""
    )
    st.session_state[K.ANNOTATOR_SESSION_NOTICE] = (
        f"Processed {completed} screenshots; {errors} failed{skipped}. Failed items remain retryable."
    )
    st.rerun()


def _export(store: ReviewStore, settings: Settings) -> None:
    """Export the dataset and show what was written (or why the splits stopped it)."""
    try:
        result = export_dataset(store, settings.output_dir, reviewed_only=settings.reviewed_only)
    except SplitConflict as conflict:
        st.error(str(conflict))
        return
    st.success(
        f"Exported {result.images} images and {result.annotations} boxes to "
        f"`{result.manifest_path}` and `{result.coco_path}`. Splits: "
        + ", ".join(f"{name} {count}" for name, count in (result.splits or {}).items())
        + (f"; {result.ledger_added} screenshots added to the split ledger." if result.ledger_added else "")
    )
    if result.unknown:
        st.warning(
            "Exported labels the dataset does not know as classes of their own: "
            + ", ".join(f"`{label}` ({count})" for label, count in sorted(result.unknown.items()))
            + ". If the labels changed since those screenshots were detected, rerun them (Rerun all) instead."
        )
    if result.skipped_annotations:
        st.warning(f"Skipped {result.skipped_annotations} invalid annotations or icons the dataset leaves out.")
    if result.changed:
        st.warning(
            f"Left out {len(result.changed)} screenshots changed since their detection (rerun their detection): "
            + ", ".join(f"`{source}`" for source in result.changed[:20])
        )
    if result.report:
        with st.expander("Split balance"):
            st.code(result.report, language=None)


def _model_prelabels(settings: Settings) -> None:
    """Start the model pre-label pass (``model_prelabel``, its own process: the GPU work would stall the page) and
    show its progress."""
    running = st.session_state.get(K.ANNOTATOR_SESSION_PRELABEL)
    busy = running is not None and running.poll() is None
    # this session's pass's own log, else the folder's newest (another tab's): every pass writes its own
    log = st.session_state.get(K.ANNOTATOR_SESSION_PRELABEL_LOG)
    if log is None or Path(log).parent != settings.output_dir:
        logs = sorted(settings.output_dir.glob(K.ANNOTATOR_PRELABEL_LOG_GLOB), key=lambda path: path.stat().st_mtime)
        log = logs[-1] if logs else None
    with st.expander("Model pre-labels"):
        st.caption(
            "An RF-DETR model pre-labels unreviewed training screenshots beside the classical boxes: a share of their "
            "blocks, the rest keep the classical boxes, so the effort report compares both. Validation and test "
            "screenshots never get them."
        )
        model = st.text_input("Model folder", relative_source(DK.RF_DETR_DEFAULT_MODEL_DIR))
        share = st.slider("Share of blocks the model pre-labels", 0.0, 1.0, 0.5, 0.05)
        if st.button("Pre-label", width="stretch", disabled=busy):
            settings.output_dir.mkdir(parents=True, exist_ok=True)
            stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.monotonic_ns()}"
            log = settings.output_dir / K.ANNOTATOR_PRELABEL_LOG.format(stamp=stamp)
            st.session_state[K.ANNOTATOR_SESSION_PRELABEL_LOG] = log
            with open(log, "x", encoding="utf-8") as out:  # a new file: never another pass's
                st.session_state[K.ANNOTATOR_SESSION_PRELABEL] = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",  # unbuffered: the plan and progress reach the log as they are printed
                        "-m",
                        "tools.detection_dataset_annotator.model_prelabel",
                        "--model",
                        str(resolve_path(model)),
                        "--share",
                        str(share),
                        "--output-dir",
                        str(settings.output_dir),
                    ],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    cwd=str(resolve_path(".")),
                )
            st.rerun()
        if busy:
            st.caption("Pre-labelling… (refresh to follow it)")
        if log is not None and Path(log).is_file():
            lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()[-4:]
            st.code("\n".join(lines) or "(no output yet)", language=None)


def _sidebar_actions(store: ReviewStore, queue: list[QueueEntry], settings: Settings) -> None:
    """Discover, detect, export and rerun-all buttons."""
    pending_count = sum(not entry.detected for entry in queue)
    with st.sidebar:
        discover, detect_new = st.columns(2)
        if discover.button("Discover", width="stretch", help="Find screenshots below the roots"):
            found = discover_images(settings.roots)
            added, existing = store.add_images(found)  # new screenshots only: every detection and edit is kept
            store.set_input_roots(settings.roots)
            st.session_state[K.ANNOTATOR_SESSION_NOTICE] = (
                f"Discovered {len(found)} images ({added} new, {existing} already in the queue)."
            )
            st.rerun()
        if detect_new.button(f"Detect new ({pending_count})", width="stretch", disabled=not pending_count):
            _run_detection(store, settings)
        if st.button("Export dataset", type="primary", width="stretch"):
            _export(store, settings)
        manifest = settings.output_dir / K.ANNOTATOR_MANIFEST_FILE
        if manifest.is_file():
            st.caption(f"Last export: `{manifest}`")
        _model_prelabels(settings)
        with st.expander("Rerun all screenshots"):
            confirmed = st.checkbox(
                "I understand this replaces existing edits",
                help=(
                    "Successful reruns replace annotations and clear review flags. If a rerun fails, its previous "
                    "detections and review flag are kept."
                ),
            )
            if st.button("Rerun all", width="stretch", disabled=not queue or not confirmed):
                _run_detection(store, settings, keys=[entry.key for entry in queue], force=True)


def _queue_picker(store: ReviewStore, queue: list[QueueEntry], settings: Settings, keys: list[str]) -> str:
    """The screenshot select box and its detect / rerun button; return the image key on screen (a screenshot picked
    in the list is shown once the editor saved its boxes for the move: ``_on_pick``)."""
    entries = {entry.key: entry for entry in queue}
    state = st.session_state
    if state.get(K.ANNOTATOR_SESSION_SELECTED) not in keys:
        _select(keys[0])
    shown = state[K.ANNOTATOR_SESSION_SELECTED]
    if state.get(K.ANNOTATOR_SESSION_GOTO) not in keys:
        state.pop(K.ANNOTATOR_SESSION_GOTO, None)  # (the list changed meanwhile: the move is off)
    if state.get(K.ANNOTATOR_SESSION_PICKED) not in (shown, state.get(K.ANNOTATOR_SESSION_GOTO)):
        state[K.ANNOTATOR_SESSION_PICKED] = shown  # (set before the list is drawn, as Streamlit allows)

    def option_text(key: str) -> str:
        entry = entries[key]
        marker = "✓" if entry.reviewed else ("·" if entry.detected else "○")
        guesses = f" · {entry.guesses} guesses" if entry.guesses and not entry.reviewed else ""
        return f"{marker} {entry.source}{guesses}"

    processed = sum(entry.detected for entry in queue)
    reviewed = sum(entry.reviewed for entry in queue)
    pick, detect = st.columns([5, 1], vertical_alignment="bottom")
    pick.selectbox(
        f"Screenshot · {len(queue)} images · {processed} processed · {reviewed} reviewed",
        keys,
        format_func=option_text,
        key=K.ANNOTATOR_SESSION_PICKED,
        on_change=_on_pick,
    )
    selected = shown
    detected = entries[selected].detected
    if detected:
        run = detect.button(
            "Rerun detection",
            width="stretch",
            help="Replace this screenshot's boxes with a fresh classical detection (clears its review flag).",
        )
    else:
        run = detect.button("Detect", type="primary", width="stretch")
    if run:
        _run_detection(store, settings, keys=[selected], force=detected)
    return selected


def _page(store: ReviewStore, settings: Settings) -> None:
    """Everything below the sidebar's settings, for the open review store."""
    queue = store.queue()
    if queue and store.settings() != settings.options:
        st.sidebar.warning(
            "Settings affect new detections only. Rerun selected/all screenshots to apply them; "
            "rerunning replaces edits."
        )
    _sidebar_actions(store, queue, settings)
    if notice := st.session_state.pop(K.ANNOTATOR_SESSION_NOTICE, None):
        st.toast(notice)

    # the screenshot on screen stays in the queue until the editor moves on (which saves its boxes first): hiding the
    # reviewed ones (the checkbox ticked) retired its editor with edits not saved yet (CodeRabbit)
    current = st.session_state.get(K.ANNOTATOR_SESSION_SELECTED)
    shown = [entry for entry in queue if not settings.hide_reviewed or not entry.reviewed or entry.key == current]
    if settings.guesses_first:
        shown.sort(key=lambda entry: -entry.guesses)  # stable: equal counts keep the queue's order
    keys = [entry.key for entry in shown]
    if not keys:
        st.info(
            "Nothing to review: press **Discover** and **Detect new** in the sidebar, or turn off "
            "‘Hide reviewed screenshots’ to revisit completed work."
        )
        _unmount()  # no editor on screen: the next one mounts fresh (its saved count from zero)
        return
    selected = _queue_picker(store, queue, settings, keys)
    _render_editor(store, selected, keys, settings)


def main() -> None:
    """Run the Streamlit page."""
    st.set_page_config(page_title="Detection Dataset Annotator", layout="wide")
    settings = _sidebar()
    try:
        # One connection per script run: it belongs to this thread (the detection pool runs in it too).
        store = ReviewStore.open(settings.store_path, settings.roots)
    except (OSError, sqlite3.Error) as exc:
        st.error(f"Could not load review state: {exc}")
        return
    with store:
        _page(store, settings)


if __name__ == "__main__":
    main()
