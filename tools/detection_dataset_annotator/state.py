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
from collections.abc import Callable, Iterable, Mapping
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


def resolve_path(value: str | Path, root: Path = paths.ROOT) -> Path:
    """An absolute path for a user-entered one; relative paths are relative to the project folder."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def resolve_input_paths(values: Iterable[str], root: Path = paths.ROOT) -> list[Path]:
    """Resolve user-entered screenshot roots (one per entry), skipping blank entries."""
    return [resolve_path(value.strip(), root) for value in values if value.strip()]


def in_skipped_folder(path: Path) -> bool:
    """Whether a file lies in a folder discovery never enters (``ANNOTATOR_SKIP_DIRS``: an atlas's own map pictures),
    anywhere above it: the one rule for discovery and the store's clean-up (``build_store.left_out``)."""
    return any(part in K.ANNOTATOR_SKIP_DIRS for part in Path(path).resolve().parent.parts)


def discover_images(roots: Iterable[Path]) -> list[Path]:
    """Recursively find supported image files below each input root, without duplicate paths or copies.

    A file in a folder named in ``ANNOTATOR_SKIP_DIRS`` (an atlas's own map pictures) is left out, wherever the root
    is (``in_skipped_folder``). A file whose path UTF-8
    cannot hold is left out (see ``_utf8``). Of files with the same bytes only the first in ``discovery_order`` is
    kept, a pinned test screenshot before the others (``copies``).
    """
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_file():
            candidates: Iterable[Path] = (root,)
        elif root.is_dir():
            candidates = root.rglob("*")
        else:
            continue
        for path in candidates:
            if path.suffix.lower() in K.ANNOTATOR_IMAGE_EXTENSIONS and path.is_file() and not in_skipped_folder(path):
                resolved = path.resolve()
                if _utf8(str(resolved)):
                    found[os.path.normcase(str(resolved))] = resolved
    ordered = discovery_order(found.values())
    later = copies(ordered)
    return [path for path in ordered if path not in later]


def discovery_order(paths: Iterable[Path]) -> list[Path]:
    """Paths in discovery's order (by path, ignoring case): of files with the same bytes, the first is kept (a
    pinned test screenshot first, ``copies``)."""
    # the path itself breaks a tie of names only the case tells apart (a case-sensitive file system), so which one is
    # kept never depends on the order they were found in
    return sorted(paths, key=lambda path: (str(path).casefold(), str(path)))


def file_hash(path: Path) -> str:
    """SHA-256 of a file's bytes: a screenshot's identity wherever it lies (the app's own, ``builder.py``; an
    ``atlas.json`` frame's ``sha``), where its image key hashes its path on this machine.

    Raises:
        OSError: The file cannot be read.
    """
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def changed_since_detection(item: Mapping[str, Any], digest: str | None) -> bool:
    """Whether a screenshot's file (its bytes' SHA-256 now, None when it cannot be read) is not the one its boxes were
    detected on (``ANNOTATOR_DETECTED_SHA``; a detection without one is not known to be it): its boxes are rerun, not
    shown, pre-labelled, seeded or exported."""
    return digest is None or item.get(K.ANNOTATOR_DETECTED_SHA) != digest


def current_digest(path: Path) -> str | None:
    """A file's SHA-256 now (``file_hash``), or None when it cannot be read."""
    try:
        return file_hash(path)
    except OSError:
        return None


def _pinned(path: Path) -> bool:
    """Whether a screenshot is pinned to the test split (``splits.pinned_split``; imported here: splits imports this
    module through blocks)."""
    from .splits import pinned_split

    return pinned_split(path) is not None


def copies(paths: Iterable[Path], prefer: Callable[[Path], bool] = _pinned) -> dict[Path, Path]:
    """Each file with the same bytes as an earlier one (in the given order) -> that first one; a file ``prefer``
    picks (by default a pinned test screenshot) comes before the others with its bytes, so it is the one kept.

    A copy would be labelled twice and could land in two splits (the 115 ``screenshots/crawl`` files are fr-atlas's
    own); a pinned screenshot kept as an unpinned copy would lose its test split. Only files of one size are
    compared, so a usual discovery reads no file. A file that cannot be read is no copy.
    """
    by_size: dict[int, list[Path]] = {}
    for path in paths:
        with contextlib.suppress(OSError):
            by_size.setdefault(path.stat().st_size, []).append(path)
    out: dict[Path, Path] = {}
    for same_size in by_size.values():
        first: dict[str, Path] = {}
        ordered = sorted(same_size, key=lambda path: not prefer(path)) if len(same_size) > 1 else ()  # stable
        for path in ordered:
            try:
                digest = file_hash(path)
            except OSError:
                continue
            if digest in first:
                out[path] = first[digest]
            else:
                first[digest] = path
    return out


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
    write_text_atomic(path, json.dumps(value, indent=2) + "\n")


def write_text_atomic(path: Path, text: str) -> None:
    """Write text (UTF-8, the same line ends on every system) through a neighbouring temporary file, so an
    interrupted write never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def label_names(used: Iterable[str], *, named_icons: bool) -> list[str]:
    """The editor's labels: the dataset's (``labels.annotator_labels``) and nothing else.

    With named icons every icon type is a label (``icon_<name>``, in ``ICON_INFO`` order) whether or not a
    screenshot has one yet, so every type can be labelled, plus ``icon_unidentified`` while some box still has it (the
    icons to name); without, only ``icon`` (user). Other labels
    in ``used`` (the store's ``used_labels``: labels the dataset no longer has, such as boxes from before the labels
    changed) are not offered: rerun those screenshots. A box that still has one shows it as is.
    """
    labels = annotator_labels(named_icons=named_icons)
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
