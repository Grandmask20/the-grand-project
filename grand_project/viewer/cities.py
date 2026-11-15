"""viewer.cities: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import gc
import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import cv2
import numpy as np

from grand_project import cities as atlas_cities
from grand_project import core
from grand_project import finalize as atlas_finalize
from grand_project import paths as rc_paths

from .constants import EDIT_SPOT, LANDMARK_KINDS, POTENTIAL_TYPES, TERRAIN_PIXELS, VERSION
from .helpers import LOG, icon_label
from .model import view_model


def settle_memory():
    """Runs after an atlas is opened: collect once, then leave everything alive now out of later full
    collections.

    With a large atlas open (~470k objects) each automatic full collection paused the window for 120-180 ms,
    at random while panning. Objects let go later are still freed (reference counting).
    """
    gc.unfreeze()  # the atlas opened before can be collected now
    gc.collect()
    gc.freeze()


def _quiet(fn):
    """Calls a function and only logs a warning if it fails (used to save the ground cache from a thread).

    Args:
        fn: The function to call, without arguments.
    """
    try:
        fn()
    except Exception:
        LOG.warning("ground cache could not be saved", exc_info=True)


class CitiesMixin:
    """Atlas loading and the map model of the Viewer window: opening an atlas, the city biome lasso, landmark
    edits, locked Breach strongholds, city types and biomes, and the stitched map image (terrain, Fix seams).

    A mixin of the Viewer class (viewer/app.py). Methods run on the window (Tk) thread unless they say
    otherwise; background work hands its results to the window through the viewer's queue (`self._q`).
    """

    # ------------------------------------------------------------------ city biome lasso
    def start_lasso(self):
        """Starts drawing a city biome by hand (the Draw city biome button): the next drag on the map draws a
        lasso around map nodes; Esc cancels.
        """
        if not self.atlas:
            return
        self._lasso = []
        self.canvas.configure(cursor="pencil")
        self.status.set("draw around the maps of the biome (hold the left button); Esc cancels")

    def _lasso_menu(self, ids: list[int], sx, sy):
        """Pops up the menu that asks what the lassoed map nodes are: a city type, a Breach stronghold, or no
        biome.

        Args:
            ids: Indices of the lassoed map nodes in the view model.
            sx: Where to show the menu, x on the map canvas (screen px).
            sy: Where to show the menu, y on the map canvas (screen px).
        """
        m = tk.Menu(self.root, tearoff=0)
        for t in atlas_cities.TYPES:
            m.add_command(label=f"{t} city", command=lambda t=t: self.set_biome(ids, f"{t} city"))
        m.add_command(label="Breach stronghold", command=lambda: self.set_biome(ids, "Breach stronghold"))
        m.add_separator()
        m.add_command(label="Not a biome (clear these maps)", command=lambda: self.set_biome(ids, ""))
        m.add_command(label="Cancel", command=self.request_redraw)
        m.tk_popup(int(self.canvas.winfo_rootx() + sx), int(self.canvas.winfo_rooty() + sy))

    def set_biome(self, ids: list[int], biome: str):
        """Makes the lassoed map nodes this biome (or none); kept in the atlas by map position.

        A newer lasso wins for maps it covers (older edits within 20 atlas units of them are dropped). For a
        city, a Hall / deadly boss map inside the hand-drawn lasso is that city (its Deadly Map Boss icon map):
        it is changed into a City of that type. Saves the atlas and rebuilds the model.

        Args:
            ids: Indices of the lassoed map nodes in the view model.
            biome: "<type> city" (a type from cities.TYPES), "Breach stronghold", or "" for no biome.
        """
        pts = [[round(float(self.V["nodes"][i]["x"]), 1), round(float(self.V["nodes"][i]["y"]), 1)] for i in ids]
        keep = []
        for e in self.atlas.biome_edits:  # a newer lasso wins for maps it covers
            rest = [q for q in e["maps"] if min(math.hypot(q[0] - a, q[1] - b) for a, b in pts) > 20]
            if rest:
                keep.append(dict(e, maps=rest))
        keep.append({"biome": biome, "maps": pts})
        self.atlas.biome_edits = keep
        poly = getattr(self, "_lasso_world", None)
        if biome.endswith(" city") and poly:
            # a Hall / deadly boss map inside a hand-drawn city is that city (its Deadly Map Boss badge map)
            P = np.array(poly, np.float32).reshape(-1, 1, 2)
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
                    self.log(f"{lm['kind']} at ({lm['x']:.0f}, {lm['y']:.0f}) is now a {typ} city")
                atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        LOG.info(f"{len(ids)} maps set to biome {biome or '(none)'} by hand")
        self.log(f"{len(ids)} maps " + (f"are now {biome}" if biome else "are no longer in a biome"))
        if self.path:
            self.atlas.save(self.path)
        self.rebuild_model()
        self.request_redraw()

    def apply_biome_edits(self):
        """Puts the hand-drawn biomes (atlas.biome_edits) on top of the automatic ones in `self.potential`.

        Each stored map position is matched to the nearest map node within 20 atlas units; a biome sets it as
        that biome's own map (0 steps), "" removes it from any biome.
        """
        edits = getattr(self.atlas, "biome_edits", []) if self.atlas else []
        if not edits or not len(self.node_pts):
            return
        from scipy.spatial import cKDTree

        tree = cKDTree(self.node_pts)
        for e in edits:
            for q in e["maps"]:
                d, i = tree.query(q)
                if d > 20:
                    continue
                if e["biome"]:
                    self.potential[int(i)] = (e["biome"], 0)
                else:
                    self.potential.pop(int(i), None)

    def _initial_dir(self) -> str:
        """Returns the folder file dialogs start in: the open atlas's folder, else the last atlas's, else the
        program folder.

        Returns:
            The folder as a string.
        """
        if self.path:
            return str(self.path.parent)
        last = self.settings.get("last_atlas")
        return str(Path(last).parent) if last else str(rc_paths.ROOT)

    def open_atlas(self, p: Path):
        """Opens an atlas file and shows it.

        A read error is shown in a message box. Opening a different atlas clears this session's undo / recent /
        waiting lists and removes old undo snapshots. An atlas that predates the atlas-wide check gets it now
        (and is saved). Screenshots whose files are missing are logged (no terrain there). Auto-add follows the
        atlas: its own folder, or the one picked for it.

        Args:
            p: The atlas file.
        """
        try:
            atlas = core.Atlas.load(p)
        except Exception as e:
            LOG.exception(f"could not read atlas {p}")
            messagebox.showerror("Open atlas", f"Could not read {p}:\n{e}")
            return
        if self.path is None or Path(p).resolve() != Path(self.path).resolve():
            self._forget_session()
            self._drop_stale_snapshots(Path(p))
        self.atlas = atlas
        LOG.info(
            f"opened atlas {p}: {len(self.atlas.frames)} screenshots, "
            f"{len((self.atlas.final or {}).get('nodes', []))} maps"
        )
        self.path = p
        self.settings["last_atlas"] = str(p)
        if self.atlas.frames and self.atlas.final is None:
            self.log("this atlas predates the atlas-wide check: running it now")
            try:
                atlas_finalize.finalize(self.atlas, log=self.log)
                self.atlas.save(self.path)
            except Exception as e:
                LOG.exception("atlas-wide check failed")
                self.log(f"atlas-wide check failed: {e}")
        self._after_load(fit=True)
        missing = [f["name"] for f in self.atlas.frames if not Path(f["path"]).exists()]
        if missing:
            self.log(f"screenshots not found (terrain missing there): {', '.join(missing)}")
        if self.watch_var.get():
            self.start_watch()  # auto-add follows the atlas: its own folder, or the one picked for it

    def _forget_session(self):
        """Clears undo / recently added / waiting, which belong to the atlas they were made in.

        Cleared when another atlas is opened (undo after a switch put the old atlas's maps into the new one).
        This session's undo snapshot files are deleted.
        """
        for entry in self._undo:
            with contextlib.suppress(OSError):
                Path(entry["file"]).unlink()
        self._undo, self.recent, self._pending_watch = [], [], []
        self._wait_tries = {}
        if hasattr(self, "recent_list"):
            self._refresh_recent()

    @staticmethod
    def _drop_stale_snapshots(atlas_path: Path):
        """Removes undo snapshots left by an earlier session (undo only reaches this session's adds).

        Each is a full copy of the atlas, so they are removed instead of piling up.

        Args:
            atlas_path: The atlas file whose `<stem>_undo` folder is cleaned.
        """
        d = core.atlas_files(atlas_path) / (atlas_path.stem + "_undo")
        for f in d.glob("before_*.json") if d.is_dir() else ():
            with contextlib.suppress(OSError):
                f.unlink()

    def _after_load(self, fit=False):
        """Refreshes everything after an atlas was opened or created: map image, model, locked strongholds
        search, memory, title, auto-add label and the known atlases list.

        The cached map image comes first, so the maps model (and the city biomes in it) is built once, with the
        ground.

        Args:
            fit: True to fit the whole atlas in the window (now, and again once the canvas has its real size).
        """
        self.sel = None
        self._terrain = None
        # the cached map image first, so the maps model (and the city biomes in it) is built once, with the ground
        # (it was built without, then again when the map image came: ~1.7 s and the icon filter twice, 25k maps)
        self.rebuild_terrain(cities=False)
        self.rebuild_model()
        self.scan_locks()
        settle_memory()
        self.root.title(f"The Grand Project v{VERSION}{rc_paths.title_tag()} - {self.path.name if self.path else ''}")
        self._show_watch_label()
        if self.path:
            self.remember_atlas(self.path)
        if fit:
            self._fit_pending = True
            self.fit()
        self.request_redraw()

    def rebuild_model(self):
        """Rebuilds the view model from the atlas and everything derived from it.

        That is: map node and icon positions, icon types and their counts, locked strongholds, the atlas
        numbers, landmark and icon indexes, city types and biomes, the place types for the Find tab,
        screenshot footprints, sharp terrain tiles (cleared), bookmarks, the search results and the selected
        info.
        """
        self.V = view_model(self.atlas) if self.atlas else self.V
        self.node_pts = np.array([[n["x"], n["y"]] for n in self.V["nodes"]], float).reshape(-1, 2)
        self.icon_pts = np.array([[i["x"], i["y"]] for i in self.V["icons"]], float).reshape(-1, 2)
        counts: dict[str, int] = {}
        for ic in self.V["icons"]:
            counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
        self.icon_types = sorted(counts, key=lambda k: (k == "Unidentified badge", k))
        self.add_locks()
        self._note_atlas_numbers()
        for lm in self.V["landmarks"]:
            if not lm["status"].startswith("removed"):
                counts[lm["kind"]] = counts.get(lm["kind"], 0) + 1
        self._lm_index = {id(lm): i for i, lm in enumerate(self.V["landmarks"])}
        self._icon_index = {id(ic): i for i, ic in enumerate(self.V["icons"])}
        self.rebuild_cities(counts)
        self.place_types = [
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
            )
            if k in counts
        ]
        self.type_counts = counts  # the list itself is rebuilt by run_search below
        self.footprints = []
        for f in self.atlas.frames if self.atlas else []:
            H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            poly = core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
            self.footprints.append((poly, (*poly.min(axis=0), *poly.max(axis=0))))
        self._clear_tiles()
        self.refresh_bookmarks()
        self.run_search()
        self.show_info()

    # ------------------------------------------------------------------ locked strongholds
    def add_locks(self):
        """Marks locked Breach strongholds from the hand icons (atlas.locks).

        An existing stronghold within 300 atlas units is marked locked, otherwise one is added for the view.
        A spot where the user deleted or changed a landmark is left alone. Fills `self.locked_ids` (landmark
        indices).
        """
        self.locked_ids = set()
        locks = self.atlas.locks if self.atlas else []
        if not locks:
            return
        L = list(self.V["landmarks"])
        for k in locks:
            if any(
                math.hypot(e["x"] - k["x"], e["y"] - k["y"]) < 300 and e["kind"] != "Breach stronghold"
                for e in self.atlas.landmark_edits
            ):
                continue  # the user deleted / changed it: leave it
            near = [
                (math.hypot(lm["x"] - k["x"], lm["y"] - k["y"]), i)
                for i, lm in enumerate(L)
                if lm["kind"] == "Breach stronghold" and not lm["status"].startswith("removed")
            ]
            d, i = min(near) if near else (1e9, -1)
            if d < 300:
                self.locked_ids.add(i)
            else:
                L.append(
                    {
                        "kind": "Breach stronghold",
                        "x": k["x"],
                        "y": k["y"],
                        "n": k["n"],
                        "could": k["n"],
                        "conf": 1.0,
                        "source": "hand badge",
                        "status": "kept",
                    }
                )
                self.locked_ids.add(len(L) - 1)
        self.V = {**self.V, "landmarks": L}

    def scan_locks(self):
        """Searches the screenshots not searched yet for the hand icon (locked strongholds), in the background.

        The result goes to the window as a "locks" queue message; only one search runs at a time.
        """
        if not self.atlas or getattr(self, "_lock_job", False):
            return
        done = set(self.atlas.lock_scanned)
        todo = [f for f in self.atlas.frames if f["name"] not in done]
        if not todo:
            return
        self._lock_job = True
        atlas = self.atlas

        def work():
            """Background thread: finds the hand icons and queues the result (None on failure)."""
            try:
                found = atlas_cities.find_locks(atlas, todo)
                self._q.put(("locks", (atlas, [f["name"] for f in todo], found)))
            except Exception as e:
                LOG.exception("locked stronghold search failed")
                self._q.put(("log", f"locked stronghold search failed: {e}"))
                self._q.put(("locks", None))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ landmark edits
    def set_landmark(self, x: float, y: float, kind: str, on: str = "landmark"):
        """Changes / adds (kind) or deletes (kind "") the landmark at x, y; kept in the atlas file.

        An older edit within EDIT_SPOT is replaced. A deleted city keeps no hand-set type. Saves the atlas,
        clears the selection and rebuilds the model.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).
            kind: A landmark kind from LANDMARK_KINDS, or "" to delete.
            on: "landmark" when a landmark was edited; "map" when the user made a map into a landmark (it then
                never takes over a landmark nearby).
        """
        self.atlas.landmark_edits = [
            e for e in self.atlas.landmark_edits if math.hypot(e["x"] - x, e["y"] - y) >= EDIT_SPOT
        ]
        self.atlas.landmark_edits.append({"x": round(x, 1), "y": round(y, 1), "kind": kind, "on": on})
        if not kind:  # a deleted city keeps no hand-set type
            atlas_cities.set_type(self.atlas, x, y, None)
        LOG.info(f"landmark at ({x:.0f}, {y:.0f}) " + (f"set to {kind}" if kind else "deleted"))
        self.log(f"landmark at ({x:.0f}, {y:.0f}) " + (f"is now a {kind}" if kind else "deleted"))
        if self.path:
            self.atlas.save(self.path)
        self.sel = None
        self.rebuild_model()
        self.request_redraw()

    def _kind_menu(self, parent, x, y, current="", on="landmark"):
        """Builds the menu of landmark kinds that sets the landmark at x, y.

        Args:
            parent: The parent widget or menu.
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).
            current: The current kind, marked "●" in the menu.
            on: "landmark" or "map", passed on to set_landmark.

        Returns:
            The tk.Menu.
        """
        km = tk.Menu(parent, tearoff=0)
        for k in LANDMARK_KINDS:
            km.add_command(label=("● " if k == current else "") + k, command=lambda k=k: self.set_landmark(x, y, k, on))
        return km

    def edit_selected(self):
        """Edit button: bookmark -> its dialog; landmark / map -> pick what it is (a menu at the mouse)."""
        if not self.sel_valid():
            self.status.set("select a bookmark, landmark or map first")
            return
        kind, i = self.sel
        if kind == "bookmark":
            self.edit_bookmark()
            return
        if kind in ("landmark", "node"):
            x, y = self.item_pos(self.sel)
            cur = self.V["landmarks"][i]["kind"] if kind == "landmark" else ""
            m = self._kind_menu(self.root, x, y, cur, "landmark" if kind == "landmark" else "map")
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
            return
        self.status.set("only bookmarks, landmarks and maps can be edited")

    def delete_selected(self):
        """Delete button: deletes the selected bookmark or landmark, after asking.

        Never deletes what is ticked in the Bookmarks tab. A deleted landmark is kept in the atlas (Layers >
        Removed shows it; right-click brings it back).
        """
        if not self.sel_valid():
            self.status.set("select a bookmark or landmark first")
            return
        kind, i = self.sel
        if kind == "bookmark":
            b = self.atlas.bookmarks[i]
            if messagebox.askyesno("Delete bookmark", f'Delete "{b["name"]}"?'):
                LOG.info(f"deleted bookmark: {b['name']}")
                self.atlas.bookmarks.pop(i)
                self.sel = None
                self.save()
                self.refresh_bookmarks()
                self.run_search()
                self.show_info()
                self.request_redraw()
        elif kind == "landmark":
            lm = self.V["landmarks"][i]
            if messagebox.askyesno(
                "Delete landmark",
                f"Delete this {self.lm_name(i)}?\n"
                "(kept in the atlas; Layers > Removed shows it, right-click it to bring it back)",
            ):
                self.set_landmark(lm["x"], lm["y"], "")
        else:
            self.status.set("only bookmarks and landmarks can be deleted")

    # ------------------------------------------------------------------ cities
    def rebuild_cities(self, counts: dict | None = None):
        """Works out city types (Ezomyte / Vaal / Faridun) and the maps a city or stronghold biome may cover.

        Uses the ground under each map from the map image when there is one (cached per map image), skips
        locked strongholds as biome sources, then applies hand-drawn biomes and computes the maps near a city.
        Sets `city_type`, `icon_node`, `blocked`, `potential` and `near_city`.

        Args:
            counts: The type counts being built by rebuild_model, which gets the city types and potential maps
                added; None when the map image arrived later: the counts in `type_counts` are updated and the
                icon type list is rebuilt.
        """
        L = self.V["landmarks"]
        alive = [i for i, lm in enumerate(L) if not lm["status"].startswith("removed")]
        cities = [i for i in alive if L[i]["kind"] == "City"]
        self.city_type = {}
        if self.atlas and cities:
            try:
                res = atlas_cities.city_types(self.atlas, [L[i] for i in cities])
            except Exception:
                LOG.exception("city types failed")
                self.log("city types failed (details in the log file)")
                res = [("", "")] * len(cities)
            self.city_type = {i: r for i, r in zip(cities, res, strict=False) if r[0]}
        src = [
            (L[i]["x"], L[i]["y"], f"{self.city_type[i][0]} city" if i in self.city_type else "City") for i in cities
        ]
        src += [
            (L[i]["x"], L[i]["y"], "Breach stronghold")
            for i in alive  # locked ones show no maps
            if L[i]["kind"] == "Breach stronghold" and i not in getattr(self, "locked_ids", ())
        ]
        ground = None
        if getattr(self, "_terrain", None):  # the biome's own ground, from the map image
            if getattr(self, "_ground_for", None) is not self._terrain:
                canvas, weight, origin = self._terrain
                self._ground = self._kept_ground(atlas_cities.ground_sampler(canvas, weight, origin))
                self._ground_for = self._terrain
            ground = self._ground
        self.icon_node = atlas_cities.icon_maps(self.V["nodes"], self.V["icons"])
        live = [L[i] for i in alive if i not in getattr(self, "locked_ids", ())] + [
            L[i] for i in getattr(self, "locked_ids", ())
        ]
        self.blocked = atlas_cities.blocked_maps(self.V["nodes"], self.V["icons"], live, self.icon_node)
        self.potential = (
            atlas_cities.potential_maps(self.V["nodes"], self.V["paths"], src, ground=ground, blocked=self.blocked)
            if src
            else {}
        )
        LOG.debug(
            f"cities: {len(cities)} ({sum(1 for t in self.city_type.values() if t[1] == 'set')} set by hand), "
            f"strongholds {len(src) - len(cities)}, locked {len(getattr(self, 'locked_ids', ()))}, "
            f"biome maps {len(self.potential)}, blocked maps {len(self.blocked)}, ground {'yes' if ground else 'no'}"
        )
        if ground is not None and hasattr(ground, "save"):
            ground.save()
        self.apply_biome_edits()
        self.near_city = atlas_cities.near_city(self.V["nodes"], self.V["paths"], self.potential, self.blocked)
        if counts is None and getattr(self, "type_counts", None) is not None:  # map image arrived later
            counts = self.type_counts
            for k in POTENTIAL_TYPES:
                counts.pop(k, None)
            for _v, (lab, st) in self.potential.items():
                if st:
                    k = self.potential_kind(lab)
                    counts[k] = counts.get(k, 0) + 1
            self.rebuild_icon_filter()
        elif counts is not None:
            for _i, (t, _how) in self.city_type.items():
                counts[f"{t} city"] = counts.get(f"{t} city", 0) + 1
            for _v, (lab, st) in self.potential.items():
                if st:
                    k = self.potential_kind(lab)
                    counts[k] = counts.get(k, 0) + 1

    # The ground look under each map (ground_sampler) depends only on the map image: kept next to the map image
    # cache (<stem>_files/<stem>_ground.npz, for that map image's key) so opening an atlas again doesn't sample it
    # again (~1.6 s for 14.5k maps)
    def _ground_file(self):
        """Returns the ground cache file of the open atlas (<stem>_files/<stem>_ground.npz).

        Returns:
            The path.
        """
        d = core.atlas_files(self.path)
        return d / (self.path.stem + "_ground.npz")

    def _kept_ground(self, sample):
        """Wraps a ground sampler with the cache kept on disk for this map image.

        The ground look under each map depends only on the map image, so it is kept next to the map image cache
        (for that map image's key) and opening an atlas again doesn't sample it again (~1.6 s for 14.5k maps).

        Args:
            sample: The ground sampler, sample(x, y) -> 6 values or None (x, y in atlas units).

        Returns:
            A function ground(x, y) with the same result, using the cache; ground.save() writes new samples to
            the cache file in a background thread.
        """
        key = self._terrain_key() if self.path else ""
        kept: dict = {}
        if self.path:
            with contextlib.suppress(Exception):
                z = np.load(self._ground_file())
                if str(z["key"]) == key:
                    kept = {
                        (float(x), float(y)): (None if np.isnan(v[0]) else v)
                        for x, y, v in zip(z["x"], z["y"], z["v"], strict=True)
                    }
        state = {"new": 0}

        def ground(x, y):
            """Returns the ground look at x, y (atlas units), from the cache or sampled and remembered.

            Args:
                x: Atlas x (atlas units).
                y: Atlas y (atlas units).

            Returns:
                The sampled values, or None where there is no ground.
            """
            k = (round(float(x), 2), round(float(y), 2))
            if k not in kept:
                kept[k] = sample(x, y)
                state["new"] += 1
            return kept[k]

        def save():
            """Writes the cache to the ground file in a background thread, when anything new was sampled."""
            if not state["new"] or not self.path or not kept:
                return
            state["new"] = 0
            xs = np.array([k[0] for k in kept])
            ys = np.array([k[1] for k in kept])
            vs = np.array([np.full(6, np.nan) if v is None else v for v in kept.values()], np.float32)
            path = self._ground_file()
            threading.Thread(
                target=lambda: _quiet(lambda: np.savez(path, key=key, x=xs, y=ys, v=vs)), daemon=True
            ).start()

        ground.save = save
        return ground

    def near_city_text(self, v) -> str:
        """Returns the "Potential city: ..." line for a map, or "" when it is not on / next to a city biome.

        Args:
            v: Index of the map node in the view model, or None.

        Returns:
            The text.
        """
        t = getattr(self, "near_city", {}).get(v) if v is not None else None
        if not t:
            return ""
        lab, st = t
        return f"Potential city: {'on the' if st == 0 else '1 step from the'} {lab} biome"

    def _refilter(self):
        """Applies the "only potential city maps" setting: type list, map and listing all follow it."""
        self.rebuild_icon_filter()
        self.request_redraw()
        if getattr(self, "_last_list", None):
            self.list_type(self._last_list)
        else:
            self.run_search()

    @staticmethod
    def potential_kind(label: str) -> str:
        """Returns the Find tab type a biome's potential map is listed under.

        Args:
            label: The biome label ("Breach stronghold" or "<type> city" / "City").

        Returns:
            "Potential stronghold map" or "Potential city map".
        """
        return "Potential stronghold map" if label == "Breach stronghold" else "Potential city map"

    def potential_text(self, i: int) -> str:
        """Describes a map's place in a biome, e.g. "Vaal city (its own map)" or "Potential Vaal city map (2 steps
        away)".

        Args:
            i: Index of the map node in the view model; must be in `self.potential`.

        Returns:
            The text.
        """
        lab, st = self.potential[i]
        if st == 0:
            return f"{lab} (its own map)"
        return f"Potential {lab} map ({st} step{'s' if st > 1 else ''} away)"

    def lm_name(self, i: int) -> str:
        """Returns the landmark name with the city type: "Vaal city", "Ezomyte city?" (? = guessed by look).

        Locked strongholds are "Locked Breach stronghold"; other landmarks are their kind.

        Args:
            i: Index of the landmark in the view model.

        Returns:
            The name.
        """
        lm = self.V["landmarks"][i]
        if i in getattr(self, "locked_ids", ()):
            return "Locked Breach stronghold"
        if lm["kind"] == "City" and i in getattr(self, "city_type", {}):
            t, how = self.city_type[i]
            return f"{t} city" + ("?" if how == "look-alike" else "")
        return lm["kind"]

    def set_city_type(self, i: int, typ: str | None):
        """Sets a city's type by hand (or back to automatic), saves the atlas and rebuilds the model.

        Args:
            i: Index of the landmark in the view model.
            typ: A type from cities.TYPES, or None for automatic.
        """
        lm = self.V["landmarks"][i]
        LOG.info(f"city type at ({lm['x']:.0f}, {lm['y']:.0f}) set to {typ or 'automatic'}")
        atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        if self.path:
            self.atlas.save(self.path)
        self.rebuild_model()
        self.request_redraw()

    def on_configure(self, _e=None):
        """Redraws when the map canvas changes size; bound to <Configure> on the map canvas.

        The first real size arrives after loading: a pending fit is done then, so the map isn't fitted to
        1x1 px.

        Args:
            _e: The Tk event (unused).
        """
        # the first real size arrives after loading: fit then, so the map isn't fitted to 1x1 px
        if self._fit_pending and self.canvas.winfo_width() > 50:
            self.fit()
        self.request_redraw()

    def _terrain_key(self) -> str:
        """Returns the key of the map image: a hash of every screenshot's name and placement.

        A cached map image (or ground cache) is used only when its key matches.

        Returns:
            The hex digest.
        """
        import hashlib

        h = hashlib.sha1()
        for f in self.atlas.frames:
            h.update(f["name"].encode())
            h.update(np.round(np.array(f["M"], float), 2).tobytes())
        return h.hexdigest()

    def _terrain_files(self):
        """Returns the map image cache files of the open atlas.

        Returns:
            (<stem>_terrain.png, <stem>_terrain.npz) in the atlas's files folder.
        """
        d = core.atlas_files(self.path)
        return d / (self.path.stem + "_terrain.png"), d / (self.path.stem + "_terrain.npz")

    def rebuild_terrain(self, background=True, cities=True):
        """Shows the stitched map: from the cache next to the atlas when it matches, else built in the
        background (the window stays usable; the map appears when it is ready).

        Args:
            background: True to build in a background thread; False to build now and handle the result at once.
            cities: True to rebuild the city biomes when a cached map image is used (False when the model is
                rebuilt right after anyway).
        """
        if not self.atlas or not self.atlas.frames:
            self.pyr, self._terrain = [], None
            return
        png, npz = self._terrain_files()
        key = self._terrain_key()
        try:
            meta = np.load(npz)
            if str(meta["key"]) == key:
                canvas = cv2.imdecode(np.fromfile(str(png), np.uint8), cv2.IMREAD_COLOR)
                weight = meta["weight"].astype(np.float32)
                origin = tuple(float(v) for v in meta["origin"])
                labels = (meta["labels"], [str(n) for n in meta["names"]]) if "labels" in meta.files else None
                if canvas is not None and canvas.shape[:2] == weight.shape:
                    self._set_terrain(canvas, weight, origin, save=False, labels=labels, cities=cities)
                    return
        except Exception:
            LOG.debug("map image cache not usable, rebuilding", exc_info=True)
        self._terrain_job += 1
        job = self._terrain_job
        self._set_progress("building the map image (first time for this atlas)…")

        def work():
            """Builds the map image and queues it as a "terrain_img" message (background thread, or the window
            thread when background is False).
            """
            try:
                canvas, origin, weight = self.atlas.composite(max_pixels=TERRAIN_PIXELS, with_weight=True)
                self._q.put(("terrain_img", (job, canvas, weight, origin)))
            except Exception as e:
                LOG.exception("map image could not be built")
                self._q.put(("log", f"map image could not be built: {e}"))

        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
            self._drain_queue()

    def _set_terrain(self, canvas, weight, origin, save=True, labels=None, cities=True):
        """Shows a new map image: keeps it, builds its pyramid of smaller copies and, when asked, writes the cache.

        Window thread. The city biomes follow the new ground; the Terrain toggle picture is rebuilt.

        Args:
            canvas: The map image (BGR).
            weight: Per-pixel coverage weight, same size as canvas.
            origin: (x0, y0, scale) of the map image in atlas units.
            save: True to write the map image cache, the Saved atlases card picture, in a background thread.
            labels: (ownership map, screenshot names) of a clean map (Fix seams); None for the quick map.
            cities: True to rebuild the city biomes.
        """
        self._labels = labels
        self.root.after(50, self._build_layer_grid)  # the Terrain toggle shows a piece of this map
        self._terrain = (canvas, weight, origin)
        self.t_origin = origin
        pyr = [canvas]
        while max(pyr[-1].shape[:2]) > 600:
            pyr.append(cv2.pyrDown(pyr[-1]))
        self.pyr = pyr
        if cities and getattr(self, "V", None) and self.V.get("nodes"):
            self.rebuild_cities()  # biome clusters follow the ground now
        self._clear_tiles()
        self._pending_outline = []
        if save and self.path:
            key = self._terrain_key()
            png, npz = self._terrain_files()

            def write():
                """Background thread: writes the map image cache files and the atlas card picture."""
                try:
                    core.write_png(png, canvas, "map image")
                    self._write_thumb(canvas)  # the atlas's card in Saved atlases
                    extra = {} if labels is None else {"labels": labels[0], "names": np.array(labels[1])}
                    np.savez_compressed(
                        npz, key=key, origin=np.array(origin, float), weight=weight.astype(np.float16), **extra
                    )
                except Exception:
                    LOG.warning("map image cache could not be saved", exc_info=True)

            threading.Thread(target=write, daemon=True).start()
        self.request_redraw()

    def _paste_terrain(self, frames) -> bool:
        """Pastes new screenshots into a copy of the stitched map (fast). Runs on the worker thread.

        The result goes to the window as a "terrain_img" message.

        Args:
            frames: The new screenshots' frame dicts.

        Returns:
            True when pasted; False when there is no map image yet or they fall outside it and the whole map has
            to be rebuilt.
        """
        if self._terrain is None:
            return False
        canvas, weight, origin = self._terrain
        canvas, weight = canvas.copy(), weight.copy()
        lab = getattr(self, "_labels", None)
        labels, names = (lab[0].copy(), list(lab[1])) if lab is not None else (None, None)
        if not self.atlas.paste_into(canvas, weight, origin, frames, labels=labels, names=names):
            return False
        kept = (labels, names) if labels is not None else None
        self._q.put(("terrain_img", (None, canvas, weight, origin, kept)))
        return True

    def fix_seams(self):
        """Builds the clean map (core.seams) in a separate process: map nodes and icons whole, seams off paths and
        away from screenshot edges.

        Minutes on a large atlas; the viewer and the quick map stay usable. A process, not a thread, so the
        window is not starved. Only one runs at a time.
        """
        if not self.atlas or not self.atlas.frames:
            return
        if self.seams_running():
            self.log("Fix seams is already running")
            return
        import os
        import pickle
        import shutil
        import subprocess
        import sys
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="grand_seams_"))
        src, out, err = tmp / "atlas.pkl", tmp / "clean.npz", tmp / "errors.txt"
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
        self._seams_proc = proc
        self._set_progress("fixing seams: building the clean map...")
        self.log("Fix seams: building the clean map in the background")

        def watch():
            """Background thread: passes the process's progress lines on, then queues the clean map (or the error)
            and removes the temporary folder.
            """
            for line in proc.stdout:
                if line.strip() and line.strip() != "done":
                    self._q.put(("progress", line.strip()))
            proc.wait()
            try:
                if proc.returncode == 0 and out.exists():
                    with np.load(out) as r:
                        canvas, weight, labels = r["canvas"], r["weight"], r["labels"]
                        origin = tuple(float(v) for v in r["origin"])
                        names = [str(n) for n in r["names"]]
                    self._q.put(("terrain_img", ("seams", canvas, weight, origin, (labels, names))))
                    self._q.put(("log", "Fix seams: clean map ready"))
                elif proc.returncode in (-9, -15, 1) and getattr(self, "_seams_stopped", False):
                    pass
                else:
                    text = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    LOG.error("clean map could not be built: %s", " | ".join(text[-30:]))
                    self._q.put(("log", f"clean map could not be built: {text[-1] if text else proc.returncode}"))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
                self._q.put(("progress", None))

        threading.Thread(target=watch, daemon=True).start()

    def seams_running(self) -> bool:
        """Tells whether Fix seams is running.

        Returns:
            True while its process is alive.
        """
        proc = getattr(self, "_seams_proc", None)
        return proc is not None and proc.poll() is None

    def stop_seams(self):
        """Stops a running Fix seams process (its result is then dropped quietly)."""
        if self.seams_running():
            self._seams_stopped = True
            self._seams_proc.terminate()

    def _seams_ready(self, names):
        """Handles a clean map that arrived: screenshots added while it was being built are pasted in on top
        (in a background thread; the whole map is rebuilt if they don't fit).

        Args:
            names: The screenshot names the clean map was built from.
        """
        have = set(names)
        missing = [f for f in self.atlas.frames if f["name"] not in have]
        if missing:

            def paste():
                """Background thread: pastes the missing screenshots, or asks for a full rebuild."""
                if not self._paste_terrain(missing):
                    self._q.put(("rebuild_terrain", None))

            threading.Thread(target=paste, daemon=True).start()
