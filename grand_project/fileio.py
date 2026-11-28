"""Safe file writing and the worker-process setup shared by the builder, the atlas-wide check and the viewer.

write_text_atomic / write_bytes_atomic: the atlas, the settings and the detection caches are rewritten often
(every bookmark, every added screenshot). Writing them in place left a cut-off file when the program was closed,
crashed or the computer slept mid-write, and a cut-off atlas.json loses every bookmark. The contents go to a
temporary file next to the target, which then replaces the target in one step: readers see the old file or the new
one, never half of one.

process_pool: worker processes are always started fresh ("spawn"), as Windows and macOS do anyway. Linux
would otherwise copy ("fork") the viewer process, threads and Tk included, which can hang.
"""

from __future__ import annotations

import contextlib
import json
import multiprocessing
import os
import tempfile
import time
from pathlib import Path


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """Write a text file so readers see the old file or the new one, never half of one (``write_bytes_atomic``).

    Args:
        path: Target file path.
        text: The file contents.
        encoding: Text encoding.

    Raises:
        PermissionError: The target stayed locked through every try.
    """
    write_bytes_atomic(path, text.encode(encoding))


def write_bytes_atomic(path, data: bytes) -> None:
    """Write a file so readers see the old file or the new one, never half of one.

    The bytes go to a temporary file next to the target, which then replaces the target in one step (see the
    module docstring). On Windows a virus scanner / cloud sync may hold the target briefly, so the replace is
    tried 5 times; the temporary file is removed on any failure.

    Args:
        path: Target file path.
        data: The file contents.

    Raises:
        PermissionError: The target stayed locked through every try.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):  # Windows: a virus scanner / cloud sync may hold the target briefly
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path) -> dict | None:
    """Read the JSON in a file.

    Args:
        path: File path.

    Returns:
        The parsed JSON, or None when it is missing, cut off or not JSON (e.g. a cache from a crash).
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def workers(wanted: int) -> int:
    """Choose how many worker processes to use: at most `wanted`, and one core left for the window.

    Args:
        wanted: Number of workers wanted.

    Returns:
        Number of workers, at least 1.
    """
    return max(1, min(wanted, (os.cpu_count() or 2) - 1))


def process_pool(max_workers: int):
    """Create a process pool whose workers are started fresh ("spawn"; see the module docstring).

    Args:
        max_workers: Number of worker processes.

    Returns:
        A concurrent.futures.ProcessPoolExecutor.
    """
    from concurrent.futures import ProcessPoolExecutor

    return ProcessPoolExecutor(max_workers=max_workers, mp_context=multiprocessing.get_context("spawn"))
