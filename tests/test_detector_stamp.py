"""builder: the detector stamp follows what the detector database holds; each screenshot is hashed once (GPT audit)."""

import os
import sqlite3

from grand_project import builder
from grand_project.detect import constants, rf_detr_model


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


def _rf_detr_stamp(monkeypatch, detector, folder):
    detector(rf_detr=True, model=str(folder))
    monkeypatch.setattr(builder, "_STAMP", [])
    rf_detr_model.reset_rf_detr_runtime()  # the checkpoint digest too: both are worked out once per process
    return builder.detector_stamp()


def test_the_rf_detr_stamp_follows_the_model_files_contents(tmp_path, monkeypatch, detector):
    """The same checkpoint copied elsewhere or touched keeps its stamp (its cached detections stay); other weights in
    a file of the same name, size and time do not (CodeRabbit)."""
    first, copy = tmp_path / "best", tmp_path / "copy"
    for folder in (first, copy):
        folder.mkdir()
        (folder / "model.safetensors").write_bytes(b"weights 1")
        (folder / "labels.json").write_text("{}")
    os.utime(copy / "model.safetensors", ns=(1, 10**18))
    stamp = _rf_detr_stamp(monkeypatch, detector, first)
    assert _rf_detr_stamp(monkeypatch, detector, copy) == stamp
    st = (first / "model.safetensors").stat()
    (first / "model.safetensors").write_bytes(b"weights 2")  # the same size
    os.utime(first / "model.safetensors", ns=(st.st_atime_ns, st.st_mtime_ns))  # and the same time
    assert _rf_detr_stamp(monkeypatch, detector, first) != stamp


def test_a_screenshot_that_cannot_be_detected_fails_the_add(tmp_path, monkeypatch, capsys):
    """A failed detection is not a run that placed nothing: the builder says which and exits 1 (a rebuild stops)."""
    from types import SimpleNamespace

    from grand_project import paths

    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not a picture")
    monkeypatch.setattr(paths, "DATABASE", tmp_path / "db.sqlite3")
    (tmp_path / "db.sqlite3").write_bytes(b"")
    monkeypatch.setattr(builder, "extract_frame", lambda image, cache: (_ for _ in ()).throw(ValueError("unreadable")))
    args = SimpleNamespace(atlas=str(tmp_path / "atlas.json"), image=[str(bad)], workers=1)
    assert builder.cmd_add(args) == 1
    assert "1 screenshots could not be detected: broken.png" in capsys.readouterr().out
    assert not (tmp_path / "atlas.json").exists()


def test_an_rf_detr_stamp_without_its_checkpoint_is_worked_out_again(tmp_path, monkeypatch, detector):
    """With RF-DETR on and no checkpoint folder yet, the stamp is not kept: once the folder appears in this process
    (a training run finishing), the stamp names its contents (CodeRabbit)."""
    folder = tmp_path / "best"
    before = _rf_detr_stamp(monkeypatch, detector, folder)
    assert builder._STAMP == []
    folder.mkdir()
    (folder / "model.safetensors").write_bytes(b"weights")
    after = builder.detector_stamp()  # (no reset: the same process)
    assert after != before and [after] == builder._STAMP
