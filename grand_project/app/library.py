"""app.library: part of AtlasSession (a mixin; see app/session.py): the saved atlases and the computer's folders.

Known atlases are kept in the settings ({name, json, numbers}); each has a card picture next to its map image
(<stem>_files/<stem>_thumb.png). A folder of screenshots opens its atlas (the best one built from it) or becomes a
new one. The page's file and folder pickers list folders through list_dir (the app runs on the player's own
computer).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import string
import subprocess
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

from grand_project import builder, core
from grand_project import fileio as atlas_io
from grand_project import logs as atlas_log

from .constants import ATLAS_THUMB, FS_LIST_MAX

LOG = atlas_log.get("app")


def same_file(a, b) -> bool:
    """Tell whether two paths lead to one file.

    Args:
        a: A path.
        b: Another path.

    Returns:
        True when both resolve to the same file.
    """
    return Path(a).resolve() == Path(b).resolve()


def thumb_file(json_path) -> Path:
    """Return where an atlas's card picture is kept (<stem>_files/<stem>_thumb.png).

    Args:
        json_path: The atlas file.

    Returns:
        The path (no folder is made).
    """
    p = Path(json_path)
    return p.with_name(p.stem + "_files") / (p.stem + "_thumb.png")


def make_thumb(canvas: np.ndarray) -> np.ndarray:
    """Shrink a map image into ATLAS_THUMB, centred on a dark background.

    Args:
        canvas: BGR map image.

    Returns:
        BGR image of ATLAS_THUMB.
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
    """Count a saved atlas's maps, icons and screenshots.

    Args:
        data: The atlas JSON.

    Returns:
        {"maps", "icons", "shots"}.
    """
    final = data.get("final") or {}
    st = final.get("stats", {})
    return {
        "maps": int(st.get("nodes_kept", 0)),
        # the icons after the atlas-wide check (what the map shows), not every sighting of them in every screenshot:
        # the cards said 6062 where the top bar said 3762 (user)
        "icons": len(final["icons"]) if final.get("icons") is not None else len(data.get("icons", [])),
        "shots": len(data.get("frames", [])),
    }


def atlas_data_paths(json_path) -> list[Path]:
    """List everything the program wrote for an atlas (never the screenshots).

    Args:
        json_path: The atlas file.

    Returns:
        The paths that exist.
    """
    p = Path(json_path)
    out = [p, p.with_name(p.stem + "_frames"), p.with_name(p.stem + "_files")]
    out += [p.with_name(p.stem + s) for s in (*core.ATLAS_OUTPUTS, "_undo")]
    return [q for q in out if q.exists()]


def atlas_shot_dir(json_path: Path) -> Path | None:
    """Return the folder of an atlas's first screenshot.

    Args:
        json_path: An atlas file.

    Returns:
        The folder, or None.
    """
    try:
        frames = json.loads(json_path.read_text(encoding="utf-8")).get("frames") or []
        first = frames[0]["path"] if frames and isinstance(frames[0], dict) else None
    except (OSError, ValueError, AttributeError, KeyError):
        return None
    if not first:
        return None
    return Path(core.find_screenshot(first, json_path.resolve().parent)).parent


def list_dir(path: str | None, files: bool = True) -> dict:
    """List a folder for the page's file and folder pickers.

    Args:
        path: The folder ("" or None: the home folder; on Windows "drives" lists the drives).
        files: List image and atlas files too (else only folders).

    Returns:
        {"path", "parent", "entries": [{"name", "path", "dir", "size", "mtime"}], "truncated"}.

    Raises:
        ValueError: When the folder can't be read.
    """
    if path == "drives" and os.name == "nt":
        drives = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
        return {"path": "drives", "parent": None, "truncated": False,
                "entries": [{"name": d, "path": d, "dir": True, "size": 0} for d in drives]}  # fmt: skip
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
        items = list(os.scandir(base))
    except OSError as e:
        raise ValueError(f"can't read {base}: {e}") from e
    entries = []
    for e in items:
        if e.name.startswith("."):
            continue
        with contextlib.suppress(OSError):
            is_dir = e.is_dir()
            if not is_dir and (not files or Path(e.name).suffix.lower() not in (*core.IMAGE_EXT, ".json")):
                continue
            st = e.stat()
            entries.append({"name": e.name, "path": str(base / e.name), "dir": is_dir,
                            "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})  # fmt: skip
    entries.sort(key=lambda t: (not t["dir"], t["name"].lower()))
    parent = str(base.parent) if base.parent != base else ("drives" if os.name == "nt" else None)
    return {
        "path": str(base),
        "parent": parent,
        "entries": entries[:FS_LIST_MAX],
        "truncated": len(entries) > FS_LIST_MAX,
    }


# the known atlases are changed by one caller at a time (the background card reader raced remember_atlas:
# CodeRabbit)
ATLAS_LIST_LOCK = threading.RLock()


class LibraryMixin:
    """AtlasSession mixin: saved atlases and folders (see the module docstring)."""

    def known_atlases(self) -> list[dict]:
        """List the known atlases (the open and last ones included; missing files dropped).

        Returns:
            [{"name", "json", "numbers"?}] (the list kept in the settings).
        """
        with ATLAS_LIST_LOCK:
            L = [a for a in self.settings.get("atlases", []) if Path(a["json"]).exists()]
            for extra in (self.path, self.settings.get("last_atlas")):
                if extra and Path(extra).exists() and not any(same_file(a["json"], extra) for a in L):
                    L.append({"name": Path(extra).parent.name, "json": str(Path(extra).resolve())})
            self.settings["atlases"] = L
            return L

    def remember_atlas(self, json_path, name: str | None = None) -> None:
        """Add an atlas to the known atlases (with the open atlas's numbers) and save the settings.

        Args:
            json_path: The atlas file.
            name: Its name in the list (default: its folder's name).
        """
        with ATLAS_LIST_LOCK:
            L = self.known_atlases()
            entry = next((a for a in L if same_file(a["json"], json_path)), None)
            if entry is None:
                entry = {"name": name or Path(json_path).parent.name, "json": str(Path(json_path).resolve())}
                L.append(entry)
            if self.atlas is not None and self.path is not None and same_file(json_path, self.path):
                entry["numbers"] = atlas_numbers(
                    {"final": self.atlas.final, "icons": self.atlas.icons, "frames": self.atlas.frames}
                )
            self.save_settings()
        self.events.publish("atlases", None)

    def atlases_payload(self) -> list[dict]:
        """Return the Saved atlases cards (numbers missing are read in the background).

        Returns:
            [{"name", "json", "numbers", "open", "thumb"}].
        """
        out = []
        missing = []
        for a in self.known_atlases():
            if "numbers" not in a:
                missing.append(a["json"])
            out.append(
                {
                    "name": a["name"],
                    "json": a["json"],
                    "numbers": a.get("numbers"),
                    "open": bool(self.path) and same_file(a["json"], self.path),
                    "thumb": thumb_file(a["json"]).exists(),
                }
            )
        reading = self.__dict__.setdefault("_atl_reading", set())
        todo = [j for j in missing if j not in reading]
        if todo:
            reading.update(todo)
            threading.Thread(target=self._read_numbers, args=(todo,), daemon=True).start()
        return out

    def _read_numbers(self, paths: list[str]) -> None:
        """Read the numbers (and make the card picture) of atlases not opened since cards existed (background).

        Args:
            paths: Atlas files.
        """
        for jp in paths:
            numbers = None
            try:
                data = atlas_io.read_json(Path(jp))
                numbers = atlas_numbers(data) if isinstance(data, dict) else None
                tf = thumb_file(jp)
                terrain = tf.parent / (Path(jp).stem + "_terrain.png")
                if not tf.exists() and terrain.exists():
                    canvas = cv2.imdecode(np.fromfile(str(terrain), np.uint8), cv2.IMREAD_COLOR)
                    if canvas is not None:
                        core.write_png(tf, make_thumb(canvas), "thumbnail")
            except Exception:
                LOG.warning(f"could not read atlas {jp} for its card", exc_info=True)
            with ATLAS_LIST_LOCK:
                for a in self.known_atlases():
                    if a["json"] == jp and "numbers" not in a:  # (newer counts saved meanwhile stay: CodeRabbit)
                        a["numbers"] = numbers or {"maps": 0, "icons": 0, "shots": 0}
        with ATLAS_LIST_LOCK:
            self.save_settings()
        self.events.publish("atlases", None)

    def write_thumb(self, json_path, canvas: np.ndarray) -> None:
        """Write an atlas's card picture from its map image.

        Args:
            json_path: The atlas file.
            canvas: Its map image.
        """
        tf = thumb_file(json_path)
        try:
            tf.parent.mkdir(parents=True, exist_ok=True)
            core.write_png(tf, make_thumb(canvas), "thumbnail")
        except Exception:
            LOG.warning("atlas thumbnail could not be saved", exc_info=True)
            return
        self.events.publish("atlases", None)

    @staticmethod
    def thumb_exists(json_path) -> bool:
        """Tell whether an atlas has its card picture.

        Args:
            json_path: The atlas file.

        Returns:
            True when it exists.
        """
        return thumb_file(json_path).exists()

    def rename_atlas(self, json_path: str, name: str) -> None:
        """Rename a known atlas in the list (no file is renamed).

        Args:
            json_path: The atlas file.
            name: The new name.
        """
        for a in self.known_atlases():
            if same_file(a["json"], json_path) and name.strip():
                a["name"] = name.strip()
        self.save_settings()
        self.events.publish("atlases", None)

    def show_atlas_folder(self, json_path: str) -> None:
        """Open a known atlas's folder in the system's file browser (Saved atlases, right-click: user).

        Only atlases in the list: the page can't have any other folder opened.

        Args:
            json_path: The atlas file.

        Raises:
            ValueError: For an atlas not in the list.
        """
        known = next((a for a in self.known_atlases() if same_file(a["json"], json_path)), None)
        if known is None:
            raise ValueError("not an atlas in the list")
        folder = Path(known["json"]).parent
        if sys.platform == "win32":
            # Windows lets only the program in use bring a window to the front; the app runs in the background, so
            # the folder opened behind the browser (user). Any process may now take the front once (ASFW_ANY), so
            # Explorer's window comes up on top.
            with contextlib.suppress(Exception):
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # type: ignore[attr-defined]
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606 (a known folder, no shell)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])  # noqa: S603
        self.events.log(f"Opened the folder of the atlas {known['name']}")

    def _close_if_open(self, json_path: str) -> None:
        """Close the atlas if it is the open one (before it is deleted or forgotten).

        Args:
            json_path: The atlas file.
        """
        if self.path is None or not same_file(json_path, self.path):
            return
        if same_file(self.settings.get("last_atlas") or json_path, json_path):
            self.settings.pop("last_atlas", None)
        self.close()

    def forget_atlas(self, json_path: str) -> None:
        """Stop tracking an atlas (its files stay; the open atlas is closed first).

        Args:
            json_path: The atlas file.

        Raises:
            ValueError: While screenshots are being added to it.
        """
        if self.path is not None and same_file(json_path, self.path) and self.working():
            raise ValueError("wait until the screenshots being added are done")
        self._close_if_open(json_path)
        last = self.settings.get("last_atlas")
        if last and same_file(last, json_path):  # (also when closed already: the list put it back, CodeRabbit)
            self.settings.pop("last_atlas", None)
        with ATLAS_LIST_LOCK:  # read, changed and saved in one step, as the list's other users (CodeRabbit)
            L = self.known_atlases()
            L[:] = [a for a in L if not same_file(a["json"], json_path)]
            self.save_settings()
        self.events.log(f"stopped tracking {json_path} (its files are still there)")
        self.events.publish("atlases", None)

    def delete_atlas(self, json_path: str) -> list[str]:
        """Delete an atlas and its data for good (never the screenshots).

        Args:
            json_path: The atlas file.

        Returns:
            Items that could not be deleted.

        Raises:
            ValueError: While screenshots are being added to it.
        """
        if self.path is not None and same_file(json_path, self.path) and self.working():
            raise ValueError("wait until the screenshots being added are done")
        paths = atlas_data_paths(json_path)
        self._close_if_open(json_path)
        failed = []
        for q in paths:
            try:
                shutil.rmtree(q) if q.is_dir() else q.unlink()
            except OSError as e:
                failed.append(f"{q.name}: {e}")
        self.forget_atlas(json_path)
        self.events.log(f"deleted atlas {json_path} ({len(paths) - len(failed)} item(s)); screenshots kept")
        return failed

    def atlases_for_folder(self, folder: Path) -> list[Path]:
        """Find the atlas files of a screenshot folder, best first (current detector, most screenshots, newest).

        Args:
            folder: A screenshot folder.

        Returns:
            The atlas files.
        """
        found = [p for p in sorted(folder.glob("*.json")) if p.name == "atlas.json" or p.stem.endswith("atlas")]
        cands = [Path(a["json"]) for a in self.known_atlases()] + sorted(folder.parent.glob("*/atlas.json"))
        for j in cands:
            if j not in found and j.exists():
                d = atlas_shot_dir(j)
                if d is not None and d.resolve() == folder.resolve():
                    found.append(j)

        def rank(q: Path):
            """Sort key: current detector first, then the most cached screenshots, then the newest."""
            fr = q.with_name(q.stem + "_frames")
            new = len(list(fr.glob(f"*_{builder.NEW_DETECTOR_ID}.json"))) if fr.exists() else 0
            old = len(list(fr.glob("*.json"))) - new if fr.exists() else 0
            return (-new, -old, -q.stat().st_mtime)

        return sorted(set(found), key=rank)

    def open_folder(self, folder) -> dict:
        """Open a folder of screenshots: its atlas (the best one) when it has one, else say how many screenshots a
        new one would be built from.

        Args:
            folder: The folder.

        Returns:
            {"opened": atlas path, "new": [screenshots not in it], "others": n} or {"create": n screenshots}.

        Raises:
            ValueError: While working, or when the folder has no atlas and no screenshots.
        """
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        folder = Path(folder)
        if not folder.is_dir():
            raise ValueError(f"not a folder: {folder}")
        shots = core.screenshots_in(folder)
        atlases = self.atlases_for_folder(folder)
        if atlases:
            self.open_atlas(atlases[0])
            for j in atlases[1:]:
                self.remember_atlas(j)
            if len(atlases) > 1:
                self.events.log(
                    f"{len(atlases)} atlases were built from this folder; opened the one made with the current "
                    f"detector from the most screenshots ({atlases[0]}). The others are in Saved atlases."
                )
            have = {Path(f["path"]).name for f in self.atlas.frames}
            return {"opened": str(atlases[0]), "new": [str(q) for q in shots if q.name not in have],
                    "others": len(atlases) - 1}  # fmt: skip
        if not shots:
            raise ValueError("no screenshots and no atlas in this folder")
        return {"create": len(shots)}

    def create_from_folder(self, folder) -> int:
        """Make a new atlas (atlas.json) in a screenshot folder and add all its screenshots.

        Args:
            folder: The folder.

        Returns:
            How many screenshots are being added.
        """
        folder = Path(folder)
        shots = core.screenshots_in(folder)
        self.new_atlas(folder / "atlas.json")
        self.events.log(f"new atlas in {folder}: adding {len(shots)} screenshots")
        if shots:
            self.add_screenshots(shots)
        return len(shots)
