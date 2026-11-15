"""Training the City barrel model (citybase.py) from screenshots with known cities.

Part of ``python -m grand_project.detect train`` (every model trains with that one command); on its own:
``python -m grand_project.detect train_cities [FOLDER ...]`` (default: CITY_TRUTH_SETS).

Each folder holds screenshots plus ``cities_truth.json``::

    {"<screenshot file name>": {"cities": [[x, y], ...], "unsure": [[x, y], ...]}, ...}

Each point is a city's map node on screen (or near it, e.g. its icon row). It belongs to the nearest detected map
node within CITY_TRAIN_SNAP px; "unsure" points are left out. Every other detected map node is a "not a city"
example. The detected map nodes are cached in the truth file, so retraining does not re-detect.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from grand_project import core

from . import citybase
from .constants import CITY_BARREL_FILE, CITY_OFF_SHIFTS, CITY_P, CITY_TRAIN_C, CITY_TRAIN_SNAP, CITY_TRUTH_SETS


@dataclass
class Examples:
    """One row per map node looked at: its barrel features and what it is.

    Attributes:
        X: Feature rows (citybase.features).
        is_city: 1 for a city's map node, 0 for any other map node.
        shot: Index of the screenshot each row came from (the fair score leaves one screenshot out at a time).
        shifted: True for an ordinary map node looked at a few px off its middle (robustness report only).
        where: (screenshot name, x, y) of each row, for listing the mistakes.
    """

    X: list = field(default_factory=list)
    is_city: list = field(default_factory=list)
    shot: list = field(default_factory=list)
    shifted: list = field(default_factory=list)
    where: list = field(default_factory=list)

    def add(self, f: np.ndarray, city: bool, shot: int, shifted: bool, where: tuple) -> None:
        """Append one example.

        Args:
            f: Feature row (citybase.features).
            city: True for a city's map node.
            shot: Index of the screenshot it came from.
            shifted: True for a map node looked at a few px off its middle.
            where: (screenshot name, x, y) in screen px.
        """
        self.X.append(f)
        self.is_city.append(int(city))
        self.shot.append(shot)
        self.shifted.append(shifted)
        self.where.append(where)

    def arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """The examples as numpy arrays.

        Returns:
            (X, is_city, shot, shifted): (n, k) features, (n,) int labels, (n,) screenshot indices and (n,) bool
            shifted flags.
        """
        return np.array(self.X), np.array(self.is_city), np.array(self.shot), np.array(self.shifted, bool)


def nearest_nodes(nodes: list, points: list) -> set[int]:
    """Indices of the detected map nodes the given screen points belong to.

    Args:
        nodes: Detected map node middles, [(x, y), ...].
        points: Truth points, [(x, y), ...].

    Returns:
        For each point, the index of its nearest map node, if that is within CITY_TRAIN_SNAP px.
    """
    N = np.array(nodes, float).reshape(-1, 2)
    owners = set()
    if not len(N):
        return owners
    for x, y in points:
        d = np.hypot(N[:, 0] - x, N[:, 1] - y)
        if d.min() <= CITY_TRAIN_SNAP:
            owners.add(int(d.argmin()))
    return owners


def _detected_nodes(img: np.ndarray, entry: dict) -> list:
    """The map nodes of one screenshot: cached in its truth entry, detected (and cached) the first time.

    Args:
        img: BGR screenshot (1080p).
        entry: The screenshot's cities_truth.json entry; gains a "nodes" list when it has none.

    Returns:
        Detected map node middles, [[x, y], ...] in screen px.
    """
    if not entry.get("nodes"):
        from grand_project import detect

        entry["nodes"] = [[float(n["x"]), float(n["y"])] for n in detect.detect(img)["nodes"]]
    return entry["nodes"]


def collect(folders: list[Path]) -> Examples:
    """Read every labelled screenshot of the given folders into training examples.

    Args:
        folders: Folders with screenshots and a cities_truth.json each.

    Returns:
        The examples. Ordinary map nodes are also added looked at a few px off (CITY_OFF_SHIFTS), marked shifted.
    """
    ex = Examples()
    shot = 0
    for folder in folders:
        truth_file = folder / "cities_truth.json"
        truth = json.loads(truth_file.read_text(encoding="utf-8"))
        for name, entry in sorted(truth.items()):
            img = core.read_screenshot(folder / name)
            if img is None:
                print(f"  {name}: can't read, skipped")
                continue
            nodes = _detected_nodes(img, entry)
            cities = nearest_nodes(nodes, entry["cities"])
            unsure = nearest_nodes(nodes, entry.get("unsure", []))
            for k, (x, y) in enumerate(nodes):
                if k in unsure:
                    continue
                city = k in cities
                f = citybase.features(img, x, y)
                if f is not None:
                    ex.add(f, city, shot, False, (name, x, y))
                if city:
                    continue
                # atlas positions are a few px off a screenshot's own: an ordinary map node looked at a few px
                # off must not look like a barrel either
                for dx, dy in CITY_OFF_SHIFTS:
                    f = citybase.features(img, x + dx, y + dy)
                    if f is not None:
                        ex.add(f, False, shot, True, (name, x + dx, y + dy))
            print(f"  {name}: {len(nodes)} map nodes, {len(cities)} cities", flush=True)
            shot += 1
        truth_file.write_text(json.dumps(truth, indent=1), encoding="utf-8")  # keeps the detected map nodes
    return ex


def fit(X: np.ndarray, is_city: np.ndarray) -> tuple[StandardScaler, LogisticRegression]:
    """Fit the barrel model: features scaled to unit variance, then a logistic regression.

    Args:
        X: Feature rows.
        is_city: 1 for cities, 0 otherwise.

    Returns:
        (scaler, model).
    """
    scaler = StandardScaler().fit(X)
    model = LogisticRegression(C=CITY_TRAIN_C, max_iter=5000, class_weight="balanced")
    return scaler, model.fit(scaler.transform(X), is_city)


def fair_probabilities(ex: Examples) -> np.ndarray:
    """Barrel probability of every example, each judged by a model trained without its screenshot.

    Models are trained on map nodes themselves only (training on the shifted views made the model worse).

    Args:
        ex: The examples (collect).

    Returns:
        (n,) float array of barrel probabilities, one per example.
    """
    X, is_city, shot, shifted = ex.arrays()
    p = np.zeros(len(X))
    for s in np.unique(shot):
        train = (shot != s) & ~shifted
        scaler, model = fit(X[train], is_city[train])
        test = shot == s
        p[test] = model.predict_proba(scaler.transform(X[test]))[:, 1]
    return p


def report(ex: Examples, p: np.ndarray) -> dict:
    """Print the fair score and list its mistakes.

    Args:
        ex: The examples.
        p: Their fair probabilities (fair_probabilities).

    Returns:
        {"found", "cities", "false", "nodes", "fooled", "shifted"}: cities found of all, false cities of all
        other map nodes, and shifted views that looked like a barrel of all shifted views.
    """
    _X, is_city, _shot, shifted = ex.arrays()
    called = p >= CITY_P
    off = shifted & (is_city == 0)
    on = ~shifted
    s = {
        "found": int((called & on & (is_city == 1)).sum()),
        "cities": int((on & (is_city == 1)).sum()),
        "false": int((called & on & (is_city == 0)).sum()),
        "nodes": int((on & (is_city == 0)).sum()),
        "fooled": int((called & off).sum()),
        "shifted": int(off.sum()),
    }
    print(f"ordinary map nodes looked at a few px off: {s['fooled']} of {s['shifted']} look like a barrel")
    print(f"fair score: {s['found']} of {s['cities']} cities found, {s['false']} false of {s['nodes']} map nodes")
    for k in np.nonzero(on & (called != (is_city == 1)))[0]:
        name, x, y = ex.where[k]
        print(f"  {'missed' if is_city[k] else 'false '} {name} ({x:.0f}, {y:.0f}) p {p[k]:.2f}")
    return s


def train(folders: list[Path] | None = None) -> dict | None:
    """Print the fair score, then train on everything and save CITY_BARREL_FILE.

    Args:
        folders: Folders with screenshots and cities_truth.json (default: those of CITY_TRUTH_SETS that exist).

    Returns:
        The fair score (report), or None when there is nothing to train on.
    """
    folders = [f for f in (folders or CITY_TRUTH_SETS) if (f / "cities_truth.json").exists()]
    if not folders:
        print("city barrel: no cities_truth.json found, not retrained")
        return None
    ex = collect(folders)
    score = report(ex, fair_probabilities(ex))
    X, is_city, _shot, shifted = ex.arrays()
    scaler, model = fit(X[~shifted], is_city[~shifted])
    citybase.save_model(CITY_BARREL_FILE, scaler.mean_, scaler.scale_, model.coef_[0], model.intercept_[0])
    print(f"city barrel model -> {CITY_BARREL_FILE}")
    return score


def cmd_train_cities() -> int:
    """Command `python -m grand_project.detect train_cities [FOLDER ...]`: train only the City barrel model.

    Folders are read from sys.argv (default: CITY_TRUTH_SETS).

    Returns:
        0 (process exit code).
    """
    train([Path(a) for a in sys.argv[2:]] or None)
    return 0
