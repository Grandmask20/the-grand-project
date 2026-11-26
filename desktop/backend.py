"""The desktop app's program: what PyInstaller freezes (desktop/grand-project.spec) and Electron starts (main.js).

    grand-project --no-browser            the app's server, as python -m grand_project
    grand-project --self-check            load every stored detector model (what the freezing can miss: skops and
                                          scikit-learn import their parts by name), then stop: 0 when all load
    grand-project -m <module> [args]      a module the app starts as a program of its own: frozen, sys.executable is
                                          this program, not Python (app/mapimage.py: python -m grand_project.core.seams)

multiprocessing's worker processes (the detection's) start this program again: freeze_support() runs them.
"""

from __future__ import annotations

import multiprocessing
import runpy
import sys

PYTHON_FLAGS = ("-I", "-u", "-B", "-E", "-s")  # interpreter flags before -m: frozen, nothing to do with them


def self_check() -> int:
    """Load every detector model the program's database holds, as detecting a screenshot does.

    Returns:
        0 when every one loads, 1 when one doesn't or there are none.
    """
    import sqlite3

    from grand_project.detect import models

    c = sqlite3.connect(f"file:{models.DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        names = [n for (n,) in c.execute("SELECT name FROM detector_models ORDER BY name")]
    finally:
        c.close()
    for name in names:
        print(f"{name}: {type(models.load_model(name)).__name__}", flush=True)
    return 0 if names else 1


def main(argv: list[str]) -> int:
    """Run the app's server, or the module asked for with -m.

    Args:
        argv: The command line after the program's name.

    Returns:
        Exit code.
    """
    while argv and argv[0] in PYTHON_FLAGS:
        argv = argv[1:]
    if argv[:1] == ["--self-check"]:
        return self_check()
    if len(argv) >= 2 and argv[0] == "-m":
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        return 0
    from grand_project.app.server import main as serve

    return serve(argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
