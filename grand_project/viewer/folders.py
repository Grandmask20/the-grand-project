"""viewer.folders: part of the Viewer window (a mixin; see viewer/app.py)"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import builder, core

from .settings import save_settings


class FoldersMixin:
    # ------------------------------------------------------------------ atlas folders
    def known_atlases(self) -> list[dict]:
        """[{"name", "json"}] known atlases (settings), the open one always included"""
        L = [a for a in self.settings.get("atlases", []) if Path(a["json"]).exists()]
        for extra in (self.path, self.settings.get("last_atlas")):
            if extra and Path(extra).exists() and not any(Path(a["json"]) == Path(extra) for a in L):
                L.append({"name": Path(extra).parent.name, "json": str(extra)})
        self.settings["atlases"] = L
        return L

    def refresh_atlas_menu(self):
        m = self.atlas_menu
        m.delete(0, "end")
        for k, a in enumerate(self.known_atlases()):
            sub = tk.Menu(m, tearoff=0)
            sub.add_command(label="Open", command=lambda a=a: self.switch_atlas(Path(a["json"])))
            sub.add_command(
                label="Add new screenshots from its folder",
                command=lambda a=a: self.select_atlas_folder(Path(a["json"]).parent),
            )
            sub.add_command(label="Rename…", command=lambda k=k: self.rename_atlas(k))
            sub.add_command(label="Remove from this list", command=lambda k=k: self.forget_atlas(k))
            cur = self.path is not None and Path(a["json"]) == self.path
            m.add_cascade(label=("● " if cur else "   ") + a["name"], menu=sub)
        m.add_separator()
        m.add_command(label="Add new atlas… (choose its screenshot folder)", command=self.select_atlas_folder)
        name = next((a["name"] for a in self.known_atlases() if self.path and Path(a["json"]) == self.path), "")
        self.atlas_btn.configure(text=f"Atlas: {name} ▾" if name else "Atlas ▾")

    def remember_atlas(self, json_path: Path, name: str | None = None):
        L = self.known_atlases()
        if not any(Path(a["json"]) == Path(json_path) for a in L):
            L.append({"name": name or Path(json_path).parent.name, "json": str(json_path)})
        save_settings(self.settings)
        self.refresh_atlas_menu()

    def rename_atlas(self, k: int):
        from tkinter import simpledialog

        L = self.known_atlases()
        new = simpledialog.askstring("Rename atlas", "Name in this list:", initialvalue=L[k]["name"], parent=self.root)
        if new and new.strip():
            L[k]["name"] = new.strip()
            save_settings(self.settings)
            self.refresh_atlas_menu()

    def forget_atlas(self, k: int):
        L = self.known_atlases()
        if self.path and Path(L[k]["json"]) == self.path:
            self.status.set("the open atlas stays in the list")
            return
        L.pop(k)
        save_settings(self.settings)
        self.refresh_atlas_menu()

    def switch_atlas(self, json_path: Path):
        if self._busy:
            self.status.set("wait until the screenshots being added are done")
            return
        if self.path and Path(json_path) == self.path:
            return
        self.save_if_dirty()
        self.open_atlas(Path(json_path))
        self.refresh_atlas_menu()

    @staticmethod
    def _atlas_shot_dir(json_path: Path) -> Path | None:
        """folder of an atlas's first screenshot, read from the start of the file (atlas files are large)"""
        try:
            head = json_path.read_text(encoding="utf-8", errors="replace")[:20000]
            k = head.find('"path": "')
            if k < 0:
                return None
            v = head[k + 9 : head.find('"', k + 9)]
            return Path(json.loads(f'"{v}"')).parent
        except OSError:
            return None

    def atlases_for_folder(self, folder: Path) -> list[Path]:
        """atlas files belonging to a screenshot folder: inside it, or known / next to it and built from it"""
        found = [p for p in sorted(folder.glob("*.json")) if p.name == "atlas.json" or p.stem.endswith("atlas")]
        cands = [Path(a["json"]) for a in self.known_atlases()] + sorted(folder.parent.glob("*/atlas.json"))
        for j in cands:
            if j not in found and j.exists():
                d = self._atlas_shot_dir(j)
                if d is not None and d.resolve() == folder.resolve():
                    found.append(j)

        def rank(q: Path):
            """built with the current detector first, then the most screenshots (cached detections)"""
            fr = q.with_name(q.stem + "_frames")
            new = len(list(fr.glob(f"*_{builder.NEW_DETECTOR_ID}.json"))) if fr.exists() else 0
            old = len(list(fr.glob("*.json"))) - new if fr.exists() else 0
            return (-new, -old, -q.stat().st_mtime)

        return sorted(set(found), key=rank)

    def select_atlas_folder(self, folder: Path | None = None):
        """pick a folder of atlas screenshots: its atlas opens (the newest, if several were built from it) and
        screenshots in the folder that are not in it yet are offered for adding; no atlas yet = a new one in
        that folder, built from all its screenshots"""
        if self._busy:
            self.status.set("wait until the screenshots being added are done")
            return
        if folder is None:
            d = filedialog.askdirectory(
                title="Atlas folder (its screenshots, and atlas.json if it has one)", initialdir=self._initial_dir()
            )
            if not d:
                return
            folder = Path(d)
        shots = core.screenshots_in(folder)
        atlases = self.atlases_for_folder(folder)
        self.save_if_dirty()
        if atlases:
            self.open_atlas(atlases[0])
            self.remember_atlas(atlases[0])
            if len(atlases) > 1:
                self.log(
                    f"{len(atlases)} atlases were built from this folder; opened the one made with the "
                    f"current detector from the most screenshots "
                    f"({atlases[0]}). The others are in the Atlas list."
                )
                for j in atlases[1:]:
                    self.remember_atlas(j)
            have = {Path(f["path"]).name for f in self.atlas.frames}
            new = [q for q in shots if q.name not in have]
            if new and messagebox.askyesno(
                "Atlas folder", f"{len(new)} screenshot(s) in this folder are not in the atlas yet. Add them now?"
            ):
                self.add_screenshots(new)
            return
        if not shots:
            messagebox.showinfo("Atlas folder", "No screenshots and no atlas in this folder.")
            return
        if not messagebox.askyesno(
            "New atlas",
            f"No atlas in this folder yet. Build one from its {len(shots)} "
            f"screenshot(s)? It is saved as atlas.json in the folder.",
        ):
            return
        self.atlas, self.path = core.Atlas(), folder / "atlas.json"
        self.atlas.save(self.path)
        self.settings["last_atlas"] = str(self.path)
        self.remember_atlas(self.path)
        self._after_load(fit=True)
        self.log(f"new atlas in {folder}: adding {len(shots)} screenshots")
        self.add_screenshots(shots)
