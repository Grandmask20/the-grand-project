"""The order the path check scores links in (finalize.check._curve_keys): along the atlas, cell by cell."""

import numpy as np

from grand_project.finalize.check import _curve_keys


def test_the_curve_walks_every_cell_once_each_next_to_the_last():
    cells = np.array([[x, y] for y in range(8) for x in range(8)], float) * 200 + [37.0, -12.0]
    keys = _curve_keys(cells, 200.0)
    assert sorted(keys.tolist()) == list(range(64))  # every cell, once
    walk = cells[np.argsort(keys)]
    steps = np.abs(np.diff(walk, axis=0)).sum(1)
    assert np.all(steps == 200)  # each cell next to the one before


def test_one_point_and_a_line():
    assert _curve_keys(np.array([[5.0, 5.0]]), 200.0).tolist() == [0]
    line = np.array([[x * 200.0, 0.0] for x in range(5)])
    walk = line[np.argsort(_curve_keys(line, 200.0), kind="stable")]
    assert np.all(np.abs(np.diff(walk[:, 0])) <= 3 * 200)  # (close along the curve stays close on the atlas)
