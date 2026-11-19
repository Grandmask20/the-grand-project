"""Split one icon type into several: every stored picture of it takes the new type whose art it matches best.

    python -m tools.split_icon_type OLD NEW [NEW ...] [--db DATABASE ...] [--sheet PNG] [--no-truth] [--dry-run]

    e.g.  python -m tools.split_icon_type ArcaneOrProsperous ArcaneHordes ProsperousPopulous --dry-run

Each NEW type needs its art in references/poe2db_icons ("full__NEW.webp" / "inner__NEW.webp"). Every picture of
OLD is compared with that art, rendered as tools/import_poe2db_art.py stores it and shifted +-icon_refs.SHIFT px,
and takes the name of the closest. Relabelled are:

- the icon database's pictures (badge_refs) of each DATABASE (default: the icon database in use);
- the labelled pictures kept in each DATABASE's stored "badges" model (its book): only their names change, the
  classifier and the picture features stay as they are, so nothing is retrained (the stored model may come from
  hand labels that are not in this checkout);
- the hand-labelled icons of the truth files (TRUTH_SETS) and the detector's call stored for them in the
  truth_key.json next to each (unless --no-truth).

The review sheet (each picture with its new name and its distance to each new type's art; "?" where the two best
are within --unsure) is written every time; --dry-run writes only the sheet.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from grand_project import icon_refs
from grand_project import paths as rc_paths
from grand_project.detect import models
from grand_project.detect.constants import ICON_ART_DIR, ICON_INFO, TRUTH_SETS
from tools.import_poe2db_art import SIZES, render

_TILE = 3  # sheet: each 34 px picture drawn this many times larger
_COLS = 8  # sheet: pictures per row


@dataclass
class Match:
    """One stored picture of the old type and the new type it takes."""

    where: str  # what it is, e.g. "atlas_references.sqlite3 badge_refs #412"
    crop: np.ndarray | None  # the picture (None: only its features are stored, in a model's book)
    name: str  # the new type
    dists: list[float]  # 1 - correlation to each new type's art, in the order the new types were given
    unsure: bool  # the two best are within --unsure


def art_features(name: str) -> np.ndarray:
    """Picture features of a type's art at the sizes the importer stores it, shifted +-icon_refs.SHIFT px.

    Args:
        name: The type name.

    Returns:
        (k, d) float32 features (icon_refs.feature).

    Raises:
        SystemExit: The type has no art file.
    """
    s, size = icon_refs.SHIFT, icon_refs.SIZE
    out = []
    for kind, sizes in SIZES.items():
        f = ICON_ART_DIR / f"{kind}__{name}.webp"
        if not f.is_file():
            continue
        for d in sizes:
            pic = render(f, d)
            for dy in range(-s, s + 1):
                for dx in range(-s, s + 1):
                    shifted = cv2.warpAffine(pic, np.float32([[1, 0, dx], [0, 1, dy]]), (size, size))
                    out.append(icon_refs.feature(shifted))
    if not out:
        raise SystemExit(f"{name}: no art in {ICON_ART_DIR} (full__{name}.webp or inner__{name}.webp)")
    return np.array(out, np.float32)


def closest(f: np.ndarray, arts: dict[str, np.ndarray], unsure: float) -> tuple[str, list[float], bool]:
    """The new type whose art is closest to a picture's features.

    Args:
        f: The picture's features (icon_refs.feature).
        arts: New type -> its art features (art_features).
        unsure: Distance gap under which the choice is marked unsure.

    Returns:
        (type, distance to each type's art, whether the two best are within `unsure`).
    """
    d = [float(1 - (F @ f).max()) for F in arts.values()]
    order = np.argsort(d)
    return list(arts)[int(order[0])], d, len(d) > 1 and d[order[1]] - d[order[0]] < unsure


def stored_pictures(db: Path, old: str, arts: dict, unsure: float) -> list[tuple[int, Match]]:
    """The icon database's pictures of the old type, each with its new type.

    Returns:
        (badge_refs row id, match) per picture.
    """
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    rows = c.execute("SELECT id, png FROM badge_refs WHERE name = ? ORDER BY id", (old,)).fetchall()
    c.close()
    out = []
    for rid, png in rows:
        crop = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if crop is None or crop.shape[:2] != (icon_refs.SIZE, icon_refs.SIZE):
            continue
        out.append((rid, Match(f"{db.name} badge_refs #{rid}", crop, *closest(icon_refs.feature(crop), arts, unsure))))
    return out


def book_pictures(db: Path, old: str, arts: dict, unsure: float) -> tuple[dict | None, list[tuple[int, Match]]]:
    """The stored badges model's labelled pictures of the old type, each with its new type.

    Returns:
        (the model, or None when the database has none; (index in its book, match) per picture).
    """
    model = models.load_model("badges", db)
    if not model:
        return None, []
    out = []
    for i, n in enumerate(model["names"]):
        if n == old:
            f = np.asarray(model["F"][i], np.float32)
            out.append((i, Match(f"{db.name} badges model book #{i}", None, *closest(f, arts, unsure))))
    return model, out


def truth_pictures(old: str, arts: dict, unsure: float) -> list[tuple[Path, str, int, Match]]:
    """The hand-labelled icons of the old type in the truth files, each with its new type.

    Returns:
        (truth file, screenshot name, index in its "badges", match) per icon found whole on its screenshot.
    """
    out = []
    for tf, shots in TRUTH_SETS:
        if not tf.exists():
            continue
        for shot, t in json.loads(tf.read_text(encoding="utf-8")).items():
            img = None
            for i, b in enumerate(t["badges"]):
                if b["name"] != old:
                    continue
                if img is None:
                    img = cv2.imdecode(np.fromfile(str(shots / shot), np.uint8), cv2.IMREAD_COLOR)
                crop = icon_refs.crop(img, b["x"], b["y"]) if img is not None else None
                if crop is None:
                    print(f"  {shot} {b.get('id', i)}: screenshot missing or icon off its edge, left as {old}")
                    continue
                m = Match(f"{tf.parent.name} {b.get('id', i)}", crop, *closest(icon_refs.feature(crop), arts, unsure))
                out.append((tf, shot, i, m))
    return out


def sheet(path: Path, new: list[str], matches: list[Match]) -> None:
    """Write the review sheet: the new types' art on top, then every picture with its new name and distances."""
    t = icon_refs.SIZE * _TILE
    cell_h = t + 36

    def tile(pic: np.ndarray | None, lines: list[str], colour=(255, 255, 255)) -> np.ndarray:
        c = np.full((cell_h, t + 40, 3), 24, np.uint8)
        if pic is not None:
            c[:t, 20 : 20 + t] = cv2.resize(pic, (t, t), interpolation=cv2.INTER_NEAREST)
        else:
            cv2.putText(c, "features only", (24, t // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (160, 160, 160), 1)
        for k, line in enumerate(lines):
            cv2.putText(c, line, (2, t + 14 + 14 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.38, colour, 1, cv2.LINE_AA)
        return c

    head = []
    for n in new:
        f = next(ICON_ART_DIR / f"{k}__{n}.webp" for k in SIZES if (ICON_ART_DIR / f"{k}__{n}.webp").is_file())
        kind = f.stem.split("__")[0]
        head.append(tile(render(f, SIZES[kind][-1]), [f"art: {n}"], (120, 220, 255)))
    cells = [
        tile(m.crop, [("? " if m.unsure else "") + m.name, " ".join(f"{d:.3f}" for d in m.dists)]) for m in matches
    ]
    blank = np.full_like(head[0], 24)
    rows = [np.hstack(head + [blank] * (_COLS - len(head)))]
    for i in range(0, len(cells), _COLS):
        part = cells[i : i + _COLS]
        rows.append(np.hstack(part + [blank] * (_COLS - len(part))))
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(rows))


def _write_json(path: Path, value) -> None:
    """Rewrite a truth file as grand_project/truth.py writes it (indent 1), keeping its line endings (the files
    written on Windows have CRLF ones: rewritten with LF, every line would show as changed)."""
    crlf = b"\r\n" in path.read_bytes()
    text = json.dumps(value, indent=1)
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Run the split (see the module docstring); returns the exit status."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old", help="the type to split, e.g. ArcaneOrProsperous")
    ap.add_argument("new", nargs="+", help="the types it becomes (each with art in references/poe2db_icons)")
    ap.add_argument("--db", type=Path, action="append", help="icon database (repeatable; default: the one in use)")
    ap.add_argument("--sheet", type=Path, help="review sheet (default: runs/split_icon_type/<OLD>.png)")
    ap.add_argument("--no-truth", action="store_true", help="leave the truth files alone")
    ap.add_argument("--unsure", type=float, default=0.02, help="distance gap under which a choice is marked '?'")
    ap.add_argument("--dry-run", action="store_true", help="only write the review sheet")
    a = ap.parse_args(argv)
    if a.old in a.new:
        ap.error("the old type cannot be one of the new ones")
    for n in a.new:
        if n not in ICON_INFO:
            print(f"warning: {n} is not in ICON_INFO (grand_project/detect/constants.py)")
    arts = {n: art_features(n) for n in a.new}
    dbs = a.db or [icon_refs.DB_PATH]
    stored = {db: stored_pictures(db, a.old, arts, a.unsure) for db in dbs}
    books = {db: book_pictures(db, a.old, arts, a.unsure) for db in dbs}
    truth = [] if a.no_truth else truth_pictures(a.old, arts, a.unsure)
    matches = [m for v in stored.values() for _, m in v] + [m for _, v in books.values() for _, m in v]
    matches += [m for *_, m in truth]
    out = a.sheet or rc_paths.ROOT / "runs" / "split_icon_type" / f"{a.old}.png"
    sheet(out, a.new, matches)
    for m in matches:
        print(f"  {m.where}: {m.name}{' (unsure)' if m.unsure else ''}  " + " ".join(f"{d:.3f}" for d in m.dists))
    print(f"{len(matches)} pictures of {a.old}; review sheet: {out}")
    if a.dry_run or not matches:
        return 0
    for db, rows in stored.items():
        if rows:
            c = icon_refs._db(db)
            c.executemany("UPDATE badge_refs SET name = ? WHERE id = ?", [(m.name, rid) for rid, m in rows])
            c.commit()
            c.close()
    for db, (model, rows) in books.items():
        if rows:
            names = list(model["names"])
            for i, m in rows:
                names[i] = m.name
            model["names"] = names
            c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            info = json.loads(c.execute("SELECT info FROM detector_models WHERE name = 'badges'").fetchone()[0] or "{}")
            c.close()
            models.save_model("badges", model, info, path=db)
    for tf in {tf for tf, *_ in truth}:
        data = json.loads(tf.read_text(encoding="utf-8"))
        key_file = tf.parent / "truth_key.json"
        key = json.loads(key_file.read_text(encoding="utf-8")) if key_file.exists() else None
        for _, shot, i, m in (x for x in truth if x[0] == tf):
            b = data[shot]["badges"][i]
            b["name"] = m.name
            kb = key["badges"].get(b.get("id", "")) if key else None
            if kb and kb.get("detector") == a.old:
                kb["detector"] = m.name
        _write_json(tf, data)
        if key:
            _write_json(key_file, key)
    print("relabelled: " + ", ".join(f"{n} {sum(m.name == n for m in matches)}" for n in a.new))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
