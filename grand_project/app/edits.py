"""app.edits: part of AtlasSession (a mixin; see app/session.py): hand edits kept in the atlas file.

Landmarks changed, added or deleted (atlas.landmark_edits), city types set by hand, biomes drawn with the lasso
(atlas.biome_edits), and the search for locked Breach strongholds (the hand badge) in new screenshots.
"""

from __future__ import annotations

import math
import threading

import cv2
import numpy as np

from grand_project import cities as atlas_cities
from grand_project import logs as atlas_log

from .constants import EDIT_SPOT, LANDMARK_KINDS

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

    def set_biome(self, polygon: list, biome: str) -> int:
        """Make the maps inside a lasso this biome (or none); kept in the atlas by map position.

        A newer lasso wins for maps it covers. For a city, a Hall / deadly boss map inside the lasso is that city:
        it becomes a City of that type.

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
            if biome.endswith(" city"):
                P = np.array(polygon, np.float32).reshape(-1, 1, 2)
                typ = biome.replace(" city", "")
                for lm in self.V["landmarks"]:
                    if lm["status"].startswith("removed") or lm["kind"] not in ("Hall", "Deadly boss map", "City"):
                        continue
                    if cv2.pointPolygonTest(P, (float(lm["x"]), float(lm["y"])), False) < 0:
                        continue
                    if lm["kind"] != "City":
                        self.atlas.landmark_edits = [
                            e
                            for e in self.atlas.landmark_edits
                            if math.hypot(e["x"] - lm["x"], e["y"] - lm["y"]) >= EDIT_SPOT
                        ]
                        self.atlas.landmark_edits.append(
                            {"x": round(lm["x"], 1), "y": round(lm["y"], 1), "kind": "City", "on": "landmark"}
                        )
                        self.events.log(f"{lm['kind']} at ({lm['x']:.0f}, {lm['y']:.0f}) is now a {typ} city")
                    atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        n = f"{len(ids)} map" if len(ids) == 1 else f"{len(ids)} maps"
        verb = "is" if len(ids) == 1 else "are"
        self._edited(
            f"Biome select: {n} {verb} now {biome}" if biome else f"Biome select: {n} {verb} no longer in a biome"
        )
        return len(ids)

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
                    stale = not self.owns(gen)
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
                self.scan_locks()  # the one open now (its own search was skipped while this one ran)
                return
            if found is None:
                return
            if found:
                self.events.log(f"{len(atlas.locks)} locked Breach stronghold(s) (hand badge)", scope)
            self.rebuild_model()
            self.scan_locks()  # screenshots added meanwhile

        self._lock_thread = threading.Thread(target=work, daemon=True)  # (kept: tests wait for it, not a timer)
        self._lock_thread.start()
