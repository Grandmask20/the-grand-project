"""Map node states: grey (unreachable), blue (can be pathed to), green (cleared), red (failed: cities and halls only).

Named the way icons are named (finding vs naming): RF-DETR or the classical map finder finds and places the map
node, then the nearest stored picture of the node's middle gives its state (``icon_refs.shift_dists``, the icon
namer's pattern match over +-3 px), and only a state whose pictures glow in the same colour may be taken (the
brightest quarter's Lab a/b, ``icon_refs.bright_colour``, and how much of the middle glows blue, green or red,
``glow_shares``). New pictures never change what is found.

The pictures are plain arrays in ``NODE_STATES_FILE`` (``tools/node_state_sheet.py freeze`` makes them from
hand-checked ``states.json`` files); without them every state is unsure (None).
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import cv2
import numpy as np

from grand_project import fileio, icon_refs

from . import constants as K

_loaded: tuple[tuple, dict] | None = None  # ((path, size, modified time), pictures), reloaded when the file changes


def _empty() -> dict:
    """No pictures: every state is unsure."""
    return {
        "F": np.zeros((0, int(icon_refs._MASK.sum()) * 3), np.float32),
        "states": [],
        "colours": {},
        "glows": {},
        "stamp": "-",
    }


def glow_shares(crop: np.ndarray) -> np.ndarray:
    """How much of a map node's middle glows in each glow colour (NODE_STATE_GLOW_BANDS order).

    Args:
        crop: Square BGR crop centred on the map node (icon_refs.crop).

    Returns:
        (len(NODE_STATE_GLOW_BANDS),) float array: the share of the pixels within NODE_STATE_GLOW_R px of the
        middle in each band.
    """
    size = crop.shape[0]
    yy, xx = np.mgrid[:size, :size]
    near = np.hypot(xx - size / 2 + 0.5, yy - size / 2 + 0.5) <= K.NODE_STATE_GLOW_R
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[near].astype(int)
    H, S, V = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    return np.array(
        [
            float((np.any([(lo <= H) & (hi >= H) for lo, hi in hues], axis=0) & (s_min <= S) & (v_min <= V)).mean())
            for hues, s_min, v_min in K.NODE_STATE_GLOW_BANDS.values()
        ]
    )


def state_pictures() -> dict:
    """The state pictures, loaded once and again whenever the file changes (a new freeze).

    Returns:
        {"F": (n, d) picture features (icon_refs.feature), "states": state of each row, "colours": state -> (k, 2)
        bright-part colours of its pictures, "glows": state -> (k, len(NODE_STATE_GLOW_BANDS)) glow shares of its
        pictures (glow_shares), "stamp": states_stamp()}; no rows when there is no file.
    """
    global _loaded
    path = Path(K.NODE_STATES_FILE)
    try:
        st = path.stat()
    except OSError:
        return _empty()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if _loaded is None or _loaded[0] != key:
        data = path.read_bytes()
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            crops, states = z["crops"], [str(s) for s in z["states"]]
        cols: dict[str, list] = {}
        glows: dict[str, list] = {}
        for c, s in zip(crops, states, strict=True):
            cols.setdefault(s, []).append(icon_refs.bright_colour(c))
            glows.setdefault(s, []).append(glow_shares(c))
        book = _empty()
        if len(crops):
            book["F"] = np.array([icon_refs.feature(c) for c in crops], np.float32)
        book.update(
            states=states,
            colours={s: np.array(v, np.float32) for s, v in cols.items()},
            glows={s: np.array(v, np.float32) for s, v in glows.items()},
            stamp=hashlib.sha1(data).hexdigest(),
        )
        _loaded = (key, book)
    return _loaded[1]


def states_stamp() -> str:
    """Which pictures named the states (a hash of the file, "-" without one): saved with each screenshot's detection,
    so states named with other pictures are named again (finalize.traces) without finding everything again."""
    return state_pictures()["stamp"]


def name_state(img: np.ndarray, x: float, y: float, book: dict | None = None) -> tuple[str | None, float]:
    """Name one map node's state by its nearest picture of the same glow colour.

    Args:
        img: BGR screenshot (1080p).
        x: The map node's middle x, screen px.
        y: The map node's middle y, screen px.
        book: state_pictures(); None loads them.

    Returns:
        (state, 1 - correlation): state None when unsure (no pictures, off the screenshot, no picture of a fitting
        colour, or the nearest one further than NODE_STATE_MAX_DIST; distance 9.0 when nothing was compared).
    """
    book = book if book is not None else state_pictures()
    found = icon_refs.shift_dists(img, x, y, book["F"]) if book["states"] else None
    if found is None:
        return None, 9.0
    d, c = found
    col, glow = icon_refs.bright_colour(c), glow_shares(c)
    near = {
        s: bool(np.linalg.norm(P - col, axis=1).min() <= K.NODE_STATE_COLOUR_TOL)
        and bool(np.abs(book["glows"][s] - glow).max(axis=1).min() <= K.NODE_STATE_GLOW_TOL)
        for s, P in book["colours"].items()
    }
    d[~np.array([near[s] for s in book["states"]])] = 9.0
    k = int(np.argmin(d))
    return (book["states"][k] if d[k] <= K.NODE_STATE_MAX_DIST else None), float(d[k])


def name_states(img: np.ndarray, nodes: list[dict], book: dict | None = None) -> list[str | None]:
    """Name the state of every found map node of one screenshot.

    Args:
        img: BGR screenshot (1080p).
        nodes: Detected map nodes (dicts with "x", "y" in screen px; "hidden" / "unverified" ones are only guesses
            of where a map is, so their state is never named).
        book: state_pictures(); None loads them. A caller that saves the names with their stamp passes the book it
            takes the stamp from, so a freeze in between can't pair names with another set's stamp.

    Returns:
        One state (or None when unsure) per node, in order.
    """
    book = book if book is not None else state_pictures()
    return [None if n.get("hidden") or n.get("unverified") else name_state(img, n["x"], n["y"], book)[0] for n in nodes]


def save_state_pictures(path, crops: np.ndarray, states: list[str], shots: list[str]) -> None:
    """Store state pictures as plain arrays in a compressed .npz file (no pickled code).

    Args:
        path: Output .npz path (normally NODE_STATES_FILE).
        crops: (n, SIZE, SIZE, 3) uint8 BGR crops centred on map nodes (icon_refs.crop).
        states: State of each crop (one of NODE_STATES).
        shots: The screenshot each crop comes from.

    Raises:
        ValueError: A state outside NODE_STATES, or lengths that differ.
    """
    if len(crops) != len(states) or len(states) != len(shots):
        raise ValueError("one state and one screenshot per crop")
    bad = sorted(set(states) - set(K.NODE_STATES))
    if bad:
        raise ValueError(f"unknown state(s): {', '.join(bad)}")
    size = icon_refs.SIZE
    data = io.BytesIO()
    np.savez_compressed(
        data,
        crops=np.asarray(crops, np.uint8).reshape(-1, size, size, 3),
        states=np.array(states, dtype=str),
        shots=np.array(shots, dtype=str),
    )
    # in one step: a failed write keeps the pictures there were (the detector reads them whenever the file changes)
    fileio.write_bytes_atomic(path, data.getvalue())
