"""Hand-checking map node states and freezing the namer's pictures (tools/node_state_sheet.py)."""

import json

import cv2
import numpy as np
import pytest

from grand_project import icon_refs
from grand_project.detect import constants as K
from grand_project.detect import node_states
from tools import node_state_sheet as T

GLOW = {"blue": (255, 150, 90), "green": (70, 235, 60), "grey": (175, 175, 175), "red": (50, 40, 230)}
SPOTS = [(300, 300, "blue"), (500, 300, "green"), (700, 300, "grey"), (900, 300, "blue")]


def _screenshot(path, seed: int) -> None:
    img = np.random.default_rng(seed).integers(20, 60, (1080, 1920, 3), dtype=np.uint8)
    for x, y, state in SPOTS:
        cv2.circle(img, (x, y), 13, (40, 140, 200), 2)
        cv2.circle(img, (x, y), 10, (60, 60, 60), -1)
        cv2.circle(img, (x, y), 6, GLOW[state], -1)
    cv2.imwrite(str(path), img)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """Two screenshots whose map nodes are hand-checked already (states.json), the tool's outputs in tmp_path."""
    shots = tmp_path / "shots"
    shots.mkdir()
    for k in range(2):
        _screenshot(shots / f"2694490_2026112120000{k}_1.png", k)
    states = {p.name: [{"x": x, "y": y, "state": s} for x, y, s in SPOTS] for p in sorted(shots.glob("*.png"))}
    (shots / K.NODE_STATE_TRUTH).write_text(json.dumps(states))
    monkeypatch.setattr(K, "NODE_STATES_FILE", tmp_path / "pictures.npz")
    monkeypatch.setattr(K, "NODE_STATE_SETS", [shots])
    return shots


def test_a_sheet_corrected_by_hand_is_saved_frozen_and_scored(folder, tmp_path, capsys):
    out = tmp_path / "sheet"
    assert T.main(["sheet", str(folder), "--out", str(out)]) == 0
    proposals = json.loads((out / "proposals.json").read_text())["proposals"]
    assert len(proposals) == 8 and {p["state"] for p in proposals.values()} == {"blue", "green", "grey"}
    assert sorted(f.name for f in out.glob("sheet_*.png")) == [
        "sheet_blue_1.png",
        "sheet_green_1.png",
        "sheet_grey_1.png",
    ]
    # the hand check: S4 is no map node after all, S2 is grey
    (out / "corrections.txt").write_text("# checked\nS4 none\ns2 GREY\n")
    assert T.main(["save", str(folder), "--out", str(out)]) == 0
    saved = json.loads((folder / K.NODE_STATE_TRUTH).read_text())
    first = saved[min(saved)]
    assert [s["state"] for s in first] == ["blue", "grey", "grey"]  # S2 corrected, S4 left out
    assert T.main(["freeze"]) == 0
    assert sorted(set(node_states.state_pictures()["states"])) == ["blue", "green", "grey"]
    assert T.main(["score", str(folder)]) == 0
    assert "blue   " in capsys.readouterr().out


def test_freezing_never_takes_pictures_from_the_scoring_truth_sets(folder, monkeypatch):
    monkeypatch.setattr(K, "TRUTH_SETS", [(folder / "truth.json", folder)])
    with pytest.raises(SystemExit, match="TRUTH_SETS"):
        T.main(["freeze"])


def test_a_correction_must_name_a_state(tmp_path):
    f = tmp_path / "corrections.txt"
    f.write_text("S1 purple\n")
    with pytest.raises(ValueError, match="line 1"):
        T.read_corrections(f)
    f.write_text("S1 red # failed hall\n\nS2 none\n")
    assert T.read_corrections(f) == {"S1": "red", "S2": None}


@pytest.mark.parametrize("state", ["blue", "green", "grey", "red"])
def test_the_first_guess_goes_by_the_glow(state):
    img = np.full((80, 80, 3), 40, np.uint8)
    cv2.circle(img, (40, 40), 6, GLOW[state], -1)
    assert T.first_guess(icon_refs.crop(img, 40, 40)) == state


def test_spread_picks_one_of_each_look_first():
    F = np.array([[1, 0], [0.99, 0.141], [0, 1]], np.float32)
    assert sorted(T.spread(F, 2)) in ([0, 2], [1, 2])
    assert T.spread(F, 5) == [0, 1, 2]
