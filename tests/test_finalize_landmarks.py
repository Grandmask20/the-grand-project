"""Cities and Halls atlas-wide (finalize.landmarks._settlements): a City / Hall without its Deadly Map Boss icon."""

import pytest

from grand_project import core
from grand_project.finalize.landmarks import _settlements


def _decide(kind: str, state: str | None) -> dict:
    """One City / Hall seen in 3 screenshots, no Deadly Map Boss icon near it; its map node's state is `state`."""
    landmarks = [{"kind": kind, "x": 500.0, "y": 400.0, "n": 3, "conf": 0.9, "status": "kept"}]
    (out,) = _settlements(core.Atlas(), [], landmarks, [], lambda x, y: state)
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
