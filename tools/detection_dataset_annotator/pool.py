"""Detection in worker processes: the classical detector is CPU-heavy and would starve the Streamlit server.

Each worker is ``python -m tools.detection_dataset_annotator.worker`` started from the project folder (as the
viewer starts ``grand_project.core.seams``), so it imports the project like any other ``python -m`` run. Workers
read one JSON request per line and answer with one JSON line per screenshot (see ``worker.py``).
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from grand_project import paths

from . import constants as K
from .state import DetectionOptions

Progress = Callable[[int, int, str], None]
"""Called with (finished, total, screenshot path) after each screenshot."""

_Output = queue.Queue[tuple[subprocess.Popen[str], str | None]]
"""Worker output lines; ``None`` marks a worker whose output ended."""


@dataclass
class _Worker:
    """One detector process and the thread forwarding its output."""

    process: subprocess.Popen[str]
    reader: threading.Thread


def _forward_output(process: subprocess.Popen[str], output: _Output) -> None:
    """Forward a worker's output lines, so the Streamlit thread can wait on all workers and show progress."""
    try:
        for line in process.stdout or ():
            output.put((process, line))
    finally:
        output.put((process, None))


def _start_worker(output: _Output, opencv_threads: int) -> _Worker:
    """Start one detector process."""
    environment = {**os.environ, K.ANNOTATOR_OPENCV_THREADS_ENV: str(opencv_threads)}
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", K.ANNOTATOR_WORKER_MODULE],
        cwd=paths.ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    reader = threading.Thread(
        target=_forward_output, args=(process, output), name=f"annotator-worker-{process.pid}", daemon=True
    )
    reader.start()
    return _Worker(process, reader)


def _stop_workers(workers: Iterable[_Worker]) -> None:
    """Close every worker's input and reap it, terminating only workers that do not exit."""
    workers = list(workers)
    for worker in workers:
        if worker.process.stdin is not None and not worker.process.stdin.closed:
            with contextlib.suppress(OSError):
                worker.process.stdin.close()
    for worker in workers:
        try:
            worker.process.wait(timeout=K.ANNOTATOR_WORKER_EXIT_S)
        except subprocess.TimeoutExpired:
            worker.process.terminate()
            try:
                worker.process.wait(timeout=K.ANNOTATOR_WORKER_EXIT_S / 2)
            except subprocess.TimeoutExpired:
                worker.process.kill()
                worker.process.wait()
    for worker in workers:
        worker.reader.join(timeout=2)


@contextlib.contextmanager
def _worker_pool(count: int, output: _Output) -> Iterator[list[_Worker]]:
    """Start ``count`` workers sharing the CPU's OpenCV threads; every started worker is stopped on exit."""
    opencv_threads = max(1, (os.cpu_count() or 1) // max(1, count))
    workers: list[_Worker] = []
    try:
        for _ in range(count):
            try:
                workers.append(_start_worker(output, opencv_threads))
            except OSError as exc:
                raise RuntimeError(f"Could not start a detection worker: {exc}") from exc
        yield list(workers)
    finally:
        _stop_workers(workers)


@dataclass
class _Run:
    """Bookkeeping of one ``detect_pending`` call: results are written into the state items as they arrive."""

    pending: deque[tuple[str, dict[str, Any]]]
    force: bool
    progress: Progress | None
    total: int = 0
    completed: int = 0
    errors: int = 0
    active: dict[subprocess.Popen[str], tuple[str, dict[str, Any]]] = field(default_factory=dict)

    def succeed(self, item: dict[str, Any], result: dict[str, Any]) -> None:
        item.update(result)
        # A new revision remounts the editor, so it shows these detections instead of autosaving old boxes.
        item["edit_version"] = int(item.get("edit_version", 0)) + 1
        if self.force:
            item["reviewed"] = False
        self.completed += 1
        self._report(item)

    def fail(self, item: dict[str, Any], error: str) -> None:
        if self.force and item.get("detected"):
            item["error"] = f"Rerun failed; kept previous detections. {error}"
        else:
            item.update({"detected": False, "error": error})
        self.errors += 1
        self._report(item)

    def fail_remaining(self, error: str) -> None:
        while self.pending:
            _key, item = self.pending.popleft()
            self.fail(item, error)

    def _report(self, item: dict[str, Any]) -> None:
        if self.progress:
            self.progress(self.completed + self.errors, self.total, str(item["path"]))

    def dispatch(self, process: subprocess.Popen[str], options: DetectionOptions) -> None:
        """Send the next screenshot to an idle worker."""
        if not self.pending or process.poll() is not None:
            return
        key, item = self.pending.popleft()
        if process.stdin is None:
            self.fail(item, "Detection worker input was unavailable.")
            return
        self.active[process] = (key, item)
        request = {"key": key, "path": item["path"], **options.as_settings()}
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except OSError as exc:
            self.active.pop(process, None)
            self.fail(item, f"Could not send screenshot to detection worker: {exc}")

    def receive(self, key: str, item: dict[str, Any], line: str) -> None:
        """Apply one worker answer to its screenshot."""
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("worker answer is not a JSON object")
            if message.get("key") != key:
                raise ValueError(f"worker returned unexpected image key {message.get('key')!r}")
            if message.get("error"):
                self.fail(item, str(message["error"]))
            elif isinstance(message.get("result"), dict):
                self.succeed(item, message["result"])
            else:
                raise ValueError("worker returned neither a result nor an error")
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            self.fail(item, f"Invalid detection worker response: {exc}")


def detect_pending(
    state: dict[str, Any],
    options: DetectionOptions,
    *,
    keys: Iterable[str] | None = None,
    force: bool = False,
    max_workers: int = K.ANNOTATOR_DEFAULT_WORKERS,
    progress: Progress | None = None,
) -> tuple[int, int]:
    """Detect the selected screenshots in worker processes, applying each result as it arrives.

    Without ``keys`` every screenshot not detected yet runs. ``force`` reruns detected ones too and needs explicit
    keys, so a caller cannot replace every annotation in the dataset by accident. A failed rerun keeps the
    screenshot's previous boxes and review flag.

    Returns:
        (completed, failed) screenshot counts.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    selected = set(keys) if keys is not None else None
    if force and selected is None:
        raise ValueError("Forced detection requires explicit image keys")
    run = _Run(
        pending=deque(
            (key, item)
            for key, item in state.get("images", {}).items()
            if (selected is None or key in selected) and (force or not item.get("detected"))
        ),
        force=force,
        progress=progress,
    )
    run.total = len(run.pending)
    state["settings"] = options.as_settings()
    if not run.total:
        return 0, 0

    output: _Output = queue.Queue()
    with _worker_pool(min(max_workers, run.total), output) as workers:
        running = {worker.process for worker in workers}
        for process in running:
            run.dispatch(process, options)
        while run.active or run.pending:
            if not running:
                run.fail_remaining("All detection workers stopped before this screenshot was processed.")
                break
            try:
                process, line = output.get(timeout=K.ANNOTATOR_WORKER_POLL_S)
            except queue.Empty:
                continue
            record = run.active.pop(process, None)
            if line is None:  # the worker's output ended: it exited
                running.discard(process)
                if record is not None:
                    run.fail(record[1], f"Detection worker exited unexpectedly (code {process.poll()}).")
                continue
            if record is not None:
                run.receive(*record, line)
                run.dispatch(process, options)
    return run.completed, run.errors
