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


def test_the_check_keeps_fewer_decoded_screenshots_while_it_runs(monkeypatch):
    # (its own caches keep what it works out; placing's 90 only held ~540 MB more at its peak - roa: the same result)
    from grand_project import core
    from grand_project.finalize import check

    seen = []
    monkeypatch.setattr(check, "_finalize", lambda atlas, log=None: seen.append(atlas.IMAGE_CACHE) or {})
    at = core.Atlas()
    check.finalize(at)
    assert seen == [check.FINAL_IMAGE_CACHE] and at.IMAGE_CACHE == core.Atlas.IMAGE_CACHE  # (placing's again after)
    assert "IMAGE_CACHE" not in vars(at)


def test_the_check_trims_a_cache_a_placement_just_filled(monkeypatch):
    # (lowered, it was trimmed only at the next new read: all 90 kept when every read was a hit - CodeRabbit)
    import numpy as np

    from grand_project import core
    from grand_project.finalize import check

    at = core.Atlas()
    for k in range(check.FINAL_IMAGE_CACHE + 10):
        at._images[f"s{k}.png"] = np.zeros((2, 2, 3), np.uint8)
    seen = []
    monkeypatch.setattr(check, "_finalize", lambda atlas, log=None: seen.append(len(atlas._images)) or {})
    check.finalize(at)
    assert seen == [check.FINAL_IMAGE_CACHE] and "s0.png" not in at._images  # (the oldest let go)
