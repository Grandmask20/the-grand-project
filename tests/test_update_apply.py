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
    monkeypatch.setattr(ua, "freeze", lambda python: {})
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


def test_packages_a_failed_install_changed_are_put_back_at_their_versions(tmp_path, monkeypatch):
    # (a half-done install left the old files on changed packages: CodeRabbit)
    root, plan = program(tmp_path)
    plan["pip"] = True
    frozen = iter([{"numpy": "numpy==1.0", "scipy": "scipy==1.5"}, {"numpy": "numpy==2.0", "scipy": "scipy==1.5"}])
    monkeypatch.setattr(ua, "freeze", lambda python: next(frozen))
    ran = []

    def fake_run(args, **kw):
        ran.append(args)
        return subprocess.CompletedProcess(args, 1 if "-r" in args else 0, "", "")

    monkeypatch.setattr(ua.subprocess, "run", fake_run)
    assert not ua.apply(plan)["ok"]
    assert ran[-1][-1:] == ["numpy==1.0"]  # (only the one it changed)


def test_the_app_starts_again_even_when_the_result_can_t_be_written(tmp_path, monkeypatch):
    root, plan = program(tmp_path)
    plan.update(pid=1, result=str(tmp_path / "no_such_dir" / "result.json"), restart=["python"])
    started = []
    monkeypatch.setattr(ua, "wait_for_exit", lambda pid, timeout=0: True)
    monkeypatch.setattr(ua, "restart", lambda p: started.append(1))
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(plan), encoding="utf-8")
    ua.main(["update_apply.py", str(f)])
    assert started == [1]


def test_no_install_without_a_list_of_the_packages_to_put_back(tmp_path, monkeypatch):
    # (pip freeze failed: an install that then failed couldn't be undone, CodeRabbit)
    root, plan = program(tmp_path)
    plan["pip"] = True
    monkeypatch.setattr(ua, "freeze", lambda python: None)
    ran = []
    monkeypatch.setattr(ua.subprocess, "run", lambda args, **kw: ran.append(args))
    out = ua.apply(plan)
    assert not out["ok"] and "couldn't be listed" in out["error"] and ran == []
    assert (root / "grand_project" / "a.py").read_text(encoding="utf-8") == "old a\n"


def test_packages_a_failed_install_added_are_removed(tmp_path, monkeypatch):
    # (GPT audit: only changed ones were put back, new ones stayed)
    root, plan = program(tmp_path)
    plan["pip"] = True
    frozen = iter([{"numpy": "numpy==1.0"}, {"numpy": "numpy==1.0", "newpkg": "newpkg==0.1"}])
    monkeypatch.setattr(ua, "freeze", lambda python: next(frozen))
    ran = []

    def fake_run(args, **kw):
        ran.append(args)
        return subprocess.CompletedProcess(args, 1 if "-r" in args else 0, "", "")

    monkeypatch.setattr(ua.subprocess, "run", fake_run)
    assert not ua.apply(plan)["ok"]
    assert ran[-1][-3:] == ["uninstall", "-y", "newpkg"]
    assert not any("install" in a and "numpy==1.0" in a for a in ran)  # (unchanged: not installed again)


def test_a_package_from_a_file_or_url_is_known_and_put_back_as_it_was(tmp_path, monkeypatch):
    # (CodeRabbit: only "==" lines were read, so one installed from a URL looked new and was uninstalled)
    lines = "".join(
        f"{line}{chr(10)}"
        for line in (
            "numpy==1.0",
            "mylib @ file:///C:/wheels/mylib-1.0-py3-none-any.whl",
            "-e git+https://x/y.git#egg=dev_tool",
        )
    )
    monkeypatch.setattr(ua.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, lines, ""))
    got = ua.freeze("python")
    assert got == {"numpy": "numpy==1.0", "mylib": "mylib @ file:///C:/wheels/mylib-1.0-py3-none-any.whl",
                   "dev-tool": "-e git+https://x/y.git#egg=dev_tool"}  # fmt: skip
    root, plan = program(tmp_path)
    plan["pip"] = True
    before = dict(got)
    after = dict(got, mylib="mylib==2.0")  # (the failed install put an index one in its place)
    frozen = iter([before, after])
    monkeypatch.setattr(ua, "freeze", lambda python: next(frozen))
    ran = []

    def fake_run(args, **kw):
        ran.append(args)
        return subprocess.CompletedProcess(args, 1 if "-r" in args else 0, "", "")

    monkeypatch.setattr(ua.subprocess, "run", fake_run)
    assert not ua.apply(plan)["ok"]
    put_back = [a for a in ran if "install" in a and "-r" not in a]
    assert put_back[-1][-1] == "mylib @ file:///C:/wheels/mylib-1.0-py3-none-any.whl"  # (as it was installed)
    assert not any("uninstall" in a for a in ran)  # (nothing new: nothing taken away)
