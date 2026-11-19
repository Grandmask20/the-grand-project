"""City types on one screenshot (grand_project/cities.py: screenshot_city_types)."""

from __future__ import annotations

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
