"""app.session: the open atlas and everything the app does with it.

One AtlasSession lives in the server. It holds the open atlas, the model the map shows (view model: map nodes,
paths, icons, landmarks, with the biomes worked out), the map image, the background worker that adds screenshots,
auto-add, Fix seams, undo, bookmarks, hand edits and debug marks. The browser asks for things through the HTTP API
(app.server) and hears about changes through Events (log, progress, "model" / "terrain" versions, questions).

Each part lives in its own file as a mixin: library (known atlases, folders),
mapimage (map image, Fix seams, tiles), adding (the worker: add, drop, retry, undo, re-check), watch (auto-add),
edits (landmarks, biomes, city types, locked strongholds), bookmarks, query (search, details, screenshots of a
spot), debug (debug marks), replay (timelapse plan, colour by).
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np

from grand_project import cities as atlas_cities
from grand_project import core
from grand_project import finalize as atlas_finalize
from grand_project import logs as atlas_log

from .adding import AddingMixin
from .bookmarks import BookmarksMixin
from .constants import POTENTIAL_TYPES, STYLE_DEFAULT, VERSION
from .debug import DebugMixin
from .edits import EditsMixin
from .events import Events
from .icons import icon_label, icon_rows
from .library import LibraryMixin
from .mapimage import MapImageMixin
from .model import view_model
from .query import QueryMixin
from .replay_data import ReplayMixin
from .settings import load_settings, save_settings
from .watch import WatchMixin

LOG = atlas_log.get("app")

LAYER_DEFAULTS = {
    "Terrain": True,
    "Paths": True,
    "Nodes": True,
    "Icons": True,
    "Landmarks": True,
    "Bookmarks": True,
    "Labels": True,
    "Doubtful": False,
    "Removed": False,
    "Recent additions": True,
    "City & stronghold biomes": True,
}


class AtlasSession(
    LibraryMixin,
    MapImageMixin,
    AddingMixin,
    WatchMixin,
    EditsMixin,
    BookmarksMixin,
    QueryMixin,
    DebugMixin,
    ReplayMixin,
):
    """The open atlas and its background work (see the module docstring)."""

    def __init__(self, settings: dict | None = None, events: Events | None = None, worker: bool = True):
        """Start with no atlas open.

        Args:
            settings: The app settings (default: read from user_data).
            events: Where to publish what happens (default: a new Events).
            worker: Start the background worker thread (tests run jobs on their own thread instead).
        """
        self.settings = load_settings() if settings is None else settings
        self.events = events or Events()
        self._lock = threading.RLock()
        self.atlas: core.Atlas | None = None
        self.path: Path | None = None
        self.V: dict = {"nodes": [], "paths": [], "icons": [], "landmarks": [], "final": None}
        self.D: dict = {}  # derived from V: biomes, icon rows, type counts, footprints (rebuild_model)
        self.model_version = 0
        self.generation = 0  # bumped whenever another atlas is opened, made or closed (tile URLs carry it)
        self._closing = False
        self._extra_groups: set[str] = set()  # bookmark groups made empty (kept until the app closes)
        self._replay_on = False
        self._plan = None
        self._replay_steps = None
        self.replay_token = 0  # bumped with every timelapse plan: the timelapse tab's vector tile URLs carry it
        self._init_mapimage()
        self._init_adding(start=worker)
        self._init_watch()

    # ------------------------------------------------------------------ settings shared with the page
    def save_settings(self) -> None:
        """Write the settings file."""
        save_settings(self.settings)

    def ui_settings(self) -> dict:
        """Return the settings the page shows and changes: layers, filters, style, hidden types, replay.

        Returns:
            {"layers", "multi_only", "only_icon_maps", "near_only", "hidden_types", "style", "replay", "ui"}.
        """
        s = self.settings
        return {
            "layers": {**LAYER_DEFAULTS, **s.get("layers", {})},
            "multi_only": bool(s.get("multi_only", False)),
            "only_icon_maps": bool(s.get("only_icon_maps", False)),
            "near_only": bool(s.get("near_only", False)),
            "hidden_types": sorted(s.get("icon_hidden", [])),
            "style": {**STYLE_DEFAULT, **s.get("style", {})},
            "replay": s.get("replay", {}),
            "ui": s.get("ui", {}),
        }

    def set_ui_settings(self, changes: dict) -> dict:
        """Change some of the page's settings and save them; filters that change what the map shows bump the
        filter version (the map's tiles are made again).

        Args:
            changes: Any of the keys ui_settings returns ("style" / "replay" / "ui" / "layers" are merged).

        Returns:
            The settings after the change (ui_settings).
        """
        s = self.settings
        before = self._flags()
        for k in ("layers", "style", "replay", "ui"):
            if k in changes and isinstance(changes[k], dict):
                s[k] = {**s.get(k, {}), **changes[k]}
        for k in ("multi_only", "only_icon_maps", "near_only"):
            if k in changes:
                s[k] = bool(changes[k])
        if "hidden_types" in changes:
            s["icon_hidden"] = sorted(set(changes["hidden_types"]))
        if "style" in changes and changes["style"].get("reset"):
            s["style"] = {}
        self.save_settings()
        # what Find and the map show (not how they look): logged (user: the log said little)
        words = {"multi_only": "only what 2+ screenshots show", "only_icon_maps": "only maps with a ticked icon",
                 "near_only": "only potential city maps"}  # fmt: skip
        for k, label in words.items():
            if k in changes:
                self.events.log(f"Find: {label} {'on' if s[k] else 'off'}")
        if "hidden_types" in changes:
            self.events.log(f"Find: {len(s['icon_hidden'])} type(s) hidden")
        if self._flags() != before:  # what the tiles hold changed (not only how the page draws it)
            self.filters_changed()
        return self.ui_settings()

    # ------------------------------------------------------------------ open / new / save / close
    def open_atlas(self, p) -> None:
        """Open an atlas file and show it.

        Unsaved changes of the open atlas are saved first. An atlas with screenshots but no atlas-wide result
        (made before the check existed) is checked now. Auto-add follows the atlas.

        Args:
            p: Path of the atlas .json file.

        Raises:
            ValueError: When the file cannot be read as an atlas, or work is still running.
        """
        p = Path(p)
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        try:
            atlas = core.Atlas.load(p)
        except Exception as e:
            LOG.exception(f"could not read atlas {p}")
            raise ValueError(f"could not read {p}: {e}") from e
        switching = self.path is None or p.resolve() != self.path.resolve()
        # the open atlas's background work stops first (auto-add restarts below; Fix seams' result would be for the
        # atlas object read before, also when the same file is opened again)
        self.stop_watch()
        if self.seams_running():
            self.stop_seams()
            self.events.log("Fix seams stopped: another atlas was opened")
        self.save()
        with self._lock:
            if self.working():  # a job slipped in meanwhile
                raise ValueError("wait until the screenshots being added are done")
            if switching:
                self._forget_session()
                self._drop_stale_snapshots(p)
                self._reset_mapimage()  # the other atlas's map image never shows for this one
            self.atlas, self.path = atlas, p
            self._new_generation()
        maps = len((atlas.final or {}).get("nodes", []))
        LOG.info(f"opened atlas {p}: {len(atlas.frames)} screenshots, {maps} maps")
        name = p.stem if p.stem != "atlas" else p.parent.name
        if self.events.scope and self.events.scope != str(p.resolve()):
            self.events.log(f"switched to atlas {name}")
        self.events.set_scope(str(p.resolve()))
        self.events.log(f"opened atlas {name} ({p}): {len(atlas.frames)} screenshots, {maps} maps")
        self.settings["last_atlas"] = str(p)
        if atlas.frames and atlas.final is None:
            self.events.log("this atlas predates the atlas-wide check: running it now")
            try:
                with self._lock:
                    atlas_finalize.finalize(atlas, log=self.events.log)
                    atlas.save(p)
            except Exception as e:
                LOG.exception("atlas-wide check failed")
                self.events.log(f"atlas-wide check failed: {e}")
        self._after_load()
        missing = [f["name"] for f in atlas.frames if not Path(f["path"]).exists()]
        if missing:
            self.events.log(f"screenshots not found (terrain missing there): {', '.join(missing[:20])}" +
                            (f" and {len(missing) - 20} more" if len(missing) > 20 else ""))  # fmt: skip
        if self.settings.get("watch_on"):
            self.start_watch()  # auto-add follows the atlas: its own folder, or the one picked for it

    def new_atlas(self, p) -> None:
        """Create an empty atlas at a path and open it.

        Args:
            p: Path of the new atlas .json file (its folder is made if missing).

        Raises:
            ValueError: When work is still running or the file exists.
        """
        p = Path(p)
        if p.suffix.lower() != ".json":
            p = p / "atlas.json" if not p.suffix else p.with_suffix(".json")
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        if p.exists():
            raise ValueError(f"{p} already exists: open it instead")
        self.stop_watch()
        self.stop_seams()
        self.save()
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self.working():
                raise ValueError("wait until the screenshots being added are done")
            self._forget_session()
            self._reset_mapimage()
            self.atlas, self.path = core.Atlas(), p
            self._new_generation()
            self.atlas.save(p)
        self.settings["last_atlas"] = str(p)
        self.events.set_scope(str(p.resolve()))
        self._after_load()
        self.events.log(f"new atlas: {p}")
        if self.settings.get("watch_on"):
            self.start_watch()  # auto-add follows the new atlas too (it was stopped above and left off)

    def _new_generation(self) -> None:
        """Start a new atlas generation (call under the lock, with the new atlas set): its model starts empty.

        The model (map nodes, paths, icons, screenshot outlines) is rebuilt right after, but anything asked for
        meanwhile came from the atlas open before: the new atlas's screenshots with the old one's outlines (user:
        the old atlas's times-seen picture blinked on the new one).
        """
        self.generation += 1
        self.V = {"nodes": [], "paths": [], "icons": [], "landmarks": [], "final": None}
        self.D = {}
        self.model_version += 1

    def owns(self, gen: int) -> bool:
        """Tell whether work started under atlas generation `gen` may still change things (call under the lock).

        Every background job (map image, Fix seams, saves, exports, stronghold search, replay fog) remembers the
        generation it started under and applies its result only while that is still the open atlas: work for
        another atlas was installed into the one opened meanwhile (user, CodeRabbit).

        Args:
            gen: The generation the work started under.

        Returns:
            True while that atlas is still the open one.
        """
        return gen == self.generation

    def save(self) -> None:
        """Save the open atlas (if any)."""
        if self.atlas is not None and self.path is not None:
            with self._lock:
                self.atlas.save(self.path)

    def close(self) -> None:
        """Close the open atlas: stop auto-add and Fix seams, save, and clear everything that belonged to it.

        Raises:
            ValueError: While screenshots are being added (they would land in no atlas).
        """
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        self.stop_watch()
        self.stop_seams()
        self.save()
        with self._lock:
            self._forget_session()
            self.atlas, self.path = None, None
            self._new_generation()
            self._reset_mapimage()
        if self.events.scope:
            self.events.log("closed the atlas")
        self.events.set_scope("")
        self.events.publish("atlas", self.atlas_summary())
        self.events.publish("model", self.model_version)

    def shutdown(self) -> None:
        """Stop everything before the app exits: auto-add, Fix seams, queued jobs; save the atlas and settings."""
        self._closing = True
        self.stop_watch()
        self.stop_seams()
        self._drop_queued_jobs()
        self.wait_idle(timeout=30)
        self.save()
        self.save_settings()

    def _after_load(self) -> None:
        """Refresh everything after an atlas was opened or created: map image, model, locked strongholds."""
        self.load_terrain(cities=False)  # the cached map image first: the model's biomes then use its ground
        self.rebuild_model()
        self.scan_locks()
        if self.path:
            self.remember_atlas(self.path)
        self.save_settings()
        self.events.publish("atlas", self.atlas_summary())
        self.events.set_status(f"opened {self.path.name}" if self.path else "")

    # ------------------------------------------------------------------ the model
    def rebuild_model(self) -> None:
        """Rebuild the view model from the atlas and everything derived from it: icon rows, type counts, locked
        strongholds, city types, biomes, screenshot footprints. Publishes a "model" event with the new version."""
        with self._lock:
            V = view_model(self.atlas) if self.atlas else {"nodes": [], "paths": [], "icons": [], "landmarks": []}
            D: dict = {}
            counts: dict[str, int] = {}
            for ic in V["icons"]:
                counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
            D["icon_types"] = sorted(counts, key=lambda k: (k == "Unidentified badge", k))
            try:
                found = atlas_cities.biomes(self.atlas, V, ground=self.ground()) if self.atlas else None
            except Exception:
                LOG.exception("city types / biomes failed")
                self.events.log("city types / biomes failed (details in the log file)")
                found = None
            if found:
                V["landmarks"] = found["landmarks"]
                for k in ("potential", "near_city", "blocked", "icon_node", "city_type", "locked"):
                    D[k] = found[k]
            else:
                D.update(potential={}, near_city={}, blocked={}, icon_node={}, city_type={}, locked=set())
            for lm in V["landmarks"]:
                if not lm["status"].startswith("removed"):
                    counts[lm["kind"]] = counts.get(lm["kind"], 0) + 1
            for _i, (t, _how) in D["city_type"].items():
                counts[f"{t} city"] = counts.get(f"{t} city", 0) + 1
            for _v, (lab, st) in D["potential"].items():
                if st:
                    k = potential_kind(lab)
                    counts[k] = counts.get(k, 0) + 1
            D["place_types"] = [
                k
                for k in (
                    "City",
                    "Ezomyte city",
                    "Vaal city",
                    "Faridun city",
                    "Hall",
                    "Tower",
                    "Breach stronghold",
                    *POTENTIAL_TYPES,
                )  # fmt: skip
                if k in counts
            ]
            D["counts"] = counts
            D["node_pts"] = np.array([[n["x"], n["y"]] for n in V["nodes"]], float).reshape(-1, 2)
            D["icon_pts"] = icon_rows(V["nodes"], V["icons"], D["icon_node"]) if V["icons"] else np.zeros((0, 2))
            D["footprints"] = [core.footprint(self.atlas, f) for f in self.atlas.frames] if self.atlas else []
            self.V, self.D = V, D
            self.model_version += 1
        if getattr(self, "_replay_on", False) and self.atlas and self.atlas.frames:
            self._replan()  # screenshots added while the replay is open
        self.filters_changed(publish=False)
        self.events.publish("model", self.model_version)

    # ------------------------------------------------------------------ what the page shows of the atlas
    def atlas_summary(self) -> dict | None:
        """Return the open atlas's name, path and counts (None with no atlas open).

        Returns:
            {"name", "path", "maps", "icons", "shots", "landmarks", "bookmarks"} or None.
        """
        if self.atlas is None or self.path is None:
            return None
        N = self.V["nodes"]
        return {
            "name": self.path.stem if self.path.stem != "atlas" else self.path.parent.name,
            "path": str(self.path),
            "maps": sum(1 for n in N if n["status"] != "removed"),
            "icons": len(self.V["icons"]),
            "shots": len(self.atlas.frames),
            "landmarks": sum(1 for lm in self.V["landmarks"] if not lm["status"].startswith("removed")),
            "bookmarks": len(self.atlas.bookmarks),
        }

    def state(self) -> dict:
        """Return everything the page needs to draw its frame: the atlas, versions, work in progress, auto-add,
        undo, recently added / waiting lists, open questions, status and the last log lines.

        Returns:
            The state dict (JSON-able).
        """
        return {
            "version": VERSION,
            "atlas": self.atlas_summary(),
            "model_version": self.model_version,
            "terrain_version": self.terrain_version,
            "filter_version": self.filter_version,
            "busy": self.working(),
            "generation": self.generation,
            "progress": self.events.progress,
            "status": self.events.status,
            "watch": self.watch_state(),
            "undo": [e["names"] for e in self._undo],
            "recent": list(reversed(self.recent)),
            "waiting": self.waiting_list(),
            "seams": self.seams_running(),
            "questions": self.events.open_questions(),
            "log": list(self.events.log_lines)[-300:],
            "log_scope": self.events.scope,
        }

    def _forget_session(self) -> None:
        """Clear undo / recently added / waiting: they belong to the atlas they were made in."""
        self._forget_adding()
        self._extra_groups = set()
        self._replay_on, self._plan, self._replay_steps = False, None, None
        self._fog = None


def potential_kind(label: str) -> str:
    """Return the Find type a biome's potential map is listed under.

    Args:
        label: Biome label, e.g. "Vaal city" or "Breach stronghold".

    Returns:
        "Potential stronghold map" or "Potential city map".
    """
    return "Potential stronghold map" if label == "Breach stronghold" else "Potential city map"


def dist(a, b) -> float:
    """Distance between two (x, y) points.

    Args:
        a: (x, y).
        b: (x, y).

    Returns:
        The distance.
    """
    return math.hypot(a[0] - b[0], a[1] - b[1])


__all__ = ["AtlasSession", "potential_kind", "dist"]
