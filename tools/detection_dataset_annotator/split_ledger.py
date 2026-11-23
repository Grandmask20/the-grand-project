"""The split ledger: every screenshot's train / validation / test split, by the SHA-256 of its bytes.

    python -m tools.detection_dataset_annotator.split_ledger [freeze]                give every screenshot its split
    python -m tools.detection_dataset_annotator.split_ledger check [--manifest M]    compare with the ledger

A model trained in one round must never be validated or tested on a screenshot an earlier round trained on, also
while classical detection and the RF-DETR model take turns refining the labels (user). The store keeps each
screenshot's split, but the store is local data, and its image key hashes the screenshot's path on this machine: a
rebuilt store, another machine or a copy of the file would draw its split again. So the splits are also kept in
``ANNOTATOR_SPLIT_LEDGER`` (kept in git), one row per screenshot: the SHA-256 of its bytes (the app's own screenshot
identity, an ``atlas.json`` frame's ``sha``), its split, the block it was drawn with and its project-relative file.

``settle_splits`` (every export, and ``freeze``) gives every processed screenshot of the store its split: the
ledger's (by bytes; by file name for a file whose bytes changed), else the store's, else test for a pinned one, else
drawn by spatial blocks (``splits.assign_splits``); files with the same bytes share one. Then the store claims them and
the ledger gains rows for the screenshots it did not have (rows are never removed: another store may hold them).
Wherever the ledger, the store or a pinned root disagree, nothing is written: ``SplitConflict`` names the screenshots,
for a person to decide (moving a screenshot a model trained on into validation or test would leak).
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from grand_project.core.atlas import Atlas
from grand_project.detect.labels import export_class

from . import constants as K
from .blocks import Block, atlas_of, screenshot_blocks
from .splits import assign_splits, pinned_split, split_report
from .state import file_hash, relative_source, resolve_path, write_text_atomic
from .store import ReviewStore

LEDGER_COLUMNS = ("sha256", "split", "block", "file")
"""The ledger's CSV columns."""


@dataclass(frozen=True)
class Entry:
    """One screenshot of the ledger."""

    sha256: str
    """SHA-256 of the file's bytes: the screenshot's identity."""
    split: str
    block: str
    """``<atlas folder>#<n>``, the spatial block it was drawn with; empty for a screenshot no atlas places."""
    file: str
    """Its project-relative path when it was entered (for people, and for a file whose bytes changed)."""


@dataclass(frozen=True)
class Settled:
    """What ``settle_splits`` gave the store's screenshots."""

    split_of: dict[str, str]
    """Image key -> split, for every processed screenshot whose file could be read."""
    blocks: dict[str, Block]
    items: dict[str, dict[str, int]]
    """Image key -> its boxes per class (as exported), what the splits balance."""
    origins: Counter[str]
    """Screenshots by where their split came from."""
    added: int
    """Rows added to the ledger."""
    unreadable: list[str]
    """Processed screenshots whose file could not be read: no split."""


class SplitConflict(ValueError):
    """The ledger, the store or a pinned root give screenshots different splits."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = "\n".join(f"  {line}" for line in problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        super().__init__(
            f"{len(problems)} screenshots have different splits in the ledger, the store or a pinned root; nothing "
            f"was changed. Decide each one (a screenshot a model trained on must stay in train):\n{shown}{more}"
        )


def _ledger_path(path: Path | None) -> Path:
    return K.ANNOTATOR_SPLIT_LEDGER if path is None else Path(path)


@contextlib.contextmanager
def _ledger_lock(path: Path | None = None) -> Iterator[None]:
    """Hold the ledger for one read, check and rewrite (``<ledger>.lock``), so two exports at once (the page and a
    command, or two stores) never write over each other's new rows. The system frees the lock when a process ends."""
    lock = _ledger_path(path).with_name(f"{_ledger_path(path).name}.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # gives up after 10 s: then wait again
                    break
                except OSError:
                    continue
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_ledger(path: Path | None = None) -> dict[str, Entry]:
    """The ledger's rows by hash (empty when there is no ledger yet).

    Raises:
        ValueError: The file is not a ledger, names an unknown split, or gives one hash two splits.
    """
    path = _ledger_path(path)
    if not path.is_file():
        return {}
    out: dict[str, Entry] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LEDGER_COLUMNS:
            raise ValueError(f"{path} is not a split ledger: its columns must be {', '.join(LEDGER_COLUMNS)}")
        for row in reader:
            entry = Entry(**{column: row[column] or "" for column in LEDGER_COLUMNS})
            if entry.split not in K.ANNOTATOR_SPLITS:
                raise ValueError(f"{path}: {entry.file} has the unknown split {entry.split!r}")
            known = out.setdefault(entry.sha256, entry)
            if known.split != entry.split:
                raise ValueError(f"{path}: {entry.file} and {known.file} have the same bytes and different splits")
    return out


def write_ledger(entries: Iterable[Entry], path: Path | None = None) -> None:
    """Write the ledger, sorted by file (small diffs), in one step (``write_text_atomic``)."""
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    for entry in sorted(entries, key=lambda entry: (entry.file, entry.sha256)):
        writer.writerow([entry.sha256, entry.split, entry.block, entry.file])
    write_text_atomic(_ledger_path(path), text.getvalue())


def hash_files(paths: Mapping[str, Path]) -> dict[str, str]:
    """Image key -> SHA-256 of its file's bytes, for the files that can be read (hashlib lets go of the GIL while it
    hashes, so threads read several files at once)."""

    def one(item: tuple[str, Path]) -> tuple[str, str | None]:
        key, path = item
        try:
            return key, file_hash(path)
        except OSError:
            return key, None

    with ThreadPoolExecutor(max_workers=K.ANNOTATOR_HASH_THREADS) as pool:
        return {key: digest for key, digest in pool.map(one, paths.items()) if digest is not None}


def box_classes(item: Mapping[str, Any]) -> dict[str, int]:
    """A store screenshot's boxes per class they export as (the icon types the dataset leaves out not counted)."""
    out: dict[str, int] = {}
    for annotation in item.get("annotations", []):
        label = export_class(str(annotation.get("label", "")).strip())
        if label is not None:
            out[label] = out.get(label, 0) + 1
    return out


def _block_name(block: Block, file: str) -> str:
    """The ledger's name of a block: empty for a screenshot that is a block of its own."""
    return "" if block.atlas == file else f"{block.atlas}#{block.index}"


def join_blocks(blocks: Mapping[str, Block], groups: Iterable[Iterable[str]]) -> dict[str, Block]:
    """The blocks with those of each group of copies (the same bytes) joined into one, the first in order.

    A copy in two places overlaps the neighbours of both: its split is theirs, or a held-out screenshot would show
    what a training one shows. Moving the copy into the other's block alone would leave its own neighbours behind.

    Args:
        blocks: image key -> its block.
        groups: image keys of the same bytes.

    Returns:
        Image key -> its block, joined.
    """
    parent: dict[Block, Block] = {}

    def root(block: Block) -> Block:
        while block in parent:
            block = parent[block]
        return block

    for group in groups:
        joined = sorted({root(blocks[key]) for key in group})
        for other in joined[1:]:
            parent[other] = joined[0]
    return {key: root(block) for key, block in blocks.items()}


def settle_splits(
    store: ReviewStore,
    every: list[tuple[str, dict[str, Any]]] | None = None,
    *,
    ledger: Path | None = None,
) -> Settled:
    """Give every processed screenshot of the store its split, keep it in the store and the ledger.

    The ledger is read, checked and rewritten under its lock (``_ledger_lock``): the rows another export added
    meanwhile are kept, and checked like every other row.

    Args:
        store: the review store.
        every: the store's items as one read gave them (``store.items()``), when the caller has them already.
        ledger: the ledger file (default ``ANNOTATOR_SPLIT_LEDGER``).

    Raises:
        SplitConflict: The ledger, the store or a pinned root disagree; nothing was written.
    """
    every = list(store.items()) if every is None else every
    processed = [(key, item) for key, item in every if item.get("reviewed") or item.get("detected")]
    paths = {key: Path(item["path"]) for key, item in processed}
    digests = hash_files(paths)
    unreadable = sorted(relative_source(paths[key]) for key in paths if key not in digests)
    keys = sorted(digests)
    names = {key: relative_source(paths[key]) for key in keys}
    with _ledger_lock(ledger):
        book = read_ledger(ledger)
        by_file: dict[str, Entry] = {}
        for entry in book.values():
            by_file.setdefault(entry.file, entry)

        problems = []
        from_ledger: dict[str, str] = {}
        by_name: set[str] = set()
        for key in keys:
            entry, named = book.get(digests[key]), by_file.get(names[key])
            if entry is not None and named is not None and entry.split != named.split:
                # its bytes are another entry's than its name's: which one it is, a person decides
                problems.append(f"{names[key]}: ledger {entry.split} by its bytes, {named.split} by its file name")
            if entry is None and named is not None:
                entry = named
                by_name.add(key)  # the file's bytes changed: it is still the same screenshot
            if entry is not None:
                from_ledger[key] = entry.split
        stored = {key: split for key, split in store.splits().items() if key in digests}
        pinned = {key: split for key in keys if (split := pinned_split(paths[key])) is not None}

        for key in keys:
            given = {"ledger": from_ledger.get(key), "store": stored.get(key), "pinned": pinned.get(key)}
            given = {where: split for where, split in given.items() if split}
            if len(set(given.values())) > 1:
                problems.append(f"{names[key]}: " + ", ".join(f"{where} {split}" for where, split in given.items()))
        same_bytes: dict[str, list[str]] = defaultdict(list)
        for key in keys:
            same_bytes[digests[key]].append(key)
        for group in same_bytes.values():
            kept = {pinned.get(key) or from_ledger.get(key) or stored.get(key) for key in group} - {None}
            if len(kept) > 1:
                problems.append("same bytes, different splits: " + ", ".join(names[key] for key in group))
        if problems:
            raise SplitConflict(problems)

        fixed = {**stored, **from_ledger}
        # copies join their blocks into one, so they are drawn together with the neighbours of each of their places
        blocks = join_blocks(screenshot_blocks({key: paths[key] for key in keys}), same_bytes.values())
        for group in same_bytes.values():
            # and they take a split one of them has
            kept = next((pinned.get(key) or fixed.get(key) for key in group if pinned.get(key) or fixed.get(key)), None)
            for key in group:
                if kept is not None and key not in pinned:
                    fixed.setdefault(key, kept)
        items = {key: box_classes(item) for key, item in processed if key in digests}
        split_of = assign_splits(items, pinned=pinned, fixed=fixed, blocks=blocks)

        origins: Counter[str] = Counter()
        for key in keys:
            if key in by_name:
                origins["ledger (by file name: its bytes changed)"] += 1
            elif key in from_ledger:
                origins["ledger"] += 1
            elif key in stored:
                origins["store"] += 1
            elif key in pinned:
                origins["pinned to test"] += 1
            elif key in fixed:
                origins["same bytes as one with a split"] += 1
            else:
                origins["drawn"] += 1
        new = {key: split for key, split in split_of.items() if stored.get(key) != split}
        if new:
            split_of.update(store.claim_splits(new))  # another export's claim, made meanwhile, stands
        added = 0
        for key in keys:
            if digests[key] not in book:
                book[digests[key]] = Entry(
                    digests[key], split_of[key], _block_name(blocks[key], names[key]), names[key]
                )
                added += 1
        if added:
            write_ledger(book.values(), ledger)
    return Settled(split_of, blocks, items, origins, added, unreadable)


def _check_rows(rows: list[tuple[str, Path, str | None, str]], ledger: Path | None) -> list[str]:
    """Where rows (name, path, split, where) disagree with the ledger or are missing from it."""
    book = read_ledger(ledger)
    by_file = {entry.file: entry for entry in book.values()}
    digests = hash_files({str(i): path for i, (_name, path, _split, _where) in enumerate(rows)})
    problems = []
    for i, (name, _path, split, where) in enumerate(rows):
        digest = digests.get(str(i))
        if digest is None:
            problems.append(f"{name} ({where}): cannot be read")
            continue
        entry, named = book.get(digest), by_file.get(name)
        if entry is not None and named is not None and entry.split != named.split:
            problems.append(f"{name}: ledger {entry.split} by its bytes, {named.split} by its file name")
            continue
        entry = entry or named
        if entry is None:
            problems.append(f"{name} ({where} {split}): not in the ledger")
        elif entry.split != split:
            problems.append(f"{name}: {where} {split}, ledger {entry.split}")
    return problems


def _manifest_rows(manifest: Mapping[str, Any], base: Path | None) -> list[tuple[str, Path, str | None, str]]:
    """The manifest's screenshots as rows to check; a relative path lies in ``base`` (the manifest's folder, as
    ``rf_detr.load_annotator_manifest`` reads it)."""
    rows = []
    for row in manifest.get("images", []):
        path = Path(str(row["path"]))
        if not path.is_absolute() and base is not None:
            path = Path(base) / path
        rows.append((relative_source(path), path, row.get("split"), "manifest"))
    return rows


def check_manifest(manifest: Mapping[str, Any], *, base: Path | None = None, ledger: Path | None = None) -> list[str]:
    """Where an export's manifest disagrees with the ledger (the trainer's check before every dataset it builds:
    a screenshot a model trained on must stay in train). Needs no store; changes nothing.

    Args:
        manifest: the export's ``manifest.json``.
        base: the folder its relative paths lie in (its own folder).
        ledger: the ledger file (default ``ANNOTATOR_SPLIT_LEDGER``).
    """
    return _check_rows(_manifest_rows(manifest, base), ledger)


def check_splits(
    store: ReviewStore,
    *,
    ledger: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    manifest_base: Path | None = None,
) -> list[str]:
    """Where the store's splits (and an export's manifest's, its relative paths in ``manifest_base``) disagree with
    the ledger, or are missing from it.

    Changes nothing. An empty list: every split given so far is the ledger's.
    """
    rows = [
        (relative_source(Path(item["path"])), Path(item["path"]), item["split"], "store")
        for _key, item in store.items()
        if item.get("split")
    ]
    if manifest is not None:
        rows += _manifest_rows(manifest, manifest_base)
    return _check_rows(rows, ledger)


def held_out_overlap(atlas_file: Path, split_of_frame: Mapping[str, str]) -> dict[str, tuple[int, float]]:
    """How much of the held-out screenshots a training screenshot also shows, in one atlas.

    Args:
        atlas_file: the atlas (its map nodes list the screenshots that show them).
        split_of_frame: screenshot name without suffix (the frame's name) -> its split.

    Returns:
        Per held-out split: its screenshots that show a map node, and the mean share of their map nodes a training
        screenshot shows too.
    """
    seen: dict[str, set[int]] = defaultdict(set)
    for index, node in enumerate(Atlas.load(atlas_file).nodes):
        for frame in node["frames"]:
            seen[str(frame)].add(index)
    train, *held_out = K.ANNOTATOR_SPLITS
    in_train = set().union(*(seen[name] for name, split in split_of_frame.items() if split == train))
    out = {}
    for split in held_out:
        shares = [
            len(seen[name] & in_train) / len(seen[name])
            for name, given in split_of_frame.items()
            if given == split and seen[name]
        ]
        if shares:
            out[split] = (len(shares), float(np.mean(shares)))
    return out


def overlap_report(paths: Mapping[str, Path], split_of: Mapping[str, str]) -> str:
    """``held_out_overlap`` of every atlas the screenshots lie next to, as lines."""
    by_atlas: dict[Path, dict[str, str]] = defaultdict(dict)
    for key, split in split_of.items():
        path = Path(paths[key])
        if (atlas_file := atlas_of(path.parent)) is not None:
            by_atlas[atlas_file][path.stem] = split
    lines = []
    for atlas_file in sorted(by_atlas):
        overlap = held_out_overlap(atlas_file, by_atlas[atlas_file])
        shown = ", ".join(f"{split} {count} screenshots {share:.0%}" for split, (count, share) in overlap.items())
        lines.append(f"  {relative_source(atlas_file.parent)}: {shown or 'no held-out screenshots'}")
    if not lines:
        return ""
    return "map nodes of held-out screenshots a training screenshot also shows (mean):\n" + "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Freeze the store's splits into the ledger, or check them against it."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=("freeze", "check"), default="freeze")
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--ledger", help=f"the ledger file (default {relative_source(K.ANNOTATOR_SPLIT_LEDGER)})")
    parser.add_argument("--manifest", help="check: also an export's manifest.json")
    args = parser.parse_args(argv)
    ledger = resolve_path(args.ledger) if args.ledger else None
    with ReviewStore.open(resolve_path(args.output_dir) / K.ANNOTATOR_STORE_FILE) as store:
        every = list(store.items())
        paths = {key: Path(item["path"]) for key, item in every}
        if args.command == "check":
            manifest = base = None
            if args.manifest:
                manifest_path = resolve_path(args.manifest)
                manifest, base = json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path.parent
            problems = check_splits(store, ledger=ledger, manifest=manifest, manifest_base=base)
            report = overlap_report(paths, store.splits())
            if report:
                print(report)
            for line in problems:
                print(line)
            print(f"{len(problems)} disagreements with the ledger" if problems else "every split is the ledger's")
            return 1 if problems else 0
        try:
            settled = settle_splits(store, every, ledger=ledger)
        except SplitConflict as conflict:
            print(conflict)
            return 1
    print(f"{len(settled.split_of)} screenshots, their split from:")
    for origin, count in settled.origins.most_common():
        print(f"  {origin:<42} {count:6d}")
    for name in settled.unreadable:
        print(f"  cannot be read (no split): {name}")
    print(split_report(settled.items, settled.split_of, settled.blocks))
    report = overlap_report(paths, settled.split_of)
    if report:
        print(report)
    print(f"{settled.added} rows added to {relative_source(_ledger_path(ledger))}")
    return 0


__all__ = [
    "Entry",
    "Settled",
    "SplitConflict",
    "box_classes",
    "check_manifest",
    "check_splits",
    "held_out_overlap",
    "join_blocks",
    "overlap_report",
    "read_ledger",
    "settle_splits",
    "write_ledger",
]


if __name__ == "__main__":
    raise SystemExit(main())
