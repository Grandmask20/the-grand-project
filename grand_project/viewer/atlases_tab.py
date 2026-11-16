"""viewer.atlases_tab: the Saved atlases tab (a mixin; see viewer/app.py).

One card per known atlas: a thumbnail of its map, its name, and its maps / icons / screenshots. Click a card to
open that atlas. Refresh re-checks the open atlas; Delete asks whether to stop tracking the atlas (files stay)
or delete the atlas and its data (the screenshots themselves are never deleted). The open atlas can be deleted
too: the window is cleared first.

Thumbnails are written next to the map image cache when the map is built (<atlas>_files/<stem>_thumb.png);
the numbers are kept in the viewer settings with each atlas. An atlas not opened since this version gets both
from a background read of its files.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from grand_project import core
from grand_project import fileio as atlas_io

from .constants import ATLAS_RETRY_S, ATLAS_THUMB, BTN_RIGHT
from .folders import same_file
from .helpers import LOG
from .settings import save_settings


def thumb_file(json_path) -> Path:
    """Where an atlas's thumbnail is kept (no folder is made: listing atlases must not create files).

    Args:
        json_path: Path of the atlas JSON file (str or Path).

    Returns:
        Path <stem>_files/<stem>_thumb.png next to the atlas file.
    """
    p = Path(json_path)
    return p.with_name(p.stem + "_files") / (p.stem + "_thumb.png")


def make_thumb(canvas: np.ndarray) -> np.ndarray:
    """The map image shrunk into ATLAS_THUMB, centred on the card's dark background.

    Args:
        canvas: BGR uint8 map image of any size.

    Returns:
        BGR uint8 image of shape (ATLAS_THUMB[1], ATLAS_THUMB[0], 3).
    """
    tw, th = ATLAS_THUMB
    h, w = canvas.shape[:2]
    s = min(tw / max(1, w), th / max(1, h))
    small = cv2.resize(canvas, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    out = np.full((th, tw, 3), 24, np.uint8)
    y0, x0 = (th - small.shape[0]) // 2, (tw - small.shape[1]) // 2
    out[y0 : y0 + small.shape[0], x0 : x0 + small.shape[1]] = small
    return out


def atlas_numbers(data: dict) -> dict:
    """Maps / icons / screenshots of a saved atlas (its JSON), as the viewer counts them.

    Args:
        data: The atlas JSON as read from disk.

    Returns:
        {"maps": map nodes kept by the atlas-wide check, "icons": number of icons, "shots": number of screenshots}.
    """
    st = (data.get("final") or {}).get("stats", {})
    return {
        "maps": int(st.get("nodes_kept", 0)),
        "icons": len(data.get("icons", [])),
        "shots": len(data.get("frames", [])),
    }


class AtlasesTabMixin:
    """Viewer mixin for the Saved atlases tab: one card per known atlas, open / rename / delete."""

    # ------------------------------------------------------------------ the tab
    def _build_atlases_tab(self, parent):
        """Build the Saved atlases tab: a scrolling list of cards and the Refresh, Rename and Delete buttons.

        Args:
            parent: The tab's frame to build into.
        """
        ttk.Label(parent, text="Click an atlas to open it.", foreground="#555", wraplength=330).pack(
            anchor="w", pady=(0, 4)
        )
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        self.atl_canvas = tk.Canvas(holder, highlightthickness=0, background="white")
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.atl_canvas.yview)
        self.atl_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.atl_canvas.pack(side="left", fill="both", expand=True)
        self.atl_inner = tk.Frame(self.atl_canvas, background="white")
        win = self.atl_canvas.create_window((0, 0), window=self.atl_inner, anchor="nw")
        self.atl_inner.bind(
            "<Configure>", lambda _e: self.atl_canvas.configure(scrollregion=self.atl_canvas.bbox("all"))
        )
        self.atl_canvas.bind("<Configure>", lambda e: self.atl_canvas.itemconfigure(win, width=e.width))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Refresh (re-check whole atlas)", command=self.refinalize).pack(side="left")
        ttk.Button(row, text="Delete…", width=8, command=self.ask_delete_atlas).pack(side="right")
        ttk.Button(row, text="Rename…", width=9, command=lambda: self._rename_card(self._atl_selected)).pack(
            side="right", padx=3
        )
        self._atl_photos: list = []  # Tk images must be kept referenced
        self._atl_reading: set[str] = set()  # atlases being read in the background now
        self._atl_tried: dict[str, float] = {}  # atlas -> when its last background read ended
        self._atl_selected: str | None = None

    def refresh_atlas_cards(self):
        """Rebuild the list of cards (atlas list, numbers or thumbnails changed).

        When another atlas was opened it becomes the selected card. Atlases without numbers or a thumbnail are read in
        the background. Does nothing before the tab is built.
        """
        if not hasattr(self, "atl_inner"):
            return
        for w in self.atl_inner.winfo_children():
            w.destroy()
        self._atl_photos = []
        atlases = self.known_atlases()
        open_json = next((a["json"] for a in atlases if self.path and same_file(a["json"], self.path)), None)
        gone = not any(a["json"] == self._atl_selected for a in atlases)
        if gone or open_json != getattr(self, "_atl_open", None):  # another atlas opened: it is the selection
            self._atl_selected = open_json
        self._atl_open = open_json
        for a in atlases:
            self._atlas_card(a)
            want = a.get("numbers") is None or not thumb_file(a["json"]).exists()
            last = self._atl_tried.get(a["json"])  # a failed read (or no map image yet) is tried again later
            due = last is None or time.monotonic() - last > ATLAS_RETRY_S
            if want and due and a["json"] not in self._atl_reading:
                self._read_atlas_in_background(a["json"])

    def _atlas_card(self, a: dict):
        """Add one card: thumbnail, name, maps / icons / screenshots ("reading…" until known), "open" if open.

        Left-click picks the card (opens the atlas); right-click shows its menu.

        Args:
            a: The atlas's entry in the known atlas list ("json", "name" and optional "numbers").
        """
        is_open = self.path is not None and same_file(a["json"], self.path)
        picked = a["json"] == self._atl_selected
        bg = "#dbe9ff" if picked else "white"
        card = tk.Frame(self.atl_inner, background=bg, highlightthickness=1, highlightbackground="#c8c8c8")
        card.pack(fill="x", padx=2, pady=3)
        tf = thumb_file(a["json"])
        img = None
        if tf.exists():
            with contextlib.suppress(Exception):
                img = ImageTk.PhotoImage(Image.open(tf))
        if img is None:
            img = ImageTk.PhotoImage(Image.new("RGB", (ATLAS_THUMB[0], ATLAS_THUMB[1]), (24, 24, 24)))
        self._atl_photos.append(img)
        pic = tk.Label(card, image=img, background=bg, borderwidth=0)
        pic.pack(side="left", padx=4, pady=4)
        text = tk.Frame(card, background=bg)
        text.pack(side="left", fill="both", expand=True, padx=(2, 4), pady=4)
        tk.Label(text, text=a["name"], font=("TkDefaultFont", 10, "bold"), background=bg, anchor="w").pack(fill="x")
        n = a.get("numbers")
        lines = [f"maps: {n['maps']}", f"icons: {n['icons']}", f"screenshots: {n['shots']}"] if n else ["reading…"]
        for ln in lines:
            tk.Label(text, text=ln, background=bg, foreground="#444", anchor="w").pack(fill="x")
        if is_open:
            tk.Label(text, text="open", background=bg, foreground="#1a6", anchor="w").pack(fill="x")
        for w in (card, pic, text, *text.winfo_children()):
            w.bind("<Button-1>", lambda _e, j=a["json"]: self._pick_atlas_card(j))
            w.bind(f"<Button-{BTN_RIGHT}>", lambda e, j=a["json"]: self._atlas_card_menu(e, j))

    def _atlas_card_menu(self, e, json_path: str):
        """Show the right-click menu of a card: Open / Rename / Delete. Bound to the right mouse button on a card.

        Args:
            e: The Tk event (its x_root / y_root place the menu).
            json_path: Atlas file of the card; it becomes the selected card.
        """
        self._atl_selected = json_path
        self.refresh_atlas_cards()
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Open", command=lambda: self._pick_atlas_card(json_path))
        m.add_command(label="Rename…", command=lambda: self._rename_card(json_path))
        m.add_separator()
        m.add_command(label="Delete…", command=self.ask_delete_atlas)
        m.tk_popup(e.x_root, e.y_root)

    def _rename_card(self, json_path: str | None):
        """Rename the atlas of a card (also renames it in the Atlas menu).

        Args:
            json_path: Atlas file of the card, or None when no card is selected (says so in the status bar).
        """
        if not json_path:
            self.status.set("select an atlas first")
            return
        k = next((i for i, a in enumerate(self.known_atlases()) if a["json"] == json_path), None)
        if k is not None:
            self.rename_atlas(k)  # also renames it in the Atlas menu

    def _pick_atlas_card(self, json_path: str):
        """Select a card and open its atlas if it is not the open one. Bound to <Button-1> on a card.

        Switching waits (and says so) while screenshots are being added.

        Args:
            json_path: Atlas file of the card.
        """
        self._atl_selected = json_path
        if self.path is None or not same_file(json_path, self.path):
            self.switch_atlas(Path(json_path))  # waits (says so) while screenshots are being added
        self.refresh_atlas_cards()

    # ------------------------------------------------------------------ numbers and thumbnails
    def _note_atlas_numbers(self):
        """Put the open atlas's maps / icons / screenshots into its entry of the atlas list (shown on its card)."""
        if not self.atlas or not self.path:
            return
        st = self.V.get("stats") or {}
        numbers = {
            "maps": int(st.get("nodes_kept", 0)),
            "icons": len(self.atlas.icons),
            "shots": len(self.atlas.frames),
        }
        for a in self.known_atlases():
            if same_file(a["json"], self.path) and a.get("numbers") != numbers:
                a["numbers"] = numbers
                save_settings(self.settings)
                self.refresh_atlas_cards()
                break

    def _write_thumb(self, canvas: np.ndarray):
        """Save the open atlas's thumbnail from its freshly built map image (background thread).

        Then asks the window thread, through the queue, to rebuild the cards. A failed save is only logged.

        Args:
            canvas: BGR uint8 map image of the open atlas.
        """
        if not self.path:
            return
        tf = thumb_file(self.path)
        try:
            tf.parent.mkdir(parents=True, exist_ok=True)
            core.write_png(tf, make_thumb(canvas), "thumbnail")
        except Exception:
            LOG.warning("atlas thumbnail could not be saved", exc_info=True)
            return
        self._q.put(("atlas_cards", None))

    def _read_atlas_in_background(self, json_path: str):
        """Read numbers and a thumbnail for an atlas not opened since thumbnails were added (on a background thread).

        The thumbnail is made from the atlas's cached terrain image if there is one. The result goes to the window
        thread through the queue as ("atlas_numbers", (json_path, numbers)).

        Args:
            json_path: Atlas file to read.
        """
        self._atl_reading.add(json_path)

        def work():
            """Read the atlas file and make its thumbnail (runs on the background thread)."""
            numbers = None
            try:
                data = atlas_io.read_json(Path(json_path))
                numbers = atlas_numbers(data) if isinstance(data, dict) else None
                tf = thumb_file(json_path)
                terrain = tf.parent / (Path(json_path).stem + "_terrain.png")
                if not tf.exists() and terrain.exists():
                    canvas = cv2.imdecode(np.fromfile(str(terrain), np.uint8), cv2.IMREAD_COLOR)
                    if canvas is not None:
                        core.write_png(tf, make_thumb(canvas), "thumbnail")
            except Exception:
                LOG.warning(f"could not read atlas {json_path} for its card", exc_info=True)
            self._q.put(("atlas_numbers", (json_path, numbers)))

        threading.Thread(target=work, daemon=True).start()

    def _got_atlas_numbers(self, val):
        """Store numbers read in the background in the atlas list and rebuild the cards (window thread).

        Args:
            val: (json_path, numbers) as sent by _read_atlas_in_background; numbers is None when the read failed.
        """
        json_path, numbers = val
        # done (was never cleared, so a failed read stayed at "reading…" for the session: GPT audit)
        self._atl_reading.discard(json_path)
        self._atl_tried[json_path] = time.monotonic()
        for a in self.known_atlases():
            if a["json"] == json_path and numbers is not None:
                a["numbers"] = numbers
                save_settings(self.settings)
        self.refresh_atlas_cards()

    # ------------------------------------------------------------------ delete
    def ask_delete_atlas(self):
        """Ask what to do with the selected atlas: stop tracking it, or delete it and its data (in a small window).

        Refused while screenshots are being added to it. The screenshots themselves are never deleted.
        """
        sel = self._atl_selected
        if not sel:
            self.status.set("select an atlas first")
            return
        if self.path is not None and same_file(sel, self.path) and self.working():
            self.status.set("wait until the screenshots being added are done")
            return
        name = next((a["name"] for a in self.known_atlases() if a["json"] == sel), Path(sel).parent.name)
        win = tk.Toplevel(self.root)
        win.title("Delete atlas")
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, text=f"What should happen to “{name}”?", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", padx=14, pady=(12, 4)
        )
        ttk.Label(
            win,
            text=f"{sel}\n\nYour screenshots are never deleted.",
            foreground="#555",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=14)
        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)

        def stop():
            """Stop tracking the atlas (its files stay); clears the window first if it is the open atlas."""
            win.destroy()
            self._close_if_open(sel)
            self._forget_atlas_path(sel)

        def delete():
            """Delete the atlas and its data (asks once more, listing the files)."""
            win.destroy()
            self._delete_atlas_data(sel, name)

        ttk.Button(row, text="Stop tracking atlas", command=stop).pack(side="left")
        ttk.Button(row, text="Delete whole atlas and its data", command=delete).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.grab_set()

    def _close_if_open(self, json_path: str) -> None:
        """Clear the window if this atlas is open, before it is deleted or no longer tracked.

        The window gets an empty, unsaved atlas (pick another one from the list), so nothing can save it back
        afterwards (review: having to open another atlas first was clunky). It is also dropped as the last atlas.

        Args:
            json_path: Atlas file about to be deleted or forgotten.
        """
        if self.path is None or not same_file(json_path, self.path):
            return
        self._forget_session()
        if same_file(self.settings.get("last_atlas") or json_path, json_path):
            self.settings.pop("last_atlas", None)
        self.atlas, self.path = core.Atlas(), None
        self._after_load(fit=True)
        self.status.set("no atlas open: pick one in Saved atlases, or File > New atlas")

    def _forget_atlas_path(self, json_path: str):
        """Remove an atlas from the known atlas list and the Atlas menu (its files stay).

        Args:
            json_path: Atlas file to forget.
        """
        L = self.known_atlases()
        L[:] = [a for a in L if a["json"] != json_path]
        save_settings(self.settings)
        self._atl_selected = str(self.path) if self.path else None
        self.refresh_atlas_menu()
        self.log(f"stopped tracking {json_path} (its files are still there)")

    @staticmethod
    def atlas_data_paths(json_path) -> list[Path]:
        """Everything the program wrote for an atlas, never the screenshots.

        That is the atlas file, its saved detections (<stem>_frames), its map images / exports / undo (<stem>_files)
        and outputs older versions left next to it.

        Args:
            json_path: Atlas file (str or Path).

        Returns:
            The paths that exist.
        """
        p = Path(json_path)
        out = [p, p.with_name(p.stem + "_frames"), p.with_name(p.stem + "_files")]
        out += [p.with_name(p.stem + s) for s in (*core.ATLAS_OUTPUTS, "_undo")]
        return [q for q in out if q.exists()]

    def _delete_atlas_data(self, json_path: str, name: str):
        """Delete an atlas and its data for good, after a yes / no question listing the files.

        The window is cleared first if it is the open atlas; files that cannot be deleted are listed in a warning.

        Args:
            json_path: Atlas file.
            name: Atlas name shown in the question and the log.
        """
        paths = self.atlas_data_paths(json_path)
        listing = "\n".join(f"  {q.name}{'/' if q.is_dir() else ''}" for q in paths)
        if not messagebox.askyesno(
            "Delete whole atlas and its data",
            f"Delete “{name}” for good?\n\n{listing}\n\nin {Path(json_path).parent}\n\n"
            "This can't be undone. Your screenshots are not deleted.",
            icon="warning",
            parent=self.root,
        ):
            return
        self._close_if_open(json_path)
        failed = []
        for q in paths:
            try:
                shutil.rmtree(q) if q.is_dir() else q.unlink()
            except OSError as e:
                failed.append(f"{q.name}: {e}")
        self._forget_atlas_path(json_path)
        if failed:
            messagebox.showwarning("Delete atlas", "Some files could not be deleted:\n" + "\n".join(failed))
        self.log(f"deleted atlas {name} ({len(paths) - len(failed)} item(s)); screenshots kept")
