"""viewer.dialogs (from atlas_viewer.py)"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None

from .constants import CATEGORIES


class BookmarkDialog(tk.Toplevel):
    def __init__(self, parent, title, name="", category="Other", note="", groups=None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.grid(sticky="nsew")
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar(value=name)
        e = ttk.Entry(f, textvariable=self.name, width=36)
        e.grid(row=0, column=1, pady=3)
        ttk.Label(f, text="Group").grid(row=1, column=0, sticky="w")
        self.cat = tk.StringVar(value=category)
        ttk.Combobox(f, textvariable=self.cat, values=sorted(set(groups or []) | set(CATEGORIES)), width=33).grid(
            row=1, column=1, pady=3
        )
        ttk.Label(f, text="Note").grid(row=2, column=0, sticky="nw")
        self.note = tk.Text(f, width=36, height=4, wrap="word", font="TkDefaultFont")
        self.note.insert("1.0", note)
        self.note.grid(row=2, column=1, pady=3)
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Save", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        e.focus_set()
        e.select_range(0, "end")
        self.grab_set()

    def _ok(self):
        name = self.name.get().strip()
        if not name:
            return
        self.result = {
            "name": name,
            "category": self.cat.get().strip() or "Other",
            "note": self.note.get("1.0", "end").strip(),
        }
        self.destroy()
