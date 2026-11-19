"""Detection in worker processes: the classical detector is CPU-heavy and would starve the Streamlit server.

Each worker is ``python -m tools.detection_dataset_annotator.worker`` started from the project folder (as the
viewer starts ``grand_project.core.seams``), so it imports the project like any other ``python -m`` run (not
``multiprocessing``: spawn would re-run Streamlit's script). Workers read one JSON request per line and answer with
one JSON line per screenshot, in order (see ``worker.py``).

The pool is one asyncio task per worker, run with ``asyncio.run`` from the Streamlit script thread. All tasks take
screenshots from one queue; only the event-loop thread touches it and the review state, so no locks are needed. The
speed comes from the processes, not from asyncio: each worker is given its share of the CPU's threads (OpenMP and
BLAS included) and is kept ``ANNOTATOR_WORKER_IN_FLIGHT`` requests ahead, so it never waits for the annotator.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from grand_project import paths

from . import constants as K
from .state import DetectionOptions

Progress = Callable[[int, int, str], None]
"""Called with (finished, total, screenshot path) after each screenshot."""

Job = tuple[str, dict[str, Any]]
"""A screenshot's key and its review-state item."""


def cpu_count() -> int:
    """CPUs this process may use (its affinity where the platform tells it)."""
    process_cpu_count = getattr(os, "process_cpu_count", None)  # Python 3.13+
    if process_cpu_count is not None:
        return process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def _total_memory_gb() -> float | None:
    """Physical memory in GB, or None where ``os.sysconf`` cannot tell (Windows)."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (AttributeError, ValueError, OSError):
        return None


def default_workers() -> int:
    """Worker processes to start by default: every CPU but a few, as many as the memory holds."""
    memory = _total_memory_gb()
    by_memory = int(memory // K.ANNOTATOR_WORKER_MEMORY_GB) if memory is not None else K.ANNOTATOR_WORKER_FALLBACK
    cpus = cpu_count()
    return max(1, min(cpus - K.ANNOTATOR_WORKER_RESERVED_CPUS, by_memory, cpus))


def _worker_env(threads: int) -> dict[str, str]:
    """The worker's environment: every thread pool (OpenCV, OpenMP, BLAS) limited to its share of the CPU."""
    limits = dict.fromkeys((K.ANNOTATOR_OPENCV_THREADS_ENV, *K.ANNOTATOR_THREAD_ENV_VARS), str(threads))
    return {**os.environ, **limits}


class _Interrupted(Exception):
    """The progress callback raised: stops the TaskGroup the ordinary way (see ``_Run._report``)."""


@dataclass
class _Run:
    """Bookkeeping of one ``detect_pending`` call: results are written into the state items as they arrive."""

    pending: deque[Job]
    force: bool
    progress: Progress | None
    total: int = 0
    completed: int = 0
    errors: int = 0
    interrupt: BaseException | None = None

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
        if not self.progress:
            return
        try:
            self.progress(self.completed + self.errors, self.total, str(item["path"]))
        except BaseException as exc:
            # Streamlit's stop / rerun signals are BaseExceptions, which asyncio lets out of the event loop at once,
            # skipping the other workers' cleanup. Kept here and raised again once every worker is stopped.
            self.interrupt = exc
            raise _Interrupted from exc

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


async def _start_worker(threads: int) -> asyncio.subprocess.Process:
    """Start one detector process (the module is read live, so tests can swap in a fake worker)."""
    try:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-m",
            K.ANNOTATOR_WORKER_MODULE,
            cwd=paths.ROOT,
            env=_worker_env(threads),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            limit=K.ANNOTATOR_WORKER_LINE_LIMIT,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start a detection worker: {exc}") from exc


async def _stop_worker(process: asyncio.subprocess.Process, *, graceful: bool) -> None:
    """Close the worker's input and reap it, killing it when it does not exit; ``graceful=False`` terminates it first.

    ``communicate`` also reads the output to its end, so the pipes are closed before the event loop is.
    """
    if not graceful and process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
    try:
        await asyncio.wait_for(process.communicate(), K.ANNOTATOR_WORKER_EXIT_S)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.communicate()


async def _send(process: asyncio.subprocess.Process, key: str, item: dict[str, Any], settings: dict) -> str | None:
    """Write one request to the worker; return the error when it cannot be sent."""
    if process.stdin is None:
        return "Detection worker input was unavailable."
    request = {"key": key, "path": item["path"], **settings}
    try:
        process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await process.stdin.drain()
    except (ConnectionError, OSError) as exc:  # BrokenPipeError / ConnectionResetError: the worker is gone
        return f"Could not send screenshot to detection worker: {exc}"
    return None


async def _drive_worker(run: _Run, options: DetectionOptions, process: asyncio.subprocess.Process) -> None:
    """Feed one worker from the shared queue until it is empty, applying each answer as it arrives; then stop it."""
    settings = options.as_settings()
    in_flight: deque[Job] = deque()  # sent, not answered yet; the worker answers in order
    accepting = True
    graceful = False
    try:
        while True:
            while accepting and run.pending and len(in_flight) < K.ANNOTATOR_WORKER_IN_FLIGHT:
                key, item = run.pending.popleft()
                error = await _send(process, key, item, settings)
                if error is None:
                    in_flight.append((key, item))
                else:
                    run.fail(item, error)
                    accepting = False  # read what was already sent, then stop
            if not in_flight:
                break
            try:
                line = await asyncio.wait_for(process.stdout.readline(), K.ANNOTATOR_WORKER_ANSWER_S)
            except ValueError as exc:  # longer than ANNOTATOR_WORKER_LINE_LIMIT: the stream is out of step
                while in_flight:
                    run.fail(in_flight.popleft()[1], f"Detection worker answer could not be read: {exc}")
                break
            except TimeoutError:  # stuck: its screenshots fail (retryable), it is stopped, the other workers go on
                while in_flight:
                    error = f"Detection worker did not answer within {K.ANNOTATOR_WORKER_ANSWER_S:g} s; it was stopped."
                    run.fail(in_flight.popleft()[1], error)
                break
            if not line:  # end of output: the worker exited
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), K.ANNOTATOR_WORKER_EXIT_S)
                while in_flight:
                    error = f"Detection worker exited unexpectedly (code {process.returncode})."
                    run.fail(in_flight.popleft()[1], error)
                break
            key, item = in_flight.popleft()
            run.receive(key, item, line.decode("utf-8", errors="replace"))
        graceful = True
    finally:
        await _stop_worker(process, graceful=graceful)


async def _detect_all(run: _Run, options: DetectionOptions, workers: int) -> None:
    """Run ``workers`` workers over the queue together."""
    threads = max(1, cpu_count() // workers)
    processes: list[asyncio.subprocess.Process] = []
    try:
        # Every worker starts before any task runs, so a stop can never come between starting a process and
        # handing it to the task that stops it.
        for _ in range(workers):
            processes.append(await _start_worker(threads))
        async with asyncio.TaskGroup() as group:
            for process in processes:
                group.create_task(_drive_worker(run, options, process))
    except BaseException:
        for process in processes:
            if process.returncode is None:
                await _stop_worker(process, graceful=False)
        raise


def _first_error(group: BaseExceptionGroup) -> BaseException:
    """The first exception inside a (nested) exception group."""
    first = group.exceptions[0]
    return _first_error(first) if isinstance(first, BaseExceptionGroup) else first


def detect_pending(
    state: dict[str, Any],
    options: DetectionOptions,
    *,
    keys: Iterable[str] | None = None,
    force: bool = False,
    max_workers: int | None = None,
    progress: Progress | None = None,
) -> tuple[int, int]:
    """Detect the selected screenshots in worker processes, applying each result as it arrives.

    Without ``keys`` every screenshot not detected yet runs. ``force`` reruns detected ones too and needs explicit
    keys, so a caller cannot replace every annotation in the dataset by accident. A failed rerun keeps the
    screenshot's previous boxes and review flag. ``max_workers`` defaults to ``default_workers()``.

    Returns:
        (completed, failed) screenshot counts.
    """
    if max_workers is None:
        max_workers = default_workers()
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
    try:
        asyncio.run(_detect_all(run, options, min(max_workers, run.total)))
    except BaseExceptionGroup as group:
        # Raise the original exception, not the TaskGroup's wrapper: Streamlit must see its own stop / rerun signal,
        # and the caller a worker that could not start.
        raise (run.interrupt or _first_error(group)) from None
    run.fail_remaining("All detection workers stopped before this screenshot was processed.")
    return run.completed, run.errors
