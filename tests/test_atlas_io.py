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


def _cache(folder, name, sha, models):
    """Write a minimal cached detection for one screenshot (no maps) and return its atlas frame entry."""
    d = {
        "name": name,
        "path": f"{name}.png",
        "sha256": sha,
        "width": 1920,
        "height": 1080,
        "nodes": [],
        "edges": [],
        "landmarks": [],
        "icons": [],
        "models": models,
    }
    (folder / f"{sha[:16]}_{builder.NEW_DETECTOR_ID}.json").write_text(json.dumps(d), encoding="utf-8")
    return {"name": name, "sha": sha}


def test_damaged_detection_cache_is_skipped(tmp_path):
    frames = tmp_path / "atlas_frames"
    frames.mkdir()
    placed = {"name": "shot", "sha": "ab" * 32}
    (frames / f"{'ab' * 8}_{builder.NEW_DETECTOR_ID}.json").write_text("{", encoding="utf-8")
    assert builder.cached_frames(tmp_path / "atlas.json", [placed]) == {}


def test_recheck_reads_only_the_placed_screenshots_caches(tmp_path):
    """Re-check reads each placed screenshot's own cache, never every file in the folder (GPT audit)."""
    frames = tmp_path / "atlas_frames"
    frames.mkdir()
    stamp = builder.detector_stamp()
    placed = _cache(frames, "shot", "aa" * 32, stamp)
    _cache(frames, "shot", "bb" * 32, "old-detector")  # same name: a screenshot no longer in the atlas
    _cache(frames, "other", "cc" * 32, stamp)  # not placed
    got = builder.cached_frames(tmp_path / "atlas.json", [placed])
    assert list(got) == ["shot"] and got["shot"].sha == "aa" * 32
    old = _cache(frames, "gone", "dd" * 32, "old-detector")  # only an old result (screenshot can't be re-detected)
    assert "gone" in builder.cached_frames(tmp_path / "atlas.json", [placed, old])


def test_unreadable_screenshot_gives_a_clear_error(tmp_path):
    shot = tmp_path / "half.png"
    shot.write_bytes(b"\x89PNG not finished")
    with pytest.raises(ValueError, match="not a readable image"):
        builder.extract_frame(shot, tmp_path / "cache")


def test_screenshot_without_a_saved_hash_finds_its_cache_by_name(tmp_path):
    """An atlas placed before screenshots kept their hash still gets its icons back on re-check (review)."""
    frames = tmp_path / "atlas_frames"
    frames.mkdir()
    _cache(frames, "old", "ee" * 32, "old-detector")
    _cache(frames, "old", "ff" * 32, builder.detector_stamp())  # same name, fresh: wins
    got = builder.cached_frames(tmp_path / "atlas.json", [{"name": "old"}])
    assert list(got) == ["old"] and got["old"].sha == "ff" * 32


def test_read_screenshot_of_a_missing_or_broken_file_is_none(tmp_path):
    assert core.read_screenshot(tmp_path / "missing.png") is None
    (tmp_path / "broken.png").write_bytes(b"not a picture")
    assert core.read_screenshot(tmp_path / "broken.png") is None
    (tmp_path / "empty.png").write_bytes(b"")
    assert core.read_screenshot(tmp_path / "empty.png") is None


def test_a_screenshot_that_cant_be_read_is_not_kept(tmp_path):
    import cv2
    import numpy as np

    at = core.Atlas()
    shot = tmp_path / "back.png"
    assert at.image(str(shot)) is None  # missing
    cv2.imwrite(str(shot), np.full((1080, 1920, 3), 90, np.uint8))
    img = at.image(str(shot))  # put back: read now, not the missing one remembered
    assert img is not None and img.shape[:2] == (1080, 1920)
