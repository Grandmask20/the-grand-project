"""viewer.app (from atlas_viewer.py)"""

from __future__ import annotations

import contextlib
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import numpy as np

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import core
from grand_project import paths as rc_paths

from .autoadd import AutoAddMixin
from .bookmarks import BookmarksMixin
from .cities import CitiesMixin
from .constants import BTN_MIDDLE, BTN_RIGHT, IS_MAC, IS_WIN, MOD, MOD_LABEL, MONO_FONT, VERSION
from .debug import DebugMixin
from .drawing import DrawingMixin
from .files import FilesMixin
from .folders import FoldersMixin
from .helpers import LOG
from .navigation import NavigationMixin
from .panels import PanelsMixin
from .selection import SelectionMixin
from .settings import load_settings
from .terrain import TerrainMixin
from .view_tab import ViewTabMixin

if sys.stdout is None:  # started with pythonw: the detector prints a lot
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - stream remains open for process lifetime


if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - stream remains open for process lifetime


# The worker's Python loops share the interpreter with the window; with the default 5 ms turns a
# redraw (hundreds of small drawing calls) waited ~0.5 s while screenshots were being added.
sys.setswitchinterval(0.0005)


class Viewer(
    PanelsMixin,
    TerrainMixin,
    FilesMixin,
    ViewTabMixin,
    FoldersMixin,
    CitiesMixin,
    AutoAddMixin,
    NavigationMixin,
    DebugMixin,
    SelectionMixin,
    BookmarksMixin,
    DrawingMixin,
):
    def __init__(self, root: tk.Tk, atlas_path: str | None = None):
        self.root = root
        LOG.info(f"viewer v{VERSION}{rc_paths.title_tag()} started" + (f" with {atlas_path}" if atlas_path else ""))
        root.report_callback_exception = self._tk_error
        self.settings = load_settings()
        self.atlas: core.Atlas | None = None
        self.path: Path | None = None
        self.V: dict = {"nodes": [], "paths": [], "landmarks": [], "icons": [], "frames": [], "stats": {}}
        self.pyr: list[np.ndarray] = []  # terrain pyramid, level 0 = composite
        self.t_origin = (0.0, 0.0, 1.0)  # composite (x0, y0, scale)
        self.cx = self.cy = 0.0  # view centre, atlas units
        self.z = 1.0  # screen px per atlas unit
        self.sel: tuple[str, int] | None = None
        self.hits: list[tuple[str, int]] = []
        self.node_pts = np.zeros((0, 2))
        self.icon_pts = np.zeros((0, 2))
        self.footprints: list = []  # (atlas polygon, bbox) per screenshot
        self._hires = None  # (view key, image, mask) at native resolution
        self._jobs: queue.Queue = queue.Queue()  # (paths, mode) for the background worker
        self._lock = threading.RLock()  # held by the worker while it changes the atlas
        self._answer: queue.Queue = queue.Queue()
        self._watch_seen: dict[str, int] = {}  # file -> size at last poll
        self._pending_watch: list = []  # watched shots not placed yet (retried later)
        self._terrain = None  # (canvas, weight, origin) the stitched map
        self._terrain_job = 0  # newest background build wins
        self._progress = None  # (text, started) shown on the map while adding
        self._pending_outline = []  # just-placed screenshots, drawn until the map updates
        self._ghost = None  # hand placement: {"path", "img", "cx", "cy"}
        self._undo: list[dict] = []  # {"file", "names"} newest last
        self.recent: list[str] = []  # screenshots added, one each, newest last (outlined)
        self._hires_job = None
        self._weights: dict = {}
        self._redraw_pending = False
        self._fit_pending = False
        self._drag = None
        self._busy = False
        self._q: queue.Queue = queue.Queue()
        self.last_render_ms = 0.0
        self._build_ui()
        self.refresh_atlas_menu()
        if atlas_path:
            self.open_atlas(Path(atlas_path))
        else:
            last = self.settings.get("last_atlas")
            if last and Path(last).exists():
                self.open_atlas(Path(last))
            else:  # first start: the empty default atlas
                d = rc_paths.DEFAULT_ATLAS
                if not d.exists():
                    d.parent.mkdir(parents=True, exist_ok=True)
                    core.Atlas().save(d)
                self.open_atlas(d)
                self.log(
                    "Welcome! This is the default atlas (atlases/default). Put screenshots in that folder and "
                    "use Atlas > default > Add new screenshots from its folder. Or set Steam's external "
                    "screenshot folder to "
                    "it and tick Auto-add > Add new screenshots automatically."
                )
        self.root.after(100, self._poll_queue)
        threading.Thread(target=self._worker, daemon=True).start()
        if self.settings.get("watch_on") and self._watch_dir():
            self.watch_var.set(True)
            self.start_watch(initial=True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        r = self.root
        r.title(f"The Grand Project v{VERSION}{rc_paths.title_tag()}")
        r.geometry(self.settings.get("geometry", "1500x900"))
        r.minsize(1000, 640)
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style(r)
        # "clam" is drawn by Tk itself; the native "vista" theme left stale map fragments in the
        # side panel when the map image was redrawn many times a second
        style.theme_use("clam")
        bg = "#eceff3"
        r.configure(bg=bg)
        style.configure(".", background=bg)
        style.configure("TNotebook.Tab", padding=(6 if rc_paths.DEBUG else 10, 4))  # internal has a Debug tab too
        style.configure("Side.TFrame", background=bg)

        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)
        bar = ttk.Frame(r, padding=(6, 4))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        style.configure("File.TMenubutton", relief="raised", borderwidth=2, padding=(10, 3))
        self.file_btn = ttk.Menubutton(bar, text="File \u25be", style="File.TMenubutton")  # user: a menu bar did not
        fm = tk.Menu(self.file_btn, tearoff=0)  # read as a button
        fm.add_command(label="New atlas…", command=self.new_atlas)
        fm.add_command(label="Open atlas…", command=self.ask_open, accelerator=f"{MOD_LABEL}+O")
        fm.add_command(label="Save", command=self.save, accelerator=f"{MOD_LABEL}+S")
        fm.add_separator()
        fm.add_command(label="Open / add atlas folder…", command=self.select_atlas_folder)
        fm.add_command(label="Add screenshots…", command=self.ask_add)
        fm.add_command(label="Place a screenshot by hand…", command=self.ask_place)
        fm.add_command(label="Re-check whole atlas", command=self.refinalize)
        fm.add_command(label="Detector database…", command=self.ask_database)
        fm.add_command(label="Export map PNGs", command=self.export_pngs)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.on_close)
        self.file_btn["menu"] = fm
        self.file_btn.pack(side="left", padx=(0, 6))
        self.atlas_btn = ttk.Menubutton(bar, text="Atlas ▾", width=26)
        self.atlas_menu = tk.Menu(self.atlas_btn, tearoff=0)
        self.atlas_btn["menu"] = self.atlas_menu
        self.atlas_btn.pack(side="left")
        self.btn_add = self.atlas_btn  # disabled while screenshots are being added
        self.btn_undo = ttk.Button(bar, text="Undo last add", command=self.undo_last, state="disabled")
        self.btn_undo.pack(side="left", padx=(6, 0))
        self.btn_bm = ttk.Button(bar, text="Add bookmark", command=self.start_bookmark_mode)
        self.btn_bm.pack(side="left", padx=(6, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        saved = self.settings.get("layers", {})
        self.layers = {}
        defaults = {
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
        for name, dflt in defaults.items():
            self.layers[name] = tk.BooleanVar(value=saved.get(name, dflt))
        self.multi_only = tk.BooleanVar(value=self.settings.get("multi_only", False))
        self.btn_lasso = ttk.Button(bar, text="Draw city biome", command=self.start_lasso)
        self.btn_lasso.pack(side="left", padx=(6, 0))

        self.canvas = tk.Canvas(r, bg="#14161a", highlightthickness=0, bd=0, cursor="fleur")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.photo = None

        side = ttk.Frame(r, width=360, style="Side.TFrame", padding=(6, 4))
        side.grid(row=1, column=1, sticky="ns")
        side.grid_propagate(False)
        side.pack_propagate(False)
        self.layer_grid = ttk.Frame(side, padding=(0, 4, 0, 0))
        self.layer_grid.pack(side="bottom", fill="x")
        self.tabs = ttk.Notebook(side)
        self.tabs.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="Open an atlas (File > Open) or start a new one.")
        ttk.Label(r, textvariable=self.status, anchor="w", padding=(6, 2)).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )

        # --- Find (search + icon types in one place)
        find = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(find, text="Find")
        self.tab_find = find
        ttk.Label(find, text="Search: icon, City / Hall / Tower, bookmark, #map, or x, y to go there").pack(anchor="w")
        qrow = ttk.Frame(find)
        qrow.pack(fill="x")
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self.run_search())
        self.search_entry = ttk.Entry(qrow, textvariable=self.query)
        self.search_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(qrow, text="×", width=3, command=lambda: self.query.set("")).pack(side="left", padx=(3, 0))
        brow = ttk.Frame(find)
        brow.pack(fill="x", pady=(6, 2))
        ttk.Label(brow, text="Show on map:").pack(side="left")
        ttk.Button(brow, text="All", width=5, command=lambda: self.set_all_icons(True)).pack(side="left", padx=(4, 0))
        ttk.Button(brow, text="None", width=5, command=lambda: self.set_all_icons(False)).pack(side="left", padx=3)
        self.only_icon_maps = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            find, text="Hide maps without a ticked icon", variable=self.only_icon_maps, command=self.request_redraw
        ).pack(anchor="w", pady=(0, 3))
        self.only_near_city = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            find,
            text="Only potential city maps (on a city or 1 step from one)",
            variable=self.only_near_city,
            command=self._refilter,
        ).pack(anchor="w", pady=(0, 3))
        holder = ttk.Frame(find, height=250)
        holder.pack(fill="x")
        holder.pack_propagate(False)
        self.icon_canvas = tk.Canvas(holder, highlightthickness=1, highlightbackground="#aaa", bd=0, background="white")
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.icon_canvas.yview)
        self.icon_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.icon_canvas.pack(side="left", fill="both", expand=True)
        self.icon_frame = tk.Frame(self.icon_canvas, background="white")
        self.icon_canvas.create_window(0, 0, window=self.icon_frame, anchor="nw")
        self.icon_frame.bind(
            "<Configure>", lambda _e: self.icon_canvas.configure(scrollregion=self.icon_canvas.bbox("all"))
        )
        self.icon_canvas.configure(yscrollincrement=12)
        self.icon_canvas.bind("<MouseWheel>", self._scroll_icons)
        self.icon_canvas.bind("<Button-4>", self._scroll_icons)
        self.icon_canvas.bind("<Button-5>", self._scroll_icons)
        self.icon_vars: dict[str, tk.BooleanVar] = {}
        self.icon_hidden: set[str] = set(self.settings.get("icons_hidden", []))
        self._thumb_photos: list = []
        self.type_counts: dict[str, int] = {}
        self.icon_types: list[str] = []
        self.place_types: list[str] = []
        ttk.Label(find, text="Tick = show on the map. Click a name to list them below.", foreground="#555").pack(
            anchor="w", pady=(2, 4)
        )
        self.results = tk.Listbox(find, height=7, activestyle="none", exportselection=False, relief="solid", bd=1)
        self.results.pack(fill="x", pady=(0, 2))
        self.results.bind("<<ListboxSelect>>", lambda _e: self.goto_result(self.results, self.hits))
        frow = ttk.Frame(find)
        frow.pack(fill="x", pady=(0, 6))
        ttk.Button(frow, text="Bookmark all results…", command=self.bookmark_all).pack(side="left")
        ttk.Label(frow, text="★ = bookmarked", foreground="#555").pack(side="right")
        ttk.Label(find, text="Selected").pack(anchor="w")
        self.info = tk.Text(
            find,
            height=7,
            width=40,
            wrap="word",
            state="disabled",
            relief="solid",
            bd=1,
            background="white",
            foreground="black",
            insertbackground="black",
            font="TkDefaultFont",
        )
        self.info.pack(fill="x")
        row = ttk.Frame(find)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Bookmark", command=self.bookmark_selection).pack(side="left")
        ttk.Button(row, text="Edit", command=self.edit_selected).pack(side="left", padx=4)
        ttk.Button(row, text="Delete", command=self.delete_selected).pack(side="left")
        ttk.Button(row, text="Screenshots", command=self.show_sources_for_selection).pack(side="right")

        self._build_layer_grid()

        # --- View (zoom + what is shown)
        vw = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(vw, text="View")
        zrow = ttk.Frame(vw)
        zrow.pack(fill="x", pady=(0, 6))
        ttk.Button(zrow, text="Fit", command=self.fit).pack(side="left")
        ttk.Button(zrow, text="Zoom in", command=lambda: self.zoom_at(*self.canvas_size_half(), 1.25)).pack(
            side="left", padx=4
        )
        ttk.Button(zrow, text="Zoom out", command=lambda: self.zoom_at(*self.canvas_size_half(), 0.8)).pack(side="left")
        ttk.Label(vw, text="Keys: + / - zoom, 0 fit, arrows pan.", foreground="#555").pack(anchor="w", pady=(6, 0))
        self._build_style_ui(vw)

        # --- Auto-add
        fil = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(fil, text="Auto-add")
        self.tab_auto = fil
        ttk.Label(
            fil,
            wraplength=320,
            justify="left",
            text="Point Steam's screenshot folder at this atlas's folder (Steam > Settings > In Game > "
            "External screenshots folder) and tick the box below: every new screenshot is detected and "
            "added on its own, wherever it fits in the atlas. A rare weak match is shown to you "
            "before it is added. (Watch folder… watches another folder instead.)\n\n"
            "You can also drag a screenshot onto the map to place it by hand.",
        ).pack(anchor="w")
        wrow = ttk.Frame(fil)
        wrow.pack(fill="x", pady=(8, 2))
        self.watch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            wrow, text="Add new screenshots automatically", variable=self.watch_var, command=self.toggle_watch
        ).pack(side="left")
        ttk.Button(wrow, text="Watch folder…", command=self.ask_watch_folder).pack(side="left", padx=6)
        ttk.Button(wrow, text="Atlas folder", command=self.use_atlas_folder).pack(side="left")
        self.watch_label = tk.StringVar(value="")
        ttk.Label(fil, textvariable=self.watch_label, foreground="#555", wraplength=320).pack(anchor="w")

        ttk.Separator(fil).pack(fill="x", pady=8)
        ttk.Label(
            fil, text="Recently added (newest first; outlined on the map)", font=("TkDefaultFont", 9, "bold")
        ).pack(anchor="w")
        self.recent_list = tk.Listbox(fil, height=6, activestyle="none", exportselection=False, relief="solid", bd=1)
        self.recent_list.pack(fill="x", pady=(2, 2))
        self.recent_list.bind("<<ListboxSelect>>", lambda _e: self.goto_recent())
        rrow = ttk.Frame(fil)
        rrow.pack(fill="x")
        ttk.Button(rrow, text="Undo last add", command=self.undo_last).pack(side="left")
        ttk.Button(rrow, text="Go to newest", command=lambda: self.goto_recent(0)).pack(side="left", padx=4)

        ttk.Separator(fil).pack(fill="x", pady=8)
        ttk.Label(fil, text="Waiting (no overlap found yet)", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        self.wait_list = tk.Listbox(fil, height=5, activestyle="none", exportselection=False, relief="solid", bd=1)
        self.wait_list.pack(fill="x", pady=(2, 2))
        self.wait_list.bind("<Double-Button-1>", lambda _e: self.retry_waiting(selected=True))
        qrow2 = ttk.Frame(fil)
        qrow2.pack(fill="x")
        ttk.Button(qrow2, text="Retry selected", command=lambda: self.retry_waiting(selected=True)).pack(side="left")
        ttk.Button(qrow2, text="Retry all", command=lambda: self.retry_waiting(selected=False)).pack(
            side="left", padx=4
        )
        ttk.Button(qrow2, text="Place by hand…", command=self.place_waiting).pack(side="left")
        ttk.Label(
            fil,
            text="Waiting screenshots are retried on their own whenever another one is added; "
            "double-click one to retry it now.",
            foreground="#555",
            wraplength=320,
        ).pack(anchor="w")

        # --- Bookmarks
        bmf = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(bmf, text="Bookmarks")
        brow = ttk.Frame(bmf)
        brow.pack(fill="x", pady=(0, 4))
        ttk.Button(brow, text="Add…", command=self.start_bookmark_mode).pack(side="left")
        ttk.Button(brow, text="Edit…", command=self.edit_bookmark).pack(side="left", padx=3)
        ttk.Button(brow, text="Move to group…", command=self.move_bookmarks).pack(side="left")
        ttk.Button(brow, text="Delete", command=self.delete_bookmark).pack(side="left", padx=3)
        grow = ttk.Frame(bmf)
        grow.pack(fill="x", pady=(0, 4))
        ttk.Button(grow, text="New group…", command=self.new_group).pack(side="left")
        ttk.Button(grow, text="Rename group…", command=self.rename_group).pack(side="left", padx=3)
        ttk.Label(bmf, text="Click to go there; Ctrl/Shift-click selects several.", foreground="#555").pack(anchor="w")
        tree_holder = ttk.Frame(bmf)
        tree_holder.pack(fill="both", expand=True)
        self.bm_tree = ttk.Treeview(
            tree_holder,
            columns=("eye", "note"),
            show="tree headings",
            selectmode="extended",
            displaycolumns=("eye", "note"),
        )
        self.bm_tree.heading("#0", text="Bookmark")
        self.bm_tree.heading("eye", text="Show")
        self.bm_tree.heading("note", text="Note")
        self.bm_tree.column("#0", width=190)
        self.bm_tree.column("eye", width=46, anchor="center", stretch=False)
        self.bm_tree.column("note", width=90)
        self.bm_tree.bind("<Button-1>", self.on_bm_tree_click, add="+")
        tsb = ttk.Scrollbar(tree_holder, orient="vertical", command=self.bm_tree.yview)
        self.bm_tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.bm_tree.pack(side="left", fill="both", expand=True)
        self.bm_tree.bind("<<TreeviewSelect>>", self.on_bm_tree_select)
        self.bm_tree.bind("<Delete>", lambda _e: self.delete_bookmark())
        self._extra_groups: set[str] = set()
        ttk.Label(
            bmf,
            text="Click an eye to hide or show a group, or one bookmark, on the map.",
            foreground="#555",
            wraplength=330,
        ).pack(anchor="w", pady=(2, 0))

        # --- Debug (internal copy only): the user's marks of wrong / missing maps and paths, for the next fixes
        if rc_paths.DEBUG:
            dbf = ttk.Frame(self.tabs, padding=6)
            self.tabs.add(dbf, text="Debug")
            ttk.Label(
                dbf,
                text="Right-click a map, a path or an empty spot: Debug \u25b8 ...\n"
                "Marks are drawn in magenta and saved with the atlas.",
                foreground="#555",
                wraplength=330,
            ).pack(anchor="w")
            self.dbg_list = tk.Listbox(dbf, height=16, activestyle="none")
            self.dbg_list.pack(fill="both", expand=True, pady=4)
            self.dbg_list.bind("<Double-Button-1>", lambda e: self._dbg_goto())
            row = ttk.Frame(dbf)
            row.pack(fill="x")
            ttk.Button(row, text="Go to", command=self._dbg_goto).pack(side="left")
            ttk.Button(row, text="Delete", command=self._dbg_delete).pack(side="left", padx=4)
            self.dbg_file_lab = ttk.Label(dbf, text="", foreground="#555", wraplength=330)
            self.dbg_file_lab.pack(anchor="w", pady=(4, 0))

        # --- Log
        lgf = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(lgf, text="Log")
        self.log_box = tk.Text(
            lgf,
            wrap="word",
            state="disabled",
            relief="solid",
            bd=1,
            font=(MONO_FONT, 8),
            background="white",
            foreground="black",
        )
        self.log_box.pack(fill="both", expand=True)

        c = self.canvas
        c.bind("<Configure>", self.on_configure)
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind(f"<ButtonPress-{BTN_MIDDLE}>", self.on_press)
        c.bind(f"<B{BTN_MIDDLE}-Motion>", self.on_drag)
        c.bind(f"<ButtonRelease-{BTN_MIDDLE}>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.25))
        c.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 0.8))
        c.bind(f"<ButtonPress-{BTN_RIGHT}>", self.on_right)
        if IS_MAC:  # one-button trackpad: Ctrl+click is a right click
            c.bind("<Control-Button-1>", self.on_right)
        c.bind("<Motion>", self.on_motion)
        c.bind(
            "<Escape>",
            lambda _e: (
                self._cancel_lasso()
                if getattr(self, "_lasso", None) is not None
                else self.cancel_ghost()
                if self._ghost
                else self._cancel_bm_mode()
            ),
        )
        c.bind("<Return>", lambda _e: self.fit_ghost())
        self.dnd = False
        if TkinterDnD is not None and hasattr(c, "drop_target_register"):
            with contextlib.suppress(tk.TclError):  # needs the window made by TkinterDnD.Tk()
                c.drop_target_register(DND_FILES)
                c.dnd_bind("<<Drop>>", self.on_drop)
                self.dnd = True
        r.bind(f"<{MOD}-o>", lambda _e: self.ask_open())
        r.bind(f"<{MOD}-s>", lambda _e: self.save())
        r.bind(
            f"<{MOD}-f>",
            lambda _e: (self.tabs.select(0), self.search_entry.focus_set(), self.search_entry.select_range(0, "end")),
        )
        r.bind(f"<{MOD}-b>", lambda _e: self.bookmark_selection())
        r.bind(f"<{MOD}-z>", lambda _e: self.undo_last())
        for key, f in (("plus", 1.25), ("equal", 1.25), ("KP_Add", 1.25), ("minus", 0.8), ("KP_Subtract", 0.8)):
            c.bind(f"<{key}>", lambda _e, f=f: self.zoom_at(*self.canvas_size_half(), f))
        c.bind("0", lambda _e: self.fit())
        c.bind("<Delete>", lambda _e: self.delete_bookmark())
        if IS_MAC:  # Mac keyboards label the Delete key "delete" = BackSpace
            c.bind("<BackSpace>", lambda _e: self.delete_bookmark())
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            c.bind(f"<{key}>", lambda _e, dx=dx, dy=dy: self.pan_by(dx * 120, dy * 120))
        c.bind("<Enter>", lambda _e: c.focus_set())


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if IS_WIN:  # crisp on high-DPI Windows displays
        with contextlib.suppress(Exception):
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    Viewer(root, argv[0] if argv else None)
    root.mainloop()
    return 0
