"""app.debug: part of AtlasSession (a mixin; see app/session.py): debug marks (internal copy only).

Notes pinned on wrong / missing maps and paths, kept per atlas in <stem>_files/debug_marks.json with their D number
(never reused). Shown only when paths.DEBUG is on.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from grand_project import core
from grand_project import logs as atlas_log

from .constants import VERSION

LOG = atlas_log.get("app")

DEBUG_REASONS = {
    "wrong map": [
        "not a map (no base there)",
        "map is in the wrong spot",
        "duplicate of a map next to it",
        "wrong paths at this map",
        "other",
    ],
    "wrong path": ["no path here", "wrong end map", "crosses / runs through a structure", "wrong shape", "other"],
    "missing map": ["visible map base", "hidden map (paths lead in)", "other"],
    "missing path": ["there should be a path between these maps"],
}


class DebugMixin:
    """AtlasSession mixin: debug marks (see the module docstring)."""

    def _dbg_file(self) -> Path | None:
        """Return the open atlas's debug marks file.

        Returns:
            The path, or None with no atlas open.
        """
        return core.atlas_files(self.path) / "debug_marks.json" if self.path else None

    def debug_marks(self) -> list[dict]:
        """Return the debug marks of the open atlas (read once per file and kept).

        Returns:
            The mark dicts (each with its "id").
        """
        fp = self._dbg_file()
        if fp is None:
            return []
        key = str(fp)
        if getattr(self, "_dbg_cache", (None,))[0] != key:
            try:
                marks = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
            except (OSError, ValueError):
                marks = []
            for k, m in enumerate(marks, 1):
                m.setdefault("id", k)
            self._dbg_cache = (key, marks)
        return self._dbg_cache[1]

    def _dbg_save(self) -> None:
        """Write the debug marks and tell the page."""
        fp = self._dbg_file()
        if fp is not None:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(self.debug_marks(), indent=1), encoding="utf-8")
        self.events.publish("debug", None)

    def add_debug_mark(
        self,
        kind: str,
        reason: str,
        note: str = "",
        x: float | None = None,
        y: float | None = None,
        maps: list[int] = (),
        path: int | None = None,
    ) -> dict:
        """Make a debug mark and save it.

        Args:
            kind: "wrong map", "wrong path", "missing map" or "missing path".
            reason: The reason picked.
            note: Free text.
            x: Atlas x (None: the middle of its maps / path ends).
            y: Atlas y.
            maps: Map node indices it is about.
            path: Path index it is about, or None.

        Returns:
            The mark.

        Raises:
            ValueError: With no atlas open, an unknown kind, or nothing to place the mark at.
        """
        if not self.atlas:
            raise ValueError("open an atlas first")
        if kind not in DEBUG_REASONS:
            raise ValueError(f"unknown debug mark kind: {kind}")
        N = self.V["nodes"]
        mk: dict = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "reason": reason,
            "note": note or "",
            "version": VERSION,
            "maps": [],
        }
        for i in maps:
            n = N[i]
            mk["maps"].append(
                {
                    "id": int(i),
                    "x": round(n["x"], 1),
                    "y": round(n["y"], 1),
                    "status": n["status"],
                    "seen": n.get("seen"),
                    "could": n.get("could"),
                    "origin": n.get("origin"),
                    "icons": n.get("icons", []),
                    "why": n.get("why", ""),
                }
            )
        if path is not None:
            p = self.V["paths"][path]
            mk["path"] = {
                k: p.get(k)
                for k in ("a", "b", "kind", "frames", "seen_in", "both_ends", "ends_in", "confirm", "deny", "dashes")
            }
            mk["path"]["ends"] = [
                [round(N[p["a"]]["x"], 1), round(N[p["a"]]["y"], 1)],
                [round(N[p["b"]]["x"], 1), round(N[p["b"]]["y"], 1)],
            ]
        if x is None or y is None:
            pts = [(m["x"], m["y"]) for m in mk["maps"]] or (
                [tuple(np.mean(mk["path"]["ends"], 0))] if path is not None else []
            )
            if not pts:
                raise ValueError("a debug mark needs a place")
            x, y = float(np.mean([q[0] for q in pts])), float(np.mean([q[1] for q in pts]))
        mk["x"], mk["y"] = round(float(x), 1), round(float(y), 1)
        mk["screenshots"] = [f["name"] for f, _x, _y in self.frames_at(mk["x"], mk["y"])[:5]]
        marks = self.debug_marks()
        mk["id"] = max([m.get("id", k + 1) for k, m in enumerate(marks)] + [0]) + 1  # never reused
        marks.append(mk)
        self._dbg_save()
        self.events.set_status(f"debug mark saved: {kind} ({reason})")
        return mk

    def delete_debug_mark(self, mid: int) -> None:
        """Delete a debug mark.

        Args:
            mid: Its id (D number).
        """
        marks = self.debug_marks()
        marks[:] = [m for m in marks if m.get("id") != mid]
        self._dbg_save()

    def clear_debug_marks(self) -> str:
        """Delete every debug mark, keeping a copy next to the file.

        Returns:
            The copy's file name ("" when there was nothing to clear).
        """
        marks, fp = self.debug_marks(), self._dbg_file()
        if not marks or fp is None:
            return ""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = fp.with_name(f"{fp.stem}_cleared_{stamp}.json")
        n = 1
        while backup.exists():
            n += 1
            backup = fp.with_name(f"{fp.stem}_cleared_{stamp}_{n}.json")
        backup.write_text(json.dumps(marks, indent=1), encoding="utf-8")
        marks.clear()
        self._dbg_save()
        LOG.info(f"debug marks cleared ({backup.name} keeps a copy)")
        return backup.name
