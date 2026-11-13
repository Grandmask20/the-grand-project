"""Offline checks for safe saving and damaged caches (no screenshots needed).   py test_atlas_io.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program"))
import atlas_builder as builder  # noqa: E402
import atlas_builder_core as core  # noqa: E402
import atlas_io  # noqa: E402


def test_atomic_write_replaces_and_leaves_no_temp_files():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "atlas.json"
        atlas_io.write_text_atomic(f, '{"v": 1}')
        atlas_io.write_text_atomic(f, '{"v": 2}')
        assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2}
        assert os.listdir(tmp) == ["atlas.json"]


def test_read_json_returns_none_for_cut_off_or_missing_files():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "cut.json"
        bad.write_text('{"nodes": [1, 2', encoding="utf-8")
        assert atlas_io.read_json(bad) is None
        assert atlas_io.read_json(Path(tmp) / "missing.json") is None


def test_atlas_save_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "atlas.json"
        core.Atlas().save(p)
        assert isinstance(core.Atlas.load(p), core.Atlas)


def test_damaged_detection_cache_is_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / "atlas_frames"
        frames.mkdir()
        (frames / "cut.json").write_text("{", encoding="utf-8")
        assert builder.cached_frames(Path(tmp) / "atlas.json") == {}


def test_unreadable_screenshot_gives_a_clear_error():
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "half.png"
        shot.write_bytes(b"\x89PNG not finished")
        try:
            builder.extract_frame_new(shot, Path(tmp) / "cache")
        except ValueError as e:
            assert "not a readable image" in str(e)
        else:
            raise AssertionError("an unreadable screenshot was accepted")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("PASS: safe saving")
