"""Train the City barrel model (grand_project/detect/citybase.py) from screenshots with known cities.

    python -m tools.train_city_barrel FOLDER [FOLDER ...]

Each FOLDER holds screenshots and cities_truth.json:
    {"<screenshot file name>": {"cities": [[x, y], ...], "unsure": [[x, y], ...]}, ...}
(screen px of each city: its map node, or near it, e.g. its icon row; each goes to the nearest detected map
node within SNAP px; unsure ones are left out). Every other map node the detector finds in
those screenshots is a "not a city" example. Prints a fair score first (each screenshot judged by a model
trained without it), then saves the model trained on all of them to references/city_barrel.npz.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from grand_project import core
from grand_project import detect as atlas_detect
from grand_project.detect import citybase
from grand_project.detect.constants import CITY_BARREL_FILE, CITY_P

SNAP = 40  # px: a truth point belongs to the nearest detected map node this close
C = 0.05  # regularisation: few cities, many features


def dataset(folders: list[Path]):
    X, y, group, where = [], [], [], []
    for folder in folders:
        _add(folder, X, y, group, where)
    return np.array(X), np.array(y), np.array(group), where


def _owners(nodes, pts) -> set[int]:
    """index of the detected map node each truth point belongs to"""
    out = set()
    N = np.array(nodes, float).reshape(-1, 2)
    for x, yy in pts:
        if len(N):
            d = np.hypot(N[:, 0] - x, N[:, 1] - yy)
            if d.min() <= SNAP:
                out.add(int(d.argmin()))
    return out


def _add(folder: Path, X, y, group, where):
    truth = json.loads((folder / "cities_truth.json").read_text(encoding="utf-8"))
    g0 = max(group, default=-1) + 1
    for g, (name, t) in enumerate(sorted(truth.items()), start=g0):
        img = core.read_screenshot(folder / name)
        if img is None:
            print(f"  {name}: can't read, skipped")
            continue
        nodes = t.get("nodes") or [(n["x"], n["y"]) for n in atlas_detect.detect(img)["nodes"]]
        t["nodes"] = [[float(a), float(b)] for a, b in nodes]
        cities, unsure = _owners(nodes, t["cities"]), _owners(nodes, t.get("unsure", []))
        for k, (x, yy) in enumerate(nodes):
            if k in unsure:
                continue
            f = citybase.features(img, x, yy)
            if f is not None:
                X.append(f), y.append(int(k in cities)), group.append(g), where.append((name, x, yy))
        print(f"  {name}: {len(nodes)} map nodes, {len(cities)} cities", flush=True)
    # detected map nodes are cached in the truth file: retraining doesn't re-detect
    (folder / "cities_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")


def fit(X, y):
    sc = StandardScaler().fit(X)
    m = LogisticRegression(C=C, max_iter=5000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, m


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    X, y, group, where = dataset([Path(a) for a in sys.argv[1:]])
    p = np.zeros(len(y))
    for g in np.unique(group):
        sc, m = fit(X[group != g], y[group != g])
        p[group == g] = m.predict_proba(sc.transform(X[group == g]))[:, 1]
    found = int(((p >= CITY_P) & (y == 1)).sum())
    false = int(((p >= CITY_P) & (y == 0)).sum())
    print(f"fair score: {found} of {int(y.sum())} cities found, {false} false of {int((y == 0).sum())} map nodes")
    for k in np.nonzero((p >= CITY_P) != (y == 1))[0]:
        print(f"  {'missed' if y[k] else 'false '} {where[k][0]} ({where[k][1]:.0f}, {where[k][2]:.0f}) p {p[k]:.2f}")
    sc, m = fit(X, y)
    citybase.save_model(CITY_BARREL_FILE, sc.mean_, sc.scale_, m.coef_[0], m.intercept_[0])
    print(f"saved {CITY_BARREL_FILE}")


if __name__ == "__main__":
    main()
