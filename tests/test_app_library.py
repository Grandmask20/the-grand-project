"""Saved atlases, their cards and the computer's folders (app.library and its AtlasSession part)."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from grand_project.app import library
from grand_project.app.constants import ATLAS_THUMB
from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def session():
    s = AtlasSession(settings={}, worker=False)
    yield s
    s.shutdown()


def test_same_file_and_card_picture_path(tmp_path):
    (tmp_path / "a").mkdir()
    assert library.same_file(tmp_path / "a" / ".." / "x.json", tmp_path / "x.json")
    assert not library.same_file(tmp_path / "x.json", tmp_path / "y.json")
    assert library.thumb_file(tmp_path / "run.json") == tmp_path / "run_files" / "run_thumb.png"


@pytest.mark.parametrize("shape", [(100, 1000, 3), (1000, 100, 3), (5, 5, 3)])
def test_card_picture_is_the_map_image_shrunk_and_centred(shape):
    canvas = np.full(shape, 200, np.uint8)
    out = library.make_thumb(canvas)
    tw, th = ATLAS_THUMB
    assert out.shape == (th, tw, 3)
    inside = np.argwhere(out[..., 0] == 200)
    (y0, x0), (y1, x1) = inside.min(0), inside.max(0)
    assert abs(y0 - (th - 1 - y1)) <= 1 and abs(x0 - (tw - 1 - x1)) <= 1  # centred
    assert out[0, 0, 0] == 24 or (y0 == 0 and x0 == 0)  # the background is dark where the map isn't


def test_atlas_numbers_count_what_the_map_shows():
    data = {"final": {"stats": {"nodes_kept": 12}, "icons": [{}, {}]}, "icons": [{}] * 9, "frames": [{}] * 4}
    assert library.atlas_numbers(data) == {"maps": 12, "icons": 2, "shots": 4}
    assert library.atlas_numbers({"icons": [{}] * 3}) == {"maps": 0, "icons": 3, "shots": 0}  # not checked yet


def test_atlas_data_paths_never_hold_the_screenshots(tmp_path):
    j = tmp_path / "atlas.json"
    j.write_text("{}")
    (tmp_path / "atlas_frames").mkdir()
    (tmp_path / "atlas_files").mkdir()
    (tmp_path / "shot.png").write_bytes(b"x")
    got = {p.name for p in library.atlas_data_paths(j)}
    assert got == {"atlas.json", "atlas_frames", "atlas_files"}


def test_screenshot_folder_of_an_atlas(tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "a.png").write_bytes(b"x")
    j = tmp_path / "atlas.json"
    j.write_text(json.dumps({"frames": [{"path": str(shots / "a.png")}]}))
    assert library.atlas_shot_dir(j).resolve() == shots.resolve()
    for bad in ("{}", '{"frames": []}', "not json", '{"frames": ["a.png"]}'):
        j.write_text(bad)
        assert library.atlas_shot_dir(j) is None
    assert library.atlas_shot_dir(tmp_path / "missing.json") is None


def test_list_dir_lists_folders_first_then_pictures_and_atlases(tmp_path):
    (tmp_path / "b_folder").mkdir()
    (tmp_path / "A_folder").mkdir()
    (tmp_path / ".hidden").mkdir()
    for name in ("z.png", "a.json", "notes.txt", "c.JPG"):
        (tmp_path / name).write_bytes(b"12345")
    got = library.list_dir(str(tmp_path))
    assert [e["name"] for e in got["entries"]] == ["A_folder", "b_folder", "a.json", "c.JPG", "z.png"]
    assert got["path"] == str(tmp_path.resolve()) and got["parent"] == str(tmp_path.resolve().parent)
    assert not got["truncated"]
    files = [e for e in got["entries"] if not e["dir"]]
    assert all(e["size"] == 5 for e in files)
    only_dirs = library.list_dir(str(tmp_path), files=False)
    assert [e["name"] for e in only_dirs["entries"]] == ["A_folder", "b_folder"]


def test_list_dir_cuts_long_folders_and_refuses_missing_ones(tmp_path, monkeypatch):
    for i in range(5):
        (tmp_path / f"d{i}").mkdir()
    monkeypatch.setattr(library, "FS_LIST_MAX", 3)
    got = library.list_dir(str(tmp_path))
    assert len(got["entries"]) == 3 and got["truncated"]
    with pytest.raises(ValueError):
        library.list_dir(str(tmp_path / "missing"))


def test_list_dir_defaults_to_the_home_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(library.Path, "home", classmethod(lambda cls: tmp_path))
    assert library.list_dir(None)["path"] == str(tmp_path.resolve())
    assert library.list_dir("")["path"] == str(tmp_path.resolve())


def test_remembered_atlases_drop_missing_files_and_keep_names(session, tmp_path):
    (tmp_path / "one").mkdir()
    path, _pts, _img = make_atlas(tmp_path / "one")
    session.remember_atlas(path, "Mine")
    session.settings["atlases"].append({"name": "gone", "json": str(tmp_path / "gone" / "atlas.json")})
    assert [a["name"] for a in session.known_atlases()] == ["Mine"]
    session.rename_atlas(str(path), "   ")  # blank: kept
    assert session.known_atlases()[0]["name"] == "Mine"


def test_cards_read_the_numbers_of_atlases_not_opened(session, tmp_path):
    (tmp_path / "one").mkdir()
    path, _pts, _img = make_atlas(tmp_path / "one")
    session.remember_atlas(path)
    assert "numbers" not in session.known_atlases()[0]
    session._read_numbers([str(path)])  # what the card reader does in the background
    numbers = session.known_atlases()[0]["numbers"]
    assert numbers["shots"] == 1 and numbers["maps"] >= 0


def test_card_picture_written_from_the_map_image(session, tmp_path):
    j = tmp_path / "atlas.json"
    session.write_thumb(j, np.full((300, 600, 3), 90, np.uint8))
    assert session.thumb_exists(j)


def test_delete_atlas_removes_its_data_and_keeps_the_screenshots(session, tmp_path):
    (tmp_path / "one").mkdir()
    path, _pts, _img = make_atlas(tmp_path / "one")
    shot = tmp_path / "one" / "a.png"
    shot.write_bytes(b"screenshot")
    session.open_atlas(path)
    assert session.delete_atlas(str(path)) == []
    assert not path.exists() and shot.exists()
    assert session.atlas is None and session.known_atlases() == []


def test_open_folder_without_an_atlas(session, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        session.open_folder(empty)  # nothing to open or build
    with pytest.raises(ValueError):
        session.open_folder(tmp_path / "missing")
    shots = tmp_path / "shots"
    shots.mkdir()
    for n in ("1.png", "2.png"):
        (shots / n).write_bytes(b"x")
    assert session.open_folder(shots) == {"create": 2}


def test_create_from_folder_starts_an_atlas_and_adds_its_screenshots(session, tmp_path, monkeypatch):
    shots = tmp_path / "shots"
    shots.mkdir()
    for n in ("1.png", "2.png", "3.png"):
        (shots / n).write_bytes(b"x")
    added = []
    monkeypatch.setattr(session, "add_screenshots", lambda files: added.extend(files))
    assert session.create_from_folder(shots) == 3
    assert session.path == shots / "atlas.json" and sorted(p.name for p in added) == ["1.png", "2.png", "3.png"]


def test_the_best_atlas_of_a_folder_comes_first(session, tmp_path):
    (tmp_path / "one").mkdir()
    path, _pts, _img = make_atlas(tmp_path / "one")
    older = tmp_path / "one" / "old_atlas.json"
    older.write_text(path.read_text())
    os.utime(older, (1, 1))
    frames = tmp_path / "one" / "atlas_frames"
    frames.mkdir(exist_ok=True)
    (frames / "a.json").write_text("{}")
    assert session.atlases_for_folder(tmp_path / "one")[0] == path  # more cached screenshots, newer


def test_an_atlas_folder_opens_in_the_file_browser_only_for_a_listed_atlas(session, tmp_path, monkeypatch):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    opened = []
    monkeypatch.setattr(library.sys, "platform", "linux")
    monkeypatch.setattr(library.subprocess, "Popen", lambda args: opened.append(args))
    session.show_atlas_folder(str(path))
    assert opened == [["xdg-open", str(path.parent)]]
    with pytest.raises(ValueError):
        session.show_atlas_folder(str(tmp_path / "elsewhere" / "atlas.json"))  # (no other folder: not in the list)
    assert len(opened) == 1


def test_on_windows_the_folder_may_come_to_the_front(session, tmp_path, monkeypatch):
    # the app runs in the background: without leave to take the front, Explorer opened behind the browser (user)
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    calls = []
    monkeypatch.setattr(library.sys, "platform", "win32")
    monkeypatch.setattr(library.os, "startfile", lambda f: calls.append(("open", str(f))), raising=False)
    import ctypes
    import types

    user32 = types.SimpleNamespace(AllowSetForegroundWindow=lambda who: calls.append(("front", who)))
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
    session.show_atlas_folder(str(path))
    assert calls == [("front", -1), ("open", str(path.parent))]  # leave first (ASFW_ANY), then the folder
