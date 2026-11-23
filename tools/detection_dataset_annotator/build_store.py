"""Bring the annotator's review store up to date in one rerunnable run: the steps that took the first detection run's
store (2026-11-20: 1,947 screenshots) to the one being reviewed.

    python -m tools.detection_dataset_annotator.build_store [--output-dir D] [--root R ...] [--truth T ...]
        [--workers N] [--no-detect] [--dry-run]

It builds a new store from nothing as well as it updates one built before a step existed. Each step changes only
what is not done yet, so a second run changes nothing:

1. back up the store (``ANNOTATOR_BUILD_BACKUP`` next to it; SQLite's online backup, safe while the page runs);
2. discover the screenshots below the roots (``--root``, else the store's, else ``ANNOTATOR_DEFAULT_INPUT_DIRS``)
   and queue the new ones;
3. remove what discovery leaves out: a byte copy of another screenshot (the first in discovery order stays, as
   discovery keeps it: the 115 ``screenshots/crawl`` copies of fr-atlas went) and a screenshot in an
   ``ANNOTATOR_SKIP_DIRS`` folder. Reviewed ones stay and are named; missing files are only counted (a drive may be
   away);
4. detect the screenshots not detected yet (``pool.detect_pending``, with the store's detection options; never a
   rerun);
5. seed the hand-labelled biome truths (``truth_seed``; by default ``ANNOTATOR_TRUTH_FILES``, the PM's fr-atlas
   truth).

Then ``python -m tools.detection_dataset_annotator.split_ledger`` gives every screenshot its split (the ledger's
where it has one). ``--dry-run`` backs up, adds, removes, detects and saves nothing: it says what would change.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path

from . import constants as K
from .pool import detect_pending
from .state import copies, discover_images, discovery_order, image_key, relative_source, resolve_path
from .store import ReviewStore
from .truth_seed import Truth, seed_lines, seed_store


def left_out(paths: Mapping[str, Path], discovered: Iterable[Path]) -> dict[str, str]:
    """The store's screenshots discovery leaves out, and why.

    Args:
        paths: image key -> path of every store screenshot.
        discovered: what discovery found (the originals of copies the store does not hold yet).

    Returns:
        Image key -> the reason: in a skipped folder, or the same bytes as an earlier file in discovery order.
    """
    out = {
        key: f"in a {part!r} folder"
        for key, path in paths.items()
        for part in Path(path).parent.parts
        if part in K.ANNOTATOR_SKIP_DIRS
    }
    kept = {Path(path): key for key, path in paths.items() if key not in out}
    for copy, original in copies(discovery_order({*kept, *discovered})).items():
        key = kept.get(copy)
        if key is not None:
            out[key] = f"same bytes as {relative_source(original)}"
    return out


def _backup_path(output_dir: Path) -> Path:
    """A new file for the store's backup: stamped with the time, numbered when a run in the same second made one."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / K.ANNOTATOR_BUILD_BACKUP.format(stamp=stamp)
    number = 2
    while path.exists():
        path = output_dir / K.ANNOTATOR_BUILD_BACKUP.format(stamp=f"{stamp}-{number}")
        number += 1
    return path


def _truth_files(truths: list[Path] | None, say: Callable[[str], None]) -> list[Path]:
    """The truth files to seed: the given ones (each must exist), else the defaults that exist."""
    if truths is not None:
        for path in truths:
            if not path.is_file():
                raise FileNotFoundError(f"no truth file {path}")
        return truths
    found = [Path(path) for path in K.ANNOTATOR_TRUTH_FILES if Path(path).is_file()]
    for path in K.ANNOTATOR_TRUTH_FILES:
        if not Path(path).is_file():
            say(f"  no truth file {relative_source(Path(path))} (test data not here): not seeded")
    return found


def build(
    output_dir: Path,
    *,
    roots: list[Path] | None = None,
    truths: list[Path] | None = None,
    detect: bool = True,
    workers: int | None = None,
    dry_run: bool = False,
    say: Callable[[str], None] = print,
) -> Counter[str]:
    """Run the steps on the store in ``output_dir`` (created when there is none), saying what each did.

    Returns:
        What was done: ``added``, ``removed``, ``kept reviewed``, ``missing``, ``detected``, ``failed``, ``seeded``
        (screenshots changed by the truths); with ``dry_run``, what would be.

    Raises:
        FileNotFoundError: A truth file given in ``truths`` does not exist.
    """
    done: Counter[str] = Counter()
    truth_files = _truth_files(truths, say)
    store_path = output_dir / K.ANNOTATOR_STORE_FILE
    existed = store_path.is_file()
    if dry_run and not existed:
        say(f"No store at {relative_source(store_path)}: a run would build it from the roots")
        return done
    with ReviewStore.open(store_path) as store:
        say("1. Back up")
        if dry_run:
            say("  (dry run: no backup)")
        elif not existed or not store.queue():
            say("  nothing to back up")
        else:
            backup = _backup_path(output_dir)
            store.backup(backup)
            say(f"  {relative_source(backup)}")

        say("2. Discover")
        roots = roots or [Path(root) for root in store.input_roots()] or list(K.ANNOTATOR_DEFAULT_INPUT_DIRS)
        for root in roots:
            if not Path(root).exists():
                say(f"  root {relative_source(Path(root))} is not here")
        found = discover_images(roots)
        if dry_run:
            known = set(store.paths())
            done["added"] = sum(image_key(path) not in known for path in found)
        else:
            done["added"], _existing = store.add_images(found)
            store.set_input_roots(roots)
        say(f"  {len(found)} screenshots below {len(roots)} roots, {done['added']} new")

        say("3. Remove what discovery leaves out")
        paths = {key: Path(path) for key, path in store.paths().items()}
        reviewed = {entry.key for entry in store.queue() if entry.reviewed}
        why = left_out(paths, found)
        for key in sorted(why.keys() & reviewed, key=lambda key: str(paths[key])):
            say(f"  kept, reviewed: {relative_source(paths[key])} ({why[key]})")
        done["kept reviewed"] = len(why.keys() & reviewed)
        removable = [key for key in why if key not in reviewed]
        done["removed"] = len(removable) if dry_run else len(store.remove_unreviewed(removable))
        for reason, count in sorted(Counter(why[key].split(" as ")[0] for key in removable).items()):
            say(f"  {reason}: {count}")
        done["missing"] = sum(not path.is_file() for key, path in paths.items() if key not in why)
        say(f"  {done['removed']} {'would be ' if dry_run else ''}removed; {done['missing']} files missing (kept)")

        say("4. Detect")
        pending = sum(not entry.detected for entry in store.queue())
        if not pending:
            say("  every screenshot is detected")
        elif dry_run or not detect:
            say(f"  {pending} screenshots not detected yet ({'dry run' if dry_run else '--no-detect'})")
        else:

            def progress(finished: int, total: int, _path: str) -> None:
                if finished == total or finished % K.ANNOTATOR_BUILD_PROGRESS_EVERY == 0:
                    say(f"  {finished}/{total}")

            done["detected"], done["failed"] = detect_pending(
                store, store.settings(), max_workers=workers, progress=progress
            )
            say(f"  {done['detected']} detected, {done['failed']} failed (retry: run again)")

        say("5. Seed the biome truths")
        if not truth_files:
            say("  no truth files")
        for path in truth_files:
            say(f"  {relative_source(path)}")
            seeded, changed, placed = seed_store(store, Truth.load(path), dry_run=dry_run)
            done["seeded"] += changed
            for line in seed_lines(seeded, changed, placed, dry_run=dry_run):
                say(f"    {line}")

        queue = store.queue()
        say(
            f"Store: {len(queue)} screenshots, {sum(entry.detected for entry in queue)} detected, "
            f"{sum(entry.reviewed for entry in queue)} reviewed, {sum(entry.guesses for entry in queue)} guesses"
        )
    folder = _quoted(relative_source(output_dir))
    say(
        f"Next: python -m tools.detection_dataset_annotator.split_ledger --output-dir {folder} (every screenshot's "
        "split, kept in the ledger)"
    )
    return done


def _quoted(text: str) -> str:
    """A command-line argument quoted for this system's shell (a folder name may hold spaces)."""
    return subprocess.list2cmdline([text]) if os.name == "nt" else shlex.quote(text)


def main(argv: list[str] | None = None) -> int:
    """Run the steps on the annotator's store."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default=K.ANNOTATOR_DEFAULT_OUTPUT_DIR, help="the annotator's output folder")
    parser.add_argument("--root", action="append", help="a screenshot root (repeatable; default: the store's)")
    parser.add_argument("--truth", action="append", help="a biome truth file (repeatable; default: the PM's)")
    parser.add_argument("--workers", type=int, help="detection worker processes (default: as the page's)")
    parser.add_argument("--no-detect", action="store_true", help="leave undetected screenshots for the page")
    parser.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    args = parser.parse_args(argv)
    try:
        build(
            resolve_path(args.output_dir),
            roots=[resolve_path(root) for root in args.root] if args.root else None,
            truths=[resolve_path(truth) for truth in args.truth] if args.truth else None,
            detect=not args.no_detect,
            workers=args.workers,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
