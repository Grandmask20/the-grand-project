"""Scoring the classical node guesses on reviewed screenshots (tools/detection_dataset_annotator/score_nodes.py)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project.detect import badges
from tools.detection_dataset_annotator import ReviewStore, image_key, score_nodes
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.score_nodes import guess_nodes, main, report
from tools.detection_dataset_annotator.state import file_hash

GRASS, SNOW = (40, 150, 150), (0, 10, 200)  # OpenCV HSV of two ground classes


def _shot(path: Path) -> np.ndarray:
    """A 1080p screenshot: grass on the left, snow on the right."""
    hsv = np.zeros((1080, 1920, 3), np.uint8)
    hsv[:, :960] = GRASS
    hsv[:, 960:] = SNOW
    image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    _write(path, image)
    return image


def _write(path: Path, image: np.ndarray) -> None:
    """A PNG written through Python (cv2.imwrite fails on some non-ASCII paths)."""
    path.write_bytes(cv2.imencode(".png", image)[1].tobytes())


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


def test_a_box_without_a_place_is_left_out(tmp_path: Path) -> None:
    """A box stored without a place (NaN is stored as NULL) is skipped; the placed ones are scored as before."""
    image = _shot(tmp_path / "a.png")
    nowhere = {"label": "map_node_vaal", "bbox": [None, None, None, None], "source": "manual"}
    hall = {"label": "hall", "bbox": [None, None, None, None], "source": "manual"}
    pairs = guess_nodes(image, [nowhere, hall, _node("map_node_grass", 400, 540)], 1920, 1080)
    assert pairs == [("map_node_grass", "map_node_grass", True)]


def test_the_tool_reads_reviewed_screenshots(tmp_path: Path, capsys) -> None:
    shot = tmp_path / "a.png"
    _shot(shot)
    out = tmp_path / "out"
    with ReviewStore.open(out / K.ANNOTATOR_STORE_FILE) as store:
        store.add_images([shot])
        key = image_key(shot)
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": [_node("map_node_grass", 400, 540)]}
        store.record_detection(key, {**result, K.ANNOTATOR_DETECTED_SHA: file_hash(shot)}, force=False)
        assert main(["--output-dir", str(out)]) == 1  # nothing reviewed yet
        assert store.save_review(key, 1, reviewed=True)
    assert main(["--output-dir", str(out), "--ring", "20", "40"]) == 0
    assert "1 nodes, 100.0% right" in capsys.readouterr().out
    assert main(["--output-dir", str(out), "--limit", "0"]) == 1  # none read
    with pytest.raises(SystemExit):
        main(["--output-dir", str(out), "--limit", "-1"])


def test_a_citadels_own_map_is_guessed_as_its_city(tmp_path: Path) -> None:
    """A reviewed citadel makes its map node its city's: a sure guess, as the annotator makes it for a city whose
    type is sure (a reviewed citadel's is); no node boxes, nothing to score."""
    image = _shot(tmp_path / "a.png")
    citadel = {"label": "citadel_stone", "bbox": [360, 500, 80, 80], "source": "manual"}
    pairs = guess_nodes(image, [_node("map_node_vaal", 400, 540), citadel], 1920, 1080)
    assert pairs == [("map_node_vaal", "map_node_vaal", True)]
    assert guess_nodes(image, [citadel], 1920, 1080) == []


def test_reviewed_landmarks_reach_the_city_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Towers, halls and strongholds are landmarks for the city areas, as in the detector's result (the city rules
    keep them out of a city's area): a tower at its map node (its box's bottom edge), the others at their middle."""
    image = _shot(tmp_path / "a.png")
    seen = {}

    def areas(nodes, edges, icons, landmarks, city_types):
        seen.update(landmarks=landmarks, city_types=city_types)
        return {}

    monkeypatch.setattr(score_nodes, "city_area_nodes", areas)
    boxes = [
        _node("map_node_vaal", 400, 540),
        _node("map_node_grass", 960, 500),
        {"label": "tower", "bbox": [660, 320, 80, 220]},
        {"label": "hall", "bbox": [900, 400, 120, 120]},
        {"label": "breach_stronghold", "bbox": [1200, 200, 150, 150]},
        {"label": "citadel_stone", "bbox": [360, 500, 80, 80]},
    ]
    guess_nodes(image, boxes, 1920, 1080)
    assert [(lm["kind"], lm["x"], lm["y"]) for lm in seen["landmarks"]] == [
        ("Tower", 700.0, 540.0),
        ("Hall", 960.5, 500.5),  # at its map node's middle, as the detector places a Hall
        ("Breach stronghold", 1275.0, 275.0),
        ("City", 400.0, 540.0),
    ]
    assert seen["city_types"] == {3: "Vaal"}
    # a Hall box with no map node inside is left out (the classical detector reports a Hall only at its map node:
    # one at the box's middle would keep a neighbouring map out of a city's area); the City keeps its type
    boxes = [_node("map_node_vaal", 400, 540), {"label": "hall", "bbox": [900, 400, 120, 120]},
             {"label": "citadel_stone", "bbox": [360, 500, 80, 80]}]  # fmt: skip
    guess_nodes(image, boxes, 1920, 1080)
    assert [lm["kind"] for lm in seen["landmarks"]] == ["City"] and seen["city_types"] == {0: "Vaal"}


def test_a_reviewed_hall_is_at_its_map_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, namer: dict) -> None:
    """A hall box frames its map node and structure: the Hall the city rules see is its map node (the one under its
    deadly-boss icon, even when another map node lies nearer the box's middle), as the detector reports it."""
    image = _shot(tmp_path / "a.png")
    seen = {}

    def areas(nodes, edges, icons, landmarks, city_types):
        seen.update(landmarks=landmarks)
        return {}

    monkeypatch.setattr(score_nodes, "city_area_nodes", areas)
    namer[(1000, 676)] = "MapBossSpecial"
    boxes = [
        _node("map_node_grass", 1000, 700),
        _node("map_node_grass", 930, 640),  # inside the box too, nearer its middle, but not under the icon
        {"label": "icon", "bbox": [983, 659, 34, 34]},
        {"label": "hall", "bbox": [890, 600, 130, 125]},
    ]
    guess_nodes(image, boxes, 1920, 1080)
    assert [(lm["kind"], lm["x"], lm["y"]) for lm in seen["landmarks"]] == [("Hall", 1000.5, 700.5)]  # its middle


@pytest.mark.parametrize("ring", [["38", "19"], ["-1", "10"], ["nan", "38"], ["10", "inf"], ["10", "1e9"]])
def test_a_ring_that_is_no_ring_is_refused(ring: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--ring", *ring, "--output-dir", str(tmp_path)])


def test_paths_across_a_fortress_wall_are_left_out_as_the_detector_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A city's area grows over the paths the classical detector keeps: none that runs through a fortress wall."""
    image = _shot(tmp_path / "a.png")
    seen = {}

    def areas(nodes, edges, icons, landmarks, city_types):
        seen["edges"] = edges
        return {}

    open_path = {"a": 0, "b": 1, "line": [[400.0 + 10 * k, 540.0] for k in range(21)]}
    walled = {"a": 1, "b": 2, "line": [[600.0 + 10 * k, 540.0] for k in range(21)]}
    wall = np.zeros((1080, 1920), np.uint8)
    wall[500:580, 620:780] = 1
    monkeypatch.setattr(score_nodes, "city_area_nodes", areas)
    monkeypatch.setattr("grand_project.detect.paths.trace_paths", lambda nodes, dashes, img: [open_path, walled])
    monkeypatch.setattr("grand_project.detect.walls.fortress_walls", lambda img: wall)
    nodes = [_node("map_node_grass", x, 540) for x in (400, 600, 800)]
    guess_nodes(image, nodes, 1920, 1080)
    assert seen["edges"] == [open_path]


def test_a_screenshot_without_node_boxes_uses_none_of_the_limit(tmp_path: Path, capsys) -> None:
    """--limit 1 scores the first screenshot with node boxes, not a reviewed one that has none."""
    out = tmp_path / "out"
    with ReviewStore.open(out / K.ANNOTATOR_STORE_FILE) as store:
        for name, boxes in (("empty.png", []), ("a.png", [_node("map_node_grass", 400, 540)])):
            shot = tmp_path / name
            _shot(shot)
            store.add_images([shot])
            result = {"detected": True, "width": 1920, "height": 1080, "annotations": boxes}
            store.record_detection(image_key(shot), {**result, K.ANNOTATOR_DETECTED_SHA: file_hash(shot)}, force=False)
            assert store.save_review(image_key(shot), 1, reviewed=True)
    assert main(["--output-dir", str(out), "--limit", "1"]) == 0
    assert "1 nodes" in capsys.readouterr().out


def test_a_screenshot_changed_since_its_detection_is_not_scored(tmp_path: Path, capsys) -> None:
    """Its boxes frame the bytes detected: a file replaced since by another picture of the same size is named and not
    scored, by its digest, not its size (CodeRabbit)."""
    shot = tmp_path / "a.png"
    image = _shot(shot)
    out = tmp_path / "out"
    with ReviewStore.open(out / K.ANNOTATOR_STORE_FILE) as store:
        store.add_images([shot])
        key = image_key(shot)
        node = _node("map_node_mountain", 1500, 540)
        result = {"detected": True, "width": 1920, "height": 1080, "annotations": [node]}
        store.record_detection(key, {**result, K.ANNOTATOR_DETECTED_SHA: file_hash(shot)}, force=False)
        assert store.save_review(key, 1, reviewed=True)
    assert main(["--output-dir", str(out)]) == 0
    assert "1 nodes, 100.0% right" in capsys.readouterr().out
    _write(shot, 255 - image)  # other pixels, the same 1920x1080
    assert main(["--output-dir", str(out)]) == 1
    assert "changed since its detection" in capsys.readouterr().out


def test_a_missing_store_is_named_and_not_made(tmp_path: Path, capsys) -> None:
    """Scoring reads a store, never makes one (opened read-only: its journal mode stays too)."""
    out = tmp_path / "out"
    assert main(["--output-dir", str(out)]) == 1
    assert "no annotator store at" in capsys.readouterr().out
    assert not out.exists()


def test_an_icon_the_naming_step_drops_never_takes_a_neighbours_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordinary results are their own input's (the same place): a rejected icon next to a named one stays
    unidentified; a special template found at a place of its own names the icon near it (CodeRabbit)."""
    monkeypatch.setattr(badges, "naming_book", lambda: {"names": [], "F": np.zeros((0, 0))})
    icons = [{"name": "Unidentified", "x": 100.0, "y": 100.0}, {"name": "Unidentified", "x": 120.0, "y": 100.0},
             {"name": "Unidentified", "x": 500.0, "y": 500.0}]  # fmt: skip

    def naming(img, found, book, influence_min):
        kept = {**found[1], "name": "Delirium"}  # the first (rejected) is dropped; the second is named
        special = {"x": 503.0, "y": 500.0, "name": "Breach", "score": 1.0}  # a template's own centre, near the third
        return [special, kept]

    monkeypatch.setattr(badges, "name_found_icons", naming)
    score_nodes.name_icons(np.zeros((1080, 1920, 3), np.uint8), icons)
    assert [icon["name"] for icon in icons] == ["Unidentified", "Delirium", "Breach"]
