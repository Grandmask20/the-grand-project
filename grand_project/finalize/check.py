"""finalize.check (from atlas_finalize.py)"""

from __future__ import annotations

import math

import cv2
import numpy as np

from grand_project import core
from grand_project import detect as atlas_detect
from grand_project import gold_paths as gp

from .constants import (
    ABYSS_CLEAR,
    ABYSS_LINK,
    ABYSS_NAMES,
    ABYSS_TOWER_CLEAR,
    CHECK_SEEN,
    CLUMP_N,
    CLUMP_R,
    CLUMP_SHARE,
    CONFIRM,
    DENY,
    DUP_TOL,
    END_CONE,
    END_DASHES,
    END_REACH,
    END_VIEWS,
    GAP_FOUND,
    GAP_MIN,
    GAP_ON,
    GAP_R,
    GAP_SEEN,
    GAP_SHOTS,
    ICON_ATTACH_DX,
    ICON_ATTACH_DY,
    ICON_PAIR,
    ICON_TOWER_REACH,
    ICON_TOWER_SPREAD,
    ICON_TWIN,
    JUNCTION,
    LOCAL_RETRACE,
    LONELY_ON,
    LONELY_SEEN,
    LONELY_SHOTS,
    MAX_BOW,
    MAX_BOW_STRONG,
    MAX_EXITS,
    NO_NODE_ICONS,
    ONE_END_SHARE,
    PARALLAX_TOL,
    PASS_CLEAR,
    PASS_WEAK,
    PATH_THRESHOLD,
    PROPOSE,
    RATIO_COULD,
    RATIO_COULD_REL,
    RATIO_GHOST,
    RATIO_NEAR,
    RATIO_R,
    RATIO_REL,
    RATIO_REL_NEAR,
    ROW_GAP,
    RUN_OVER,
    S_BOW,
    S_BOW_PX,
    S_TURN,
    S_WOBBLE_PX,
    SAME_SPOT,
    SEAM_DASHES,
    SEAM_MAX,
    SEAM_MIN,
    SEAM_ON,
    SEAM_PAD,
    SECTOR,
    SECTOR_NEAR,
    SECTOR_STRICT,
    SETTLE_BADGE,
    SHARED_FRAC,
    SHARED_MIN_ALONE,
    SHARED_OK,
    START_LEN,
    STRAIGHT_MAX,
    STRAIGHT_VIEWS,
    TOWER_JOIN,
    TOWER_JOIN_SEEN,
    TOWER_THRESHOLD,
    TRACE_MATCH,
    WALL_MAP,
)
from .landmarks import _clean_icons, _guessed, _one_map, _settlements
from .traces import (
    _along,
    _bypasses_two,
    _coverage,
    _dashes,
    _diamond_shortcut,
    _gold,
    _Grid,
    _log,
    _maps,
    _mst,
    _on_wall,
    _saved,
    _seg_dist,
    _trace_views,
    _visible,
)


def finalize(atlas, log=_log) -> dict:
    maps = _maps(atlas)
    maps_by = {f["name"]: (f, Hi) for f, Hi in maps}
    icons = _clean_icons(atlas, maps)
    nodes = [
        {
            "x": float(n["x"]),
            "y": float(n["y"]),
            "frames": set(n["frames"]),
            "tower": bool(n.get("tower")),
            "hidden": bool(n.get("hidden")),
            "sources": list(n.get("sources", [])),
            "icons": [],
            "guessed": _guessed(n),
            "origin": "detected",
        }
        for n in atlas.nodes
    ]
    alive = [True] * len(nodes)
    removed_why: dict[int, str] = {}

    def P():
        return np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)

    # ---- 1a. join half-merged duplicates (each seen by different screenshots, a few px apart).
    # A copy sitting on an icon's base position keeps its position (the other copy is often a
    # node the detector anchored on the badge itself, 24 px higher).
    bases = np.array([[ic["bx"], ic["by"]] for ic in icons if ic["name"] != "LostTower"], float).reshape(-1, 2)

    base_grid = _Grid(bases, 40.0)

    def base_fit(nd):
        near = base_grid.near((nd["x"], nd["y"]), 40.0)
        if not near:
            return np.inf
        return float(np.min(np.hypot(bases[near, 0] - nd["x"], bases[near, 1] - nd["y"])))

    pts = P()
    if len(pts):
        joined = 0
        into = list(range(len(nodes)))  # a joined map -> the map it went into

        def survivor(k):
            while into[k] != k:
                into[k] = into[into[k]]
                k = into[k]
            return k

        for _d0, i0, j0 in sorted(_Grid(pts, PARALLAX_TOL).pairs(PARALLAX_TOL)):
            # a pair whose map was already joined into another is judged with that map, where it is now
            # (otherwise two groups that each joined first were never compared - user's doubled maps)
            i, j = survivor(i0), survivor(j0)
            if i == j or not (alive[i] and alive[j]):
                continue
            dij = math.hypot(nodes[i]["x"] - nodes[j]["x"], nodes[i]["y"] - nodes[j]["y"])
            if dij >= PARALLAX_TOL:
                continue
            seen_i = nodes[i]["frames"] - nodes[i]["guessed"]  # a screenshot that only GUESSED one of
            seen_j = nodes[j]["frames"] - nodes[j]["guessed"]  # them (hidden map) proves nothing
            shared = seen_i & seen_j
            if len(shared) > max(SHARED_OK, SHARED_FRAC * len(seen_i | seen_j)):
                continue  # seen side by side in many screenshots: two maps
            if shared and len((seen_i | seen_j) - shared) < SHARED_MIN_ALONE:
                continue  # too few screenshots saw only one there (user: 3 wrong merges
                # with 2-4 such shots; the fortress map had 8)
            a, b = nodes[i], nodes[j]
            # one screenshot that found two points on one base (a raised structure, e.g. at the fortress:
            # user) no longer vetoes the join when the others found one map there
            if (dij > DUP_TOL or shared) and not _one_map(maps_by, a, b, ignore=shared):
                continue
            wa, wb = len(a["frames"]), len(b["frames"])
            fa, fb = base_fit(a), base_fit(b)
            if min(fa, fb) < 8 and abs(fa - fb) > 4:
                if fb < fa:
                    a["x"], a["y"] = b["x"], b["y"]
            else:
                a["x"], a["y"] = (a["x"] * wa + b["x"] * wb) / (wa + wb), (a["y"] * wa + b["y"] * wb) / (wa + wb)
            a["frames"] |= b["frames"]
            a["guessed"] = (a["guessed"] | b["guessed"]) - (seen_i | seen_j)
            a["tower"] |= b["tower"]
            a["hidden"] &= b["hidden"]
            a["sources"] += b["sources"]
            alive[j] = False
            into[j] = i
            removed_why[j] = f"joined into {i}"
            joined += 1

        # ---- 1b. maps on a tower's wide base are that tower, even where one screenshot found two of them
        # (it did not recognise the tower there, so the two sat 31-40 px apart: user's tower + ghost map)
        # only around a tower seen as one in 2+ screenshots (a single tower call that the later checks reject
        # left its map flagged "tower": that one must not swallow a real map next to it)
        sure = np.array(
            [
                [landmark["x"], landmark["y"]]
                for landmark in atlas.landmarks
                if landmark["kind"] == "Tower" and landmark.get("n", 1) >= TOWER_JOIN_SEEN
            ],
            float,
        ).reshape(-1, 2)
        towers = [
            i
            for i in range(len(nodes))
            if alive[i]
            and nodes[i]["tower"]
            and len(sure)
            and float(np.min(np.hypot(sure[:, 0] - nodes[i]["x"], sure[:, 1] - nodes[i]["y"]))) < 25
        ]
        towers.sort(key=lambda i: -len(nodes[i]["frames"]))
        tgrid = _Grid(P(), TOWER_JOIN)
        for i in towers:
            if not alive[i]:
                continue
            a = nodes[i]
            for j in tgrid.near((a["x"], a["y"]), TOWER_JOIN):
                if j == i or not alive[j]:
                    continue
                b = nodes[j]
                if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= TOWER_JOIN:
                    continue
                wa, wb = len(a["frames"]), len(b["frames"])
                a["x"], a["y"] = (a["x"] * wa + b["x"] * wb) / (wa + wb), (a["y"] * wa + b["y"] * wb) / (wa + wb)
                a["guessed"] = (a["guessed"] | b["guessed"]) - (
                    (a["frames"] - a["guessed"]) | (b["frames"] - b["guessed"])
                )
                a["frames"] |= b["frames"]
                a["hidden"] &= b["hidden"]
                a["sources"] += b["sources"]
                alive[j] = False
                into[j] = i
                removed_why[j] = f"on the base of tower {i}"
                joined += 1

    # ---- 2. icons -> nodes.  A map can carry a ROW of badges side by side (~36 px apart, e.g.
    # Abyss + Abyss Overrun + Azmeri Spirit); the base sits under the middle of the row.
    row_of = list(range(len(icons)))

    def root(k):
        while row_of[k] != k:
            row_of[k] = row_of[row_of[k]]
            k = row_of[k]
        return k

    icon_grid = _Grid([[ic["x"], ic["y"]] for ic in icons], ROW_GAP)
    for _, a_i, b_i in icon_grid.pairs(ROW_GAP + 8):
        a, b = icons[a_i], icons[b_i]
        if "LostTower" in (a["name"], b["name"]):
            continue
        if abs(a["y"] - b["y"]) < 8 and abs(a["x"] - b["x"]) < ROW_GAP:
            row_of[root(a_i)] = root(b_i)
    rows: dict[int, list[int]] = {}
    for k in range(len(icons)):
        rows.setdefault(root(k), []).append(k)
    row_base = {}
    for members in rows.values():
        bx = float(np.mean([icons[k]["bx"] for k in members]))
        by = float(np.mean([icons[k]["by"] for k in members]))
        for k in members:
            row_base[k] = (bx, by)

    icon_nodes = []
    det_pts = P()
    det_grid = _Grid(det_pts, 40.0)
    for k, ic in enumerate(icons):
        if ic["name"] == "LostTower":
            continue
        bx, by = row_base[k]
        ic = dict(ic, bx=bx, by=by)
        best_i, best_d = None, np.inf
        for i in det_grid.near((bx, by), math.hypot(ICON_ATTACH_DX, ICON_ATTACH_DY)):
            if alive[i] and abs(nodes[i]["x"] - bx) < ICON_ATTACH_DX and abs(nodes[i]["y"] - by) < ICON_ATTACH_DY:
                dd = math.hypot(nodes[i]["x"] - bx, nodes[i]["y"] - by)
                if dd < best_d:
                    best_i, best_d = i, dd
        if best_i is not None:
            nodes[best_i]["icons"].append(k)
            continue
        if ic["name"] in NO_NODE_ICONS:
            continue
        if ic.get("spread", 0.0) >= ICON_TOWER_SPREAD:
            # copies far apart and no map right under it: a tower's badge (towers are tall, their badges float
            # high and shift between views - user). Give it to a tower map below, never make a map of it.
            tw = [
                i
                for i in det_grid.near((bx, by), ICON_TOWER_REACH[1])
                if alive[i]
                and nodes[i]["tower"]
                and abs(nodes[i]["x"] - bx) < ICON_TOWER_REACH[0]
                and 0 <= nodes[i]["y"] - by <= ICON_TOWER_REACH[1]
            ]
            if tw:
                nodes[min(tw, key=lambda i: math.hypot(nodes[i]["x"] - bx, nodes[i]["y"] - by))]["icons"].append(k)
            continue
        # a second badge over a map already created from its partner badge
        near = [i for i in icon_nodes if math.hypot(nodes[i]["x"] - ic["bx"], nodes[i]["y"] - ic["by"]) < ICON_PAIR]
        if near:
            i = near[0]
            m = len(nodes[i]["icons"])
            nodes[i]["x"] = (nodes[i]["x"] * m + ic["bx"]) / (m + 1)
            nodes[i]["icons"].append(k)
            continue
        nodes.append(
            {
                "x": ic["bx"],
                "y": ic["by"],
                "frames": set(ic["frames"]),
                "tower": False,
                "hidden": False,
                "guessed": set(),
                "sources": ["icon"],
                "icons": [k],
                "origin": "from icon",
            }
        )
        alive.append(True)
        icon_nodes.append(len(nodes) - 1)

    # a map placed from a badge next to a found map carrying the same badge is that map (user: -15,1291 / -44,1278)
    for i in icon_nodes:
        if not alive[i]:
            continue
        names = {icons[k]["name"] for k in nodes[i]["icons"]}
        for j in det_grid.near((nodes[i]["x"], nodes[i]["y"]), ICON_TWIN):
            if j == i or not alive[j] or nodes[j].get("origin") == "from icon":
                continue
            if names & {icons[k]["name"] for k in nodes[j]["icons"]}:
                nodes[j]["frames"] |= nodes[i]["frames"]
                nodes[j]["icons"] = sorted(set(nodes[j]["icons"]) | set(nodes[i]["icons"]))
                alive[i] = False
                removed_why[i] = f"badge copy of map {j}"
                break

    # ---- 1b. support: how many screenshots could see each node vs. found it
    pts = P()
    could = np.zeros(len(nodes), int)
    for f, Hi in maps:
        could += _visible(f, Hi, pts)[1]
    status = []
    for i, n in enumerate(nodes):
        seen = len(n["frames"])
        n["could"] = int(max(could[i], seen))
        if not alive[i]:
            status.append("removed")
        elif n["icons"] and any(icons[k]["name"] not in NO_NODE_ICONS for k in n["icons"]):
            status.append("icon")
        elif seen >= 2:
            status.append("confirmed")
        elif could[i] <= 1:
            status.append("single")
        elif could[i] >= 3:
            status.append("removed")
            removed_why[i] = f"ghost: found in 1 of {could[i]} screenshots that show this spot"
        else:
            status.append("disputed")  # 1 of 2: decided by paths below

    # relative evidence (user): a map found by few of the screenshots that show it, among neighbours found by
    # nearly all of them, is a ghost - even when 2+ screenshots found it
    ratio = np.array([len(n["frames"]) / max(1, n["could"]) for n in nodes])
    live = [i for i in range(len(nodes)) if status[i] in ("confirmed", "disputed", "single")]
    lgrid = _Grid(pts[live], RATIO_R) if live else None
    for _q, i in enumerate(live):
        n = nodes[i]
        if n["tower"] or n["icons"] or n["could"] < min(RATIO_COULD, RATIO_COULD_REL):
            continue
        nb = [live[k] for k in lgrid.near(pts[i], RATIO_R) if live[k] != i]
        if not nb:
            continue
        med = float(np.median(ratio[nb]))
        absolute = n["could"] >= RATIO_COULD and ratio[i] <= RATIO_GHOST and med >= RATIO_NEAR
        relative = med >= RATIO_REL_NEAR and ratio[i] <= RATIO_REL * med  # user D57/D55: 4/9 among 89%, 2/4 among 100%
        if absolute or relative:
            status[i] = "removed"
            removed_why[i] = (
                f"ghost: found in {len(n['frames'])} of {n['could']} screenshots, its neighbours in "
                f"{float(np.median(ratio[nb])):.0%}"
            )
    # the gap rule (user): maps (shown or hidden) are drawn OVER the dotted lines, so where a map is, the dashes
    # stop. A "map" with amber dashes inside its ring in every screenshot that clearly shows it is a dash
    # pattern, not a map
    best_score = np.ones(len(nodes))  # (stays 1 = "clearly visible" when the gap block is off)
    if GAP_ON:
        gap_n = np.zeros(len(nodes), int)
        gap_free = np.zeros(len(nodes), bool)
        best_score = np.zeros(len(nodes))
        from scipy.spatial import cKDTree as _KD

        for f, Hi in maps:
            rec = _saved(atlas, f)
            if rec is None:
                continue
            sp, ok = _visible(f, Hi, pts)
            idx = np.nonzero(ok)[0]
            if not len(idx):
                continue
            if len(rec["P"]):  # the map finder's confidence at each spot
                dd, qq = _KD(rec["P"]).query(sp[idx])
                hitm = dd <= 15
                best_score[idx[hitm]] = np.maximum(best_score[idx[hitm]], rec["score"][qq[hitm]])
            cnt = (
                np.array([len(x) for x in rec["tree"].query_ball_point(sp[idx], GAP_R)])  # all dashes (dim too)
                if rec["tree"] is not None
                else np.zeros(len(idx), int)
            )
            gap_n[idx] += 1
            gap_free[idx[cnt < GAP_MIN]] = True
        for i in range(len(nodes)):
            if (
                status[i] not in ("removed", "icon")
                and not nodes[i]["tower"]
                and not nodes[i]["icons"]
                and best_score[i] < GAP_SEEN
                and gap_n[i] >= GAP_SHOTS
                and not gap_free[i]
                and len(nodes[i]["frames"]) < GAP_FOUND * max(1, nodes[i].get("could", 0))
            ):
                status[i] = "removed"
                removed_why[i] = f"no gap in the dotted line in any of {gap_n[i]} screenshots: not a map"

    # maps on the fortress wall are wall art (user), unless towers
    on_wall = np.zeros(len(nodes), int)
    shown = np.zeros(len(nodes), int)
    for f, Hi in maps:
        rec = _saved(atlas, f)
        if rec is None or not rec["wall"].any():
            continue
        sp, ok = _visible(f, Hi, pts)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            continue
        g, c = rec["wall"], atlas_detect.WALL_CELL
        gx = np.clip((sp[idx, 0] // c).astype(int), 0, g.shape[1] - 1)
        gy = np.clip((sp[idx, 1] // c).astype(int), 0, g.shape[0] - 1)
        shown[idx] += 1
        on_wall[idx] += g[gy, gx]
    for i in range(len(nodes)):
        if status[i] != "removed" and not nodes[i]["tower"] and shown[i] and on_wall[i] >= WALL_MAP * shown[i]:
            status[i] = "removed"
            removed_why[i] = f"on the fortress wall in {on_wall[i]} of {shown[i]} screenshots"

    # ---- 3. abyss chains
    forced: list[tuple[int, int]] = []
    no_other: set[int] = set()
    chain_segments = []
    landmarks = [dict(lm, status="kept") for lm in atlas.landmarks]

    def abyss_count(i):
        return sum(icons[k]["name"] in ABYSS_NAMES for k in nodes[i]["icons"])

    ab = [i for i in range(len(nodes)) if status[i] != "removed" and abyss_count(i)]
    seen_ab, chains = set(), []
    for s in ab:
        if s in seen_ab:
            continue
        comp, stack = [], [s]
        seen_ab.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in ab:
                if (
                    v not in seen_ab
                    and math.hypot(nodes[u]["x"] - nodes[v]["x"], nodes[u]["y"] - nodes[v]["y"]) < ABYSS_LINK
                ):
                    seen_ab.add(v)
                    stack.append(v)
        if len(comp) >= 2:
            chains.append(comp)
    for comp in chains:
        cp = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in comp])
        tree = [(comp[a], comp[b]) for a, b in _mst(cp)]
        deg = {i: 0 for i in comp}
        for a, b in tree:
            deg[a] += 1
            deg[b] += 1

        def overrun(i):
            return any(icons[k]["name"] == "AbyssOverrun" for k in nodes[i]["icons"])

        final = max(comp, key=lambda i: (abyss_count(i), overrun(i), -deg[i]))
        ends = [i for i in comp if deg[i] == 1 and i != final]
        start = max(
            ends or comp, key=lambda i: math.hypot(nodes[i]["x"] - nodes[final]["x"], nodes[i]["y"] - nodes[final]["y"])
        )
        forced += tree
        no_other |= set(comp) - {start, final}
        for i in comp:
            nodes[i]["abyss"] = "final" if i == final else "start" if i == start else "chain"
        for a, b in tree:
            chain_segments.append((a, b, {start, final}))
    if chain_segments:

        def near_chain(p, clear):
            for a, b, open_ends in chain_segments:
                pa = np.array([nodes[a]["x"], nodes[a]["y"]])
                pb = np.array([nodes[b]["x"], nodes[b]["y"]])
                dist, t = _seg_dist(p, pa, pb)
                if (t < 0.2 and a in open_ends) or (t > 0.8 and b in open_ends):
                    continue  # next to the chain's entry/exit map: may be a real neighbour
                if dist < clear:
                    return True
            return False

        chain_nodes = {i for a, b, _ in chain_segments for i in (a, b)}
        cpts = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in chain_nodes])
        cgrid = _Grid(cpts, ABYSS_LINK)
        for i, n in enumerate(nodes):
            if status[i] == "removed" or i in chain_nodes or status[i] == "icon":
                continue
            if not cgrid.near((n["x"], n["y"]), ABYSS_LINK + ABYSS_TOWER_CLEAR):
                continue
            if near_chain(np.array([n["x"], n["y"]]), ABYSS_CLEAR):
                status[i] = "removed"
                removed_why[i] = "abyss river glow"
        for lm in landmarks:
            if lm["kind"] == "Tower" and near_chain(np.array([lm["x"], lm["y"]]), ABYSS_TOWER_CLEAR):
                lm["status"] = "removed: abyss river glow"

    # ---- 4. atlas-wide paths
    keep = [i for i in range(len(nodes)) if status[i] != "removed"]
    pts = np.array([[nodes[i]["x"], nodes[i]["y"]] for i in keep], float).reshape(-1, 2)
    pos = {i: k for k, i in enumerate(keep)}
    tower = np.array([nodes[i]["tower"] for i in keep], bool)
    blocked_ends = {pos[i] for i in no_other if i in pos}
    maps_by_name = [(f["name"], Hi) for f, Hi in maps]
    views = []
    for f, Hi in maps:
        sp, ok = _visible(f, Hi, pts, margin=6)
        if ok.sum() >= 2:
            views.append((f, sp, ok))
    fields: dict[str, np.ndarray] = {}

    def field(f):
        if f["name"] not in fields:
            fields[f["name"]] = _gold(atlas, f)[1].astype(np.float32)
        return fields[f["name"]]

    cache: dict[tuple[int, int], tuple[float, int, int]] = {}
    node_views: list[set] = [set() for _ in range(len(pts))]
    for vi, (_f, _sp, ok) in enumerate(views):
        for i in np.nonzero(ok)[0]:
            node_views[int(i)].add(vi)
    pts_grid = _Grid(pts, 100.0)

    def score(i, j):
        key = (min(i, j), max(i, j))
        if key not in cache:
            vals = [
                gp.route_score(field(views[vi][0]), views[vi][1][i], views[vi][1][j])
                for vi in sorted(node_views[i] & node_views[j])
            ]
            cache[key] = ((float(np.mean(vals)) if vals else 0.0), len(vals), sum(v >= PATH_THRESHOLD for v in vals))
        return cache[key]

    proposals = []
    n = len(pts)
    visited = set()
    for i in range(n):
        if i in blocked_ends:
            continue
        local = np.array(pts_grid.near(pts[i], 300.0), int)
        dist_l = np.linalg.norm(pts[local] - pts[i], axis=1)
        for q in np.argsort(dist_l)[1:11]:
            j = int(local[q])
            x, y = min(i, j), max(i, j)
            if j in blocked_ends or not 30 <= dist_l[q] <= 300 or (x, y) in visited:
                continue
            visited.add((x, y))
            delta = pts[y] - pts[x]
            L2 = float(delta @ delta)
            loc = np.array(pts_grid.near(pts[x], math.sqrt(L2) + 30), int)  # maps near this link
            lp = pts[loc]
            t = ((lp - pts[x]) @ delta) / L2
            nearest = pts[x] + t[:, None] * delta
            blocking = (np.linalg.norm(lp - nearest, axis=1) < 24) & (t > 0.12) & (t < 0.88) & (loc != x) & (loc != y)
            if blocking.any():
                continue
            bad = False
            for s, e in ((x, y), (y, x)):
                out = pts[e] - pts[s]
                L = float(np.linalg.norm(out))
                ls = np.array(pts_grid.near(pts[s], L), int)
                v = pts[ls] - pts[s]
                vl = np.linalg.norm(v, axis=1)
                cosang = (v @ out) / np.maximum(1e-9, vl * L)
                for k in ls[np.nonzero((vl >= 30) & (vl < L * 0.88) & (cosang > 0.936))[0]]:
                    if int(k) not in (x, y) and score(s, int(k))[0] >= 0.53:
                        bad = True
                        break
                if bad:
                    break
            if bad:
                continue
            c, nf, ns = score(x, y)
            if nf and c >= (TOWER_THRESHOLD if tower[x] or tower[y] else PROPOSE):
                proposals.append((x, y, c, float(np.linalg.norm(delta))))
    supported = {(x, y): c for x, y, c, _ in proposals}
    proposals = [
        p
        for p in proposals
        if not _diamond_shortcut(pts, pts_grid, p[0], p[1], supported)
        and not _bypasses_two(pts, pts_grid, p[0], p[1], supported)
    ]

    def need(i, j):
        return TOWER_THRESHOLD if tower[i] or tower[j] else PATH_THRESHOLD

    # paths as each screenshot traced them when it was detected (saved): traced once, never again (user).
    # The clearest trace of a pair gives its line; the other screenshots only confirm or deny it.
    traces: dict[tuple[int, int], dict] = {}
    Hs = {name: np.linalg.inv(Hi) for name, Hi in maps_by_name}

    def add_trace(f, i, j, line_screen, mutual, dashes):
        if i in blocked_ends or j in blocked_ends or i == j:
            return
        key = (min(i, j), max(i, j))
        L = np.asarray(line_screen, float)
        straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
        detour = float(np.hypot(*np.diff(L, axis=0).T).sum()) / straight
        t = traces.setdefault(
            key,
            {
                "frames": set(),
                "mutual": set(),
                "dashes": 0,
                "line": None,
                "detour": 1e9,
                "clear": (-1, 0.0, 0),
                "confirm": 0,
                "deny": 0,
                "contra": 0,
            },
        )
        t["frames"].add(f["name"])
        if mutual:
            t["mutual"].add(f["name"])
        t["dashes"] = max(t["dashes"], int(dashes))
        t["detour"] = min(t["detour"], detour)
        if int(dashes) >= 5 and len(L) >= 2:  # the smoothest well-dashed trace judges the curve
            ch = L[-1] - L[0]
            n2 = float(ch @ ch)
            if n2 > 1:
                v = L - L[0]
                b_ = float(np.abs(ch[0] * v[:, 1] - ch[1] * v[:, 0]).max() / n2)
                t["minbow"] = min(t.get("minbow", 9.0), b_)
        clear = (1 if mutual else 0, min(int(dashes), 8), -round(detour, 3))  # end-to-end, enough dashes, smoothest
        if clear > t["clear"]:  # (user D31/D32: a wobbly trace drew a straight path)
            t["clear"] = clear
            line = core.persp(Hs[f["name"]], L)
            line = cv2.approxPolyDP(line.astype(np.float32).reshape(-1, 1, 2), 2.5, False).reshape(-1, 2)
            if i > j:
                line = line[::-1]
            t["line"] = line.astype(float)

    from scipy.spatial import cKDTree

    old_way = []
    for f, sp, ok in views:
        rec = _saved(atlas, f)
        if rec is None:
            old_way.append((f, sp, ok))
            continue
        vis = np.nonzero(ok)[0]
        if not len(vis) or not len(rec["P"]):
            continue
        dist, q = cKDTree(sp[vis]).query(rec["P"])
        to_atlas = {k: int(vis[q[k]]) for k in range(len(rec["P"])) if dist[k] <= TRACE_MATCH}
        # atlas maps this screenshot's own detection missed: its saved traces cannot reach them, so the area
        # around them is traced again with the atlas maps (only there: v0.91 re-traced every screenshot)
        found = set(to_atlas.values())
        missing = [int(i) for i in vis if int(i) not in found]
        if missing and LOCAL_RETRACE > 0:
            local = np.zeros(len(sp), bool)
            mp = sp[missing]
            for i in vis:
                if np.min(np.hypot(mp[:, 0] - sp[i, 0], mp[:, 1] - sp[i, 1])) <= LOCAL_RETRACE:
                    local[i] = True
            if local.sum() >= 2:
                miss = set(missing)
                for (i, j), r in atlas_detect.screen_paths(_dashes(atlas, f), sp, local, tower).items():
                    if (i in miss or j in miss) and _on_wall(rec, r["line"]) < atlas_detect.WALL_CROSS:
                        add_trace(f, i, j, r["line"], len(r["from"]) == 2, r["dashes"])
        for e in rec["edges"]:
            i, j = to_atlas.get(e["a"]), to_atlas.get(e["b"])
            if i is None or j is None:
                continue
            L = np.asarray(e["line"], float)
            if _on_wall(rec, L) >= atlas_detect.WALL_CROSS:
                continue  # through the fortress wall (detected before v0.92)
            seen, cov = _coverage(rec, f, L)
            dashes = int(round(cov * seen * len(_along(L))))
            dashes = max(dashes, int(round(float(e.get("conf", 0)) * 10)))  # the tracer's own count (dark ground)
            add_trace(f, i, j, L, e.get("status") == "chain", dashes)
    for f, _sp, _ok, res in _trace_views(atlas, old_way, tower, log) if old_way else []:
        for (i, j), r in res.items():
            add_trace(f, i, j, r["line"] if i < j else r["line"][::-1], len(r["from"]) == 2, r["dashes"])

    # every other screenshot that shows both maps: dashes along the line confirm it; a clearly visible,
    # empty stretch denies it; dark / fog / blurred / off-screen says nothing (user's image 3)
    for (i, j), t in traces.items():
        if t["line"] is None:
            continue
        for vi in node_views[i] & node_views[j]:
            f = views[vi][0]
            if f["name"] in t["frames"]:
                continue
            rec = _saved(atlas, f)
            if rec is None:
                continue
            Ls = core.persp(maps_by[f["name"]][1], t["line"])
            if _on_wall(rec, Ls) >= atlas_detect.WALL_CROSS:
                t["deny"] += 1  # this screenshot shows the wall in its way (one vote:
                # the wall model can be a little off at its edges)
                continue
            seen, cov = _coverage(rec, f, Ls)
            if seen >= CHECK_SEEN:
                if cov >= CONFIRM:
                    t["confirm"] += 1  # dashes there (only for ranking: a wrong walk can run
                else:  # along real dashes for most of its way)
                    t["contra"] += 1  # clearly visible, its own tracer did not draw it
                    if cov < DENY:
                        t["deny"] += 1  # clearly visible and empty

    # ---- seams: two maps that no screenshot shows together (user). Their path is a dead end in each
    # screenshot; the dashes of all screenshots around them are put together in atlas coordinates and
    # walked like one screenshot. Only pairs without any trace; the usual rules judge the result.
    seam_n = 0
    det = (
        [] if not SEAM_ON else [nodes[keep[k]]["frames"] - nodes[keep[k]]["guessed"] for k in range(n)]
    )  # screenshots that FOUND it
    for i in range(n if SEAM_ON else 0):
        if i in blocked_ends or not node_views[i]:
            continue
        for j in pts_grid.near(pts[i], SEAM_MAX):
            if j <= i or j in blocked_ends or not node_views[j] or (i, j) in traces:
                continue
            if det[i] & det[j] or not det[i] or not det[j]:
                continue  # some screenshot found both: it traced them itself
            dij = float(np.hypot(*(pts[i] - pts[j])))
            if dij < SEAM_MIN:
                continue
            lo = np.minimum(pts[i], pts[j]) - SEAM_PAD
            hi = np.maximum(pts[i], pts[j]) + SEAM_PAD
            D, src = [], {}
            for vi in node_views[i] | node_views[j]:
                f = views[vi][0]
                if f["name"] not in det[i] | det[j]:
                    continue  # only screenshots that found one of the two
                rec = _saved(atlas, f)
                if rec is None or rec["tree"] is None:
                    continue
                q = core.persp(Hs[f["name"]], rec["tree"].data)
                q = q[(q[:, 0] >= lo[0]) & (q[:, 0] <= hi[0]) & (q[:, 1] >= lo[1]) & (q[:, 1] <= hi[1])]
                if len(q):
                    D.append(q)
                    src[f["name"]] = "i" if f["name"] in det[i] else "j"
            if len(D) < 2 or set(src.values()) != {"i", "j"}:
                continue
            D = np.unique(np.round(np.vstack(D) / 3) * 3, axis=0)  # overlapping shots: same dash once
            loc = [k for k in pts_grid.near((pts[i] + pts[j]) / 2, dij / 2 + SEAM_PAD)]
            local = [{"x": float(pts[k][0]), "y": float(pts[k][1]), "tower": bool(tower[k])} for k in loc]
            ii, jj = loc.index(i), loc.index(j)
            for w in atlas_detect.walk_paths(local, D):
                if {w["a"], w["b"]} != {ii, jj}:
                    continue
                L = np.asarray(w["line"], float)
                if w["a"] != ii:
                    L = L[::-1]
                straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
                traces[(i, j)] = {
                    "frames": set(src),
                    "mutual": set(),
                    "dashes": int(w["dashes"]),
                    "line": L,
                    "detour": float(np.hypot(*np.diff(L, axis=0).T).sum()) / straight,
                    "clear": (0, min(int(w["dashes"]), 8), 0.0),
                    "confirm": 0,
                    "deny": 0,
                    "contra": 0,
                    "seam": True,
                }
                for vi in node_views[i] | node_views[j]:  # a wall on either side stops it
                    rec = _saved(atlas, views[vi][0])
                    if _on_wall(rec, core.persp(maps_by[views[vi][0]["name"]][1], L)) >= atlas_detect.WALL_CROSS:
                        traces[(i, j)]["deny"] += 99
                seam_n += 1
                break
    if log and seam_n:
        log(f"paths across screenshot seams: {seam_n} candidates")

    def could_both(i, j):
        return len(node_views[i] & node_views[j])

    def passed_maps(key, line, clear=None):
        """the third maps a path's line runs past (interior points within PASS_CLEAR, or `clear`)"""
        if line is None or len(line) < 3:
            return set()
        dense = np.vstack([np.linspace(a0, a1, 6) for a0, a1 in zip(line[:-1], line[1:], strict=False)])
        ends = pts[list(key)]
        inner = dense[(np.linalg.norm(dense - ends[0], axis=1) > 20) & (np.linalg.norm(dense - ends[1], axis=1) > 20)]
        return {k for q in inner for k in pts_grid.near(q, clear or PASS_CLEAR) if k not in key}

    def weak_map(k):
        nd = nodes[keep[k]]
        return nd.get("origin") == "from icon" or len(nd["frames"]) < PASS_WEAK * max(1, nd.get("could", 1))

    ends_at: dict = {}  # traced paths ending at each map (any screenshot)
    for a_, b_ in traces:
        ends_at[a_] = ends_at.get(a_, 0) + 1
        ends_at[b_] = ends_at.get(b_, 0) + 1
    run_by: dict = {}
    run_over: set = set()  # weak maps a strongly traced path runs through: ghosts (user D54 etc.)

    def passes_a_map(key, line, t=None):
        """a path never runs past a third map: interior points within PASS_CLEAR of one. A path traced end to end
        in 2+ screenshots may pass a map: a weak one there is a ghost (dropped), a well-seen one a floating map"""
        if t is not None and len(t["mutual"]) >= 2:
            on_line = passed_maps(key, line, RUN_OVER)  # ON the line only
            on_line = {k for k in on_line if ends_at.get(k, 0) < JUNCTION}
            if on_line and all(weak_map(k) for k in on_line):
                for k in on_line:
                    run_over.add(k)
                    run_by.setdefault(k, key)
                return False
            if not on_line and not (passed_maps(key, line) - set()):
                return False
            return on_line  # beside a map, not on it: allowed (floating map)
        if line is None or len(line) < 3:
            return False
        dense = np.vstack([np.linspace(a0, a1, 6) for a0, a1 in zip(line[:-1], line[1:], strict=False)])
        ends = pts[list(key)]
        inner = dense[(np.linalg.norm(dense - ends[0], axis=1) > 20) & (np.linalg.norm(dense - ends[1], axis=1) > 20)]
        if not len(inner):
            return False
        return any(any(k not in key for k in pts_grid.near(q, PASS_CLEAR)) for q in inner)

    def start_dir(line, frm):
        """unit direction a path leaves map `frm` (first START_LEN of its line)"""
        L = np.asarray(line, float)
        if np.hypot(*(L[0] - pts[frm])) > np.hypot(*(L[-1] - pts[frm])):
            L = L[::-1]
        cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(L, axis=0).T))])
        q = L[min(int(np.searchsorted(cum, START_LEN)), len(L) - 1)]
        v = q - pts[frm]
        n = float(np.hypot(*v))
        return v / n if n > 1e-6 else (L[-1] - L[0]) / max(1e-6, float(np.hypot(*(L[-1] - L[0]))))

    def skips_nearer(key, line):
        """user's sector rule: a path heading (within SECTOR) for a map that is nearer than its end goes there"""
        cos_s, cos_strict = math.cos(math.radians(SECTOR)), math.cos(math.radians(SECTOR_STRICT))
        for frm, to in (key, key[::-1]):
            d_end = float(np.hypot(*(pts[to] - pts[frm])))
            u = start_dir(line, frm)
            for k in pts_grid.near(pts[frm], d_end * SECTOR_NEAR):
                if k in key:
                    continue
                v = pts[k] - pts[frm]
                dk = float(np.hypot(*v))
                if dk < 30 or float(v @ u) / dk < cos_s:
                    continue
                kk = (min(frm, k), max(frm, k))
                if float(v @ u) / dk >= cos_strict or kk in traces or score(frm, k)[0] >= 0.53:
                    return True  # dead ahead: always; in the sector: with evidence
        return False

    def bow(line):
        L = np.asarray(line, float)
        ch = L[-1] - L[0]
        n = float(np.hypot(*ch))
        if n < 1:
            return 0.0
        v = L - L[0]
        return float(np.abs(ch[0] * v[:, 1] - ch[1] * v[:, 0]).max() / n / n)

    def s_shaped(line):
        """user: a path changes direction once. S-shaped = it bows clearly to BOTH sides of the line between
        its ends (a straight trace's pixel wobble no longer counts: user's straight S15 was called S-shaped)"""
        L = np.asarray(line, float)
        if len(L) < 4:
            return False
        ch = L[-1] - L[0]
        n_ = float(np.hypot(*ch))
        if n_ < 1:
            return False
        v = L - L[0]
        side = (ch[0] * v[:, 1] - ch[1] * v[:, 0]) / n_  # signed px from the chord
        lim = max(S_BOW_PX, S_BOW * n_)
        if side.max() >= lim and side.min() <= -lim:
            return True
        # turning clearly one way and then the other (summed turns), with real bends to both sides
        a_ = np.degrees(np.arctan2(*np.diff(L, axis=0)[:, ::-1].T))
        turn = (np.diff(a_) + 180) % 360 - 180
        both = side.max() >= S_WOBBLE_PX and side.min() <= -S_WOBBLE_PX
        return both and min(turn[turn > 0].sum(), -turn[turn < 0].sum()) >= S_TURN

    def clumped(t):
        """share of the trace (in the screenshots that drew it) that runs through dash CLUMPS: a real path is
        one row of spaced dashes; amber trees and lit structures give piles of them (user: 2499 -> 2533)"""
        worst = 0.0
        for name in list(t["frames"])[:4]:
            if name not in maps_by:
                continue
            f, Hi = maps_by[name]
            rec = _saved(atlas, f)
            if rec is None or rec["tree"] is None:
                continue
            q = _along(core.persp(Hi, t["line"]), 6.0, 20.0)
            if not len(q):
                continue
            cnt = np.array([len(x) for x in rec["tree"].query_ball_point(q, CLUMP_R)])
            worst = max(worst, float((cnt >= CLUMP_N).mean()))
        return worst >= CLUMP_SHARE

    def ends_point(key, line):
        """user: a real path leaves BOTH its maps pointing at the other one. For each end, some screenshot
        that found that map shows dashes 15-50 px out of it within END_CONE degrees of the path's direction"""
        cos_c = math.cos(math.radians(END_CONE))
        for e in key:
            o = key[1] if e == key[0] else key[0]
            u = (pts[o] - pts[e]) / max(1e-6, float(np.hypot(*(pts[o] - pts[e]))))  # straight at the other map
            ok = False
            for vi in list(node_views[e])[:END_VIEWS]:
                f = views[vi][0]
                rec = _saved(atlas, f)
                if rec is None or rec["tree"] is None:
                    continue
                Hi = maps_by[f["name"]][1]
                se = core.persp(Hi, [pts[e]])[0]
                ahead = core.persp(Hi, [pts[e] + u * 40.0])[0] - se
                n_ = float(np.hypot(*ahead))
                if n_ < 1e-6:
                    continue
                ahead /= n_
                near = rec["tree"].query_ball_point(se, END_REACH[1])
                if not near:
                    continue
                v = rec["tree"].data[near] - se
                d = np.hypot(v[:, 0], v[:, 1])
                m = (d >= END_REACH[0]) & ((v @ ahead) >= cos_c * np.maximum(d, 1e-6))
                if int(m.sum()) >= END_DASHES:
                    ok = True
                    break
            if not ok:
                return False
        return True

    def trace_ok(key, t):
        if passes_a_map(key, t["line"], t):
            t["why"] = "runs past a third map"
            return False
        strong_ = len(t["mutual"]) >= 2 and not t.get("seam")
        if t["line"] is not None and t.get("minbow", bow(t["line"])) > (MAX_BOW_STRONG if strong_ else MAX_BOW):
            t["why"] = "curves too much for its length"
            return False
        strong = not t.get("seam") and (len(t["mutual"]) >= 2 or len(t["frames"]) >= 2)  # traced end to end
        if t.get("seam") and (t["dashes"] < SEAM_DASHES or t["deny"]):  # twice / in 2+ shots (seams: never)
            t["why"] = "seam: too few dashes / wall"
            return False
        if not strong and t["line"] is not None and s_shaped(t["line"]):  # user: real paths can have a mild S
            t["why"] = "s-shaped"
            return False
        if not strong and t["line"] is not None and skips_nearer(key, t["line"]):
            t["why"] = "skips a nearer map"
            return False
        support = len(t["frames"]) if not t.get("seam") else 2  # screenshots whose own tracer drew it
        if not t["mutual"] and not t.get("seam") and support < ONE_END_SHARE * could_both(*key):
            t["why"] = "only one-end traces, drawn by under half the screenshots that show both maps"
            return False
        if not strong_ and t["line"] is not None and clumped(t):
            t["why"] = "runs through clumps of dashes (amber trees / structure lights), not a row of dashes"
            return False
        if not t["mutual"] and t["line"] is not None and not ends_point(key, t["line"]):
            t["why"] = "an end map shows no dashes leaving toward the other map"
            return False
        if not t["mutual"] and t["contra"] > support:
            t["why"] = "more clear screenshots show both maps without it than drew it"
            return False
        if support >= 2 or (t["mutual"] and t["contra"] == 0):  # drawn twice, or both ends reached and no
            return t["deny"] < support  # clear view contradicts it
        # one one-end trace (a walk that may have run on where that screenshot missed a map): kept unless a
        # clearly visible view shows both maps without it; dark / fog / off-screen views never count (user)
        if t["dashes"] >= 5 and t["contra"] == 0:
            return True
        t["why"] = (
            "one weak one-end trace" if t["dashes"] < 5 else "one trace, and a clear view shows both maps without it"
        )
        return False

    degree = np.zeros(n, int)
    chosen: list[tuple[int, int, float, str, np.ndarray]] = []  # i, j, confidence, kind, shape

    def shape_of(i, j, line=None):
        return line if line is not None and len(line) >= 2 else np.array([pts[i], pts[j]])

    seg_cells: dict[tuple[int, int], list[int]] = {}
    SEG_CELL = 150.0

    def cells_of(shp):
        lo, hi = np.floor(shp.min(axis=0) / SEG_CELL).astype(int), np.floor(shp.max(axis=0) / SEG_CELL).astype(int)
        return [(gx, gy) for gx in range(lo[0], hi[0] + 1) for gy in range(lo[1], hi[1] + 1)]

    pair_set: set = set()

    crossed = [None]

    def crosses(i, j, shp):
        near = {c for cell in cells_of(shp) for c in seg_cells.get(cell, ())}
        for idx in near:
            k, other_idx, _, kind_o, other = chosen[idx]
            if len({i, j, k, other_idx}) < 4:
                continue
            for a0, a1 in zip(shp[:-1], shp[1:], strict=False):
                for b0, b1 in zip(other[:-1], other[1:], strict=False):
                    if gp._crosses(a0, a1, b0, b1):
                        crossed[0] = (min(k, other_idx), max(k, other_idx), kind_o)
                        return True
        return False

    exits: dict[int, list] = {}

    def same_sector(i, j, shp):
        """another chosen path already leaves i (or j) in this direction (user's sector rule)"""
        cos_s = math.cos(math.radians(SECTOR * 0.8))
        for frm in (i, j):
            u = start_dir(shp, frm)
            if any(float(u @ w) > cos_s for w in exits.get(frm, [])):
                return True
        return False

    blocked_by: dict = {}  # (inspection aid) pair -> why selection refused it

    def take(i, j, conf, kind, shp):
        kk = (min(i, j), max(i, j))
        if kk in pair_set:
            return False
        if degree[i] >= MAX_EXITS or degree[j] >= MAX_EXITS:
            blocked_by.setdefault(kk, "5 paths already")
            return False
        tk = traces.get((min(i, j), max(i, j)))
        sure = tk is not None and (len(tk["mutual"]) >= 2 or len(tk["frames"]) >= 3)
        if kind != "abyss" and not sure and same_sector(i, j, shp):
            if (min(i, j), max(i, j)) in traces:
                traces[(min(i, j), max(i, j))]["why"] = "same sector as a chosen path"
            return False
        if kind != "abyss" and crosses(i, j, shp):
            blocked_by.setdefault(kk, ("crosses", crossed[0]))
            return False
        chosen.append((i, j, conf, kind, shp))
        pair_set.add((min(i, j), max(i, j)))
        for cell in cells_of(shp):
            seg_cells.setdefault(cell, []).append(len(chosen) - 1)
        degree[[i, j]] += 1
        for frm in (i, j):
            exits.setdefault(frm, []).append(start_dir(shp, frm))
        return True

    for a, b in forced:
        if a in pos and b in pos:
            take(pos[a], pos[b], 1.0, "abyss", shape_of(pos[a], pos[b]))
    ranked = sorted(
        ((k, t) for k, t in traces.items() if trace_ok(k, t)),
        key=lambda kt: (
            -len(kt[1]["mutual"]),
            -len(kt[1]["frames"]),
            -kt[1]["confirm"],
            -kt[1]["dashes"],
            round(kt[1]["detour"], 2),
            float(np.linalg.norm(pts[kt[0][0]] - pts[kt[0][1]])),
        ),
    )
    globals()["_last_traces"] = (traces, pts)
    globals()["_last_blocked"] = blocked_by
    globals()["_last_run_by"] = (run_by, pts)  # (inspection aid for tests / debugging)
    for (i, j), t in ranked:
        take(i, j, 1.0, "traced", shape_of(i, j, t["line"]))

    def walled(i, j):
        """a straight link through the fortress wall in any screenshot that shows it"""
        for vi in node_views[i] & node_views[j]:
            f, sp, _ok = views[vi]
            rec = _saved(atlas, f)
            if rec is not None and _on_wall(rec, np.array([sp[i], sp[j]])) >= atlas_detect.WALL_CROSS:
                return True
        return False

    proposals = [p for p in proposals if not walled(p[0], p[1])]
    rejected = {k for k, t in traces.items() if not trace_ok(k, t)}  # a traced pair judged not a path:
    proposals = [p for p in proposals if (min(p[0], p[1]), max(p[0], p[1])) not in rejected]  # no straight line either
    # an untraced straight link: only with gold along it in STRAIGHT_VIEWS screenshots and not too long
    # (user: missing a real path is better than a fake one - later screenshots fill the gaps)
    proposals = [p for p in proposals if score(p[0], p[1])[2] >= STRAIGHT_VIEWS and p[3] <= STRAIGHT_MAX]
    for i, j, c, _L in sorted(proposals, key=lambda p: (-int(p[2] >= need(p[0], p[1])), p[3], -p[2])):
        if c >= need(i, j):
            take(i, j, c, "straight", shape_of(i, j))
    for i, j, c, _L in sorted(proposals, key=lambda p: (p[3], -p[2])):  # one weak link for a lonely node
        if c < need(i, j) and c >= PROPOSE and not (degree[i] and degree[j]):
            take(i, j, c, "straight", shape_of(i, j))

    # weak maps that a path traced end to end runs straight through are ghosts: removed with their paths
    for k in run_over:
        i = keep[k]
        if status[i] != "removed":
            status[i] = "removed"
            removed_why[i] = "a path traced end to end runs through it: not a map"
    if run_over:
        chosen[:] = [c for c in chosen if c[0] not in run_over and c[1] not in run_over]
        for k in run_over:
            degree[k] = 0

    # ---- 5. nodes nobody can corroborate
    for k, i in enumerate(keep):
        if degree[k]:
            continue
        if status[i] == "disputed":
            status[i] = "removed"
            removed_why[i] = "found in 1 of 2 screenshots and no dotted path reaches it"
        elif status[i] == "single" and not nodes[i]["tower"]:
            status[i] = "doubtful"
        elif (
            LONELY_ON
            and status[i] == "confirmed"
            and not nodes[i]["tower"]
            and not nodes[i]["icons"]
            and nodes[i].get("could", 0) >= LONELY_SHOTS
            and best_score[i] < LONELY_SEEN
        ):
            # user: a map with no badge and no path is very unlikely; a real floating map is rare and never hidden,
            # losing a few of them is better than keeping the ghosts. Only inside the explored area (3+ shots)
            status[i] = "removed"
            removed_why[i] = "no badge and no path reaches it"

    # ---- 6. landmarks: Halls / Cities by beam colour, then the seen / could-see test
    landmarks = _settlements(atlas, maps, landmarks, icons)
    for lm in landmarks:
        if lm["status"] != "kept" or lm.get("beam"):
            continue
        c = sum(_visible(f, Hi, [[lm["x"], lm["y"]]], margin=30)[1][0] for f, Hi in maps)
        lm["could"] = int(max(c, lm["n"]))
        if lm["n"] == 1 and c >= 3:
            lm["status"] = f"removed: found in 1 of {c} screenshots"
        elif lm["n"] == 1 and c == 2:
            lm["status"] = "disputed"

    # one of each badge per map (user): a second copy of the same badge on one map is the same badge seen
    # elsewhere (mountain parallax): the copy seen in fewer screenshots is dropped
    dup_badge: set = set()
    for nd in nodes:
        best: dict = {}
        for k in nd["icons"]:
            nm = icons[k]["name"]
            if nm == "Unidentified":
                continue
            if nm in best:
                lo, hi = sorted((best[nm], k), key=lambda q: icons[q]["n"])
                dup_badge.add(lo)
                best[nm] = hi
            else:
                best[nm] = k
        # two badges on the SAME spot of one map are one badge read two ways (Delirium / Grand Mirror / Ancient
        # Trove get confused): the reading seen more often wins (user D34-D36)
        ks = sorted((k for k in nd["icons"] if k not in dup_badge), key=lambda q: -icons[q]["n"])
        for a_, k1 in enumerate(ks):
            if k1 in dup_badge:
                continue
            for k2 in ks[a_ + 1 :]:
                if (
                    k2 not in dup_badge
                    and math.hypot(icons[k1]["x"] - icons[k2]["x"], icons[k1]["y"] - icons[k2]["y"]) < SAME_SPOT
                ):
                    dup_badge.add(k2)
        nd["icons"] = [k for k in nd["icons"] if k not in dup_badge]

    out_nodes = []
    for i, nd in enumerate(nodes):
        out_nodes.append(
            {
                "id": i,
                "x": round(nd["x"], 2),
                "y": round(nd["y"], 2),
                "status": status[i],
                "seen": len(nd["frames"]),
                "could": nd.get("could", 0),
                "frames": sorted(nd["frames"]),
                "tower": nd["tower"],
                "origin": nd["origin"],
                "icons": [icons[k]["name"] for k in nd["icons"]],
                "abyss": nd.get("abyss", ""),
                "why": removed_why.get(i, ""),
            }
        )
    out_paths = []
    for i, j, c, kind, shp in chosen:
        t = traces.get((min(i, j), max(i, j)))
        nf = could_both(i, j)
        seen_in = len(t["frames"]) if t else (score(i, j)[2] if kind == "straight" else 0)
        rec = {
            "a": keep[i],
            "b": keep[j],
            "kind": kind,
            "frames": nf,
            "seen_in": seen_in,
            "both_ends": bool(t and t["mutual"]),
            "abyss": kind == "abyss",
            "score": round(c, 3),
        }
        if t:  # why it is drawn (shown when the path is selected)
            rec["ends_in"] = len(t["mutual"])
            rec["confirm"], rec["deny"] = int(t["confirm"]), int(t["deny"])
            rec["dashes"] = int(t["dashes"])
        if kind == "traced" and len(shp) > 2:
            rec["line"] = [[round(float(x), 1), round(float(y), 1)] for x, y in shp]
        out_paths.append(rec)
    stats = {
        "nodes_kept": sum(s not in ("removed",) for s in status),
        "ghosts_removed": sum(1 for i, s in enumerate(status) if s == "removed" and "ghost" in removed_why.get(i, "")),
        "river_removed": sum(1 for v in removed_why.values() if v == "abyss river glow"),
        "unsupported_removed": sum(1 for v in removed_why.values() if v.startswith("found in 1 of 2")),
        "duplicates_joined": sum(1 for v in removed_why.values() if v.startswith("joined")),
        "nodes_from_icons": len(icon_nodes),
        "doubtful": status.count("doubtful"),
        "paths": len(out_paths),
        "paths_multi": sum(p["seen_in"] >= 2 for p in out_paths),
        "paths_traced": sum(p["kind"] == "traced" for p in out_paths),
        "abyss_chains": len(chains),
        "landmarks_removed": sum(lm["status"].startswith("removed") for lm in landmarks),
    }
    # the special-boss crest marks a Hall / City boss next to the building, otherwise a deadly
    # map boss (e.g. the red spiky trees)
    settle = [lm for lm in landmarks if lm["kind"] in ("City", "Hall") and not lm["status"].startswith("removed")]
    for ic in icons:
        if ic["name"] == "MapBossSpecial":
            near = [lm for lm in settle if math.hypot(lm["x"] - ic["bx"], lm["y"] - ic["by"]) < SETTLE_BADGE]
            ic["label"] = f"Deadly Map Boss ({near[0]['kind']})" if near else "Deadly Map Boss"
    # badges to show: on a kept map, or seen by most screenshots that show the spot
    on_map = {k for i, nd in enumerate(nodes) if status[i] != "removed" for k in nd["icons"]}
    out_icons = []
    for k, ic in enumerate(icons):
        if k in dup_badge:
            continue
        if k in on_map or (ic["name"] != "Unidentified" and ic["n"] * 2 >= ic["could"]):
            out_icons.append({key: (round(v, 2) if isinstance(v, float) else v) for key, v in ic.items()})
    stats["icons_shown"] = len(out_icons)
    stats["icons_dropped"] = len(atlas.icons) - len(out_icons)
    atlas.final = {"nodes": out_nodes, "paths": out_paths, "landmarks": landmarks, "icons": out_icons, "stats": stats}
    if log:
        log("final: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return atlas.final
