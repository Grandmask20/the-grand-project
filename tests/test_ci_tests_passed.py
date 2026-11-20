"""tools.ci_tests_passed: the CI run's verdict, past a macOS job cancelled before it ran."""

from tools.ci_tests_passed import SELF, group, main, verdict

GREEN = [
    ("offline (windows-latest, 3.11)", "success"),
    ("offline (macos-latest, 3.11)", "success"),
    ("offline (ubuntu-latest, 3.11)", "success"),
    ("data (windows-latest, the-rest)", "success"),
    ("data (macos-latest, the-rest)", "success"),
    ("data (ubuntu-latest, the-rest)", "success"),
    ("testdata", "success"),
    ("e2e", "success"),
    ("page", "success"),
    ("coverage", "success"),
    (SELF, ""),
]


def test_jobs_group_by_their_name_without_the_system():
    assert group("data (macos-latest, the-rest)") == "data (the-rest)"
    assert group("offline (ubuntu-latest, 3.13)") == "offline (3.13)"
    assert group("e2e") == "e2e"


def test_all_green_passes():
    assert verdict(GREEN) == (True, [])


def test_a_macos_job_cancelled_before_it_ran_passes_when_the_others_did():
    jobs = [(n, "cancelled" if n == "data (macos-latest, the-rest)" else c) for n, c in GREEN]
    assert verdict(jobs)[0]


def test_a_failure_on_any_system_fails():
    jobs = [(n, "failure" if n == "data (macos-latest, the-rest)" else c) for n, c in GREEN]
    ok, problems = verdict(jobs)
    assert not ok and problems == ["failed: data (macos-latest, the-rest)"]


def test_a_test_that_passed_nowhere_fails():
    jobs = [(n, "cancelled" if n.startswith("data") or n == "e2e" else c) for n, c in GREEN]
    ok, problems = verdict(jobs)
    assert not ok
    assert [p.split(" (")[0] for p in problems] == ["passed on no system: data", "passed on no system: e2e"]


def test_skipped_everywhere_fails():
    jobs = [(n, "skipped" if n == "page" else c) for n, c in GREEN]
    assert not verdict(jobs)[0]


def test_main_reads_the_jobs_and_answers_with_its_exit_code(tmp_path, capsys):
    f = tmp_path / "jobs.tsv"
    f.write_text("\n".join(f"{n}\t{c}" for n, c in GREEN) + "\n")
    assert main([str(f)]) == 0
    assert "none failed" in capsys.readouterr().out
    f.write_text("page\tfailure\n")
    assert main([str(f)]) == 1
