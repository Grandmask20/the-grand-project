"""Waiting screenshots as mini-atlases ("islands").

A crawl that pans too far leaves screenshots that fit nothing in the atlas yet. On their own each may share
too few maps with the atlas, but the waiting ones usually overlap each other: they are joined into islands
by their maps alone (no images, no terrain, no clean-up: cheap), and each island is then matched against the
atlas as one piece, with all its maps. A match is accepted by the same rules as one screenshot (enough maps
agree, enough of the overlapping maps agree) plus a terrain check of the island screenshot that overlaps
the atlas most - the only image read, and only when a match is found.

Placement is a pure shift (PLACEMENT = "shift"): an island screenshot's place in the atlas is its place in the
island plus the island's shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.spatial import cKDTree

from .atlas import Atlas
from .constants import (
    ISLAND_CANDIDATES,
    ISLAND_COVER_CELL,
    ISLAND_MIN,
    ISLAND_QUICK_TOL,
    ISLAND_TERRAIN_TRIES,
    MERGE_TOL,
    MIN_INLIERS,
    MIN_NCC,
    MIN_OVERLAP_RATIO,
    PARALLAX_MIN_INLIERS,
    PARALLAX_RATIO,
    PARALLAX_TOL,
)
from .frame import Frame
from .geometry import apply, persp, screen_to_atlas
from .register import Registration, _inside_rect, mutual_pairs, refine


@dataclass
class Island:
    atlas: Atlas  # the screenshots placed relative to the island's first one (maps only)
    frames: list = field(default_factory=list)  # Frame objects, in the order they joined


def build_islands(frames: list[Frame]) -> list[Island]:
    """join waiting screenshots that match each other by their maps; every screenshot ends in exactly one
    island (a lone one is an island of one)"""
    left = list(frames)
    out = []
    while left:
        isl = Island(Atlas())
        isl.atlas.add_frame(left[0], verify=False)
        isl.frames.append(left.pop(0))
        grew = True
        while grew and left:
            grew = False
            for fr in list(left):
                reg = isl.atlas.add_frame(fr, verify=False)
                if reg.ok:
                    isl.frames.append(fr)
                    left.remove(fr)
                    grew = True
        out.append(isl)
    return out


def _footprint_masks(isl: Island, T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """which of pts lie inside any island screenshot once the island is shifted by T"""
    inside = np.zeros(len(pts), bool)
    for f in isl.atlas.frames:
        M = np.array(f["M"], float)
        M[:, 2] += T
        inside |= _inside_rect(pts, M, f["w"], f["h"], isl.atlas.frame_R(f))
    return inside


def _cover(footprints) -> tuple[np.ndarray, np.ndarray]:
    """the area screenshots cover, drawn on a coarse grid: (grid, its origin)"""
    polys = []
    for M, w, h, R in footprints:
        H = screen_to_atlas(np.asarray(M, float), R)
        m = 30  # the same inset as the exact overlap test (_inside_rect)
        polys.append(persp(H, [[m, m], [w - m, m], [w - m, h - m], [m, h - m]]))
    allp = np.vstack(polys)
    o = allp.min(axis=0) - ISLAND_COVER_CELL
    size = np.ceil((allp.max(axis=0) - o) / ISLAND_COVER_CELL).astype(int) + 2
    grid = np.zeros((size[1], size[0]), np.uint8)
    for p in polys:
        cv2.fillConvexPoly(grid, np.round((p - o) / ISLAND_COVER_CELL).astype(np.int32), 1)
    return grid, o


def _inside(cover, pts: np.ndarray) -> np.ndarray:
    grid, o = cover
    g = np.floor((pts - o) / ISLAND_COVER_CELL).astype(int)
    ok = (g[..., 0] >= 0) & (g[..., 1] >= 0) & (g[..., 0] < grid.shape[1]) & (g[..., 1] < grid.shape[0])
    out = np.zeros(pts.shape[:-1], bool)
    out[ok] = grid[g[..., 1][ok], g[..., 0][ok]] > 0
    return out


def _pair_candidates(main: Atlas, isl: Island, src: np.ndarray, dst: np.ndarray, top: int):
    """shifts (dst - src for some pair) that pass the placement rules by a quick count: enough group maps land
    on atlas maps, and enough of the maps that overlap do (or the raised-ground second chance); best first.
    A group's few true agreements are outnumbered by chance ones in a dense atlas, so every candidate gets the
    overlap rule here, not just the best-voted few (groups are rare: this is a few array operations)"""
    d = (dst[None, :, :] - src[:, None, :]).reshape(-1, 2)
    d = np.unique(np.round(d / 4.0) * 4.0, axis=0)  # pairs proposing (almost) the same shift count once
    tree = cKDTree(dst)
    cover_main = _cover(main.footprints())
    cover_isl = _cover([(f["M"], f["w"], f["h"], isl.atlas.frame_R(f)) for f in isl.atlas.frames])
    keep = []
    for k in range(0, len(d), 1000):
        blk = d[k : k + 1000]
        q = src[None, :, :] + blk[:, None, :]  # (shifts, src, 2)
        dist = tree.query(q.reshape(-1, 2), distance_upper_bound=PARALLAX_TOL)[0].reshape(len(blk), len(src))
        exact = (dist <= ISLAND_QUICK_TOL).sum(axis=1)  # (the exact check that follows uses 5 px)
        loose = (dist <= PARALLAX_TOL).sum(axis=1)
        o_src = _inside(cover_main, q).sum(axis=1)
        o_dst = _inside(cover_isl, dst[None, :, :] - blk[:, None, :]).sum(axis=1)
        n = np.maximum(1, np.minimum(o_src, o_dst))
        ok = (exact >= MIN_INLIERS) & (
            (exact / n >= MIN_OVERLAP_RATIO) | ((exact >= PARALLAX_MIN_INLIERS) & (loose / n >= PARALLAX_RATIO))
        )
        keep += [(int(exact[i]), float(blk[i, 0]), float(blk[i, 1])) for i in np.nonzero(ok)[0]]
    keep.sort(key=lambda t: -t[0])
    return [(tx, ty) for _n, tx, ty in keep[:top]]


def match_island(main: Atlas, isl: Island) -> tuple[np.ndarray | None, str]:
    """the shift that puts the island into the atlas, or (None, why not)"""
    src, dst = isl.atlas.points(), main.points()
    if len(src) < MIN_INLIERS or len(dst) < MIN_INLIERS:
        return None, "too few maps"
    # candidates come from a quick count over every map pairing (see _pair_candidates); each is refined and
    # checked exactly, like one screenshot in Atlas.add_frame: enough maps agree, most of the overlapping ones
    # agree (or the raised-ground second chance)
    in_any = main.footprints()
    good, tried, seen = [], 0, set()
    cands = _pair_candidates(main, isl, src, dst, ISLAND_CANDIDATES)
    for tx, ty in cands:
        M, pairs, _rmse = refine(src, dst, (tx, ty))
        inl = len(pairs)
        tried = max(tried, inl)
        if inl < MIN_INLIERS:
            continue
        T_ = M[:, 2].copy()
        key = (round(T_[0] / 3), round(T_[1] / 3))
        if key in seen:  # several candidates refine to the same shift
            continue
        seen.add(key)
        moved = src + T_
        in_main = np.zeros(len(moved), bool)
        for FM, fw, fh, FR in in_any:
            in_main |= _inside_rect(moved, FM, fw, fh, FR)
        o_src, o_dst = int(in_main.sum()), int(_footprint_masks(isl, T_, dst).sum())
        n_over = max(1, min(o_src, o_dst))
        ratio = inl / n_over
        if ratio < MIN_OVERLAP_RATIO:
            # raised ground: maps on hills shift up to ~45 units between screenshots, so few agree within 5 px;
            # the same second chance as one screenshot (Atlas._parallax_ok): enough exact matches AND most maps
            # within PARALLAX_TOL
            loose = len(mutual_pairs(moved, dst, PARALLAX_TOL)) / n_over
            if inl < PARALLAX_MIN_INLIERS or loose < PARALLAX_RATIO:
                continue
            ratio = loose
        good.append((T_, inl, ratio))
    if not good:
        return None, (
            f"only {tried} maps agree (need {MIN_INLIERS})"
            if tried < MIN_INLIERS
            else f"no shift where {MIN_OVERLAP_RATIO:.0%} of the overlapping maps agree"
        )
    # terrain: the island screenshot sharing the most maps with the atlas must look like the atlas there; the
    # best few shifts get this check (the best-counted one can be a chance match with the true one next)
    good.sort(key=lambda g: -g[1])
    tree = cKDTree(dst)
    why = ""
    for T, inl, _ratio in good[:ISLAND_TERRAIN_TRIES]:
        best_f, best_M, best_n = None, None, -1
        for fr, f in zip(isl.frames, isl.atlas.frames, strict=True):
            Mf = np.array(f["M"], float)
            Mf[:, 2] += T
            pts = apply(Mf, fr.pts[fr.usable])
            n = int((tree.query(pts)[0] <= MERGE_TOL).sum()) if len(pts) else 0
            if n > best_n:
                best_f, best_M, best_n = fr, Mf, n
        reg = Registration(False, "", best_M, inl)
        main._verify(best_f, reg)
        if reg.ncc_pixels >= 15000 and reg.ncc >= MIN_NCC:
            return T, f"{inl} maps agree, terrain {reg.ncc:.2f}"
        why = f"terrain does not match (NCC {reg.ncc:.2f})"
    return None, why


def place_island(main: Atlas, isl: Island, T: np.ndarray, why: str) -> list[Frame]:
    """add every island screenshot at its island place + T; returns the frames added"""
    added = []
    for fr, f in zip(isl.frames, isl.atlas.frames, strict=True):
        M = np.array(f["M"], float)
        M[:, 2] += T
        reg = Registration(True, f"merged with its waiting group ({why})", M, 0)
        if not any(g["sha"] == fr.sha for g in main.frames):
            main.commit_frame(fr, reg)
            added.append(fr)
    return added


def merge_waiting(main: Atlas, waiting: list[Frame], log=None) -> list[Frame]:
    """try every island of 2+ waiting screenshots against the atlas; returns the screenshots added"""
    if len(waiting) < ISLAND_MIN or not main.frames:
        return []
    added = []
    for isl in build_islands(waiting):
        if len(isl.frames) < ISLAND_MIN:
            continue
        T, why = match_island(main, isl)
        if log:
            names = ", ".join(f.name[-8:] for f in isl.frames)
            log(f"waiting group of {len(isl.frames)} ({names}): " + (f"joined, {why}" if T is not None else why))
        if T is not None:
            added += place_island(main, isl, T, why)
    return added
