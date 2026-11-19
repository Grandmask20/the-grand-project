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
from grand_project.detect.icon_types import dataset_icon_types, icon_class

from . import constants as K


@dataclass(frozen=True)
class DetectionOptions:
    """What a detection run emits besides the core labels; stored as the state's ``settings``."""

    include_paths: bool = False
    """Traced paths (with their dashes) as ``path`` boxes."""
    include_fortress_walls: bool = False
    """Classical fortress-wall regions as ``fortress_wall`` boxes."""
    named_icons: bool = False
    """Icons labelled by name (``icon_mapboss``) instead of one ``icon`` class."""

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
    """Recursively find supported image files below each input root, without duplicate paths."""
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_file():
            candidates: Iterable[Path] = (root,)
        elif root.is_dir():
            candidates = root.rglob("*")
        else:
            continue
        for path in candidates:
            if path.suffix.lower() in K.ANNOTATOR_IMAGE_EXTENSIONS and path.is_file():
                resolved = path.resolve()
                found[os.path.normcase(str(resolved))] = resolved
    return sorted(found.values(), key=lambda path: str(path).casefold())


def image_key(path: Path) -> str:
    """A stable, filesystem-safe identifier for a screenshot.

    A file name with bytes that are not UTF-8 (POSIX keeps them as surrogate escapes) is hashed in its filesystem
    encoding instead, so discovery does not stop at it; every other path keeps its UTF-8 key.
    """
    resolved = str(path.resolve())
    try:
        encoded = resolved.encode("utf-8")
    except UnicodeEncodeError:
        encoded = os.fsencode(resolved)
    return hashlib.sha256(encoded).hexdigest()[:24]


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


def label_names(used: Iterable[str], *, named_icons: bool, derived: bool) -> list[str]:
    """The dataset's labels: the core labels (and the derived ones), every icon type, then the other labels in use.

    With named icons the generic ``icon`` label is left out: icons are labelled ``icon_<name>`` instead, one label
    per icon type (``dataset_icon_types``, in ``ICON_INFO`` order) whether or not a screenshot has one yet, so every
    type can be labelled and an export numbers the classes the same way every time (user). Labels in ``used`` (the
    store's ``used_labels``) that are not one of them (``icon_unidentified``, an old type, a custom label) follow in
    alphabetical order, so their numbers do not depend on which screenshot happens to use them first.
    """
    labels = list(K.ANNOTATOR_ALL_LABELS if derived else K.ANNOTATOR_CORE_LABELS)
    if named_icons:
        labels.remove("icon")
        labels.extend(icon_class(name) for name in dataset_icon_types())
    known = set(labels)
    labels.extend(label for label in sorted(set(used)) if label and label not in known)
    return labels


def neighbour_key(keys: list[str], current: str, step: int) -> str | None:
    """The screenshot ``step`` places from ``current`` in the queue, or None past either end."""
    if not keys:
        return None
    if current not in keys:
        return keys[0]
    index = keys.index(current) + step
    return keys[index] if 0 <= index < len(keys) else None
