"""detect.training"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import paths as rc_paths
from grand_project import truth as atlas_truth

from .badges import badge_book, badge_candidates, badge_features, badge_labels, badges_from
from .constants import (
    DB_PATH,
    EXTRA_BADGES,
    EXTRA_MAPS,
    MAP,
    NODE_STATE_TRUTH,
    TESTS,
    TOWER_REFS,
    TREE_NEG_WEIGHT,
    TRUTH,
    TRUTH_SETS,
)
from .landmarks import expedition_rules, landmarks_from, old_landmarks, tower_features, tower_labels
from .maps import _nms, candidate_labels, map_candidates, map_features
from .models import save_model
from .node_states import name_states
from .paths import maps_from_paths, path_dashes, path_features, trace_paths
from .walls import fortress_walls


# ---------------------------------------------------------------- commands
def _labelled() -> tuple[dict, dict]:
    """Load the hand-labelled truth (all TRUTH_SETS) and compute every stage's training data per screenshot.

    Ship markers are not ring badges: left out of the badge training.

    Returns:
        (truth, data): truth per screenshot name, and per screenshot name a dict with "img", "old"
        (old_landmarks), "dashes", "path", and (points, features, labels) tuples for "towers", "maps" and
        "badges".
    """
    truth, where = _truth_screenshots()
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
    """Extra tower training data: the user's 'pure tower references' shots.

    9 towers panned across the screen, projected into every shot; the maps found there are the non-towers.

    Returns:
        (X, y): tower feature rows and 1 / 0 labels; empty arrays when TOWER_REFS or its shots are missing
        (the tower shots are not in the public test data).
    """
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
    """Extra map training data (maps only, no badge / landmark labels): the user's path-marked shots.

    The user circled the missed maps there - mostly plain unlit bases the 10 labelled shots barely have.

    Returns:
        Screenshot path -> (points, features, labels) as for the "maps" stage; {} without EXTRA_MAPS.
    """
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


def _extra_badges() -> dict:
    """Extra icon-finder training data (positions only, no names).

    Crawl screenshots with every icon marked, so the finder sees the glowing / rare icons the hand-labelled shots
    barely have.

    Returns:
        Screenshot name -> (points, features, labels) as for the "badges" stage; {} without EXTRA_BADGES.
    """
    if not EXTRA_BADGES.exists():
        return {}
    out = {}
    for f, v in json.loads(EXTRA_BADGES.read_text(encoding="utf-8")).items():
        img = cv2.imdecode(np.fromfile(str(TESTS / f), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        bp, ring, extra = badge_candidates(img)
        t = {"badges": [{"x": x, "y": y} for x, y in v["badges"]]}
        out[f] = (bp, badge_features(img, bp, ring, extra), badge_labels(bp, t))
    return out


def _tree_rounds():
    """The files of every arborist round.

    Returns:
        List of (key file, labels file, labels name the maps?) tuples.
    """
    return [
        (TESTS / "trees" / "trees_key.json", TESTS / "trees" / "trees_labels.txt", True),
        (TESTS / "trees2" / "trees2_key.json", TESTS / "trees2" / "trees2_labels.txt", False),
    ]


def _tree_examples() -> tuple[np.ndarray, np.ndarray] | None:
    """Map training rows from the arborist sheets.

    Every tile is a labelled map / not-a-map spot (orange foliage, beams, Corruption ground and copper-rimmed bases
    look alike to the map model). Round 1 lists the maps, round 2 the non-maps. Tiles on fortress walls (fortress
    special maps) are never training examples (user); a tile needs a map candidate within 3 px.

    Returns:
        (X, y): map feature rows and 1 / 0 labels, or None when no round is labelled yet.
    """
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
    """Fit one stage's gradient-boosted classifier on the given screenshots.

    Candidates labelled -1 are left out. Adds the stage's extra data when present in `data`: "_extra_badges"
    (badges), "_extra_maps" and "_trees" (maps; tree look-alikes weigh TREE_NEG_WEIGHT), "_tower_refs" (towers).

    Args:
        data: Per-screenshot training data (_labelled) plus the optional "_..." extra entries.
        names: Screenshot names to train on.
        stage: "maps", "badges" or "towers".
        weight: Class weight of class 1 (class 0 weighs 1).
        leaf: min_samples_leaf of the classifier.

    Returns:
        The fitted HistGradientBoostingClassifier.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = np.vstack([data[n][stage][1][data[n][stage][2] >= 0] for n in names])
    y = np.concatenate([data[n][stage][2][data[n][stage][2] >= 0] for n in names])
    if stage == "badges" and data.get("_extra_badges"):
        X = np.vstack([X] + [v[1][v[2] >= 0] for v in data["_extra_badges"].values()])
        y = np.concatenate([y] + [v[2][v[2] >= 0] for v in data["_extra_badges"].values()])
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
    """Fit every stage's model on the given screenshots.

    Args:
        truth: Truth per screenshot name.
        data: Per-screenshot training data (_labelled) plus the optional extra entries.
        names: Screenshot names to train on.

    Returns:
        {"maps": classifier, "badges": {"clf": classifier, "names", "F"} (with the badge book), "towers":
        classifier}.
    """
    book = badge_book(truth, {n: data[n]["img"] for n in names}, names)
    return {
        "maps": _fit(data, names, "maps"),
        "badges": dict(book, clf=_fit(data, names, "badges")),
        "towers": _fit(data, names, "towers", weight=5),
    }


def _run_stages(d: dict, models: dict) -> dict:
    """Run the detector stages on one screenshot's precomputed training data (like pipeline.detect).

    A landmark inside the HUD outline is HUD art and is dropped. Unlike detect, no ship markers and no fortress
    wall filter.

    Args:
        d: One screenshot's entry from _labelled.
        models: Models as returned by _fit_all.

    Returns:
        Dict with "nodes", "landmarks", "icons" and "edges" (paths) lists.
    """
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
    for n, state in zip(nodes, name_states(img, nodes), strict=True):  # as builder.extract_frame names them
        n["state"] = state
    return {"nodes": nodes, "landmarks": lms, "icons": icons, "edges": trace_paths(nodes, d["dashes"], img)}


def cmd_score() -> int:
    """Command `python -m grand_project.detect score`: test every stage leave-one-screenshot-out.

    Each labelled screenshot is judged by models trained without it; prints the score and writes the outputs to
    last_score_outputs.json next to TRUTH.

    Returns:
        0 (process exit code).
    """
    t0 = time.time()
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    data["_extra_badges"] = _extra_badges()
    # each screenshot judged by models trained without it
    new = {name: _run_stages(data[name], _fit_all(truth, data, [n for n in truth if n != name])) for name in truth}
    print("\n== detector (leave-one-screenshot-out)")
    atlas_truth.print_score(atlas_truth.score(truth, new))
    print(f"\nhidden maps from badge rows: {sum(1 for o in new.values() for n in o['nodes'] if n.get('hidden'))}")
    (TRUTH.parent / "last_score_outputs.json").write_text(json.dumps(new, default=float), encoding="utf-8")
    print(f"{time.time() - t0:.0f} s")
    return 0


def _truth_screenshots() -> tuple[dict, dict]:
    """The hand-labelled truth (all TRUTH_SETS) and where each screenshot is, as ``_labelled`` reads them (Expedition
    ship markers are not ring badges: left out)."""
    truth, where = {}, {}
    for tf, shots in TRUTH_SETS:
        if tf.exists():
            states = _states_truth(shots)
            for name, t in json.loads(tf.read_text(encoding="utf-8")).items():
                truth[name] = dict(
                    t,
                    badges=[b for b in t["badges"] if not b["name"].startswith("ExpeditionShip")],
                    states=states.get(name, []),
                )
                where[name] = shots / name
    return truth, where


def _states_truth(shots: Path) -> dict:
    """The hand-checked map node states next to a folder's screenshots (NODE_STATE_TRUTH; {} without the file).

    Returns:
        {screenshot file name: [{x, y, state}]} (screen px, as truth.json).
    """
    f = shots / NODE_STATE_TRUTH
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def cmd_score_rf_detr() -> int:
    """Command `python -m grand_project.detect score_rf_detr`: the RF-DETR detector on the hand-labelled screenshots.

    The model is GRAND_PROJECT_RF_DETR_MODEL's, else runs/rf-detr-small/best. The truth screenshots are pinned to the
    annotator's test split, so no model ever trained on them: the score is a held-out one, beside `score`'s
    leave-one-out score of the classical detector. Writes the outputs to last_score_outputs_rf_detr.json next to
    TRUTH.

    Returns:
        0 (process exit code).
    """
    from .rf_detr_model import detect_rf_detr

    t0 = time.time()
    truth, where = _truth_screenshots()
    new = {}
    for name in truth:
        img = cv2.imdecode(np.fromfile(str(where[name]), np.uint8), cv2.IMREAD_COLOR)
        out = detect_rf_detr(img)
        out["icons"] = [icon for icon in out["icons"] if not icon["name"].startswith("ExpeditionShip")]
        for n, state in zip(out["nodes"], name_states(img, out["nodes"]), strict=True):  # as the program names them
            n["state"] = state
        new[name] = out
    print("\n== RF-DETR detector (held-out: the truth screenshots are always test)")
    atlas_truth.print_score(atlas_truth.score(truth, new))
    (TRUTH.parent / "last_score_outputs_rf_detr.json").write_text(json.dumps(new, default=float), encoding="utf-8")
    print(f"{time.time() - t0:.0f} s")
    return 0


def cmd_train() -> int:
    """Command `python -m grand_project.detect train`: fit every model on all labelled screenshots.

    Training mode: stores the maps, badges and towers models in the DB, then trains the City barrel model
    (references/city_barrel.npz).

    Returns:
        0 (process exit code).
    """
    truth, data = _labelled()
    data["_tower_refs"] = _tower_refs()
    data["_extra_maps"] = _extra_maps()
    data["_extra_badges"] = _extra_badges()
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
    from .citytrain import train as train_cities

    train_cities()  # the City barrel model (references/city_barrel.npz)
    return 0
