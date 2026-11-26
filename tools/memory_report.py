"""Where the app's memory goes, measured: open an atlas as the app does, use it, and after each step print the
process's memory and the size of every cache that holds pictures or arrays.

    python tools/memory_report.py atlases/default/atlas.json [--check] [--final out.json]

Steps: the libraries loaded; the atlas opened (map image, model); the map browsed (every tile of a few zoom levels,
as panning the map would); with --check, the atlas-wide path check (minutes on a big atlas); then idle a while (the
decoded screenshots let go, app.idle). Nothing is saved: the
atlas file is never written, and the app's settings are a throwaway copy (user_data is not touched).
"""

from __future__ import annotations

import argparse
import gc
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

# always a throwaway (even when one is set: its viewer settings would be overwritten); before the app imports
os.environ["GRAND_PROJECT_USER_DATA"] = tempfile.mkdtemp(prefix="gp-memory-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

MB = 1024 * 1024


def rss() -> float:
    """This process's resident memory (MB), as the OS's process list shows it: psutil when installed, else the OS's
    own figure (Windows has no `ps`: the tool stopped there without psutil, which the app doesn't need)."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / MB
    except ImportError:
        pass
    if os.name == "nt":
        return _windows_working_set() / MB
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout
    return int(out.strip() or 0) / 1024


def _windows_working_set() -> int:
    """This process's working set in bytes (what Windows' process list shows), from GetProcessMemoryInfo."""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    c = Counters()
    c.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize


def size(obj, seen: set | None = None, depth: int = 0) -> int:
    """Bytes held by an object: its arrays and bytes, through dicts, lists, tuples and objects' attributes.

    An array that is a view of another counts nothing (its base counts when reached); depth is capped at 8.
    """
    seen = set() if seen is None else seen
    if id(obj) in seen or depth > 8:
        return 0
    seen.add(id(obj))
    if isinstance(obj, np.ndarray):
        return obj.nbytes if obj.base is None or not isinstance(obj.base, np.ndarray) else 0
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return len(obj)
    if isinstance(obj, (str, int, float, bool, type(None))):
        return 0
    if isinstance(obj, dict):
        return sum(size(v, seen, depth + 1) for v in obj.values())
    if isinstance(obj, (list, tuple, set, frozenset)):
        return sum(size(v, seen, depth + 1) for v in obj)
    data = getattr(obj, "data", None)  # (the app's _LRU)
    if data is not None and not isinstance(obj, np.ndarray):
        return size(data, seen, depth + 1)
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return sum(size(v, seen, depth + 1) for k, v in vars(obj).items() if not k.startswith("__"))
    return 0


def caches(S) -> list[tuple[str, int, float]]:
    """(name, entries, MB) of every cache and big array the app keeps."""
    from grand_project.core import atlas as core_atlas
    from grand_project.core import frame as core_frame
    from grand_project.core import terrain as core_terrain
    from grand_project.finalize import traces

    out = []
    seen: set = set()  # (shared: an array several caches point at counts once, under the first listed)

    def add(name, obj, n=None):
        out.append((name, len(obj) if n is None and hasattr(obj, "__len__") else (n or 0), size(obj, seen) / MB))

    add("decoded screenshots (atlas._images)", getattr(S.atlas, "_images", {}))
    add("SIFT features (Atlas._feat_cache)", core_atlas.Atlas._feat_cache)
    add("terrain masks (terrain._MASKS)", core_terrain._MASKS)
    add("HUD masks (frame._hud_cache)", core_frame._hud_cache)
    add("gold paths (traces._GOLD)", traces._GOLD)
    add("path dashes (traces._DASHES)", traces._DASHES)
    add("saved detections (traces._SAVED)", traces._SAVED)
    add("encoded tiles (session._tiles)", S._tiles.data)
    add("map image (session.terrain: picture, coverage weight)", S.terrain or (), 1)
    skip = {"atlas", "_tiles", "settings", "events", "terrain"}
    for k, v in sorted(vars(S).items()):
        if k not in skip and not k.startswith("__"):
            add(f"session.{k}", v, 1)
    return out


def report(step: str, S, t0: float) -> None:
    gc.collect()
    held, peak = (v / MB for v in tracemalloc.get_traced_memory()) if tracemalloc.is_tracing() else (0, 0)
    print(
        f"\n== {step}  ({time.time() - t0:.0f} s)  process: {rss():,.0f} MB"
        + (
            f"  ·  held by Python and NumPy: {held:,.0f} MB (peak so far {peak:,.0f} MB)"
            if tracemalloc.is_tracing()
            else ""
        )
    )
    if tracemalloc.is_tracing():
        tracemalloc.reset_peak()
        stats = (
            tracemalloc.take_snapshot()
            .filter_traces([tracemalloc.Filter(False, tracemalloc.__file__), tracemalloc.Filter(False, "<frozen *>")])
            .statistics("lineno")
        )
        print("   where what's held was made:")
        for st in stats[:10]:
            fr = st.traceback[0]
            name = fr.filename.split("grand_project")[-1] if "grand_project" in fr.filename else Path(fr.filename).name
            print(f"   {st.size / MB:8,.0f} MB  {name}:{fr.lineno}  ({st.count:,} blocks)")
    if S is None or S.atlas is None:
        return
    rows = sorted(caches(S), key=lambda r: -r[2])
    total = sum(r[2] for r in rows)
    for name, n, mb in rows:
        if mb >= 1:
            print(f"   {mb:8,.0f} MB  {name}  ({n})")
    print(f"   {total:8,.0f} MB  in these caches; the rest is libraries, Python objects and freed memory not returned")


def browse(S) -> int:
    """Ask for every map image and vector tile of a few zoom levels (as panning the map does); returns how many."""
    g = S.grid
    n = 0
    for z in range(max(0, g.zmax - 6), g.zmax - 2):
        side = 2**z
        for x in range(side):
            for y in range(side):
                S.terrain_tile(z, x, y)
                S.vector_tile(z, x, y)
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("atlas", help="the atlas .json file")
    ap.add_argument("--check", action="store_true", help="also run the atlas-wide path check (slow on a big atlas)")
    ap.add_argument("--no-trace", action="store_true", help="skip tracemalloc (faster; no 'where it was made')")
    ap.add_argument("--final", help="with --check: write the checked atlas's maps and paths here (compare two runs)")
    a = ap.parse_args()
    if not a.no_trace:
        tracemalloc.start()
    t0 = time.time()
    report("start", None, t0)
    from grand_project.app.session import AtlasSession
    from grand_project.core.atlas import Atlas

    Atlas.save = lambda self, path: None  # (nothing written to the atlas file: opening one may finalize and save it)
    S = AtlasSession(settings={}, worker=False)
    S.save = lambda: None
    report("libraries loaded", S, t0)
    S.open_atlas(Path(a.atlas))
    t = getattr(S, "_lock_thread", None)
    if t:
        t.join()
    report(f"atlas opened ({len(S.atlas.frames)} screenshots)", S, t0)
    if S.grid is not None:
        n = browse(S)
        report(f"map browsed ({n} tiles of each kind)", S, t0)
    if a.check:
        from grand_project import finalize as atlas_finalize

        t1 = time.time()

        def said(m, *_):
            if str(m).startswith("path check"):
                print(f"   ({m})")

        atlas_finalize.finalize(S.atlas, log=said)
        report(f"path check run (the check itself: {time.time() - t1:.0f} s)", S, t0)
        if a.final:
            import json

            Path(a.final).write_text(json.dumps(S.atlas.final, sort_keys=True, default=str), encoding="utf-8")
            print(f"\n   the checked atlas written to {a.final}")
    if hasattr(S, "release_idle"):  # (app.idle: as if the app sat idle for IMAGE_IDLE_RELEASE_S)
        n = S.release_idle(now=time.monotonic() + 1e6)
        report(f"idle a while (as if: {n} decoded screenshots let go)", S, t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
