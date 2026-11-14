"""Map badges taught by hand: reference crops with names, and a nearest-match classifier.

The game has far more badge types (map content, tablet / atlas-tree modifiers) than the icon
assets the template matcher knows.  Badges you name on the badge sheet are stored as small
reference crops in the icon database (table badge_refs of node_references_0_18.sqlite3, the
same database the recognizer trains into; one row per example: name + PNG).  A detected badge
that the matcher could not name, or named with a type known to be unreliable, is compared with
every reference; the closest wins if it is close enough.  "NotABadge" references remove
detections that are really terrain or buildings.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REF_DIR = HERE / "icon_refs"  # old storage: imported into the database once, then unused

from grand_project import paths as rc_paths  # noqa: E402

DB_PATH = rc_paths.DATABASE
SIZE = 34  # badge crop, px at 1080p
RADIUS = 11  # compared area: the badge picture inside the gold rim
SHIFT = 3  # search +-3 px for the best alignment
MAX_DIST = 0.40  # 1 - correlation; leave-one-out on 350 labelled badges: 95% right
RELABEL = {"Unidentified", "RogueExile", "StoneCircle"}  # matcher results to re-check
# weak template assets: kept only when the taught references agree, otherwise unnamed
CONFIRM = {
    "Trader",
    "Sanctification",
    "SanctificationBoss",
    "RogueExile",
    "StoneCircle",
    "AbyssalDepths",
    "ExpeditionRemnant",
    "Shrine",
    "RareMonster",
    "Checkpoint",
    "NamelessSeer",
}
MARGIN = 0.75  # best distance must beat the nearest OTHER name by this factor
NOT_A_BADGE = "NotABadge"

_yy, _xx = np.mgrid[:SIZE, :SIZE]
_MASK = np.hypot(_xx - SIZE / 2 + 0.5, _yy - SIZE / 2 + 0.5) <= RADIUS


def crop(img: np.ndarray, x: float, y: float, size: int = SIZE) -> np.ndarray | None:
    x, y, r = int(round(x)), int(round(y)), size // 2
    c = img[y - r : y - r + size, x - r : x - r + size]
    return c if c.shape[:2] == (size, size) else None


def feature(c: np.ndarray) -> np.ndarray:
    c = cv2.GaussianBlur(c, (0, 0), 1.5)  # tolerate a pixel or two of misalignment
    v = c[_MASK].astype(np.float32)  # colour inside the rim
    v -= v.mean(axis=0)
    n = np.linalg.norm(v)
    return (v / n).ravel() if n > 1e-6 else v.ravel()


def _db(path: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(str(path or DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS badge_refs (
                     id INTEGER PRIMARY KEY, name TEXT NOT NULL, png BLOB NOT NULL,
                     png_hash TEXT NOT NULL UNIQUE, created TEXT NOT NULL)""")
    return c


def add(name: str, crop_bgr: np.ndarray, conn: sqlite3.Connection | None = None) -> bool:
    """store one named badge crop; False when the same picture is already stored"""
    png = cv2.imencode(".png", crop_bgr)[1].tobytes()
    c = conn or _db()
    try:
        c.execute(
            "INSERT INTO badge_refs(name, png, png_hash, created) VALUES (?,?,?,?)",
            (name, png, hashlib.sha1(png).hexdigest(), time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    if conn is None:
        c.commit()
        c.close()
    global _REFS
    _REFS = None
    return ok


def load(name: str | None = None) -> list[tuple[str, np.ndarray]]:
    """(name, BGR crop) of every stored reference, or of one name"""
    if not DB_PATH.exists():
        return []
    c = _db()
    rows = c.execute(
        "SELECT name, png FROM badge_refs" + (" WHERE name=?" if name else "") + " ORDER BY id", (name,) if name else ()
    ).fetchall()
    c.close()
    out = []
    for n, png in rows:
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            out.append((n, img))
    return out


class Refs:
    def __init__(self):
        self.names: list[str] = []
        feats = []
        for name, img in load():
            if img.shape[:2] != (SIZE, SIZE):
                continue
            self.names.append(name)
            feats.append(feature(img))
        self.F = np.array(feats, np.float32) if feats else np.zeros((0, int(_MASK.sum()) * 3), np.float32)

    def __len__(self):
        return len(self.names)

    def classify(self, img: np.ndarray, x: float, y: float, exclude: int | None = None):
        """(name, distance) of the closest reference, trying small shifts; None if no refs"""
        if not len(self.names):
            return None
        big = crop(img, x, y, SIZE + 2 * SHIFT)
        if big is None:
            return None
        names = np.array(self.names)
        dmin = np.full(len(names), 9.0, np.float32)
        for dy in range(0, 2 * SHIFT + 1, 1):
            for dx in range(0, 2 * SHIFT + 1, 1):
                f = feature(big[dy : dy + SIZE, dx : dx + SIZE])
                dmin = np.minimum(dmin, 1.0 - self.F @ f)
        if exclude is not None:
            dmin[exclude] = 9.0
        k = int(np.argmin(dmin))
        other = dmin[names != names[k]]
        second = float(other.min()) if len(other) else 9.0
        return self.names[k], float(dmin[k]), second


_REFS: Refs | None = None


def refs() -> Refs:
    global _REFS
    if _REFS is None:
        _REFS = Refs()
    return _REFS


# Badges the template matcher never proposes (no ring found around them): searched for directly
# with their taught reference crops.
SEARCH_BY_REFS = {"GlimmeringMutation"}
SEARCH_MIN = 0.70  # colour correlation; real Glimmering Mutation badges scored 0.72-0.80,
# terrain at most 0.62


def find_by_refs(img: np.ndarray, records: list[dict]) -> list[dict]:
    """add badges of SEARCH_BY_REFS types found by template search with their references"""
    out = list(records)
    for name in SEARCH_BY_REFS:
        for _n, c in load(name):
            inner = c[7:27, 7:27]  # the picture inside the rim
            res = cv2.matchTemplate(img, inner, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= SEARCH_MIN)
            for y, x in sorted(zip(ys, xs, strict=False), key=lambda t: -res[t[0], t[1]]):
                cx, cy = int(x) + 10, int(y) + 10
                if any(abs(m["x"] - cx) < 16 and abs(m["y"] - cy) < 16 for m in out):
                    continue
                out.append({"name": name, "x": cx, "y": cy, "score": round(float(res[y, x]), 3), "source": "taught"})
    return out
