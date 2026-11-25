"""A map's icons over time (finalize.icon_time, user's rules): an icon a newer moment shows gone is removed, one that
appeared where it never can is dropped, an attempted deadly boss map keeps only its Deadly Map Boss icon; screenshots
of one moment never disagree, and an unsure look decides nothing."""

import types
from pathlib import Path

import numpy as np
import pytest

from grand_project.finalize import icon_time as it

OLD, NEW = "2694490_20261121200833_1", "2694490_20261121202535_1"  # (15 minutes apart: two moments)
NEW2 = "2694490_20261121202537_1"  # (2 s after NEW: the same moment)


def test_screenshots_close_together_are_one_moment():
    assert it.moments([0.0, 3.0, 5.0, 100.0, 101.0, None]) == [[0, 1, 2], [3, 4], [5]]
    assert it.moments([100.0, 0.0]) == [[1], [0]]  # (oldest first)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Screenshots that show the atlas 1:1 (atlas units = px), one map at (500, 500); icon_check answers from
    `looks` ({(screenshot, icon name): True / False / None})."""
    looks: dict = {}
    frames = []
    for name in (OLD, NEW, NEW2):
        path = tmp_path / f"{name}.png"
        path.write_bytes(b"x")
        frames.append({"name": name, "path": str(path), "w": 1920, "h": 1080})
    maps = [(f, np.eye(3)) for f in frames]
    monkeypatch.setattr(
        it,
        "icon_check",
        lambda img, x, y, name, anchored=True, others=None: looks.get(
            (img.rsplit("\\", 1)[-1][:-4].rsplit("/", 1)[-1], name)
        ),
    )
    # the atlas's pictures (core.Atlas.image: the screenshot, else its copy): the "image" is its path, none when gone
    atlas = types.SimpleNamespace(frames_dir=None, image=lambda p: p if Path(p).exists() else None)

    def run(icons, seen_by=(OLD, NEW, NEW2), tower=False, cities=None):
        node = {"x": 500.0, "y": 500.0, "frames": set(seen_by), "icons": list(range(len(icons))), "tower": tower}
        return it.icons_over_time(atlas, maps, [node], [True], icons, set(), cities)

    return run, looks


def icon(name, *frames):
    return {"name": name, "frames": list(frames)}


def test_an_icon_a_newer_moment_shows_gone_is_removed(world):
    run, looks = world
    looks[(NEW, "MapBoss")] = looks[(NEW2, "MapBoss")] = False  # (the newer screenshots show the map without it)
    assert run([icon("MapBoss", OLD)]) == {"gone": {0}, "false": set()}


def test_found_or_seen_in_the_newest_moment_it_stays(world):
    run, looks = world
    looks[(NEW, "MapBoss")] = False
    looks[(NEW2, "MapBoss")] = True  # (one look of the moment finds it: the detector missed it in the other)
    assert run([icon("MapBoss", OLD)])["gone"] == set()
    assert run([icon("MapBoss", OLD, NEW)])["gone"] == set()  # (found by the detector: not looked at)


def test_an_unsure_newest_moment_decides_nothing(world):
    run, looks = world
    looks[(NEW, "MapBoss")] = None  # (half off the screen, a weak match...)
    assert run([icon("MapBoss", OLD)])["gone"] == set()


def test_one_moment_never_disagrees_with_itself(world):
    run, looks = world
    looks[(NEW2, "MapBoss")] = False
    assert run([icon("MapBoss", NEW)], seen_by=(NEW, NEW2))["gone"] == set()  # (2 s apart: nothing changed)


def test_towers_unknown_icons_and_markers_are_left_alone(world):
    run, looks = world
    for name in ("MapBoss", "Unidentified", "PlayerOrBookmark"):
        looks[(NEW, name)] = looks[(NEW2, name)] = False
    assert run([icon("MapBoss", OLD)], tower=True)["gone"] == set()  # (a tower's icons float above it)
    assert run([icon("Unidentified", OLD), icon("PlayerOrBookmark", OLD)])["gone"] == set()


def test_an_icon_that_never_appears_found_only_later_was_found_falsely(world):
    run, looks = world
    looks[(OLD, "Corruption")] = False  # (the older moment shows the map without it)
    assert run([icon("Corruption", NEW)]) == {"gone": set(), "false": {0}}
    looks[(OLD, "Ritual")] = False  # (Ritual can appear: kept)
    assert run([icon("Ritual", NEW)]) == {"gone": set(), "false": set()}
    looks[(OLD, "Corruption")] = None  # (the older moment unsure: no evidence it appeared)
    assert run([icon("Corruption", NEW)])["false"] == set()


def test_cleansed_only_replaces_corruption(world):
    run, looks = world
    looks[(OLD, "Sanctification")] = False
    assert run([icon("Sanctification", NEW)])["false"] == {0}  # (no Corruption before)
    looks[(NEW, "Corruption")] = looks[(NEW2, "Corruption")] = False
    got = run([icon("Sanctification", NEW), icon("Corruption", OLD)])
    assert got == {"gone": {1}, "false": set()}  # (Corruption before, Cleansed in its place)


def test_an_attempted_deadly_boss_map_keeps_only_its_deadly_boss_icon(world):
    run, looks = world
    looks[(NEW, "Sanctification")] = looks[(NEW2, "Sanctification")] = False
    icons = [icon("MapBossSpecial", OLD, NEW), icon("Sanctification", OLD), icon("Breach", OLD)]
    assert run(icons)["gone"] == {1, 2}  # (one gone takes the other non-deadly icons; Breach was unsure)
    assert run(icons, cities=[(505.0, 495.0)])["gone"] == {1}  # (a City isn't a plain deadly boss map)


# ------------------------------------------------------------------ the second look itself (the real one)
def grey(level=90):
    return np.full((1080, 1920, 3), level, np.uint8)


def test_a_clear_row_with_no_icon_shows_it_gone():
    assert it.icon_check(grey(), 960.0, 540.0, "MapBoss") is False  # (no icon rim anywhere in the row)


def test_the_dark_fog_and_the_hud_decide_nothing():
    assert it.icon_check(grey(10), 960.0, 540.0, "MapBoss") is None  # (no icons are drawn in the dark fog)
    # the search bar's corner of the HUD over part of the row (user: missing under the HUD changes nothing)
    hud = it.core.hud_mask(1920, 1080)
    ys, xs = np.nonzero(hud[:200, 400:1500])
    y, x = int(ys.max()) + 30, int(xs[ys.argmax()]) + 400  # (a map just below the HUD's lowest point up there)
    assert it.icon_check(grey(), float(x), float(y), "MapBoss") is None
    assert it.icon_check(grey(), 30.0, 540.0, "MapBoss") is None  # (the row runs off the screen)


def test_an_icon_with_no_pictures_of_its_own_is_never_judged():
    assert it.icon_check(grey(), 960.0, 540.0, "CorruptionNexus") is None


def test_a_floating_icon_with_copies_far_apart_is_a_towers_and_left_alone(world):
    run, looks = world
    looks[(NEW, "Corruption")] = looks[(NEW2, "Corruption")] = False
    assert run([dict(icon("Corruption", OLD), spread=65.0)])["gone"] == set()  # (user: a tower's icons)


def test_a_screenshot_with_no_known_time_decides_nothing(world, monkeypatch):
    run, looks = world
    times = {OLD: 1000.0, NEW: None, NEW2: None}  # (the newer ones' times unknown: they can't come after OLD)
    monkeypatch.setattr(it.core, "capture_time", lambda f: times[f["name"]])
    looks[(NEW, "MapBoss")] = looks[(NEW2, "MapBoss")] = False
    assert run([icon("MapBoss", OLD)])["gone"] == set()


def test_cleansed_replacing_corruption_the_second_look_confirmed(world):
    run, looks = world
    looks[(OLD, "Sanctification")] = False
    looks[(OLD, "Corruption")] = True  # (the detector missed it in OLD; the second look saw it)
    looks[(NEW, "Corruption")] = looks[(NEW2, "Corruption")] = False
    got = run([icon("Sanctification", NEW), icon("Corruption", NEW)])  # (Corruption "found" only in NEW: missed)
    assert 0 not in got["false"]  # (Corruption was there before: Cleansed replaced it)


def test_the_deadly_boss_sweep_leaves_a_towers_floating_icon(world):
    run, looks = world
    looks[(NEW, "Sanctification")] = looks[(NEW2, "Sanctification")] = False
    icons = [icon("MapBossSpecial", OLD, NEW), icon("Sanctification", OLD), dict(icon("Breach", OLD), spread=60.0)]
    assert run(icons)["gone"] == {1}  # (the floating Breach copy is a tower's: never judged)
