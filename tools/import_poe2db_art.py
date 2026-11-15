"""Add poe2db's Map Content / Map Legend art as icon pictures for the types that have none yet.

    python -m tools.import_poe2db_art [DATABASE ...]

references/poe2db_icons/ holds the art (https://poe2db.tw/us/Waystones#MapContent / #MapLegends), named
"full__<Name>.webp" (the whole icon with its rim: AtlasIconContent*) or "inner__<Name>.webp" (atlas-tree art: the
picture inside the rim). Each is shrunk to the size the game draws it at 1080p - whole icons 34 px (the icon crop),
inner art 20-22 px (the area inside the rim): the sizes where the art best matched real on-screen icons - and
stored as a picture of that name in each DATABASE's badge_refs (default: the icon database in use).

Only for types with no on-screen picture yet: on the hand-labelled icons the art alone names 87% right against
99% for real on-screen pictures (the art is sharper and lit differently, and some types look alike in it), and
adding it next to real pictures changed nothing. A rare type found by its art (e.g. Energized Ley Lines) should
then get real pictures stored from the screenshots it was found in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from grand_project import icon_refs
from grand_project import paths as rc_paths
from grand_project.detect.constants import TRUTH_SETS

ART = rc_paths.ref("poe2db_icons")
SIZES = {"full": (34,), "inner": (20, 22)}


def render(f: Path, d: int) -> np.ndarray:
    """the art shrunk to d px on black, centred in an icon crop (icon_refs.SIZE)"""
    im = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_UNCHANGED)
    if im.ndim == 3 and im.shape[2] == 4:
        a = im[..., 3:4].astype(np.float32) / 255
        im = (im[..., :3].astype(np.float32) * a).astype(np.uint8)
    S = icon_refs.SIZE
    t = cv2.resize(im, (d, d), interpolation=cv2.INTER_AREA)
    c = np.zeros((S, S, 3), np.uint8)
    o = (S - d) // 2
    if o >= 0:
        c[o : o + d, o : o + d] = t
    else:
        c[:] = t[-o : -o + S, -o : -o + S]
    return c


def known_names(db: Path) -> set[str]:
    import json
    import sqlite3

    c = sqlite3.connect(str(db))
    have = {r[0] for r in c.execute("SELECT DISTINCT name FROM badge_refs")}
    c.close()
    for tf, _shots in TRUTH_SETS:  # hand-labelled icons name types too (the detector learns from them)
        if tf.exists():
            have |= {b["name"] for v in json.loads(tf.read_text(encoding="utf-8")).values() for b in v["badges"]}
    return have


def main():
    dbs = [Path(a) for a in sys.argv[1:]] or [icon_refs.DB_PATH]
    for db in dbs:
        have = known_names(db)
        conn = icon_refs._db(db)
        added = []
        for f in sorted(ART.glob("*.webp")):
            kind, name = f.stem.split("__", 1)
            name = name.rstrip("2")  # two pictures of one type: Name, Name2
            if name in have and name not in added:
                continue
            for d in SIZES[kind]:
                if icon_refs.add(name, render(f, d), conn):
                    added.append(name)
        conn.commit()
        conn.close()
        print(f"{db.name}: art pictures added for {len(set(added))} types: {', '.join(sorted(set(added)))}")


if __name__ == "__main__":
    main()
