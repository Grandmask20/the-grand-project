"""app.update_apply: the helper that puts a downloaded release in place once the app has closed, then starts it."""

import json
import os
import subprocess
import sys

from grand_project.app import update_apply as ua


def program(tmp_path):
    """A program folder with two files, a new release with one changed and one new, and a plan to put it in place."""
    root, new, backup = tmp_path / "program", tmp_path / "new", tmp_path / "backup"
    (root / "grand_project").mkdir(parents=True)
    (root / "grand_project" / "a.py").write_text("old a\n", encoding="utf-8")
    (root / "grand_project" / "gone.py").write_text("dropped\n", encoding="utf-8")
    (root / "atlases").mkdir()
    (root / "atlases" / "mine.json").write_text("{}", encoding="utf-8")
    (new / "grand_project").mkdir(parents=True)
    (new / "grand_project" / "a.py").write_text("new a\n", encoding="utf-8")
    (new / "grand_project" / "b.py").write_text("new b\n", encoding="utf-8")
    plan = {
        "root": str(root),
        "new": str(new),
        "backup": str(backup),
        "copy": ["grand_project/a.py", "grand_project/b.py"],
        "delete": ["grand_project/gone.py"],
        "pip": False,
        "python": "python",
        "from": "1.3",
        "to": "1.4",
    }
    return root, plan


def test_the_new_files_go_in_the_dropped_ones_go_and_nothing_else_is_touched(tmp_path):
    root, plan = program(tmp_path)
    out = ua.apply(plan)
    assert out["ok"] and out["copied"] == 2 and out["deleted"] == 1
    assert (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "new a\n"
    assert (root / "grand_project" / "b.py").exists() and not (root / "grand_project" / "gone.py").exists()
    assert (root / "atlases" / "mine.json").exists()  # (not the release's: never touched)


def test_a_failure_puts_every_file_back(tmp_path):
    root, plan = program(tmp_path)
    plan["copy"].append("grand_project/missing.py")  # (not in the download: copying it fails)
    out = ua.apply(plan)
    assert not out["ok"] and "missing.py" in out["error"]
    assert (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "old a\n"
    assert not (root / "grand_project" / "b.py").exists()
    assert (root / "grand_project" / "gone.py").exists()


def test_packages_that_fail_to_install_put_the_old_files_back(tmp_path, monkeypatch):
    root, plan = program(tmp_path)
    plan["pip"] = True
    ran = []

    def fake_run(args, **kw):
        ran.append(args)
        return subprocess.CompletedProcess(args, 1, "", "no network")

    monkeypatch.setattr(ua.subprocess, "run", fake_run)
    out = ua.apply(plan)
    assert ran and ran[0][1:4] == ["-m", "pip", "install"]
    assert not out["ok"] and (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "old a\n"
    assert "no network" in (tmp_path / "pip.log").read_text(encoding="utf-8")


def test_it_waits_for_the_app_writes_what_happened_and_starts_the_app(tmp_path, monkeypatch):
    root, plan = program(tmp_path)
    plan.update(pid=os.getpid(), result=str(tmp_path / "result.json"), restart=["python", "-m", "grand_project"])
    started = []
    monkeypatch.setattr(ua, "wait_for_exit", lambda pid, timeout=0: True)
    monkeypatch.setattr(ua, "restart", lambda p: started.append(p["restart"]))
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(plan), encoding="utf-8")
    assert ua.main(["update_apply.py", str(f)]) == 0
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["ok"] is True
    assert started == [["python", "-m", "grand_project"]]


def test_an_app_that_doesn_t_close_changes_nothing(tmp_path, monkeypatch):
    root, plan = program(tmp_path)
    plan.update(pid=1, result=str(tmp_path / "result.json"), restart=["python"])
    monkeypatch.setattr(ua, "wait_for_exit", lambda pid, timeout=0: False)
    monkeypatch.setattr(ua, "restart", lambda p: None)
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(plan), encoding="utf-8")
    assert ua.main(["update_apply.py", str(f)]) == 1
    assert (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "old a\n"


def test_a_process_that_ended_is_waited_for_at_once():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert ua.wait_for_exit(p.pid, timeout=2.0)
