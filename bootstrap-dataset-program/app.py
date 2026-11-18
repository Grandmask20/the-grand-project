"""Streamlit UI for bootstrapping an RF-DETR atlas detection dataset.

Run from the project folder with::

    streamlit run bootstrap-dataset-program/app.py
"""

from __future__ import annotations

import copy
import json
from functools import partial
from pathlib import Path
from typing import Any

import streamlit as st
from annotator import annotate
from constants import (
    BOOTSTRAP_ALL_LABELS,
    BOOTSTRAP_DEFAULT_INPUT_DIRS,
    BOOTSTRAP_DEFAULT_OUTPUT_DIR,
    BOOTSTRAP_DEFAULT_WORKERS,
    BOOTSTRAP_EDITOR_AUTOSAVE_MS,
    BOOTSTRAP_EDITOR_CHIP_PX,
    BOOTSTRAP_EDITOR_HEIGHT,
    BOOTSTRAP_MANIFEST_FILE,
    BOOTSTRAP_ROOT,
    BOOTSTRAP_STATE_FILE,
)
from dataset_bootstrap import (
    annotations_changed,
    apply_editor_boxes,
    detect_pending,
    discover_images,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    ensure_annotation_ids,
    export_dataset,
    label_palette,
    merge_discovered_images,
    neighbour_key,
    read_state,
    relative_source,
    resolve_input_paths,
    save_state,
)

SELECTED = "selected_image"
HIDE_REVIEWED = "hide_reviewed"
MOUNTED_EDITOR = "mounted_editor"


def _output_path(value: str) -> Path:
    """Resolve an output path relative to the project root."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else BOOTSTRAP_ROOT / path).resolve()


def _label_options(state: dict[str, Any], named_icons: bool) -> list[str]:
    """Return core, optional, and already-used labels for the editor."""
    labels = list(BOOTSTRAP_ALL_LABELS)
    if named_icons:
        labels.remove("icon")
    for image in state.get("images", {}).values():
        for annotation in image.get("annotations", []):
            label = str(annotation.get("label", ""))
            if label and label not in labels:
                labels.append(label)
    return labels


@st.cache_data(max_entries=8, show_spinner=False)
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


def _on_action(state_path: Path, image_key: str, revision: int, editor_key: str, keys: list[str]) -> None:
    """Navigation and review keys: save the boxes the action carries, then move through the queue."""
    result = st.session_state.get(editor_key) or {}
    action = result.get("action")
    state = read_state(state_path, [])
    item = _save_from_editor(state, image_key, revision, editor_key, action)
    if item is None:
        return
    kind = action.get("type")
    hide_reviewed = bool(st.session_state.get(HIDE_REVIEWED, True))
    target = image_key
    if kind in {"review_next", "toggle_review"}:
        item["reviewed"] = True if kind == "review_next" else not item.get("reviewed", False)
        leaves_queue = hide_reviewed and item["reviewed"]
        if kind == "review_next" or leaves_queue:
            target = neighbour_key(keys, image_key, 1) or (
                neighbour_key(keys, image_key, -1) if leaves_queue else image_key
            )
    elif kind == "next":
        target = neighbour_key(keys, image_key, 1) or image_key
    elif kind == "prev":
        target = neighbour_key(keys, image_key, -1) or image_key
    save_state(state_path, state)
    if target:
        st.session_state[SELECTED] = target


def _render_editor(state: dict[str, Any], key: str, keys: list[str], state_path: Path, named_icons: bool) -> None:
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
        save_state(state_path, state)
    revision = int(item.get("edit_version", 0))
    editor_key = _editor_key(key, revision)
    if st.session_state.get(MOUNTED_EDITOR) != editor_key:
        # A freshly mounted editor counts its edits from zero and its undo history starts here.
        st.session_state[MOUNTED_EDITOR] = editor_key
        st.session_state[_saved_seq_key(editor_key)] = 0
        st.session_state[_known_key(editor_key)] = {}
    _remember(editor_key, item.get("annotations", []))
    index = keys.index(key) if key in keys else -1
    payload = {
        "image_key": key,
        "revision": revision,
        "image_url": image_url,
        "width": int(item["width"]),
        "height": int(item["height"]),
        "labels": label_palette(_label_options(state, named_icons)),
        "boxes": editor_boxes(item.get("annotations", [])),
        "reviewed": bool(item.get("reviewed", False)),
        "position": f"{index + 1} / {len(keys)}" if index >= 0 else "",
        "has_prev": index > 0,
        "has_next": 0 <= index < len(keys) - 1,
        "saved_seq": st.session_state.get(_saved_seq_key(editor_key), 0),
        "chip_px": BOOTSTRAP_EDITOR_CHIP_PX,
        "autosave_ms": BOOTSTRAP_EDITOR_AUTOSAVE_MS,
        "editor_height": BOOTSTRAP_EDITOR_HEIGHT,
    }
    annotate(
        payload,
        key=editor_key,
        on_edit_change=partial(_on_edit, state_path, key, revision, editor_key),
        on_action_change=partial(_on_action, state_path, key, revision, editor_key, keys),
    )
    st.caption(
        f"`{relative_source(path)}` · {item['width']} × {item['height']} · boxes are saved as source-image pixels; "
        "the screenshot file is never changed. Press **?** in the editor for shortcuts."
    )


def main() -> None:
    """Run the Streamlit bootstrapper."""
    st.set_page_config(page_title="RF-DETR Atlas Dataset Bootstrapper", layout="wide")

    with st.sidebar:
        st.header("RF-DETR dataset")
        st.subheader("Dataset settings")
        input_text = st.text_area(
            "Screenshot roots (one per line)",
            value="\n".join(BOOTSTRAP_DEFAULT_INPUT_DIRS),
            height=100,
            help="Paths are recursive. Relative paths are resolved from the project folder.",
        )
        output_text = st.text_input("Output folder", BOOTSTRAP_DEFAULT_OUTPUT_DIR)
        include_paths = st.checkbox(
            "Include paths and path dashes",
            value=False,
            help="Traced paths and their dashes are emitted together as the `path` class.",
        )
        include_fortress_walls = st.checkbox(
            "Include fortress walls",
            value=False,
            help="Export classical fortress-wall regions as a separate `fortress_wall` class.",
        )
        named_icons = st.checkbox(
            "Name icons by type",
            value=False,
            help="Labels icons such as `icon_mapboss`. Changes labels only, not whether icons are found. "
            "Rerun processed screenshots to apply it.",
        )
        max_workers = st.number_input(
            "Concurrent detector workers",
            min_value=1,
            max_value=8,
            value=BOOTSTRAP_DEFAULT_WORKERS,
            help="More workers finish large queues faster but use more memory, especially for 4K screenshots.",
        )
        st.divider()
        hide_reviewed = st.checkbox("Hide reviewed screenshots", value=True, key=HIDE_REVIEWED)
        reviewed_only = st.checkbox("Export reviewed screenshots only", value=True)

    roots = resolve_input_paths(input_text.splitlines())
    output_dir = _output_path(output_text)
    state_path = output_dir / BOOTSTRAP_STATE_FILE
    try:
        state = read_state(state_path, roots)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Could not load review state: {exc}")
        return

    state.setdefault("settings", {})
    old_derived = state["settings"].get("include_derived", False)
    settings_changed = (
        state["settings"].get("include_paths", old_derived) != include_paths
        or state["settings"].get("include_fortress_walls", old_derived) != include_fortress_walls
        or state["settings"].get("named_icons") != named_icons
    )
    if settings_changed and state.get("images"):
        st.sidebar.warning(
            "Settings affect new detections only. Rerun selected/all screenshots to apply them; "
            "rerunning replaces edits."
        )

    def run_detection(*, keys: list[str] | None = None, force: bool = False, show_progress: bool = True) -> None:
        progress_bar = st.progress(0.0) if show_progress else None
        status = st.empty()

        def progress(done: int, total: int, path: str) -> None:
            if progress_bar is not None:
                progress_bar.progress(done / max(1, total), text=f"{done:,}/{total:,} complete")
            status.caption(f"Finished {Path(path).name}")
            if done % 10 == 0 or done == total:
                save_state(state_path, state)

        with st.spinner("Running the classical detector…"):
            completed, errors = detect_pending(
                state,
                include_paths=include_paths,
                include_fortress_walls=include_fortress_walls,
                named_icons=named_icons,
                keys=keys,
                force=force,
                max_workers=int(max_workers),
                progress=progress,
            )
        save_state(state_path, state)
        st.session_state["detection_notice"] = (
            f"Processed {completed} screenshots; {errors} failed. Failed items remain retryable."
        )
        st.rerun()

    images = state.get("images", {})
    pending_count = sum(not item.get("detected") for item in images.values())
    with st.sidebar:
        discover, detect_all = st.columns(2)
        if discover.button("Discover", use_container_width=True, help="Find screenshots below the roots"):
            paths = discover_images(roots)
            added, existing = merge_discovered_images(state, paths)
            state["input_roots"] = [str(root) for root in roots]
            save_state(state_path, state)
            st.session_state["detection_notice"] = (
                f"Discovered {len(paths)} images ({added} new, {existing} already in the queue)."
            )
            st.rerun()
        if detect_all.button(f"Detect new ({pending_count})", use_container_width=True, disabled=not pending_count):
            run_detection()
        if st.button("Export dataset", type="primary", use_container_width=True):
            result = export_dataset(state, output_dir, reviewed_only=reviewed_only)
            st.success(
                f"Exported {result['images']} images and {result['annotations']} boxes to "
                f"`{result['manifest_path']}` and `{result['coco_path']}`."
            )
            if result["skipped_annotations"]:
                st.warning(f"Skipped {result['skipped_annotations']} invalid annotations.")
        if (output_dir / BOOTSTRAP_MANIFEST_FILE).is_file():
            st.caption(f"Last export: `{output_dir / BOOTSTRAP_MANIFEST_FILE}`")
        with st.expander("Rerun all screenshots"):
            rerun_all_confirmed = st.checkbox(
                "I understand this replaces existing edits",
                help=(
                    "Successful reruns replace annotations and clear review flags. If a rerun fails, its previous "
                    "detections and review flag are kept."
                ),
            )
            if st.button("Rerun all", use_container_width=True, disabled=not images or not rerun_all_confirmed):
                run_detection(keys=list(images), force=True)

    if notice := st.session_state.pop("detection_notice", None):
        st.toast(notice)

    visible = {key: item for key, item in images.items() if not hide_reviewed or not item.get("reviewed", False)}
    processed = sum(1 for item in images.values() if item.get("detected"))
    reviewed = sum(1 for item in images.values() if item.get("reviewed"))
    if not visible:
        st.info(
            "Nothing to review: press **Discover** and **Detect new** in the sidebar, or turn off "
            "‘Hide reviewed screenshots’ to revisit completed work."
        )
        return

    keys = list(visible)
    if st.session_state.get(SELECTED) not in keys:
        st.session_state[SELECTED] = keys[0]

    def option_text(key: str) -> str:
        item = images[key]
        marker = "✓" if item.get("reviewed") else ("·" if item.get("detected") else "○")
        return f"{marker} {item.get('source', item.get('path', key))}"

    pick, detect = st.columns([5, 1], vertical_alignment="bottom")
    selected = pick.selectbox(
        f"Screenshot · {len(images)} images · {processed} processed · {reviewed} reviewed",
        keys,
        format_func=option_text,
        key=SELECTED,
    )
    selected_item = images.get(selected, {})
    if selected_item.get("detected"):
        rerun = detect.button(
            "Rerun detection",
            use_container_width=True,
            help="Replace this screenshot's boxes with a fresh classical detection (clears its review flag).",
        )
    else:
        rerun = detect.button("Detect", type="primary", use_container_width=True)
    if rerun:
        run_detection(keys=[selected], force=bool(selected_item.get("detected")), show_progress=False)
    _render_editor(state, selected, keys, state_path, named_icons)


if __name__ == "__main__":
    main()
