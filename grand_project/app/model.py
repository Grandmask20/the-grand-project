"""app.model: what the map shows of an atlas (the view model), built from the atlas file."""

from __future__ import annotations

import math

from grand_project import core

from .constants import EDIT_SAME, EDIT_SPOT, MAP_EDIT_REACH, MAP_ICON_REACH


def view_model(atlas: core.Atlas) -> dict:
    """Builds what the map shows: nodes / paths / landmarks / icons, the atlas-wide result when there is one.

    An atlas made before atlas_finalize existed has no atlas-wide result; its raw map nodes and paths are
    converted to the same shape (a map node seen in 2+ screenshots is "confirmed", else "single"). The
    user's map edits (maps deleted or added) and landmark edits are applied on top.

    Args:
        atlas: The open atlas.

    Returns:
        A dict with "nodes", "paths", "landmarks", "icons", "frames" (lists of dicts) and "stats" (dict).
    """
    j = atlas.to_json()
    fin = j.get("final")
    if fin:
        nodes, landmarks = fin["nodes"], fin["landmarks"]
        paths = [dict(p) for p in fin["paths"]]
    else:  # an atlas made before atlas_finalize existed
        nodes = [
            {
                "id": n["id"],
                "x": n["x"],
                "y": n["y"],
                "frames": sorted(set(n["frames"])),
                "seen": len(set(n["frames"])),
                "could": len(set(n["frames"])),
                "status": "confirmed" if len(set(n["frames"])) >= 2 else "single",
                "tower": n["tower"],
                "icons": [n["icon"]] if n.get("icon") else [],
                "abyss": "",
                "why": "",
                "origin": "detected",
            }
            for n in j["nodes"]
        ]
        paths = [
            {
                "a": e["a"],
                "b": e["b"],
                "frames": e["could"],
                "support": e["seen"],
                "abyss": False,
                "score": e["strength"],
            }
            for e in j["edges"]
        ]
        landmarks = [dict(lm, status="kept") for lm in j["landmarks"]]
    icons = fin["icons"] if fin and "icons" in fin else [i for i in j.get("icons", []) if i["name"] != "LostTower"]
    nodes, icons = apply_map_edits(nodes, icons, getattr(atlas, "map_edits", []))
    landmarks = apply_landmark_edits(landmarks, getattr(atlas, "landmark_edits", []))
    return {
        "nodes": nodes,
        "paths": paths,
        "landmarks": landmarks,
        "icons": icons,
        "frames": j["frames"],
        "stats": (fin or {}).get("stats", {}),
    }


def apply_map_edits(nodes: list[dict], icons: list[dict], edits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns the map nodes and icons with the maps the user deleted or added (user: ghost maps the detector made
    can't be removed otherwise, nor a map it missed added).

    A "remove" deletes the live map node nearest its spot within MAP_EDIT_REACH (status "removed", why "removed by
    you": shown with Layers > Removed), and the icons standing on it go with it (their base nearest it, within
    MAP_ICON_REACH). An "add" puts a map node on its spot, unless a live one is there already (found since). By spot,
    so they hold after the atlas is checked again.

    Args:
        nodes: Map node dicts; not changed.
        icons: Icon dicts ("x", "y", optional base "bx", "by"); not changed.
        edits: {"x", "y", "op": "remove" | "add"} (atlas units).

    Returns:
        (nodes, icons): new lists, an added map node at the end (its id its place).
    """
    if not edits:
        return nodes, icons
    out = list(nodes)
    gone: list[int] = []
    for e in (e for e in edits if e.get("op") == "remove"):
        near = [
            (math.hypot(n["x"] - e["x"], n["y"] - e["y"]), i) for i, n in enumerate(out) if n.get("status") != "removed"
        ]
        d, i = min(near) if near else (1e9, -1)
        if d < MAP_EDIT_REACH:
            out[i] = {**out[i], "status": "removed", "why": "removed by you"}
            gone.append(i)
    for e in (e for e in edits if e.get("op") == "add"):
        if any(
            n.get("status") != "removed" and math.hypot(n["x"] - e["x"], n["y"] - e["y"]) < MAP_EDIT_REACH for n in out
        ):
            continue
        out.append(
            {
                "id": len(out),
                "x": float(e["x"]),
                "y": float(e["y"]),
                "frames": [],
                "seen": 0,
                "could": 0,
                "status": "confirmed",
                "tower": False,
                "icons": [],
                "abyss": "",
                "why": "added by you",
                "origin": "by you",
            }
        )
    if gone:
        # an icon goes with a deleted map when that map is the nearest to its base (live ones count too). Only the
        # icons in reach of one are looked at further (an atlas has thousands of icons and maps)
        keep = []
        for ic in icons:
            bx, by = ic.get("bx", ic["x"]), ic.get("by", ic["y"])
            d = min(math.hypot(out[i]["x"] - bx, out[i]["y"] - by) for i in gone)
            if d > MAP_ICON_REACH or any(
                n.get("status") != "removed" and math.hypot(n["x"] - bx, n["y"] - by) < d for n in out
            ):
                keep.append(ic)
        icons = keep
    return out, icons


def apply_landmark_edits(landmarks: list[dict], edits: list[dict]) -> list[dict]:
    """Returns the landmarks with the user's changes: kind changed, deleted (kind ""), or added on a map.

    An edit made on a map ("on": "map") adds its own landmark there (unless one sits on that very spot,
    within EDIT_SPOT); an edit made on a landmark changes the nearest landmark within EDIT_SAME. Each
    landmark takes one edit, closest first, so a City set on a map next to a Tower never turns the Tower
    into a City.

    Args:
        landmarks: Landmark dicts ("kind", "x", "y", ... in atlas units); not changed.
        edits: The user's edits, dicts with "kind" ("" = delete), "x", "y" (atlas units) and optional "on".

    Returns:
        New landmark dicts: edited ones get status "kept" (or "removed: deleted by you") and source "you";
        added ones are appended.
    """
    out = [dict(lm) for lm in landmarks]
    taken: set = set()
    order = sorted(
        range(len(edits)),
        key=lambda k: min([math.hypot(lm["x"] - edits[k]["x"], lm["y"] - edits[k]["y"]) for lm in out] + [1e9]),
    )
    for k in order:
        e = edits[k]
        reach = EDIT_SPOT if e.get("on") == "map" else EDIT_SAME
        near = [(math.hypot(lm["x"] - e["x"], lm["y"] - e["y"]), i) for i, lm in enumerate(out) if i not in taken]
        d, i = min(near) if near else (1e9, -1)
        if d < reach:
            taken.add(i)
            lm = out[i]
            if e["kind"]:
                lm.update(kind=e["kind"], status="kept", beam="set by you", source="you")
            else:
                lm["status"] = "removed: deleted by you"
        elif e["kind"]:
            out.append(
                {
                    "kind": e["kind"],
                    "x": e["x"],
                    "y": e["y"],
                    "n": 1,
                    "could": 1,
                    "conf": 1.0,
                    "source": "you",
                    "status": "kept",
                    "beam": "set by you",
                    "added": True,
                }
            )
            taken.add(len(out) - 1)
    return out
