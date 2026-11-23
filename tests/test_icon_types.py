"""The icon types (ICON_INFO): each has its art, a dataset class that maps back to it, and the classical detector can
name it - the dataset annotator offers every type as a label (user: every poe2db map content icon)."""

import sqlite3

import numpy as np

from grand_project import icon_refs
from grand_project.detect import constants as K
from grand_project.detect import models
from grand_project.detect.icon_types import dataset_icon_types, file_picture, icon_class, icon_picture, icon_type


def _nameable() -> set[str]:
    """The types the classical detector can output: the icon database's pictures and the badges model's own labelled
    pictures (detect/badges.py names icons by both), the icons with their own template, and the ship markers
    (found by their square button, landmarks.ship_markers)."""
    # as_uri percent-encodes the path ("#", "?" or "%" in a folder name would break a raw one)
    c = sqlite3.connect(f"{icon_refs.DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    stored = {r[0] for r in c.execute("SELECT DISTINCT name FROM badge_refs")}
    c.close()
    return stored | set(models.load_model("badges")["names"]) | set(K.SPECIAL_ICONS) | {"ExpeditionShip"}


def test_every_art_file_is_an_icon_type() -> None:
    """references/poe2db_icons holds "full__<Type>.webp" / "inner__<Type>.webp" (a second picture: "<Type>2")."""
    files = sorted(K.ICON_ART_DIR.glob("*.webp"))
    assert files
    kinds = {f.stem.split("__", 1)[0] for f in files}
    names = {f.stem.split("__", 1)[1].rstrip("2") for f in files}
    assert kinds <= {"full", "inner"}
    assert sorted(names - set(K.ICON_INFO)) == []
    assert sorted(names & K.ICON_LEGACY) == []


def test_every_icon_type_has_a_picture() -> None:
    """The annotator shows each type's picture next to its label (its art, else a stored on-screen picture)."""
    assert [name for name in dataset_icon_types() if icon_picture(name, 24) is None] == []
    picture = icon_picture("BreachHive", 24)
    assert picture.shape == (24, 24, 4) and picture.dtype == np.uint8
    assert picture[..., 3].min() == 0 < picture[..., 3].max()  # a round icon on a transparent square


def test_every_icon_type_can_be_named_by_the_classical_detector() -> None:
    """A type without any picture can never be named, so the annotator's classical boxes would never carry it
    (tools/import_poe2db_art.py adds the art of such types)."""
    nameable = _nameable()
    assert [name for name in dataset_icon_types() if name not in nameable] == []
    assert sorted(K.ICON_LEGACY & nameable) == []  # old names are no longer given


def test_dataset_classes_are_unique_and_map_back() -> None:
    """The class loses capitals ("icon_abyssoverrun"); icon_type gives the program's spelling back."""
    classes = [icon_class(name) for name in K.ICON_INFO]
    assert len(set(classes)) == len(classes)
    assert [name for name in K.ICON_INFO if icon_type(icon_class(name)) != name] == []
    assert icon_class("Map Boss") == "icon_map_boss"
    assert icon_type("icon_abyssoverrun") == "AbyssOverrun"
    assert icon_type("icon_not_a_type") is None


def test_dataset_types_keep_the_table_order() -> None:
    types = dataset_icon_types()
    assert types == [name for name in K.ICON_INFO if name in types]
    assert "Unidentified" not in types
    assert not set(types) & K.ICON_LEGACY


def test_an_empty_or_broken_picture_file_is_no_picture(tmp_path) -> None:
    """OpenCV refuses an empty buffer with an error: such a file is no picture, as a broken one is."""
    empty, broken = tmp_path / "empty.webp", tmp_path / "broken.webp"
    empty.write_bytes(b"")
    broken.write_bytes(b"not a picture")
    assert file_picture(empty, 34) is None and file_picture(broken, 34) is None
