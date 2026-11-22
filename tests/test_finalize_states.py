"""Map node states and icons over time (finalize.states): the user's rules on what may change between sightings."""

import hashlib
import json

import cv2
import numpy as np
import pytest

from grand_project import core, icon_refs
from grand_project import detect as atlas_detect
from grand_project.finalize import states as S
from grand_project.finalize import traces


# ---------------------------------------------------------------- the state of one map over its looks
def test_the_newest_sighting_shows_a_change():
    """One map is often run between two screenshots: one newest sighting is enough."""
    assert S.fit_path([["blue", "blue"], ["blue"], ["green"]]) == (["blue", "blue", "green"], 0)


def test_a_sighting_against_the_rules_is_a_detection_error():
    assert S.fit_path([["blue"], ["grey"], ["blue"]]) == (["blue", "blue", "blue"], 1)


def test_several_steps_can_pass_between_two_far_apart_sightings():
    assert S.fit_path([["grey"], ["green"]]) == (["grey", "green"], 0)


def test_green_never_changes_and_a_tie_goes_to_the_newest_look():
    assert S.fit_path([["green"], ["blue"]]) == (["blue", "blue"], 1)
    assert S.fit_path([["green"], ["green"], ["blue"]]) == (["green", "green", "green"], 1)


def test_red_only_where_a_city_or_hall_can_stand():
    assert S.fit_path([["blue"], ["red"]], red_ok=True) == (["blue", "red"], 0)
    assert S.fit_path([["blue"], ["red"]], red_ok=False) == (["blue", "blue"], 1)


def test_screenshots_of_one_look_share_its_state():
    """Two screenshots taken in the same second are one look: they cannot show two states."""
    assert S.fit_path([["blue", "blue", "green"]]) == (["blue"], 1)


# ---------------------------------------------------------------- one icon over the looks
def test_a_map_that_turns_green_loses_its_icons():
    assert S.fit_presence([True, True, None], ["blue", "blue", "green"]) == [True, True, False]
    # and keeps none after it, whatever later screenshots seem to show
    assert S.fit_presence([True, None, True, True], ["blue", "green", "green", "green"]) == [True, False, False, False]


def test_one_missed_newest_sighting_keeps_an_icon_two_drop_it():
    assert S.fit_presence([True, True, False], ["blue"] * 3) == [True, True, True]
    assert S.fit_presence([True, False, False], ["blue"] * 3) == [True, False, False]


def test_a_blue_map_can_gain_an_icon_that_moved_to_it():
    """Fleeing Exile moves to a neighbour when its map is run (user: any icon can move to a grey / blue map)."""
    assert S.fit_presence([False, False, True], ["blue"] * 3) == [False, False, True]


def test_a_green_maps_icons_never_change():
    assert S.fit_presence([False, False, False, True], ["green"] * 4) == [False] * 4


def test_a_failed_map_may_lose_an_icon_but_never_gains_one():
    assert S.fit_presence([True, False, False], ["blue", "red", "red"]) == [True, False, False]
    # on a blue map it arrived; on a failed one it was there all along (missed twice), it cannot have arrived
    assert S.fit_presence([False, False, True, True], ["blue"] * 4) == [False, False, True, True]
    assert S.fit_presence([False, False, True, True], ["blue", "red", "red", "red"]) == [True] * 4


def test_a_map_no_sighting_names_the_state_of_follows_the_icon_rules_of_a_blue_one():
    assert S.fit_presence([True, False, False], [None] * 3) == [True, False, False]


# ---------------------------------------------------------------- a whole atlas
NAMES = ["2694490_20261121200833_1", "2694490_20261121200834_1", "2694490_20261121202535_1"]


def _atlas(tmp_path, states: list[list], icon_frames: list[str], stamp: str | None = None):
    """Three screenshots of one spot (atlas units = screen px), two map nodes, one icon on the first map.

    states: per screenshot, the state its detection gave each of the two map nodes.
    """
    at = core.Atlas()
    at.frames_dir = tmp_path
    maps_by = {}
    for k, name in enumerate(NAMES):
        sha = hashlib.sha256(f"{tmp_path}/{k}".encode()).hexdigest()  # each test's own (the saved-detection memo)
        f = {"name": name, "path": str(tmp_path / f"{name}.png"), "sha": sha}
        f.update(w=1920, h=1080, M=np.eye(3)[:2].tolist(), horizon=None)
        at.frames.append(f)
        maps_by[name] = (f, np.eye(3))
        rec = {
            "nodes": [
                {"x": 900.0, "y": 500.0, "state": states[k][0], "hidden": False},
                {"x": 1100.0, "y": 500.0, "state": states[k][1], "hidden": False},
            ],
            "edges": [],
            "dash_pts": [],
            "amber_pts": [],
            "seen_grid": [],
            "wall_grid": [],
            "states_from": stamp if stamp is not None else atlas_detect.states_stamp(),
            "icons": [{"name": "FleeingExile", "x": 900, "y": 472}] if name in icon_frames else [],
        }
        (tmp_path / f"{f['sha'][:16]}_{atlas_detect.DETECTOR_ID}.json").write_text(json.dumps(rec))
    icons = [{"name": "FleeingExile", "x": 900.0, "y": 476.0, "n": len(icon_frames), "frames": icon_frames}]
    nodes = [
        {"x": 900.0, "y": 500.0, "frames": set(NAMES), "guessed": set(), "icons": [0]},
        {"x": 1100.0, "y": 500.0, "frames": set(NAMES), "guessed": set(), "icons": []},
    ]
    return at, maps_by, nodes, icons


def test_a_cleared_map_is_green_and_its_icon_is_lost(tmp_path):
    at, maps_by, nodes, icons = _atlas(
        tmp_path, [["blue", "grey"], ["blue", "grey"], ["green", "blue"]], icon_frames=NAMES[:2]
    )
    fits = S.fit_nodes(at, maps_by, nodes, ["icon", "confirmed"], icons)
    assert fits[0]["state"] == "green" and fits[0]["lost"] == ["FleeingExile"] and fits[0]["errors"] == 0
    assert fits[1]["state"] == "blue" and fits[1]["lost"] == []
    assert fits[0]["seen"] == core.capture_time(at.frames[2])
    assert S.state_near(fits, nodes, 905, 498) == "green"
    assert S.state_near(fits, nodes, 1000, 500) is None
    assert S.state_stats([{"status": "icon", "state": "green", "state_errors": 0, "icons_lost": ["FleeingExile"]}]) == {
        "maps_grey": 0,
        "maps_blue": 0,
        "maps_green": 1,
        "maps_red": 0,
        "state_errors": 0,
        "icons_lost": 1,
    }


def test_an_icon_never_seen_without_its_map_is_kept(tmp_path):
    """Absence only counts where the map itself was found: an icon is not lost because its map was missed."""
    at, maps_by, nodes, icons = _atlas(tmp_path, [["blue", "grey"]] * 3, icon_frames=NAMES)
    nodes[0]["frames"] = set(NAMES[:1])
    fits = S.fit_nodes(at, maps_by, nodes, ["icon", "confirmed"], icons)
    assert fits[0]["lost"] == [] and fits[0]["icon_errors"] == 0


def test_removed_map_nodes_and_ones_with_no_sightings_are_not_fitted(tmp_path):
    at, maps_by, nodes, icons = _atlas(tmp_path, [["blue", "grey"]] * 3, icon_frames=NAMES)
    nodes[1]["guessed"] = set(NAMES)  # only guessed under an icon row: no map base seen
    fits = S.fit_nodes(at, maps_by, nodes, ["removed", "confirmed"], icons)
    assert fits == {}


def test_states_named_with_other_pictures_are_named_again(tmp_path, monkeypatch):
    """A new freeze re-names the saved states from the image (finding stays as it is), and the cache keeps them."""
    at, maps_by, _nodes, _icons = _atlas(tmp_path, [["grey", "grey"]] * 3, icon_frames=[], stamp="old pictures")
    f = at.frames[0]
    cv2.imwrite(f["path"], np.zeros((1080, 1920, 3), np.uint8))
    monkeypatch.setattr(atlas_detect, "name_states", lambda img, nodes: ["blue", None])
    rec = traces._saved(at, f)
    assert rec["state"] == ["blue", None]
    saved = json.loads((tmp_path / f"{f['sha'][:16]}_{atlas_detect.DETECTOR_ID}.json").read_text())
    assert saved["states_from"] == atlas_detect.states_stamp()
    assert [n["state"] for n in saved["nodes"]] == ["blue", None]


def test_states_stay_as_saved_when_the_screenshot_is_gone(tmp_path):
    at, _maps_by, _nodes, _icons = _atlas(tmp_path, [["green", "grey"]] * 3, icon_frames=[], stamp="old pictures")
    assert traces._saved(at, at.frames[1])["state"] == ["green", "grey"]


@pytest.mark.parametrize("bad", ["auto", 7])
def test_a_saved_value_that_is_no_state_counts_as_unsure(tmp_path, bad):
    at, _maps_by, _nodes, _icons = _atlas(tmp_path, [[bad, "blue"]] * 3, icon_frames=[])
    assert traces._saved(at, at.frames[2])["state"] == [None, "blue"]


# ---------------------------------------------------------------- an icon the finder missed: the screenshot decides
ICON = np.random.default_rng(5).integers(0, 255, (icon_refs.SIZE, icon_refs.SIZE, 3), dtype=np.uint8)


def _draw_icon(path, x: float | None) -> None:
    """A screenshot with the icon drawn with its middle at (x, 472), or none."""
    img = np.full((1080, 1920, 3), 40, np.uint8)
    if x is not None:
        half = icon_refs.SIZE // 2
        img[472 - half : 472 - half + icon_refs.SIZE, int(x) - half : int(x) - half + icon_refs.SIZE] = ICON
    cv2.imwrite(str(path), img)


@pytest.mark.parametrize(
    ("drawn_at", "there"),
    [
        (900, True),  # missed by the finder, there all the same
        (918, True),  # moved half a step along its row (another icon left the row)
        (None, False),  # gone
    ],
)
def test_the_screenshot_decides_whether_a_missed_icon_is_there(tmp_path, monkeypatch, drawn_at, there):
    """The finder found the icon in the first two screenshots only: the third one itself is looked at."""
    at, maps_by, nodes, _icons = _atlas(tmp_path, [["blue", "grey"]] * 3, icon_frames=NAMES[:2])
    for f in at.frames[:2]:
        _draw_icon(f["path"], 900)
    _draw_icon(at.frames[2]["path"], drawn_at)
    monkeypatch.setattr(S, "_icon_pictures", lambda: {"FleeingExile": icon_refs.feature(ICON)[None]})
    spots = {f: S._map_at_spot(at, *maps_by[f], nodes[0]) for f in NAMES}
    checks = S._icon_checks(at, maps_by, {0: (set(NAMES), {"FleeingExile": set(NAMES[:2])}, spots)})
    assert checks == {(0, "FleeingExile", NAMES[2]): there}
