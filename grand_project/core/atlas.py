"""core.atlas (from atlas_builder_core.py)"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import cv2
import numpy as np

from grand_project import fileio as atlas_io

from .constants import (
    DROP_MIN_INLIERS,
    ICON_MERGE,
    LANDMARK_MERGE,
    MERGE_TOL,
    MIN_INLIERS,
    MIN_NCC,
    MIN_OVERLAP_RATIO,
    PARALLAX_MIN_INLIERS,
    PARALLAX_RATIO,
    PARALLAX_TOL,
    TERRAIN_MIN_AGREE,
    TERRAIN_MIN_NCC,
    TERRAIN_SCALE,
)
from .frame import Frame, row_bases
from .geometry import apply, persp, rectifier, screen_to_atlas
from .register import Registration, _horizon_of, _inside_rect, mutual_pairs, refine, register
from .terrain import _valid_mask, terrain_ncc


# ------------------------------------------------------------------ terrain verification
def _find_screenshot(p: str, atlas_dir: Path) -> str:
    """a screenshot path saved in an atlas, wherever the atlas now is: relative paths are relative to the
    atlas file; an absolute path that no longer exists (atlas folder moved, or copied to another computer)
    falls back to the same file name next to the atlas"""
    q = Path(p)
    if not q.is_absolute():
        return str((atlas_dir / q).resolve())
    if not q.exists() and (atlas_dir / q.name).exists():
        return str(atlas_dir / q.name)
    return p


# ------------------------------------------------------------------ the atlas
class Atlas:
    def __init__(self):
        self.nodes: list[dict] = []  # {x,y,n,frames,tower}
        self.edges: dict[tuple[int, int], dict] = {}
        self.landmarks: list[dict] = []
        self.bookmarks: list[dict] = []  # {name,category,note,x,y} set in the viewer
        self.icons: list[dict] = []  # every badge, merged across screenshots
        self.final: dict | None = None  # atlas-wide clean-up result (atlas_finalize)
        self.city_types: list[dict] = []  # {x,y,type} cities whose type was set by hand
        self.city_auto: list[dict] = []  # {x,y,d:[..]} cached look-alike distances per city type
        self.landmark_edits: list[dict] = []  # {x,y,kind[,on]} set by hand in the viewer; kind "" = deleted
        self.biome_edits: list[
            dict
        ] = []  # {"biome": "Vaal city"... or "" (none), "maps": [[x, y], ...]} lassoed by hand
        self.locks: list[dict] = []  # {x,y,n} hand badges = locked Breach strongholds
        self.lock_scanned: list[str] = []  # screenshots already searched for the hand badge
        self.frames: list[dict] = []  # {name,path,sha,w,h,M,stats}
        self._images: dict[str, np.ndarray] = {}

    # -------- image access
    IMAGE_CACHE = 90  # decoded screenshots kept in memory (~6 MB each; a terrain
    # check of one screenshot reads ~60 neighbours)

    _image_lock = threading.Lock()  # the viewer reads images while a worker places

    def image(self, path: str) -> np.ndarray:
        with Atlas._image_lock:
            if path in self._images:
                img = self._images.pop(path)
                self._images[path] = img  # most recently used last
                return img
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        with Atlas._image_lock:
            self._images[path] = img
            while len(self._images) > self.IMAGE_CACHE:
                self._images.pop(next(iter(self._images)))
        return img

    def points(self) -> np.ndarray:
        return np.array([[n["x"], n["y"]] for n in self.nodes], float).reshape(-1, 2)

    @staticmethod
    def frame_R(f: dict) -> np.ndarray:
        return rectifier(f["w"], f["h"], f.get("horizon"))

    def central_views(self, x: float, y: float, n: int = 3, limit: float = 0.42):
        """the n screenshots showing atlas point (x, y) closest to their middle, as
        (offset from the middle 0..0.5, frame, screen point); only those with offset < limit"""
        out = []
        for f in self.frames:
            Hi = np.linalg.inv(screen_to_atlas(np.array(f["M"], float), self.frame_R(f)))
            p = persp(Hi, [[x, y]])[0]
            c = max(abs(p[0] / f["w"] - 0.5), abs(p[1] / f["h"] - 0.5))
            if c < limit:
                out.append((c, f, p))
        return sorted(out, key=lambda t: t[0])[:n]

    def footprints(self):
        return [(np.array(f["M"], float), f["w"], f["h"], self.frame_R(f)) for f in self.frames]

    # -------- adding frames
    def add_frame(
        self,
        frame: Frame,
        verify: bool = True,
        hints: list[str] | None = None,
        seeds: list | None = None,
        commit: bool = True,
    ) -> Registration:
        """Place by the map layout; when too few maps are in the overlap (fog at the atlas edge,
        big pans), fall back to terrain features against the screenshots named in `hints`.
        commit=False only works out the placement (reg.ok, reg.M); commit it with commit_frame."""
        if any(f["sha"] == frame.sha for f in self.frames):
            return Registration(False, "this screenshot is already in the atlas")
        if not self.frames:
            reg0 = Registration(True, "first frame", np.array([[1, 0, 0], [0, 1, 0]], float))
            if commit:
                self._ingest(frame, reg0.M, reg0)
            return reg0
        reg, tried = register(frame, self.points(), self.footprints())
        reg.candidates = [(r.inliers, round(r.rmse, 2), round(r.ratio, 2)) for r in tried[:4]]
        why = None
        if reg.M is None:
            why = "no match"
        elif reg.inliers < MIN_INLIERS:
            why = f"only {reg.inliers} nodes agree (need {MIN_INLIERS})"
        elif reg.ratio < MIN_OVERLAP_RATIO and not self._parallax_ok(frame, reg):
            why = f"only {reg.ratio:.0%} of overlapping nodes agree (need {MIN_OVERLAP_RATIO:.0%})"
        elif verify:
            self._verify(frame, reg)
            if reg.ncc_pixels < 15000:
                why = "overlap too small to verify with terrain"
            elif reg.ncc < MIN_NCC:
                why = f"terrain does not match (NCC {reg.ncc:.2f} < {MIN_NCC})"
        if why is not None:
            alt = None
            for seed in seeds or []:  # (shift, label[, where the terrain lines up])
                shift, label = seed[0], seed[1]
                at = np.asarray(seed[2], float) if len(seed) > 2 else None
                alt = self._check_shift(frame, np.asarray(shift, float), label, at) if verify else None
                if alt is not None:
                    break
            if alt is None and verify and hints:
                alt = self._terrain_register(frame, hints)
            if alt is None:
                reg.reason = why
                return reg
            reg = alt
        reg.ok, reg.reason = True, (reg.reason or "merged")
        if commit:
            self._ingest(frame, reg.M, reg)
        return reg

    def place_near(self, frame: Frame, x: float, y: float, near: float = 900.0, strict: bool = False) -> Registration:
        """Line up a screenshot dropped by hand with its centre near (x, y) in atlas coordinates:
        only placements within `near` of that spot count (maps first, then terrain).  Does not
        commit; reg.ok False when nothing near there fits.  strict=True keeps the normal evidence
        thresholds (the spot is only a search hint, e.g. what the window shows); otherwise the
        spot counts as evidence (a hand drop) and fewer agreeing maps are accepted."""
        if any(f["sha"] == frame.sha for f in self.frames):
            return Registration(False, "this screenshot is already in the atlas")
        seed = np.array([x, y], float)
        if not self.frames:
            return Registration(True, "first frame", np.array([[1, 0, 0], [0, 1, 0]], float))
        best = None
        _, tried = register(frame, self.points(), self.footprints())
        # also refine straight from the dropped position (the vote may not list a peak there)
        src = frame.pts[frame.usable]
        if len(src) and len(self.nodes):
            M, pairs, rmse = refine(src, self.points(), (x, y))
            moved = apply(M, src)
            inside = np.zeros(len(src), bool)
            for FM, fw, fh, FR in self.footprints():
                inside |= _inside_rect(moved, FM, fw, fh, FR)
            n_in = int(inside.sum())
            tried = list(tried) + [Registration(False, "", M, len(pairs), rmse, n_in, n_in, len(pairs) / max(1, n_in))]
        for r in sorted(tried, key=lambda r: (-r.inliers, r.rmse)):
            if r.M is None or np.hypot(*(r.M[:, 2] - seed)) > near:
                continue
            if r.inliers < (MIN_INLIERS if strict else DROP_MIN_INLIERS) or r.ratio < MIN_OVERLAP_RATIO:
                continue
            self._verify(frame, r)
            # the drop point is evidence too: fewer agreeing maps are enough when the terrain
            # check is the stricter one used for terrain-only placements
            need = MIN_NCC if (strict or r.inliers >= MIN_INLIERS or r.ratio >= 0.5) else TERRAIN_MIN_NCC
            if r.ncc_pixels >= 15000 and r.ncc >= need:
                best = r
                break
        if best is None:  # terrain against the screenshots around the spot
            centres = []
            for f in self.frames:
                H = screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
                c = persp(H, [[f["w"] / 2, f["h"] / 2]])[0]
                centres.append((float(np.hypot(*(c - seed))), f["name"]))
            hints = [n for d, n in sorted(centres)[:10] if d < near + 2500]
            alt = self._terrain_register(frame, hints) if hints else None
            if alt is not None and np.hypot(*(alt.M[:, 2] - seed)) <= near:
                best = alt
        if best is None:
            return Registration(
                False,
                f"nothing within {near:.0f} units of where it was dropped lines up",
                np.array([[1, 0, x], [0, 1, y]], float),
            )
        best.ok = True
        best.reason = best.reason or "placed near the drop point"
        return best

    def _parallax_ok(self, frame: Frame, reg: Registration) -> bool:
        """Mountainous ground: raised maps shift up to ~45 units between screenshots, so few land
        within the 5 px the agreement count uses.  Second chance: enough exact matches AND most
        maps within PARALLAX_TOL (wrong spots stay under 20% there; the terrain check follows)."""
        if reg.M is None or reg.inliers < PARALLAX_MIN_INLIERS:
            return False
        src = frame.pts[frame.usable]
        moved = apply(reg.M, src)
        P = self.points()
        n = max(1, min(reg.overlap_src, reg.overlap_dst))
        loose = len(mutual_pairs(moved, P, PARALLAX_TOL)) / n
        if loose >= PARALLAX_RATIO:
            reg.reason = f"merged (raised ground: {loose:.0%} of maps within {PARALLAX_TOL:.0f} px)"
            return True
        return False

    def commit_frame(self, frame: Frame, reg: Registration) -> None:
        """add a frame placed with add_frame(..., commit=False)"""
        if any(f["sha"] == frame.sha for f in self.frames):
            return
        self._ingest(frame, reg.M, reg)

    def _ingest(self, frame: Frame, M: np.ndarray, reg: Registration) -> None:
        moved = apply(M, frame.pts)
        atlas_pts = self.points()
        mapping: dict[int, int] = {}
        # greedy one-to-one node merge, closest pairs first
        if len(atlas_pts):
            d = np.linalg.norm(moved[:, None, :] - atlas_pts[None, :, :], axis=2)
            order = np.dstack(np.unravel_index(np.argsort(d, axis=None), d.shape))[0]
            used_a = set()
            for i, j in order:
                if d[i, j] > MERGE_TOL:
                    break
                if int(i) in mapping or int(j) in used_a:
                    continue
                mapping[int(i)], _ = int(j), used_a.add(int(j))
        new_nodes = 0
        on_hud = getattr(frame, "on_hud", np.zeros(len(moved), bool))
        hud_skipped = 0
        for i, p in enumerate(moved):
            if on_hud[i] and i not in mapping:
                hud_skipped += 1
                continue  # a "node" on the game UI: never enters the atlas
            n = frame.nodes[i]
            if i in mapping:
                a = self.nodes[mapping[i]]
                a["x"] = (a["x"] * a["n"] + p[0]) / (a["n"] + 1)
                a["y"] = (a["y"] * a["n"] + p[1]) / (a["n"] + 1)
                a["n"] += 1
                a["frames"].append(frame.name)
                a["tower"] = a["tower"] or bool(n["tower"])
                a["icon"] = a.get("icon") or n.get("icon", "")
                a["hidden"] = a["hidden"] and bool(n["hidden"] or n["unverified"])
                if n["hidden"] or n["unverified"]:
                    a.setdefault("guessed_in", []).append(frame.name)  # only a guess there (no map base seen)
                a.setdefault("sources", []).append(str(n.get("source", "")).split("#")[0])
            else:
                mapping[i] = len(self.nodes)
                self.nodes.append(
                    {
                        "x": float(p[0]),
                        "y": float(p[1]),
                        "n": 1,
                        "frames": [frame.name],
                        "tower": bool(n["tower"]),
                        "icon": n.get("icon", ""),
                        "hidden": bool(n["hidden"] or n["unverified"]),
                        "guessed_in": [frame.name] if (n["hidden"] or n["unverified"]) else [],
                        "sources": [str(n.get("source", "")).split("#")[0]],
                    }
                )
                new_nodes += 1
        mapped_ids = set(mapping.values())
        seen_now = set()
        for a, b, _conf, status in frame.edges:
            ia, ib = mapping.get(a), mapping.get(b)
            if ia is None or ib is None or ia == ib:
                continue
            key = (min(ia, ib), max(ia, ib))
            seen_now.add(key)
            e = self.edges.setdefault(key, {"seen": 0, "could": 0, "confirmed": False})
            e["seen"] += 1
            e["confirmed"] = e["confirmed"] or status == "confirmed"
        # an edge "could" have been seen by this frame when both of its ends were visible in it
        for key, e in self.edges.items():
            if key[0] in mapped_ids and key[1] in mapped_ids:
                e["could"] += 1
        # landmarks: merge same kind nearby, otherwise add
        for lm in frame.landmarks:
            p = apply(M, persp(frame.R, [[lm["x"], lm["y"]]]))[0]
            for ex in self.landmarks:
                if ex["kind"] == lm["kind"] and math.hypot(ex["x"] - p[0], ex["y"] - p[1]) < LANDMARK_MERGE:
                    ex["x"] = (ex["x"] * ex["n"] + p[0]) / (ex["n"] + 1)
                    ex["y"] = (ex["y"] * ex["n"] + p[1]) / (ex["n"] + 1)
                    ex["n"] += 1
                    ex["conf"] = max(ex["conf"], lm["conf"])
                    break
            else:
                self.landmarks.append(
                    {
                        "kind": lm["kind"],
                        "x": float(p[0]),
                        "y": float(p[1]),
                        "n": 1,
                        "conf": lm["conf"],
                        "source": lm["source"],
                    }
                )
        self._merge_icons(frame, M)
        reg.reason = reg.reason or "merged"
        self.frames.append(
            {
                "name": frame.name,
                "path": frame.path,
                "sha": frame.sha,
                "w": frame.w,
                "h": frame.h,
                "M": M.tolist(),
                "horizon": _horizon_of(frame),
                "stats": {
                    "inliers": reg.inliers,
                    "rmse": round(reg.rmse, 2),
                    "ncc": round(reg.ncc, 3),
                    "ratio": round(reg.ratio, 2),
                    "reference": reg.ref_frame,
                    "reason": reg.reason,
                },
                "new_nodes": new_nodes,
                "matched_nodes": len(frame.pts) - new_nodes - hud_skipped,
                "hud_nodes_dropped": hud_skipped,
            }
        )

    def _verify(self, frame: Frame, reg: Registration) -> None:
        """terrain NCC against the placed screenshots that overlap the new one most"""
        img_new = self.image(frame.path)
        best_ncc, best_n, best_ref = -1.0, 0, ""
        H_new = screen_to_atlas(reg.M, frame.R)
        c_new = persp(H_new, [[frame.w / 2, frame.h / 2]])[0]
        for f in self.frames:
            H_ref = screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
            c_ref = persp(H_ref, [[f["w"] / 2, f["h"] / 2]])[0]
            if np.hypot(*(c_ref - c_new)) > 1.6 * max(f["w"], frame.w):
                continue  # too far apart to overlap: skip the pixel check
            ncc, n = terrain_ncc(self.image(f["path"]), img_new, np.linalg.inv(H_ref) @ H_new)
            if n >= 15000 and ncc > best_ncc:
                best_ncc, best_n, best_ref = ncc, n, f["name"]
        reg.ncc, reg.ncc_pixels, reg.ref_frame = max(best_ncc, 0.0), best_n, best_ref

    # -------- terrain fallback
    _feat_cache: dict = {}

    def _features(self, path: str, R: np.ndarray):
        key = path
        if key in Atlas._feat_cache:
            pts, d16 = Atlas._feat_cache[key]
            return pts, (None if d16 is None else d16.astype(np.float32))
        img = self.image(path)
        sift = cv2.SIFT_create(6000)  # dark / foggy screenshots need many to find enough matches
        k, d = sift.detectAndCompute(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), _valid_mask(img))
        pts = persp(R, np.float32([p.pt for p in k])) if k else np.zeros((0, 2))
        Atlas._feat_cache[key] = (pts, None if d is None else d.astype(np.float16))  # ~1.5 MB each
        while len(Atlas._feat_cache) > 300:  # ~1 MB each
            Atlas._feat_cache.pop(next(iter(Atlas._feat_cache)))
        return pts, d

    def _terrain_register(self, frame: Frame, hints: list[str]) -> Registration | None:
        """Shift from terrain features (flattened coordinates) against hinted screenshots.  The
        game reuses identical terrain pieces in different places, so the result must also pass a
        stricter whole-overlap terrain check, and any maps in the overlap must agree."""
        by_name = {f["name"]: f for f in self.frames}
        pn, dn = self._features(frame.path, frame.R)
        if dn is None or len(pn) < 50:
            return None
        matcher = cv2.BFMatcher()
        best = None
        for name in hints:
            f = by_name.get(name)
            if f is None:
                continue
            pr, dr = self._features(f["path"], self.frame_R(f))
            if dr is None or len(pr) < 50:
                continue
            m = matcher.knnMatch(dn, dr, k=2)
            g = [x[0] for x in m if len(x) == 2 and x[0].distance < 0.75 * x[1].distance]
            if len(g) < TERRAIN_MIN_AGREE:
                continue
            d = pr[[x.trainIdx for x in g]] - pn[[x.queryIdx for x in g]]
            votes = [(int((np.hypot(*(d - d[k]).T) < 6).sum()), k) for k in range(len(d))]
            n_agree, k = max(votes)
            if n_agree < TERRAIN_MIN_AGREE:
                continue
            inl = np.hypot(*(d - d[k]).T) < 6
            t_ref = np.array(f["M"], float)[:, 2]
            raw = np.median(d[inl], axis=0)
            if best is None or n_agree > best[0]:
                best = (n_agree, t_ref + raw / TERRAIN_SCALE, name, t_ref + raw)
        if best is None:
            return None
        n_agree, shift, ref, at = best
        return self._check_shift(frame, shift, f"terrain ({n_agree} features agree vs {ref})", at)

    def _check_shift(
        self, frame: Frame, shift: np.ndarray, label: str, terrain_at: np.ndarray | None = None
    ) -> Registration | None:
        """Accept a terrain-proposed shift only if the whole overlap correlates (stricter than the
        map route) and the maps in the overlap don't clearly contradict it.  `shift` is in map units;
        `terrain_at` is where the terrain pixels line up (TERRAIN_SCALE parallax): the pixel check is
        done there, the map position is what gets stored."""
        M = np.array([[1, 0, shift[0]], [0, 1, shift[1]]], float)
        src = frame.pts[frame.usable]
        M2, pairs, rmse = (
            refine(src, self.points(), (shift[0], shift[1])) if len(src) and len(self.nodes) else (M, [], 99.0)
        )
        moved = apply(M, src)
        inside = np.zeros(len(src), bool)
        for FM, fw, fh, FR in self.footprints():
            inside |= _inside_rect(moved, FM, fw, fh, FR)
        n_in = int(inside.sum())
        ratio = len(pairs) / max(1, n_in)
        # Thin far-away overlaps (top strip of a screenshot, under the header, in fog) show
        # different maps to each screenshot, so map agreement only vetoes a clear contradiction.
        loose = len(mutual_pairs(moved[inside], self.points(), 20)) if n_in else 0
        if n_in >= 12 and loose == 0:
            return None
        if len(pairs) >= 3 and np.hypot(*(M2[:, 2] - shift)) < 10:
            M = M2  # maps refine the terrain shift
        reg = Registration(False, "", M, len(pairs), rmse, n_in, n_in, ratio)
        if terrain_at is not None:  # pixel check where the terrain lines up
            chk = Registration(False, "", M.copy(), len(pairs), rmse, n_in, n_in, ratio)
            chk.M[:, 2] += np.asarray(terrain_at, float) - shift
            self._verify(frame, chk)
            reg.ncc, reg.ncc_pixels, reg.ref_frame = chk.ncc, chk.ncc_pixels, chk.ref_frame
        else:
            self._verify(frame, reg)
        if reg.ncc_pixels < 15000 or reg.ncc < TERRAIN_MIN_NCC:
            return None
        reg.reason = label
        return reg

    def terrain_link(self, a: Frame, b: Frame) -> tuple[int, np.ndarray]:
        """Terrain features between two screenshots (placed or not): how many agree on one
        shift, and that shift in flattened coordinates (t_b = t_a + shift)."""
        pa, da = self._features(a.path, a.R)
        pb, db = self._features(b.path, b.R)
        if da is None or db is None or len(pa) < 50 or len(pb) < 50:
            return 0, np.zeros(2)
        m = cv2.BFMatcher().knnMatch(db, da, k=2)
        g = [x[0] for x in m if len(x) == 2 and x[0].distance < 0.75 * x[1].distance]
        if len(g) < TERRAIN_MIN_AGREE:
            return 0, np.zeros(2)
        d = pa[[x.trainIdx for x in g]] - pb[[x.queryIdx for x in g]]
        n_agree, k = max((int((np.hypot(*(d - d[q]).T) < 6).sum()), q) for q in range(len(d)))
        inl = np.hypot(*(d - d[k]).T) < 6
        return n_agree, np.median(d[inl], axis=0) / TERRAIN_SCALE

    def _merge_icons(self, frame: Frame, M: np.ndarray) -> None:
        """icon badges: the same badge (or an unidentified ring at the same spot) merges. Each badge's map
        base is its ROW's base, found in this screenshot's own pixels (up to 5 badges side by side, ~36 px
        apart, the map under the row's middle - user): grouping rows later from merged atlas positions split
        rows whose copies from two passes landed a little apart, and doubled their map."""
        icons = getattr(frame, "icons", [])
        base_of = row_bases(icons)
        for k, m in enumerate(icons):
            p = apply(M, persp(frame.R, [[m["x"], m["y"]]]))[0]
            b = apply(M, persp(frame.R, [base_of[k]]))[0]
            for ex in self.icons:
                same = ex["name"] == m["name"] or "Unidentified" in (ex["name"], m["name"])
                if same and math.hypot(ex["x"] - p[0], ex["y"] - p[1]) < ICON_MERGE:
                    k = ex["n"]
                    for key, v in (("x", p[0]), ("y", p[1]), ("bx", b[0]), ("by", b[1])):
                        ex[key] = (ex[key] * k + float(v)) / (k + 1)
                    ex["n"] += 1
                    ex["frames"].append(frame.name)
                    if ex["name"] == "Unidentified" and m["name"] != "Unidentified":
                        ex["name"], ex["source"] = m["name"], m["source"]
                    ex["score"] = max(ex["score"], m["score"])
                    break
            else:
                self.icons.append(
                    {
                        "name": m["name"],
                        "x": float(p[0]),
                        "y": float(p[1]),
                        "bx": float(b[0]),
                        "by": float(b[1]),
                        "n": 1,
                        "frames": [frame.name],
                        "score": m["score"],
                        "source": m["source"],
                    }
                )

    def rebuild_icons(self, frames_by_name: dict) -> None:
        """Re-merge every screenshot's badges from its (re-labelled) detection, e.g. after
        icons were re-detected or taught.  Screenshots without a detection are skipped."""
        self.icons = []
        for f in self.frames:
            fr = frames_by_name.get(f["name"])
            if fr is not None:
                self._merge_icons(fr, np.array(f["M"], float))

    # -------- export
    def to_json(self) -> dict:
        def strength(e):
            return e["seen"] / max(1, e["could"])

        return {
            "version": "atlas-builder-0.2",
            "frames": [{**{k: v for k, v in f.items() if k != "stats"}, **f["stats"]} for f in self.frames],
            "nodes": [
                {"id": i, **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in n.items()}}
                for i, n in enumerate(self.nodes)
            ],
            "edges": [
                {
                    "a": a,
                    "b": b,
                    "seen": e["seen"],
                    "could": e["could"],
                    "strength": round(strength(e), 2),
                    "confirmed": e["confirmed"],
                }
                for (a, b), e in sorted(self.edges.items())
            ],
            "landmarks": self.landmarks,
            "bookmarks": self.bookmarks,
            "icons": self.icons,
            "city_types": self.city_types,
            "city_auto": self.city_auto,
            "landmark_edits": self.landmark_edits,
            "biome_edits": self.biome_edits,
            "locks": self.locks,
            "lock_scanned": self.lock_scanned,
            "final": self.final,
        }

    def save(self, path) -> None:
        atlas_io.write_text_atomic(path, json.dumps(self.to_json(), indent=1))
        # saved detections live next to the atlas; a copy saved elsewhere (undo snapshot) has none, so keep
        # pointing at the real ones (v1.00: every auto-add re-traced ~100 screenshots from their images)
        new_dir = Path(path).with_name(Path(path).stem + "_frames")
        if getattr(self, "frames_dir", None) is None or new_dir.is_dir():
            self.frames_dir = new_dir

    @staticmethod
    def load(path) -> Atlas:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        at = Atlas()
        at.frames_dir = Path(path).with_name(Path(path).stem + "_frames")  # saved detections (paths, dashes)
        at.nodes = [
            {
                "x": n["x"],
                "y": n["y"],
                "n": n["n"],
                "frames": n["frames"],
                "tower": n["tower"],
                "icon": n.get("icon", ""),
                "hidden": n["hidden"],
                "sources": n.get("sources", []),
                **({"guessed_in": n["guessed_in"]} if "guessed_in" in n else {}),
            }
            for n in d["nodes"]
        ]
        at.edges = {
            (e["a"], e["b"]): {"seen": e["seen"], "could": e["could"], "confirmed": e["confirmed"]} for e in d["edges"]
        }
        at.landmarks = d["landmarks"]
        at.bookmarks = d.get("bookmarks", [])
        at.icons = d.get("icons", [])
        at.final = d.get("final")
        at.city_types = d.get("city_types", [])
        at.city_auto = d.get("city_auto", [])
        at.landmark_edits = d.get("landmark_edits", [])
        at.biome_edits = d.get("biome_edits", [])
        at.locks = d.get("locks", [])
        at.lock_scanned = d.get("lock_scanned", [])
        keys = ("inliers", "rmse", "ncc", "ratio", "reference", "reason")
        at.frames = [
            {**{k: v for k, v in f.items() if k not in keys}, "stats": {k: f.get(k) for k in keys}} for f in d["frames"]
        ]
        base = Path(path).resolve().parent
        for f in at.frames:
            f["path"] = _find_screenshot(f["path"], base)
        return at

    # -------- composite image
    def composite(self, max_pixels: int = 36_000_000, with_weight: bool = False):
        """stitched terrain: each spot from the screenshot that shows it most centrally.
        with_weight also returns the per-pixel weight, so screenshots can be pasted in later
        (paste_into) without rebuilding everything."""
        corners = []
        frames = [f for f in self.frames if Path(f["path"]).exists()]  # moved/deleted shots: skip
        if not frames:
            empty = (np.zeros((1, 1, 3), np.uint8), (0, 0, 1.0))
            return (*empty, np.zeros((1, 1), np.float32)) if with_weight else empty
        for f in frames:
            c = np.array([[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]], float)
            corners.append(persp(screen_to_atlas(np.array(f["M"], float), self.frame_R(f)), c))
        allc = np.vstack(corners)
        x0, y0 = np.floor(allc.min(axis=0)).astype(int)
        x1, y1 = np.ceil(allc.max(axis=0)).astype(int)
        W, H = int(x1 - x0), int(y1 - y0)
        scale = min(1.0, math.sqrt(max_pixels / max(1, W * H)))
        CW, CH = max(1, int(W * scale)), max(1, int(H * scale))
        best_w = np.zeros((CH, CW), np.float32)
        canvas = np.zeros((CH, CW, 3), np.uint8)
        self.paste_into(canvas, best_w, (x0, y0, scale), frames)
        if with_weight:
            return canvas, (x0, y0, scale), best_w
        return canvas, (x0, y0, scale)

    def paste_into(self, canvas, best_w, origin, frames) -> bool:
        """warp screenshots into an existing stitched canvas, each only into its own patch.
        False when one falls outside the canvas (then rebuild with composite)."""
        x0, y0, scale = origin
        CH, CW = best_w.shape
        T = np.array([[scale, 0, -x0 * scale], [0, scale, -y0 * scale], [0, 0, 1]], float)
        inside = True
        for f in frames:
            if not Path(f["path"]).exists():
                continue
            Hc = T @ screen_to_atlas(np.array(f["M"], float), self.frame_R(f))
            c = persp(Hc, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
            if c[:, 0].min() < -1 or c[:, 1].min() < -1 or c[:, 0].max() > CW + 1 or c[:, 1].max() > CH + 1:
                inside = False
            bx0, by0 = np.maximum(np.floor(c.min(axis=0)).astype(int), 0)
            bx1, by1 = np.minimum(np.ceil(c.max(axis=0)).astype(int), [CW, CH])
            if bx1 <= bx0 or by1 <= by0:
                continue
            Hroi = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]], float) @ Hc
            size = (int(bx1 - bx0), int(by1 - by0))
            img = self.image(f["path"])
            valid = (_valid_mask(img) > 0).astype(np.uint8) * 255  # (the cached mask is read-only)
            dist = cv2.distanceTransform(valid, cv2.DIST_L2, 3)
            wmap = cv2.warpPerspective(dist, Hroi, size, flags=cv2.INTER_LINEAR, borderValue=0)
            pix = cv2.warpPerspective(img, Hroi, size, flags=cv2.INTER_LINEAR, borderValue=0)
            sub_w = best_w[by0:by1, bx0:bx1]
            take = wmap > sub_w
            canvas[by0:by1, bx0:bx1][take] = pix[take]
            sub_w[take] = wmap[take]
        return inside
