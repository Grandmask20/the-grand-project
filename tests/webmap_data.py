"""Hand-made atlases and a vector tile reader, shared by the app and web map tests (no screenshots needed)."""

import math
from pathlib import Path

import cv2
import numpy as np

from grand_project import core

IMG_W, IMG_H = 1500, 900  # the test map image (atlas units = px: origin (0, 0), scale 1)


# ------------------------------------------------------------------ a minimal MVT reader (from the spec)
def _varint(b: bytes, i: int):
    n = shift = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return n, i


def _fields(b: bytes):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(b, i)
        elif wire == 1:
            v, i = b[i : i + 8], i + 8
        elif wire == 2:
            n, i = _varint(b, i)
            v, i = b[i : i + n], i + n
        elif wire == 5:
            v, i = b[i : i + 4], i + 4
        else:
            raise AssertionError(f"wire type {wire}")
        yield field, v


def _packed(b: bytes):
    out, i = [], 0
    while i < len(b):
        v, i = _varint(b, i)
        out.append(v)
    return out


def read_tile(data: bytes) -> dict:
    """Decode a vector tile: {layer name: [(type, [(cmd, x, y)], props, id)]}."""
    import struct

    zz = lambda n: (n >> 1) ^ -(n & 1)  # noqa: E731
    out = {}
    for f, layer in _fields(data):
        assert f == 3
        name, feats, keys, values, version, extent = None, [], [], [], None, None
        for lf, v in _fields(layer):
            if lf == 1:
                name = v.decode()
            elif lf == 2:
                feats.append(v)
            elif lf == 3:
                keys.append(v.decode())
            elif lf == 4:
                (vf, vv), *_ = list(_fields(v))
                values.append(
                    {1: lambda x: x.decode(), 3: lambda x: struct.unpack("<d", x)[0], 5: int, 6: zz, 7: bool}[vf](vv)
                )
            elif lf == 5:
                extent = v
            elif lf == 15:
                version = v
        assert version == 2 and extent == 4096
        rows = []
        for ft in feats:
            fid, tags, gtype, geom = None, [], None, []
            for ff, v in _fields(ft):
                if ff == 1:
                    fid = v
                elif ff == 2:
                    tags = _packed(v)
                elif ff == 3:
                    gtype = v
                elif ff == 4:
                    geom = _packed(v)
            pts, i, x, y = [], 0, 0, 0
            while i < len(geom):
                cmd, cnt = geom[i] & 7, geom[i] >> 3
                i += 1
                if cmd == 7:  # ClosePath: no parameters
                    pts.append((7, x, y))
                    continue
                for _ in range(cnt):
                    x, y = x + zz(geom[i]), y + zz(geom[i + 1])
                    i += 2
                    pts.append((cmd, x, y))
            props = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags), 2)}
            rows.append((gtype, pts, props, fid))
        out[name] = rows
    return out


# ------------------------------------------------------------------ a hand-made atlas
def make_atlas(folder: Path) -> tuple[Path, list[tuple[float, float]], np.ndarray]:
    rng = np.random.default_rng(3)
    pts = [(120 + 250 * (i % 5) + rng.uniform(-40, 40), 120 + 220 * (i // 5) + rng.uniform(-40, 40)) for i in range(15)]
    icons = [[] for _ in pts]
    for i, names in {0: ["Breach"], 2: ["Ritual"], 4: ["MapBoss"], 6: ["Breach", "Delirium"], 10: ["Abyss"]}.items():
        icons[i] = names
    nodes = [
        {"id": i, "x": x, "y": y, "status": "confirmed", "seen": 2, "could": 2, "frames": [0], "tower": i == 7,
         "origin": "detected", "icons": icons[i], "abyss": "", "why": ""}
        for i, (x, y) in enumerate(pts)
    ]  # fmt: skip
    nodes.append({**nodes[0], "id": 15, "x": 30.0, "y": 30.0, "status": "removed", "icons": [], "why": "ghost"})
    paths = [
        {"a": i, "b": i + 1, "kind": "trace", "frames": 2, "seen_in": 2, "both_ends": True, "abyss": False}
        for i in range(15)
        if i % 5 < 4
    ]
    a, b = pts[2], pts[7]
    paths.append({"a": 2, "b": 7, "kind": "trace", "frames": 1, "seen_in": 1, "abyss": True,
                  "line": [list(a), [a[0] + 90, (a[1] + b[1]) / 2], list(b)]})  # fmt: skip
    paths.append({"a": 0, "b": 15, "kind": "trace", "frames": 1, "seen_in": 1, "abyss": False})  # to the removed one
    at = core.Atlas()
    at.frames = [{"name": "a", "path": str(folder / "a.png"), "w": 1920, "h": 1080, "M": [[1, 0, 0], [0, 1, 0]],
                  "stats": {}}]  # fmt: skip
    at.final = {
        "nodes": nodes,
        "paths": paths,
        "landmarks": [{"kind": "Vaal city", "x": pts[4][0], "y": pts[4][1] - 50, "status": "kept"}],
        "icons": [],
        "stats": {},
    }
    at.bookmarks = [{"name": "farm <here>", "group": "g", "note": "", "x": pts[6][0], "y": pts[6][1]}]
    path = folder / "atlas.json"
    at.save(path)
    img = cv2.GaussianBlur(rng.integers(0, 255, (IMG_H, IMG_W, 3)).astype(np.uint8), (0, 0), 4)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img[:, 1030:] = 0  # unexplored: no tiles there (the image ends at 1500)
    png, npz = core.map_image_files(path)
    core.write_png(png, img, "map image")
    np.savez_compressed(
        npz, key=at.terrain_key(), origin=np.array([0.0, 0.0, 1.0]), weight=np.ones(img.shape[:2], np.float16)
    )
    return path, pts, img


def web_px(lng: float, lat: float, world: int) -> tuple[float, float]:
    """Longitude / latitude -> world px (the inverse of Grid.lnglat)."""
    wx = (lng + 180.0) / 360.0 * world
    wy = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * world
    return wx, wy


def biome_atlas(folder: Path):
    """A 10 x 8 grid of maps with two cities (one typed by hand), two strongholds (one locked by a hand icon), a
    hand-drawn biome, influence icons and icon records; with a cached map image."""
    nodes, paths = [], []
    for r in range(8):
        for c in range(10):
            nodes.append({"id": len(nodes), "x": c * 220.0, "y": r * 200.0, "status": "confirmed", "seen": 2,
                          "could": 2, "frames": [0], "tower": False, "origin": "detected", "icons": [], "abyss": "",
                          "why": ""})  # fmt: skip
            i = len(nodes) - 1
            if c:
                paths.append({"a": i - 1, "b": i, "frames": 2, "seen_in": 2, "abyss": False})
            if r:
                paths.append({"a": i - 10, "b": i, "frames": 2, "seen_in": 2, "abyss": False})
    for i, names in {22: ["MapBossSpecial"], 67: ["MapBossSpecial"], 3: ["ForestInfluence"], 4: ["ForestInfluence"],
                     70: ["DesertInfluence"], 50: ["Breach", "Ritual"]}.items():  # fmt: skip
        nodes[i]["icons"] = names
    icons = [
        {"name": n, "x": nd["x"] + 36 * k, "y": nd["y"] - 30, "bx": nd["x"], "by": nd["y"], "n": 2, "could": 2}
        for nd in nodes
        for k, n in enumerate(nd["icons"])
    ]
    kept = {"status": "kept", "n": 2, "could": 2, "conf": 1.0, "source": "detector"}
    at = core.Atlas()
    at.final = {"nodes": nodes, "paths": paths, "icons": icons, "stats": {}, "landmarks": [
        {"kind": "City", "x": 480.0, "y": 360.0, **kept}, {"kind": "City", "x": 1580.0, "y": 1160.0, **kept},
        {"kind": "Breach stronghold", "x": 1100.0, "y": 800.0, **kept},
        {"kind": "Breach stronghold", "x": 220.0, "y": 1300.0, **kept}]}  # fmt: skip
    at.locks = [{"x": 230.0, "y": 1290.0, "n": 2}]
    at.city_types = [{"x": 480.0, "y": 360.0, "type": "Vaal"}]
    at.biome_edits = [{"biome": "Faridun city", "maps": [[0.0, 0.0], [220.0, 0.0]]}]
    at.frames = [{"name": "a", "path": str(folder / "a.png"), "w": 1920, "h": 1080, "M": [[1, 0, -300], [0, 1, -300]],
                  "stats": {}}]  # fmt: skip
    path = folder / "atlas.json"
    at.save(path)
    img = np.full((2000, 2600, 3), 90, np.uint8)
    img[:, 2450:] = 0  # unexplored strip
    png, npz = core.map_image_files(path)
    core.write_png(png, img, "map image")
    np.savez_compressed(
        npz, key=at.terrain_key(), origin=np.array([-300.0, -300.0, 1.0]), weight=np.ones(img.shape[:2], np.float16)
    )
    return path, at
