"""app.replay: the order screenshots are revealed in for the replay / timelapse, and when each was taken.

Pure logic: the session works out the page's timelapse and "Colour by" with it (app.replay_data), and the tests
check it directly.

A replay is a list of steps; each step reveals a few screenshots (per_step). Everything the atlas holds appears at
the step of the first screenshot that saw it: a map node or icon by the screenshots listed with it, a landmark by
the first revealed screenshot whose area holds it. Ordered by time, the screenshots of an island that waited for a
bridge appear when they were taken, and the bridge last (user), not all at once when the island was placed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from grand_project.core import capture_time, time_order

from .constants import (
    REPLAY_AREA_RES,
    REPLAY_AREA_STEPS,
    REPLAY_BATCH_GAP,
    REPLAY_SCAN_COLUMN,
    REPLAY_SESSION_GAP,
    REPLAY_SPIRAL_PITCH,
)


def sessions(times: list[float | None], gap: float = REPLAY_SESSION_GAP) -> list[int]:
    """Session number of each screenshot: a new session starts after a pause of more than `gap` seconds.

    Args:
        times: capture_time of each screenshot.
        gap: Seconds between two screenshots that start a new session.

    Returns:
        Session index (0 = first) of each screenshot; untimed ones join the session of the one before them in time
        order.
    """
    out = [0] * len(times)
    s, prev = 0, None
    for i in time_order(times):
        t = times[i]
        if t is not None and prev is not None and t - prev > gap:
            s += 1
        out[i] = s
        prev = t if t is not None else prev
    return out


def centres(footprints: list) -> np.ndarray:
    """Middle of each screenshot's area in the atlas.

    Args:
        footprints: (polygon (4, 2) in atlas units, bbox) per screenshot (core.footprint).

    Returns:
        (n, 2) float array.
    """
    if not footprints:
        return np.zeros((0, 2))
    return np.array([np.asarray(poly, float).mean(axis=0) for poly, _bb in footprints])


def sweep_key(kind: str, pts: np.ndarray, start: np.ndarray, x_right: float, y_top: float, y_span: float):
    """Where along a sweep each point is (smaller = earlier): the order spiral / distance / scan lines reveal in.

    Args:
        kind: "spiral" (around the start, turning outward), "distance" (rings around the start) or "scan lines"
            (columns REPLAY_SCAN_COLUMN wide from the right, each from the top down).
        pts: (..., 2) atlas points.
        start: The start point (the first screenshot taken).
        x_right: The atlas's right edge (scan lines).
        y_top: The atlas's top edge (scan lines).
        y_span: The atlas's height (scan lines: one column's worth of key).

    Returns:
        Float keys, shape pts.shape[:-1], 0 at the start.
    """
    q = np.asarray(pts, float)
    if kind == "scan lines":
        col = np.floor((x_right - q[..., 0]) / REPLAY_SCAN_COLUMN)
        return col * (y_span + 1) + (q[..., 1] - y_top)  # a whole column, then the next
    d = q - start
    r = np.hypot(d[..., 0], d[..., 1])
    if kind == "distance":
        return r
    turn = (np.arctan2(d[..., 1], d[..., 0]) % (2 * np.pi)) / (2 * np.pi)  # 0..1 around
    # which turn of r = pitch * (ring + turn) the point is on; never before the first, so nothing comes before the
    # start (a point just "behind" it got a negative key: review)
    ring = np.maximum(np.round(r / REPLAY_SPIRAL_PITCH - turn), 0)
    return (ring + turn) * REPLAY_SPIRAL_PITCH


def reveal_order(kind: str, times: list[float | None], mids: np.ndarray) -> list[int]:
    """The order screenshots are revealed in (reveal by screenshots).

    Args:
        kind: "by time" (when taken), "spiral", "distance" or "scan lines" (see sweep_key; spiral and distance
            start at the first screenshot taken).
        times: capture_time of each screenshot, in placement order.
        mids: (n, 2) middle of each screenshot.

    Returns:
        Screenshot indices in reveal order.
    """
    n = len(times)
    if n < 2:
        return list(range(n))
    by_time = time_order(times)
    if kind not in ("spiral", "distance", "scan lines"):
        return by_time
    span = float(mids[:, 1].max() - mids[:, 1].min())
    key = sweep_key(kind, mids, mids[by_time[0]], mids[:, 0].max(), mids[:, 1].min(), span)
    return [int(i) for i in np.lexsort((np.arange(n), key))]


@dataclass
class Field:
    """Reveal by area: the sweep key on a grid over the atlas (smaller = revealed earlier)."""

    grid: np.ndarray  # float32 (h, w) keys
    origin: tuple[float, float, float]  # (x0, y0, cell size): cell (i, j) is atlas (x0 + j * size, y0 + i * size)
    top: float  # the largest key on the atlas

    def at(self, pts) -> np.ndarray:
        """Key at atlas points (nearest cell).

        Args:
            pts: (n, 2) atlas points.

        Returns:
            (n,) float keys.
        """
        x0, y0, c = self.origin
        h, w = self.grid.shape
        q = np.asarray(pts, float).reshape(-1, 2)
        j = np.clip(((q[:, 0] - x0) / c).astype(int), 0, w - 1)
        i = np.clip(((q[:, 1] - y0) / c).astype(int), 0, h - 1)
        return self.grid[i, j].astype(float)


def area_field(kind: str, start, bounds: tuple[float, float, float, float]) -> Field:
    """The sweep of a reveal by area over the whole atlas.

    Args:
        kind: "spiral", "distance" or "scan lines".
        start: The start point (the first screenshot taken).
        bounds: (x0, y0, x1, y1) of the atlas.

    Returns:
        The Field.
    """
    x0, y0, x1, y1 = bounds
    c = max(x1 - x0, y1 - y0, 1.0) / REPLAY_AREA_RES
    w, h = max(1, int(np.ceil((x1 - x0) / c)) + 1), max(1, int(np.ceil((y1 - y0) / c)) + 1)
    xs, ys = np.meshgrid(x0 + np.arange(w) * c, y0 + np.arange(h) * c)
    key = sweep_key(kind, np.stack([xs, ys], -1), np.asarray(start, float), x1, y0, y1 - y0)
    return Field(key.astype(np.float32), (x0, y0, c), float(key.max()) or 1.0)


@dataclass
class Plan:
    """A replay: which step reveals each screenshot, plus what the timeline shows."""

    order: list[int]  # screenshot indices in reveal order
    step_of: np.ndarray  # per screenshot (placement order): its step
    n_steps: int
    times: list[float | None]
    session_of: list[int]  # per screenshot
    ticks: list[int] = field(default_factory=list)  # steps where a new batch of screenshots starts ("by time")
    step_time: list[float | None] = field(default_factory=list)  # when each step's last screenshot was taken
    sweep: Field | None = None  # reveal by area: the sweep (step_of then holds fractional steps)
    kind: str = "by time"
    # spiral / distance / scan lines: (start point, right edge, top edge, height) of the sweep (sweep_key's frame)
    # and each step's sweep key (the farthest revealed by the end of the step): the grow camera follows them
    frame: tuple | None = None
    step_key: np.ndarray | None = None

    def steps_at(self, pts) -> np.ndarray:
        """Reveal by area: the (fractional) step each atlas point is revealed at.

        Args:
            pts: (n, 2) atlas points.

        Returns:
            (n,) float steps.
        """
        return self.sweep.at(pts) / self.sweep.top * self.n_steps


def make_plan(
    frames: list[dict],
    footprints: list,
    kind: str,
    per_step: int = 1,
    reveal: str = "screenshots",
    bounds: tuple[float, float, float, float] | None = None,
) -> Plan:
    """Work out a replay of the atlas's screenshots.

    Args:
        frames: Atlas frames (placement order).
        footprints: Their areas (core.footprint), in the same order.
        kind: One of REPLAY_TYPES.
        per_step: Screenshots revealed per step (at least 1; reveal by screenshots).
        reveal: "screenshots" (whole screenshots in order) or "area" (spiral / distance / scan lines only: a smooth
            sweep over the ground in REPLAY_AREA_STEPS steps; user: whole screenshots jumped back and forth).
        bounds: (x0, y0, x1, y1) of the atlas (reveal by area; default: around the screenshots).

    Returns:
        The Plan.
    """
    per_step = max(1, int(per_step))
    times = [capture_time(f) for f in frames]
    mids = centres(footprints)
    if reveal == "area" and kind in ("spiral", "distance", "scan lines") and len(frames) > 1:
        if bounds is None:
            allp = np.vstack([np.asarray(p, float) for p, _bb in footprints])
            bounds = (*allp.min(axis=0), *allp.max(axis=0))
        start = mids[time_order(times)[0]]
        sweep = area_field(kind, start, bounds)
        n_steps = REPLAY_AREA_STEPS
        step_of = sweep.at(mids) / sweep.top * n_steps
        order = [int(i) for i in np.argsort(step_of, kind="stable")]
        step_time: list[float | None] = [None] * n_steps
        for i in order:  # when the newest screenshot revealed by then was taken
            s = min(n_steps - 1, int(step_of[i]))
            if times[i] is not None:
                step_time[s] = times[i] if step_time[s] is None else max(step_time[s], times[i])
        frame = (start, bounds[2], bounds[1], bounds[3] - bounds[1])
        step_key = np.linspace(0, sweep.top, n_steps + 1)[1:]
        return Plan(order, step_of, n_steps, times, sessions(times), [], step_time, sweep, kind, frame, step_key)
    order = reveal_order(kind, times, mids)
    step_of = np.zeros(len(frames), int)
    for k, i in enumerate(order):
        step_of[i] = k // per_step
    n_steps = (len(order) + per_step - 1) // per_step
    frame = step_key = None
    if kind in ("spiral", "distance", "scan lines") and len(frames) > 1:
        frame = (mids[time_order(times)[0]], mids[:, 0].max(), mids[:, 1].min(), mids[:, 1].max() - mids[:, 1].min())
        keys = sweep_key(kind, mids, *frame)
        step_key = np.zeros(n_steps)
        for i in order:
            step_key[step_of[i]] = max(step_key[step_of[i]], keys[i])
        step_key = np.maximum.accumulate(step_key)
    step_time = [None] * n_steps
    for i in order:
        if times[i] is not None:
            s = step_of[i]
            step_time[s] = times[i] if step_time[s] is None else max(step_time[s], times[i])
    ticks = []
    if kind == "by time":  # a pause of a minute or more between screenshots starts a new batch
        prev = None
        for s, t in enumerate(step_time):
            if t is not None and (prev is None or t - prev > REPLAY_BATCH_GAP):
                ticks.append(s)
            prev = t if t is not None else prev
    return Plan(order, step_of, n_steps, times, sessions(times), ticks, step_time, None, kind, frame, step_key)


def real_span(times: list[float | None]) -> float:
    """How long taking the screenshots took: first to last, without the pauses between sessions.

    Args:
        times: capture_time of each screenshot.

    Returns:
        Seconds (0 when fewer than two are timed).
    """
    t = sorted(x for x in times if x is not None)
    return float(sum(b - a for a, b in zip(t, t[1:], strict=False) if b - a <= REPLAY_SESSION_GAP))


def item_steps(lists: list[list[str]], frames: list[dict], step_of: np.ndarray, default: int = 0) -> np.ndarray:
    """The step each item appears at: that of the first revealed screenshot among those that saw it.

    Args:
        lists: Per item, the names of the screenshots that saw it (a map node's or an icon's "frames").
        frames: Atlas frames (placement order).
        step_of: Plan.step_of.
        default: Step for an item no listed screenshot is known for.

    Returns:
        int array, one step per item.
    """
    at = {f["name"]: int(step_of[i]) for i, f in enumerate(frames)}
    out = np.full(len(lists), default, int)
    for k, names in enumerate(lists):
        steps = [at[n] for n in names if n in at]
        if steps:
            out[k] = min(steps)
    return out


def point_steps(points: np.ndarray, footprints: list, step_of: np.ndarray, default: int = 0) -> np.ndarray:
    """The step each point appears at: that of the first revealed screenshot whose area holds it (landmarks).

    Args:
        points: (m, 2) atlas points.
        footprints: Screenshot areas (placement order).
        step_of: Plan.step_of.
        default: Step for a point no screenshot holds.

    Returns:
        int array, one step per point.
    """
    out = np.full(len(points), default, int)
    best = np.full(len(points), np.iinfo(int).max)
    for i, (poly, (x0, y0, x1, y1)) in enumerate(footprints):
        s = int(step_of[i])
        near = np.nonzero(
            (points[:, 0] >= x0) & (points[:, 0] <= x1) & (points[:, 1] >= y0) & (points[:, 1] <= y1) & (best > s)
        )[0]
        pts = np.asarray(poly, np.float32).reshape(-1, 1, 2)
        for j in near:
            if cv2.pointPolygonTest(pts, (float(points[j, 0]), float(points[j, 1])), False) >= 0:
                best[j] = s
    found = best != np.iinfo(int).max
    out[found] = best[found]
    return out


def session_label(t: float | None) -> str:
    """A short date and time for a session or a step, e.g. "15 Nov 19:38".

    Args:
        t: Seconds since the epoch, or None.

    Returns:
        The text, or "time unknown".
    """
    return time.strftime("%d %b %H:%M", time.localtime(t)) if t is not None else "time unknown"
