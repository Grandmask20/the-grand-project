"""Screenshots kept safe to delete (app.keeping, core.Atlas.picture): copies in the atlas folder's terrain/, the
detected originals in used/, the pictures read from the copies once a screenshot is gone (user's design, 2026-11-14;
a Reddit player's question, 2026-11-25)."""

import cv2
import numpy as np
import pytest

from grand_project import cities, core
from grand_project.app.session import AtlasSession
from grand_project.finalize import traces
from tests.webmap_data import make_atlas


def screenshot(path, seed: int = 1) -> np.ndarray:
    """Write a 1920 x 1080 screenshot (soft noise, like ground) and return its pixels."""
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (1080, 1920, 3)).astype(np.uint8), (0, 0), 3)
    cv2.imwrite(str(path), img)
    return img


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    s = AtlasSession(settings={}, worker=False)
    path, _pts, _img = make_atlas(tmp_path)
    screenshot(tmp_path / "a.png")  # (the atlas's one screenshot, in its own folder)
    s.open_atlas(path)
    t = getattr(s, "_lock_thread", None)
    if t:
        t.join(60)
    yield s
    s.shutdown()


def test_a_detected_screenshot_in_the_atlas_folder_is_copied_then_moved_to_used(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.webp").exists()  # the 1080p copy
    used = tmp_path / core.SCREENSHOTS_USED / "a.png"
    assert used.exists() and not (tmp_path / "a.png").exists()  # the original, safe to delete now
    assert session.atlas.frames[0]["path"] == str(used)
    again = core.Atlas.load(tmp_path / "atlas.json")  # (saved with its new place)
    assert again.frames[0]["path"] == str(used)


def test_a_screenshot_outside_the_atlas_folder_is_copied_but_never_moved(session, tmp_path):
    steam = tmp_path / "steam"
    steam.mkdir()
    (tmp_path / "a.png").rename(steam / "a.png")
    session.atlas.frames[0]["path"] = str(steam / "a.png")
    session._keep_screenshots(session.opened, ["a"])
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.webp").exists()
    assert (steam / "a.png").exists() and session.atlas.frames[0]["path"] == str(steam / "a.png")  # (user's rule)


def test_nothing_is_moved_for_an_atlas_closed_meanwhile(session, tmp_path):
    rec = session.opened
    (tmp_path / "other").mkdir()
    other, _pts, _img = make_atlas(tmp_path / "other")
    real = rec.atlas.write_copy

    def copy_then_switch(path):
        ok = real(path)
        session.open_atlas(other)  # another atlas opened while the copies were made
        return ok

    rec.atlas.write_copy = copy_then_switch
    session._keep_screenshots(rec, ["a"])
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.webp").exists()  # (its copy: harmless, the atlas's own)
    assert (tmp_path / "a.png").exists()  # not moved: that atlas isn't open any more


def test_the_pictures_come_from_the_copy_once_the_screenshot_is_gone(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    shot = session.atlas.frames[0]["path"]
    original = cv2.imread(shot)
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()  # the player deletes it
    fresh = core.Atlas.load(tmp_path / "atlas.json")  # (nothing cached)
    assert fresh.has_picture(shot) and fresh.picture(shot).endswith("a.webp")
    img = fresh.image(shot)
    assert img is not None and img.shape == original.shape
    assert float(np.abs(img.astype(int) - original.astype(int)).mean()) < 6  # (WebP at quality 90: ~3 / 255)
    # the map image built again still has its ground (it was lost before: the player's question)
    canvas, _origin, weight = fresh.composite(with_weight=True)
    assert canvas is not None and float((weight > 0).mean()) > 0.5


def test_a_screenshot_with_no_picture_left_is_skipped_by_the_path_check(session, tmp_path):
    f = session.atlas.frames[0]
    (tmp_path / "a.png").unlink()  # gone, and no copy was kept
    assert not session.atlas.has_picture(f["path"])
    assert traces._dashes(session.atlas, f) is None  # (the path detector crashed on a missing picture)
    sp, ok, tower = np.zeros((2, 2)), np.array([True, True]), np.array([False, False])
    assert traces._trace_views(session.atlas, [(f, sp, ok)], tower) == [(f, sp, ok, {})]


def test_an_atlas_finds_its_screenshots_in_used_after_a_move_it_didnt_save(tmp_path):
    (tmp_path / core.SCREENSHOTS_USED).mkdir()
    screenshot(tmp_path / core.SCREENSHOTS_USED / "b.png")
    gone = str(tmp_path / "elsewhere" / "b.png")  # (the place the atlas file still names)
    assert core.find_screenshot(gone, tmp_path) == str(tmp_path / core.SCREENSHOTS_USED / "b.png")


def test_copies_are_written_whole_and_only_once(session, tmp_path):
    shot = session.atlas.frames[0]["path"]
    assert session.atlas.write_copy(shot)
    copy = tmp_path / core.SCREENSHOT_COPIES / "a.webp"
    first = copy.stat().st_mtime_ns
    assert session.atlas.write_copy(shot) and copy.stat().st_mtime_ns == first  # (kept, not written again)
    assert not list((tmp_path / core.SCREENSHOT_COPIES).glob("*.tmp"))  # (no half-written file left)


def test_the_keep_prompt_says_what_it_will_do(session, tmp_path):
    info = session.keep_info()
    assert info == {"shots": 1, "copied": 0, "todo": 1, "lost": 0, "move": 1, "mb": 0.8, "seconds": 0}


def test_keeping_copies_of_an_atlas_made_before(session, tmp_path):
    session.run_job([], "keep_all")  # (the prompt's job, run here)
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.webp").exists()
    assert (tmp_path / core.SCREENSHOTS_USED / "a.png").exists()
    assert session.keep_info() | {"seconds": 0} == {
        "shots": 1, "copied": 1, "todo": 0, "lost": 0, "move": 0, "mb": 0.0, "seconds": 0,
    }  # fmt: skip
    assert any("copies kept of 1 screenshot" in line for line in session.events.log_lines)


def test_a_screenshot_gone_before_its_copy_was_kept_is_counted_as_lost(session, tmp_path):
    (tmp_path / "a.png").unlink()
    info = session.keep_info()
    assert info["lost"] == 1 and info["todo"] == 0 and info["move"] == 0


def test_a_deleted_screenshot_keeps_its_time_for_oldest_to_newest_and_the_timelapse(session, tmp_path):
    # (a screenshot without a Steam name: its time came from its file, lost with it; "times seen" counts places only)
    taken = core.capture_time(session.atlas.frames[0])
    session._keep_screenshots(session.opened, ["a"])
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()
    fresh = core.Atlas.load(tmp_path / "atlas.json")
    assert core.capture_time(fresh.frames[0]) == pytest.approx(taken)
