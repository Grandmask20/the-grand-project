"""core.frame (from atlas_builder_core.py)"""

from __future__ import annotations

import contextlib
import re
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import constants as K
from .constants import (
    ATLAS_OLD_SHEETS,
    ATLAS_OUTPUTS,
    GENERATED_TAG,
    HUD_DEPTH,
    HUD_MASK_FILE,
    ICON_BASE_DY,
    IMAGE_EXT,
    ROW_STEP_PX,
)
from .geometry import persp, rectifier


# ------------------------------------------------------------------ frame data
@dataclass
class Frame:
    """One screenshot's detection, ready to be placed in the atlas.

    Attributes:
        name: Screenshot file name.
        path: Screenshot file path.
        sha: SHA-256 of the screenshot file (a screenshot already in the atlas is not added again).
        w: Screenshot width in px.
        h: Screenshot height in px.
        pts: (N, 2) map node positions in flat map coordinates (screenshot px with the camera tilt undone by R).
        usable: (N,) bool: real, visible bases (no hidden / icon-only guesses, nothing on the game HUD).
        nodes: The detector's map nodes (dicts with x, y in screen px, hidden, unverified, tower, icon, source).
        edges: Paths as (node a, node b, confidence, status) with indices into `nodes`.
        landmarks: The detector's landmarks (dicts with kind, x, y in screen px, conf, source).
        R: 3x3 rectifier: screen px -> flat map coords.
        on_hud: (N,) bool, set by from_json: map nodes that lie on the game HUD.
        icons: Icons ("badges") from the detector, screen px, those on the HUD left out; set by from_json.
    """

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
        """Build a Frame from a detector result.

        Map nodes, paths, landmarks and icons that lie on the game HUD are dropped (nodes stay in `nodes` but are
        not usable).

        Args:
            d: Detector result for one screenshot (name, path, sha256, width, height, nodes, edges, landmarks,
                optional icons).
            horizon: Horizon row as a fraction of the screenshot height, None for no tilt correction, or
                "default" to use the module setting K.HORIZON (in px; read live because tests flatten it).

        Returns:
            The Frame, with `on_hud` and `icons` set.
        """
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
        fr.icons = icons  # screen px; icons from the detector
        return fr


_hud_cache: dict = {}


def read_screenshot(path) -> np.ndarray | None:
    """Read a screenshot as the detector sees it: scaled to SCREEN_HEIGHT (1080) px tall, keeping its shape.

    Everything the detector knows (map bases, badges, towers, dash sizes) was learned in 1080p pixels, and
    the game draws the atlas and its interface in proportion to the screen, so a 1440p or 4K screenshot
    scaled down looks like a 1080p one. 1080p files, and crops (not shaped like a whole game window: widescreen,
    720+ px tall), come back unchanged.

    Args:
        path: Image file path (non-ASCII paths work).

    Returns:
        BGR image, or None when it can't be read (missing, moved, or not a picture).
    """
    try:
        buf = np.fromfile(str(path), np.uint8)
        # an empty file: OpenCV raises on an empty buffer (CodeRabbit)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    # missing or unreadable: said so, not raised (Screenshots of this spot answered 500)
    except (OSError, ValueError, cv2.error):
        return None
    return None if img is None else scale_screenshot(img)


def scale_screenshot(img: np.ndarray) -> np.ndarray:
    """A decoded screenshot as the detector sees it (see read_screenshot), for callers that keep the original too.

    Args:
        img: BGR image at its original size.

    Returns:
        The image scaled to SCREEN_HEIGHT px tall, or ``img`` itself when it is 1080p already or a crop.
    """
    height, width = img.shape[:2]
    size = detector_size(width, height)
    if size == (width, height):
        return img
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA if size[1] < height else cv2.INTER_CUBIC)


def detector_size(width: int, height: int) -> tuple[int, int]:
    """The size scale_screenshot gives a screenshot of this size: the detector's pixels.

    Args:
        width: The screenshot's width in px.
        height: Its height in px.

    Returns:
        (width, height) scaled to SCREEN_HEIGHT px tall, or the size itself for a 1080p screenshot or a crop (under
        720 px tall, or not shaped like a whole game window: widescreen, 1.5 to 2.5 wide per tall).
    """
    if height == K.SCREEN_HEIGHT or height < 720 or not 1.5 <= width / height <= 2.5:
        return width, height
    s = K.SCREEN_HEIGHT / height
    return max(1, round(width * s)), K.SCREEN_HEIGHT


def is_full_window(w: int, h: int) -> bool:
    """Tell whether a screenshot size is a whole 16:9 game window (as opposed to a crop).

    Args:
        w: Width in px (after read_screenshot scaling).
        h: Height in px.

    Returns:
        True for at least 1850 x 1040 px with an aspect ratio within 0.03 of 16:9.
    """
    return w >= 1850 and h >= 1040 and abs(w / h - 16 / 9) < 0.03


def atlas_files(atlas_path) -> Path:
    """Return the folder for everything an atlas writes besides atlas.json and its detection cache.

    That is the map image cache, exports and undo snapshots. A subfolder, so the atlas folder can also be the
    screenshot folder (user). Files from atlases made before v0.88 (next to atlas.json) are moved in.
    The folder is created if missing.

    Args:
        atlas_path: Path of the atlas .json file.

    Returns:
        Path of the "<atlas stem>_files" folder next to the atlas.
    """
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


def map_image_files(atlas_path) -> tuple[Path, Path]:
    """Return the cache files of an atlas's stitched map image (written and read by the app).

    Args:
        atlas_path: Path of the atlas .json file.

    Returns:
        (<stem>_terrain.png, <stem>_terrain.npz) in the atlas's files folder: the picture, and its key, origin,
        weight and (after Fix seams) ownership labels.
    """
    p = Path(atlas_path)
    d = atlas_files(p)
    return d / (p.stem + "_terrain.png"), d / (p.stem + "_terrain.npz")


def png_bytes(img: np.ndarray, what: str = "output") -> bytes:
    """Encode an image as PNG with the program's text tag (GENERATED_TAG: what) right after the header.

    Args:
        img: BGR or greyscale image.
        what: Text stored in the tag, saying what the image is.

    Returns:
        The PNG file contents.
    """
    data = cv2.imencode(".png", img)[1].tobytes()
    body = b"tEXt" + GENERATED_TAG + b"\0" + what.encode("latin-1", "replace")
    chunk = (len(body) - 4).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")
    return data[:33] + chunk + data[33:]  # 8-byte signature + 25-byte IHDR, then the tag


def write_png(path, img: np.ndarray, what: str = "output") -> None:
    """Write an image the program made (map image, export, thumbnail, sheet).

    It is tagged, so it is never taken for a screenshot (works with non-ASCII paths, unlike cv2.imwrite).

    Args:
        path: Output file path.
        img: BGR or greyscale image.
        what: Text stored in the tag, saying what the image is.
    """
    Path(path).write_bytes(png_bytes(img, what))


def is_generated(p) -> bool:
    """Tell whether a file is a PNG the program wrote itself (its text tag sits in the first bytes).

    Args:
        p: File path.

    Returns:
        True for a tagged PNG; False otherwise or when the file can't be read.
    """
    try:
        with open(p, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return False
    return head[:8] == b"\x89PNG\r\n\x1a\n" and b"tEXt" + GENERATED_TAG + b"\0" in head


def is_atlas_output(name: str) -> bool:
    """Tell whether a file name is one of the images an atlas writes (by name; newer ones are also tagged).

    Args:
        name: The file name.

    Returns:
        True for <atlas>_terrain.png, _composite.png, ... and old <atlas>_badges_<round>.png sheets.
    """
    return name.endswith(ATLAS_OUTPUTS) or re.search(ATLAS_OLD_SHEETS, name) is not None


def is_screenshot(p) -> bool:
    """Tell whether an image file can be a screenshot.

    Not one of the atlas's own outputs (an old atlas may still have them next to atlas.json), not inside an
    atlas's _files / _frames / _undo folder, and not any image the program made (tagged: is_generated).

    Args:
        p: File path.

    Returns:
        True when the file is an existing image (IMAGE_EXT) that can be a screenshot.
    """
    p = Path(p)
    if p.suffix.lower() not in IMAGE_EXT or not p.is_file():
        return False
    if is_atlas_output(p.name):
        return False
    if p.parent.name.endswith(("_files", "_frames", "_undo")):
        return False
    return not is_generated(p)


def screenshots_in(folder) -> list[Path]:
    """List the screenshots directly in a folder, in name (= time) order.

    Args:
        folder: Folder path.

    Returns:
        Sorted screenshot paths (see is_screenshot); empty when the folder can't be read.
    """
    try:
        return sorted(q for q in Path(folder).iterdir() if is_screenshot(q))
    except OSError:
        return []


def hud_mask(w: int, h: int, pad: int = 0) -> np.ndarray:
    """Return the game HUD mask for a screenshot size (cached).

    Args:
        w: Screenshot width in px.
        h: Screenshot height in px.
        pad: Grow the HUD by this many px; < 0 shrinks it (only spots that deep inside the HUD).

    Returns:
        (h, w) uint8 mask, 255 = game HUD (all zero for cropped screenshots).
    """
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
    """Tell which screen points lie on the game HUD.

    Args:
        pts: Points in screen px, anything numpy can reshape to (n, 2).
        w: Screenshot width in px.
        h: Screenshot height in px.
        pad: HUD growth in px (see hud_mask); the default -HUD_DEPTH counts only points that deep inside it.

    Returns:
        (n,) bool array, True on the HUD (all False for cropped screenshots).
    """
    pts = np.asarray(pts, float).reshape(-1, 2)
    if not is_full_window(w, h) or not len(pts):
        return np.zeros(len(pts), bool)
    m = hud_mask(w, h, int(pad))
    x = np.clip(pts[:, 0].round().astype(int), 0, w - 1)
    y = np.clip(pts[:, 1].round().astype(int), 0, h - 1)
    return m[y, x] > 0


def row_bases(icons: list[dict]) -> list[tuple[float, float]]:
    """Find each icon's map base: under the middle of the row of icons it is in.

    A row: icons (badges) at the same height (within 6 px), ROW_STEP_PX (36) px apart (72 when the middle one was
    missed). Lost Tower icons always stand alone. The base is ICON_BASE_DY below the row.

    Args:
        icons: Icons of one screenshot (dicts with x, y in screen px and name).

    Returns:
        One (x, y) map base position in screen px per icon, in the same order.
    """
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


# (moved here from app.replay: the atlas-wide check needs it too, for icons over time)
STEAM_TIME = re.compile(r"_(\d{14})_\d+$")  # Steam names screenshots <app id>_<YYYYMMDDHHMMSS>_<n>


def capture_time(frame: dict) -> float | None:
    """When a screenshot was taken: from its Steam file name, else the time kept with it ("taken": saved when its
    copy was kept, app/keeping.py, so a deleted screenshot keeps its place in "oldest to newest" and the timelapse),
    else the file's modified time.

    Args:
        frame: Atlas frame dict ("name", "path", "taken").

    Returns:
        Seconds since the epoch (local time), or None when none is known.
    """
    m = STEAM_TIME.search(frame.get("name", ""))
    if m:
        try:
            return time.mktime(time.strptime(m.group(1), "%Y%m%d%H%M%S"))
        except ValueError:
            pass
    if frame.get("taken") is not None:
        return float(frame["taken"])
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
