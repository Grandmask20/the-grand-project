"""viewer.cities: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import contextlib
import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import cv2
import numpy as np

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import cities as atlas_cities
from grand_project import core
from grand_project import finalize as atlas_finalize
from grand_project import paths as rc_paths

from .constants import EDIT_SPOT, LANDMARK_KINDS, POTENTIAL_TYPES, TERRAIN_PIXELS, VERSION
from .helpers import LOG, icon_label
from .model import view_model


class CitiesMixin:
    # ------------------------------------------------------------------ city biome lasso
    def start_lasso(self):
        if not self.atlas:
            return
        self._lasso = []
        self.canvas.configure(cursor="pencil")
        self.status.set("draw around the maps of the biome (hold the left button); Esc cancels")

    def _lasso_menu(self, ids: list[int], sx, sy):
        m = tk.Menu(self.root, tearoff=0)
        for t in atlas_cities.TYPES:
            m.add_command(label=f"{t} city", command=lambda t=t: self.set_biome(ids, f"{t} city"))
        m.add_command(label="Breach stronghold", command=lambda: self.set_biome(ids, "Breach stronghold"))
        m.add_separator()
        m.add_command(label="Not a biome (clear these maps)", command=lambda: self.set_biome(ids, ""))
        m.add_command(label="Cancel", command=self.request_redraw)
        m.tk_popup(int(self.canvas.winfo_rootx() + sx), int(self.canvas.winfo_rooty() + sy))

    def set_biome(self, ids: list[int], biome: str):
        """the lassoed maps become this biome (or none); kept in the atlas by map position"""
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
        """hand-drawn biomes on top of the automatic ones (atlas.biome_edits)"""
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
        if self.path:
            return str(self.path.parent)
        last = self.settings.get("last_atlas")
        return str(Path(last).parent) if last else str(rc_paths.ROOT)

    def open_atlas(self, p: Path):
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
        if self.watch_var.get() and not self.settings.get("watch_folder"):
            self.start_watch()  # auto-add follows the atlas: now its folder is watched

    def _forget_session(self):
        """undo / recently added / waiting belong to the atlas they were made in: cleared when another atlas
        is opened (undo after a switch put the old atlas's maps into the new one)"""
        for entry in self._undo:
            with contextlib.suppress(OSError):
                Path(entry["file"]).unlink()
        self._undo, self.recent, self._pending_watch = [], [], []
        self._wait_tries = {}
        if hasattr(self, "recent_list"):
            self._refresh_recent()

    @staticmethod
    def _drop_stale_snapshots(atlas_path: Path):
        """undo snapshots left by an earlier session (undo only reaches this session's adds): a full copy
        of the atlas each, so they are removed instead of piling up"""
        d = core.atlas_files(atlas_path) / (atlas_path.stem + "_undo")
        for f in d.glob("before_*.json") if d.is_dir() else ():
            with contextlib.suppress(OSError):
                f.unlink()

    def _after_load(self, fit=False):
        self.sel = None
        self._terrain = None
        self.rebuild_model()
        self.rebuild_terrain()
        self.scan_locks()
        self.root.title(f"The Grand Project v{VERSION}{rc_paths.title_tag()} - {self.path.name if self.path else ''}")
        self._show_watch_label()
        if self.path:
            self.remember_atlas(self.path)
        if fit:
            self._fit_pending = True
            self.fit()
        self.request_redraw()

    def rebuild_model(self):
        self.V = view_model(self.atlas) if self.atlas else self.V
        self.node_pts = np.array([[n["x"], n["y"]] for n in self.V["nodes"]], float).reshape(-1, 2)
        self.icon_pts = np.array([[i["x"], i["y"]] for i in self.V["icons"]], float).reshape(-1, 2)
        counts: dict[str, int] = {}
        for ic in self.V["icons"]:
            counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
        self.icon_types = sorted(counts, key=lambda k: (k == "Unidentified badge", k))
        self.add_locks()
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
        self._hires, self._weights = None, {}
        self.refresh_bookmarks()
        self.run_search()
        self.show_info()

    # ------------------------------------------------------------------ locked strongholds
    def add_locks(self):
        """hand badges (atlas.locks) = locked Breach strongholds: an existing stronghold nearby is
        marked locked, otherwise one is added for the view"""
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
        """search screenshots not searched yet for the hand badge, in the background"""
        if not self.atlas or getattr(self, "_lock_job", False):
            return
        done = set(self.atlas.lock_scanned)
        todo = [f for f in self.atlas.frames if f["name"] not in done]
        if not todo:
            return
        self._lock_job = True
        atlas = self.atlas

        def work():
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
        """change / add (kind) or delete (kind "") the landmark at x, y; kept in the atlas file.
        on = "map" when the user made a map into a landmark (it then never takes over a landmark nearby)"""
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
        km = tk.Menu(parent, tearoff=0)
        for k in LANDMARK_KINDS:
            km.add_command(label=("● " if k == current else "") + k, command=lambda k=k: self.set_landmark(x, y, k, on))
        return km

    def edit_selected(self):
        """Edit button: bookmark -> its dialog; landmark / map -> pick what it is"""
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
        """Delete button: the selected bookmark or landmark (never what is ticked in the Bookmarks tab)"""
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
        """city types (Ezomyte / Vaal / Faridun) and the maps a city or stronghold biome may cover"""
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
                self._ground = atlas_cities.ground_sampler(canvas, weight, origin)
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

    def near_city_text(self, v) -> str:
        """ "Potential city: ..." for a map, or "" when it is not on / next to a city biome"""
        t = getattr(self, "near_city", {}).get(v) if v is not None else None
        if not t:
            return ""
        lab, st = t
        return f"Potential city: {'on the' if st == 0 else '1 step from the'} {lab} biome"

    def _refilter(self):
        """the "only potential city maps" setting: type list, map and listing all follow it"""
        self.rebuild_icon_filter()
        self.request_redraw()
        if getattr(self, "_last_list", None):
            self.list_type(self._last_list)
        else:
            self.run_search()

    @staticmethod
    def potential_kind(label: str) -> str:
        return "Potential stronghold map" if label == "Breach stronghold" else "Potential city map"

    def potential_text(self, i: int) -> str:
        lab, st = self.potential[i]
        if st == 0:
            return f"{lab} (its own map)"
        return f"Potential {lab} map ({st} step{'s' if st > 1 else ''} away)"

    def lm_name(self, i: int) -> str:
        """landmark name with the city type: "Vaal city", "Ezomyte city?" (? = guessed by look)"""
        lm = self.V["landmarks"][i]
        if i in getattr(self, "locked_ids", ()):
            return "Locked Breach stronghold"
        if lm["kind"] == "City" and i in getattr(self, "city_type", {}):
            t, how = self.city_type[i]
            return f"{t} city" + ("?" if how == "look-alike" else "")
        return lm["kind"]

    def set_city_type(self, i: int, typ: str | None):
        lm = self.V["landmarks"][i]
        LOG.info(f"city type at ({lm['x']:.0f}, {lm['y']:.0f}) set to {typ or 'automatic'}")
        atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        if self.path:
            self.atlas.save(self.path)
        self.rebuild_model()
        self.request_redraw()

    def on_configure(self, _e=None):
        # the first real size arrives after loading: fit then, so the map isn't fitted to 1x1 px
        if self._fit_pending and self.canvas.winfo_width() > 50:
            self.fit()
        self.request_redraw()

    def _terrain_key(self) -> str:
        import hashlib

        h = hashlib.sha1()
        for f in self.atlas.frames:
            h.update(f["name"].encode())
            h.update(np.round(np.array(f["M"], float), 2).tobytes())
        return h.hexdigest()

    def _terrain_files(self):
        d = core.atlas_files(self.path)
        return d / (self.path.stem + "_terrain.png"), d / (self.path.stem + "_terrain.npz")

    def rebuild_terrain(self, background=True):
        """stitched map: from the cache next to the atlas when it matches, else built in the
        background (the window stays usable; the map appears when it is ready)"""
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
                if canvas is not None and canvas.shape[:2] == weight.shape:
                    self._set_terrain(canvas, weight, origin, save=False)
                    return
        except Exception:
            LOG.debug("map image cache not usable, rebuilding", exc_info=True)
        self._terrain_job += 1
        job = self._terrain_job
        self._set_progress("building the map image (first time for this atlas)…")

        def work():
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

    def _set_terrain(self, canvas, weight, origin, save=True):
        self.root.after(50, self._build_layer_grid)  # the Terrain toggle shows a piece of this map
        self._terrain = (canvas, weight, origin)
        self.t_origin = origin
        pyr = [canvas]
        while max(pyr[-1].shape[:2]) > 600:
            pyr.append(cv2.pyrDown(pyr[-1]))
        self.pyr = pyr
        if getattr(self, "V", None) and self.V.get("nodes"):
            self.rebuild_cities()  # biome clusters follow the ground now
        self._hires = None
        self._pending_outline = []
        if save and self.path:
            key = self._terrain_key()
            png, npz = self._terrain_files()

            def write():
                try:
                    cv2.imencode(".png", canvas)[1].tofile(str(png))
                    np.savez_compressed(npz, key=key, origin=np.array(origin, float), weight=weight.astype(np.float16))
                except Exception:
                    LOG.warning("map image cache could not be saved", exc_info=True)

            threading.Thread(target=write, daemon=True).start()
        self.request_redraw()

    def _paste_terrain(self, frames) -> bool:
        """worker: paste new screenshots into a copy of the stitched map (fast); False when they
        fall outside it and the whole map has to be rebuilt"""
        if self._terrain is None:
            return False
        canvas, weight, origin = self._terrain
        canvas, weight = canvas.copy(), weight.copy()
        if not self.atlas.paste_into(canvas, weight, origin, frames):
            return False
        self._q.put(("terrain_img", (None, canvas, weight, origin)))
        return True
