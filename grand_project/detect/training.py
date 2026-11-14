"""detect.training (from atlas_detect.py)"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import paths as rc_paths
from grand_project import truth as atlas_truth

from .badges import badge_book, badge_candidates, badge_features, badge_labels, badges_from
from .constants import CACHE, DB_PATH, EXTRA_MAPS, MAP, TESTS, TOWER_REFS, TREE_NEG_WEIGHT, TRUTH, TRUTH_SETS
from .landmarks import expedition_rules, landmarks_from, old_landmarks, tower_features, tower_labels
from .maps import _nms, candidate_labels, drop_hud, map_candidates, map_features
from .models import save_model
from .paths import maps_from_paths, path_dashes, path_features, trace_paths
from .walls import fortress_walls


# ---------------------------------------------------------------- commands
def _labelled() -> tuple[dict, dict]:
    """truth (all TRUTH_SETS) + per screenshot: image, map (points, features, labels), badge (points, features,
    labels). Ship markers are not ring badges: left out of the badge training."""
    truth, where = {}, {}
    for tf, shots in TRUTH_SETS:
        if tf.exists():
            for name, t in json.loads(tf.read_text(encoding="utf-8")).items():
                truth[name] = dict(t, badges=[b for b in t["badges"] if not b["name"].startswith("ExpeditionShip")])
                where[name] = shots / name
    data = {}
    for name, t in truth.items():
        img = cv2.imdecode(np.fromfile(str(where[name]), np.uint8), cv2.IMREAD_COLOR)
        pts, dv = map_candidates(img)
        bp, ring, extra = badge_candidates(img)
        dashes = path_dashes(img)
        old = old_landmarks(img)
        tp = [(m["x"], m["y"]) for m in t["maps"] if "ui" not in m["flags"]]
        data[name] = {
            "img": img,
            "old": old,
            "dashes": dashes,
            "path": where[name],
            "towers": (tp, tower_features(img, tp, old["towers"]), tower_labels(tp, t)),
            "maps": (
                pts,
                np.hstack([map_features(img, pts, dv), path_features(pts, dashes)]),
                candidate_labels(pts, t),
            ),
            "badges": (bp, badge_features(img, bp, ring, extra), badge_labels(bp, t)),
        }
    return truth, data


def _tower_refs() -> tuple[np.ndarray, np.ndarray]:
    """extra tower training data: the user's 'pure tower references' shots (9 towers panned across the
    screen, projected into every shot; the maps found there are the non-towers)"""
    if not TOWER_REFS.exists():
        return np.zeros((0, 0)), np.zeros(0)
    X, y = [], []
    for f, v in json.loads(TOWER_REFS.read_text(encoding="utf-8")).items():
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        if img is None or not v["items"]:
            continue
        X.append(tower_features(img, [(i["x"], i["y"]) for i in v["items"]], v["old_towers"]))
        y += [int(i["tower"]) for i in v["items"]]
    if not X:  # (the tower shots are not in the public test data)
        return np.zeros((0, 0)), np.zeros(0)
    return np.vstack(X), np.array(y)


def _extra_maps() -> dict:
    """extra map training data (maps only, no badge / landmark labels): the user's path-marked shots,
    where they circled the missed maps - mostly plain unlit bases the 10 labelled shots barely have"""
    if not EXTRA_MAPS.exists():
        return {}
    out = {}
    for f, v in json.loads(EXTRA_MAPS.read_text(encoding="utf-8")).items():
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        pts, dv = map_candidates(img)
        t = {"maps": [dict(m, flags=[]) for m in v["maps"]], "maybe": [], "landmarks": []}
        out[f] = (
            pts,
            np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))]),
            candidate_labels(pts, t),
        )
    return out


def _tree_rounds():
    """(key file, labels file, labels name the maps?) of every arborist round"""
    return [
        (TESTS / "trees" / "trees_key.json", TESTS / "trees" / "trees_labels.txt", True),
        (TESTS / "trees2" / "trees2_key.json", TESTS / "trees2" / "trees2_labels.txt", False),
    ]


def _tree_examples() -> tuple[np.ndarray, np.ndarray] | None:
    """map training rows from the arborist sheets: every tile is a labelled map / not-a-map spot (orange foliage,
    beams, Corruption ground and copper-rimmed bases look alike to the map model). Round 1 lists the maps,
    round 2 the non-maps."""
    import re

    X, y = [], []
    for kf, lf, lists_maps in _tree_rounds():
        if not kf.exists() or not lf.exists():
            continue
        key = json.loads(kf.read_text(encoding="utf-8"))
        text = " ".join(line.split("#")[0] for line in lf.read_text(encoding="utf-8").splitlines())
        ids = {
            m.group(1).upper()
            for m in re.finditer(r"\b([A-Za-z]\d+)\b(\([^)]*\))?", text)
            if not (m.group(2) and "map base" in m.group(2).lower())
        }  # "U21(map base ...)" = a map
        if not ids and "none" not in text.lower():
            continue  # not labelled yet
        by_shot: dict = {}
        for t in key:
            p = Path(t["path"]) if "path" in t else rc_paths.ROOT.parent / "rc-1" / "atlases" / "default" / t["shot"]
            by_shot.setdefault(str(p), []).append(t)
        for p, items in by_shot.items():
            if not Path(p).exists():
                continue
            img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            pts, dv = map_candidates(img)
            if not len(pts):
                continue
            F = np.hstack([map_features(img, pts, dv), path_features(pts, path_dashes(img))])
            wall = fortress_walls(img)
            for t in items:
                x0, y0 = int(t["x"]), int(t["y"])
                if wall[max(0, y0 - 60) : y0 + 60, max(0, x0 - 60) : x0 + 60].mean() > 0.15:
                    continue  # fortress special maps: never training examples (user)
                d = np.hypot(pts[:, 0] - t["x"], pts[:, 1] - t["y"])
                k = int(np.argmin(d))
                if d[k] <= 3:
                    X.append(F[k])
                    listed = t["id"].upper() in ids
                    y.append(int(listed if lists_maps else not listed))
    return (np.array(X), np.array(y)) if X else None


def _fit(data: dict, names, stage: str, weight: float = 5, leaf: int = 20):
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = np.vstack([data[n][stage][1][data[n][stage][2] >= 0] for n in names])
    y = np.concatenate([data[n][stage][2][data[n][stage][2] >= 0] for n in names])
    if stage == "maps" and data.get("_extra_maps"):
        X = np.vstack([X] + [v[1][v[2] >= 0] for v in data["_extra_maps"].values()])
        y = np.concatenate([y] + [v[2][v[2] >= 0] for v in data["_extra_maps"].values()])
    sw = np.ones(len(y))
    if stage == "maps" and data.get("_trees") is not None:
        X = np.vstack([X, data["_trees"][0]])
        y = np.concatenate([y, data["_trees"][1]])
        # hand-labelled look-alikes (orange trees, beams, Corruption ground) weigh like the maps (class 1 x weight)
        sw = np.concatenate([sw, np.where(data["_trees"][1] == 0, TREE_NEG_WEIGHT, 1.0)])
    if stage == "towers" and "_tower_refs" in data and len(data["_tower_refs"][1]):
        X = np.vstack([X, data["_tower_refs"][0]])
        y = np.concatenate([y, data["_tower_refs"][1]])
        sw = np.ones(len(y))
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.1, class_weight={0: 1, 1: weight}, min_samples_leaf=leaf, random_state=0
    ).fit(X, y, sample_weight=sw if len(sw) == len(y) else None)


def _fit_all(truth: dict, data: dict, names) -> dict:
    book = badge_book(truth, {n: data[n]["img"] for n in names}, names)
    return {
        "maps": _fit(data, names, "maps"),
        "badges": dict(book, clf=_fit(data, names, "badges")),
        "towers": _fit(data, names, "towers", weight=5),
    }


def _run_stages(d: dict, models: dict) -> dict:
    img = d["img"]
    pts, X, _l = d["maps"]
    prob = models["maps"].predict_proba(X)
    nodes = _nms(pts, prob)
    bp, BX, _l = d["badges"]
    icons, more = badges_from(
        img, bp, models["badges"]["clf"].predict_proba(BX)[:, 1], models["badges"], nodes, pts, prob[:, MAP]
    )
    nodes = nodes + more
    vis = [n for n in nodes if not n.get("hidden")]
    tp = models["towers"].predict_proba(tower_features(img, [(n["x"], n["y"]) for n in vis], d["old"]["towers"]))[:, 1]
    lms, nodes = landmarks_from(img, nodes, icons, tp, d["old"])
    lms = [
        landmark
        for landmark, on in zip(
            lms,
            core.on_hud_mask([(item["x"], item["y"]) for item in lms], img.shape[1], img.shape[0], pad=0),
            strict=False,
        )
        if not on
    ]  # a landmark inside the HUD outline is HUD art
    nodes = nodes + maps_from_paths(nodes, d["dashes"], img, pts, prob[:, MAP])
    nodes, icons, lms = expedition_rules(nodes, icons, lms)
    return {"nodes": nodes, "landmarks": lms, "icons": icons, "edges": trace_paths(nodes, d["dashes"], img)}


def cmd_score() -> int:
    t0 = time.time()
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    before, after, new = {}, {}, {}
    for name in truth:
        img = data[name]["img"]
        cf = CACHE / f"{hashlib.sha256(Path(data[name]['path']).read_bytes()).hexdigest()[:16]}.json"
        if cf.exists():
            r = json.loads(cf.read_text(encoding="utf-8"))
            before[name], after[name] = r, drop_hud(r, img.shape[1], img.shape[0])
        new[name] = _run_stages(data[name], _fit_all(truth, data, [n for n in truth if n != name]))
    for title, outs in (
        ("old detector", before),
        ("old detector + stage 1 (HUD)", after),
        ("NEW stages 2-4 (leave-one-screenshot-out)", new),
    ):
        print(f"\n== {title}")
        atlas_truth.print_score(atlas_truth.score(truth, outs))
    print(f"\nhidden maps from badge rows: {sum(1 for o in new.values() for n in o['nodes'] if n.get('hidden'))}")
    (TRUTH.parent / "last_score_outputs.json").write_text(json.dumps(new, default=float), encoding="utf-8")
    print(f"{time.time() - t0:.0f} s")
    return 0


def cmd_train() -> int:
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    data["_trees"] = _tree_examples()
    if data["_trees"] is not None:
        print(f"arborist round: {len(data['_trees'][1])} labelled spots ({int(data['_trees'][1].sum())} maps)")
    m = _fit_all(truth, data, list(truth))
    nm = int(sum((d["maps"][2] == 1).sum() for k, d in data.items() if not k.startswith("_")))
    nb = int(sum((d["badges"][2] == 1).sum() for k, d in data.items() if not k.startswith("_")))
    save_model("maps", m["maps"], {"screenshots": len(truth), "maps": nm})
    save_model("badges", m["badges"], {"screenshots": len(truth), "badges": nb, "pictures": len(m["badges"]["names"])})
    nt = int(sum(d["towers"][2].sum() for k, d in data.items() if not k.startswith("_")) + data["_tower_refs"][1].sum())
    save_model("towers", m["towers"], {"screenshots": len(truth), "towers": nt})
    print(
        f"trained on {len(truth)} screenshots: map model ({nm} maps), badge model ({nb} badges, "
        f"{len(m['badges']['names'])} labelled pictures) -> {DB_PATH.name}"
    )
    return 0
