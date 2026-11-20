"""release_manifest: the player release's list of its files, which the in-app update compares and checks against."""

from grand_project import release_manifest as rm


def test_text_files_hash_the_same_with_either_line_end_binary_ones_as_they_are():
    # (GitHub's zip writes .bat files with "\r\n", a copy on Windows may have either)
    assert rm.content_hash(b"a\r\nb\r\n") == rm.content_hash(b"a\nb\n")
    png = b"\x89PNG\r\n\x1a\n\0\0\r\n"
    assert rm.content_hash(png) != rm.content_hash(png.replace(b"\r\n", b"\n"))


def test_a_release_folder_s_manifest_reads_back(tmp_path):
    (tmp_path / "grand_project").mkdir()
    (tmp_path / "grand_project" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
    m = rm.make(tmp_path, ["LICENSE", "grand_project/a.py"], "1.3", "1.21")
    assert m["release"] == "1.3" and set(m["files"]) == {"LICENSE", "grand_project/a.py"}
    import json

    (tmp_path / rm.MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    assert rm.read(tmp_path) == m
    assert rm.file_hash(tmp_path / "LICENSE") == m["files"]["LICENSE"]
    assert rm.file_hash(tmp_path / "gone") is None


def test_no_or_a_broken_manifest_is_no_release(tmp_path):
    assert rm.read(tmp_path) is None
    (tmp_path / rm.MANIFEST).write_text("{not json", encoding="utf-8")
    assert rm.read(tmp_path) is None
    (tmp_path / rm.MANIFEST).write_text('{"files": {}}', encoding="utf-8")
    assert rm.read(tmp_path) is None  # (no release number)


def test_release_numbers_compare_as_numbers():
    assert rm.release_key("v1.10") > rm.release_key("1.9")
    assert rm.release_key("1.3") == (1, 3)
    assert rm.release_key("latest") == () and rm.release_key("") == ()
