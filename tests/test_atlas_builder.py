"""Offline checks for the atlas builder core (no screenshots or detector needed).  py test_atlas_builder.py"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program"))
import atlas_builder_core as C
import cv2
import numpy as np

C.HORIZON = None  # synthetic crops of one image: flat, no camera tilt


def make_world(seed=1, w=1500, h=700, n=110):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), (0, 0), 3)
    img = cv2.normalize(img, None, 30, 220, cv2.NORM_MINMAX)
    pts = []
    while len(pts) < n:
        p = rng.uniform([60, 130], [w - 60, h - 130])
        if all(np.hypot(*(p - q)) > 48 for q in pts):
            pts.append(p)
    return img, np.array(pts)


def frame_from(world, pts, x0, x1, name, tmp, jitter=0.6, drop=0.08, ghosts=3, seed=0):
    rng = np.random.default_rng(seed)
    crop = world[:, x0:x1]
    path = str(Path(tmp) / f"{name}.png")
    cv2.imencode(".png", crop)[1].tofile(path)
    inside = [p for p in pts if x0 + 25 < p[0] < x1 - 25]
    keep = [p - [x0, 0] + rng.normal(0, jitter, 2) for p in inside if rng.random() > drop]
    keep += [rng.uniform([40, 130], [x1 - x0 - 40, 570]) for _ in range(ghosts)]
    nodes = [
        {
            "x": int(p[0]),
            "y": int(p[1]),
            "score": 0.9,
            "state": "review",
            "source": "t",
            "hidden": False,
            "unverified": False,
            "tower": False,
            "icon": "",
        }
        for p in keep
    ]
    return C.Frame.from_json(
        {
            "name": name,
            "path": path,
            "sha256": name,
            "width": x1 - x0,
            "height": 700,
            "nodes": nodes,
            "edges": [{"a": 0, "b": 1, "conf": 1.0, "status": "detected"}],
            "landmarks": [{"kind": "Tower", "x": 300, "y": 300, "conf": 0.9, "source": "t"}],
        }
    )


def test_translation_recovered_and_nodes_merged():
    with tempfile.TemporaryDirectory() as tmp:
        world, pts = make_world()
        a = frame_from(world, pts, 0, 900, "a", tmp, seed=1)
        b = frame_from(world, pts, 500, 1500, "b", tmp, seed=2)
        at = C.Atlas()
        at.add_frame(a)
        r = at.add_frame(b)
        assert r.ok, r.reason
        assert np.allclose(r.M[:, 2], [500, 0], atol=2) and np.allclose(r.M[:, :2], np.eye(2), atol=0.01)
        both = [n for n in at.nodes if len(set(n["frames"])) == 2]
        assert len(both) >= 20, len(both)  # nodes in the overlap were merged, not duplicated
        assert len(at.landmarks) == 2  # the two towers are 500px apart in atlas space


def test_unrelated_screenshot_is_rejected_and_atlas_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        w1, p1 = make_world(1)
        w2, p2 = make_world(2)
        at = C.Atlas()
        at.add_frame(frame_from(w1, p1, 0, 900, "a", tmp))
        before = json.dumps(at.to_json(), sort_keys=True)
        r = at.add_frame(frame_from(w2, p2, 0, 900, "z", tmp, seed=5))
        assert not r.ok
        assert json.dumps(at.to_json(), sort_keys=True) == before


def test_graph_match_with_wrong_terrain_is_rejected():
    """Same node layout but different ground: the pixel check must veto it."""
    with tempfile.TemporaryDirectory() as tmp:
        w1, p1 = make_world(1)
        w2, _ = make_world(7)
        at = C.Atlas()
        at.add_frame(frame_from(w1, p1, 0, 900, "a", tmp))
        r = at.add_frame(frame_from(w2, p1, 500, 1500, "b", tmp, seed=3))
        assert not r.ok and "terrain" in r.reason, r.reason


def test_save_load_roundtrip_and_support_counts():
    with tempfile.TemporaryDirectory() as tmp:
        world, pts = make_world()
        at = C.Atlas()
        at.add_frame(frame_from(world, pts, 0, 900, "a", tmp, seed=1))
        at.add_frame(frame_from(world, pts, 500, 1500, "b", tmp, seed=2))
        path = Path(tmp) / "atlas.json"
        at.save(path)
        again = C.Atlas.load(path)
        assert json.dumps(again.to_json(), sort_keys=True) == json.dumps(at.to_json(), sort_keys=True)
        r = again.add_frame(frame_from(world, pts, 250, 1150, "c", tmp, seed=4))  # merge after reload
        assert r.ok, r.reason
        assert max(len(set(n["frames"])) for n in again.nodes) == 3


def test_duplicate_screenshot_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        world, pts = make_world()
        f = frame_from(world, pts, 0, 900, "a", tmp)
        at = C.Atlas()
        at.add_frame(f)
        assert not at.add_frame(f).ok and len(at.frames) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("PASS: atlas builder core")
