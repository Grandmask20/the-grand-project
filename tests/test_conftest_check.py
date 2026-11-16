"""The shared `check` fixture: a failed check fails the test itself (not its teardown)."""

from pathlib import Path

pytest_plugins = ["pytester"]  # pytest's own fixture for running a small test session inside a test


def test_failed_check_fails_the_test(pytester):
    """A test with a failed check is reported as failed, with the check's name."""
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"))
    pytester.makepyfile(
        """
        def test_one(check):
            check("this holds", True)
            check("this does not", False, "detail")
        """
    )
    r = pytester.runpytest("-p", "no:cacheprovider")
    r.assert_outcomes(failed=1)
    r.stdout.fnmatch_lines(["*this does not (detail)*"])
