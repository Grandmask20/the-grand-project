"""The dataset's label registry (grand_project/detect/labels.py over RF_DETR_LABEL_INFO): what each label means, how
it is exported, and how a further fine-tuned model keeps its class rows."""

import pytest

from grand_project import cities
from grand_project.detect import constants as K
from grand_project.detect import labels as L
from grand_project.detect.icon_types import dataset_icon_types, icon_class


def test_registry_entries_are_complete_and_their_keys_unique() -> None:
    entries = K.RF_DETR_LABEL_INFO
    for label, entry in entries.items():
        assert {"title", "family", "rule", "color"} <= set(entry), label
        assert len(entry["color"]) == 3 and all(0 <= c <= 255 for c in entry["color"]), label
    keys = [entry["key"] for entry in entries.values() if "key" in entry]
    assert len(keys) == len(set(keys))
    assert len({entry["color"] for entry in entries.values()}) == len(entries)


def test_node_classes_name_one_biome_or_one_city_each() -> None:
    """User: one node class per biome (grass, desert, water, mountain) and per city area; map_node when unknown."""
    nodes = L.node_labels()
    assert nodes[0] == "map_node"
    biomes = {L.biome(label) for label in nodes} - {None}
    assert biomes == set(K.BIOME_GROUND.values()) == {"grass", "desert", "water", "mountain"}
    assert {L.city_type(label) for label in nodes} - {None} == set(cities.TYPES)
    for label in nodes[1:]:
        assert (L.biome(label) is None) != (L.city_type(label) is None), label
        assert L.parent(label) == "map_node"
    assert L.node_label() == "map_node"
    assert L.node_label(biome="desert") == "map_node_desert"
    assert L.node_label(biome="grass", city_type="Vaal") == "map_node_vaal"  # a city's area wins
    with pytest.raises(KeyError):
        L.node_label(biome="lava")


def test_citadels_are_named_after_their_city_type() -> None:
    """User: Iron citadel = Ezomyte, Copper citadel = Faridun (desert), Stone citadel = Vaal."""
    assert L.citadel_label("Ezomyte") == "citadel_iron"
    assert L.citadel_label("Faridun") == "citadel_copper"
    assert L.citadel_label("Vaal") == "citadel_stone"
    for label in ("citadel_iron", "citadel_copper", "citadel_stone"):
        assert L.landmark_kind(label) == "City" and L.family(label) == "citadel"


def test_every_icon_type_is_found_as_one_icon_class() -> None:
    """User: the detector finds icons as `icon` and the classical namer names them, the deadly-boss icon too (the
    program's city, hall and deadly-boss rules read the name, as they read the classical detector's)."""
    assert L.export_class("icon_breachhive") == "icon"
    assert L.export_class("icon_unidentified") == "icon"
    assert L.export_class("icon_mapbossspecial") == "icon"
    assert L.export_class("icon") == "icon"
    assert L.export_class("custom") == "custom"
    assert L.family("icon_breachhive") == "icon" and L.family("icon_mapbossspecial") == "icon"
    assert [label for label, entry in K.RF_DETR_LABEL_INFO.items() if entry["family"] == "icon"] == ["icon"]


def test_left_out_icon_types_are_no_labels() -> None:
    """User: the Lost Tower and Checkpoint icons are not labelled, exported or reported by the RF-DETR detector; the
    Expedition ship is no icon label either (it is a reveal button)."""
    left_out = {"LostTower", "Checkpoint", "ExpeditionShip"}
    assert left_out <= K.RF_DETR_ICON_EXCLUDED
    assert not left_out & set(dataset_icon_types())
    assert L.export_class("icon_losttower") is None and L.export_class("icon_checkpoint") is None
    assert L.export_class("icon_expeditionship") is None
    assert not L.known("icon_losttower") and L.known("icon_breachhive") and L.known("citadel_iron")
    assert not L.known("custom")
    named = L.annotator_labels(named_icons=True, paths=True, walls=True)
    assert not {"icon_losttower", "icon_checkpoint", "icon_expeditionship"} & set(named)


def test_reveal_buttons_are_one_class_and_strongholds_one_structure() -> None:
    """User: the square framed buttons that reveal maps (a locked stronghold's hand, the Expedition ship ...) are one
    class whatever their kind (the classical namer names it); a Breach stronghold is one class, locked or open."""
    assert L.family("reveal_button") == "button" and L.export_class("reveal_button") == "reveal_button"
    assert L.landmark_kind("reveal_button") is None  # no landmark of its own: it makes its stronghold locked
    assert "locked_stronghold" not in K.RF_DETR_LABEL_INFO
    strongholds = [label for label, entry in K.RF_DETR_LABEL_INFO.items() if entry["family"] == "stronghold"]
    assert strongholds == ["breach_stronghold"]
    for named in (False, True):
        labels = L.annotator_labels(named_icons=named)
        assert labels.count("reveal_button") == 1 and "icon_expeditionship" not in labels


def test_dataset_classes_are_the_registry_then_other_labels_in_use() -> None:
    classes = L.dataset_classes()
    assert classes == [label for label, entry in K.RF_DETR_LABEL_INFO.items() if not entry.get("optional")]
    assert len(classes) == 16 and "path" not in classes
    used = ["icon_breachhive", "path", "zzz", "icon_losttower", "map_node"]
    # a used optional label takes its registry place, a reviewer's own label comes last, a left-out icon never
    assert L.dataset_classes(used) == [*classes, "path", "zzz"]


def test_annotator_labels_offer_every_icon_type_when_named() -> None:
    named = L.annotator_labels(named_icons=True)
    assert "icon" not in named and named[-len(dataset_icon_types()) :] == [icon_class(n) for n in dataset_icon_types()]
    plain = L.annotator_labels(named_icons=False)
    assert [label for label in plain if label.startswith("icon")] == ["icon"]  # user: no icon types when unnamed
    assert "path" not in plain and "fortress_wall" not in plain  # user: only with their options
    assert L.annotator_labels(named_icons=False, paths=True)[-2:] == ["path", "icon"]
    walls = L.annotator_labels(named_icons=False, walls=True)
    assert "fortress_wall" in walls and "path" not in walls


def test_warm_start_rows_follow_names_and_parents() -> None:
    """--init-from: a class the old model had keeps its row, a node biome class starts from map_node's, a class with
    no row to start from (a new one) starts fresh."""
    old = ["map_node", "tower", "citadel_stone", "hall", "icon"]
    new = [
        "map_node",
        "map_node_grass",
        "map_node_vaal",
        "citadel_stone",
        "hall",
        "tower",
        "icon",
        "citadel_iron",
    ]
    assert L.warm_start_rows(old, new) == [0, 0, 0, 2, 3, 1, 4, None]
