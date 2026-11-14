"""detect.paths (from atlas_detect.py)"""

from __future__ import annotations

import cv2
import numpy as np

from grand_project import core

from .cache import _per_image
from .constants import (
    CHAIN,
    DASH_AREA,
    DASH_SIZE,
    PATH_AHEAD,
    PATH_ARRIVE,
    PATH_ARRIVE_TOWER,
    PATH_BEND_MAX,
    PATH_BEND_SMOOTH,
    PATH_END_RESCUE,
    PATH_JUMP,
    PATH_LAT,
    PATH_LEAVE_ANGLE,
    PATH_LOOSE_DASHES,
    PATH_LOOSE_MEET,
    PATH_MAX_ANG,
    PATH_MAX_DEGREE,
    PATH_MAX_DETOUR,
    PATH_MAX_STEPS,
    PATH_MEET_COS,
    PATH_MEET_MANY,
    PATH_MIN_DASHES,
    PATH_REGULAR,
    PATH_SHARE,
    PATH_SINGLE_END,
    PATH_SINGLE_END_ON,
    PATH_SNAP,
    PATH_SPACING,
    PATH_START,
    PATH_STEP,
    SEEN_CELL,
    WALK_FILL_ON_DOTS,
    WALL_CELL,
)
from .walls import fortress_walls


@_per_image
def path_dashes(img: np.ndarray) -> np.ndarray:
    b, g, r = [img[..., i].astype(np.int16) for i in range(3)]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = [hsv[..., i].astype(np.int16) for i in range(3)]
    lift = cv2.morphologyEx(hsv[..., 2], cv2.MORPH_TOPHAT, np.ones((7, 7), np.uint8)).astype(np.int16)
    amber = (r > 145) & (g > 95) & (r - g > 32) & (g - b > 35) & (b < 145)
    dim = (H >= 8) & (H <= 30) & (S >= 110) & (V >= 55) & (lift >= 18)
    fog = (H >= 8) & (H <= 30) & (S >= 60) & (S < 110) & (V >= 110) & (lift >= 15)  # washed out by Delirium fog
    m = ((amber | dim | fog) & (core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH) == 0)).astype(np.uint8)
    _n, _l, st, cen = cv2.connectedComponentsWithStats(m, 8)
    ok = (st[1:, 4] >= DASH_AREA[0]) & (st[1:, 4] <= DASH_AREA[1]) & (st[1:, 2] <= DASH_SIZE) & (st[1:, 3] <= DASH_SIZE)
    return cen[1:][ok].astype(float)


def path_features(pts, dashes: np.ndarray) -> np.ndarray:
    """dashes in rings around a spot, and in how many of 12 directions dashes leave it"""
    F = []
    for x, y in pts:
        v = dashes - (x, y) if len(dashes) else np.zeros((0, 2))
        d = np.hypot(v[:, 0], v[:, 1])
        f = [float(((d >= a) & (d < b)).sum()) for a, b in ((0, 10), (10, 20), (20, 32), (32, 48))]
        sel = (d >= 12) & (d < 45)
        sect = (
            np.bincount(((np.arctan2(v[sel, 1], v[sel, 0]) + np.pi) / (2 * np.pi) * 12).astype(int) % 12, minlength=12)
            if sel.any()
            else np.zeros(12)
        )
        f += [float((sect > 0).sum()), float((sect >= 2).sum())]
        F.append(f)
    return np.asarray(F, np.float32).reshape(len(F), 6)


def _walks_raw(nodes: list[dict], dashes: np.ndarray, loose: list | None = None) -> list[dict]:
    """every walk from every map along the dashes until it reaches another map; walks that follow a
    regular dotted line but reach no map are added to `loose` (their end point and direction).
    Each dash's neighbours are looked up once; each step only tests the maps near it."""
    N = np.array([[n["x"], n["y"]] for n in nodes], float)
    rad = np.array([PATH_ARRIVE_TOWER if n.get("tower") else PATH_ARRIVE for n in nodes])
    if len(dashes) == 0 or len(N) < 2:
        return []
    from scipy.spatial import cKDTree

    tree = cKDTree(dashes)
    mtree = cKDTree(N)
    rmax = float(rad.max())
    nbr = [np.array(x, int) for x in tree.query_ball_point(dashes, PATH_JUMP)]
    nvec = [dashes[k] - dashes[i] for i, k in enumerate(nbr)]
    nlen = [np.hypot(v[:, 0], v[:, 1]) for v in nvec]
    cos_max = np.cos(np.radians(PATH_MAX_ANG))
    in_walk = np.zeros(len(dashes), bool)
    out = []
    for a, A in enumerate(N):
        for s in tree.query_ball_point(A, PATH_START[1]):
            p = dashes[s]
            r0 = float(np.hypot(*(p - A)))
            if r0 < PATH_START[0]:
                continue
            d = (p - A) / r0
            used, line, steps, length = [s], [A.copy(), p.copy()], [], r0
            in_walk[s] = True
            cur = s  # p is dashes[cur]
            w = 0.0  # bend per px, learned along the walk
            end = None
            for _ in range(PATH_MAX_STEPS):
                best = None
                K, V, Ls = nbr[cur], nvec[cur], nlen[cur]
                free = ~in_walk[K] & (Ls >= 2)
                for R, tol in ((PATH_STEP, 1.0), (PATH_JUMP, 0.7)):
                    m = free & (Ls <= R)
                    if not m.any():
                        continue
                    k_, v_, L_ = K[m], V[m], Ls[m]
                    ang = w * L_ / 2  # heading the curve predicts over each step
                    ca, sa = np.cos(ang), np.sin(ang)
                    ex, ey = d[0] * ca - d[1] * sa, d[0] * sa + d[1] * ca
                    fwd = v_[:, 0] * ex + v_[:, 1] * ey
                    lat = np.abs(ex * v_[:, 1] - ey * v_[:, 0])
                    ok = (fwd > 0) & (fwd >= L_ * cos_max) & (lat <= (PATH_LAT[0] + PATH_LAT[1] * L_) * tol)
                    if ok.any():
                        cost = np.where(ok, L_ + 3.0 * lat, np.inf)
                        j = int(np.argmin(cost))
                        best = (float(cost[j]), int(k_[j]), v_[j] / L_[j], float(L_[j]))
                        break
                q = dashes[best[1]] if best else p + d * PATH_STEP  # last stretch: towards a map just ahead
                # first map on the way: the segment p -> q passes a map's ring
                seg = q - p
                near = np.array(mtree.query_ball_point(p, float(np.hypot(*seg)) + rmax), int)
                near = near[near != a]
                if len(near):
                    Nn = N[near]
                    t = np.clip(((Nn - p) @ seg) / max(float(seg @ seg), 1e-9), 0, 1)
                    dist = np.hypot(*(p + t[:, None] * seg - Nn).T)
                    hit = np.nonzero(dist < rad[near])[0]
                    if len(hit):
                        b = int(near[hit[np.argmin(t[hit])]])
                        end = b
                        length += float(np.hypot(*(N[b] - p)))
                        break
                if best is None:
                    near = np.array(mtree.query_ball_point(p, PATH_SNAP), int)  # ran out just in front of a map
                    near = near[near != a]
                    if len(near):
                        dn = np.hypot(*(N[near] - p).T)
                        ahead = ((N[near] - p) @ d) > 0
                        cand = np.nonzero((dn <= PATH_SNAP) & ahead)[0]
                        if len(cand):
                            end = int(near[cand[np.argmin(dn[cand])]])
                            length += float(np.hypot(*(N[end] - p)))
                    break
                _, k, u, L = best
                turn = float(np.arctan2(d[0] * u[1] - d[1] * u[0], d @ u))  # heading change this step
                w = (1 - PATH_BEND_SMOOTH) * w + PATH_BEND_SMOOTH * float(
                    np.clip(2 * turn / max(L, 1.0), -PATH_BEND_MAX, PATH_BEND_MAX)
                )
                d = u.copy()
                p = dashes[k]
                cur = k
                used.append(k)
                in_walk[k] = True
                line.append(p.copy())
                steps.append(L)
                length += L
            in_walk[used] = False
            if end is None and loose is not None and len(used) >= PATH_LOOSE_DASHES:
                st = np.array(steps)
                if ((st >= PATH_SPACING[0]) & (st <= PATH_SPACING[1])).mean() >= PATH_REGULAR:
                    loose.append((p + d * 10.0, a, d.copy()))
            if end is None or len(used) < PATH_MIN_DASHES:
                continue
            straight = float(np.hypot(*(N[end] - A)))
            if straight < 25 or length > PATH_MAX_DETOUR * straight:
                continue
            st = np.array(steps) if steps else np.array([10.0])
            regular = float(((st >= PATH_SPACING[0]) & (st <= PATH_SPACING[1])).mean())
            if regular < PATH_REGULAR:
                continue
            out.append(
                {
                    "a": a,
                    "b": end,
                    "dashes": used,
                    "line": line + [N[end].copy()],
                    "score": len(used) / max(1.0, straight / 10.0) * regular / (length / straight),
                }
            )
    return out


def _cross(l1: np.ndarray, l2: np.ndarray) -> bool:
    """do two drawn lines cross (proper intersection of any segments)?"""
    if (l1.min(0) > l2.max(0)).any() or (l2.min(0) > l1.max(0)).any():
        return False
    p1, p2 = l1[:-1, None], l1[1:, None]
    q1, q2 = l2[None, :-1], l2[None, 1:]

    def side(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])

    return bool(((side(p1, p2, q1) * side(p1, p2, q2) < 0) & (side(q1, q2, p1) * side(q1, q2, p2) < 0)).any())


def maps_from_paths(
    nodes: list[dict], dashes: np.ndarray, img: np.ndarray, map_pts: np.ndarray, map_p: np.ndarray, rounds: int = 3
) -> list[dict]:
    """maps the map finder missed: where dotted lines from two different maps both run out, there is a
    map (paths never cross or fork - user). A line that runs into the HUD, the screen edge or black fog
    has not ended, it is only out of view: such ends do not count, and two lines must come in from
    clearly different directions. Our walks also stop where a few dashes go undetected, so the map
    finder must have seen a (weak) map candidate at the meeting point too. Repeated: a new map can open
    more lines."""
    valid = core._valid_mask(img)
    h, w = valid.shape

    def in_view(p, d):
        q = p + d * PATH_AHEAD
        x, y = int(round(q[0])), int(round(q[1]))
        return 0 <= x < w and 0 <= y < h and valid[y, x] > 0

    found: list[dict] = []
    for _ in range(rounds):
        loose = [(p, a, d) for p, a, d in (lambda L: (_walks(nodes + found, dashes, L), L)[1])([]) if in_view(p, d)]
        new: list[dict] = []
        for p, a, d in loose:
            mates = [
                q
                for q, b, e in loose
                if b != a and np.hypot(*(q - p)) <= PATH_LOOSE_MEET and float(d @ e) < PATH_MEET_COS
            ]
            if not mates and not PATH_SINGLE_END_ON:
                continue
            c = np.mean([p] + mates, 0) if mates else p + d * 10.0  # one line alone: the map is just past its end
            if any(np.hypot(c[0] - n["x"], c[1] - n["y"]) < 30 for n in nodes + found + new):
                continue
            dd = np.hypot(map_pts[:, 0] - c[0], map_pts[:, 1] - c[1]) if len(map_pts) else np.zeros(0)
            reach = PATH_END_RESCUE[1] if mates else PATH_SINGLE_END[1]
            # 3+ lines from different maps running out at one spot: a map, however unlit its base (user's
            # grey bases the map model rates ~0); the nearest candidate (any score) places it
            many = (
                len(
                    {
                        b
                        for q, b, e in loose
                        if b != a and np.hypot(*(q - p)) <= PATH_LOOSE_MEET and float(d @ e) < PATH_MEET_COS
                    }
                )
                >= PATH_MEET_MANY - 1
            )
            floor = 0.0 if many else PATH_END_RESCUE[0]
            ok = (dd <= reach) & (map_p >= floor) if len(dd) else dd.astype(bool)
            if not ok.any():
                if not many:
                    continue
                x, y = float(c[0]), float(c[1])
                if any(np.hypot(x - n["x"], y - n["y"]) < 30 for n in nodes + found + new):
                    continue
                new.append({"x": x, "y": y, "score": 0.0, "source": "path ends"})
                continue
            j = int(np.argmax(np.where(ok, map_p, -1)))
            x, y = float(map_pts[j][0]), float(map_pts[j][1])
            if any(np.hypot(x - n["x"], y - n["y"]) < 30 for n in nodes + found + new):
                continue  # several meeting points snapped to the same map: add it once
            new.append({"x": x, "y": y, "score": round(float(map_p[j]), 3), "source": "path ends"})
        if not new:
            break
        found += new
    return found


def _no_diamond_shortcuts(kept: list[dict], nodes: list[dict]) -> list[dict]:
    """the old diamond rule: a path a-b is a shortcut across a diamond when maps on BOTH sides of it are
    joined to both a and b by kept paths; the four sides are the real paths"""
    N = np.array([[n["x"], n["y"]] for n in nodes], float)
    adj: dict = {}
    for w in kept:
        adj.setdefault(w["a"], set()).add(w["b"])
        adj.setdefault(w["b"], set()).add(w["a"])
    out = []
    for w in kept:
        a, b = w["a"], w["b"]
        axis = N[b] - N[a]
        length = float(np.hypot(*axis))
        sides = set()
        for k in (adj.get(a, set()) & adj.get(b, set())) - {a, b}:
            cross = float(axis[0] * (N[k][1] - N[a][1]) - axis[1] * (N[k][0] - N[a][0]))
            if abs(cross) >= length * 16:
                sides.add(cross > 0)
        if len(sides) < 2:
            out.append(w)
    return out


def walk_paths(nodes: list[dict], dashes: np.ndarray) -> list[dict]:
    """paths between the maps (hidden ones too): {a, b (node indices), conf, status, dashes, line}.
    Walks along the dashes, then keeps the best walks first; a walk that crosses a kept path, reuses its
    dashes, joins two maps already joined, leaves a map in the same direction as a kept path, or gives a
    map more than 5 paths is dropped (paths never cross, fork or share a route - user); then the diamond
    rule."""
    walks = sorted(_walks(nodes, dashes), key=lambda w: -w["score"])
    kept, owner, pairs = [], {}, set()
    degree: dict = {}
    leave: dict = {}  # map -> directions its kept paths leave in

    def leaving(line, at_start):
        L = np.asarray(line, float)
        L = L if at_start else L[::-1]
        far = next((q for q in L[1:] if np.hypot(*(q - L[0])) >= 25), L[-1])
        v = far - L[0]
        return v / max(1e-6, float(np.hypot(*v)))

    cos_leave = np.cos(np.radians(PATH_LEAVE_ANGLE))
    for w in walks:
        key = (min(w["a"], w["b"]), max(w["a"], w["b"]))
        if key in pairs:
            continue
        if degree.get(w["a"], 0) >= PATH_MAX_DEGREE or degree.get(w["b"], 0) >= PATH_MAX_DEGREE:
            continue
        da, db = leaving(w["line"], True), leaving(w["line"], False)
        if any(float(da @ u) > cos_leave for u in leave.get(w["a"], [])) or any(
            float(db @ u) > cos_leave for u in leave.get(w["b"], [])
        ):
            continue
        if sum(1 for k in w["dashes"] if k in owner) > PATH_SHARE:
            continue
        L = np.array(w["line"], float)
        inner = L[2:-2] if len(L) > 5 else L  # ends meet at maps: only the middle may not cross
        if any(_cross(inner, np.array(o["line"], float)) for o in kept):
            continue
        kept.append(w)
        pairs.add(key)
        degree[w["a"]] = degree.get(w["a"], 0) + 1
        degree[w["b"]] = degree.get(w["b"], 0) + 1
        leave.setdefault(w["a"], []).append(da)
        leave.setdefault(w["b"], []).append(db)
        for k in w["dashes"]:
            owner[k] = len(kept)
    kept = _no_diamond_shortcuts(kept, nodes)
    return [
        {
            "a": int(min(w["a"], w["b"])),
            "b": int(max(w["a"], w["b"])),
            "conf": round(min(1.0, len(w["dashes"]) / 10), 3),
            "status": "traced",
            "dashes": len(w["dashes"]),
            "line": [
                [round(float(x), 1), round(float(y), 1)] for x, y in (w["line"] if w["a"] < w["b"] else w["line"][::-1])
            ],
        }
        for w in kept
    ]


@_per_image
def amber_dashes(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """strict amber filter -> dash strokes: centres and unit directions"""
    b, g, r = [img[..., i].astype(np.int16) for i in range(3)]
    m = ((r > 145) & (g > 95) & (r - g > 32) & (g - b > 35) & (b < 145)).astype(np.uint8)
    m[core.hud_mask(img.shape[1], img.shape[0], -core.HUD_DEPTH) > 0] = 0
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    C, U = [], []
    for k in range(1, n):
        if not (CHAIN["area"][0] <= st[k, 4] <= CHAIN["area"][1]):
            continue
        ys, xs = np.nonzero(lab[st[k, 1] : st[k, 1] + st[k, 3], st[k, 0] : st[k, 0] + st[k, 2]] == k)
        pts = np.stack([xs, ys], 1).astype(float)
        if len(pts) < 3:
            continue
        ev, evec = np.linalg.eigh(np.cov((pts - pts.mean(0)).T) + np.eye(2) * 0.08)
        if np.sqrt(ev[1] / ev[0]) < CHAIN["elong"] or not (CHAIN["len"][0] <= 4 * np.sqrt(ev[1]) <= CHAIN["len"][1]):
            continue
        C.append(cen[k])
        U.append(evec[:, 1])
    return np.array(C, float).reshape(-1, 2), np.array(U, float).reshape(-1, 2)


def _dash_links(C: np.ndarray, U: np.ndarray) -> set:
    """each dash links to its best neighbour ahead and behind along its own direction; mutual links kept"""
    from scipy.spatial import cKDTree

    if len(C) < 2:
        return set()
    T = cKDTree(C)
    ca = np.cos(np.radians(CHAIN["ang"]))
    best = {}
    for i in range(len(C)):
        for side in (1, -1):
            u = U[i] * side
            cand = []
            for j in T.query_ball_point(C[i], CHAIN["gap"][1]):
                v = C[j] - C[i]
                d = float(np.hypot(*v))
                if j == i or d < CHAIN["gap"][0]:
                    continue
                along = float(v @ u)
                lat = abs(u[0] * v[1] - u[1] * v[0])
                if along <= 0 or along / d < ca or lat > CHAIN["side"] + 0.12 * d or abs(float(U[j] @ U[i])) < ca:
                    continue
                cand.append((d + 3 * lat, j))
            if cand:
                best[(i, side)] = min(cand)[1]
    return {(min(i, j), max(i, j)) for (i, _s), j in best.items() if i in (best.get((j, 1)), best.get((j, -1)))}


def _chain_end(pts: np.ndarray, first: bool) -> tuple[np.ndarray, np.ndarray]:
    e, inn = (pts[0], pts[min(3, len(pts) - 1)]) if first else (pts[-1], pts[max(-4, -len(pts))])
    o = e - inn
    return e, o / max(1e-6, float(np.hypot(*o)))


def dash_chains(C: np.ndarray, U: np.ndarray) -> list[list[int]]:
    """linked dashes as chains; chain ends that line up across a short gap are joined, closest pair first
    (a heap of candidate end pairs, refreshed only for the chain that just changed)"""
    import heapq

    from scipy.spatial import cKDTree

    adj: dict = {}
    for i, j in _dash_links(C, U):
        adj.setdefault(i, []).append(j)
        adj.setdefault(j, []).append(i)
    seen: set = set()
    chs: list[list[int]] = []
    starts = [k for k in adj if len(adj[k]) != 2] + list(adj)  # open chains first, then closed loops
    for s0 in starts:
        if s0 in seen:
            continue
        ch, prev, cur = [s0], None, s0
        seen.add(s0)
        while True:
            nx = [k for k in adj[cur] if k != prev and k not in seen]
            if not nx:
                break
            prev, cur = cur, nx[0]
            ch.append(cur)
            seen.add(cur)
        chs.append(ch)
    ca = np.cos(np.radians(CHAIN["stitch_ang"]))
    alive = {cid: c for cid, c in enumerate(chs)}
    order = {cid: cid for cid in alive}  # position in the list (for the final order)
    ends: dict = {}  # (cid, first) -> (dash index, outward dir)
    for cid, c in alive.items():
        if len(c) >= 2:
            for f in (True, False):
                ends[(cid, f)] = (c[0] if f else c[-1], _chain_end(C[c], f)[1])
    tree = cKDTree(C) if len(C) else None
    end_at: dict = {}  # dash index -> end key (an end sits on a dash)
    for k, (di, _o) in ends.items():
        end_at.setdefault(di, set()).add(k)
    heap: list = []

    def push_for(k):
        di, o1 = ends[k]
        for dj in tree.query_ball_point(C[di], CHAIN["stitch"]):
            for k2 in end_at.get(dj, ()):
                if k2 == k or k2[0] == k[0] or k2 not in ends:
                    continue
                v = C[dj] - C[di]
                d = float(np.hypot(*v))
                o2 = ends[k2][1]
                if d < 1 or float(v @ o1) / d < ca or float(-v @ o2) / d < ca:
                    continue
                heapq.heappush(heap, (d, min(order[k[0]], order[k2[0]]), k, k2))

    for k in list(ends):
        push_for(k)
    nxt = len(chs)
    while heap:
        _d, _o, k1, k2 = heapq.heappop(heap)
        if k1 not in ends or k2 not in ends:
            continue  # one of the ends was used / changed since
        (i, fi), (j, fj) = k1, k2
        a = alive.pop(i)
        b = alive.pop(j)
        merged = (a[::-1] if fi else a) + (b if fj else b[::-1])
        for k in ((i, True), (i, False), (j, True), (j, False)):
            if k in ends:
                end_at[ends[k][0]].discard(k)
                del ends[k]
        cid = nxt
        nxt += 1
        alive[cid] = merged
        order[cid] = min(order[i], order[j])
        for f in (True, False):
            k = (cid, f)
            ends[k] = (merged[0] if f else merged[-1], _chain_end(C[merged], f)[1])
            end_at.setdefault(ends[k][0], set()).add(k)
        for f in (True, False):
            push_for((cid, f))
    return [alive[c] for c in sorted(alive, key=lambda c: order[c])]


def chain_paths(nodes: list[dict], C: np.ndarray, U: np.ndarray) -> list[dict]:
    """dash chains cut where they pass through a map; each piece between two maps is a path"""
    N = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
    if not len(N) or not len(C):
        return []
    cm = np.cos(np.radians(CHAIN["map_ang"]))

    def attach(e, o):
        v = N - e
        d = np.hypot(*v.T)
        ok = np.nonzero((d <= 12) | ((d <= CHAIN["map_r"]) & ((v @ o) / np.maximum(d, 1e-6) >= cm)))[0]
        return int(ok[np.argmin(d[ok])]) if len(ok) else None

    best: dict = {}
    for ch in dash_chains(C, U):
        pts = C[ch]
        pieces, cur, start = [], [0], None
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            ab = b - a
            t = np.clip(((N - a) @ ab) / max(float(ab @ ab), 1e-9), 0, 1)
            d = np.hypot(*(a + t[:, None] * ab - N).T)
            m = int(np.argmin(d))
            if d[m] <= CHAIN["through"]:
                pieces.append((start, cur, m))
                start, cur = m, [k + 1]
            else:
                cur.append(k + 1)
        pieces.append((start, cur, None))
        for sa, idx, sb in pieces:
            q = pts[idx]
            if len(idx) < CHAIN["min_dashes"] and (sa is None or sb is None):
                continue
            if sa is None and len(q) >= 2:
                sa = attach(*_chain_end(q, True))
            if sb is None and len(q) >= 2:
                sb = attach(*_chain_end(q, False))
            if sa is None or sb is None or sa == sb:
                continue
            line = [N[sa].tolist()] + q.tolist() + [N[sb].tolist()]
            key = (min(sa, sb), max(sa, sb))
            if sa > sb:
                line = line[::-1]
            if key not in best or len(idx) > best[key]["dashes"]:
                best[key] = {
                    "a": key[0],
                    "b": key[1],
                    "conf": round(min(1.0, len(idx) / 10), 3),
                    "status": "chain",
                    "dashes": len(idx),
                    "line": [[round(float(x), 1), round(float(y), 1)] for x, y in line],
                }
    return list(best.values())


def _on_dots(line, tree) -> float:
    L = np.asarray(line, float)[1:-1]
    if len(L) < 2:
        return 0.0
    P = np.concatenate(
        [
            a + (b - a) * np.linspace(0, 1, max(1, int(np.hypot(*(b - a)) // 4)), endpoint=False)[:, None]
            for a, b in zip(L[:-1], L[1:], strict=False)
        ]
    )
    return float((tree.query(P)[0] <= 8).mean())


def trace_paths(
    nodes: list[dict], dashes: np.ndarray, img: np.ndarray | None = None, amber: tuple | None = None
) -> list[dict]:
    """paths between the maps: amber dash chains first, then walk paths for pairs they missed that run on
    the dots and cross nothing (no map gets more than PATH_MAX_DEGREE). `amber` = amber_dashes(img), if known."""
    if img is None and amber is None:
        return walk_paths(nodes, dashes)
    from scipy.spatial import cKDTree

    C, U = amber if amber is not None else amber_dashes(img)
    out = chain_paths(nodes, C, U)
    if not len(C):
        return out + walk_paths(nodes, dashes)
    tree = cKDTree(np.vstack([C, dashes]) if len(dashes) else C)  # dim / fog dashes count as dots here
    pairs = {(e["a"], e["b"]) for e in out}
    deg: dict = {}
    for e in out:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    for w in walk_paths(nodes, dashes):
        k = (w["a"], w["b"])
        if k in pairs or deg.get(k[0], 0) >= PATH_MAX_DEGREE or deg.get(k[1], 0) >= PATH_MAX_DEGREE:
            continue
        if _on_dots(w["line"], tree) < WALK_FILL_ON_DOTS:
            continue
        L = np.array(w["line"], float)
        if any(_cross(L[2:-2] if len(L) > 5 else L, np.array(o["line"], float)) for o in out):
            continue
        out.append(w)
        pairs.add(k)
        deg[k[0]] = deg.get(k[0], 0) + 1
        deg[k[1]] = deg.get(k[1], 0) + 1
    return out


def dash_record(img: np.ndarray) -> dict:
    """what the atlas-wide path check needs from a screenshot, saved with its detection so the check never
    re-reads or re-traces the image: every path dash (amber strokes + dim / fog dashes, screen px) and a
    coarse grid of where the atlas is clearly visible (not dark fog, not HUD) - there an empty stretch along
    a path really means "no path"; elsewhere it means nothing (user)"""
    dim = path_dashes(img)
    C, _U = amber_dashes(img)
    pts = np.vstack([np.asarray(C, float).reshape(-1, 2), np.asarray(dim, float).reshape(-1, 2)])
    h, w = img.shape[:2]
    ok = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) >= 30) & (core._valid_mask(img) > 0)
    gh, gw = (h + SEEN_CELL - 1) // SEEN_CELL, (w + SEEN_CELL - 1) // SEEN_CELL
    pad = np.zeros((gh * SEEN_CELL, gw * SEEN_CELL), bool)
    pad[:h, :w] = ok
    grid = pad.reshape(gh, SEEN_CELL, gw, SEEN_CELL).mean(axis=(1, 3)) >= 0.6
    wall = fortress_walls(img)
    wh, ww = (h + WALL_CELL - 1) // WALL_CELL, (w + WALL_CELL - 1) // WALL_CELL
    wp = np.zeros((wh * WALL_CELL, ww * WALL_CELL), np.float32)
    wp[:h, :w] = wall
    wg = wp.reshape(wh, WALL_CELL, ww, WALL_CELL).mean(axis=(1, 3)) >= 0.5
    return {
        "dash_pts": np.round(pts).astype(int).tolist(),
        "amber_pts": np.round(np.asarray(C, float).reshape(-1, 2)).astype(int).tolist(),
        "seen_grid": ["".join("1" if v else "0" for v in row) for row in grid],
        "wall_grid": ["".join("1" if v else "0" for v in row) for row in wg],
    }


def screen_paths(img_dashes: tuple, pts: np.ndarray, ok: np.ndarray, tower: np.ndarray | None = None) -> dict:
    """for the builder's atlas-wide check: paths between given map positions (screen px) of one screenshot,
    using only the maps inside it (ok). img_dashes = (path_dashes(img), amber_dashes(img)).
    -> {(i, j): {"dashes", "from", "line", "detour"}}, i < j indices into pts (the atlas_trace format)"""
    dashes, amber = img_dashes
    vis = np.nonzero(ok)[0]
    nodes = [
        {"x": float(pts[i][0]), "y": float(pts[i][1]), "tower": bool(tower[i]) if tower is not None else False}
        for i in vis
    ]
    out = {}
    for e in trace_paths(nodes, dashes, amber=amber):
        i, j = int(vis[e["a"]]), int(vis[e["b"]])
        L = np.asarray(e["line"], float)
        straight = max(1.0, float(np.hypot(*(L[-1] - L[0]))))
        length = float(np.hypot(*np.diff(L, axis=0).T).sum())
        out[(min(i, j), max(i, j))] = {
            "dashes": int(e["dashes"]),
            "line": (L if i < j else L[::-1]).tolist(),
            "detour": length / straight,
            "from": {i, j} if e.get("status") == "chain" else {i},
        }
    return out


_WALK_MEMO: dict = {}


def _walks(nodes: list[dict], dashes: np.ndarray, loose: list | None = None) -> list[dict]:
    """_walks_raw, remembered for the last maps + dashes: tracing repeats the dead-end search's last round"""
    key = (
        len(dashes),
        float(dashes.sum()) if len(dashes) else 0.0,
        tuple((round(n["x"], 2), round(n["y"], 2), bool(n.get("tower"))) for n in nodes),
    )
    if _WALK_MEMO.get("key") != key:
        lo: list = []
        _WALK_MEMO.clear()
        _WALK_MEMO.update(key=key, out=_walks_raw(nodes, dashes, lo), loose=lo)
    if loose is not None:
        loose.extend(_WALK_MEMO["loose"])
    return _WALK_MEMO["out"]
