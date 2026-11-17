"""core.render (from atlas_builder_core.py)"""

from __future__ import annotations

import cv2
import numpy as np

from .atlas import Atlas


def render_overlay(atlas: Atlas, canvas: np.ndarray, origin) -> np.ndarray:
    """Draw the atlas's map nodes, paths and landmarks on a stitched image.

    Nodes are coloured by how many screenshots saw them; edges (paths) by how many agreed. When the
    atlas-wide result (atlas.final) exists, that is drawn instead (see _render_final).

    node ring: orange = 1 screenshot, green = 2, cyan = 3+.
    edge: cyan = every screenshot that could see it did; amber = only one screenshot could
    see it; red = some screenshots saw it and others (that could) did not -> review.

    Args:
        atlas: The atlas to draw.
        canvas: BGR stitched image (from Atlas.composite); not changed.
        origin: (x0, y0, scale) of the canvas: atlas point (x, y) is at canvas px ((x - x0) * scale, (y - y0) * scale).

    Returns:
        A BGR copy of the canvas with the overlay drawn on it.
    """
    x0, y0, sc = origin
    out = canvas.copy()

    def P(x, y):
        """Convert an atlas point to canvas px.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).

        Returns:
            (x, y) integer canvas px.
        """
        return (int((x - x0) * sc), int((y - y0) * sc))

    if atlas.final:
        return _render_final(atlas, out, P)
    j = atlas.to_json()
    for e in j["edges"]:
        a, b = j["nodes"][e["a"]], j["nodes"][e["b"]]
        if e["could"] < 2:
            col = (0, 200, 255)
        elif e["seen"] >= e["could"]:
            col = (255, 230, 0)
        else:
            col = (60, 60, 255)
        cv2.line(out, P(a["x"], a["y"]), P(b["x"], b["y"]), col, 2, cv2.LINE_AA)
    for n in j["nodes"]:
        k = len(set(n["frames"]))
        col = {1: (0, 150, 255), 2: (0, 255, 200)}.get(k, (255, 255, 0))
        cv2.circle(out, P(n["x"], n["y"]), 9, col, 2, cv2.LINE_AA)
    for lm in j["landmarks"]:
        p = P(lm["x"], lm["y"])
        cv2.rectangle(out, (p[0] - 30, p[1] - 60), (p[0] + 30, p[1] + 10), (70, 240, 100), 2)
        cv2.putText(out, lm["kind"], (p[0] - 28, p[1] - 64), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (70, 240, 100), 2)
    return out


def _render_final(atlas: Atlas, out: np.ndarray, P) -> np.ndarray:
    """Draw the atlas-wide result (atlas.final) on an image.

    paths cyan = 2+ screenshots agree, amber = one screenshot, magenta = abyss chain; nodes cyan =
    confirmed / from icon, orange = one screenshot, grey = doubtful; red x = removed (ghost / river glow).
    Icon names are written next to their map node; landmarks get a box (red when removed).

    Args:
        atlas: The atlas; its `final` dict holds nodes, paths and landmarks.
        out: BGR image to draw on (changed in place).
        P: Function (x, y) -> canvas px for atlas points.

    Returns:
        The same image `out`, drawn on.
    """
    fin = atlas.final
    N = fin["nodes"]
    for e in fin["paths"]:
        a, b = N[e["a"]], N[e["b"]]
        strong = e.get("seen_in", e["frames"]) >= 2 or e.get("both_ends")
        col = (230, 80, 255) if e["abyss"] else (255, 220, 40) if strong else (0, 185, 255)
        line = e.get("line") or [[a["x"], a["y"]], [b["x"], b["y"]]]
        cv2.polylines(out, [np.array([P(x, y) for x, y in line], np.int32)], False, col, 2, cv2.LINE_AA)
    for n in N:
        p = P(n["x"], n["y"])
        st = n["status"]
        if st == "removed":
            if not n["why"].startswith("joined"):
                cv2.drawMarker(out, p, (60, 60, 255), cv2.MARKER_TILTED_CROSS, 12, 2)
            continue
        col = {
            "confirmed": (255, 220, 40),
            "icon": (255, 220, 40),
            "single": (0, 150, 255),
            "disputed": (0, 150, 255),
            "doubtful": (150, 150, 150),
        }.get(st, (255, 255, 255))
        cv2.circle(out, p, 8, col, 2, cv2.LINE_AA)
        if n["icons"]:
            txt = "+".join(sorted(set(n["icons"])))
            cv2.putText(out, txt, (p[0] + 9, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, txt, (p[0] + 9, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (230, 140, 255), 1, cv2.LINE_AA)
    for lm in fin["landmarks"]:
        p = P(lm["x"], lm["y"])
        col = (60, 60, 255) if lm["status"].startswith("removed") else (70, 240, 100)
        cv2.rectangle(out, (p[0] - 30, p[1] - 60), (p[0] + 30, p[1] + 10), col, 2)
        cv2.putText(out, lm["kind"], (p[0] - 28, p[1] - 64), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    return out
