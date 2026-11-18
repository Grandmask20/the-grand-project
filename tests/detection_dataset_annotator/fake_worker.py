"""A stand-in for the annotator's detector worker, for the pool tests: same JSON-lines protocol, no detector.

    python -m tests.detection_dataset_annotator.fake_worker

What it does depends on the request's file name: ``ok*`` answers a small result that echoes the worker's thread
limits, ``error*`` answers an error, ``crash*`` exits with code 3 without answering, ``big*`` answers a line
longer than asyncio's default 64 KiB limit, ``slow*`` sleeps a moment first.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from tools.detection_dataset_annotator import constants as K


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        key, name = request["key"], Path(request["path"]).name
        if name.startswith("crash"):
            sys.exit(3)
        if name.startswith("slow"):
            time.sleep(0.3)
        if name.startswith("error"):
            answer = {"key": key, "error": "ValueError: Could not read image"}
        else:
            limits = (K.ANNOTATOR_OPENCV_THREADS_ENV, *K.ANNOTATOR_THREAD_ENV_VARS)
            threads = {var: os.environ.get(var) for var in limits}
            result = {"detected": True, "annotations": [], "threads": threads, "pid": os.getpid(), "error": None}
            if name.startswith("big"):
                result["padding"] = "x" * 200_000
            answer = {"key": key, "result": result, "error": None}
        sys.stdout.write(json.dumps(answer) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
