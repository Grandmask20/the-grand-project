"""Offline checks for safe saving and damaged caches (no screenshots needed).   pytest tests/test_atlas_io.py"""

import json
import os

import pytest

from grand_project import builder, core
from grand_project import fileio as atlas_io


def test_atomic_write_replaces_and_leaves_no_temp_files(tmp_path):
    f = tmp_path / "atlas.json"
    atlas_io.write_text_atomic(f, '{"v": 1}')
    atlas_io.write_text_atomic(f, '{"v": 2}')
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2}
    assert os.listdir(tmp_path) == ["atlas.json"]


def test_read_json_returns_none_for_cut_off_or_missing_files(tmp_path):
    bad = tmp_path / "cut.json"
    bad.write_text('{"nodes": [1, 2', encoding="utf-8")
    assert atlas_io.read_json(bad) is None
    assert atlas_io.read_json(tmp_path / "missing.json") is None


def test_atlas_save_roundtrip(tmp_path):
    p = tmp_path / "atlas.json"
    core.Atlas().save(p)
    assert isinstance(core.Atlas.load(p), core.Atlas)


def test_damaged_detection_cache_is_skipped(tmp_path):
    frames = tmp_path / "atlas_frames"
    frames.mkdir()
    (frames / "cut.json").write_text("{", encoding="utf-8")
    assert builder.cached_frames(tmp_path / "atlas.json") == {}


def test_unreadable_screenshot_gives_a_clear_error(tmp_path):
    shot = tmp_path / "half.png"
    shot.write_bytes(b"\x89PNG not finished")
    with pytest.raises(ValueError, match="not a readable image"):
        builder.extract_frame(shot, tmp_path / "cache")
