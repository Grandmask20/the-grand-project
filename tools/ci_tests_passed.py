"""Decide whether a CI run passed (the "tests passed" job of .github/workflows/tests.yml).

    python -m tools.ci_tests_passed jobs.tsv     one job per line: its name, a tab, its conclusion

The same tests run on Windows, macOS and Linux. GitHub's macOS runners are few on a free account: a job waiting for
one is sometimes cancelled without having run (user: "Cancelled after 15m" on a macOS job blocked merging, every
other job green). So a run passes when no job failed and every test ran and passed on at least one system: the jobs
are grouped by their name without the system ("data (macos-latest, the-rest)" -> "data (the-rest)"), and each group
needs a success. A real failure, on any system, still fails the run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OS = re.compile(r"\b(?:windows|macos|ubuntu)-[\w.]+(?:,\s*)?")
SELF = "tests passed"  # this job (still running while it decides)
BAD = {"failure", "timed_out", "action_required", "startup_failure"}


def group(name: str) -> str:
    """The job's name without the system it ran on."""
    return re.sub(r"\(\s*\)", "", OS.sub("", name)).replace("( ", "(").replace(" )", ")").strip()


def verdict(jobs: list[tuple[str, str]]) -> tuple[bool, list[str]]:
    """Whether the run passed, and why not.

    Args:
        jobs: (name, conclusion) of every job of the run (its latest try).

    Returns:
        (passed, problems): problems lists the failed jobs and the tests that passed nowhere.
    """
    problems = [f"failed: {name}" for name, c in jobs if name != SELF and c in BAD]
    groups: dict[str, list[str]] = {}
    for name, c in jobs:
        if name != SELF:
            groups.setdefault(group(name), []).append(c)
    problems += [f"passed on no system: {g} ({', '.join(cs)})" for g, cs in groups.items() if "success" not in cs]
    return not problems, problems


def main(argv: list[str]) -> int:
    jobs = [tuple(line.split("\t", 1)) for line in Path(argv[0]).read_text().splitlines() if "\t" in line]
    ok, problems = verdict([(n.strip(), c.strip()) for n, c in jobs])
    for name, c in jobs:
        print(f"{c or 'running':>10}  {name}")
    print("\n".join(["", *problems]) if problems else "\nevery test passed on at least one system, none failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
