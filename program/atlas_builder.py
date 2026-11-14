"""PoE2 atlas builder: add screenshots to a growing atlas, one at a time.

    py atlas_builder.py add  --atlas my_atlas.json --image shot1.png shot2.png ...
    py atlas_builder.py info --atlas my_atlas.json

Each screenshot is run through atlas_detect (it only reads the reference database), then matched against the atlas
graph and merged.  A screenshot that cannot be placed with confidence is rejected with the
reason, and the atlas is left untouched.  After every successful add it writes
<atlas>_composite.png and <atlas>_network.png next to the JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:  # the detector imports PIL.ImageTk; headless machines lack Tk
    import tkinter  # noqa: F401
except ImportError:
    sys.modules["tkinter"] = types.ModuleType("tkinter")

import atlas_builder_core as core  # noqa: E402
import atlas_finalize  # noqa: E402
import atlas_io  # noqa: E402
import atlas_log  # noqa: E402

_log = atlas_log.printer("builder")


def default_database() -> Path:
    """the reference DB the detector reads (the new detector: its trained models + badge pictures)"""
    import rc_paths

    return rc_paths.DATABASE


NEW_DETECTOR_ID = "detect1"  # = atlas_detect.DETECTOR_ID, in cache file names (kept here so the viewer need not
# import the detector just to tell atlases apart)


def extract_frame_new(image_path: Path, cache_dir: Path) -> core.Frame:
    """atlas_detect in live mode (reads its trained models from the reference DB, never writes it);
    cached by file hash + detector id"""
    import atlas_detect
    import cv2
    import numpy as np

    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    cache = cache_dir / f"{digest[:16]}_{atlas_detect.DETECTOR_ID}.json"
    cached = atlas_io.read_json(cache) if cache.exists() else None
    if cached is not None:  # a cut-off cache (crash mid-write) is detected again
        cached["path"] = str(image_path.resolve())  # the file as it is now (moved / another computer)
        return core.Frame.from_json(cached)
    img = cv2.imdecode(np.fromfile(str(image_path), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"{image_path.name} is not a readable image (damaged or not fully written)")
    r = atlas_detect.detect(img)
    data = {
        "name": image_path.stem,
        "path": str(image_path.resolve()),
        "sha256": digest,
        "detector": atlas_detect.DETECTOR_ID,
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
    import atlas_detect

    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    return (cache_dir / f"{digest[:16]}_{atlas_detect.DETECTOR_ID}.json").exists()


def detect_uncached(paths: list, cache_dir: Path, log=None) -> dict:
    """the viewer's batches: detect the screenshots not cached yet, several at a time; {path: error} for
    failures (afterwards extract_frame reads each from the cache)"""
    todo = [p for p in paths if not is_cached(Path(p), cache_dir)]
    if len(todo) < 2 or DETECT_WORKERS < 2:
        return {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    errors = {}
    try:
        with atlas_io.process_pool(min(DETECT_WORKERS, len(todo))) as ex:
            for p, err in ex.map(_detect_one, [(str(p), "", str(cache_dir)) for p in todo]):
                if err:
                    errors[p] = err
    except Exception as e:  # no worker processes: one at a time later
        if log:
            log(f"parallel detection failed ({e}); detecting one at a time")
    return errors


def extract_frame(image_path: Path, database: Path, cache_dir: Path) -> core.Frame:
    """Detect nodes/paths/landmarks (cached by file hash)."""
    return extract_frame_new(image_path, cache_dir)


def export(atlas: core.Atlas, base: Path) -> None:
    import cv2

    canvas, origin = atlas.composite()
    d = core.atlas_files(base)
    cv2.imencode(".png", canvas)[1].tofile(str(d / (base.stem + "_composite.png")))
    cv2.imencode(".png", core.render_overlay(atlas, canvas, origin))[1].tofile(str(d / (base.stem + "_network.png")))


LINK_SPAN = 3  # terrain links are measured between each screenshot and its next 3


def place_frames(atlas: core.Atlas, frames: list, log=_log) -> tuple[int, list]:
    """Place screenshots in any order.

    1. Terrain links are measured between each screenshot and the next LINK_SPAN in input order
       (usually the order they were taken; a slow pan overlaps its neighbours).
    2. The atlas grows from what is placed: the strongest link from a placed screenshot to an
       unplaced one is tried first (maps first, then the link's shift; both terrain-checked).
    3. When no link leads anywhere new, every remaining screenshot is matched against the whole
       atlas by its maps (revisits, second passes), and growth continues from there.
    Returns (added, names not added)."""
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
        f = next(f for f in atlas.frames if f["name"] == name_of[i])
        return np.array(f["M"], float)[:, 2]

    def report(i, reg):
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
    image, database, cache_dir = job
    try:
        extract_frame(Path(image), Path(database), Path(cache_dir))
        return image, None
    except Exception as e:  # one bad screenshot must not stop the batch
        return image, repr(e)


def detect_many(images: list, database: Path, cache_dir: Path, workers: int = 1, log=_log) -> list:
    """Detect every screenshot (cached ones are instant), several at once when workers > 1."""
    todo = [i for i in images]
    if workers > 1 and len(todo) > 1:
        from concurrent.futures import as_completed

        with atlas_io.process_pool(workers) as ex:
            futs = [ex.submit(_detect_one, (str(i), str(database), str(cache_dir))) for i in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                image, err = fu.result()
                log(f"[{k}/{len(todo)}] {Path(image).name}" + (f"  FAILED: {err}" if err else ""))
    frames = []
    for image in images:
        try:
            frame = extract_frame(Path(image), database, cache_dir)
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
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path) if atlas_path.exists() else core.Atlas()
    cache_dir = atlas_path.with_name(atlas_path.stem + "_frames")
    database = Path(args.database) if args.database else default_database()
    if not database.exists():
        raise SystemExit(f"database not found: {database}  (use --database)")
    added = 0
    images = []
    for i in args.image:  # a folder = all its screenshots, in name (= time) order
        images += core.screenshots_in(i) if Path(i).is_dir() else [Path(i)]
    pending = detect_many(images, database, cache_dir, args.workers)
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
    """atlas-wide clean-up after adding screenshots: only around them when the atlas already has
    a result and only a few were added (same result as a full check there, much faster)"""
    if atlas.final is not None and len(new_names) <= LOCAL_SHARE * len(atlas.frames):
        atlas_finalize.finalize_local(atlas, new_names, log=log)
    else:
        atlas_finalize.finalize(atlas, log=log)


def cached_frames(atlas_path: Path) -> dict:
    """the cached detection of every screenshot of an atlas, by name"""
    out = {}
    for cf in atlas_path.with_name(atlas_path.stem + "_frames").glob("*.json"):
        data = atlas_io.read_json(cf)
        if data is None:  # cut-off cache: skipped (re-detected when that screenshot is next added)
            _log(f"skipping damaged detection cache {cf.name}")
            continue
        fr = core.Frame.from_json(data)
        out[fr.name] = fr
    return out


def cmd_finalize(args) -> int:
    atlas_path = Path(args.atlas)
    atlas = core.Atlas.load(atlas_path)
    atlas.rebuild_icons(cached_frames(atlas_path))  # picks up re-detected / taught badges
    atlas_finalize.finalize(atlas)
    atlas.save(atlas_path)
    export(atlas, atlas_path)
    print(f"saved {atlas_path.name} + composite/network PNGs")
    return 0


def cmd_info(args) -> int:
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add screenshots to an atlas (created if missing)")
    a.add_argument("--atlas", required=True)
    a.add_argument("--image", nargs="+", required=True)
    a.add_argument("--database", help="node_references_*.sqlite3 (default: the detector's default)")
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
