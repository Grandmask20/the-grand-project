"""Save badge-sheet labels as reference crops in the icon database (badge_refs table).

    python -m tools.atlas_icon_teach --atlas my_atlas.json --labels labels.txt

labels.txt, one per line:  G4.10 PowerOfFaith    |  G2 Corruption  (whole group, the 14 shown)
                           RogueExile.13 HuntingGrounds   (rows of matched types)
                           G3 NotABadge                    (terrain mistaken for a badge)
Tiles are numbered 1-14 left to right as on the sheet atlas_badge_sheet.py made.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
from tools.atlas_badge_sheet import CHECK_TYPES, PER_ROW  # noqa: E402, I001

from grand_project import core  # noqa: E402
from grand_project import icon_refs as R  # noqa: E402


def sheet_badges(atlas_path: Path):
    """the same per-badge sightings the sheet was drawn from (most central sighting first)"""
    atlas = core.Atlas.load(atlas_path)
    by_name = {f["name"]: f for f in atlas.frames}
    sightings = []
    for cf in atlas_path.with_name(atlas_path.stem + "_frames").glob("*.json"):
        fr = core.Frame.from_json(json.loads(cf.read_text(encoding="utf-8")))
        f = by_name.get(fr.name)
        if f is None:
            continue
        H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
        for m in fr.icons:
            p = core.persp(H, [[m["x"], m["y"]]])[0]
            c = max(abs(m["x"] / fr.w - 0.5), abs(m["y"] / fr.h - 0.5))
            sightings.append((m["name"], p[0], p[1], fr.path, m["x"], m["y"], c, m.get("source", "")))
    badges: dict[str, list] = {}
    for s in sorted(sightings, key=lambda s: s[6]):
        lst = badges.setdefault(s[0], [])
        if not any(abs(b[1] - s[1]) < 30 and abs(b[2] - s[2]) < 30 for b in lst):
            lst.append(s)
    return badges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--sheet", help="the sheet PNG the labels refer to (default <atlas>_badges.png)")
    a = ap.parse_args()
    atlas_path = Path(a.atlas)
    sheet = Path(a.sheet) if a.sheet else core.atlas_files(atlas_path) / (atlas_path.stem + "_badges.png")
    groups = json.loads(sheet.with_suffix(".json").read_text(encoding="utf-8"))
    badges = sheet_badges(atlas_path)
    imgs: dict[str, np.ndarray] = {}

    def image(p):
        if p not in imgs:
            imgs[p] = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        return imgs[p]

    unk = badges.get("Unidentified", [])

    def tiles(row: str) -> list:
        """the badges shown in a sheet row, in tile order"""
        if row.startswith("G"):
            out = []
            for x, y in groups[row][:PER_ROW]:
                b = min(unk, key=lambda b: abs(b[1] - x) + abs(b[2] - y))
                out.append(b)
            return out
        bs = badges.get(row, [])  # same rows as atlas_badge_sheet: "matched as" for
        if row not in CHECK_TYPES:  # the poe2db types, "taught as" for the rest
            bs = [b for b in bs if b[7] == "taught"]
        return [b for b in bs[:PER_ROW] if R.crop(image(b[3]), b[4], b[5], 44) is not None]

    count: dict[str, int] = {}
    saved = 0
    for line in Path(a.labels).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        key, name = line.split()
        row, _, tile = key.partition(".")
        bs = tiles(row)
        chosen = [bs[int(tile) - 1]] if tile else bs
        for b in chosen:
            c = R.crop(image(b[3]), b[4], b[5])
            if c is not None and R.add(name, c):
                count[name] = count.get(name, 0) + 1
                saved += 1
    print(
        f"saved {saved} reference crops in {R.DB_PATH.name} (badge_refs): "
        + ", ".join(f"{n} {c}" for n, c in sorted(count.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
