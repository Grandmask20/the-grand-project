"""The detector's score against the hand-made truth (grand_project.truth.score / print_score): map node states."""

from grand_project import truth as atlas_truth


def _shot(states: list[dict]) -> dict:
    maps = [{"x": s["x"], "y": s["y"], "flags": []} for s in states]
    return {"maps": maps, "maybe": [], "not_maps": [], "landmarks": [], "badges": [], "states": states}


def test_the_states_of_found_map_nodes_are_scored(capsys):
    truth = {
        "a.png": _shot(
            [
                {"x": 100.0, "y": 100.0, "state": "blue"},
                {"x": 300.0, "y": 100.0, "state": "green"},
                {"x": 500.0, "y": 100.0, "state": "grey"},
                {"x": 700.0, "y": 100.0, "state": "blue"},
            ]
        )
    }
    found = {
        "a.png": {
            "nodes": [
                {"x": 101.0, "y": 99.0, "state": "blue"},
                {"x": 300.0, "y": 103.0, "state": "blue"},
                {"x": 500.0, "y": 100.0, "state": None},
            ],  # the fourth map node was not found: the maps score has it, not the states score
            "landmarks": [],
            "icons": [],
        }
    }
    s = atlas_truth.score(truth, found)
    assert s["states"] == {"right": 1, "wrong": 1, "unsure": 1, "confusion": {"green called blue": 1}}
    atlas_truth.print_score(s)
    out = capsys.readouterr().out
    assert "map node states: 1 right, 1 wrong, 1 unsure" in out and "1 x green called blue" in out


def test_truth_without_states_prints_no_states_score(capsys):
    truth = {"a.png": dict(_shot([{"x": 100.0, "y": 100.0, "state": "blue"}]), states=[])}
    s = atlas_truth.score(truth, {"a.png": {"nodes": [{"x": 100.0, "y": 100.0}], "landmarks": [], "icons": []}})
    atlas_truth.print_score(s)
    assert "map node states" not in capsys.readouterr().out
