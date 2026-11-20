"""The classical detector's result as the dataset's labelled first guesses (grand_project/detect/proposals.py)."""

import cv2
import numpy as np
import pytest

from grand_project import cities
from grand_project.detect import constants as K
from grand_project.detect import proposals

GRASS = (40, 150, 150)  # OpenCV HSV of grass (finalize.landmarks._ground_classes)


def _grass() -> np.ndarray:
    hsv = np.zeros((1080, 1920, 3), np.uint8)
    hsv[:] = GRASS
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


@pytest.fixture(autouse=True)
def buttons(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """A stand-in for the square-button finder (a flat test picture is no screenshot): the buttons given."""
    found: list[dict] = []
    monkeypatch.setattr(cities, "square_buttons", lambda img: [dict(button) for button in found])
    return found


@pytest.fixture
def vaal_city(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every City looks surely Vaal."""
    monkeypatch.setattr(cities, "landmark_city_types", lambda img, lms: {
        i: ("Vaal", True) for i, lm in enumerate(lms) if lm.get("kind") == "City"})  # fmt: skip


def test_every_kind_gets_its_label_and_box(vaal_city, buttons) -> None:
    detection = {
        "nodes": [
            {"x": 600, "y": 500},  # the city's own map
            {"x": 720, "y": 500},  # in its area (a path links them)
            {"x": 1300, "y": 500},  # elsewhere, on grass
            {"x": 1000, "y": 800},  # the Hall's map
        ],
        "edges": [{"a": 0, "b": 1}],
        "landmarks": [
            {"kind": "City", "x": 600, "y": 500},
            {"kind": "Hall", "x": 1000, "y": 800},
            {"kind": "Tower", "x": 1500, "y": 700},
            {"kind": "Breach stronghold", "x": 300, "y": 300},
            {"kind": "Locked stronghold", "x": 1700, "y": 300},
            {"kind": "Deadly boss map", "x": 1300, "y": 500},
        ],
        "icons": [
            {"x": 600, "y": 476, "name": "MapBossSpecial"},
            {"x": 1300, "y": 476, "name": "BreachHive"},
            {"x": 1500, "y": 450, "name": "LostTower"},  # left out of the dataset (user): no box
            {"x": 900, "y": 300, "name": "Checkpoint"},
            {"x": 200, "y": 900, "name": "ExpeditionShip", "source": "square button"},  # a reveal button, no icon
        ],
    }
    buttons.extend(
        [
            {"kind": "lock", "x": 1750.0, "y": 420.0, "frame": 0.95, "symbol": 0.9},  # the locked stronghold's hand
            {"kind": "ship", "x": 200.0, "y": 900.0, "frame": 0.97, "symbol": 0.95},
            {"kind": "unknown", "x": 500.0, "y": 900.0, "frame": 0.93, "symbol": 0.3},  # a symbol not taught yet
        ]
    )
    boxes = proposals.dataset_boxes(detection, _grass())
    found = [(b["label"], b["source"]) for b in boxes]
    assert found == [
        ("map_node_vaal", K.RF_DETR_SOURCE_CLASSICAL),  # the citadel's own map: as sure as the city's type
        ("map_node_vaal", K.RF_DETR_SOURCE_CITY_AREA_GUESS),
        ("map_node_grass", K.RF_DETR_SOURCE_CLASSICAL),
        ("map_node_grass", K.RF_DETR_SOURCE_CLASSICAL),
        ("citadel_stone", K.RF_DETR_SOURCE_CLASSICAL),
        ("hall", K.RF_DETR_SOURCE_CLASSICAL),
        ("tower", K.RF_DETR_SOURCE_CLASSICAL),
        ("breach_stronghold", K.RF_DETR_SOURCE_CLASSICAL),
        ("breach_stronghold", K.RF_DETR_SOURCE_CLASSICAL),  # locked or open: one structure (user)
        ("reveal_button", K.RF_DETR_SOURCE_CLASSICAL),  # every kind of reveal button is one class (user)
        ("reveal_button", K.RF_DETR_SOURCE_CLASSICAL),
        ("reveal_button", K.RF_DETR_SOURCE_CLASSICAL),
        ("icon", K.RF_DETR_SOURCE_CLASSICAL),  # icons not named by type: the deadly-boss icon too (user)
        ("icon", K.RF_DETR_SOURCE_CLASSICAL),
    ]  # no box for the deadly boss map: its node and icon say it (user); the ship button is no icon box
    ship = next(b for b in boxes if b["label"] == "reveal_button" and b["item"]["kind"] == "ship")
    assert ship["box"] == (166.0, 867.0, 68.0, 66.0) and ship["item"]["score"] == 0.97  # on its frame
    citadel = next(b["box"] for b in boxes if b["label"] == "citadel_stone")
    assert citadel == (560.0, 460.0, 80.0, 80.0)  # the city's node and barrel, as before
    named = proposals.dataset_boxes(detection, _grass(), named_icons=True)
    assert [b["label"] for b in named][-2:] == ["icon_mapbossspecial", "icon_breachhive"]
    assert sum(b["label"] == "reveal_button" for b in named) == 3  # one class whatever the naming option


def test_a_citys_own_map_is_as_sure_as_that_citys_type() -> None:
    """Two Vaal cities, one surely Vaal and one an unsure look-alike guess: each own map takes its own city's
    certainty, not the other city's of the same type."""
    detection = {
        "nodes": [{"x": 400, "y": 500}, {"x": 1400, "y": 500}],
        "edges": [],
        "landmarks": [{"kind": "City", "x": 400, "y": 500}, {"kind": "City", "x": 1400, "y": 500}],
        "icons": [],
    }
    found = proposals.node_classes(_grass(), detection, {0: ("Vaal", True), 1: ("Vaal", False)})
    assert found == [
        ("map_node_vaal", K.RF_DETR_SOURCE_CLASSICAL),
        ("map_node_vaal", K.RF_DETR_SOURCE_CITY_GUESS),
    ]


def test_a_hall_box_holds_its_node_and_the_whole_structure() -> None:
    """User: the hall box covers the hall structure, which stands under its orange beam; with no beam seen it goes
    where it stood on the measured halls (up-left of the node)."""
    x, y = 1000.0, 600.0
    img = np.zeros((1080, 1920, 3), np.uint8)
    x0, y0, w, h = proposals.hall_box(img, x, y)
    width, height = K.RF_DETR_HALL_STRUCTURE_BOX
    assert w >= width and h >= height
    assert x0 < x - 100 and x0 + w >= x + K.RF_DETR_MAP_BOX / 2  # the structure left, the node inside
    assert y0 < y - 90 and y0 + h >= y + K.RF_DETR_MAP_BOX / 2

    beam = np.zeros((1080, 1920, 3), np.uint8)
    beam[int(y) - 150 : int(y) - 40, int(x) + 50 : int(x) + 90] = (0, 120, 240)  # orange (BGR), to the right
    bx0, _by0, bw, _bh = proposals.hall_box(beam, x, y)
    assert bx0 <= x - K.RF_DETR_MAP_BOX / 2 and bx0 + bw > x + 100  # now the structure is right of the node


def test_box_helpers_clip_to_the_image(monkeypatch: pytest.MonkeyPatch) -> None:
    assert proposals.box_at_point(5, 5, 20, 20, 100, 100) == (0.0, 0.0, 15.0, 15.0)
    assert proposals.box_at_point(50, 50, 20, 40, 100, 100, anchor="base") == (40.0, 10.0, 20.0, 40.0)
    assert proposals.box_at_point(-50, -50, 20, 20, 100, 100) is None
    assert proposals.box_around_line([[10, 20], [30, 40]], 5, 100, 100) == (5.0, 15.0, 30.0, 30.0)
    mask = np.zeros((100, 100), np.uint8)
    mask[10:40, 10:40] = 1
    assert proposals.wall_boxes(mask) == []  # 900 px², under RF_DETR_WALL_MIN_AREA
    monkeypatch.setattr(K, "RF_DETR_WALL_MIN_AREA", 100)
    assert proposals.wall_boxes(mask) == [(10.0, 10.0, 30.0, 30.0)]


@pytest.mark.data
def test_hall_boxes_hold_the_hand_labelled_hall_structures(test_data) -> None:
    """The hand truth labels halls on their structure ("offcenter"): wherever the classical detector finds the hall,
    that point lies in its hall box (user: the box holds the whole hall structure)."""
    import json

    from grand_project import core
    from grand_project.detect.pipeline import detect_classical, ensure_models

    ensure_models()
    truth = json.loads((test_data / "truth" / "truth.json").read_text(encoding="utf-8"))
    checked = 0
    for name, labels in truth.items():
        points = [(lm["x"], lm["y"]) for lm in labels.get("landmarks", [])
                  if lm.get("kind") == "Hall" and "offcenter" in (lm.get("flags") or [])]  # fmt: skip
        if not points:
            continue
        image = core.read_screenshot(test_data / "screenshots" / "random_samples" / name)
        boxes = [b["box"] for b in proposals.dataset_boxes(detect_classical(image), image) if b["label"] == "hall"]
        for x, y in points:
            near = [
                b
                for b in boxes
                if abs(b[0] + b[2] - K.RF_DETR_MAP_BOX / 2 - x) < 150 and abs(b[1] + b[3] / 2 - y) < 150
            ]
            if not near:
                continue  # the classical detector did not find this hall (a detection miss, not the box rule)
            assert any(b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3] for b in near), (name, x, y, near)
            checked += 1
    assert checked >= 5
