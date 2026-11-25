"""Screenshots kept safe to delete (app.keeping, core.Atlas.picture): copies in the atlas folder's terrain/, the
detected originals in used/, the pictures read from the copies once a screenshot is gone (user's design, 2026-11-14;
a Reddit player's question, 2026-11-25)."""

import threading
from pathlib import Path

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
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.png.webp").exists()  # the 1080p copy
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
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.png.webp").exists()
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
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.png.webp").exists()  # (its copy: harmless, the atlas's own)
    assert (tmp_path / "a.png").exists()  # not moved: that atlas isn't open any more


def test_the_pictures_come_from_the_copy_once_the_screenshot_is_gone(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    shot = session.atlas.frames[0]["path"]
    original = cv2.imread(shot)
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()  # the player deletes it
    fresh = core.Atlas.load(tmp_path / "atlas.json")  # (nothing cached)
    assert fresh.has_picture(shot) and fresh.picture(shot).endswith("a.png.webp")
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
    copy = tmp_path / core.SCREENSHOT_COPIES / "a.png.webp"
    first = copy.stat().st_mtime_ns
    assert session.atlas.write_copy(shot) and copy.stat().st_mtime_ns == first  # (kept, not written again)
    assert not list((tmp_path / core.SCREENSHOT_COPIES).glob("*.tmp"))  # (no half-written file left)


def test_the_keep_prompt_says_what_it_will_do(session, tmp_path):
    info = session.keep_info()
    assert info == {"shots": 1, "copied": 0, "todo": 1, "lost": 0, "move": 1, "mb": 0.8, "seconds": 0}


def test_keeping_copies_of_an_atlas_made_before(session, tmp_path):
    session.run_job([], "keep_all")  # (the prompt's job, run here)
    assert (tmp_path / core.SCREENSHOT_COPIES / "a.png.webp").exists()
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


def gone_mid_way(atlas, monkeypatch):
    """The screenshot is deleted (no copy) between the "picture there?" check and the read (user: aggressive checking
    on files deleted mid detection / Fix seams / Re-check)."""
    monkeypatch.setattr(atlas, "has_picture", lambda path: True)
    monkeypatch.setattr(atlas, "image", lambda path: None)


def test_a_screenshot_deleted_mid_map_image_or_fix_seams_is_left_out(session, monkeypatch):
    gone_mid_way(session.atlas, monkeypatch)
    canvas, _origin = session.atlas.composite()  # (the map image)
    assert canvas is not None
    from grand_project.core import seams

    seams.clean_composite(session.atlas)  # (Fix seams' clean map: crashed on the missing picture)


def test_a_screenshot_deleted_mid_sharp_tile_leaves_a_hole(session, monkeypatch):
    f = session.atlas.frames[0]
    gone_mid_way(session.atlas, monkeypatch)
    out, best = core.build_sharp_tile(
        session.atlas, [core.footprint(session.atlas, f)], 1.0, 0.0, 0.0, 256, lambda f: None, 4
    )
    assert out.shape == (256, 256, 3) and float(best.max()) <= 0  # (nothing from it: the map image fills the hole)


def test_a_new_screenshot_gets_its_copy_before_it_is_placed(session, tmp_path, monkeypatch):
    import types

    from grand_project import builder

    new = tmp_path / "b.png"
    screenshot(new, seed=2)
    seen = []
    monkeypatch.setattr(session, "_detect", lambda paths, what: ([types.SimpleNamespace(path=new)], []))

    def place(atlas, frames, log=None):
        seen.append((tmp_path / core.SCREENSHOT_COPIES / "b.png.webp").exists())
        new.unlink()  # deleted while it is placed: its picture is still there (the copy)
        seen.append(atlas.has_picture(str(new)))
        return 0, ["b"]

    monkeypatch.setattr(builder, "place_frames", place)
    session.run_job([new], "manual")
    assert seen == [True, True]  # (made after the job, there was none: self review)


def test_undo_puts_its_screenshots_back_from_used(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    assert (tmp_path / core.SCREENSHOTS_USED / "a.png").exists()
    with session._lock:
        session._unkeep(list(session.atlas.frames))  # (as Undo does for the screenshots it takes out)
    assert (tmp_path / "a.png").exists() and not (tmp_path / core.SCREENSHOTS_USED / "a.png").exists()


def test_screenshots_sharing_a_stem_get_copies_of_their_own(session, tmp_path):
    atlas = session.atlas
    assert atlas.copy_path(str(tmp_path / "x.png")) != atlas.copy_path(str(tmp_path / "x.jpg"))


def test_the_prompt_counts_only_moves_that_will_happen(session, tmp_path):
    (tmp_path / core.SCREENSHOTS_USED).mkdir()
    screenshot(tmp_path / core.SCREENSHOTS_USED / "a.png", seed=3)  # (its name taken in used/: it stays)
    assert session.keep_info()["move"] == 0


def second_view(session, tmp_path, name: str = "b"):
    """Add a screenshot showing exactly what "a" shows (the same placement), kept in used/ with its copy."""
    f = dict(session.atlas.frames[0], name=name, path=str(tmp_path / core.SCREENSHOTS_USED / f"{name}.png"))
    (tmp_path / core.SCREENSHOTS_USED).mkdir(exist_ok=True)
    screenshot(Path(f["path"]), seed=5)
    session.atlas.frames.append(f)
    session.atlas.write_copy(f["path"])
    return f


def test_a_screenshot_shown_better_by_another_goes_to_dump_and_comes_back_when_that_one_goes(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)  # (b shows nothing a doesn't show at least as centrally)
    session._sort_dump(session.opened)
    dump = tmp_path / core.SCREENSHOTS_DUMP / "b.png"
    assert dump.exists() and session.atlas.frames[1]["path"] == str(dump)  # delete these first (user)
    assert (tmp_path / core.SCREENSHOTS_USED / "a.png").exists()  # (a still shows its spots best)
    del session.atlas.frames[0]  # a taken out (an undo): b shows those spots best again
    session._sort_dump(session.opened)
    assert (tmp_path / core.SCREENSHOTS_USED / "b.png").exists() and not dump.exists()  # (its copy made it possible)


def test_slim_down_removes_the_copies_of_dump_screenshots_only_when_ticked(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    copy_b = tmp_path / core.SCREENSHOT_COPIES / "b.png.webp"
    assert session.slim_info(session.atlas, session.opened)["count"] == 1
    assert session.recheck_info()["slim"]["count"] == 1  # (the Re-check prompt's tick says how many)
    session._slim_down(session.opened)
    assert copy_b.exists()  # (not ticked: nothing removed)
    session.set_ui_settings({"recheck_slim": True})
    session._slim_down(session.opened)
    assert not copy_b.exists() and (tmp_path / core.SCREENSHOT_COPIES / "a.png.webp").exists()


def test_the_re_check_prompt_never_waits_for_a_job_to_count_the_slim_down(session, tmp_path):
    second_view(session, tmp_path)
    holding, go = threading.Event(), threading.Event()

    def job():
        with session._lock:
            holding.set()
            go.wait(10)

    t = threading.Thread(target=job, daemon=True)
    t.start()
    assert holding.wait(10)
    try:
        assert session.recheck_info()["slim"]["count"] == 1  # (answered from the grid while the job holds the lock)
    finally:
        go.set()
        t.join(10)


def test_undo_brings_back_to_used_a_screenshot_the_undone_add_sent_to_dump(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    snapshot = session._snapshot()  # (the atlas before the add: a in used/)
    second_view(session, tmp_path)
    session.atlas.frames.insert(0, session.atlas.frames.pop())  # (b first: it keeps every spot, a shows none better)
    session._remember_add(["b"], snapshot)
    session._sort_dump(session.opened)
    assert (tmp_path / core.SCREENSHOTS_DUMP / "a.png").exists()
    session._run_undo()
    a = next(f for f in session.atlas.frames if f["name"] == "a")
    # (the snapshot named used/a.png from before the add: kept, a stayed in dump/ for good - self review)
    assert a["path"] == str(tmp_path / core.SCREENSHOTS_USED / "a.png") and Path(a["path"]).exists()


def slimmed(session, tmp_path) -> Path:
    """b shown better by a, in dump/ with its copy removed by a ticked slim down; returns the copy's place."""
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    session._sort_dump(session.opened)
    session.set_ui_settings({"recheck_slim": True})
    session._slim_down(session.opened)
    copy_b = tmp_path / core.SCREENSHOT_COPIES / "b.png.webp"
    assert (tmp_path / core.SCREENSHOTS_DUMP / "b.png").exists() and not copy_b.exists()
    return copy_b


def test_a_screenshot_back_from_dump_after_a_slim_down_gets_its_copy_again(session, tmp_path):
    copy_b = slimmed(session, tmp_path)
    del session.atlas.frames[0]  # (a taken out: b shows those spots best again)
    session._sort_dump(session.opened)
    assert (tmp_path / core.SCREENSHOTS_USED / "b.png").exists() and copy_b.exists()  # (used/ stays safe to delete)


def test_a_slimmed_screenshot_gone_for_good_is_no_missing_terrain_warning(session, tmp_path):
    slimmed(session, tmp_path)
    (tmp_path / core.SCREENSHOTS_DUMP / "b.png").unlink()  # (the player deleted dump/)
    path = session.path
    session.open_atlas(path)  # (opened again)
    t = getattr(session, "_lock_thread", None)
    if t:
        t.join(60)
    lines = list(session.events.log_lines)
    assert any("slimmed down" in line for line in lines)
    assert not any("screenshots not found" in line for line in lines)
