"""The replay's order and timing (viewer.replay): no window, no screenshots needed."""

import numpy as np

from grand_project.viewer import replay as R


def _frame(name, x=0.0, y=0.0):
    """An atlas frame and its area: a 1920 x 1080 screenshot whose top-left corner is at (x, y)."""
    poly = np.array([[x, y], [x + 1920, y], [x + 1920, y + 1080], [x, y + 1080]], float)
    return {"name": name, "path": f"/nowhere/{name}.png"}, (poly, (x, y, x + 1920, y + 1080))


def test_capture_time_comes_from_the_steam_name():
    t1 = R.capture_time({"name": "2694490_20261115193515_1", "path": "/nowhere"})
    t2 = R.capture_time({"name": "2694490_20261115193535_2", "path": "/nowhere"})
    assert t1 is not None and t2 - t1 == 20
    assert R.capture_time({"name": "Screenshot_12", "path": "/nowhere/x.png"}) is None


def test_by_time_reveals_an_island_when_taken_and_the_bridge_last():
    """Placed together when the bridge arrived, an island's screenshots still appear in the order they were taken."""
    names = [
        "2694490_20261115100000_1",  # placed first
        "2694490_20261115100200_1",  # island screenshot 1 (placed late, with the bridge)
        "2694490_20261115100100_1",  # island screenshot 2
        "2694490_20261115100300_1",  # the bridge
    ]
    fr = [_frame(n, 2000.0 * k)[0] for k, n in enumerate(names)]
    fp = [_frame(n, 2000.0 * k)[1] for k, n in enumerate(names)]
    plan = R.make_plan(fr, fp, "by time")
    assert plan.order == [0, 2, 1, 3]


def test_steps_sessions_and_batches():
    names = [
        "2694490_20261115100000_1",
        "2694490_20261115100010_1",
        "2694490_20261115100500_1",  # 5 minutes later: a new batch (tick)
        "2694490_20261115140000_1",  # hours later: a new session
    ]
    fr, fp = zip(*[_frame(n, 100.0 * k) for k, n in enumerate(names)], strict=True)
    plan = R.make_plan(list(fr), list(fp), "by time", per_step=2)
    assert plan.n_steps == 2 and list(plan.step_of) == [0, 0, 1, 1]
    assert plan.session_of == [0, 0, 0, 1]
    one = R.make_plan(list(fr), list(fp), "by time")
    assert one.ticks == [0, 2, 3]


def test_spiral_and_distance_start_at_the_first_screenshot_taken():
    rng = np.random.default_rng(3)
    pos = rng.uniform(-6000, 6000, (40, 2))
    names = [f"2694490_202611151{k:03d}00_1" for k in range(40)]
    fr, fp = zip(*[_frame(n, x, y) for n, (x, y) in zip(names, pos, strict=True)], strict=True)
    mids = R.centres(list(fp))
    first = R.time_order([R.capture_time(f) for f in fr])[0]
    for kind in ("spiral", "distance"):
        order = R.make_plan(list(fr), list(fp), kind).order
        assert order[0] == first and sorted(order) == list(range(40))
    dist = np.hypot(*(mids - mids[first]).T)
    order = R.make_plan(list(fr), list(fp), "distance").order
    assert np.all(np.diff(dist[order]) >= 0), "distance: rings outward"
    order = R.make_plan(list(fr), list(fp), "spiral").order
    assert np.corrcoef(np.arange(40), dist[order])[0, 1] > 0.8, "spiral: moves outward overall"


def test_items_appear_with_their_first_screenshot():
    names = ["a", "b", "c"]
    fr = [{"name": n, "path": "/nowhere"} for n in names]
    step_of = np.array([2, 0, 1])
    assert list(R.item_steps([["a", "c"], ["b"], [], ["zz"]], fr, step_of, default=5)) == [1, 0, 5, 5]
    _f, fp_a = _frame("a", 0, 0)
    _f, fp_b = _frame("b", 1000, 0)
    pts = np.array([[1500.0, 500.0], [100.0, 100.0], [9000.0, 9000.0]])
    assert list(R.point_steps(pts, [fp_a, fp_b], np.array([1, 0]), default=7)) == [0, 1, 7]


def test_scan_lines_go_column_by_column_from_the_right():
    pos = [(5000, 0), (5000, 3000), (0, 0), (2500, 1500), (0, 3000)]
    names = [f"2694490_2026111510000{k}_1" for k in range(5)]
    fr, fp = zip(*[_frame(n, x, y) for n, (x, y) in zip(names, pos, strict=True)], strict=True)
    assert R.make_plan(list(fr), list(fp), "scan lines").order == [0, 1, 3, 2, 4]


def test_reveal_by_area_sweeps_smoothly():
    """By area: a fixed number of steps, screenshots and points revealed as the sweep reaches them."""
    pos = [(0, 0), (4000, 0), (8000, 0), (0, 4000)]
    names = [f"2694490_2026111510000{k}_1" for k in range(4)]
    fr, fp = zip(*[_frame(n, x, y) for n, (x, y) in zip(names, pos, strict=True)], strict=True)
    plan = R.make_plan(list(fr), list(fp), "distance", reveal="area")
    assert plan.sweep is not None and plan.n_steps > 100
    assert plan.step_of[0] < plan.step_of[1] < plan.step_of[2], "farther screenshots later"
    near, far = plan.steps_at([[960, 540], [9000, 540]])
    assert near < far
    assert R.make_plan(list(fr), list(fp), "by time", reveal="area").sweep is None, "by time: whole screenshots"


def test_real_span_leaves_out_pauses():
    t = R.capture_time
    stamps = ("20261115100000", "20261115100500", "20261115150000")  # 5 min, then a 5 h pause
    times = [t({"name": f"2694490_{s}_1", "path": "/x"}) for s in stamps]
    assert R.real_span(times) == 300
