"""builder: the detector stamp follows what the detector database holds; each screenshot is hashed once (GPT audit)."""

import os
import sqlite3

from grand_project import builder
from grand_project.detect import constants


def _db(path, blob):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE detector_models (name TEXT, blob BLOB, info TEXT, created TEXT)")
    c.execute("CREATE TABLE badge_refs (id INTEGER, name TEXT, png BLOB, png_hash TEXT, created TEXT)")
    c.execute("INSERT INTO detector_models VALUES ('nodes', ?, '{}', '2026-01-01')", (blob,))
    c.execute("INSERT INTO badge_refs VALUES (1, 'Tower', x'00', '', '2026-01-01')")
    c.commit()
    c.close()


def test_a_model_trained_again_under_the_same_name_and_time_changes_the_stamp(tmp_path, monkeypatch):
    stamps = []
    for k, blob in enumerate((b"old weights", b"new weights")):
        db = tmp_path / f"d{k}.sqlite3"
        _db(db, blob)
        monkeypatch.setattr(constants, "DB_PATH", db)
        monkeypatch.setattr(builder, "_STAMP", [])
        stamps.append(builder.detector_stamp())
    assert stamps[0] != stamps[1]


def test_a_screenshot_is_hashed_once_until_it_changes(tmp_path, monkeypatch):
    f = tmp_path / "a.png"
    f.write_bytes(b"one")
    reads = []
    real = type(f).read_bytes
    monkeypatch.setattr(type(f), "read_bytes", lambda self: (reads.append(self.name), real(self))[1])
    d1 = builder.file_digest(f)
    assert builder.file_digest(f) == d1 and reads == ["a.png"]
    f.write_bytes(b"two!")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 10**9))
    assert builder.file_digest(f) != d1


def test_a_replaced_screenshot_is_hashed_again(tmp_path):
    # (CodeRabbit: a replacement keeping the size and the time got the old hash)
    f = tmp_path / "a.png"
    f.write_bytes(b"one!")
    d1 = builder.file_digest(f)
    st = f.stat()
    new = tmp_path / "new.png"
    new.write_bytes(b"two!")  # (the same size)
    os.replace(new, f)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))  # (and the same time)
    assert builder.file_digest(f) != d1
