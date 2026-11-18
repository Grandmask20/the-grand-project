"""The dataset bootstrap worker uses a small JSON-lines protocol."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_worker_returns_image_errors_as_json(tmp_path: Path) -> None:
    """A bad image is reported for that job without crashing the persistent worker."""
    project_root = Path(__file__).resolve().parents[1]
    program_dir = project_root / "bootstrap-dataset-program"
    image = tmp_path / "not-an-image.png"
    image.write_bytes(b"not an image")
    environment = os.environ.copy()
    python_paths = [str(program_dir), str(project_root)]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)

    completed = subprocess.run(
        [sys.executable, "-u", "-m", "bootstrap_dataset_program.worker"],
        cwd=project_root,
        env=environment,
        input=json.dumps(
            {
                "key": "sample",
                "path": str(image),
                "include_paths": False,
                "include_fortress_walls": False,
                "named_icons": False,
            }
        )
        + "\n",
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert response["key"] == "sample"
    assert response["error"].startswith("ValueError: Could not read image:")
    assert "result" not in response
