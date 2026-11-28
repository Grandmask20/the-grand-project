"""The dataset's labels: the registry (``RF_DETR_LABEL_INFO``) and the icon types (``ICON_INFO``) as one vocabulary.

The annotator stores a box under a *label*: a registry label (``map_node_grass``, ``citadel_stone``, ``hall`` ...),
``icon_<type>`` for a named icon, or a reviewer's own label. The exporter turns each label into a detector *class*
(``export_class``): registry labels stay themselves, every icon type becomes ``icon`` (the classical namer names it,
``badges.name_found_icons``, as it names the classical finder's icons), and an icon type the dataset leaves out
(``RF_DETR_ICON_EXCLUDED``: the Lost Tower and Checkpoint icons; the Expedition ship, a ``reveal_button``) is not
exported as an icon. The square framed buttons that reveal maps (a locked stronghold's hand, the Expedition ship) are
one class, ``reveal_button``, named by their symbol (``cities.name_button``). Classes of one *family* are alternatives
for one object (a map node is exactly one of the node classes), so inference scores and suppresses them together.

Changing a label (adding, renaming or splitting one, or giving it a new box rule) means detecting the screenshots again
("Rerun all" in the annotator) and reviewing them again; a model fine-tuned further with ``--init-from`` keeps the rows
of the classes it already had by name (``warm_start_rows``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import constants as K
from .icon_types import dataset_icon_types, icon_class, icon_type

GENERIC_ICON = "icon"
"""The detector class of every icon type it does not keep as a class of its own."""


def info(label: str) -> dict[str, Any]:
    """A label's registry entry: its own, else its detector class's (an icon type's is ``icon``'s), else ``{}``."""
    entry = K.RF_DETR_LABEL_INFO.get(label)
    if entry is None:
        cls = export_class(label)
        entry = K.RF_DETR_LABEL_INFO.get(cls) if cls is not None else None
    return entry or {}


def export_class(label: str) -> str | None:
    """The detector class a stored label is exported as.

    Args:
        label: A stored label.

    Returns:
        The label itself for a registry label or a reviewer's own label; ``icon`` for an icon type; None for an icon
        type the dataset leaves out (``RF_DETR_ICON_EXCLUDED``). An ``icon_`` label of no known type (one the icon
        types no longer have) stays itself, so the export reports it instead of hiding it in ``icon``.
    """
    if label in K.RF_DETR_LABEL_INFO:
        return label
    if label.startswith(f"{GENERIC_ICON}_") and (name := icon_type(label)) is not None:
        return None if name in K.RF_DETR_ICON_EXCLUDED else GENERIC_ICON
    return label


def known(label: str) -> bool:
    """Whether a label is one of the dataset's: a registry label or a dataset icon type (``dataset_icon_types``)."""
    if label in K.RF_DETR_LABEL_INFO:
        return True
    name = icon_type(label)
    return name is not None and name in dataset_icon_types()


def family(label: str) -> str | None:
    """The family of a label's detector class (node, citadel, hall, tower, stronghold, button, icon), or None for a
    reviewer's own label."""
    return info(label).get("family")


def is_node(label: str) -> bool:
    """Whether a label marks a map node (one of the node classes)."""
    return family(label) == "node"


def node_labels() -> list[str]:
    """The node classes in export order (``map_node`` first)."""
    return [label for label, entry in K.RF_DETR_LABEL_INFO.items() if entry["family"] == "node"]


def node_label(biome: str | None = None, city_type: str | None = None) -> str:
    """The node class of a map node: its city's area if it lies in one, else its biome, else plain ``map_node``.

    Args:
        biome: "grass", "desert", "water", "mountain" or None.
        city_type: "Ezomyte", "Vaal", "Faridun" (cities.TYPES) or None.

    Returns:
        The class name.

    Raises:
        KeyError: An unknown biome or city type.
    """
    nodes = {label: K.RF_DETR_LABEL_INFO[label] for label in node_labels()}
    if city_type is not None:
        return next(label for label, entry in nodes.items() if entry.get("city_type") == city_type)
    if biome is not None:
        found = [label for label, entry in nodes.items() if entry.get("biome") == biome]
        if not found:
            raise KeyError(biome)
        return found[0]
    return "map_node"


def citadel_label(city_type: str) -> str:
    """The citadel class of a city type, e.g. "Vaal" -> "citadel_stone".

    Raises:
        StopIteration: An unknown city type.
    """
    return next(
        label
        for label, entry in K.RF_DETR_LABEL_INFO.items()
        if entry["family"] == "citadel" and entry.get("city_type") == city_type
    )


def city_type(label: str) -> str | None:
    """The city type a node or citadel class names ("Vaal" ...), else None."""
    return K.RF_DETR_LABEL_INFO.get(label, {}).get("city_type")


def biome(label: str) -> str | None:
    """The biome a node class names ("grass" ...), else None (city-area classes name a city instead)."""
    return K.RF_DETR_LABEL_INFO.get(label, {}).get("biome")


def landmark_kind(label: str) -> str | None:
    """The classical landmark kind a class becomes ("City", "Hall", "Tower" ...), else None."""
    return K.RF_DETR_LABEL_INFO.get(label, {}).get("landmark")


def parent(label: str) -> str | None:
    """The class a new class's detector row starts from when a checkpoint is fine-tuned further (``--init-from``)."""
    return K.RF_DETR_LABEL_INFO.get(label, {}).get("parent")


def annotator_labels(*, named_icons: bool) -> list[str]:
    """The labels the editor offers.

    Registry labels first, then the icon labels: with named icons every icon type (``dataset_icon_types``), else the
    one ``icon`` label (user: no icon types when icons are not named).
    """
    labels = [label for label, entry in K.RF_DETR_LABEL_INFO.items() if entry["family"] != "icon"]
    if named_icons:
        labels.extend(icon_class(name) for name in dataset_icon_types())
    else:
        labels.append(GENERIC_ICON)
    return labels


def dataset_classes(used: Iterable[str] = ()) -> list[str]:
    """The detector classes of an export, in id order.

    Every registry label, then the classes of the other labels in use (a reviewer's own labels) in alphabetical
    order, so their ids do not depend on which screenshot uses them first.

    Args:
        used: The stored labels in use.

    Returns:
        The class names; a class's id is its position.
    """
    exported = {cls for cls in (export_class(label) for label in used) if cls is not None}
    classes = list(K.RF_DETR_LABEL_INFO)
    known = set(classes)
    classes.extend(sorted(cls for cls in exported if cls not in known))
    return classes


def warm_start_rows(old_names: list[str], new_names: list[str]) -> list[int | None]:
    """Which class row of an earlier checkpoint each class of a new one starts from (``--init-from``).

    A class the old checkpoint had keeps its row; a new class with a ``parent`` the old checkpoint had (a node biome
    class from ``map_node``) starts from its parent's row; any other class starts fresh (None).

    Args:
        old_names: the old checkpoint's class names, by id.
        new_names: the new checkpoint's class names, by id.

    Returns:
        Per new class id, the old class id whose row it copies, or None.
    """
    old_rows: dict[str, int] = {}
    for index, name in enumerate(old_names):
        old_rows.setdefault(name, index)
    out: list[int | None] = []
    for name in new_names:
        row = old_rows.get(name)
        if row is None and (up := parent(name)) is not None:
            row = old_rows.get(up)
        out.append(row)
    return out


__all__ = [
    "GENERIC_ICON",
    "annotator_labels",
    "biome",
    "citadel_label",
    "city_type",
    "dataset_classes",
    "export_class",
    "family",
    "info",
    "is_node",
    "known",
    "landmark_kind",
    "node_label",
    "node_labels",
    "parent",
    "warm_start_rows",
]
