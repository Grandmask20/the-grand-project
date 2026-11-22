"""Map node states named from stored pictures (detect.node_states), on drawn map nodes."""

import numpy as np
import pytest

from grand_project import icon_refs
from grand_project.detect import constants as K
from grand_project.detect import node_states

# the glowing middle of a map node per state (BGR): blue, green, grey (no glow), red
GLOW = {"blue": (255, 150, 90), "green": (70, 235, 60), "grey": (175, 175, 175), "red": (50, 40, 230)}


def _draw(img: np.ndarray, x: int, y: int, state: str) -> None:
    """A map node as the atlas shows one: a gold rim, a dark ring and its glowing middle."""
    import cv2

    cv2.circle(img, (x, y), 13, (40, 140, 200), 2)
    cv2.circle(img, (x, y), 10, (60, 60, 60), -1)
    cv2.circle(img, (x, y), 6, GLOW[state], -1)


def _screenshot(rng: np.random.Generator, nodes: list[tuple[int, int, str]]) -> np.ndarray:
    img = rng.integers(20, 60, (1080, 1920, 3), dtype=np.uint8)
    for x, y, state in nodes:
        _draw(img, x, y, state)
    return img


@pytest.fixture
def rng(seed) -> np.random.Generator:
    """The background noise's generator (numpy), seeded with `seed`."""
    return np.random.default_rng(seed)


@pytest.fixture
def pictures(tmp_path, monkeypatch, rng):
    """A picture file of two drawn map nodes per state (red only when asked), used as NODE_STATES_FILE."""

    def make(states=("grey", "blue", "green")):
        img = _screenshot(rng, [(200 + 100 * k, 300 + 100 * j, s) for j, s in enumerate(states) for k in range(2)])
        crops = [icon_refs.crop(img, 200 + 100 * k, 300 + 100 * j) for j, _s in enumerate(states) for k in range(2)]
        path = tmp_path / f"states_{len(states)}.npz"
        node_states.save_state_pictures(
            path, np.array(crops), [s for s in states for _k in range(2)], ["a"] * len(crops)
        )
        monkeypatch.setattr(K, "NODE_STATES_FILE", path)
        return path

    return make


def test_each_state_is_named_by_its_nearest_picture(pictures, rng):
    pictures()
    img = _screenshot(rng, [(900, 500, "blue"), (1000, 520, "green"), (1100, 480, "grey")])
    nodes = [{"x": 901, "y": 499}, {"x": 1000, "y": 522}, {"x": 1098, "y": 480}]  # a px or two off the middle
    assert node_states.name_states(img, nodes) == ["blue", "green", "grey"]


def test_guessed_map_nodes_and_ones_off_the_screenshot_are_unsure(pictures, rng):
    pictures()
    img = _screenshot(rng, [(900, 500, "blue"), (8, 500, "blue")])
    nodes = [{"x": 900, "y": 500, "hidden": True}, {"x": 900, "y": 500, "unverified": True}, {"x": 8, "y": 500}]
    assert node_states.name_states(img, nodes) == [None, None, None]


def test_no_pictures_means_every_state_is_unsure(tmp_path, monkeypatch, rng):
    monkeypatch.setattr(K, "NODE_STATES_FILE", tmp_path / "missing.npz")
    img = _screenshot(rng, [(900, 500, "blue")])
    assert node_states.name_states(img, [{"x": 900, "y": 500}]) == [None]
    assert node_states.states_stamp() == "-"


def test_a_glow_no_picture_has_is_unsure_not_the_nearest_pattern(pictures, rng):
    """Red has no pictures here: a red map node looks like the others in shape, but no picture glows red."""
    pictures()
    img = _screenshot(rng, [(900, 500, "red")])
    state, dist = node_states.name_state(img, 900, 500)
    assert state is None and dist == 9.0


def test_the_stamp_follows_the_picture_file(pictures):
    pictures()
    first = node_states.states_stamp()
    pictures(("grey", "blue", "green", "red"))
    assert node_states.states_stamp() not in (first, "-")
    assert node_states.state_pictures()["states"].count("red") == 2


def test_saving_refuses_unknown_states_and_uneven_lists(tmp_path):
    crops = np.zeros((1, icon_refs.SIZE, icon_refs.SIZE, 3), np.uint8)
    with pytest.raises(ValueError, match="unknown state"):
        node_states.save_state_pictures(tmp_path / "x.npz", crops, ["purple"], ["a"])
    with pytest.raises(ValueError, match="one state"):
        node_states.save_state_pictures(tmp_path / "x.npz", crops, ["blue", "grey"], ["a"])
