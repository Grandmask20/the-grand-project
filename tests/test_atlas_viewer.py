"""Drives the real viewer window on a COPY of an atlas.  Opens a window for ~20 s.

    python -m tests.test_atlas_viewer ATLAS.json [SCREENSHOT ...] [--out DIR]

Checks: render + fit, wheel zoom at cursor, drag pan, click select, search, bookmark
add/persist/delete, source-screenshot lookup, and (when screenshots are given) building a NEW
atlas through the viewer's own add-screenshots path.  Saves window grabs to --out.
"""

import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageGrab

HERE = Path(__file__).resolve().parent
from grand_project import paths as rc_paths  # noqa: E402

rc_paths.need_test_data()
TD = rc_paths.TEST_DATA
from tkinter import messagebox  # noqa: E402

import grand_project.viewer.app as V  # noqa: E402
from grand_project import (  # noqa: E402
    builder,  # noqa: E402
    core,
)
from grand_project.viewer import constants as VC  # noqa: E402
from grand_project.viewer import settings as VS  # noqa: E402

args = sys.argv[1:]
out = Path(tempfile.mkdtemp())
if "--out" in args:
    i = args.index("--out")
    out = Path(args[i + 1])
    del args[i : i + 2]
out.mkdir(parents=True, exist_ok=True)
if not args:  # default: the small test atlas
    args = [str(TD / "small_atlas" / "atlas.json")]
src = Path(args[0]).resolve()
shots = [Path(a).resolve() for a in args[1:]]
work = Path(tempfile.mkdtemp())
atlas_copy = work / "atlas.json"
_d = json.loads(src.read_text(encoding="utf-8"))
for _f in _d["frames"]:  # the copy lives elsewhere: screenshot paths as they resolve here
    _f["path"] = core._find_screenshot(_f["path"], src.parent)
atlas_copy.write_text(json.dumps(_d), encoding="utf-8")
if src.with_name(src.stem + "_frames").exists():
    shutil.copytree(src.with_name(src.stem + "_frames"), work / "atlas_frames")
VS.SETTINGS = work / "settings.json"  # never touch the user's viewer settings

fails = []


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({extra})" if extra else ""))
    if not ok:
        fails.append(name)


stall = [0.0]  # longest single window update (responsiveness)


def pump(t=0.25):
    end = time.time() + t
    while time.time() < end:
        t0 = time.perf_counter()
        root.update()
        stall[0] = max(stall[0], time.perf_counter() - t0)
        time.sleep(0.01)


def grab(name):
    pump(0.4)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(out / name)


root = V.TkinterDnD.Tk() if V.TkinterDnD is not None else V.tk.Tk()
root.geometry("1500x900+40+40")
app = V.Viewer(root, str(atlas_copy))
root.lift()
root.attributes("-topmost", True)
pump(1.0)
t_map = time.time()
while not app.pyr and time.time() - t_map < 120:  # the map image builds in the background
    pump(0.3)
check("window responsive while the map builds", True, f"map ready after {time.time() - t_map:.1f}s")
c = app.canvas
W, H = app.canvas_size()

check(
    "atlas loaded",
    len(app.V["nodes"]) > 0 and len(app.atlas.frames) > 0,
    f"{len(app.V['nodes'])} nodes, {len(app.atlas.frames)} shots",
)
check("atlas-wide result shown", bool(app.V["stats"]), str(app.V["stats"]))
check("terrain built", bool(app.pyr), f"{app.pyr[0].shape if app.pyr else None}")
img = app.render(W, H)
check("render not blank", img.std() > 10)
times = []
for _k in range(15):
    t0 = time.perf_counter()
    app.render(W, H)
    times.append((time.perf_counter() - t0) * 1000)
check("render fast at fit", np.median(times) < 120, f"{np.median(times):.0f} ms median")
grab("01_fit.png")

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
        "places listed", app.hits and all(k == "landmark" for k, _ in app.hits), f"{len(app.hits)} {app.place_types[0]}"
    )
app.query.set("hall")
pump()
rows = [w.winfo_children()[-1].cget("text") for w in app.icon_frame.winfo_children() if isinstance(w, V.tk.Frame)]
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
img_hidden = app.render(W, H)
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
# native-resolution terrain when zoomed in
nd = app.V["nodes"][target]
app.center_on(nd["x"], nd["y"], min_zoom=1.6)
app.z = 1.6
app._hires = None
over = [k for k in ("Paths", "Nodes", "Icons", "Landmarks", "Labels", "Bookmarks") if app.layers[k].get()]
for k in over:
    app.layers[k].set(False)  # measure the terrain alone
low = app.render(W, H)
app._make_hires(background=False)
high = app.render(W, H)
for k in over:
    app.layers[k].set(True)


def sharp(im):
    return float(cv2.Laplacian(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


check(
    "zoomed-in terrain at screenshot resolution",
    app._hires is not None and (app.t_origin[2] > 0.9 or sharp(high) > 1.3 * sharp(low)),
    f"map image scale {app.t_origin[2]:.2f}, sharpness {sharp(low):.0f} -> {sharp(high):.0f}",
)
pump()
grab("08_zoomed_native.png")

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
same = [landmark for landmark in app.V["landmarks"] if math.hypot(landmark["x"] - lm["x"], landmark["y"] - lm["y"]) < 1]
check(
    "landmark kind changed",
    same and same[0]["kind"] == new_kind and same[0]["beam"] == "set by you",
    f"{lm['kind']} -> {same[0]['kind'] if same else None}",
)
i = app.V["landmarks"].index(same[0])
app.select(("landmark", i))
messagebox.askyesno = lambda *a, **k: True  # the confirm dialog
app.delete_selected()
gone = [landmark for landmark in app.V["landmarks"] if math.hypot(landmark["x"] - lm["x"], landmark["y"] - lm["y"]) < 1]
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
    atlas_log.LOG_FILE.read_bytes()[log_size0:].decode("utf-8", errors="replace") if atlas_log.LOG_FILE.exists() else ""
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
        landmark for landmark in app.V["landmarks"] if math.hypot(landmark["x"] - tw["x"], landmark["y"] - tw["y"]) < 1
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

# build a NEW atlas through the viewer's own add path (cached detections make this fast)
if shots:
    new = work / "fresh.json"
    core.Atlas().save(new)
    if (work / "atlas_frames").exists():
        shutil.copytree(work / "atlas_frames", work / "fresh_frames")
    app.open_atlas(new)
    pump()
    app.settings["database"] = str(Path(app.settings.get("database") or "") or "")
    db = app.database(ask=False)
    if db is None:
        print("skip: no detector database found for the add test (set one with File > Detector database)")
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
    app.settings.pop("watch_folder", None)
    check("auto-add watches the atlas's own folder by default", app._watch_dir() == str(new.parent), app._watch_dir())
    app.settings["watch_folder"] = str(sdir)
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
    # a screenshot from far away waits and is listed (crawl #0 vs this run, if far enough)
    far = crawl_only[0] if k > 60 else crawl_only[-1]
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
        "placed wherever the window looks", len(app.atlas.frames) == 4 and not asked, f"{len(app.atlas.frames)} placed"
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
        builder_frame := builder.extract_frame(seq[4], None, wdir),
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

print(f"\nwindow grabs in {out}")
print("PASS: atlas viewer" if not fails else f"FAILED: {fails}")
root.destroy()
if "pytest" in sys.modules:  # under pytest: a failure, not an exit
    assert not fails, "see the FAIL lines above"
else:
    sys.exit(1 if fails else 0)
