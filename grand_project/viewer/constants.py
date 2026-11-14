"""viewer.constants (from atlas_viewer.py)"""

from __future__ import annotations

import os
import sys

try:  # drag and drop of screenshot files (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None
from grand_project import __version__, core

VERSION = __version__  # one place: grand_project/__init__.py

# --- platform differences (Windows / macOS / Linux) ---
IS_MAC = sys.platform == "darwin"


IS_WIN = sys.platform == "win32"


MOD = "Command" if IS_MAC else "Control"  # shortcut modifier: Cmd on macOS, Ctrl elsewhere


MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"


# Tk numbers the mouse buttons differently on macOS: 2 is the right button and 3 the middle one
BTN_MIDDLE, BTN_RIGHT = (3, 2) if IS_MAC else (2, 3)


MONO_FONT = "Menlo" if IS_MAC else ("Consolas" if IS_WIN else "DejaVu Sans Mono")


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


LANDMARK_KINDS = ("City", "Hall", "Tower", "Breach stronghold", "Locked stronghold", "Deadly boss map")


EDIT_SAME = 90.0  # atlas units: a hand edit applies to the landmark this close (landmarks drift


# a little between re-checks)
EDIT_SPOT = 15.0  # a new edit replaces an older one only at the same spot
