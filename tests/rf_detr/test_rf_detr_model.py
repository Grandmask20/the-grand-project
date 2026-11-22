"""The opt-in RF-DETR backend (grand_project/detect/rf_detr_model.py): how a checkpoint's classes come back to the
program, tiled prediction (with a stand-in model), model loading, icon naming, reveal buttons and the wall mask."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from grand_project import core
from grand_project.detect import constants as K
from grand_project.detect import rf_detr_model
from grand_project.detect.rf_detr_model import class_families, family_detections


def test_icons_are_named_by_the_classical_naming_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model's icons are named as the classical detector names its own (badges.name_found_icons with the icon
    model's pictures), without the rim finder's influence rule: the model's score is not the rim finder's."""
    calls = []

    def namer(img, icons, book, *, influence_min):
        calls.append((icons, book, influence_min))
        return [dict(icon, name="Delirium") for icon in icons]

    book = {"names": ["Delirium"], "F": np.zeros((1, 4), np.float32)}
    monkeypatch.setattr(rf_detr_model, "name_found_icons", namer)
    monkeypatch.setattr(rf_detr_model, "naming_book", lambda: book)
    found = [{"x": 50.0, "y": 50.0, "score": 0.4}]
    assert rf_detr_model._name_icons(np.zeros((100, 100, 3), np.uint8), found)[0]["name"] == "Delirium"
    assert calls == [(found, book, None)]


def test_class_families_group_classes_by_name() -> None:
    """Classes are matched by name, whatever their ids; a class of no family (a reviewer's own) is one of its own."""
    labels = {0: "map_node", 1: "citadel_stone", 2: "map_node_grass", 3: "icon", 4: "custom"}
    assert class_families(labels) == {
        "node": [(0, "map_node"), (2, "map_node_grass")],
        "citadel": [(1, "citadel_stone")],
        "icon": [(3, "icon")],
        "custom": [(4, "custom")],
    }


def test_sibling_classes_are_scored_together() -> None:
    """A node unsure between two biomes is still one node: its family's score is the sum of its classes' scores, its
    class the best one (each class alone is under the threshold)."""
    families = class_families({0: "map_node", 1: "map_node_grass", 2: "map_node_mountain", 3: "icon"})
    probs = np.array([[0.05, 0.25, 0.22, 0.01], [0.0, 0.02, 0.01, 0.9], [0.01, 0.1, 0.1, 0.02]])
    boxes = np.array([[10, 10, 49, 49], [100, 10, 134, 44], [200, 10, 239, 49]], float)
    found = family_detections(probs, boxes, families, threshold=0.35)
    assert [(d["label"], d["family"], round(d["score"], 2)) for d in found] == [
        ("map_node_grass", "node", 0.52),
        ("icon", "icon", 0.9),
    ]
    assert family_detections(np.zeros((0, 4)), np.zeros((0, 4)), families, threshold=0.35) == []


class _SquareFinder:
    """A stand-in RF-DETR: in each tile it "detects" every white square, as a map node unsure between grass (0.3)
    and mountain (0.25); the processor stand-in records the tiles it is given."""

    QUERIES = 4

    def __init__(self) -> None:
        self.tiles: list[np.ndarray] = []

    def processor(self, *, images, return_tensors):
        import torch

        self.tiles.extend(images)
        return {"pixel_values": torch.from_numpy(np.stack(images))}

    def __call__(self, pixel_values):
        import torch

        logits = torch.full((len(pixel_values), self.QUERIES, 4), -20.0)
        boxes = torch.zeros((len(pixel_values), self.QUERIES, 4))
        tile = K.RF_DETR_TILE
        for b, image in enumerate(pixel_values.numpy()):
            white = (image == 255).all(axis=-1).astype(np.uint8)
            _count, _labels, stats, _centres = cv2.connectedComponentsWithStats(white, 8)
            for q, (x, y, w, h, _area) in enumerate(stats[1 : self.QUERIES + 1]):
                logits[b, q] = torch.tensor([-20.0, np.log(0.3 / 0.7), np.log(0.25 / 0.75), -20.0])
                boxes[b, q] = torch.tensor([(x + w / 2) / tile, (y + h / 2) / tile, w / tile, h / tile])
        return SimpleNamespace(logits=logits, pred_boxes=boxes)


def test_tiles_find_each_object_once_in_screenshot_pixels() -> None:
    """The HUD is painted over in what the model sees; a square cut by a tile's inner edge counts only from the tile
    holding it whole; overlapping tiles' sightings of one square merge into one map node, in screenshot pixels."""
    torch = pytest.importorskip("torch")
    shot = np.full((1080, 1920, 3), 40, np.uint8)
    shot[500:539, 1000:1039] = 255  # whole in two tiles (x 544, y 0 and 312)
    shot[600:639, 750:789] = 255  # across the first tiles' right edge (768): whole only from x 544
    model = _SquareFinder()
    families = class_families({0: "map_node", 1: "map_node_grass", 2: "map_node_mountain", 3: "icon"})

    found = rf_detr_model.predict_tiles(model, model.processor, shot, families, torch.device("cpu"), threshold=0.35)

    assert sorted((d["label"], [round(v) for v in d["box"]]) for d in found) == [
        ("map_node_grass", [750, 600, 789, 639]),
        ("map_node_grass", [1000, 500, 1039, 539]),
    ]
    assert all(round(d["score"], 2) == 0.55 for d in found)
    assert len(model.tiles) == 8
    hud = core.hud_mask(1920, 1080) > 0
    ys, xs = np.nonzero(hud)
    x, y = int(xs[0]), int(ys[0])  # a HUD pixel; the tile holding it shows the HUD grey there
    ox, oy = next(
        (ox, oy) for ox, oy in rf_detr_model.T.tile_origins(1920, 1080) if ox <= x < ox + 768 and oy <= y < oy + 768
    )
    tile = model.tiles[rf_detr_model.T.tile_origins(1920, 1080).index((ox, oy))]
    assert tuple(tile[y - oy, x - ox]) == K.RF_DETR_HUD_FILL[::-1]  # RGB


def test_a_missing_model_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(K.RF_DETR_MODEL_ENV, str(tmp_path / "none"))
    rf_detr_model.reset_rf_detr_runtime()
    with pytest.raises(RuntimeError, match="does not exist"):
        rf_detr_model._load_runtime()


def _stub_loaders(monkeypatch: pytest.MonkeyPatch, transformers, tmp_path: Path, labels: dict[str, str]) -> None:
    """A checkpoint folder with ``labels`` and stand-in transformers loaders (they must ask for safetensors)."""
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    model = SimpleNamespace(config=SimpleNamespace(), to=lambda device: None, eval=lambda: None)

    def load_model(path, **kwargs):
        assert kwargs.get("use_safetensors") is True  # never a pickle (AGENTS.md, models)
        return model

    monkeypatch.setattr(transformers.AutoImageProcessor, "from_pretrained", lambda path: "processor")
    monkeypatch.setattr(transformers.AutoModelForObjectDetection, "from_pretrained", load_model)
    monkeypatch.setenv(K.RF_DETR_MODEL_ENV, str(tmp_path))
    monkeypatch.setenv(K.RF_DETR_DEVICE_ENV, "cpu")
    rf_detr_model.reset_rf_detr_runtime()


def test_a_checkpoint_loads_its_own_label_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The checkpoint's saved label map (its labels.json) gives its classes' families, matched by name."""
    pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    _stub_loaders(monkeypatch, transformers, tmp_path, {"0": "citadel_stone", "1": "map_node", "2": "icon"})
    try:
        runtime = rf_detr_model._load_runtime()
        assert runtime["families"] == {
            "citadel": [(0, "citadel_stone")],
            "node": [(1, "map_node")],
            "icon": [(2, "icon")],
        }
        assert rf_detr_model._load_runtime() is runtime  # loaded once
        assert str(runtime["device"]) == "cpu"
    finally:
        rf_detr_model.reset_rf_detr_runtime()


def test_a_checkpoint_of_retired_classes_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkpoint of an earlier label set would find its retired classes (City, locked stronghold) and silently drop
    them: it is refused, naming them."""
    pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    _stub_loaders(monkeypatch, transformers, tmp_path, {"0": "map_node", "1": "city", "2": "locked_stronghold"})
    try:
        with pytest.raises(RuntimeError, match="city, locked_stronghold"):
            rf_detr_model._load_runtime()
    finally:
        rf_detr_model.reset_rf_detr_runtime()


def _detect(monkeypatch, predictions: list[dict], size=(1080, 1920), names=None) -> dict:
    """detect_rf_detr with stand-ins for the model and the icon namer (``names``: the name of each icon, in order)."""
    monkeypatch.setattr(rf_detr_model, "_predict", lambda img: predictions)
    given = iter(names or [])
    monkeypatch.setattr(
        rf_detr_model, "_name_icons", lambda img, found: [dict(icon, name=next(given)) for icon in found]
    )
    return rf_detr_model.detect_rf_detr(np.zeros((*size, 3), np.uint8))


def test_citadels_halls_and_deadly_bosses_come_back_as_the_classical_landmarks(monkeypatch) -> None:
    """A citadel is a typed City at its map node; a hall a Hall at the map node under its deadly-boss icon; a
    deadly-boss icon over a map that is neither is a "Deadly boss map" (user); node classes carry their biome or
    city; a Breach stronghold with no map node inside is locked."""
    predictions = [
        {"label": "map_node_vaal", "family": "node", "box": [480.0, 480.0, 520.0, 520.0], "score": 0.9},
        {"label": "citadel_stone", "family": "citadel", "box": [460.0, 460.0, 540.0, 540.0], "score": 0.8},
        {"label": "icon", "family": "icon", "box": [483.0, 459.0, 517.0, 493.0], "score": 0.9},
        {"label": "map_node_grass", "family": "node", "box": [980.0, 680.0, 1020.0, 720.0], "score": 0.9},
        {"label": "hall", "family": "hall", "box": [890.0, 600.0, 1020.0, 725.0], "score": 0.7},
        {"label": "icon", "family": "icon", "box": [983.0, 659.0, 1017.0, 693.0], "score": 0.9},
        {"label": "map_node_desert", "family": "node", "box": [1480.0, 280.0, 1520.0, 320.0], "score": 0.9},
        {"label": "icon", "family": "icon", "box": [1483.0, 259.0, 1517.0, 293.0], "score": 0.8},
        {"label": "breach_stronghold", "family": "stronghold", "box": [1200.0, 200.0, 1350.0, 350.0], "score": 0.6},
        {"label": "map_node", "family": "node", "box": [10.0, 1060.0, 30.0, 1078.0], "score": 0.9},  # on the HUD
    ]
    result = _detect(monkeypatch, predictions, names=["MapBossSpecial"] * 3)
    landmarks = sorted((lm["kind"], lm["x"], lm["y"], lm.get("city_type")) for lm in result["landmarks"])
    assert landmarks == [
        ("City", 500.0, 500.0, "Vaal"),
        ("Deadly boss map", 1500.0, 300.0, None),
        ("Hall", 1000.0, 700.0, None),
        ("Locked stronghold", 1275.0, 275.0, None),
    ]
    nodes = {(n["x"], n["y"]): (n.get("biome"), n.get("city_type")) for n in result["nodes"]}
    assert nodes == {
        (500.0, 500.0): (None, "Vaal"),
        (1000.0, 700.0): ("grass", None),
        (1500.0, 300.0): ("desert", None),
    }  # the node on the HUD is dropped
    assert sorted(i["name"] for i in result["icons"]) == ["MapBossSpecial"] * 3


def test_a_citadel_is_a_city_at_the_map_node_inside_its_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """The City is the map node inside the citadel box (nearest its middle), wherever in the box the model put it;
    with no map node inside, the box's middle."""
    predictions = [
        {"label": "citadel_stone", "family": "citadel", "box": [460.0, 460.0, 540.0, 540.0], "score": 0.8},
        {"label": "map_node_vaal", "family": "node", "box": [492.0, 495.0, 532.0, 535.0], "score": 0.9},  # (512, 515)
        {"label": "map_node_vaal", "family": "node", "box": [580.0, 480.0, 620.0, 520.0], "score": 0.9},  # outside
        {"label": "citadel_iron", "family": "citadel", "box": [1160.0, 460.0, 1240.0, 540.0], "score": 0.7},
    ]
    result = _detect(monkeypatch, predictions)
    cities = sorted((lm["x"], lm["y"], lm["city_type"]) for lm in result["landmarks"] if lm["kind"] == "City")
    assert cities == [(512.0, 515.0, "Vaal"), (1200.0, 500.0, "Ezomyte")]


def test_left_out_icon_types_are_never_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """User: Lost Tower and Checkpoint icons are no dataset labels; an icon the namer names so is dropped (the model
    never learned them)."""
    predictions = [
        {"label": "icon", "family": "icon", "box": [100.0 + 100 * i, 100.0, 134.0 + 100 * i, 134.0], "score": 0.9}
        for i in range(3)
    ]
    result = _detect(monkeypatch, predictions, names=["LostTower", "BreachHive", "Checkpoint"])
    assert [i["name"] for i in result["icons"]] == ["BreachHive"]


def test_reveal_buttons_are_found_by_the_model_and_named_by_their_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """User: the model finds every square reveal button as one class and the classical namer names its kind (searching
    RF_DETR_BUTTON_SHIFT px around the model's middle): a ship button is an ExpeditionShip icon, a hand button makes
    the Breach stronghold beside it locked (maps inside or not), a symbol not taught yet is not reported, and an icon
    the model also reports on a button is that button."""
    predictions = [
        {"label": "reveal_button", "family": "button", "box": [266.0, 367.0, 334.0, 433.0], "score": 0.8},
        {"label": "icon", "family": "icon", "box": [285.0, 385.0, 319.0, 419.0], "score": 0.5},  # on the ship button
        {"label": "icon", "family": "icon", "box": [683.0, 383.0, 717.0, 417.0], "score": 0.9},
        {"label": "reveal_button", "family": "button", "box": [1316.0, 367.0, 1384.0, 433.0], "score": 0.9},
        {"label": "breach_stronghold", "family": "stronghold", "box": [1225.0, 175.0, 1375.0, 325.0], "score": 0.7},
        {"label": "map_node_grass", "family": "node", "box": [1280.0, 230.0, 1320.0, 270.0], "score": 0.9},
        {"label": "breach_stronghold", "family": "stronghold", "box": [425.0, 625.0, 575.0, 775.0], "score": 0.7},
        {"label": "map_node_grass", "family": "node", "box": [480.0, 680.0, 520.0, 720.0], "score": 0.9},
        {"label": "reveal_button", "family": "button", "box": [866.0, 667.0, 934.0, 733.0], "score": 0.6},
    ]
    margins = []

    def name_button(img, x, y, margin):
        margins.append(margin)
        return {300.0: "ship", 1350.0: "lock", 900.0: "unknown"}[x], 0.9

    monkeypatch.setattr(rf_detr_model, "name_button", name_button)
    result = _detect(monkeypatch, predictions, names=["BreachHive"])
    assert sorted((i["name"], i["x"], i["y"]) for i in result["icons"]) == [
        ("BreachHive", 700.0, 400.0),
        ("ExpeditionShip", 300.0, 400.0),
    ]
    assert sorted((lm["kind"], lm["x"], lm["y"]) for lm in result["landmarks"]) == [
        ("Breach stronghold", 500.0, 700.0),  # maps inside, no hand button beside it
        ("Locked stronghold", 1300.0, 250.0),  # its hand button 158 px away, though a map shows inside
    ]
    assert margins == [K.RF_DETR_BUTTON_SHIFT] * 3


def test_rf_detr_tower_keeps_its_map_node(monkeypatch) -> None:
    """As in the classical detector, a tower's map node stays in the graph flagged "tower" (paths reach it); another
    map node on the same wide tower base is a duplicate and goes; a map node farther away stays."""
    predictions = [
        {"label": "map_node_grass", "family": "node", "box": [880.0, 480.0, 920.0, 520.0], "score": 0.9},
        {"label": "map_node_grass", "family": "node", "box": [900.0, 485.0, 940.0, 525.0], "score": 0.6},
        {"label": "map_node", "family": "node", "box": [1180.0, 480.0, 1220.0, 520.0], "score": 0.9},
        {"label": "tower", "family": "tower", "box": [860.0, 285.0, 940.0, 505.0], "score": 0.8},
    ]
    result = _detect(monkeypatch, predictions)
    assert sorted((n["x"], n["y"], bool(n.get("tower"))) for n in result["nodes"]) == [
        (900.0, 500.0, True),
        (1200.0, 500.0, False),
    ]
    assert [(lm["x"], lm["y"]) for lm in result["landmarks"] if lm["kind"] == "Tower"] == [(900.0, 505.0)]


def test_predicted_walls_join_the_classical_wall_mask() -> None:
    img = np.zeros((200, 300, 3), np.uint8)
    walls = [{"family": "wall", "box": [10.0, 20.0, 60.0, 80.0]}, {"family": "node", "box": [100, 100, 140, 140]}]
    mask = rf_detr_model._wall_mask(img, walls)
    assert mask[50, 30] and not mask[120, 120] and not mask[5, 5]
