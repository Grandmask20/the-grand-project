"""Auto-add's folder and the files it would add (app.watch: the AtlasSession part)."""

from __future__ import annotations

import pytest

from grand_project.app.session import AtlasSession
from tests.webmap_data import make_atlas


@pytest.fixture
def session():
    s = AtlasSession(settings={}, worker=False)
    yield s
    s.shutdown()


def test_the_folder_needs_an_atlas_and_must_exist(session, tmp_path):
    with pytest.raises(ValueError):
        session.set_watch_folder(str(tmp_path))
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    with pytest.raises(ValueError):
        session.set_watch_folder(str(tmp_path / "missing"))


def test_a_picked_folder_is_kept_per_atlas_until_reset(session, tmp_path):
    (tmp_path / "atlas").mkdir()
    shots = tmp_path / "shots"
    shots.mkdir()
    path, _pts, _img = make_atlas(tmp_path / "atlas")
    session.open_atlas(path)
    own = session.watch_dir()
    session.set_watch_folder(str(shots))
    assert session.watch_state() == {"on": False, "folder": str(shots), "picked": True}
    session.set_watch_folder(None)
    assert session.watch_dir() == own and not session.watch_state()["picked"]


def test_only_screenshots_are_watched(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    session.set_watch_folder(str(tmp_path))
    for name in ("shot1.png", "shot2.JPG", "notes.txt", "atlas_terrain.png"):
        (tmp_path / name).write_bytes(b"12345")
    (tmp_path / "folder.png").mkdir()
    got = {p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]: n for p, n in session._watch_files().items()}
    assert got == {"shot1.png": 5, "shot2.JPG": 5}  # not the program's own pictures, not folders


def test_the_programs_own_folders_are_never_watched(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    files = tmp_path / "atlas_files"
    files.mkdir(exist_ok=True)
    (files / "shot.png").write_bytes(b"x")
    session.set_watch_folder(str(files))
    assert session._watch_files() == {}
