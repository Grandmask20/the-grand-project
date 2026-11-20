"""What the annotator's review state is made of: screenshot discovery and keys, the detection options, the labels
and the review queue. The state itself is kept by ``store.py``; it never holds pixels, screenshots are referenced by
path.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from grand_project import paths
from grand_project.detect.icon_types import icon_class
from grand_project.detect.labels import annotator_labels

from . import constants as K

UNIDENTIFIED_ICON = icon_class("Unidentified")
"""The label of icons the detector found but could not name: offered while some box has it, so it can be named."""


@dataclass(frozen=True)
class DetectionOptions:
    """What a detection run emits besides the core labels; stored as the state's ``settings``."""

    include_paths: bool = False
    """Traced paths (with their dashes) as ``path`` boxes."""
    include_fortress_walls: bool = False
    """Classical fortress-wall regions as ``fortress_wall`` boxes."""
    named_icons: bool = False
    """Icons labelled by name (``icon_mapboss``) instead of one ``icon`` label (off: every icon is ``icon``, the
    deadly-boss icon too). Named or not, an export gives the detector the one ``icon`` class
    (``labels.export_class``), and the classical namer names what it finds."""

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> DetectionOptions:
        """The options saved in a state's ``settings`` (or sent to a worker); missing ones are off."""
        return cls(**{field.name: bool(settings.get(field.name, False)) for field in fields(cls)})

    def as_settings(self) -> dict[str, bool]:
        """The options as JSON for the state file and the worker request."""
        return asdict(self)

    @property
    def derived(self) -> bool:
        """Whether any optional derived label is emitted."""
        return self.include_paths or self.include_fortress_walls


def resolve_path(value: str | Path, root: Path = paths.ROOT) -> Path:
    """An absolute path for a user-entered one; relative paths are relative to the project folder."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def resolve_input_paths(values: Iterable[str], root: Path = paths.ROOT) -> list[Path]:
    """Resolve user-entered screenshot roots (one per entry), skipping blank entries."""
    return [resolve_path(value.strip(), root) for value in values if value.strip()]


def discover_images(roots: Iterable[Path]) -> list[Path]:
    """Recursively find supported image files below each input root, without duplicate paths.

    Folders named in ``ANNOTATOR_SKIP_DIRS`` (an atlas's own map pictures) are not entered. A file whose path UTF-8
    cannot hold is left out (see ``_utf8``).
    """
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_file():
            candidates: Iterable[Path] = (root,)
        elif root.is_dir():
            candidates = (
                path
                for path in root.rglob("*")
                if not any(part in K.ANNOTATOR_SKIP_DIRS for part in path.relative_to(root).parts[:-1])
            )
        else:
            continue
        for path in candidates:
            if path.suffix.lower() in K.ANNOTATOR_IMAGE_EXTENSIONS and path.is_file():
                resolved = path.resolve()
                if _utf8(str(resolved)):
                    found[os.path.normcase(str(resolved))] = resolved
    return sorted(found.values(), key=lambda path: str(path).casefold())


def _utf8(text: str) -> bool:
    """Whether UTF-8 can hold the text. A file name with bytes that are not UTF-8 (only Linux file systems allow
    one; Python keeps the bytes as surrogate escapes) cannot: the screenshot's key and the store's SQLite text need
    UTF-8, so such a file is left out rather than stopping discovery. Steam's screenshot names are plain ASCII."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def image_key(path: Path) -> str:
    """A stable, filesystem-safe identifier for a screenshot."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def relative_source(path: Path, root: Path = paths.ROOT) -> str:
    """The screenshot's project-relative name, or its absolute path when it lies outside the project."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def write_json_atomic(path: Path, value: Any) -> None:
    """Write JSON through a neighbouring temporary file, so an interrupted write never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def label_names(used: Iterable[str], *, named_icons: bool, paths: bool = False, walls: bool = False) -> list[str]:
    """The editor's labels: the dataset's (``labels.annotator_labels``) and nothing else.

    With named icons every icon type is a label (``icon_<name>``, in ``ICON_INFO`` order) whether or not a
    screenshot has one yet, so every type can be labelled, plus ``icon_unidentified`` while some box still has it (the
    icons to name); without, only ``icon`` (user). ``path`` and ``fortress_wall`` only with their options. Other labels
    in ``used`` (the store's ``used_labels``: labels the dataset no longer has, such as boxes from before the labels
    changed) are not offered: rerun those screenshots. A box that still has one shows it as is.
    """
    labels = annotator_labels(named_icons=named_icons, paths=paths, walls=walls)
    if named_icons and UNIDENTIFIED_ICON in set(used):
        labels.append(UNIDENTIFIED_ICON)
    return labels


def neighbour_key(keys: list[str], current: str, step: int) -> str | None:
    """The screenshot ``step`` places from ``current`` in the queue, or None past either end."""
    if not keys:
        return None
    if current not in keys:
        return keys[0]
    index = keys.index(current) + step
    return keys[index] if 0 <= index < len(keys) else None
