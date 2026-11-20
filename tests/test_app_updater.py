"""app.updater: the in-app update (check GitHub, download, check every file, hand over to the helper), with GitHub,
the download and the helper faked."""

import json
import time
import zipfile

import pytest

from grand_project import paths as rc_paths
from grand_project import release_manifest as rm
from grand_project.app import updater
from grand_project.app.session import AtlasSession

OLD = {"grand_project/a.py": "old a\n", "grand_project/gone.py": "dropped\n", "requirements.txt": "numpy\n"}
NEW = {"grand_project/a.py": "new a\n", "grand_project/b.py": "new b\n", "requirements.txt": "numpy\n"}


def release_zip(path, release, files, top="Grandmask20-the-grand-project-abc123/", tamper=None, extra=None):
    """A release as GitHub zips it: one top folder, the files and their manifest."""
    m = {"release": release, "program": "1.21", "files": {f: rm.content_hash(t.encode()) for f, t in files.items()}}
    with zipfile.ZipFile(path, "w") as z:
        for f, t in files.items():
            z.writestr(top + f, tamper if f == "grand_project/a.py" and tamper else t)
        z.writestr(top + rm.MANIFEST, json.dumps(m))
        for f, t in (extra or {}).items():
            z.writestr(top + f, t)
    return path


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A player release 1.3 in a folder of its own, its user data beside it."""
    root = tmp_path / "program"
    for f, t in OLD.items():
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text(t, encoding="utf-8")
    m = rm.make(root, list(OLD), "1.3", "1.21")
    (root / rm.MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(rc_paths, "ROOT", root)
    monkeypatch.setattr(rc_paths, "CHANNEL", "release")
    monkeypatch.setattr(rc_paths, "USER_DATA", tmp_path / "user_data")
    s = AtlasSession(settings={}, worker=False)
    yield s, root, tmp_path
    s.shutdown()


def github(release="1.4"):
    return lambda url: {
        "tag_name": f"v{release}",
        "name": f"The Grand Project {release}",
        "body": "What's new: routes",
        "html_url": "https://github.com/x/y/releases/tag/v" + release,
        "zipball_url": "https://api.github.com/repos/x/y/zipball/v" + release,
        "published_at": "2026-11-21T00:00:00Z",
    }


def test_a_newer_release_is_found_and_said(installed):
    s, root, _ = installed
    s.check_update(background=False, fetch=github("1.4"))
    st = s.update_status()
    assert st["available"] and st["release"] == "1.3" and st["latest"]["release"] == "1.4" and st["can"]
    assert any("The Grand Project 1.4 is out (you have 1.3)" in line for line in s.events.log_lines)
    s.check_update(background=False, fetch=github("1.3"))
    assert not s.update_status()["available"]


def test_github_out_of_reach_is_said_not_raised(installed):
    s, _, _ = installed

    def offline(url):
        raise OSError("no network")

    s.check_update(background=False, fetch=offline)
    st = s.update_status()
    assert st["state"] == "error" and "no network" in st["error"]


def test_the_check_at_start_runs_once_a_day_and_not_when_turned_off(installed):
    s, _, _ = installed
    asked = []
    fetch = github("1.4")

    def counting(url):
        asked.append(url)
        return fetch(url)

    assert s.check_update_at_start(fetch=counting)
    _wait(lambda: s.update_status()["state"] == "idle" and asked)
    assert not s.check_update_at_start(fetch=counting)  # (checked today)
    s.settings["update_checked"] = time.time() - 2 * 24 * 3600
    s.set_update_auto(False)
    assert not s.check_update_at_start(fetch=counting) and len(asked) == 1


def test_a_development_copy_is_updated_with_git(installed, monkeypatch):
    s, _, _ = installed
    monkeypatch.setattr(rc_paths, "CHANNEL", "internal")
    st = s.update_status()
    assert not st["can"] and "git" in st["why"]
    assert not s.check_update_at_start(fetch=github())
    with pytest.raises(ValueError):
        s.install_update(quit_app=lambda: None, background=False)


def test_update_now_checks_the_download_plans_the_files_and_hands_over(installed):
    s, root, tmp = installed
    s.check_update(background=False, fetch=github("1.4"))
    z = release_zip(tmp / "dl.zip", "1.4", NEW)
    launched, quit_ = [], []

    def download(url, dest, progress):
        dest.write_bytes(z.read_bytes())
        progress(10, 10)

    s.install_update(quit_app=lambda: quit_.append(1), download=download, launch=launched.append, background=False)
    assert s.update_status()["state"] == "restarting" and quit_ == [1]
    work = tmp / "user_data" / "update"
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    assert sorted(plan["copy"]) == sorted(["grand_project/a.py", "grand_project/b.py", rm.MANIFEST])
    assert plan["delete"] == ["grand_project/gone.py"] and plan["pip"] is False
    assert plan["from"] == "1.3" and plan["to"] == "1.4" and plan["root"] == str(root)
    assert (work / "new" / "grand_project" / "b.py").read_text(encoding="utf-8") == "new b\n"
    assert launched[0][-2:] == [str(work / "update_apply.py"), str(work / "plan.json")] and "-I" in launched[0]
    assert (work / "update_apply.py").exists()


def test_a_broken_or_tampered_download_changes_nothing(installed):
    s, root, tmp = installed
    s.check_update(background=False, fetch=github("1.4"))
    z = release_zip(tmp / "dl.zip", "1.4", NEW, tamper="evil\n")
    launched = []
    s.install_update(
        quit_app=lambda: None,
        download=lambda url, dest, progress: dest.write_bytes(z.read_bytes()),
        launch=launched.append,
        background=False,
    )
    st = s.update_status()
    assert st["state"] == "error" and "a.py" in st["error"] and not launched
    assert (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "old a\n"


def test_a_file_that_would_land_outside_the_program_folder_is_refused(tmp_path):
    z = release_zip(tmp_path / "dl.zip", "1.4", {"../outside.py": "x\n"})
    with pytest.raises(ValueError, match="outside"):
        updater.unpack(z, tmp_path / "new")
    assert not (tmp_path / "outside.py").exists()


def test_changed_requirements_install_the_packages_again(installed):
    s, root, tmp = installed
    s.check_update(background=False, fetch=github("1.4"))
    z = release_zip(tmp / "dl.zip", "1.4", {**NEW, "requirements.txt": "numpy\nscipy\n"})
    s.install_update(
        quit_app=lambda: None,
        download=lambda url, dest, progress: dest.write_bytes(z.read_bytes()),
        launch=lambda argv: None,
        background=False,
    )
    plan = json.loads((tmp / "user_data" / "update" / "plan.json").read_text(encoding="utf-8"))
    assert plan["pip"] is True


def test_what_the_last_update_did_is_logged_once_at_start(installed):
    s, _, tmp = installed
    f = tmp / "user_data" / "update_result.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"ok": True, "from": "1.3", "to": "1.4"}), encoding="utf-8")
    assert s.after_update()["to"] == "1.4"
    assert any("Updated from release 1.3 to 1.4" in line for line in s.events.log_lines)
    assert s.update_status()["just"]["ok"] and s.after_update() is None


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        time.sleep(0.02)
    assert cond()
