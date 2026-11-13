"""One debug log for the atlas builder, the atlas-wide check and the viewer: atlas_debug.log.

Every module gets a logger with `atlas_log.get("viewer")` etc.  Lines look like
    [2026-11-10 14:02:11] [INFO] [viewer] added 3 screenshot(s): ...
and errors carry their full traceback.  Uncaught errors (main thread, background threads and Tk
button handlers) are written here too, so a problem the window only shows as "nothing happened"
still leaves a trace.  When reporting an issue, send this file (it rotates at 5 MB, 3 old copies).
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent.parent / "user_data" / "atlas_debug.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_ready = False


def _setup() -> None:
    global _ready
    if _ready:
        return
    _ready = True
    root = logging.getLogger("atlas")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    try:
        h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    except OSError:                                   # read-only folder: log nowhere rather than crash
        h = logging.NullHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    root.addHandler(h)

    old_hook = sys.excepthook

    def hook(tp, val, tb):
        root.critical("uncaught error", exc_info=(tp, val, tb))
        old_hook(tp, val, tb)
    sys.excepthook = hook

    def thread_hook(args):
        root.error(f"uncaught error in thread {args.thread.name if args.thread else '?'}",
                   exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_hook


def get(name: str) -> logging.Logger:
    """logger "atlas.<name>" writing to atlas_debug.log"""
    _setup()
    return logging.getLogger(f"atlas.{name}")


def printer(name: str):
    """a log(msg) function for the builder / finalize `log=` arguments: prints and writes the file"""
    lg = get(name)

    def log(msg, *rest):
        text = " ".join(str(m) for m in (msg, *rest))
        lg.info(text)
        print(text, flush=True)
    return log
