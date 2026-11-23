"""Cities and Halls atlas-wide (finalize.landmarks._settlements): a City / Hall without its Deadly Map Boss icon."""

import pytest

from grand_project import core
from grand_project.finalize.landmarks import _recheck_settlements, _settlements


def _decide(kind: str, state: str | None, icons: list[dict] | None = None) -> dict:
    """One City / Hall seen in 3 screenshots, no Deadly Map Boss icon near it; its map node's state is `state`."""
    landmarks = [{"kind": kind, "x": 500.0, "y": 400.0, "n": 3, "conf": 0.9, "status": "kept"}]
    (out,) = _settlements(core.Atlas(), [], landmarks, icons or [], lambda x, y: state)
    return out


@pytest.mark.parametrize(("kind", "state", "word"), [("City", "green", "completed"), ("Hall", "red", "failed")])
def test_a_completed_or_failed_one_keeps_its_place_without_its_icon(kind, state, word):
    out = _decide(kind, state)
    assert out["kind"] == kind and out["status"] == "kept"
    assert out["beam"] == f"no Deadly Map Boss badge: {word} ({state} map)"


@pytest.mark.parametrize("state", ["blue", "grey", None])
def test_one_on_a_map_that_can_still_be_run_is_none_without_its_icon(state):
    """The false Cities of #33 came from the old "completed city?" guess: now the map must be green or red."""
    assert _decide("City", state)["status"].startswith("removed: no Deadly Map Boss badge and its map is not green")


def test_a_completed_one_on_another_types_map_is_none():
    """A green map carrying another exclusive type's icon (here a hideout) is no City, badge or not."""
    hideout = [{"name": "Hideout", "x": 500.0, "y": 376.0, "bx": 500.0, "by": 400.0}]
    out = _decide("City", "green", hideout)
    assert out["status"].startswith("removed: its map is a hideout map")


@pytest.mark.parametrize(("state", "kept"), [("green", True), ("red", True), ("blue", False), (None, False)])
def test_one_whose_badge_went_over_time_must_be_green_or_red(state, kept):
    """_settlements kept it for its badge; the icons over time then found the badge gone (the map was run): it is
    judged again as one without a badge."""
    badge = {"name": "MapBossSpecial", "x": 500.0, "y": 376.0}
    landmarks = [
        {"kind": "City", "x": 500.0, "y": 400.0, "status": "kept"},
        {"kind": "Hall", "x": 900.0, "y": 400.0, "status": "kept"},  # its badge stays
    ]
    icons = [badge, dict(badge, x=900.0)]
    _recheck_settlements(landmarks, icons, {0}, lambda x, y: state)
    assert (landmarks[0]["status"] == "kept") is kept
    assert landmarks[1]["status"] == "kept"
