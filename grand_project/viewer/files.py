"""viewer.files: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

from grand_project import core


class FilesMixin:
    """File menu actions of the Viewer window: open an atlas and start a new one.

    A mixin of the Viewer class (viewer/app.py); runs on the window (Tk) thread.
    """

    # ------------------------------------------------------------------ files
    def ask_open(self):
        """Asks for an atlas JSON file and opens it (File > Open atlas, Ctrl/Cmd+O).

        Refused while screenshots are being added; unsaved changes are saved first.
        """
        if self.working():
            self.status.set("wait until the screenshots being added are done")
            return
        self.save_if_dirty()
        p = filedialog.askopenfilename(
            title="Open atlas", filetypes=[("Atlas JSON", "*.json"), ("All", "*.*")], initialdir=self._initial_dir()
        )
        if p:
            self.open_atlas(Path(p))

    def new_atlas(self):
        """Asks where to save a new, empty atlas, creates it there and opens it (File > New atlas).

        Refused while screenshots are being added; unsaved changes are saved first. The new atlas becomes
        the last atlas, opened at the next start.
        """
        if self.working():
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
