"""Safe file writing when the file is held, and the worker processes (fileio; the basics: test_atlas_io.py)."""

from __future__ import annotations

import multiprocessing
import os

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
