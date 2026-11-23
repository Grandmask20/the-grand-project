"""app.friends: friends' atlases from live sharing, kept here and opened read-only in the real map.

A friend sharing their atlas sends it whole (live sharing: their page reads it with `share_payload`): the atlas file,
their map image's frame (not the picture: megabytes, user) and their view settings. The watching page hands it to
this app (`save_friend`), which keeps it in user_data/friends/<name>/ beside a blank map image of the same frame, so
the atlas opens like any other (load_terrain finds that image in its cache and never looks for the screenshots,
which are on the friend's computer). While a friend's atlas is open:

- it is read-only: the server refuses every change to it (`friend_refuses`), it is never saved, auto-add and the
  locked-stronghold search don't run on it, and it isn't added to your atlases or made the one opened at start;
- the map shows it as they see it: their filters and styles (`view_settings`), their position (I'm here). Changing a
  view setting changes it for this visit only; your own settings are kept as they were.

Their atlas keeps coming as they add screenshots: an open one is read again in place.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
import time
import zlib
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project import paths as rc_paths
from grand_project.fileio import write_text_atomic

from .library import same_file

# the settings that make a map look as it does: a friend's are shown with their atlas
VIEW_KEYS = ("layers", "multi_only", "only_icon_maps", "near_only", "icon_hidden", "style")
# the blank map image's size at most (pixels): its frame is all it is for
BLANK_PIXELS = 1_000_000
# what a page may still ask of the app while a friend's atlas is open (method, path prefix): reading it, its view,
# opening or making another, the app's own business. Every other change is refused (friend_refuses)
FRIEND_ALLOWED = (
    "/api/settings",
    "/api/atlas/open",
    "/api/atlas/new",
    "/api/atlas/close",
    "/api/atlas/folder",
    "/api/atlases",
    "/api/friends",
    "/api/pick",
    "/api/recent/goto",
    "/api/replay",
    "/api/log",
    "/api/quit",
    "/api/questions/",
    "/api/update",
)


def friends_dir() -> Path:
    """Where friends' atlases are kept (user_data/friends)."""
    return rc_paths.USER_DATA / "friends"


def friend_slug(name: str) -> str:
    """A friend's folder name: their name in plain letters, digits, - and _ ("friend" when nothing is left)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")[:40]
    return slug or "friend"


def unpack_file(packed: str) -> dict:
    """A shared atlas back from the page's packing: "z" + deflate-raw, or "p" + plain, in URL-safe base64.

    Raises:
        ValueError: When it can't be read.
    """
    if not isinstance(packed, str) or packed[:1] not in ("z", "p"):
        raise ValueError("not a shared atlas")
    try:
        raw = base64.urlsafe_b64decode(packed[1:] + "=" * (-len(packed[1:]) % 4))
        if packed[0] == "z":
            raw = zlib.decompress(raw, -15)
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"the shared atlas can't be read: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("atlas"), dict):
        raise ValueError("the shared atlas can't be read: no atlas in it")
    return data


def write_blank_map(atlas_path: Path, atlas: core.Atlas, frame: dict) -> None:
    """Write a blank map image of the friend's map image's frame, as the cache load_terrain reads.

    Args:
        atlas_path: The friend's atlas file here.
        atlas: It, read (its key: the cache is used only while it matches).
        frame: {"origin": [x0, y0, scale], "width", "height"} of their map image.
    """
    x0, y0, scale = (float(v) for v in frame["origin"])
    w, h = int(frame["width"]), int(frame["height"])
    f = min(1.0, (BLANK_PIXELS / max(1, w * h)) ** 0.5)
    bw, bh = max(1, round(w * f)), max(1, round(h * f))
    png, npz = core.map_image_files(atlas_path)
    ok, buf = cv2.imencode(".png", np.zeros((bh, bw, 3), np.uint8))
    if ok:
        png.write_bytes(buf.tobytes())
    np.savez_compressed(
        npz,
        key=atlas.terrain_key(),
        origin=np.array([x0, y0, scale * f], float),
        weight=np.zeros((bh, bw), np.float16),
    )


def pack_file(data: dict) -> str:
    """A shared atlas packed for the page to send: "z" + deflate-raw in URL-safe base64 (unpack_file)."""
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    raw = c.compress(json.dumps(data, separators=(",", ":")).encode("utf-8")) + c.flush()
    return "z" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class FriendsMixin:
    """Friends' atlases (see the module docstring)."""

    def share_payload(self) -> dict:
        """This atlas as live sharing sends it to friends: the atlas file, the map image's frame, your view.

        Read without the session lock (a job holds it for minutes, and the friend would wait for it): an atlas
        changing as it is read is read again.

        Returns:
            {"file": packed (pack_file) {"atlas", "map", "view"}}, or {"file": None} with no atlas open.
        """
        for attempt in range(5):
            atlas, terrain = self.atlas, self.terrain
            if atlas is None:
                return {"file": None}
            try:
                data = json.loads(json.dumps(atlas.to_json()))
                break
            except RuntimeError:  # (changed while read)
                if attempt == 4:
                    raise
                time.sleep(0.05)
        # the screenshots' names only: where they are on your computer is yours
        for f in data.get("frames", []):
            f["path"] = Path(str(f.get("path", ""))).name
        frame = None
        if terrain is not None:
            canvas, _weight, origin = terrain
            frame = {"origin": [float(v) for v in origin], "width": canvas.shape[1], "height": canvas.shape[0]}
        u = self.ui_settings()  # (whole: a friend's app fills nothing in from its own)
        view = {
            "layers": u["layers"],
            "multi_only": u["multi_only"],
            "only_icon_maps": u["only_icon_maps"],
            "near_only": u["near_only"],
            "icon_hidden": u["hidden_types"],
            "style": u["style"],
        }
        return {"file": pack_file({"atlas": data, "map": frame, "view": view})}

    def friend_of(self, path) -> str | None:
        """The friend an atlas file is from (their name), or None for one of yours."""
        if path is None:
            return None
        p = Path(path).resolve()
        root = friends_dir().resolve()
        if root not in p.parents:
            return None
        meta = self._friend_meta(p)
        return str(meta.get("name") or p.parent.name)

    def friend_open(self) -> str | None:
        """The friend whose atlas is open (their name), or None."""
        return self.friend_of(self.path)

    def friend_refuses(self, method: str, path: str) -> bool:
        """Whether a page request is refused because a friend's atlas is open (a change to it)."""
        if method in ("GET", "HEAD") or not self.friend_open():
            return False
        return not path.startswith(FRIEND_ALLOWED)

    def save_friend(self, name: str, packed: str, player: dict | None = None) -> str:
        """Keep a friend's atlas as they sent it (the one open is read again in place).

        Args:
            name: The friend's name.
            packed: The shared atlas (unpack_file): {"atlas", "map", "view"}.
            player: Where they are ({"x", "y", "node"}), or None.

        Returns:
            Its atlas file here.
        """
        data = unpack_file(packed)
        folder = friends_dir() / friend_slug(name)
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / "atlas.json"
        write_text_atomic(p, json.dumps(data["atlas"]))
        atlas = core.Atlas.load(p)
        if isinstance(data.get("map"), dict):
            write_blank_map(p, atlas, data["map"])
        view = {k: v for k, v in (data.get("view") or {}).items() if k in VIEW_KEYS}
        meta = {"name": name.strip()[:40] or "Friend", "view": view, "player": player, "updated": time.time()}
        write_text_atomic(p.with_name("friend.json"), json.dumps(meta))
        if self.path is not None and same_file(self.path, p):
            self._reread_friend(p)
        self.events.publish("atlases", None)
        return str(p)

    def _reread_friend(self, p: Path) -> None:
        """The friend's atlas open read again in place: the same atlas (generation), so the map stays where it is
        (opened again, it was another atlas to the page, and the map went back to the whole of it)."""
        atlas = core.Atlas.load(p)
        with self._lock:
            if self.path is None or not same_file(self.path, p):
                return
            self.opened = dataclasses.replace(self.opened, atlas=atlas)
            self._view_overlay = self._overlay_for(self.path)
        self.load_terrain(cities=False, background=False)  # (their blank map image: its frame may have grown)
        self.rebuild_model()
        self.filters_changed()  # (their view may have changed)
        self.events.publish("atlas", self.atlas_summary())

    def set_friend_player(self, name: str, player: dict | None) -> None:
        """Where a friend is now, shown while their atlas is open (I'm here)."""
        p = friends_dir() / friend_slug(name) / "atlas.json"
        meta = self._friend_meta(p)
        if not meta:
            return
        meta["player"] = player
        write_text_atomic(p.with_name("friend.json"), json.dumps(meta))
        if self.path is not None and same_file(self.path, p):
            self._view_overlay = self._overlay_for(p)
            self.events.publish("lists", None)  # (the page reads its state again: their position)

    def friends_payload(self) -> dict:
        """The Atlases tab's friends' atlases, and your own to go back to.

        Returns:
            {"friends": [{"name", "json", "updated", "open", "maps"}], "own": the atlas opened at start, or None}.
        """
        out = []
        root = friends_dir()
        for p in sorted(root.glob("*/atlas.json")) if root.is_dir() else []:
            meta = self._friend_meta(p)
            try:
                final = json.loads(p.read_text(encoding="utf-8")).get("final") or {}
                maps = sum(1 for n in final.get("nodes", []) if n.get("status") != "removed")
            except Exception:
                maps = None
            out.append(
                {
                    "name": str(meta.get("name") or p.parent.name),
                    "json": str(p.resolve()),
                    "updated": meta.get("updated"),
                    "open": self.path is not None and same_file(self.path, p),
                    "maps": maps,
                }
            )
        own = self.settings.get("last_atlas")
        return {"friends": out, "own": own if own and Path(own).is_file() else None}

    def view_settings(self) -> dict:
        """The settings the view reads: yours, or a friend's while their atlas is open (_view_overlay)."""
        return getattr(self, "_view_overlay", None) or self.settings

    def _overlay_for(self, p: Path) -> dict:
        """Your settings with a friend's view in them: their filters and styles, their position as yours (I'm here)."""
        meta = self._friend_meta(p)
        mine = {k: v for k, v in self.settings.items() if k not in VIEW_KEYS}  # (none of your view: theirs, or none)
        view = {**json.loads(json.dumps(mine)), **json.loads(json.dumps(meta.get("view") or {}))}
        ui = dict(self.settings.get("ui", {}))
        pl = meta.get("player")
        ui["player"] = {**pl, "atlas": str(p)} if isinstance(pl, dict) else None
        view["ui"] = ui
        return view

    def _friend_meta(self, p: Path) -> dict:
        """A friend's atlas's friend.json ({} when missing or unreadable)."""
        try:
            meta = json.loads(Path(p).with_name("friend.json").read_text(encoding="utf-8"))
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return {}
