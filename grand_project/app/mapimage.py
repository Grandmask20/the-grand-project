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
import math
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np

from grand_project import builder, core
from grand_project import cities as atlas_cities
from grand_project import logs as atlas_log
from grand_project.webmap.constants import (
    WEBMAP_FOG_DARK,
    WEBMAP_ICON_MIN_PX,
    WEBMAP_ICON_SPRITE,
    WEBMAP_ICON_UNITS,
    WEBMAP_MASK_MAX,
    WEBMAP_OVERZOOM,
    WEBMAP_SHARP_LEVEL,
    WEBMAP_TOWER_SAME,
)
from grand_project.webmap.shapes import biome_polygons, land_polygons
from grand_project.webmap.sharp import SharpTiles
from grand_project.webmap.solids import map_pillar, structure
from grand_project.webmap.tiles import Grid, RasterTiler, VectorTiler

from .constants import TERRAIN_PIXELS, TILE_CACHE
from .icons import bgr_hex, icon_col, icon_label, icon_name

LOG = atlas_log.get("app")
SESSION_RUN = os.urandom(4).hex()  # this run of the app: part of every tile URL (map_info "tile_key")


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


class MapImageMixin:
    """AtlasSession mixin: the map image, Fix seams and the map's tiles (see the module docstring)."""

    # ------------------------------------------------------------------ state
    def _init_mapimage(self) -> None:
        """Start with no map image."""
        self._tiles = _LRU(TILE_CACHE)
        self._seams_proc = None
        self._seams_stopped = False
        self._terrain_job = 0
        self.filter_version = 0
        self._vector = None  # (key, VectorTiler)
        self._vector_lock = threading.Lock()
        self._reset_mapimage()

    def _reset_mapimage(self) -> None:
        """Forget the map image (another atlas, or none)."""
        self.terrain = None  # (canvas, weight, origin)
        self.labels = None  # (ownership map, screenshot names) of the clean map
        self.terrain_version = getattr(self, "terrain_version", 0) + 1
        self.grid: Grid | None = None
        self._raster: RasterTiler | None = None
        self._sharp: SharpTiles | None = None
        self._ground = None
        self._ground_for = None
        self._tiles.clear()

    # ------------------------------------------------------------------ the map image
    def load_terrain(self, cities: bool = True, background: bool = True) -> None:
        """Show the stitched map: from the cache next to the atlas when it matches, else built in the background.

        Args:
            cities: Rebuild the model when the map image arrives (its biomes follow the ground).
            background: Build on a background thread (False: now, on this thread; tests).
        """
        if not self.atlas or not self.atlas.frames:
            self._reset_mapimage()
            self.events.publish("terrain", self.terrain_version)
            return
        png, npz = core.map_image_files(self.path)
        key = self.atlas.terrain_key()
        try:
            with np.load(npz) as meta:
                if str(meta["key"]) == key:
                    import cv2

                    canvas = cv2.imdecode(np.fromfile(str(png), np.uint8), cv2.IMREAD_COLOR)
                    weight = meta["weight"].astype(np.float32)
                    origin = tuple(float(v) for v in meta["origin"])
                    labels = (meta["labels"], [str(n) for n in meta["names"]]) if "labels" in meta.files else None
                    if canvas is not None and canvas.shape[:2] == weight.shape:
                        self.set_terrain(canvas, weight, origin, save=False, labels=labels, cities=cities)
                        return
        except Exception:
            LOG.debug("map image cache not usable, rebuilding", exc_info=True)
        self._terrain_job += 1
        job, atlas = self._terrain_job, self.atlas
        self.events.set_progress("building the map image (first time for this atlas)…")

        def work():
            """Build the map image and show it (background thread)."""
            try:
                canvas, origin, weight = atlas.composite(max_pixels=TERRAIN_PIXELS, with_weight=True)
                if job == self._terrain_job and atlas is self.atlas:
                    self.set_terrain(canvas, weight, origin)
            except Exception as e:
                LOG.exception("map image could not be built")
                self.events.log(f"map image could not be built: {e}")
            finally:
                self.events.set_progress(None)

        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def set_terrain(self, canvas, weight, origin, save: bool = True, labels=None, cities: bool = True) -> None:
        """Show a new map image: keep it, set up its grid and tilers and, when asked, write its cache files.

        Args:
            canvas: BGR map image.
            weight: Its coverage weight (0 where no screenshot is).
            origin: (x0, y0, scale): atlas (x, y) is image px ((x - x0) * scale, (y - y0) * scale).
            save: Write the cache files and the atlas card picture.
            labels: (ownership map, screenshot names) of the clean map, or None.
            cities: Rebuild the model (biomes follow the ground).
        """
        origin = tuple(float(v) for v in origin)
        with self._lock:
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
            self._tiles.clear()
            self._vector = None
        if save and self.path:
            key, path = self.atlas.terrain_key(), self.path

            def write():
                """Write the map image cache files and the atlas card picture (background thread)."""
                try:
                    png, npz = core.map_image_files(path)
                    core.write_png(png, canvas, "map image")
                    self.write_thumb(path, canvas)
                    extra = {} if labels is None else {"labels": labels[0], "names": np.array(labels[1])}
                    np.savez_compressed(
                        npz, key=key, origin=np.array(origin, float), weight=weight.astype(np.float16), **extra
                    )
                except Exception:
                    LOG.warning("map image cache could not be saved", exc_info=True)

            threading.Thread(target=write, daemon=True).start()
        elif self.path and not self.thumb_exists(self.path):
            threading.Thread(target=self.write_thumb, args=(self.path, canvas), daemon=True).start()
        if cities and self.V.get("nodes"):
            self.rebuild_model()  # the biomes follow the ground now
        self.events.publish("terrain", self.terrain_version)

    def _sharp_folder(self) -> Path | None:
        """Return the folder sharp tiles of the current screenshots are kept in (older ones are removed).

        Returns:
            <stem>_files/<stem>_sharp/<key>, or None with no atlas.
        """
        if not self.path or not self.atlas:
            return None
        base = core.atlas_files(self.path) / (self.path.stem + "_sharp")
        key = self.atlas.terrain_key()[:16] + ("c" if self.labels is not None else "")
        if base.exists():
            for d in base.iterdir():  # tiles of other screenshots / placements: never shown again
                if d.is_dir() and d.name != key:
                    shutil.rmtree(d, ignore_errors=True)
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
        if self.terrain is None:
            return None
        w, h = min(int(w), WEBMAP_MASK_MAX), min(int(h), WEBMAP_MASK_MAX)
        canvas, weight, (ox, oy, sc) = self.terrain
        # grid cell (c, r) -> map image px ((x0 + c * cell - ox) * sc, ...)
        A = np.array([[cell * sc, 0, (x0 - ox) * sc], [0, cell * sc, (y0 - oy) * sc]], np.float32)
        grey = canvas.mean(axis=2).astype(np.float32) if canvas.ndim == 3 else canvas.astype(np.float32)
        wt = (weight > 0).astype(np.float32)
        flags = cv2.INTER_AREA | cv2.WARP_INVERSE_MAP
        g = cv2.warpAffine(grey, A, (w, h), flags=flags, borderValue=0.0)
        k = cv2.warpAffine(wt, A, (w, h), flags=flags, borderValue=0.0)
        return ((g > WEBMAP_FOG_DARK) & (k > 0.5)).astype(np.uint8).tobytes()

    # ------------------------------------------------------------------ Fix seams
    def fix_seams(self) -> None:
        """Build the clean map (core.seams) in a separate process: map nodes and icons whole, seams where the
        ground matches. Progress lines become the progress box; the clean map replaces the map image when ready.

        Raises:
            ValueError: With no screenshots, or when it is already running.
        """
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots in this atlas")
        if self.seams_running():
            raise ValueError("Fix seams is already running")
        tmp = Path(tempfile.mkdtemp(prefix="grand_seams_"))
        src, out, err = tmp / "atlas.pkl", tmp / "clean.npz", tmp / "errors.txt"
        with self._lock:
            src.write_bytes(pickle.dumps(self.atlas))
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
        self._seams_proc, self._seams_stopped = proc, False
        atlas = self.atlas
        self.events.set_progress("fixing seams: building the clean map...")
        self.events.log("Fix seams: building the clean map in the background")
        self.events.publish("seams", True)

        def watch():
            """Pass the process's progress lines on, then show the clean map (background thread)."""
            for line in proc.stdout:
                if line.strip() and line.strip() != "done":
                    self.events.set_progress(line.strip())
            proc.wait()
            try:
                if proc.returncode == 0 and out.exists() and atlas is self.atlas:
                    with np.load(out) as r:
                        canvas, weight, labels = r["canvas"], r["weight"], r["labels"]
                        origin = tuple(float(v) for v in r["origin"])
                        names = [str(n) for n in r["names"]]
                    self.set_terrain(canvas, weight, origin, labels=(labels, names))
                    self.events.log("Fix seams: clean map ready")
                    self._seams_ready(names)
                elif self._seams_stopped:
                    pass  # stopped: dropped quietly
                elif proc.returncode != 0:
                    text = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    LOG.error("clean map could not be built: %s", " | ".join(text[-30:]))
                    self.events.log(f"clean map could not be built: {text[-1] if text else proc.returncode}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
                self._seams_proc = None
                self.events.set_progress(None)
                self.events.publish("seams", False)

        threading.Thread(target=watch, daemon=True).start()

    def seams_running(self) -> bool:
        """Tell whether Fix seams is running.

        Returns:
            True while its process runs.
        """
        p = self._seams_proc
        return p is not None and p.poll() is None

    def stop_seams(self) -> None:
        """Stop a running Fix seams (its result is then dropped quietly)."""
        p = self._seams_proc
        if p is not None and p.poll() is None:
            self._seams_stopped = True
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
        if not self.atlas or not self.path:
            raise ValueError("open an atlas first")
        with self._lock:
            builder.export(self.atlas, self.path)
        d = core.atlas_files(self.path)
        files = [str(p) for p in sorted(d.glob(f"{self.path.stem}_*.png")) if not p.name.endswith("_thumb.png")]
        self.events.log(f"map PNGs written in {d}")
        return files

    # ------------------------------------------------------------------ what the map shows (filters)
    def filters_changed(self, publish: bool = True) -> None:
        """Note that what the map shows changed (a filter, a hidden type, the model): vector tiles are made again.

        Args:
            publish: Tell the page (a "filters" event with the new version).
        """
        self.filter_version += 1
        self._vector = None
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

    def node_shown(self, n: dict, fl: dict) -> bool:
        """Whether a map node passes the filters (removed map nodes never do).

        Args:
            n: Map node dict.
            fl: _flags().

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
                and any(t.startswith("Deadly Map Boss") and t not in fl["hidden"] for t in self.D.get("icon_types", []))
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
        if fl["freq"] > 0 and not p.get("abyss") and p.get("seen_in", 0) < fl["freq"] * max(1, p.get("frames", 0)):
            return False  # drawn by too few of the screenshots that show both maps
        return node_ok[p["a"]] and node_ok[p["b"]]

    def landmark_name(self, i: int) -> str:
        """Return a landmark's name with the city type: "Vaal city", "Ezomyte city?" (? = guessed by look),
        "Locked Breach stronghold".

        Args:
            i: Landmark index in V["landmarks"].

        Returns:
            The name.
        """
        lm = self.V["landmarks"][i]
        if i in self.D.get("locked", ()):
            return "Locked Breach stronghold"
        ct = self.D.get("city_type", {})
        if lm["kind"] == "City" and i in ct:
            t, how = ct[i]
            return f"{t} city" + ("?" if how == "look-alike" else "")
        return lm["kind"]

    def landmark_shown(self, i: int, fl: dict) -> bool:
        """Whether a landmark passes the filters.

        Args:
            i: Landmark index.
            fl: _flags().

        Returns:
            True when shown.
        """
        lm = self.V["landmarks"][i]
        if lm["status"].startswith("removed"):
            return fl["removed"]
        if lm["kind"] in fl["hidden"] or (fl["near"] and lm["kind"] != "City"):
            return False
        t = self.D.get("city_type", {}).get(i)
        return not t or f"{t[0]} city" not in fl["hidden"]

    def icon_visible(self, i: int, fl: dict) -> bool:
        """Whether an icon passes the filters (its type ticked, and near a city when only those are shown).

        Args:
            i: Icon index.
            fl: _flags().

        Returns:
            True when shown.
        """
        if icon_label(self.V["icons"][i]) in fl["hidden"]:
            return False
        if fl["near"]:
            v = self.D.get("icon_node", {}).get(i)
            return v is not None and v in self.D.get("near_city", {})
        return True

    # ------------------------------------------------------------------ map info and tiles
    def map_info(self) -> dict | None:
        """Return what the page's map needs besides tiles: grid, zoom range, bounds, versions, icon picture size.

        Returns:
            The info dict, or None without a map image.
        """
        g = self.grid
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
            "tile_key": f"{SESSION_RUN}.{self.generation}",
            "terrain_version": self.terrain_version,
            "model_version": self.model_version,
            "filter_version": self.filter_version,
            "sprite": {"size": WEBMAP_ICON_SPRITE, "units": WEBMAP_ICON_UNITS, "min_px": WEBMAP_ICON_MIN_PX},
        }

    def terrain_tile(self, z: int, x: int, y: int) -> bytes | None:
        """Return a ground tile as JPEG: the map image's levels, sharp ground past them.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            The JPEG bytes, or None where there is no ground.
        """
        key = ("t", self.terrain_version, z, x, y)
        hit = self._tiles.get(key)
        if hit is not None:
            return hit or None
        raster, sharp = self._raster, self._sharp
        if raster is None:
            return None
        if sharp is not None and sharp.has(z):
            if raster.pixels(raster.grid.zmax, x >> (z - raster.grid.zmax), y >> (z - raster.grid.zmax)) is None:
                data = None  # nothing under it at all: no screenshot there
            else:
                data = sharp.jpeg(z, x, y)
        else:
            data = raster.jpeg(z, x, y)
        self._tiles.put(key, data or b"")
        return data

    def vector_tile(self, z: int, x: int, y: int) -> bytes:
        """Return a vector tile (MVT) of what the filters show.

        Args:
            z: Tile level.
            x: Tile column.
            y: Tile row.

        Returns:
            The tile's bytes (b"" when empty).
        """
        tiler = self._vector_tiler()
        if tiler is None:
            return b""
        key = ("v", self.model_version, self.filter_version, self.terrain_version, z, x, y)
        hit = self._tiles.get(key)
        if hit is not None:
            return hit
        data = tiler.tile(z, x, y)
        self._tiles.put(key, data)
        return data

    def _vector_tiler(self) -> VectorTiler | None:
        """Return the vector tiler of the current model, filters and map image (made on first use).

        Returns:
            The tiler, or None without a map image.
        """
        key = (self.model_version, self.filter_version, self.terrain_version)
        v = self._vector
        if v is not None and v[0] == key:
            return v[1]
        with self._vector_lock:
            v = self._vector
            if v is not None and v[0] == key:
                return v[1]
            if self.grid is None:
                return None
            with self._lock:
                layers = self.vector_layers(self.grid)
            g = self.grid
            dense = max(0, g.zmax - 4)  # icons, models and labels are not drawn zoomed far out
            tiler = VectorTiler(layers, g, min_zoom={"icons": dense, "solids": dense})
            self._vector = (key, tiler)
            return tiler

    def vector_layers(self, grid: Grid) -> dict[str, list[dict]]:
        """Build the vector tile features of what the filters show (world px at zmax).

        Args:
            grid: The map image's grid.

        Returns:
            Layer name -> features: land, biomes, paths, removed, maps, icons, landmarks, bookmarks, solids.
        """
        V, D, fl = self.V, self.D, self._flags()
        nodes = V["nodes"]
        W = grid.world_px
        node_ok = [self.node_shown(n, fl) for n in nodes]
        potential = D.get("potential", {})
        rs = self.replay_steps()  # while the replay is open: the step each item appears at (the page filters)

        def step(kind: str, i: int) -> dict:
            """Return {"step": s} for an item while replaying, else {}."""
            if rs is None or i >= len(rs[kind]):
                return {}
            return {"step": round(float(rs[kind][i]), 3)}

        L: dict[str, list[dict]] = {k: [] for k in ("land", "biomes", "paths", "removed", "maps", "icons",
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
                        **({"step": max(step("node", p["a"])["step"], step("node", p["b"])["step"])} if rs else {}),
                    },
                }
            )
        pts = D.get("icon_pts")
        for i, ic in enumerate(V["icons"]):
            if not self.icon_visible(i, fl):
                continue
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
            if not self.landmark_shown(i, fl):
                continue
            L["landmarks"].append(
                {
                    "kind": "point",
                    "pts": [W(lm["x"], lm["y"])],
                    "id": i,
                    "props": {
                        "id": i,
                        "kind": lm["kind"],
                        "name": self.landmark_name(i),
                        "removed": lm["status"].startswith("removed"),
                        "locked": i in D.get("locked", ()),
                        **step("landmark", i),
                    },
                }
            )
        for i, bm in enumerate(self.atlas.bookmarks if self.atlas else []):
            if self.bookmark_shown(bm):
                L["bookmarks"].append(
                    {"kind": "point", "pts": [W(bm["x"], bm["y"])], "id": i, "props": {"id": i, "name": bm["name"]}}
                )
        # the vector ground: land where screenshots show it, biome areas from the biomes and the influence icons
        for poly in self._land():
            L["land"].append({"kind": "polygon", "rings": [[W(x, y) for x, y in r] for r in poly], "props": {}})
        for kind, polys in biome_polygons(nodes, potential, lambda i: nodes[i].get("icons") or []):
            for poly in polys:
                L["biomes"].append(
                    {"kind": "polygon", "rings": [[W(x, y) for x, y in r] for r in poly], "props": {"kind": kind}}
                )
        L["solids"] = self._solids(grid, node_ok)
        return L

    def _land(self) -> list:
        """Return the land polygons of the map image (webmap.shapes.land_polygons), made once per map image.

        Returns:
            Polygons in atlas units ([] without a map image).
        """
        if self.terrain is None:
            return []
        hit = getattr(self, "_land_cache", None)
        if hit is None or hit[0] != self.terrain_version:
            canvas, _w, origin = self.terrain
            hit = self._land_cache = (self.terrain_version, land_polygons(canvas, origin))
        return hit[1]

    def _solids(self, grid: Grid, node_ok: list[bool]) -> list[dict]:
        """Build the 3D view's extruded shapes (webmap.solids), with heights in the metres MapLibre extrudes by.

        MapLibre extrudes in metres and a Mercator metre is smaller the further from the equator, so each shape's
        heights are turned into metres at its own latitude: the models keep their proportions in atlas units.

        Args:
            grid: The map image's grid.
            node_ok: node_shown of every map node.

        Returns:
            Polygon features (props colour, base and height in metres, node for map pillars).
        """
        V, D = self.V, self.D
        nodes = V["nodes"]
        shapes = []
        for i, nd in enumerate(nodes):
            if not node_ok[i]:
                continue
            icons = sorted(set(nd.get("icons") or []))
            colour = bgr_hex(icon_col(icons[0])) if icons else "#9aa0a8"
            shapes += map_pillar(nd["x"], nd["y"], icons, colour, i)
        towers = []
        ct, locked = D.get("city_type", {}), D.get("locked", set())
        for k, lm in enumerate(V["landmarks"]):
            if str(lm.get("status", "")).startswith("removed"):
                continue
            if lm["kind"] == "Tower":
                towers.append((lm["x"], lm["y"]))
            shapes += structure(lm["kind"], lm["x"], lm["y"], ct.get(k, ("", ""))[0], k in locked)
        for i, nd in enumerate(nodes):  # map nodes marked as towers with no Tower landmark: a tower too
            if (
                node_ok[i]
                and nd.get("tower")
                and all(math.hypot(nd["x"] - tx, nd["y"] - ty) > WEBMAP_TOWER_SAME for tx, ty in towers)
            ):
                shapes += structure("Tower", nd["x"], nd["y"])
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
            out.append(
                {"kind": "polygon", "rings": [[grid.world_px(x, y) for x, y in r] for r in sh["rings"]], "props": props}
            )
        return out
