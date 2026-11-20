"""Scoring the classical node guesses on reviewed screenshots (tools/detection_dataset_annotator/score_nodes.py)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project.detect import badges
from tools.detection_dataset_annotator import ReviewStore, image_key
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.score_nodes import guess_nodes, main, report

GRASS, SNOW = (40, 150, 150), (0, 10, 200)  # OpenCV HSV of two ground classes


def _shot(path: Path) -> np.ndarray:
    """A 1080p screenshot: grass on the left, snow on the right."""
    hsv = np.zeros((1080, 1920, 3), np.uint8)
    hsv[:, :960] = GRASS
    hsv[:, 960:] = SNOW
    image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    cv2.imwrite(str(path), image)
    return image


def _node(label: str, x: float, y: float) -> dict:
    return {"label": label, "bbox": [x - 19, y - 19, 39, 39], "source": "manual"}


@pytest.fixture(autouse=True)
def namer(monkeypatch: pytest.MonkeyPatch) -> dict:
    """A stand-in for the classical naming step: names by place (``names``), else "Unidentified"."""
    names: dict = {}
    monkeypatch.setattr(badges, "naming_book", lambda: {"names": [], "F": np.zeros((0, 0))})
    monkeypatch.setattr(
        badges,
        "name_found_icons",
        lambda img, icons, book, influence_min: [
            dict(icon, name=names.get((round(icon["x"]), round(icon["y"])), "Unidentified")) for icon in icons
        ],
    )
    return names


def test_unnamed_icons_take_the_classical_names(tmp_path: Path, namer: dict) -> None:
    """The annotator guessed from the classical names whatever the labels; with icons labelled `icon` the guesses are
    made again from the same names: a Delirium map's white is its mist, not mountain (unsure, no biome)."""
    image = _shot(tmp_path / "a.png")
    node, icon = _node("map_node_grass", 1500, 540), _node("icon", 1500, 516)
    icon["bbox"] = [1483, 499, 34, 34]
    assert guess_nodes(image, [node, icon], 1920, 1080) == [("map_node_grass", "map_node_mountain", True)]
    namer[(1500, 516)] = "Delirium"
    assert guess_nodes(image, [node, icon], 1920, 1080) == [("map_node_grass", "map_node", False)]
    named = {"label": "icon_delirium", "bbox": [1483, 499, 34, 34]}  # a reviewer's type is kept
    namer.clear()
    assert guess_nodes(image, [node, named], 1920, 1080) == [("map_node_grass", "map_node", False)]


def test_guesses_are_compared_with_the_reviewed_classes(tmp_path: Path) -> None:
    image = _shot(tmp_path / "a.png")
    annotations = [_node("map_node_grass", 400, 540), _node("map_node_grass", 1500, 540), _node("icon", 400, 300)]
    pairs = guess_nodes(image, annotations, 1920, 1080)
    assert pairs == [("map_node_grass", "map_node_grass", True), ("map_node_grass", "map_node_mountain", True)]
    text = report(pairs)
    assert "2 nodes, 50.0% right" in text and "precision" in text


def test_the_tool_reads_reviewed_screenshots(tmp_path: Path, capsys) -> None:
    shot = tmp_path / "a.png"
    _shot(shot)
    out = tmp_path / "out"
    with ReviewStore.open(out / K.ANNOTATOR_STORE_FILE) as store:
        store.add_images([shot])
        key = image_key(shot)
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": [_node("map_node_grass", 400, 540)]}
        store.record_detection(key, result, force=False)
        assert main(["--output-dir", str(out)]) == 1  # nothing reviewed yet
        assert store.save_review(key, 1, reviewed=True)
    assert main(["--output-dir", str(out), "--ring", "20", "40"]) == 0
    assert "1 nodes, 100.0% right" in capsys.readouterr().out


def test_a_citadels_own_map_is_guessed_as_its_city(tmp_path: Path) -> None:
    """A reviewed citadel makes its map node a city-area guess (never "sure"); no node boxes, nothing to score."""
    image = _shot(tmp_path / "a.png")
    citadel = {"label": "citadel_stone", "bbox": [360, 500, 80, 80], "source": "manual"}
    pairs = guess_nodes(image, [_node("map_node_vaal", 400, 540), citadel], 1920, 1080)
    assert pairs == [("map_node_vaal", "map_node_vaal", False)]
    assert guess_nodes(image, [citadel], 1920, 1080) == []
