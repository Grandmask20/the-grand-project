"""One detector worker process (started by ``pool.py``): JSON-lines requests in, one JSON line per screenshot out.

    python -m tools.detection_dataset_annotator.worker

Request: ``{"key", "path", "include_paths", "include_fortress_walls", "named_icons"}``. Answer: ``{"key", "result",
"error": null}`` or ``{"key", "error"}``; a screenshot that fails is reported and the worker keeps running.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2

from . import constants as K
from .detection import run_classical_detector
from .state import DetectionOptions


def _answer(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Read detection jobs from stdin and answer each with one JSON line."""
    cv2.setNumThreads(max(1, int(os.environ.get(K.ANNOTATOR_OPENCV_THREADS_ENV, "1"))))
    for line in sys.stdin:
        try:
            request = json.loads(line)
            key = str(request["key"])
            path = Path(str(request["path"]))
            options = DetectionOptions.from_settings(request)
        except (KeyError, TypeError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            _answer({"key": None, "error": f"Invalid detection request: {exc}"})
            continue
        try:
            result = run_classical_detector(path, options)
        except Exception as exc:  # noqa: BLE001 - report the screenshot's error and keep the worker alive
            _answer({"key": key, "error": f"{type(exc).__name__}: {exc}"})
        else:
            _answer({"key": key, "result": result, "error": None})


if __name__ == "__main__":
    main()
