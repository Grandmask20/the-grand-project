"""Hand-check map node states and make the state namer's pictures (grand_project/detect/node_states.py).

    python -m tools.node_state_sheet sheet FOLDER [--shots NAME ...] [--every N] [--out DIR]
    python -m tools.node_state_sheet save FOLDER [--out DIR]
    python -m tools.node_state_sheet freeze [--leave-out FOLDER] [--to FILE]
    python -m tools.node_state_sheet score FOLDER [--pictures FILE]

sheet   crops of the map nodes of a folder's screenshots, grouped by the state proposed for each (the namer's,
        or a first guess from the glow's colour while there are no pictures), every crop with an id (S1, S2 ...).
        Positions come from the folder's states.json when it has the screenshot, else from its truth.json maps
        (one of TRUTH_SETS), else from the detector. Writes sheet_<state>_<page>.png, proposals.json and an empty
        corrections.txt to DIR (default runs/node_state_sheets/<folder>).
save    corrections.txt holds only what the sheet got wrong, one per line: "S12 green", "S40 none" (not a map
        node, or its state can't be told); every other crop keeps its proposed state. Writes the result to the
        folder's states.json ({screenshot file: [{x, y, state}]}, screen px at 1080p), replacing the screenshots
        of this sheet.
freeze  the pictures from the states.json of every NODE_STATE_SETS folder (--leave-out one to score it unseen),
        at most NODE_STATE_PICTURES per state, picked to cover the looks (farthest first), to NODE_STATES_FILE
        (or --to).
score   the namer on a folder's states.json positions (with --pictures, e.g. a --leave-out freeze), per state.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from grand_project import core, icon_refs
from grand_project.detect import constants as K
from grand_project.detect import node_states

STATES = (*K.NODE_STATES, None)
CROP, ZOOM, PER_ROW, ROWS = 48, 2, 12, 9  # sheet tiles: a 48 px crop shown at 2x, 12 x 9 per page
# first guess while there are no pictures: a glow's share (node_states.glow_shares) from which the map node has that
# state; below every share it is grey (map_state_change: blue map nodes 0.18-0.41, grey ones mostly 0)
GUESS_SHARE = 0.10
DEFAULT_OUT = Path("runs") / "node_state_sheets"


def first_guess(crop: np.ndarray) -> str:
    """A state from the glow's colour alone (only to start the first sheet, before any pictures exist)."""
    shares = dict(zip(K.NODE_STATE_GLOW_BANDS, node_states.glow_shares(crop), strict=True))
    state, share = max(shares.items(), key=lambda kv: kv[1])
    return state if share >= GUESS_SHARE else "grey"


def read_states(folder: Path) -> dict:
    """A folder's hand-checked states ({screenshot file: [{x, y, state}]}; {} without states.json)."""
    f = Path(folder) / K.NODE_STATE_TRUTH
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _truth_maps(folder: Path) -> dict:
    """The truth.json maps of a TRUTH_SETS screenshot folder ({screenshot file: [(x, y)]}), {} for other folders."""
    for truth, shots in K.TRUTH_SETS:
        if Path(shots).resolve() == Path(folder).resolve() and truth.exists():
            return {
                name: [(m["x"], m["y"]) for m in t["maps"] if not {"ui", "hidden"} & set(m["flags"])]
                for name, t in json.loads(truth.read_text(encoding="utf-8")).items()
            }
    return {}


def _positions(path: Path, img: np.ndarray, known: dict, truth: dict) -> list[tuple[float, float, str | None]]:
    """Where a screenshot's map nodes are, with their checked state when states.json has them."""
    if path.name in known:
        return [(s["x"], s["y"], s["state"]) for s in known[path.name]]
    if path.name in truth:
        return [(x, y, None) for x, y in truth[path.name]]
    from grand_project.detect import detect

    return [(n["x"], n["y"], None) for n in detect(img)["nodes"] if not n.get("hidden")]


def _holds_corrections(path: Path) -> bool:
    """Whether a corrections file has a correction in it (not only comments)."""
    return path.exists() and any(
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )


def cmd_sheet(folder: Path, out: Path, shots: list[str], every: int) -> int:
    """Write the sheets, proposals.json and corrections.txt for a folder's screenshots."""
    if _holds_corrections(out / "corrections.txt"):
        # new sheets number their crops anew: the corrections would land on other crops
        raise SystemExit(
            f"{out / 'corrections.txt'} holds corrections for the sheets there now: save them (save), then empty it"
        )
    paths = core.screenshots_in(folder)
    if shots:
        want = set(shots)
        paths = [p for p in paths if p.name in want or p.stem in want]
    paths = paths[:: max(1, every)]
    known, truth = read_states(folder), _truth_maps(folder)
    has_pictures = bool(node_states.state_pictures()["states"])
    proposals, tiles = {}, {s: [] for s in STATES}
    for path in paths:
        img = core.read_screenshot(path)
        if img is None:
            continue
        for x, y, state in _positions(path, img, known, truth):
            crop = icon_refs.crop(img, x, y)
            if crop is None:
                continue
            if state is None:
                state = node_states.name_state(img, x, y)[0] if has_pictures else first_guess(crop)
            sid = f"S{len(proposals) + 1}"
            proposals[sid] = {"shot": path.name, "x": round(float(x), 1), "y": round(float(y), 1), "state": state}
            tiles[state].append((sid, icon_refs.crop(img, x, y, CROP)))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("sheet_*.png"):
        old.unlink()
    for state, items in tiles.items():
        per = PER_ROW * ROWS
        for page in range(0, len(items), per):
            core.write_png(out / f"sheet_{state or 'unsure'}_{page // per + 1}.png", _page(items[page : page + per]))
    (out / "proposals.json").write_text(json.dumps({"folder": str(folder), "proposals": proposals}), encoding="utf-8")
    corrections = out / "corrections.txt"
    if not corrections.exists():
        corrections.write_text("# one per line: <id> <grey|blue|green|red|none>, e.g. S12 green\n", encoding="utf-8")
    counts = Counter(p["state"] or "unsure" for p in proposals.values())
    print(
        f"{len(proposals)} map nodes of {len(paths)} screenshots -> {out}: "
        + ", ".join(f"{k} {v}" for k, v in counts.items())
    )
    return 0


def _page(items: list[tuple[str, np.ndarray | None]]) -> np.ndarray:
    """One sheet page: the crops in rows, each with its id under it."""
    side = CROP * ZOOM
    tiles = []
    for sid, crop in items:
        tile = np.full((side + 18, side, 3), 30, np.uint8)
        if crop is not None:
            tile[:side] = cv2.resize(crop, (side, side), interpolation=cv2.INTER_NEAREST)
        cv2.putText(tile, sid, (4, side + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % PER_ROW)
    return np.vstack([np.hstack(tiles[i : i + PER_ROW]) for i in range(0, len(tiles), PER_ROW)])


def read_corrections(path: Path) -> dict[str, str | None]:
    """The corrections file: id -> state (None for "none").

    Raises:
        ValueError: A line that is not "<id> <state>" with a known state.
    """
    out = {}
    for k, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[1].lower() not in (*K.NODE_STATES, "none"):
            raise ValueError(f"{path.name} line {k}: {line!r} is not '<id> <grey|blue|green|red|none>'")
        out[parts[0].upper()] = None if parts[1].lower() == "none" else parts[1].lower()
    return out


def cmd_save(folder: Path, out: Path) -> int:
    """Apply corrections.txt to the proposals and write the folder's states.json."""
    data = json.loads((out / "proposals.json").read_text(encoding="utf-8"))
    if Path(data["folder"]).resolve() != Path(folder).resolve():  # two folders of one name share the default out
        raise SystemExit(f"the sheets in {out} are of {data['folder']}, not {folder}")
    proposals = data["proposals"]
    fixes = read_corrections(out / "corrections.txt")
    unknown = sorted(set(fixes) - set(proposals))
    if unknown:
        raise SystemExit(f"no such crop on the sheet: {', '.join(unknown)}")
    states = read_states(folder)
    for shot in {p["shot"] for p in proposals.values()}:
        states[shot] = []
    unsure = 0
    for sid, p in proposals.items():
        state = fixes[sid] if sid in fixes else p["state"]
        if state is None:
            unsure += sid not in fixes
            continue
        states[p["shot"]].append({"x": p["x"], "y": p["y"], "state": state})
    target = folder / K.NODE_STATE_TRUTH
    target.write_text(json.dumps(dict(sorted(states.items())), indent=1), encoding="utf-8")
    total = sum(len(v) for v in states.values())
    print(f"{total} map node states -> {target} ({len(fixes)} corrected, {unsure} unsure left out)")
    return 0


def _labelled(folders: list[Path]) -> list[tuple[np.ndarray, str, str]]:
    """Every hand-checked map node of the folders as (crop, state, screenshot file)."""
    out = []
    for folder in folders:
        for shot, items in read_states(folder).items():
            img = core.read_screenshot(folder / shot)
            if img is None:
                continue
            for s in items:
                crop = icon_refs.crop(img, s["x"], s["y"])
                if crop is not None:
                    out.append((crop, s["state"], shot))
    return out


def spread(F: np.ndarray, n: int) -> list[int]:
    """Up to n rows of F that cover its looks: the one nearest the middle first, then each time the one furthest
    from those picked (farthest-point sampling, so many crops of one map node seen again count once)."""
    if len(F) <= n:
        return list(range(len(F)))
    picked = [int(np.argmax(F @ F.mean(axis=0)))]
    far = 1 - F @ F[picked[0]]
    while len(picked) < n:
        k = int(np.argmax(far))
        picked.append(k)
        far = np.minimum(far, 1 - F @ F[k])
    return picked


def cmd_freeze(leave_out: Path | None, to: Path) -> int:
    """Freeze the pictures from the NODE_STATE_SETS folders (never the scoring truth sets)."""
    scoring = {Path(shots).resolve() for _truth, shots in K.TRUTH_SETS}
    folders = [Path(f) for f in K.NODE_STATE_SETS if leave_out is None or Path(f).resolve() != leave_out.resolve()]
    if any(f.resolve() in scoring for f in folders):
        raise SystemExit("NODE_STATE_SETS holds a TRUTH_SETS folder: those score the namer and must stay unseen")
    rows = _labelled(folders)
    crops, states, shots = [], [], []
    for state in K.NODE_STATES:
        mine = [r for r in rows if r[1] == state]
        if not mine:
            continue
        F = np.array([icon_refs.feature(c) for c, _s, _f in mine], np.float32)
        for k in spread(F, K.NODE_STATE_PICTURES):
            crops.append(mine[k][0])
            states.append(state)
            shots.append(mine[k][2])
    if not crops:
        raise SystemExit("no hand-checked map node states in " + ", ".join(str(f) for f in folders))
    node_states.save_state_pictures(to, np.array(crops), states, shots)
    print(f"{len(crops)} pictures ({', '.join(f'{k} {v}' for k, v in Counter(states).items())}) of {len(rows)} -> {to}")
    return 0


def cmd_score(folder: Path, pictures: Path | None) -> int:
    """Name the states at a folder's hand-checked positions and print right / wrong / unsure per state."""
    if pictures is not None:
        K.NODE_STATES_FILE = pictures
    book = node_states.state_pictures()
    if not book["states"]:
        raise SystemExit(f"no pictures in {K.NODE_STATES_FILE}")
    per: dict[str, Counter] = {}
    confusion: Counter = Counter()
    for shot, items in read_states(folder).items():
        img = core.read_screenshot(folder / shot)
        if img is None:
            continue
        for s in items:
            got = node_states.name_state(img, s["x"], s["y"], book)[0]
            c = per.setdefault(s["state"], Counter())
            c["right" if got == s["state"] else "unsure" if got is None else "wrong"] += 1
            if got not in (None, s["state"]):
                confusion[f"{s['state']} called {got}"] += 1
    for state, c in per.items():
        print(f"{state:6s} {c['right']} right, {c['wrong']} wrong, {c['unsure']} unsure")
    for k, v in confusion.most_common(12):
        print(f"   {v} x {k}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheet")
    p.add_argument("folder", type=Path)
    p.add_argument("--shots", nargs="*", default=[], help="only these screenshots (file names or stems)")
    p.add_argument("--every", type=int, default=1, help="every Nth screenshot")
    p.add_argument("--out", type=Path)
    p = sub.add_parser("save")
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path)
    p = sub.add_parser("freeze")
    p.add_argument("--leave-out", type=Path)
    p.add_argument("--to", type=Path)
    p = sub.add_parser("score")
    p.add_argument("folder", type=Path)
    p.add_argument("--pictures", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "freeze":
        return cmd_freeze(a.leave_out, a.to or Path(K.NODE_STATES_FILE))
    if a.cmd == "score":
        return cmd_score(a.folder, a.pictures)
    out = a.out or DEFAULT_OUT / a.folder.name
    return cmd_sheet(a.folder, out, a.shots, a.every) if a.cmd == "sheet" else cmd_save(a.folder, out)


if __name__ == "__main__":
    raise SystemExit(main())
