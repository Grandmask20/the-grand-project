"""Map node states over time on real screenshots (atlas_test_data/map_state_change).

One area of the author's atlas, seen before running maps (pre-change: 20:08-20:10), after (post-change: 20:25-20:26)
and then once per map run (single-map: 20:28-20:35), placed into one atlas with the classical detector. The check
(finalize) must keep each map's state and icons from its newest sightings:

- the map that carried Fleeing Exile + Sanctification was run: it is green and lost its Sanctification (the
  classical icon finder never found its Fleeing Exile);
- the Fleeing Exile moved to a blue neighbour (user: icons move to a neighbour when their map is run);
- a blue map lost its Sanctification and stayed blue; a Unique map failed (red) and lost its icon;
- the maps of the newest screenshot have the states hand-checked there (single-map/states.json);
- few sightings disagree with the rules (detection errors).
"""

import json
import math
import shutil

import numpy as np
import pytest

from grand_project import core
from grand_project.finalize import finalize

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def checked(test_data, tmp_path_factory):
    """The state-change atlas checked in a copy (the check may re-name saved states and write them back)."""
    src = test_data / "map_state_change"
    if not (src / "atlas.json").exists():
        pytest.skip("no map_state_change atlas in the test data")
    atlas = core.Atlas.load(src / "atlas.json")  # its screenshots where they are, its saved detections copied
    atlas.frames_dir = tmp_path_factory.mktemp("map_state_change") / "atlas_frames"
    shutil.copytree(src / "atlas_frames", atlas.frames_dir)
    return atlas, finalize(atlas, log=None), src


def _kept(final):
    return [n for n in final["nodes"] if n["status"] != "removed"]


def test_the_cleared_map_is_green_and_its_fleeing_exile_moved_on(checked, check):
    _atlas, final, _src = checked
    kept = _kept(final)
    gained = [n for n in kept if "FleeingExile" in n["icons"] and "Sanctification" in n["icons"]]
    check("one map carries Fleeing Exile and Sanctification", len(gained) == 1, [n["id"] for n in gained])
    if not gained:
        return
    to = gained[0]
    check("it is blue", to["state"] == "blue", to["state"])
    exile = [
        ic
        for ic in final["icons"]
        if ic["name"] == "FleeingExile" and math.hypot(ic["bx"] - to["x"], ic["by"] - to["y"]) < 30
    ]
    check(
        "its Fleeing Exile was first seen after the maps were run",
        exile and min(exile[0]["frames"]) > "2694490_20261121202000",
        exile,
    )
    cleared = [
        n
        for n in kept
        if n["state"] == "green"
        and "Sanctification" in n["icons_lost"]
        and 150 < math.hypot(n["x"] - to["x"], n["y"] - to["y"]) < 400
    ]
    check("the map it came from is green and lost its Sanctification", len(cleared) == 1, [n["id"] for n in cleared])


def test_a_blue_map_can_lose_an_icon_and_a_failed_one_is_red(checked, check):
    _atlas, final, _src = checked
    kept = _kept(final)
    check(
        "a blue map lost Sanctification",
        any(n["state"] == "blue" and "Sanctification" in n["icons_lost"] for n in kept),
    )
    failed = [n for n in kept if n["state"] == "red"]
    check(
        "one map failed: the Unique map, which lost its icon",
        [n["icons_lost"] for n in failed] == [["UniqueMap"]],
        failed,
    )
    shown = {(ic["name"], round(ic["bx"]), round(ic["by"])) for ic in final["icons"]}
    for n in kept:
        for name in n["icons_lost"]:
            near = [s for s in shown if s[0] == name and math.hypot(s[1] - n["x"], s[2] - n["y"]) < 30]
            check(f"map {n['id']}'s lost {name} is not shown", not near, near)


def test_the_newest_screenshot_shows_the_maps_as_they_are(checked, check):
    """The maps of the newest screenshot (taken last, after every map run) end with the states seen there."""
    atlas, final, src = checked
    newest = max(atlas.frames, key=core.capture_time)
    labels = _states(src / "single-map", newest["name"] + ".png")
    H = core.screen_to_atlas(np.array(newest["M"], float), atlas.frame_R(newest))
    kept = _kept(final)
    pts = np.array([[n["x"], n["y"]] for n in kept], float)
    right = wrong = 0
    for s in labels:
        x, y = core.persp(H, [[s["x"], s["y"]]])[0]
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        if d.min() > 15 or kept[int(d.argmin())]["state"] is None:
            continue
        ok = kept[int(d.argmin())]["state"] == s["state"]
        right, wrong = right + ok, wrong + (not ok)
    check(
        "most of its map nodes were found and named", right + wrong >= 0.8 * len(labels), (right + wrong, len(labels))
    )
    check("at least 97% end in the state seen there", right >= 0.97 * (right + wrong), (right, wrong))


def test_few_sightings_break_the_rules(checked, check):
    _atlas, final, _src = checked
    stats = final["stats"]
    check(
        "some maps are green, some blue, some grey",
        min(stats["maps_green"], stats["maps_blue"], stats["maps_grey"]) > 10,
    )
    seen = sum(n["seen"] for n in _kept(final))
    check("under 1% of the sightings disagree", stats["state_errors"] < 0.01 * seen, (stats["state_errors"], seen))


def _states(folder, shot):
    return json.loads((folder / "states.json").read_text(encoding="utf-8")).get(shot, [])
