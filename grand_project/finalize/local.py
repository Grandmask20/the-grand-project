"""finalize.local (from atlas_finalize.py)"""

from __future__ import annotations

import numpy as np

from grand_project import core

from .check import finalize
from .constants import CONTEXT_PAD, CORE_PAD, SETTLE_BADGE, SETTLE_MERGE
from .traces import _log

# every screenshot that sees the core is included)


def _footprint(atlas, f):
    """Return the four corners of a screenshot placed on the atlas.

    Args:
        atlas: the core.Atlas the screenshot is placed in.
        f: the screenshot (frame) dict (needs "M", "w", "h").

    Returns:
        A (4, 2) array of the screenshot's corners in atlas units (top-left, top-right, bottom-right, bottom-left).
    """
    H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
    return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])


def finalize_local(atlas, new_names: list[str], log=_log) -> dict:
    """Re-check only the area around the screenshots in new_names and splice it into the existing atlas-wide result.

    The area gets exactly the evidence a full check would use (every screenshot that shows any of it), so its
    result matches a full check; the rest is kept. The core is each new screenshot's box grown by CORE_PAD; the
    context around it (CONTEXT_PAD more) supplies screenshots, map nodes, icons and landmarks to the sub-check.
    Without an earlier result (atlas.final is None) a full check is run.

    Args:
        atlas: the core.Atlas; atlas.final is replaced.
        new_names: names of the newly added screenshots (frames).
        log: callable taking one message string, or None for no log output.

    Returns:
        The new atlas.final dict (same shape as finalize's), with stats["local_updates"] counted up.
    """
    if atlas.final is None:
        return finalize(atlas, log)
    polys = [_footprint(atlas, f) for f in atlas.frames if f["name"] in set(new_names)]
    if not polys:
        return atlas.final
    # one box per new screenshot (v1.01: a single box around a batch that pans across the atlas covered
    # half of it); every point of the core still has the full context margin around it
    boxes = np.array([[*p.min(axis=0), *p.max(axis=0)] for p in polys], float)
    core_b = boxes + [-CORE_PAD, -CORE_PAD, CORE_PAD, CORE_PAD]
    ctx_b = core_b + [-CONTEXT_PAD, -CONTEXT_PAD, CONTEXT_PAD, CONTEXT_PAD]

    def _in(b, x, y, pad=0.0):
        """Tell whether a point lies in any of the boxes.

        Args:
            b: (N, 4) array of boxes (x0, y0, x1, y1) in atlas units.
            x: the point's x (atlas units).
            y: the point's y (atlas units).
            pad: extra margin around each box (atlas units).

        Returns:
            True when (x, y) is inside some box grown by pad.
        """
        return bool(np.any((b[:, 0] - pad <= x) & (x <= b[:, 2] + pad) & (b[:, 1] - pad <= y) & (y <= b[:, 3] + pad)))

    def in_core(x, y):
        """Tell whether atlas point (x, y) is in the core area whose result is replaced.

        Args:
            x: x in atlas units.
            y: y in atlas units.

        Returns:
            True inside the core.
        """
        return _in(core_b, x, y)

    def in_ctx(x, y):
        """Tell whether atlas point (x, y) is in the context area that feeds the sub-check.

        Args:
            x: x in atlas units.
            y: y in atlas units.

        Returns:
            True inside the context area.
        """
        return _in(ctx_b, x, y)

    sub = core.Atlas()
    sub._images = atlas._images
    sub.frames_dir = getattr(atlas, "frames_dir", None)
    # only the core's result is kept: image checks that only set a map's colour or a settlement's kind
    # are skipped further out (settlements: with a margin, a badge / merge can reach in from there)
    sub._focus = (in_core, lambda x, y: _in(core_b, x, y, SETTLE_MERGE + SETTLE_BADGE + 50))
    for f in atlas.frames:
        p = _footprint(atlas, f)
        x0, y0, x1, y1 = *p.min(axis=0), *p.max(axis=0)
        if np.any((x1 >= ctx_b[:, 0]) & (x0 <= ctx_b[:, 2]) & (y1 >= ctx_b[:, 1]) & (y0 <= ctx_b[:, 3])):
            sub.frames.append(f)
    sub.nodes = [n for n in atlas.nodes if in_ctx(n["x"], n["y"])]
    sub.icons = [i for i in atlas.icons if in_ctx(i["x"], i["y"])]
    sub.landmarks = [landmark for landmark in atlas.landmarks if in_ctx(landmark["x"], landmark["y"])]
    fin = finalize(sub, log=None)
    old = atlas.final

    nodes, old_map, sub_map = [], {}, {}
    for i, n in enumerate(old["nodes"]):
        if not in_core(n["x"], n["y"]):
            old_map[i] = len(nodes)
            nodes.append(dict(n, id=len(nodes)))
    for i, n in enumerate(fin["nodes"]):
        if in_core(n["x"], n["y"]):
            sub_map[i] = len(nodes)
            nodes.append(dict(n, id=len(nodes)))
    kept_outside = np.array(
        [[nodes[j]["x"], nodes[j]["y"]] for j in old_map.values() if nodes[j]["status"] != "removed"], float
    ).reshape(-1, 2)
    kept_ids = [j for j in old_map.values() if nodes[j]["status"] != "removed"]

    def end_of(i):
        """Map a sub-check map node to its id in the spliced result.

        Outside the core the existing map node at that spot (within 12 atlas units) is used; failing that the
        sub-check's map node is added.

        Args:
            i: index of the map node in the sub-check's result (fin["nodes"]).

        Returns:
            The map node's id in the spliced nodes list.
        """
        if i in sub_map:
            return sub_map[i]
        n = fin["nodes"][i]
        if len(kept_outside):
            d = np.hypot(kept_outside[:, 0] - n["x"], kept_outside[:, 1] - n["y"])
            k = int(np.argmin(d))
            if d[k] < 12:
                return kept_ids[k]
        sub_map[i] = len(nodes)
        nodes.append(dict(n, id=len(nodes)))
        return sub_map[i]

    paths, pairs = [], set()
    for p in old["paths"]:
        if p["a"] in old_map and p["b"] in old_map:
            q = dict(p, a=old_map[p["a"]], b=old_map[p["b"]])
            paths.append(q)
            pairs.add((min(q["a"], q["b"]), max(q["a"], q["b"])))
    for p in fin["paths"]:
        na, nb = fin["nodes"][p["a"]], fin["nodes"][p["b"]]
        if not (in_core(na["x"], na["y"]) or in_core(nb["x"], nb["y"])):
            continue
        a, b = end_of(p["a"]), end_of(p["b"])
        key = (min(a, b), max(a, b))
        if a != b and key not in pairs:
            pairs.add(key)
            paths.append(dict(p, a=a, b=b))
    landmarks = [landmark for landmark in old["landmarks"] if not in_core(landmark["x"], landmark["y"])] + [
        landmark for landmark in fin["landmarks"] if in_core(landmark["x"], landmark["y"])
    ]
    icons = [i for i in old.get("icons", []) if not in_core(i["x"], i["y"])] + [
        i for i in fin.get("icons", []) if in_core(i["x"], i["y"])
    ]
    stats = dict(old.get("stats", {}))
    stats.update(
        {
            "nodes_kept": sum(n["status"] != "removed" for n in nodes),
            "paths": len(paths),
            "paths_multi": sum(p.get("seen_in", 0) >= 2 for p in paths),
            "paths_traced": sum(p.get("kind") == "traced" for p in paths),
            "icons_shown": len(icons),
            "local_updates": stats.get("local_updates", 0) + 1,
        }
    )
    atlas.final = {"nodes": nodes, "paths": paths, "landmarks": landmarks, "icons": icons, "stats": stats}
    if log:
        log(f"local re-check: {len(sub.frames)} of {len(atlas.frames)} screenshots, {len(sub_map)} maps updated")
    return atlas.final
