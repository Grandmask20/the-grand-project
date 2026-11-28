"""finalize.states: each map node's state over time.

A map node is grey (unreachable), blue (can be pathed to), green (cleared) or red (failed: cities and halls, and
Unique maps), and running maps changes that over time. The check keeps a map's state from its newest sightings (by
when each screenshot was taken, ``core.capture_time``) as long as the change from the older ones is allowed (user's
rules): grey -> blue -> green, blue -> red (only where a City / Hall stands or on a STATE_RED_ICONS map: the Deadly
Map Boss, a Unique map); green and red never change again. A map's icons over time are finalize.icon_time's.

Anything else between two screenshots of one spot is a detection error: the fit is the allowed story that the
fewest sightings disagree with (each disagreeing sighting costs 1, a change STATE_CHANGE_COST), and the sightings
that still disagree are counted as errors.

Screenshots taken in the same second are one look. Two screenshots a minute apart can differ (one map run between
them), and some taken minutes apart cannot, so every sighting counts on its own: no time gap is a session.
"""

from __future__ import annotations

import math

import numpy as np

from grand_project import core
from grand_project.detect.constants import NODE_STATES

from .constants import (
    STATE_AFTER,
    STATE_CHANGE_COST,
    STATE_LOG_MAX,
    STATE_RED_ICONS,
    STATE_SETTLE_REACH,
    TRACE_MATCH,
)
from .traces import _saved


def fit_path(groups: list[list[str]], red_ok: bool = True) -> tuple[list[str], int]:
    """The allowed run of states that the fewest sightings disagree with.

    Args:
        groups: The states seen in each look at the map, oldest first (screenshots of one second are one look);
            every look holds at least one state.
        red_ok: Whether the map can fail (a City / Hall stands on it, or a STATE_RED_ICONS icon); otherwise a red
            sighting is an error.

    Returns:
        (one state per look, how many sightings disagree with it). Ties go to the state most seen in the newest
        look, then to fewer changes.
    """
    if not groups:
        return [], 0
    states = [s for s in NODE_STATES if red_ok or s != "red"]
    cost = [[sum(1 for seen in g if seen != s) for s in states] for g in groups]
    best = [list(map(float, cost[0]))]
    back: list[list[int]] = [[-1] * len(states)]
    for k in range(1, len(groups)):
        row, came = [], []
        for b, s in enumerate(states):
            options = [
                (best[k - 1][a] + (0.0 if a == b else STATE_CHANGE_COST), a != b, a)
                for a, before in enumerate(states)
                if s in STATE_AFTER[before]
            ]
            total, _changed, a = min(options)
            row.append(total + cost[k][b])
            came.append(a)
        best.append(row)
        back.append(came)
    last = groups[-1]
    end = min(range(len(states)), key=lambda b: (best[-1][b], -last.count(states[b])))
    path = [end]
    for k in range(len(groups) - 1, 0, -1):
        path.append(back[k][path[-1]])
    path.reverse()
    picked = [states[b] for b in path]
    return picked, sum(cost[k][b] for k, b in enumerate(path))


def _looks(atlas) -> dict[str, tuple]:
    """Screenshot name -> (look key, order): screenshots taken in the same second are one look; ones with no time
    are each a look of their own, after the screenshot placed before them (core.time_order)."""
    times = [core.capture_time(f) for f in atlas.frames]
    order = core.time_order(times)
    out = {}
    for rank, i in enumerate(order):
        f, t = atlas.frames[i], times[i]
        out[f["name"]] = (t if t is not None else ("untimed", rank), rank, t)
    return out


def fit_nodes(atlas, maps_by: dict, nodes: list[dict], status: list[str], icons: list[dict], log=None) -> dict:
    """Fit every kept map node's state over time.

    A map's sightings are the screenshots that found it (not those that only guessed it under an icon row); in
    each, its state is that of the screenshot's own map node at that spot (the saved detection, within
    TRACE_MATCH).

    Args:
        atlas: the core.Atlas (frames, landmarks, saved detections).
        maps_by: screenshot name -> (frame dict, atlas-to-screen homography).
        nodes: the check's map nodes (x, y, frames, guessed, icons: indices into icons).
        status: each node's status so far ("removed" ones are skipped).
        icons: the merged icons (name): a STATE_RED_ICONS icon on a map lets it fail.
        log: callable taking one message string, or None.

    Returns:
        Node index -> {"state", "seen" (when the newest look was taken, epoch seconds, or None), "sightings",
        "errors" (sightings whose state disagrees)}, for the map nodes a sighting names the state of.
    """
    looks = _looks(atlas)
    places = [(lm["x"], lm["y"]) for lm in atlas.landmarks if lm["kind"] in ("City", "Hall")]
    fits: dict[int, dict] = {}
    noisy = []
    for i, nd in enumerate(nodes):
        if status[i] == "removed":
            continue
        by_look: dict = {}
        for name in nd["frames"] - nd["guessed"]:
            state = _state_at_spot(atlas, *maps_by[name], nd) if name in maps_by else None
            if state is None:
                continue
            key, rank, t = looks[name]
            look = by_look.setdefault(key, {"rank": rank, "t": t, "states": []})
            look["rank"] = min(look["rank"], rank)
            look["states"].append(state)
        if not by_look:
            continue
        ordered = sorted(by_look.values(), key=lambda lk: lk["rank"])
        red_ok = bool(STATE_RED_ICONS & {icons[k]["name"] for k in nd["icons"]}) or any(
            math.hypot(x - nd["x"], y - nd["y"]) < STATE_SETTLE_REACH for x, y in places
        )
        picked, errors = fit_path([lk["states"] for lk in ordered], red_ok)
        fits[i] = {
            "state": picked[-1],
            "seen": ordered[-1]["t"],
            "sightings": sum(len(lk["states"]) for lk in ordered),
            "errors": int(errors),
        }
        if errors:
            noisy.append((i, nd, picked, fits[i]))
    if log and noisy:
        for i, nd, picked, fit in noisy[:STATE_LOG_MAX]:
            story = " -> ".join(s for k, s in enumerate(picked) if k == 0 or s != picked[k - 1])
            log(
                f"map #{i} at ({nd['x']:.0f}, {nd['y']:.0f}): {fit['errors']} of {fit['sightings']} sightings disagree "
                f"with {story} (detection errors)"
            )
        if len(noisy) > STATE_LOG_MAX:
            log(f"... and {len(noisy) - STATE_LOG_MAX} more map nodes whose sightings disagree")
    return fits


def _state_at_spot(atlas, f: dict, Hi: np.ndarray, nd: dict) -> str | None:
    """The state of the screenshot's own (not hidden) map node at the map's spot (within TRACE_MATCH), or None when
    it has none there or did not name its state."""
    rec = _saved(atlas, f)
    if rec is None or not len(rec["P"]):
        return None
    sp = core.persp(Hi, [[nd["x"], nd["y"]]])[0]
    d = np.hypot(rec["P"][:, 0] - sp[0], rec["P"][:, 1] - sp[1])
    d[rec["hidden"]] = np.inf
    j = int(np.argmin(d))
    return rec["state"][j] if d[j] <= TRACE_MATCH else None


def state_near(fits: dict, nodes: list[dict], x: float, y: float) -> str | None:
    """The state of the fitted map node nearest a point, within STATE_SETTLE_REACH (a City / Hall's own map node).

    Args:
        fits: fit_nodes' result.
        nodes: the check's map nodes.
        x: Point x, atlas units.
        y: Point y, atlas units.

    Returns:
        The state, or None when no fitted map node with a state is that close.
    """
    near = [
        (math.hypot(nodes[i]["x"] - x, nodes[i]["y"] - y), fit["state"])
        for i, fit in fits.items()
        if fit["state"] is not None
    ]
    d, state = min(near, default=(math.inf, None))
    return state if d < STATE_SETTLE_REACH else None


def state_stats(out_nodes: list[dict]) -> dict[str, int]:
    """The check's state counts over the kept map nodes (finalize and finalize_local's stats).

    Args:
        out_nodes: atlas.final["nodes"].

    Returns:
        {"maps_grey", "maps_blue", "maps_green", "maps_red": map nodes of each state, "state_errors": sightings
        whose state disagrees}.
    """
    kept = [n for n in out_nodes if n["status"] != "removed"]
    out = {f"maps_{s}": sum(n.get("state") == s for n in kept) for s in NODE_STATES}
    out["state_errors"] = sum(n.get("state_errors", 0) for n in kept)
    return out
