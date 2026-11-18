"""The bootstrapper's box editor: a Streamlit components v2 component with plain JS and CSS, no build step.

The screenshot is shown as an ``<img>`` and every box as its own element above it, so boxes are never part of the
picture. The editor sends its boxes back as the ``edit`` state (autosave) and navigation as the ``action`` trigger.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

_HERE = Path(__file__).resolve().parent

# Registered once per process; asset paths only work for installed packages, so the files are passed as text.
_COMPONENT = st.components.v2.component(
    "bootstrap_box_editor",
    js=(_HERE / "annotator.js").read_text(encoding="utf-8"),
    css=(_HERE / "annotator.css").read_text(encoding="utf-8"),
)

__all__ = ["annotate"]


def annotate(
    payload: dict[str, Any],
    *,
    key: str,
    on_edit_change: Callable[[], None],
    on_action_change: Callable[[], None],
) -> Any:
    """Mount the editor and return its result (``.edit`` state, ``.action`` trigger).

    The callbacks run before the next script run, so a save is on disk before the page is drawn again; inside
    them ``st.session_state[key]`` holds the ``edit`` and ``action`` values.
    """
    return _COMPONENT(
        data=payload,
        key=key,
        default={"edit": None},
        on_edit_change=on_edit_change,
        on_action_change=on_action_change,
        width="stretch",
        height="content",
    )
