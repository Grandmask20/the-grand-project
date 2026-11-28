"""The classical detector's paths (grand_project/detect/paths.py): the path evidence around map candidates and the
walks along the dashes."""

from __future__ import annotations

import numpy as np

from grand_project.detect import paths


def brute_path_features(pts, dashes: np.ndarray) -> np.ndarray:
    """path_features worked out against every dash (as it was before the dashes were looked up in a tree)."""
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


def test_path_evidence_is_the_same_as_against_every_dash(rng, runs):
    for _ in range(runs(20)):
        dashes = np.array([[rng.uniform(0, 400), rng.uniform(0, 300)] for _ in range(rng.randint(0, 400))]).reshape(
            -1, 2
        )
        pts = np.array([[rng.randint(0, 400), rng.randint(0, 300)] for _ in range(rng.randint(1, 60))])
        assert np.array_equal(paths.path_features(pts, dashes), brute_path_features(pts, dashes))


def test_dashes_right_at_the_rings_edges_count_as_before():
    x, y = 100, 100
    edges = [0.0, 9.999, 10.0, 12.0, 19.999, 20.0, 31.999, 32.0, 44.999, 45.0, 47.999, 47.9999999, 48.0, 48.0000001]
    dashes = np.array([[x + r * np.cos(a), y + r * np.sin(a)] for r in edges for a in np.linspace(0, 6, 7)])
    pts = [(x, y), (x + 0.5, y - 0.25)]  # (spots as plain tuples too)
    assert np.array_equal(paths.path_features(pts, dashes), brute_path_features(pts, dashes))
    assert paths.path_features(pts, np.zeros((0, 2))).tolist() == [[0.0] * 6, [0.0] * 6]


def test_a_dotted_line_between_two_maps_is_walked_from_both_ends():
    nodes = [{"x": 100.0, "y": 100.0}, {"x": 300.0, "y": 140.0}]
    t = np.linspace(0, 1, 26)[2:-2]  # dashes ~8 px apart, clear of both maps' rings
    dashes = np.stack([100 + 200 * t, 100 + 40 * t], 1)
    loose: list = []
    walks = paths._walks_raw(nodes, dashes, loose)
    # (a walk starts at every dash within PATH_START of a map, so several go each way)
    assert {(w["a"], w["b"]) for w in walks} == {(0, 1), (1, 0)}
    # (the longest runs the whole line; it ends on passing into the far map's ring, a dash before its last)
    assert max(len(w["dashes"]) for w in walks if w["a"] == 0) >= len(dashes) - 1 and loose == []
    assert paths._walks_raw(nodes[:1], dashes) == []  # (one map: nowhere to go)
