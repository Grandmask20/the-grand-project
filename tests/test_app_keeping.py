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


def copy_of(atlas, name: str) -> Path:
    """Where a screenshot of the atlas keeps its copy (terrain/<file name>.<its content's sha>.webp)."""
    return atlas.copy_path(next(f["path"] for f in atlas.frames if f["name"] == name))


def clean_map(session, monkeypatch, owner: str = "a") -> None:
    """A clean map (Fix seams) over the atlas's screenshots in which `owner` shows every spot."""
    names = [f["name"] for f in session.atlas.frames]
    monkeypatch.setattr(session, "labels", (np.full((1080, 1920), names.index(owner), np.int16), names))
    monkeypatch.setattr(session, "terrain", (None, None, (0.0, 0.0, 1.0)))


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
    assert copy_of(session.atlas, "a").exists()  # the 1080p copy
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
    assert copy_of(session.atlas, "a").exists()
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
    assert copy_of(rec.atlas, "a").exists()  # (its copy: harmless, the atlas's own)
    assert (tmp_path / "a.png").exists()  # not moved: that atlas isn't open any more


def test_the_pictures_come_from_the_copy_once_the_screenshot_is_gone(session, tmp_path):
    session._keep_screenshots(session.opened, ["a"])
    shot = session.atlas.frames[0]["path"]
    original = cv2.imread(shot)
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()  # the player deletes it
    fresh = core.Atlas.load(tmp_path / "atlas.json")  # (nothing cached)
    assert fresh.has_picture(shot) and fresh.picture(shot) == str(copy_of(fresh, "a"))
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
    copy = copy_of(session.atlas, "a")
    first = copy.stat().st_mtime_ns
    assert session.atlas.write_copy(shot) and copy.stat().st_mtime_ns == first  # (kept, not written again)
    assert not list((tmp_path / core.SCREENSHOT_COPIES).glob("*.tmp"))  # (no half-written file left)


def test_the_keep_prompt_says_what_it_will_do(session, tmp_path):
    info = session.keep_info()
    assert info == {"shots": 1, "copied": 0, "todo": 1, "lost": 0, "move": 1, "mb": 0.8, "seconds": 0}


def test_keeping_copies_of_an_atlas_made_before(session, tmp_path):
    session.run_job([], "keep_all")  # (the prompt's job, run here)
    assert copy_of(session.atlas, "a").exists()
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


def test_slim_down_removes_the_copies_of_dump_screenshots_only_when_ticked(session, tmp_path, monkeypatch):
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    clean_map(session, monkeypatch)
    copy_b = copy_of(session.atlas, "b")
    assert session.slim_info(session.atlas, session.opened)["count"] == 1
    assert session.recheck_info()["slim"]["count"] == 1  # (the Re-check prompt's tick says how many)
    session._slim_down(session.opened)
    assert copy_b.exists()  # (not ticked: nothing removed)
    session.set_ui_settings({"recheck_slim": True})
    session._slim_down(session.opened)
    assert not copy_b.exists() and copy_of(session.atlas, "a").exists()


def test_the_re_check_prompt_never_waits_for_a_job_to_count_the_slim_down(session, tmp_path, monkeypatch):
    second_view(session, tmp_path)
    clean_map(session, monkeypatch)
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


def slimmed(session, tmp_path, monkeypatch) -> Path:
    """b shown better by a, in dump/ with its copy removed by a ticked slim down; returns the copy's place."""
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    session._sort_dump(session.opened)
    clean_map(session, monkeypatch)
    session.set_ui_settings({"recheck_slim": True})
    copy_b = copy_of(session.atlas, "b")
    session._slim_down(session.opened)
    assert (tmp_path / core.SCREENSHOTS_DUMP / "b.png").exists() and not copy_b.exists()
    return copy_b


def test_a_screenshot_back_from_dump_after_a_slim_down_gets_its_copy_again(session, tmp_path, monkeypatch):
    copy_b = slimmed(session, tmp_path, monkeypatch)
    del session.atlas.frames[0]  # (a taken out: b shows those spots best again; the clean map names a: the grid)
    session._sort_dump(session.opened)
    assert (tmp_path / core.SCREENSHOTS_USED / "b.png").exists() and copy_b.exists()  # (used/ stays safe to delete)


def test_a_slimmed_screenshot_gone_for_good_is_no_missing_terrain_warning(session, tmp_path, monkeypatch):
    slimmed(session, tmp_path, monkeypatch)
    (tmp_path / core.SCREENSHOTS_DUMP / "b.png").unlink()  # (the player deleted dump/)
    path = session.path
    session.open_atlas(path)  # (opened again)
    t = getattr(session, "_lock_thread", None)
    if t:
        t.join(60)
    lines = list(session.events.log_lines)
    assert any("slimmed down" in line for line in lines)
    assert not any("screenshots not found" in line for line in lines)


def test_two_screenshots_of_one_name_from_different_folders_keep_copies_of_their_own(session, tmp_path):
    # (CodeRabbit: the second one's copy was "there" already, and showed the first one's pixels once deleted)
    (tmp_path / "two").mkdir()
    screenshot(tmp_path / "two" / "a.png", seed=9)
    other = dict(session.atlas.frames[0], name="a", path=str(tmp_path / "two" / "a.png"), sha="f" * 64)
    session.atlas.frames.append(other)
    first, second = (session.atlas.copy_path(f["path"]) for f in session.atlas.frames)
    assert first != second
    assert session.atlas.write_copy(other["path"]) and second.exists() and not first.exists()


def test_a_copy_keeps_its_name_when_its_screenshot_moves(session, tmp_path):
    before = copy_of(session.atlas, "a")
    session._keep_screenshots(session.opened, ["a"])  # (moved to used/)
    assert copy_of(session.atlas, "a") == before and before.exists()


def test_a_screenshot_with_no_picture_left_never_takes_spots_from_one_with_a_picture(session, tmp_path):
    second_view(session, tmp_path)  # (b shows what a shows)
    ghost = dict(session.atlas.frames[0], name="ghost", path=str(tmp_path / "ghost.png"), sha="0" * 64)
    session.atlas.frames.insert(0, ghost)  # (first: it won every tie, though it has neither file nor copy)
    dump = session._dump_names(session.atlas, session.opened)
    assert "a" not in dump and "ghost" not in dump  # (a still shows its spots: CodeRabbit)


def test_a_clean_map_naming_a_screenshot_undone_or_missing_a_new_one_is_not_used(session, tmp_path, monkeypatch):
    second_view(session, tmp_path)
    clean_map(session, monkeypatch)
    assert session._ownership_input(session.atlas, session.opened)[1] is not None
    monkeypatch.setattr(session, "labels", (session.labels[0], ["a", "b", "undone"]))  # (an undo took one out)
    assert session._ownership_input(session.atlas, session.opened)[1] is None
    monkeypatch.setattr(session, "labels", (session.labels[0], ["a"]))  # (b added while the map is made again)
    assert session._ownership_input(session.atlas, session.opened)[1] is None


def test_slim_down_removes_nothing_without_a_clean_map(session, tmp_path):
    # (the grid knows placements, not each screenshot's fog: never what is deleted - CodeRabbit)
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    assert session.slim_info(session.atlas, session.opened) == {"count": 0, "mb": 0.0, "clean": False}
    session.set_ui_settings({"recheck_slim": True})
    session._slim_down(session.opened)
    assert copy_of(session.atlas, "b").exists()
    assert any("it needs the clean map (Fix seams)" in line for line in session.events.log_lines)


def test_undo_keeps_the_time_a_screenshot_was_taken_recorded_after_its_snapshot(session, tmp_path):
    snapshot = session._snapshot()  # (before a's time was kept)
    second_view(session, tmp_path)
    session._remember_add(["b"], snapshot)
    session._keep_screenshots(session.opened, ["a"])  # (records a's time: no Steam name)
    taken = session.atlas.frames[0]["taken"]
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()  # (then deleted: its time only in the atlas now)
    session._run_undo()
    assert session.atlas.frames[0].get("taken") == pytest.approx(taken)  # (CodeRabbit)


def test_a_screenshot_unreadable_mid_fix_seams_owns_no_spot_of_the_clean_map(session, monkeypatch):
    from grand_project.core import seams

    real, seen = session.atlas.image, set()

    def once(path):  # (read for its scores, deleted before it is drawn, no copy)
        if path in seen:
            return None
        seen.add(path)
        return real(path)

    monkeypatch.setattr(session.atlas, "image", once)
    _canvas, _origin, weight, labels, _names = seams.clean_composite(session.atlas)
    assert int((labels >= 0).sum()) == 0 and float(weight.max()) <= 0  # (CodeRabbit: black, owned and weighted)


def test_a_sharp_tile_missing_a_screenshot_gone_mid_build_is_not_kept(session, monkeypatch):
    f = session.atlas.frames[0]
    gone_mid_way(session.atlas, monkeypatch)
    skipped = []
    core.build_sharp_tile(
        session.atlas, [core.footprint(session.atlas, f)], 1.0, 0.0, 0.0, 256, lambda f: None, 4, skipped=skipped
    )
    assert skipped == ["a"]  # (webmap's SharpTiles keeps no such tile in its folder: built again next time)


def test_paths_are_traced_again_through_the_copy_of_a_screenshot_deleted_mid_trace():
    assert traces._trace_one((None, None, None, None)) == {}  # (no picture left: nothing traced)
    assert traces._trace_one(("gone.png", None, None, None)) is None  # (picked, then deleted: traced again)


def test_no_gold_is_looked_for_in_a_screenshot_with_no_picture_left(session, monkeypatch):
    monkeypatch.setattr(session.atlas, "image", lambda path: None)
    assert traces._gold(session.atlas, {"path": "gone.png", "name": "gone"}) is None  # (the check stopped on it)


def test_a_clean_map_whose_spots_belong_to_a_screenshot_with_no_picture_left_is_not_used(
    session, tmp_path, monkeypatch
):
    # (those spots counted for no one: a screenshot showing them too looked like dump - CodeRabbit)
    session._keep_screenshots(session.opened, ["a"])
    second_view(session, tmp_path)
    clean_map(session, monkeypatch)  # (a owns every spot)
    copy_of(session.atlas, "a").unlink()
    (tmp_path / core.SCREENSHOTS_USED / "a.png").unlink()  # (a's picture gone for good)
    assert session._ownership_input(session.atlas, session.opened)[1] is None
    assert session.slim_info(session.atlas, session.opened)["clean"] is False  # (b's copy is the last picture)


def test_a_clean_map_still_fits_when_only_a_slimmed_screenshot_is_gone(session, tmp_path, monkeypatch):
    slimmed(session, tmp_path, monkeypatch)
    (tmp_path / core.SCREENSHOTS_DUMP / "b.png").unlink()  # (b owns no spot: nothing lost)
    assert session._ownership_input(session.atlas, session.opened)[1] is not None


def test_sharp_tiles_are_made_again_once_a_missing_picture_is_back(session, tmp_path):
    before = session._sharp_folder()
    shot = tmp_path / "a.png"
    kept = shot.read_bytes()
    shot.unlink()  # (no copy: its picture is gone, tiles made now leave it out)
    without = session._sharp_folder()
    shot.write_bytes(kept)
    assert without != before and session._sharp_folder() == before  # (CodeRabbit)


def test_a_tile_missing_a_screenshot_lost_mid_build_is_not_kept_in_memory_either(session, monkeypatch):
    # (CodeRabbit: the folder skipped it, the app's tile cache didn't)
    built = []

    class Raster:
        grid = type("G", (), {"zmax": 0})()

        def pixels(self, z, x, y):
            return np.zeros((1, 1, 3), np.uint8)

    class Sharp:
        def has(self, z):
            return True

        def jpeg(self, z, x, y, wanted=None, skipped=None):
            built.append((z, x, y))
            skipped.append("a")
            return b"tile"

    state = (None, Raster(), Sharp(), 99)
    assert session._tile_from(state, 1, 0, 0) == b"tile" and session._tile_from(state, 1, 0, 0) == b"tile"
    assert len(built) == 2  # (made again: never served from memory)
    # ...nor kept by the browser: its address stays the same once the picture is back (CodeRabbit)
    monkeypatch.setattr(session, "_tile_state", state)
    assert session.terrain_tile_for(1, 0, 0, "") == (b"tile", False)
