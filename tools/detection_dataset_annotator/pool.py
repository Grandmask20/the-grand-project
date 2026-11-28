"""Detection in worker processes: the classical detector is CPU-heavy and would starve the Streamlit server.

Each worker is ``python -m tools.detection_dataset_annotator.worker`` started from the project folder (as the
viewer starts ``grand_project.core.seams``), so it imports the project like any other ``python -m`` run (not
``multiprocessing``: spawn would re-run Streamlit's script). Workers read one JSON request per line and answer with
one JSON line per screenshot, in order (see ``worker.py``).

The pool is one asyncio task per worker, run with ``asyncio.run`` from the Streamlit script thread. All tasks take
screenshots from one queue; only the event-loop thread touches it and the review store's connection (the thread that
opened it), so no locks are needed. Each answer is committed to the store as it arrives, so a stopped run keeps every
screenshot it finished. The speed comes from the processes, not from asyncio: each worker is given its share of the
CPU's threads (OpenMP and BLAS included) and is kept ``ANNOTATOR_WORKER_IN_FLIGHT`` requests ahead, so it never waits
for the annotator.
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
from typing import TYPE_CHECKING, Any

from grand_project import paths

from . import constants as K
from .state import DetectionOptions

if TYPE_CHECKING:
    from .store import ReviewStore

Progress = Callable[[int, int, str], None]
"""Called with (finished, total, screenshot path) after each screenshot."""

Job = tuple[str, str, int]
"""A screenshot's key, path and review generation when it was queued (``ReviewStore.detection_jobs``)."""


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
    """Bookkeeping of one ``detect_pending`` call: results are written to the store as they arrive."""

    store: ReviewStore
    pending: deque[Job]
    force: bool
    progress: Progress | None
    total: int = 0
    completed: int = 0
    errors: int = 0
    removed: int = 0
    """Screenshots taken out of the store (a rebuild removing copies) while they were being detected."""
    interrupt: BaseException | None = None

    def succeed(self, job: Job, result: dict[str, Any]) -> None:
        # The store raises the screenshot's revision: the editor remounts and shows these detections instead of
        # autosaving old boxes over them.
        try:
            self.store.record_detection(job[0], result, force=self.force, generation=job[2])
        except KeyError:
            if not self._gone(job):
                raise
            return
        self.completed += 1
        self._report(job)

    def fail(self, job: Job, error: str) -> None:
        try:
            self.store.record_failure(job[0], error, force=self.force, generation=job[2])
        except KeyError:
            if not self._gone(job):
                raise
            return
        self.errors += 1
        self._report(job)

    def _gone(self, job: Job) -> bool:
        """Whether the job's screenshot left the store meanwhile (then it is skipped and counted); a KeyError for a
        screenshot still there is no such case, and its caller raises it again."""
        if self.store.item(job[0]) is not None:
            return False
        self.removed += 1
        self._report(job)
        return True

    def fail_remaining(self, error: str) -> None:
        while self.pending:
            self.fail(self.pending.popleft(), error)

    def _report(self, job: Job) -> None:
        if not self.progress:
            return
        try:
            self.progress(self.completed + self.errors + self.removed, self.total, job[1])
        except BaseException as exc:
            # Streamlit's stop / rerun signals are BaseExceptions, which asyncio lets out of the event loop at once,
            # skipping the other workers' cleanup. Kept here and raised again once every worker is stopped.
            self.interrupt = exc
            raise _Interrupted from exc

    def receive(self, job: Job, line: str) -> None:
        """Apply one worker answer to its screenshot."""
        key = job[0]
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("worker answer is not a JSON object")
            if message.get("key") != key:
                raise ValueError(f"worker returned unexpected image key {message.get('key')!r}")
            if message.get("error"):
                self.fail(job, str(message["error"]))
            elif isinstance(message.get("result"), dict):
                self.succeed(job, message["result"])
            else:
                raise ValueError("worker returned neither a result nor an error")
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            self.fail(job, f"Invalid detection worker response: {exc}")


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
        # input b"": stdin is closed (EOF ends the worker's loop) on Python 3.11 too; communicate() alone closes it
        # only from 3.12
        await asyncio.wait_for(process.communicate(b""), K.ANNOTATOR_WORKER_EXIT_S)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.communicate()


async def _send(process: asyncio.subprocess.Process, job: Job, settings: dict) -> str | None:
    """Write one request to the worker; return the error when it cannot be sent.

    Raises:
        TimeoutError: the worker took no input for ``ANNOTATOR_WORKER_ANSWER_S`` (stuck: its pipe stays full).
    """
    if process.stdin is None:
        return "Detection worker input was unavailable."
    key, path, _generation = job
    request = {"key": key, "path": path, **settings}
    try:
        process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await asyncio.wait_for(process.stdin.drain(), K.ANNOTATOR_WORKER_ANSWER_S)
    except TimeoutError:
        raise  # a stuck worker (TimeoutError is an OSError): the driver stops it, it is no broken pipe
    except (ConnectionError, OSError) as exc:  # BrokenPipeError / ConnectionResetError: the worker is gone
        return f"Could not send screenshot to detection worker: {exc}"
    return None


async def _drive_worker(run: _Run, options: DetectionOptions, process: asyncio.subprocess.Process) -> None:
    """Feed one worker from the shared queue until it is empty, applying each answer as it arrives; then stop it."""
    settings = options.as_settings()
    in_flight: deque[Job] = deque()  # sent, not answered yet; the worker answers in order
    accepting = True
    graceful = False
    stuck = False  # it missed an answer's deadline: terminated, not waited on
    try:
        while True:
            while accepting and run.pending and len(in_flight) < K.ANNOTATOR_WORKER_IN_FLIGHT:
                job = run.pending.popleft()
                try:
                    error = await _send(process, job, settings)
                except TimeoutError:  # stuck reading: its screenshots fail (retryable), it is stopped, not waited on
                    error = f"Detection worker took no input within {K.ANNOTATOR_WORKER_ANSWER_S:g} s; it was stopped."
                    run.fail(job, error)
                    while in_flight:
                        run.fail(in_flight.popleft(), error)
                    stuck = True
                    break
                if error is None:
                    in_flight.append(job)
                else:
                    run.fail(job, error)
                    accepting = False  # read what was already sent, then stop
            if stuck or not in_flight:
                break
            try:
                line = await asyncio.wait_for(process.stdout.readline(), K.ANNOTATOR_WORKER_ANSWER_S)
            except ValueError as exc:  # longer than ANNOTATOR_WORKER_LINE_LIMIT: the stream is out of step
                while in_flight:
                    run.fail(in_flight.popleft(), f"Detection worker answer could not be read: {exc}")
                break
            except TimeoutError:  # stuck: its screenshots fail (retryable), it is stopped, the other workers go on
                while in_flight:
                    error = f"Detection worker did not answer within {K.ANNOTATOR_WORKER_ANSWER_S:g} s; it was stopped."
                    run.fail(in_flight.popleft(), error)
                stuck = True
                break
            if not line:  # end of output: the worker exited
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), K.ANNOTATOR_WORKER_EXIT_S)
                while in_flight:
                    error = f"Detection worker exited unexpectedly (code {process.returncode})."
                    run.fail(in_flight.popleft(), error)
                break
            run.receive(in_flight.popleft(), line.decode("utf-8", errors="replace"))
        graceful = not stuck  # a healthy worker ends at EOF; a stuck one would only make the run wait
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
    store: ReviewStore,
    options: DetectionOptions,
    *,
    keys: Iterable[str] | None = None,
    force: bool = False,
    max_workers: int | None = None,
    progress: Progress | None = None,
) -> tuple[int, int]:
    """Detect the selected screenshots of the store in worker processes, saving each result as it arrives.

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
    if force and keys is None:
        raise ValueError("Forced detection requires explicit image keys")
    run = _Run(store=store, pending=deque(store.detection_jobs(keys, force=force)), force=force, progress=progress)
    run.total = len(run.pending)
    store.set_settings(options)
    if not run.total:
        return 0, 0
    try:
        asyncio.run(_detect_all(run, options, min(max_workers, run.total)))
    except BaseExceptionGroup as group:
        # Raise the original exception, not the TaskGroup's wrapper: Streamlit must see its own stop / rerun signal,
        # and the caller a worker that could not start.
        raise (run.interrupt or _first_error(group)) from None
    left = "All detection workers stopped before this screenshot was processed."
    try:
        run.fail_remaining(left)
    except _Interrupted:
        # the page's stop / rerun signal came from a progress report: the rest are failed unreported, then it goes on
        run.progress = None
        run.fail_remaining(left)
        raise run.interrupt from None
    return run.completed, run.errors
