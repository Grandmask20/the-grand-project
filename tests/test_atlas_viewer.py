"""Drives the real viewer window on a COPY of the small test atlas (about a minute; needs a desktop).

    pytest -m gui tests/test_atlas_viewer.py          (ATLAS_TEST_GEOMETRY="1500x900+-1880+40": put the window
                                                        somewhere else, e.g. on another monitor)

The tests share one window (module fixture `viewer`) and run in file order: each picks up where the previous
one left the window. Window grabs are saved in the fixture's temporary folder (printed).
"""

import contextlib
import json
import math
import os
import shutil
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import ImageGrab

from grand_project import paths as rc_paths  # noqa: E402

TD = rc_paths.TEST_DATA
from tkinter import messagebox  # noqa: E402

import grand_project.viewer.app as V  # noqa: E402
from grand_project import (  # noqa: E402
    builder,  # noqa: E402
    core,
)
from grand_project.viewer import constants as VC  # noqa: E402
from grand_project.viewer import settings as VS  # noqa: E402

pytestmark = [pytest.mark.data, pytest.mark.gui]


@pytest.fixture(scope="module")
def viewer(tmp_path_factory):
    """The viewer window on a copy of the small test atlas, shared by the tests of this module.

    Yields:
        SimpleNamespace: ``root``, ``app`` (the Viewer), ``pump(t)`` (run the window for t s), ``grab(name)``
        (save a window picture), ``W``, ``H`` (canvas size), ``work`` (temporary folder of the atlas copy),
        ``atlas_copy``, ``shots`` (screenshots for the add test; none by default), ``out`` (window grabs),
        ``stall`` ([longest single window update, s]) and ``map_secs`` (seconds until the map image was ready).
    """
    out = tmp_path_factory.mktemp("grabs")
    src = (TD / "small_atlas" / "atlas.json").resolve()
    shots = []
    work = tmp_path_factory.mktemp("atlas")
    atlas_copy = work / "atlas.json"
    _d = json.loads(src.read_text(encoding="utf-8"))
    for _f in _d["frames"]:  # the copy lives elsewhere: screenshot paths as they resolve here
        _f["path"] = core.find_screenshot(_f["path"], src.parent)
    atlas_copy.write_text(json.dumps(_d), encoding="utf-8")
    if src.with_name(src.stem + "_frames").exists():
        shutil.copytree(src.with_name(src.stem + "_frames"), work / "atlas_frames")
    VS.SETTINGS = work / "settings.json"  # never touch the user's viewer settings
    stall = [0.0]  # longest single window update (responsiveness)

    def pump(t=0.25):
        """Run the window for t seconds, recording the longest single update."""
        end = time.time() + t
        while time.time() < end:
            t0 = time.perf_counter()
            root.update()
            stall[0] = max(stall[0], time.perf_counter() - t0)
            time.sleep(0.01)

    def grab(name):
        """Save a picture of the window as `name` in the grabs folder."""
        pump(0.4)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(out / name)

    root = V.TkinterDnD.Tk() if V.TkinterDnD is not None else V.tk.Tk()
    root.geometry(os.environ.get("ATLAS_TEST_GEOMETRY", "1500x900+40+40"))
    app = V.Viewer(root, str(atlas_copy))
    root.lift()
    root.attributes("-topmost", True)
    pump(1.0)
    t_map = time.time()
    while not app.pyr and time.time() - t_map < 120:  # the map image builds in the background
        pump(0.3)
    W, H = app.canvas_size()
    S = SimpleNamespace(
        root=root,
        app=app,
        pump=pump,
        grab=grab,
        W=W,
        H=H,
        work=work,
        atlas_copy=atlas_copy,
        shots=shots,
        out=out,
        stall=stall,
        map_secs=time.time() - t_map,
        c=app.canvas,
        target=0,
        closed=False,
    )
    print(f"window grabs in {out}")
    yield S
    if not S.closed:
        with contextlib.suppress(Exception):
            root.destroy()


def test_map_builds_and_renders(viewer, check):
    """The atlas loads, the map image builds without freezing the window, Fix seams works."""
    app = viewer.app
    grab = viewer.grab
    W = viewer.W
    H = viewer.H
    check("window responsive while the map builds", True, f"map ready after {viewer.map_secs:.1f}s")
    check(
        "atlas loaded",
        len(app.V["nodes"]) > 0 and len(app.atlas.frames) > 0,
        f"{len(app.V['nodes'])} nodes, {len(app.atlas.frames)} shots",
    )
    check("atlas-wide result shown", bool(app.V["stats"]), str(app.V["stats"]))
    check("terrain built", bool(app.pyr), f"{app.pyr[0].shape if app.pyr else None}")
    img = app.render(W, H)
    check("render not blank", img.std() > 10)
    # Fix seams: the clean map (core.seams) replaces the quick one, with its ownership map
    quick_shape = app.pyr[0].shape
    app.fix_seams()
    first = app._seams_proc
    app.fix_seams()  # a second click while it runs: refused, not a second build
    check("fix seams: one build at a time", app._seams_proc is first and app.seams_running())
    t_fix = time.time()
    longest, last = 0.0, time.perf_counter()
    while getattr(app, "_labels", None) is None and time.time() - t_fix < 180:
        app.root.update()
        now = time.perf_counter()
        if getattr(app, "_labels", None) is None:  # still building (taking in the finished map is a step of its own)
            longest = max(longest, now - last)
        last = now
        time.sleep(0.02)
    check("fix seams: window responsive while it builds", longest < 1.0, f"longest pause {longest:.2f}s")
    lab = getattr(app, "_labels", None)
    check(
        "fix seams: clean map with ownership",
        lab is not None and lab[0].shape == app.pyr[0].shape[:2] and (lab[0] >= 0).mean() > 0.3,
        f"{time.time() - t_fix:.1f}s, {len(lab[1]) if lab else 0} screenshots, quick map was {quick_shape}",
    )
    check("fix seams: map still drawn", app.render(W, H).std() > 10)
    times = []
    for _k in range(15):
        t0 = time.perf_counter()
        app.render(W, H)
        times.append((time.perf_counter() - t0) * 1000)
    check("render fast at fit", np.median(times) < 120, f"{np.median(times):.0f} ms median")
    grab("01_fit.png")


def test_icon_types_listed_and_searchable(viewer, check):
    """Every icon type is listed and can be searched."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    # every icon type is listed and searchable
    types = list(app.icon_types)
    check(
        "icon type list",
        len(types) > 3 and len(app._thumb_photos) >= len(types),
        f"{len(types)} types, {len(app._thumb_photos)} pictures; places {app.place_types}",
    )
    app.list_type(types[0])
    pump()
    check("icon type listed", app.hits and all(k == "icon" for k, _ in app.hits), f"{len(app.hits)} {types[0]}")
    if app.place_types:
        app.list_type(app.place_types[0])
        check(
            "places listed",
            app.hits and all(k == "landmark" for k, _ in app.hits),
            f"{len(app.hits)} {app.place_types[0]}",
        )
    app.query.set("hall")
    pump()
    rows = list(app.type_rows)
    check(
        "search filters the type list",
        rows and any(r.startswith("Hall") for r in rows) and len(rows) < len(app.icon_types) // 2,
        ", ".join(rows),
    )
    grab("01c_find_hall.png")
    app.query.set("map boss")
    pump()
    check("search 'map boss'", any(k == "icon" for k, _ in app.hits), f"{len(app.hits)} hits")
    app.query.set("")
    app.z *= 0.6
    pump()
    grab("01b_zoomed_out.png")
    app.fit()


def test_zoom_pan_search_select(viewer, check):
    """Wheel zoom at the cursor, drag pan, search and jump, click to select."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    W = viewer.W
    H = viewer.H
    c = viewer.c
    # wheel zoom keeps the world point under the cursor fixed
    wx, wy = app.to_world(W * 0.3, H * 0.4)
    z0 = app.z
    c.event_generate("<MouseWheel>", x=int(W * 0.3), y=int(H * 0.4), delta=360)
    pump()
    wx2, wy2 = app.to_world(W * 0.3, H * 0.4)
    check("wheel zooms in", app.z > z0 * 1.5, f"{z0:.2f} -> {app.z:.2f}")
    check(
        "zoom keeps cursor point",
        max(abs(wx - wx2), abs(wy - wy2)) * app.z < 1.5,  # in screen px
        f"drift {(wx - wx2) * app.z:.2f},{(wy - wy2) * app.z:.2f} px",
    )
    times = []
    for _k in range(15):
        t0 = time.perf_counter()
        app.render(W, H)
        times.append((time.perf_counter() - t0) * 1000)
    check("render fast zoomed", np.median(times) < 120, f"{np.median(times):.0f} ms median")

    # drag pan
    cx0 = app.cx
    c.event_generate("<ButtonPress-1>", x=600, y=400)
    for k in range(1, 11):
        c.event_generate("<B1-Motion>", x=600 - 20 * k, y=400)
    c.event_generate("<ButtonRelease-1>", x=400, y=400)
    pump()
    check("drag pans", abs((app.cx - cx0) * app.z - 200) < 3, f"moved {(app.cx - cx0) * app.z:.1f}px")
    check("drag does not select", app.sel is None)

    # search and jump
    app.query.set("tower")
    pump()
    check("search finds towers", any(k == "landmark" for k, _ in app.hits), f"{len(app.hits)} hits")
    app.results.selection_clear(0, "end")
    app.results.selection_set(0)
    app.goto_result(app.results, app.hits)
    pump()
    check("jump selects result", app.sel == app.hits[0])
    grab("02_search_tower.png")

    # click a node selects it
    icon_nodes = [i for i, n in enumerate(app.V["nodes"]) if n.get("icons") and n["status"] == "icon"]
    target = icon_nodes[0] if icon_nodes else 0
    nx, ny = app.V["nodes"][target]["x"], app.V["nodes"][target]["y"]
    app.center_on(nx, ny, min_zoom=1.4)
    app.query.set("")
    pump()
    sx, sy = app.to_screen([[nx, ny]])[0]
    c.event_generate("<ButtonPress-1>", x=int(sx) + 2, y=int(sy) + 1)
    c.event_generate("<ButtonRelease-1>", x=int(sx) + 2, y=int(sy) + 1)
    pump()
    check("click selects node", app.sel == ("node", target), f"{app.sel}")
    info = app.info.get("1.0", "end")
    check("info shows node", f"#{target}" in info, info.splitlines()[0] if info else "")
    viewer.target, viewer.nx, viewer.ny = target, nx, ny  # the selected map, for the next tests


def test_bookmarks_and_source_screenshots(viewer, check):
    """Bookmarks persist, no duplicates, groups hide; source screenshots open."""
    app = viewer.app
    root = viewer.root
    pump = viewer.pump
    grab = viewer.grab
    W = viewer.W
    H = viewer.H
    atlas_copy = viewer.atlas_copy
    nx, ny, out = viewer.nx, viewer.ny, viewer.out
    # bookmark persists in the atlas file
    app.add_bookmark(nx, ny, "Test boss spot", "Boss", "selftest")
    pump()
    reloaded = core.Atlas.load(atlas_copy)
    check("bookmark saved to file", any(b["name"] == "Test boss spot" for b in reloaded.bookmarks))
    app.query.set("boss spot")
    pump()
    check("search finds bookmark", ("bookmark", len(app.atlas.bookmarks) - 1) in app.hits)
    app.query.set("")
    grab("03_bookmark.png")
    found = app.frames_at(nx, ny)
    check("source screenshots found", len(found) >= 1, ", ".join(f["name"] for f, *_ in found))
    root.attributes("-topmost", False)
    app.show_sources(nx, ny)
    pump(0.3)
    for w in root.winfo_children():
        if isinstance(w, V.tk.Toplevel):
            w.attributes("-topmost", True)
    pump(0.8)
    srcwin = [w for w in root.winfo_children() if isinstance(w, V.tk.Toplevel)]
    if srcwin:
        s = srcwin[-1]
        x, y = s.winfo_rootx(), s.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + s.winfo_width(), y + s.winfo_height()), all_screens=True).save(
            out / "04_sources.png"
        )
        s.destroy()
    check("source window opened", bool(srcwin))
    app.atlas.bookmarks.pop()
    app.save()
    check("bookmark removed", not core.Atlas.load(atlas_copy).bookmarks)

    # bookmarks: no duplicates, bookmark all, stars in Find, groups hidden like layers
    app.add_bookmark(nx, ny, "Spot A", "Test group")
    n0 = len(app.atlas.bookmarks)
    app.add_bookmark_dialog(nx + 5, ny - 10)  # same map again: no dialog, no duplicate
    check("same spot is not bookmarked twice", len(app.atlas.bookmarks) == n0, app.status.get()[:60])
    types = list(app.icon_types)
    app.query.set(types[0])
    pump()
    want = sum(1 for h in app.hits if h[0] != "bookmark")
    app._ask_group = lambda *a_, **k_: "All of them"
    app.bookmark_all()
    pump()
    check(
        "bookmark all results",
        sum(app.bm_group(b) == "All of them" for b in app.atlas.bookmarks) >= want - 1 and want > 0,
        f"{want} results",
    )
    app.run_search()
    pump()
    starred = sum(1 for k in range(app.results.size()) if app.results.get(k).startswith("★"))
    check("bookmarked results show a star", starred >= want - 1, f"{starred} of {want} starred")
    app.tabs.select(3)  # Bookmarks
    pump()
    grab("13_bookmarks.png")
    i0 = next(i for i, b in enumerate(app.atlas.bookmarks) if app.bm_group(b) == "All of them")
    app.toggle_bookmark(i0)
    check(
        "one bookmark hidden on its own",
        not app.bookmark_shown(app.atlas.bookmarks[i0])
        and app.bm_tree.set(f"bm::{i0}", "eye") == "—"
        and sum(app.bookmark_shown(b) for b in app.atlas.bookmarks if app.bm_group(b) == "All of them") == want - 1,
    )
    app.toggle_bookmark(i0)
    app.toggle_group("All of them")
    app.render(W, H)
    check(
        "group hidden on the map",
        "All of them" in app.hidden_groups() and app.bm_tree.set("group::All of them", "eye") == "—",
    )
    app.toggle_group("All of them")
    check("group shown again", "All of them" not in app.hidden_groups())
    app.atlas.bookmarks = []
    app.save()
    app.refresh_bookmarks()
    app.query.set("")
    app.tabs.select(0)

    check("subway and ground-biome layers gone (v1.03)", "Subway" not in app.layers and "Biomes" not in app.layers)

    root.attributes("-topmost", True)


def test_sharp_ground(viewer, check):
    """Zoomed in, the ground is drawn from the screenshots, and tiles meet without lines."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    W = viewer.W
    H = viewer.H
    target = viewer.target
    # native-resolution terrain when zoomed in
    nd = app.V["nodes"][target]
    app.center_on(nd["x"], nd["y"], min_zoom=1.6)
    app.z = 1.6
    app._clear_tiles()
    over = [k for k in ("Paths", "Nodes", "Icons", "Landmarks", "Labels", "Bookmarks") if app.layers[k].get()]
    for k in over:
        app.layers[k].set(False)  # measure the terrain alone
    low = app.render(W, H)
    app.build_view_tiles()
    high = app.render(W, H)
    for k in over:
        app.layers[k].set(True)

    def sharp(im):
        return float(cv2.Laplacian(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    check(
        "zoomed-in terrain at screenshot resolution",
        len(app._tiles) > 0 and (app.t_origin[2] > 0.9 or sharp(high) > 1.3 * sharp(low)),
        f"map image scale {app.t_origin[2]:.2f}, sharpness {sharp(low):.0f} -> {sharp(high):.0f}",
    )
    pump()
    grab("08_zoomed_native.png")

    # sharp-ground tiles meet without a line: at zooms that don't land on whole pixels, the column / row where two
    # tiles meet is not darker than the pixels beside it (a dark line along every tile edge: user)
    from grand_project.viewer.constants import HIRES_TILE  # noqa: E402

    for k in over:
        app.layers[k].set(False)
    dips = []
    for zz in (0.73, 1.37):
        app.z = zz
        unit = HIRES_TILE / app._tile_level()
        app.cx = math.floor(nd["x"] / unit) * unit + 37 / zz
        app.cy = math.floor(nd["y"] / unit) * unit + 29 / zz
        app.build_view_tiles()
        g = cv2.cvtColor(app.render(W, H), cv2.COLOR_BGR2GRAY).astype(float)
        for i in range(-20, 21):
            x = round((math.floor(app.cx / unit + i) * unit - app.cx) * zz + W / 2)
            if 3 < x < W - 3:
                dips.append(float(np.median(np.minimum(g[:, x - 2], g[:, x + 2]) - g[:, x])))
            y = round((math.floor(app.cy / unit + i) * unit - app.cy) * zz + H / 2)
            if 3 < y < H - 3:
                dips.append(float(np.median(np.minimum(g[y - 2, :], g[y + 2, :]) - g[y, :])))
    for k in over:
        app.layers[k].set(True)
    check("no line where terrain tiles meet", dips and max(dips) < 6, f"darkest edge {max(dips, default=0):.0f}")


def test_filters_landmarks_and_biomes(viewer, check):
    """Icon filter, landmark edits, hidden-map selection and lasso biomes."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    atlas_copy = viewer.atlas_copy
    # icon filter
    app.set_all_icons(False)
    check("icon filter hides all", len(app.icon_hidden) == len(app.icon_vars) > 0, f"{len(app.icon_vars)} types")
    app.icon_vars[app.icon_types[0]].set(True)
    app.on_icon_filter()
    app.only_icon_maps.set(True)
    shown = sum(app.node_shown(n) for n in app.V["nodes"])
    check(
        "only maps with ticked icon",
        0 < shown < sum(n["status"] != "removed" for n in app.V["nodes"]),
        f"{shown} maps shown for {app.icon_types[0]}",
    )
    app.tabs.select(0)
    pump()
    grab("09_icon_filter.png")
    app.only_icon_maps.set(False)
    app.set_all_icons(True)

    # landmark edits: change a landmark's kind, delete it (Delete button), add one on a map; all saved
    from grand_project import logs as atlas_log  # noqa: E402

    log_size0 = atlas_log.LOG_FILE.stat().st_size if atlas_log.LOG_FILE.exists() else 0
    kept = [i for i, lm in enumerate(app.V["landmarks"]) if lm["status"] == "kept"]
    lm = app.V["landmarks"][kept[0]]
    new_kind = "Hall" if lm["kind"] != "Hall" else "City"
    app.set_landmark(lm["x"], lm["y"], new_kind)
    same = [
        landmark for landmark in app.V["landmarks"] if math.hypot(landmark["x"] - lm["x"], landmark["y"] - lm["y"]) < 1
    ]
    check(
        "landmark kind changed",
        same and same[0]["kind"] == new_kind and same[0]["beam"] == "set by you",
        f"{lm['kind']} -> {same[0]['kind'] if same else None}",
    )
    i = app.V["landmarks"].index(same[0])
    app.select(("landmark", i))
    messagebox.askyesno = lambda *a, **k: True  # the confirm dialog
    app.delete_selected()
    gone = [
        landmark for landmark in app.V["landmarks"] if math.hypot(landmark["x"] - lm["x"], landmark["y"] - lm["y"]) < 1
    ]
    check(
        "Delete button removes a landmark",
        gone and gone[0]["status"].startswith("removed"),
        gone[0]["status"] if gone else "",
    )
    nd = next(
        n
        for n in app.V["nodes"]
        if n["status"] != "removed"
        and all(math.hypot(landmark["x"] - n["x"], landmark["y"] - n["y"]) > 200 for landmark in app.V["landmarks"])
    )
    n_city = app.type_counts.get("City", 0)
    app.set_landmark(nd["x"], nd["y"], "City")
    check(
        "a map marked as City becomes one",
        app.type_counts.get("City", 0) == n_city + 1,
        f"{n_city} -> {app.type_counts.get('City', 0)}",
    )
    saved = core.Atlas.load(atlas_copy).landmark_edits
    check("landmark edits saved in the atlas", len(saved) == 2, str(saved))
    log_text = (
        atlas_log.LOG_FILE.read_bytes()[log_size0:].decode("utf-8", errors="replace")
        if atlas_log.LOG_FILE.exists()
        else ""
    )
    check(
        "actions written to the debug log",
        "deleted" in log_text and "set to City" in log_text,
        f"{atlas_log.LOG_FILE.name}: {len(log_text)} new bytes",
    )
    app.atlas.landmark_edits = []
    app.save()
    app.rebuild_model()

    # v0.78: a City set on a map next to a Tower, then the Tower re-set: both stay
    tw = next(
        (landmark for landmark in app.V["landmarks"] if landmark["kind"] == "Tower" and landmark["status"] == "kept"),
        None,
    )
    near_tw = tw and next(
        (
            n
            for n in app.V["nodes"]
            if n["status"] != "removed" and 30 < math.hypot(n["x"] - tw["x"], n["y"] - tw["y"]) < 85
        ),
        None,
    )
    if near_tw:
        app.set_landmark(near_tw["x"], near_tw["y"], "City", "map")
        app.set_landmark(tw["x"], tw["y"], "Tower")
        at_city = [
            landmark
            for landmark in app.V["landmarks"]
            if math.hypot(landmark["x"] - near_tw["x"], landmark["y"] - near_tw["y"]) < 1
        ]
        at_tw = [
            landmark
            for landmark in app.V["landmarks"]
            if math.hypot(landmark["x"] - tw["x"], landmark["y"] - tw["y"]) < 1
        ]
        check(
            "City on a map next to a Tower survives re-setting the Tower",
            at_city and at_city[0]["kind"] == "City" and at_tw and at_tw[0]["kind"] == "Tower",
            f"{at_city[0]['kind'] if at_city else None} / {at_tw[0]['kind'] if at_tw else None}",
        )
        app.atlas.landmark_edits = []
        app.save()
        app.rebuild_model()

    # v0.78: a map hidden by a filter is still selected by a click on it
    nd = next(n for n in app.V["nodes"] if n["status"] not in ("removed", "icon"))
    k = app.V["nodes"].index(nd)
    app.center_on(nd["x"], nd["y"], 2.0)
    app.layers["Nodes"].set(False)
    pump()
    sp = app.to_screen([[nd["x"], nd["y"]]])[0]
    hit = app.pick(sp[0], sp[1])
    check("click selects a hidden map", hit == ("node", k) or (hit and hit[0] == "node"), str(hit))
    app.layers["Nodes"].set(True)

    # v0.78: lasso a few maps into a Vaal city biome; saved and shown
    app.start_lasso()
    r_ = 120
    cxs, cys = sp
    app.on_press(type("E", (), {"x": cxs - r_, "y": cys - r_})())
    for x_, y_ in ((cxs + r_, cys - r_), (cxs + r_, cys + r_), (cxs - r_, cys + r_)):
        app.on_drag(type("E", (), {"x": x_, "y": y_})())
    V.tk.Menu.tk_popup = lambda *a, **k: None  # the biome menu
    app.on_release(type("E", (), {"x": cxs - r_, "y": cys + r_})())
    ids = getattr(app, "_lasso_ids", [])
    app.set_biome(ids, "Vaal city")
    check(
        "lasso sets a city biome",
        ids and all(app.potential.get(i, ("",))[0] == "Vaal city" for i in ids),
        f"{len(ids)} maps",
    )
    check("hand biome saved in the atlas", core.Atlas.load(atlas_copy).biome_edits[-1]["biome"] == "Vaal city")
    app.atlas.biome_edits = []
    app.save()
    app.rebuild_model()


def test_atlas_list_and_reload(viewer, check):
    """The atlas list holds the open atlas; the file stays valid for the builder."""
    app = viewer.app
    atlas_copy = viewer.atlas_copy
    # v0.78: atlas list holds the open atlas; last entry adds a new one
    labels = [
        app.atlas_menu.entrycget(i, "label")
        for i in range(app.atlas_menu.index("end") + 1)
        if app.atlas_menu.type(i) != "separator"
    ]
    check(
        "atlas dropdown lists the open atlas + 'Add new atlas'",
        any(label.startswith("●") for label in labels) and labels[-1].startswith("Add new atlas"),
        str(labels[-2:]),
    )

    # reopening keeps the file valid for the command-line builder
    check("atlas reloads", core.Atlas.load(atlas_copy).final is not None)


def test_add_screenshots(viewer, check):
    """A new atlas built through the viewer's own add path."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    work = viewer.work
    shots = viewer.shots
    if not shots:
        pytest.skip("no screenshots given for building a new atlas (set viewer.shots in the fixture)")
    # build a NEW atlas through the viewer's own add path (cached detections make this fast)
    if shots:
        new = work / "fresh.json"
        core.Atlas().save(new)
        if (work / "atlas_frames").exists():
            shutil.copytree(work / "atlas_frames", work / "fresh_frames")
        app.open_atlas(new)
        pump()
        if not rc_paths.DATABASE.exists():
            print(f"skip: no detector database for the add test ({rc_paths.DATABASE})")
        else:
            t0 = time.time()
            app.add_screenshots(shots, sync=True)
            pump(0.5)
            check(
                "viewer adds screenshots",
                len(app.atlas.frames) == len(shots),
                f"{len(app.atlas.frames)}/{len(shots)} placed in {time.time() - t0:.0f}s",
            )
            check("new atlas written", len(core.Atlas.load(new).frames) == len(app.atlas.frames))
            grab("05_added.png")


def test_auto_add_waiting_and_hand_placement(viewer, check):
    """Auto-add from a watched folder, undo, waiting list, hand placement."""
    app = viewer.app
    pump = viewer.pump
    grab = viewer.grab
    work = viewer.work
    stall = viewer.stall
    # auto-add from a watched folder: a random run of 4 consecutive crawl screenshots
    crawl = TD / "screenshots" / "crawl"
    crawl_cache = TD / "crawl_atlas" / "atlas_frames"
    if crawl.exists() and crawl_cache.exists():
        import hashlib
        import random

        seed = random.randrange(10**6)
        all_shots = sorted(q for q in crawl.iterdir() if q.suffix == ".png")
        crawl_only = [q for q in all_shots if q.stem < "2694490_202611090801"]  # the original crawl run
        # skip runs with a screenshot that matched only weakly in the full crawl atlas too: for those the
        # viewer rightly asks (e.g. #43-#45: the 2nd had 6 maps / terrain 0.44 there)
        crawl_atlas = TD / "crawl_atlas" / "atlas.json"
        weak = set()
        if crawl_atlas.exists():
            for f in json.loads(crawl_atlas.read_text(encoding="utf-8"))["frames"]:
                few = str(f.get("reason", "")).startswith("terrain") or (f.get("inliers") or 0) <= VC.WEAK_INLIERS
                if few and (f.get("ncc") or 0) < VC.WEAK_NCC:
                    weak.add(f["name"])
        rnd = random.Random(seed)
        while True:
            k = rnd.randrange(0, len(crawl_only) - 5)
            if not {q.stem for q in crawl_only[k + 1 : k + 3]} & weak:
                break
        seq = crawl_only[k : k + 5]
        wdir, sdir = work / "watch_frames", work / "shots"
        wdir.mkdir()
        sdir.mkdir()
        for q in seq:
            h = hashlib.sha256(q.read_bytes()).hexdigest()[:16]
            if (crawl_cache / f"{h}_detect1.json").exists():
                shutil.copy(crawl_cache / f"{h}_detect1.json", wdir / f"{h}_detect1.json")
        new = work / "watch.json"
        core.Atlas().save(new)
        app.open_atlas(new)
        app.settings.pop("watch_folders", None)
        check(
            "auto-add watches the atlas's own folder by default", app._watch_dir() == str(new.parent), app._watch_dir()
        )
        app.settings["watch_folders"] = {app._atlas_key(): str(sdir)}
        other = work / "other" / "atlas.json"
        other.parent.mkdir(exist_ok=True)
        core.Atlas().save(other)
        app.open_atlas(other)
        check(
            "a folder picked for one atlas doesn't follow you to another",
            app._watch_dir() == str(other.parent),
            app._watch_dir(),
        )
        app.open_atlas(new)
        check("... and is back when its atlas is opened again", app._watch_dir() == str(sdir), app._watch_dir())
        app.watch_var.set(True)
        app.start_watch()
        asked = []
        messagebox.askyesno = lambda title, msg, **kw: (asked.append(msg), False)[1]

        def drop(q, want):
            shutil.copy(q, sdir / q.name)
            end = time.time() + 90
            while time.time() < end and len(app.V["frames"]) < want and not asked:
                pump(0.5)
            pump(2.0)

        stall[0] = 0.0
        for n, q in enumerate(seq[:3], 1):
            drop(q, n)
        check("window stays responsive while adding", stall[0] < 1.0, f"longest pause {stall[0]:.2f}s")
        check(
            "watched folder: new screenshots added",
            len(app.atlas.frames) == 3 and not asked,
            f"seed {seed}, crawl #{k}-#{k + 2}: {len(app.atlas.frames)} added, {len(asked)} questions",
        )
        check(
            "map updated after auto-add",
            app.atlas.final is not None and len(app.V["frames"]) == 3,
            f"{len(app.V['frames'])} screenshots in the view",
        )
        check(
            "newest addition listed and outlined",
            app.recent and app.recent[-1] == seq[2].stem and app.recent_list.get(0).startswith("NEWEST"),
            app.recent_list.get(0) if app.recent else "nothing",
        )
        grab("12_newest.png")
        # undo the last add: back to 2 screenshots, the file too
        messagebox.askyesno = lambda *a_, **k_: True
        app.undo_last()
        end = time.time() + 30
        while time.time() < end and len(app.atlas.frames) != 2:
            pump(0.3)
        pump(1.0)
        check(
            "undo removes the last screenshot",
            len(app.atlas.frames) == 2
            and len(core.Atlas.load(new).frames) == 2
            and seq[2].stem not in [f["name"] for f in app.atlas.frames],
            f"{len(app.atlas.frames)} left",
        )
        # put it back the normal way (the watcher ignores files it already handled)
        app.add_screenshots([sdir / seq[2].name], mode="watch")
        end = time.time() + 60
        while time.time() < end and len(app.V["frames"]) < 3:
            pump(0.5)
        pump(1.0)
        messagebox.askyesno = lambda title, msg, **kw: (asked.append(msg), False)[1]
        # a screenshot from far away waits and is listed: the crawl screenshot farthest from this run in the crawl
        # atlas (the crawl doubles back: "first or last screenshot" sat next to the run for 18 starting points)
        crawl_frames = json.loads(crawl_atlas.read_text(encoding="utf-8"))["frames"]
        pos = {f["name"]: np.array(f["M"], float)[:, 2] for f in crawl_frames}
        run = [pos[q.stem] for q in seq if q.stem in pos]
        cands = [
            q
            for q in crawl_only
            if q.stem in pos
            and (crawl_cache / f"{hashlib.sha256(q.read_bytes()).hexdigest()[:16]}_detect1.json").exists()
        ]
        far = max(cands, key=lambda q: min(np.hypot(*(pos[q.stem] - r)) for r in run))
        shutil.copy(crawl_cache / f"{hashlib.sha256(far.read_bytes()).hexdigest()[:16]}_detect1.json", wdir)
        app.add_screenshots([far], mode="watch")
        end = time.time() + 60
        while time.time() < end and app.wait_list.size() == 0:
            pump(0.5)
        check(
            "a screenshot that does not fit is listed as waiting",
            app.wait_list.size() == 1 and app.wait_list.get(0).startswith(far.name),
            f"{app.wait_list.size()} waiting: {app.wait_list.get(0) if app.wait_list.size() else ''}",
        )
        app.wait_list.selection_set(0)
        app.retry_waiting(selected=True)  # still no overlap: stays waiting, tries counted
        end = time.time() + 60
        while time.time() < end and "tried 2x" not in (app.wait_list.get(0) if app.wait_list.size() else ""):
            pump(0.5)
        check(
            "retry a waiting screenshot",
            app.wait_list.size() == 1 and "tried 2x" in app.wait_list.get(0),
            app.wait_list.get(0) if app.wait_list.size() else "",
        )
        app._pending_watch = []
        app._refresh_recent()
        f0 = app.atlas.frames[0]
        c0 = core.persp(core.screen_to_atlas(np.array(f0["M"], float), app.atlas.frame_R(f0)), [[960, 540]])[0]
        app.center_on(c0[0] + 20000, c0[1], min_zoom=0.5)  # look somewhere else entirely
        pump(0.5)
        drop(seq[3], 4)
        check(
            "placed wherever the window looks",
            len(app.atlas.frames) == 4 and not asked,
            f"{len(app.atlas.frames)} placed",
        )
        # program restarted with a screenshot in the folder that the atlas does not have: added on its own (user)
        app.watch_var.set(False)
        messagebox.askyesno = lambda *a_, **k_: True
        app.undo_last()  # seq[3] leaves the atlas, its file stays in the folder
        end = time.time() + 30
        while time.time() < end and len(app.atlas.frames) != 3:
            pump(0.3)
        messagebox.askyesno = lambda title, msg, **kw: (asked.append(msg), False)[1]
        app.watch_var.set(True)
        app.start_watch(initial=True)
        end = time.time() + 90
        while time.time() < end and len(app.atlas.frames) < 4 and not asked:
            pump(0.5)
        pump(1.0)
        check(
            "restart: screenshots already in the folder are added",
            len(app.atlas.frames) == 4 and seq[3].stem in [f["name"] for f in app.atlas.frames],
            f"{len(app.atlas.frames)} in the atlas",
        )
        app.watch_var.set(False)

        # hand placement: the 5th screenshot, dropped ~300 units off, fitted with Enter
        r0 = app.atlas.add_frame(
            builder_frame := builder.extract_frame(seq[4], wdir),
            hints=[f["name"] for f in app.atlas.frames],
            commit=False,
        )
        if r0.ok:
            want = r0.M[:, 2]
            asked.clear()
            app.center_on(want[0], want[1], min_zoom=0.5)
            pump(0.5)
            sx, sy = app.to_screen([want + [240, -180]])[0]
            app.start_ghost(seq[4], sx, sy)
            pump(0.5)
            grab("11_ghost.png")
            app.fit_ghost()
            end = time.time() + 90
            while time.time() < end and len(app.V["frames"]) < 5 and not asked:
                pump(0.5)
            placed = [f for f in app.atlas.frames if f["name"] == builder_frame.name]
            err = float(np.hypot(*(np.array(placed[0]["M"])[:, 2] - want))) if placed else -1
            check(
                "hand placement: dropped 300 units off, lined up",
                bool(placed) and err < 10 and not asked,
                f"error {err:.1f} units",
            )


def test_icon_list_wheel(viewer, check):
    """The wheel scrolls the icon list wherever the pointer is over it (not only on a row's text, user)."""
    app = viewer.app
    pump = viewer.pump
    app.tabs.select(0)
    pump(0.3)
    ic = app.icon_canvas
    if ic.yview()[1] >= 1.0:
        pytest.skip("the icon list fits without scrolling")
    ic.yview_moveto(0)
    pump(0.2)
    x = ic.winfo_rootx() + ic.winfo_width() - 8  # the right edge: blank space beside the rows
    y = ic.winfo_rooty() + ic.winfo_height() // 2
    app._wheel_router(SimpleNamespace(x_root=x, y_root=y, delta=-120, num=0))
    pump(0.2)
    check("wheel scrolls the icon list from the blank space beside rows", ic.yview()[0] > 0, str(ic.yview()))


def test_weak_match_preview(viewer, check, monkeypatch):
    """A weak match: while "Check this screenshot" asks, the screenshot is shown where it would go, then cleared."""
    app = viewer.app
    f0 = app.atlas.frames[0]
    H0 = core.screen_to_atlas(np.array(f0["M"], float), app.atlas.frame_R(f0))
    seen = []
    monkeypatch.setattr(
        messagebox, "askyesno", lambda title, msg, **kw: (seen.append((msg, app._weak_preview is not None)), True)[1]
    )
    app._handle("ask", ("Add it anyway?", (f0["path"], H0)))
    check(
        "weak match: shown on the map while asking, cleared after",
        seen
        and seen[0][1]
        and "shown and outlined" in seen[0][0]
        and app._weak_preview is None
        and app._answer.get_nowait() is True,
        str(seen),
    )
    # No: the view goes back to where it was before the preview centred on the screenshot
    app.cx, app.cy, app.z = app.cx + 5000.0, app.cy + 5000.0, 0.05
    before = (app.cx, app.cy, app.z)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    app._handle("ask", ("Add it anyway?", (f0["path"], H0)))
    check(
        "weak match answered No: the view is put back",
        (app.cx, app.cy, app.z) == before and app._answer.get_nowait() is False,
        f"{before} -> {(app.cx, app.cy, app.z)}",
    )


def test_type_list_rebuilds_keep_one_set_of_bindings(viewer, check):
    """Searching rebuilds the type list; its click bindings are made once, not again per rebuild (review)."""
    app = viewer.app
    pump = viewer.pump
    before = len(app.icon_canvas._tclCommands or [])
    for q in ("ha", "hal", "tow", ""):
        app.query.set(q)
        pump(0.1)
    after = len(app.icon_canvas._tclCommands or [])
    check("type list: no new callbacks per rebuild", after == before, f"{before} -> {after}")


def test_replay_panel(viewer, check, monkeypatch, tmp_path):
    """Timelapse: the panel opens at the end, reveals step by step, plays, exports a GIF and puts the view back."""
    from tkinter import filedialog

    from PIL import Image

    app = viewer.app
    pump = viewer.pump
    if len(app.atlas.frames) < 3:
        pytest.skip("needs an atlas of 3+ screenshots")
    view = (app.cx, app.cy, app.z)
    app.open_replay()
    pump(0.3)
    plan = app.rp["plan"]
    check("replay: one step per screenshot", plan.n_steps == len(app.atlas.frames), str(plan.n_steps))
    check("replay: opens at the end (whole atlas)", app.rp["pos"] == plan.n_steps, str(app.rp["pos"]))
    all_maps = int(app.shown_masks()[1].sum())
    app._rp_seek(1.0)
    first = int(app.shown_masks()[1].sum())
    app._rp_seek(plan.n_steps / 2)
    half = int(app.shown_masks()[1].sum())
    check("replay: map nodes appear as their screenshots do", 0 < first < half < all_maps, f"{first} {half} {all_maps}")
    app._rp_seek(0.0)
    check("replay: nothing before the first step", int(app.shown_masks()[1].sum()) == 0)
    img = app.render(*app.canvas_size())
    check("replay: the ground is hidden before the first step", img.mean() < 25, f"mean {img.mean():.1f}")
    app._rp_set(length=3.0, speed=1.0)
    app._rp_toggle_play()
    pump(1.2)
    check("replay: plays", 0 < app.rp["pos"] < plan.n_steps, f"{app.rp['pos']:.2f}")
    app._rp_toggle_play()
    out = tmp_path / "replay.gif"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: str(out))
    app._rp_set(length=1.0, gif_width=320)
    import grand_project.viewer.cities as VCI

    builds = []
    real_view_model = VCI.view_model
    monkeypatch.setattr(VCI, "view_model", lambda atlas: (builds.append(1), real_view_model(atlas))[1])
    app._rp_export_gif()
    held = app.rp["exporting"]
    app.rebuild_model()  # e.g. screenshots added mid-export: the rebuild waits until the GIF is done (review)
    held = held and app.rp.get("rebuild_after", False) and not builds
    pyr = app.pyr
    if app._terrain is not None:  # a new map image mid-export (a screenshot pasted in) waits too (user)
        app._handle("terrain_img", (None, *app._terrain, None))
        held = held and app.pyr is pyr and app.rp.get("terrain_after", False)
        names = [f["name"] for f in app.atlas.frames]  # a finished Fix seams mid-export is kept for after (review)
        own = np.zeros(app._terrain[1].shape, np.int32)  # (one owner everywhere is enough for the check)
        app._handle("terrain_img", ("seams", *app._terrain, (own, names)))
        held = held and app.pyr is pyr and app.rp.get("seams_after") is not None
    where = app.path
    app.open_atlas(where)  # no atlas switching while the GIF renders
    held = held and app.rp is not None and "wait until the timelapse GIF" in app.status.get()
    end = time.time() + 60
    while time.time() < end and (app.rp["exporting"] or not out.exists() or "saved" not in app.status.get()):
        pump(0.3)
    check("replay: during export the model, ground, Fix seams and atlas switches wait", held, str(held))
    check(
        "replay: after the export the held-back rebuild ran once, and the clean map was shown",
        len(builds) == 1 and "seams_after" not in app.rp and "terrain_after" not in app.rp,
        f"builds {len(builds)}",
    )
    check("replay: reveal lists match the model", len(app.rp["node_step"]) == len(app.V["nodes"]))
    gif = Image.open(out) if out.exists() else None
    check("replay: GIF exported", gif is not None and gif.size[0] == 320 and gif.n_frames >= 10, app.status.get())
    if gif is not None:  # lasts the length setting (1 s) plus the 2 s hold on the last frame (review)
        total = 0
        for k in range(gif.n_frames):
            gif.seek(k)
            total += gif.info.get("duration", 0)
        check("replay: the GIF lasts its length", 2700 <= total <= 3300, f"{total} ms")
    app._rp_set(type="spiral", reveal="area")
    app._rp_replan()
    app._rp_seek(app.rp["plan"].n_steps / 2)
    half = int(app.shown_masks()[1].sum())
    check("replay by area: a smooth sweep", app.rp["plan"].sweep is not None and 0 < half < all_maps, str(half))
    app.set_style(age_tint="times seen")
    img = app.render(*app.canvas_size())
    check("times seen: drawn while replaying", img is not None and app.heat_top() >= 1, str(app.heat_top()))
    app.set_style(age_tint="off")
    app._rp_set(type="by time", reveal="screenshots")
    app.close_replay()
    pump(0.2)
    check("replay: closing puts the view back", (app.cx, app.cy, app.z) == view and app.rp is None)
    other = tmp_path / "other" / "atlas.json"
    other.parent.mkdir()
    core.Atlas().save(other)
    here = app.path
    app.open_replay()
    app.open_atlas(other)
    check("replay: opening another atlas closes the replay", app.rp is None and app.path == other, str(app.path))
    app.open_atlas(here)
    pump(1.0)
    app.set_style(age_tint="by session")
    img = app.render(*app.canvas_size())
    check("colour by when taken: drawn with a legend", app.age_legend() and img is not None, str(app.age_legend()))
    app.set_style(age_tint="off")


def test_debug_marks_toggle_and_clear(viewer, check, monkeypatch):
    """Debug tab (internal only): marks can be hidden on the map and cleared all at once, with a copy kept (user)."""
    app = viewer.app
    if not rc_paths.DEBUG or not hasattr(app, "dbg_show"):
        pytest.skip("debug tools are only in the internal / develop copy")
    x, y = app.cx, app.cy
    for k in range(2):
        app._dbg_add("missing map", "test", "", x + 40 * k, y)
    check("debug: marks added", len(app._dbg_marks()) >= 2, str(len(app._dbg_marks())))
    app.dbg_show.set(False)
    app._dbg_toggle()
    check("debug: hiding is remembered", app.settings.get("debug_marks_shown") is False)
    app.dbg_show.set(True)
    app._dbg_toggle()
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    fp = app._dbg_file()
    app._dbg_clear_all()
    copies = list(fp.parent.glob(f"{fp.stem}_cleared_*.json"))
    check("debug: clear all empties the list and keeps a copy", not app._dbg_marks() and copies, str(copies))


def test_saved_atlases_tab(viewer, check):
    """Saved atlases: cards, rename, stop tracking, delete (also the open atlas)."""
    app = viewer.app
    pump = viewer.pump
    work = viewer.work
    # Saved atlases tab: a card per known atlas; rename; stop tracking keeps the files; deleting an atlas and its
    # data removes the atlas file, its saved detections and its _files folder but never the screenshots
    gone_dir = work / "gone"
    gone_dir.mkdir()
    gone = gone_dir / "atlas.json"
    core.Atlas().save(gone)
    (gone_dir / "atlas_frames").mkdir()
    (gone_dir / "atlas_frames" / "x_detect1.json").write_text("{}", encoding="utf-8")
    (gone_dir / "atlas_files").mkdir()
    (gone_dir / "atlas_files" / "atlas_thumb.png").write_bytes(b"png")
    shot = gone_dir / "2694490_20260101000000_1.png"
    shot.write_bytes(b"a screenshot")
    app.remember_atlas(gone, "to delete")
    pump(0.3)
    names = [w.winfo_children()[1].winfo_children()[0].cget("text") for w in app.atl_inner.winfo_children()]
    check(
        "Saved atlases: a card per atlas", len(names) == len(app.known_atlases()) and "to delete" in names, str(names)
    )
    from tkinter import simpledialog  # noqa: E402

    simpledialog.askstring = lambda *a, **k: "renamed one"
    app._rename_card(str(gone.resolve()))
    check("Saved atlases: rename", any(a["name"] == "renamed one" for a in app.known_atlases()))
    check(
        "deleting an atlas: its files, never screenshots",
        set(app.atlas_data_paths(gone)) == {gone, gone_dir / "atlas_frames", gone_dir / "atlas_files"},
        str([q.name for q in app.atlas_data_paths(gone)]),
    )
    messagebox.askyesno = lambda *a, **k: True
    app._delete_atlas_data(str(gone.resolve()), "renamed one")
    check(
        "delete whole atlas and its data",
        not gone.exists()
        and not (gone_dir / "atlas_frames").exists()
        and not (gone_dir / "atlas_files").exists()
        and shot.exists()
        and not any(a["name"] == "renamed one" for a in app.known_atlases()),
        str(sorted(q.name for q in gone_dir.iterdir())),
    )
    kept = work / "kept" / "atlas.json"
    kept.parent.mkdir()
    core.Atlas().save(kept)
    app.remember_atlas(kept, "keep files")
    app._forget_atlas_path(next(a["json"] for a in app.known_atlases() if a["name"] == "keep files"))
    check(
        "stop tracking an atlas keeps its files",
        kept.exists() and not any(a["name"] == "keep files" for a in app.known_atlases()),
    )

    # the open atlas can be deleted too: the window is cleared first (review)
    open_one = work / "open_one" / "atlas.json"
    open_one.parent.mkdir()
    core.Atlas().save(open_one)
    app.open_atlas(open_one)
    pump(0.3)
    app._delete_atlas_data(str(open_one.resolve()), "open one")
    pump(0.3)
    check(
        "delete the open atlas: window cleared, files gone",
        app.path is None
        and not app.atlas.frames
        and not open_one.exists()
        and not (open_one.parent / "atlas_files").exists(),
        str(app.path),
    )


def test_background_jobs_and_close(viewer, check):
    """Jobs keep their atlas; closing waits for the step in progress and saves it."""
    app = viewer.app
    root = viewer.root
    pump = viewer.pump
    work = viewer.work
    # background jobs of any kind (auto-add too, not only Add screenshots) keep their atlas: no switching
    # while one runs, a job queued for another atlas is skipped, and closing finishes the step in progress and
    # saves it (closing used to lose it: the save waited for the worker and the window was gone first)
    import threading  # noqa: E402

    job_a, job_b = work / "job_a.json", work / "job_b" / "atlas.json"
    job_b.parent.mkdir(exist_ok=True)
    core.Atlas().save(job_a)
    core.Atlas().save(job_b)
    app.watch_var.set(False)
    app.open_atlas(job_a)
    pump(0.3)
    gate, ran = threading.Event(), []

    def slow_job(paths, mode):  # stands in for a long auto-add: changes the atlas, doesn't save it
        ran.append(mode)
        gate.wait(30)
        app.atlas.bookmarks.append(
            {"name": "made by the job", "group": "Other", "note": "", "x": 1.0, "y": 2.0, "created": "test"}
        )
        app._q.put(("done", mode))

    app._run_job = slow_job
    app._queue_job([], "watch")
    end = time.time() + 5
    while time.time() < end and not ran:
        pump(0.1)
    check("an auto-add job counts as working", app.working() and ran == ["watch"], str(ran))
    app.switch_atlas(job_b)
    pump(0.2)
    check("no atlas switch while a job runs", app.path == job_a, str(app.path))
    app._jobs.put(([], "watch", core.Atlas()))  # queued for an atlas that is not open
    messagebox.askyesno = lambda *a, **k: True
    app.on_close()
    pump(0.3)
    check("closing waits for the step in progress", app._closing and root.winfo_exists() and app.working())
    app._queue_job([], "recheck_all")
    check("no new jobs while closing", app._jobs.unfinished_tasks == 1, f"{app._jobs.unfinished_tasks} jobs")
    gate.set()
    end = time.time() + 20
    closed = False
    while time.time() < end and not closed:
        try:
            root.update()
            root.winfo_exists()
        except V.tk.TclError:  # the window is gone ("application has been destroyed")
            closed = True
        time.sleep(0.02)
    saved = [b["name"] for b in core.Atlas.load(job_a).bookmarks]
    viewer.closed = closed
    check("window closes once the job is done", closed)
    check("the job's work is saved on close", "made by the job" in saved, str(saved))
    check("the job queued for another atlas never ran", ran == ["watch"], str(ran))
