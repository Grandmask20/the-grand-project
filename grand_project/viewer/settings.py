"""viewer.settings (from atlas_viewer.py)"""

from __future__ import annotations

import json

from grand_project import fileio as atlas_io
from grand_project import paths as rc_paths

from .helpers import LOG

SETTINGS = rc_paths.USER_DATA / "viewer_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s: dict) -> None:
    try:
        atlas_io.write_text_atomic(SETTINGS, json.dumps(s, indent=1))
    except Exception:
        LOG.warning("settings could not be saved", exc_info=True)
