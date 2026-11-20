"""tools/import_poe2db_art.py: poe2db art becomes icon pictures only for the types the detector cannot name yet."""

import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

from grand_project import icon_refs
from grand_project.detect import constants as K
from grand_project.detect import models
from tools import import_poe2db_art


def _names(db: Path) -> dict[str, int]:
    c = sqlite3.connect(str(db))
    rows = dict(c.execute("SELECT name, COUNT(*) FROM badge_refs GROUP BY name").fetchall())
    c.close()
    return rows


def test_art_is_added_only_for_types_without_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    art = tmp_path / "art"
    art.mkdir()
    for name in ("inner__BreachHive.webp", "full__RogueExile.webp", "inner__WisdomsTeachings.webp"):
        shutil.copy(K.ICON_ART_DIR / name, art / name)
    shutil.copy(K.ICON_ART_DIR / "inner__BreachHive.webp", art / "inner__NotAType.webp")
    db = tmp_path / "icons.sqlite3"
    conn = icon_refs._db(db)
    icon_refs.add("BreachHive", np.full((icon_refs.SIZE, icon_refs.SIZE, 3), 90, np.uint8), conn)  # an on-screen one
    conn.commit()
    conn.close()
    # the stored badges model's own labelled pictures name WisdomsTeachings (only its names are read here)
    models.save_model("badges", {"names": ["WisdomsTeachings"], "F": np.zeros((1, 3), np.float32)}, {}, path=db)
    monkeypatch.setattr(import_poe2db_art, "ART", art)
    monkeypatch.setattr(import_poe2db_art, "TRUTH_SETS", [])
    monkeypatch.setattr(sys, "argv", ["import_poe2db_art", str(db)])

    import_poe2db_art.main()

    assert _names(db) == {"BreachHive": 1, "RogueExile": 1}  # full art: one size; the other two have pictures
    out = capsys.readouterr().out
    assert "NotAType is not an icon type" in out
    assert "art pictures added for 1 types: RogueExile" in out
