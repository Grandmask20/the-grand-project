"""City types on one screenshot (grand_project/cities.py: screenshot_city_types) and the square reveal buttons
(square_buttons, name_button)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from grand_project import cities

# Two cities 300 px apart (closer than TRIO_GAP: never the same type), both with whole ground windows.
POINTS = [(600.0, 500.0), (900.0, 500.0)]


def _types(monkeypatch: pytest.MonkeyPatch, looks: list[list[float]]) -> list[tuple[str, bool]]:
    """screenshot_city_types with the given look-alike distances (TYPES order), one per city."""
    found = iter(looks)
    monkeypatch.setattr(cities, "look_distances", lambda feats: next(found))
    return cities.screenshot_city_types(np.zeros((1080, 1920, 3), np.uint8), POINTS)


def test_a_neighbours_doubt_carries_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second city is clear only because its neighbour's type was ruled out: as unsure as that neighbour."""
    # A: Vaal by a small margin (0.05, unsure). B alone would be Ezomyte by 0.01; without Vaal by 0.60.
    assert _types(monkeypatch, [[0.50, 0.45, 0.60], [0.30, 0.31, 0.90]]) == [("Vaal", False), ("Ezomyte", False)]


def test_a_sure_neighbour_keeps_the_city_sure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same second city next to a clearly Vaal neighbour is sure."""
    assert _types(monkeypatch, [[0.50, 0.30, 0.60], [0.30, 0.31, 0.90]]) == [("Vaal", True), ("Ezomyte", True)]


def _button_shot(kind: str, left: int = 800, top: int = 400) -> tuple[np.ndarray, tuple[float, float]]:
    """A dark screenshot with one square button ("lock": the hand, "ship": the Expedition ship) and its middle."""
    refs = cities._button_refs()
    h, w = refs["frame"].shape
    if kind == "lock":
        picture = refs["frame"]
    else:
        ship = cv2.imdecode(np.fromfile(str(cities.SHIP_BUTTON), np.uint8), cv2.IMREAD_GRAYSCALE)
        picture = cv2.resize(ship, (w, h))
    grey = np.zeros((1080, 1920), np.uint8)
    grey[top : top + h, left : left + w] = picture
    return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR), (left + w / 2, top + h / 2)


@pytest.mark.parametrize("kind", ["lock", "ship"])
def test_square_buttons_are_found_by_their_frame_and_named_by_their_symbol(kind: str) -> None:
    img, (x, y) = _button_shot(kind)
    assert [(b["kind"], b["x"], b["y"]) for b in cities.square_buttons(img)] == [(kind, x, y)]
    assert cities.name_button(img, x, y)[0] == kind


@pytest.mark.parametrize("kind", ["lock", "ship"])
def test_a_wider_search_names_a_button_found_off_its_middle(kind: str) -> None:
    """User: RF-DETR finds the reveal buttons and the classical code names them; the model's middle can be a few px
    off, so its buttons are named with a wider search (RF_DETR_BUTTON_SHIFT, 16 px: measured on the dataset)."""
    from grand_project.detect import constants as DK

    img, (x, y) = _button_shot(kind)
    assert cities.name_button(img, x + 10, y - 6, margin=DK.RF_DETR_BUTTON_SHIFT)[0] == kind
    assert cities.name_button(img, x + 10, y - 6)[0] == "unknown"  # the finder's own search: its frame is exact


def test_no_button_is_unknown() -> None:
    rng = np.random.default_rng(3)
    noise = rng.integers(0, 256, (1080, 1920, 3), np.uint8)
    assert cities.name_button(noise, 960, 540, margin=16)[0] == "unknown"
    assert cities.name_button(noise, 5, 5) == ("unknown", -1.0)  # too near the edge for a symbol
