"""release_manifest: the player release's list of its own files (manifest.json at the program folder's top).

Written by tools/make_release.py into every release: the release number ("1.3"), the program version it was built
from, and a SHA-256 of each program file. The in-app update (app/updater.py) compares it with the next release's to
know which files to replace or remove, and checks every downloaded file against it. Only the files listed here are
the program's: an update never touches anything else (atlases/, user_data/, local_paths.json, .venv/).

Text files are hashed with Windows line ends turned into "\\n": GitHub's zip of a release writes them as its
.gitattributes says (the .bat files with "\\r\\n"), and a copy unzipped or edited on Windows may have either.
No imports beyond the standard library: the release script and the update use it without the app's packages.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST = "manifest.json"
BINARY_PROBE = 8192  # bytes looked at for a NUL: a file with one there is binary (hashed as it is)


def content_hash(data: bytes) -> str:
    """Return a file's hash: SHA-256 of its bytes, with "\\r\\n" read as "\\n" in a text file.

    Args:
        data: The file's bytes.

    Returns:
        The hex digest.
    """
    if b"\0" not in data[:BINARY_PROBE]:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str | None:
    """Return a file's content_hash, or None when there is no such file."""
    try:
        return content_hash(path.read_bytes())
    except OSError:
        return None


def make(root: Path, files: list[str], release: str, program: str) -> dict:
    """Return the manifest of a release folder.

    Args:
        root: The release folder.
        files: Its program files, relative ("/"-separated).
        release: The release number ("1.3").
        program: The program version it was built from ("1.21").

    Returns:
        {"release", "program", "files": {path: hash}}.
    """
    return {
        "release": release,
        "program": program,
        "files": {f: content_hash((root / f).read_bytes()) for f in sorted(files)},
    }


def read(root: Path) -> dict | None:
    """Return the manifest at the top of a program folder, or None (not a release, or unreadable)."""
    try:
        m = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or not isinstance(m.get("files"), dict) or not m.get("release"):
        return None
    return m


def release_key(release: str) -> tuple[int, ...]:
    """Return a release number as numbers to compare ("v1.10" > "1.9"); () when it isn't one."""
    parts = release.strip().lstrip("vV").split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) and parts != [""] else ()
