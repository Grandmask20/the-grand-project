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

from grand_project import paths as rc_paths

DB_PATH = rc_paths.DATABASE
SIZE = 34  # badge crop, px at 1080p
RADIUS = 11  # compared area: the badge picture inside the gold rim
SHIFT = 3  # search +-3 px for the best alignment
MAX_DIST = 0.40  # 1 - correlation; leave-one-out on 350 labelled badges: 95% right
# The pattern match removes each badge's average colour, so a bright blue blob (Azmeri Spirit) and a bright white
# fleur-de-lis (Hideout) correlate well. The colour of the brightest quarter tells them apart: a badge can only take
# a name whose stored pictures have a bright part this close in colour (Lab a/b units; pictures of one name differ
# by up to ~12, Azmeri Spirit vs Hideout 17, Hideout vs the red hideout 34).
BRIGHT_TOL = 12.0
# only these look-alikes are checked (other names' bright parts vary more, e.g. MapBoss up to 34)
COLOUR_CHECKED = {"AzmeriSpirit", "Hideout", "HideoutRed"}
# Grand Mirror (dark grey oval) and Delirium Mirror (bright white splash) differ in brightness, which the pattern
# match removes (user: the two were flaky). Measured against the icon's own rim, so fog dims both alike: the
# brightest quarter inside / the rim's, Grand Mirror 1.10-1.28 (35 crawl icons), Delirium 1.38-1.75 (184).
BRIGHT_SPLIT = {"GrandMirror": (None, 1.35), "Delirium": (1.35, None)}
NOT_A_BADGE = "NotABadge"

_yy, _xx = np.mgrid[:SIZE, :SIZE]
_MASK = np.hypot(_xx - SIZE / 2 + 0.5, _yy - SIZE / 2 + 0.5) <= RADIUS


def crop(img: np.ndarray, x: float, y: float, size: int = SIZE) -> np.ndarray | None:
    """Cut a square icon crop centred on a point.

    Args:
        img: BGR screenshot (1080p px).
        x: Icon centre x, px.
        y: Icon centre y, px.
        size: Crop side, px.

    Returns:
        (size, size, 3) crop, or None when it would reach past the image edge.
    """
    x, y, r = int(round(x)), int(round(y)), size // 2
    c = img[y - r : y - r + size, x - r : x - r + size]
    return c if c.shape[:2] == (size, size) else None


def feature(c: np.ndarray) -> np.ndarray:
    """Turn an icon crop into a pattern vector for matching.

    The crop is blurred (to tolerate a pixel or two of misalignment), the colour inside the rim (_MASK) taken,
    its average colour removed and the result scaled to unit length, so a dot product is a correlation.

    Args:
        c: (SIZE, SIZE, 3) BGR icon crop.

    Returns:
        1-D float32 vector.
    """
    c = cv2.GaussianBlur(c, (0, 0), 1.5)  # tolerate a pixel or two of misalignment
    v = c[_MASK].astype(np.float32)  # colour inside the rim
    v -= v.mean(axis=0)
    n = np.linalg.norm(v)
    return (v / n).ravel() if n > 1e-6 else v.ravel()


def bright_colour(c: np.ndarray) -> np.ndarray:
    """Measure the (a, b) colour of the brightest quarter inside the rim, 0 = grey / white.

    Args:
        c: (SIZE, SIZE, 3) BGR icon crop.

    Returns:
        (2,) float32 array of Lab a/b units.
    """
    lab = cv2.cvtColor(cv2.GaussianBlur(c, (0, 0), 1.0), cv2.COLOR_BGR2LAB)[_MASK].astype(np.float32)
    top = lab[lab[:, 0] >= np.percentile(lab[:, 0], 75)]
    return top[:, 1:].mean(axis=0) - 128.0


_RIM_RING = (np.hypot(_xx - SIZE / 2 + 0.5, _yy - SIZE / 2 + 0.5) >= 9.5) & (
    np.hypot(_xx - SIZE / 2 + 0.5, _yy - SIZE / 2 + 0.5) <= 11.5
)


def bright_level(c: np.ndarray) -> float:
    """Brightness of the brightest quarter inside the rim, relative to the rim's own (fog dims both alike).

    Args:
        c: (SIZE, SIZE, 3) BGR icon crop.

    Returns:
        The ratio (Grand Mirror 1.10-1.28, Delirium 1.38-1.75; see BRIGHT_SPLIT).
    """
    lum = cv2.cvtColor(cv2.GaussianBlur(c, (0, 0), 1.0), cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    return float(np.percentile(lum[_MASK], 75) / (np.percentile(lum[_RIM_RING], 75) + 1.0))


def colour_ok(names: list[str], profiles: dict[str, np.ndarray], c: np.ndarray) -> np.ndarray:
    """For each name, tell whether an icon with crop c may take it.

    Names outside COLOUR_CHECKED or without pictures are always allowed by colour; the BRIGHT_SPLIT names must
    also fit their brightness range.

    Args:
        names: Candidate icon names.
        profiles: Name -> (k, 2) bright-part colours of its stored pictures (Refs.colours).
        c: (SIZE, SIZE, 3) BGR icon crop.

    Returns:
        (len(names),) bool array.
    """
    col = bright_colour(c)
    ok = {
        n: bool(np.linalg.norm(P - col, axis=1).min() <= BRIGHT_TOL)
        for n, P in profiles.items()
        if n in COLOUR_CHECKED and len(P)
    }
    lvl = bright_level(c)
    for n, (lo, hi) in BRIGHT_SPLIT.items():
        ok[n] = ok.get(n, True) and (lo is None or lvl >= lo) and (hi is None or lvl <= hi)
    return np.array([ok.get(n, True) for n in names])


def _db(path: Path | None = None) -> sqlite3.Connection:
    """Open the icon database, creating the badge_refs table if missing.

    Args:
        path: Database file; None uses DB_PATH.

    Returns:
        An open sqlite3 connection (the caller closes it).
    """
    c = sqlite3.connect(str(path or DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS badge_refs (
                     id INTEGER PRIMARY KEY, name TEXT NOT NULL, png BLOB NOT NULL,
                     png_hash TEXT NOT NULL UNIQUE, created TEXT NOT NULL)""")
    return c


def add(name: str, crop_bgr: np.ndarray, conn: sqlite3.Connection | None = None) -> bool:
    """Store one named icon crop.

    Clears the cached references so the next refs() call reads them again.

    Args:
        name: Icon name (NOT_A_BADGE for a false detection).
        crop_bgr: BGR icon crop (SIZE x SIZE).
        conn: Open connection to use (the caller commits); None opens, commits and closes one.

    Returns:
        False when the same picture is already stored, else True.
    """
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
    """Read the stored icon references.

    Args:
        name: Only this name; None for every one.

    Returns:
        List of (name, BGR crop) in the order they were stored (empty when there is no database).
    """
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
    """Every stored icon reference, ready for nearest-match naming.

    Attributes:
        names: Name of each reference (crops not SIZE x SIZE are skipped).
        F: (n, d) float32 pattern vectors (see feature), one row per name.
        colours: Name -> (k, 2) bright-part colours of its stored pictures (the colour check, BRIGHT_TOL);
            NOT_A_BADGE has none.
    """

    def __init__(self):
        """Load every stored reference from the database."""
        self.names: list[str] = []
        feats, cols = [], {}
        for name, img in load():
            if img.shape[:2] != (SIZE, SIZE):
                continue
            self.names.append(name)
            feats.append(feature(img))
            if name != NOT_A_BADGE:
                cols.setdefault(name, []).append(bright_colour(img))
        self.F = np.array(feats, np.float32) if feats else np.zeros((0, int(_MASK.sum()) * 3), np.float32)
        # per name: bright-part colours of its stored pictures (the colour check, BRIGHT_TOL)
        self.colours = {n: np.array(v, np.float32) for n, v in cols.items()}

    def __len__(self):
        """Return the number of references."""
        return len(self.names)


_REFS: Refs | None = None


def refs() -> Refs:
    """Return the stored references, loaded once and kept until add() changes them.

    Returns:
        The Refs.
    """
    global _REFS
    if _REFS is None:
        _REFS = Refs()
    return _REFS
