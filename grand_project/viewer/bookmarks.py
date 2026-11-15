"""viewer.bookmarks: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import math
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from grand_project import core

from .constants import CATEGORIES, SAME_SPOT, SNAP_PX
from .dialogs import BookmarkDialog
from .helpers import LOG, icon_label, icon_name
from .settings import save_settings


class BookmarksMixin:
    """Bookmarks of the Viewer window: groups, the Bookmarks tab tree, adding / editing / deleting bookmarks,
    and the window that shows the source screenshots of a spot.

    A mixin of the Viewer class (viewer/app.py); every method runs on the window (Tk) thread.
    """

    # ------------------------------------------------------------------ bookmarks
    @staticmethod
    def bm_group(b) -> str:
        """Returns the group a bookmark belongs to.

        Older atlases stored the group as "category"; a bookmark with neither is in "Other".

        Args:
            b: A bookmark dict from `atlas.bookmarks`.

        Returns:
            The group name.
        """
        return b.get("group") or b.get("category") or "Other"

    def groups(self) -> list[str]:
        """Lists every bookmark group: the groups bookmarks use plus empty groups made with New group.

        Returns:
            The group names, sorted case-insensitively.
        """
        g = {self.bm_group(b) for b in (self.atlas.bookmarks if self.atlas else [])} | self._extra_groups
        return sorted(g, key=str.lower)

    def bookmark_at(self, x, y) -> int | None:
        """Finds a bookmark already on this spot (same map node / icon).

        Args:
            x: Atlas x of the spot (atlas units).
            y: Atlas y of the spot (atlas units).

        Returns:
            The index in `atlas.bookmarks` of the nearest bookmark closer than SAME_SPOT, else None.
        """
        best, bd = None, SAME_SPOT
        for i, b in enumerate(self.atlas.bookmarks if self.atlas else []):
            d = math.hypot(b["x"] - x, b["y"] - y)
            if d < bd:
                best, bd = i, d
        return best

    def refresh_bookmarks(self):
        """Rebuilds the Bookmarks tab tree: one row per group (with its count and eye), its bookmarks under it.

        Groups that were open stay open (all are open when none was); hidden groups and hidden bookmarks show
        "—" in the eye column and are greyed out.
        """
        t = self.bm_tree
        open_groups = {t.item(g, "text").split("  (")[0] for g in t.get_children() if t.item(g, "open")}
        t.delete(*t.get_children())
        if not self.atlas:
            return
        for g in self.groups():
            items = sorted(
                (i for i, b in enumerate(self.atlas.bookmarks) if self.bm_group(b) == g),
                key=lambda i: self.atlas.bookmarks[i]["name"].lower(),
            )
            shown = g not in self.hidden_groups()
            gid = t.insert(
                "",
                "end",
                iid=f"group::{g}",
                text=f"{g}  ({len(items)})",
                values=("👁" if shown else "—", ""),
                open=(g in open_groups) or not open_groups,
            )
            for i in items:
                b = self.atlas.bookmarks[i]
                eye = "—" if (not shown or b.get("hidden")) else "👁"
                t.insert(
                    gid,
                    "end",
                    iid=f"bm::{i}",
                    text=b["name"],
                    values=(eye, b.get("note", "")[:40]),
                    tags=("off",) if eye == "—" else (),
                )
        t.tag_configure("off", foreground="#999")

    def hidden_groups(self) -> set:
        """Returns the bookmark groups hidden on the map for the open atlas (kept per atlas file in the settings).

        Returns:
            The set of hidden group names.
        """
        key = str(self.path) if self.path else ""
        return set(self.settings.get("hidden_groups", {}).get(key, []))

    def toggle_group(self, g):
        """Hides a bookmark group on the map, or shows it again, and saves that in the settings.

        Args:
            g: The group name.
        """
        key = str(self.path) if self.path else ""
        hg = self.settings.setdefault("hidden_groups", {})
        cur = set(hg.get(key, []))
        cur.symmetric_difference_update({g})
        hg[key] = sorted(cur)
        save_settings(self.settings)
        self.refresh_bookmarks()
        self.request_redraw()

    def on_bm_tree_click(self, e):
        """Toggles a group or a bookmark when its eye is clicked.

        Bound to <Button-1> on the Bookmarks tree (added to the default binding); clicks outside the eye column
        are left to the tree.

        Args:
            e: The Tk event.

        Returns:
            "break" when the eye was clicked (stops the tree selecting the row), else None.
        """
        t = self.bm_tree
        if t.identify_column(e.x) != "#1":  # the eye column
            return
        iid = t.identify_row(e.y)
        if iid.startswith("group::"):
            self.toggle_group(iid[7:])
            return "break"
        if iid.startswith("bm::"):
            self.toggle_bookmark(int(iid[4:]))
            return "break"

    def toggle_bookmark(self, i):
        """Hides one bookmark on the map, or shows it again, and saves the atlas.

        If its whole group is hidden, the group is shown and every other bookmark in it is hidden instead, so
        the click shows just this one.

        Args:
            i: Index in `atlas.bookmarks`.
        """
        b = self.atlas.bookmarks[i]
        if self.bm_group(b) in self.hidden_groups():  # group is hidden: show the group, hide the rest
            self.toggle_group(self.bm_group(b))
            for k, o in enumerate(self.atlas.bookmarks):
                if self.bm_group(o) == self.bm_group(b):
                    o["hidden"] = k != i
        else:
            b["hidden"] = not b.get("hidden")
        self.save()
        self.refresh_bookmarks()
        self.request_redraw()

    def bookmark_shown(self, b) -> bool:
        """Tells whether a bookmark is drawn on the map (neither its group nor itself is hidden).

        Args:
            b: A bookmark dict from `atlas.bookmarks`.

        Returns:
            True when it is shown.
        """
        return self.bm_group(b) not in self.hidden_groups() and not b.get("hidden")

    def selected_bookmarks(self) -> list[int]:
        """Lists the bookmarks selected in the Bookmarks tree; a selected group counts as all its bookmarks.

        With nothing selected in the tree, a bookmark selected on the map is used.

        Returns:
            Sorted indices in `atlas.bookmarks`, without duplicates.
        """
        out = []
        for iid in self.bm_tree.selection():
            if iid.startswith("bm::"):
                out.append(int(iid[4:]))
            elif iid.startswith("group::"):
                g = iid[7:]
                out += [i for i, b in enumerate(self.atlas.bookmarks) if self.bm_group(b) == g]
        if not out and self.sel and self.sel[0] == "bookmark":
            out = [self.sel[1]]
        return sorted(set(out))

    def on_bm_tree_select(self, _e=None):
        """Goes to a bookmark and selects it when exactly one bookmark is selected in the tree.

        Bound to <<TreeviewSelect>> on the Bookmarks tree.

        Args:
            _e: The Tk event (unused).
        """
        sel = self.bm_tree.selection()
        if len(sel) == 1 and sel[0].startswith("bm::"):
            i = int(sel[0][4:])
            b = self.atlas.bookmarks[i]
            self.center_on(b["x"], b["y"], min_zoom=max(self.z, 0.6))
            self.sel = ("bookmark", i)
            self.show_info()
            self.request_redraw()

    def new_group(self):
        """Asks for a name and adds an empty bookmark group to the list (it is kept only until a restart unless a
        bookmark is put in it).
        """
        from tkinter import simpledialog

        name = simpledialog.askstring("New group", "Group name:", parent=self.root)
        if name and name.strip():
            self._extra_groups.add(name.strip())
            self.refresh_bookmarks()

    def rename_group(self):
        """Renames the group selected in the Bookmarks tree (asks for the new name) and saves the atlas."""
        from tkinter import simpledialog

        sel = [i for i in self.bm_tree.selection() if i.startswith("group::")]
        if not sel:
            self.status.set("select a group in the list first")
            return
        old = sel[0][7:]
        name = simpledialog.askstring("Rename group", "New name:", initialvalue=old, parent=self.root)
        if not name or not name.strip():
            return
        for b in self.atlas.bookmarks:
            if self.bm_group(b) == old:
                b["group"] = name.strip()
        self._extra_groups.discard(old)
        self.save()
        self.refresh_bookmarks()

    def move_bookmarks(self):
        """Moves the selected bookmarks (or a selected group's bookmarks) to a group the user picks, and saves."""
        idx = self.selected_bookmarks()
        if not idx:
            self.status.set("select bookmarks (or a group) first")
            return
        g = self._ask_group(f"Move {len(idx)} bookmark(s) to group:")
        if not g:
            return
        for i in idx:
            self.atlas.bookmarks[i]["group"] = g
        self.save()
        self.refresh_bookmarks()

    def _ask_group(self, prompt, initial="") -> str | None:
        """Shows a small modal window with a group combobox (existing groups or a new name) and waits for it.

        Args:
            prompt: The text shown above the combobox.
            initial: The group filled in at the start.

        Returns:
            The group typed or picked, or None when the window was closed or left empty.
        """
        win = tk.Toplevel(self.root)
        win.title("Group")
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, text=prompt, padding=(10, 8, 10, 2)).pack(anchor="w")
        var = tk.StringVar(value=initial)
        cb = ttk.Combobox(win, textvariable=var, values=self.groups(), width=34)
        cb.pack(padx=10, pady=4)
        res = {}

        def ok(_e=None):
            """Stores the chosen group and closes the window (OK button, or <Return>).

            Args:
                _e: The Tk event when called from <Return> (unused).
            """
            res["g"] = var.get().strip()
            win.destroy()

        ttk.Button(win, text="OK", command=ok).pack(pady=(2, 10))
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda _e: win.destroy())
        cb.focus_set()
        win.grab_set()
        self.root.wait_window(win)
        return res.get("g") or None

    def default_name(self, item) -> tuple[str, str]:
        """Suggests a bookmark name and group for a map node, icon or landmark.

        Landmarks are named after their kind; map nodes and icons after their (first identified) icon, with the
        group taken from the icon type (Boss, Abyss, Delirium, Unique map, Breach, else Other).

        Args:
            item: The selection, ("node" | "icon" | "landmark", index into the view model list).

        Returns:
            (name, group).
        """
        kind, i = item
        raws = []
        if kind == "landmark":
            k = self.V["landmarks"][i]["kind"]
            return k, k if k in CATEGORIES else "Other"
        if kind == "node":
            raws = self.V["nodes"][i].get("icons", [])
        if kind == "icon":
            raws = [self.V["icons"][i]["name"]]
        raw = next((r for r in raws if r != "Unidentified"), raws[0] if raws else "")
        cat = (
            "Boss"
            if "Boss" in raw
            else "Abyss"
            if "Abyss" in raw
            else "Delirium"
            if "Delirium" in raw
            else "Unique map"
            if "Unique" in raw
            else "Breach"
            if "Breach" in raw
            else "Other"
        )
        name = icon_label(self.V["icons"][i]) if kind == "icon" else (icon_name(raw) if raw else f"Map #{i}")
        return name, cat

    def bookmark_selection(self):
        """Bookmarks the selected map node, icon or landmark (asks for name and group).

        With nothing selected, or a bookmark selected, starts bookmark mode instead. Also bound to Ctrl/Cmd+B.
        """
        if not self.atlas:
            return
        if not self.sel or self.sel[0] == "bookmark":
            self.start_bookmark_mode()
            return
        x, y = self.item_pos(self.sel)
        name, cat = self.default_name(self.sel)
        self.add_bookmark_dialog(x, y, name, cat)

    # bookmark mode: the next click on the map adds a bookmark (snapping to a map/icon/landmark)
    def start_bookmark_mode(self):
        """Starts bookmark mode: the next click on the map adds a bookmark (snapping to a map/icon/landmark).

        Esc cancels it.
        """
        if not self.atlas:
            return
        self._bm_mode = True
        self.canvas.configure(cursor="crosshair")
        self.status.set(
            "click the map to bookmark: on a map or icon to bookmark it, anywhere else to mark that spot (Esc cancels)"
        )

    def _bm_click(self, sx, sy):
        """Handles the click that ends bookmark mode.

        A click near a map node, icon or landmark (within SNAP_PX, or 14 screen px times the zoom) bookmarks
        it with a suggested name; anywhere else bookmarks that spot with an empty name.

        Args:
            sx: Click x on the map canvas (screen px).
            sy: Click y on the map canvas (screen px).
        """
        self._bm_mode = False
        self.canvas.configure(cursor="fleur")
        hit = self.pick(sx, sy)
        if hit and hit[0] != "bookmark":
            sp = self.to_screen([self.item_pos(hit)])[0]
            if math.hypot(sp[0] - sx, sp[1] - sy) <= max(SNAP_PX, 14 * self.z):
                x, y = self.item_pos(hit)
                name, cat = self.default_name(hit)
                self.add_bookmark_dialog(x, y, name, cat)
                return
        x, y = self.to_world(sx, sy)
        self.add_bookmark_dialog(x, y, "", "Other")

    def add_bookmark_dialog(self, x, y, name="", category="Other"):
        """Opens the Add bookmark window for a spot and adds the bookmark when it is saved.

        If a bookmark already sits on the spot, that one is selected instead and the status bar says so.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).
            name: The suggested name.
            category: The suggested group.
        """
        dup = self.bookmark_at(x, y)
        if dup is not None:
            b = self.atlas.bookmarks[dup]
            self.select(("bookmark", dup))
            self.status.set(f'already bookmarked as "{b["name"]}" in {self.bm_group(b)} (selected)')
            return
        if self.sel and self.sel[0] != "bookmark":
            pass
        d = BookmarkDialog(self.root, "Add bookmark", name, category, groups=self.groups())
        self.root.wait_window(d)
        if d.result:
            self.add_bookmark(x, y, **d.result)

    def add_bookmark(self, x, y, name, category="Other", note="", quiet=False):
        """Adds a bookmark to the atlas unless one already sits on that spot.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).
            name: Bookmark name.
            category: Group to put it in.
            note: Free text note.
            quiet: True to only add it (the caller saves and refreshes once after many); False to also save
                the atlas, refresh the lists, select it and log it.

        Returns:
            True if it was added, False if a bookmark was already there.
        """
        if self.bookmark_at(x, y) is not None:
            return False
        self.atlas.bookmarks.append(
            {
                "name": name,
                "group": category,
                "note": note,
                "x": float(x),
                "y": float(y),
                "created": time.strftime("%Y-%m-%d %H:%M"),
            }
        )
        if quiet:
            return True
        self.save()
        self.refresh_bookmarks()
        self.run_search()
        self.select(("bookmark", len(self.atlas.bookmarks) - 1))
        self.log(f"bookmarked {name}")
        return True

    def bookmark_all(self):
        """Bookmarks every Find result (except bookmarks) into one group the user picks, then saves.

        The group suggested is the search text. Spots that already have a bookmark are skipped and counted.
        """
        items = [h for h in self.hits if h[0] != "bookmark"]
        if not items:
            self.status.set("search for something first (Find tab), then bookmark all of it")
            return
        g = self._ask_group(f"Bookmark all {len(items)} results into group:", initial=self.query.get().strip())
        if not g:
            return
        added = skipped = 0
        for item in items:
            x, y = self.item_pos(item)
            name, _ = self.default_name(item)
            if self.add_bookmark(x, y, name, g, quiet=True):
                added += 1
            else:
                skipped += 1
        self.save()
        self.refresh_bookmarks()
        self.run_search()
        self.request_redraw()
        msg = f'bookmarked {added} into "{g}"' + (f" ({skipped} were already bookmarked)" if skipped else "")
        self.status.set(msg)
        self.log(msg)

    def edit_bookmark(self):
        """Opens the Edit bookmark window for the one selected bookmark and saves the changes.

        The old "category" key is dropped in favour of "group".
        """
        idx = self.selected_bookmarks()
        if len(idx) != 1:
            self.status.set("select one bookmark to edit")
            return
        i = idx[0]
        b = self.atlas.bookmarks[i]
        d = BookmarkDialog(
            self.root, "Edit bookmark", b["name"], self.bm_group(b), b.get("note", ""), groups=self.groups()
        )
        self.root.wait_window(d)
        if d.result:
            b.update(name=d.result["name"], group=d.result["category"], note=d.result["note"])
            b.pop("category", None)
            self.save()
            self.refresh_bookmarks()
            self.show_info()
            self.request_redraw()

    def delete_bookmark(self):
        """Deletes the selected bookmarks after asking, and saves the atlas.

        Bound to <Delete> on the Bookmarks tree and the map (and <BackSpace> on the map on a Mac).
        """
        idx = self.selected_bookmarks()
        if not idx:
            return
        names = [self.atlas.bookmarks[i]["name"] for i in idx]
        what = f'"{names[0]}"' if len(names) == 1 else f"{len(names)} bookmarks"
        if not messagebox.askyesno("Delete bookmark", f"Delete {what}?"):
            return
        LOG.info(f"deleted bookmark(s): {names}")
        for i in sorted(idx, reverse=True):
            self.atlas.bookmarks.pop(i)
        self.sel = None
        self.save()
        self.refresh_bookmarks()
        self.run_search()
        self.show_info()
        self.request_redraw()

    # ------------------------------------------------------------------ source screenshots
    def frames_at(self, x, y) -> list[tuple[dict, float, float]]:
        """Finds the screenshots that cover an atlas spot.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).

        Returns:
            (frame dict, x, y) per covering screenshot, the x, y being the spot in that screenshot's pixels;
            best view first: the spot nearest the middle of the screenshot.
        """
        out = []
        for f in self.atlas.frames:
            H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            p = core.persp(np.linalg.inv(H), [[x, y]])[0]
            if 0 <= p[0] < f["w"] and 0 <= p[1] < f["h"]:
                out.append((f, float(p[0]), float(p[1])))
        # best view first: the spot nearest the middle of the screenshot
        out.sort(key=lambda t: max(abs(t[1] / t[0]["w"] - 0.5), abs(t[2] / t[0]["h"] - 0.5)))
        return out

    def show_sources_for_selection(self):
        """Shows the screenshots of the selected map node, icon, landmark or bookmark (the Screenshots button)."""
        if self.sel:
            self.show_sources(*self.item_pos(self.sel))

    def show_sources(self, x, y):
        """Opens a window listing the screenshots that cover an atlas spot, showing the chosen one with the spot
        circled.

        Args:
            x: Atlas x (atlas units).
            y: Atlas y (atlas units).
        """
        found = self.frames_at(x, y)
        if not found:
            self.status.set("no screenshot covers that spot")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Screenshots of {x:.0f}, {y:.0f}")
        win.geometry("1200x720")
        win.transient(self.root)
        win.lift()
        win.focus_set()
        lb = tk.Listbox(win, width=24, exportselection=False)
        lb.pack(side="left", fill="y")
        cv = tk.Canvas(win, bg="#111")
        cv.pack(side="left", fill="both", expand=True)
        for f, *_ in found:
            lb.insert("end", f["name"])
        holder = {}

        def show(_e=None):
            """Draws the screenshot selected in the list, scaled to the window, with the spot circled.

            Bound to <<ListboxSelect>> on the list and <Configure> on the picture; a missing file is reported in
            the picture instead.

            Args:
                _e: The Tk event (unused).
            """
            sel = lb.curselection()
            if not sel:
                return
            f, px, py = found[sel[0]]
            if not Path(f["path"]).exists():
                cv.delete("all")
                cv.create_text(20, 20, anchor="nw", fill="white", text=f"missing file: {f['path']}")
                return
            img = core.read_screenshot(f["path"])
            W, H = max(50, cv.winfo_width()), max(50, cv.winfo_height())
            s = min(W / img.shape[1], H / img.shape[0])
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            cv2.circle(img, (int(px * s), int(py * s)), 22, (0, 255, 255), 2, cv2.LINE_AA)
            holder["p"] = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
            cv.delete("all")
            cv.create_image(0, 0, anchor="nw", image=holder["p"])

        lb.bind("<<ListboxSelect>>", show)
        cv.bind("<Configure>", show)
        lb.selection_set(0)
        win.after(50, show)
