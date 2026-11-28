"""The annotator's review store: screenshots, their boxes, review flags and the dataset settings, in SQLite.

One database (``review_state.sqlite3``) in the output folder. An edit reads and writes only its screenshot's rows, so
it takes milliseconds however many screenshots are detected, and each detection result is committed as it arrives.

- ``images``: one row per screenshot, in queue (discovery) order by ``position``. Detector result fields without a
  column of their own are kept as JSON in ``extra``. ``split`` is its train / validation / test split once an export
  gave it one (it keeps it), ``guesses`` how many of its boxes are guesses (``ANNOTATOR_GUESS_SOURCES``), for the
  queue.
- ``annotations``: one row per box. ``WITHOUT ROWID`` with the key ``(image_key, ord)`` keeps a screenshot's boxes
  together on disk, so loading or replacing them touches a few pages, however large the dataset grows.
- ``prelabels``: the boxes a reviewer is first shown (``annotations``' columns): written by detection, truth seeding
  and model pre-labels, never by an edit, so a background pass can tell nobody edited a screenshot (``untouched``).
- ``meta``: the discovery roots and the detection options, as JSON.

The database runs in WAL mode, so the editor reads and writes while a detection run writes. Every write is one short
``BEGIN IMMEDIATE`` transaction: a check and the change it guards (``save_review``'s revision) cannot be split by
another session. A connection belongs to the thread that opened it; the page opens one per script run and one per
callback (about a millisecond each).

Items come back in the shape the rest of the annotator uses: ``path``, ``source``, ``reviewed``, ``detected``,
``edit_version``, ``next_annotation_id``, ``split``, ``guesses``, the detector's fields, and
``annotations`` (``id``, ``label``, ``bbox``, ``area``, ``iscrowd``, ``source``, ``score``). The database is plain
SQLite and can be read without this program.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import operator
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import constants as K
from .boxes import ensure_annotation_ids
from .state import DetectionOptions, image_key, relative_source

_SCHEMA = (
    "CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE images (
        key TEXT PRIMARY KEY,
        position INTEGER NOT NULL UNIQUE,
        path TEXT NOT NULL,
        source TEXT NOT NULL,
        reviewed INTEGER NOT NULL DEFAULT 0,
        detected INTEGER NOT NULL DEFAULT 0,
        detector TEXT,
        width INTEGER,
        height INTEGER,
        detector_width INTEGER,
        detector_height INTEGER,
        error TEXT,
        edit_version INTEGER NOT NULL DEFAULT 0,
        next_annotation_id INTEGER NOT NULL DEFAULT 0,
        extra TEXT NOT NULL DEFAULT '{}',
        split TEXT,
        guesses INTEGER NOT NULL DEFAULT 0,
        review_generation INTEGER NOT NULL DEFAULT 0
    )""",
    # x, y, w, h may be NULL: SQLite stores a NaN as NULL. The editor and export skip such a box, as they skip NaN.
    """CREATE TABLE annotations (
        image_key TEXT NOT NULL REFERENCES images(key) ON DELETE CASCADE,
        ord INTEGER NOT NULL,
        id TEXT NOT NULL,
        label TEXT NOT NULL,
        x REAL,
        y REAL,
        w REAL,
        h REAL,
        area REAL,
        iscrowd INTEGER NOT NULL DEFAULT 0,
        source TEXT,
        score REAL,
        PRIMARY KEY (image_key, ord),
        UNIQUE (image_key, id)
    ) WITHOUT ROWID""",
    "CREATE INDEX annotations_label ON annotations(label)",
    """CREATE TABLE prelabels (
        image_key TEXT NOT NULL REFERENCES images(key) ON DELETE CASCADE,
        ord INTEGER NOT NULL,
        id TEXT NOT NULL,
        label TEXT NOT NULL,
        x REAL,
        y REAL,
        w REAL,
        h REAL,
        area REAL,
        iscrowd INTEGER NOT NULL DEFAULT 0,
        source TEXT,
        score REAL,
        PRIMARY KEY (image_key, ord)
    ) WITHOUT ROWID""",
)

_RESULT_COLUMNS = ("detector", "width", "height", "detector_width", "detector_height", "error")
"""Detector result fields with a column of their own (besides ``detected`` and ``annotations``)."""

_ITEM_FIELDS = frozenset(
    {
        "path",
        "source",
        "reviewed",
        "detected",
        "edit_version",
        "next_annotation_id",
        "annotations",
        "split",
        "guesses",
        *_RESULT_COLUMNS,
    }
)
"""Item fields with a column (or table) of their own; any other field goes to ``extra``."""

_IMAGE_COLUMNS = (
    "key", "path", "source", "reviewed", "detected", *_RESULT_COLUMNS, "edit_version", "next_annotation_id", "extra",
    "split", "guesses",
)  # fmt: skip
_ANNOTATION_COLUMNS = ("id", "label", "x", "y", "w", "h", "area", "iscrowd", "source", "score")
_IMAGE_LIST = ", ".join(f"images.{name}" for name in _IMAGE_COLUMNS)
_ANNOTATION_LIST = ", ".join(f"annotations.{name}" for name in _ANNOTATION_COLUMNS)

_SELECT_IMAGE = f"SELECT {_IMAGE_LIST} FROM images"
_SELECT_ANNOTATIONS = f"SELECT {_ANNOTATION_LIST} FROM annotations"
_INSERT_ANNOTATION = (
    f"INSERT INTO annotations (image_key, ord, {', '.join(_ANNOTATION_COLUMNS)}) "
    f"VALUES ({', '.join('?' * (len(_ANNOTATION_COLUMNS) + 2))})"
)
_INSERT_PRELABEL = _INSERT_ANNOTATION.replace("INSERT INTO annotations", "INSERT INTO prelabels")
_SELECT_PRELABELS = f"SELECT {', '.join(_ANNOTATION_COLUMNS)} FROM prelabels"

# The distinct labels by a skip scan of the label index: one seek per label in use (about 90), where SELECT DISTINCT
# reads every box (180,000 after one detection run). The editor asks for them on every page update.
_USED_LABELS = """
    WITH RECURSIVE used(label) AS (
        SELECT MIN(label) FROM annotations WHERE label > ''
        UNION ALL
        SELECT (SELECT MIN(label) FROM annotations WHERE label > used.label) FROM used WHERE used.label IS NOT NULL
    )
    SELECT label FROM used WHERE label IS NOT NULL
"""


@dataclass(frozen=True)
class QueueEntry:
    """What the review queue shows of a screenshot (no boxes)."""

    key: str
    source: str
    detected: bool
    reviewed: bool
    guesses: int = 0
    """How many of its boxes are guesses (``ANNOTATOR_GUESS_SOURCES``)."""


def _item(row: tuple[Any, ...]) -> dict[str, Any]:
    """An item without its boxes from an ``_SELECT_IMAGE`` row (the key, its first value, is left out)."""
    values = dict(zip(_IMAGE_COLUMNS, row, strict=True))
    item: dict[str, Any] = json.loads(values["extra"])
    item.update(
        path=values["path"],
        source=values["source"],
        reviewed=bool(values["reviewed"]),
        detected=bool(values["detected"]),
        edit_version=values["edit_version"],
        next_annotation_id=values["next_annotation_id"],
        split=values["split"],
        guesses=values["guesses"],
    )
    item.update({name: values[name] for name in _RESULT_COLUMNS if values[name] is not None})
    item["annotations"] = []
    return item


def _annotation(row: tuple[Any, ...]) -> dict[str, Any]:
    """An annotation from a ``_SELECT_ANNOTATIONS`` row; fields stored as NULL (no score) are left out."""
    box_id, label, x, y, w, h, area, iscrowd, source, score = row
    annotation: dict[str, Any] = {"id": box_id, "label": label, "bbox": [x, y, w, h]}
    if area is not None:
        annotation["area"] = area
    annotation["iscrowd"] = iscrowd
    if source is not None:
        annotation["source"] = source
    if score is not None:
        annotation["score"] = score
    return annotation


def _number(value: Any) -> float | None:
    """A value as a float, or None (stored as NULL) when it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _annotation_row(key: str, ord_: int, annotation: Mapping[str, Any]) -> tuple[Any, ...]:
    """An annotation's ``_INSERT_ANNOTATION`` values; a bbox that is not four values is stored as NULLs."""
    bbox = annotation.get("bbox")
    corners = list(bbox) if isinstance(bbox, list | tuple) and len(bbox) == 4 else [None] * 4
    source, score = annotation.get("source"), annotation.get("score")
    return (
        key,
        ord_,
        str(annotation["id"]),
        str(annotation.get("label", "")),
        *(_number(value) for value in corners),
        _number(annotation.get("area")),
        int(annotation.get("iscrowd") or 0),
        None if source is None else str(source),
        _number(score),
    )


def _numbered(annotations: Iterable[Mapping[str, Any]], counter: int) -> tuple[list[dict[str, Any]], int]:
    """Copies of the annotations, each with a unique id (``ensure_annotation_ids``), and the id counter after them."""
    holder: dict[str, Any] = {"annotations": [dict(a) for a in annotations], "next_annotation_id": counter}
    ensure_annotation_ids(holder)
    return holder["annotations"], int(holder["next_annotation_id"])


def _extra(item: Mapping[str, Any]) -> str:
    """The item's fields without a column of their own, as JSON."""
    return json.dumps({name: value for name, value in item.items() if name not in _ITEM_FIELDS})


class UnknownScreenshot(KeyError):
    """A screenshot that is not in the store (removed, or never added): found out inside the write that needed it, so
    no later look can see it back (a rebuild adding it again)."""


class ReviewStore:
    """The review state of one output folder. Open it with ``ReviewStore.open``; close it (or ``with``) when done."""

    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self._db = connection
        self.path = path

    # ---- opening -------------------------------------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path, input_roots: Iterable[Path | str] = (), *, read_only: bool = False) -> ReviewStore:
        """Open the store at ``path``, creating it (with ``input_roots`` and the default detection options) when it
        does not exist yet.

        ``read_only`` (a dry run): an existing store opened for reading only, the file left exactly as it is (no
        journal mode set, no tables made); its writes raise.

        Raises:
            sqlite3.Error: The file is not a database, is locked for longer than ``ANNOTATOR_STORE_BUSY_S``, or (read
                only) does not exist or has no tables yet.
        """
        if read_only:
            # as_uri percent-encodes the path: a raw "#" or "?" in it would end the path early and drop "mode=ro"
            uri = f"{Path(path).resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=K.ANNOTATOR_STORE_BUSY_S, isolation_level=None)
            try:
                store = cls(connection, path)
                if not store._version():
                    raise sqlite3.OperationalError(f"{path} is not an annotator store yet")
            except BaseException:
                connection.close()
                raise
            return store
        path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: no implicit transactions; _write() and _read() say where each one starts and ends.
        connection = sqlite3.connect(str(path), timeout=K.ANNOTATOR_STORE_BUSY_S, isolation_level=None)
        try:
            # WAL: readers never wait for the writer. A file system that cannot do WAL keeps its journal mode.
            connection.execute("PRAGMA journal_mode = WAL")
            # In WAL, NORMAL syncs at checkpoints only: a power cut can lose the last edits, never corrupt the file.
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA foreign_keys = ON")
            store = cls(connection, path)
            store._initialise([str(root) for root in input_roots])
        except BaseException:
            connection.close()
            raise
        return store

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> ReviewStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _version(self) -> int:
        return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def _initialise(self, input_roots: list[str]) -> None:
        """Create the schema when the file is new (``PRAGMA user_version`` 0)."""
        if self._version():
            return  # the usual case, without taking the write lock
        with self._write():
            if self._version():
                return  # another session created it meanwhile
            for statement in _SCHEMA:
                self._db.execute(statement)
            self._set_meta("input_roots", input_roots)
            self._set_meta("settings", DetectionOptions().as_settings())
            self._db.execute(f"PRAGMA user_version = {int(K.ANNOTATOR_STORE_CREATED)}")

    # ---- transactions --------------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _write(self) -> Iterator[None]:
        """A write transaction: it takes the write lock at once, so what it reads first cannot change under it."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    @contextlib.contextmanager
    def _read(self) -> Iterator[None]:
        """A read transaction: every query in it sees the store as it was at its first query."""
        self._db.execute("BEGIN")
        try:
            yield
        finally:
            if self._db.in_transaction:
                self._db.execute("COMMIT")

    # ---- dataset settings ----------------------------------------------------------------------------------------

    def _meta(self, name: str, default: Any) -> Any:
        row = self._db.execute("SELECT value FROM meta WHERE name = ?", (name,)).fetchone()
        return default if row is None else json.loads(row[0])

    def _set_meta(self, name: str, value: Any) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta (name, value) VALUES (?, ?)", (name, json.dumps(value)))

    def settings(self) -> DetectionOptions:
        """The detection options of the last detection run (or the defaults)."""
        return DetectionOptions.from_settings(self._meta("settings", {}))

    def set_settings(self, options: DetectionOptions) -> None:
        with self._write():
            self._set_meta("settings", options.as_settings())

    def input_roots(self) -> list[str]:
        """The screenshot roots of the last discovery (export's source groups)."""
        return [str(root) for root in self._meta("input_roots", [])]

    def set_input_roots(self, roots: Iterable[Path | str]) -> None:
        with self._write():
            self._set_meta("input_roots", [str(root) for root in roots])

    # ---- screenshots ---------------------------------------------------------------------------------------------

    def add_images(self, paths: Iterable[Path]) -> tuple[int, int]:
        """Add newly discovered screenshots at the end of the queue, keeping every existing one as it is.

        Returns:
            (added, existing) screenshot counts.
        """
        # Keys and names first: resolving paths reads the disk, which should not happen while holding the lock. The
        # path is stored absolute, as the key resolves it: the split ledger's hash and the export read the same file
        rows = [(image_key(path), str(Path(path).resolve()), relative_source(path)) for path in paths]
        added = 0
        with self._write():
            position = self._db.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM images").fetchone()[0]
            for key, path, source in rows:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO images (key, position, path, source) VALUES (?, ?, ?, ?)",
                    (key, position, path, source),
                )
                if cursor.rowcount:
                    added += 1
                    position += 1
        return added, len(rows) - added

    def paths(self) -> dict[str, str]:
        """Image key -> screenshot path, in queue order (no boxes read)."""
        return dict(self._db.execute("SELECT key, path FROM images ORDER BY position"))

    def remove_unreviewed(self, keys: Iterable[str]) -> list[str]:
        """Remove the listed screenshots that are not reviewed, with their boxes, in one write (a review saved
        meanwhile keeps its screenshot).

        Returns:
            The keys removed.
        """
        removed = []
        with self._write():
            for key in dict.fromkeys(keys):
                if self._db.execute("DELETE FROM images WHERE key = ? AND reviewed = 0", (key,)).rowcount:
                    removed.append(key)
        return removed

    def backup(self, target: Path) -> None:
        """Copy the store to ``target`` (SQLite's online backup: one consistent moment, while others keep writing).

        Raises:
            FileExistsError: ``target`` exists.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb"):  # claimed in one step: a backup of the same name at once raises, never shares it
            pass
        try:
            copy = sqlite3.connect(str(target))
            try:
                self._db.backup(copy)
            finally:
                copy.close()
        except BaseException:
            target.unlink(missing_ok=True)  # this call made it: no half a backup left under the name
            raise

    def queue(self) -> list[QueueEntry]:
        """Every screenshot in queue order, without boxes."""
        rows = self._db.execute("SELECT key, source, detected, reviewed, guesses FROM images ORDER BY position")
        return [
            QueueEntry(key, source, bool(detected), bool(reviewed), int(guesses))
            for key, source, detected, reviewed, guesses in rows
        ]

    def item(self, key: str) -> dict[str, Any] | None:
        """One screenshot with its boxes in the editor's order, or None when it is not in the store."""
        with self._read():
            row = self._db.execute(f"{_SELECT_IMAGE} WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            item = _item(row)
            rows = self._db.execute(f"{_SELECT_ANNOTATIONS} WHERE image_key = ? ORDER BY ord", (key,))
            item["annotations"] = [_annotation(row) for row in rows]
        return item

    def items(self, *, reviewed_only: bool = False) -> Iterator[tuple[str, dict[str, Any]]]:
        """Every (reviewed) screenshot with its boxes, in queue order, read in one query as it is iterated.

        The read lasts until the iteration ends, so the whole export sees one moment of the store.
        """
        query = (
            f"SELECT {_IMAGE_LIST}, {_ANNOTATION_LIST} FROM images "
            "LEFT JOIN annotations ON annotations.image_key = images.key"
            f"{' WHERE images.reviewed = 1' if reviewed_only else ''} ORDER BY images.position, annotations.ord"
        )
        width = len(_IMAGE_COLUMNS)
        with self._read():
            for key, rows in itertools.groupby(self._db.execute(query), key=operator.itemgetter(0)):
                item: dict[str, Any] | None = None
                for row in rows:
                    if item is None:
                        item = _item(row[:width])
                    if row[width] is not None:  # an annotation's id is never NULL: NULL is the LEFT JOIN's no box
                        item["annotations"].append(_annotation(row[width:]))
                assert item is not None  # groupby never yields an empty group
                yield key, item

    def used_labels(self) -> list[str]:
        """Every label some box has, sorted."""
        return [label for (label,) in self._db.execute(_USED_LABELS)]

    # ---- splits --------------------------------------------------------------------------------------------------

    def splits(self) -> dict[str, str]:
        """Image key -> split, for the screenshots that have one."""
        return dict(self._db.execute("SELECT key, split FROM images WHERE split IS NOT NULL"))

    def claim_splits(
        self, splits: Mapping[str, str], *, only_if_free: bool = False, written: set[str] | None = None
    ) -> dict[str, str]:
        """Give screenshots their split where they have none yet, in one write, so two exports at once cannot give
        one screenshot two splits. A split is kept: nothing here moves a screenshot to another split.

        Args:
            splits: image key -> the split to give it.
            only_if_free: all or nothing: when any of them already has another split, none is written (checked in the
                same write), so the caller can stop with the store as it was.
            written: filled with the keys this write gave their split (not those another session gave the same one
                first): the ones to take back should the caller's next step fail (``release_splits``).

        Returns:
            Image key -> split as the store now has it, for every key of ``splits`` still in the store.
        """
        with self._write():
            if only_if_free:
                taken = self._splits_of(list(splits))
                if any(taken.get(key, split) != split for key, split in splits.items()):
                    return {key: taken.get(key, split) for key, split in splits.items() if key in taken}
            for key, split in splits.items():
                cursor = self._db.execute("UPDATE images SET split = ? WHERE key = ? AND split IS NULL", (split, key))
                if cursor.rowcount and written is not None:
                    written.add(key)
            stored = dict(self._db.execute("SELECT key, split FROM images WHERE split IS NOT NULL"))
        return {key: stored[key] for key in splits if key in stored}

    def release_splits(self, splits: Mapping[str, str]) -> None:
        """Take back splits a ``claim_splits`` gave (the ledger could not be written after it), in one write: each
        screenshot that still has the split given loses it."""
        with self._write():
            for key, split in splits.items():
                self._db.execute("UPDATE images SET split = NULL WHERE key = ? AND split = ?", (key, split))

    def _splits_of(self, keys: list[str]) -> dict[str, str]:
        """Image key -> its split, for those of ``keys`` that have one (inside a transaction)."""
        out: dict[str, str] = {}
        for start in range(0, len(keys), K.ANNOTATOR_SQL_CHUNK):
            chunk = keys[start : start + K.ANNOTATOR_SQL_CHUNK]
            query = f"SELECT key, split FROM images WHERE split IS NOT NULL AND key IN ({', '.join('?' * len(chunk))})"
            out.update(dict(self._db.execute(query, chunk)))
        return out

    # ---- the editor ----------------------------------------------------------------------------------------------

    def save_review(
        self,
        key: str,
        revision: int,
        *,
        annotations: Iterable[Mapping[str, Any]] | None = None,
        reviewed: bool | None = None,
        extra: Mapping[str, Any] | None = None,
        prelabel: bool = False,
        untouched: bool = False,
        expect_boxes: Iterable[Mapping[str, Any]] | None = None,
        unmarked: Iterable[str] = (),
        marked: Mapping[str, Any] | None = None,
        split: str | None = None,
        expect_reviewed: bool | None = None,
    ) -> bool:
        """Save a screenshot's edited boxes, its review flag and/or fields of ``extra``, if it is still at detection
        ``revision``.

        A detection rerun since the editor showed the screenshot raises its revision: then nothing is saved and
        False is returned, so late edits never overwrite the new detections. Boxes without a (unique) id get one.

        Args:
            key: the screenshot.
            revision: the detection revision the change was made against.
            annotations: its new boxes.
            reviewed: its new review flag.
            extra: fields merged into ``extra`` (None removes one): a truth mark, a model pre-label's record.
            prelabel: the boxes are new pre-labels (truth seeding, model pre-labels), not an edit: they also replace
                the snapshot the review is measured against (``prelabels``), and raise the revision as a detection
                does, so an editor showing the old boxes reloads instead of saving them over the new ones.
            untouched: save only while nobody reviewed or edited the screenshot (unreviewed, its boxes still its
                pre-labels), checked in the same write: a model pass running beside the page never overwrites a review
                in progress.
            expect_boxes: save only while the screenshot's boxes are still these (the snapshot a background pass
                worked from): another pass's boxes saved meanwhile are never overwritten with ones made from older.
            unmarked: save only while ``extra`` has none of these fields (a truth mark or a model pre-label set
                meanwhile).
            marked: save only while each of these ``extra`` fields is absent or has this value (another truth's
                mark set meanwhile).
            split: save only while the screenshot has this split (model pre-labels: train only, user's rule).
            expect_reviewed: save only while its review flag is still this (a toggle worked out from it: another tab
                toggling meanwhile would otherwise be undone, and the page move on by a flag never saved).
        """
        with self._write():
            row = self._db.execute(
                "SELECT edit_version, next_annotation_id, split, reviewed FROM images WHERE key = ?", (key,)
            ).fetchone()
            if row is None or row[0] != revision or (split is not None and row[2] != split):
                return False
            if expect_reviewed is not None and bool(row[3]) != expect_reviewed:
                return False
            if untouched and not self._untouched(key):
                return False
            if expect_boxes is not None and self._boxes(key) != [dict(box) for box in expect_boxes]:
                return False
            marks = tuple(unmarked)
            if marks or marked:
                (stored,) = self._db.execute("SELECT extra FROM images WHERE key = ?", (key,)).fetchone()
                have = json.loads(stored)
                if any(name in have for name in marks):
                    return False
                if any(have.get(name, value) != value for name, value in (marked or {}).items()):
                    return False
            if annotations is not None or reviewed is not None:
                # a detection queued before this edit must not replace it (record_detection's ``generation``)
                self._db.execute("UPDATE images SET review_generation = review_generation + 1 WHERE key = ?", (key,))
            if annotations is not None:
                numbered, counter = _numbered(annotations, row[1])
                self._replace_annotations(key, numbered)
                if prelabel:
                    self._replace_prelabels(key, numbered)
                    self._db.execute("UPDATE images SET edit_version = edit_version + 1 WHERE key = ?", (key,))
                self._db.execute("UPDATE images SET next_annotation_id = ? WHERE key = ?", (counter, key))
            if reviewed is not None:
                self._db.execute("UPDATE images SET reviewed = ? WHERE key = ?", (reviewed, key))
            if extra:
                (stored,) = self._db.execute("SELECT extra FROM images WHERE key = ?", (key,)).fetchone()
                merged = json.loads(stored)
                for name, value in extra.items():
                    if value is None:
                        merged.pop(name, None)
                    else:
                        merged[name] = value
                self._db.execute("UPDATE images SET extra = ? WHERE key = ?", (json.dumps(merged), key))
        return True

    def _boxes(self, key: str) -> list[dict[str, Any]]:
        """A screenshot's boxes in the editor's order, as ``item`` gives them (inside a transaction)."""
        rows = self._db.execute(f"{_SELECT_ANNOTATIONS} WHERE image_key = ? ORDER BY ord", (key,))
        return [_annotation(row) for row in rows]

    def untouched(self, key: str) -> bool:
        """Whether a screenshot is unreviewed and its boxes are still its pre-labels (False when it is not in the
        store)."""
        with self._read():
            if self._db.execute("SELECT 1 FROM images WHERE key = ?", (key,)).fetchone() is None:
                return False
            return self._untouched(key)

    def _untouched(self, key: str) -> bool:
        """Whether a screenshot is unreviewed and its boxes are still its pre-labels (inside a transaction)."""
        if self._db.execute("SELECT reviewed FROM images WHERE key = ?", (key,)).fetchone()[0]:
            return False
        query = f"SELECT {', '.join(_ANNOTATION_COLUMNS)} FROM {{}} WHERE image_key = ? ORDER BY ord"
        boxes = self._db.execute(query.format("annotations"), (key,)).fetchall()
        return boxes == self._db.execute(query.format("prelabels"), (key,)).fetchall()

    def prelabels(self, key: str) -> list[dict[str, Any]]:
        """The boxes the screenshot was first shown with (its last detection, truth seeding or model pre-labels)."""
        rows = self._db.execute(f"{_SELECT_PRELABELS} WHERE image_key = ? ORDER BY ord", (key,))
        return [_annotation(row) for row in rows]

    # ---- detection -----------------------------------------------------------------------------------------------

    def detection_jobs(self, keys: Iterable[str] | None = None, *, force: bool = False) -> list[tuple[str, str, int]]:
        """(key, path, review generation) of the screenshots to detect, in queue order: the selected ones (all without
        ``keys``), only those not detected yet unless ``force``. The generation goes with the job to
        ``record_detection``: an edit or review saved meanwhile makes its result stale."""
        selected = set(keys) if keys is not None else None
        rows = self._db.execute("SELECT key, path, detected, review_generation FROM images ORDER BY position")
        return [
            (key, path, generation)
            for key, path, detected, generation in rows
            if (selected is None or key in selected) and (force or not detected)
        ]

    def _stale(self, key: str, generation: int | None) -> bool:
        """Whether a job queued at ``generation`` is stale: the screenshot's boxes or review changed since (inside a
        write). None: no generation to check."""
        if generation is None:
            return False
        (now,) = self._db.execute("SELECT review_generation FROM images WHERE key = ?", (key,)).fetchone()
        return now != generation

    def record_detection(
        self, key: str, result: Mapping[str, Any], *, force: bool, generation: int | None = None
    ) -> bool:
        """Replace a screenshot's detector fields and boxes with a detection result.

        Its revision goes up, so an editor showing the old boxes is remounted and its late saves are refused. A
        forced rerun also clears the review flag. Box ids continue the screenshot's counter, so none is reused.

        A result that is not forced, for a screenshot detected meanwhile (another run took the same screenshot), is
        dropped: it must not replace that detection and the edits made since. So is any result, forced too, of a job
        queued at another ``generation`` (``detection_jobs``): boxes edited or a review saved since the rerun was
        asked for are kept, never cleared by it.

        Returns:
            Whether the result was saved.

        Raises:
            UnknownScreenshot: The screenshot is not in the store (a ``KeyError``).
        """
        with self._write():
            row = self._db.execute("SELECT next_annotation_id, detected FROM images WHERE key = ?", (key,)).fetchone()
            if row is None:
                raise UnknownScreenshot(key)
            if (row[1] and not force) or self._stale(key, generation):
                return False
            annotations, counter = _numbered(result.get("annotations", []), row[0])
            self._db.execute(
                "UPDATE images SET detected = ?, detector = ?, width = ?, height = ?, detector_width = ?, "
                "detector_height = ?, error = ?, extra = ?, next_annotation_id = ?, edit_version = edit_version + 1, "
                "review_generation = review_generation + 1, reviewed = CASE WHEN ? THEN 0 ELSE reviewed END "
                "WHERE key = ?",
                (
                    bool(result.get("detected", True)),
                    *(result.get(name) for name in _RESULT_COLUMNS),
                    _extra(result),
                    counter,
                    force,
                    key,
                ),
            )
            self._replace_annotations(key, annotations)
            self._replace_prelabels(key, annotations)
        return True

    def record_failure(self, key: str, error: str, *, force: bool, generation: int | None = None) -> None:
        """Note a failed detection. A failed rerun of a detected screenshot keeps its boxes and review flag; a failure
        that is not forced, for a screenshot detected meanwhile (by another run), or of a job queued at another
        ``generation``, changes nothing; otherwise the screenshot counts as not detected (it can be retried).

        Raises:
            UnknownScreenshot: The screenshot is not in the store (a ``KeyError``).
        """
        with self._write():
            row = self._db.execute("SELECT detected FROM images WHERE key = ?", (key,)).fetchone()
            if row is None:
                raise UnknownScreenshot(key)
            if self._stale(key, generation):
                return  # edited or reviewed since the job was queued: what it shows stands
            if force and row[0]:
                message = f"Rerun failed; kept previous detections. {error}"
                self._db.execute("UPDATE images SET error = ? WHERE key = ?", (message, key))
            elif row[0]:
                return  # another run detected it meanwhile: its result stands
            else:
                self._db.execute("UPDATE images SET detected = 0, error = ? WHERE key = ?", (error, key))

    # ---- boxes ---------------------------------------------------------------------------------------------------

    def _insert_annotations(self, key: str, annotations: list[dict[str, Any]]) -> None:
        """Insert boxes that all have unique ids (``_numbered``), in their order."""
        self._db.executemany(
            _INSERT_ANNOTATION, (_annotation_row(key, ord_, annotation) for ord_, annotation in enumerate(annotations))
        )

    def _replace_prelabels(self, key: str, annotations: list[dict[str, Any]]) -> None:
        self._db.execute("DELETE FROM prelabels WHERE image_key = ?", (key,))
        self._db.executemany(
            _INSERT_PRELABEL, (_annotation_row(key, ord_, annotation) for ord_, annotation in enumerate(annotations))
        )

    def _replace_annotations(self, key: str, annotations: list[dict[str, Any]]) -> None:
        self._db.execute("DELETE FROM annotations WHERE image_key = ?", (key,))
        self._insert_annotations(key, annotations)
        guesses = sum(annotation.get("source") in K.ANNOTATOR_GUESS_SOURCES for annotation in annotations)
        self._db.execute("UPDATE images SET guesses = ? WHERE key = ?", (guesses, key))
