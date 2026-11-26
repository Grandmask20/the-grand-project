"""app.updater: the in-app update (check GitHub, download, check every file, hand over to the helper), with GitHub,
the download and the helper faked."""

import json
import os
import time
import zipfile

import pytest

from grand_project import paths as rc_paths
from grand_project import release_manifest as rm
from grand_project.app import constants as K
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
    s.check_update(background=False, fetch=github("1.3"))  # (within a minute: not asked, the last answer stands)
    assert s.update_status()["available"] and s.update_status()["next"] > time.time()
    s._update["asked"] -= K.UPDATE_CHECK_GAP
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
    _wait(lambda: s.update_status()["state"] == "idle" and asked and s.settings.get("update_checked"))
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


def test_quick_checks_ask_github_once_a_minute(installed):
    # (user: ~20 checks in 6 s; GitHub answers 60 an hour per address)
    s, _, _ = installed
    asked = []
    fetch = github("1.4")

    def counting(url):
        asked.append(url)
        return fetch(url)

    for _ in range(5):
        s.check_update(background=False, fetch=counting)
    # (the time is given to a tenth of a second: it can be a few hundredths past the minute from here, CI)
    assert len(asked) == 1 and 0 < s.update_status()["next"] - time.time() <= K.UPDATE_CHECK_GAP + 0.2


def test_github_s_used_up_limit_is_said_with_when():
    reset = str(int(time.time()) + 600)
    msg = updater.limit_message(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset})
    assert "limit" in msg and time.strftime("%H:%M", time.localtime(int(reset))) in msg
    assert updater.limit_message(403, {"X-RateLimit-Remaining": "12"}) is None  # (another refusal)
    assert updater.limit_message(404, {}) is None


def test_a_status_carries_a_number_that_goes_up_with_each_change(installed):
    s, _, _ = installed
    a = s.update_status()["seq"]
    s.check_update(background=False, fetch=github("1.4"))
    assert s.update_status()["seq"] > a and s.update_status()["run"] > 0


def test_an_answer_cut_off_ends_the_check_as_an_error(installed):
    import http.client

    s, _, _ = installed

    def cut(url):
        raise http.client.IncompleteRead(b"{")

    s.check_update(background=False, fetch=cut)
    assert s.update_status()["state"] == "error"


@pytest.mark.skipif(os.name == "nt", reason="no executable bit on Windows")
def test_a_launcher_keeps_its_permission_to_run(tmp_path):
    # (start.sh lost it: ./start.sh said permission denied, CodeRabbit)
    data = b"#!/bin/sh\n"
    m = {"release": "1.4", "program": "1.21", "files": {"start.sh": rm.content_hash(data)}}
    with zipfile.ZipFile(tmp_path / "dl.zip", "w") as z:
        info = zipfile.ZipInfo("top/start.sh")
        info.external_attr = 0o755 << 16
        z.writestr(info, data)
        z.writestr("top/" + rm.MANIFEST, json.dumps(m))
    updater.unpack(tmp_path / "dl.zip", tmp_path / "new")
    assert (tmp_path / "new" / "start.sh").stat().st_mode & 0o111


NOTES = """## 1.3.1 Hotfix

- Fixed deletion of images crashing stuff

---

Program version v1.27. Download **Source code (zip)** below and unzip it into a folder you can write to.

## How to install and start

| | Once, to install | Every time, to start |
|---|---|---|

#### First time
1. Install Python"""
SHOWN = "## 1.3.1 Hotfix\n\n- Fixed deletion of images crashing stuff"


def test_the_update_box_shows_whats_new_only_not_how_to_install():
    # (user: the install steps are for downloading by hand; a line of dashes says where they start)
    assert updater.whats_new(NOTES) == SHOWN
    assert updater.whats_new(NOTES.replace("\n---\n", "\n  ----------  \n")) == SHOWN  # (any length, spaces)
    # (two dashes are no divider: the install part goes as in notes without one)
    assert updater.whats_new(NOTES.replace("\n---\n", "\n--\n")) == SHOWN + "\n\n--"
    got = updater.latest_release(lambda url: dict(github("1.3.1")("x"), body=NOTES.replace("\n", "\r\n")))
    assert got["notes"] == SHOWN


def test_older_notes_without_the_line_lose_their_install_part():
    old = (
        "## What's new\n\n- routes\n\nVersion v1.3. Download **Source code (zip)** below and unzip it.\n\n"
        "## How to install and start\n\n#### First time\n1. Install Python\n\n## Thanks\n\n- everyone"
    )
    assert updater.whats_new(old) == "## What's new\n\n- routes\n\n\n## Thanks\n\n- everyone"
    assert updater.whats_new("What's new: routes") == "What's new: routes"


def test_the_last_updates_line_reaches_the_first_atlas_log(installed):
    # (checked in the app: said at start, before any atlas was open, it never showed in the Log tab)
    from tests.webmap_data import make_atlas

    s, _root, tmp = installed
    (rc_paths.USER_DATA).mkdir(parents=True, exist_ok=True)
    (rc_paths.USER_DATA / K.UPDATE_RESULT).write_text(json.dumps({"ok": True, "from": "1.3", "to": "1.3.1"}))
    s.after_update()
    (tmp / "atlas").mkdir()
    path, _pts, _img = make_atlas(tmp / "atlas")
    s.open_atlas(path)
    assert any(line.endswith("Updated from release 1.3 to 1.3.1") for line in s.events.log_lines)
    s.say_update(s.opened.scope)  # (once: not again in the next atlas)
    assert sum(line.endswith("Updated from release 1.3 to 1.3.1") for line in s.events.log_lines) == 1
