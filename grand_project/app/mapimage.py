"""app.mapimage: part of AtlasSession (a mixin; see app/session.py): the map image, Fix seams, and the map's tiles.

The map image (the stitched screenshots) is kept in memory and cached next to the atlas (<stem>_terrain.png / .npz,
with the clean map's ownership after Fix seams). The page's map is MapLibre on tiles made here when asked for:
the map image's levels (raster), sharp ground past it built from the screenshots, and vector tiles (MVT) of what
the filters show: map nodes, paths, icons, landmarks, bookmarks, the vector ground (land, biome areas) and the 3D
models. Every tile URL carries a version, so a changed atlas, map image or filter is fetched again.
"""

from __future__ import annotations

import collections
import contextlib
import itertools
import math
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from grand_project import builder, core
from grand_project import cities as atlas_cities
from grand_project import logs as atlas_log
from grand_project.webmap.constants import (
    WEBMAP_BEAM_MIN,
    WEBMAP_CROP_PX,
    WEBMAP_CROP_UNITS,
    WEBMAP_FOG_DARK,
    WEBMAP_ICON_MIN_PX,
    WEBMAP_ICON_SPRITE,
    WEBMAP_ICON_UNITS,
    WEBMAP_JPEG_QUALITY,
    WEBMAP_MASK_MAX,
    WEBMAP_OVERZOOM,
    WEBMAP_SHARP_LEVEL,
    WEBMAP_TILE,
    WEBMAP_TOWER_SAME,
)
from grand_project.webmap.shapes import biome_polygons, land_polygons
from grand_project.webmap.sharp import SharpTiles
from grand_project.webmap.solids import map_pillar, structure
from grand_project.webmap.tiles import Grid, RasterTiler, VectorTiler

from .constants import TERRAIN_PIXELS, TILE_CACHE
from .icons import bgr_hex, icon_art_version, icon_col, icon_label, icon_name
from .tilesource import TileSource

LOG = atlas_log.get("app")
# how each part of the tiles' source is read from the session (_source_sync)
_SOURCE_PARTS = {
    "gen": lambda s: s.opened.gen,
    "V": lambda s: s.V,
    "D": lambda s: s.D,
    "flags": lambda s: s._flags(),
    "model_version": lambda s: s.model_version,
    "filter_version": lambda s: s.filter_version,
    "terrain_version": lambda s: s.terrain_version,
    "terrain": lambda s: s.terrain,
    "grid": lambda s: s.grid,
    "replay": lambda s: s.replay_steps(),
    "replay_token": lambda s: s.replay_token,
}
# the map image's parts of it (shown, or forgotten)
MAP_IMAGE_PARTS = ("terrain", "grid", "terrain_version")

SESSION_RUN = os.urandom(4).hex()  # this run of the app: part of every tile URL (map_info "tile_key")


def path_share(p: dict) -> float:
    """How many of the screenshots that show both its map nodes drew a path, 0..1 (an Abyss chain: 1, always shown).

    The page hides paths below "drawn by at least" with it, without new tiles.

    Args:
        p: Path dict ("seen_in", "frames", "abyss").

    Returns:
        The share, rounded to 3 places.
    """
    if p.get("abyss"):
        return 1.0
    return round(min(1.0, p.get("seen_in", 0) / max(1, p.get("frames", 0))), 3)


class _LRU:
    """A small thread-safe least-recently-used cache."""

    def __init__(self, size: int):
        """Make an empty cache.

        Args:
            size: Entries kept at most.
        """
        self.size, self.data, self.lock = size, collections.OrderedDict(), threading.Lock()

    def get(self, key):
        """Return a cached value (None when missing).

        Args:
            key: The key.

        Returns:
            The value or None.
        """
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        return None

    def put(self, key, value) -> None:
        """Keep a value.

        Args:
            key: The key.
            value: The value.
        """
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)

    def clear(self) -> None:
        """Forget everything."""
        with self.lock:
            self.data.clear()


def files_key(path) -> str:
    """An atlas file as one spelling (resolved, case folded where the file system ignores case): retire_files."""
    p = str(Path(path).resolve())
    return p.lower() if os.name == "nt" else p


class MapImageMixin:
    """AtlasSession mixin: the map image, Fix seams and the map's tiles (see the module docstring)."""

    # ------------------------------------------------------------------ state
    def _init_mapimage(self) -> None:
        """Start with no map image."""
        self._tiles = _LRU(TILE_CACHE)
        self._seams_proc = None
        self._seams_starting = False  # Fix seams claimed, its process not registered yet
        self._seams_stopped = False
        # a Fix seams waiting for adding to finish: {"gen": its atlas, "token": its own id} (fix_seams); kept until its
        # start is claimed (cleared before, a Stop in between was lost: CodeRabbit)
        self._seams_waiting: dict | None = None
        self._seams_tokens = itertools.count(1)
        self._seams_trouble: list[str] = []  # why adding didn't finish while one waited (_start_waiting_seams asks)
        self._seams_asking = False  # that question is open
        self._cache_writes: dict[str, int] = {}  # per atlas file: cache writes asked for, the newest written
        self._cache_lock = threading.Lock()  # (every background write of an atlas's files: retire_files)
        self._retired: set[str] = set()  # atlas files being deleted: their background writes are skipped
        self._sharp_key = None  # the sharp tile folder in use (kept with the new one: _sharp_folder)
        self._terrain_job = 0
        self.filter_version = 0
        self._vector = None  # (key, VectorTiler)
        # one build of the vector tiles or 3D scene at a time (never the session lock: they are made from _source)
        self._vector_lock = threading.Lock()
        # what they are made from (app/tilesource.py), replaced in the same step as each change to it
        self._source_lock = threading.Lock()
        self._source = TileSource()
        self._reset_mapimage()
        self._source_sync(*_SOURCE_PARTS)

    def _source_sync(self, *parts: str) -> None:
        """Put a new tiles' source in place with these parts as they are now: called in the same step as the change
        to them (under the session lock where the change is), so a tile is never made from half of a change.

        Args:
            *parts: Names of TileSource fields that changed.
        """
        with self._source_lock:
            self._source = self._source.with_(**{k: _SOURCE_PARTS[k](self) for k in parts})

    def _reset_mapimage(self) -> None:
        """Forget the map image (another atlas, or none)."""
        self.terrain = None  # (canvas, weight, origin)
        self.labels = None  # (ownership map, screenshot names) of the clean map
        self.terrain_version = getattr(self, "terrain_version", 0) + 1
        self._terrain_snap = (None, self.terrain_version)  # (map image, its version): read as one
        self.grid: Grid | None = None
        self._raster: RasterTiler | None = None
        self._sharp: SharpTiles | None = None
        # (grid, raster tiler, sharp tiles, version): the map image's tiling, handed over as one (a crop read the grid
        # and the tiles at different moments of a change: CodeRabbit)
        self._tile_state: tuple = (None, None, None, self.terrain_version)
        # the tiling in place when the jobs running now began (pinned by the worker, let go when it is idle): the
        # page's backdrop keeps asking for that ground while they run (user: the old terrain viewable until the new
        # is in, even offscreen), and answered from the new one, a map image built again elsewhere put it off its
        # place (CodeRabbit). It holds the old map image's memory meanwhile.
        self._tile_before: tuple | None = None
        self._ground = None
        self._ground_for = None
        self._tiles.clear()
        if hasattr(self, "_source"):  # (not yet while the session is being set up: _init_mapimage)
            self._source_sync(*MAP_IMAGE_PARTS)

    # ------------------------------------------------------------------ the map image
    def load_terrain(self, cities: bool = True, background: bool = True) -> None:
        """Show the stitched map: from the cache next to the atlas when it matches, else built in the background.

        Args:
            cities: Rebuild the model when the map image arrives (its biomes follow the ground).
            background: Build on a background thread (False: now, on this thread; tests).
        """
        with self._lock:  # the build claimed, then its part started: in one step (a replacement started its part
            # first, and an older build failing in between still counted as current, CodeRabbit). The atlas is
            # read once, here, as one record: read field by field after it, a switch between gave A's cached image
            # B's generation, and it was shown for B (CodeRabbit)
            opened = self.opened
            if not opened.atlas or not opened.atlas.frames:
                self._reset_mapimage()
                self.parts.done("map_image", opened.gen)  # (nothing to show: not waited for)
                empty = True
            else:
                empty = False
                self._terrain_job += 1
                job = self._terrain_job
                self.parts.start("map_image", opened.gen)
        if empty:
            self.events.publish("terrain", self.terrain_version)
            return
        png, npz = core.map_image_files(opened.path)
        key = opened.atlas.terrain_key()
        gen = opened.gen
        try:
            with np.load(npz) as meta:
                if str(meta["key"]) == key:
                    import cv2

                    canvas = cv2.imdecode(np.fromfile(str(png), np.uint8), cv2.IMREAD_COLOR)
                    weight = meta["weight"].astype(np.float32)
                    origin = tuple(float(v) for v in meta["origin"])
                    labels = (meta["labels"], [str(n) for n in meta["names"]]) if "labels" in meta.files else None
                    if canvas is not None and canvas.shape[:2] == weight.shape:
                        # (its build number too: a clean map put in since drops it, as for a built one: CodeRabbit)
                        self.set_terrain(
                            canvas, weight, origin, save=False, labels=labels, cities=cities, gen=gen, job=job
                        )
                        return
        except Exception:
            LOG.debug("map image cache not usable, rebuilding", exc_info=True)
        atlas, scope = opened.atlas, opened.scope  # (the record taken in the claim above)
        # each build its own line: an older one ending (a newer build took over) cleared the newer one's (CodeRabbit)
        owner = f"map{job}"
        self.events.set_progress("building the map image (first time for this atlas)…", scope, owner=owner)

        def failed(e: Exception) -> None:
            """Report the map image as failed (its log line always; the part only for the build still current: an
            older build failing late marked the newer one failed, CodeRabbit)."""
            LOG.exception("map image could not be built")
            self.events.log(f"map image could not be built: {e}", scope)
            with self._lock:  # (checked and marked in one step: a replacement claims its number under this lock)
                current = job == self._terrain_job
                if current:
                    self.parts.fail("map_image", f"{type(e).__name__}: {e}", gen)  # (it only reached the log: user)
            if current:
                self.events.publish("terrain", self.terrain_version)

        def work():
            """Build the map image and show it (background thread)."""
            try:
                t0 = time.monotonic()
                try:
                    canvas, origin, weight = atlas.composite(
                        max_pixels=TERRAIN_PIXELS, with_weight=True, progress=lambda: self.parts.beat("map_image", gen)
                    )
                except Exception as e:
                    failed(e)
                    return
                if job != self._terrain_job:
                    return  # a newer build took over
                try:
                    shown = self.set_terrain(canvas, weight, origin, gen=gen, job=job)
                except Exception as e:
                    # once the image is in, an error comes from the model rebuilt after it, which reports itself:
                    # not the map image's (it marked a shown image failed, CodeRabbit)
                    if self.parts.payload()["parts"].get("map_image", {}).get("state") == "building":
                        failed(e)
                    else:
                        LOG.exception("the model after the new map image failed")
                    return
                if shown:
                    h, w = canvas.shape[:2]
                    self.events.log(f"map image built in {time.monotonic() - t0:.1f} s ({w} x {h} px)", scope)
            finally:
                self.events.set_progress(None, owner=owner)

        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def set_terrain(
        self,
        canvas,
        weight,
        origin,
        save: bool = True,
        labels=None,
        cities: bool = True,
        gen: int | None = None,
        job: int | None = None,
    ) -> bool:
        """Show a new map image: keep it, set up its grid and tilers and, when asked, write its cache files.

        Args:
            canvas: BGR map image.
            weight: Its coverage weight (0 where no screenshot is).
            origin: (x0, y0, scale): atlas (x, y) is image px ((x - x0) * scale, (y - y0) * scale).
            save: Write the cache files and the atlas card picture.
            labels: (ownership map, screenshot names) of the clean map, or None.
            cities: Rebuild the model (biomes follow the ground).
            gen: The atlas generation the image was made for (None: now): another atlas opened since drops it.
            job: The map image build it comes from (None: not a build): a newer one, or a clean map put in since
                (Fix seams retires the builds), drops it, checked under the lock it is put in with (checked
                before, an older build put in after the clean map replaced it: CodeRabbit).

        Returns:
            Whether it was shown (False: made for an atlas no longer open).
        """
        origin = tuple(float(v) for v in origin)
        with self._lock:
            if job is not None and job != self._terrain_job:
                LOG.info("a map image from a build no longer current was dropped")
                return False
            if gen is not None and not self.owns(gen):
                LOG.info("a map image made for another atlas was dropped")
                return False
            self.terrain = (canvas, weight, origin)
            self.labels = labels
            self.grid = Grid(origin, canvas.shape[1], canvas.shape[0])
            self._raster = RasterTiler(canvas, self.grid)
            self._sharp = SharpTiles(
                self.atlas,
                [core.footprint(self.atlas, f) for f in self.atlas.frames],
                self.grid,
                self._raster,
                self.grid.deepest(WEBMAP_SHARP_LEVEL),
                labels=labels,
                origin=origin if labels is not None else None,
                folder=self._sharp_folder(),
            )
            self._ground = None
            self.terrain_version += 1
            self._terrain_snap = (self.terrain, self.terrain_version)
            self._tile_state = (self.grid, self._raster, self._sharp, self.terrain_version)  # (all of it at once)
            self._source_sync(*MAP_IMAGE_PARTS)
            self._tiles.clear()
            self._vector = None
            self._scene3d = None
            self.parts.done("map_image", self.generation)
            # the cache's identity (atlas file, key) and its turn taken with the image shown, in one locked step:
            # taken after, two images shown one after the other could take their turns the other way round, or an
            # atlas switch between paired this image with the next atlas (CodeRabbit). Turns per atlas file.
            cache = None
            if save and self.path:
                path = self.path
                mine = self._cache_writes[str(path)] = self._cache_writes.get(str(path), 0) + 1
                cache = (self.atlas.terrain_key(), path, mine)
        if cache is not None:
            key, path, mine = cache

            def write():
                """Write the map image cache files and the atlas card picture (background thread). One write at a
                time, and only the newest: an older one finishing last left the older image in the cache, or a
                picture of one with the key of another (GPT audit)."""
                with self._cache_lock:
                    if mine != self._cache_writes.get(str(path)) or files_key(path) in self._retired:
                        return  # a newer image was shown meanwhile: its own write follows
                    try:
                        png, npz = core.map_image_files(path)
                        core.write_png(png, canvas, "map image")
                        self.write_thumb(path, canvas)
                        extra = {} if labels is None else {"labels": labels[0], "names": np.array(labels[1])}
                        tmp = npz.with_name(npz.stem + ".writing.npz")  # (whole, or not there: a quit midway)
                        np.savez_compressed(
                            tmp, key=key, origin=np.array(origin, float), weight=weight.astype(np.float16), **extra
                        )
                        os.replace(tmp, npz)
                    except Exception:
                        LOG.warning("map image cache could not be saved", exc_info=True)

            threading.Thread(target=write, daemon=True).start()
        elif self.path and not self.thumb_exists(self.path):
            threading.Thread(target=self._write_thumb_now, args=(self.path, canvas), daemon=True).start()
        try:
            if cities and self.V.get("nodes"):
                self.rebuild_model()  # the biomes follow the ground now
        finally:
            # the image is in whatever the model does after it: told to the page also when the rebuild fails (the
            # page kept the old image until something else refreshed its state, CodeRabbit)
            self.events.publish("terrain", self.terrain_version)
        return True

    def _labels_key(self) -> str:
        """Return a short fingerprint of the clean map's ownership map (which screenshot shows each spot).

        Fix seams again after adding screenshots can give the same screenshots other spots: tiles built from the old
        clean map were served for the new one (CodeRabbit).

        Returns:
            8 hex digits.
        """
        import hashlib

        labels, names = self.labels
        h = hashlib.blake2b(digest_size=4)
        h.update(np.ascontiguousarray(labels).tobytes())  # (every pixel: a sample missed changes, CodeRabbit)
        h.update("|".join(names).encode())
        return h.hexdigest()

    def _write_thumb_now(self, path, canvas) -> None:
        """Write an atlas card picture (background thread), unless the atlas is being deleted (retire_files)."""
        with self._cache_lock:
            if files_key(path) not in self._retired:
                self.write_thumb(path, canvas)

    def retire_files(self, path) -> None:
        """Stop every background write of an atlas's files before they are deleted: the one running ends first (its
        lock is taken), the ones waiting skip. A write still running filled the folder while it was deleted
        ("Directory not empty", seen on macOS CI). Opening an atlas at that path again lets them write (_switch).

        Args:
            path: The atlas file.
        """
        with self._cache_lock:
            self._retired.add(files_key(path))

    def _sharp_folder(self) -> Path | None:
        """Return the folder sharp tiles of the current screenshots are kept in (older ones are removed, except the
        one in use until now: tiles still being made or served from it were taken away mid-way, GPT audit).

        Returns:
            <stem>_files/<stem>_sharp/<key>, or None with no atlas.
        """
        if not self.path or not self.atlas:
            return None
        base = core.atlas_files(self.path) / (self.path.stem + "_sharp")
        key = self.atlas.terrain_key()[:16] + (f"c{self._labels_key()}" if self.labels is not None else "")
        keep = {key, self._sharp_key}
        if base.exists():
            for d in base.iterdir():  # tiles of other screenshots / placements: never shown again
                if d.is_dir() and d.name not in keep:
                    shutil.rmtree(d, ignore_errors=True)
        self._sharp_key = key
        return base / key

    def paste_terrain(self, frames: list[dict]) -> bool:
        """Paste new screenshots into a copy of the map image (fast). Worker thread.

        Args:
            frames: The new screenshots' atlas.frames entries.

        Returns:
            False when they fall outside the map image (it has to be built again).
        """
        if self.terrain is None:
            return False
        canvas, weight, origin = self.terrain
        canvas, weight = canvas.copy(), weight.copy()
        lab = self.labels
        labels, names = (lab[0].copy(), list(lab[1])) if lab is not None else (None, None)
        if not self.atlas.paste_into(canvas, weight, origin, frames, labels=labels, names=names):
            return False
        self.set_terrain(canvas, weight, origin, labels=(labels, names) if labels is not None else None, cities=False)
        return True

    def ground(self):
        """Return the ground sampler of the map image (the biomes compare ground looks), made once per map image.

        Returns:
            A cities.ground_sampler, or None without a map image.
        """
        if self.terrain is None:
            return None
        if self._ground_for != self.terrain_version:
            canvas, weight, origin = self.terrain
            self._ground = atlas_cities.ground_sampler(canvas, weight, origin)
            self._ground_for = self.terrain_version
        return self._ground

    @staticmethod
    def _model_tops(shapes: list[dict]) -> dict[int, float]:
        """The top of the 3D models standing at each map node (atlas units): its pillar, or a structure that marks it.

        Read from the very shapes the 3D view draws (_solid_shapes), so an icon stands on what is shown there: a
        separate guess of the heights missed the towers drawn for map nodes without a Tower landmark (CodeRabbit).

        Args:
            shapes: The 3D view's shapes, each with its pick ("node", i) when a click on it selects map node i.

        Returns:
            Map node index -> height.
        """
        tops: dict[int, float] = {}
        for sh in shapes:
            kind, i = sh.get("pick", ("", -1))
            # the beam of a hall or tower is thin and tall: the icon stands on the building, not on the beam
            if kind == "node" and sh["top"] < WEBMAP_BEAM_MIN:
                tops[i] = max(tops.get(i, 0.0), sh["top"])
        return tops

    def ground_mask(self, x0: float, y0: float, cell: float, w: int, h: int) -> bytes | None:
        """Where the map image shows ground (not the black fog at screenshots' edges), on a grid over the atlas.

        "Colour by" tints only there (user: the fog around the atlas was tinted too, unlike the old window).

        Args:
            x0, y0: Atlas point of the grid's top left corner.
            cell: Atlas units per grid cell.
            w, h: Grid size in cells (each at most WEBMAP_MASK_MAX).

        Returns:
            One byte per cell, row by row (1 = ground), or None without a map image.
        """
        terrain, version = self._terrain_snap  # one read: the image and its version together (CodeRabbit)
        if terrain is None:
            return None
        w, h = min(int(w), WEBMAP_MASK_MAX), min(int(h), WEBMAP_MASK_MAX)
        # kept until the map image changes: Colour by asks again each time it is turned on, and working it out from a
        # big map image took a while (user: the blocky tint showed every time first)
        key = (version, float(x0), float(y0), float(cell), w, h)
        kept = getattr(self, "_masks", {})
        if key in kept:
            return kept[key]
        canvas, weight, (ox, oy, sc) = terrain
        # grid cell (c, r) -> map image px ((x0 + c * cell - ox) * sc, ...)
        A = np.array([[cell * sc, 0, (x0 - ox) * sc], [0, cell * sc, (y0 - oy) * sc]], np.float32)
        grey = canvas.mean(axis=2).astype(np.float32) if canvas.ndim == 3 else canvas.astype(np.float32)
        wt = (weight > 0).astype(np.float32)
        flags = cv2.INTER_AREA | cv2.WARP_INVERSE_MAP
        g = cv2.warpAffine(grey, A, (w, h), flags=flags, borderValue=0.0)
        k = cv2.warpAffine(wt, A, (w, h), flags=flags, borderValue=0.0)
        mask = ((g > WEBMAP_FOG_DARK) & (k > 0.5)).astype(np.uint8).tobytes()
        # a few grids (plain and while replaying) of this map image only
        kept = {k_: v for k_, v in kept.items() if k_[0] == version}
        if len(kept) >= 4:
            kept = {}
        kept[key] = mask
        self._masks = kept
        return mask

    # ------------------------------------------------------------------ Fix seams
    def fix_seams(self, after_adding: bool = False, claim: int | None = None) -> str:
        """Build the clean map (core.seams) in a separate process: map nodes and icons whole, seams where the
        ground matches. Progress lines become the progress box; the clean map replaces the map image when ready.

        It doesn't start while adding runs (or Re-check, Undo...): it built from the atlas as it was, and both
        jobs' progress shared one box (GPT audit). The page then asks: cancel, or queue it (after_adding), started
        by the worker once it has nothing left to do (_start_waiting_seams). Adding that starts while Fix seams
        runs goes on (you: its screenshots get the costlier merging, _seams_ready).

        Args:
            after_adding: When adding runs: wait for it to finish, then start.
            claim: The queued request's id, when that one starts (_start_queued_seams): it starts only if it is still
                the one queued, for the atlas open, in the same locked step (Stop, a switch or closing in between
                leave it off).

        Returns:
            "started"; "adding" (adding runs, not started: the page asks); "queued" (starts once adding is done);
            "dropped" (claim: no longer queued).

        Raises:
            ValueError: With no screenshots, or when it is already running.
        """
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots in this atlas")
        # Starting is a state of its own, from the claim to the process's registration: every way out of it
        # releases the claim (a failing temp folder or input write left it set: "already running" until a restart),
        # and a Stop during it is kept and honoured at registration (it was lost: CodeRabbit, rounds 3 and 4)
        with self._lock:
            # the check and the claim in one step: two quick clicks both passed the check and started two
            # processes, the first one then out of stop_seams' reach (CodeRabbit)
            w = self._seams_waiting
            if claim is not None and (
                w is None or w["token"] != claim or not self.owns(w["gen"]) or getattr(self, "_closing", False)
            ):
                return "dropped"
            queued = w is not None and self.owns(w["gen"])
            # any request while one is queued, its own start or another click (a second request skipped the box and
            # started it, past the box's Cancel: CodeRabbit); with none queued it starts at once as before
            if queued and (self._seams_asking or self._seams_trouble):
                # a box is open, or failures wait to be asked about: it stays queued, in the same step as the claim
                # (claimed anyway, it started without asking, or past a box whose Cancel then did nothing: CodeRabbit)
                return "queued"
            if self.seams_running():
                raise ValueError("Fix seams is already running")
            if self.working():
                if claim is not None:  # adding again: it stays queued, with its id
                    return "queued"
                if not after_adding:
                    return "adding"
                if w is None or not self.owns(w["gen"]):
                    self._seams_waiting = {"gen": self.opened.gen, "token": next(self._seams_tokens)}
                    self._seams_trouble = []
                    self.events.log("Fix seams: queued, starts once adding is done")
                    self.events.publish("seams", True)
                return "queued"
            self._seams_waiting = None
            self._seams_starting, self._seams_stopped = True, False
        tmp = None
        try:
            with self._lock:
                tmp = Path(tempfile.mkdtemp(prefix="grand_seams_"))
                src, out, err = tmp / "atlas.pkl", tmp / "clean.npz", tmp / "errors.txt"
                # its input and its atlas generation together (CodeRabbit); the atlas pickles without its decoded
                # screenshot cache (core.Atlas.__getstate__), so the lock is held only briefly
                src.write_bytes(pickle.dumps(self.atlas))
                gen, scope = self.opened.gen, self.opened.scope
            root = Path(__file__).resolve().parents[2]  # the folder holding the grand_project package
            with open(err, "w", encoding="utf-8") as errf:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "grand_project.core.seams", str(src), str(out), str(TERRAIN_PIXELS)],
                    cwd=str(root),
                    stdout=subprocess.PIPE,
                    stderr=errf,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
        except Exception:
            with self._lock:
                self._seams_starting = False
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            raise
        with self._lock:
            self._seams_starting = False
            stopped = self._seams_stopped
            if stopped or not self.owns(gen):  # stopped while starting, or another atlas opened: never registered
                _end_process(proc)
                shutil.rmtree(tmp, ignore_errors=True)
                if stopped:
                    self.events.log("Fix seams: stopped", scope)
                return "started"
            self._seams_proc, self._seams_busy = proc, True
        t0 = time.monotonic()
        owner = f"seams{next(self._seams_tokens)}"  # (each run its own line: a run ending cleared the next one's)
        self.events.set_progress("fixing seams: building the clean map...", owner=owner)
        self.events.log("Fix seams: building the clean map in the background")
        self.events.publish("seams", True)

        def watch():
            """Pass the process's progress lines on, then show the clean map (background thread)."""
            for line in proc.stdout:
                if line.strip() and line.strip() != "done":
                    self.events.set_progress(line.strip(), scope, owner=owner)
            proc.wait()
            try:
                if proc.returncode == 0 and out.exists() and self.owns(gen) and not self._seams_stopped:
                    with np.load(out) as r:
                        canvas, weight, labels = r["canvas"], r["weight"], r["labels"]
                        origin = tuple(float(v) for v in r["origin"])
                        names = [str(n) for n in r["names"]]
                    with self._lock:  # shown and followed up for the same atlas (a close between: CodeRabbit)
                        # a Stop while it was being loaded counts too (it was put in anyway: GPT audit)
                        if self._seams_stopped:
                            self.events.log("Fix seams: stopped (its clean map was left out)", scope)
                        elif self.owns(gen):
                            self._terrain_job += 1  # (a map image build still running is older: retired)
                            if self.set_terrain(canvas, weight, origin, labels=(labels, names), gen=gen):
                                self.events.log(f"Fix seams: clean map ready ({time.monotonic() - t0:.0f} s)", scope)
                                self._seams_ready(names)
                elif self._seams_stopped:
                    self.events.log("Fix seams: stopped (its clean map was left out)", scope)
                elif proc.returncode != 0:
                    text = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    LOG.error("clean map could not be built: %s", " | ".join(text[-30:]))
                    self.events.log(f"clean map could not be built: {text[-1] if text else proc.returncode}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
                if self._seams_proc is proc:  # (a newer Fix seams may have started meanwhile: CodeRabbit)
                    self._seams_proc, self._seams_busy = None, False
                self.events.set_progress(None, owner=owner)
                self.events.publish("seams", False)

        threading.Thread(target=watch, daemon=True).start()
        return "started"

    def _note_seams_trouble(self, why: str) -> None:
        """Adding didn't finish as it should (a job failed, a screenshot couldn't be read): a queued Fix seams then
        asks before it starts (_start_waiting_seams)."""
        with self._lock:
            if self._seams_waiting is not None:
                self._seams_trouble.append(why)

    def _start_waiting_seams(self) -> None:
        """Start a Fix seams queued while adding ran (the worker, once it has nothing left to do), only when adding
        finished: after a failure it asks first, why and whether to start anyway (you). Not for another atlas than
        the one it was queued in, nor while closing."""
        with self._lock:
            w = self._seams_waiting
            if w is None or self._seams_asking:  # (asked already: the answer decides)
                return
            if not self.owns(w["gen"]) or self._closing:
                self._seams_waiting = None
                self.events.publish("seams", self.seams_running())
                return
            trouble, self._seams_trouble = self._seams_trouble, []
            self._seams_asking = bool(trouble)
        if trouble:  # (asked on a thread of its own: the worker goes on with what is added meanwhile)
            threading.Thread(target=self._ask_seams_anyway, args=(w["token"], trouble), daemon=True).start()
            return
        self.events.log("Fix seams: adding is done, starting")
        self._start_queued_seams(w["token"])

    def _ask_seams_anyway(self, token: int, trouble: list[str]) -> None:
        """Ask whether to start a queued Fix seams although adding didn't finish (background thread)."""
        shown = trouble[:5] + ([f"... and {len(trouble) - 5} more"] if len(trouble) > 5 else [])
        self.events.log("Fix seams: adding didn't finish, asking whether to start it anyway")
        try:
            yes = self.events.ask(
                "Adding didn't finish:\n" + "\n".join(f"- {t}" for t in shown) + "\n\nFix seams was queued to start "
                "once adding finished. Start it anyway, on the atlas as it is now?",
                labels={"title": "Fix seams", "yes": "Fix seams anyway", "no": "Cancel"},
            )
        except Exception:  # (the question failing counts as Cancel; the flag is let go below all the same)
            LOG.exception("asking whether to start Fix seams failed")
            yes = False
        with self._lock:
            self._seams_asking = False
            w = self._seams_waiting
            # this question's own request: an answer to one Stop took off never acts on a newer one (CodeRabbit)
            still = w is not None and w["token"] == token and self.owns(w["gen"]) and not self._closing
            if still and not yes:
                self._seams_waiting = None
                self.events.log("Fix seams: cancelled (adding didn't finish)")
            # yes covers what was asked; failures that came in while it was open stay, and are asked about before
            # it starts (cleared, a Yes started it without showing them: CodeRabbit). Adding again: the worker
            # starts it (or asks) once that is done.
            busy = self.working()
            again = still and yes and not busy and bool(self._seams_trouble)
            if again:
                again, self._seams_trouble = self._seams_trouble, []
                self._seams_asking = True
            newer = w is not None and not still and not busy  # (a newer request waited for this answer)
        if not still or not yes:  # (stopped, another atlas, or closing meanwhile)
            self.events.publish("seams", self.seams_running())
            if newer:
                self._start_waiting_seams()
            return
        if again:
            threading.Thread(target=self._ask_seams_anyway, args=(token, again), daemon=True).start()
            return
        if busy:
            return
        self.events.log("Fix seams: starting anyway")
        self._start_queued_seams(token)

    def _start_queued_seams(self, token: int) -> None:
        """Start the queued Fix seams `token`: claimed in fix_seams' locked step, so a Stop, a switch or closing
        just before leave it off; while adding runs again it stays queued."""
        try:
            if self.fix_seams(after_adding=True, claim=token) == "dropped":
                self.events.publish("seams", self.seams_running())
        except Exception as e:  # (no screenshots left after an Undo...)
            with self._lock:
                if self._seams_waiting is not None and self._seams_waiting["token"] == token:
                    self._seams_waiting = None
            self.events.log(f"Fix seams could not start: {e}")
            self.events.publish("seams", self.seams_running())

    def seams_waiting(self) -> bool:
        """Tell whether a Fix seams waits for adding to finish."""
        return getattr(self, "_seams_waiting", None) is not None

    def seams_running(self) -> bool:
        """Tell whether Fix seams is running.

        Returns:
            True while its process runs.
        """
        if getattr(self, "_seams_starting", False):  # claimed, its process starting
            return True
        p = self._seams_proc
        # also while its watcher still applies the result after the process ended (CodeRabbit)
        return p is not None and (p.poll() is None or getattr(self, "_seams_busy", False))

    def stop_seams(self) -> None:
        """Stop a running Fix seams, whatever its phase: starting, building, or its clean map being loaded (only the
        building phase was stopped before, the loaded map then went in: GPT audit). Its result is dropped. A queued
        one (waiting for adding to finish) is taken off."""
        with self._lock:
            if self._seams_waiting is not None:
                self._seams_waiting = None
                self.events.log("Fix seams: taken off the queue")
                self.events.publish("seams", self.seams_running())
            if self._seams_starting:  # its process not registered yet: kept, honoured at registration (CodeRabbit)
                self._seams_stopped = True
                return
            if self.seams_running():
                self._seams_stopped = True  # (the watcher checks it again right before putting the map in)
        p = self._seams_proc
        if p is not None and p.poll() is None:
            p.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=3)

    def _seams_ready(self, names: list[str]) -> None:
        """Paste screenshots added while the clean map was being built.

        Args:
            names: The screenshots the clean map was built from.
        """
        have = set(names)
        missing = [f for f in self.atlas.frames if f["name"] not in have]
        if missing and not self.paste_terrain(missing):
            self.load_terrain()

    def export_pngs(self) -> list[str]:
        """Write the map PNGs (<stem>_composite.png and _network.png) into the atlas's files folder.

        Returns:
            The files written.

        Raises:
            ValueError: With no atlas open.
        """
        with self._lock:  # atlas and path read together: an atlas opened meanwhile can't mix them
            atlas, path = self.atlas, self.path
            if not atlas or not path:
                raise ValueError("open an atlas first")
            builder.export(atlas, path)
        d = core.atlas_files(path)
        files = [str(p) for p in sorted(d.glob(f"{path.stem}_*.png")) if not p.name.endswith("_thumb.png")]
        self.events.log(f"map PNGs written in {d}")
        return files

    # ------------------------------------------------------------------ what the map shows (filters)
    def filters_changed(self, publish: bool = True) -> None:
        """Note that what the map shows changed (a filter, a hidden type, the model): vector tiles are made again.

        Args:
            publish: Tell the page (a "filters" event with the new version).
        """
        self.filter_version += 1
        self._source_sync("filter_version", "flags")
        self._vector = None
        self._vector_steps = None
        self._scene3d = None
        self._scene3d_steps = None
        if publish:
            self.events.publish("filters", self.filter_version)

    def _flags(self) -> dict:
        """Return the filter settings, read once.

        Returns:
            {"doubtful", "removed", "multi", "only_icons", "near", "freq", "hidden"}.
        """
        s = self.ui_settings()
        return {
            "doubtful": bool(s["layers"].get("Doubtful")),
            "removed": bool(s["layers"].get("Removed")),
            "multi": s["multi_only"],
            "only_icons": s["only_icon_maps"],
            "near": s["near_only"],
            "freq": float(s["style"].get("path_freq") or 0.0),
            "hidden": set(s["hidden_types"]),
        }

    def node_shown(self, n: dict, fl: dict, src: TileSource | None = None) -> bool:
        """Whether a map node passes the filters (removed map nodes never do).

        Args:
            n: Map node dict.
            fl: _flags().
            src: The tiles' source it is read from (None: the session as it is now).

        Returns:
            True when shown.
        """
        st = n["status"]
        if st == "removed" or (st == "doubtful" and not fl["doubtful"]):
            return False
        if fl["multi"] and n.get("seen", 1) < 2 and st != "icon":
            return False
        if fl["only_icons"]:
            shown = {icon_name(r) for r in n.get("icons", [])} - fl["hidden"]
            if not shown and not (
                "MapBossSpecial" in n.get("icons", [])
                and any(
                    t.startswith("Deadly Map Boss") and t not in fl["hidden"]
                    for t in (src or self).D.get("icon_types", [])
                )
            ):
                return False
        return True

    def path_shown(self, p: dict, node_ok: list[bool], fl: dict) -> bool:
        """Whether a path passes the filters (both its map nodes shown, enough screenshots drew it).

        Args:
            p: Path dict.
            node_ok: node_shown of every map node.
            fl: _flags().

        Returns:
            True when shown.
        """
        if fl["multi"] and p["frames"] < 2 and not p.get("abyss"):
            return False
        if fl["freq"] > 0 and path_share(p) < fl["freq"] - 1e-9:
            return False  # drawn by too few of the screenshots that show both maps
        return node_ok[p["a"]] and node_ok[p["b"]]

    def landmark_name(self, i: int, src: TileSource | None = None) -> str:
        """Return a landmark's name with the city type: "Vaal city", "Ezomyte city?" (? = guessed by look),
        "Locked Breach stronghold".

        Args:
            i: Landmark index in V["landmarks"].
            src: The tiles' source it is read from (None: the session as it is now).

        Returns:
            The name.
        """
        V, D = (src or self).V, (src or self).D
        lm = V["landmarks"][i]
        if i in D.get("locked", ()):
            return "Locked Breach stronghold"
        ct = D.get("city_type", {})
        if lm["kind"] == "City" and i in ct:
            t, how = ct[i]
            return f"{t} city" + ("?" if how == "look-alike" else "")
        return lm["kind"]

    def landmark_shown(self, i: int, fl: dict, src: TileSource | None = None) -> bool:
        """Whether a landmark passes the filters.

        Args:
            i: Landmark index.
            fl: _flags().
            src: The tiles' source it is read from (None: the session as it is now).

        Returns:
            True when shown.
        """
        V, D = (src or self).V, (src or self).D
        lm = V["landmarks"][i]
        if lm["status"].startswith("removed"):
            return fl["removed"]
        if lm["kind"] in fl["hidden"] or (fl["near"] and lm["kind"] != "City"):
            return False
        t = D.get("city_type", {}).get(i)
        return not t or f"{t[0]} city" not in fl["hidden"]

    def icon_visible(self, i: int, fl: dict, src: TileSource | None = None) -> bool:
        """Whether an icon passes the filters (its type ticked, and near a city when only those are shown).

        Args:
            i: Icon index.
            fl: _flags().
            src: The tiles' source it is read from (None: the session as it is now).

        Returns:
            True when shown.
        """
        V, D = (src or self).V, (src or self).D
        if icon_label(V["icons"][i]) in fl["hidden"]:
            return False
        if fl["near"]:
            v = D.get("icon_node", {}).get(i)
            return v is not None and v in D.get("near_city", {})
        return True

    # ------------------------------------------------------------------ map info and tiles
    def map_info(self) -> dict | None:
        """Return what the page's map needs besides tiles: grid, zoom range, bounds, versions, icon picture size.

        Returns:
            The info dict, or None without a map image.
        """
        # the versions as the tiles are made from them (_source): the page never asks for tiles newer than those
        src = self._source
        g = src.grid
        if g is None:
            return None
        zdeep = g.deepest(WEBMAP_SHARP_LEVEL)
        return {
            "grid": g.to_json(),
            "zmax": g.zmax,
            "zdeep": zdeep,
            "world": g.world,
            "offset": g.offset,
            # MapLibre shows 256 px raster tiles of level z at map zoom z - 1: sharpest at zdeep - 1, then stretched
            "maxzoom": zdeep - 1 + WEBMAP_OVERZOOM,
            "bounds": g.bounds(),
            # in every tile URL: this run of the app and the open atlas. The versions alone restart at every start
            # and are shared by every atlas, and the browser keeps tiles for a year, so another atlas's cached tiles
            # showed at some zooms (user; CodeRabbit)
            "tile_key": f"{SESSION_RUN}.{src.gen}",
            "terrain_version": src.terrain_version,
            "model_version": src.model_version,
            "filter_version": src.filter_version,
            "sprite": {
                "size": WEBMAP_ICON_SPRITE,
                "units": WEBMAP_ICON_UNITS,
                "min_px": WEBMAP_ICON_MIN_PX,
                "art": icon_art_version(),  # (in the pictures' URLs)
            },
        }

    def terrain_tile(self, z: int, x: int, y: int, wanted=None) -> bytes | None:
        """Return a ground tile as JPEG: the map image's levels, sharp ground past them.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            The JPEG bytes, or None where there is no ground.
        """
        return self._tile_from(self._tile_state, z, x, y, wanted)

    def pin_ground(self) -> None:
        """Keep the map image's tiling as it is now for the page's backdrop while jobs run (_tile_before; the worker
        calls this as a busy spell begins, under the session lock, and lets it go once idle). Its map image levels
        only: the sharp ground is cut from the live atlas's screenshots, which an Undo or the next add replaces, so
        an old-version sharp tile would mix new screenshots with the old placement (CodeRabbit); the backdrop asks
        for those levels only."""
        if self._tile_before is None:
            grid, raster, _sharp, version = self._tile_state
            self._tile_before = (grid, raster, None, version)

    def terrain_tile_for(self, z: int, x: int, y: int, asked: str, wanted=None) -> tuple[bytes | None, bool]:
        """Return a ground tile of the map image version its address names: the current one, or the one from before
        the jobs running now (pin_ground, the backdrop's, its map image levels), else the current one.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.
            asked: Its address's "v": "<tile key>-<map image version>" ("": none given, the current one).
            wanted: Whether the browser still waits for it (terrain_tile).

        Returns:
            (the JPEG bytes or None where there is no ground; whether it is of the address asked, so the browser may
            keep it under it: the whole address, this run of the app and this atlas included, as versions restart
            with every run and a tab outliving one asked with the old run's numbers, CodeRabbit).
        """
        state, before = self._tile_state, self._tile_before
        if not asked:
            return self._tile_from(state, z, x, y, wanted), True
        key, _, end = asked.rpartition("-")
        version = int(end) if end.isdigit() else None
        mine = key == f"{SESSION_RUN}.{self._source.gen}"  # (map_info's tile key)
        if (
            mine
            and version is not None
            and version != state[3]
            and before is not None
            and before[3] == version
            and before[0] is not None
            and z <= before[0].zmax  # (its map image levels: deeper, the current ground, not kept)
        ):
            state = before
        return self._tile_from(state, z, x, y, wanted), mine and state[3] == version

    def _tile_from(self, state: tuple, z: int, x: int, y: int, wanted=None) -> bytes | None:
        """terrain_tile, from one map image's tiling (_tile_state, read once by the caller)."""
        _grid, raster, sharp, version = state
        key = ("t", version, z, x, y)
        hit = self._tiles.get(key)
        if hit is not None:
            return hit or None
        if raster is None:
            return None
        if sharp is not None and sharp.has(z):
            if raster.pixels(raster.grid.zmax, x >> (z - raster.grid.zmax), y >> (z - raster.grid.zmax)) is None:
                data = None  # nothing under it at all: no screenshot there
            else:
                data = sharp.jpeg(z, x, y, wanted)
                if data is None:  # given up by the browser: built when asked again, not cached as empty
                    return None
        else:
            data = raster.jpeg(z, x, y)
        self._tiles.put(key, data or b"")
        return data

    def crop_jpeg(self, x: float, y: float, gen: int) -> bytes | None:
        """Return a small picture of the ground around an atlas point (Find's rows show the map node itself: user's
        mockup), from the map's own ground tiles (so shared with the map and its caches): the sharp ground when the
        map image alone is too coarse for it.

        Args:
            x: Atlas x.
            y: Atlas y.
            gen: The atlas generation the page asked for: another atlas's crop is never made or sent (the page's
                pictures carry it; checked again once made, a switch meanwhile drops it).

        Returns:
            JPEG bytes (WEBMAP_CROP_PX square), or None (another atlas, no map image, no ground there).
        """
        if gen != self.generation:
            return None
        # one map image's grid and tiles, read once: a map image put in meanwhile can't mix with it (no session lock:
        # jobs hold it long; CodeRabbit)
        state = self._tile_state
        g, raster, sharp, _version = state
        if g is None or raster is None:
            return None
        want = WEBMAP_CROP_PX / (2 * WEBMAP_CROP_UNITS)  # px per atlas unit wanted
        z = g.zmax
        while sharp is not None and sharp.has(z + 1) and g.scale * 2.0 ** (z - g.zmax) < want:
            z += 1
        f = 2.0 ** (z - g.zmax)
        wx, wy = g.world_px(x, y)
        half = WEBMAP_CROP_UNITS * g.scale * f  # px at level z
        cx, cy = wx * f, wy * f
        x0, y0 = int(math.floor(cx - half)), int(math.floor(cy - half))
        side = max(1, int(math.ceil(2 * half)))
        T = WEBMAP_TILE
        canvas = np.zeros((side, side, 3), np.uint8)
        found = False
        for ty in range(y0 // T, (y0 + side - 1) // T + 1):
            for tx in range(x0 // T, (x0 + side - 1) // T + 1):
                if tx < 0 or ty < 0:
                    continue
                data = self._tile_from(state, z, tx, ty)
                if not data:
                    continue
                tile = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if tile is None:
                    continue
                # the part of this tile in the crop
                ax0, ay0 = max(x0, tx * T), max(y0, ty * T)
                ax1, ay1 = min(x0 + side, (tx + 1) * T), min(y0 + side, (ty + 1) * T)
                if ax1 <= ax0 or ay1 <= ay0:
                    continue
                canvas[ay0 - y0 : ay1 - y0, ax0 - x0 : ax1 - x0] = tile[
                    ay0 - ty * T : ay1 - ty * T, ax0 - tx * T : ax1 - tx * T
                ]
                found = True
        if not found or gen != self.generation:
            return None
        small = cv2.resize(
            canvas,
            (WEBMAP_CROP_PX, WEBMAP_CROP_PX),
            interpolation=cv2.INTER_AREA if side > WEBMAP_CROP_PX else cv2.INTER_CUBIC,
        )
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, WEBMAP_JPEG_QUALITY])
        return buf.tobytes() if ok else None

    def vector_tile(self, z: int, x: int, y: int, replay: bool = False) -> bytes:
        """Return a vector tile (MVT) of what the filters show (vector_tile_made, without its address).

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.
            replay: Asked by the page tab playing the timelapse: its items carry their reveal step (while one is
                open). Every other tab gets the plain tiles (user: opening the timelapse in one tab changed them all,
                and a reload left the steps on).

        Returns:
            The tile's bytes (b"" when empty).
        """
        return self.vector_tile_made(z, x, y, replay)[0]

    def vector_tile_made(self, z: int, x: int, y: int, replay: bool = False) -> tuple[bytes, str | None]:
        """Return a vector tile and the address it was made for (_address): the page may ask with an older one.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.
            replay: Asked by the page tab playing the timelapse (vector_tile).

        Returns:
            (the tile's bytes, b"" when empty; its address, None without a map image).
        """
        steps = replay and self._source.replay is not None
        made = self._vector_made(steps)
        if made is None:
            return b"", None
        tiler = made[1]
        # kept under the versions of the tiler that made it: read again, they may name a newer one (CodeRabbit)
        key = ("v", *made[0], made[4], z, x, y)
        hit = self._tiles.get(key)
        if hit is None:
            hit = tiler.tile(z, x, y)
            self._tiles.put(key, hit)
        return hit, self._address(made)

    @staticmethod
    def _address(made: tuple) -> str:
        """The address a vector tile or the 3D scene made at these versions is asked for with: the page's "v" (its
        vectorVersion: map_info's tile key, then the model, filter and map image versions), and "&r=" the timelapse
        plan's token when it was made with the timelapse's steps (from the build itself: decided before it, a
        timelapse closed meanwhile labelled a build without steps with the timelapse's address, CodeRabbit).

        Args:
            made: (versions, what was made, grid, generation, made with steps) from _made.

        Returns:
            "<run>.<generation>-<model>-<filters>-<map image>" (+ "&r=<token>").
        """
        key, gen = made[0], made[3]
        return f"{SESSION_RUN}.{gen}-{key[0]}-{key[1]}-{key[2]}" + (f"&r={key[3]}" if made[4] else "")

    def _vector_tiler(self, steps: bool = False) -> VectorTiler | None:
        """Return the vector tiler of the current model, filters and map image (made on first use).

        Args:
            steps: The timelapse's tiler (items carry their reveal step), kept beside the plain one.

        Returns:
            The tiler, or None without a map image.
        """
        made = self._vector_made(steps)
        return made[1] if made is not None else None

    def _vector_made(self, steps: bool = False) -> tuple | None:
        """Return (versions, tiler, grid, generation, made with steps) of the current model, filters and map image,
        made once (_made).

        Args:
            steps: The timelapse's (items carry their reveal step), kept beside the plain one.

        Returns:
            The tuple, or None without a map image.
        """

        def build(src: TileSource) -> VectorTiler:
            """The tiler of what the filters show."""
            # without the 3D view's parts: built only when it asks (scene_3d). Built for every flat map too, they
            # were ~0.8 s of a big atlas's first tiles though never in them (user: what isn't shown shouldn't slow it)
            layers = self.vector_layers(src, steps, with_3d=False)
            for k in ("icon_rows", "solids"):
                layers.pop(k, None)
            dense = max(0, src.grid.zmax - 4)  # icons and labels are not drawn zoomed far out
            return VectorTiler(layers, src.grid, min_zoom={"icons": dense})

        return self._made("_vector_steps" if steps else "_vector", steps, build)

    def _scene_made(self, steps: bool = False) -> tuple | None:
        """Return (versions, 3D scene features, grid, generation, made with steps) of the current model, filters and
        map image, made
        once and only
        when the 3D view asks (the flat map's tiles never carry them): _made.

        The 3D view's icons and models aren't cut into tiles: the page gets them whole (scene_3d); read back from
        loaded tiles they were missing zoomed out, came twice at tile edges and were gathered again after every move
        (user: lag, popping).

        Args:
            steps: The timelapse's (items carry their reveal step), kept beside the plain one.

        Returns:
            The tuple, or None without a map image.
        """

        def build(src: TileSource) -> dict:
            """The 3D view's features."""
            layers = self.vector_layers(src, steps)
            return {"icon_rows": layers["icon_rows"], "solids": layers["solids"], "paths": layers["paths"]}

        return self._made("_scene3d_steps" if steps else "_scene3d", steps, build)

    def _made(self, slot: str, steps: bool, build: Callable[[TileSource], object]) -> tuple | None:
        """Return (versions, what `build` made, grid, generation, made with the timelapse's steps) for the tiles'
        source now (_source), kept in
        `slot`.

        Made from the source alone, never under the session lock: a job holds that lock for minutes, and the tiles
        asked for meanwhile waited for it and took all the browser's connections, so even the ground of a spot jumped
        to stayed black (user). The source's versions, grid and model belong together (it is replaced whole, in the
        same step as each change: _source_sync), so what is made is always what its versions say.

        Args:
            slot: The attribute it is kept in.
            steps: The timelapse's (items carry their reveal step).
            build: Makes it from the source.

        Returns:
            The tuple, or None without a map image.
        """
        src = self._source
        v = getattr(self, slot, None)
        if v is not None and v[0] == src.key(steps):
            return v
        with self._vector_lock:  # (one build at a time: two requests at once would each make the same)
            src = self._source  # the newest, a change while this waited included
            if src.grid is None:
                return None
            key = src.key(steps)
            v = getattr(self, slot, None)
            if v is not None and v[0] == key:
                return v
            # (with steps only when this source has them: a timelapse closed since the request decided leaves none)
            made = (key, build(src), src.grid, src.gen, steps and src.replay is not None)
            setattr(self, slot, made)
            return made

    def scene_3d(self, replay: bool = False) -> bytes:
        """The 3D view's icons, paths and models as JSON (scene_3d_made, without its address).

        Args:
            replay: For the tab playing the timelapse: each item carries the step it appears at.

        Returns:
            The JSON (scene_3d_made).
        """
        return self.scene_3d_made(replay)[0]

    def scene_3d_made(self, replay: bool = False) -> tuple[bytes, str | None]:
        """Return the 3D view's icons, paths and models as JSON, whole (what the filters show, in atlas units).

        Built from the same features the vector tiles are cut from, once per model / filter / map image version.

        Args:
            replay: For the tab playing the timelapse: each item carries the step it appears at.

        Returns:
            JSON {"icons": [[x, y, id, name, slot, lift, step, node]],
            "paths": [{"id", "strong", "abyss", "share", "step", "pts"}],
            "models": [{"rings", "colour", "base", "height" (metres), "ax", "ay", "step", "pick"}]} (step -1: from
            the start; pick: what a click on it selects, "node:<i>" / "landmark:<i>" / ""), and the address it was
            made for (_address; None without a map image).
        """
        steps = replay and self._source.replay is not None
        made = self._scene_made(steps)  # its own snapshot: the slot can be replaced meanwhile (CodeRabbit)
        if made is None:
            return b'{"icons": [], "paths": [], "models": []}', None
        key, scene, g, _gen, with_steps = made
        kept = getattr(self, "_scene", None)
        if kept is not None and kept[0] == (key, with_steps):
            return kept[1], self._address(made)

        def A(p) -> list[float]:  # world px at zmax -> atlas units
            return [round((p[0] - g.offset) / g.scale + g.x0, 1), round((p[1] - g.offset) / g.scale + g.y0, 1)]

        st = lambda pr: pr.get("step", -1)  # noqa: E731
        icons = [
            [*A(f["pts"][0]), f["props"]["id"], f["props"]["name"], float(f["props"]["slot"]), f["props"]["lift"],
             st(f["props"]), f["props"]["node"]]
            for f in scene["icon_rows"]
        ]  # fmt: skip
        paths = [
            {"id": f["props"]["id"], "strong": f["props"]["strong"], "abyss": f["props"]["abyss"],
             "share": f["props"]["share"], "step": st(f["props"]), "pts": [A(p) for p in f["pts"]]}
            for f in scene["paths"]
        ]  # fmt: skip
        models = [
            {"rings": [[A(p) for p in r] for r in f["rings"]], "colour": f["props"]["colour"],
             "base": f["props"]["base"], "height": f["props"]["height"], "ax": f["props"]["ax"],
             "ay": f["props"]["ay"], "step": st(f["props"]), "pick": f["props"].get("pick", "")}
            for f in scene["solids"]
        ]  # fmt: skip
        import json

        data = json.dumps({"icons": icons, "paths": paths, "models": models}, separators=(",", ":")).encode()
        self._scene = ((key, with_steps), data)
        return data, self._address(made)

    def vector_layers(self, src: TileSource, steps: bool = False, with_3d: bool = True) -> dict[str, list[dict]]:
        """Build the vector tile features of what the filters show (world px at zmax).

        Args:
            src: What they are made from (_source; it has a map image).
            steps: Give items their timelapse reveal step (while one is open).
            with_3d: Also the 3D view's parts (icon rows, models); without them icon_rows and solids stay empty.

        Returns:
            Layer name -> features: land, biomes, paths, removed, maps, icons, landmarks, bookmarks, solids.
        """
        # every path whatever "drawn by at least" says: each carries its share and the page hides the ones below it
        V, D, fl, grid = src.V, src.D, {**src.flags, "freq": 0.0}, src.grid
        nodes = V["nodes"]
        W = grid.world_px
        node_ok = [self.node_shown(n, fl, src) for n in nodes]
        potential = D.get("potential", {})
        rs = src.replay if steps else None  # the step each item appears at (the page filters)

        def step(kind: str, i: int) -> dict:
            """Return {"step": s} for an item while replaying, else {}."""
            if rs is None or i >= len(rs[kind]):
                return {}
            return {"step": round(float(rs[kind][i]), 3)}

        L: dict[str, list[dict]] = {k: [] for k in ("land", "biomes", "paths", "removed", "maps", "icons", "icon_rows",
                                                     "landmarks", "bookmarks", "solids")}  # fmt: skip
        for i, n in enumerate(nodes):
            if n["status"] == "removed":
                if fl["removed"] and not str(n.get("why", "")).startswith("joined"):
                    L["removed"].append({"kind": "point", "pts": [W(n["x"], n["y"])], "id": i, "props": {"id": i}})
                continue
            if not node_ok[i]:
                continue
            icons = sorted(set(n.get("icons") or []))
            pot = potential.get(i)
            L["maps"].append(
                {
                    "kind": "point",
                    "pts": [W(n["x"], n["y"])],
                    "id": i,
                    "props": {
                        "id": i,
                        "status": n["status"],
                        "fill": bgr_hex(icon_col(icons[0])) if icons else "",
                        "icons": "|" + "|".join(icons) + "|" if icons else "",
                        "tower": bool(n.get("tower")),
                        "biome": pot[0] if pot else "",
                        **step("node", i),
                    },
                }
            )
        for k, p in enumerate(V["paths"]):
            if not self.path_shown(p, node_ok, fl):
                continue
            a, b = nodes[p["a"]], nodes[p["b"]]
            line = p.get("line") or [[a["x"], a["y"]], [b["x"], b["y"]]]
            strong = p.get("seen_in", p["frames"]) >= 2 or bool(p.get("both_ends"))
            L["paths"].append(
                {
                    "kind": "line",
                    "pts": [W(x, y) for x, y in line],
                    "id": k,
                    "props": {
                        "id": k,
                        "abyss": bool(p.get("abyss")),
                        "strong": bool(strong),
                        "share": path_share(p),
                        **(
                            {"step": max(step("node", p["a"]).get("step", -1), step("node", p["b"]).get("step", -1))}
                            if rs
                            else {}
                        ),
                    },
                }
            )
        pts = D.get("icon_pts")
        # the 3D view's icons: at their map node, with their place in its row (-2 .. 2 in halves), so the page stands
        # them upright in a row above the node, as in the game (user: on the ground they shifted oddly and stacked)
        slot: dict[int, float] = {}
        rows: dict[int, list[int]] = {}
        for i, v in D.get("icon_node", {}).items():
            rows.setdefault(v, []).append(i)
        for members in rows.values():
            members.sort(key=lambda i: V["icons"][i]["x"])
            for k, i in enumerate(members):
                slot[i] = k - (len(members) - 1) / 2
        node_of = D.get("icon_node", {})
        shapes = self._solid_shapes(node_ok, src) if with_3d else []
        lift = self._model_tops(shapes)
        for i, ic in enumerate(V["icons"]):
            if not self.icon_visible(i, fl, src):
                continue
            v = node_of.get(i)
            at = (nodes[v]["x"], nodes[v]["y"]) if v is not None and v < len(nodes) else (ic["x"], ic["y"])
            if with_3d:
                L["icon_rows"].append(
                    {
                        "kind": "point",
                        "pts": [W(*at)],
                        "id": i,
                        "props": {
                            "id": i,
                            "name": ic["name"],
                            "slot": f"{slot.get(i, 0.0):g}",
                            # the top of the 3D model under it (pillar, tower, city), atlas units in steps of 10: the
                            # page stands the icon on top when the models are shown (user: city icons sat inside)
                            "lift": int(round(lift.get(v, 0.0) / 10) * 10) if v is not None else 0,
                            "node": -1 if v is None else v,  # (a selected map node rings its icon in 3D)
                            **step("icon", i),
                        },
                    }
                )
            x, y = pts[i] if pts is not None and i < len(pts) else (ic["x"], ic["y"])
            L["icons"].append(
                {
                    "kind": "point",
                    "pts": [W(x, y)],
                    "id": i,
                    "props": {"id": i, "name": ic["name"], "label": icon_label(ic), **step("icon", i)},
                }
            )
        for i, lm in enumerate(V["landmarks"]):
            if not self.landmark_shown(i, fl, src):
                continue
            L["landmarks"].append(
                {
                    "kind": "point",
                    "pts": [W(lm["x"], lm["y"])],
                    "id": i,
                    "props": {
                        "id": i,
                        "kind": lm["kind"],
                        "name": self.landmark_name(i, src),
                        "removed": lm["status"].startswith("removed"),
                        "locked": i in D.get("locked", ()),
                        **step("landmark", i),
                    },
                }
            )
        # (bookmarks: drawn by the page from its bookmark list, so hiding one doesn't make every tile again)
        # the vector ground: land where screenshots show it, and the city / stronghold biome areas (no icon makes one)
        for poly in self._land(src):
            L["land"].append({"kind": "polygon", "rings": [[W(x, y) for x, y in r] for r in poly], "props": {}})
        for kind, polys in biome_polygons(nodes, potential):
            for poly in polys:
                L["biomes"].append(
                    {"kind": "polygon", "rings": [[W(x, y) for x, y in r] for r in poly], "props": {"kind": kind}}
                )
        L["solids"] = self._solids(grid, shapes, rs) if with_3d else []
        return L

    def _land(self, src: TileSource) -> list:
        """Return the land polygons of the source's map image (webmap.shapes.land_polygons), made once per map image.

        Args:
            src: The tiles' source.

        Returns:
            Polygons in atlas units ([] without a map image).
        """
        if src.terrain is None:
            return []
        hit = getattr(self, "_land_cache", None)
        if hit is None or hit[0] != src.terrain_version:
            canvas, _w, origin = src.terrain
            hit = self._land_cache = (src.terrain_version, land_polygons(canvas, origin))
        return hit[1]

    def _solid_shapes(self, node_ok: list[bool], src: TileSource | None = None) -> list[dict]:
        """The 3D view's extruded shapes (webmap.solids) in atlas units, each with its anchor and pick.

        Args:
            node_ok: node_shown of every map node.
            src: The tiles' source they are made from (None: the session as it is now).

        Returns:
            Shapes ("rings", "base", "top", "colour", "anchor", "pick": ("node" | "landmark", index)).
        """
        src = src or self._source
        V, D = src.V, src.D
        nodes = V["nodes"]
        fl = src.flags
        shapes = []
        for i, nd in enumerate(nodes):
            if not node_ok[i]:
                continue
            icons = sorted(set(nd.get("icons") or []))
            colour = bgr_hex(icon_col(icons[0])) if icons else "#9aa0a8"
            shapes += [
                dict(sh, anchor=(nd["x"], nd["y"]), pick=("node", i))
                for sh in map_pillar(nd["x"], nd["y"], icons, colour, i)
            ]
        ct, locked = D.get("city_type", {}), D.get("locked", set())
        # every Tower landmark, shown or not: a map node at one is that tower (hidden by "near only", its map node
        # drew a tower of its own in its place: CodeRabbit)
        towers = [
            (lm["x"], lm["y"])
            for lm in V["landmarks"]
            if lm["kind"] == "Tower" and not str(lm.get("status", "")).startswith("removed")
        ]
        for k, lm in enumerate(V["landmarks"]):
            if str(lm.get("status", "")).startswith("removed"):
                continue
            if not self.landmark_shown(k, fl, src):  # hidden type (e.g. Tower): no model either (CodeRabbit)
                continue
            # a click on it selects the map node it marks (its city, hall, tower or boss map: user), else itself
            v = D.get("landmark_node", {}).get(k)
            pick = ("node", v) if v is not None else ("landmark", k)
            shapes += [
                dict(sh, anchor=(lm["x"], lm["y"]), pick=pick)
                for sh in structure(lm["kind"], lm["x"], lm["y"], ct.get(k, ("", ""))[0], k in locked)
            ]
        for i, nd in enumerate(nodes):  # map nodes marked as towers with no Tower landmark: a tower too
            if (
                node_ok[i]
                and "Tower" not in fl["hidden"]  # (hiding towers hid the landmark, then this one showed)
                and nd.get("tower")
                and all(math.hypot(nd["x"] - tx, nd["y"] - ty) > WEBMAP_TOWER_SAME for tx, ty in towers)
            ):
                shapes += [
                    dict(sh, anchor=(nd["x"], nd["y"]), pick=("node", i)) for sh in structure("Tower", nd["x"], nd["y"])
                ]
        return shapes

    def _solids(self, grid: Grid, shapes: list[dict], rs: dict | None = None) -> list[dict]:
        """Turn the 3D view's shapes (_solid_shapes) into features with heights in the metres MapLibre extrudes by.

        MapLibre extrudes in metres and a Mercator metre is smaller the further from the equator, so each shape's
        heights are turned into metres at its own latitude: the models keep their proportions in atlas units.

        Args:
            grid: The map image's grid.
            shapes: The shapes.
            rs: The timelapse's steps (replay_steps), or None: each model then carries the step it appears at (the
                models stood from the start).

        Returns:
            Polygon features (props colour, base and height in metres, node for map pillars).
        """
        out = []
        for sh in shapes:
            lat = math.radians(grid.lnglat(*sh["rings"][0][0])[1])
            metres = 40075016.686 * math.cos(lat) / grid.world * grid.scale  # metres per atlas unit there
            props = {
                "colour": sh["colour"],
                "base": round(sh["base"] * metres, 2),
                "height": round(sh["top"] * metres, 2),
            }
            if "node" in sh:
                props["node"] = sh["node"]
            kind, idx = sh.get("pick", ("", -1))
            if kind:
                props["pick"] = f"{kind}:{idx}"
                if rs is not None and idx < len(rs[kind]):
                    props["step"] = round(float(rs[kind][idx]), 3)
            # the structure's centre (atlas units): the page's own 3D layer sizes a model around it
            ax, ay = sh.get("anchor", sh["rings"][0][0])
            props["ax"], props["ay"] = round(float(ax), 1), round(float(ay), 1)
            out.append(
                {"kind": "polygon", "rings": [[grid.world_px(x, y) for x, y in r] for r in sh["rings"]], "props": props}
            )
        return out


def _end_process(proc: subprocess.Popen) -> None:
    """Stop a child process that won't be used, and release its pipe (left open, CodeRabbit)."""
    proc.terminate()
    if proc.stdout is not None:
        proc.stdout.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
