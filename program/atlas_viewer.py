"""PoE2 Atlas viewer: browse, search and bookmark a merged atlas, and add screenshots to it.

    py atlas_viewer.py                      (reopens the last atlas)
    py atlas_viewer.py my_atlas.json

Mouse:  wheel = zoom at cursor, drag = pan, click = select, double-click = zoom in,
        right-click = bookmark here / show source screenshots.
Keys:   + / - zoom, 0 fit, arrows pan, Ctrl+F search, Ctrl+B bookmark selection,
        Ctrl+O open, Ctrl+S save (Cmd instead of Ctrl on macOS), Delete remove selected bookmark.

Shows the atlas-wide result (atlas["final"]): nodes and paths checked against every screenshot.
The atlas file is the same JSON the command-line builder writes; bookmarks are stored in it.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

if sys.stdout is None:  # started with pythonw: the detector prints a lot
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - stream remains open for process lifetime
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - stream remains open for process lifetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    TkinterDnD = None

# --- platform differences (Windows / macOS / Linux) ---
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
MOD = "Command" if IS_MAC else "Control"  # shortcut modifier: Cmd on macOS, Ctrl elsewhere
MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"
# Tk numbers the mouse buttons differently on macOS: 2 is the right button and 3 the middle one
BTN_MIDDLE, BTN_RIGHT = (3, 2) if IS_MAC else (2, 3)
MONO_FONT = "Menlo" if IS_MAC else ("Consolas" if IS_WIN else "DejaVu Sans Mono")


def wheel_steps(e) -> float:
    """mouse-wheel notches from a <MouseWheel> event: Windows reports multiples of 120, macOS small integers"""
    return e.delta / (1 if IS_MAC else 120)


VERSION = "1.07"  # +1 per round of changes (v0.18 was the last ChatGPT release); same in internal + rc-1

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import atlas_builder as builder  # noqa: E402
import atlas_builder_core as core  # noqa: E402
import atlas_cities  # noqa: E402
import atlas_finalize  # noqa: E402
import atlas_io  # noqa: E402
import atlas_log  # noqa: E402

LOG = atlas_log.get("viewer")

import rc_paths  # noqa: E402

SETTINGS = rc_paths.USER_DATA / "viewer_settings.json"
CATEGORIES = [
    "Boss",
    "Unique map",
    "Abyss",
    "Breach",
    "Delirium",
    "Expedition",
    "Ritual",
    "Tower",
    "City",
    "Hall",
    "Farm spot",
    "Note",
    "Other",
]

# BGR colours (OpenCV draws the map)
BG = (26, 22, 20)
NODE_COL = {
    "confirmed": (255, 220, 40),
    "icon": (255, 220, 40),
    "single": (0, 150, 255),
    "disputed": (0, 150, 255),
    "doubtful": (140, 140, 140),
}
PATH_MULTI = (255, 215, 40)  # scored in 2+ screenshots
PATH_SINGLE = (0, 185, 255)  # only one screenshot shows both ends
PATH_ABYSS = (230, 80, 255)
LANDMARK_COL = {
    "Tower": (100, 235, 100),
    "City": (255, 200, 80),
    "Hall": (60, 150, 255),
    "Breach stronghold": (235, 110, 225),
    "Locked stronghold": (150, 90, 150),
    "Deadly boss map": (50, 50, 255),
}
BOOKMARK_COL = (40, 210, 255)
SELECT_COL = (255, 255, 255)
HIT_COL = (0, 255, 255)
REMOVED_COL = (70, 70, 255)
STYLE_DEFAULT = {
    "path_style": "solid",
    "path_width": 0,
    "path_col": "",
    "path_col1": "",
    "map_col": "",
    "map_size": 1.0,
    "map_style": "circles",
    "path_freq": 0.0,
    "ov_badges": False,
    "ov_towers": False,
}  # View tab


def hex_bgr(h: str, default):
    try:
        h = h.lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)) if len(h) == 6 else default
    except ValueError:
        return default


def bgr_hex(c) -> str:
    return f"#{int(c[2]):02x}{int(c[1]):02x}{int(c[0]):02x}"


def draw_paths(img, lines, col, th, style):
    """many path polylines in one draw call: solid, or cut into dashes / dots first (fast at any zoom)"""
    if not lines:
        return
    if style == "solid":
        cv2.polylines(img, [np.asarray(L, np.int32) for L in lines], False, col, th, cv2.LINE_AA)
        return
    on = max(6.0, 5.0 * th) if style == "dashed" else 0.5
    period = on + (max(4.0, 3.0 * th) if style == "dashed" else max(5.0, 4.0 * th))
    pieces = []
    for L in lines:
        L = np.asarray(L, float)
        seg = np.hypot(*np.diff(L, axis=0).T)
        cum = np.concatenate([[0], np.cumsum(seg)])
        if cum[-1] < 2:
            continue
        t0 = np.arange(0, cum[-1], period)
        t1 = np.minimum(t0 + on, cum[-1])
        x0, y0 = np.interp(t0, cum, L[:, 0]), np.interp(t0, cum, L[:, 1])
        x1, y1 = np.interp(t1, cum, L[:, 0]), np.interp(t1, cum, L[:, 1])
        pieces.extend(np.stack([np.column_stack([x0, y0]), np.column_stack([x1, y1])], 1).astype(np.int32))
    if pieces:
        w = th if style == "dashed" else max(2, 2 * th)
        cv2.polylines(img, pieces, False, col, w, cv2.LINE_AA)


def draw_map(img, pt, r, col, th, style, pic):
    """one map in the chosen style: circles / squares / map icons / hidden"""
    x, y = int(pt[0]), int(pt[1])
    if style == "hidden":
        return
    if style == "squares":
        cv2.rectangle(img, (int(x - r), int(y - r)), (int(x + r), int(y + r)), col, th, cv2.LINE_AA)
    elif style == "map icons":
        blit_rgba(img, pic, x, y, 2.8 * r)
    else:
        cv2.circle(img, (x, y), int(r), col, th, cv2.LINE_AA)


_BLIT: dict = {}


def blit_rgba(img, pil_rgba, x, y, size):
    """paste a PIL RGBA picture centred at (x, y), `size` px wide"""
    size = int(max(6, min(96, size)))
    key = (id(pil_rgba), size)
    if key not in _BLIT:
        a = np.asarray(pil_rgba.resize((size, size), Image.LANCZOS).convert("RGBA"), np.float32)
        _BLIT[key] = (a[..., [2, 1, 0]], a[..., 3:4] / 255.0)
        while len(_BLIT) > 400:
            _BLIT.pop(next(iter(_BLIT)))
    rgb, al = _BLIT[key]
    h, w = img.shape[:2]
    x0, y0 = int(x - size / 2), int(y - size / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(w, x0 + size), min(h, y0 + size)
    if xa >= xb or ya >= yb:
        return
    sub = img[ya:yb, xa:xb].astype(np.float32)
    r_ = rgb[ya - y0 : yb - y0, xa - x0 : xb - x0]
    a_ = al[ya - y0 : yb - y0, xa - x0 : xb - x0]
    img[ya:yb, xa:xb] = (sub * (1 - a_) + r_ * a_).astype(np.uint8)


IMAGE_EXT = core.IMAGE_EXT
WATCH_BATCH = 24  # auto-add: screenshots waiting in the queue are added together (one re-check)
WATCH_POLL_MS = 2000  # how often the watched folder is checked
TERRAIN_PIXELS = 40_000_000  # stitched map size limit
SAME_SPOT = 28.0  # atlas units: a bookmark this close to a thing IS that thing's bookmark
# (a map's badge sits ~24 above its base; maps are >= ~36 apart)
SNAP_PX = 16  # bookmark mode: clicks this close (screen px) to a map/icon snap to it
RECENT_KEEP = 200  # screenshots listed under Recently added (one line each, newest first)
RECENT_FADE = 5  # ...of which the newest 5 are outlined on the map: 100% fading to 0
UNDO_KEEP = 10  # atlas snapshots kept for "Undo last add"
RECENT_COL = (255, 0, 255)  # outline of the newest screenshot(s); older recent ones fade
# A placement is "weak" only when BOTH signs are poor (crawl: correct placements went down to
# 9 agreeing maps, 13% were terrain-only; terrain agreement 2nd percentile 0.43) -> ~1-2% asked
WEAK_INLIERS = 9  # at most this many agreeing maps (or terrain only) ...
WEAK_NCC = 0.45  # ... AND terrain agreement below this
PROFILE = bool(os.environ.get("ATLAS_VIEWER_PROFILE"))  # print slow window-thread steps
# The worker's Python loops share the interpreter with the window; with the default 5 ms turns a
# redraw (hundreds of small drawing calls) waited ~0.5 s while screenshots were being added.
sys.setswitchinterval(0.0005)
HIRES_MAX_FRAMES = 30  # screenshots warped at native resolution for one zoomed-in view

# game icon -> (poe2db name, BGR colour, other names it can be searched by).  Names follow
# poe2db.tw Waystones > Map Legends / Map Content.
ICON_INFO = {
    "MapBoss": ("Powerful Map Boss", (70, 120, 255), "map boss, defeat the map boss"),
    "MapBossSpecial": ("Deadly Map Boss", (50, 50, 255), "special boss, hall boss, city boss"),
    "UniqueMap": ("Unique Map", (0, 190, 255), ""),
    "Abyss": ("Abyss", (90, 230, 60), "complete all abysses, abyssal fissure"),
    "AbyssOverrun": ("Overrun by the Abyssal", (40, 190, 40), "abyss overrun, many extra abysses"),
    "AbyssalDepths": ("Abyssal Depths", (40, 160, 40), "complete the abyssal depths"),
    "AzmeriSpirit": ("Spirit Guide", (255, 200, 90), "azmeri spirit, complete all azmeri spirits, viridian wildwood"),
    "Delirium": ("Delirium", (225, 225, 225), "delirium mirror, simulacrum"),
    "Breach": ("Breach", (235, 90, 220), "unstable breaches, breach hive"),
    "Expedition": ("Expedition", (90, 200, 255), "kalguuran expedition, grand expedition"),
    "ExpeditionRemnant": ("Verisium Remnants", (90, 200, 255), "collect the verisium remnants"),
    "Ritual": ("Ritual", (60, 60, 200), "ritual altars"),
    "Essence": ("Essence Trove", (200, 120, 255), "essence, free all essence monsters"),
    "Irradiated": ("Irradiated", (60, 255, 200), "+1 monster level"),
    "StrongBox": ("Monstrous Treasure", (80, 170, 230), "strongbox, open all strongboxes"),
    "Incursion": ("Vaal Beacons", (120, 160, 120), "incursion, energise the vaal beacons"),
    "Shrine": ("Shrines", (200, 200, 120), "activate all shrines"),
    "RogueExile": ("Rogue Exiles", (60, 60, 230), "defeat all rogue exiles"),
    "RareMonster": ("Rare Monsters", (40, 200, 230), "defeat all rare monsters"),
    "Checkpoint": ("Checkpoints", (200, 200, 200), "activate all checkpoints"),
    "StoneCircle": ("Summoning Circles", (150, 150, 200), "stone circle, complete all summoning circles"),
    "Corruption": ("Corruption", (130, 40, 160), ""),
    "CorruptionNexus": ("Corrupted Boss", (160, 40, 200), "defeat the corrupted boss, corrupted nexus"),
    "CorruptionNexusNoGrowth": ("Corrupted Nexus", (160, 60, 200), ""),
    "Sanctification": ("Cleansed", (220, 240, 255), "sanctification"),
    "SanctificationBoss": ("Immured Fury", (200, 220, 255), "doryani"),
    "Trader": ("Wandering Trader", (120, 220, 255), "trader"),
    "NamelessSeer": ("Nameless Seer", (200, 140, 255), "seer"),
    "Hideout": ("Hideout", (200, 255, 200), ""),
    "LostTower": ("Precursor Tower", (100, 235, 100), "lost tower, tower"),
    "Unidentified": ("Unidentified badge", (160, 160, 160), "unknown"),
    # taught by hand on the badge sheet (atlas_icon_refs, badge_refs table in the icon database);
    # poe2db Map Content names
    "MirageOfRiches": ("Mirage of Riches", (120, 200, 220), "equipment replaced"),
    "ZealousReverence": ("Zealous Reverence", (200, 120, 160), "shrine duration"),
    "SurprisingAlliances": ("Surprising Alliances", (60, 160, 230), "rogue exiles in pairs"),
    "SpiritMigration": ("Spirit Migration", (220, 140, 255), "azmeri spirit moves"),
    "PowerOfFaith": ("Power of Faith", (60, 120, 220), "additional shrines"),
    "TwiceLockedBoxes": ("Twice-Locked Boxes", (90, 160, 210), "strongboxes openable twice"),
    "BehemothsBounty": ("Behemoth's Bounty", (230, 190, 120), "map boss drops a unique"),
    "ExceptionalFind": ("Exceptional Find", (230, 170, 90), "exceptional items"),
    "GiganticUprising": ("Gigantic Uprising", (240, 200, 110), "gigantic monsters"),
    "ScatteredStones": ("Scattered Stones", (220, 180, 100), "summoning circles"),
    "TwinnedTerrors": ("Twinned Terrors", (200, 160, 90), "summoning circles additional boss"),
    "Headhunters": ("Headhunters", (60, 80, 230), "rare monster modifiers"),
    "ArcaneOrProsperous": (
        "Arcane Hordes / Prosperous Populous",
        (60, 100, 240),
        "arcane hordes, prosperous populous, magic monsters, rarity",
    ),
    "CorruptedMirage": ("Corrupted Mirage", (40, 70, 240), "additional waystone modifiers"),
    "GrandMirror": ("Grand Mirror", (200, 200, 200), "mirror"),
    "Simulacrum": ("Simulacrum", (230, 230, 230), "delirium manifestation"),
    "IndomitableEssence": ("Indomitable Essence", (255, 200, 150), "essence"),
    "AzmeriEnergisation": ("Azmeri Energisation", (240, 90, 220), "azmeri spirits empowerment"),
    "EchoesOfPower": ("Echoes of Power", (200, 80, 180), "rare monsters duplicated"),
    "ChaoticCacophony": ("Chaotic Cacophony", (120, 200, 120), "extra of each content"),
    "GrassInfluence": ("Grass Influence", (80, 210, 120), "grass area, biome"),
    "PowerStruggle": ("Power Struggle", (230, 80, 140), "additional map bosses"),
    "HuntingGrounds": ("Hunting Grounds", (60, 220, 60), "rogue exiles rare beasts"),
    "AzmeriChampion": ("Azmeri Champion", (255, 170, 80), "map boss is possessed"),
    "LargeCongregation": ("Large Congregation", (90, 150, 210), "shrines worshippers"),
    "AncientTrove": ("Ancient Trove", (60, 120, 200), "unique trove, unique strongbox"),
    "SacredSpirit": ("Sacred Spirit", (60, 120, 255), "azmeri sacred spirit"),
    "SwarmingSpirits": ("Swarming Spirits", (200, 160, 80), "additional azmeri spirits"),
    "AzmeriBloodline": ("Azmeri Bloodline", (80, 200, 120), "rogue exile azmeri"),
    "NatureShrines": ("Nature Shrines", (140, 200, 120), "shrines azmeri spirit"),
    "RitesOfTheRogues": ("Rites of the Rogues", (40, 150, 230), "shrines rogue exile"),
    "AffluentArmies": ("Affluent Armies", (60, 210, 230), "rarity"),
    "FragmentOfImmortality": ("Fragment of Immortality", (200, 100, 200), "unlimited revivals"),
    "PersistentDevotion": ("Persistent Devotion", (120, 180, 140), "shrine buffs"),
    "CrystalisedTwinning": ("Crystalised Twinning", (220, 120, 140), "essence packs"),
    "TightPockets": ("Tight Pockets", (200, 110, 150), "gold replaced"),
    "ForestInfluence": ("Forest Influence", (60, 160, 60), "forest area, biome"),
    "MountainInfluence": ("Mountain Influence", (190, 190, 190), "mountain area, biome"),
    "StolenPower": ("Stolen Power", (40, 120, 255), "summoning circle bosses, power of enemy slain"),
    "GlimmeringMutation": ("Glimmering Mutation", (40, 200, 255), "currency replaced with rarer varieties"),
    "PlayerOrBookmark": ("Player / bookmark marker", (255, 255, 255), "player, bookmark, pin, ritual"),
}


def icon_aliases(raw: str) -> str:
    info = ICON_INFO.get(raw)
    return f"{info[0]} {info[2]} {raw}".lower() if info else raw.lower()


def icon_name(raw: str) -> str:
    if raw in ICON_INFO:
        return ICON_INFO[raw][0]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", raw).capitalize()


def icon_label(ic: dict) -> str:
    return ic.get("label") or icon_name(ic["name"])


PLACE_ICON = {
    "City": "MapBossSpecial",
    "Hall": "MapBossSpecial",
    "Breach stronghold": "MapBossSpecial",
    "Tower": "LostTower",
    "Ezomyte city": "MapBossSpecial",
    "Vaal city": "MapBossSpecial",
    "Faridun city": "MapBossSpecial",
    "Potential city map": "GrassInfluence",
    "Potential stronghold map": "Breach",
}  # place rows in the Find list: shown with these icons
CITY_COL = {
    "Ezomyte": (90, 210, 90),
    "Vaal": (240, 150, 50),
    "Faridun": (240, 215, 130),
    "Breach": (225, 80, 235),
}  # tint of the maps a city / stronghold biome may cover
POTENTIAL_TYPES = ("Potential city map", "Potential stronghold map")
_THUMBS: dict = {}


def icon_thumb(raw: str, size: int = 22):
    """small RGBA picture of a badge type (PIL image): the game's own icon from atlas_icons.zip
    when there is one, otherwise a taught reference crop (icon database) cut to a circle"""
    key = (raw, size)
    if key in _THUMBS:
        return _THUMBS[key]
    img = None
    try:
        import io
        import zipfile

        with zipfile.ZipFile(rc_paths.ref("atlas_icons.zip")) as z:
            want = {f"AtlasIconContent{raw}.webp", f"{raw}.webp"}
            name = next((n for n in z.namelist() if n.split("/")[-1] in want), None)
            if name:
                im = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
                bbox = im.getchannel("A").point(lambda a: 255 if a > 120 else 0).getbbox()
                img = im.crop(bbox) if bbox else im
    except Exception:
        img = None
    if img is None:
        import atlas_icon_refs

        refs = atlas_icon_refs.load(raw)[:1]
        if refs:
            c = refs[0][1]
            if c is not None:
                c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
                hh, ww = c.shape[:2]
                yy, xx = np.mgrid[:hh, :ww]
                alpha = (np.hypot(xx - ww / 2 + 0.5, yy - hh / 2 + 0.5) <= min(hh, ww) / 2 - 1).astype(np.uint8) * 255
                img = Image.fromarray(np.dstack([c, alpha]), "RGBA")
    if img is None:  # no picture: a dot in the type's colour
        b, g, r = icon_col(raw)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        from PIL import ImageDraw

        ImageDraw.Draw(img).ellipse((4, 4, size - 4, size - 4), fill=(r, g, b, 255))
    img = img.resize((size, size), Image.LANCZOS)
    _THUMBS[key] = img
    return img


def icon_col(raw: str):
    return ICON_INFO.get(raw, ("", (230, 140, 255), ""))[1]


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s: dict) -> None:
    try:
        atlas_io.write_text_atomic(SETTINGS, json.dumps(s, indent=1))
    except Exception:
        LOG.warning("settings could not be saved", exc_info=True)


def put_text(img, text, org, col, scale=0.5, thick=1):
    x, y = int(org[0]), int(org[1])
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick, cv2.LINE_AA)


def view_model(atlas: core.Atlas) -> dict:
    """Nodes / paths / landmarks to show: the atlas-wide result when there is one."""
    j = atlas.to_json()
    fin = j.get("final")
    if fin:
        nodes, landmarks = fin["nodes"], fin["landmarks"]
        paths = [dict(p) for p in fin["paths"]]
    else:  # an atlas made before atlas_finalize existed
        nodes = [
            {
                "id": n["id"],
                "x": n["x"],
                "y": n["y"],
                "frames": sorted(set(n["frames"])),
                "seen": len(set(n["frames"])),
                "could": len(set(n["frames"])),
                "status": "confirmed" if len(set(n["frames"])) >= 2 else "single",
                "tower": n["tower"],
                "icons": [n["icon"]] if n.get("icon") else [],
                "abyss": "",
                "why": "",
                "origin": "detected",
            }
            for n in j["nodes"]
        ]
        paths = [
            {
                "a": e["a"],
                "b": e["b"],
                "frames": e["could"],
                "support": e["seen"],
                "abyss": False,
                "score": e["strength"],
            }
            for e in j["edges"]
        ]
        landmarks = [dict(lm, status="kept") for lm in j["landmarks"]]
    icons = fin["icons"] if fin and "icons" in fin else [i for i in j.get("icons", []) if i["name"] != "LostTower"]
    landmarks = apply_landmark_edits(landmarks, getattr(atlas, "landmark_edits", []))
    return {
        "nodes": nodes,
        "paths": paths,
        "landmarks": landmarks,
        "icons": icons,
        "frames": j["frames"],
        "stats": (fin or {}).get("stats", {}),
    }


LANDMARK_KINDS = ("City", "Hall", "Tower", "Breach stronghold", "Locked stronghold", "Deadly boss map")
EDIT_SAME = 90.0  # atlas units: a hand edit applies to the landmark this close (landmarks drift
# a little between re-checks)
EDIT_SPOT = 15.0  # a new edit replaces an older one only at the same spot


def apply_landmark_edits(landmarks: list[dict], edits: list[dict]) -> list[dict]:
    """landmarks with the user's changes: kind changed, deleted (kind ""), or added on a map.
    An edit made on a map ("on": "map") adds its own landmark there (unless one sits on that very spot);
    an edit made on a landmark changes the nearest landmark within EDIT_SAME. Each landmark takes one edit,
    closest first, so a City set on a map next to a Tower never turns the Tower into a City."""
    out = [dict(lm) for lm in landmarks]
    taken: set = set()
    order = sorted(
        range(len(edits)),
        key=lambda k: min([math.hypot(lm["x"] - edits[k]["x"], lm["y"] - edits[k]["y"]) for lm in out] + [1e9]),
    )
    for k in order:
        e = edits[k]
        reach = EDIT_SPOT if e.get("on") == "map" else EDIT_SAME
        near = [(math.hypot(lm["x"] - e["x"], lm["y"] - e["y"]), i) for i, lm in enumerate(out) if i not in taken]
        d, i = min(near) if near else (1e9, -1)
        if d < reach:
            taken.add(i)
            lm = out[i]
            if e["kind"]:
                lm.update(kind=e["kind"], status="kept", beam="set by you", source="you")
            else:
                lm["status"] = "removed: deleted by you"
        elif e["kind"]:
            out.append(
                {
                    "kind": e["kind"],
                    "x": e["x"],
                    "y": e["y"],
                    "n": 1,
                    "could": 1,
                    "conf": 1.0,
                    "source": "you",
                    "status": "kept",
                    "beam": "set by you",
                }
            )
            taken.add(len(out) - 1)
    return out


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


class Viewer:
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
        style.configure(
            "TNotebook.Tab", padding=(10 if rc_paths.CHANNEL != "internal" else 6, 4)
        )  # internal has a Debug tab too
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
        if rc_paths.CHANNEL == "internal":
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

    # ------------------------------------------------------------------ icon filter
    def rebuild_icon_filter(self, counts: dict[str, int] | None = None):
        """the type list in Find: places (City, Hall, Tower, Breach stronghold) then map icons, each
        with its picture, a show-on-map tick and its count; filtered by the search text"""
        if counts is not None:
            self.type_counts = counts
        counts = self.type_counts
        near = self.near_only()
        if near:  # only what is on / next to a city biome
            counts = {}
            for i, ic in enumerate(self.V["icons"]):
                if self.icon_near_city(i):
                    counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
            for k in ("City", "Ezomyte city", "Vaal city", "Faridun city", "Potential city map"):
                if k in self.type_counts:
                    counts[k] = self.type_counts[k]
        q = self.query.get().strip().lower() if hasattr(self, "query") else ""
        key = (q, near, tuple(sorted(counts.items())), tuple(self.place_types), tuple(self.icon_types))
        if key == getattr(self, "_type_list_key", None):
            return  # nothing changed: keep the widgets
        self._type_list_key = key
        for w in self.icon_frame.winfo_children():
            w.destroy()
        self._thumb_photos = []
        photos = self.__dict__.setdefault("_photo_cache", {})
        kept = {lab: self.icon_vars[lab].get() for lab in self.icon_vars}
        self.icon_vars = {}
        raw_of = {}
        for ic in self.V["icons"]:
            raw_of.setdefault(icon_label(ic), ic["name"])
        sections = [("Places", self.place_types), ("Map icons", self.icon_types)]
        r = 0
        for title, labels in sections:
            labels = [lab for lab in labels if lab in counts]
            shown = [
                lab for lab in labels if not q or q in lab.lower() or (lab in raw_of and q in icon_aliases(raw_of[lab]))
            ]
            for lab in labels:  # keep ticks of rows filtered out of view
                self.icon_vars[lab] = tk.BooleanVar(value=kept.get(lab, lab not in self.icon_hidden))
            if not shown:
                continue
            hd = tk.Label(
                self.icon_frame, text=title, background="white", foreground="#666", font=("TkDefaultFont", 8, "bold")
            )
            hd.grid(row=r, column=0, sticky="w", padx=4, pady=(4, 0))
            r += 1
            for lab in shown:
                raw = PLACE_ICON.get(lab) if title == "Places" else raw_of.get(lab, "")
                row = tk.Frame(self.icon_frame, background="white")
                row.grid(row=r, column=0, sticky="w")
                r += 1
                tk.Checkbutton(
                    row,
                    variable=self.icon_vars[lab],
                    background="white",
                    activebackground="white",
                    foreground="black",
                    selectcolor="white",
                    command=self.on_icon_filter,
                ).pack(side="left")
                photo = photos.get(raw or "Unidentified")
                if photo is None:
                    photo = photos[raw or "Unidentified"] = ImageTk.PhotoImage(icon_thumb(raw or "Unidentified"))
                self._thumb_photos.append(photo)
                tk.Label(row, image=photo, background="white").pack(side="left", padx=(0, 4))
                name = tk.Label(
                    row, text=f"{lab}  ({counts.get(lab, 0)})", background="white", foreground="black", cursor="hand2"
                )
                name.pack(side="left")
                name.bind("<Button-1>", lambda _e, lb=lab: self.list_type(lb))
                for wdg in row.winfo_children() + [row]:
                    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                        wdg.bind(seq, self._scroll_icons)
        self.icon_canvas.yview_moveto(0)

    def _scroll_icons(self, e):
        """scroll the type list, never past its ends (that left smeared copies of the rows on Windows)"""
        c = self.icon_canvas
        first, last = c.yview()
        step = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
        if (step < 0 and first <= 0.0) or (step > 0 and last >= 1.0):
            return "break"
        c.yview_scroll(step * 3, "units")
        c.update_idletasks()
        return "break"

    def list_type(self, label):
        """list every map / place of one type in the results (keeps the type list as it is)"""
        self._last_list = label
        self.hits, labels = [], []
        if label in POTENTIAL_TYPES:
            for v, (lab, st) in sorted(self.potential.items(), key=lambda t: (t[1][0], t[1][1])):
                if st and self.potential_kind(lab) == label:
                    self.hits.append(("node", v))
                    labels.append(self.potential_text(v))
        elif label.endswith(" city"):
            for i, (t, how) in self.city_type.items():
                if f"{t} city" == label:
                    self.hits.append(("landmark", i))
                    labels.append(f"{self.lm_name(i)}  ({'set by hand' if how == 'set' else how})")
        elif label in self.place_types:
            for i, lm in enumerate(self.V["landmarks"]):
                if lm["kind"] == label and not lm["status"].startswith("removed"):
                    self.hits.append(("landmark", i))
                    labels.append(f"{lm['kind']}  (seen {lm['n']}x)")
        else:
            for i, ic in enumerate(self.V["icons"]):
                if icon_label(ic) == label:
                    self.hits.append(("icon", i))
                    labels.append(f"{label}  (seen {ic['n']}x)")
        self._fill_results(labels)
        self.status.set(f"{len(labels)} {label}")

    def on_icon_filter(self):
        self.icon_hidden = {lab for lab, v in self.icon_vars.items() if not v.get()}
        self.request_redraw()

    def set_all_icons(self, on: bool):
        for v in self.icon_vars.values():
            v.set(on)
        self.on_icon_filter()

    def near_only(self) -> bool:
        v = getattr(self, "only_near_city", None)
        return bool(v is not None and v.get())

    def icon_near_city(self, i: int) -> bool:
        v = getattr(self, "icon_node", {}).get(i)
        return v is not None and v in getattr(self, "near_city", {})

    def icon_visible(self, ic) -> bool:
        if icon_label(ic) in self.icon_hidden:
            return False
        if self.near_only():
            i = getattr(self, "_icon_index", {}).get(id(ic))
            return i is not None and self.icon_near_city(i)
        return True

    # ------------------------------------------------------------------ fill-in areas
    # ------------------------------------------------------------------ native-resolution terrain
    def hires_wanted(self) -> bool:
        return bool(self.pyr) and self.z > self.t_origin[2] * 1.15 and self.layers["Terrain"].get()

    def view_key(self, w, h):
        return (w, h, round(self.cx, 2), round(self.cy, 2), round(self.z, 6))

    def _schedule_hires(self):
        if self._hires_job:
            self.root.after_cancel(self._hires_job)
        self._hires_job = self.root.after(140, self._make_hires)

    def _frame_weight(self, f):
        """distance-to-edge weight (quarter resolution) so each spot comes from its most central screenshot"""
        key = f["name"]
        if key not in self._weights:
            img = self.atlas.image(f["path"])
            v = core._valid_mask(img)
            small = cv2.resize(v, (v.shape[1] // 4, v.shape[0] // 4), interpolation=cv2.INTER_NEAREST)
            small[small > 0] = 255
            d = cv2.distanceTransform(small, cv2.DIST_L2, 3)
            self._weights[key] = d.astype(np.float32)
        return self._weights[key]

    def _make_hires(self, background=True):
        """sharp view from the screenshots themselves; built in a background thread so panning
        and adding stay smooth (the newest request wins)"""
        self._hires_job = None
        if not self.atlas or not self.hires_wanted():
            return
        w, h = self.canvas_size()
        key = self.view_key(w, h)
        cx, cy, z = self.cx, self.cy, self.z
        jobs = list(zip(list(self.atlas.frames), list(self.footprints), strict=False))
        self._hires_req = key
        if background:
            threading.Thread(target=self._hires_work, args=(key, w, h, cx, cy, z, jobs), daemon=True).start()
        else:
            self._hires_work(key, w, h, cx, cy, z, jobs)
            self._drain_queue()

    def _hires_work(self, key, w, h, cx, cy, z, jobs):
        t0 = time.perf_counter()
        V = np.array([[z, 0, -cx * z + w / 2], [0, z, -cy * z + h / 2], [0, 0, 1]])
        out = np.zeros((h, w, 3), np.uint8)
        best = np.zeros((h, w), np.float32)
        frames = []
        for f, (poly, _bb) in jobs:
            sp = (np.asarray(poly, float) - [cx, cy]) * z + [w / 2, h / 2]
            x0, y0 = np.floor(sp.min(axis=0)).astype(int)
            x1, y1 = np.ceil(sp.max(axis=0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if x1 <= x0 or y1 <= y0 or not Path(f["path"]).exists():
                continue
            ctr = sp.mean(axis=0)
            frames.append((math.hypot(ctr[0] - w / 2, ctr[1] - h / 2), f, (x0, y0, x1, y1)))
        frames.sort(key=lambda t: t[0])
        for _, f, (x0, y0, x1, y1) in frames[:HIRES_MAX_FRAMES]:
            Hf = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]]) @ V @ Hf
            size = (x1 - x0, y1 - y0)
            pix = cv2.warpPerspective(
                self.atlas.image(f["path"]), T, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            S4 = np.diag([4.0, 4.0, 1.0])
            wt = cv2.warpPerspective(
                self._frame_weight(f), T @ S4, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
            )
            sub_b = best[y0:y1, x0:x1]
            take = wt > sub_b
            out[y0:y1, x0:x1][take] = pix[take]
            sub_b[take] = wt[take]
            if time.perf_counter() - t0 > 1.5 or getattr(self, "_hires_req", key) != key:
                break  # too slow, or the view moved on
        self._q.put(("hires", (key, out, best > 0)))

    def canvas_size(self) -> tuple[int, int]:
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def canvas_size_half(self) -> tuple[float, float]:
        w, h = self.canvas_size()
        return w / 2, h / 2

    def _tk_error(self, tp, val, tb):
        """an error inside a button / menu / key handler: logged with its traceback, shown in Log"""
        LOG.error("error in a window handler", exc_info=(tp, val, tb))
        with contextlib.suppress(Exception):
            self.log(f"error: {val!r} (details in {atlas_log.LOG_FILE.name})")

    def log(self, text: str):
        LOG.info(text.strip("\n"))
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.strip("\n") + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

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

    # ------------------------------------------------------------------ layer toggles (under the tabs)
    LAYER_GRID = (
        ("Terrain", "Terrain"),
        ("Paths", "Paths"),
        ("Nodes", "Maps"),
        ("Icons", "Icons"),
        ("Landmarks", "Landmarks"),
        ("Bookmarks", "Bookmarks"),
        ("Labels", "Labels"),
        ("Doubtful", "Doubtful"),
        ("Removed", "Removed"),
        ("Recent additions", "New"),
        ("City & stronghold biomes", "City biomes"),
    )

    # ------------------------------------------------------------------ View tab: styles and overlays
    def style(self) -> dict:
        st = self.settings.setdefault("style", {})
        return {**STYLE_DEFAULT, **st}

    def set_style(self, **kw):
        self.settings.setdefault("style", {}).update(kw)
        save_settings(self.settings)
        self.request_redraw()

    def _build_style_ui(self, vw):
        """View tab (user's mockup): Paths and Maps sections with a live preview each; colour squares are buttons"""
        from tkinter import colorchooser

        st = self.style()
        PW, PH = 300, 46

        def preview_paths():
            S_ = self.style()
            im = np.full((PH, PW, 3), (34, 38, 42), np.uint8)
            th = int(S_["path_width"]) or 2
            draw_paths(
                im,
                [np.array([[14, PH * 0.62], [PW * 0.45, PH * 0.3], [PW - 14, PH * 0.55]])],
                hex_bgr(S_["path_col"], PATH_MULTI),
                th,
                S_["path_style"],
            )
            return im

        def preview_maps():
            S_ = self.style()
            im = np.full((PH, PW, 3), (34, 38, 42), np.uint8)
            r = 8 * float(S_["map_size"])
            col = hex_bgr(S_["map_col"], NODE_COL["confirmed"])
            draw_map(im, (PW // 2, PH // 2), r, col, 2, S_["map_style"], self._map_pic())  # one map, centred
            return im

        previews = []

        def refresh():
            for lab, fn in previews:
                ph = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(fn(), cv2.COLOR_BGR2RGB)))
                lab.configure(image=ph)
                lab.image = ph

        def changed(**kw):
            self.set_style(**kw)
            refresh()

        def swatch(parent, key, default, text):
            box = ttk.Frame(parent)
            box.pack(side="left", padx=(0, 12))
            sw = tk.Label(
                box,
                width=3,
                height=1,
                relief="raised",
                borderwidth=2,
                cursor="hand2",
                background=self.style()[key] or bgr_hex(default),
            )
            sw.pack(side="left", padx=(0, 4))
            ttk.Label(box, text=text).pack(side="left")

            def pick(_e=None):
                got = colorchooser.askcolor(color=self.style()[key] or bgr_hex(default), title=text)[1]
                if got:
                    sw.configure(background=got)
                    changed(**{key: got})

            sw.bind("<Button-1>", pick)
            return sw, key, default

        def section(title):
            ttk.Separator(vw).pack(fill="x", pady=(10, 4))
            ttk.Label(vw, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
            lab = tk.Label(vw, borderwidth=1, relief="sunken")
            lab.pack(anchor="w", pady=(2, 4))
            return lab

        # --- Paths
        previews.append((section("Paths"), preview_paths))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        sw_list = [swatch(row, "path_col", PATH_MULTI, "colour"), swatch(row, "path_col1", PATH_SINGLE, "1 shot")]
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        self._st_width = tk.IntVar(value=int(st["path_width"]))
        ttk.Spinbox(
            row,
            from_=0,
            to=8,
            width=3,
            textvariable=self._st_width,
            command=lambda: changed(path_width=int(self._st_width.get())),
        ).pack(side="left")
        ttk.Label(row, text="width (0 = auto)").pack(side="left", padx=(4, 12))
        self._st_path = tk.StringVar(value=st["path_style"])
        cb = ttk.Combobox(
            row, textvariable=self._st_path, values=("solid", "dashed", "dotted"), width=8, state="readonly"
        )
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: changed(path_style=self._st_path.get()))
        ttk.Label(row, text="style").pack(side="left", padx=4)
        ttk.Checkbutton(
            vw, text="only what 2+ screenshots show", variable=self.multi_only, command=self.request_redraw
        ).pack(anchor="w", pady=(2, 0))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="drawn by at least").pack(side="left")
        self._st_freq = tk.DoubleVar(value=float(st["path_freq"]) * 100)
        freq_lab = ttk.Label(row, text=f"{self._st_freq.get():.0f}%", width=5)

        def on_freq(v):
            freq_lab.configure(text=f"{float(v):.0f}%")
            changed(path_freq=round(float(v) / 100, 2))

        ttk.Scale(row, from_=0, to=100, variable=self._st_freq, length=110, command=on_freq).pack(side="left", padx=4)
        freq_lab.pack(side="left")
        ttk.Label(vw, text="   of the screenshots that show both maps", foreground="#555").pack(anchor="w")

        # --- Maps
        previews.append((section("Maps"), preview_maps))
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        sw_list.append(swatch(row, "map_col", NODE_COL["confirmed"], "colour"))
        ttk.Label(row, text="size").pack(side="left")
        self._st_size = tk.DoubleVar(value=float(st["map_size"]))
        ttk.Scale(
            row,
            from_=0.5,
            to=2.5,
            variable=self._st_size,
            length=120,
            command=lambda v: changed(map_size=round(float(v), 2)),
        ).pack(side="left", padx=4)
        row = ttk.Frame(vw)
        row.pack(fill="x", pady=2)
        self._st_mstyle = tk.StringVar(value=st["map_style"])
        cb2 = ttk.Combobox(
            row,
            textvariable=self._st_mstyle,
            values=("circles", "squares", "map icons", "hidden"),
            width=10,
            state="readonly",
        )
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda e: changed(map_style=self._st_mstyle.get()))
        ttk.Label(row, text="style").pack(side="left", padx=4)

        # --- pictures
        ttk.Separator(vw).pack(fill="x", pady=(10, 4))
        ttk.Label(vw, text="Pictures on the map (zoomed in)", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self._st_ov = {}
        for key, text in (("ov_badges", "badge pictures (the icons ticked in Find)"), ("ov_towers", "tower picture")):
            v = self._st_ov[key] = tk.BooleanVar(value=bool(st[key]))
            ttk.Checkbutton(
                vw, text=text, variable=v, command=lambda k=key: changed(**{k: bool(self._st_ov[k].get())})
            ).pack(anchor="w")

        def reset():
            self.settings["style"] = {}
            save_settings(self.settings)
            d = self.style()
            self._st_path.set(d["path_style"])
            self._st_width.set(d["path_width"])
            self._st_size.set(d["map_size"])
            self._st_mstyle.set(d["map_style"])
            self._st_freq.set(d["path_freq"] * 100)
            for k, v in self._st_ov.items():
                v.set(d[k])
            for sw, _key, default in sw_list:
                sw.configure(background=bgr_hex(default))
            self.request_redraw()
            refresh()

        ttk.Button(vw, text="Reset styles", command=reset).pack(anchor="w", pady=(10, 0))
        self.root.after(200, refresh)

    def _layer_icon(self, layer: str, size: int = 20):
        """small picture for a layer toggle (PIL RGBA)"""
        from PIL import ImageDraw

        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if layer == "Terrain":
            t = getattr(self, "_terrain", None)
            if t is not None and t[0] is not None and t[0].size:
                c = t[0]
                h, w = c.shape[:2]
                crop = c[
                    h // 2 - min(h, w) // 8 : h // 2 + min(h, w) // 8, w // 2 - min(h, w) // 8 : w // 2 + min(h, w) // 8
                ]
                if crop.size:
                    return Image.fromarray(
                        cv2.cvtColor(cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                    ).convert("RGBA")
            rng = np.random.default_rng(3)
            base = np.array([70, 95, 55], np.float32) + rng.normal(0, 18, (size, size, 3))
            return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")
        if layer == "Paths":
            d.line((2, size - 4, size - 3, 3), fill=(80, 200, 255, 255), width=3)
            return im
        if layer == "Nodes":
            f = rc_paths.ref("map_node_icon.webp")
            if f.exists():
                return Image.open(f).convert("RGBA").resize((size, size), Image.LANCZOS)
        if layer == "Landmarks":
            return icon_thumb("LostTower", size)
        if layer == "Icons":
            return icon_thumb("MapBoss", size)
        if layer == "Bookmarks":
            c, r1, r2 = size / 2, size / 2 - 1, size / 5
            pts = [
                (
                    c + (r1 if k % 2 == 0 else r2) * math.sin(math.pi * k / 5),
                    c - (r1 if k % 2 == 0 else r2) * math.cos(math.pi * k / 5),
                )
                for k in range(10)
            ]
            d.polygon(pts, fill=(255, 205, 40, 255), outline=(150, 110, 0, 255))
            return im
        if layer == "Labels":
            d.rounded_rectangle(
                (1, 5, size - 2, size - 5), radius=3, fill=(245, 245, 245, 255), outline=(90, 90, 90, 255)
            )
            d.ellipse((3, size / 2 - 2, 7, size / 2 + 2), fill=(90, 90, 90, 255))
            d.line((9, size / 2, size - 5, size / 2), fill=(90, 90, 90, 255), width=2)
            return im
        if layer == "Doubtful":
            d.ellipse((1, 1, size - 2, size - 2), fill=(150, 150, 150, 255))
            d.text((size / 2 - 3, 2), "?", fill=(255, 255, 255, 255))
            return im
        if layer == "Removed":
            d.ellipse((2, 2, size - 3, size - 3), outline=(220, 40, 40, 255), width=3)
            d.line((5, 5, size - 6, size - 6), fill=(220, 40, 40, 255), width=3)
            return im
        if layer == "Recent additions":
            d.rounded_rectangle((0, 4, size - 1, size - 5), radius=3, fill=(255, 210, 0, 255))
            try:
                from PIL import ImageFont

                fnt = ImageFont.load_default(size=8)
            except Exception:
                fnt = None
            tw = d.textlength("NEW", font=fnt) if fnt else 18
            d.text(((size - tw) / 2, 5 if fnt else 5), "NEW", fill=(40, 30, 0, 255), font=fnt)
            return im
        if layer == "City & stronghold biomes":
            return icon_thumb("MapBossSpecial", size)
        d.ellipse((4, 4, size - 4, size - 4), fill=(200, 200, 200, 255))
        return im

    def _build_layer_grid(self):
        """the map layers as picture toggles, 4 per row, under the tabs (visible in every tab)"""
        from PIL import ImageTk

        g = self.layer_grid
        for w in g.winfo_children():
            w.destroy()
        ttk.Label(g, text="Show on the map", font=("TkDefaultFont", 8, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        self._layer_photos = []
        for k, (layer, label) in enumerate(self.LAYER_GRID):
            ph = ImageTk.PhotoImage(self._layer_icon(layer))
            self._layer_photos.append(ph)
            b = tk.Checkbutton(
                g,
                text=label,
                image=ph,
                compound="top",
                variable=self.layers[layer],
                indicatoron=False,
                command=self.request_redraw,
                width=72,
                font=("TkDefaultFont", 8),
                selectcolor="#cfe3ff",
                relief="raised",
                offrelief="flat",
                bd=1,
                background="#ececec",
                activebackground="#dde8f7",
                foreground="black",
                activeforeground="black",
            )
            b.grid(row=1 + k // 4, column=k % 4, padx=1, pady=1, sticky="ew")
        for c in range(4):
            g.columnconfigure(c, weight=1)

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

    # ------------------------------------------------------------------ city biome lasso
    def start_lasso(self):
        if not self.atlas:
            return
        self._lasso = []
        self.canvas.configure(cursor="pencil")
        self.status.set("draw around the maps of the biome (hold the left button); Esc cancels")

    def _lasso_menu(self, ids: list[int], sx, sy):
        m = tk.Menu(self.root, tearoff=0)
        for t in atlas_cities.TYPES:
            m.add_command(label=f"{t} city", command=lambda t=t: self.set_biome(ids, f"{t} city"))
        m.add_command(label="Breach stronghold", command=lambda: self.set_biome(ids, "Breach stronghold"))
        m.add_separator()
        m.add_command(label="Not a biome (clear these maps)", command=lambda: self.set_biome(ids, ""))
        m.add_command(label="Cancel", command=self.request_redraw)
        m.tk_popup(int(self.canvas.winfo_rootx() + sx), int(self.canvas.winfo_rooty() + sy))

    def set_biome(self, ids: list[int], biome: str):
        """the lassoed maps become this biome (or none); kept in the atlas by map position"""
        pts = [[round(float(self.V["nodes"][i]["x"]), 1), round(float(self.V["nodes"][i]["y"]), 1)] for i in ids]
        keep = []
        for e in self.atlas.biome_edits:  # a newer lasso wins for maps it covers
            rest = [q for q in e["maps"] if min(math.hypot(q[0] - a, q[1] - b) for a, b in pts) > 20]
            if rest:
                keep.append(dict(e, maps=rest))
        keep.append({"biome": biome, "maps": pts})
        self.atlas.biome_edits = keep
        poly = getattr(self, "_lasso_world", None)
        if biome.endswith(" city") and poly:
            # a Hall / deadly boss map inside a hand-drawn city is that city (its Deadly Map Boss badge map)
            P = np.array(poly, np.float32).reshape(-1, 1, 2)
            typ = biome.replace(" city", "")
            for lm in self.V["landmarks"]:
                if lm["status"].startswith("removed") or lm["kind"] not in ("Hall", "Deadly boss map", "City"):
                    continue
                if cv2.pointPolygonTest(P, (float(lm["x"]), float(lm["y"])), False) < 0:
                    continue
                if lm["kind"] != "City":
                    self.atlas.landmark_edits = [
                        e
                        for e in self.atlas.landmark_edits
                        if math.hypot(e["x"] - lm["x"], e["y"] - lm["y"]) >= EDIT_SPOT
                    ]
                    self.atlas.landmark_edits.append(
                        {"x": round(lm["x"], 1), "y": round(lm["y"], 1), "kind": "City", "on": "landmark"}
                    )
                    self.log(f"{lm['kind']} at ({lm['x']:.0f}, {lm['y']:.0f}) is now a {typ} city")
                atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        LOG.info(f"{len(ids)} maps set to biome {biome or '(none)'} by hand")
        self.log(f"{len(ids)} maps " + (f"are now {biome}" if biome else "are no longer in a biome"))
        if self.path:
            self.atlas.save(self.path)
        self.rebuild_model()
        self.request_redraw()

    def apply_biome_edits(self):
        """hand-drawn biomes on top of the automatic ones (atlas.biome_edits)"""
        edits = getattr(self.atlas, "biome_edits", []) if self.atlas else []
        if not edits or not len(self.node_pts):
            return
        from scipy.spatial import cKDTree

        tree = cKDTree(self.node_pts)
        for e in edits:
            for q in e["maps"]:
                d, i = tree.query(q)
                if d > 20:
                    continue
                if e["biome"]:
                    self.potential[int(i)] = (e["biome"], 0)
                else:
                    self.potential.pop(int(i), None)

    def _initial_dir(self) -> str:
        if self.path:
            return str(self.path.parent)
        last = self.settings.get("last_atlas")
        return str(Path(last).parent) if last else str(HERE)

    def open_atlas(self, p: Path):
        try:
            atlas = core.Atlas.load(p)
        except Exception as e:
            LOG.exception(f"could not read atlas {p}")
            messagebox.showerror("Open atlas", f"Could not read {p}:\n{e}")
            return
        if self.path is None or Path(p).resolve() != Path(self.path).resolve():
            self._forget_session()
            self._drop_stale_snapshots(Path(p))
        self.atlas = atlas
        LOG.info(
            f"opened atlas {p}: {len(self.atlas.frames)} screenshots, "
            f"{len((self.atlas.final or {}).get('nodes', []))} maps"
        )
        self.path = p
        self.settings["last_atlas"] = str(p)
        if self.atlas.frames and self.atlas.final is None:
            self.log("this atlas predates the atlas-wide check: running it now")
            try:
                atlas_finalize.finalize(self.atlas, log=self.log)
                self.atlas.save(self.path)
            except Exception as e:
                LOG.exception("atlas-wide check failed")
                self.log(f"atlas-wide check failed: {e}")
        self._after_load(fit=True)
        missing = [f["name"] for f in self.atlas.frames if not Path(f["path"]).exists()]
        if missing:
            self.log(f"screenshots not found (terrain missing there): {', '.join(missing)}")
        if self.watch_var.get() and not self.settings.get("watch_folder"):
            self.start_watch()  # auto-add follows the atlas: now its folder is watched

    def _forget_session(self):
        """undo / recently added / waiting belong to the atlas they were made in: cleared when another atlas
        is opened (undo after a switch put the old atlas's maps into the new one)"""
        for entry in self._undo:
            with contextlib.suppress(OSError):
                Path(entry["file"]).unlink()
        self._undo, self.recent, self._pending_watch = [], [], []
        self._wait_tries = {}
        if hasattr(self, "recent_list"):
            self._refresh_recent()

    @staticmethod
    def _drop_stale_snapshots(atlas_path: Path):
        """undo snapshots left by an earlier session (undo only reaches this session's adds): a full copy
        of the atlas each, so they are removed instead of piling up"""
        d = core.atlas_files(atlas_path) / (atlas_path.stem + "_undo")
        for f in d.glob("before_*.json") if d.is_dir() else ():
            with contextlib.suppress(OSError):
                f.unlink()

    def _after_load(self, fit=False):
        self.sel = None
        self._terrain = None
        self.rebuild_model()
        self.rebuild_terrain()
        self.scan_locks()
        self.root.title(f"The Grand Project v{VERSION}{rc_paths.title_tag()} - {self.path.name if self.path else ''}")
        self._show_watch_label()
        if self.path:
            self.remember_atlas(self.path)
        if fit:
            self._fit_pending = True
            self.fit()
        self.request_redraw()

    def rebuild_model(self):
        self.V = view_model(self.atlas) if self.atlas else self.V
        self.node_pts = np.array([[n["x"], n["y"]] for n in self.V["nodes"]], float).reshape(-1, 2)
        self.icon_pts = np.array([[i["x"], i["y"]] for i in self.V["icons"]], float).reshape(-1, 2)
        counts: dict[str, int] = {}
        for ic in self.V["icons"]:
            counts[icon_label(ic)] = counts.get(icon_label(ic), 0) + 1
        self.icon_types = sorted(counts, key=lambda k: (k == "Unidentified badge", k))
        self.add_locks()
        for lm in self.V["landmarks"]:
            if not lm["status"].startswith("removed"):
                counts[lm["kind"]] = counts.get(lm["kind"], 0) + 1
        self._lm_index = {id(lm): i for i, lm in enumerate(self.V["landmarks"])}
        self._icon_index = {id(ic): i for i, ic in enumerate(self.V["icons"])}
        self.rebuild_cities(counts)
        self.place_types = [
            k
            for k in (
                "City",
                "Ezomyte city",
                "Vaal city",
                "Faridun city",
                "Hall",
                "Tower",
                "Breach stronghold",
                *POTENTIAL_TYPES,
            )
            if k in counts
        ]
        self.type_counts = counts  # the list itself is rebuilt by run_search below
        self.footprints = []
        for f in self.atlas.frames if self.atlas else []:
            H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
            poly = core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])
            self.footprints.append((poly, (*poly.min(axis=0), *poly.max(axis=0))))
        self._hires, self._weights = None, {}
        self.refresh_bookmarks()
        self.run_search()
        self.show_info()

    # ------------------------------------------------------------------ locked strongholds
    def add_locks(self):
        """hand badges (atlas.locks) = locked Breach strongholds: an existing stronghold nearby is
        marked locked, otherwise one is added for the view"""
        self.locked_ids = set()
        locks = self.atlas.locks if self.atlas else []
        if not locks:
            return
        L = list(self.V["landmarks"])
        for k in locks:
            if any(
                math.hypot(e["x"] - k["x"], e["y"] - k["y"]) < 300 and e["kind"] != "Breach stronghold"
                for e in self.atlas.landmark_edits
            ):
                continue  # the user deleted / changed it: leave it
            near = [
                (math.hypot(lm["x"] - k["x"], lm["y"] - k["y"]), i)
                for i, lm in enumerate(L)
                if lm["kind"] == "Breach stronghold" and not lm["status"].startswith("removed")
            ]
            d, i = min(near) if near else (1e9, -1)
            if d < 300:
                self.locked_ids.add(i)
            else:
                L.append(
                    {
                        "kind": "Breach stronghold",
                        "x": k["x"],
                        "y": k["y"],
                        "n": k["n"],
                        "could": k["n"],
                        "conf": 1.0,
                        "source": "hand badge",
                        "status": "kept",
                    }
                )
                self.locked_ids.add(len(L) - 1)
        self.V = {**self.V, "landmarks": L}

    def scan_locks(self):
        """search screenshots not searched yet for the hand badge, in the background"""
        if not self.atlas or getattr(self, "_lock_job", False):
            return
        done = set(self.atlas.lock_scanned)
        todo = [f for f in self.atlas.frames if f["name"] not in done]
        if not todo:
            return
        self._lock_job = True
        atlas = self.atlas

        def work():
            try:
                found = atlas_cities.find_locks(atlas, todo)
                self._q.put(("locks", (atlas, [f["name"] for f in todo], found)))
            except Exception as e:
                LOG.exception("locked stronghold search failed")
                self._q.put(("log", f"locked stronghold search failed: {e}"))
                self._q.put(("locks", None))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ landmark edits
    def set_landmark(self, x: float, y: float, kind: str, on: str = "landmark"):
        """change / add (kind) or delete (kind "") the landmark at x, y; kept in the atlas file.
        on = "map" when the user made a map into a landmark (it then never takes over a landmark nearby)"""
        self.atlas.landmark_edits = [
            e for e in self.atlas.landmark_edits if math.hypot(e["x"] - x, e["y"] - y) >= EDIT_SPOT
        ]
        self.atlas.landmark_edits.append({"x": round(x, 1), "y": round(y, 1), "kind": kind, "on": on})
        if not kind:  # a deleted city keeps no hand-set type
            atlas_cities.set_type(self.atlas, x, y, None)
        LOG.info(f"landmark at ({x:.0f}, {y:.0f}) " + (f"set to {kind}" if kind else "deleted"))
        self.log(f"landmark at ({x:.0f}, {y:.0f}) " + (f"is now a {kind}" if kind else "deleted"))
        if self.path:
            self.atlas.save(self.path)
        self.sel = None
        self.rebuild_model()
        self.request_redraw()

    def _kind_menu(self, parent, x, y, current="", on="landmark"):
        km = tk.Menu(parent, tearoff=0)
        for k in LANDMARK_KINDS:
            km.add_command(label=("● " if k == current else "") + k, command=lambda k=k: self.set_landmark(x, y, k, on))
        return km

    def edit_selected(self):
        """Edit button: bookmark -> its dialog; landmark / map -> pick what it is"""
        if not self.sel_valid():
            self.status.set("select a bookmark, landmark or map first")
            return
        kind, i = self.sel
        if kind == "bookmark":
            self.edit_bookmark()
            return
        if kind in ("landmark", "node"):
            x, y = self.item_pos(self.sel)
            cur = self.V["landmarks"][i]["kind"] if kind == "landmark" else ""
            m = self._kind_menu(self.root, x, y, cur, "landmark" if kind == "landmark" else "map")
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
            return
        self.status.set("only bookmarks, landmarks and maps can be edited")

    def delete_selected(self):
        """Delete button: the selected bookmark or landmark (never what is ticked in the Bookmarks tab)"""
        if not self.sel_valid():
            self.status.set("select a bookmark or landmark first")
            return
        kind, i = self.sel
        if kind == "bookmark":
            b = self.atlas.bookmarks[i]
            if messagebox.askyesno("Delete bookmark", f'Delete "{b["name"]}"?'):
                LOG.info(f"deleted bookmark: {b['name']}")
                self.atlas.bookmarks.pop(i)
                self.sel = None
                self.save()
                self.refresh_bookmarks()
                self.run_search()
                self.show_info()
                self.request_redraw()
        elif kind == "landmark":
            lm = self.V["landmarks"][i]
            if messagebox.askyesno(
                "Delete landmark",
                f"Delete this {self.lm_name(i)}?\n"
                "(kept in the atlas; Layers > Removed shows it, right-click it to bring it back)",
            ):
                self.set_landmark(lm["x"], lm["y"], "")
        else:
            self.status.set("only bookmarks and landmarks can be deleted")

    # ------------------------------------------------------------------ cities
    def rebuild_cities(self, counts: dict | None = None):
        """city types (Ezomyte / Vaal / Faridun) and the maps a city or stronghold biome may cover"""
        L = self.V["landmarks"]
        alive = [i for i, lm in enumerate(L) if not lm["status"].startswith("removed")]
        cities = [i for i in alive if L[i]["kind"] == "City"]
        self.city_type = {}
        if self.atlas and cities:
            try:
                res = atlas_cities.city_types(self.atlas, [L[i] for i in cities])
            except Exception:
                LOG.exception("city types failed")
                self.log("city types failed (details in the log file)")
                res = [("", "")] * len(cities)
            self.city_type = {i: r for i, r in zip(cities, res, strict=False) if r[0]}
        src = [
            (L[i]["x"], L[i]["y"], f"{self.city_type[i][0]} city" if i in self.city_type else "City") for i in cities
        ]
        src += [
            (L[i]["x"], L[i]["y"], "Breach stronghold")
            for i in alive  # locked ones show no maps
            if L[i]["kind"] == "Breach stronghold" and i not in getattr(self, "locked_ids", ())
        ]
        ground = None
        if getattr(self, "_terrain", None):  # the biome's own ground, from the map image
            if getattr(self, "_ground_for", None) is not self._terrain:
                canvas, weight, origin = self._terrain
                self._ground = atlas_cities.ground_sampler(canvas, weight, origin)
                self._ground_for = self._terrain
            ground = self._ground
        self.icon_node = atlas_cities.icon_maps(self.V["nodes"], self.V["icons"])
        live = [L[i] for i in alive if i not in getattr(self, "locked_ids", ())] + [
            L[i] for i in getattr(self, "locked_ids", ())
        ]
        self.blocked = atlas_cities.blocked_maps(self.V["nodes"], self.V["icons"], live, self.icon_node)
        self.potential = (
            atlas_cities.potential_maps(self.V["nodes"], self.V["paths"], src, ground=ground, blocked=self.blocked)
            if src
            else {}
        )
        LOG.debug(
            f"cities: {len(cities)} ({sum(1 for t in self.city_type.values() if t[1] == 'set')} set by hand), "
            f"strongholds {len(src) - len(cities)}, locked {len(getattr(self, 'locked_ids', ()))}, "
            f"biome maps {len(self.potential)}, blocked maps {len(self.blocked)}, ground {'yes' if ground else 'no'}"
        )
        self.apply_biome_edits()
        self.near_city = atlas_cities.near_city(self.V["nodes"], self.V["paths"], self.potential, self.blocked)
        if counts is None and getattr(self, "type_counts", None) is not None:  # map image arrived later
            counts = self.type_counts
            for k in POTENTIAL_TYPES:
                counts.pop(k, None)
            for _v, (lab, st) in self.potential.items():
                if st:
                    k = self.potential_kind(lab)
                    counts[k] = counts.get(k, 0) + 1
            self.rebuild_icon_filter()
        elif counts is not None:
            for _i, (t, _how) in self.city_type.items():
                counts[f"{t} city"] = counts.get(f"{t} city", 0) + 1
            for _v, (lab, st) in self.potential.items():
                if st:
                    k = self.potential_kind(lab)
                    counts[k] = counts.get(k, 0) + 1

    def near_city_text(self, v) -> str:
        """ "Potential city: ..." for a map, or "" when it is not on / next to a city biome"""
        t = getattr(self, "near_city", {}).get(v) if v is not None else None
        if not t:
            return ""
        lab, st = t
        return f"Potential city: {'on the' if st == 0 else '1 step from the'} {lab} biome"

    def _refilter(self):
        """the "only potential city maps" setting: type list, map and listing all follow it"""
        self.rebuild_icon_filter()
        self.request_redraw()
        if getattr(self, "_last_list", None):
            self.list_type(self._last_list)
        else:
            self.run_search()

    @staticmethod
    def potential_kind(label: str) -> str:
        return "Potential stronghold map" if label == "Breach stronghold" else "Potential city map"

    def potential_text(self, i: int) -> str:
        lab, st = self.potential[i]
        if st == 0:
            return f"{lab} (its own map)"
        return f"Potential {lab} map ({st} step{'s' if st > 1 else ''} away)"

    def lm_name(self, i: int) -> str:
        """landmark name with the city type: "Vaal city", "Ezomyte city?" (? = guessed by look)"""
        lm = self.V["landmarks"][i]
        if i in getattr(self, "locked_ids", ()):
            return "Locked Breach stronghold"
        if lm["kind"] == "City" and i in getattr(self, "city_type", {}):
            t, how = self.city_type[i]
            return f"{t} city" + ("?" if how == "look-alike" else "")
        return lm["kind"]

    def set_city_type(self, i: int, typ: str | None):
        lm = self.V["landmarks"][i]
        LOG.info(f"city type at ({lm['x']:.0f}, {lm['y']:.0f}) set to {typ or 'automatic'}")
        atlas_cities.set_type(self.atlas, lm["x"], lm["y"], typ)
        if self.path:
            self.atlas.save(self.path)
        self.rebuild_model()
        self.request_redraw()

    def on_configure(self, _e=None):
        # the first real size arrives after loading: fit then, so the map isn't fitted to 1x1 px
        if self._fit_pending and self.canvas.winfo_width() > 50:
            self.fit()
        self.request_redraw()

    def _terrain_key(self) -> str:
        import hashlib

        h = hashlib.sha1()
        for f in self.atlas.frames:
            h.update(f["name"].encode())
            h.update(np.round(np.array(f["M"], float), 2).tobytes())
        return h.hexdigest()

    def _terrain_files(self):
        d = core.atlas_files(self.path)
        return d / (self.path.stem + "_terrain.png"), d / (self.path.stem + "_terrain.npz")

    def rebuild_terrain(self, background=True):
        """stitched map: from the cache next to the atlas when it matches, else built in the
        background (the window stays usable; the map appears when it is ready)"""
        if not self.atlas or not self.atlas.frames:
            self.pyr, self._terrain = [], None
            return
        png, npz = self._terrain_files()
        key = self._terrain_key()
        try:
            meta = np.load(npz)
            if str(meta["key"]) == key:
                canvas = cv2.imdecode(np.fromfile(str(png), np.uint8), cv2.IMREAD_COLOR)
                weight = meta["weight"].astype(np.float32)
                origin = tuple(float(v) for v in meta["origin"])
                if canvas is not None and canvas.shape[:2] == weight.shape:
                    self._set_terrain(canvas, weight, origin, save=False)
                    return
        except Exception:
            LOG.debug("map image cache not usable, rebuilding", exc_info=True)
        self._terrain_job += 1
        job = self._terrain_job
        self._set_progress("building the map image (first time for this atlas)…")

        def work():
            try:
                canvas, origin, weight = self.atlas.composite(max_pixels=TERRAIN_PIXELS, with_weight=True)
                self._q.put(("terrain_img", (job, canvas, weight, origin)))
            except Exception as e:
                LOG.exception("map image could not be built")
                self._q.put(("log", f"map image could not be built: {e}"))

        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
            self._drain_queue()

    def _set_terrain(self, canvas, weight, origin, save=True):
        self.root.after(50, self._build_layer_grid)  # the Terrain toggle shows a piece of this map
        self._terrain = (canvas, weight, origin)
        self.t_origin = origin
        pyr = [canvas]
        while max(pyr[-1].shape[:2]) > 600:
            pyr.append(cv2.pyrDown(pyr[-1]))
        self.pyr = pyr
        if getattr(self, "V", None) and self.V.get("nodes"):
            self.rebuild_cities()  # biome clusters follow the ground now
        self._hires = None
        self._pending_outline = []
        if save and self.path:
            key = self._terrain_key()
            png, npz = self._terrain_files()

            def write():
                try:
                    cv2.imencode(".png", canvas)[1].tofile(str(png))
                    np.savez_compressed(npz, key=key, origin=np.array(origin, float), weight=weight.astype(np.float16))
                except Exception:
                    LOG.warning("map image cache could not be saved", exc_info=True)

            threading.Thread(target=write, daemon=True).start()
        self.request_redraw()

    def _paste_terrain(self, frames) -> bool:
        """worker: paste new screenshots into a copy of the stitched map (fast); False when they
        fall outside it and the whole map has to be rebuilt"""
        if self._terrain is None:
            return False
        canvas, weight, origin = self._terrain
        canvas, weight = canvas.copy(), weight.copy()
        if not self.atlas.paste_into(canvas, weight, origin, frames):
            return False
        self._q.put(("terrain_img", (None, canvas, weight, origin)))
        return True

    # ------------------------------------------------------------------ progress on the map
    def _set_progress(self, text):
        self._progress = (text, self._progress[1] if self._progress else time.time()) if text else None
        if text:
            self.status.set(text)
        self.request_redraw()
        if text and not getattr(self, "_progress_tick", None):
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _tick_progress(self):
        self._progress_tick = None
        if self._progress:
            self.request_redraw()
            self._progress_tick = self.root.after(500, self._tick_progress)

    def _draw_progress(self, img, w, h):
        if not self._progress:
            return
        text, t0 = self._progress
        dots = "." * (1 + int(time.time() * 2) % 3)
        line = f"{text.rstrip('.…')}{dots}   {time.time() - t0:.0f}s"
        tw = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 4)[0][0]
        x0 = w - tw - 36
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (25, 25, 25), -1)
        cv2.rectangle(img, (x0, 10), (w - 12, 44), (0, 200, 255), 1)
        put_text(img, line, (x0 + 12, 33), (0, 220, 255), 0.55)

    def _draw_pending(self, img):
        for poly in self._pending_outline:
            pts = self.to_screen(poly).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 220, 255), 2, cv2.LINE_AA)

    # ------------------------------------------------------------------ hand placement (drag a file in)
    def start_ghost(self, path: Path, sx=None, sy=None):
        """show a see-through screenshot to put roughly in place; Enter / double-click fits it"""
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            return
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self.status.set(f"not an image: {path.name}")
            return
        w, h = self.canvas_size()
        sx = w / 2 if sx is None else sx
        sy = h / 2 if sy is None else sy
        cx, cy = self.to_world(sx, sy)
        R = core.rectifier(img.shape[1], img.shape[0], core.HORIZON / img.shape[0] if core.HORIZON else None)
        small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)
        self._ghost = {
            "path": Path(path),
            "img": small,
            "R": R @ np.diag([2.0, 2.0, 1.0]),
            "w": img.shape[1],
            "h": img.shape[0],
            "cx": cx,
            "cy": cy,
            "drag": None,
        }
        self.canvas.focus_set()
        self.status.set(
            f"{path.name}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels)"
        )
        self.request_redraw()

    def _draw_ghost(self, img, w, h):
        g = self._ghost
        if not g:
            return
        V = np.array([[self.z, 0, -self.cx * self.z + w / 2], [0, self.z, -self.cy * self.z + h / 2], [0, 0, 1]])
        H = V @ np.array([[1, 0, g["cx"]], [0, 1, g["cy"]], [0, 0, 1]]) @ g["R"]
        warped = cv2.warpPerspective(g["img"], H, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
        mask = cv2.warpPerspective(np.full(g["img"].shape[:2], 255, np.uint8), H, (w, h), flags=cv2.INTER_NEAREST) > 0
        img[mask] = cv2.addWeighted(warped, 0.55, img, 0.45, 0)[mask]
        corners = core.persp(
            H, [[0, 0], [g["img"].shape[1], 0], [g["img"].shape[1], g["img"].shape[0]], [0, g["img"].shape[0]]]
        ).astype(np.int32)
        cv2.polylines(img, [corners], True, (0, 220, 255), 2, cv2.LINE_AA)
        c = corners.mean(axis=0).astype(int)
        put_text(img, "Enter / double-click: fit it here    Esc: cancel", (c[0] - 190, c[1]), (0, 220, 255), 0.55)

    def fit_ghost(self):
        g, self._ghost = self._ghost, None
        if not g:
            return
        self.request_redraw()
        if self.database() is None:
            return
        self._jobs.put(([g["path"]], ("drop", g["cx"], g["cy"])))

    def _cancel_lasso(self):
        self._lasso = None
        self.canvas.configure(cursor="fleur")
        self.status.set("lasso cancelled")
        self.request_redraw()

    def _cancel_bm_mode(self):
        if getattr(self, "_bm_mode", False):
            self._bm_mode = False
            self.canvas.configure(cursor="fleur")
            self.status.set("bookmark cancelled")

    def cancel_ghost(self):
        self._ghost = None
        self.status.set("placement cancelled")
        self.request_redraw()

    def on_drop(self, e):
        files = [Path(f) for f in self.root.tk.splitlist(e.data)]
        files = [f for f in files if core.is_screenshot(f)]
        if not files:
            self.status.set("drop screenshot image files (.png, .jpg)")
            return
        x = e.x_root - self.canvas.winfo_rootx()
        y = e.y_root - self.canvas.winfo_rooty()
        if len(files) > 1:  # several files: add them the normal way
            self.add_screenshots(files)
            return
        self.start_ghost(files[0], x, y)

    def ask_place(self):
        p = filedialog.askopenfilename(
            title="Screenshot to place by hand",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
            initialdir=self.settings.get("watch_folder") or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if p:
            self.start_ghost(Path(p))

    def save(self):
        if not self.atlas or not self.path:
            return
        if not self._lock.acquire(timeout=0.2):  # worker busy: it saves when it finishes
            self.root.after(1500, self.save)
            return
        try:
            self.atlas.save(self.path)
        finally:
            self._lock.release()
        self.status.set(f"saved {self.path}")

    def save_if_dirty(self):
        if self.atlas and self.path:
            self.save()

    def export_pngs(self):
        if not self.atlas or not self.path or not self.atlas.frames:
            return
        builder.export(self.atlas, self.path)
        self.log(f"wrote {self.path.stem}_composite.png and _network.png in {core.atlas_files(self.path).name}/")

    def refinalize(self):
        """full re-check, in the background (minutes on a large atlas)"""
        if not self.atlas or not self.atlas.frames:
            return
        self._jobs.put(([], "recheck_all"))

    def on_close(self):
        if self._busy and not messagebox.askyesno("Atlas viewer", "Screenshots are still being added. Quit anyway?"):
            return
        self.save_if_dirty()
        self.settings["geometry"] = self.root.geometry()
        self.settings["layers"] = {k: v.get() for k, v in self.layers.items()}
        self.settings["multi_only"] = self.multi_only.get()
        self.settings["icons_hidden"] = sorted(self.icon_hidden)
        save_settings(self.settings)
        self.root.destroy()

    # ------------------------------------------------------------------ adding screenshots
    def database(self, ask=True) -> Path | None:
        p = self.settings.get("database")
        if p and Path(p).exists():
            return Path(p)
        for cand in (rc_paths.DATABASE,):
            if cand.exists():
                return cand
        try:
            d = builder.default_database()
            if d.exists():
                return d
        except Exception:
            LOG.warning("detector default database not found", exc_info=True)
        return self.ask_database() if ask else None

    def ask_database(self) -> Path | None:
        p = filedialog.askopenfilename(
            title="Detector reference database (node_references_*.sqlite3)",
            filetypes=[("SQLite", "*.sqlite3"), ("All", "*.*")],
            initialdir=str(HERE),
        )
        if not p:
            return None
        self.settings["database"] = p
        save_settings(self.settings)
        return Path(p)

    def ask_add(self):
        if self._busy:
            return
        if not self.atlas or not self.path:
            self.new_atlas()
            if not self.atlas or not self.path:
                return
        paths = filedialog.askopenfilenames(
            title="Add atlas screenshots",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All", "*.*")],
            initialdir=self.settings.get("shots_dir", self._initial_dir()),
        )
        if paths:
            self.settings["shots_dir"] = str(Path(paths[0]).parent)
            self.add_screenshots([Path(p) for p in paths])

    def add_screenshots(self, paths: list[Path], sync: bool = False, mode: str = "manual"):
        if self.database() is None:
            return
        if mode == "manual":
            self._busy = True
            self.btn_add.state(["disabled"])
        if sync:
            self._run_job(list(paths), mode)
            self._drain_queue()
        else:
            self._jobs.put((list(paths), mode))

    # ------------------------------------------------------------------ background worker
    def _worker(self):
        while True:
            paths, mode = self._jobs.get()
            if mode == "watch":  # screenshots that arrived meanwhile: one batch, one re-check
                paths = list(paths)  # (v1.00 re-checked after every 2-3: ~45 s each)
                with self._jobs.mutex:
                    q = self._jobs.queue
                    while q and q[0][1] == "watch" and len(paths) < WATCH_BATCH:
                        paths += q.popleft()[0]
            try:
                self._run_job(paths, mode)
            except Exception as e:
                LOG.exception(f"adding failed ({mode}): {paths}")
                self._q.put(("log", f"adding failed: {e}"))
                self._q.put(("done", mode))

    def _run_job(self, paths, mode):
        if mode == "undo":
            self._run_undo()
            return
        retry = isinstance(mode, tuple) and mode[0] == "retry"
        if mode == "recheck_all":
            self._q.put(("progress", "re-checking the whole atlas"))
            with self._lock:
                self.atlas.rebuild_icons(builder.cached_frames(self.path))
                atlas_finalize.finalize(self.atlas, log=lambda t: self._q.put(("log", t)))
                self.atlas.save(self.path)
            self._q.put(("placed", ("recheck", 1, [], len(self.atlas.frames))))
            return
        db = self.database(ask=False)
        cache_dir = self.path.with_name(self.path.stem + "_frames")
        frames = []
        if len(paths) > 1:
            self._q.put(("progress", f"detecting {len(paths)} screenshots"))
            for p, err in builder.detect_uncached(paths, cache_dir, log=lambda t: self._q.put(("log", t))).items():
                LOG.warning(f"{Path(p).name}: detection failed in a worker: {err}")
        for i, p in enumerate(paths, 1):
            self._q.put(("progress", f"detecting {p.name} ({i}/{len(paths)})"))
            try:
                fr = builder.extract_frame(p, db, cache_dir)
                frames.append(fr)
                self._q.put(("log", f"{p.name}: {int(fr.usable.sum())} maps, {len(getattr(fr, 'icons', []))} icons"))
            except Exception as e:
                LOG.exception(f"{p.name}: detection failed")
                self._q.put(("log", f"{p.name}: detection failed: {e}"))
        self._q.put(("progress", "placing"))
        with self._lock:
            before = len(self.atlas.frames)
            snapshot = self._snapshot()
            if retry:  # waiting screenshots, searched again
                idx = mode[1]
                aside = [f for k, f in enumerate(self._pending_watch) if idx is not None and k not in idx]
                self._pending_watch = [f for k, f in enumerate(self._pending_watch) if idx is None or k in idx]
                added, refused = self._place_watched([])
                self._pending_watch += aside
                refused = [Path(f.path).name for f in self._pending_watch]
            elif isinstance(mode, tuple):  # dropped by hand near (x, y)
                added, refused = self._place_dropped(frames, mode[1], mode[2])
            elif mode == "manual":
                lines = []
                added, refused = builder.place_frames(self.atlas, frames, log=lines.append)
                for ln in lines:
                    if ln.strip().startswith(("MERGED", "first", "NOT ADDED", "final")) or "==" in ln:
                        self._q.put(("log", ln))
            else:
                added, refused = self._place_watched(frames)
            if added:
                new = self.atlas.frames[-added:]
                self._q.put(("added_names", ([f["name"] for f in new], snapshot)))
                self._q.put(("outline", [self._poly(f) for f in new]))
                if not self._paste_terrain(new):  # outside the map: rebuild it in the background
                    self._q.put(("rebuild_terrain", None))
                if mode != "manual":
                    self._q.put(("progress", "updating maps and paths around the new screenshot"))
                    builder.recheck(self.atlas, [f["name"] for f in new], log=lambda t: self._q.put(("log", t)))
                self._q.put(("progress", "saving"))
                self.atlas.save(self.path)
            else:  # nothing added: nothing to undo
                with contextlib.suppress(OSError):
                    snapshot.unlink()
        self._q.put(("placed", (mode, added, refused, before)))

    # ------------------------------------------------------------------ undo / recent additions
    def _undo_dir(self) -> Path:
        d = core.atlas_files(self.path) / (self.path.stem + "_undo")
        d.mkdir(exist_ok=True)
        return d

    def _snapshot(self) -> Path:
        """the atlas as it is before an add (worker thread, under the lock)"""
        f = self._undo_dir() / f"before_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.atlas.frames)}.json"
        self.atlas.save(f)
        return f

    def _remember_add(self, names, snapshot):
        self._undo.append({"file": snapshot, "names": names})
        while len(self._undo) > UNDO_KEEP:
            old = self._undo.pop(0)
            with contextlib.suppress(OSError):
                Path(old["file"]).unlink()
        self.recent += list(names)  # one screenshot per entry, in the order they were added
        self.recent = self.recent[-RECENT_KEEP:]
        self._recent_pick = None
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_list.delete(0, "end")
        for k, n in enumerate(reversed(self.recent)):  # newest first, line by line
            self.recent_list.insert("end", ("NEWEST  " if k == 0 else f"{k:>4}    ") + n)
        self.btn_undo.state(["!disabled"] if self._undo else ["disabled"])
        self.wait_list.delete(0, "end")
        tries = getattr(self, "_wait_tries", {})
        for fr in self._pending_watch:
            name = Path(fr.path).name
            n = tries.get(name, 0)
            self.wait_list.insert("end", f"{name}   - waiting, tried {n}x" if n else f"{name}   - queued")

    def goto_recent(self, index=None):
        if index is None:
            sel = self.recent_list.curselection()
            if not sel:
                return
            index = sel[0]
        flat = list(reversed(self.recent))
        if index >= len(flat):
            return
        f = next((f for f in self.atlas.frames if f["name"] == flat[index]), None)
        if f is None:
            return
        self._recent_pick = f["name"]  # outlined on the map until the next add
        c = self._poly(f).mean(axis=0)
        self.center_on(c[0], c[1], min_zoom=0.25)
        self.request_redraw()

    def undo_last(self):
        if not self._undo or self._busy:
            return
        names = self._undo[-1]["names"]
        if not messagebox.askyesno("Undo last add", "Remove the screenshot(s) added last?\n\n" + "\n".join(names)):
            return
        self._jobs.put(([], "undo"))

    def _run_undo(self):
        entry = self._undo.pop()
        self._q.put(("progress", "undoing the last add"))
        with self._lock:
            old = core.Atlas.load(entry["file"])
            keep_bookmarks = self.atlas.bookmarks
            for attr in ("nodes", "edges", "landmarks", "frames", "icons", "final"):
                setattr(self.atlas, attr, getattr(old, attr))
            self.atlas.bookmarks = keep_bookmarks
            self.atlas.save(self.path)
        with contextlib.suppress(OSError):
            Path(entry["file"]).unlink()
        self._q.put(("undone", entry["names"]))

    def retry_waiting(self, selected: bool = True):
        """search again for screenshots in the waiting queue (selected ones, or all), e.g. after others were
        placed; runs in the background like an auto-add"""
        if not self._pending_watch:
            self.status.set("nothing is waiting")
            return
        idx = None
        if selected:
            sel = self.wait_list.curselection()
            if not sel:
                self.status.set("select a waiting screenshot first (or use Retry all)")
                return
            idx = [k for k in sel if k < len(self._pending_watch)]
        self.status.set(f"retrying {len(idx) if idx else len(self._pending_watch)} waiting screenshot(s)")
        self._jobs.put(([], ("retry", idx)))

    def place_waiting(self):
        sel = self.wait_list.curselection()
        if not sel or sel[0] >= len(self._pending_watch):
            return
        fr = self._pending_watch.pop(sel[0])
        self._refresh_recent()
        self.start_ghost(Path(fr.path))

    def _draw_recent(self, img):
        """the newest screenshot outlined; the 4 before it fade out (5 in all, one screenshot each, not per
        batch); a screenshot clicked in the Recently added list is outlined too"""
        if not self.recent or not self.atlas or not self.layers["Recent additions"].get():
            return
        by_name = {f["name"]: f for f in self.atlas.frames}
        older = list(reversed(self.recent[:-1]))[: RECENT_FADE - 1]  # newest-but-one first
        for k, n in reversed(list(enumerate(older))):  # draw the oldest first
            alpha = 1 - (k + 1) / RECENT_FADE  # 0.8, 0.6, 0.4, 0.2: fades with age
            f = by_name.get(n)
            if f is None:
                continue
            layer = img.copy()
            pts = self.to_screen(self._poly(f)).astype(np.int32)
            cv2.polylines(layer, [pts], True, RECENT_COL, 2, cv2.LINE_AA)
            cv2.addWeighted(layer, alpha, img, 1 - alpha, 0, dst=img)
        marks = [(self.recent[-1], "newest: ", RECENT_COL)]
        pick = getattr(self, "_recent_pick", None)
        if pick and pick != self.recent[-1]:
            marks.append((pick, "", (255, 255, 255)))
        for n, label, col in marks:
            f = by_name.get(n)
            if f is None:
                continue
            pts = self.to_screen(self._poly(f)).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 0, 0), 6, cv2.LINE_AA)
            cv2.polylines(img, [pts], True, col, 3, cv2.LINE_AA)
            top = pts[np.argmin(pts[:, 1])]
            put_text(img, label + n[-10:], (top[0] + 6, top[1] + 22), col, 0.55)

    def _poly(self, f):
        H = core.screen_to_atlas(np.array(f["M"], float), self.atlas.frame_R(f))
        return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])

    def _place_dropped(self, frames, x, y):
        """a screenshot put roughly in place by hand: line it up near there"""
        added, refused = 0, []
        for fr in frames:
            name = Path(fr.path).name
            reg = self.atlas.place_near(fr, x, y)
            if reg.ok:
                d = np.hypot(*(reg.M[:, 2] - [x, y]))
                self.atlas.commit_frame(fr, reg)
                added += 1
                self._q.put(("log", f"{name}: lined up {d:.0f} units from where you put it ({reg.reason})"))
            elif "already" in reg.reason:
                self._q.put(("log", f"{name}: already in the atlas"))
            elif self._ask(
                f"{name} could not be lined up with the atlas near where you put it "
                f"({reg.reason}).\n\nAdd it exactly where you put it?"
            ):
                reg.ok, reg.reason = True, "placed by hand"
                self.atlas.commit_frame(fr, reg)
                added += 1
                self._q.put(("log", f"{name}: placed by hand where you put it"))
            else:
                refused.append(name)
        return added, refused

    def _concerns(self, frame, reg) -> list[str]:
        """reasons to ask before adding a watched screenshot (normally none)"""
        out = []
        few = reg.reason.startswith("terrain") or reg.inliers <= WEAK_INLIERS
        if few and reg.ncc < WEAK_NCC:
            maps = "no maps to compare" if reg.reason.startswith("terrain") else f"only {reg.inliers} maps agree"
            out.append(f"the match is weak ({maps}, terrain agreement {reg.ncc:.2f})")
        return out

    def _ask(self, question: str) -> bool:
        """ask on the main thread and wait for the answer (worker thread)"""
        self._q.put(("ask", question))
        return self._answer.get()

    def _place_one(self, fr):
        """anywhere in the atlas by its maps; terrain is compared with the newest screenshots first (the next
        one usually overlaps them). (v1.03: the "visible area first" search was dropped - placing is fast
        enough everywhere and it found nothing the full search missed)"""
        hints = [f["name"] for f in self.atlas.frames[-6:]][::-1]
        return self.atlas.add_frame(fr, hints=hints, commit=False)

    def _place_watched(self, frames):
        """one screenshot at a time, as they arrive; earlier ones that did not fit are retried"""
        added, todo = 0, self._pending_watch + frames
        self._pending_watch = []
        progress = True
        while progress and todo:
            progress, left = False, []
            for fr in todo:
                reg = self._place_one(fr)
                name = Path(fr.path).name
                if not reg.ok:
                    if "already in the atlas" not in reg.reason:
                        left.append(fr)
                        self._wait_tries = getattr(self, "_wait_tries", {})
                        self._wait_tries[name] = self._wait_tries.get(name, 0) + 1
                        self._q.put(("log", f"{name}: no place found yet ({reg.reason}); will retry"))
                    continue
                worry = self._concerns(fr, reg) if self.atlas.frames else []
                if worry:
                    q = (
                        f"{name} would be added, but " + "; and ".join(worry) + ".\n\n"
                        "Add it anyway? (No = leave it out; you can add it later with Add screenshots.)"
                    )
                    if not self._ask(q):
                        self._q.put(("log", f"{name}: left out by you"))
                        continue
                self.atlas.commit_frame(fr, reg)
                added += 1
                progress = True
                self._q.put(("log", f"{name}: added ({reg.inliers} maps agree, terrain {reg.ncc:.2f})"))
            todo = left
        self._pending_watch = todo
        return added, [Path(f.path).name for f in todo]

    def _after_placed(self, info):
        mode, added, refused, before = info
        self._set_progress(None)
        self._refresh_recent()
        if added:
            self.rebuild_model()  # the map image was already updated by pasting
            if before == 0:
                self.rebuild_terrain()
                self._fit_pending = True
                self.fit()
            self.request_redraw()
        if isinstance(mode, tuple):
            mode = "retry" if mode[0] == "retry" else "drop"
        if mode == "manual":
            msg = f"added {added} screenshot(s)"
            if refused:
                msg += f"; not placed (no overlap found): {', '.join(refused)}"
            self._busy = False
            self.btn_add.state(["!disabled"])
            if added:
                threading.Thread(target=self._export_quiet, daemon=True).start()
        elif mode == "drop":
            msg = "screenshot added" if added else "screenshot not added"
        elif mode == "recheck":
            msg = "whole atlas re-checked"
        elif mode == "retry":
            msg = f"retry: {added} waiting screenshot(s) placed" + (
                f"; {len(refused)} still waiting" if refused else ""
            )
        else:
            msg = f"auto-add: {added} new screenshot(s) added" + (
                f"; {len(refused)} NOT added yet (see Auto-add tab: place by hand)" if refused else ""
            )
            if refused and not added:
                self.tabs.select(self.tab_auto)
        self.status.set(msg)
        self.log(msg)

    def _export_quiet(self):
        try:
            with self._lock:
                builder.export(self.atlas, self.path)
        except Exception as e:
            LOG.exception("PNG export failed")
            self._q.put(("log", f"PNG export failed: {e}"))

    # ------------------------------------------------------------------ watched folder
    def _watch_dir(self) -> str:
        """the folder auto-add watches: one chosen by hand, otherwise the open atlas's own folder (where Steam
        should save the screenshots while you map: README)"""
        if self.settings.get("watch_folder"):
            return self.settings["watch_folder"]
        return str(self.path.parent) if getattr(self, "path", None) else ""

    def _show_watch_label(self):
        d = self._watch_dir()
        self.watch_label.set(
            ("watching: " if self.settings.get("watch_folder") else "watching this atlas's folder: ") + d
            if d
            else "open an atlas first"
        )

    def use_atlas_folder(self):
        """forget a hand-picked folder: watch the open atlas's own folder again"""
        self.settings.pop("watch_folder", None)
        save_settings(self.settings)
        self._show_watch_label()
        if self.watch_var.get():
            self.start_watch()

    def ask_watch_folder(self):
        d = filedialog.askdirectory(
            title="Folder your screenshots are saved to",
            initialdir=self.settings.get("watch_folder") or self.settings.get("shots_dir") or self._initial_dir(),
        )
        if d:
            self.settings["watch_folder"] = d
            self._show_watch_label()
            save_settings(self.settings)
            if self.watch_var.get():
                self.start_watch()

    def toggle_watch(self):
        if self.watch_var.get():
            if not self._watch_dir():
                self.status.set("open or create an atlas first")
                self.watch_var.set(False)
                return
            self.start_watch()
        else:
            self.settings["watch_on"] = False
            self.status.set("auto-add off")
        save_settings(self.settings)

    def _watch_files(self) -> dict[str, int]:
        folder = Path(self._watch_dir())
        out = {}
        with contextlib.suppress(OSError):
            for f in core.screenshots_in(folder):
                out[str(f.resolve())] = f.stat().st_size
        return out

    def start_watch(self, initial=False):
        """new files in the folder are added from now on - and screenshots already there that the atlas does not
        have yet (taken while the program was closed, or left over: user), from the atlas's first screenshot on,
        so a big screenshot folder doesn't pull in old shots of something else. An empty atlas takes them all."""
        if not self.atlas or not self.path:
            self.status.set("open or create an atlas first")
            self.watch_var.set(False)
            return
        self.settings["watch_on"] = True
        files = self._watch_files()
        self._watch_seen = {k: -1 for k in files}  # -1: handled (not watched for changes)
        todo = self._not_in_atlas(files)
        self._show_watch_label()
        self.status.set(f"watching {self._watch_dir()} for new screenshots")
        self.log(
            f"auto-add: watching {self._watch_dir()}"
            + (f"; {len(todo)} screenshot(s) there are not in the atlas yet: adding them" if todo else "")
        )
        if todo:
            self.add_screenshots(todo, mode="watch")
        if not getattr(self, "_watch_job", None):
            self._watch_job = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _not_in_atlas(self, files) -> list[Path]:
        """screenshots of the watched folder the atlas does not have (by file or by name), oldest first; only
        those from the atlas's first screenshot on (all of them for an empty atlas)"""
        have_path = {str(Path(f["path"]).resolve()) for f in self.atlas.frames}
        have_name = {f["name"] for f in self.atlas.frames}
        since = None
        for f in self.atlas.frames:
            try:
                t = Path(f["path"]).stat().st_mtime
            except OSError:
                continue
            since = t if since is None else min(since, t)
        out = []
        for f in files:
            p = Path(f)
            if f in have_path or p.stem in have_name:
                continue
            try:
                t = p.stat().st_mtime
            except OSError:
                continue
            if since is None or t >= since - 1:
                out.append((t, p))
        return [p for _t, p in sorted(out)]

    def _poll_watch(self):
        self._watch_job = None
        if not self.watch_var.get() or not self.atlas:
            return
        key = (id(self.atlas), len(self.atlas.frames))
        if getattr(self, "_known_key", None) != key:  # resolving ~800 paths every 2 s cost the window thread
            self._known = {str(Path(f["path"]).resolve()) for f in self.atlas.frames}
            self._known_key = key
        known = self._known
        ready = []
        for f, size in self._watch_files().items():
            prev = self._watch_seen.get(f)
            if prev == -1 or f in known:
                continue
            if prev is not None and prev == size and size > 0:  # finished writing: same size twice
                ready.append(Path(f))
                self._watch_seen[f] = -1
            else:
                self._watch_seen[f] = size
        if ready:
            ready.sort(key=lambda q: q.stat().st_mtime)
            self.log(f"auto-add: {len(ready)} new screenshot(s): {', '.join(q.name for q in ready)}")
            self.add_screenshots(ready, mode="watch")
        self._watch_job = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _drain_queue(self):
        while True:
            try:
                kind, val = self._q.get_nowait()
            except queue.Empty:
                return
            t_msg = time.perf_counter()
            try:
                self._handle(kind, val)
            finally:
                dt = time.perf_counter() - t_msg
                if PROFILE and dt > 0.2:
                    print(f"[viewer] slow on the window thread: {kind} took {dt:.2f}s", flush=True)

    def _handle(self, kind, val):
        if True:
            if kind == "status":
                self.status.set(val)
            elif kind == "hires":
                if val[0] == self.view_key(*self.canvas_size()):
                    self._hires = val
                    self.request_redraw()
            elif kind == "progress":
                self._set_progress(val)
            elif kind == "added_names":
                self._remember_add(*val)
            elif kind == "undone":
                self.recent = [n for n in self.recent if n not in set(val)]
                self._refresh_recent()
                self.rebuild_model()
                self._terrain = None
                self.rebuild_terrain()
                self._set_progress(None)
                self.status.set(f"undone: {', '.join(val)}")
                self.log(f"undone: {', '.join(val)}")
            elif kind == "outline":
                self._pending_outline = val
                self.request_redraw()
            elif kind == "rebuild_terrain":
                self.rebuild_terrain()
            elif kind == "terrain_img":
                job, canvas, weight, origin = val
                if job is None or job == self._terrain_job:
                    self._set_terrain(canvas, weight, origin)
                    self.footprints = [
                        (poly, (*poly.min(axis=0), *poly.max(axis=0)))
                        for poly in (self._poly(f) for f in self.atlas.frames)
                    ]
                    if self._progress and self._progress[0].startswith("building the map"):
                        self._set_progress(None)
            elif kind == "log":
                self.log(val)
            elif kind == "locks":
                self._lock_job = False
                if val and val[0] is self.atlas:
                    _atlas, names, found = val
                    self.atlas.locks = atlas_cities.merge_locks(self.atlas.locks, found)
                    self.atlas.lock_scanned = sorted(set(self.atlas.lock_scanned) | set(names))
                    if self.path:
                        self.atlas.save(self.path)
                    if found:
                        self.log(f"{len(self.atlas.locks)} locked Breach stronghold(s) (hand badge)")
                    self.rebuild_model()
                    self.request_redraw()
                    self.scan_locks()  # screenshots added meanwhile
            elif kind == "placed":
                self._after_placed(val)
            elif kind == "done":
                self.scan_locks()
                self._set_progress(None)
                self._busy = False
                self.btn_add.state(["!disabled"])
            elif kind == "ask":
                self._answer.put(messagebox.askyesno("Check this screenshot", val))

    def _poll_queue(self):
        self._drain_queue()
        self.root.after(150, self._poll_queue)

    # ------------------------------------------------------------------ view maths
    def to_screen(self, pts) -> np.ndarray:
        w, h = self.canvas_size()
        return (np.asarray(pts, float).reshape(-1, 2) - [self.cx, self.cy]) * self.z + [w / 2, h / 2]

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        w, h = self.canvas_size()
        return self.cx + (sx - w / 2) / self.z, self.cy + (sy - h / 2) / self.z

    def bounds(self):
        if self.pyr:
            x0, y0, s = self.t_origin
            h, w = self.pyr[0].shape[:2]
            return x0, y0, x0 + w / s, y0 + h / s
        if len(self.node_pts):
            (a, b), (c, d) = self.node_pts.min(0), self.node_pts.max(0)
            return a - 100, b - 100, c + 100, d + 100
        return -500, -300, 500, 300

    def fit(self):
        x0, y0, x1, y1 = self.bounds()
        w, h = self.canvas_size()
        if w > 50:
            self._fit_pending = False
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.z = max(0.02, min(w / max(1, x1 - x0), h / max(1, y1 - y0)) * 0.96)
        self.request_redraw()

    def zoom_limits(self):
        x0, y0, x1, y1 = self.bounds()
        w, h = self.canvas_size()
        fit = min(w / max(1, x1 - x0), h / max(1, y1 - y0))
        return fit * 0.3, 6.0

    def zoom_at(self, sx, sy, factor):
        wx, wy = self.to_world(sx, sy)
        lo, hi = self.zoom_limits()
        self.z = min(hi, max(lo, self.z * factor))
        w, h = self.canvas_size()
        self.cx, self.cy = wx - (sx - w / 2) / self.z, wy - (sy - h / 2) / self.z
        self.request_redraw()

    def pan_by(self, dx_screen, dy_screen):
        self.cx += dx_screen / self.z
        self.cy += dy_screen / self.z
        self.request_redraw()

    def center_on(self, x, y, min_zoom=1.0):
        self.cx, self.cy = x, y
        self.z = max(self.z, min_zoom)
        self.request_redraw()

    # ------------------------------------------------------------------ what is shown
    def _flags(self) -> tuple:
        """toggle states, read once per frame (Tk variable reads were ~30% of a frame)"""
        if getattr(self, "_frame_flags", None) is not None:
            return self._frame_flags
        return (
            self.layers["Doubtful"].get(),
            self.multi_only.get(),
            self.only_icon_maps.get(),
            float(self.style()["path_freq"]),
        )

    FAR_ZOOM = 0.12  # below this: maps / icons as stamped dots, no per-item drawing

    def shown_masks(self):
        """node_shown / path_shown for every map and path, kept until a filter or the atlas changes
        (re-checking ~18k maps and ~14k paths each frame made the zoomed-out view lag)"""
        key = (
            self._flags(),
            frozenset(self.icon_hidden),
            id(self.V["nodes"]),
            id(self.V["paths"]),
            len(self.icon_vars),
        )
        c = getattr(self, "_shown_cache", None)
        if c is None or c[0] != key:
            N = self.V["nodes"]
            nm = np.array([self.node_shown(n) for n in N], bool)
            multi = key[0][1]
            P = self.V["paths"]
            if P:
                A = np.array([q["a"] for q in P], int)
                B = np.array([q["b"] for q in P], int)
                pm = nm[A] & nm[B]
                if multi:
                    pm &= np.array([q["frames"] >= 2 or bool(q.get("abyss")) for q in P], bool)
                strong = np.array([q.get("seen_in", q["frames"]) >= 2 or bool(q.get("both_ends")) for q in P], bool)
                abyss = np.array([bool(q.get("abyss")) for q in P], bool)
            else:
                A = B = np.zeros(0, int)
                pm = strong = abyss = np.zeros(0, bool)
            col = np.array([NODE_COL.get(n["status"], (255, 255, 255)) for n in N], np.uint8).reshape(-1, 3)
            self._shown_cache = c = (key, nm, pm, A, B, strong, abyss, col)
        return c

    def node_shown(self, n) -> bool:
        st = n["status"]
        if st == "removed":
            return False
        doubtful, multi, only_icons = self._flags()[:3]
        if st == "doubtful" and not doubtful:
            return False
        if multi and n.get("seen", 1) < 2 and st != "icon":
            return False
        if only_icons:
            shown = {icon_name(r) for r in n.get("icons", [])} - self.icon_hidden
            if not shown and not (
                "MapBossSpecial" in n.get("icons", [])
                and any(icon.startswith("Deadly Map Boss") and icon not in self.icon_hidden for icon in self.icon_vars)
            ):
                return False
        return True

    def path_shown(self, p) -> bool:
        fl = self._flags()
        if fl[1] and p["frames"] < 2 and not p.get("abyss"):
            return False
        if fl[3] > 0 and not p.get("abyss") and p.get("seen_in", 0) < fl[3] * max(1, p.get("frames", 0)):
            return False  # drawn by too few of the screenshots that show both maps (user)
        N = self.V["nodes"]
        return self.node_shown(N[p["a"]]) and self.node_shown(N[p["b"]])

    def landmark_shown(self, lm) -> bool:
        if lm["status"].startswith("removed"):
            return self.layers["Removed"].get()
        if lm["kind"] in self.icon_hidden:
            return False
        if self.near_only() and lm["kind"] != "City":
            return False
        i = getattr(self, "_lm_index", {}).get(id(lm))
        t = getattr(self, "city_type", {}).get(i)
        return not t or f"{t[0]} city" not in self.icon_hidden

    # ------------------------------------------------------------------ mouse
    def on_press(self, e, mark=False):
        self.canvas.focus_set()
        if getattr(self, "_lasso", None) is not None:
            self._lasso = [(e.x, e.y)]
            return
        if getattr(self, "_bm_mode", False):
            self._bm_click(e.x, e.y)
            return
        if self._ghost:
            self._ghost["drag"] = (e.x, e.y, self._ghost["cx"], self._ghost["cy"])
            return
        self._drag = (e.x, e.y, self.cx, self.cy, False)

    def on_drag(self, e):
        if getattr(self, "_lasso", None):
            self._lasso.append((e.x, e.y))
            self.request_redraw()
            return
        if self._ghost and self._ghost.get("drag"):
            x0, y0, gx, gy = self._ghost["drag"]
            self._ghost["cx"], self._ghost["cy"] = gx + (e.x - x0) / self.z, gy + (e.y - y0) / self.z
            self.request_redraw()
            return
        if not self._drag:
            return
        x0, y0, cx0, cy0, moved = self._drag
        if not moved and abs(e.x - x0) + abs(e.y - y0) < 4:
            return
        self._drag = (x0, y0, cx0, cy0, True)
        self.cx = cx0 - (e.x - x0) / self.z
        self.cy = cy0 - (e.y - y0) / self.z
        self.request_redraw()

    def on_release(self, e):
        if getattr(self, "_lasso", None) is not None:
            poly, self._lasso = self._lasso, None
            self.canvas.configure(cursor="fleur")
            if len(poly) < 3:
                self.status.set("lasso cancelled")
                self.request_redraw()
                return
            sp = self.to_screen(self.node_pts) if len(self.node_pts) else np.zeros((0, 2))
            P = np.array(poly, np.float32).reshape(-1, 1, 2)
            ids = [
                i
                for i, q in enumerate(sp)
                if self.V["nodes"][i]["status"] != "removed"
                and cv2.pointPolygonTest(P, (float(q[0]), float(q[1])), False) >= 0
            ]
            if not ids:
                self.status.set("no maps inside the lasso")
                self.request_redraw()
                return
            self._lasso_ids = ids
            self._lasso_world = [self.to_world(x_, y_) for x_, y_ in poly]
            self.status.set(f"{len(ids)} maps inside: choose their biome")
            self.request_redraw()
            self._lasso_menu(ids, e.x, e.y)
            return
        if self._ghost:
            self._ghost["drag"] = None
            return
        if self._drag and not self._drag[4] and getattr(self, "_dbg_link", None) is not None:
            hit = self.pick(e.x, e.y)
            a, note = self._dbg_link
            self._dbg_link = None
            self._drag = None
            if hit and hit[0] == "node" and hit[1] != a:
                self._dbg_add("missing path", "there should be a path between these maps", note, maps=[a, hit[1]])
            else:
                self.status.set("debug: no second map clicked - link cancelled")
            return
        if self._drag and not self._drag[4]:
            hit = self.pick(e.x, e.y)
            self.select(hit)
            if hit:
                self.tabs.select(self.tab_find)  # the details ("Selected") are in the Find tab
        self._drag = None

    def on_double(self, e):
        if self._ghost:
            self.fit_ghost()
            return
        self.zoom_at(e.x, e.y, 2.0)

    def on_wheel(self, e):
        # some Tk builds give wheel x/y relative to the screen: derive canvas coords from root coords
        x = e.x_root - self.canvas.winfo_rootx()
        y = e.y_root - self.canvas.winfo_rooty()
        self.zoom_at(x, y, 1.2 ** max(-5.0, min(5.0, wheel_steps(e))))

    def on_motion(self, e):
        if not self.atlas:
            return
        wx, wy = self.to_world(e.x, e.y)
        st = self.V["stats"]
        extra = (
            (
                f"   |   {st.get('nodes_kept', 0)} nodes, {st.get('paths', 0)} paths "
                f"({st.get('paths_multi', 0)} seen in 2+ shots), {len(self.V['icons'])} icons"
            )
            if st
            else ""
        )
        self.status.set(f"x {wx:7.0f}  y {wy:7.0f}   zoom {self.z:.2f}   {len(self.V['frames'])} screenshots{extra}")

    def on_right(self, e):
        if not self.atlas:
            return
        wx, wy = self.to_world(e.x, e.y)
        hit = self.pick(e.x, e.y)
        m = tk.Menu(self.root, tearoff=0)
        if hit:
            self.select(hit)
            m.add_command(label="Bookmark this…", command=self.bookmark_selection)
        m.add_command(label="Add bookmark here…", command=lambda: self.add_bookmark_dialog(wx, wy))
        m.add_command(label="Screenshots of this spot", command=lambda: self.show_sources(wx, wy))
        if hit and hit[0] == "bookmark":
            m.add_separator()
            m.add_command(label="Delete bookmark", command=self.delete_bookmark)
        if hit and hit[0] == "landmark":
            lm = self.V["landmarks"][hit[1]]
            m.add_separator()
            m.add_cascade(label="Change to", menu=self._kind_menu(m, lm["x"], lm["y"], lm["kind"]))
            if lm["status"].startswith("removed"):
                m.add_command(label="Restore landmark", command=lambda: self.set_landmark(lm["x"], lm["y"], lm["kind"]))
            else:
                m.add_command(label="Delete landmark", command=lambda: self.set_landmark(lm["x"], lm["y"], ""))
        if hit and hit[0] == "node":
            nd = self.V["nodes"][hit[1]]
            m.add_separator()
            m.add_cascade(label="This map is a…", menu=self._kind_menu(m, nd["x"], nd["y"], on="map"))
        if hit and hit[0] == "landmark" and self.V["landmarks"][hit[1]]["kind"] == "City":
            i = hit[1]
            cur = self.city_type.get(i, ("", ""))
            tm = tk.Menu(m, tearoff=0)
            for t in atlas_cities.TYPES:
                tm.add_command(
                    label=("● " if cur == (t, "set") else "") + t, command=lambda t=t: self.set_city_type(i, t)
                )
            tm.add_separator()
            tm.add_command(
                label="Automatic" + (" ●" if cur[1] != "set" else ""), command=lambda: self.set_city_type(i, None)
            )
            m.add_separator()
            m.add_cascade(label="City type", menu=tm)
        if rc_paths.CHANNEL == "internal":
            m.add_separator()
            m.add_cascade(label="Debug", menu=self._dbg_menu(m, hit, wx, wy))
        m.tk_popup(e.x_root, e.y_root)

    # ------------------------------------------------------------------ debug marks (internal copy only)
    def _dbg_file(self) -> Path | None:
        return core.atlas_files(self.path) / "debug_marks.json" if self.path else None

    def _dbg_marks(self) -> list:
        fp = self._dbg_file()
        if fp is None:
            return []
        key = str(fp)
        if getattr(self, "_dbg_cache", (None,))[0] != key:
            try:
                marks = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
            except (OSError, ValueError):
                marks = []
            for i_, m_ in enumerate(marks, 1):  # a mark keeps its D number for good (user)
                m_.setdefault("id", i_)
            self._dbg_cache = (key, marks)
        return self._dbg_cache[1]

    def _dbg_save(self):
        fp = self._dbg_file()
        if fp is not None:
            fp.write_text(json.dumps(self._dbg_marks(), indent=1), encoding="utf-8")
        self._dbg_refresh()
        self.request_redraw()

    def _dbg_refresh(self):
        if not hasattr(self, "dbg_list"):
            return
        self.dbg_list.delete(0, "end")
        for k, mk in enumerate(self._dbg_marks(), 1):
            self.dbg_list.insert(
                "end",
                f"D{mk.get('id', k)}  {mk['kind']}: {mk['reason']}"
                + (f" - {mk['note']}" if mk.get("note") else "")
                + f"  ({mk['x']:.0f}, {mk['y']:.0f})",
            )
        fp = self._dbg_file()
        self.dbg_file_lab.configure(text=f"{len(self._dbg_marks())} mark(s) in {fp}" if fp else "")

    def _dbg_goto(self):
        sel = self.dbg_list.curselection()
        if sel:
            mk = self._dbg_marks()[sel[0]]
            self.center_on(mk["x"], mk["y"], min_zoom=1.0)

    def _dbg_delete(self):
        sel = self.dbg_list.curselection()
        if sel:
            del self._dbg_marks()[sel[0]]
            self._dbg_save()

    def _dbg_shots(self, x, y, k=5) -> list[str]:
        """the screenshots that show (x, y) best (nearest their centre)"""
        return [f["name"] for f, _x, _y in self.frames_at(x, y)[:k]]

    def _dbg_add(self, kind, reason, note, x=None, y=None, maps=(), path=None):
        from tkinter import simpledialog

        if note is None:
            note = simpledialog.askstring("Debug mark", f"{kind}: {reason}\nNote (optional):", parent=self.root)
            if note is None:  # cancelled
                return
        N = self.V["nodes"]
        mk = {
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
                k_: p.get(k_)
                for k_ in ("a", "b", "kind", "frames", "seen_in", "both_ends", "ends_in", "confirm", "deny", "dashes")
            }
            mk["path"]["ends"] = [
                [round(N[p["a"]]["x"], 1), round(N[p["a"]]["y"], 1)],
                [round(N[p["b"]]["x"], 1), round(N[p["b"]]["y"], 1)],
            ]
        if x is None:
            pts = [(m_["x"], m_["y"]) for m_ in mk["maps"]] or (
                [tuple(np.mean(mk["path"]["ends"], 0))] if path is not None else []
            )
            x, y = float(np.mean([q[0] for q in pts])), float(np.mean([q[1] for q in pts]))
        mk["x"], mk["y"] = round(float(x), 1), round(float(y), 1)
        mk["screenshots"] = self._dbg_shots(mk["x"], mk["y"])
        marks = self._dbg_marks()
        mk["id"] = max([m_.get("id", i_ + 1) for i_, m_ in enumerate(marks)] + [0]) + 1  # never reused
        marks.append(mk)
        self._dbg_save()
        self.status.set(f"debug mark saved: {kind} ({reason})")

    def _dbg_menu(self, parent, hit, wx, wy):
        dm = tk.Menu(parent, tearoff=0)
        if hit and hit[0] in ("node", "icon"):
            i = hit[1] if hit[0] == "node" else getattr(self, "icon_node", {}).get(hit[1])
            if i is not None:
                for reason in (
                    "not a map (no base there)",
                    "map is in the wrong spot",
                    "duplicate of a map next to it",
                    "wrong paths at this map",
                    "other",
                ):
                    dm.add_command(
                        label=f"Map: {reason}…", command=lambda r=reason: self._dbg_add("wrong map", r, None, maps=[i])
                    )
                dm.add_separator()

                def start_link():
                    self._dbg_link = (i, "")
                    self.status.set("debug: now click the map this one should have a path to")

                dm.add_command(label="Missing path from here: click the other map", command=start_link)
                dm.add_separator()
        if hit and hit[0] == "path":
            for reason in (
                "no path here",
                "wrong end map",
                "crosses / runs through a structure",
                "wrong shape",
                "other",
            ):
                dm.add_command(
                    label=f"Path: {reason}…", command=lambda r=reason: self._dbg_add("wrong path", r, None, path=hit[1])
                )
            dm.add_separator()
        for reason in ("visible map base", "hidden map (paths lead in)", "other"):
            dm.add_command(
                label=f"Add a map here: {reason}…",
                command=lambda r=reason: self._dbg_add("missing map", r, None, x=wx, y=wy),
            )
        return dm

    def _dbg_draw(self, img):
        col = (255, 0, 255)
        for k, mk in enumerate(self._dbg_marks(), 1):
            p = self.to_screen([[mk["x"], mk["y"]]])[0]
            x, y = int(p[0]), int(p[1])
            if mk["kind"] in ("missing path", "wrong path") and (len(mk["maps"]) == 2 or mk.get("path")):
                ends = mk["path"]["ends"] if mk.get("path") else [[m_["x"], m_["y"]] for m_ in mk["maps"]]
                q = self.to_screen(ends).astype(int)
                if mk["kind"] == "missing path":
                    draw_paths(img, [q], col, 2, "dotted")
                else:
                    cv2.line(img, tuple(q[0]), tuple(q[1]), col, 2, cv2.LINE_AA)
                    cv2.drawMarker(img, (x, y), col, cv2.MARKER_TILTED_CROSS, 18, 2)
            elif mk["kind"] == "missing map":
                cv2.drawMarker(img, (x, y), col, cv2.MARKER_CROSS, 26, 2)
            else:
                cv2.circle(img, (x, y), 18, col, 2, cv2.LINE_AA)
                cv2.drawMarker(img, (x, y), col, cv2.MARKER_TILTED_CROSS, 16, 2)
            put_text(img, f"D{mk.get('id', k)}", (x + 14, y - 12), col, 0.45)

    def pick(self, sx, sy) -> tuple[str, int] | None:
        if not self.atlas:
            return None
        best, bd = None, 1e9
        if self.layers["Bookmarks"].get():
            for i, b in enumerate(self.atlas.bookmarks):
                if not self.bookmark_shown(b):
                    continue
                p = self.to_screen([[b["x"], b["y"]]])[0]
                d = math.hypot(p[0] - sx, p[1] - sy + 14)
                if d < 16 and d < bd:
                    best, bd = ("bookmark", i), d
        if best:
            return best
        if self.layers["Icons"].get() and len(self.icon_pts):
            sp = self.to_screen(self.icon_pts)
            d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
            i = int(np.argmin(d))
            if d[i] < max(9, 15 * self.z) and d[i] < bd:
                best, bd = ("icon", i), d[i]
        if self.layers["Landmarks"].get():
            for i, lm in enumerate(self.V["landmarks"]):
                if not self.landmark_shown(lm):
                    continue
                p = self.to_screen([[lm["x"], lm["y"]]])[0]
                hw, top, bot = self.landmark_box()
                if p[0] - hw <= sx <= p[0] + hw and p[1] - top <= sy <= p[1] + bot:
                    d = math.hypot(p[0] - sx, p[1] - top / 2 - sy)
                    if d < bd:
                        best, bd = ("landmark", i), d
        if len(self.node_pts):
            # maps are clickable even when hidden (layer off, filtered out): a click right on a map's centre
            # selects the map, also inside a landmark's box (only removed maps are never picked)
            sp = self.to_screen(self.node_pts)
            d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
            for i in np.argsort(d)[:5]:
                if self.V["nodes"][i]["status"] == "removed":
                    continue
                if d[i] < max(10, self.node_radius() + 5) and (d[i] < bd or best and best[0] == "landmark"):
                    best, bd = ("node", int(i)), d[i]
                break
        if best is None and self.layers["Paths"].get() and self.V["paths"]:
            best = self._pick_path(sx, sy)
        if best is None and self.layers["City & stronghold biomes"].get() and getattr(self, "potential", None):
            ids = [v for v, (lab, _st) in self.potential.items() if self.potential_kind(lab) not in self.icon_hidden]
            if ids:  # anywhere inside a biome circle selects its map
                sp = self.to_screen(self.node_pts[ids])
                d = np.hypot(sp[:, 0] - sx, sp[:, 1] - sy)
                k = int(np.argmin(d))
                if d[k] <= max(4, int(44 * self.z)):
                    best = ("node", int(ids[k]))
        return best

    def _path_pieces(self, ST, th, c_multi, c_single) -> dict:
        """{(colour, width): (all piece points in atlas units, start index of each piece)} for the shown paths,
        cut into dashes / dots for the style; cached until paths, filters, style or zoom change"""
        z = round(self.z, 3)
        key = (
            id(self.V["paths"]),
            id(self.V["nodes"]),
            self._flags(),
            frozenset(self.icon_hidden),
            ST["path_style"],
            th,
            c_multi,
            c_single,
            z if ST["path_style"] != "solid" else 0,
        )
        c = getattr(self, "_pp_cache", None)
        if c is not None and c[0] == key:
            return c[1]
        N = self.V["nodes"]
        groups: dict = {}
        style = ST["path_style"]
        on = (max(6.0, 5.0 * th) if style == "dashed" else 0.6) / max(z, 1e-3)
        period = on + (max(4.0, 3.0 * th) if style == "dashed" else max(5.0, 4.0 * th)) / max(z, 1e-3)
        for p in self.V["paths"]:
            if not self.path_shown(p):
                continue
            strong = p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends")
            col = PATH_ABYSS if p.get("abyss") else c_multi if strong else c_single
            wdt = th + (1 if p.get("abyss") else 0)
            L = np.array(p.get("line") or [[N[p["a"]]["x"], N[p["a"]]["y"]], [N[p["b"]]["x"], N[p["b"]]["y"]]], float)
            L[0] = (N[p["a"]]["x"], N[p["a"]]["y"])
            L[-1] = (N[p["b"]]["x"], N[p["b"]]["y"])
            g = groups.setdefault((col, wdt if style != "dotted" else max(2, 2 * wdt)), [])
            if style == "solid":
                g.append(L)
                continue
            seg = np.hypot(*np.diff(L, axis=0).T)
            cum = np.concatenate([[0], np.cumsum(seg)])
            if cum[-1] < 1e-6:
                continue
            t0 = np.arange(0, cum[-1], period)
            t1 = np.minimum(t0 + on, cum[-1])
            a_ = np.column_stack([np.interp(t0, cum, L[:, 0]), np.interp(t0, cum, L[:, 1])])
            b_ = np.column_stack([np.interp(t1, cum, L[:, 0]), np.interp(t1, cum, L[:, 1])])
            g.extend(np.stack([a_, b_], 1))
        out = {}
        for k, pieces in groups.items():
            if not pieces:
                continue
            lens = np.array([len(x) for x in pieces])
            out[k] = (np.vstack(pieces), np.concatenate([[0], np.cumsum(lens)[:-1]]))
        self._pp_cache = (key, out)
        return out

    def _path_atlas_line(self, p) -> np.ndarray:
        """a path's line in atlas units with its ends on its maps, exactly as it is drawn"""
        N = self.V["nodes"]
        L = np.array(p.get("line") or [[N[p["a"]]["x"], N[p["a"]]["y"]], [N[p["b"]]["x"], N[p["b"]]["y"]]], float)
        L[0] = (N[p["a"]]["x"], N[p["a"]]["y"])
        L[-1] = (N[p["b"]]["x"], N[p["b"]]["y"])
        return L

    def _pick_path(self, sx, sy):
        """the path within a few px of the click (clicks right on a map pick the map first)"""
        q = np.array([sx, sy], float)
        best, bd = None, 7.0
        for k, p in enumerate(self.V["paths"]):
            if not self.path_shown(p):
                continue
            L = self.to_screen(self._path_atlas_line(p))
            lo, hi = L.min(axis=0) - bd, L.max(axis=0) + bd
            if not (lo[0] <= sx <= hi[0] and lo[1] <= sy <= hi[1]):
                continue
            a, b = L[:-1], L[1:]
            ab = b - a
            t = np.clip(((q - a) * ab).sum(1) / np.maximum(1e-9, (ab * ab).sum(1)), 0, 1)
            d = float(np.min(np.hypot(*(a + t[:, None] * ab - q).T)))
            if d < bd:
                best, bd = ("path", k), d
        return best

    # ------------------------------------------------------------------ selection / info
    def select(self, item):
        self.sel = item
        self.show_info()
        self.request_redraw()

    def item_pos(self, item) -> tuple[float, float]:
        kind, i = item
        if kind == "path":
            p = self.V["paths"][i]
            a, b = self.V["nodes"][p["a"]], self.V["nodes"][p["b"]]
            return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        src = {"node": self.V["nodes"], "landmark": self.V["landmarks"], "icon": self.V["icons"]}.get(kind)
        n = src[i] if src is not None else self.atlas.bookmarks[i]
        return float(n["x"]), float(n["y"])

    def sel_valid(self) -> bool:
        """drop a selection whose item no longer exists (deleted bookmark, rebuilt atlas)"""
        if not self.sel:
            return False
        kind, i = self.sel
        size = {
            "node": len(self.V["nodes"]),
            "landmark": len(self.V["landmarks"]),
            "icon": len(self.V["icons"]),
            "path": len(self.V["paths"]),
            "bookmark": len(self.atlas.bookmarks) if self.atlas else 0,
        }.get(kind, 0)
        if not 0 <= i < size:
            self.sel = None
            return False
        return True

    def show_info(self):
        lines = []
        self.sel_valid()
        if self.sel and self.atlas:
            kind, i = self.sel
            if kind == "node":
                n = self.V["nodes"][i]
                deg = [p for p in self.V["paths"] if i in (p["a"], p["b"])]
                multi = sum(p.get("seen_in", p["frames"]) >= 2 or p.get("both_ends", False) for p in deg)
                icons = ", ".join(icon_name(k) for k in n.get("icons", []))
                lines += [
                    f"Map #{i}" + (f": {icons}" if icons else ""),
                    f"found in {n['seen']} of {n['could']} screenshot(s) that show it",
                    f"{len(deg)} path(s), {multi} confirmed (traced from both ends or in 2+ shots)",
                ]
                st = {
                    "confirmed": "confirmed by several screenshots",
                    "icon": "confirmed by its icon",
                    "single": "only one screenshot shows it",
                    "disputed": "1 of 2 screenshots, kept: a path reaches it",
                    "doubtful": "doubtful: one screenshot, no icon, no path",
                }.get(n["status"], n["status"])
                lines.append(st)
                if n.get("abyss"):
                    lines.append(
                        {"start": "Abyss chain: first map", "final": "Abyss chain: final map", "chain": "Abyss chain"}[
                            n["abyss"]
                        ]
                    )
                if n.get("tower"):
                    lines.append("Tower foot (path endpoint)")
                if i in self.potential:
                    lines.append(self.potential_text(i))
                if self.near_city_text(i):
                    lines.append(self.near_city_text(i))
                if n.get("origin") == "from icon":
                    lines.append("map base not detected; placed under its icon")
            elif kind == "path":
                p = self.V["paths"][i]
                a, b = self.V["nodes"][p["a"]], self.V["nodes"][p["b"]]
                lines += [
                    f"Path: map #{p['a']} ({a['x']:.0f}, {a['y']:.0f}) - map #{p['b']} ({b['x']:.0f}, {b['y']:.0f})",
                    {
                        "traced": "traced along its dashes",
                        "straight": "straight link (gold along it, not traced)",
                        "abyss": "Abyss chain link",
                    }.get(p.get("kind"), p.get("kind", "")),
                    f"drawn by {p.get('seen_in', 0)} of {p.get('frames', 0)} screenshot(s) that show both maps",
                ]
                if "ends_in" in p:
                    lines.append(
                        f"traced end to end in {p['ends_in']}, confirmed by {p['confirm']} more, "
                        f"denied by {p['deny']}; {p['dashes']} dashes on its clearest trace"
                    )
            elif kind == "landmark":
                lm = self.V["landmarks"][i]
                lines += [
                    lm["kind"],
                    f"found in {lm['n']} of {lm.get('could', lm['n'])} screenshot(s)",
                    f"confidence {lm['conf']:.2f}, detected by {lm.get('source', '')}",
                ]
                if i in self.city_type:
                    t, how = self.city_type[i]
                    lines.insert(0, f"{t} city")
                    lines.append(
                        {
                            "set": "type set by hand (right-click to change)",
                            "trio": "type from its trio: the cities next to it are the other two types",
                            "look-alike": "type guessed by look; right-click to set it",
                        }[how]
                    )
                if i in getattr(self, "locked_ids", ()):
                    lines.insert(0, "Locked Breach stronghold")
                    lines.append("locked (hand badge): only its ground shows, no maps yet")
                if lm.get("beam"):
                    lines.append(f"{lm['kind']} because: {lm['beam']}")
                if lm["status"] != "kept":
                    lines.append(lm["status"])
            elif kind == "icon":
                ic = self.V["icons"][i]
                lines += [
                    icon_label(ic),
                    f"seen in {ic['n']} screenshot(s), match {ic['score']:.2f}",
                    f"raw name: {ic['name']}",
                ]
                v = getattr(self, "icon_node", {}).get(i)
                if v is not None and v in getattr(self, "blocked", {}):
                    lines.append(f"not a city map ({self.blocked[v]})")
                elif self.near_city_text(v):
                    lines.append(self.near_city_text(v))
            else:
                b = self.atlas.bookmarks[i]
                lines += [f"★ {b['name']}", f"group: {self.bm_group(b)}"]
                if b.get("note"):
                    lines.append(b["note"])
            x, y = self.item_pos(self.sel)
            lines.append(f"position {x:.0f}, {y:.0f}")
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(lines) if lines else "Click a map, icon, landmark or bookmark.")
        self.info.configure(state="disabled")

    # ------------------------------------------------------------------ search
    def _item_node(self, item):
        kind, i = item
        if kind == "node":
            return i
        if kind == "icon":
            return getattr(self, "icon_node", {}).get(i)
        return None

    def _fill_results(self, labels):
        if getattr(self, "only_near_city", None) is not None and self.only_near_city.get():
            keep = [k for k, it in enumerate(self.hits) if self.near_city_text(self._item_node(it))]
            self.hits = [self.hits[k] for k in keep]
            labels = [labels[k] for k in keep]
        for k, it in enumerate(self.hits):
            t = getattr(self, "near_city", {}).get(self._item_node(it))
            if t and it[0] == "icon":
                labels[k] += f"   ⌂ {t[0]}" + ("" if t[1] == 0 else " +1")
        for k, (item, s_) in enumerate(zip(self.hits, labels, strict=False)):
            if item[0] != "bookmark" and self.bookmark_at(*self.item_pos(item)) is not None:
                s_ = "★ " + s_
            labels[k] = s_
        self.results.delete(0, "end")
        for s_ in labels:
            self.results.insert("end", s_)
        self.request_redraw()

    def run_search(self):
        self._last_list = None
        q = self.query.get().strip().lower()
        self.hits = []
        self.results.delete(0, "end")
        if hasattr(self, "type_counts") and self.atlas:
            self.rebuild_icon_filter()
        if not self.atlas or not q:
            self.request_redraw()
            return
        import re

        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*", q)
        if m:  # coordinates (user: no more hot-or-cold panning)
            x, y = float(m.group(1)), float(m.group(2))
            self._goto = (x, y)
            self.center_on(x, y, min_zoom=1.0)
            self.status.set(f"centred on {x:.0f}, {y:.0f} (marked with a cross)")
            self.request_redraw()
            return
        labels = []
        for i, b in enumerate(self.atlas.bookmarks):
            if q in f"{b['name']} {self.bm_group(b)} {b.get('note', '')}".lower():
                self.hits.append(("bookmark", i))
                labels.append(f"[bookmark] {b['name']}  ({self.bm_group(b)})")
        for i, lm in enumerate(self.V["landmarks"]):
            if q in self.lm_name(i).lower() and not lm["status"].startswith("removed"):
                self.hits.append(("landmark", i))
                labels.append(f"{self.lm_name(i)}  (seen {lm['n']}x)")
        for i, ic in enumerate(self.V["icons"]):
            nice = icon_label(ic)
            if q in nice.lower() or q in icon_aliases(ic["name"]):
                self.hits.append(("icon", i))
                labels.append(f"{nice}  (seen {ic['n']}x)")
        if len(q) >= 4 and q in "potential city map potential stronghold map":
            for v, (lab, st) in self.potential.items():
                if st and q in self.potential_kind(lab).lower():
                    self.hits.append(("node", v))
                    labels.append(self.potential_text(v))
        m = re.fullmatch(r"#(\d+)", q)
        if m and int(m.group(1)) < len(self.V["nodes"]):
            self.hits.append(("node", int(m.group(1))))
            labels.append(f"Map #{m.group(1)}")
        self._fill_results(labels)
        self.status.set(f'{len(labels)} match(es) for "{q}"')

    def goto_result(self, box: tk.Listbox, index: list):
        sel = box.curselection()
        if not sel or sel[0] >= len(index):
            return
        item = index[sel[0]]
        x, y = self.item_pos(item)
        self.center_on(x, y, min_zoom=1.0)
        self.select(item)

    # ------------------------------------------------------------------ bookmarks
    @staticmethod
    def bm_group(b) -> str:
        return b.get("group") or b.get("category") or "Other"

    def groups(self) -> list[str]:
        g = {self.bm_group(b) for b in (self.atlas.bookmarks if self.atlas else [])} | self._extra_groups
        return sorted(g, key=str.lower)

    def bookmark_at(self, x, y) -> int | None:
        """index of a bookmark already on this spot (same map / icon), else None"""
        best, bd = None, SAME_SPOT
        for i, b in enumerate(self.atlas.bookmarks if self.atlas else []):
            d = math.hypot(b["x"] - x, b["y"] - y)
            if d < bd:
                best, bd = i, d
        return best

    def refresh_bookmarks(self):
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
        key = str(self.path) if self.path else ""
        return set(self.settings.get("hidden_groups", {}).get(key, []))

    def toggle_group(self, g):
        key = str(self.path) if self.path else ""
        hg = self.settings.setdefault("hidden_groups", {})
        cur = set(hg.get(key, []))
        cur.symmetric_difference_update({g})
        hg[key] = sorted(cur)
        save_settings(self.settings)
        self.refresh_bookmarks()
        self.request_redraw()

    def on_bm_tree_click(self, e):
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
        return self.bm_group(b) not in self.hidden_groups() and not b.get("hidden")

    def selected_bookmarks(self) -> list[int]:
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
        sel = self.bm_tree.selection()
        if len(sel) == 1 and sel[0].startswith("bm::"):
            i = int(sel[0][4:])
            b = self.atlas.bookmarks[i]
            self.center_on(b["x"], b["y"], min_zoom=max(self.z, 0.6))
            self.sel = ("bookmark", i)
            self.show_info()
            self.request_redraw()

    def new_group(self):
        from tkinter import simpledialog

        name = simpledialog.askstring("New group", "Group name:", parent=self.root)
        if name and name.strip():
            self._extra_groups.add(name.strip())
            self.refresh_bookmarks()

    def rename_group(self):
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
        if not self.atlas:
            return
        self._bm_mode = True
        self.canvas.configure(cursor="crosshair")
        self.status.set(
            "click the map to bookmark: on a map or icon to bookmark it, anywhere else to mark that spot (Esc cancels)"
        )

    def _bm_click(self, sx, sy):
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
        if self.sel:
            self.show_sources(*self.item_pos(self.sel))

    def show_sources(self, x, y):
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
            sel = lb.curselection()
            if not sel:
                return
            f, px, py = found[sel[0]]
            if not Path(f["path"]).exists():
                cv.delete("all")
                cv.create_text(20, 20, anchor="nw", fill="white", text=f"missing file: {f['path']}")
                return
            img = cv2.imdecode(np.fromfile(f["path"], np.uint8), cv2.IMREAD_COLOR)
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

    # ------------------------------------------------------------------ drawing
    def node_radius(self) -> float:
        return float(min(13, max(2, 8 * self.z))) * float(self.style()["map_size"])

    def _map_pic(self):
        if getattr(self, "_mpic", None) is None:
            fp = rc_paths.ref("map_node_icon.webp")
            self._mpic = Image.open(fp).convert("RGBA") if fp.exists() else icon_thumb("Unidentified", 48)
        return self._mpic

    def landmark_box(self):
        """half-width, height above, depth below the landmark point, in screen px (scales with zoom)"""
        s = max(0.12, self.z)
        return max(5, 30 * s), max(8, 60 * s), max(2, 10 * s)

    def request_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.root.after(8, self._redraw)

    def _redraw(self):
        self._redraw_pending = False
        w, h = self.canvas_size()
        t0 = time.perf_counter()
        img = self.render(w, h)
        self.photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        self.canvas.itemconfigure(self.img_item, image=self.photo)
        self.last_render_ms = (time.perf_counter() - t0) * 1000
        if PROFILE and self.last_render_ms > 200:
            print(f"[viewer] slow on the window thread: redraw took {self.last_render_ms / 1000:.2f}s", flush=True)

    def render(self, w: int, h: int) -> np.ndarray:
        img = np.empty((h, w, 3), np.uint8)
        img[:] = BG
        if not self.atlas:
            put_text(
                img, "File > New atlas, then Add screenshots   |   File > Open atlas", (30, 40), (220, 220, 220), 0.7
            )
            return img
        L = {k: v.get() for k, v in self.layers.items()}
        self._frame_flags = None
        self._frame_flags = self._flags()
        try:
            return self._render(img, w, h, L)
        finally:
            self._frame_flags = None

    def _render(self, img, w, h, L):
        z = self.z
        overview = z < 0.45  # zoomed out: dots, no small labels
        if L["Terrain"] and self.pyr:
            x0, y0, s0 = self.t_origin
            lvl = int(min(len(self.pyr) - 1, max(0, math.floor(math.log2(max(1e-6, s0 / z))))))
            sl = s0 / (2**lvl)
            a = z / sl
            A = np.array([[a, 0, (x0 - self.cx) * z + w / 2], [0, a, (y0 - self.cy) * z + h / 2]])
            cv2.warpAffine(self.pyr[lvl], A, (w, h), dst=img, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
            if self.hires_wanted():
                if self._hires and self._hires[0] == self.view_key(w, h):
                    img[self._hires[2]] = self._hires[1][self._hires[2]]  # screenshot pixels, 1:1
                else:
                    self._schedule_hires()  # sharpen once the view settles
            if L["Paths"] or L["Nodes"]:
                # dim the ground under the lines; a smooth slope (a step at the overview switch
                # made the map jump ~20% darker between zoom 0.50 and 0.42)
                img = cv2.convertScaleAbs(img, alpha=float(np.clip(0.72 + 0.16 * (z - 0.2), 0.72, 0.8)))
        N = self.V["nodes"]
        sp = self.to_screen(self.node_pts) if len(self.node_pts) else np.zeros((0, 2))
        vis = ((sp[:, 0] > -80) & (sp[:, 0] < w + 80) & (sp[:, 1] > -80) & (sp[:, 1] < h + 80)) if len(sp) else []
        th = 1 if z < 0.7 else 2
        if L["City & stronghold biomes"] and self.potential and len(sp):
            tint = img.copy()
            rad = max(4, int(44 * z))
            rings = []
            for i, (lab, _st) in self.potential.items():
                if (
                    not vis[i]
                    or self.potential_kind(lab) in self.icon_hidden
                    or (self.near_only() and "city" not in lab.lower())
                ):
                    continue
                cols = [
                    CITY_COL.get(part.replace(" city", "").replace(" stronghold", ""), (255, 200, 80))
                    for part in lab.split(" / ")
                ]
                pt = (int(sp[i, 0]), int(sp[i, 1]))
                cv2.circle(tint, pt, rad, cols[0], -1, cv2.LINE_AA)
                rings.append((pt, cols[-1]))
            img = cv2.addWeighted(tint, 0.38, img, 0.62, 0)
            for pt, col in rings:
                cv2.circle(img, pt, rad, col, 1 if overview else 2, cv2.LINE_AA)
        ST = self.style()
        c_multi = hex_bgr(ST["path_col"], PATH_MULTI)
        c_single = hex_bgr(ST["path_col1"], PATH_SINGLE)
        c_map = hex_bgr(ST["map_col"], None)
        pth = int(ST["path_width"]) or th
        if L["Paths"] and overview and len(sp):
            # zoomed out: one batched draw call per colour (14k paths on a large atlas), masks cached
            _k, nm, pm, A, B, strong, abyss, _c = self.shown_masks()
            keep = pm & (vis[A] | vis[B]) if len(A) else pm
            for col, sel in (
                (PATH_ABYSS, keep & abyss),
                (c_multi, keep & ~abyss & strong),
                (c_single, keep & ~abyss & ~strong),
            ):
                if sel.any():
                    segs = np.stack([sp[A[sel]], sp[B[sel]]], 1).astype(np.int32)
                    cv2.polylines(img, list(segs), False, col, 1, cv2.LINE_8)
        elif L["Paths"]:
            # pieces (whole lines, dashes or dots) are cut once in atlas units and cached; a pan only moves them
            groups = self._path_pieces(ST, pth, c_multi, c_single)
            aa = cv2.LINE_AA if z >= 0.8 else cv2.LINE_8
            for (col, wdt), (pts_a, starts) in groups.items():
                q = self.to_screen(pts_a)
                inside = (q[:, 0] > -50) & (q[:, 0] < w + 50) & (q[:, 1] > -50) & (q[:, 1] < h + 50)
                keep = np.logical_or.reduceat(inside, starts) if len(starts) else np.zeros(0, bool)
                ends = np.append(starts[1:], len(q))
                pieces = [q[a:b].astype(np.int32) for a, b, k in zip(starts, ends, keep, strict=False) if k]
                if pieces:
                    cv2.polylines(img, pieces, False, col, wdt, aa)
            if self.sel and self.sel[0] == "path" and self.sel_valid():
                p = self.V["paths"][self.sel[1]]
                line = self.to_screen(self._path_atlas_line(p))
                cv2.polylines(img, [line.astype(np.int32)], False, (0, 0, 0), pth + 6, cv2.LINE_AA)
                cv2.polylines(img, [line.astype(np.int32)], False, SELECT_COL, pth + 3, cv2.LINE_AA)
        r = self.node_radius()
        hit_nodes = {i for k, i in self.hits if k == "node"}
        far = z < self.FAR_ZOOM
        if L["Nodes"] and len(sp) and far:
            _k, nm, _pm, _A, _B, _s, _a, ncol = self.shown_masks()
            sel = np.nonzero(vis & nm)[0]
            X = np.round(sp[sel, 0]).astype(int)
            Y = np.round(sp[sel, 1]).astype(int)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xx, yy = X + dx, Y + dy
                    ok = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
                    img[yy[ok], xx[ok]] = ncol[sel[ok]]
            for i in hit_nodes:
                if i < len(sp) and vis[i]:
                    cv2.circle(img, (int(sp[i, 0]), int(sp[i, 1])), 8, HIT_COL, 2, cv2.LINE_AA)
        elif L["Nodes"] and len(sp):
            _k, nm, *_ = self.shown_masks()
            for i in np.nonzero(vis)[0]:
                n = N[i]
                pt = (int(sp[i, 0]), int(sp[i, 1]))
                if n["status"] == "removed":
                    if L["Removed"] and not n["why"].startswith("joined"):
                        cv2.drawMarker(img, pt, REMOVED_COL, cv2.MARKER_TILTED_CROSS, max(6, int(2 * r)), 2)
                    continue
                if not nm[i]:
                    continue
                col = NODE_COL.get(n["status"], (255, 255, 255))
                if c_map is not None and n["status"] in ("confirmed", "icon"):
                    col = c_map
                if ST["map_style"] == "hidden":
                    pass
                elif overview:
                    if ST["map_style"] == "squares":
                        cv2.rectangle(
                            img,
                            (pt[0] - max(2, int(r)), pt[1] - max(2, int(r))),
                            (pt[0] + max(2, int(r)), pt[1] + max(2, int(r))),
                            col,
                            -1,
                        )
                    else:
                        cv2.circle(img, pt, max(2, int(r)), col, -1, cv2.LINE_AA)
                else:
                    draw_map(img, pt, r, col, th, ST["map_style"], self._map_pic())
                if i in hit_nodes:
                    cv2.circle(img, pt, int(r + 7), HIT_COL, 2, cv2.LINE_AA)
        if L["Icons"] and len(self.icon_pts) and far:
            ip = self.to_screen(self.icon_pts)
            ck = (frozenset(self.icon_hidden), id(self.V["icons"]), self.near_only())
            if getattr(self, "_icon_far", (None,))[0] != ck:
                show = np.array(
                    [self.icon_visible(ic) and ic["name"] != "Unidentified" for ic in self.V["icons"]], bool
                )
                icol = np.array([icon_col(ic["name"]) for ic in self.V["icons"]], np.uint8).reshape(-1, 3)
                self._icon_far = (ck, show, icol)
            _ck, show, icol = self._icon_far
            X = np.round(ip[:, 0]).astype(int)
            Y = np.round(ip[:, 1]).astype(int)
            sel = np.nonzero(show & (X >= 1) & (w - 1 > X) & (Y >= 1) & (h - 1 > Y))[0]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    img[Y[sel] + dy, X[sel] + dx] = icol[sel]
        elif L["Icons"] and len(self.icon_pts):
            ip = self.to_screen(self.icon_pts)
            hit_ic = {i for k, i in self.hits if k == "icon"}
            labels = L["Labels"] and z >= 0.8
            placed: list[tuple[int, int, int, int]] = []  # label boxes, so labels never overlap
            for i, ic in enumerate(self.V["icons"]):
                x, y = int(ip[i, 0]), int(ip[i, 1])
                if not (-40 < x < w + 200 and -40 < y < h + 40):
                    continue
                if not self.icon_visible(ic):
                    continue
                if ic["name"] == "Unidentified" and overview:
                    continue
                col = icon_col(ic["name"])
                rr = max(3, int(13 * z)) if not overview else max(3, int(8 * z) + 2)
                if overview:
                    cv2.circle(img, (x, y), rr, col, -1, cv2.LINE_AA)
                    cv2.circle(img, (x, y), rr, (0, 0, 0), 1, cv2.LINE_AA)
                elif ST["ov_badges"]:
                    blit_rgba(img, icon_thumb(ic["name"], 48), x, y, 2.2 * rr)
                else:
                    cv2.circle(img, (x, y), rr, col, 2, cv2.LINE_AA)
                if i in hit_ic:
                    cv2.circle(img, (x, y), rr + 7, HIT_COL, 2, cv2.LINE_AA)
                if labels:
                    text = icon_label(ic)
                    box = (x + rr + 4, y - 8, x + rr + 4 + 8 * len(text), y + 6)
                    if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                        placed.append(box)
                        put_text(img, text, (x + rr + 4, y + 4), col, 0.42)
        if L["Landmarks"]:
            hit_lm = {i for k, i in self.hits if k == "landmark"}
            hw, top, bot = self.landmark_box()
            for i, lm in enumerate(self.V["landmarks"]):
                if not self.landmark_shown(lm):
                    continue
                p = self.to_screen([[lm["x"], lm["y"]]])[0]
                if not (-80 < p[0] < w + 80 and -80 < p[1] < h + 120):
                    continue
                removed = lm["status"].startswith("removed")
                col = REMOVED_COL if removed else LANDMARK_COL.get(lm["kind"], (200, 200, 200))
                x, y = int(p[0]), int(p[1])
                if overview:
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), col, -1)
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), (0, 0, 0), 1)
                else:
                    if ST["ov_towers"] and lm["kind"] == "Tower" and not removed:
                        blit_rgba(img, icon_thumb("LostTower", 64), x, y - int(top) / 2, 1.6 * hw)
                    cv2.rectangle(img, (x - int(hw), y - int(top)), (x + int(hw), y + int(bot)), col, 2, cv2.LINE_AA)
                if lm["status"] == "disputed" and not overview:
                    put_text(img, "?", (x + int(hw) - 10, y - int(top) + 16), col, 0.6, 2)
                if i in hit_lm:
                    cv2.rectangle(
                        img, (x - int(hw) - 5, y - int(top) - 5), (x + int(hw) + 5, y + int(bot) + 5), HIT_COL, 2
                    )
                if L["Labels"] and z >= 0.3:
                    put_text(img, self.lm_name(i), (x - int(hw), y - int(top) - 6), col, 0.45 if z < 1 else 0.55)
        if L["Bookmarks"]:
            hit_bm = {i for k, i in self.hits if k == "bookmark"}
            for i, b in enumerate(self.atlas.bookmarks):
                if not self.bookmark_shown(b):
                    continue
                p = self.to_screen([[b["x"], b["y"]]])[0]
                x, y = int(p[0]), int(p[1])
                if not (-40 < x < w + 300 and -40 < y < h + 40):
                    continue
                pin = np.array([[x, y], [x - 7, y - 14], [x + 7, y - 14]], np.int32)
                cv2.fillPoly(img, [pin], BOOKMARK_COL, cv2.LINE_AA)
                cv2.circle(img, (x, y - 16), 8, BOOKMARK_COL, -1, cv2.LINE_AA)
                cv2.circle(img, (x, y - 16), 8, (0, 0, 0), 1, cv2.LINE_AA)
                if i in hit_bm:
                    cv2.circle(img, (x, y - 12), 18, HIT_COL, 2, cv2.LINE_AA)
                put_text(img, b["name"], (x + 11, y - 12), BOOKMARK_COL, 0.5)
        self._draw_pending(img)
        self._draw_recent(img)
        if getattr(self, "_lasso", None) and len(self._lasso) > 1:
            cv2.polylines(img, [np.array(self._lasso, np.int32)], True, (0, 255, 255), 2, cv2.LINE_AA)
        self._draw_ghost(img, w, h)
        self._draw_progress(img, w, h)
        if self.hits:  # everything listed in Find: a ring on each
            R = int(np.clip(30 * z, 16, 34))  # grows when zooming in, stays visible zoomed out
            pts = self.to_screen([self.item_pos(it) for it in self.hits])
            for x, y in pts:
                if -40 < x < w + 40 and -40 < y < h + 40:
                    cv2.circle(img, (int(x), int(y)), R, (0, 0, 0), 5, cv2.LINE_AA)
                    cv2.circle(img, (int(x), int(y)), R, SELECT_COL, 2, cv2.LINE_AA)
        if rc_paths.CHANNEL == "internal" and self.path:
            if getattr(self, "_dbg_listed", None) != self.path:  # another atlas: its own marks
                self._dbg_listed = self.path
                self._dbg_refresh()
            self._dbg_draw(img)
        if getattr(self, "_goto", None) is not None:
            g = self.to_screen([self._goto])[0]
            gx, gy = int(g[0]), int(g[1])
            for c_, t_ in (((0, 0, 0), 5), ((0, 0, 255), 2)):
                cv2.line(img, (gx - 22, gy), (gx + 22, gy), c_, t_, cv2.LINE_AA)
                cv2.line(img, (gx, gy - 22), (gx, gy + 22), c_, t_, cv2.LINE_AA)
        if self.sel and self.sel_valid() and self.sel[0] != "path":
            p = self.to_screen([self.item_pos(self.sel)])[0]
            cv2.circle(img, (int(p[0]), int(p[1])), int(max(r, 10) + 10), SELECT_COL, 2, cv2.LINE_AA)
        self._legend(img, L)
        return img

    def _legend(self, img, L=None):
        h = img.shape[0]
        L = L or {}
        items = [
            ("map: 2+ shots / icon", NODE_COL["confirmed"]),
            ("1 shot", NODE_COL["single"]),
            ("path: confirmed", PATH_MULTI),
            ("single evidence", PATH_SINGLE),
            ("abyss chain", PATH_ABYSS),
        ]
        if L.get("City & stronghold biomes") and getattr(self, "potential", None):
            items += [(f"near {k}", CITY_COL[k]) for k in CITY_COL]
        x = 10
        width = 24 + sum(22 + len(t) * 8 for t, _ in items)
        cv2.rectangle(img, (4, h - 26), (min(img.shape[1] - 4, width), h - 4), (20, 20, 20), -1)
        for text, col in items:
            cv2.circle(img, (x + 6, h - 15), 5, col, -1, cv2.LINE_AA)
            put_text(img, text, (x + 15, h - 10), (215, 215, 215), 0.42)
            x += 22 + len(text) * 8


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


if __name__ == "__main__":
    raise SystemExit(main())
