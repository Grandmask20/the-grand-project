"""tools/split_icon_type.py: the review sheet."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from grand_project import icon_refs
from grand_project.detect.constants import ICON_ART_DIR
from tools import split_icon_type as S


def _width() -> int:
    """A sheet row's width: _COLS cells of a picture drawn _TILE times larger plus its margins."""
    return S._COLS * (icon_refs.SIZE * S._TILE + 40)


def test_a_split_into_more_types_than_a_row_holds_wraps_the_art_row(tmp_path: Path) -> None:
    """The new types' art takes as many rows as it needs, each as wide as the pictures' rows."""
    names = sorted({f.stem.split("__", 1)[1].rstrip("2") for f in ICON_ART_DIR.glob("full__*.webp")})[: S._COLS + 1]
    crop = np.zeros((icon_refs.SIZE, icon_refs.SIZE, 3), np.uint8)
    matches = [S.Match(f"#{i}", crop, names[0], [0.1] * len(names), False) for i in range(3)]
    sheet = tmp_path / "sheet.png"
    S.sheet(sheet, names, matches)
    image = cv2.imread(str(sheet))
    assert image.shape[1] == _width()
    assert image.shape[0] == 3 * (icon_refs.SIZE * S._TILE + 36)  # two rows of art, one of pictures


def test_up_to_a_rows_worth_of_types_keeps_one_art_row(tmp_path: Path) -> None:
    names = sorted({f.stem.split("__", 1)[1].rstrip("2") for f in ICON_ART_DIR.glob("full__*.webp")})[:2]
    sheet = tmp_path / "sheet.png"
    S.sheet(sheet, names, [])
    image = cv2.imread(str(sheet))
    assert image.shape == (icon_refs.SIZE * S._TILE + 36, _width(), 3)
