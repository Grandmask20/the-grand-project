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
import hashlib
import json
import sys
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
            c = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
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


_DIGESTS: dict[tuple[str, int, int], str] = {}


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
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
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


def detect_uncached(paths: list, cache_dir: Path, log=None, progress=None) -> dict:
    """Detect the screenshots not cached yet, several at a time (the viewer's batches).

    Afterwards extract_frame reads each from the cache. Does nothing for fewer than 2 screenshots or when
    DETECT_WORKERS < 2; when worker processes fail, the screenshots are left to be detected one at a time later.

    Args:
        paths: Screenshot paths.
        cache_dir: Folder of the cached detections.
        log: Optional function taking one line of text.
        progress: Optional function (done, total) called as each screenshot finishes (user: the progress box
            showed only the total while 1261 screenshots were re-detected).

    Returns:
        {path: error} for failures.
    """
    todo = [p for p in paths if not is_cached(Path(p), cache_dir)]
    if len(todo) < 2 or DETECT_WORKERS < 2:
        return {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    errors = {}
    try:
        with atlas_io.process_pool(min(DETECT_WORKERS, len(todo))) as ex:
            jobs = [ex.submit(_detect_one, (str(p), str(cache_dir))) for p in todo]
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
        job: (screenshot path, cache folder) as strings.

    Returns:
        (screenshot path, None) or (screenshot path, repr of the error).
    """
    image, cache_dir = job
    try:
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
            futs = [ex.submit(_detect_one, (str(i), str(cache_dir))) for i in todo]
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
