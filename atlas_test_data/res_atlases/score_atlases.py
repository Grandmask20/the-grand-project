"""Detection numbers for the standard test atlases in this folder, so detector changes can be compared.

Each res_* atlas holds the same 3 screenshots (the same 3 bookmarked spots on the atlas) taken at a different
screen resolution and in-game render scale. res_4k_100 (4K, 100% render) is the reference: the other atlases are
compared with it, after lining them up by the median shift between matching map nodes.

Run from a checkout of the repo (after `git lfs pull --include="atlas_test_data/**"`), with
S=atlas_test_data/res_atlases:

    python $S/score_atlases.py                            print the numbers of every atlas here
    python $S/score_atlases.py --save run.json            also save them
    python $S/score_atlases.py --compare $S/baseline_v1.15.json   show the change from a saved run
    python $S/score_atlases.py --rebuild                  first rebuild every atlas from its screenshots with this
                                                          checkout's detector (in a temp copy)

"vs 4K 100%" columns: maps / icons / paths of this atlas that match the reference (same spot within MATCH units;
icons also the same name; paths the same two matched maps) and how many of the reference's it found.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MATCH = 15.0  # atlas units (1080p screen px): two maps / icons this close are the same one
REFERENCE = "res_4k_100"
# screen resolution, then render scale (the reference first); other atlases added here come after these
ORDER = [
    "res_4k_100",
    "res_4k_67",
    "res_4k_50",
    "res_4k_33",
    "res_1440_100",
    "res_1440_50",
    "res_1080_100",
    "res_1080_67",
]


def program_root() -> Path:
    """The checkout whose program is scored: the repo this folder sits in, else the current folder."""
    repo = HERE.parents[1]
    return repo if (repo / "grand_project").is_dir() else Path(os.getcwd())


def _import():
    """Import the program from this checkout, ahead of any installed copy (review: an installed, older copy would
    have been scored instead): the repo this folder sits in (atlas_test_data/res_atlases), else the current folder.
    """
    sys.path.insert(0, str(program_root()))
    try:
        from grand_project.app.model import view_model  # the web app's (the viewer package is gone: CodeRabbit)
    except ImportError:
        from grand_project.viewer.model import view_model  # a checkout from before the web app

    from grand_project import core

    return core, view_model


def atlases() -> list[Path]:
    """The atlas folders here: every sub-folder with an atlas.json, the reference first."""
    found = sorted(p.parent for p in HERE.glob("*/atlas.json"))
    return sorted(found, key=lambda p: (ORDER.index(p.name) if p.name in ORDER else len(ORDER), p.name))


def rebuild(folder: Path) -> bool:
    """Rebuild one atlas from its screenshots with this checkout's detector (in a temp copy, then copied back).

    Returns:
        False when the builder ran without error and placed no screenshot (it saves no atlas then), else True.
    """
    shots = sorted(p for p in folder.glob("*.png") if p.name[:1].isdigit())
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / folder.name
        work.mkdir()
        for s in shots:
            shutil.copy2(s, work / s.name)
        cmd = [sys.executable, "-m", "grand_project.builder", "add", "--atlas", str(work / "atlas.json"), "--image"]
        root = program_root()  # the rebuild uses the same checkout as the scoring (review)
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(root), os.environ.get("PYTHONPATH")]))}
        subprocess.run(cmd + [str(work / s.name) for s in shots], check=True, capture_output=True, cwd=root, env=env)
        if not (work / "atlas.json").is_file():
            return False  # nothing placed: no atlas to copy back
        d = json.loads((work / "atlas.json").read_text(encoding="utf-8"))
        for f in d["frames"]:  # bare names (the screenshots sit next to the atlas), not the temp folder's paths
            f["path"] = Path(f["path"]).name
        (folder / "atlas.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
        for d in ("atlas_frames", "atlas_files"):
            if (folder / d).exists():
                shutil.rmtree(folder / d)
            if (work / d).exists():
                shutil.copytree(work / d, folder / d)
    return True


def numbers(folder: Path, core, view_model) -> dict:
    """Count what the atlas holds after the atlas-wide check, and what each screenshot's detection found."""
    atlas = core.Atlas.load(folder / "atlas.json")
    V = view_model(atlas)
    shots = sorted(p.name for p in folder.glob("*.png") if p.name[:1].isdigit())
    live = [i for i, n in enumerate(V["nodes"]) if n["status"] != "removed"]
    maps = [V["nodes"][i] for i in live]
    at = {vi: li for li, vi in enumerate(live)}  # view-model map index -> index in `maps`
    status = Counter(n["status"] for n in maps)
    icons = [i for i in V["icons"]]
    lms = Counter(lm["kind"] for lm in V["landmarks"] if not lm["status"].startswith("removed"))
    per_shot = []
    for f in atlas.frames:
        cache = folder / "atlas_frames" / f"{f['sha'][:16]}_detect1.json"
        d = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
        per_shot.append(
            {
                "name": f["name"],
                "maps": sum(1 for n in d.get("nodes", []) if not n.get("hidden")),
                "hidden maps": sum(1 for n in d.get("nodes", []) if n.get("hidden")),
                "icons": len(d.get("icons", [])),
                "paths": len(d.get("edges", [])),
                "landmarks": len(d.get("landmarks", [])),
            }
        )
    return {
        "screenshots": f"{len(atlas.frames)} / {len(shots)} placed",
        "maps": len(maps),
        "maps by status": dict(sorted(status.items())),
        "paths": len(V["paths"]),
        "icons": len(icons),
        "icons unnamed": sum(1 for i in icons if i["name"] == "Unidentified"),
        "icon types": dict(sorted(Counter(i["name"] for i in icons).items())),
        "landmarks": dict(sorted(lms.items())),
        "per screenshot": per_shot,
        "_pts": {
            "maps": [[n["x"], n["y"]] for n in maps],
            "icons": [[i["x"], i["y"], i["name"]] for i in icons],
            "paths": [[at[p["a"]], at[p["b"]]] for p in V["paths"] if p["a"] in at and p["b"] in at],
        },
    }


def best_pairs(a, b) -> dict[int, int]:
    """The largest one-to-one matching of points a to points b within MATCH, closest overall among those.

    (A nearest-first pass could miss a pair: two points wanting the same reference point, one of which also had
    another in reach; and its result depended on the order of the points: review.)

    Args:
        a: (n, 2) points.
        b: (m, 2) points.

    Returns:
        {index in a: index in b}.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    a, b = np.asarray(a, float).reshape(-1, 2), np.asarray(b, float).reshape(-1, 2)
    if not len(a) or not len(b):
        return {}
    d = np.hypot(*(a[:, None, :] - b[None, :, :]).transpose(2, 0, 1))
    big = 1e6  # more than any sum of in-reach distances: as many pairs as possible first, then the closest
    rows, cols = linear_sum_assignment(np.where(d <= MATCH, d, big))
    return {int(i): int(j) for i, j in zip(rows, cols, strict=True) if d[i, j] <= MATCH}


def compare_to_reference(cur: dict, ref: dict) -> dict:
    """Match this atlas's maps, icons and paths to the reference's (after the median shift between them)."""
    import numpy as np
    from scipy.spatial import cKDTree

    a, b = np.array(cur["_pts"]["maps"], float), np.array(ref["_pts"]["maps"], float)
    if not len(a) or not len(b):
        return {}
    d, k = cKDTree(b).query(a)
    near = d < 60
    shift = np.median(b[k[near]] - a[near], axis=0) if near.any() else np.zeros(2)
    a2 = a + shift
    pairs = best_pairs(a2, b)  # this atlas's map -> reference map, one to one
    ia = [[x + shift[0], y + shift[1], n] for x, y, n in cur["_pts"]["icons"]]
    ib = ref["_pts"]["icons"]
    icon_hits = 0
    for name in {n for _x, _y, n in ia}:  # icons pair up only with icons of the same name
        mine = [(x, y) for x, y, n in ia if n == name]
        theirs = [(u, v) for u, v, m in ib if m == name]
        icon_hits += len(best_pairs(mine, theirs))
    # paths: the same two maps (each matched to a reference map)
    ref_paths = {frozenset(p) for p in ref["_pts"]["paths"]}
    path_hits = sum(
        1 for p in cur["_pts"]["paths"] if all(e in pairs for e in p) and frozenset(pairs[e] for e in p) in ref_paths
    )
    return {
        "maps": f"{len(pairs)} of {len(a)} match; found {len(pairs)} of {len(b)} ({len(pairs) / len(b):.0%})",
        "icons": f"{icon_hits} of {len(ia)} match; found {icon_hits} of {len(ib)} ({icon_hits / max(1, len(ib)):.0%})",
        "paths": f"{path_hits} of {len(cur['_pts']['paths'])} match; found {path_hits} of {len(ref_paths)} "
        f"({path_hits / max(1, len(ref_paths)):.0%})",
        "shift": [round(float(s), 1) for s in shift],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", help="save the numbers to this JSON file")
    ap.add_argument("--compare", help="show the change from numbers saved with --save")
    ap.add_argument("--rebuild", action="store_true", help="rebuild every atlas here first (this checkout's detector)")
    args = ap.parse_args()
    core, view_model = _import()
    folders = atlases()
    if args.rebuild:
        for f in folders:
            print(f"rebuilding {f.name} ...", flush=True)
            if not rebuild(f):  # nothing placed: the folder's atlas.json would be an older build's, scored as new
                print(f"{f.name}: the builder placed no screenshot; not scoring a stale atlas", file=sys.stderr)
                return 1
    res = {f.name: numbers(f, core, view_model) for f in folders}
    ref = res.get(REFERENCE)
    for name, r in res.items():
        if ref is not None and name != REFERENCE:
            r["vs 4K 100%"] = compare_to_reference(r, ref)
    old = json.loads(Path(args.compare).read_text(encoding="utf-8")) if args.compare else {}
    print(f"{'atlas':<14} {'shots':<14} {'maps':>5} {'paths':>6} {'icons':>6}  landmarks")
    for name, r in res.items():
        delta = ""
        if name in old:
            o = old[name]
            delta = f"   (was {o['maps']} / {o['paths']} / {o['icons']})"
        lm = ", ".join(f"{k} {v}" for k, v in r["landmarks"].items())
        print(f"{name:<14} {r['screenshots']:<14} {r['maps']:>5} {r['paths']:>6} {r['icons']:>6}  {lm}{delta}")
    print()
    for name, r in res.items():
        c = r.get("vs 4K 100%")
        if c:  # (empty when either atlas has no map nodes)
            print(f"{name:<14} vs 4K 100%:  maps {c['maps']} | icons {c['icons']} | paths {c['paths']}")
    if args.save:
        out = {n: {k: v for k, v in r.items() if k != "_pts"} for n, r in res.items()}
        Path(args.save).write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"\nsaved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
