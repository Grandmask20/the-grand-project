"""finalize.states: each map node's state and icons over time.

A map node is grey (unreachable), blue (can be pathed to), green (cleared) or red (failed: cities and halls only),
and running maps changes that over time. The check keeps a map's state and icons from its newest sightings (by
when each screenshot was taken, ``core.capture_time``) as long as the change from the older ones is allowed (user's
rules):

- grey -> blue -> green, blue -> red (only where a City / Hall stands or on a STATE_RED_ICONS map: the Deadly Map
  Boss, a Unique map); green and red never change again;
- while a map is grey or blue its icons may be lost or gained (icons move to a neighbour when their map is run);
- a blue map that turns green loses every icon; one that turns red may lose icons, never gain one.

Anything else between two screenshots of one spot is a detection error: the fit is the allowed story that the
fewest sightings disagree with (each disagreeing sighting costs 1, a change STATE_CHANGE_COST), and the sightings
that still disagree are counted as errors.

Screenshots taken in the same second are one look. Two screenshots a minute apart can differ (one map run between
them), and some taken minutes apart cannot, so every sighting counts on its own: no time gap is a session.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from grand_project import core, icon_refs
from grand_project.detect.constants import ICON_CLEAR, ICON_NOT_A_CLASS, NODE_STATES, ROW_DY, ROW_STEP

from .constants import (
    STATE_AFTER,
    STATE_CHANGE_COST,
    STATE_ICON_CHANGE_COST,
    STATE_ICON_GONE_DIST,
    STATE_ICON_MISS_COST,
    STATE_ICON_ROW,
    STATE_ICON_THERE_DIST,
    STATE_LOG_MAX,
    STATE_OPEN,
    STATE_RED_ICONS,
    STATE_SETTLE_REACH,
    TRACE_MATCH,
)
from .traces import _saved, _visible


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


def fit_presence(obs: list[bool | None], path: list[str | None]) -> list[bool]:
    """Whether one icon is on its map at each look, under the state rules.

    Args:
        obs: Per look: True (found), False (its map and its spot seen, no such icon) or None (no say).
        path: The map's state at each look (fit_path), or None where nothing names it (treated as grey / blue).

    Returns:
        The icon's presence at each look: the allowed story the fewest sightings disagree with (a missed icon costs
        STATE_ICON_MISS_COST, a wrongly found one 1, a loss or gain STATE_ICON_CHANGE_COST).
    """
    if not obs:
        return []

    def cost(k: int, on: bool) -> float:
        if obs[k] is None or obs[k] == on:
            return 0.0
        return STATE_ICON_MISS_COST if on else 1.0

    def moves(k: int) -> dict[tuple[bool, bool], float]:
        """(before, after) -> cost of going from look k - 1 to look k."""
        before, now = path[k - 1], path[k]
        if before not in (None, *STATE_OPEN):  # green or red: nothing changes any more
            return {(False, False): 0.0, (True, True): 0.0}
        if now == "green":  # a map that turns green loses every icon
            return {(False, False): 0.0, (True, False): 0.0}
        step = {(False, False): 0.0, (True, True): 0.0, (True, False): STATE_ICON_CHANGE_COST}
        if now != "red":  # a failed map never gains an icon
            step[(False, True)] = STATE_ICON_CHANGE_COST
        return step

    best = [{on: cost(0, on) for on in (False, True)}]
    back: list[dict[bool, bool]] = [{}]
    for k in range(1, len(obs)):
        row: dict[bool, float] = {}
        came: dict[bool, bool] = {}
        for (a, b), c in moves(k).items():
            if a not in best[k - 1]:  # e.g. an icon on a map that turned green earlier
                continue
            total = best[k - 1][a] + c
            if b not in row or total < row[b] or (total == row[b] and a == b):
                row[b], came[b] = total, a
        best.append({b: row[b] + cost(k, b) for b in row})
        back.append(came)
    newest = obs[-1] if obs[-1] is not None else True  # a tie keeps the icon unless the newest look lacks it
    end = min(best[-1], key=lambda on: (best[-1][on], on != newest))
    out = [end]
    for k in range(len(obs) - 1, 0, -1):
        out.append(back[k][out[-1]])
    out.reverse()
    return out


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
    """Fit every kept map node's state and icons over time.

    A map's sightings are the screenshots that found it (not those that only guessed it under an icon row) and
    those that found one of its icons; in each, its state is that of the screenshot's own map node at that spot
    (the saved detection, within TRACE_MATCH). Where the map was found but one of its icons was not, the
    screenshot itself is looked at (``_icon_checks``): the icon finder misses many icons, so only a spot that is
    clearly not that icon counts as the icon being gone.

    Args:
        atlas: the core.Atlas (frames, landmarks, saved detections, screenshots).
        maps_by: screenshot name -> (frame dict, atlas-to-screen homography).
        nodes: the check's map nodes (x, y, frames, guessed, icons: indices into icons).
        status: each node's status so far ("removed" ones are skipped).
        icons: the merged icons (name, x, y, frames).
        log: callable taking one message string, or None.

    Returns:
        Node index -> {"state" (None when no sighting names it), "seen" (when the newest look was taken, epoch
        seconds, or None), "sightings", "errors" (sightings whose state disagrees), "icon_errors", "lost" (names of
        icons it lost)}.
    """
    looks = _looks(atlas)
    places = [(lm["x"], lm["y"]) for lm in atlas.landmarks if lm["kind"] in ("City", "Hall")]
    maps = {}  # node index -> (frames that found it, {icon name: frames that found it}, {frame: its map there})
    for i, nd in enumerate(nodes):
        if status[i] == "removed":
            continue
        found = {f for f in nd["frames"] - nd["guessed"] if f in maps_by}
        with_icon: dict[str, set] = {}
        for k in nd["icons"]:
            with_icon.setdefault(icons[k]["name"], set()).update(f for f in icons[k]["frames"] if f in maps_by)
        if found or with_icon:
            maps[i] = (found, with_icon, {f: _map_at_spot(atlas, *maps_by[f], nd) for f in found})
    present = _icon_checks(atlas, maps_by, maps)
    fits: dict[int, dict] = {}
    noisy = []
    for i, (found, with_icon, at_spot) in maps.items():
        nd = nodes[i]
        by_look: dict = {}
        for name in found | {f for fs in with_icon.values() for f in fs}:
            look = by_look.setdefault(looks[name][0], {"rank": looks[name][1], "t": looks[name][2], "states": []})
            look["rank"] = min(look["rank"], looks[name][1])
            spot = at_spot.get(name)
            if spot is not None and spot["state"] is not None:
                look["states"].append(spot["state"])
            for icon, fs in with_icon.items():
                seen = True if name in fs else present.get((i, icon, name))
                if seen is not None:
                    look.setdefault("icons", {})[icon] = look.get("icons", {}).get(icon) or seen
        ordered = sorted(by_look.values(), key=lambda lk: lk["rank"])
        named = [k for k, lk in enumerate(ordered) if lk["states"]]
        red_ok = bool(STATE_RED_ICONS & set(with_icon)) or any(
            math.hypot(x - nd["x"], y - nd["y"]) < STATE_SETTLE_REACH for x, y in places
        )
        picked, errors = fit_path([ordered[k]["states"] for k in named], red_ok)
        # each look takes the state of the newest named look at or before it (the first one's before it)
        path: list[str | None] = []
        for k in range(len(ordered)):
            before = [j for j, n in enumerate(named) if n <= k]
            path.append(picked[before[-1]] if before else (picked[0] if picked else None))
        lost, icon_errors = [], 0
        for icon in with_icon:
            obs = [lk.get("icons", {}).get(icon) for lk in ordered]
            on = fit_presence(obs, path)
            icon_errors += sum(1 for o, p in zip(obs, on, strict=True) if o is not None and o != p)
            if not on[-1]:
                lost.append(icon)
        fits[i] = {
            "state": path[-1] if path else None,
            "seen": ordered[named[-1]]["t"] if named else None,
            "sightings": sum(len(lk["states"]) for lk in ordered),
            "errors": int(errors),
            "icon_errors": icon_errors,
            "lost": sorted(lost),
        }
        if errors or icon_errors:
            noisy.append((i, nd, picked, fits[i]))
    if log and noisy:
        for i, nd, picked, fit in noisy[:STATE_LOG_MAX]:
            story = " -> ".join(s for k, s in enumerate(picked) if k == 0 or s != picked[k - 1])
            log(
                f"map #{i} at ({nd['x']:.0f}, {nd['y']:.0f}): {fit['errors']} of {fit['sightings']} sightings disagree "
                f"with {story or 'no state'}, {fit['icon_errors']} icon sightings disagree (detection errors)"
            )
        if len(noisy) > STATE_LOG_MAX:
            log(f"... and {len(noisy) - STATE_LOG_MAX} more map nodes whose sightings disagree")
    return fits


def _map_at_spot(atlas, f: dict, Hi: np.ndarray, nd: dict) -> dict | None:
    """The screenshot's own (not hidden) map node at the map's spot: {"x", "y" (screen px), "state", "icons"
    (the icons it found: name, x, y)}, or None when it has none there (within TRACE_MATCH)."""
    rec = _saved(atlas, f)
    if rec is None or not len(rec["P"]):
        return None
    sp = core.persp(Hi, [[nd["x"], nd["y"]]])[0]
    d = np.hypot(rec["P"][:, 0] - sp[0], rec["P"][:, 1] - sp[1])
    d[rec["hidden"]] = np.inf
    j = int(np.argmin(d))
    if d[j] > TRACE_MATCH:
        return None
    return {"x": float(rec["P"][j, 0]), "y": float(rec["P"][j, 1]), "state": rec["state"][j], "icons": rec["icons"]}


def _icon_checks(atlas, maps_by: dict, maps: dict) -> dict:
    """Look at the screenshots where a map was found but one of its icons was not: is the icon there after all?

    Icons are drawn at a fixed screen offset from their map (the row above it), so the icon's spot in such a
    screenshot is the map found there plus the icon's offset, measured in the screenshots that found both. A row
    is centred on its map, so when another icon leaves it the others move by half a step: every row place is
    tried (STATE_ICON_ROW). The nearest of the icon's own pictures decides (icon_refs.shift_dists): within
    STATE_ICON_THERE_DIST it is there, from STATE_ICON_GONE_DIST on (everywhere along the row) it is gone, between:
    no say (any other icon in its gold rim looks a little like it, so "there" must be close).

    Args:
        atlas: the core.Atlas (screenshots).
        maps_by: screenshot name -> (frame dict, atlas-to-screen homography).
        maps: node index -> (frames that found it, {icon name: frames that found it}, {frame: _map_at_spot}).

    Returns:
        (node index, icon name, screenshot name) -> True (there) / False (gone); missing = no say.
    """
    pictures = _icon_pictures()
    todo: dict[str, list] = {}  # screenshot -> [(node, icon, x, y)]: where to look
    for i, (found, with_icon, at_spot) in maps.items():
        for icon, fs in with_icon.items():
            if icon not in pictures:
                continue
            offsets = []
            for name in found & fs:
                spot = at_spot[name]
                if spot is not None:
                    near = [(x - spot["x"], y - spot["y"]) for nm, x, y in spot["icons"] if nm == icon]
                    near = [o for o in near if abs(o[0]) <= 2 * ROW_STEP and -2 * ROW_DY <= o[1] <= 0]
                    if near:
                        offsets.append(min(near, key=lambda o: abs(o[0])))
            if not offsets:
                continue
            dx, dy = np.median(np.array(offsets), axis=0)
            for name in found - fs:
                spot = at_spot[name]
                if spot is not None:
                    todo.setdefault(name, []).append((i, icon, spot["x"] + dx, spot["y"] + dy))
    out = {}
    for name, checks in todo.items():
        f, _Hi = maps_by[name]
        img = atlas.image(f["path"]) if Path(f["path"]).exists() else None
        if img is None:
            continue
        for i, icon, x, y in checks:
            d = 9.0
            for step in sorted(STATE_ICON_ROW, key=abs):  # its own place first, then the others along the row
                px = x + step * ROW_STEP / 2
                if not _visible(f, np.eye(3), [[px, y]], margin=ICON_CLEAR)[1][0]:
                    continue
                hit = icon_refs.shift_dists(img, px, y, pictures[icon])
                if hit is not None:
                    d = min(d, float(hit[0].min()))
                if d <= STATE_ICON_THERE_DIST:
                    break
            if d <= STATE_ICON_THERE_DIST:
                out[(i, icon, name)] = True
            elif STATE_ICON_GONE_DIST <= d < 9.0:
                out[(i, icon, name)] = False
    return out


def _icon_pictures() -> dict[str, np.ndarray]:
    """Every icon name's pictures (the stored ones and the icon model's, as the namer has them): name -> (k, d)."""
    from grand_project.detect.badges import naming_book  # here: detect imports finalize (its biome guess)

    book = naming_book()
    refs = icon_refs.refs()
    rows: dict[str, list] = {}
    for names, F in ((refs.names, refs.F), (book["names"], book["F"])):
        for name, row in zip(names, F, strict=True):
            rows.setdefault(name, []).append(row)
    return {name: np.array(v, np.float32) for name, v in rows.items() if name not in ICON_NOT_A_CLASS}


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
        whose state disagrees, "icons_lost": icons lost by kept maps}.
    """
    kept = [n for n in out_nodes if n["status"] != "removed"]
    out = {f"maps_{s}": sum(n.get("state") == s for n in kept) for s in NODE_STATES}
    out["state_errors"] = sum(n.get("state_errors", 0) for n in kept)
    out["icons_lost"] = sum(len(n.get("icons_lost", [])) for n in kept)
    return out
