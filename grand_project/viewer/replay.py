"""viewer.replay: the order screenshots are revealed in for the replay / timelapse, and when each was taken.

Pure logic, no window: the replay panel (replay_panel.py) and "Colour by when taken" use it, and the tests
check it directly.

A replay is a list of steps; each step reveals a few screenshots (per_step). Everything the atlas holds appears at
the step of the first screenshot that saw it: a map node or icon by the screenshots listed with it, a landmark by
the first revealed screenshot whose area holds it. Ordered by time, the screenshots of an island that waited for a
bridge appear when they were taken, and the bridge last (user), not all at once when the island was placed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .constants import REPLAY_BATCH_GAP, REPLAY_SESSION_GAP, REPLAY_SPIRAL_PITCH

STEAM_TIME = re.compile(r"_(\d{14})_\d+$")  # Steam names screenshots <app id>_<YYYYMMDDHHMMSS>_<n>


def capture_time(frame: dict) -> float | None:
    """When a screenshot was taken: from its Steam file name, else the file's modified time.

    Args:
        frame: Atlas frame dict ("name", "path").

    Returns:
        Seconds since the epoch (local time), or None when neither is known.
    """
    m = STEAM_TIME.search(frame.get("name", ""))
    if m:
        try:
            return time.mktime(time.strptime(m.group(1), "%Y%m%d%H%M%S"))
        except ValueError:
            pass
    try:
        return Path(frame["path"]).stat().st_mtime
    except (OSError, KeyError):
        return None


def time_order(times: list[float | None]) -> list[int]:
    """Screenshot indices by when they were taken; ones without a time keep their place after the timed one before.

    Args:
        times: capture_time of each screenshot, in placement order.

    Returns:
        Indices into times.
    """
    last = float("-inf")
    keys = []
    for i, t in enumerate(times):  # untimed: right after the screenshot placed before it
        last = t if t is not None else last
        keys.append((last if t is None else t, t is None, i))
    return [k[2] for k in sorted(keys)]


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
        footprints: (polygon (4, 2) in atlas units, bbox) per screenshot, as the viewer keeps them.

    Returns:
        (n, 2) float array.
    """
    if not footprints:
        return np.zeros((0, 2))
    return np.array([np.asarray(poly, float).mean(axis=0) for poly, _bb in footprints])


def reveal_order(kind: str, times: list[float | None], mids: np.ndarray, pitch: float = REPLAY_SPIRAL_PITCH):
    """The order screenshots are revealed in.

    Args:
        kind: "by time" (when taken), "by placement" (when added to the atlas), "spiral" (around the first
            screenshot taken, turning outward) or "distance" (rings around it).
        times: capture_time of each screenshot, in placement order.
        mids: (n, 2) middle of each screenshot.
        pitch: Atlas units between turns of the spiral.

    Returns:
        Screenshot indices in reveal order.
    """
    n = len(times)
    if kind == "by placement" or n < 2:
        return list(range(n))
    by_time = time_order(times)
    if kind == "by time":
        return by_time
    d = mids - mids[by_time[0]]  # around the first screenshot taken
    r = np.hypot(d[:, 0], d[:, 1])
    if kind == "distance":
        return [int(i) for i in np.lexsort((np.arange(n), r))]
    turn = (np.arctan2(d[:, 1], d[:, 0]) % (2 * np.pi)) / (2 * np.pi)  # 0..1 around
    ring = np.round(r / pitch - turn)  # which turn of the spiral r = pitch * (ring + turn) the screenshot is on
    return [int(i) for i in np.lexsort((np.arange(n), ring + turn))]


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


def make_plan(frames: list[dict], footprints: list, kind: str, per_step: int = 1) -> Plan:
    """Work out a replay of the atlas's screenshots.

    Args:
        frames: Atlas frames (placement order).
        footprints: Their areas, as the viewer keeps them (same order).
        kind: One of REPLAY_TYPES.
        per_step: Screenshots revealed per step (at least 1).

    Returns:
        The Plan.
    """
    per_step = max(1, int(per_step))
    times = [capture_time(f) for f in frames]
    order = reveal_order(kind, times, centres(footprints))
    step_of = np.zeros(len(frames), int)
    for k, i in enumerate(order):
        step_of[i] = k // per_step
    n_steps = (len(order) + per_step - 1) // per_step
    step_time: list[float | None] = [None] * n_steps
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
    return Plan(order, step_of, n_steps, times, sessions(times), ticks, step_time)


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
