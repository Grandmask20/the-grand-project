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


def test_the_score_command_reads_the_states_next_to_the_screenshots(tmp_path, capsys):
    """`truth score`: truth.json has no states; the hand-checked ones are the screenshots' states.json."""
    import argparse
    import hashlib
    import json

    shots, cache = tmp_path / "shots", tmp_path / "cache"
    shots.mkdir()
    cache.mkdir()
    (shots / "a.png").write_bytes(b"a screenshot")
    shot = _shot([{"x": 100.0, "y": 100.0, "state": "green"}])
    del shot["states"]
    (tmp_path / "truth.json").write_text(json.dumps({"a.png": shot}))
    (shots / "states.json").write_text(json.dumps({"a.png": [{"x": 100.0, "y": 100.0, "state": "green"}]}))
    found = {"nodes": [{"x": 100.0, "y": 101.0, "state": "blue"}], "landmarks": [], "icons": []}
    (cache / f"{hashlib.sha256(b'a screenshot').hexdigest()[:16]}.json").write_text(json.dumps(found))
    args = argparse.Namespace(truth=str(tmp_path / "truth.json"), shots=str(shots), cache=str(cache))
    assert atlas_truth.cmd_score(args) == 0
    assert "map node states: 0 right, 1 wrong, 0 unsure" in capsys.readouterr().out
