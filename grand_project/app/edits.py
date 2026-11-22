"""app.edits: part of AtlasSession (a mixin; see app/session.py): hand edits kept in the atlas file.

Maps deleted or added (atlas.map_edits), landmarks changed, added or deleted (atlas.landmark_edits), city types
set by hand, biomes drawn with the lasso
(atlas.biome_edits), and the search for locked Breach strongholds (the hand badge) in new screenshots.
"""

from __future__ import annotations

import math
import threading

import cv2
import numpy as np

from grand_project import cities as atlas_cities
from grand_project import logs as atlas_log

from .atlaslock import atlas_edit
from .constants import EDIT_SPOT, LANDMARK_KINDS, MAP_EDIT_REACH

LOG = atlas_log.get("app")

BIOMES = [*(f"{t} city" for t in atlas_cities.TYPES), "Breach stronghold"]


class EditsMixin:
    """AtlasSession mixin: hand edits (see the module docstring)."""

    def _need_atlas(self) -> None:
        """Raise when no atlas is open.

        Raises:
            ValueError: With no atlas open.
        """
        if not self.atlas:
            raise ValueError("open an atlas first")

    def _edited(self, msg: str) -> None:
        """Save the atlas after a hand edit, log it and rebuild the model.

        Args:
            msg: What changed (log line).
        """
        self.events.log(msg)  # (into the log file too: written here as well, each edit was in it twice)
        if self.path:
            with self._lock:
                self.atlas.save(self.path)
        self.rebuild_model()

    @atlas_edit
    def set_landmark(self, x: float, y: float, kind: str, on: str = "landmark") -> None:
        """Change / add (kind) or delete (kind "") the landmark at x, y; an older edit within EDIT_SPOT is replaced.

        Args:
            x: Atlas x.
            y: Atlas y.
            kind: A landmark kind (LANDMARK_KINDS), or "" to delete.
            on: "landmark" (a landmark was edited) or "map" (a map was made into a landmark).

        Raises:
            ValueError: With no atlas open or an unknown kind.
        """
        self._need_atlas()
        if kind and kind not in LANDMARK_KINDS:
            raise ValueError(f"unknown landmark kind: {kind}")
        with self._lock:
            self.atlas.landmark_edits = [
                e for e in self.atlas.landmark_edits if math.hypot(e["x"] - x, e["y"] - y) >= EDIT_SPOT
            ]
            self.atlas.landmark_edits.append({"x": round(x, 1), "y": round(y, 1), "kind": kind, "on": on})
            if not kind:  # a deleted city keeps no hand-set type
                atlas_cities.set_type(self.atlas, x, y, None)
        self._edited(f"landmark at ({x:.0f}, {y:.0f}) " + (f"is now a {kind}" if kind else "deleted"))

    @atlas_edit
    def edit_map(self, x: float, y: float, op: str, kind: str = "") -> None:
        """Delete the map at x, y, or add one there (user: ghost maps from detection, maps it missed).

        Delete: a map added by hand there goes (its edit with it); any other map is marked deleted by you, and a
        landmark standing on it is deleted too. Add: a map deleted by hand there comes back, its landmark as it was;
        else a map is added (a landmark of `kind` with it: a City, a Hall, a Tower...).

        Args:
            x: Atlas x.
            y: Atlas y.
            op: "remove" or "add".
            kind: For "add": a landmark kind (LANDMARK_KINDS) to put on it, or "" for a plain map.

        Raises:
            ValueError: With no atlas open, an unknown op or kind, no map to delete there, or a map already there.
        """
        self._need_atlas()
        if op not in ("remove", "add"):
            raise ValueError(f"unknown map edit: {op}")
        if kind and (op != "add" or kind not in LANDMARK_KINDS):
            raise ValueError(f"unknown landmark kind: {kind}")
        near = lambda e: math.hypot(e["x"] - x, e["y"] - y) < MAP_EDIT_REACH  # noqa: E731
        with self._lock:
            edits = self.atlas.map_edits
            # the maps shown there now, nearest first (the first found could be a neighbour: CodeRabbit)
            live = sorted(
                (i for i, n in enumerate(self.V["nodes"]) if n.get("status") != "removed" and near(n)),
                key=lambda i: math.hypot(self.V["nodes"][i]["x"] - x, self.V["nodes"][i]["y"] - y),
            )
            if op == "remove":
                if not live:
                    raise ValueError("there is no map there to delete")
                n = self.V["nodes"][live[0]]
                # the add that made this map (or one a check found there since) goes: the nearest to it, not every add
                # near the click (a neighbour you added went too: CodeRabbit)
                to_n = lambda e: math.hypot(e["x"] - n["x"], e["y"] - n["y"])  # noqa: E731
                added = sorted((e for e in edits if e["op"] == "add" and to_n(e) < MAP_EDIT_REACH), key=to_n)[:1]
                self.atlas.map_edits = [e for e in edits if e not in added]
                # the landmark standing on it goes with it (a false City on a ghost map): the landmark edits this
                # takes away and makes are kept in the delete, so bringing the map back puts them back as they were
                # (its City came back with it no more: self review)
                dropped: list[dict] = []
                made: list[dict] = []
                for k, v in self.D.get("landmark_node", {}).items():
                    lm = self.V["landmarks"][k]
                    if v == live[0] and not lm["status"].startswith("removed"):
                        own = [
                            e
                            for e in self.atlas.landmark_edits
                            if math.hypot(e["x"] - lm["x"], e["y"] - lm["y"]) < EDIT_SPOT
                        ]
                        self.atlas.landmark_edits = [e for e in self.atlas.landmark_edits if e not in own]
                        dropped += own
                        # one put there by hand just goes (a delete with nothing at its spot would reach a landmark
                        # next to it); a detected one is marked deleted, also when an edit had changed its kind (a
                        # Hall brought back as a City stayed a Hall: CodeRabbit)
                        if not lm.get("added"):
                            e = {"x": round(lm["x"], 1), "y": round(lm["y"], 1), "kind": "", "on": "landmark"}
                            self.atlas.landmark_edits.append(e)
                            made.append(e)
                # a delete is kept unless the map shown is the one you added (its add just goes); one a check found
                # since, where you had added one, needs it (it stayed: CodeRabbit)
                if n.get("origin") != "by you":
                    rm = {"x": round(n["x"], 1), "y": round(n["y"], 1), "op": "remove"}
                    self.atlas.map_edits.append(
                        rm
                        | ({"landmarks_dropped": dropped} if dropped else {})
                        | ({"landmarks_made": made} if made else {})
                    )
                what = f"map #{live[0]} deleted"
            else:
                deleted = [e for e in edits if e["op"] == "remove" and near(e)]
                if live and not deleted:
                    raise ValueError("there is a map there already")
                self.atlas.map_edits = [e for e in edits if e not in deleted]
                # a deleted map brought back: its landmark edits as they were before the delete
                for d in deleted:
                    made = d.get("landmarks_made", [])
                    self.atlas.landmark_edits = [e for e in self.atlas.landmark_edits if e not in made]
                    self.atlas.landmark_edits += [
                        e for e in d.get("landmarks_dropped", []) if e not in self.atlas.landmark_edits
                    ]
                if not deleted:
                    self.atlas.map_edits.append({"x": round(x, 1), "y": round(y, 1), "op": "add"})
                if kind:
                    self.atlas.landmark_edits = [
                        e for e in self.atlas.landmark_edits if math.hypot(e["x"] - x, e["y"] - y) >= EDIT_SPOT
                    ]
                    self.atlas.landmark_edits.append({"x": round(x, 1), "y": round(y, 1), "kind": kind, "on": "map"})
                what = ("deleted map brought back" if deleted else "map added") + (f" as a {kind}" if kind else "")
        self._edited(f"{what} at ({x:.0f}, {y:.0f})")

    @atlas_edit
    def set_city_type(self, i: int, typ: str | None) -> None:
        """Set a city's type by hand (None: automatic again).

        Args:
            i: Landmark index in V["landmarks"].
            typ: A type from cities.TYPES, or None.

        Raises:
            ValueError: With no atlas open, a bad index or an unknown type.
        """
        self._need_atlas()
        if not 0 <= i < len(self.V["landmarks"]):
            raise ValueError("no such landmark")
        if typ and typ not in atlas_cities.TYPES:
            raise ValueError(f"unknown city type: {typ}")
        lm = self.V["landmarks"][i]
        with self._lock:
            atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ or None)
        self._edited(f"city type at ({lm['x']:.0f}, {lm['y']:.0f}) set to {typ or 'automatic'}")

    def lasso_nodes(self, polygon: list) -> list[int]:
        """Return the map nodes inside a lasso: every one not removed, whatever the filters show.

        A biome area is drawn around every such map, so the lasso takes them all: with only the shown ones, a map the
        filters hid (doubtful, or seen once) kept its biome and its area stayed (user: painting didn't stick).

        Args:
            polygon: [[x, y], ...] in atlas units.

        Returns:
            Map node indices.
        """
        if len(polygon) < 3 or not len(self.D.get("node_pts", [])):
            return []
        P = np.array(polygon, np.float32).reshape(-1, 1, 2)
        return [
            i
            for i, n in enumerate(self.V["nodes"])
            if n["status"] != "removed" and cv2.pointPolygonTest(P, (float(n["x"]), float(n["y"])), False) >= 0
        ]

    @atlas_edit
    def set_biome(self, polygon: list, biome: str) -> int:
        """Make the maps inside a lasso this biome (or none); kept in the atlas by map position.

        A newer lasso wins for maps it covers. For a city, a Hall / deadly boss map inside the lasso is that city:
        it becomes a City of that type, marked as the biome's doing; painting no biome (or a stronghold) there takes
        those back, leaving what you set by hand (clearing it left the Cities: GPT audit).

        Args:
            polygon: The lasso, [[x, y], ...] in atlas units.
            biome: "<type> city", "Breach stronghold", or "" for no biome.

        Returns:
            How many maps changed.

        Raises:
            ValueError: With no atlas open, an unknown biome, or no maps inside the lasso.
        """
        self._need_atlas()
        if biome and biome not in BIOMES:
            raise ValueError(f"unknown biome: {biome}")
        ids = self.lasso_nodes(polygon)
        if not ids:
            raise ValueError("no maps inside the lasso")
        N = self.V["nodes"]
        pts = [[round(float(N[i]["x"]), 1), round(float(N[i]["y"]), 1)] for i in ids]
        with self._lock:
            keep = []
            for e in self.atlas.biome_edits:  # a newer lasso wins for maps it covers
                rest = [q for q in e["maps"] if min(math.hypot(q[0] - a, q[1] - b) for a, b in pts) > 20]
                if rest:
                    keep.append(dict(e, maps=rest))
            keep.append({"biome": biome, "maps": pts})
            self.atlas.biome_edits = keep
            P = np.array(polygon, np.float32).reshape(-1, 1, 2)
            inside = [
                lm
                for lm in self.V["landmarks"]
                if cv2.pointPolygonTest(P, (float(lm["x"]), float(lm["y"])), False) >= 0
            ]
            if biome.endswith(" city"):
                typ = biome.replace(" city", "")
                for lm in inside:
                    if lm["status"].startswith("removed") or lm["kind"] not in ("Hall", "Deadly boss map", "City"):
                        continue
                    near = [
                        e
                        for e in self.atlas.landmark_edits
                        if math.hypot(e["x"] - lm["x"], e["y"] - lm["y"]) < EDIT_SPOT
                    ]
                    # one you set by hand stays as you set it (it was deleted, and clearing the biome then couldn't
                    # bring it back: CodeRabbit); a landmark takes one edit, so none is added over it. A City you
                    # set still takes the biome's type below (unless you set one); anything else you set, none.
                    mine = any(not e.get("by") for e in near)
                    if mine and lm["kind"] != "City":
                        continue
                    if lm["kind"] != "City":
                        self.atlas.landmark_edits = [e for e in self.atlas.landmark_edits if e not in near]
                        self.atlas.landmark_edits.append(
                            {"x": round(lm["x"], 1), "y": round(lm["y"], 1), "kind": "City", "on": "landmark",
                             "by": "biome"}
                        )  # fmt: skip
                        self.events.log(f"{lm['kind']} at ({lm['x']:.0f}, {lm['y']:.0f}) is now a {typ} city")
                    hand = any(
                        math.hypot(c["x"] - lm["x"], c["y"] - lm["y"]) < atlas_cities.SAME_CITY and not c.get("by")
                        for c in self.atlas.city_types
                    )
                    if not hand:  # (a type you set yourself stays)
                        atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ, by="biome")
            else:
                self._take_back_biome_cities(inside)
        n = f"{len(ids)} map" if len(ids) == 1 else f"{len(ids)} maps"
        verb = "is" if len(ids) == 1 else "are"
        self._edited(
            f"Biome select: {n} {verb} now {biome}" if biome else f"Biome select: {n} {verb} no longer in a biome"
        )
        return len(ids)

    def _take_back_biome_cities(self, landmarks: list[dict]) -> None:
        """Undo what a city biome did to these landmarks (Cities it made, types it set), not your own edits."""
        near = lambda e, r: any(math.hypot(e["x"] - lm["x"], e["y"] - lm["y"]) < r for lm in landmarks)  # noqa: E731
        gone = [e for e in self.atlas.landmark_edits if e.get("by") == "biome" and near(e, EDIT_SPOT)]
        self.atlas.landmark_edits = [e for e in self.atlas.landmark_edits if e not in gone]
        self.atlas.city_types = [
            c for c in self.atlas.city_types if not (c.get("by") == "biome" and near(c, atlas_cities.SAME_CITY))
        ]
        for e in gone:
            self.events.log(f"the City at ({e['x']:.0f}, {e['y']:.0f}) is back to what was found there (biome cleared)")

    def scan_locks(self) -> None:
        """Search the screenshots not searched yet for the hand badge (locked strongholds), in the background."""
        with self._lock:  # its screenshots, atlas and generation read together (a switch between: CodeRabbit)
            if not self.atlas or getattr(self, "_lock_job", False):
                return
            done = set(self.atlas.lock_scanned)
            todo = [f for f in self.atlas.frames if f["name"] not in done]
            if not todo:
                return
            self._lock_job = True
            job = self.opened  # (one record: its atlas, generation and log together)
            atlas, gen, scope = job.atlas, job.gen, job.scope
            # the screenshots it searches, as they are now: an Undo meanwhile puts others back (its result would
            # have put back the strongholds of the screenshots Undo took away: CodeRabbit)
            rev = getattr(self, "_lock_rev", 0)

        def work():
            """Find the hand badges, keep them in the atlas and rebuild the model (background thread)."""
            found = None
            try:
                found = atlas_cities.find_locks(atlas, todo)
            except Exception as e:
                LOG.exception("locked stronghold search failed")
                self.events.log(f"locked stronghold search failed: {e}", scope)
            with self._lock:
                try:
                    # another atlas opened meanwhile: its file is not this one's (user, CodeRabbit)
                    stale = not self.owns(gen) or rev != getattr(self, "_lock_rev", 0)
                    if found is not None and not stale:
                        atlas.locks = atlas_cities.merge_locks(atlas.locks, found)
                        atlas.lock_scanned = sorted(set(atlas.lock_scanned) | {f["name"] for f in todo})
                        if self.path:
                            atlas.save(self.path)
                finally:
                    # released with the result, in one step: released before it, a second search took the same
                    # screenshots from the old searched list (CodeRabbit)
                    self._lock_job = False
            if stale:
                self.scan_locks()  # the screenshots as they are now (its own search was skipped while this one ran)
                return
            if found is None:
                return
            if found:
                self.events.log(f"{len(atlas.locks)} locked Breach stronghold(s) (hand badge)", scope)
            self.rebuild_model()
            self.scan_locks()  # screenshots added meanwhile

        self._lock_thread = threading.Thread(target=work, daemon=True)  # (kept: tests wait for it, not a timer)
        self._lock_thread.start()
