"""core.frame (from atlas_builder_core.py)"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import constants as K
from .constants import ATLAS_OUTPUTS, HUD_DEPTH, HUD_MASK_FILE, ICON_BASE_DY, IMAGE_EXT, ROW_STEP_PX
from .geometry import persp, rectifier


# ------------------------------------------------------------------ frame data
@dataclass
class Frame:
    name: str
    path: str
    sha: str
    w: int
    h: int
    pts: np.ndarray  # (N,2) screenshot pixels
    usable: np.ndarray  # (N,) bool: real, visible bases (no hidden / icon-only guesses)
    nodes: list[dict]
    edges: list[tuple[int, int, float, str]]
    landmarks: list[dict]
    R: np.ndarray = field(default_factory=lambda: np.eye(3))  # screen px -> flat map coords

    @staticmethod
    def from_json(d: dict, horizon: float | None | str = "default") -> Frame:
        if horizon == "default":  # module setting is in px; rectifier takes image heights
            horizon = None if K.HORIZON is None else K.HORIZON / d["height"]  # (read live: tests flatten it)
        nodes = d["nodes"]
        R = rectifier(d["width"], d["height"], horizon)
        screen = np.array([[n["x"], n["y"]] for n in nodes], float).reshape(-1, 2)
        on_hud = on_hud_mask(screen, d["width"], d["height"])
        usable = np.array([not (n["hidden"] or n["unverified"]) for n in nodes], bool) & ~on_hud
        edges = [(e["a"], e["b"], e["conf"], e["status"]) for e in d["edges"] if not (on_hud[e["a"]] or on_hud[e["b"]])]
        landmarks = [
            lm
            for lm in d["landmarks"]
            if not on_hud_mask(np.array([[lm["x"], lm["y"]]], float), d["width"], d["height"])[0]
        ]
        fr = Frame(
            d["name"],
            d["path"],
            d["sha256"],
            d["width"],
            d["height"],
            persp(R, screen),
            usable,
            nodes,
            edges,
            landmarks,
            R,
        )
        fr.on_hud = on_hud
        icons = d.get("icons", [])
        if icons:
            ip = np.array([[m["x"], m["y"]] for m in icons], float)
            keep = ~on_hud_mask(ip, d["width"], d["height"])
            icons = [m for m, k in zip(icons, keep, strict=False) if k]
        fr.icons = icons  # screen px; badges from the icon matcher
        return fr


_hud_cache: dict = {}


def is_full_window(w: int, h: int) -> bool:
    return w >= 1850 and h >= 1040 and abs(w / h - 16 / 9) < 0.03


def atlas_files(atlas_path) -> Path:
    """the folder for everything an atlas writes besides atlas.json and its detection cache: map image cache,
    exports, undo snapshots. A subfolder, so the atlas folder can also be the screenshot folder (user).
    Files from atlases made before v0.88 (next to atlas.json) are moved in."""
    atlas_path = Path(atlas_path)
    d = atlas_path.with_name(atlas_path.stem + "_files")
    d.mkdir(parents=True, exist_ok=True)
    for suffix in ATLAS_OUTPUTS + ("_undo",):
        old = atlas_path.with_name(atlas_path.stem + suffix)
        new = d / (atlas_path.stem + suffix)
        if old.exists() and not new.exists():
            with contextlib.suppress(OSError):
                old.rename(new)
    return d


def is_screenshot(p) -> bool:
    """an image file that can be a screenshot: not one of the atlas's own outputs (an old atlas may still have
    them next to atlas.json), not inside an atlas's _files / _frames folder"""
    p = Path(p)
    if p.suffix.lower() not in IMAGE_EXT or not p.is_file():
        return False
    if any(p.name.endswith(o) for o in ATLAS_OUTPUTS):
        return False
    return not p.parent.name.endswith(("_files", "_frames", "_undo"))


def screenshots_in(folder) -> list[Path]:
    """the screenshots directly in a folder, in name (= time) order"""
    try:
        return sorted(q for q in Path(folder).iterdir() if is_screenshot(q))
    except OSError:
        return []


def hud_mask(w: int, h: int, pad: int = 0) -> np.ndarray:
    """uint8 mask, 255 = game HUD (all zero for cropped screenshots), grown by pad px (shrunk if < 0)"""
    k = (w, h, pad)
    if k not in _hud_cache:
        m = np.zeros((h, w), np.uint8)
        if is_full_window(w, h):
            src = cv2.imread(str(HUD_MASK_FILE), cv2.IMREAD_GRAYSCALE)
            m = (cv2.resize(src, (w, h), interpolation=cv2.INTER_NEAREST) > 127).astype(np.uint8) * 255
            if pad:  # pad < 0: only spots that deep inside the HUD
                se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(pad) + 1, 2 * abs(pad) + 1))
                m = cv2.dilate(m, se) if pad > 0 else cv2.erode(m, se)
        _hud_cache[k] = m
    return _hud_cache[k]


def on_hud_mask(pts: np.ndarray, w: int, h: int, pad: float = -HUD_DEPTH) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    if not is_full_window(w, h) or not len(pts):
        return np.zeros(len(pts), bool)
    m = hud_mask(w, h, int(pad))
    x = np.clip(pts[:, 0].round().astype(int), 0, w - 1)
    y = np.clip(pts[:, 1].round().astype(int), 0, h - 1)
    return m[y, x] > 0


def row_bases(icons: list[dict]) -> list[tuple[float, float]]:
    """per badge (screen px): its map base = under the middle of the row of badges it is in. A row: badges
    at the same height, 36 px apart (72 when the middle one was missed)."""
    order = sorted(range(len(icons)), key=lambda k: icons[k]["x"])
    rows: list[list[int]] = []
    for k in order:
        m = icons[k]
        for r in rows:
            last = icons[r[-1]]
            gap = m["x"] - last["x"]
            if (
                abs(m["y"] - last["y"]) <= 6
                and (abs(gap - ROW_STEP_PX) <= 8 or abs(gap - 2 * ROW_STEP_PX) <= 8)
                and "LostTower" not in (m["name"], last["name"])
            ):
                r.append(k)
                break
        else:
            rows.append([k])
    out = [(0.0, 0.0)] * len(icons)
    for r in rows:
        bx = (icons[r[0]]["x"] + icons[r[-1]]["x"]) / 2
        by = float(np.mean([icons[k]["y"] for k in r])) + ICON_BASE_DY
        for k in r:
            out[k] = (bx, by)
    return out
