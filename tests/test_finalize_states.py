"""Map node states over time (finalize.states): the user's rules on what may change between sightings."""

import hashlib
import json

import cv2
import numpy as np
import pytest

from grand_project import core
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


# ---------------------------------------------------------------- a whole atlas
NAMES = ["2694490_20261121200833_1", "2694490_20261121200834_1", "2694490_20261121202535_1"]


def _atlas(tmp_path, states: list[list], icon: str = "FleeingExile", stamp: str | None = None):
    """Three screenshots of one spot (atlas units = screen px), two map nodes, one icon (`icon`) on the first map.

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
        }
        (tmp_path / f"{f['sha'][:16]}_{atlas_detect.DETECTOR_ID}.json").write_text(json.dumps(rec))
    icons = [{"name": icon, "x": 900.0, "y": 476.0, "n": 3, "frames": NAMES}]
    nodes = [
        {"x": 900.0, "y": 500.0, "frames": set(NAMES), "guessed": set(), "icons": [0]},
        {"x": 1100.0, "y": 500.0, "frames": set(NAMES), "guessed": set(), "icons": []},
    ]
    return at, maps_by, nodes, icons


def test_a_cleared_map_is_green_from_its_newest_screenshot(tmp_path):
    at, maps_by, nodes, icons = _atlas(tmp_path, [["blue", "grey"], ["blue", "grey"], ["green", "blue"]])
    fits = S.fit_nodes(at, maps_by, nodes, ["icon", "confirmed"], icons)
    assert fits[0] == {"state": "green", "seen": core.capture_time(at.frames[2]), "sightings": 3, "errors": 0}
    assert fits[1]["state"] == "blue"
    assert S.state_near(fits, nodes, 905, 498) == "green"
    assert S.state_near(fits, nodes, 1000, 500) is None
    assert S.state_stats([{"status": "icon", "state": "green", "state_errors": 0}]) == {
        "maps_grey": 0,
        "maps_blue": 0,
        "maps_green": 1,
        "maps_red": 0,
        "state_errors": 0,
    }


def test_only_a_map_that_can_fail_turns_red(tmp_path):
    """Red only on a STATE_RED_ICONS map (or where a City / Hall stands): elsewhere a red sighting is an error."""
    seen = [["blue", "grey"], ["red", "grey"], ["red", "grey"]]
    at, maps_by, nodes, icons = _atlas(tmp_path, seen)
    assert S.fit_nodes(at, maps_by, nodes, ["icon", "confirmed"], icons)[0]["state"] != "red"
    (tmp_path / "unique").mkdir()
    at, maps_by, nodes, icons = _atlas(tmp_path / "unique", seen, icon="UniqueMap")
    fit = S.fit_nodes(at, maps_by, nodes, ["icon", "confirmed"], icons)[0]
    assert fit["state"] == "red" and fit["errors"] == 0


def test_removed_map_nodes_and_ones_with_no_sightings_are_not_fitted(tmp_path):
    at, maps_by, nodes, icons = _atlas(tmp_path, [["blue", "grey"]] * 3)
    nodes[1]["guessed"] = set(NAMES)  # only guessed under an icon row: no map base seen
    fits = S.fit_nodes(at, maps_by, nodes, ["removed", "confirmed"], icons)
    assert fits == {}


def test_states_named_with_other_pictures_are_named_again(tmp_path, monkeypatch):
    """A new freeze re-names the saved states from the image (finding stays as it is), and the cache keeps them."""
    at, maps_by, _nodes, _icons = _atlas(tmp_path, [["grey", "grey"]] * 3, stamp="old pictures")
    f = at.frames[0]
    cv2.imwrite(f["path"], np.zeros((1080, 1920, 3), np.uint8))
    monkeypatch.setattr(atlas_detect, "name_states", lambda img, nodes, book=None: ["blue", None])
    rec = traces._saved(at, f)
    assert rec["state"] == ["blue", None]
    saved = json.loads((tmp_path / f"{f['sha'][:16]}_{atlas_detect.DETECTOR_ID}.json").read_text())
    assert saved["states_from"] == atlas_detect.states_stamp()
    assert [n["state"] for n in saved["nodes"]] == ["blue", None]


def test_states_stay_as_saved_when_the_screenshot_is_gone(tmp_path, monkeypatch):
    """...and are named again once it is back (CodeRabbit: they were kept as today's names before)."""
    at, _maps_by, _nodes, _icons = _atlas(tmp_path, [["green", "grey"]] * 3, stamp="old pictures")
    f = at.frames[1]
    assert traces._saved(at, f)["state"] == ["green", "grey"]
    cv2.imwrite(f["path"], np.zeros((1080, 1920, 3), np.uint8))
    monkeypatch.setattr(atlas_detect, "name_states", lambda img, nodes, book=None: ["blue", None])
    assert traces._saved(at, f)["state"] == ["blue", None]


@pytest.mark.parametrize("bad", ["auto", 7])
def test_a_saved_value_that_is_no_state_counts_as_unsure(tmp_path, bad):
    at, _maps_by, _nodes, _icons = _atlas(tmp_path, [[bad, "blue"]] * 3)
    assert traces._saved(at, at.frames[2])["state"] == [None, "blue"]
