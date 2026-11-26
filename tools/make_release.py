"""Build the player release (GitHub main) from this working copy (GitHub develop).

    py -m tools.make_release --release 1.3
                                  build release 1.3 into ../1.0 on a new branch release/v<version> from
                                  origin/main, commit and push it; then open a pull request into main (main is
                                  protected). The release number is the GitHub release's (tag v1.3): the app's
                                  in-app update compares it (manifest.json)
    py -m tools.make_release --check    only list what the release would contain
    py -m tools.make_release --notes    only print the release notes (also written next to ../1.0 on a release)
    py -m tools.make_release --db       first refresh references/atlas_references.sqlite3 from the private database
                                  (keeps only badge_refs + detector_models: nothing from anyone's atlas)

The player build has the program, the reference files, the launchers, LICENSE and README, the app's page built
(frontend/dist: players need no Node.js) and only the model safety test: no dev tests, tools, test data, Makefile,
page sources or debug tools (channel.txt = "release"), and manifest.json: the release number and a hash of each of
its files, which the in-app update reads (grand_project/release_manifest.py).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]  # the repo (this file is in tools/)
TARGET = HERE.parent / "1.0"
REPO = "https://github.com/Grandmask20/the-grand-project"

# what the player build contains (paths relative to this folder)
TREES = ("grand_project", "references")
FILES = (
    "LICENSE",
    "requirements.txt",
    "pyproject.toml",
    "Start The Grand Project.bat",
    "Install (run once).bat",
    "install.sh",
    "start.sh",
)
TESTS = ("tests/__init__.py", "tests/test_model_safety.py")
PAGE = HERE / "frontend"  # the app's page (React); built into frontend/dist, which the release ships
KEEP_TABLES = ("badge_refs", "detector_models")

GITIGNORE = """__pycache__/
*.pyc
user_data/
atlases/*
local_paths.json
The Grand Project.lnk
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
      - run: python -m pip install -r requirements.txt pytest
      - name: the stored detector models load, and a tampered database is refused
        run: python -m pytest tests/test_model_safety.py
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


def release_notes(release: str = "") -> str:
    """The GitHub release's notes, in the user's layout (2026-11-25): the release's header and what's new, a divider
    (app/constants.UPDATE_NOTES_CUT, a line of dashes: the in-app update shows only what is above it), then how to
    install and start it
    on each system, every time (manny: tell newcomers which script to run on Windows vs macOS / Linux).

    The install and start part is the README's "How to install and start" section ("Run it" before 1.26: without
    its "Get it", that is on the download page), so the notes and the README never disagree; its ### headings a
    level down, under the notes' own ## heading.

    Args:
        release: The release number for the header ("1.3.1"); "" for a placeholder.
    """
    from grand_project.app.constants import UPDATE_NOTES_CUT

    s = (HERE / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = ""
    for head in ("## How to install and start\n", "## Run it\n"):
        a = s.find(head)
        if a != -1:
            b = s.find("\n## ", a + len(head))  # (to the next section; "---" ended it before)
            run = s[a + len(head) : b if b != -1 else len(s)].split("\n---\n")[0].strip()
            break
    g, h = run.find("### Get it"), run.find("### First time")
    if g != -1 and h > g:
        run = run[:g] + run[h:]
    run = re.sub(r"(?m)^### ", "#### ", run)
    return (
        f"## {release or 'x.y'}\n\n"
        "- (write the highlights here)\n\n"
        f"{UPDATE_NOTES_CUT}\n\n"
        f"Program version v{version()}. Download **Source code (zip)** below and unzip it into a folder you can "
        "write to.\n\n"
        f"## How to install and start\n\n{run}\n"
    )


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


def build_page() -> None:
    """Build the app's page (npm install, then npm run build: type check, then Vite) into frontend/dist."""
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm was not found: install Node.js 20+ to build the app's page")
    for args in (["install", "--no-audit", "--no-fund"], ["run", "build"]):
        r = subprocess.run([npm, *args], cwd=PAGE)
        if r.returncode:
            raise SystemExit(f"npm {' '.join(args)} failed in {PAGE}")


def page_files() -> list[str]:
    """the built page's files (frontend/dist), relative to this folder"""
    dist = PAGE / "dist"
    return [p.relative_to(HERE).as_posix() for p in sorted(dist.rglob("*")) if p.is_file()]


def build() -> list[str]:
    files = []
    for t in TREES:
        files += tracked(t)
    files += [f for f in FILES + TESTS if (HERE / f).exists()]
    files += page_files()
    return sorted(files)


def release_number() -> str:
    """The release number given with --release ("1.3"), checked."""
    from grand_project import release_manifest as rm

    if "--release" not in sys.argv or sys.argv.index("--release") + 1 >= len(sys.argv):
        raise SystemExit("give the release number: py -m tools.make_release --release 1.3 (the GitHub tag v1.3)")
    r = sys.argv[sys.argv.index("--release") + 1].lstrip("vV")
    if not rm.release_key(r):
        raise SystemExit(f"not a release number: {r!r} (like 1.3)")
    return r


def write_manifest(release: str, files: list[str]) -> None:
    """manifest.json in the build: the release, the program version, a hash of each of its files (the in-app
    update's list: only these are the program's)."""
    from grand_project import release_manifest as rm

    listed = sorted(set(files) | {"README.md", ".gitignore", ".gitattributes", "channel.txt"})
    m = rm.make(TARGET, listed, release, version())
    (TARGET / rm.MANIFEST).write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    if "--notes" in sys.argv:
        print(release_notes(release_number() if "--release" in sys.argv else ""))
        return 0
    # the release number first: a run without it stops before building anything
    release = release_number() if "--check" not in sys.argv else ""
    if "--db" in sys.argv:
        refresh_db()
    if "--check" not in sys.argv:
        build_page()
    files = build()
    if not any(f.startswith("frontend/dist/") for f in files):
        print("note: the page is not built (frontend/dist): the release would have no page")
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
    # no atlases/ in the release: the app makes atlases/default on first start. Shipped (for its .gitkeep), copying
    # an update over with macOS Finder's Replace swapped the player's whole atlases folder for it (CodeRabbit)
    write_manifest(release, files)
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
    notes = TARGET.parent / f"release_notes_v{v}.md"
    notes.write_text(release_notes(release), encoding="utf-8")
    print(f"pushed {branch}: open the pull request into main at\n  {REPO}/compare/main...{branch}?expand=1")
    print(f"release notes (paste into the GitHub release, then add what's new): {notes}")
    print("after merging it:  git -C ../1.0 checkout main && git -C ../1.0 pull")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
