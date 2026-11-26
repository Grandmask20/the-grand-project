"""webmap.sharp: the map's tiles past the map image, built from the screenshots when the browser asks.

The map image tiles stop at the map image's own resolution (zmax), which on a large atlas is far below the
screenshots'. Past it, each tile is built like the zoomed-in ground (core.build_sharp_tile) and kept (in memory by
the caller, and on disk when a folder is given). Spots no screenshot shows (moved or deleted screenshots) are taken
from the map image tile above, scaled up.
"""

from __future__ import annotations

import collections
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from grand_project import core

from .constants import (
    WEBMAP_JPEG_QUALITY,
    WEBMAP_SHARP_BUILDERS,
    WEBMAP_SHARP_IMAGES,
    WEBMAP_SHARP_MAX_FRAMES,
    WEBMAP_SHARP_WEIGHTS,
    WEBMAP_TILE,
)
from .tiles import Grid, RasterTiler


class SharpTiles:
    """Builds the tiles past zmax for one map image. Thread-safe (the server answers in threads)."""

    def __init__(
        self,
        atlas,
        footprints: list,
        grid: Grid,
        raster: RasterTiler,
        zdeep: int,
        labels: tuple | None = None,
        origin: tuple | None = None,
        folder: Path | None = None,
    ):
        """Keep what the tiles are built from.

        Args:
            atlas: The atlas (its screenshots).
            footprints: core.footprint of every screenshot, in atlas.frames order.
            grid: The map image's grid.
            raster: The map image tiler (fills spots no screenshot shows).
            zdeep: The deepest level.
            labels: (ownership map, screenshot names) of the clean map (Fix seams), or None.
            origin: (x0, y0, scale) of the map image the ownership map belongs to.
            folder: Folder to keep built tiles in ({z}/{x}/{y}.jpg), or None.
        """
        self.atlas, self.footprints, self.grid, self.raster, self.zdeep = atlas, footprints, grid, raster, zdeep
        self.labels, self.origin, self.folder = labels, origin, folder
        self._weights: collections.OrderedDict = collections.OrderedDict()
        self._images: collections.OrderedDict = collections.OrderedDict()  # (its own few: _image)
        self._lock = threading.Lock()
        self._builders = threading.Semaphore(WEBMAP_SHARP_BUILDERS)
        self._building: dict[tuple, threading.Event] = {}

    def has(self, z: int) -> bool:
        """Tell whether level z is one of the sharp levels.

        Args:
            z: Tile level.

        Returns:
            True for zmax < z <= zdeep.
        """
        return self.grid.zmax < z <= self.zdeep

    def _weight(self, f: dict) -> np.ndarray:
        """Return a screenshot's ground weight (core.ground_weight), kept for the most recently used ones.

        Args:
            f: The screenshot's entry from atlas.frames.

        Returns:
            Its weight array, or None when its picture is gone.
        """
        key = f["name"]
        with self._lock:
            if key in self._weights:
                self._weights.move_to_end(key)
                return self._weights[key].astype(np.float32)
        img = self._image(f["path"])
        if img is None:  # (deleted, with no copy: the tile leaves it out, core.build_sharp_tile)
            return None
        # (kept float16: it only picks which screenshot shows a spot, half the memory; warped as float32). Given as
        # kept also when just worked out: full precision then, rounded once kept, one tile picked another screenshot on
        # a near tie by what was cached (CodeRabbit)
        w = core.ground_weight(img).astype(np.float16)
        with self._lock:
            self._weights[key] = w
            while len(self._weights) > WEBMAP_SHARP_WEIGHTS:
                self._weights.popitem(last=False)
        return w.astype(np.float32)

    def _image(self, path: str) -> np.ndarray | None:
        """Return a screenshot for the zoomed-in ground: from its own WEBMAP_SHARP_IMAGES, else the atlas's (one a
        placement keeps is given, a new one isn't kept there: Atlas.image keep=False).

        Args:
            path: The screenshot's path.

        Returns:
            The decoded screenshot, or None when its picture is gone.
        """
        with self._lock:
            if path in self._images:
                self._images.move_to_end(path)
                # (a screenshot used, as Atlas.image says it: panning over the same spots isn't idle time - CodeRabbit)
                self.atlas.images_used = time.monotonic()
                return self._images[path]
        img = self.atlas.image(path, keep=False)
        if img is None:
            return None
        with self._lock:
            self._images[path] = img
            while len(self._images) > WEBMAP_SHARP_IMAGES:
                self._images.popitem(last=False)
        return img

    def release(self) -> int:
        """Let go of what it keeps (its screenshots and weights: made again when next asked for; app.idle).

        Returns:
            How many decoded screenshots were let go.
        """
        with self._lock:
            n = len(self._images)
            self._images.clear()
            self._weights.clear()
        return n

    def holding(self) -> bool:
        """Tell whether it keeps anything release would let go."""
        return bool(self._images or self._weights)

    def _fallback(self, z: int, x: int, y: int) -> np.ndarray:
        """Return the tile cut from the map image tile above it (zmax), scaled up: for holes.

        Args:
            z: Tile level (> zmax).
            x: Tile column.
            y: Tile row.

        Returns:
            BGR (WEBMAP_TILE, WEBMAP_TILE, 3); black where the map image has nothing.
        """
        k = z - self.grid.zmax
        T = WEBMAP_TILE
        img = self.raster.pixels(self.grid.zmax, x >> k, y >> k)
        if img is None:
            return np.zeros((T, T, 3), np.uint8)
        f = 1 << k
        px, py = (x % f) * T / f, (y % f) * T / f
        A = np.array([[f, 0, -px * f], [0, f, -py * f]], float)
        return cv2.warpAffine(img, A, (T, T), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def build(self, z: int, x: int, y: int, skipped: list | None = None) -> np.ndarray:
        """Build one sharp tile.

        Args:
            z: Tile level (> zmax).
            x: Tile column.
            y: Tile row.
            skipped: A list the screenshots left out are added to (core.build_sharp_tile), or None.

        Returns:
            BGR (WEBMAP_TILE, WEBMAP_TILE, 3).
        """
        ax0, ay0, s = self.grid.tile_area(z, x, y)
        out, best = core.build_sharp_tile(
            self.atlas,
            self.footprints,
            s,
            ax0,
            ay0,
            WEBMAP_TILE,
            self._weight,
            WEBMAP_SHARP_MAX_FRAMES,
            labels=self.labels,
            origin=self.origin,
            skipped=skipped,
            image_of=self._image,
        )
        holes = best <= 0
        if holes.any():
            out[holes] = self._fallback(z, x, y)[holes]
        return out

    def jpeg(self, z: int, x: int, y: int, wanted=None, skipped: list | None = None) -> bytes | None:
        """Return a sharp tile as JPEG: from the folder when kept there, else built (once, even when asked for
        twice at the same time; at most WEBMAP_SHARP_BUILDERS at a time).

        Args:
            z: Tile level (> zmax).
            x: Tile column.
            y: Tile row.
            wanted: Callable telling whether the tile is still wanted (its browser request not given up), asked
                once a builder is free: zooming in from far, the browser drops most tiles it asked for on the way,
                and building them all kept the ones finally shown waiting (user: the sharp ground came late).
            skipped: A list the screenshots left out of the tile built here are added to (their picture gone mid-way),
                or None: such a tile is never kept, in the folder or by the caller (CodeRabbit).

        Returns:
            The JPEG bytes, or None when no longer wanted.
        """
        path = self.folder / str(z) / str(x) / f"{y}.jpg" if self.folder else None
        key = (z, x, y)
        while True:
            if path is not None and path.exists():
                return path.read_bytes()
            with self._lock:
                ev = self._building.get(key)
                mine = ev is None
                if mine:
                    ev = self._building[key] = threading.Event()
            if not mine:  # another request is building it: wait for that one, then read it
                ev.wait()
                if path is None:
                    mine = True  # nothing kept to read: build it here too
                else:
                    continue
            try:
                with self._builders:
                    if wanted is not None and not wanted():
                        return None
                    left: list[str] = skipped if skipped is not None else []
                    pix = self.build(z, x, y, left)
                ok, buf = cv2.imencode(".jpg", pix, [cv2.IMWRITE_JPEG_QUALITY, WEBMAP_JPEG_QUALITY])
                if not ok:
                    raise OSError(f"sharp tile {z}/{x}/{y} could not be encoded")
                data = buf.tobytes()
                # (one with a screenshot left out, gone mid-build, isn't kept: built again next time - CodeRabbit)
                if path is not None and not left:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(path.name + ".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(path)  # whole or not at all: a half-written tile is never read
                return data
            finally:
                with self._lock:
                    if self._building.get(key) is ev:
                        self._building.pop(key, None)
                ev.set()
