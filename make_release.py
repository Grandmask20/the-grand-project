"""Publish this internal working copy to a shareable folder (same version, same code).

    py make_release.py                # -> ../rc-1  (test release; title says "rc-1")
    py make_release.py --to 1.0       # -> ../1.0   (the public GitHub release: + LICENSE, .gitignore, Git LFS
                                      #    settings; the test data itself comes from make_test_pack.py)
    py make_release.py --check        # only list what differs

Copies grand_project/, tools/, tests/ (code only), references/ (pictures / data) and the launchers;
README_release.md becomes rc-1/README.md; the database copy keeps only the reference tables the
detector reads (badge_refs, detector_models) - nothing from your atlas.  rc-1's atlases/ and
user_data/ are left alone (only created if missing); local_paths.json is never copied.
"""

import filecmp
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
from grand_project import paths as rc_paths  # noqa: E402

TARGET = HERE.parent / (sys.argv[sys.argv.index("--to") + 1] if "--to" in sys.argv else "rc-1")
PUBLIC = TARGET.name != "rc-1"  # the GitHub release
GITIGNORE = """__pycache__/
*.pyc
user_data/
atlases/*
!atlases/default/
atlases/default/*
!atlases/default/.gitkeep
local_paths.json
.venv/
atlas_test_data/detect_pairs_out/
*.egg-info
.ruff_cache/
"""
GITATTRIBUTES = """# the trimmed test data (make_test_pack.py) lives in Git LFS
atlas_test_data/** filter=lfs diff=lfs merge=lfs -text
atlas_test_data/README.md -filter -diff -merge text
# shell scripts must keep Unix line endings to run on macOS / Linux
*.sh text eol=lf
"""
LFSCONFIG = """# a normal clone does NOT download the test data; developers get it with
#   git lfs pull --include="atlas_test_data/**"
[lfs]
	fetchexclude = atlas_test_data/**
"""
LICENSE = """MIT License

Copyright (c) 2026 The Grand Project contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
CODE = ("grand_project", "tools", "tests")
FILES = (
    "Start Atlas Viewer.bat",
    "Install (run once).bat",
    "requirements.txt",
    "install.sh",
    "start.sh",
    "pyproject.toml",
    "Makefile",
)
KEEP_TABLES = ("badge_refs", "detector_models")


def code_files(root: Path):
    for d in CODE:
        for f in sorted((root / d).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".bat", ".sh"):
                yield f.relative_to(root)


def differences() -> list[str]:
    out = []
    for rel in sorted(set(code_files(HERE)) | set(code_files(TARGET)) if TARGET.exists() else code_files(HERE)):
        a, b = HERE / rel, TARGET / rel
        if not b.exists():
            out.append(f"new      {rel}")
        elif not a.exists():
            out.append(f"removed  {rel}")
        elif not filecmp.cmp(a, b, shallow=False):
            out.append(f"changed  {rel}")
    return out


def release() -> None:
    TARGET.mkdir(exist_ok=True)
    for d in CODE:  # code: replaced as a whole (no stale files)
        if (TARGET / d).exists():
            shutil.rmtree(TARGET / d)
        shutil.copytree(HERE / d, TARGET / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    ref = TARGET / "references"
    ref.mkdir(exist_ok=True)
    have = {f.name for f in (HERE / "references").iterdir() if f.is_file()}
    for f in ref.iterdir():  # pictures the program no longer reads
        if f.is_file() and f.name not in have and f.name != "atlas_references.sqlite3":
            f.unlink()
    for f in (HERE / "references").iterdir():
        if f.is_file():
            shutil.copy2(f, ref / f.name)
    for f in FILES:
        shutil.copy2(HERE / f, TARGET / f)
    readme = (HERE / "README_release.md").read_text(encoding="utf-8")
    if PUBLIC:
        readme = readme.replace(" (rc-1)", "", 1)
        (TARGET / "LICENSE").write_text(LICENSE, encoding="utf-8")
        (TARGET / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        (TARGET / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
        (TARGET / ".lfsconfig").write_text(LFSCONFIG, encoding="utf-8")
        if (HERE / ".github").exists():  # CI: the offline tests on Windows / macOS / Linux
            shutil.rmtree(TARGET / ".github", ignore_errors=True)
            shutil.copytree(HERE / ".github", TARGET / ".github")
    (TARGET / "README.md").write_text(readme, encoding="utf-8")
    (TARGET / "channel.txt").write_text("release" if PUBLIC else "rc-1", encoding="utf-8")
    # database: reference tables only
    db = ref / "atlas_references.sqlite3"
    tmp = db.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    shutil.copy2(rc_paths.DATABASE, tmp)
    c = sqlite3.connect(tmp)
    for (n,) in list(c.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        if n not in KEEP_TABLES and not n.startswith("sqlite_"):
            c.execute(f"DROP TABLE {n}")
    c.commit()
    c.execute("VACUUM")
    c.close()
    tmp.replace(db)
    for d in ("atlases/default", "user_data"):
        (TARGET / d).mkdir(parents=True, exist_ok=True)
    (TARGET / "atlases/default/.gitkeep").touch()
    (TARGET / "local_paths.json").unlink(missing_ok=True)


if __name__ == "__main__":
    diff = differences()
    print("\n".join(diff) or "code identical")
    if "--check" not in sys.argv:
        release()
        print(f"released to {TARGET} (database: {', '.join(KEEP_TABLES)} only)")
