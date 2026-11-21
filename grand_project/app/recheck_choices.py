"""app.recheck_choices: what a Re-check changed, in groups, and the atlas-wide result made of the groups you take.

A Re-check makes a new atlas-wide result (atlas.final) next to the old one. Before it is used, the page lists what
changed per group (maps, paths, landmarks, towers, biomes, icons), each change named and placed; you tick the groups
to update. An unticked group stays as it was before, linked to the map it was on (user: "things that aren't ticked
don't get updated from recheck and just use the pre-checked choices linked to each map it was on beforehand").

Maps are matched old to new by position (one to one, nearest first, within RECHECK_MATCH). Everything else is tied
to maps: paths by their two maps, a map's icons and tower flag by the map, landmarks and icons placed on the map's
spot, moved with it. Biomes are worked out from the rest (cities.biomes), so a biome kept as it was is stored
apart: the maps whose biome would change keep theirs in atlas.biome_kept (applied like the biomes drawn by hand,
below them), until a Re-check that updates biomes.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from . import constants as K

GROUPS = K.RECHECK_GROUPS
GROUP_NAMES = K.RECHECK_GROUP_NAMES


def _alive(nodes: list[dict]) -> list[int]:
    return [i for i, n in enumerate(nodes) if n.get("status") != "removed"]


def _alive_lm(lms: list[dict]) -> list[int]:
    return [i for i, lm in enumerate(lms) if not str(lm.get("status", "")).startswith("removed")]


def _pairs(a: np.ndarray, b: np.ndarray, reach: float) -> list[tuple[int, int, float]]:
    """One-to-one pairs of points of a and b, nearest first, within reach.

    Returns:
        [(index in a, index in b, distance)].
    """
    if not len(a) or not len(b):
        return []
    tb = cKDTree(b)
    cand = []
    for i, near in enumerate(tb.query_ball_point(a, reach)):
        for j in near:
            cand.append((float(math.hypot(*(a[i] - b[j]))), i, j))
    cand.sort()
    used_a, used_b, out = set(), set(), []
    for d, i, j in cand:
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            out.append((i, j, d))
    return out


def _xy(items: list[dict], idx: list[int], kx: str = "x", ky: str = "y") -> np.ndarray:
    return np.array([[items[i][kx], items[i][ky]] for i in idx], float).reshape(-1, 2)


def match_maps(old: dict, new: dict) -> dict[int, int]:
    """Pair the old result's maps with the new one's (removed maps left out).

    Args:
        old: The old atlas.final.
        new: The new atlas.final.

    Returns:
        {old node index: new node index}.
    """
    ia, ib = _alive(old["nodes"]), _alive(new["nodes"])
    return {ia[i]: ib[j] for i, j, _d in _pairs(_xy(old["nodes"], ia), _xy(new["nodes"], ib), K.RECHECK_MATCH)}


def _item(text: str, x: float, y: float, kind: str = "change") -> dict:
    """One change: its text, its spot, and whether something was "added", "removed" or changed ("change")."""
    return {"text": text, "x": round(float(x), 1), "y": round(float(y), 1), "kind": kind}


def _path_key(p: dict) -> tuple[int, int]:
    return (min(p["a"], p["b"]), max(p["a"], p["b"]))


def _mid(nodes: list[dict], p: dict) -> tuple[float, float]:
    a, b = nodes[p["a"]], nodes[p["b"]]
    return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2


def _lm_name(lm: dict) -> str:
    return str(lm.get("kind") or "Landmark")


def _landmark_changes(old: list[dict], new: list[dict], towers: bool) -> list[dict]:
    """Landmarks (or towers) added, removed or changed kind."""

    def pick(lms):
        return [i for i in _alive_lm(lms) if (lms[i].get("kind") == "Tower") == towers]

    ia, ib = pick(old), pick(new)
    pairs = _pairs(_xy(old, ia), _xy(new, ib), K.RECHECK_LANDMARK_MATCH)
    out = []
    for i, j, _d in pairs:
        a, b = old[ia[i]], new[ib[j]]
        if a.get("kind") != b.get("kind"):
            out.append(_item(f"{_lm_name(a)} → {_lm_name(b)}", b["x"], b["y"]))
    got_a, got_b = {i for i, _j, _d in pairs}, {j for _i, j, _d in pairs}
    out += [
        _item(f"{_lm_name(old[ia[i]])} removed", old[ia[i]]["x"], old[ia[i]]["y"], "removed")
        for i in range(len(ia))
        if i not in got_a
    ]
    out += [
        _item(f"{_lm_name(new[ib[j]])} added", new[ib[j]]["x"], new[ib[j]]["y"], "added")
        for j in range(len(ib))
        if j not in got_b
    ]
    return out


def _icon_pairs(old: list[dict], new: list[dict]) -> list[tuple[int, int, float]]:
    """One-to-one pairs of old and new icons of the same name, by their base spot."""
    out = []
    for name in {ic["name"] for ic in old} & {ic["name"] for ic in new}:
        ia = [i for i, ic in enumerate(old) if ic["name"] == name]
        ib = [j for j, ic in enumerate(new) if ic["name"] == name]
        out += [
            (ia[i], ib[j], d)
            for i, j, d in _pairs(_xy(old, ia, "bx", "by"), _xy(new, ib, "bx", "by"), K.RECHECK_ICON_MATCH)
        ]
    return out


def changes(
    old: dict, new: dict, old_biomes: dict[int, str | None], new_biomes: dict[int, str | None], icon_label=None
) -> dict:
    """What a Re-check changed, per group, each change named and placed.

    Args:
        old: The atlas-wide result before (atlas.final).
        new: The Re-check's result.
        old_biomes: Old map node index -> its biome (None: none).
        new_biomes: New map node index -> its biome.
        icon_label: Function naming an icon dict (None: its raw name).

    Returns:
        {group: {"count", "added", "removed", "changed", "items": [{"text", "x", "y", "kind"}] (at most
        RECHECK_ITEMS_SHOWN)}}, every group of GROUPS.
    """
    label = icon_label or (lambda ic: ic["name"])
    m = match_maps(old, new)
    back = {j: i for i, j in m.items()}
    on, nn = old["nodes"], new["nodes"]
    out: dict[str, list[dict]] = {g: [] for g in K.RECHECK_GROUPS}

    for i in _alive(on):
        if i not in m:
            out["maps"].append(_item(f"Map #{i} removed", on[i]["x"], on[i]["y"], "removed"))
        else:
            b = nn[m[i]]
            d = math.hypot(b["x"] - on[i]["x"], b["y"] - on[i]["y"])
            if d > K.RECHECK_MOVED:
                out["maps"].append(_item(f"Map #{i} moved {d:.0f} units", b["x"], b["y"]))
    out["maps"] += [_item("New map", nn[j]["x"], nn[j]["y"], "added") for j in _alive(nn) if j not in back]

    # paths, by their two maps (a path to a map that came or went is listed with the maps too)
    # (a path kept to a map the check removed isn't drawn: left out on both sides, or it read as gone and new)
    alive_o, alive_n = set(_alive(on)), set(_alive(nn))
    old_keys = {_path_key(p): p for p in old["paths"] if p["a"] in alive_o and p["b"] in alive_o}
    new_keys = {_path_key(p): p for p in new["paths"] if p["a"] in alive_n and p["b"] in alive_n}
    in_new = {(min(m[a], m[b]), max(m[a], m[b])) for a, b in old_keys if a in m and b in m}
    for (a, b), p in old_keys.items():
        if not (a in m and b in m and (min(m[a], m[b]), max(m[a], m[b])) in new_keys):
            out["paths"].append(_item(f"Path #{a} – #{b} removed", *_mid(on, p), "removed"))
    for k, p in new_keys.items():
        if k not in in_new:
            a, b = back.get(p["a"]), back.get(p["b"])
            name = f"#{a}" if a is not None else "a new map"
            other = f"#{b}" if b is not None else "a new map"
            out["paths"].append(_item(f"Path {name} – {other} added", *_mid(nn, p), "added"))

    old_lm, new_lm = old.get("landmarks", []), new.get("landmarks", [])
    out["landmarks"] = _landmark_changes(old_lm, new_lm, towers=False)
    out["towers"] = _landmark_changes(old_lm, new_lm, towers=True)
    for i, j in m.items():  # a map seen as a tower's base, or no more
        if bool(on[i].get("tower")) != bool(nn[j].get("tower")):
            what = "now a tower's map" if nn[j].get("tower") else "no longer a tower's map"
            out["towers"].append(
                _item(f"Map #{i} {what}", nn[j]["x"], nn[j]["y"], "added" if nn[j].get("tower") else "removed")
            )

    for i, j in sorted(m.items()):
        a, b = old_biomes.get(i), new_biomes.get(j)
        if a != b:
            kind = "added" if not a else ("removed" if not b else "change")  # (a biome gained / lost / another)
            out["biomes"].append(
                _item(f"Map #{i}: {a or 'no biome'} → {b or 'no biome'}", nn[j]["x"], nn[j]["y"], kind)
            )

    oi, ni = old.get("icons", []), new.get("icons", [])
    pairs = _icon_pairs(oi, ni)
    got_a, got_b = {i for i, _j, _d in pairs}, {j for _i, j, _d in pairs}
    out["icons"] = [
        _item(f"{label(oi[i])} removed", oi[i]["x"], oi[i]["y"], "removed") for i in range(len(oi)) if i not in got_a
    ]
    out["icons"] += [
        _item(f"{label(ni[j])} added", ni[j]["x"], ni[j]["y"], "added") for j in range(len(ni)) if j not in got_b
    ]
    return {
        g: {
            "count": len(v),
            "added": sum(1 for it in v if it["kind"] == "added"),
            "removed": sum(1 for it in v if it["kind"] == "removed"),
            "changed": sum(1 for it in v if it["kind"] == "change"),
            "items": v[: K.RECHECK_ITEMS_SHOWN],
        }
        for g, v in out.items()
    }


def _nearest_map(nodes: list[dict], alive: list[int], tree, x: float, y: float, reach: float) -> int | None:
    if tree is None:
        return None
    d, k = tree.query([x, y], distance_upper_bound=reach)
    return alive[int(k)] if np.isfinite(d) else None


def _tree(nodes: list[dict], alive: list[int]):
    return cKDTree(_xy(nodes, alive)) if alive else None


def _moved(item: dict, dx: float, dy: float, keys=(("x", "y"),)) -> dict:
    out = dict(item)
    for kx, ky in keys:
        if kx in out:
            out[kx] = round(out[kx] + dx, 2)
            out[ky] = round(out[ky] + dy, 2)
    return out


def merge(old: dict, new: dict, update: set[str]) -> dict:
    """The atlas-wide result with the ticked groups from the Re-check and the rest as before.

    The maps come from one side (new when "maps" is ticked); everything kept from the other side is carried over by
    its map: a path needs both its maps, a landmark / icon on a map moves with it (one that was on a map now gone is
    dropped; a landmark on no map stays where it was). Biomes aren't part of the result (see the module docstring).

    Args:
        old: The atlas-wide result before.
        new: The Re-check's result.
        update: The groups to take from the Re-check.

    Returns:
        A new atlas-wide result (old and new aren't changed).
    """
    m = match_maps(old, new)
    take_maps = "maps" in update
    base, other = (new, old) if take_maps else (old, new)
    to_base = m if take_maps else {j: i for i, j in m.items()}  # other's node index -> base's
    from_base = {b: o for o, b in to_base.items()}
    nodes = [dict(n) for n in base["nodes"]]
    on = other["nodes"]

    def side(group: str) -> str:
        """Where a group comes from: "base" (the maps' own side) or "other"."""
        return "base" if (group in update) == take_maps else "other"

    # what a map carries: its icons (icons), tower flag (towers), abyss chain (paths)
    for group, keys in (("icons", ("icons",)), ("towers", ("tower",)), ("paths", ("abyss",))):
        if side(group) == "other":
            for i, n in enumerate(nodes):
                o = from_base.get(i)
                for k in keys:
                    if o is not None and k in on[o]:
                        n[k] = on[o][k]
                    elif k in n:
                        n[k] = [] if k == "icons" else (False if k == "tower" else "")

    if side("paths") == "base":
        paths = [dict(p) for p in base["paths"]]
    else:
        paths = []
        for p in other["paths"]:
            a, b = to_base.get(p["a"]), to_base.get(p["b"])
            if a is not None and b is not None:
                paths.append({**p, "a": a, "b": b})

    # the other side's things placed by their map: (its index in base, how far it moved)
    alive_o = _alive(on)
    tree_o = _tree(on, alive_o)

    def carried(x: float, y: float, reach: float) -> tuple[bool, float, float]:
        """Whether a thing of the other side at x, y may stay (False: its map is gone), and its shift."""
        o = _nearest_map(on, alive_o, tree_o, x, y, reach)
        if o is None:
            return True, 0.0, 0.0  # on no map: as it was
        b = to_base.get(o)
        if b is None:
            return False, 0.0, 0.0
        return True, nodes[b]["x"] - on[o]["x"], nodes[b]["y"] - on[o]["y"]

    def kept_landmarks(src: dict, which) -> list[dict]:
        """src's landmarks that which() takes (by whether each is a tower), in their order."""
        out = []
        for lm in src.get("landmarks", []):
            if not which(lm.get("kind") == "Tower"):
                continue
            if src is base:
                out.append(dict(lm))
                continue
            ok, dx, dy = carried(lm["x"], lm["y"], K.RECHECK_LANDMARK_ON_MAP)
            if ok:
                out.append(_moved(lm, dx, dy))
        return out

    # (in their order: of one side, both groups together; of two, the maps' side's group first)
    sides = {side("towers"), side("landmarks")}
    landmarks = kept_landmarks(base, lambda t: (side("towers") if t else side("landmarks")) == "base")
    if "other" in sides:
        landmarks += kept_landmarks(other, lambda t: (side("towers") if t else side("landmarks")) == "other")

    if side("icons") == "base":
        icons = [dict(ic) for ic in base.get("icons", [])]
    else:
        icons = []
        for ic in other.get("icons", []):
            ok, dx, dy = carried(ic.get("bx", ic["x"]), ic.get("by", ic["y"]), K.RECHECK_ICON_ON_MAP)
            if ok:
                icons.append(_moved(ic, dx, dy, (("x", "y"), ("bx", "by"))))

    stats = dict(new.get("stats", {}))
    stats["recheck_kept"] = sorted(set(K.RECHECK_GROUPS) - set(update))
    return {"nodes": nodes, "paths": paths, "landmarks": landmarks, "icons": icons, "stats": stats}


def biome_labels(potential: dict) -> dict[int, str | None]:
    """Map node index -> its biome, from cities.biomes' "potential"."""
    return {int(i): lab for i, (lab, _st) in potential.items()}


def kept_biomes(merged: dict, old: dict, merged_biomes: dict, old_biomes: dict, already: list[dict]) -> list[dict]:
    """The biomes kept as they were: for each map of the merged result whose biome isn't the one it had before,
    its old biome at its spot (on top of the ones kept by an earlier Re-check, which a new one at the same spot
    replaces).

    Args:
        merged: The merged result (merge).
        old: The result before.
        merged_biomes: Merged node index -> biome (worked out with the earlier kept ones).
        old_biomes: Old node index -> biome.
        already: atlas.biome_kept so far.

    Returns:
        The new atlas.biome_kept: [{"x", "y", "biome" ("" = none)}].
    """
    m = match_maps(old, merged)
    out = [dict(k) for k in already]
    add = []
    for i, j in m.items():
        a, b = old_biomes.get(i), merged_biomes.get(j)
        if a != b:
            n = merged["nodes"][j]
            add.append({"x": round(n["x"], 2), "y": round(n["y"], 2), "biome": a or ""})
    if add and out:
        t = cKDTree(np.array([[k["x"], k["y"]] for k in add], float))
        out = [k for k in out if not t.query_ball_point([k["x"], k["y"]], K.RECHECK_MATCH)]
    return out + add
