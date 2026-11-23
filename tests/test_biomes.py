"""A map node's biome and city area on one screenshot (grand_project/detect/biomes.py): the first guesses of the
dataset's node classes, on screenshots painted with the ground colours finalize.landmarks._ground_classes knows."""

import cv2
import numpy as np

from grand_project.detect import biomes
from grand_project.finalize import landmarks as fl

# OpenCV HSV of each ground class (finalize.landmarks._ground_classes)
GRASS, SAND, WATER, SNOW = (40, 150, 150), (20, 80, 180), (100, 150, 120), (0, 10, 200)


def _painted(regions: list[tuple[int, int, tuple[int, int, int]]], base=(0, 0, 60)) -> np.ndarray:
    """A 1080p screenshot painted in vertical bands: (x0, x1, HSV colour) each."""
    hsv = np.zeros((1080, 1920, 3), np.uint8)
    hsv[:] = base
    for x0, x1, colour in regions:
        hsv[:, x0:x1] = colour
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_each_ground_gives_its_biome() -> None:
    """PM: green = grass, sand = desert, white = mountain, read in a ring around the map node."""
    img = _painted([(300, 700, GRASS), (800, 1100, SAND), (1200, 1600, SNOW)])
    nodes = [{"x": 500, "y": 540}, {"x": 950, "y": 540}, {"x": 1400, "y": 540}]
    guesses = biomes.node_biomes(img, nodes, [])
    assert [(g.biome, g.sure) for g in guesses] == [("grass", True), ("desert", True), ("mountain", True)]


def test_a_map_in_the_ocean_is_water_whatever_its_island() -> None:
    img = _painted([(0, 1920, WATER), (930, 990, SAND)])  # a sand island in the ocean
    (guess,) = biomes.node_biomes(img, [{"x": 960, "y": 540}], [])
    assert (guess.biome, guess.sure) == ("water", True)


def test_white_under_delirium_mist_is_not_mountain() -> None:
    """PM: mountain and Delirium both look white. Under a Delirium icon's mist (its map and the maps around it) the
    white is left out and the guess is unsure."""
    img = _painted([(300, 1700, SNOW)])
    nodes = [{"x": 600, "y": 540}, {"x": 700, "y": 540}, {"x": 1400, "y": 540}]
    icons = [{"name": "Delirium", "x": 600, "y": 516}]
    guesses = biomes.node_biomes(img, nodes, icons)
    assert guesses[0].biome != "mountain" and not guesses[0].sure
    assert guesses[1].biome != "mountain" and not guesses[1].sure  # within BIOME_MIST_REACH of the misted map
    assert (guesses[2].biome, guesses[2].sure) == ("mountain", True)  # far from it


def test_fog_gives_no_biome() -> None:
    img = np.zeros((1080, 1920, 3), np.uint8)
    (guess,) = biomes.node_biomes(img, [{"x": 960, "y": 540}], [])
    assert guess.biome is None and not guess.sure and guess.shares == {}


def test_ocean_flags_agree_with_the_classical_ocean_rule() -> None:
    """The many-points version reads the same 350 px disc as finalize.landmarks._ocean."""
    img = _painted([(0, 800, WATER), (800, 1920, GRASS)])
    points = np.array([[300, 540], [700, 300], [790, 540], [900, 540], [1500, 540]], float)
    cls, bad = fl.ground_of(img)
    flags = biomes.ocean_flags(cls, bad, points)
    assert list(flags) == [fl._ocean(img, x, y) for x, y in points]
    assert flags[0] and not flags[-1]


def test_a_city_area_grows_from_its_own_map_through_the_paths() -> None:
    """The city's own map is step 0; maps linked to it join its area; a Hall's map never does (user's rule)."""
    nodes = [{"x": 600 + 120 * c, "y": 400 + 120 * r} for r in range(3) for c in range(3)]
    edges = []
    for r in range(3):
        for c in range(3):
            i = 3 * r + c
            if c < 2:
                edges.append({"a": i, "b": i + 1})
            if r < 2:
                edges.append({"a": i, "b": i + 3})
    landmarks = [{"kind": "City", "x": 600, "y": 400}, {"kind": "Hall", "x": 840, "y": 640}]
    area = biomes.city_area_nodes(nodes, edges, [], landmarks, {0: "Vaal"})
    assert area[0] == ("Vaal", 0)
    assert 8 not in area  # the Hall's map
    assert {city for city, _steps in area.values()} == {"Vaal"} and len(area) >= 5
    assert biomes.city_area_nodes(nodes, edges, [], landmarks, {}) == {}


def test_maps_at_and_beyond_the_screenshot_edge() -> None:
    """A map whose ring is mostly off the screenshot has too little ground for a guess; half a ring on it is enough;
    no maps, no guesses. On a cropped screenshot (no game HUD), so only the edge cuts the rings."""
    img = cv2.cvtColor(np.full((700, 900, 3), GRASS, np.uint8), cv2.COLOR_HSV2BGR)
    nodes = [{"x": 450, "y": 350}, {"x": 0, "y": 350}, {"x": -34, "y": 350}, {"x": -100, "y": 350}]
    guesses = biomes.node_biomes(img, nodes, [])
    assert [g.biome for g in guesses] == ["grass", "grass", None, None]  # x -34: a ~100 px sliver of its ring
    assert biomes.node_biomes(img, [], []) == []
    cls, bad = fl.ground_of(img)
    assert biomes.ocean_flags(cls, bad, np.zeros((0, 2))).shape == (0,)


def test_a_delirium_icon_without_a_map_under_it_mists_nothing() -> None:
    img = _painted([(300, 1700, SNOW)])
    far_icon = [{"name": "Delirium", "x": 1500, "y": 100}]  # no map node under its row
    (guess,) = biomes.node_biomes(img, [{"x": 600, "y": 540}], far_icon)
    assert (guess.biome, guess.sure) == ("mountain", True)


def _row(x: float, y: float, names: list[str]) -> list[dict]:
    """A row of icons centred over a map at (x, y): 36 px apart, 24 px above its base."""
    start = x - 36 * (len(names) - 1) / 2
    return [{"name": name, "x": start + 36 * k, "y": y - 24} for k, name in enumerate(names)]


def test_an_outer_icon_of_a_wide_row_belongs_to_the_map_under_the_row() -> None:
    """The map under a row is under its middle: an outer UniqueMap icon 54 px to the side still keeps its map out of a
    city's area, and an outer Delirium icon still mists its map."""
    nodes = [{"x": 600 + 120 * c, "y": 400} for c in range(3)]
    edges = [{"a": 0, "b": 1}, {"a": 1, "b": 2}]
    landmarks = [{"kind": "City", "x": 600, "y": 400}]
    icons = _row(720, 400, ["Breach", "Abyss", "Expedition", "UniqueMap"])  # the UniqueMap icon is 54 px right
    assert 1 not in biomes.city_area_nodes(nodes, edges, icons, landmarks, {0: "Vaal"})
    img = _painted([(300, 1700, SNOW)])
    far = [{"x": 600, "y": 540}, {"x": 1500, "y": 540}]
    misted = _row(600, 540, ["Breach", "Abyss", "Expedition", "Delirium"])
    guesses = biomes.node_biomes(img, far, misted)
    assert guesses[0].biome != "mountain" and (guesses[1].biome, guesses[1].sure) == ("mountain", True)
