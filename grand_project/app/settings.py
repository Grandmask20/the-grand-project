"""app.settings: the app's settings (layers, styles, known atlases, auto-add folders), kept in user_data."""

from __future__ import annotations

import json

from grand_project import fileio as atlas_io
from grand_project import logs as atlas_log
from grand_project import paths as rc_paths

LOG = atlas_log.get("app")

SETTINGS = rc_paths.USER_DATA / "viewer_settings.json"


def load_settings() -> dict:
    """Reads the viewer settings (window size, layers, last atlas, ...) from user_data/viewer_settings.json.

    Returns:
        The settings dict; empty when the file is missing or unreadable.
    """
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s: dict) -> None:
    """Writes the viewer settings to user_data/viewer_settings.json (atomically); a failure is only logged.

    Args:
        s: The settings dict.
    """
    try:
        atlas_io.write_text_atomic(SETTINGS, json.dumps(s, indent=1))
    except Exception:
        LOG.warning("settings could not be saved", exc_info=True)
