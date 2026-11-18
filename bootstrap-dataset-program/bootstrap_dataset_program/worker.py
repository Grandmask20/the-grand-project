"""One persistent process worker for classical screenshot detection."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
from constants import BOOTSTRAP_OPENCV_THREADS_ENV
from dataset_bootstrap import run_classical_detector


def _write_response(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Read detection jobs from stdin and return one JSON response per job."""
    cv2.setNumThreads(max(1, int(os.environ.get(BOOTSTRAP_OPENCV_THREADS_ENV, "1"))))
    for line in sys.stdin:
        try:
            request = json.loads(line)
            key = str(request["key"])
            path = Path(str(request["path"]))
            include_paths = bool(request["include_paths"])
            include_fortress_walls = bool(request["include_fortress_walls"])
            named_icons = bool(request["named_icons"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            _write_response({"key": None, "error": f"Invalid detection request: {exc}"})
            continue

        try:
            result = run_classical_detector(
                path,
                include_paths=include_paths,
                include_fortress_walls=include_fortress_walls,
                named_icons=named_icons,
            )
        except Exception as exc:  # noqa: BLE001 - return a per-image error while keeping the worker alive
            _write_response({"key": key, "error": f"{type(exc).__name__}: {exc}"})
        else:
            _write_response({"key": key, "result": result, "error": None})


if __name__ == "__main__":
    main()
