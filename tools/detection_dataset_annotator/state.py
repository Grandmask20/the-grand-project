"""The annotator's review state: screenshot discovery, the ``review_state.json`` file and the review queue.

The state is plain JSON (``schema_version``, ``input_roots``, ``settings``, ``images``) keyed by ``image_key``, so
it can be read without this program. It never holds pixels; screenshots are referenced by path.
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
    """A stable, filesystem-safe identifier for a screenshot."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def relative_source(path: Path, root: Path = paths.ROOT) -> str:
    """The screenshot's project-relative name, or its absolute path when it lies outside the project."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def new_state(input_roots: Iterable[Path]) -> dict[str, Any]:
    """An empty review state with the default detection options."""
    return {
        "schema_version": K.ANNOTATOR_SCHEMA_VERSION,
        "input_roots": [str(path) for path in input_roots],
        "settings": DetectionOptions().as_settings(),
        "images": {},
    }


def read_state(path: Path, input_roots: Iterable[Path]) -> dict[str, Any]:
    """Load a review state, or a fresh one when the file does not exist yet.

    Raises:
        ValueError: The file is from another schema version.
        json.JSONDecodeError: The file is not JSON.
    """
    if not path.is_file():
        return new_state(input_roots)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != K.ANNOTATOR_SCHEMA_VERSION:
        raise ValueError(f"Unsupported review state version: {state.get('schema_version')}")
    state.setdefault("input_roots", [str(root) for root in input_roots])
    state.setdefault("settings", {})
    state.setdefault("images", {})
    return state


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


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist the review state."""
    write_json_atomic(path, state)


def merge_discovered_images(state: dict[str, Any], images: Iterable[Path]) -> tuple[int, int]:
    """Add newly discovered screenshots, keeping every existing detection and edit; return (added, existing)."""
    added = existing = 0
    items = state.setdefault("images", {})
    for path in images:
        key = image_key(path)
        if key in items:
            existing += 1
            continue
        items[key] = {
            "path": str(path),
            "source": relative_source(path),
            "reviewed": False,
            "detected": False,
            "annotations": [],
        }
        added += 1
    return added, existing


def label_names(state: dict[str, Any], *, named_icons: bool, derived: bool) -> list[str]:
    """The labels of a state: the core labels (and the derived ones), every icon type, then every other label in use.

    With named icons the generic ``icon`` label is left out: icons are labelled ``icon_<name>`` instead, one label
    per icon type (``dataset_icon_types``, in ``ICON_INFO`` order) whether or not a screenshot has one yet, so every
    type can be labelled and an export numbers the classes the same way every time (user). Labels in use that are
    not one of them (``icon_unidentified``, an old type, a custom label) follow.
    """
    labels = list(K.ANNOTATOR_ALL_LABELS if derived else K.ANNOTATOR_CORE_LABELS)
    if named_icons:
        labels.remove("icon")
        labels.extend(icon_class(name) for name in dataset_icon_types())
    for image in state.get("images", {}).values():
        for annotation in image.get("annotations", []):
            label = str(annotation.get("label", ""))
            if label and label not in labels:
                labels.append(label)
    return labels


def neighbour_key(keys: list[str], current: str, step: int) -> str | None:
    """The screenshot ``step`` places from ``current`` in the queue, or None past either end."""
    if not keys:
        return None
    if current not in keys:
        return keys[0]
    index = keys.index(current) + step
    return keys[index] if 0 <= index < len(keys) else None
