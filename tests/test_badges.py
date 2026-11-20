"""The classical icon naming step both detectors use (grand_project/detect/badges.py: name_found_icons, naming_book)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from grand_project import icon_refs
from grand_project.detect import badges
from grand_project.detect import constants as K

IMG = np.zeros((1080, 1920, 3), np.uint8)


@pytest.fixture
def namer(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stand-ins for the pictures: one stored picture, the given special icons, and names by place (``names``)."""
    state: dict = {"names": {}, "special": [], "seen": None, "water": True}
    monkeypatch.setattr(icon_refs, "refs", lambda: SimpleNamespace(names=["Stored"], F=np.ones((1, 4), np.float32)))
    monkeypatch.setattr(badges, "special_icons", lambda img: [dict(icon) for icon in state["special"]])
    monkeypatch.setattr(badges, "_in_water", lambda img, x, y: state["water"])

    def name_badge(img, x, y, names, F):
        state["seen"] = (list(names), F.shape)
        return state["names"].get((x, y), "Unidentified"), 0.1

    monkeypatch.setattr(badges, "name_badge", name_badge)
    return state


def test_icons_are_named_from_the_stored_and_the_icon_models_pictures(namer: dict) -> None:
    book = {"names": ["Delirium", "MapBossSpecial"], "F": np.zeros((2, 4), np.float32)}
    namer["names"] = {(100.0, 100.0): "MapBossSpecial"}
    out = badges.name_found_icons(IMG, [{"x": 100.0, "y": 100.0, "score": 0.7, "source": "rf-detr"}], book)
    assert out == [{"x": 100.0, "y": 100.0, "score": 0.7, "source": "rf-detr", "name": "MapBossSpecial", "dist": 0.1}]
    assert namer["seen"] == (["Stored", "Delirium", "MapBossSpecial"], (3, 4))  # both picture sets
    badges.name_found_icons(IMG, [{"x": 100.0, "y": 100.0, "score": 0.7}], {"names": [], "F": np.zeros((0, 0))})
    assert namer["seen"] == (["Stored"], (1, 4))  # no icon model: the stored pictures alone


def test_special_icons_replace_found_icons_on_them(namer: dict) -> None:
    """Icons with their own rim are found and named by their whole-icon template, and win over a found icon there."""
    namer["special"] = [{"x": 500.0, "y": 300.0, "score": 0.9, "name": "AbyssalDepths", "dist": 0.0}]
    found = [{"x": 500.0 + K.BADGE_NMS - 1, "y": 300.0, "score": 0.9}, {"x": 900.0, "y": 300.0, "score": 0.9}]
    out = badges.name_found_icons(IMG, found, {"names": [], "F": np.zeros((0, 0))})
    assert [(icon["name"], icon["x"]) for icon in out] == [("AbyssalDepths", 500.0), ("Unidentified", 900.0)]


def test_the_classical_rules_apply(namer: dict) -> None:
    """User: a weak circle named an influence is terrain (only with the rim finder's score), Expedition only appears
    in water, and a picture of "not an icon" drops the icon."""
    namer["names"] = {
        (100.0, 100.0): "ForestInfluence",
        (200.0, 100.0): "Expedition",
        (300.0, 100.0): icon_refs.NOT_A_BADGE,
    }
    namer["water"] = False
    found = [{"x": float(x), "y": 100.0, "score": 0.5} for x in (100, 200, 300)]
    book = {"names": [], "F": np.zeros((0, 0))}
    assert [icon["name"] for icon in badges.name_found_icons(IMG, found, book)] == ["Unidentified"]
    loose = badges.name_found_icons(IMG, found, book, influence_min=None)  # a finder with a score of its own
    assert [icon["name"] for icon in loose] == ["ForestInfluence", "Unidentified"]


def test_the_naming_book_is_the_icon_models_loaded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    models: dict = {}
    loads = []
    book = {"names": ["Delirium"], "F": np.zeros((1, 4), np.float32)}
    monkeypatch.setattr(badges, "_models", models)
    monkeypatch.setattr(badges, "load_model", lambda name: loads.append(name) or book)
    assert badges.naming_book() is book and badges.naming_book() is book
    assert loads == ["badges"] and models["badges"] is book  # where the classical detector keeps it
    models.clear()
    monkeypatch.setattr(badges, "load_model", lambda name: None)
    assert badges.naming_book()["names"] == [] and "badges" not in models  # no icon model: no pictures of its own
