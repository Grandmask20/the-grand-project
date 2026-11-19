"""The atlas-wide check's loose badge rule: a badge seen beside the map that carries it is that badge, not another."""

from grand_project.finalize.check import _loose_copies


def test_a_loose_copy_goes_unless_a_screenshot_shows_both():
    nodes = [{"x": 0.0, "y": 0.0, "icons": [0]}]
    icons = [
        {"name": "Delirium", "bx": 0.0, "by": -20.0, "frames": ["a", "b"]},  # on the map
        {"name": "Delirium", "bx": 30.0, "by": -20.0, "frames": ["c"]},  # beside it, never seen with it: a copy
        {"name": "Delirium", "bx": -30.0, "by": -20.0, "frames": ["b"]},  # beside it in the same screenshot: its own
        {"name": "Breach", "bx": 30.0, "by": 0.0, "frames": ["c"]},  # another badge
    ]
    assert _loose_copies(nodes, ["kept"], icons, {0}) == {1}
    assert _loose_copies(nodes, ["removed"], icons, {0}) == set()  # (a removed map carries nothing)
