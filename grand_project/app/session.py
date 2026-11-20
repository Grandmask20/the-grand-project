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
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from grand_project import cities as atlas_cities
from grand_project import core
from grand_project import finalize as atlas_finalize
from grand_project import logs as atlas_log

from .adding import AddingMixin
from .atlaslock import AtlasLock
from .bookmarks import BookmarksMixin
from .constants import (
    LANDMARK_NODE_REACH,
    LANDMARK_NODE_REACH_STRONGHOLD,
    POTENTIAL_TYPES,
    SHUTDOWN_WAIT,
    STYLE_DEFAULT,
    VERSION,
)
from .debug import DebugMixin
from .edits import EditsMixin
from .events import Events
from .icons import icon_label, icon_rows
from .library import LibraryMixin
from .mapimage import MapImageMixin
from .model import view_model
from .parts import Parts
from .query import QueryMixin
from .replay_data import ReplayMixin
from .settings import load_settings, save_settings
from .updater import UpdatesMixin
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


@dataclass(frozen=True)
class Opened:
    """The open atlas as one record, swapped whole when another is opened, made or closed (AtlasSession._switch).

    Work takes it once when it starts, and gets every part of one atlas from it: the atlas, its file, its
    generation (`owns`) and its log.
    """

    atlas: core.Atlas | None
    path: Path | None
    gen: int
    scope: str  # its log's key in the Log tab ("" for none)


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
    UpdatesMixin,
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
        # refuses a page change meant for an atlas no longer open (app/atlaslock.py)
        self._lock = AtlasLock(lambda: self.opened.gen)
        self.opened = Opened(None, None, 0, "")  # the open atlas (atlas, path, generation, log): one record
        self.V: dict = {"nodes": [], "paths": [], "icons": [], "landmarks": [], "final": None}
        self.D: dict = {}  # derived from V: biomes, icon rows, type counts, footprints (rebuild_model)
        self.model_version = 0
        self.parts = Parts()  # the map's parts (map image, model) and how far each is: the page's loading cover
        self.opening: str | None = None  # the atlas being opened at start (its name), shown on the page meanwhile
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
        if s.get("style", {}).get("map_style") == "hidden":
            # the "hidden" map style left the View tab (user: the same as unticking Maps): saved that way, it becomes
            # the Maps switch off, kept from the next save on
            s["style"]["map_style"] = "circles"
            s.setdefault("layers", {})["Nodes"] = False
        if s.get("layers", {}).get("Doubtful"):
            # Doubtful left the layer buttons (user: room for Routes): saved on, it would stay on with no way off
            s["layers"]["Doubtful"] = False
        return {
            "layers": {**LAYER_DEFAULTS, **s.get("layers", {})},
            "multi_only": bool(s.get("multi_only", False)),
            "only_icon_maps": bool(s.get("only_icon_maps", False)),
            "near_only": bool(s.get("near_only", False)),
            "hidden_types": sorted(s.get("icon_hidden", [])),
            "style": _style(s),
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
        hidden_before = set(s.get("icon_hidden", []))
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
        # every change you make, in one line of the Log tab (user: "every user made change should be listed")
        self.events.log(f"Changed: {settings_change_text(changes, hidden_before)}")
        if tile_flags(self._flags()) != tile_flags(before):  # what the tiles hold changed (not how the page draws it)
            self.filters_changed()
        return self.ui_settings()

    # ------------------------------------------------------------------ open / new / save / close
    def open_atlas(self, p, expect_gen: int | None = None) -> None:
        """Open an atlas file and show it.

        Unsaved changes of the open atlas are saved first. An atlas with screenshots but no atlas-wide result
        (made before the check existed) is checked now. Auto-add follows the atlas.

        Args:
            p: Path of the atlas .json file.
            expect_gen: Open it only while this is still the generation (the app's start opening the last atlas in
                the background: an atlas opened on the page meanwhile stays, CodeRabbit). None: always.

        Raises:
            ValueError: When the file cannot be read as an atlas, or work is still running.
        """
        p = Path(p)
        if expect_gen is not None and not self.owns(expect_gen):
            return
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        try:
            atlas = core.Atlas.load(p)
        except Exception as e:
            LOG.exception(f"could not read atlas {p}")
            raise ValueError(f"could not read {p}: {e}") from e
        switching = self.path is None or p.resolve() != self.path.resolve()
        # the open atlas's background work stops first (auto-add restarts below; Fix seams' result would be for the
        # atlas object read before, also when the same file is opened again). Not for the app's start (expect_gen):
        # nothing of its own is open yet, so any work running belongs to an atlas opened on the page meanwhile, and
        # stopping it there cancelled that atlas's Fix seams (CodeRabbit)
        if expect_gen is None:
            self.stop_watch()
            if self.seams_running() or self.seams_waiting():
                self.stop_seams()
                self.events.log("Fix seams stopped: another atlas was opened")
            self.save()
        name = p.stem if p.stem != "atlas" else p.parent.name
        with self._lock:
            if expect_gen is not None and not self.owns(expect_gen):  # another atlas opened while this one loaded
                return
            if self.working():  # a job slipped in meanwhile
                self._resume_watch()  # (stopped above for a switch that doesn't happen: CodeRabbit)
                raise ValueError("wait until the screenshots being added are done")
            if switching:
                self._forget_session()
                self._drop_stale_snapshots(p)
                self._reset_mapimage()  # the other atlas's map image never shows for this one
            before, now = self.opened, self._switch(atlas, p)
            # in the same step as the switch: set after it, an older load finishing late made itself the atlas
            # opened at the next start (CodeRabbit)
            self.settings["last_atlas"] = str(p)
            if before.scope and before.scope != now.scope:
                self.events.log(f"switched to atlas {name}", before.scope)
        maps = len((atlas.final or {}).get("nodes", []))
        self.events.log(f"opened atlas {name} ({p}): {len(atlas.frames)} screenshots, {maps} maps", now.scope)
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
                self._resume_watch()  # (stopped above for a switch that doesn't happen: CodeRabbit)
                raise ValueError("wait until the screenshots being added are done")
            self._forget_session()
            self._reset_mapimage()
            now = self._switch(core.Atlas(), p)
            now.atlas.save(p)
        self.settings["last_atlas"] = str(p)
        self._after_load()
        self.events.log(f"new atlas: {p}", now.scope)
        if self.settings.get("watch_on"):
            self.start_watch()  # auto-add follows the new atlas too (it was stopped above and left off)

    def _switch(self, atlas: core.Atlas | None, p: Path | None) -> Opened:
        """Make `atlas` (at `p`; None: none) the open one, as a new generation (call under the lock).

        The only place the open atlas changes: its record (atlas, path, generation, log) is swapped whole, so work
        that took the record never mixes one atlas's parts with another's. Read field by field, a switch between
        the reads gave a job atlas A's screenshots with B's generation, or A's log lines in B's log (CodeRabbit,
        many times over).

        The model (map nodes, paths, icons, screenshot outlines) starts empty and is rebuilt right after: anything
        asked for meanwhile came from the atlas open before (user: the old atlas's times-seen picture blinked on the
        new one).

        Returns:
            The new record.
        """
        scope = str(p.resolve()) if p is not None else ""
        self.opened = Opened(atlas, p, self.opened.gen + 1, scope)
        self.parts.reset(self.opened.gen)
        self.V = {"nodes": [], "paths": [], "icons": [], "landmarks": [], "final": None}
        self.D = {}
        self.model_version += 1
        self.events.set_scope(scope)
        return self.opened

    @property
    def atlas(self) -> core.Atlas | None:
        """The open atlas (None: none)."""
        return self.opened.atlas

    @property
    def path(self) -> Path | None:
        """The open atlas's file."""
        return self.opened.path

    @property
    def generation(self) -> int:
        """The open atlas's generation: bumped whenever another is opened, made or closed (tile URLs carry it)."""
        return self.opened.gen

    def _resume_watch(self) -> None:
        """Start auto-add again on the open atlas when it is on (after a stop for a switch that was refused)."""
        if self.atlas is not None and self.settings.get("watch_on"):
            self.start_watch()

    def owns(self, job: Opened | int) -> bool:
        """Tell whether work started for an atlas may still change things (call under the lock).

        Every background job (map image, Fix seams, saves, exports, stronghold search, replay fog) takes the open
        atlas's record (`opened`) when it starts, works on that record's atlas, logs into its log, and applies its
        result only while it is still the open one: work for another atlas was installed into the one opened
        meanwhile (user, CodeRabbit).

        Args:
            job: The record the work took, or its generation.

        Returns:
            True while that atlas is still the open one.
        """
        return (job.gen if isinstance(job, Opened) else job) == self.opened.gen

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
            before = self.opened
            self._switch(None, None)
            self._reset_mapimage()
            if before.scope:
                self.events.log("closed the atlas", before.scope)
        self.events.publish("atlas", self.atlas_summary())
        self.events.publish("model", self.model_version)

    def shutdown(self) -> bool:
        """Stop everything before the app exits: auto-add, Fix seams, queued jobs, open questions (answered No, so
        a job waiting on one ends); then save the atlas and settings.

        Returns:
            True when the work running ended in time; False when it was cut off, which the log says (the wait's
            outcome was ignored, as if all work had finished: GPT audit).
        """
        self._closing = True
        self.stop_watch()
        self.stop_seams()
        self._drop_queued_jobs()
        if n := self.events.end_questions():
            self.events.log(f"closing: {n} open question(s) answered No")
        done = self.wait_idle(timeout=SHUTDOWN_WAIT)
        if not done:
            LOG.warning("closing while a job still runs: cut off")
            self.events.log(
                f"closing: the work still running after {SHUTDOWN_WAIT:.0f} s was cut off; what it had not saved yet "
                "is lost (the atlas is saved as it is now)"
            )
        self.save()
        self.save_settings()
        return done

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
        gen = self.generation
        self.parts.start("model", gen)
        try:
            self._rebuild_model(gen)
        except Exception as e:
            self.parts.fail("model", f"{type(e).__name__}: {e}", gen)  # (it only reached the log: user)
            raise
        self.parts.done("model", gen)
        self.filters_changed(publish=False)
        self.events.publish("model", self.model_version)

    def _rebuild_model(self, gen: int) -> None:
        """The work of rebuild_model, beating the model part between its steps.

        Args:
            gen: The generation it was started for.
        """
        with self._lock:
            V = view_model(self.atlas) if self.atlas else {"nodes": [], "paths": [], "icons": [], "landmarks": []}
            self.parts.beat("model", gen)
            D: dict = {}
            counts: dict[str, int] = {}
            for ic in V["icons"]:
                counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
            D["icon_types"] = sorted(counts, key=lambda k: (k == "Unidentified badge", k))
            try:
                found = atlas_cities.biomes(self.atlas, V, ground=self.ground()) if self.atlas else None
                self.parts.beat("model", gen)
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
            D["landmark_node"] = landmark_nodes(V["nodes"], V["landmarks"], D["locked"])
            self.V, self.D = V, D
            self.model_version += 1
            # screenshots added while the replay is open: replanned in the same locked step (checked apart, a
            # close between the check and the replan made the rebuild fail after it said the model was ready,
            # CodeRabbit)
            if getattr(self, "_replay_on", False) and self.atlas and self.atlas.frames:
                self._replan()

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
        opened = self.opened  # read first: a switch meanwhile shows as another generation, never a mix (CodeRabbit)
        return {
            "version": VERSION,
            "atlas": self.atlas_summary(),
            "model_version": self.model_version,
            "terrain_version": self.terrain_version,
            "filter_version": self.filter_version,
            "busy": self.working(),
            "generation": opened.gen,
            "progress": self.events.progress,
            "status": self.events.status,
            "watch": self.watch_state(),
            "undo": [e["names"] for e in self._undo],
            "recent": list(reversed(self.recent)),
            "waiting": self.waiting_list(),
            "seams": self.seams_running() or self.seams_waiting(),  # (queued counts: Stop takes it off)
            "questions": self.events.open_questions(),
            "log": list(self.events.log_lines)[-300:],
            "log_scope": opened.scope,
            "opening": self.opening,
        }

    def _forget_session(self) -> None:
        """Clear undo / recently added / waiting: they belong to the atlas they were made in."""
        self._forget_adding()
        self._extra_groups = set()
        self._replay_on, self._plan, self._replay_steps = False, None, None
        self._fog = None


# how a settings key reads in the log (others: their own name)
_WORDS = {
    "multi_only": "Find: only what 2+ screenshots show",
    "only_icon_maps": "Find: only maps with a ticked icon",
    "near_only": "Find: only potential city maps",
    "path_freq": "paths drawn by at least",
    "path_width": "path width",
    "path_style": "path style",
    "icon_size": "icon size",
    "icon_style": "icon style",
    "map_size": "map size",
    "map_style": "map style",
    "age_tint": "colour by",
    "side_width": "side panel width",
}


def _say(v) -> str:
    """A setting's value as the log says it: on / off, 35% for a share, else as it is."""
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def _style(s: dict) -> dict:
    """The saved style over the defaults, without settings that are gone ("ov_towers": the tower picture, left with
    its switch: the 3D view shows towers, user and banner).

    Args:
        s: The settings.

    Returns:
        The style the page gets.
    """
    style = {**STYLE_DEFAULT, **s.get("style", {})}
    style.pop("ov_towers", None)
    return style


def settings_change_text(changes: dict, hidden_before: set) -> str:
    """Say a settings change in one log line: "Paths layer off, paths drawn by at least 35%, types shown: Breach".

    Args:
        changes: The change the page sent (set_ui_settings).
        hidden_before: The hidden types before it (only what changed is named).

    Returns:
        The line.
    """
    parts = []
    for k, v in changes.items():
        if k == "hidden_types":
            now = set(v)
            shown, hidden = sorted(hidden_before - now), sorted(now - hidden_before)
            for word, names in (("types shown", shown), ("types hidden", hidden)):
                if names:
                    parts.append(
                        f"{word}: " + ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
                    )
        elif k == "layers" and isinstance(v, dict):
            parts += [f"{kk} layer {_say(vv)}" for kk, vv in v.items()]
        elif k == "style" and isinstance(v, dict) and v.get("reset"):
            parts.append("styles reset")
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if kk == "player":  # (I'm here)
                    parts.append(
                        f"your position map #{vv['node']}" if isinstance(vv, dict) else "your position forgotten"
                    )
                    continue
                share = kk == "path_freq" and isinstance(vv, (int, float)) and not isinstance(vv, bool)
                val = f"{round(100 * vv)}%" if share else _say(vv)
                parts.append(f"{_WORDS.get(kk, kk.replace('_', ' '))} {val}")
        else:
            parts.append(f"{_WORDS.get(k, k)} {_say(v)}")
    return ", ".join(parts) or "nothing"


def tile_flags(fl: dict) -> dict:
    """The filters the map's tiles hold: all but the paths' "drawn by at least" share, which the page applies itself
    (each path carries its share), so moving that slider makes no tile again (user: it lagged, each step remade every
    tile and the 3D scene).

    Args:
        fl: _flags().

    Returns:
        The filters without "freq".
    """
    return {k: v for k, v in fl.items() if k != "freq"}


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


__all__ = ["AtlasSession", "Opened", "potential_kind", "dist"]


def landmark_nodes(nodes: list[dict], landmarks: list[dict], locked=()) -> dict[int, int]:
    """Find the map node each landmark marks: the nearest live map node within reach (a locked stronghold has none).

    A click on a landmark's 3D model selects this map node (user: clicking a city's citadel didn't light up its map).

    Args:
        nodes: The view model's map nodes ("x", "y", "status").
        landmarks: The view model's landmarks ("x", "y", "kind", "status").
        locked: Indexes of locked strongholds: they stand apart, not at a map node (one nearby was picked: CodeRabbit).

    Returns:
        Landmark index -> map node index.
    """
    live = [i for i, n in enumerate(nodes) if n.get("status") != "removed"]
    if not live or not landmarks:
        return {}
    from scipy.spatial import cKDTree

    tree = cKDTree(np.array([[nodes[i]["x"], nodes[i]["y"]] for i in live], float))
    out = {}
    for k, lm in enumerate(landmarks):
        if str(lm.get("status", "")).startswith("removed") or k in locked:
            continue
        reach = LANDMARK_NODE_REACH_STRONGHOLD if lm.get("kind") == "Breach stronghold" else LANDMARK_NODE_REACH
        d, j = tree.query([lm["x"], lm["y"]])
        if d <= reach:
            out[k] = live[int(j)]
    return out
