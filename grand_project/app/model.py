"""app.model: what the map shows of an atlas (the view model), built from the atlas file."""

from __future__ import annotations

import math

from grand_project import core

from .constants import EDIT_SAME, EDIT_SPOT


def view_model(atlas: core.Atlas) -> dict:
    """Builds what the map shows: nodes / paths / landmarks / icons, the atlas-wide result when there is one.

    An atlas made before atlas_finalize existed has no atlas-wide result; its raw map nodes and paths are
    converted to the same shape (a map node seen in 2+ screenshots is "confirmed", else "single"). The
    user's landmark edits are applied on top.

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
    landmarks = apply_landmark_edits(landmarks, getattr(atlas, "landmark_edits", []))
    return {
        "nodes": nodes,
        "paths": paths,
        "landmarks": landmarks,
        "icons": icons,
        "frames": j["frames"],
        "stats": (fin or {}).get("stats", {}),
    }


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
                }
            )
            taken.add(len(out) - 1)
    return out
