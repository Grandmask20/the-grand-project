"""Streamlit page of the detection dataset annotator. Start it from the project folder with::

    python -m tools.detection_dataset_annotator

Streamlit runs this file as a script, not as part of its package, so it imports the package by its absolute name
(the project folder is on the path because the program is started with ``python -m`` from there).
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import streamlit as st

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.boxes import (
    annotations_changed,
    apply_editor_boxes,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    ensure_annotation_ids,
    label_palette,
)
from tools.detection_dataset_annotator.component import annotate
from tools.detection_dataset_annotator.export import export_dataset
from tools.detection_dataset_annotator.pool import cpu_count, default_workers, detect_pending
from tools.detection_dataset_annotator.state import (
    DetectionOptions,
    discover_images,
    label_names,
    merge_discovered_images,
    neighbour_key,
    read_state,
    relative_source,
    resolve_input_paths,
    resolve_path,
    save_state,
)


@dataclass(frozen=True)
class Settings:
    """The sidebar's choices."""

    roots: tuple[Path, ...]
    output_dir: Path
    options: DetectionOptions
    max_workers: int
    hide_reviewed: bool
    reviewed_only: bool

    @property
    def state_path(self) -> Path:
        return self.output_dir / K.ANNOTATOR_STATE_FILE


# ---- the editor's autosave and navigation ----------------------------------------------------------------------


@st.cache_data(max_entries=K.ANNOTATOR_EDITOR_IMAGE_CACHE, show_spinner=False)
def _image_url(path: str, modified_ns: int) -> str | None:
    """The editor's copy of a screenshot, re-encoded only when the file changes."""
    del modified_ns  # part of the cache key only
    return editor_image_url(Path(path))


def _editor_key(image_key: str, revision: int) -> str:
    return f"annotator-{image_key}-{revision}"


def _saved_seq_key(editor_key: str) -> str:
    return f"saved-seq-{editor_key}"


def _known_key(editor_key: str) -> str:
    return f"known-boxes-{editor_key}"


def _remember(editor_key: str, annotations: list[dict[str, Any]]) -> None:
    """Keep every annotation version this editor has shown, by id, so Ctrl+Z after a saved delete restores it."""
    known = st.session_state.setdefault(_known_key(editor_key), {})
    known.update({str(a["id"]): copy.deepcopy(a) for a in annotations if a.get("id") is not None})


def _save_from_editor(
    state: dict[str, Any], image_key: str, revision: int, editor_key: str, payload: Any
) -> dict[str, Any] | None:
    """Apply an editor message to ``state``; return the item, or None when the message is stale."""
    item = state.get("images", {}).get(image_key)
    if item is None or int(item.get("edit_version", 0)) != revision:
        return None
    if not editor_payload_matches(payload, image_key, revision):
        return None
    saved = item.get("annotations", [])
    _remember(editor_key, saved)
    edited = apply_editor_boxes(
        saved,
        payload["boxes"],
        width=int(item["width"]),
        height=int(item["height"]),
        known=st.session_state[_known_key(editor_key)].values(),
    )
    if annotations_changed(saved, edited):
        item["annotations"] = edited
        ensure_annotation_ids(item)
        _remember(editor_key, item["annotations"])
    st.session_state[_saved_seq_key(editor_key)] = int(payload.get("seq", 0))
    return item


def _on_edit(state_path: Path, image_key: str, revision: int, editor_key: str) -> None:
    """Autosave: runs before the script whenever the editor sends its boxes."""
    result = st.session_state.get(editor_key) or {}
    state = read_state(state_path, [])
    if _save_from_editor(state, image_key, revision, editor_key, result.get("edit")) is not None:
        save_state(state_path, state)


def _action_target(kind: str, item: dict[str, Any], keys: list[str], image_key: str) -> str:
    """Apply a review action to ``item`` and return the screenshot to show next."""
    if kind in {"review_next", "toggle_review"}:
        item["reviewed"] = kind == "review_next" or not item.get("reviewed", False)
        leaves_queue = bool(st.session_state.get(K.ANNOTATOR_SESSION_HIDE_REVIEWED, True)) and item["reviewed"]
        if kind == "review_next" or leaves_queue:
            fallback = neighbour_key(keys, image_key, -1) if leaves_queue else image_key
            return neighbour_key(keys, image_key, 1) or fallback or image_key
        return image_key
    step = {"next": 1, "prev": -1}.get(kind)
    return (neighbour_key(keys, image_key, step) if step else None) or image_key


def _on_action(state_path: Path, image_key: str, revision: int, editor_key: str, keys: list[str]) -> None:
    """Navigation and review keys: save the boxes the action carries, then move through the queue."""
    result = st.session_state.get(editor_key) or {}
    action = result.get("action")
    state = read_state(state_path, [])
    item = _save_from_editor(state, image_key, revision, editor_key, action)
    if item is None:
        return
    target = _action_target(str(action.get("type")), item, keys, image_key)
    save_state(state_path, state)
    st.session_state[K.ANNOTATOR_SESSION_SELECTED] = target


def _render_editor(state: dict[str, Any], key: str, keys: list[str], settings: Settings) -> None:
    """Show the box editor for one screenshot."""
    item = state["images"][key]
    path = Path(item["path"])
    if item.get("error"):
        st.error(item["error"])
    if not item.get("detected"):
        st.info("This screenshot has not been processed by the classical detector yet. Press **Detect**.")
        return
    try:
        image_url = _image_url(str(path), path.stat().st_mtime_ns)
    except OSError:
        image_url = None
    if image_url is None:
        st.error(f"The screenshot could not be read: `{relative_source(path)}`")
        return

    if ensure_annotation_ids(item):
        save_state(settings.state_path, state)
    revision = int(item.get("edit_version", 0))
    editor_key = _editor_key(key, revision)
    if st.session_state.get(K.ANNOTATOR_SESSION_MOUNTED_EDITOR) != editor_key:
        # A freshly mounted editor counts its edits from zero and its undo history starts here.
        st.session_state[K.ANNOTATOR_SESSION_MOUNTED_EDITOR] = editor_key
        st.session_state[_saved_seq_key(editor_key)] = 0
        st.session_state[_known_key(editor_key)] = {}
    _remember(editor_key, item.get("annotations", []))
    index = keys.index(key) if key in keys else -1
    labels = label_names(state, named_icons=settings.options.named_icons, derived=True)
    payload = {
        "image_key": key,
        "revision": revision,
        "image_url": image_url,
        "width": int(item["width"]),
        "height": int(item["height"]),
        "labels": label_palette(labels),
        "boxes": editor_boxes(item.get("annotations", [])),
        "reviewed": bool(item.get("reviewed", False)),
        "position": f"{index + 1} / {len(keys)}" if index >= 0 else "",
        "has_prev": index > 0,
        "has_next": 0 <= index < len(keys) - 1,
        "saved_seq": st.session_state.get(_saved_seq_key(editor_key), 0),
        "chip_px": K.ANNOTATOR_EDITOR_CHIP_PX,
        "autosave_ms": K.ANNOTATOR_EDITOR_AUTOSAVE_MS,
        "editor_height": K.ANNOTATOR_EDITOR_HEIGHT,
    }
    annotate(
        payload,
        key=editor_key,
        on_edit_change=partial(_on_edit, settings.state_path, key, revision, editor_key),
        on_action_change=partial(_on_action, settings.state_path, key, revision, editor_key, keys),
    )
    st.caption(
        f"`{relative_source(path)}` · {item['width']} × {item['height']} · boxes are saved as source-image pixels; "
        "the screenshot file is never changed. Press **?** in the editor for shortcuts."
    )


# ---- page sections ---------------------------------------------------------------------------------------------


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
        output_text = st.text_input("Output folder", K.ANNOTATOR_DEFAULT_OUTPUT_DIR)
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
                "Changes labels only, not whether icons are found. Rerun processed screenshots to apply it.",
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
        reviewed_only = st.checkbox("Export reviewed screenshots only", value=True)
    return Settings(
        roots=tuple(resolve_input_paths(input_text.splitlines())),
        output_dir=resolve_path(output_text),
        options=options,
        max_workers=int(max_workers),
        hide_reviewed=hide_reviewed,
        reviewed_only=reviewed_only,
    )


def _run_detection(
    state: dict[str, Any], settings: Settings, *, keys: list[str] | None = None, force: bool = False
) -> None:
    """Detect screenshots with progress, save the state, and rerun the page to show the results."""
    progress_bar = st.progress(0.0) if keys is None or len(keys) > 1 else None
    status = st.empty()
    last_save = time.monotonic()

    def progress(done: int, total: int, path: str) -> None:
        nonlocal last_save
        if progress_bar is not None:
            progress_bar.progress(done / max(1, total), text=f"{done:,}/{total:,} complete")
        status.caption(f"Finished {Path(path).name}")
        # By time, not by count: with many workers a save every few screenshots would take most of the time.
        if time.monotonic() - last_save >= K.ANNOTATOR_SAVE_EVERY_S:
            save_state(settings.state_path, state)
            last_save = time.monotonic()

    with st.spinner("Running the classical detector…"):
        completed, errors = detect_pending(
            state, settings.options, keys=keys, force=force, max_workers=settings.max_workers, progress=progress
        )
    save_state(settings.state_path, state)
    st.session_state[K.ANNOTATOR_SESSION_NOTICE] = (
        f"Processed {completed} screenshots; {errors} failed. Failed items remain retryable."
    )
    st.rerun()


def _sidebar_actions(state: dict[str, Any], settings: Settings) -> None:
    """Discover, detect, export and rerun-all buttons."""
    images = state["images"]
    pending_count = sum(not item.get("detected") for item in images.values())
    with st.sidebar:
        discover, detect_new = st.columns(2)
        if discover.button("Discover", use_container_width=True, help="Find screenshots below the roots"):
            found = discover_images(settings.roots)
            added, existing = merge_discovered_images(state, found)
            state["input_roots"] = [str(root) for root in settings.roots]
            save_state(settings.state_path, state)
            st.session_state[K.ANNOTATOR_SESSION_NOTICE] = (
                f"Discovered {len(found)} images ({added} new, {existing} already in the queue)."
            )
            st.rerun()
        if detect_new.button(f"Detect new ({pending_count})", use_container_width=True, disabled=not pending_count):
            _run_detection(state, settings)
        if st.button("Export dataset", type="primary", use_container_width=True):
            result = export_dataset(state, settings.output_dir, reviewed_only=settings.reviewed_only)
            st.success(
                f"Exported {result.images} images and {result.annotations} boxes to "
                f"`{result.manifest_path}` and `{result.coco_path}`."
            )
            if result.skipped_annotations:
                st.warning(f"Skipped {result.skipped_annotations} invalid annotations.")
        manifest = settings.output_dir / K.ANNOTATOR_MANIFEST_FILE
        if manifest.is_file():
            st.caption(f"Last export: `{manifest}`")
        with st.expander("Rerun all screenshots"):
            confirmed = st.checkbox(
                "I understand this replaces existing edits",
                help=(
                    "Successful reruns replace annotations and clear review flags. If a rerun fails, its previous "
                    "detections and review flag are kept."
                ),
            )
            if st.button("Rerun all", use_container_width=True, disabled=not images or not confirmed):
                _run_detection(state, settings, keys=list(images), force=True)


def _queue_picker(state: dict[str, Any], settings: Settings, keys: list[str]) -> str:
    """The screenshot select box and its detect / rerun button; return the selected image key."""
    images = state["images"]
    if st.session_state.get(K.ANNOTATOR_SESSION_SELECTED) not in keys:
        st.session_state[K.ANNOTATOR_SESSION_SELECTED] = keys[0]

    def option_text(key: str) -> str:
        item = images[key]
        marker = "✓" if item.get("reviewed") else ("·" if item.get("detected") else "○")
        return f"{marker} {item.get('source', item.get('path', key))}"

    processed = sum(1 for item in images.values() if item.get("detected"))
    reviewed = sum(1 for item in images.values() if item.get("reviewed"))
    pick, detect = st.columns([5, 1], vertical_alignment="bottom")
    selected = pick.selectbox(
        f"Screenshot · {len(images)} images · {processed} processed · {reviewed} reviewed",
        keys,
        format_func=option_text,
        key=K.ANNOTATOR_SESSION_SELECTED,
    )
    detected = bool(images[selected].get("detected"))
    if detected:
        run = detect.button(
            "Rerun detection",
            use_container_width=True,
            help="Replace this screenshot's boxes with a fresh classical detection (clears its review flag).",
        )
    else:
        run = detect.button("Detect", type="primary", use_container_width=True)
    if run:
        _run_detection(state, settings, keys=[selected], force=detected)
    return selected


def main() -> None:
    """Run the Streamlit page."""
    st.set_page_config(page_title="Detection Dataset Annotator", layout="wide")
    settings = _sidebar()
    try:
        state = read_state(settings.state_path, settings.roots)
    except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        st.error(f"Could not load review state: {exc}")
        return

    if state["images"] and DetectionOptions.from_settings(state["settings"]) != settings.options:
        st.sidebar.warning(
            "Settings affect new detections only. Rerun selected/all screenshots to apply them; "
            "rerunning replaces edits."
        )
    _sidebar_actions(state, settings)
    if notice := st.session_state.pop(K.ANNOTATOR_SESSION_NOTICE, None):
        st.toast(notice)

    images = state["images"]
    keys = [key for key, item in images.items() if not settings.hide_reviewed or not item.get("reviewed", False)]
    if not keys:
        st.info(
            "Nothing to review: press **Discover** and **Detect new** in the sidebar, or turn off "
            "‘Hide reviewed screenshots’ to revisit completed work."
        )
        return
    selected = _queue_picker(state, settings, keys)
    _render_editor(state, selected, keys, settings)


if __name__ == "__main__":
    main()
