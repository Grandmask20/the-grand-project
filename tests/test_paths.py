"""Where things are (paths): the references, the test data and which copy this is."""

from __future__ import annotations

import pytest

from grand_project import paths


def test_ref_is_in_the_references_folder():
    assert paths.ref("atlas_icons.zip") == paths.REFERENCES / "atlas_icons.zip"


def test_test_data_comes_from_the_environment_first(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_TEST_DATA", str(tmp_path))
    assert paths._test_data() == tmp_path
    monkeypatch.delenv("ATLAS_TEST_DATA")
    assert paths._test_data() in (paths.ROOT / "atlas_test_data", paths.ROOT.parent / "atlas_test_data")


def test_test_data_problem_says_what_is_wrong(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "TEST_DATA", tmp_path)
    assert "not found" in paths.test_data_problem()
    shots = tmp_path / "screenshots" / "set"
    shots.mkdir(parents=True)
    (shots / "a.png").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 9\n")
    assert "Git LFS placeholders" in paths.test_data_problem()
    (shots / "a.png").write_bytes(b"\x89PNG" + bytes(2000))
    assert paths.test_data_problem() is None


def test_need_test_data_stops_tools_without_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(paths, "TEST_DATA", tmp_path)
    with pytest.raises(SystemExit) as stop:
        paths.need_test_data()
    assert stop.value.code == 0 and capsys.readouterr().out.startswith("SKIP: test data not found")


@pytest.mark.parametrize(("channel", "tag"), [("release", ""), ("develop", " develop"), ("internal", " internal")])
def test_title_tag_names_the_copy(monkeypatch, channel, tag):
    monkeypatch.setattr(paths, "CHANNEL", channel)
    assert paths.title_tag() == tag


def test_user_data_can_be_moved_for_tests(tmp_path):
    import os
    import subprocess
    import sys

    env = {**os.environ, "GRAND_PROJECT_USER_DATA": str(tmp_path / "ud")}
    out = subprocess.run(
        [sys.executable, "-c", "from grand_project import paths; print(paths.USER_DATA)"],
        capture_output=True, text=True, env=env, check=True, cwd=paths.ROOT,
    ).stdout.strip()  # fmt: skip
    assert out == str((tmp_path / "ud").resolve())


def test_the_desktop_app_keeps_atlases_and_settings_in_its_own_folder(tmp_path):
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "GRAND_PROJECT_USER_DATA"}
    env.update(GRAND_PROJECT_HOME=str(tmp_path / "home"), GRAND_PROJECT_DESKTOP="1")
    said = "from grand_project import paths as p; print(p.DESKTOP, p.ATLASES, p.DEFAULT_ATLAS, p.USER_DATA, sep='|')"
    out = subprocess.run(
        [sys.executable, "-c", said], capture_output=True, text=True, env=env, check=True, cwd=paths.ROOT
    ).stdout.strip()
    home = (tmp_path / "home").resolve()
    atlases = home / "atlases"
    assert out.split("|") == ["True", str(atlases), str(atlases / "default" / "atlas.json"), str(home / "user_data")]
