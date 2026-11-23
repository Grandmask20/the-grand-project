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


def test_a_sheet_that_cannot_be_written_stops_before_any_relabelling(tmp_path: Path, monkeypatch) -> None:
    names = sorted({f.stem.split("__", 1)[1].rstrip("2") for f in ICON_ART_DIR.glob("full__*.webp")})[:2]
    monkeypatch.setattr(S.cv2, "imwrite", lambda *args: False)  # OpenCV says so by its result, not an error
    try:
        S.sheet(tmp_path / "sheet.png", names, [])
    except OSError as error:
        assert "could not write the review sheet" in str(error)
    else:
        raise AssertionError("no OSError")


def test_a_database_without_pictures_gives_none_and_its_book_is_still_split(tmp_path: Path) -> None:
    """A database holding only stored models has no ``badge_refs`` table: no pictures from it, no error."""
    import sqlite3

    db = tmp_path / "models_only.sqlite3"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE detector_models (name TEXT, blob BLOB, info TEXT, created TEXT)")
    c.commit()
    c.close()
    assert S.stored_pictures(db, "Old", {}, 0.02) == []


def test_a_truth_file_is_rewritten_whole_with_its_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "truth_key.json"
    path.write_bytes(b'{\r\n "badges": {}\r\n}')
    S._write_json(path, {"badges": {"B1": {"detector": "New", "row": "Old"}}})
    assert b"\r\n" in path.read_bytes() and not list(tmp_path.glob(".*.new"))


def test_a_renamed_icon_call_is_saved_under_its_new_name(tmp_path: Path) -> None:
    """After a split renamed a badge's call, ``truth save`` still finds its review row (``row``) and keeps the new
    name for it (it failed with a KeyError: no row is named after the new type)."""
    import json
    from types import SimpleNamespace

    from grand_project import truth

    key = {
        "shots": {"S1": {"name": "shot1.png"}},
        "maps": {},
        "landmarks": {},
        "badges": {"B1": {"shot": "S1", "x": 100, "y": 100, "detector": "ArcaneHordes", "row": "ArcaneOrProsperous"}},
        "rows": {"R1": "ArcaneOrProsperous"},
    }
    (tmp_path / "truth_key.json").write_text(json.dumps(key), encoding="utf-8")
    labels = tmp_path / "labels.txt"
    labels.write_text("", encoding="utf-8")
    assert truth.cmd_save(SimpleNamespace(out=str(tmp_path), labels=str(labels))) == 0
    saved = json.loads((tmp_path / "truth.json").read_text(encoding="utf-8"))
    assert [b["name"] for b in saved["shot1.png"]["badges"]] == ["ArcaneHordes"]


def test_a_truth_icon_changed_meanwhile_stops_before_anything_is_written(tmp_path: Path, monkeypatch) -> None:
    """The truth file is read again before any write: an icon moved since it was matched stops the split, the
    databases and the truth file untouched."""
    import json

    import pytest

    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"s.png": {"badges": [{"id": "B1", "name": "Old", "x": 105, "y": 100}]}}))
    before = truth.read_bytes()
    match = S.Match("truth B1", None, "New", [0.1], False)
    monkeypatch.setattr(S, "art_features", lambda name: np.zeros((1, 1), np.float32))
    monkeypatch.setattr(S, "stored_pictures", lambda *a: [])
    monkeypatch.setattr(S, "book_pictures", lambda *a: (None, []))
    monkeypatch.setattr(S, "truth_pictures", lambda *a: [(truth, "s.png", 0, match, ("B1", "Old", 100, 100))])
    monkeypatch.setattr(S, "sheet", lambda *a: None)
    monkeypatch.setattr(S.models, "save_model", lambda *a, **k: pytest.fail("a database was written"))
    with pytest.raises(SystemExit, match="changed while the split ran"):
        S.main(["Old", "New", "--sheet", str(tmp_path / "sheet.png")])
    assert truth.read_bytes() == before


def test_a_truth_saved_while_the_databases_were_relabelled_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    """Both truth files are checked against their reread bytes right before either is replaced: the truth labeller
    saving its key meanwhile stops the split there, that edit kept."""
    import json
    import sqlite3

    import pytest

    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"s.png": {"badges": [{"id": "B1", "name": "Old", "x": 100, "y": 100}]}}))
    key_file = tmp_path / "truth_key.json"
    key_file.write_text(json.dumps({"badges": {"B1": {"detector": "Old"}}}))
    db = tmp_path / "refs.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE detector_models (name TEXT, info TEXT)")
        c.execute("INSERT INTO detector_models VALUES ('badges', '{}')")
    before = truth.read_bytes()
    match = S.Match("truth B1", None, "New", [0.1], False)
    book = (({"names": ["Old"]}), [(0, S.Match("book #0", None, "New", [0.1], False))])
    monkeypatch.setattr(S, "art_features", lambda name: np.zeros((1, 1), np.float32))
    monkeypatch.setattr(S, "stored_pictures", lambda *a: [])
    monkeypatch.setattr(S, "book_pictures", lambda *a: book)
    monkeypatch.setattr(S, "truth_pictures", lambda *a: [(truth, "s.png", 0, match, ("B1", "Old", 100, 100))])
    monkeypatch.setattr(S, "sheet", lambda *a: None)
    # the labeller saves its key while the stored model is relabelled
    monkeypatch.setattr(S.models, "save_model", lambda *a, **k: key_file.write_text('{"badges": {}}'))
    with pytest.raises(SystemExit, match="truth_key.json changed while the split ran"):
        S.main(["Old", "New", "--db", str(db), "--sheet", str(tmp_path / "sheet.png")])
    assert truth.read_bytes() == before and key_file.read_text() == '{"badges": {}}'
