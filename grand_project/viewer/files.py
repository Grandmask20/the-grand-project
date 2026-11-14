"""viewer.files: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import core


class FilesMixin:
    # ------------------------------------------------------------------ files
    def ask_open(self):
        if self._busy:
            self.status.set("wait until the screenshots being added are done")
            return
        self.save_if_dirty()
        p = filedialog.askopenfilename(
            title="Open atlas", filetypes=[("Atlas JSON", "*.json"), ("All", "*.*")], initialdir=self._initial_dir()
        )
        if p:
            self.open_atlas(Path(p))

    def new_atlas(self):
        if self._busy:
            self.status.set("wait until the screenshots being added are done")
            return
        self.save_if_dirty()
        p = filedialog.asksaveasfilename(
            title="New atlas: choose where to save it",
            defaultextension=".json",
            filetypes=[("Atlas JSON", "*.json")],
            initialdir=self._initial_dir(),
            initialfile="my_atlas.json",
        )
        if not p:
            return
        self._forget_session()
        self.atlas, self.path = core.Atlas(), Path(p)
        self.atlas.save(self.path)
        self.settings["last_atlas"] = str(self.path)
        self._after_load(fit=True)
        self.log(f"new atlas {self.path.name}: add screenshots to start")
