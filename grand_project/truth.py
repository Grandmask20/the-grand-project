"""Ground truth for the detector, labelled by hand on contact sheets (like the badge sheets).

    py atlas_truth.py sheet --shots DIR --cache DIR --out DIR      make the sheets
    py atlas_truth.py save  --out DIR --labels labels.txt          store your corrections

Three sheets, every tile numbered:
  truth_maps.png       map bases. Green border = the detector says "map", red = a loose candidate
                       it rejected (to catch maps it missed). Label only the WRONG ones: the id
                       flips (A12 -> not a map / a map).
  truth_landmarks.png  Cities, Halls, Towers, strongholds and every Deadly Map Boss badge, with
                       the detector's call. Label wrong ones as  L7 City / L7 Hall / L7 Tower /
                       L7 Stronghold / L7 Locked / L7 Deadly (deadly boss map, no Hall/City) / L7 none
  truth_badges.png     badges grouped by the detector's name. Label wrong ones as  B31 Corruption,
                       B31 none (not a badge), or a whole row  R4 Delirium.
  A landmark the detector missed: name the map tile it stands on,  A12 City  (same kind words).
Unlabelled tiles keep the detector's call.  `save` writes truth.json (per screenshot: maps,
landmarks, badges in screen px), which the detector tests score against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
from grand_project import core as core  # noqa: E402

MAP_CROP, MAP_TILE, MAP_ROW = 56, 64, 20
LM_W, LM_H, LM_ROW = 170, 210, 10
BADGE_CROP, BADGE_TILE, BADGE_ROW = 40, 56, 20
LOOSE_PER_SHOT = 30
LM_KINDS = {
    "city": "City",
    "hall": "Hall",
    "tower": "Tower",
    "stronghold": "Breach stronghold",
    "locked": "Locked stronghold",
    "deadly": "Deadly boss map",
    "none": "",
}


def loose_maps(img: np.ndarray, taken: np.ndarray) -> list[tuple[int, int, float]]:
    """bright small blobs (map-base glow) the detector did not keep: candidates for missed maps"""
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32)
    dog = cv2.GaussianBlur(v, (0, 0), 2) - cv2.GaussianBlur(v, (0, 0), 7)
    mx = cv2.dilate(dog, np.ones((21, 21), np.uint8))
    ok = (dog >= mx) & (dog > 22) & (core._valid_mask(img) > 0)
    ys, xs = np.nonzero(ok)
    out = []
    for x, y in zip(xs, ys, strict=False):
        if len(taken) and np.min(np.hypot(taken[:, 0] - x, taken[:, 1] - y)) < 16:
            continue
        out.append((int(x), int(y), float(dog[y, x])))
    return sorted(out, key=lambda t: -t[2])[:LOOSE_PER_SHOT]


def crop(img, x, y, w, h):
    big = cv2.copyMakeBorder(img, h, h, w, w, cv2.BORDER_CONSTANT)
    return big[int(y) + h - h // 2 : int(y) + h - h // 2 + h, int(x) + w - w // 2 : int(x) + w - w // 2 + w].copy()


def label_tile(t, text, col):
    cv2.rectangle(t, (0, 0), (t.shape[1] - 1, t.shape[0] - 1), col, 2)
    cv2.putText(t, text, (3, 12), 0, 0.38, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(t, text, (3, 12), 0, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    return t


def grid(rows: list[tuple[str, list[np.ndarray]]], per_row: int, tw: int, th: int) -> np.ndarray:
    lines = []
    for title, tiles in rows:
        head = np.full((20, per_row * tw, 3), 30, np.uint8)
        cv2.putText(head, title, (4, 15), 0, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        lines.append(head)
        for k in range(0, len(tiles), per_row):
            part = tiles[k : k + per_row]
            part += [np.zeros((th, tw, 3), np.uint8)] * (per_row - len(part))
            lines.append(np.hstack(part))
    return np.vstack(lines) if lines else np.zeros((10, 10, 3), np.uint8)


def cmd_sheet(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = sorted(Path(a.shots).glob("*.png"))
    cache = Path(a.cache)
    key = {"shots": {}, "maps": {}, "landmarks": {}, "badges": {}, "rows": {}}
    map_rows, lm_tiles, by_name = [], [], {}
    letter = 0
    for p in shots:
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        cf = cache / f"{h}.json"
        if not cf.exists():
            continue
        d = json.loads(cf.read_text(encoding="utf-8"))
        img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
        S = chr(ord("A") + letter)
        letter += 1
        key["shots"][S] = {"name": p.name, "path": str(p)}
        # maps
        det = [(n["x"], n["y"]) for n in d["nodes"] if not n.get("hidden")]
        cands = [(x, y, True) for x, y in det]
        cands += [(x, y, False) for x, y, _s in loose_maps(img, np.array(det, float).reshape(-1, 2))]
        tiles = []
        for k, (x, y, yes) in enumerate(cands, 1):
            mid = f"{S}{k}"
            key["maps"][mid] = {"shot": S, "x": round(float(x), 1), "y": round(float(y), 1), "detector": yes}
            t = cv2.resize(crop(img, x, y, MAP_CROP, MAP_CROP), (MAP_TILE, MAP_TILE))
            cv2.circle(t, (MAP_TILE // 2, MAP_TILE // 2), 13, (255, 255, 0), 1, cv2.LINE_AA)
            tiles.append(label_tile(t, mid, (60, 200, 60) if yes else (40, 40, 220)))
        map_rows.append((f"{S}: {p.name}  (green = detector says map, red = rejected candidate)", tiles))
        # landmarks: detector landmarks + every Deadly Map Boss badge not already covered
        lms = [(landmark["x"], landmark["y"], landmark["kind"]) for landmark in d["landmarks"]]
        for ic in d["icons"]:
            if ic["name"] == "MapBossSpecial":
                bx, by = ic["x"], ic["y"] + 24
                if not any(np.hypot(bx - x, by - y) < 70 for x, y, _k in lms):
                    lms.append((bx, by, "Deadly boss map"))
        for x, y, kind in lms:
            lid = f"L{len(key['landmarks']) + 1}"
            key["landmarks"][lid] = {"shot": S, "x": round(float(x), 1), "y": round(float(y), 1), "detector": kind}
            t = crop(img, x, y - 60, LM_W, LM_H)
            cv2.drawMarker(t, (LM_W // 2, LM_H // 2 + 60), (255, 255, 0), cv2.MARKER_CROSS, 12, 1)
            lm_tiles.append(label_tile(t, f"{lid} {S} {kind}", (0, 200, 255)))
        # badges
        for ic in d["icons"]:
            bid = f"B{len(key['badges']) + 1}"
            key["badges"][bid] = {"shot": S, "x": ic["x"], "y": ic["y"], "detector": ic["name"]}
            t = cv2.resize(crop(img, ic["x"], ic["y"], BADGE_CROP, BADGE_CROP), (BADGE_TILE, BADGE_TILE))
            by_name.setdefault(ic["name"], []).append(label_tile(t, bid, (200, 200, 200)))
            key["badges"][bid]["_row"] = ic["name"]
    names = sorted(by_name, key=lambda n: -len(by_name[n]))
    badge_rows = []
    for r, n in enumerate(names, 1):
        key["rows"][f"R{r}"] = n
        badge_rows.append((f"R{r}: detector says {n}  ({len(by_name[n])})", by_name[n]))
    for b in key["badges"].values():
        b.pop("_row", None)
    cv2.imwrite(str(out / "truth_maps.png"), grid(map_rows, MAP_ROW, MAP_TILE, MAP_TILE))
    cv2.imwrite(
        str(out / "truth_landmarks.png"), grid([("landmarks (cross = map base)", lm_tiles)], LM_ROW, LM_W, LM_H)
    )
    cv2.imwrite(str(out / "truth_badges.png"), grid(badge_rows, BADGE_ROW, BADGE_TILE, BADGE_TILE))
    (out / "truth_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(
        f"{len(key['shots'])} screenshots: {len(key['maps'])} map tiles, {len(key['landmarks'])} landmarks, "
        f"{len(key['badges'])} badges in {len(names)} rows -> {out}"
    )
    return 0


def cmd_more(a) -> int:
    """another labelling round: a new detector's maps that are not on the sheets yet (yellow, counted as
    maps unless you name them). --proposals is JSON {screenshot name: [[x, y, score], ...]}."""
    out = Path(a.out)
    key = json.loads((out / "truth_key.json").read_text(encoding="utf-8"))
    props = json.loads(Path(a.proposals).read_text(encoding="utf-8"))
    rnd = 1 + max((m.get("round", 1) for m in key["maps"].values()), default=1)
    rows, added = [], 0
    for S, s in key["shots"].items():
        have = np.array([[m["x"], m["y"]] for m in key["maps"].values() if m["shot"] == S], float).reshape(-1, 2)
        n = max(int(mid[1:]) for mid in key["maps"] if mid[0] == S)
        sp = Path(s["path"])
        img = cv2.imdecode(np.fromfile(str(sp), np.uint8), cv2.IMREAD_COLOR)
        tiles = []
        for x, y, _sc in sorted(props.get(s["name"], []), key=lambda t: -t[2]):
            if len(have) and np.min(np.hypot(have[:, 0] - x, have[:, 1] - y)) < 20:
                continue
            n += 1
            mid = f"{S}{n}"
            key["maps"][mid] = {
                "shot": S,
                "x": round(float(x), 1),
                "y": round(float(y), 1),
                "detector": True,
                "round": rnd,
            }
            have = np.vstack([have, [x, y]])
            t = cv2.resize(crop(img, x, y, MAP_CROP, MAP_CROP), (MAP_TILE, MAP_TILE))
            cv2.circle(t, (MAP_TILE // 2, MAP_TILE // 2), 13, (255, 255, 0), 1, cv2.LINE_AA)
            tiles.append(label_tile(t, mid, (0, 220, 255)))
            added += 1
        if tiles:
            rows.append((f"{S}: {s['name']}  (new finds - counted as maps unless you name them)", tiles))
    cv2.imwrite(str(out / f"truth_maps_round{rnd}.png"), grid(rows, MAP_ROW, MAP_TILE, MAP_TILE))
    (out / "truth_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"round {rnd}: {added} new map tiles -> truth_maps_round{rnd}.png")
    return 0


MAP_ID = re.compile(r"(?<![\w-])([a-j]?)(\d+)(?![\w])", re.I)
RANGE = re.compile(r"([a-j])(\d+)\s*-\s*([a-j])(\d+)", re.I)
BADGE_ID = re.compile(r"(?<![\d])b(\d+)", re.I)
# your words for badges -> badge names (checked in this order)
BADGE_WORDS = [
    ("expedition", "ExpeditionShip"),
    ("ship", "ExpeditionShip"),
    ("powerful map boss", "MapBoss"),
    ("deadly map boss", "MapBossSpecial"),
    ("breach hive", "BreachHive"),
    ("rogue exile", "RogueExile"),
    ("wisdom", "WisdomsTeachings"),
    ("abyssal overrun", "AbyssOverrun"),
    ("same element", "UnnamedR5"),
    ("terrain", "none"),
    ("map node", "none"),
    ("map icon", "none"),
    ("top of", "none"),
    ("ui", "none"),
    ("none", "none"),
]
NOT_WORDS = [
    ("ui", "ui"),
    ("text", "text"),
    ("waypoint", "waypoint"),
    ("player", "player"),
    ("tops of breach", "stronghold_top"),
    ("top", "tower_top"),
    ("beam", "hall_beam"),
    ("structure", "hall_beam"),
    ("icon", "icon"),
    ("path", "path"),
    ("terrain", "terrain"),
    ("glow", "glow"),
]


def _flags(t: str) -> list[str]:
    f = []
    if re.search(r"off ?cent", t):
        f.append("offcenter")
    if "hidden" in t:
        f.append("hidden")
    if re.search(r"(behind|under|blocked by)( the)? (ui|text)", t):
        f.append("ui")
    elif re.search(r"blocked|behind terrain|under terrain|behind something", t):
        f.append("occluded")
    if "completed" in t:
        f.append("completed")
    if "special" in t:
        f.append("special")
    return f


def _city_type(t: str) -> str | None:
    return next((c.title() for c in ("vaal", "faridun", "ezomyte") if c in t), None)


def classify_map(text: str) -> dict:
    """one of your map-tile notes -> {state: map/maybe/not, what, flags, landmark, city_type}"""
    t = text.lower().replace("'", "")
    out = {"state": None, "what": "", "flags": _flags(t), "landmark": "", "city_type": _city_type(t)}
    if "could be a node" in t:
        out["state"] = "maybe"
    elif "tower icon" in t:
        out["state"], out["what"] = "not", "tower_icon"  # badges of a tower sit high above its base
    elif re.search(r"not a node|not nodes|dont think|next to", t):
        out["state"] = "not"
        out["what"] = "near_node" if re.search(r"next to|above|below", t) else "not"
    elif (
        re.search(
            r"is a node|are (all )?nodes|barely a node|there is a node|hidden node|map node|city node|be a node", t
        )
        or "tower" in t
        and "top" not in t
    ):
        out["state"] = "map"
    elif "expedition" in t:
        out["state"], out["what"] = "not", "expedition_badge"  # the white-swirl badge right above an ocean map
    elif re.search(r"\bboat|\bship", t):
        out["state"], out["what"] = "not", "expedition_ship"  # Expedition ship marker (user: boat)
    elif re.search(r"off ?cent", t):
        out["state"] = "map"  # "is offcenter": a map, circle off its centre
    elif re.search(r"^\s*none\b", t):
        out["state"], out["what"] = "not", "not"
    else:
        for w, what in NOT_WORDS:
            if w in t:
                out["state"], out["what"] = "not", what
                break
    if out["state"] == "map":
        t = re.sub(
            r"(behind|under|next to) (a|the) (hall|tower|city)", "", t
        )  # "hidden node behind a hall" is not a Hall
        if "deadly" in t:
            out["landmark"] = "Deadly boss map"
        elif "city" in t:
            out["landmark"] = "City"
        elif "hall" in t:
            out["landmark"] = "Hall"
        elif "tower" in t:
            out["landmark"] = "Tower"
    else:
        out["flags"] = []
    return out


def classify_landmark(text: str, detector: str) -> dict:
    t = text.lower()
    f = _flags(t)
    if "another map" in t:
        f.append("badge_of_other_map")
    if re.search(r"\bnot a\b|^\s*none", t):
        kind = ""
    elif "locked" in t:
        kind = "Locked stronghold"
    elif "city" in t:
        kind = "City"
    elif "deadly" in t:
        kind = "Deadly boss map"
    elif "hall" in t:
        kind = "Hall"
    elif "tower" in t:
        kind = "Tower"
    elif "stronghold" in t:
        kind = "Breach stronghold"
    else:
        kind = detector
    return {"kind": kind, "city_type": _city_type(t), "flags": f}


def _badge_name(text: str, known: set[str]) -> tuple[str | None, list[str]]:
    t = text.lower()
    flags = ["ui"] if re.search(r"behind( the)? ui", t) else []
    t = re.sub(r"behind( the)? ui", "", t)
    word = re.sub(r"[^a-z]", "", t)
    for name in known:
        if word == name.lower():
            return name, flags
    for w, name in BADGE_WORDS:
        if w in t:
            return name, flags
    return None, flags


def _segments(line: str, rx: re.Pattern, letter_ok: bool) -> list[tuple[str, str]]:
    """ids in a line, each with the note that follows it (ids with no note share the next note);
    'f69-f98' is a range; a bare number after an id keeps that id's letter ('c122 139')"""
    for m in RANGE.finditer(line):
        if m.group(1).lower() == m.group(3).lower():
            ids = " ".join(f"{m.group(1)}{n}" for n in range(int(m.group(2)), int(m.group(4)) + 1))
            line = line.replace(m.group(0), ids)
    ms = list(rx.finditer(line))
    segs, last = [], None
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
        text = line[m.end() : end].strip(" ,:;.\t")
        if letter_ok:
            L = (m.group(1) or last or "").upper()
            if not L:
                continue
            last, sid = L, f"{L}{int(m.group(2))}"
        else:
            sid = f"B{int(m.group(1))}"
        segs.append([sid, text])
    nxt = ""
    for sg in reversed(segs):
        if sg[1]:
            nxt = sg[1]
        else:
            sg[1] = nxt
    return [(a, b) for a, b in segs]


def parse_notes(path: Path, key: dict) -> dict:
    """labels.txt (free text or the short syntax) -> per-tile decisions + lines it could not read"""
    known = set(key["rows"].values()) | {w[1] for w in BADGE_WORDS}
    maps, lms, badges, rows, unclear = {}, {}, {}, {}, []
    section = "maps"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        low = line.lower()
        if not line:
            continue
        head = low.rstrip(": ")
        if head in ("badges", "landmarks", "maps"):
            section = head
            continue
        if head in ("labels", "icons", "badge", "map icons", "badge sheet"):
            section = "badges"
            continue
        if head in ("map nodes", "nodes", "map", "map sheet"):
            section = "maps"
            continue
        if re.match(r"^r\d+\s*:?$", low):
            section = "badges"
            continue
        m = re.match(r"^r(\d+)\s+([a-z][a-z ]*)$", low)
        if m:  # short syntax: a whole row
            rows["R" + m.group(1)] = _badge_name(m.group(2), known)[0] or m.group(2)
            continue
        m = re.match(r"^l(\d+)\b\s*(.*)$", low)
        if m:
            lid, rest = "L" + m.group(1), m.group(2)
            note = rest.split(":", 1)[1] if ":" in rest else rest
            if lid in key["landmarks"]:
                lms[lid] = classify_landmark(note, key["landmarks"][lid]["detector"])
            else:
                unclear.append(raw)
            continue
        if section == "badges":
            m = re.search(r"the rest of r(\d+)", low)
            if m:
                rows["R" + m.group(1)] = _badge_name(low[m.end() :], known)[0] or "none"
                continue
            segs = _segments(line, BADGE_ID, False)
            if not segs:
                unclear.append(raw)
            for bid, txt in segs:
                name, fl = _badge_name(txt, known)
                if name is None or bid not in key["badges"]:
                    unclear.append(raw)
                    continue
                badges[bid] = (name, fl)
            continue
        segs = _segments(line, MAP_ID, True)
        if not segs:
            unclear.append(raw)
        for mid, txt in segs:
            if mid not in key["maps"]:
                unclear.append(raw)
                continue
            if not txt:  # short syntax: bare id = flip
                det = key["maps"][mid]["detector"]
                maps[mid] = {
                    "state": "not" if det else "map",
                    "what": "",
                    "flags": [],
                    "landmark": "",
                    "city_type": None,
                }
                continue
            if txt.split()[0].lower() in LM_KINDS and txt.split()[0].lower() != "none":  # short syntax: A12 City
                txt = f"is a node, {txt}"
            c = classify_map(txt)
            if c["state"] is None:
                unclear.append(raw)
                continue
            maps[mid] = c
    return {"maps": maps, "landmarks": lms, "badges": badges, "rows": rows, "unclear": unclear}


def cmd_save(a) -> int:
    out = Path(a.out)
    key = json.loads((out / "truth_key.json").read_text(encoding="utf-8"))
    n = parse_notes(Path(a.labels), key)
    truth = {
        S: {"name": s["name"], "maps": [], "maybe": [], "not_maps": [], "landmarks": [], "badges": []}
        for S, s in key["shots"].items()
    }
    flips = 0
    for mid, m in key["maps"].items():
        c = n["maps"].get(mid)
        T = truth[m["shot"]]
        was = "map" if m["detector"] else "not"
        state = c["state"] if c else was
        flips += state not in (was, "maybe")
        if state == "map":
            T["maps"].append({"id": mid, "x": m["x"], "y": m["y"], "flags": c["flags"] if c else []})
        elif state == "maybe":
            T["maybe"].append({"id": mid, "x": m["x"], "y": m["y"]})
        elif c:  # labelled non-maps: negatives for training
            T["not_maps"].append({"id": mid, "x": m["x"], "y": m["y"], "what": c["what"]})
    for lid, lm in key["landmarks"].items():
        c = n["landmarks"].get(lid, {"kind": lm["detector"], "city_type": None, "flags": []})
        if c["kind"]:
            truth[lm["shot"]]["landmarks"].append(
                {
                    "id": lid,
                    "kind": c["kind"],
                    "x": lm["x"],
                    "y": lm["y"],
                    "city_type": c["city_type"],
                    "flags": c["flags"],
                }
            )
    added = 0
    for mid, c in n["maps"].items():  # landmarks named on map tiles
        if c["state"] != "map" or not c["landmark"]:
            continue
        m = key["maps"][mid]
        L = truth[m["shot"]]["landmarks"]
        if any(
            landmark["kind"] == c["landmark"] and np.hypot(landmark["x"] - m["x"], landmark["y"] - m["y"]) < 90
            for landmark in L
        ):
            continue
        L.append(
            {
                "id": mid,
                "kind": c["landmark"],
                "x": m["x"],
                "y": m["y"],
                "city_type": c["city_type"],
                "flags": c["flags"] + ["from_map_tile"],
            }
        )
        added += 1
    for mid, c in n["maps"].items():  # Expedition ship markers named on map tiles
        if c["state"] == "not" and c["what"] in ("expedition_ship", "expedition_badge"):
            nm = "ExpeditionShip" if c["what"] == "expedition_ship" else "Expedition"
            m = key["maps"][mid]
            B = truth[m["shot"]]["badges"]
            if not any(np.hypot(b["x"] - m["x"], b["y"] - m["y"]) < 30 for b in B if b["name"] == nm):
                B.append({"id": mid, "name": nm, "x": m["x"], "y": m["y"], "flags": ["from_map_tile"]})
    row_of = {nm: r for r, nm in key["rows"].items()}
    for bid, b in key["badges"].items():
        name, fl = n["badges"].get(bid, (n["rows"].get(row_of[b["detector"]], b["detector"]), []))
        if name.lower() != "none":
            truth[b["shot"]]["badges"].append({"id": bid, "name": name, "x": b["x"], "y": b["y"], "flags": fl})
    res = {v.pop("name"): v for v in truth.values()}
    (out / "truth.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    tot = lambda k: sum(len(v[k]) for v in res.values())  # noqa: E731
    print(
        f"truth.json: {tot('maps')} maps ({flips} changed from the detector), {tot('maybe')} maybe, "
        f"{tot('not_maps')} labelled non-maps, {tot('landmarks')} landmarks ({len(n['landmarks'])} corrected, "
        f"{added} added from map notes), {tot('badges')} badges ({len(n['badges'])} single + "
        f"{len(n['rows'])} whole-row corrections)"
    )
    for u in dict.fromkeys(n["unclear"]):
        print("  could not read:", u)
    return 0


MAP_R, MAP_R_OFF, LM_R, BADGE_R = 20, 45, 90, 14


def _match(pred: list, truth: list, radius) -> tuple[list, list, list]:
    """greedy nearest pairs; radius may be a function of the truth item. -> (pairs, unmatched pred, unmatched truth)"""
    cand = []
    for i, p in enumerate(pred):
        for j, t in enumerate(truth):
            d = float(np.hypot(p["x"] - t["x"], p["y"] - t["y"]))
            if d <= (radius(t) if callable(radius) else radius):
                cand.append((d, i, j))
    used_p, used_t, pairs = set(), set(), []
    for _d, i, j in sorted(cand):
        if i not in used_p and j not in used_t:
            used_p.add(i)
            used_t.add(j)
            pairs.append((i, j))
    return pairs, [i for i in range(len(pred)) if i not in used_p], [j for j in range(len(truth)) if j not in used_t]


def score(truth: dict, outputs: dict) -> dict:
    """compare detector outputs {shot name: {nodes, landmarks, icons}} with truth.json.
    Maps hidden behind the HUD and 'maybe' spots never count against the detector; misses are split
    into plainly visible ones and hidden/occluded ones."""
    s = {
        "maps": {"tp": 0, "fp": 0, "miss_visible": 0, "miss_hidden": 0, "fp_what": {}},
        "landmarks": {},
        "badges": {"right": 0, "wrong": 0, "extra": 0, "missed": 0, "confusion": {}},
    }
    for name, T in truth.items():
        out = outputs.get(name)
        if out is None:
            continue
        pred = [n for n in out["nodes"] if not n.get("hidden")]
        tm = T["maps"]
        pairs, fp, fn = _match(pred, tm, lambda t: MAP_R_OFF if "offcenter" in t["flags"] else MAP_R)
        s["maps"]["tp"] += sum(1 for _i, j in pairs if "ui" not in tm[j]["flags"])
        soft = [t for t in tm if "ui" in t["flags"]] + T["maybe"]
        negs = T["not_maps"]
        for i in fp:
            p = pred[i]
            if any(np.hypot(p["x"] - t["x"], p["y"] - t["y"]) <= MAP_R_OFF for t in soft):
                continue
            s["maps"]["fp"] += 1
            near = min(negs, key=lambda t: np.hypot(p["x"] - t["x"], p["y"] - t["y"]), default=None)
            what = near["what"] if near and np.hypot(p["x"] - near["x"], p["y"] - near["y"]) <= MAP_R else "other"
            s["maps"]["fp_what"][what] = s["maps"]["fp_what"].get(what, 0) + 1
        for j in fn:
            f = tm[j]["flags"]
            if "ui" in f:
                continue
            s["maps"]["miss_hidden" if {"hidden", "occluded"} & set(f) else "miss_visible"] += 1
        # landmarks, per kind
        tl, pl = T["landmarks"], out["landmarks"]
        for kind in {landmark["kind"] for landmark in tl} | {landmark["kind"] for landmark in pl}:
            k = s["landmarks"].setdefault(kind, {"tp": 0, "fp": 0, "fn": 0})
            a = [landmark for landmark in pl if landmark["kind"] == kind]
            b = [landmark for landmark in tl if landmark["kind"] == kind]
            pairs, fp, fn = _match(a, b, LM_R)
            k["tp"] += len(pairs)
            k["fp"] += len(fp)
            k["fn"] += len(fn)
        # badges
        tb, pb = T["badges"], out["icons"]
        pairs, fp, fn = _match(pb, tb, BADGE_R)
        B = s["badges"]
        for i, j in pairs:
            ok = pb[i]["name"] == tb[j]["name"]
            B["right" if ok else "wrong"] += 1
            if not ok:
                key = f"{tb[j]['name']} called {pb[i]['name']}"
                B["confusion"][key] = B["confusion"].get(key, 0) + 1
        B["extra"] += len(fp)
        B["missed"] += len(fn)
    m = s["maps"]
    m["precision"] = round(m["tp"] / max(1, m["tp"] + m["fp"]), 3)
    m["recall_visible"] = round(m["tp"] / max(1, m["tp"] + m["miss_visible"]), 3)
    return s


def print_score(s: dict) -> None:
    m = s["maps"]
    print(
        f"maps: {m['tp']} right, {m['fp']} wrong, {m['miss_visible']} visible missed, "
        f"{m['miss_hidden']} hidden/blocked "
        f"missed  (precision {m['precision']:.0%}, recall of visible {m['recall_visible']:.0%})"
    )
    print("   wrong maps were:", ", ".join(f"{k} {v}" for k, v in sorted(m["fp_what"].items(), key=lambda kv: -kv[1])))
    print("landmarks:")
    for kind, k in sorted(s["landmarks"].items()):
        print(f"   {kind:20s} {k['tp']} right, {k['fp']} wrong, {k['fn']} missed")
    B = s["badges"]
    print(f"badges: {B['right']} right, {B['wrong']} wrong name, {B['extra']} not a badge, {B['missed']} missed")
    for k, v in sorted(B["confusion"].items(), key=lambda kv: -kv[1])[:12]:
        print(f"   {v} x {k}")


def cmd_score(a) -> int:
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
    outputs = {}
    for p in Path(a.shots).glob("*.png"):
        if p.name in truth:
            cf = Path(a.cache) / f"{hashlib.sha256(p.read_bytes()).hexdigest()[:16]}.json"
            if cf.exists():
                outputs[p.name] = json.loads(cf.read_text(encoding="utf-8"))
    print(f"{len(outputs)} of {len(truth)} screenshots have detector output")
    print_score(score(truth, outputs))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--shots", required=True)
    s.add_argument("--cache", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_sheet)
    v = sub.add_parser("save")
    v.add_argument("--out", required=True)
    v.add_argument("--labels", required=True)
    v.set_defaults(func=cmd_save)
    r = sub.add_parser("more")
    r.add_argument("--out", required=True)
    r.add_argument("--proposals", required=True)
    r.set_defaults(func=cmd_more)
    c = sub.add_parser("score")
    c.add_argument("--truth", required=True)
    c.add_argument("--shots", required=True)
    c.add_argument("--cache", required=True)
    c.set_defaults(func=cmd_score)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
