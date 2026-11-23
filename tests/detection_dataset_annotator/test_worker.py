"""The annotator's detector worker process speaks a small JSON-lines protocol."""

import json
import os
import subprocess
import sys
from pathlib import Path

from grand_project import paths
from tools.detection_dataset_annotator import constants as K


def _ask_worker(*requests: str) -> list[dict]:
    """Send request lines to a worker started as the annotator starts it and return its answers."""
    completed = subprocess.run(
        [sys.executable, "-u", "-m", K.ANNOTATOR_WORKER_MODULE],
        cwd=paths.ROOT,
        input="".join(f"{request}\n" for request in requests),
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines()]


def test_worker_returns_image_errors_as_json(tmp_path: Path) -> None:
    """A bad image or a bad request is reported for that job without stopping the persistent worker."""
    image = tmp_path / "not-an-image.png"
    image.write_bytes(b"not an image")
    request = {"key": "sample", "path": str(image), "include_paths": False, "named_icons": False}

    bad_request, bad_image = _ask_worker("not json", json.dumps(request))

    assert bad_request["key"] is None
    assert bad_request["error"].startswith("Invalid detection request:")
    assert bad_image["key"] == "sample"
    assert bad_image["error"].startswith("ValueError: Could not read image:")
    assert "result" not in bad_image


def test_worker_reads_and_answers_utf8_whatever_the_console_encoding(tmp_path: Path) -> None:
    """The pool writes UTF-8 lines: a non-ASCII path arrives whole even where Python's console encoding is another
    (a Windows code page)."""
    image = tmp_path / "bild-ä€.png"
    image.write_bytes(b"not an image")
    request = json.dumps(
        {"key": "k", "path": str(image), "include_paths": False, "named_icons": False}, ensure_ascii=False
    )
    completed = subprocess.run(
        [sys.executable, "-u", "-m", K.ANNOTATOR_WORKER_MODULE],
        cwd=paths.ROOT,
        input=(request + "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "latin-1"},
    )
    assert completed.returncode == 0, completed.stderr
    (answer,) = [json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()]
    assert str(image) in answer["error"]
