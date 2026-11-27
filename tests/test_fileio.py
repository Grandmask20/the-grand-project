"""Safe file writing when the file is held, and the worker processes (fileio; the basics: test_atlas_io.py)."""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import sys
import threading

import pytest

from grand_project import fileio


def test_write_text_atomic_tries_again_while_the_file_is_held(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    real = os.replace
    tries = []

    def held_twice(src, dst):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError("held by a virus scanner")
        return real(src, dst)

    monkeypatch.setattr(fileio.os, "replace", held_twice)
    monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
    fileio.write_text_atomic(f, "saved")
    assert f.read_text() == "saved" and len(tries) == 3


def test_write_text_atomic_gives_up_and_cleans_up(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    f.write_text("kept")

    def always_held(src, dst):
        raise PermissionError("held")

    monkeypatch.setattr(fileio.os, "replace", always_held)
    monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        fileio.write_text_atomic(f, "lost")
    assert f.read_text() == "kept"
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_files_rewritten_from_several_threads_at_once_are_never_read_half_written(tmp_path, rng, runs):
    # the atlas, the settings and the detection caches are written from the page's requests, the worker and the
    # detection processes at once (two copies of one screenshot share one cache file)
    f = tmp_path / "atlas.json"
    writers, each = rng.randint(2, 6), runs(15)
    texts = {f"{w}-{i}": f"{w}-{i}:" + "x" * rng.randint(10_000, 60_000) for w in range(writers) for i in range(each)}
    # Windows: a file open for reading can't be replaced (the writers' tries would run out); there only the writers
    reading = sys.platform != "win32"
    start = threading.Barrier(writers + reading)
    done = threading.Event()
    seen: list[str] = []
    failed: list[BaseException] = []

    def write(w: int) -> None:
        try:
            start.wait(5)
            for i in range(each):
                fileio.write_text_atomic(f, texts[f"{w}-{i}"])
        except BaseException as exc:  # a writer's error fails the test, not only its thread
            failed.append(exc)

    def read() -> None:
        start.wait(5)
        while not done.is_set():
            with contextlib.suppress(FileNotFoundError):  # (none written yet)
                seen.append(f.read_text())

    threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
    reader = threading.Thread(target=read) if reading else None
    for t in threads + ([reader] if reader else []):
        t.start()
    for t in threads:
        t.join(30)
        assert not t.is_alive(), "a writer did not finish"
    assert not failed, failed
    done.set()
    if reader:
        reader.join(10)
    assert f.read_text() in texts.values()
    assert all(text == texts[text.split(":", 1)[0]] for text in seen), "a reader saw half a file"
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.json"]  # no temporary file left


def test_workers_leave_a_core_free(monkeypatch):
    monkeypatch.setattr(fileio.os, "cpu_count", lambda: 8)
    assert fileio.workers(4) == 4
    assert fileio.workers(16) == 7
    assert fileio.workers(0) == 1
    monkeypatch.setattr(fileio.os, "cpu_count", lambda: None)  # unknown: as if 2
    assert fileio.workers(4) == 1


def test_process_pool_starts_its_workers_fresh():
    with fileio.process_pool(1) as pool:
        assert pool._mp_context.get_start_method() == "spawn"
        assert pool.submit(abs, -3).result(timeout=60) == 3
    assert multiprocessing.get_context("spawn").get_start_method() == "spawn"


def _thread_limits() -> tuple[int, int, str | None]:
    """What a worker process may use (run in it): its share (and OpenCV's threads, but on macOS, whose GCD backend
    reports the CPU count whatever it was told), the largest OpenMP / BLAS pool, OMP_NUM_THREADS."""
    import cv2
    from threadpoolctl import threadpool_info

    share = fileio.thread_share()
    if sys.platform != "darwin":
        assert cv2.getNumThreads() == share
    return share, max(p["num_threads"] for p in threadpool_info()), os.environ.get("OMP_NUM_THREADS")


def test_each_worker_process_uses_only_its_share_of_the_cpu():
    # uncapped, every worker started one thread per CPU: 4 workers detected 2.7x slower (core.constants)
    with fileio.process_pool(2, threads=1) as pool:
        assert pool.submit(_thread_limits).result(timeout=120) == (1, 1, "1")
    with fileio.process_pool(1, threads=2) as pool:
        assert pool.submit(_thread_limits).result(timeout=120) == (2, 2, "2")


def test_a_worker_s_share_is_the_cpus_divided_among_the_workers(monkeypatch):
    monkeypatch.setattr(fileio.os, "cpu_count", lambda: 22)
    assert [fileio.worker_threads(n) for n in (1, 4, 6, 22, 40)] == [22, 5, 3, 1, 1]
    monkeypatch.setattr(fileio.os, "cpu_count", lambda: None)  # unknown: as if 2
    assert fileio.worker_threads(4) == 1
    with fileio.process_pool(4) as pool:  # (no worker started: they start with the first job)
        assert pool._initargs == (1,)
