"""Safe file writing and the worker-process setup shared by the builder, the atlas-wide check and the viewer.

write_text_atomic: the atlas, the settings and the detection caches are rewritten often (every bookmark,
every added screenshot). Writing them in place left a cut-off file when the program was closed, crashed or
the computer slept mid-write, and a cut-off atlas.json loses every bookmark. The text goes to a temporary
file next to the target, which then replaces the target in one step: readers see the old file or the new
one, never half of one.

process_pool: worker processes are always started fresh ("spawn"), as Windows and macOS do anyway. Linux
would otherwise copy ("fork") the viewer process, threads and Tk included, which can hang.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
from pathlib import Path


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):        # Windows: a virus scanner / cloud sync may hold the target briefly
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path) -> dict | None:
    """the JSON in a file, or None when it is missing, cut off or not JSON (e.g. a cache from a crash)"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def workers(wanted: int) -> int:
    """at most `wanted` worker processes, and one core left for the window"""
    return max(1, min(wanted, (os.cpu_count() or 2) - 1))


def process_pool(max_workers: int):
    from concurrent.futures import ProcessPoolExecutor
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=multiprocessing.get_context("spawn"))
