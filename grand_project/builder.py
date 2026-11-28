"""PoE2 atlas builder: add screenshots to a growing atlas, one at a time.

    python -m grand_project.builder add  --atlas my_atlas.json --image shot1.png shot2.png ...
    python -m grand_project.builder info --atlas my_atlas.json

Each screenshot is run through the detector (it only reads the detector database, paths.DATABASE), then matched
against the atlas graph and merged.  A screenshot that cannot be placed with confidence is rejected with the
reason, and the atlas is left untouched.  After every successful add it writes
<atlas>_composite.png and <atlas>_network.png next to the JSON.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
import threading
import time
import types
from concurrent.futures import as_completed
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
try:  # the detector imports PIL.ImageTk; headless machines lack Tk
    import tkinter  # noqa: F401
except ImportError:
    sys.modules["tkinter"] = types.ModuleType("tkinter")

from grand_project import core as core  # noqa: E402
from grand_project import fileio as atlas_io  # noqa: E402
from grand_project import finalize as atlas_finalize  # noqa: E402
from grand_project import logs as atlas_log  # noqa: E402

_log = atlas_log.printer("builder")


NEW_DETECTOR_ID = "detect1"  # = atlas_detect.DETECTOR_ID, in cache file names (kept here so the viewer need not
# import the detector just to tell atlases apart)


_STAMP: list[str] = []


def detector_stamp() -> str:
    """Say which detector a cached detection came from.

    The stamp covers the trained models and icon pictures in the detector database (their content), plus the rim /
    barrel reference files. A cache with another stamp is detected again (Re-check re-detects with the current
    detector: user). Worked out once per process.

    Returns:
        12-character hex stamp.
    """
    if not _STAMP:
        import sqlite3

        from grand_project.detect.constants import BADGE_FINDER_FILE, CITY_BARREL_FILE, DB_PATH

        h = hashlib.sha1()
        try:
            # as_uri percent-encodes the path: a raw "#" or "?" in it would end the path early and drop "mode=ro"
            c = sqlite3.connect(f"{Path(DB_PATH).resolve().as_uri()}?mode=ro", uri=True)
            # what the rows hold, not their names and counts: a model trained again under the same name and time,
            # or an icon picture replaced in place, kept the stamp, so the old detections stayed (GPT audit)
            for row in c.execute("SELECT name, info, blob FROM detector_models ORDER BY name"):
                h.update(repr(row[:2]).encode())
                h.update(row[2] or b"")
            for row in c.execute("SELECT id, name, png FROM badge_refs ORDER BY id"):
                h.update(repr(row[:2]).encode())
                h.update(row[2] or b"")
            c.close()
        except Exception:  # no database: models load nothing either
            h.update(b"no database")
        for f in (BADGE_FINDER_FILE, CITY_BARREL_FILE):
            h.update(f.read_bytes() if f.exists() else b"-")
        _STAMP.append(h.hexdigest()[:12])
    return _STAMP[0]


_DIGESTS: dict[tuple, str] = {}


def file_digest(path: Path) -> str:
    """Return a screenshot's sha256, worked out once per file as it is (path, size, time): checking whether one is
    cached and then detecting it read and hashed every file twice (GPT audit).

    Args:
        path: The file.

    Returns:
        Its sha256 in hex.
    """
    from grand_project.detect.constants import DETECT_DIGEST_MEMO

    st = path.stat()
    # the file itself too (device, inode, change time): a replacement keeping the size and time got the old hash
    # (CodeRabbit)
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_dev, st.st_ino)
    if key not in _DIGESTS:
        if len(_DIGESTS) > DETECT_DIGEST_MEMO:  # (a long session over many atlases)
            _DIGESTS.clear()
        _DIGESTS[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _DIGESTS[key]


def _fresh(cache: Path) -> dict | None:
    """Read a cached detection if it was made by the current detector.

    Args:
        cache: Path of the cached detection .json.

    Returns:
        The cached detection dict, or None (missing, cut off, or from another detector).
    """
    if not cache.exists():
        return None
    data = atlas_io.read_json(cache)
    return data if data is not None and data.get("models") == detector_stamp() else None


def extract_frame(image_path: Path, cache_dir: Path) -> core.Frame:
    """Detect a screenshot with the detector in live mode, cached by file hash + detector id.

    The detector reads its trained models from the reference DB and never writes it. A cut-off cache (crash
    mid-write) or one from an older detector is detected again; a cached one gets the screenshot's current
    path (moved / another computer).

    Args:
        image_path: Screenshot file.
        cache_dir: Folder of the cached detections (the atlas's "_frames" folder).

    Returns:
        The screenshot's Frame.

    Raises:
        ValueError: The file is not a readable image (damaged or not fully written).
    """

    from grand_project import detect as atlas_detect

    digest = file_digest(image_path)
    cache = cache_dir / f"{digest[:16]}_{atlas_detect.DETECTOR_ID}.json"
    cached = _fresh(cache)
    if cached is not None:  # a cut-off cache (crash mid-write) or one from an older detector is detected again
        cached["path"] = str(image_path.resolve())  # the file as it is now (moved / another computer)
        return core.Frame.from_json(cached)
    img = core.read_screenshot(str(image_path))
    if img is None:
        raise ValueError(f"{image_path.name} is not a readable image (damaged or not fully written)")
    r = atlas_detect.detect(img)
    data = {
        "name": image_path.stem,
        "path": str(image_path.resolve()),
        "sha256": digest,
        "detector": atlas_detect.DETECTOR_ID,
        "models": detector_stamp(),
        # which program version detected it, and when (the Re-check prompt groups screenshots by them: user)
        "version": _program_version(),
        "detected_at": round(time.time(), 1),
        "width": img.shape[1],
        "height": img.shape[0],
        "nodes": [
            {
                "x": float(n["x"]),
                "y": float(n["y"]),
                "score": float(n.get("score", 0.5)),
                "state": "auto",
                "source": n.get("source", "map finder"),
                "hidden": bool(n.get("hidden")),
                "unverified": False,
                "tower": bool(n.get("tower")),
                "icon": "",
            }
            for n in r["nodes"]
        ],
        "edges": [
            {"a": int(e["a"]), "b": int(e["b"]), "conf": float(e["conf"]), "status": e["status"], "line": e["line"]}
            for e in r["edges"]
        ],
        "landmarks": [
            dict(
                {
                    "kind": landmark["kind"],
                    "x": float(landmark["x"]),
                    "y": float(landmark["y"]),
                    "conf": float(landmark.get("score", 0.9)),
                    "source": landmark.get("why", "atlas_detect"),
                },
                **({"city_type": landmark["city_type"]} if landmark.get("city_type") else {}),
            )
            for landmark in r["landmarks"]
        ],
        "icons": [
            {
                "name": b_["name"],
                "x": int(round(b_["x"])),
                "y": int(round(b_["y"])),
                "score": float(b_.get("score", 0)),
                "source": "atlas_detect",
            }
            for b_ in r["icons"]
        ],
        **atlas_detect.dash_record(img),
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    atlas_io.write_text_atomic(cache, json.dumps(data))
    return core.Frame.from_json(data)


DETECT_WORKERS = atlas_io.workers(4)  # new screenshots detected at once (each ~8 s alone; v1.01)


def _program_version() -> str:
    from grand_project import __version__

    return __version__


_HEAD = re.compile(r'"(models|version|detected_at)":\s*("([^"]*)"|[0-9.]+)')


def cache_head(cache_dir: Path, sha: str) -> dict | None:
    """Say which detector, program version and time a screenshot's saved detection came from, read from the start of
    its file only (the Re-check prompt asks this of every screenshot of an atlas; the rest of a detection is large).

    Args:
        cache_dir: Folder of the cached detections.
        sha: The screenshot's sha256 (as the atlas keeps it).

    Returns:
        {"fresh" (from the current detector), "version" (None: before versions were kept), "time" (detected then;
        the file's time when it doesn't say)}, or None when it has no saved detection.
    """
    from grand_project import detect as atlas_detect
    from grand_project.detect.constants import CACHE_HEAD_BYTES

    cache = cache_dir / f"{sha[:16]}_{atlas_detect.DETECTOR_ID}.json"
    try:
        with open(cache, encoding="utf-8", errors="replace") as fh:
            head = fh.read(CACHE_HEAD_BYTES)
        mtime = cache.stat().st_mtime
    except OSError:
        return None
    got = {m.group(1): (m.group(3) if m.group(3) is not None else m.group(2)) for m in _HEAD.finditer(head)}
    try:
        when = float(got["detected_at"]) if "detected_at" in got else mtime
    except ValueError:
        when = mtime
    return {"fresh": got.get("models") == detector_stamp(), "version": got.get("version"), "time": when}


def is_cached(image_path: Path, cache_dir: Path) -> bool:
    """Tell whether a screenshot already has a detection from the current detector.

    Args:
        image_path: Screenshot file.
        cache_dir: Folder of the cached detections.

    Returns:
        True when a fresh cached detection exists.
    """
    from grand_project import detect as atlas_detect

    digest = file_digest(image_path)
    return _fresh(cache_dir / f"{digest[:16]}_{atlas_detect.DETECTOR_ID}.json") is not None


class WarmPool:
    """Detection worker processes kept between jobs (the viewer's: one per session).

    Starting a pool took ~3.3 s a job (4 processes started, the program imported, the models loaded) before the
    first screenshot was detected; a pool kept warm pays that once. It starts with the first job and closes after
    `idle_s` without one (giving back ~1.3 GB a worker), at the next job it starts again. A pool whose worker died
    is dropped and the next job gets a new one.
    """

    def __init__(self, workers: int, idle_s: float):
        """Make the pool (no process starts yet).

        Args:
            workers: Worker processes.
            idle_s: Seconds without a job after which the processes are closed.
        """
        self.workers = workers
        self.idle_s = idle_s
        # held to hand out, drop or close the executor and to count its users, never while waiting for a job
        self._lock = threading.Lock()
        self._ex = None
        self._users = 0
        self._timer: threading.Timer | None = None
        self._timer_gen = 0  # the armed timer's number: a cancelled timer already running is told apart by it
        self._closed = False
        # executors an idle timer took out, until their shutdown returns: closing the pool waits for them too (it
        # returned while their processes still ran: CodeRabbit)
        self._retiring: set = set()
        self._retired = threading.Condition(self._lock)

    @contextlib.contextmanager
    def use(self):
        """The pool's executor for one job (started when there is none).

        Yields:
            A concurrent.futures executor; an error inside the block drops it (a dead worker breaks the whole pool).

        Raises:
            RuntimeError: The pool was closed (the app is closing).
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("the detection workers are closed")
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._timer_gen += 1  # a timer whose cancel came too late (its thread waits for the lock) does nothing
            if self._ex is None:
                self._ex = atlas_io.process_pool(self.workers)
            ex = self._ex
            self._users += 1
        try:
            yield ex
        except BaseException:
            self._drop(ex)
            raise
        finally:
            with self._lock:
                self._users -= 1
                if not self._users and self._ex is not None and not self._closed:
                    # the executor held now: a job that dropped a broken one may end after another started anew
                    self._timer_gen += 1
                    self._timer = threading.Timer(self.idle_s, self._idle, args=(self._ex, self._timer_gen))
                    self._timer.daemon = True
                    self._timer.start()

    def running(self) -> bool:
        """Tell whether the worker processes are up (started and not closed since)."""
        with self._lock:
            return self._ex is not None

    def _drop(self, ex) -> None:
        """Forget a broken executor (the next job starts a new one) and stop what it still runs."""
        with self._lock:
            if self._ex is not ex:
                return
            self._ex = None
        _stop(ex)

    def _idle(self, ex, gen: int) -> None:
        """Close the processes after idle_s without a job (the timer's thread); ``gen`` is the timer's number."""
        with self._lock:
            # a job came meanwhile, or this timer was cancelled after it fired and another was armed since
            if gen != self._timer_gen or self._ex is not ex or self._users:
                return
            self._ex, self._timer = None, None
            self._retiring.add(ex)
        try:  # (outside the lock: a new job starts a new executor meanwhile)
            ex.shutdown(wait=True)
        finally:
            with self._retired:
                self._retiring.discard(ex)
                self._retired.notify_all()

    def close(self, wait: bool = True) -> None:
        """Close the worker processes for good (the app is closing).

        Args:
            wait: Let a running job finish and an idle executor still closing end (else the current executor's
                processes are stopped: closing cut its job off).
        """
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
            ex, self._ex, self._timer = self._ex, None, None
        if ex is not None:
            ex.shutdown(wait=True) if wait else _stop(ex)
        if wait:
            with self._retired:
                self._retired.wait_for(lambda: not self._retiring)


def _stop(ex) -> None:
    """Stop an executor without waiting: queued jobs cancelled, its processes ended (on Windows a process still
    running keeps the program's files locked, and the update replaces them)."""
    # ProcessPoolExecutor's own dict, kept (shutdown sets the attribute to None) and read after the shutdown: a
    # worker started while it shuts down is in it too (a copy taken before missed it: CodeRabbit)
    processes = getattr(ex, "_processes", None)
    if processes is None:
        processes = {}
    ex.shutdown(wait=False, cancel_futures=True)
    for proc in list(processes.values()):
        with contextlib.suppress(Exception):
            proc.terminate()


def detect_uncached(paths: list, cache_dir: Path, log=None, progress=None, pool: WarmPool | None = None) -> dict:
    """Detect the screenshots not cached yet in worker processes (the viewer's jobs).

    Afterwards extract_frame reads each from the cache. Without a warm pool it starts one for the call, and then
    does nothing for fewer than 2 screenshots or when DETECT_WORKERS < 2; with one, a single screenshot goes to it
    too (detected there, not in the viewer's process, whose page requests then wait less). When the worker
    processes fail, the screenshots are left to be detected one at a time later. A worker whose detector is not the
    caller's (its database changed since the caller read it) detects nothing: its detections would not count as
    fresh to the caller, who detects them itself.

    Args:
        paths: Screenshot paths.
        cache_dir: Folder of the cached detections.
        log: Optional function taking one line of text.
        progress: Optional function (done, total) called as each screenshot finishes (user: the progress box
            showed only the total while 1261 screenshots were re-detected).
        pool: The session's warm pool, or None for one started for this call.

    Returns:
        {path: error} for failures.
    """
    todo = [p for p in paths if not is_cached(Path(p), cache_dir)]
    if not todo or (pool is None and (len(todo) < 2 or DETECT_WORKERS < 2)):
        return {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = detector_stamp()
    errors = {}
    try:
        with pool.use() if pool is not None else atlas_io.process_pool(min(DETECT_WORKERS, len(todo))) as ex:
            jobs = [ex.submit(_detect_one, (str(p), str(cache_dir), stamp)) for p in todo]
            for done, job in enumerate(as_completed(jobs), 1):
                p, err = job.result()
                if err:
                    errors[p] = err
                if progress:
                    progress(done, len(todo))
    except Exception as e:  # no worker processes: one at a time later
        if log:
            log(f"parallel detection failed ({e}); detecting one at a time")
    return errors


def export(atlas: core.Atlas, base: Path) -> None:
    """Write the stitched map and the network overlay as PNGs in the atlas's _files folder.

    Args:
        atlas: The atlas.
        base: Path of the atlas .json (names the "<stem>_composite.png" and "<stem>_network.png" files).
    """
    canvas, origin = atlas.composite()
    d = core.atlas_files(base)
    core.write_png(d / (base.stem + "_composite.png"), canvas, "composite")
    core.write_png(d / (base.stem + "_network.png"), core.render_overlay(atlas, canvas, origin), "network")


LINK_SPAN = 3  # terrain links are measured between each screenshot and its next 3


def place_frames(atlas: core.Atlas, frames: list, log=_log) -> tuple[int, list]:
    """Place screenshots in any order.

    1. Terrain links are measured between each screenshot and the next LINK_SPAN in input order
       (usually the order they were taken; a slow pan overlaps its neighbours).
    2. The atlas grows from what is placed: the strongest link from a placed screenshot to an
       unplaced one is tried first (maps first, then the link's shift; both terrain-checked).
    3. When no link leads anywhere new, every remaining screenshot is matched against the whole
       atlas by its maps (revisits, second passes), and growth continues from there.

    The atlas-wide check (recheck) runs afterwards when anything was added.

    Args:
        atlas: The atlas, changed in place.
        frames: The screenshots' Frames, in the order they were taken.
        log: Function taking one line of text.

    Returns:
        (added, names not added).
    """
    n = len(frames)
    if not n:
        return 0, []
    name_of = [f.name for f in frames]
    known = {f["name"] for f in atlas.frames}
    links: dict[int, list] = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i + 1, min(n, i + 1 + LINK_SPAN)):
            agree, shift = atlas.terrain_link(frames[i], frames[j])
            if agree >= core.TERRAIN_MIN_AGREE:
                links[i].append((agree, j, shift))  # t_j = t_i + shift
                links[j].append((agree, i, -shift))
    log(f"terrain links between neighbouring screenshots: {sum(len(v) for v in links.values()) // 2}")
    placed = {i for i in range(n) if name_of[i] in known}
    tried: set = set()
    added = 0

    def t_of(i):
        """Return the shift of a placed screenshot.

        Args:
            i: Index into frames.

        Returns:
            (2,) shift in atlas units.
        """
        f = next(f for f in atlas.frames if f["name"] == name_of[i])
        return np.array(f["M"], float)[:, 2]

    def report(i, reg):
        """Count a placed screenshot and log how it was placed.

        Args:
            i: Index into frames.
            reg: Its Registration.
        """
        nonlocal added
        added += 1
        placed.add(i)
        if len(atlas.frames) == 1:
            log(f"\n== {Path(frames[i].path).name}\n   first screenshot: it defines the atlas coordinate system")
            return
        info = atlas.frames[-1]
        how = f" by {reg.reason}" if reg.reason.startswith("terrain") else ""
        log(
            f"\n== {Path(frames[i].path).name}\n   MERGED{how}  {reg.inliers} nodes agree (rmse {reg.rmse:.1f}px), "
            f"overlap {reg.ratio:.0%}, terrain match {reg.ncc:.2f} vs {reg.ref_frame}; "
            f"{info['matched_nodes']} nodes matched, {info['new_nodes']} new"
        )

    if not atlas.frames:
        reg = atlas.add_frame(frames[0])
        report(0, reg)
    while len(placed) < n:
        grew = False
        cands = sorted(
            (
                (agree, j, i, shift)
                for i in placed
                for agree, j, shift in links[i]
                if j not in placed and (j, i) not in tried
            ),
            key=lambda c: -c[0],
        )
        for agree, j, i, shift in cands:
            if j in placed:
                continue
            tried.add((j, i))
            seed = t_of(i) + shift
            at = t_of(i) + shift * core.TERRAIN_SCALE  # where the terrain pixels line up
            reg = atlas.add_frame(frames[j], seeds=[(seed, f"terrain ({agree} features agree vs {name_of[i]})", at)])
            if reg.ok:
                report(j, reg)
                grew = True
                break  # re-rank: new links are now reachable
        if grew:
            continue
        for j in range(n):  # revisits: whole-atlas map matching
            if j in placed or ("maps", j, len(placed)) in tried:
                continue
            tried.add(("maps", j, len(placed)))
            reg = atlas.add_frame(frames[j])
            if reg.ok:
                report(j, reg)
                grew = True
                break
        if not grew:
            break
    refused = [Path(frames[j].path).name for j in range(n) if j not in placed]
    for name in refused:
        log(f"NOT ADDED: {name} (no overlap found)")
    if added:
        recheck(atlas, [f["name"] for f in atlas.frames[-added:]], log=log)
    return added, refused


def _detect_one(job):
    """Detect one screenshot into the cache (run in a worker process).

    One bad screenshot must not stop the batch, so errors are returned, not raised.

    Args:
        job: (screenshot path, cache folder, the caller's detector_stamp()).

    Returns:
        (screenshot path, None) or (screenshot path, repr of the error).
    """
    image, cache_dir, stamp = job
    try:
        # inside the try: a stamp that cannot be worked out (the database) is this screenshot's error, not the
        # batch's
        mine = detector_stamp()
        if mine != stamp:  # (a warm worker started after the database changed, or the caller before)
            return image, f"detector changed (this worker's {mine}, the caller's {stamp})"
        extract_frame(Path(image), Path(cache_dir))
        return image, None
    except Exception as e:  # one bad screenshot must not stop the batch
        return image, repr(e)


def detect_many(images: list, cache_dir: Path, workers: int = 1, log=_log) -> list:
    """Detect every screenshot (cached ones are instant), several at once when workers > 1.

    Screenshots whose detection fails are logged and skipped.

    Args:
        images: Screenshot paths.
        cache_dir: Folder of the cached detections.
        workers: Number of worker processes.
        log: Function taking one line of text.

    Returns:
        The Frames of the screenshots detected, in input order.
    """
    todo = [i for i in images]
    if workers > 1 and len(todo) > 1:
        from concurrent.futures import as_completed

        with atlas_io.process_pool(workers) as ex:
            stamp = detector_stamp()
            futs = [ex.submit(_detect_one, (str(i), str(cache_dir), stamp)) for i in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                image, err = fu.result()
                log(f"[{k}/{len(todo)}] {Path(image).name}" + (f"  FAILED: {err}" if err else ""))
    frames = []
    for image in images:
        try:
            frame = extract_frame(Path(image), cache_dir)
        except Exception as e:
            log(f"skipped {Path(image).name}: detection failed ({e})")
            continue
        log(
            f"detected {Path(image).name}: {int(frame.usable.sum())} usable nodes, {len(frame.edges)} paths, "
            f"{len(frame.landmarks)} landmarks"
        )
        frames.append(frame)
    return frames


def cmd_add(args) -> int:
    """Run "add": add screenshots (files or folders) to an atlas, created if missing.

    Saves the atlas and the PNGs when anything was added.

    Args:
        args: Parsed arguments (atlas, image, workers).

    Returns:
        Exit code 0.

    Raises:
        SystemExit: The detector database is missing.
    """
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path) if atlas_path.exists() else core.Atlas()
    cache_dir = atlas_path.with_name(atlas_path.stem + "_frames")
    from grand_project import paths as rc_paths

    if not rc_paths.DATABASE.exists():
        raise SystemExit(f"detector database not found: {rc_paths.DATABASE}  (DATABASE in local_paths.json)")
    added = 0
    images = []
    for i in args.image:  # a folder = all its screenshots, in name (= time) order
        images += core.screenshots_in(i) if Path(i).is_dir() else [Path(i)]
    pending = detect_many(images, cache_dir, args.workers)
    added, _ = place_frames(atlas, pending)
    if added:
        atlas.save(atlas_path)
        export(atlas, atlas_path)
        print(
            f"\nsaved {atlas_path.name} ({len(atlas.nodes)} nodes, {len(atlas.edges)} paths, "
            f"{len(atlas.landmarks)} landmarks, {len(atlas.frames)} screenshots) + composite/network PNGs"
        )
    else:
        print("\nnothing added; atlas unchanged")
    return 0


LOCAL_SHARE = 0.25  # adding more than this share of the atlas at once: re-check all of it


def recheck(atlas: core.Atlas, new_names: list, log=_log) -> None:
    """Run the atlas-wide clean-up after adding screenshots.

    Only around them when the atlas already has a result and only a few were added (at most LOCAL_SHARE of the
    atlas; same result as a full check there, much faster).

    Args:
        atlas: The atlas, changed in place.
        new_names: Names of the screenshots just added.
        log: Function taking one line of text.
    """
    if atlas.final is not None and len(new_names) <= LOCAL_SHARE * len(atlas.frames):
        atlas_finalize.finalize_local(atlas, new_names, log=log)
    else:
        atlas_finalize.finalize(atlas, log=log)


def cached_frames(atlas_path: Path, frames: list[dict]) -> dict:
    """Read the cached detection of every screenshot placed in an atlas, by name.

    Each placed screenshot's own cache is read (found by the screenshot's hash, as it was saved), never every file
    in the folder: a glob also picked up caches of screenshots no longer in the atlas, and with two caches of one
    name the one read last won (GPT audit). A cache from another detector is used only when there is no fresh one
    (its screenshot can't be detected again: moved or deleted), so its icons aren't lost; cut-off caches are skipped.

    Args:
        atlas_path: Path of the atlas .json.
        frames: The atlas's placed screenshots (Atlas.frames: "name" and "sha").

    Returns:
        {screenshot name: Frame}.
    """
    cache_dir = atlas_path.with_name(atlas_path.stem + "_frames")
    out = {}
    by_name = None  # name -> cache file, only read if a screenshot has no saved hash (none of 5453 on 34 atlases)
    for f in frames:
        sha = f.get("sha")
        if sha:
            cf = cache_dir / f"{sha[:16]}_{NEW_DETECTOR_ID}.json"
        else:  # placed before screenshots kept their hash: its cache by name, so its icons aren't lost (review)
            if by_name is None:
                by_name = _caches_by_name(cache_dir)
            cf = by_name.get(f["name"])
        if cf is None or not cf.exists():
            continue
        data = atlas_io.read_json(cf)
        if data is None:  # cut-off cache: skipped (re-detected when that screenshot is next added)
            _log(f"skipping damaged detection cache {cf.name}")
            continue
        if data.get("models") != detector_stamp():
            _log(f"{f['name']}: only an older detector's result (screenshot can't be re-detected); using it")
        out[f["name"]] = core.Frame.from_json(data)
    return out


def _caches_by_name(cache_dir: Path) -> dict:
    """Every cache file in a folder by the screenshot name inside it (a fresh one wins over an older detector's).

    Args:
        cache_dir: The atlas's "_frames" folder.

    Returns:
        {screenshot name: cache file}.
    """
    out, fresh = {}, set()
    for cf in sorted(cache_dir.glob(f"*_{NEW_DETECTOR_ID}.json")):
        data = atlas_io.read_json(cf)
        if not data or "name" not in data:
            continue
        name, is_fresh = data["name"], data.get("models") == detector_stamp()
        if name not in out or (is_fresh and name not in fresh):
            out[name] = cf
            if is_fresh:
                fresh.add(name)
    return out


def cmd_finalize(args) -> int:
    """Run "finalize": re-merge icons from the cached detections and redo the atlas-wide clean-up.

    Picks up re-detected / taught icons; saves the atlas and the PNGs.

    Args:
        args: Parsed arguments (atlas).

    Returns:
        Exit code 0.
    """
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path)
    atlas.rebuild_icons(cached_frames(atlas_path, atlas.frames))  # picks up re-detected / taught badges
    atlas_finalize.finalize(atlas)
    atlas.save(atlas_path)
    export(atlas, atlas_path)
    print(f"saved {atlas_path.name} + composite/network PNGs")
    return 0


def cmd_info(args) -> int:
    """Run "info": print a summary of an atlas and of each screenshot in it.

    Args:
        args: Parsed arguments (atlas).

    Returns:
        Exit code 0.
    """
    atlas = core.Atlas.load(Path(args.atlas))
    j = atlas.to_json()
    multi = sum(len(set(n["frames"])) > 1 for n in j["nodes"])
    print(
        f"{len(j['nodes'])} nodes ({multi} seen in 2+ screenshots), {len(j['edges'])} paths, "
        f"{len(j['landmarks'])} landmarks, {len(j['frames'])} screenshots"
    )
    for f in j["frames"]:
        print(
            f"  {f['name']}: {f['matched_nodes']} nodes matched, {f['new_nodes']} new "
            f"(ncc {f.get('ncc')}, reference {f.get('reference') or '-'})"
        )
    return 0


def main() -> int:
    """Parse the command line and run the chosen command (add, finalize, info).

    Returns:
        The command's exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add screenshots to an atlas (created if missing)")
    a.add_argument("--atlas", required=True)
    a.add_argument("--image", nargs="+", required=True)
    a.add_argument(
        "--workers", type=int, default=1, help="detect this many screenshots at once (e.g. 6 on an 8+ core PC)"
    )
    a.set_defaults(func=cmd_add)
    fz = sub.add_parser("finalize", help="re-run the atlas-wide clean-up (nodes, icons, abyss, paths)")
    fz.add_argument("--atlas", required=True)
    fz.set_defaults(func=cmd_finalize)
    i = sub.add_parser("info", help="summarise an atlas")
    i.add_argument("--atlas", required=True)
    i.set_defaults(func=cmd_info)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
