"""Build the player release (GitHub main) from this working copy (GitHub develop).

    py make_release.py            build into ../1.0 on a new branch release/v<version> from origin/main,
                                  commit and push it; then open a pull request into main (main is protected)
    py make_release.py --check    only list what the release would contain
    py make_release.py --db       first refresh references/atlas_references.sqlite3 from the private database
                                  (keeps only badge_refs + detector_models: nothing from anyone's atlas)

The player build has the program, the reference files, the launchers, LICENSE and README, and only the model
safety test: no dev tests, tools, test data, Makefile or debug tools (channel.txt = "release").
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "1.0"
REPO = "https://github.com/Grandmask20/the-grand-project"

# what the player build contains (paths relative to this folder)
TREES = ("grand_project", "references")
FILES = (
    "LICENSE",
    "requirements.txt",
    "pyproject.toml",
    "Start Atlas Viewer.bat",
    "Install (run once).bat",
    "install.sh",
    "start.sh",
)
TESTS = ("tests/__init__.py", "tests/test_model_safety.py")
KEEP_TABLES = ("badge_refs", "detector_models")

GITIGNORE = """__pycache__/
*.pyc
user_data/
atlases/*
!atlases/default/
atlases/default/*
!atlases/default/.gitkeep
local_paths.json
.venv/
*.egg-info
"""
GITATTRIBUTES = """* text=auto eol=lf
*.bat text eol=crlf
*.png binary
*.webp binary
*.zip binary
*.npz binary
*.sqlite3 binary
"""
CI = """name: safety

on:
  push:
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: python -m pip install -r requirements.txt
      - name: the stored detector models load, and a tampered database is refused
        run: python -m tests.test_model_safety
"""


def version() -> str:
    m = re.search(r'__version__ = "([^"]+)"', (HERE / "grand_project" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1)


def player_readme() -> str:
    """the README without the developer section (that part lives on the develop branch)"""
    s = (HERE / "README.md").read_text(encoding="utf-8")
    a, b = s.find("## For developers"), s.find("## License and credits")
    if a != -1 and b > a:
        s = (
            s[:a]
            + (
                "## For developers\n\nThis is the player release. The code with its tests, tools, test data and debug "
                f"tools is on the [`develop` branch]({REPO}/tree/develop).\n\n"
            )
            + s[b:]
        )
    return s


def refresh_db() -> None:
    sys.path.insert(0, str(HERE))
    from grand_project import paths

    dst = HERE / "references" / "atlas_references.sqlite3"
    tmp = dst.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    shutil.copy2(paths.DATABASE, tmp)
    c = sqlite3.connect(tmp)
    for (n,) in list(c.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        if n not in KEEP_TABLES and not n.startswith("sqlite_"):
            c.execute(f"DROP TABLE {n}")
    c.commit()
    c.execute("VACUUM")
    c.close()
    tmp.replace(dst)
    print(f"references/atlas_references.sqlite3 refreshed from {paths.DATABASE} ({', '.join(KEEP_TABLES)})")


def git(*args, cwd=TARGET, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout.strip()


def tracked(rel: str) -> list[str]:
    """files under rel that git tracks here (never caches, never private files)"""
    return [f for f in git("ls-files", rel, cwd=HERE).splitlines() if f]


def build() -> list[str]:
    files = []
    for t in TREES:
        files += tracked(t)
    files += [f for f in FILES + TESTS if (HERE / f).exists()]
    return sorted(files)


def main() -> int:
    if "--db" in sys.argv:
        refresh_db()
    files = build()
    if "--check" in sys.argv:
        print("\n".join(files))
        print(f"{len(files)} files + README.md, .gitignore, .gitattributes, channel.txt, CI (release v{version()})")
        return 0
    if git("status", "--porcelain", cwd=HERE):
        print("note: this working copy has uncommitted changes; they are released too (commit them to develop)")
    v = version()
    branch = f"release/v{v}"
    git("fetch", "-q", "origin")
    git("checkout", "-q", "-B", branch, "origin/main")
    for f in git("ls-files").splitlines():  # start from nothing: the release is exactly the list below
        p = TARGET / f
        if p.exists():
            p.unlink()
    for f in files:
        (TARGET / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / f, TARGET / f)
    (TARGET / "README.md").write_text(player_readme(), encoding="utf-8")
    (TARGET / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (TARGET / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
    (TARGET / "channel.txt").write_text("release\n", encoding="utf-8")
    (TARGET / "atlases" / "default").mkdir(parents=True, exist_ok=True)
    (TARGET / "atlases" / "default" / ".gitkeep").touch()
    (TARGET / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (TARGET / ".github" / "workflows" / "safety.yml").write_text(CI, encoding="utf-8")
    for leftover in (TARGET / "atlas_test_data", TARGET / "tools", TARGET / ".lfsconfig"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        elif leftover.exists():
            leftover.unlink()
    git("add", "-A")
    if not git("status", "--porcelain"):
        print(f"nothing to release: main already matches v{v}")
        return 0
    git(
        "commit",
        "-q",
        "-m",
        f"Release v{v}\n\nPlayer build from develop ({git('rev-parse', '--short', 'HEAD', cwd=HERE)}).",
    )
    git("push", "-q", "-u", "origin", branch, "--force")
    print(f"pushed {branch}: open the pull request into main at\n  {REPO}/compare/main...{branch}?expand=1")
    print("after merging it:  git -C ../1.0 checkout main && git -C ../1.0 pull")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
